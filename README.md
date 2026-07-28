# PCBMasking — offline privacy pre-processing for PCB defect detection

Masks customer logos, barcodes, QR/DataMatrix codes, serial numbers, and lot
codes on PCB/AOI images **before** they are used for ML training. Runs fully
offline — no image data ever leaves the machine. See [PROPOSAL.md](PROPOSAL.md)
for the research-level design rationale, model options, and dataset sources.

---

## 1. Quick reference — commands

### One-time setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional (better decoding coverage — requires Homebrew):

```bash
brew install zbar libdmtx
pip install pyzbar pylibdmtx
```

Optional (much better text detection; large download, offline after first run):

```bash
pip install easyocr
```

### Testing with synthetic data (no real data needed)

```bash
# 1. Generate a fake PCB image containing a barcode, QR code, serial text, and logo
.venv/bin/python make_test_image.py

# 2. Mask it
.venv/bin/python pcb_privacy_mask.py testdata/raw -o output --board-type demo_board

# 3. Inspect results
open output/masked/demo_board_01.png     # sensitive items must be blacked out
cat output/audit_log.json                # compliance record
ls output/quarantine 2>/dev/null         # should not exist / be empty
```

### Production usage (real AOI images)

```bash
# Single image
.venv/bin/python pcb_privacy_mask.py /path/to/board.png -o output_prod

# Whole directory (recurses into subfolders; png/jpg/bmp/tif)
.venv/bin/python pcb_privacy_mask.py /path/to/aoi_images -o output_prod

# With a per-board ROI profile defined in config.yaml (recommended in production)
.venv/bin/python pcb_privacy_mask.py /path/to/aoi_images -o output_prod --board-type BOARD_A123

# With a custom config file
.venv/bin/python pcb_privacy_mask.py /path/to/aoi_images -o output_prod --config prod_config.yaml
```

Production checklist per batch:

1. Run the pipeline into a fresh output directory.
2. Confirm `quarantine/` is empty; if not, review those images manually,
   fix the cause (usually: add an ROI or logo template), and re-run.
3. Spot-check 5–10 % of `masked/` images visually.
4. Archive `audit_log.json` alongside the released dataset — this is your
   compliance evidence for the Legal team.
5. Only the `masked/` folder leaves the isolated environment.

### Output layout

```
output/
  masked/        # released images (passed fail-closed verification)
  quarantine/    # images where sensitive content was STILL detectable after masking
  audit_log.json # per-image record: SHA-256 hashes, detections, coordinates, status
```

---

## 2. Libraries used and the purpose of each

| Library | What it detects | Why it is in the ensemble |
|---|---|---|
| **zxing-cpp** | Decodes QR, DataMatrix, Aztec, and all common 1-D barcodes | Primary decoder. Pure pip install (no system libraries). A successful *decode* is proof the region contains machine-readable tracking data — zero false positives. Pinned to 2.2.0 on Python 3.9. |
| **pyzbar** (optional) | Decodes QR + 1-D barcodes via the zbar C library | Second, independent decoder implementation. Different engines fail on different damaged/low-contrast codes, so running both raises recall. Needs `brew install zbar`. |
| **pylibdmtx** (optional) | Decodes DataMatrix codes | DataMatrix is the *most common* code format laser-etched on real PCBs; a dedicated decoder for it is worth having. Needs `brew install libdmtx`. |
| **OpenCV `QRCodeDetector`** | *Locates* QR codes even when they cannot be decoded | Decoders only report codes they can read. A blurred or damaged QR still leaks partial information, so we also need pure *detection*. Both the multi-code and single-code APIs are called because they fail on different images. |
| **OpenCV `cv2.barcode`** (contrib) | Locates 1-D barcodes without decoding | Same reasoning: find bars that no decoder could read. |
| **Gradient heuristic** (built-in, no ML) | 1-D barcode stripe patterns | Barcode bars produce a strong horizontal gradient and weak vertical gradient. Sobel-based filtering + morphology finds this signature. Always available, catches codes every other detector missed. Tuned to over-detect. |
| **White-label heuristic** (built-in, no ML) | Bright adhesive labels | On real AOI images, barcodes/serials are almost always printed on white labels stuck to a dark board. Masking *every* bright blob is a cheap, very-high-recall safety net. Disable with `mask_white_labels: false` if your boards are light-coloured. |
| **EasyOCR** or **EAST** (optional) | Printed text regions (serial numbers, lot codes, model IDs) | Silkscreen/label text is sensitive under the NDA. EasyOCR (CRAFT detector) has the best recall on small text; EAST is a lighter frozen model (`models/frozen_east_text_detection.pb`). Whichever is available is used. |
| **Template matching** (OpenCV) | Known customer logos | Multi-scale `matchTemplate` against crops in `templates/logos/`. Deterministic and easy to explain to Legal; add one crop per known logo. |
| **Fixed ROIs** (`config.yaml`) | Anything at a known position | Logo/serial positions are fixed per board design, so a per-board ROI list gives *guaranteed* masking with zero ML uncertainty. This is the compliance backbone in production; the learned detectors are the safety net for new/unknown designs. |
| **numpy / pyyaml** | — | Array math and config parsing. |

Every optional library degrades gracefully: if it is not installed, that
backend is silently disabled and the rest of the ensemble still runs. The
startup banner prints exactly which detectors are active — check it matches
what you expect before a production run.

---

## 3. The masking procedure, step by step

```
raw image
   │
   ▼
[1] DETECT  — every active detector runs independently
   │            (decoders, locators, heuristics, OCR, templates, fixed ROIs)
   ▼
[2] MERGE   — overlapping boxes of the same class are union-merged
   ▼
[3] PAD     — every box is expanded by padding_px (default 12 px)
   ▼
[4] MASK    — union of all boxes is filled solid black (irreversible)
   ▼
[5] VERIFY  — all decoders + OCR re-run on the MASKED image
   │
   ├─ nothing found → output/masked/  + audit record  (released)
   └─ anything found → output/quarantine/ + audit record (never released)
```

---

## 4. Technical rationale — why the pipeline is designed this way

### Why detect first, then mask (two phases, not one)?

1. **You cannot mask what you have not located.** Masking is just "set these
   pixels to black" — the entire difficulty is deciding *which* pixels. Splitting
   detection from masking means each detector only has to answer "where is
   something sensitive?", and the masking stage can combine all answers.
2. **Auditability.** The audit log records every detected region with its
   coordinates, class, confidence, and which detector found it. If masking were
   fused into detection, you could not show the Legal team *what* was removed
   and *why* — the two-phase design produces the evidence trail.
3. **Ensemble union.** No single detector is reliable enough for a compliance
   guarantee (decoders miss damaged codes; OCR misses stylized logos; templates
   miss new designs). Because detection is a separate phase, the pipeline can
   take the **union** of many weak-but-different detectors, so one detector's
   miss is covered by another's hit. Precision matters less than recall here —
   an over-masked component is a minor training-data loss; a leaked serial
   number is an NDA violation.
4. **Tunability without touching the mask logic.** Thresholds, new detectors,
   or per-board ROIs can be added without ever changing (or re-validating) the
   masking and verification code.

### Why solid fill instead of blur?

Gaussian blur and pixelation are *partially reversible* — deconvolution and
ML-based deblurring can recover text and even decode blurred barcodes.
Setting pixels to a constant destroys the information irrecoverably, which is
the only masking style with a defensible compliance story. (An `inpaint` style
exists for cases where hard black rectangles disturb downstream training; it
is equally irreversible but slightly slower.)

### Why pad every detection?

Detectors return tight boxes. A barcode's quiet zone, the first character of a
serial, or a logo's outline can extend a few pixels beyond the detection. The
12 px padding (configurable via `padding_px`) makes the mask robust to small
localisation errors at negligible cost.

### Why a verification pass ("fail-closed")?

The masked image is re-scanned with every decoder and the OCR before release.
If *anything* sensitive is still detectable, the image goes to `quarantine/`
and is never released. This inverts the failure mode: a pipeline bug or a
missed detection results in a *withheld* image, not a *leaked* one. For a
compliance process, the default outcome of any failure must be "no data
released" — that is what fail-closed means, and it is the property that makes
this pipeline something Legal can sign off, rather than a best-effort blur.

Note the asymmetry: verification can only use detectors that *positively
identify* content (decoders, OCR). Heuristics that over-detect (gradient,
white-label) are used for masking but not for verification, otherwise every
image would quarantine itself.

### Why hashes in the audit log?

Each record stores the SHA-256 of the input and output files. This proves,
later, exactly which raw image produced which released image and that neither
was modified after processing — chain-of-custody for the dataset.

### Why per-board fixed ROIs when we have detectors?

In production at Flex, every board design has a known, fixed layout — the logo
is always at the same coordinates on BOARD_A123. A configured ROI is masked
*unconditionally*: no model, no threshold, no failure mode. Detectors then only
carry the risk for *unknown* content (new labels, repositioned markings, new
board types). This is the same defense-in-depth logic as the ensemble: the
deterministic layer guarantees the known cases, the learned layer covers the
unknown ones.

---

## 5. Configuring for real boards

- Add each board design to `board_types` in [config.yaml](config.yaml) with the
  fixed pixel ROIs of its logo/serial/label areas, then run with
  `--board-type <key>`.
- Drop cropped logo images into `templates/logos/` (any common image format).
- `mask_style: fill | inpaint`, `padding_px`, `mask_white_labels`,
  `logo_threshold`, and `text_conf` are all tunable in the config.
- For higher text recall install EasyOCR (`pip install easyocr`) or place the
  EAST model at `models/frozen_east_text_detection.pb`.
