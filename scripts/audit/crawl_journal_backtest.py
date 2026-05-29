"""
Targeted Playwright crawl: all Journal and Backtesting pages + tabs.
Captures full-page PNGs and uploads tarball to Drive.
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = "http://localhost:7777"
VIEWPORT = {"width": 1440, "height": 900}
WAIT_MS = 2000

# All pages and tabs to capture
TARGETS = [
    # Journal Hub tabs
    {"url": "/v2/journal", "name": "journal_entries", "label": "Journal — Entries"},
    {"url": "/v2/journal?tab=analytics", "name": "journal_analytics", "label": "Journal — Analytics"},
    {"url": "/v2/journal?tab=reports", "name": "journal_reports_tab", "label": "Journal — Reports"},
    {"url": "/v2/journal?tab=automated", "name": "journal_automated", "label": "Journal — Automated"},
    # Journal Reports standalone page
    {"url": "/v2/journal-reports", "name": "journal_reports_page", "label": "Journal Reports (standalone)"},
    # Backtesting tabs
    {"url": "/v2/backtesting", "name": "backtesting_overview", "label": "Backtesting — Overview"},
]

# Backtesting tabs that need clicking (URL doesn't change for tab switches)
BACKTEST_TABS = [
    ("strategy", "backtesting_strategy", "Backtesting — Strategy"),
    ("trades", "backtesting_trades", "Backtesting — Trades"),
    ("missed", "backtesting_missed", "Backtesting — Missed"),
    ("results", "backtesting_results", "Backtesting — Results"),
    ("runs", "backtesting_runs", "Backtesting — Runs"),
    ("trailing", "backtesting_trailing", "Backtesting — Trail Analysis"),
    ("mfe", "backtesting_mfe", "Backtesting — MFE/MAE"),
    ("optimization", "backtesting_optimization", "Backtesting — Optimization"),
    ("llm_reviews", "backtesting_llm_reviews", "Backtesting — LLM Reviews"),
]


def capture(page, url, name, label, out_dir):
    print(f"  {label} ...", end=" ", flush=True)
    start = time.time()
    try:
        page.goto(BASE + url, wait_until="domcontentloaded", timeout=20000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PWTimeout:
            pass
        page.wait_for_timeout(WAIT_MS)
        page.screenshot(path=str(out_dir / f"{name}.png"), full_page=True, timeout=15000)
        elapsed = int((time.time() - start) * 1000)
        print(f"OK ({elapsed}ms)")
        return {"name": name, "label": label, "status": "ok", "elapsed_ms": elapsed}
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        print(f"FAIL: {e}")
        return {"name": name, "label": label, "status": "error", "elapsed_ms": elapsed, "error": str(e)[:200]}


def capture_tab(page, tab_text, name, label, out_dir):
    """Click a tab button by its text content and screenshot."""
    print(f"  {label} ...", end=" ", flush=True)
    start = time.time()
    try:
        # Find and click the tab button
        tabs = page.query_selector_all("button")
        clicked = False
        for btn in tabs:
            txt = (btn.inner_text() or "").strip()
            if txt.lower().replace("/", "").replace(" ", "") == tab_text.lower().replace("_", "").replace(" ", ""):
                btn.click()
                clicked = True
                break
        if not clicked:
            # Try broader match
            for btn in tabs:
                txt = (btn.inner_text() or "").strip().lower()
                if tab_text.lower().replace("_", " ") in txt or tab_text.lower().replace("_", "") in txt.replace(" ", "").replace("/", ""):
                    btn.click()
                    clicked = True
                    break
        if not clicked:
            raise RuntimeError(f"Tab button '{tab_text}' not found")

        try:
            page.wait_for_load_state("networkidle", timeout=6000)
        except PWTimeout:
            pass
        page.wait_for_timeout(WAIT_MS)
        page.screenshot(path=str(out_dir / f"{name}.png"), full_page=True, timeout=15000)
        elapsed = int((time.time() - start) * 1000)
        print(f"OK ({elapsed}ms)")
        return {"name": name, "label": label, "status": "ok", "elapsed_ms": elapsed}
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        print(f"FAIL: {e}")
        return {"name": name, "label": label, "status": "error", "elapsed_ms": elapsed, "error": str(e)[:200]}


# Tab text mapping for backtesting buttons
TAB_BUTTON_TEXT = {
    "strategy": "Strategy",
    "trades": "Trades",
    "missed": "Missed",
    "results": "Results",
    "runs": "Runs",
    "trailing": "Trail Analysis",
    "mfe": "MFE/MAE",
    "optimization": "Optimization",
    "llm_reviews": "LLM Reviews",
}


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = Path(f"/tmp/playwright_journal_backtest_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport=VIEWPORT, ignore_https_errors=True)
        page = ctx.new_page()

        print(f"\n=== Journal & Backtesting Playwright Crawl ===")
        print(f"Output: {out_dir}\n")

        # Journal pages
        print("--- Journal ---")
        for t in TARGETS[:5]:
            r = capture(page, t["url"], t["name"], t["label"], out_dir)
            results.append(r)

        # Backtesting overview (navigate first)
        print("\n--- Backtesting ---")
        r = capture(page, "/v2/backtesting", "backtesting_overview", "Backtesting — Overview", out_dir)
        results.append(r)

        # Backtesting tabs (click through)
        for tab_id, name, label in BACKTEST_TABS:
            btn_text = TAB_BUTTON_TEXT.get(tab_id, tab_id)
            r = capture_tab(page, btn_text, name, label, out_dir)
            results.append(r)

        ctx.close()
        browser.close()

    # Write summary
    summary = {"timestamp": ts, "total": len(results),
               "ok": sum(1 for r in results if r["status"] == "ok"),
               "errors": sum(1 for r in results if r["status"] != "ok"),
               "results": results}
    (out_dir / "crawl_summary.json").write_text(json.dumps(summary, indent=2))

    # Create tarball
    import tarfile
    tgz = f"/tmp/playwright_journal_backtest_{ts}.tgz"
    with tarfile.open(tgz, "w:gz") as tar:
        tar.add(str(out_dir), arcname=f"journal_backtest_{ts}")
    print(f"\n=== Done: {summary['ok']}/{summary['total']} OK ===")
    print(f"Tarball: {tgz}")

    # Print summary
    for r in results:
        status = "OK" if r["status"] == "ok" else f"FAIL: {r.get('error', '')[:60]}"
        print(f"  {r['label']:40s} {status}")

    return tgz


if __name__ == "__main__":
    tgz_path = main()
    print(f"\nTarball ready: {tgz_path}")
