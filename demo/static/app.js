/* PCB inspection live-show engine.
 *
 * Endless loop, one board per cycle:
 *   reset panels -> Step 1 load -> Step 2 detect (red, blink 3x)
 *   -> Step 3 mask (black, blink 3x) -> Step 4 defects (yellow, blink 3x)
 *   -> advance the top queue leftwards -> next board.
 */

"use strict";

const BLINK_COUNT = 3;      // frame + overlay blinks per step
const BLINK_ON_MS = 300;
const BLINK_OFF_MS = 220;
const STEP_DWELL_MS = 2000; // pause after each step so viewers can follow
const PROCESS_MS = 1400;    // simulated processing time inside steps 2-4

const CHIP_W = 128 + 10;    // chip width + flex gap, keep in sync with CSS

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const $ = (id) => document.getElementById(id);

const panels = [1, 2, 3, 4].map((n) => ({
  el: $("panel" + n),
  cv: $("cv" + n),
  ctx: $("cv" + n).getContext("2d"),
  sn: $("sn" + n),
  info: $("info" + n),
}));

let boards = [];
let cycle = 0;

/* ---------------- settings / dark mode ---------------- */

(function initSettings() {
  const btn = $("settingsBtn");
  const menu = $("settingsMenu");
  const toggle = $("darkToggle");
  const root = document.getElementById("app") || document.body;
  let dark = false;
  try { dark = localStorage.getItem("pcbdemo-dark") === "1"; } catch (e) {}
  root.classList.toggle("dark", dark);
  toggle.checked = dark;
  btn.addEventListener("click", () => {
    menu.hidden = !menu.hidden;
  });
  toggle.addEventListener("change", () => {
    root.classList.toggle("dark", toggle.checked);
    try {
      localStorage.setItem("pcbdemo-dark", toggle.checked ? "1" : "0");
    } catch (e) {}
  });
  document.addEventListener("click", (ev) => {
    if (!menu.hidden && !ev.target.closest(".settings")) menu.hidden = true;
  });
})();

/* ---------------- clock ---------------- */

function tickClock() {
  $("clock").textContent = new Date().toLocaleString(undefined, {
    hour12: false,
  });
}
setInterval(tickClock, 1000);
tickClock();

/* ---------------- action-history overlay ---------------- */

const MAX_ACTIONS = 22;

/* Insert a timestamped entry at the top of the action bar; entries flow
 * downward (newest first), all in solid color, oldest dropped off the
 * bottom past MAX_ACTIONS. Format: time [SN] message. Kinds: "begin"
 * (gold edge) marks a task starting, "alert" (red edge) a blink warning,
 * default (navy edge) a completed action. */
function logAction(sn, msg, kind = "") {
  const list = $("actionList");
  const e = document.createElement("div");
  e.className = "ah-entry" + (kind ? " ah-" + kind : "");
  e.innerHTML =
    `<span class="ah-time">${fmtTime(new Date())}</span>` +
    `<span class="ah-sn">[${sn}]</span> ${msg}`;
  list.insertBefore(e, list.firstChild);
  while (list.children.length > MAX_ACTIONS) list.removeChild(list.lastChild);
}

const MAX_REPORTS = 12;

/* Append one per-board summary card to the REPORT area (newest on top):
 * counts, masked share, defect codes, and a big green PASS / red FAIL. */
function addReport(ann, pct) {
  const list = $("reportList");
  const e = document.createElement("div");
  e.className = "rp-entry";
  const fail = ann.defects.length > 0;
  const detail =
    `${ann.labels.length} sensitive object(s) masked (${pct.toFixed(1)} %)` +
    (fail ? ` · defects: ${ann.defects.map((d) => d.code).join(", ")}`
          : ` · no defect`) +
    ` · ${fmtTime(new Date())}`;
  e.innerHTML =
    `<div class="rp-head"><span class="rp-sn">${ann.sn}</span>` +
    `<span class="rp-verdict ${fail ? "fail" : "pass"}">` +
    `${fail ? "FAIL" : "PASS"}</span></div>` +
    `<div class="rp-detail">${detail}</div>`;
  list.insertBefore(e, list.firstChild);
  while (list.children.length > MAX_REPORTS) list.removeChild(list.lastChild);
}

/* ---------------- queue bar ---------------- */

function buildQueue() {
  const track = $("queueTrack");
  track.innerHTML = "";
  for (const sn of boards) {
    const chip = document.createElement("div");
    chip.className = "chip";
    chip.id = "chip-" + sn;
    chip.innerHTML =
      `<img src="/dataset/raw/${sn}.png" alt="${sn}" loading="lazy">` +
      `<div class="chip-sn">${sn}</div>`;
    track.appendChild(chip);
  }
}

function updateQueue(idx) {
  boards.forEach((sn, i) => {
    const chip = $("chip-" + sn);
    chip.classList.toggle("current", i === idx);
    chip.classList.toggle("done", i < idx);
  });
  // slide processed chips out to the left; keep the current board first
  $("queueTrack").style.transform = `translateX(${-idx * CHIP_W}px)`;
}

/* ---------------- drawing helpers ---------------- */

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

function drawBase(p, img) {
  p.cv.width = img.naturalWidth;
  p.cv.height = img.naturalHeight;
  p.ctx.drawImage(img, 0, 0);
}

function drawDetectionBoxes(p, img, labels) {
  drawBase(p, img);
  p.ctx.lineWidth = 8;
  p.ctx.strokeStyle = "#d81f26";
  for (const l of labels) {
    const [x1, y1, x2, y2] = l.bbox;
    p.ctx.strokeRect(x1 - 6, y1 - 6, x2 - x1 + 12, y2 - y1 + 12);
  }
}

function drawMasks(p, img, labels) {
  drawBase(p, img);
  for (const l of labels) {
    const [x1, y1, x2, y2] = l.bbox;
    p.ctx.fillStyle = "#000";
    p.ctx.fillRect(x1 - 6, y1 - 6, x2 - x1 + 12, y2 - y1 + 12);
    p.ctx.lineWidth = 8;
    p.ctx.strokeStyle = "#d81f26";
    p.ctx.strokeRect(x1 - 6, y1 - 6, x2 - x1 + 12, y2 - y1 + 12);
  }
}

function drawDefects(p, img, labels, defects) {
  drawMasks(p, img, labels); // defects are checked on the privacy-safe image
  p.ctx.lineWidth = 9;
  p.ctx.strokeStyle = "#f5d000";
  for (const d of defects) {
    const [x1, y1, x2, y2] = d.bbox;
    p.ctx.strokeRect(x1 - 8, y1 - 8, x2 - x1 + 16, y2 - y1 + 16);
  }
}

function clearPanel(p) {
  p.cv.width = 4;
  p.cv.height = 4;
  p.ctx.clearRect(0, 0, 4, 4);
  p.sn.textContent = "—";
  p.info.innerHTML = '<p class="placeholder">Idle</p>';
  p.el.classList.remove("active", "frame-blink");
}

/* ---------------- blink effects ---------------- */

async function blinkFrame(p) {
  for (let i = 0; i < BLINK_COUNT; i++) {
    p.el.classList.add("frame-blink");
    await sleep(BLINK_ON_MS);
    p.el.classList.remove("frame-blink");
    await sleep(BLINK_OFF_MS);
  }
  p.el.classList.add("active");
}

/* Blink an overlay by alternating a plain redraw and the overlay redraw. */
async function blinkOverlay(p, drawPlain, drawOverlay) {
  for (let i = 0; i < BLINK_COUNT; i++) {
    drawOverlay();
    await sleep(BLINK_ON_MS);
    drawPlain();
    await sleep(BLINK_OFF_MS);
  }
  drawOverlay(); // finish with the overlay visible
}

/* ---------------- info renderers ---------------- */

const fmtTime = (d) =>
  d.toLocaleTimeString(undefined, { hour12: false }) +
  "." + String(d.getMilliseconds()).padStart(3, "0");

function setProcessing(p, msg) {
  p.info.innerHTML = `<p class="proc">${msg}</p>`;
}

function labelCounts(labels) {
  const names = {
    barcode: "1-D barcode",
    qrcode: "QR code",
    datamatrix: "DataMatrix",
    text: "Serial / lot text",
    logo: "Company logo",
  };
  const counts = {};
  for (const l of labels) counts[l.type] = (counts[l.type] || 0) + 1;
  return Object.entries(counts)
    .map(([t, n]) => `<tr><td>${names[t] || t}</td><td>${n}</td></tr>`)
    .join("");
}

function step1Info(p, ann, start) {
  p.info.innerHTML =
    `<h4>Board loaded</h4>
     <p><span class="k">Serial:</span> <b>${ann.sn}</b><br>
        <span class="k">Data source:</span> demo dataset<br>
        <span class="k">File:</span> dataset/raw/${ann.sn}.png<br>
        <span class="k">Image size:</span> ${ann.width} × ${ann.height} px<br>
        <span class="k">Inspection start:</span><br><b>${start.toLocaleString(
          undefined, { hour12: false })}</b></p>
     <p class="k">Board image loaded from the demo sample dataset (synthetic
        boards — no line camera attached in demo mode). Forwarding to
        sensitive-object detection…</p>`;
}

function step2Info(p, ann, ms) {
  p.info.innerHTML =
    `<h4>Sensitive objects: ${ann.labels.length}</h4>
     <table><tr><th>Object type</th><th>Qty</th></tr>${labelCounts(
       ann.labels)}</table>
     <p class="k">All customer-identifying items (codes, serials, logos)
        located and boxed in red.</p>
     <p><span class="k">Processing time:</span> ${(ms / 1000).toFixed(2)} s</p>`;
}

function step3Info(p, ann, areaPx, pct, ms) {
  p.info.innerHTML =
    `<h4>Masking applied</h4>
     <p><span class="k">Regions masked:</span> <b>${ann.labels.length}</b><br>
        <span class="k">Masked area:</span> ${areaPx.toLocaleString()} px²
        (${pct.toFixed(2)} % of board)<br>
        <span class="k">Mask style:</span> irreversible black fill</p>
     <p class="k">Image is now privacy-safe for ML training and export.</p>
     <p><span class="k">Processing time:</span> ${(ms / 1000).toFixed(2)} s</p>`;
}

function step4Info(p, ann, ms) {
  const rows = ann.defects
    .map((d) => {
      const [x1, y1] = d.bbox;
      return `<tr><td>${d.code}</td><td>${d.desc}</td><td>(${x1}, ${y1})</td></tr>`;
    })
    .join("");
  const verdict = ann.defects.length
    ? `<span class="badge-fail">FAIL — ${ann.defects.length} defect(s), route to rework</span>`
    : `<span class="badge-pass">PASS — no defect found</span>`;
  p.info.innerHTML =
    `<h4>Defect result: ${verdict}</h4>` +
    (ann.defects.length
      ? `<table><tr><th>Code</th><th>Description</th><th>Location</th></tr>${rows}</table>`
      : `<p class="k">Board surface clean — released to next station.</p>`) +
    `<p><span class="k">Processing time:</span> ${(ms / 1000).toFixed(2)} s</p>`;
}

/* ---------------- the show ---------------- */

function maskedArea(ann) {
  let area = 0;
  for (const l of ann.labels) {
    const [x1, y1, x2, y2] = l.bbox;
    area += (x2 - x1 + 12) * (y2 - y1 + 12);
  }
  return area;
}

async function runBoard(idx) {
  const sn = boards[idx];
  const status = $("statusMsg");
  updateQueue(idx);
  $("counter").textContent =
    `Board ${idx + 1} / ${boards.length} · cycle ${cycle + 1}`;

  // new board: every panel resets to blank first
  logAction(sn, `new inspection cycle — all step panels reset`, "begin");
  panels.forEach(clearPanel);
  $("stamp1").textContent = "";
  panels.forEach((p) => (p.sn.textContent = sn));

  const [ann, img] = await Promise.all([
    fetch(`/api/board/${sn}`).then((r) => r.json()),
    loadImage(`/dataset/raw/${sn}.png`),
  ]);

  /* ---- STEP 1: inspection / load ---- */
  status.textContent = `Step 1 — loading board ${sn}`;
  const start = new Date();
  logAction(sn, `step 1 started — loading dataset/raw/${sn}.png`, "begin");
  await blinkFrame(panels[0]);
  drawBase(panels[0], img);
  $("stamp1").textContent = `${sn} · start ${fmtTime(start)}`;
  step1Info(panels[0], ann, start);
  logAction(sn, `step 1 finished — image loaded, ${ann.width} × ${ann.height} px`);
  await sleep(STEP_DWELL_MS);

  /* ---- STEP 2: sensitive-object detection ---- */
  status.textContent = `Step 2 — detecting sensitive objects on ${sn}`;
  logAction(sn, `step 2 started — scanning for codes, texts, logos`, "begin");
  await blinkFrame(panels[1]);
  drawBase(panels[1], img);
  setProcessing(panels[1], "Scanning for barcodes, QR codes, texts, logos");
  const t2 = performance.now();
  await sleep(PROCESS_MS);
  const ms2 = performance.now() - t2;
  logAction(sn, `detection complete — <b>${ann.labels.length}</b> object(s) in ${(ms2 / 1000).toFixed(2)} s`);
  logAction(sn, `blinking red detection boxes 3×`, "alert");
  await blinkOverlay(
    panels[1],
    () => drawBase(panels[1], img),
    () => drawDetectionBoxes(panels[1], img, ann.labels)
  );
  step2Info(panels[1], ann, ms2);
  logAction(sn, `step 2 finished — results displayed`);
  await sleep(STEP_DWELL_MS);

  /* ---- STEP 3: masking ---- */
  status.textContent = `Step 3 — masking sensitive areas on ${sn}`;
  logAction(sn, `step 3 started — masking ${ann.labels.length} region(s)`, "begin");
  await blinkFrame(panels[2]);
  drawDetectionBoxes(panels[2], img, ann.labels);
  setProcessing(panels[2], "Applying irreversible black fill");
  const t3 = performance.now();
  await sleep(PROCESS_MS);
  const ms3 = performance.now() - t3;
  logAction(sn, `blinking masked areas 3×`, "alert");
  await blinkOverlay(
    panels[2],
    () => drawDetectionBoxes(panels[2], img, ann.labels),
    () => drawMasks(panels[2], img, ann.labels)
  );
  const area = maskedArea(ann);
  step3Info(panels[2], ann, area, (100 * area) / (ann.width * ann.height), ms3);
  logAction(sn, `step 3 finished — ${((100 * area) / (ann.width * ann.height)).toFixed(1)} % of board masked in ${(ms3 / 1000).toFixed(2)} s`);
  await sleep(STEP_DWELL_MS);

  /* ---- STEP 4: defect detection ---- */
  status.textContent = `Step 4 — defect detection on ${sn}`;
  logAction(sn, `step 4 started — golden-board defect compare`, "begin");
  await blinkFrame(panels[3]);
  drawMasks(panels[3], img, ann.labels);
  setProcessing(panels[3], "Comparing against golden board, locating defects");
  const t4 = performance.now();
  await sleep(PROCESS_MS);
  const ms4 = performance.now() - t4;
  if (ann.defects.length) {
    logAction(sn, `defect scan — <b>${ann.defects.length}</b> defect(s): ` +
              ann.defects.map((d) => d.code).join(", "));
    logAction(sn, `blinking yellow defect marks 3×`, "alert");
  } else {
    logAction(sn, `defect scan — no defect found`);
  }
  await blinkOverlay(
    panels[3],
    () => drawMasks(panels[3], img, ann.labels),
    () => drawDefects(panels[3], img, ann.labels, ann.defects)
  );
  step4Info(panels[3], ann, ms4);
  logAction(sn, `step 4 finished — verdict ` +
            (ann.defects.length ? `<b>FAIL</b>` : `<b>PASS</b>`));
  addReport(ann, (100 * area) / (ann.width * ann.height));
  await sleep(STEP_DWELL_MS);

  status.textContent =
    `Board ${sn} complete — ` +
    (ann.defects.length ? `${ann.defects.length} defect(s) found` : "PASS") +
    ` · advancing queue`;
  logAction(sn, `inspection complete — advancing queue`);
  await sleep(800);
}

async function fetchBoardsWithRetry() {
  // kiosk autostart can open the browser before the server is up — keep trying
  for (;;) {
    try {
      const r = await fetch("/api/boards");
      if (r.ok) {
        const res = await r.json();
        if (res.boards && res.boards.length) return res.boards;
        $("statusMsg").textContent =
          "Dataset is empty — run `python demo/generate_dataset.py`, then reload";
      }
    } catch (err) {
      $("statusMsg").textContent = "Waiting for demo server…";
    }
    await sleep(2000);
  }
}

async function show() {
  boards = await fetchBoardsWithRetry();
  buildQueue();
  $("statusMsg").textContent = `${boards.length} boards queued — starting live inspection`;
  await sleep(1200);
  for (;;) {
    for (let i = 0; i < boards.length; i++) {
      try {
        await runBoard(i);
      } catch (err) {
        console.error("board failed, skipping:", err);
        $("statusMsg").textContent = `Error on ${boards[i]} — skipping`;
        await sleep(1000);
      }
    }
    cycle++;
    updateQueue(0);
    $("queueTrack").style.transition = "none";
    $("queueTrack").style.transform = "translateX(0)";
    void $("queueTrack").offsetWidth; // reflow before re-enabling animation
    $("queueTrack").style.transition = "";
  }
}

show();
