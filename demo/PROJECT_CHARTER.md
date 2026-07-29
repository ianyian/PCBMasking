# PCB Inspection Live Demo — Project Charter

**Version:** 1.0 · **Owner:** PCBMasking project · **Type:** self-running exhibition demo

## Objective
A self-running, big-screen web demo that visualises the PCB privacy-masking +
defect-inspection pipeline as a continuous "live show": boards stream in from a
top preview bar and pass through four visible processing steps, one board per
cycle, forever.

## Scope
1. **Dataset generator** — 100 synthetic PCB board images with controlled
   variance (barcodes, QR/DataMatrix codes, serial texts, company logos,
   injected defects) plus ground-truth annotations, saved under
   `demo/dataset/`.
2. **Demo web app** (Python/Flask + vanilla JS) — single page, four step
   panels matching the approved mock-up:
   - **Step 1 Inspection** — load raw image, show SN + start timestamp.
   - **Step 2 Object detection** — red boxes on sensitive items; boxes blink
     3×; feature description (counts of barcodes / logos / texts).
   - **Step 3 Object masking** — detected areas filled black (red outline);
     blink 3×; masked-area statistics.
   - **Step 4 Defect detection** — yellow circles/boxes on defects; blink 3×;
     defect code + location list.
   - Each step's frame blinks 3× when it starts and dwells ≥ 2 s.
   - Top preview bar advances to the left after each board; all panels reset
     to blank when a new board is loaded.

## Acceptance criteria
- `python demo/generate_dataset.py` produces 100 PNGs + `annotations.json`.
- `python demo/app.py` serves the demo at http://localhost:8000 and cycles
  boards without any operator input.
- Visual design: formal navy blue (#16345C family) on white background.
- Blink counts (3×) and ≥ 2 s per-step dwell verified in code constants.

## Out of scope
- Real camera/AOI input, real ML models, authentication, persistence.
  Detection results come from generator ground truth so the show is
  deterministic and reliable on stage (see README note).

## Risks
- Browser performance on 4K screens → mitigate with canvas drawing, no video.
- Dataset regeneration must be reproducible → fixed RNG seed.
