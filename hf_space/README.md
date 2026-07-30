---
title: PCB Privacy Masking
emoji: 🛡️
colorFrom: blue
colorTo: green
sdk: gradio
app_file: app.py
pinned: false
---

# PCB Privacy Masking

Upload a PCB / AOI board photo and the pipeline detects and irreversibly
masks sensitive regions before the image is used for ML training:

- **Barcodes / QR / DataMatrix** — zxing-cpp, pyzbar, pylibdmtx and OpenCV
  detectors, cross-checked and merged
- **Printed text** (serials, lot codes) — EasyOCR
- **White adhesive labels** — classical high-recall safety net
- **Customer logos** — template matching against a preset logo library

A fail-closed verification pass re-scans the masked output: if anything is
still decodable the image is marked **QUARANTINED** instead of released.

Source: <https://github.com/ianyian/PCBMasking>
