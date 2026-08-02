# PCB Defect-Detection Model Training — Background & Plan

Purpose of this document: background, model/dataset analysis and the
training workflow for the **Step 4 defect-detection model** of the
PCBMasking solution. This file is meant to seed a **dedicated
model-training repository** — no code here, only the research results and
the plan. The trained model produced by that repo will be copied back into
the main PCBMasking project and attached to Step 4 of the inspection flow
(currently marked SKIPPED in the HF20 console).

---

## 1. Background — where this model fits

The PCBMasking inspection flow has four steps:

1. **Load board** (operator upload / dataset)
2. **Sensitive-object detection** (barcodes, QR/DataMatrix, text, logos —
   classical decoder + OCR ensemble, already in production)
3. **Irreversible masking** (black fill + fail-closed verification)
4. **Defect detection** — *this model*. Input: a board image. Output:
   bounding boxes + class + confidence for manufacturing defects, which
   drive the PASS/FAIL verdict, the report cards and the defect Pareto.

Target defect taxonomy (HRIPCB standard, 6 classes):

| Class | Meaning |
|---|---|
| `missing_hole` | pad without its drilled hole |
| `mouse_bite` | nibbled trace edge |
| `open_circuit` | broken trace |
| `short` | unintended copper bridge |
| `spur` | copper protrusion from a trace |
| `spurious_copper` | stray copper patch |

Important ordering note for integration: on a real line the defect
detector should see the **original (pre-mask)** image — Step 3's black
rectangles would otherwise hide or imitate defects. The server will run
detection before masking and only display results after.

---

## 2. Base model — is YOLO26 a good pick?

**Yes — YOLO26 is a good and current choice.** (Note on the name: the
model is **YOLO26** by Ultralytics; there is no "YOLO26E" variant — the
"E" you may have seen probably comes from mixing it up with **YOLOE**, a
separate Ultralytics open-vocabulary model. For supervised fine-tuning on
a fixed 6-class defect taxonomy, YOLO26 is the right family; YOLOE is for
text-prompted "detect anything" use cases and is not needed here.)

What the research says (checked August 2026):

- YOLO26 was released January 2026; it is **end-to-end (NMS-free)**,
  smaller and faster than YOLO11/YOLOv8 at the same accuracy tier —
  40.9–57.5 mAP on COCO at 1.7–11.8 ms TensorRT-T4 latency, and
  +1.6…+2.5 box-AP over YOLO11 across sizes.
- The official fine-tuning guide confirms clean transfer learning: a
  COCO-pretrained YOLO26n transfers ~606 of 708 weight tensors onto a
  small custom class set — exactly our situation (6 classes).
- NMS-free end-to-end inference simplifies deployment (no NMS tuning,
  easier ONNX export) — relevant because our HF Space runs on CPU.

**Recommended size: `yolo26n` (nano) first, `yolo26s` if accuracy is
short.** PCB defects are small objects on high-resolution images; the win
comes from training at a large input size (~960–1280 px), not from a
bigger backbone. Nano keeps Colab training fast (well under an hour per
run on a T4) and CPU inference in the Space at roughly 150–300 ms/board.

Fallback option: if YOLO26 tooling gives any trouble in Colab, YOLO11 or
YOLOv8 use the identical dataset format and API — nothing in the plan
changes except the model name.

---

## 3. Dataset comparison — the three Kaggle candidates

| | akhatova / **pcb-defects** | norbertelter / **pcb-defect-dataset** | frettapper / **micropcb-images** |
|---|---|---|---|
| Underlying source | **HRIPCB** (PKU) | **HRIPCB** (same source) | own photos of 13 hobby micro-PCBs |
| Task type | defect **detection** | defect **detection** | board **classification** (which PCB is it) |
| Images | ~1,386 (693 originals + rotated copies) | ~10k+ (HRIPCB with augmented copies) | ~8,000+ |
| Defect classes | 6 (our taxonomy) | 6 (our taxonomy) | **none — no defect labels** |
| Annotation format | Pascal-VOC XML boxes | **YOLO txt, pre-split train/val/test** | class per folder (angle/perspective coded) |
| Fit for Step 4 | good, needs VOC→YOLO conversion | **best — train directly, zero conversion** | not usable for defect training |

Key analysis points:

1. **akhatova and norbertelter are the *same* underlying data (HRIPCB).**
   Using "all datasets" would not add information — it would add
   *duplicates*, and duplicates are actively harmful: augmented copies of
   one physical board landing in both train and validation inflate the
   metrics (data leakage) and hide real weaknesses. **Pick one: use
   norbertelter's** — it is already in YOLO format with proper splits, so
   Colab training starts immediately.
2. **micropcb-images cannot train a defect detector** (it has no defect
   annotations — it exists for recognizing *which* of 13 boards is in the
   photo, across angles). Optional advanced use later: its images make
   good **negative / background samples** (boards with zero defect labels)
   to teach the model that populated, component-covered boards are not
   walls of defects — HRIPCB is bare copper boards, and that is its main
   weakness. Keep it as a stage-2 idea, not part of the first training.
3. **Known limitation to state honestly:** HRIPCB is ~10 bare (unpopulated)
   template boards, photographed cleanly. A model trained only on it will
   be strong on bare-board imagery and weaker on populated boards like the
   NRFMOD sample in the console. The long-term fix is stage-3 fine-tuning
   on ~100–300 labeled photos of *your own* boards from *your own* camera —
   that small dataset will matter more than any public one.

**Recommendation: primary = norbertelter/pcb-defect-dataset. Skip
akhatova (duplicate). Park micropcb for background images later.**

---

## 3b. Full dataset landscape (comparison table)

Clarification first: **HRIPCB is the original academic dataset** (Peking
University HRI Open Lab, paper: "HRIPCB: a challenging dataset for PCB
defects detection and classification"). The two Kaggle sets *akhatova*
and *norbertelter* are **mirrors of HRIPCB** — norbertelter's mirror is
simply HRIPCB repackaged in YOLO format. So "train on norbertelter" and
"train on HRIPCB" mean the same data.

Training sequence: **Run 1** = HRIPCB alone (norbertelter mirror) →
baseline model. **Run 2** = start from the Run-1 weights and retrain on
**HRIPCB + DsPCBSD+ combined** (HRIPCB stays in the mix; DsPCBSD+ is
added). **Run 3** = fine-tune the best model on 100–300 labeled photos of
your own boards.

| Dataset | Total pictures | Source (download) | Advantage | Disadvantage | Use in this project | Others / notes |
|---|---|---|---|---|---|---|
| **HRIPCB** via norbertelter mirror | ~10k YOLO-ready images (from 693 originals + augmented copies, 6 classes) | [kaggle.com/datasets/norbertelter/pcb-defect-dataset](https://www.kaggle.com/datasets/norbertelter/pcb-defect-dataset) (original: PKU HRI Open Lab) | Exactly our 6-class taxonomy; YOLO format + clean splits; zero conversion; the community benchmark | Only ~10 bare template boards; clean studio imagery; weak on populated-board photos | **Y — Run 1 (baseline)** | Same data as akhatova; academic-use license — verify before commercial use |
| **akhatova/pcb-defects** (HRIPCB mirror) | ~1,386 (693 + rotated), VOC XML | [kaggle.com/datasets/akhatova/pcb-defects](https://www.kaggle.com/datasets/akhatova/pcb-defects) | Same content as above | Duplicate of norbertelter; VOC→YOLO conversion needed; mixing both causes train/val leakage | **N — duplicate** | Keep only as a cross-check reference |
| **DsPCBSD+** | 10,259 images / 20,276 hand-annotated defects, 9 classes | [Scientific Data paper + open data links](https://www.nature.com/articles/s41597-024-03656-8) | Largest open real-image PCB defect set; purpose-built for DL detection; adds variety HRIPCB lacks | 9-class taxonomy needs mapping onto ours (extras: scratch, pin-hole…); still bare boards | **Y — Run 2 (added to HRIPCB)** | Highest-value public addition; published 2024 with the data openly released |
| **DeepPCB** | 1,500 template/test pairs, 640×640, 6 classes | [github.com/tangsanli5201/DeepPCB](https://github.com/tangsanli5201/DeepPCB) or [Roboflow mirror](https://universe.roboflow.com/pcbdefectsyolooic/deeppcb-4dhir-dwgtd) | Well-known benchmark; free; YOLO mirror exists | **Binarized** linear-scan images — looks nothing like photos; can *hurt* photo performance | **N for the main mix** (optional experiment only) | Class names differ slightly (pin-hole vs missing_hole) |
| **Roboflow "Bare PCB defects"** | ~9,666 images, 8 classes | [universe.roboflow.com/bare-pcb-defects/obj-detection-pcb-defects-yolov8](https://universe.roboflow.com/bare-pcb-defects/obj-detection-pcb-defects-yolov8) | One-click YOLO export; adds scratch / pin-hole / false-copper classes | Community-curated (quality varies); partially overlaps HRIPCB — dedup needed | **Optional — Run 2 supplement** | Check per-image licenses on Roboflow |
| **SolDef_AI** | 1,150 soldered-SMT images, 3 viewpoints | [kaggle.com/datasets/mauriziocalabrese/soldef-ai-pcb-dataset-for-defect-detection](https://www.kaggle.com/datasets/mauriziocalabrese/soldef-ai-pcb-dataset-for-defect-detection) | Only set covering **solder-joint defects on populated boards** — closest to HF20 uploads | Different defect family; small; mixing into the bare-board model degrades both | **Y — but as a separate later model/class-set (Run 4)** | Bridging / insufficient-solder classes complement, not replace, our 6 |
| **AOI-BarePCB** | n/a (paper dataset) | via authors of [SME-YOLO paper](https://arxiv.org/pdf/2601.11402) | Captured by a real production AOI machine | Not openly downloadable; only 3 defect types | **N — not accessible** | Watch for a public release |
| **micropcb-images** | ~8,000+, 13 board types | [kaggle.com/datasets/frettapper/micropcb-images](https://www.kaggle.com/datasets/frettapper/micropcb-images) | Many angles/perspectives of populated boards | **No defect labels at all** (board-classification set) | **N for training** | Optional: negative/background images in Run 2+ |
| **Your own boards** (to collect) | target 100–300 labeled photos | your camera + LabelImg / CVAT / Roboflow labeling | Matches the real HF20 input exactly — the decisive dataset | Must be photographed and labeled by you | **Y — Run 3 (final fine-tune)** | The single biggest accuracy lever for production |

---

## 4. Training workflow (VS Code + Colab + Google Drive)

Your planned setup is the standard, proven one. The flow:

1. **Google Drive layout** — one project folder, e.g.
   `MyDrive/pcb-defect-training/` containing `datasets/` (the unzipped
   Kaggle download), `runs/` (training outputs), `exports/` (final model
   files). Drive persists between Colab sessions; the ~1–2 GB dataset
   uploads once.
2. **Colab session** (via the VS Code Colab add-in): mount Drive, install
   `ultralytics`, point the dataset YAML at the Drive path, select the
   **T4 GPU** runtime. Free-tier T4 is enough: nano at 960 px for
   ~100 epochs on HRIPCB is well under an hour.
3. **Dataset YAML** — 6 class names in the fixed order above; keep the
   dataset's provided train/val/test split untouched (that split was made
   to avoid the leakage problem from §3).
4. **Training recipe** (first run): `yolo26n` pretrained weights, image
   size 960, ~100 epochs with early stopping, default augmentation except
   **mosaic reduced/off near the end** (mosaic can shred small defects),
   batch size to fill the T4 (~16 at 960 px).
5. **Evaluate** on the untouched test split: overall mAP50 plus
   **per-class recall** — recall matters more than precision here (a
   missed short circuit costs more than a false alarm that a human
   re-checks). HRIPCB-trained detectors typically reach mAP50 ≈ 0.9+;
   treat noticeably lower numbers as a setup problem, not a model limit.
6. **Keep every run's `results.csv` + weights in Drive `runs/`** so
   experiments are comparable; promote the best run's `best.pt` to
   `exports/`.

Suggested repo contents for the new training repository: this document,
the dataset YAML, one Colab notebook, and an `exports/` folder holding the
released model plus a short model card (training date, dataset commit,
metrics, image size).

---

## 5. Bringing the model back into PCBMasking (Step 4)

1. **Export two artifacts** from the best run: `best.pt` (PyTorch, for
   local/GPU use) and an **ONNX export** (for CPU inference in the HF
   Docker Space — ONNX Runtime on CPU is the smoothest path, and YOLO26's
   NMS-free head makes the exported graph self-contained).
2. Place the model in the main repo (e.g. `models/pcb-defect-yolo26n.onnx`,
   well under GitHub/HF size limits at ~5–10 MB for nano).
3. Server change (later, in code): Step 4 runs the model on the
   **original** image, returns defect boxes+classes to the front end; the
   console's SKIP state is replaced by the real verdict — FAIL red flash if
   any defect above threshold, PASS green otherwise; defect codes flow into
   the report cards and the Pareto chart exactly as the on-prem demo
   already renders them.
4. **Threshold policy**: start at confidence ≈ 0.25 and tune on your own
   boards; expose it as a setting later. Bias toward recall (lower
   threshold) with human review of FAILs, consistent with the project's
   fail-safe philosophy.
5. **Golden-board diff stays complementary**: the 3 ms classical
   comparison (already benchmarked in `defect_benchmark.py`, 13/13 recall
   on synthetic boards) remains valuable when fixtures are controlled; the
   YOLO model covers uncontrolled uploads. They can run side by side.

---

## 6. Risks & open items

- **Domain gap (biggest risk):** HRIPCB = bare boards; your console gets
  populated-board photos. Expect degraded real-world recall until stage-3
  fine-tuning on your own labeled photos. Plan labeling early (LabelImg /
  Roboflow / CVAT all export YOLO format).
- **Class imbalance:** monitor per-class metrics; HRIPCB is fairly
  balanced but augmented variants may not be.
- **License:** HRIPCB is published for academic research; verify the
  Kaggle mirror's license terms before any commercial deployment.
- **Colab free-tier limits:** sessions disconnect (~idle timeouts, GPU
  quotas). Keeping everything on Drive makes runs resumable; nano-size
  runs finish comfortably inside one session.
- **Reproducibility:** pin the `ultralytics` version in the training repo
  and record it in the model card with the dataset revision.

---

## Sources

- [Ultralytics YOLO26 docs](https://docs.ultralytics.com/models/yolo26)
- [Ultralytics YOLO26: Unified Real-Time End-to-End Vision Models (arXiv)](https://arxiv.org/html/2606.03748v1)
- [YOLO26: Key Architectural Enhancements and Performance Benchmarking (arXiv)](https://arxiv.org/pdf/2509.25164)
- [Ultralytics fine-tuning guide](https://docs.ultralytics.com/guides/finetuning-guide)
- [Roboflow — YOLO26 overview](https://blog.roboflow.com/yolo26/)
- [HRIPCB: a challenging dataset for PCB defects detection and classification](https://digital-library.theiet.org/doi/full/10.1049/joe.2019.1183)
- [Kaggle — akhatova/pcb-defects](https://www.kaggle.com/datasets/akhatova/pcb-defects)
- [Kaggle — norbertelter/pcb-defect-dataset](https://www.kaggle.com/datasets/norbertelter/pcb-defect-dataset)
- [Kaggle — frettapper/micropcb-images](https://www.kaggle.com/datasets/frettapper/micropcb-images)
- [Enhanced YOLOv11 framework for PCB defect detection (Scientific Reports)](https://www.nature.com/articles/s41598-025-27415-w)
