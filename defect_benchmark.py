"""Defect-detection method benchmark on the synthetic dataset.

Method A: golden-board comparison (classical, no ML)
  - regenerate each board WITHOUT its defects (deterministic generator)
  - absdiff(test, golden) -> threshold -> morphology -> contours = defects
  - measure per-board runtime + recall vs ground truth

Method B: YOLOv8-nano CPU inference-speed measurement
  - random-initialised weights (no download needed) -> timing only,
    to show what a trained HRIPCB YOLO would cost per board on CPU.
"""
import json, sys, time
from pathlib import Path

import cv2, numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / "demo"))
import random
import generate_dataset as gen

REPO = Path(__file__).resolve().parent
SP = Path.cwd()
ANN = json.load(open(REPO / "demo/dataset/annotations.json"))
N_BOARDS = 10

# ---- build golden twins (defect step skipped, all else identical) ----
real_add_defect = gen.add_defect
def no_defect(img, code, x, y, rng, board, trace):
    # consume the same rng draws as the real one would NOT matter here:
    # defects are the last generation step, nothing depends on rng after.
    return (x - 1, y - 1, x + 1, y + 1)

goldens = {}
gen.add_defect = no_defect
random.seed(gen.SEED)
for i in range(1, N_BOARDS + 1):
    sn = f"PCB-{i:03d}"
    rng = np.random.default_rng(gen.SEED + i)
    img, _ = gen.generate_board(sn, rng)
    goldens[sn] = img
gen.add_defect = real_add_defect

# sanity: golden must be pixel-identical to shipped board outside defect areas
sn0 = "PCB-001"
test0 = cv2.imread(str(REPO / f"demo/dataset/raw/{sn0}.png"))
d = cv2.absdiff(test0, goldens[sn0]).sum(axis=2)
mask = np.zeros(d.shape, bool)
for df in ANN[sn0]["defects"]:
    x1, y1, x2, y2 = df["bbox"]
    mask[max(0,y1-6):y2+6, max(0,x1-6):x2+6] = True
outside = d[~mask]
print(f"sanity: max pixel diff outside defect areas = {outside.max()} (must be 0)")

# ---- Method A: golden diff ----
def golden_diff_detect(test, golden, min_area=60):
    diff = cv2.absdiff(test, golden)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 25, 255, cv2.THRESH_BINARY)
    th = cv2.dilate(th, np.ones((7, 7), np.uint8), iterations=2)
    boxes = []
    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        if cv2.contourArea(c) >= min_area:
            x, y, w, h = cv2.boundingRect(c)
            boxes.append((x, y, x + w, y + h))
    return boxes

def hit(gt, boxes):
    gx1, gy1, gx2, gy2 = gt
    for (x1, y1, x2, y2) in boxes:
        ix = max(0, min(gx2, x2) - max(gx1, x1))
        iy = max(0, min(gy2, y2) - max(gy1, y1))
        if ix * iy > 0:
            return True
    return False

tot_gt = found = extra = 0
times = []
for sn, golden in goldens.items():
    test = cv2.imread(str(REPO / f"demo/dataset/raw/{sn}.png"))
    t = time.perf_counter()
    boxes = golden_diff_detect(test, golden)
    times.append((time.perf_counter() - t) * 1000)
    gts = [tuple(d["bbox"]) for d in ANN[sn]["defects"]]
    tot_gt += len(gts)
    found += sum(hit(g, boxes) for g in gts)
    extra += max(0, len(boxes) - len(gts))
print(f"\nMethod A — golden-board diff over {N_BOARDS} boards:")
print(f"  runtime: mean {np.mean(times):.1f} ms/board  (min {min(times):.1f}, max {max(times):.1f})")
print(f"  recall:  {found}/{tot_gt} ground-truth defects found")
print(f"  false-positive boxes: {extra} total")

# save a visual for PCB-003: golden | test | detections vs ground truth
sn = "PCB-003"
test = cv2.imread(str(REPO / f"demo/dataset/raw/{sn}.png"))
boxes = golden_diff_detect(test, goldens[sn])
vis = test.copy()
for (x1, y1, x2, y2) in boxes:
    cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 210, 255), 8)      # found: yellow
for df in ANN[sn]["defects"]:
    x1, y1, x2, y2 = df["bbox"]
    cv2.rectangle(vis, (x1-14, y1-14), (x2+14, y2+14), (255, 80, 160), 4)  # GT: pink
    cv2.putText(vis, df["code"], (x1-14, max(24, y1-22)),
                cv2.FONT_HERSHEY_SIMPLEX, .95, (255, 80, 160), 2)

def panel(img, title):
    bar = np.full((70, img.shape[1], 3), (64, 35, 14), np.uint8)
    cv2.putText(bar, title, (20, 48), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
    return np.vstack([bar, img])

gap = np.full((test.shape[0] + 70, 16, 3), 255, np.uint8)
combo = np.hstack([panel(goldens[sn], "1. GOLDEN (known-good)"),
                   gap, panel(test, "2. TEST board"),
                   gap, panel(vis, "3. DIFF result vs ground truth")])
combo = cv2.resize(combo, (2400, int(combo.shape[0] * 2400 / combo.shape[1])))
cv2.imwrite(str(SP / "defect_golden_diff.png"), combo)
print(f"  wrote defect_golden_diff.png ({sn}: {len(boxes)} boxes, "
      f"{len(ANN[sn]['defects'])} ground-truth defects)")

# ---- Method B: YOLOv8n CPU speed (random weights, timing only) ----
try:
    from ultralytics import YOLO
    model = YOLO("yolov8n.yaml", verbose=False)  # architecture only, no download
    img = cv2.imread(str(REPO / "demo/dataset/raw/PCB-003.png"))
    model.predict(img, imgsz=960, device="cpu", verbose=False)  # warm-up
    ts = []
    for _ in range(5):
        t = time.perf_counter()
        model.predict(img, imgsz=960, device="cpu", verbose=False)
        ts.append((time.perf_counter() - t) * 1000)
    print(f"\nMethod B — YOLOv8-nano CPU inference (960 px): "
          f"mean {np.mean(ts):.0f} ms/board over 5 runs "
          f"(timing only — weights untrained)")
except Exception as e:
    print("\nMethod B skipped:", type(e).__name__, str(e)[:200])
