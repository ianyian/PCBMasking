"""Gradio front end for the PCB privacy-masking pipeline (Hugging Face Space).

Upload a board photo -> ensemble detection -> irreversible black-fill mask
-> fail-closed verification. Shows detections, the masked result, and the
audit-style region table.
"""

import cv2
import numpy as np
import gradio as gr

# On ZeroGPU hardware HF requires at least one @spaces.GPU function; on
# CPU hardware the `spaces` package is absent and the decorator is a no-op.
try:
    import spaces
    gpu_task = spaces.GPU
except ImportError:
    def gpu_task(fn):
        return fn

from pcb_privacy_mask import PrivacyMasker, apply_masks

CONFIG = {
    "mask_style": "fill",
    "padding_px": 12,
    "logo_template_dir": "templates/logos",
    "logo_threshold": 0.75,
    "mask_white_labels": True,
    "use_easyocr": True,
}

print("initialising detectors (first run downloads EasyOCR models)…")
MASKER = PrivacyMasker(CONFIG)
print("active detectors:", ", ".join(MASKER.active_detectors()))

BOX_COLORS = {  # BGR
    "barcode": (38, 31, 216), "qrcode": (38, 31, 216), "datamatrix": (38, 31, 216),
    "text": (0, 200, 0), "label": (0, 165, 255), "logo": (255, 80, 160),
}


@gpu_task
def process(image):
    if image is None:
        return None, None, "Upload a board image first.", []
    bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    regions = MASKER.detect_all(bgr, "unknown")
    masked, _ = apply_masks(bgr, regions, MASKER.pad, MASKER.style)
    released = MASKER.verify(masked)

    overlay = bgr.copy()
    for r in regions:
        x1, y1, x2, y2 = map(int, r.bbox)
        col = BOX_COLORS.get(r.label, (255, 255, 255))
        cv2.rectangle(overlay, (x1, y1), (x2, y2), col, 4)
        cv2.putText(overlay, r.label, (x1, max(18, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)

    verdict = (
        f"✅ RELEASED — {len(regions)} region(s) masked; verification re-scan "
        f"found nothing still decodable."
        if released else
        f"🚫 QUARANTINED — {len(regions)} region(s) masked but the verification "
        f"re-scan still detects sensitive content. Do NOT use this output."
    )
    table = [[r.label, r.source, str(tuple(map(int, r.bbox))),
              f"{r.confidence:.2f}", "yes" if r.decoded else "no"]
             for r in regions]
    return (cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB),
            cv2.cvtColor(masked, cv2.COLOR_BGR2RGB),
            verdict, table)


with gr.Blocks(title="PCB Privacy Masking") as demo:
    gr.Markdown(
        "# 🛡️ PCB Privacy Masking\n"
        "Detects and irreversibly masks **barcodes, QR/DataMatrix codes, "
        "serial text, labels and customer logos** on PCB/AOI images. "
        "A fail-closed verification pass re-scans the output before release.")
    with gr.Row():
        inp = gr.Image(label="Board image", type="numpy")
        det = gr.Image(label="Detections", type="numpy")
        out = gr.Image(label="Masked output", type="numpy")
    verdict = gr.Textbox(label="Verification result", interactive=False)
    table = gr.Dataframe(
        headers=["type", "detector", "bbox (x1, y1, x2, y2)", "confidence",
                 "decoded"],
        label="Detected regions (audit view)", interactive=False)
    gr.Button("Detect & Mask", variant="primary").click(
        process, inputs=inp, outputs=[det, out, verdict, table])

if __name__ == "__main__":
    demo.launch()
