#!/usr/bin/env python3
"""PCB inspection live-show demo server.

Serves a single-page, self-running demo that cycles through the synthetic
dataset produced by demo/generate_dataset.py:

    Step 1  Inspection        - load raw board image, SN + start timestamp
    Step 2  Object detection  - red boxes on sensitive items (blink 3x)
    Step 3  Object masking    - detected areas filled black (blink 3x)
    Step 4  Defect detection  - yellow marks on defects (blink 3x)

Run:
    python demo/generate_dataset.py     # once, to build the dataset
    python demo/app.py [--port 8000]
then open http://localhost:8000 (full-screen it on the big display).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, send_from_directory

BASE = Path(__file__).resolve().parent
DATASET = BASE / "dataset"
RAW = DATASET / "raw"

app = Flask(__name__)


def load_annotations() -> dict:
    path = DATASET / "annotations.json"
    if not path.is_file():
        raise SystemExit(
            "dataset not found - run `python demo/generate_dataset.py` first")
    with open(path) as f:
        return json.load(f)


ANNOTATIONS = load_annotations()
BOARD_ORDER = sorted(ANNOTATIONS.keys())


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/boards")
def boards():
    """Ordered board queue for the top preview bar."""
    return jsonify({"boards": BOARD_ORDER})


@app.route("/api/board/<sn>")
def board(sn: str):
    """Ground-truth detection + defect data for one board."""
    ann = ANNOTATIONS.get(sn)
    if ann is None:
        abort(404)
    return jsonify(ann)


@app.route("/dataset/raw/<path:name>")
def raw_image(name: str):
    return send_from_directory(RAW, name)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    print(f"PCB inspection demo: {len(BOARD_ORDER)} boards loaded")
    print(f"open http://localhost:{args.port} and press F11 for full screen")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
