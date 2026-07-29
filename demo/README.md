# PCB Inspection Live Demo

A self-running, big-screen "live show" that visualises the privacy-masking +
defect-inspection flow on a stream of 100 synthetic PCB boards. Formal navy
blue / white design intended for shop-floor displays.

Flow: top preview bar (PCB-001 … PCB-100, advancing to the left) →
**Step 1 Inspection** → **Step 2 Object detection** (red boxes, blink 3×) →
**Step 3 Object masking** (black fill, blink 3×) →
**Step 4 Defect detection** (yellow marks, blink 3×) → next board, forever.

## Quick start

```bash
pip install -r demo/requirements.txt
python demo/generate_dataset.py        # builds demo/dataset (100 boards, ~1 min)
python demo/app.py                     # serves http://localhost:8000
```

Open the page on the big screen and press **F11** for full-screen. No operator
input is needed — the show loops through all 100 boards and then restarts.

## What the show does per board

| Step | Visual | Alerting |
|------|--------|----------|
| 1 Inspection | raw board image, SN badge, start timestamp | panel frame blinks 3× |
| 2 Object detection | red boxes on barcodes / QR / DataMatrix / serial texts / logos, feature count table | frame blinks 3×, red boxes blink 3× |
| 3 Object masking | detected regions filled irreversible black (red outline), masked-area statistics | frame blinks 3×, masks blink 3× |
| 4 Defect detection | yellow boxes on defects with code + location table, PASS / FAIL verdict | frame blinks 3×, yellow marks blink 3× |

Every step also dwells ≥ 2 s (`STEP_DWELL_MS` in `static/app.js`) so viewers
can follow, and steps 2–4 show a simulated processing phase (`PROCESS_MS`).
When a new board loads, all four panels reset to blank first.

## Dataset

`generate_dataset.py` writes `demo/dataset/raw/PCB-001.png … PCB-100.png`
(1400×900) plus `demo/dataset/annotations.json` with ground-truth bounding
boxes for every sensitive item and injected defect. Generation is seeded, so
the dataset is reproducible; it is therefore not committed to git.

Variance per board: 1–2 barcodes, 1–2 QR codes, optional DataMatrix,
1–3 serial/lot texts, 1–2 company logos (4 styles), 0–5 defects.

Defect classes follow the public
[PCB defect dataset](https://www.kaggle.com/datasets/norbertelter/pcb-defect-dataset)
(HRIPCB, Peking University), so the demo uses the same vocabulary as the
defect-detection literature: `missing_hole`, `mouse_bite`, `open_circuit`,
`short`, `spur`, `spurious_copper`. Each is drawn with local copper context
(a trace segment or pad) so the anomaly is visually recognisable on screen.

## Demo note

To keep the on-stage show deterministic and rock-solid, the web app replays
the generator's ground-truth annotations rather than running live detectors.
The real detection ensemble lives in `pcb_privacy_mask.py` at the repository
root and can be run offline against `demo/dataset/raw/` to produce genuine
detections on the same images.

## Tuning

All timings are constants at the top of `demo/static/app.js`:
`BLINK_COUNT`, `BLINK_ON_MS`, `BLINK_OFF_MS`, `STEP_DWELL_MS`, `PROCESS_MS`.
