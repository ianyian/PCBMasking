---
title: PCB Privacy Masking Console
emoji: 🛡️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# PCB Privacy Masking — live upload console

Operator-style console (same design as the on-prem demo): upload PCB / AOI
board photos into the top preview bar; each board runs through the 4-step
flow — load → sensitive-object detection → irreversible masking → release
verification — with an action log, per-board report cards and a last-hour
yield + object Pareto chart.

Detection is the real offline ensemble (zxing-cpp, pyzbar, pylibdmtx,
OpenCV, EasyOCR, logo template matching) from `pcb_privacy_mask.py`.
The fail-closed verification pass re-scans the masked output; anything
still decodable marks the board **QUARANTINED**.

Defect detection (step 4 model) is not enabled in this deployment yet —
the panel currently shows the release-verification result.

Source: <https://github.com/ianyian/PCBMasking>
