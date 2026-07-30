"""FastAPI backend for the PCB privacy-masking upload console.

Serves the operator-style front end (static/) and one API endpoint that
runs the real detection ensemble on an uploaded board image.
"""

import time
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, UploadFile
from fastapi.staticfiles import StaticFiles

from pcb_privacy_mask import PrivacyMasker, apply_masks

CONFIG = {
    "mask_style": "fill",
    "padding_px": 12,
    "logo_template_dir": str(Path(__file__).parent / "templates" / "logos"),
    "logo_threshold": 0.75,
    "mask_white_labels": True,
    "use_easyocr": True,
}

print("initialising detectors (first run downloads EasyOCR models)…")
MASKER = PrivacyMasker(CONFIG)
print("active detectors:", ", ".join(MASKER.active_detectors()))

app = FastAPI(title="PCB Privacy Masking")


@app.post("/api/process")
async def process(file: UploadFile):
    data = await file.read()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return {"error": "could not decode the uploaded image"}

    t0 = time.perf_counter()
    regions = MASKER.detect_all(img, "unknown")
    detect_ms = (time.perf_counter() - t0) * 1000

    t1 = time.perf_counter()
    masked, _ = apply_masks(img, regions, MASKER.pad, MASKER.style)
    mask_ms = (time.perf_counter() - t1) * 1000

    t2 = time.perf_counter()
    verified = MASKER.verify(masked)
    verify_ms = (time.perf_counter() - t2) * 1000

    return {
        "width": int(img.shape[1]),
        "height": int(img.shape[0]),
        "regions": [
            {"label": r.label, "source": r.source,
             "bbox": [int(v) for v in r.bbox],
             "confidence": round(float(r.confidence), 2),
             "decoded": bool(r.decoded)}
            for r in regions
        ],
        "verified": bool(verified),
        "detect_ms": round(detect_ms, 1),
        "mask_ms": round(mask_ms, 1),
        "verify_ms": round(verify_ms, 1),
        "detectors": MASKER.active_detectors(),
        "pad": MASKER.pad,
    }


app.mount("/", StaticFiles(directory=str(Path(__file__).parent / "static"),
                           html=True), name="static")
