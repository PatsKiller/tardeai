"""Redeploy workstation visual matrix — resolutions × browser zoom, with assertions.

Captures go to artifacts/playwright/redeploy/<run_id>/ per
docs/runbooks/PLAYWRIGHT_ARTIFACTS_POLICY.md (gitignored, Drive-excluded, 7-day retention).

Assertions per cell:
  - no horizontal document overflow (body never scrolls sideways)
  - page is not blank (rendered text > 200 chars)
Browser zoom Z% is emulated the way zoom actually works: CSS viewport = physical / Z.

Usage: .venv/bin/python scripts/redeploy_visual_matrix.py [--event 144]
Exit code 1 if any cell fails.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:7777/v3"
ROOT = Path(__file__).resolve().parent.parent

RESOLUTIONS = [(1440, 900), (1680, 1050), (1920, 1080), (2560, 1440)]
ZOOMS = [125, 150, 200]           # applied at 1680×1050
MATRIX_TABS = ["CAPITAL BOOK", "PLAN LAB", "PRO-FORMA", "PERFORMANCE"]
ZOOM_TABS = ["CAPITAL BOOK", "PLAN LAB"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", type=int, default=144)
    args = ap.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "artifacts" / "playwright" / "redeploy" / f"visual_matrix_{run_id}"
    out.mkdir(parents=True, exist_ok=True)

    cells = []
    for w, h in RESOLUTIONS:
        for tab in MATRIX_TABS:
            cells.append((w, h, 100, tab))
    for z in ZOOMS:
        for tab in ZOOM_TABS:
            cells.append((1680, 1050, z, tab))

    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for w, h, zoom, tab in cells:
            vw, vh = int(w * 100 / zoom), int(h * 100 / zoom)
            page = browser.new_page(viewport={"width": vw, "height": vh})
            name = f"{w}x{h}_z{zoom}_{re.sub(r'[^A-Za-z0-9]+', '_', tab).lower()}"
            try:
                url = f"{BASE}/redeploy?event={args.event}&tab={quote(tab)}"
                if tab == "CAPITAL BOOK":
                    url = f"{BASE}/redeploy"
                page.goto(url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(1500)
                overflow = page.evaluate(
                    "document.documentElement.scrollWidth - document.documentElement.clientWidth")
                text_len = page.evaluate("document.body.innerText.length")
                page.screenshot(path=str(out / f"{name}.png"), full_page=True)
                ok = overflow <= 2 and text_len > 200
                results.append({"cell": name, "ok": ok, "h_overflow_px": overflow, "text_chars": text_len})
                print(f"{'PASS' if ok else 'FAIL'} {name} overflow={overflow}px text={text_len}", flush=True)
            except Exception as e:
                results.append({"cell": name, "ok": False, "error": str(e)[:200]})
                print(f"FAIL {name} — {str(e)[:120]}", flush=True)
            finally:
                page.close()
        browser.close()

    n_fail = sum(1 for r in results if not r["ok"])
    lines = [f"<html><head><title>Redeploy visual matrix {run_id}</title></head><body>",
             f"<h1>Visual matrix — {run_id} · {len(results) - n_fail}/{len(results)} pass</h1><ul>"]
    for r in results:
        mark = "✅" if r["ok"] else "❌"
        detail = r.get("error") or f"overflow {r.get('h_overflow_px')}px · {r.get('text_chars')} chars"
        lines.append(f'<li>{mark} <a href="{r["cell"]}.png">{r["cell"]}</a> — {detail}</li>')
    lines.append("</ul></body></html>")
    (out / "index.html").write_text("\n".join(lines))
    print(f"\n{len(results) - n_fail}/{len(results)} pass → {out}", flush=True)
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
