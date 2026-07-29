#!/usr/bin/env python3
"""Build the static GitHub Pages version of the demo into /docs.

GitHub Pages only serves from the repo root or /docs, and runs no Python,
so this script adapts the demo front end to plain static hosting:
  * Flask endpoints (/api/boards, /api/board/<sn>) are replaced by one
    fetch of dataset/annotations.json,
  * image URLs become relative paths,
  * demo/dataset/ is copied to docs/dataset/.

Re-run after changing the demo front end or dataset:
    python demo/build_static_site.py
then commit /docs. Enable in repo settings: Pages -> deploy from branch,
main + /docs.
"""

import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEMO = REPO / "demo"
DOCS = REPO / "docs"


def build_js() -> str:
    js = (DEMO / "static/app.js").read_text()

    old_fetch = '''async function fetchBoardsWithRetry() {
  // kiosk autostart can open the browser before the server is up — keep trying
  for (;;) {
    try {
      const r = await fetch("/api/boards");
      if (r.ok) {
        const res = await r.json();
        if (res.boards && res.boards.length) return res.boards;
        $("statusMsg").textContent =
          "Dataset is empty — run `python demo/generate_dataset.py`, then reload";
      }
    } catch (err) {
      $("statusMsg").textContent = "Waiting for demo server…";
    }
    await sleep(2000);
  }
}'''
    new_fetch = '''let ANN = null;  // static hosting: whole ground truth in one file

async function fetchBoardsWithRetry() {
  for (;;) {
    try {
      const r = await fetch("dataset/annotations.json");
      if (r.ok) {
        ANN = await r.json();
        const b = Object.keys(ANN).sort();
        if (b.length) return b;
        $("statusMsg").textContent = "Dataset is empty — rebuild /docs";
      }
    } catch (err) {
      $("statusMsg").textContent = "Loading dataset…";
    }
    await sleep(2000);
  }
}'''
    assert old_fetch in js
    js = js.replace(old_fetch, new_fetch)

    old_board = '''  const [ann, img] = await Promise.all([
    fetch(`/api/board/${sn}`).then((r) => r.json()),
    loadImage(`/dataset/raw/${sn}.png`),
  ]);'''
    new_board = '''  const ann = ANN[sn];
  const img = await loadImage(`dataset/raw/${sn}.png`);'''
    assert old_board in js
    js = js.replace(old_board, new_board)

    old_chip = '`<img src="/dataset/raw/${sn}.png" alt="${sn}" loading="lazy">`'
    new_chip = '`<img src="dataset/raw/${sn}.png" alt="${sn}" loading="lazy">`'
    assert old_chip in js
    js = js.replace(old_chip, new_chip)

    assert "/api/" not in js and "/dataset/raw" not in js
    return js


def build_html() -> str:
    html = (DEMO / "templates/index.html").read_text()
    html = html.replace(
        """{{ url_for('static', filename='style.css') }}""", "style.css")
    html = html.replace(
        """{{ url_for('static', filename='app.js') }}""", "app.js")
    assert "url_for" not in html
    return html


def main():
    if DOCS.exists():
        shutil.rmtree(DOCS)
    DOCS.mkdir()
    (DOCS / "index.html").write_text(build_html())
    (DOCS / "app.js").write_text(build_js())
    shutil.copy(DEMO / "static/style.css", DOCS / "style.css")
    shutil.copytree(DEMO / "dataset", DOCS / "dataset")
    n = len(list((DOCS / "dataset/raw").glob("*.png")))
    print(f"built docs/ with {n} boards — enable Pages: main + /docs")


if __name__ == "__main__":
    main()
