#!/usr/bin/env python3
"""Offline PCB privacy-masking pipeline.

Detects and irreversibly masks sensitive regions on PCB/AOI images before they
are used for ML training: barcodes, QR/DataMatrix codes, printed text (serials,
lot codes, model IDs), and customer logos.

Design goals:
  * Fully offline (no network calls at runtime).
  * Ensemble of detectors; every detector is optional and degrades gracefully.
  * Fail-closed: a verification pass re-scans the masked output; if anything is
    still decodable the image is quarantined instead of released.
  * Per-image JSON audit record for compliance evidence.

Usage:
    python pcb_privacy_mask.py INPUT_DIR_OR_FILE -o OUTPUT_DIR [--config config.yaml]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

# Help pyzbar/pylibdmtx find Homebrew-installed zbar/libdmtx on macOS
# (ctypes reads DYLD_LIBRARY_PATH at lookup time, so setting it here works).
if sys.platform == "darwin":
    for _p in ("/opt/homebrew/lib", "/usr/local/lib"):
        if os.path.isdir(_p) and _p not in os.environ.get("DYLD_LIBRARY_PATH", ""):
            os.environ["DYLD_LIBRARY_PATH"] = (
                _p + ":" + os.environ.get("DYLD_LIBRARY_PATH", ""))
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import cv2
import numpy as np

try:
    import yaml
except ImportError:
    yaml = None

# ---------------------------------------------------------------------------
# Optional detector backends — each import failure just disables that backend.
# ---------------------------------------------------------------------------
try:
    from pyzbar import pyzbar
    HAS_PYZBAR = True
except Exception:
    HAS_PYZBAR = False

try:
    from pylibdmtx import pylibdmtx
    HAS_DMTX = True
except Exception:
    HAS_DMTX = False

HAS_CV_BARCODE = hasattr(cv2, "barcode")

try:
    import zxingcpp
    HAS_ZXING = True
except Exception:
    HAS_ZXING = False

try:
    import easyocr
    HAS_EASYOCR = True
except Exception:
    HAS_EASYOCR = False


PIPELINE_VERSION = "1.0.0"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


@dataclass
class Region:
    """One detected sensitive region (axis-aligned bbox, x1y1x2y2)."""
    label: str          # barcode | qrcode | datamatrix | text | logo | roi
    source: str         # which detector produced it
    bbox: tuple         # (x1, y1, x2, y2) ints
    confidence: float = 1.0
    decoded: bool = False   # True if the content was actually decodable


@dataclass
class AuditRecord:
    input_file: str
    input_sha256: str
    output_file: str = ""
    output_sha256: str = ""
    pipeline_version: str = PIPELINE_VERSION
    timestamp: str = ""
    board_type: str = "unknown"
    detectors_active: list = field(default_factory=list)
    regions: list = field(default_factory=list)
    verification_passed: bool = False
    quarantined: bool = False
    notes: str = ""


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------

def detect_pyzbar(img) -> list:
    """QR + 1D barcodes via zbar. Decoded content is proof the region is sensitive."""
    regions = []
    if not HAS_PYZBAR:
        return regions
    for sym in pyzbar.decode(img):
        x, y, w, h = sym.rect
        label = "qrcode" if sym.type == "QRCODE" else "barcode"
        regions.append(Region(label, "pyzbar", (x, y, x + w, y + h), 1.0, True))
    return regions


def detect_datamatrix(img, timeout_ms=3000) -> list:
    """DataMatrix codes (very common on PCBs) via libdmtx."""
    regions = []
    if not HAS_DMTX:
        return regions
    h = img.shape[0]
    for sym in pylibdmtx.decode(img, timeout=timeout_ms):
        x, y, w, hh = sym.rect
        # pylibdmtx uses a bottom-left origin
        regions.append(Region("datamatrix", "pylibdmtx",
                              (x, h - y - hh, x + w, h - y), 1.0, True))
    return regions


def detect_zxing(img) -> list:
    """QR + DataMatrix + 1-D barcodes via zxing-cpp (pip-only, no system libs).
    Decoded content is proof the region is sensitive."""
    regions = []
    if not HAS_ZXING:
        return regions
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    try:
        results = zxingcpp.read_barcodes(gray)
    except Exception:
        return regions
    for r in results:
        p = r.position
        xs = [p.top_left.x, p.top_right.x, p.bottom_left.x, p.bottom_right.x]
        ys = [p.top_left.y, p.top_right.y, p.bottom_left.y, p.bottom_right.y]
        fmt = str(r.format).lower()
        if "qr" in fmt:
            label = "qrcode"
        elif "matrix" in fmt or "aztec" in fmt:
            label = "datamatrix"
        else:
            label = "barcode"
        regions.append(Region(label, "zxing-cpp",
                              (int(min(xs)), int(min(ys)),
                               int(max(xs)), int(max(ys))), 1.0, True))
    return regions


def detect_cv_qr(img) -> list:
    """OpenCV multi-QR detector — catches QR codes zbar fails to decode."""
    regions = []
    det = cv2.QRCodeDetector()
    quads = []
    try:
        ok, points = det.detectMulti(img)
        if ok and points is not None:
            quads.extend(points)
    except Exception:
        pass
    try:
        # detectMulti is flaky on some images; the single-code detector often
        # succeeds where it fails, so always run both.
        ok, points = det.detect(img)
        if ok and points is not None:
            quads.extend(points)
    except Exception:
        pass
    for quad in quads:
        x1, y1 = quad.reshape(-1, 2).min(axis=0)
        x2, y2 = quad.reshape(-1, 2).max(axis=0)
        regions.append(Region("qrcode", "cv2.QRCodeDetector",
                              (int(x1), int(y1), int(x2), int(y2)), 0.9))
    return regions


def detect_cv_barcode(img) -> list:
    """OpenCV contrib 1-D barcode detector (detects even when undecodable)."""
    regions = []
    if not HAS_CV_BARCODE:
        return regions
    try:
        det = cv2.barcode.BarcodeDetector()
        ok, points = det.detectMulti(img)
        if ok and points is not None:
            for quad in points:
                x1, y1 = quad.min(axis=0)
                x2, y2 = quad.max(axis=0)
                regions.append(Region("barcode", "cv2.barcode",
                                      (int(x1), int(y1), int(x2), int(y2)), 0.8))
    except Exception:
        pass
    return regions


def detect_barcode_gradient(img) -> list:
    """Classical fallback for 1-D barcode stripes: strong horizontal gradient,
    weak vertical gradient, morphologically closed into bars. No ML, no deps."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=-1)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=-1)
    grad = cv2.convertScaleAbs(cv2.subtract(np.abs(gx), np.abs(gy)))
    grad = cv2.blur(grad, (9, 9))
    # Low threshold: over-masking is acceptable, missing a barcode is not.
    _, thresh = cv2.threshold(grad, 60, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (31, 9))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    closed = cv2.erode(closed, None, iterations=2)
    closed = cv2.dilate(closed, None, iterations=6)
    regions = []
    H, W = gray.shape[:2]
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        # A real 1-D barcode is a compact stripe block; reject blobs that span
        # a large fraction of the board (busy trace areas merged together) —
        # they black out most of the image instead of a label.
        if w > 0.55 * W or h > 0.45 * H:
            continue
        if w > 40 and h > 12 and w / max(h, 1) > 1.5:
            regions.append(Region("barcode", "gradient", (x, y, x + w, y + h), 0.5))
    return regions


def detect_white_labels(img, min_area=2500) -> list:
    """Bright label regions. On AOI images, barcodes/serials/QRs are usually
    printed on white adhesive labels — masking every bright label blob is a
    cheap, high-recall safety net (over-masking is acceptable)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)))
    regions = []
    H, W = gray.shape[:2]
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        if cv2.contourArea(c) < min_area:
            continue
        x, y, w, h = cv2.boundingRect(c)
        # An adhesive label is a small patch. A bright blob spanning a large
        # fraction of the frame is the photo background, a connector, or the
        # board itself — masking it would black out the whole image.
        if w * h > 0.25 * W * H:
            continue
        regions.append(Region("label", "white-label", (x, y, x + w, y + h), 0.6))
    return regions


class EastTextDetector:
    """EAST text detector (frozen_east_text_detection.pb, ~25 MB, offline).

    Download once from e.g. the OpenCV model zoo mirrors, place next to this
    script or point east_model_path in config.yaml at it.
    """

    def __init__(self, model_path: str, conf: float = 0.5):
        self.net = cv2.dnn.readNet(model_path)
        self.conf = conf

    def detect(self, img) -> list:
        H, W = img.shape[:2]
        newW, newH = (W // 32) * 32, (H // 32) * 32
        if newW == 0 or newH == 0:
            return []
        rW, rH = W / newW, H / newH
        blob = cv2.dnn.blobFromImage(img, 1.0, (newW, newH),
                                     (123.68, 116.78, 103.94), swapRB=True, crop=False)
        self.net.setInput(blob)
        scores, geometry = self.net.forward(
            ["feature_fusion/Conv_7/Sigmoid", "feature_fusion/concat_3"])
        regions = []
        rows, cols = scores.shape[2:4]
        for y in range(rows):
            sd = scores[0, 0, y]
            x0, x1, x2, x3 = (geometry[0, i, y] for i in range(4))
            ang = geometry[0, 4, y]
            for x in range(cols):
                if sd[x] < self.conf:
                    continue
                offX, offY = x * 4.0, y * 4.0
                cos, sin = np.cos(ang[x]), np.sin(ang[x])
                h = x0[x] + x2[x]
                w = x1[x] + x3[x]
                endX = int(offX + cos * x1[x] + sin * x2[x])
                endY = int(offY - sin * x1[x] + cos * x2[x])
                startX, startY = int(endX - w), int(endY - h)
                regions.append(Region("text", "east",
                                      (int(startX * rW), int(startY * rH),
                                       int(endX * rW), int(endY * rH)),
                                      float(sd[x])))
        return merge_overlapping(regions, iou_thresh=0.1)


class EasyOcrTextDetector:
    """EasyOCR (CRAFT) text detection; models cached locally after first use."""

    def __init__(self, langs=("en",)):
        self.reader = easyocr.Reader(list(langs), gpu=False, verbose=False)

    def detect(self, img) -> list:
        regions = []
        for quad, _txt, conf in self.reader.readtext(img):
            pts = np.array(quad)
            x1, y1 = pts.min(axis=0)
            x2, y2 = pts.max(axis=0)
            regions.append(Region("text", "easyocr",
                                  (int(x1), int(y1), int(x2), int(y2)),
                                  float(conf), decoded=True))
        return regions


def detect_logo_templates(img, template_dir: Path, threshold=0.75) -> list:
    """Multi-scale template matching against known logo crops in template_dir."""
    regions = []
    if not template_dir or not template_dir.is_dir():
        return regions
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    for tpath in sorted(template_dir.iterdir()):
        if tpath.suffix.lower() not in IMAGE_EXTS:
            continue
        tmpl = cv2.imread(str(tpath), cv2.IMREAD_GRAYSCALE)
        if tmpl is None:
            continue
        for scale in (0.5, 0.75, 1.0, 1.25, 1.5):
            th, tw = int(tmpl.shape[0] * scale), int(tmpl.shape[1] * scale)
            if th < 8 or tw < 8 or th >= gray.shape[0] or tw >= gray.shape[1]:
                continue
            res = cv2.matchTemplate(gray, cv2.resize(tmpl, (tw, th)),
                                    cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(res >= threshold)
            for (y, x) in zip(ys, xs):
                regions.append(Region("logo", f"template:{tpath.stem}",
                                      (int(x), int(y), int(x) + tw, int(y) + th),
                                      float(res[y, x])))
    return merge_overlapping(regions, iou_thresh=0.3)


def fixed_rois(board_cfg: dict) -> list:
    """Per-board-type fixed ROIs from config — the compliance backbone."""
    regions = []
    for roi in board_cfg.get("rois", []):
        x1, y1, x2, y2 = roi["bbox"]
        regions.append(Region(roi.get("label", "roi"), "config", (x1, y1, x2, y2)))
    return regions


# ---------------------------------------------------------------------------
# Geometry / masking helpers
# ---------------------------------------------------------------------------

def iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix = max(0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    if inter == 0:
        return 0.0
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union


def merge_overlapping(regions: list, iou_thresh=0.2) -> list:
    """Greedy union-merge of overlapping boxes with the same label."""
    merged = []
    for r in sorted(regions, key=lambda r: -r.confidence):
        placed = False
        for m in merged:
            if m.label == r.label and iou(m.bbox, r.bbox) > iou_thresh:
                x1 = min(m.bbox[0], r.bbox[0]); y1 = min(m.bbox[1], r.bbox[1])
                x2 = max(m.bbox[2], r.bbox[2]); y2 = max(m.bbox[3], r.bbox[3])
                m.bbox = (x1, y1, x2, y2)
                placed = True
                break
        if not placed:
            merged.append(Region(r.label, r.source, tuple(r.bbox),
                                 r.confidence, r.decoded))
    return merged


def apply_masks(img, regions: list, pad: int, style: str):
    """Irreversibly mask regions. Styles: fill | inpaint. (Blur deliberately
    not offered: partially reversible, weak compliance story.)"""
    out = img.copy()
    H, W = out.shape[:2]
    mask = np.zeros((H, W), np.uint8)
    for r in regions:
        x1 = max(0, int(r.bbox[0]) - pad); y1 = max(0, int(r.bbox[1]) - pad)
        x2 = min(W, int(r.bbox[2]) + pad); y2 = min(H, int(r.bbox[3]) + pad)
        mask[y1:y2, x1:x2] = 255
    if style == "inpaint":
        out = cv2.inpaint(out, mask, 7, cv2.INPAINT_TELEA)
    else:
        out[mask == 255] = 0
    return out, mask


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class PrivacyMasker:
    def __init__(self, config: dict):
        self.cfg = config
        self.pad = int(config.get("padding_px", 12))
        self.style = config.get("mask_style", "fill")
        self.text_detector = None

        east_path = config.get("east_model_path")
        if east_path and Path(east_path).is_file():
            self.text_detector = EastTextDetector(east_path,
                                                  config.get("text_conf", 0.5))
        elif HAS_EASYOCR and config.get("use_easyocr", True):
            self.text_detector = EasyOcrTextDetector()

        tdir = config.get("logo_template_dir")
        self.template_dir = Path(tdir) if tdir else None

    def active_detectors(self) -> list:
        active = ["cv2.QRCodeDetector", "gradient-barcode", "white-label", "config-roi"]
        if HAS_ZXING: active.append("zxing-cpp")
        if HAS_PYZBAR: active.append("pyzbar")
        if HAS_DMTX: active.append("pylibdmtx")
        if HAS_CV_BARCODE: active.append("cv2.barcode")
        if isinstance(self.text_detector, EastTextDetector): active.append("east")
        if isinstance(self.text_detector, EasyOcrTextDetector): active.append("easyocr")
        if self.template_dir: active.append("logo-template")
        return active

    def detect_all(self, img, board_type: str) -> list:
        regions = []
        regions += detect_zxing(img)
        regions += detect_pyzbar(img)
        regions += detect_datamatrix(img)
        regions += detect_cv_qr(img)
        regions += detect_cv_barcode(img)
        regions += detect_barcode_gradient(img)
        if self.cfg.get("mask_white_labels", True):
            regions += detect_white_labels(img)
        if self.text_detector:
            regions += self.text_detector.detect(img)
        regions += detect_logo_templates(img, self.template_dir,
                                         self.cfg.get("logo_threshold", 0.75))
        board_cfg = self.cfg.get("board_types", {}).get(board_type, {})
        regions += fixed_rois(board_cfg)
        return merge_overlapping(regions, iou_thresh=0.2)

    def verify(self, masked_img) -> bool:
        """Fail-closed verification: nothing sensitive may survive in the output."""
        if detect_zxing(masked_img):
            return False
        if detect_pyzbar(masked_img):
            return False
        if HAS_DMTX and detect_datamatrix(masked_img, timeout_ms=1500):
            return False
        try:
            data, _, _ = cv2.QRCodeDetector().detectAndDecode(masked_img)
            if data:
                return False
        except Exception:
            pass
        if isinstance(self.text_detector, EasyOcrTextDetector):
            leftover = [r for r in self.text_detector.detect(masked_img)
                        if r.confidence > 0.6]
            if leftover:
                return False
        return True

    def process(self, in_path: Path, out_dir: Path, board_type="unknown") -> AuditRecord:
        rec = AuditRecord(input_file=str(in_path),
                          input_sha256=sha256_file(in_path),
                          timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
                          board_type=board_type,
                          detectors_active=self.active_detectors())
        img = cv2.imread(str(in_path))
        if img is None:
            rec.quarantined = True
            rec.notes = "unreadable image"
            return rec

        regions = self.detect_all(img, board_type)
        rec.regions = [asdict(r) for r in regions]
        masked, _ = apply_masks(img, regions, self.pad, self.style)

        rec.verification_passed = self.verify(masked)
        if rec.verification_passed:
            out_path = out_dir / "masked" / in_path.name
            out_path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out_path), masked)
            rec.output_file = str(out_path)
            rec.output_sha256 = sha256_file(out_path)
        else:
            rec.quarantined = True
            rec.notes = "verification failed: sensitive content still detectable"
            qpath = out_dir / "quarantine" / in_path.name
            qpath.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(qpath), masked)
        return rec


def load_config(path) -> dict:
    if path and Path(path).is_file():
        if yaml is None:
            sys.exit("pyyaml not installed but --config given: pip install pyyaml")
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="input image or directory")
    ap.add_argument("-o", "--output", default="output", help="output directory")
    ap.add_argument("--config", default="config.yaml", help="YAML config file")
    ap.add_argument("--board-type", default="unknown",
                    help="board type key from config for fixed ROIs")
    args = ap.parse_args()

    cfg = load_config(args.config)
    masker = PrivacyMasker(cfg)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    in_path = Path(args.input)
    files = ([in_path] if in_path.is_file()
             else sorted(p for p in in_path.rglob("*")
                         if p.suffix.lower() in IMAGE_EXTS))
    if not files:
        sys.exit(f"no images found under {in_path}")

    print(f"pipeline v{PIPELINE_VERSION} | detectors: "
          f"{', '.join(masker.active_detectors())}")
    audits = []
    n_ok = n_q = 0
    for f in files:
        rec = masker.process(f, out_dir, args.board_type)
        audits.append(asdict(rec))
        status = "QUARANTINED" if rec.quarantined else "ok"
        n_q += rec.quarantined
        n_ok += not rec.quarantined
        print(f"  {f.name}: {len(rec.regions)} region(s) masked [{status}]")

    audit_path = out_dir / "audit_log.json"
    with open(audit_path, "w") as f:
        json.dump(audits, f, indent=2)
    print(f"\ndone: {n_ok} released, {n_q} quarantined | audit: {audit_path}")


if __name__ == "__main__":
    main()
