# PCBMasking — offline privacy pre-processing for PCB defect detection

Masks customer logos, barcodes, QR/DataMatrix codes, serial numbers, and lot
codes on PCB/AOI images **before** they are used for ML training. Runs fully
offline. See [PROPOSAL.md](PROPOSAL.md) for the full design rationale, model
options, and dataset sources.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Optional but strongly recommended system libraries for the decoders:
brew install zbar libdmtx        # macOS (apt-get install libzbar0 libdmtx0b on Linux)

# Generate a synthetic test board (no real data needed) and run the pipeline:
python make_test_image.py
python pcb_privacy_mask.py testdata/raw -o output --board-type demo_board
```

Output layout:

```
output/
  masked/        # released images (passed fail-closed verification)
  quarantine/    # images where sensitive content was still detectable
  audit_log.json # per-image compliance record (hashes, detections, status)
```

## How it works

1. **Ensemble detection** — every detector that is installed runs; missing
   optional dependencies just disable that backend:
   - `pyzbar` (QR + 1-D), `pylibdmtx` (DataMatrix), OpenCV QR + barcode detectors
   - gradient-based 1-D barcode heuristic (no ML, always available)
   - white-label blob detector (barcode/serial labels are bright on dark boards)
   - text detection: EAST (drop `frozen_east_text_detection.pb` into `models/`)
     or EasyOCR if installed
   - logo template matching (`templates/logos/`) + per-board fixed ROIs
     (`config.yaml`) — the highest-precision compliance tool
2. **Irreversible masking** — union of all regions, padded, solid-filled
   (blur is deliberately not offered; it is partially reversible).
3. **Fail-closed verification** — decoders/OCR re-run on the masked output;
   any surviving sensitive content sends the image to `quarantine/` instead of
   `masked/`.
4. **Audit log** — SHA-256 of input/output, every detection with source and
   coordinates, pipeline version, quarantine status.

## Configuring for real boards

- Add each board design to `board_types` in [config.yaml](config.yaml) with the
  fixed pixel ROIs of its logo/serial/label areas.
- Drop cropped logo images into `templates/logos/`.
- For higher text recall install EasyOCR (`pip install easyocr`, models cached
  locally after first run) or place the EAST model in `models/`.
