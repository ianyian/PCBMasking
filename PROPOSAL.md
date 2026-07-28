# PCB Privacy Masking Pipeline — Proposal

**Context:** Pre-processing module (Approach A from Chapter 3) that masks customer logos,
barcodes/QR codes, serial numbers, lot codes, and product model identifiers on PCB/AOI
images **before** they are fed to YOLOE-26s. Runs fully offline on a local machine.

---

## 1. Why Approach A (pre-processing) should be the baseline

- **Provable compliance:** the model never receives sensitive pixels. You can hand the
  Legal team a folder of masked images plus a per-image audit log — no need to argue
  about what a backbone "sees" internally.
- **Model-agnostic:** works with YOLOE-26s today and any future architecture.
- **Fail-closed design is possible:** if any detector is uncertain, you can over-mask or
  quarantine the image for human review. Approach B cannot fail closed.

Keep Approach B (P3-level attention masking) as a *research contribution / comparison*,
but use Approach A as the compliance gate. A hybrid ("A for compliance, B for robustness
against masking misses") is a defensible thesis position.

## 2. What must be detected, and the best tool for each

| Sensitive item | Primary detector | Backup / ensemble |
|---|---|---|
| QR / DataMatrix codes | `pyzbar` + OpenCV `QRCodeDetector` (multi) | `pylibdmtx` for DataMatrix (very common on PCBs) |
| 1-D barcodes (Code128/39) | OpenCV contrib `cv2.barcode.BarcodeDetector` | `pyzbar` |
| Serial numbers, lot codes, silkscreen text | Text detector: **PaddleOCR PP-OCR det** or **EAST** | EasyOCR (CRAFT) |
| Customer logos | Per-board **fixed ROI config** (logo positions are fixed per design) + template matching | Open-vocabulary detector (YOLOE / YOLO-World, prompt: "logo") |
| Product model identifiers | Covered by text detection + ROI config | — |

**Key insight for your factory setting:** every board design has a known layout. A
per-board-type ROI configuration (YAML) is the highest-precision, zero-ML compliance
tool — the learned detectors then act as a safety net for anything outside the
configured ROIs and for new/unknown board types.

## 3. Model options (all run offline after a one-time download)

**Option 1 — Classical / lightweight (recommended starting point)**
- pyzbar + pylibdmtx + OpenCV barcode/QR detectors, EAST text detector (frozen `.pb`,
  ~25 MB), template matching for logos.
- CPU-only, milliseconds per image, fully deterministic, easy to explain to Legal.
- Weakness: EAST misses stylized logos; decoders can miss damaged/low-contrast codes
  (mitigated by the ROI config + padding + ensemble).

**Option 2 — OCR-toolkit detection**
- PaddleOCR PP-OCRv4 detection model (DBNet) or EasyOCR (CRAFT). Better recall on small
  silkscreen text than EAST. ~100–200 ms/image CPU. Download once, then fully offline.

**Option 3 — Open-vocabulary zero-shot detection**
- YOLOE / YOLO-World (Ultralytics) or Grounding DINO with text prompts:
  `"barcode", "qr code", "company logo", "printed text"`. No training data needed,
  best for logos on unseen board designs. Runs offline on your GPU. This also dovetails
  nicely with your thesis — the privacy masker itself is open-vocabulary.

**Option 4 — Fine-tuned custom detector (best long-term)**
- Annotate ~300–1000 PCB images with 4 classes (barcode, qr/datamatrix, text, logo) and
  fine-tune YOLOv8n/YOLO11n. Highest accuracy, single fast model. Do this once the
  classical pipeline has bootstrapped pseudo-labels for you (decoded barcodes = free
  ground truth).

**Recommended architecture: ensemble of 1 + 2 + 3**, union all detections, pad each
region, mask, and log. Precision of decoders + recall of text/open-vocab detectors.

## 4. Masking method — use irreversible fill, not blur

- **Solid fill (black/board-colour)** — recommended. Gaussian blur and pixelation can be
  partially reversible (deblurring attacks) and Legal may reject them.
- Optional **inpainting** (`cv2.inpaint` or LaMa) if hard black rectangles hurt the
  defect detector near masked regions — still irreversible.
- Pad every detected region by ~10–15 px before masking.
- **Fail-closed rule:** if pyzbar *decodes* a code anywhere in the final masked image
  (verification pass), the image is quarantined, never released.

## 5. Compliance workflow

1. Raw AOI image (isolated environment) → 2. ensemble detection → 3. union + padding →
4. solid-fill mask → 5. **verification pass** (re-run decoders/OCR on masked output; must
find nothing) → 6. per-image JSON audit record (SHA-256 of input/output, detections,
mask coords, pipeline version) → 7. random 5–10 % human spot-check → 8. release masked
set to training environment.

The audit JSON + verification pass is what turns this from "we blur images" into
something the Flex Legal team can sign off.

## 6. Sample datasets (for developing/testing the masker before real data)

Public PCB image datasets containing real text/logos/codes:

- **FICS-PCB / FPIC** (University of Florida SCAN Lab) — high-res real PCB photos with
  component + text annotations. https://www.trust-hub.org/#/data/pcb-images
- **PCB-DSLR dataset** (TU Wien CVL) — 748 DSLR images of real scrap PCBs, lots of ICs
  with printed text/logos. https://cvl.tuwien.ac.at/research/cvl-databases/pcb-dslr-dataset/
- **PCB WACV / PCB-METAL** datasets — real boards, visible silkscreen and markings.
- **PKU-Market-PCB** (Peking Univ.) and **DeepPCB** — the standard PCB *defect* datasets
  (open circuit, short, mousebite …) to verify masking doesn't hurt defect detection.
  https://robotics.pkusz.edu.cn/resources/dataset/ · https://github.com/tangsanli5201/DeepPCB
- **Roboflow Universe** — search "PCB text", "barcode", "QR" for small annotated sets
  you can merge for fine-tuning Option 4.
- **Synthetic augmentation:** paste generated barcodes (`python-barcode`), QR codes
  (`qrcode`), DataMatrix (`treepoem`) and fake logos onto PCB backgrounds — free
  unlimited labelled data for the masker. The included `make_test_image.py` does a
  simple version of this.

## 7. Suggested evaluation for the thesis

- **Privacy recall** (fraction of sensitive regions fully masked — the compliance
  metric; target ≈ 100 % with fail-closed quarantine)
- **Over-masking rate** (masked area that was not sensitive)
- **Downstream impact:** mAP of defect detection on masked vs. unmasked DeepPCB/PKU
  images — quantifies the cost of Approach A, which motivates the Approach B comparison.
