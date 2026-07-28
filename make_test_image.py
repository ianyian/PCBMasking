#!/usr/bin/env python3
"""Generate a synthetic PCB-like test image containing a QR code, a 1-D
barcode pattern, serial-number text, and a fake logo — so the masking
pipeline can be tested without any real production data."""

from pathlib import Path

import cv2
import numpy as np

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False


def make_pcb_background(w=1280, h=960):
    img = np.full((h, w, 3), (60, 110, 30), np.uint8)  # PCB green (BGR)
    rng = np.random.default_rng(42)
    # traces
    for _ in range(60):
        x1, y1 = rng.integers(0, w), rng.integers(0, h)
        l = rng.integers(60, 300)
        horiz = rng.random() < 0.5
        x2, y2 = (x1 + l, y1) if horiz else (x1, y1 + l)
        cv2.line(img, (int(x1), int(y1)), (int(x2), int(y2)), (80, 150, 50), 3)
    # pads
    for _ in range(150):
        c = (int(rng.integers(0, w)), int(rng.integers(0, h)))
        cv2.circle(img, c, 6, (140, 190, 200), -1)
        cv2.circle(img, c, 3, (40, 60, 60), -1)
    # ICs
    for _ in range(8):
        x, y = int(rng.integers(50, w - 200)), int(rng.integers(50, h - 120))
        cv2.rectangle(img, (x, y), (x + 160, y + 90), (30, 30, 30), -1)
    return img


def add_barcode(img, x, y, w=260, h=80):
    cv2.rectangle(img, (x - 10, y - 10), (x + w + 10, y + h + 10), (255, 255, 255), -1)
    rng = np.random.default_rng(7)
    cx = x
    while cx < x + w:
        bw = int(rng.integers(2, 7))
        if rng.random() < 0.5:
            cv2.rectangle(img, (cx, y), (cx + bw, y + h), (0, 0, 0), -1)
        cx += bw + int(rng.integers(1, 5))


def add_qr(img, x, y, size=160):
    if HAS_QRCODE:
        qr = qrcode.QRCode(box_size=4, border=2)
        qr.add_data("SN-2026-FLEX-DEMO-0001")
        qr.make()
        m = np.array(qr.get_matrix(), dtype=np.uint8)
        qr_img = cv2.resize((1 - m) * 255, (size, size),
                            interpolation=cv2.INTER_NEAREST)
        img[y:y + size, x:x + size] = cv2.cvtColor(qr_img, cv2.COLOR_GRAY2BGR)
    else:  # crude QR-like block pattern fallback
        rng = np.random.default_rng(3)
        cell = size // 21
        cv2.rectangle(img, (x, y), (x + size, y + size), (255, 255, 255), -1)
        for i in range(21):
            for j in range(21):
                if rng.random() < 0.45:
                    cv2.rectangle(img, (x + j * cell, y + i * cell),
                                  (x + (j + 1) * cell, y + (i + 1) * cell),
                                  (0, 0, 0), -1)


def add_text(img, x, y, text, scale=1.0):
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale,
                (255, 255, 255), 2, cv2.LINE_AA)


def add_logo(img, x, y):
    cv2.ellipse(img, (x + 70, y + 35), (70, 35), 0, 0, 360, (255, 255, 255), -1)
    cv2.putText(img, "ACME", (x + 22, y + 47), cv2.FONT_HERSHEY_TRIPLEX, 1.1,
                (200, 60, 30), 2, cv2.LINE_AA)
    return img[y:y + 70, x:x + 140].copy()


def main():
    out = Path("testdata")
    (out / "raw").mkdir(parents=True, exist_ok=True)
    Path("templates/logos").mkdir(parents=True, exist_ok=True)

    img = make_pcb_background()
    add_barcode(img, 80, 60)
    add_qr(img, 1020, 60)
    add_text(img, 80, 220, "SN: 8834-AA-2026-0417", 0.9)
    add_text(img, 80, 900, "LOT 55021-B  MODEL X99", 0.8)
    logo_crop = add_logo(img, 560, 820)

    cv2.imwrite(str(out / "raw" / "demo_board_01.png"), img)
    cv2.imwrite("templates/logos/acme.png", logo_crop)
    print("wrote testdata/raw/demo_board_01.png and templates/logos/acme.png")
    if not HAS_QRCODE:
        print("note: `pip install qrcode` for a real decodable QR in the test image")


if __name__ == "__main__":
    main()
