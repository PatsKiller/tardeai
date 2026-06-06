"""
Targeted Playwright crawl of the v3 Journal hub (/v3/journal) — every tab,
sub-tab, and a representative drill-down. Captures full-page PNGs + console
errors, then compiles a single tarball under docs/playwright/ (picked up by the
docs→Drive sync).

v3 is a BrowserRouter SPA; the Journal hub tabs and the embedded Backtesting
panel sub-tabs switch via click (no URL change), so we click buttons by text.
"""
import json
import time
import tarfile
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = "http://localhost:7777"
ROUTE = "/v3/journal"
VIEWPORT = {"width": 1600, "height": 1000}
WAIT_MS = 2500
OUT_ROOT = Path(__file__).resolve().parents[2] / "docs" / "playwright"

# Top-level Journal hub tabs (exact button text)
JOURNAL_TABS = ["Trades", "Analytics", "Lessons", "Protection", "Backtesting"]

# Embedded Backtesting panel sub-tabs — match by label PREFIX (labels carry
# dynamic counts, e.g. "Trades (123)"). Order mirrors BacktestPanel.tsx.
BACKTEST_TABS = [
    ("Overview", "overview"),
    ("Entry Quality", "entry_quality"),
    ("AI Trade Eval", "ai_trade_eval"),
    ("Capture", "capture"),
    ("Potential Over Time", "potential"),
    ("Strategy", "strategy"),
    ("Trades", "trades"),
    ("Missed", "missed"),
    ("Results", "results"),
    ("Runs", "runs"),
    ("Trail Analysis", "trailing"),
    ("MFE/MAE", "mfe"),
    ("Optimization", "optimization"),
    ("LLM Review Coverage", "llm_reviews"),
]


def _norm(s):
    return (s or "").strip()


def click_button_by_text(page, target, exact=True, exclude_exact=None):
    """Click the first <button> whose text matches. Returns the matched label."""
    exclude_exact = set(exclude_exact or [])
    for btn in page.query_selector_all("button"):
        txt = _norm(btn.inner_text())
        if not txt or txt in exclude_exact:
            continue
        hit = (txt == target) if exact else txt.startswith(target)
        if hit:
            btn.scroll_into_view_if_needed(timeout=4000)
            btn.click()
            return txt
    raise RuntimeError(f"button not found: {target!r} (exact={exact})")


def settle(page):
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except PWTimeout:
        pass
    page.wait_for_timeout(WAIT_MS)


def shoot(page, out_dir, idx, name, label, console_errors):
    fn = f"{idx:02d}_{name}.png"
    start = time.time()
    before = len(console_errors)
    page.screenshot(path=str(out_dir / fn), full_page=True, timeout=20000)
    ms = int((time.time() - start) * 1000)
    err = len(console_errors) - before
    print(f"  [{idx:02d}] {label:34s} -> {fn}  ({ms}ms, {err} new console err)")
    return {"idx": idx, "file": fn, "label": label, "status": "ok",
            "console_errors_during": err}


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    run_name = f"journal_audit_{ts}"
    out_dir = OUT_ROOT / f"_tmp_{run_name}" / run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport=VIEWPORT, ignore_https_errors=True)
        page = ctx.new_page()
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

        print(f"\n=== v3 Journal Crawl → {out_dir} ===")
        page.goto(BASE + ROUTE, wait_until="domcontentloaded", timeout=25000)
        # wait for the SPA tab bar to render
        try:
            page.wait_for_selector("button", timeout=15000)
        except PWTimeout:
            pass
        settle(page)

        idx = 0
        # 1) Journal hub tabs
        for tab in JOURNAL_TABS:
            idx += 1
            try:
                click_button_by_text(page, tab, exact=True)
                settle(page)
                results.append(shoot(page, out_dir, idx, f"journal_{tab.lower()}",
                                     f"Journal — {tab}", console_errors))
            except Exception as e:
                print(f"  [{idx:02d}] Journal — {tab}: FAIL {e}")
                results.append({"idx": idx, "label": f"Journal — {tab}",
                                "status": "error", "error": str(e)[:200]})

        # 2) Backtesting sub-tabs (Backtesting tab already active from loop above)
        try:
            click_button_by_text(page, "Backtesting", exact=True)
            settle(page)
        except Exception as e:
            print(f"  could not re-enter Backtesting tab: {e}")
        for label_prefix, slug in BACKTEST_TABS:
            idx += 1
            try:
                matched = click_button_by_text(page, label_prefix, exact=False,
                                               exclude_exact=JOURNAL_TABS)
                settle(page)
                results.append(shoot(page, out_dir, idx, f"backtest_{slug}",
                                     f"Backtest — {matched}", console_errors))
            except Exception as e:
                print(f"  [{idx:02d}] Backtest — {label_prefix}: FAIL {e}")
                results.append({"idx": idx, "label": f"Backtest — {label_prefix}",
                                "status": "error", "error": str(e)[:200]})

        # 3) Representative drill-down: open a trade row on the Trades tab
        idx += 1
        try:
            click_button_by_text(page, "Trades", exact=True)
            settle(page)
            # Trades tab renders clickable <div onClick> rows (cursor:pointer) for
            # calendar days / strategy rows / individual trades — find the first one
            # that looks like a data row (inline cursor:pointer + a $ P&L value).
            # Prefer a Journal "By Strategy" / calendar row (text has both % and $),
            # not the page-header metric strip; fall back to any clickable row.
            row = page.evaluate_handle("""() => {
                const els = Array.from(document.querySelectorAll('main div[style*="cursor: pointer"], div[style*="cursor: pointer"]'));
                const inHeader = e => !!e.closest('header');
                const rows = els.filter(e => !inHeader(e));
                return rows.find(e => /%/.test(e.innerText||'') && /\\$/.test(e.innerText||''))
                    || rows.find(e => /\\$/.test(e.innerText||''))
                    || rows[rows.length-1] || null;
            }""").as_element()
            if row:
                row.scroll_into_view_if_needed(timeout=4000)
                row.click()
                settle(page)
                results.append(shoot(page, out_dir, idx, "drilldown_trade",
                                     "Drill-down — Trade detail drawer", console_errors))
            else:
                raise RuntimeError("no trade row found to drill into")
        except Exception as e:
            print(f"  [{idx:02d}] Drill-down: FAIL {e}")
            results.append({"idx": idx, "label": "Drill-down — Trade detail",
                            "status": "error", "error": str(e)[:200]})

        ctx.close()
        browser.close()

    ok = sum(1 for r in results if r["status"] == "ok")
    summary = {
        "run": run_name, "route": ROUTE, "captured_at": datetime.now().isoformat(),
        "total": len(results), "ok": ok, "errors": len(results) - ok,
        "total_console_errors": len(console_errors),
        "console_errors_sample": console_errors[:30],
        "results": results,
    }
    (out_dir / "crawl_summary.json").write_text(json.dumps(summary, indent=2))

    # Single tarball into docs/playwright/ ; delete prior journal_audit tarballs
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    for old in OUT_ROOT.glob("journal_audit_*.tgz"):
        old.unlink()
        print(f"  deleted old tarball: {old.name}")
    tgz = OUT_ROOT / f"{run_name}.tgz"
    with tarfile.open(tgz, "w:gz") as tar:
        tar.add(out_dir, arcname=run_name)
    # cleanup tmp tree
    import shutil
    shutil.rmtree(out_dir.parent)

    print(f"\n=== Done: {ok}/{len(results)} OK, {len(console_errors)} console errors ===")
    print(f"Tarball: {tgz}")
    return str(tgz)


if __name__ == "__main__":
    main()
