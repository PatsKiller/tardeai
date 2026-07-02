#!/usr/bin/env python3
"""Capture Command Center v3 Proposals + Entry Desk (Manual ToS) for layout comparison."""
from __future__ import annotations

import os
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get("CC_V3_BASE", "http://127.0.0.1:7777")


def capture(page, url: str, out_dir: Path, prefix: str, card_selector: str) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    try:
        page.wait_for_selector(card_selector, timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(6000)

    page.screenshot(path=str(out_dir / f"{prefix}_full.png"), full_page=True)
    page.screenshot(path=str(out_dir / f"{prefix}_viewport.png"), full_page=False)

    cards = page.locator(card_selector)
    n = cards.count()
    print(f"  {prefix}: {n} card(s)")
    for i in range(min(n, 3)):
        try:
            cards.nth(i).screenshot(path=str(out_dir / f"{prefix}_card_{i}.png"))
        except Exception as e:
            print(f"    card {i} skip: {e}")
    return n


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Install: .venv/bin/python -m playwright install chromium")
        return 2

    proposals_out = ROOT / "docs" / "ui_review" / "proposals_desk"
    tos_out = ROOT / "docs" / "ui_review" / "entry_desk"

    proposals_url = f"{BASE.rstrip('/')}/v3/trading?tab=Proposals"
    tos_tab = urllib.parse.quote("Entry Desk")
    tos_url = f"{BASE.rstrip('/')}/v3/trading?tab={tos_tab}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1200})

        print("Proposals desk")
        capture(page, proposals_url, proposals_out, "proposals", "article")

        print("Entry desk (Manual ToS)")
        capture(page, tos_url, tos_out, "entry_desk", '[data-testid="entry-desk-row"]')

        browser.close()

    print(f"Saved proposals → {proposals_out}")
    print(f"Saved entry desk → {tos_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())