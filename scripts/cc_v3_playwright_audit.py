#!/usr/bin/env python3
"""Playwright smoke audit — every CC v3 nav route + hub tabs."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BASE = "http://127.0.0.1:7777/v3"

NAV_ROUTES = [
    ("/", "Home"),
    ("/portfolio", "Portfolio"),
    ("/risk", "Risk"),
    ("/trading", "Trading"),
    ("/strategy", "Strategy"),
    ("/agents", "Agents"),
    ("/intelligence", "Intelligence"),
    ("/hermes", "Hermes"),
    ("/retirement", "Retirement"),
    ("/journal", "TradeInView"),
    ("/watch", "Watch"),
    ("/watchlist", "Watchlist (redirect)"),
    ("/watchpool", "Watchpool (redirect)"),
    ("/reports", "Reports"),
    ("/rotation", "Rotation"),
    ("/rec-intel", "Rec Intelligence"),
    ("/advisor-changes", "Advisor Changes"),
    ("/health", "Health"),
    ("/system", "System"),
    ("/manual-execution", "Manual Execution (orphan route)"),
]

HUB_TABS: dict[str, list[str]] = {
    "/": [],
    "/watch": ["Watchlist", "Watchpool", "Sectors", "Pullback/MACD"],
    "/portfolio": ["Holdings", "Look-through", "Returns", "Dividends", "Forecast", "Tax", "Redeploy", "Stop Management"],
    "/risk": ["Exposure", "Correlation", "Regime", "Recovery"],
    "/trading": [
        "Trade AI", "Options", "Open Trades", "Proposals", "Entry Desk", "Execution",
        "Broker Recon", "Scalp", "ATM Controls", "Broker Orders", "Schwab Accounts",
    ],
    "/strategy": ["Leaderboard", "Analytics", "Planner", "Desk", "Incubator", "Plan vs Perf"],
    "/agents": ["Roster", "Calibration", "Workflow", "Performance", "Weekly Learning"],
    "/intelligence": [
        "Command Center", "Inferences", "Signal Quality", "News", "Research", "Sources", "Workflow",
    ],
    "/hermes": ["Overview", "Workflow", "Maturity", "Provenance", "Sources", "Research", "Dual Opinion", "Pipeline"],
    "/retirement": ["Overview", "Accounts", "Timeline", "Planning Research"],
    "/journal": [
        "Trades", "Tagging Queue", "Analytics", "Exit Intel", "Behavioral", "Session", "Advanced",
        "Lessons", "Protection", "Backtesting", "Real Accounts", "Import",
    ],
    "/health": ["Overview", "Coders", "History"],
    "/system": [
        "Pipeline", "Control Plane", "Data Sources", "Queue", "SIEM", "Jobs", "Apps", "Access",
        "Admin", "Brokers", "Crons", "LLM", "Hermes", "OpenClaw", "TradeAI",
    ],
}


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed — run: pip install playwright && playwright install chromium")
        return 2

    out_path = Path(__file__).resolve().parent.parent / "data" / "runtime" / "cc_v3_playwright_audit.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    with sync_playwright() as p:
        # Chromium unsupported on some hosts (e.g. Ubuntu 26) — prefer Firefox.
        try:
            browser = p.firefox.launch(headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        console_errors: list[str] = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda err: console_errors.append(f"PAGEERROR: {err}"))

        for route, label in NAV_ROUTES:
            console_errors.clear()
            url = BASE + route
            row = {"route": route, "label": label, "url": url, "tabs": [], "ok": True, "issues": []}
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1200)
                row["status"] = resp.status if resp else 0
                if not resp or resp.status >= 400:
                    row["ok"] = False
                    row["issues"].append(f"HTTP {row['status']}")
                body = page.inner_text("main.app-main") if page.locator("main.app-main").count() else page.inner_text("body")
                if len(body.strip()) < 80:
                    row["ok"] = False
                    row["issues"].append("main content very short — possible blank page")
                if "Reconnecting to backend" in page.inner_text("body"):
                    row["issues"].append("degraded connection bar visible")
                title_h = page.locator("main.app-main").inner_text()[:200] if page.locator("main.app-main").count() else ""
                row["headline_sample"] = title_h.split("\n")[0][:80]

                for tab in HUB_TABS.get(route, []):
                    tab_row = {"tab": tab, "ok": True, "issues": []}
                    try:
                        btn = page.get_by_role("button", name=tab, exact=True)
                        if btn.count() == 0:
                            tab_row["ok"] = False
                            tab_row["issues"].append("tab button not found")
                        else:
                            btn.first.click(timeout=5000)
                            page.wait_for_timeout(900)
                            tab_text = page.locator("main.app-main").inner_text() if page.locator("main.app-main").count() else ""
                            if len(tab_text.strip()) < 60:
                                tab_row["ok"] = False
                                tab_row["issues"].append("tab content very short")
                            if any(x in tab_text.lower() for x in ("loading...", "loading ", "request failed", "unavailable")):
                                tab_row["issues"].append("loading/error copy visible")
                    except Exception as e:
                        tab_row["ok"] = False
                        tab_row["issues"].append(str(e)[:120])
                    if tab_row["issues"]:
                        row["issues"].extend([f"{tab}: {i}" for i in tab_row["issues"]])
                    if not tab_row["ok"]:
                        row["ok"] = False
                    row["tabs"].append(tab_row)

                if console_errors:
                    row["issues"].extend([f"console: {e[:100]}" for e in console_errors[:3]])
            except Exception as e:
                row["ok"] = False
                row["issues"].append(str(e)[:160])
            results.append(row)
            print(("OK " if row["ok"] else "FAIL") + f" {label} ({route})" + (f" — {row['issues'][0]}" if row.get("issues") else ""))

        browser.close()

    fail = [r for r in results if not r["ok"]]
    summary = {
        "audited_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "routes": len(results),
        "failed_routes": len(fail),
        "results": results,
    }
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nWrote {out_path}")
    print(f"Routes: {len(results)} OK-ish: {len(results)-len(fail)} FAIL: {len(fail)}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())