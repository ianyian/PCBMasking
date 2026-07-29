# How to Run the PCB Inspection Live Demo

Step-by-step instructions for setting up and running the demo on a
presentation machine / big screen. Everything runs locally — no internet
connection is needed at show time.

---

## 1. Prerequisites

- **Python 3.10 or newer** (`python3 --version` to check)
- A modern browser (Chrome / Edge / Firefox)
- ~50 MB free disk space for the generated dataset

## 2. One-time setup

From the repository root:

```bash
# (recommended) create an isolated environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# install the demo's dependencies
pip install -r demo/requirements.txt
```

The 100-board sample dataset is **already included in the repository** at
`demo/dataset/raw/PCB-001.png … PCB-100.png` with its ground truth in
`demo/dataset/annotations.json`. It was generated once and committed, so
every demo run uses the identical fixed folder — you can point auditors at
that path to cross-check the source images. Nothing is generated on the fly.

(Only if you ever want to rebuild it deliberately:
`python demo/generate_dataset.py` — the generator is seeded and reproduces
the identical dataset.)

## 3. Start the demo

```bash
python demo/app.py
```

Then open **http://localhost:8000** in the browser and press **F11** for
full screen. That's all — the show starts by itself, cycles through all
100 boards (Step 1 load → Step 2 detect → Step 3 mask → Step 4 defects),
and loops forever. No clicks or keyboard input are needed during the show.

To use another port (e.g. 8000 already taken):

```bash
python demo/app.py --port 8080
```

To show it on a second machine on the same network, start the server as
above and browse to `http://<server-ip>:8000` from the display machine.

## 4. What you will see

- **Top preview bar** — the queue of upcoming boards; the current board is
  highlighted and the bar slides to the left after each board finishes.
- **Four step panels** — each panel's frame blinks 3× when its step starts,
  detection boxes (red), masks (black) and defect marks (yellow) each blink
  3×, and every step pauses ~2 s so the audience can follow.
- **Action log (right edge, top ~70%)** — a timestamped before/after history
  of every action in the format `HH:MM:SS.mmm [PCB-006] message`, so entries
  group by board serial at a glance. The newest entry appears at the top and
  entries flow downward; the oldest drop off the bottom.
- **Report (right edge, bottom ~30%)** — one summary card per finished
  board: objects masked, masked share, defect codes, and a big verdict —
  green **PASS** / red **FAIL**. Newest on top, keeps appending as boards
  complete.
- **Settings (gear button, top-right)** — toggle **dark mode**; the choice
  is remembered across reloads.
- **Status bar (bottom)** — the current step and board counter.

## 5. Adjusting the show

Timing constants at the top of `demo/static/app.js` (edit, then reload the
browser page — no server restart needed):

| Constant | Default | Meaning |
|---|---|---|
| `BLINK_COUNT` | 3 | blinks per frame / overlay alert |
| `BLINK_ON_MS` / `BLINK_OFF_MS` | 300 / 220 | blink speed |
| `STEP_DWELL_MS` | 2000 | pause after each step (ms) |
| `PROCESS_MS` | 1400 | simulated processing phase (ms) |
| `MAX_ACTIONS` | 22 | entries kept in the action log |

Dataset size or content: re-run `python demo/generate_dataset.py`
(`--count N` for a different number of boards), then restart `app.py`
(the server loads annotations at startup).

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `dataset not found` when starting `app.py` | run `python demo/generate_dataset.py` first |
| Page stuck on "Waiting for demo server…" | the browser was opened before the server — it retries automatically every 2 s; check the server terminal |
| "Dataset is empty" message on screen | regenerate the dataset, then restart the server and reload the page |
| Port already in use | `python demo/app.py --port 8080` and browse to that port |
| Boards look different after editing the generator | expected — delete `demo/dataset/` and regenerate |

## 7. Demo-mode notes (transparency)

- **Data source:** the boards are synthetic images from the demo dataset
  (`demo/dataset/raw/`), not a live line camera — Step 1 states this on
  screen.
- **Detection results** shown in the demo are replayed from the dataset's
  ground-truth annotations so the show is deterministic and never misses on
  stage. The real detection ensemble (barcode/QR decoders, OCR, logo
  matching) lives in `pcb_privacy_mask.py` at the repository root and can be
  run offline against the same images:
  `python pcb_privacy_mask.py demo/dataset/raw -o output`
