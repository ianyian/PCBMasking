/* PCB privacy-masking upload console.
 *
 * Same operator design as the on-prem demo, but boards come from manual
 * uploads (the + box in the top preview bar) and the detection results are
 * REAL — each board is POSTed to /api/process, which runs the offline
 * ensemble (zxing-cpp, pyzbar, pylibdmtx, OpenCV, EasyOCR, logo templates).
 *
 * Flow per board: Step 1 load -> Step 2 detect (red boxes blink 3x)
 * -> Step 3 mask (black fill blinks 3x) -> Step 4 release verification
 * (header flashes green RELEASED / red QUARANTINED).
 */

"use strict";

const BLINK_COUNT = 3;
const BLINK_ON_MS = 300;
const BLINK_OFF_MS = 220;
const STEP_DWELL_MS = 1600;

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

/* ---------------- settings / dark mode ---------------- */

(function initSettings() {
  const btn = $("settingsBtn");
  const menu = $("settingsMenu");
  const toggle = $("darkToggle");
  const root = document.getElementById("app") || document.body;
  let dark = true; // dark mode is the default
  try {
    const stored = localStorage.getItem("pcbdemo-dark");
    if (stored !== null) dark = stored === "1";
  } catch (e) {}
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

/* ---------------- report / action-log pager ---------------- */

(function initPager() {
  const sw = $("pageSwitch");
  const pages = { report: $("reportList"), log: $("actionList") };
  const tabs = { report: $("tabReport"), log: $("tabLog") };
  let page = "report";
  function apply() {
    for (const k of Object.keys(pages)) {
      pages[k].hidden = k !== page;
      tabs[k].classList.toggle("active", k === page);
    }
  }
  function toggle() {
    page = page === "report" ? "log" : "report";
    apply();
  }
  sw.addEventListener("click", toggle);
  sw.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      toggle();
    }
  });
  apply();
})();

/* ---------------- clock ---------------- */

function tickClock() {
  $("clock").textContent = new Date().toLocaleString("en-US", {
    hour12: true,
  });
}
setInterval(tickClock, 1000);
tickClock();

/* 12-hour time with milliseconds, e.g. "9:49:01.804 AM" */
const fmtTime = (d) =>
  d.toLocaleTimeString("en-US", { hour12: true }).replace(
    /(:\d\d)(\s?[AP]M)/i,
    (m, sec, ap) => `${sec}.${String(d.getMilliseconds()).padStart(3, "0")}${ap}`);

/* ---------------- action log & report ---------------- */

const MAX_ACTIONS = 22;
const MAX_REPORTS = 12;

async function copyText(text, btn) {
  let ok = false;
  try {
    await navigator.clipboard.writeText(text);
    ok = true;
  } catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { ok = document.execCommand("copy"); } catch (e2) {}
    ta.remove();
  }
  btn.textContent = ok ? "✓" : "!";
  setTimeout(() => { btn.textContent = "⧉"; }, 1200);
}

function addCopyButton(entry, text) {
  const btn = document.createElement("button");
  btn.className = "copy-btn";
  btn.title = "Copy this record";
  btn.textContent = "⧉";
  btn.addEventListener("click", () => copyText(text, btn));
  entry.appendChild(btn);
}

/* Neutral navy entries; only the final result entry per board is colored —
 * kind "pass" (green, released) or "fail" (red, quarantined). */
function logAction(sn, msg, kind = "") {
  const list = $("actionList");
  const e = document.createElement("div");
  e.className = "ah-entry" + (kind ? " ah-" + kind : "");
  e.innerHTML =
    `<span class="ah-time">${fmtTime(new Date())}</span>` +
    `<span class="ah-sn">[${sn}]</span> ${msg}`;
  addCopyButton(e, `${fmtTime(new Date())} [${sn}] ` +
                   msg.replace(/<[^>]+>/g, ""));
  list.insertBefore(e, list.firstChild);
  while (list.children.length > MAX_ACTIONS) list.removeChild(list.lastChild);
}

function addReport(sn, released, nRegions, pct) {
  const list = $("reportList");
  const e = document.createElement("div");
  e.className = "rp-entry";
  const detail =
    `${nRegions} region(s) masked (${pct.toFixed(1)} %)` +
    ` · ${fmtTime(new Date())}`;
  e.innerHTML =
    `<div class="rp-head"><span class="rp-sn">${sn}</span>` +
    `<span class="rp-verdict ${released ? "pass" : "fail"}">` +
    `${released ? "RELEASED" : "QUARANTINED"}</span></div>` +
    `<div class="rp-detail">${detail}</div>`;
  addCopyButton(e, `${sn} ${released ? "RELEASED" : "QUARANTINED"} — ${detail}`);
  list.insertBefore(e, list.firstChild);
  while (list.children.length > MAX_REPORTS) list.removeChild(list.lastChild);
}

/* ---------------- last-hour yield & object Pareto chart ---------------- */

const WINDOW_MS = 60 * 60 * 1000;
const OBJ_COLORS = {
  barcode: "#ef6461", qrcode: "#f2a541", datamatrix: "#5b8dd9",
  text: "#00b4a0", logo: "#9b5de5", label: "#c98bdb",
};
const OBJ_SHORT = {
  barcode: "bar", qrcode: "qr", datamatrix: "dmtx",
  text: "text", logo: "logo", label: "label",
};

const history = []; // {t, released, counts:{type:n}} per processed board
let trendChart = null;

function initChart() {
  if (typeof Chart === "undefined") return;
  const AXIS = "#8a97a8";
  trendChart = new Chart($("trendChart"), {
    type: "bar",
    data: {
      labels: [],
      datasets: [
        { label: "objects", data: [], backgroundColor: [], yAxisID: "y" },
        {
          type: "line", label: "cumulative %", data: [], yAxisID: "y1",
          borderColor: "#c0392b", backgroundColor: "#c0392b",
          borderWidth: 2, pointRadius: 3, pointStyle: "rectRot", tension: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: AXIS, font: { size: 8 }, maxRotation: 0 },
        },
        y: {
          beginAtZero: true,
          ticks: { color: AXIS, font: { size: 8 }, precision: 0 },
          grid: { color: "rgba(138, 151, 168, .22)" },
        },
        y1: {
          position: "right", min: 0, max: 100,
          ticks: { color: AXIS, font: { size: 8 },
                   callback: (v) => v + "%" },
          grid: { drawOnChartArea: false },
        },
      },
    },
  });
}

function recordResult(released, regions) {
  const counts = {};
  for (const r of regions) counts[r.label] = (counts[r.label] || 0) + 1;
  history.push({ t: Date.now(), released, counts });
  updateChart();
}

function updateChart() {
  const now = Date.now();
  const start = now - WINDOW_MS;
  while (history.length && history[0].t < start) history.shift();

  const total = history.length;
  const relCnt = history.filter((r) => r.released).length;
  const yv = $("yieldValue");
  const ys = $("yieldSub");
  if (total) {
    const pct = (100 * relCnt) / total;
    yv.textContent = pct.toFixed(1) + " %";
    yv.classList.toggle("pass", pct >= 90);
    yv.classList.toggle("fail", pct < 90);
    ys.textContent = `${relCnt} released / ${total} boards · target > 90 %`;
  } else {
    yv.textContent = "—";
    yv.classList.remove("pass", "fail");
    ys.textContent = "no boards processed in the last hour";
  }

  if (!trendChart) return;
  const counts = {};
  for (const r of history) {
    for (const [k, n] of Object.entries(r.counts)) {
      counts[k] = (counts[k] || 0) + n;
    }
  }
  const order = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
  const totalObj = order.reduce((s, c) => s + counts[c], 0);
  let run = 0;
  const cum = order.map((c) => {
    run += counts[c];
    return Math.round((1000 * run) / totalObj) / 10;
  });
  trendChart.data.labels = order.map((c) => OBJ_SHORT[c] || c);
  trendChart.data.datasets[0].data = order.map((c) => counts[c]);
  trendChart.data.datasets[0].backgroundColor =
    order.map((c) => OBJ_COLORS[c] || "#5b8dd9");
  trendChart.data.datasets[1].data = cum;
  trendChart.update();
}

initChart();
setInterval(updateChart, 60 * 1000);

/* ---------------- upload queue bar ---------------- */

/* queue item: {sn, name, dataUrl, status: pending|current|done, released} */
const queue = [];
let curIdx = -1;
let boardSeq = 0;
let busy = false;

function addChip(item) {
  const track = $("queueTrack");
  const chip = document.createElement("div");
  chip.className = "chip pending";
  chip.id = "chip-" + item.sn;
  chip.innerHTML =
    `<img src="${item.dataUrl}" alt="${item.sn}">` +
    `<div class="chip-sn">${item.sn}</div>`;
  track.appendChild(chip);
}

function updateQueue() {
  queue.forEach((b, i) => {
    const chip = $("chip-" + b.sn);
    if (!chip) return;
    chip.classList.toggle("current", i === curIdx);
    chip.classList.toggle("done", b.status === "done");
    chip.classList.toggle("pending", b.status === "pending");
  });
  centerQueue();
}

function centerQueue() {
  const vp = document.querySelector(".queue-viewport");
  const idx = curIdx >= 0 ? curIdx : queue.length; // rest position: after last
  const offset = vp.clientWidth / 2 - (idx * CHIP_W + (CHIP_W - 10) / 2);
  $("queueTrack").style.transform = `translateX(${offset}px)`;
}

window.addEventListener("resize", centerQueue);

function markChipResult(sn, released) {
  const chip = $("chip-" + sn);
  if (chip) chip.classList.add(released ? "res-pass" : "res-fail");
}

(function initUpload() {
  const box = $("uploadChip");
  const input = $("fileInput");
  box.addEventListener("click", () => input.click());
  box.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      input.click();
    }
  });
  input.addEventListener("change", () => {
    for (const file of input.files) {
      const reader = new FileReader();
      reader.onload = () => {
        boardSeq++;
        const item = {
          sn: "B-" + String(boardSeq).padStart(3, "0"),
          name: file.name,
          dataUrl: reader.result,
          status: "pending",
          released: null,
        };
        queue.push(item);
        addChip(item);
        updateQueue();
        logAction(item.sn, `board queued — ${item.name}`);
        pump();
      };
      reader.readAsDataURL(file);
    }
    input.value = "";
  });
})();

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

function drawDetectionBoxes(p, img, regions) {
  drawBase(p, img);
  p.ctx.lineWidth = Math.max(4, Math.round(img.naturalWidth / 200));
  p.ctx.strokeStyle = "#d81f26";
  for (const r of regions) {
    const [x1, y1, x2, y2] = r.bbox;
    p.ctx.strokeRect(x1 - 6, y1 - 6, x2 - x1 + 12, y2 - y1 + 12);
  }
}

function drawMasks(p, img, regions, pad) {
  drawBase(p, img);
  p.ctx.fillStyle = "#000";
  for (const r of regions) {
    const [x1, y1, x2, y2] = r.bbox;
    p.ctx.fillRect(x1 - pad, y1 - pad, x2 - x1 + 2 * pad, y2 - y1 + 2 * pad);
  }
}

function clearPanel(p) {
  p.cv.width = 4;
  p.cv.height = 4;
  p.ctx.clearRect(0, 0, 4, 4);
  p.sn.textContent = "—";
  p.info.innerHTML = '<p class="placeholder">Idle</p>';
  p.el.classList.remove("active", "frame-blink");
  p.el.querySelector(".panel-head")
      .classList.remove("verdict-pass", "verdict-fail");
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

async function flashVerdict(p, pass) {
  const head = p.el.querySelector(".panel-head");
  const cls = pass ? "verdict-pass" : "verdict-fail";
  for (let i = 0; i < BLINK_COUNT; i++) {
    head.classList.add(cls);
    await sleep(BLINK_ON_MS);
    head.classList.remove(cls);
    await sleep(BLINK_OFF_MS);
  }
  head.classList.add(cls);
}

async function blinkOverlay(p, drawPlain, drawOverlay) {
  for (let i = 0; i < BLINK_COUNT; i++) {
    drawOverlay();
    await sleep(BLINK_ON_MS);
    drawPlain();
    await sleep(BLINK_OFF_MS);
  }
  drawOverlay();
}

/* ---------------- info renderers ---------------- */

function setProcessing(p, msg) {
  p.info.innerHTML = `<p class="proc">${msg}</p>`;
}

const TYPE_NAMES = {
  barcode: "1-D barcode",
  qrcode: "QR code",
  datamatrix: "DataMatrix",
  text: "Printed text",
  logo: "Company logo",
  label: "White label",
};

function typeCounts(regions) {
  const counts = {};
  for (const r of regions) counts[r.label] = (counts[r.label] || 0) + 1;
  return Object.entries(counts)
    .map(([t, n]) => `<tr><td>${TYPE_NAMES[t] || t}</td><td>${n}</td></tr>`)
    .join("");
}

function maskedPct(regions, pad, w, h) {
  let area = 0;
  for (const r of regions) {
    const [x1, y1, x2, y2] = r.bbox;
    area += (x2 - x1 + 2 * pad) * (y2 - y1 + 2 * pad);
  }
  return Math.min(100, (100 * area) / (w * h));
}

/* ---------------- the show ---------------- */

async function runBoard(idx) {
  const board = queue[idx];
  const sn = board.sn;
  const status = $("statusMsg");
  curIdx = idx;
  board.status = "current";
  updateQueue();
  $("counter").textContent =
    `Board ${idx + 1} / ${queue.length} queued`;

  logAction(sn, `new inspection cycle — all step panels reset`);
  panels.forEach(clearPanel);
  $("stamp1").textContent = "";
  panels.forEach((p) => (p.sn.textContent = sn));

  const img = await loadImage(board.dataUrl);

  /* ---- STEP 1: load ---- */
  status.textContent = `Step 1 — loading board ${sn}`;
  const start = new Date();
  logAction(sn, `step 1 started — loading uploaded image ${board.name}`);
  await blinkFrame(panels[0]);
  drawBase(panels[0], img);
  $("stamp1").textContent = `${sn} · start ${fmtTime(start)}`;
  panels[0].info.innerHTML =
    `<h4>Board loaded</h4>
     <p><span class="k">Board ID:</span> <b>${sn}</b><br>
        <span class="k">Data source:</span> operator upload<br>
        <span class="k">File:</span> ${board.name}<br>
        <span class="k">Image size:</span> ${img.naturalWidth} × ${img.naturalHeight} px<br>
        <span class="k">Inspection start:</span><br><b>${start.toLocaleString(
          "en-US", { hour12: true })}</b></p>
     <p class="k">Image uploaded manually by the operator. Forwarding to
        sensitive-object detection…</p>`;
  logAction(sn, `step 1 finished — image loaded, ${img.naturalWidth} × ${img.naturalHeight} px`);
  await sleep(STEP_DWELL_MS);

  /* ---- STEP 2: real detection on the server ---- */
  status.textContent = `Step 2 — detecting sensitive objects on ${sn} (real ensemble, please wait)`;
  logAction(sn, `step 2 started — server ensemble scan (codes, text, logos)`);
  await blinkFrame(panels[1]);
  drawBase(panels[1], img);
  setProcessing(panels[1],
    "Running detector ensemble on server — barcodes, QR, DataMatrix, OCR, logos");

  const blob = await (await fetch(board.dataUrl)).blob();
  const form = new FormData();
  form.append("file", blob, board.name);
  const t2 = performance.now();
  let res;
  try {
    res = await (await fetch("api/process", { method: "POST", body: form })).json();
  } catch (err) {
    logAction(sn, `server error — ${err}`, "fail");
    board.status = "done";
    curIdx = -1;
    updateQueue();
    return;
  }
  if (res.error) {
    logAction(sn, `server rejected image — ${res.error}`, "fail");
    board.status = "done";
    curIdx = -1;
    updateQueue();
    return;
  }
  const ms2 = performance.now() - t2;
  const regions = res.regions;
  const pad = res.pad || 12;

  logAction(sn, `detection complete — <b>${regions.length}</b> region(s) in ${(ms2 / 1000).toFixed(1)} s`);
  logAction(sn, `blinking red detection boxes 3×`);
  await blinkOverlay(
    panels[1],
    () => drawBase(panels[1], img),
    () => drawDetectionBoxes(panels[1], img, regions)
  );
  panels[1].info.innerHTML =
    `<h4>Sensitive regions: ${regions.length}</h4>
     <table><tr><th>Object type</th><th>Qty</th></tr>${typeCounts(regions)}</table>
     <p class="k">Detected by the offline ensemble:
        ${res.detectors.join(", ")}.</p>
     <p><span class="k">Processing time:</span> ${(ms2 / 1000).toFixed(1)} s</p>`;
  logAction(sn, `step 2 finished — results displayed`);
  await sleep(STEP_DWELL_MS);

  /* ---- STEP 3: masking ---- */
  status.textContent = `Step 3 — masking sensitive areas on ${sn}`;
  logAction(sn, `step 3 started — masking ${regions.length} region(s)`);
  await blinkFrame(panels[2]);
  drawDetectionBoxes(panels[2], img, regions);
  setProcessing(panels[2], "Applying irreversible black fill");
  await sleep(600);
  logAction(sn, `blinking masked areas 3×`);
  await blinkOverlay(
    panels[2],
    () => drawDetectionBoxes(panels[2], img, regions),
    () => drawMasks(panels[2], img, regions, pad)
  );
  const pct = maskedPct(regions, pad, img.naturalWidth, img.naturalHeight);
  panels[2].info.innerHTML =
    `<h4>Masking applied</h4>
     <p><span class="k">Regions masked:</span> <b>${regions.length}</b><br>
        <span class="k">Masked share:</span> ${pct.toFixed(1)} % of board<br>
        <span class="k">Mask style:</span> irreversible black fill
        (server: ${(res.mask_ms / 1000).toFixed(2)} s)</p>
     <p class="k">Image is now privacy-safe for ML training and export.</p>`;
  logAction(sn, `step 3 finished — ${pct.toFixed(1)} % of board masked`);
  await sleep(STEP_DWELL_MS);

  /* ---- STEP 4: release verification (fail-closed re-scan) ---- */
  status.textContent = `Step 4 — release verification on ${sn}`;
  logAction(sn, `step 4 started — fail-closed re-scan of the masked image`);
  await blinkFrame(panels[3]);
  drawMasks(panels[3], img, regions, pad);
  setProcessing(panels[3], "Re-scanning masked image for surviving codes / text");
  await sleep(800);
  const released = res.verified;
  panels[3].info.innerHTML =
    `<h4>Verification: ${released
        ? '<span class="badge-pass">RELEASED</span>'
        : '<span class="badge-fail">QUARANTINED</span>'}</h4>
     <p class="k">${released
        ? "The masked image was re-scanned by the decoder + OCR ensemble; " +
          "nothing sensitive is still detectable. Safe to export."
        : "Sensitive content is still detectable after masking. The image " +
          "is quarantined — do not export."}</p>
     <p><span class="k">Verification time:</span>
        ${(res.verify_ms / 1000).toFixed(1)} s</p>
     <p class="k">Defect detection (AI model) is not enabled in this
        deployment yet.</p>`;
  logAction(sn, `flashing step-4 header ` +
            (released ? `green (RELEASED)` : `red (QUARANTINED)`) + ` 3×`);
  await flashVerdict(panels[3], released);
  logAction(sn, `inspection complete — ` +
            (released ? `<b>RELEASED</b>` : `<b>QUARANTINED</b>`),
            released ? "pass" : "fail");
  addReport(sn, released, regions.length, pct);
  markChipResult(sn, released);
  recordResult(released, regions);
  await sleep(STEP_DWELL_MS);

  board.status = "done";
  board.released = released;
  status.textContent =
    `Board ${sn} complete — ${released ? "RELEASED" : "QUARANTINED"}` +
    (queue.some((b) => b.status === "pending")
      ? " · next board starting" : " · waiting for uploads");
}

async function pump() {
  if (busy) return;
  const next = queue.findIndex((b) => b.status === "pending");
  if (next < 0) return;
  busy = true;
  try {
    await runBoard(next);
  } catch (err) {
    console.error("board failed:", err);
    queue[next].status = "done";
    logAction(queue[next].sn, `processing failed — ${err}`, "fail");
  }
  busy = false;
  curIdx = -1;
  updateQueue();
  pump();
}
