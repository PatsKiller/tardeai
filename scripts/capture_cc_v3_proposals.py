#!/usr/bin/env python3
"""Capture Command Center v3 Proposals desk for visual redesign review."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "ui_review" / "proposals_desk"
BASE = os.environ.get("CC_V3_BASE", "http://127.0.0.1:7777")


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Install: .venv/bin/python -m playwright install chromium")
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    url = f"{BASE.rstrip('/')}/v3/trading?tab=Proposals"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1200})
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        # Wait for broker cards or queue header
        try:
            page.wait_for_selector("article", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(8000)

        page.screenshot(path=str(OUT / "proposals_full.png"), full_page=True)
        page.screenshot(path=str(OUT / "proposals_viewport.png"), full_page=False)

        cards = page.locator("article")
        n = cards.count()
        print(f"Captured {n} proposal card(s)")
        for i in range(min(n, 4)):
            try:
                cards.nth(i).screenshot(path=str(OUT / f"card_{i}.png"))
            except Exception as e:
                print(f"  card {i} skip: {e}")

        browser.close()

    print(f"Saved to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())