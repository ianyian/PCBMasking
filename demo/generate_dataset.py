#!/usr/bin/env python3
"""Generate the 100-board synthetic PCB demo dataset.

Each board image contains a random mix of sensitive items (1-D barcodes,
QR codes, DataMatrix-style codes, serial-number texts, a company logo) and
injected manufacturing defects (scratch, solder bridge, missing pad,
tombstoned part, discoloration).  Ground truth for every item is written to
demo/dataset/annotations.json so the demo web app can replay detection,
masking and defect marking deterministically on stage.

Usage:
    python demo/generate_dataset.py [--count 100] [--out demo/dataset]
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

SEED = 20260729
W, H = 1400, 900          # board image size
MARGIN = 30               # keep-out border for placed items

DEFECT_TYPES = [
    ("DEF-SCR", "Scratch on solder mask"),
    ("DEF-SB",  "Solder bridge"),
    ("DEF-MP",  "Missing pad / lifted pad"),
    ("DEF-TS",  "Tombstoned component"),
    ("DEF-DC",  "Copper discoloration"),
]

LOGO_STYLES = ["bear", "shield", "ring", "wordmark"]


# ---------------------------------------------------------------------------
# Board background
# ---------------------------------------------------------------------------

def make_board_background(rng: np.random.Generator) -> np.ndarray:
    base_green = (int(rng.integers(35, 55)), int(rng.integers(95, 130)),
                  int(rng.integers(25, 45)))  # BGR dark PCB green
    img = np.full((H, W, 3), base_green, np.uint8)

    trace = (base_green[0] + 25, base_green[1] + 45, base_green[2] + 25)
    for _ in range(int(rng.integers(70, 110))):
        x1, y1 = int(rng.integers(0, W)), int(rng.integers(0, H))
        length = int(rng.integers(60, 380))
        if rng.random() < 0.5:
            x2, y2 = min(W - 1, x1 + length), y1
        else:
            x2, y2 = x1, min(H - 1, y1 + length)
        cv2.line(img, (x1, y1), (x2, y2), trace, int(rng.integers(2, 4)))

    # via pads
    for _ in range(int(rng.integers(140, 220))):
        c = (int(rng.integers(0, W)), int(rng.integers(0, H - 60)))
        cv2.circle(img, c, 6, (150, 200, 210), -1)
        cv2.circle(img, c, 3, (40, 60, 60), -1)

    # IC packages with pins
    for _ in range(int(rng.integers(6, 12))):
        x = int(rng.integers(MARGIN, W - 240))
        y = int(rng.integers(MARGIN, H - 200))
        iw, ih = int(rng.integers(90, 190)), int(rng.integers(60, 110))
        cv2.rectangle(img, (x, y), (x + iw, y + ih), (25, 25, 25), -1)
        for px in range(x + 6, x + iw - 6, 12):
            cv2.rectangle(img, (px, y - 6), (px + 5, y), (170, 190, 200), -1)
            cv2.rectangle(img, (px, y + ih), (px + 5, y + ih + 6),
                          (170, 190, 200), -1)

    # small passives
    for _ in range(int(rng.integers(30, 60))):
        x = int(rng.integers(0, W - 30))
        y = int(rng.integers(0, H - 70))
        cv2.rectangle(img, (x, y), (x + 22, y + 10),
                      (int(rng.integers(60, 120)),) * 3, -1)

    # gold edge-connector fingers along the bottom, like the reference photo
    for fx in range(60, W - 60, 26):
        cv2.rectangle(img, (fx, H - 46), (fx + 16, H - 4), (60, 190, 235), -1)

    # mounting holes
    for c in ((45, 45), (W - 45, 45), (45, H - 90), (W - 45, H - 90)):
        cv2.circle(img, c, 14, (200, 205, 210), -1)
        cv2.circle(img, c, 8, base_green, -1)
    return img


# ---------------------------------------------------------------------------
# Placement bookkeeping (avoid overlapping labels)
# ---------------------------------------------------------------------------

class Placer:
    def __init__(self, rng: np.random.Generator):
        self.rng = rng
        self.taken: list[tuple[int, int, int, int]] = []

    def spot(self, w: int, h: int, tries: int = 60):
        for _ in range(tries):
            x = int(self.rng.integers(MARGIN, W - MARGIN - w))
            y = int(self.rng.integers(MARGIN, H - 90 - h))
            box = (x - 15, y - 15, x + w + 15, y + h + 15)
            if all(box[2] < t[0] or box[0] > t[2] or box[3] < t[1] or
                   box[1] > t[3] for t in self.taken):
                self.taken.append(box)
                return x, y
        return None


# ---------------------------------------------------------------------------
# Sensitive items
# ---------------------------------------------------------------------------

def add_barcode(img, x, y, rng) -> tuple:
    w, h = int(rng.integers(200, 280)), int(rng.integers(60, 90))
    cv2.rectangle(img, (x - 8, y - 8), (x + w + 8, y + h + 22),
                  (255, 255, 255), -1)
    cx = x
    while cx < x + w:
        bw = int(rng.integers(2, 6))
        if rng.random() < 0.55:
            cv2.rectangle(img, (cx, y), (cx + bw, y + h), (0, 0, 0), -1)
        cx += bw + int(rng.integers(1, 4))
    digits = "".join(str(rng.integers(0, 10)) for _ in range(9))
    cv2.putText(img, digits, (x + 20, y + h + 17), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return (x - 8, y - 8, x + w + 8, y + h + 22)


def add_qr(img, x, y, rng, payload: str) -> tuple:
    size = int(rng.integers(110, 170))
    if HAS_QRCODE:
        qr = qrcode.QRCode(box_size=4, border=2)
        qr.add_data(payload)
        qr.make()
        m = np.array(qr.get_matrix(), dtype=np.uint8)
        patch = cv2.resize((1 - m) * 255, (size, size),
                           interpolation=cv2.INTER_NEAREST)
    else:
        cells = 21
        cell = max(3, size // cells)
        size = cell * cells
        patch = np.full((size, size), 255, np.uint8)
        for i in range(cells):
            for j in range(cells):
                if rng.random() < 0.45:
                    patch[i * cell:(i + 1) * cell,
                          j * cell:(j + 1) * cell] = 0
    img[y:y + size, x:x + size] = cv2.cvtColor(patch, cv2.COLOR_GRAY2BGR)
    return (x, y, x + size, y + size)


def add_datamatrix(img, x, y, rng) -> tuple:
    """DataMatrix-style block code (visual only)."""
    cells = 14
    cell = int(rng.integers(5, 8))
    size = cells * cell
    patch = np.full((size, size), 255, np.uint8)
    for i in range(cells):
        for j in range(cells):
            if i == cells - 1 or j == 0:            # solid L finder pattern
                patch[i * cell:(i + 1) * cell, j * cell:(j + 1) * cell] = 0
            elif (i == 0 and j % 2 == 0) or (j == cells - 1 and i % 2 == 0):
                patch[i * cell:(i + 1) * cell, j * cell:(j + 1) * cell] = 0
            elif rng.random() < 0.45:
                patch[i * cell:(i + 1) * cell, j * cell:(j + 1) * cell] = 0
    img[y:y + size, x:x + size] = cv2.cvtColor(patch, cv2.COLOR_GRAY2BGR)
    return (x, y, x + size, y + size)


def add_serial_text(img, x, y, rng) -> tuple[tuple, str]:
    text = rng.choice([
        f"SN {rng.integers(1000, 9999)}-{rng.integers(10, 99)}-2026",
        f"LOT {rng.integers(10000, 99999)}-{chr(65 + rng.integers(0, 6))}",
        f"MODEL X{rng.integers(10, 99)} REV{chr(65 + rng.integers(0, 4))}",
        f"WO-{rng.integers(100000, 999999)}",
    ])
    scale = 0.75
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    cv2.rectangle(img, (x - 6, y - th - 8), (x + tw + 6, y + 8),
                  (245, 245, 245), -1)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale,
                (10, 10, 10), 2, cv2.LINE_AA)
    return (x - 6, y - th - 8, x + tw + 6, y + 8), text


def add_logo(img, x, y, rng, style: str) -> tuple:
    s = 90
    if style == "bear":
        cv2.rectangle(img, (x, y), (x + s, y + s), (20, 20, 20), -1)
        c = (x + s // 2, y + s // 2 + 6)
        cv2.circle(img, c, 28, (255, 255, 255), -1)
        cv2.circle(img, (c[0] - 22, c[1] - 24), 11, (255, 255, 255), -1)
        cv2.circle(img, (c[0] + 22, c[1] - 24), 11, (255, 255, 255), -1)
        cv2.circle(img, (c[0] - 10, c[1] - 6), 4, (20, 20, 20), -1)
        cv2.circle(img, (c[0] + 10, c[1] - 6), 4, (20, 20, 20), -1)
        cv2.circle(img, (c[0], c[1] + 8), 6, (20, 20, 20), -1)
    elif style == "shield":
        pts = np.array([(x + s // 2, y), (x + s, y + s // 4),
                        (x + s - 12, y + s), (x + 12, y + s),
                        (x, y + s // 4)], np.int32)
        cv2.fillPoly(img, [pts], (255, 255, 255))
        cv2.putText(img, "NX", (x + 18, y + 62), cv2.FONT_HERSHEY_TRIPLEX,
                    1.1, (140, 60, 20), 2, cv2.LINE_AA)
    elif style == "ring":
        cv2.circle(img, (x + s // 2, y + s // 2), s // 2, (255, 255, 255), -1)
        cv2.circle(img, (x + s // 2, y + s // 2), s // 2 - 12, (30, 80, 160), 6)
        cv2.putText(img, "O", (x + 28, y + 64), cv2.FONT_HERSHEY_TRIPLEX,
                    1.3, (30, 80, 160), 3, cv2.LINE_AA)
    else:  # wordmark
        cv2.rectangle(img, (x, y + 20), (x + 150, y + 70), (255, 255, 255), -1)
        cv2.putText(img, "ACME", (x + 14, y + 56), cv2.FONT_HERSHEY_TRIPLEX,
                    1.0, (170, 70, 20), 2, cv2.LINE_AA)
        return (x, y + 20, x + 150, y + 70)
    return (x, y, x + s, y + s)


# ---------------------------------------------------------------------------
# Defects
# ---------------------------------------------------------------------------

def add_defect(img, code: str, x, y, rng) -> tuple:
    if code == "DEF-SCR":
        x2 = min(x + int(rng.integers(70, 150)), W - MARGIN)
        y2 = int(np.clip(y + int(rng.integers(-30, 30)), MARGIN, H - 100))
        cv2.line(img, (x, y), (x2, y2), (185, 205, 210), 3)
        return (min(x, x2) - 8, min(y, y2) - 8, max(x, x2) + 8, max(y, y2) + 8)
    if code == "DEF-SB":
        cv2.rectangle(img, (x, y), (x + 26, y + 10), (150, 170, 180), -1)
        cv2.ellipse(img, (x + 13, y + 14), (16, 8), 0, 0, 360,
                    (160, 180, 190), -1)
        return (x - 8, y - 8, x + 34, y + 28)
    if code == "DEF-MP":
        cv2.circle(img, (x, y), 11, (30, 45, 35), -1)
        cv2.circle(img, (x, y), 11, (90, 110, 100), 2)
        return (x - 19, y - 19, x + 19, y + 19)
    if code == "DEF-TS":
        cv2.rectangle(img, (x, y), (x + 24, y + 10), (70, 70, 75), -1)
        pts = np.array([(x + 24, y + 10), (x + 40, y - 12), (x + 46, y - 8),
                        (x + 30, y + 12)], np.int32)
        cv2.fillPoly(img, [pts], (95, 95, 100))
        return (x - 8, y - 20, x + 54, y + 20)
    # DEF-DC discoloration
    overlay = img.copy()
    axes = (int(rng.integers(25, 45)), int(rng.integers(18, 32)))
    cv2.ellipse(overlay, (x, y), axes, 0, 0, 360, (40, 90, 120), -1)
    cv2.addWeighted(overlay, 0.55, img, 0.45, 0, img)
    return (x - axes[0] - 6, y - axes[1] - 6, x + axes[0] + 6, y + axes[1] + 6)


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------

def generate_board(sn: str, rng: np.random.Generator) -> tuple[np.ndarray, dict]:
    img = make_board_background(rng)
    placer = Placer(rng)
    labels = []

    for _ in range(int(rng.integers(1, 3))):          # 1-2 barcodes
        pos = placer.spot(300, 120)
        if pos:
            labels.append({"type": "barcode",
                           "bbox": add_barcode(img, *pos, rng)})
    for _ in range(int(rng.integers(1, 3))):          # 1-2 QR codes
        pos = placer.spot(175, 175)
        if pos:
            labels.append({"type": "qrcode",
                           "bbox": add_qr(img, *pos, rng, f"{sn}-TRACE")})
    if rng.random() < 0.75:                           # optional DataMatrix
        pos = placer.spot(120, 120)
        if pos:
            labels.append({"type": "datamatrix",
                           "bbox": add_datamatrix(img, *pos, rng)})
    for _ in range(int(rng.integers(1, 4))):          # 1-3 serial texts
        pos = placer.spot(320, 50)
        if pos:
            bbox, text = add_serial_text(img, pos[0], pos[1] + 34, rng)
            labels.append({"type": "text", "bbox": bbox, "value": text})
    n_logos = int(rng.integers(1, 3))                 # 1-2 logos
    for _ in range(n_logos):
        style = str(rng.choice(LOGO_STYLES))
        pos = placer.spot(160, 100)
        if pos:
            labels.append({"type": "logo", "style": style,
                           "bbox": add_logo(img, *pos, rng, style)})

    defects = []
    for _ in range(int(rng.integers(0, 6))):          # 0-5 defects
        code, desc = DEFECT_TYPES[int(rng.integers(0, len(DEFECT_TYPES)))]
        pos = placer.spot(70, 60)
        if pos:
            bbox = add_defect(img, code, pos[0] + 20, pos[1] + 20, rng)
            defects.append({"code": code, "desc": desc,
                            "bbox": tuple(int(v) for v in bbox)})

    ann = {
        "sn": sn,
        "width": W,
        "height": H,
        "labels": [{**l, "bbox": [int(v) for v in l["bbox"]]} for l in labels],
        "defects": [{**d, "bbox": [int(v) for v in d["bbox"]]} for d in defects],
    }
    return img, ann


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--out", default=str(Path(__file__).parent / "dataset"))
    args = ap.parse_args()

    out = Path(args.out)
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    random.seed(SEED)
    annotations = {}
    for i in range(1, args.count + 1):
        sn = f"PCB-{i:03d}"
        rng = np.random.default_rng(SEED + i)
        img, ann = generate_board(sn, rng)
        cv2.imwrite(str(raw / f"{sn}.png"), img)
        annotations[sn] = ann
        if i % 20 == 0:
            print(f"  generated {i}/{args.count}")

    with open(out / "annotations.json", "w") as f:
        json.dump(annotations, f)
    print(f"done: {args.count} boards in {raw}, "
          f"ground truth in {out / 'annotations.json'}")
    if not HAS_QRCODE:
        print("note: `pip install qrcode` to embed real decodable QR codes")


if __name__ == "__main__":
    main()
