#!/usr/bin/env python3
"""Playwright screenshot pass — captures every page and sub-tab in Command Center v3."""
from playwright.sync_api import sync_playwright
import os, sys, time

BASE_URL = "http://127.0.0.1:7777/v3"
OUT_DIR = os.path.expanduser("~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/docs/screenshots_2026-08-02")
os.makedirs(OUT_DIR, exist_ok=True)

# ── All routes with sub-tabs to expand ──
ROUTES = [
    # page, tabs to click (empty = just capture default)
    ("home", []),
    ("portfolio", ["Overview", "Re-Entry", "Risk", "Trading", "Active Trader", "Strategy",
                    "TradeInView", "Watch", "Defense"]),
    ("portfolio/re-entry", []),
    ("risk", ["Overview", "Holding Risk", "Portfolio Risk", "Systemic"]),
    ("trading", ["Proposals", "Broker", "Trade Log", "Stop Management", "Options Desk",
                  "Strategy Planner", "Trade Review", "Execution", "Paper", "Live Adjacent", "Audit"]),
    ("active-trader", ["Dashboard", "Signals", "Positions"]),
    ("strategy", ["Overview", "Regime", "Setups", "Entry", "Exit", "Rotation Watch"]),
    ("watch", ["Watchlist", "CIO Synthesis", "Entry Planner", "Indicators", "Maria Priority"]),
    ("defense", []),
    ("intel", ["Intel Hub", "Directives", "Research Queue", "Catalysts", "News Dashboard",
               "Macro", "Social Sentiment"]),
    ("research-intel", []),
    ("intelligence", []),
    ("hermes", ["Dashboard", "Coverage", "External Research", "Signal Aggregator",
                "Analyst", "Reports", "Agent Dashboard", "CIO", "Scalp", "Post-Trade", "Quality"]),
    ("reports", ["Weekly", "Monthly", "Quarterly", "Yearly", "Custom"]),
    ("rotation", ["Rotation Queue", "Oversight"]),
    ("retirement", ["Dashboard", "Holdings", "Allocation", "Withdrawals"]),
    ("health", ["Overview", "Coders", "History"]),
    ("consumption", []),
    ("system", ["Overview", "Agents", "Cron", "DB", "Processes", "Health Probes",
                "Metrics", "Data Feeds", "LLM Health", "OAuth", "Scheduler",
                "Watchdog", "Pipelines", "Environment", "Deploy"]),
    ("journal", ["Overview", "Trades", "P&L", "Reviews", "Insights", "Search",
                 "Ask AI", "Export", "Settings", "Import", "Drafts", "Sentiment",
                 "Weekly", "Monthly"]),
    ("agents", ["Agents", "Create Agent", "Redeploy", "Config"]),
    ("redeploy", ["Plan", "Deploy", "Rollback", "Pipelines", "Settings",
                  "Secrets", "DNS", "SSL", "Backups", "Monitoring",
                  "Logs", "Health", "API Keys"]),
    ("rec-intel", []),
    ("ops", ["Overview", "Data", "Pipelines", "Health", "System"]),
]

def screenshot(page, name):
    path = os.path.join(OUT_DIR, f"{name}.png")
    try:
        page.screenshot(path=path, full_page=True)
        print(f"  ✓ {name}")
        return True
    except Exception as e:
        print(f"  ✗ {name}: {e}")
        return False

def main():
    print("Launching Playwright…")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path="/tmp/cursor-sandbox-cache/b15bb43ba10eb38d1e5d7001d169057a/playwright/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell",
        )
        context = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page = context.new_page()

        total = 0
        passed = 0

        for route, tabs in ROUTES:
            url = f"{BASE_URL}/{route}" if route != "home" else f"{BASE_URL}/"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(2000)  # let React hydrate
            except Exception as e:
                print(f"  ✗ {route} - navigation failed: {e}")
                continue

            # Screenshot default view
            if screenshot(page, f"{route.replace('/', '_')}_default"):
                passed += 1
            total += 1

            # Click each tab
            for tab in tabs:
                try:
                    # Try to find and click the tab button/span
                    elem = page.locator(f"button:has-text('{tab}'), [role='tab']:has-text('{tab}'), span:has-text('{tab}')").first
                    if elem.is_visible(timeout=2000):
                        elem.click()
                        page.wait_for_timeout(1500)
                except Exception:
                    pass

                tab_safe = tab.lower().replace(" ", "_").replace("/", "_")
                name = f"{route.replace('/', '_')}__{tab_safe}"
                if screenshot(page, name):
                    passed += 1
                total += 1

        browser.close()

    print(f"\n{'='*60}")
    print(f"Done. {passed}/{total} screenshots passed.")
    print(f"Output: {OUT_DIR}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
