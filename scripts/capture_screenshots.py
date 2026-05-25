#!/usr/bin/env python3
"""Capture desktop screenshots of all Command Center v2 routes using Playwright."""
import os, time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:7777/v2"
OUT = "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/docs/ui_redesign/screenshots"

ROUTES = [
    "command", "agent-collaboration", "self-improvement", "ops", "pipeline",
    "system-health", "agent-pipeline", "governance", "trade-ai", "prospects",
    "alerts", "risk", "risk-regime", "recovery", "research",
    "topic-monitor", "ai-analyst", "technical", "watchlist", "cio",
    "paper-proposals", "paper-review", "paper-status", "automated-trade-mode",
    "incubator", "tax", "rebalance", "retirement", "reports",
    "journal", "journal?tab=reports", "journal?tab=analytics",
    "strategy-admin", "agent-calibration", "weekly-learning", "backtesting",
    "correlation", "forecast", "broker-reconciliation", "execution-quality",
    "plan-vs-performance", "proposal-alerts", "", "portfolio",
    "dividends", "returns", "attribution",
]

os.makedirs(OUT, exist_ok=True)
results = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1920, "height": 1080})

    for route in ROUTES:
        if route == "":
            fname = "overview_desktop.png"
            label = "overview"
        elif "?" in route:
            fname = route.replace("?tab=", "-").replace("/", "-") + "_desktop.png"
            label = route.replace("?tab=", "-")
        else:
            fname = route + "_desktop.png"
            label = route

        url = f"{BASE}/{route}" if route else f"{BASE}/"
        path = os.path.join(OUT, fname)

        try:
            page.goto(url, wait_until="networkidle", timeout=15000)
            time.sleep(1)
            page.screenshot(path=path, full_page=False)
            fsize = os.path.getsize(path)
            results.append((label, fname, "OK", fsize))
            print(f"OK: {label} -> {fname} ({fsize} bytes)")
        except Exception as e:
            results.append((label, fname, "FAIL", str(e)[:80]))
            print(f"FAIL: {label} -> {e}")

    browser.close()

ok = sum(1 for r in results if r[2] == "OK")
print(f"\nDone: {ok}/{len(results)} captured")
