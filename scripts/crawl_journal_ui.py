#!/usr/bin/env python3
"""crawl_journal_ui.py — Playwright visual audit of the v3 Journal tabs.

Walks every Journal tab, screenshots it, then clicks interactive elements (KPI cards, strategy rows, badges,
replay buttons, drilldown rows) and captures any modal/drawer that opens. Compresses to JPEG + writes a
manifest. Read-only — navigates + clicks the UI only; no API writes. Hardened: viewport-only shots (the
Trade Log is very tall), per-tab re-navigation, bounded clicks, sanitized names, per-tab progress flush.
"""
import os, time, json, sys, re
from playwright.sync_api import sync_playwright
from PIL import Image

BASE = "http://127.0.0.1:7777/v3/journal"
RAW = "/tmp/journal_crawl_raw"
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/journal_crawl_out"
TABS = ["Trades", "Analytics", "Lessons", "Protection", "Backtesting", "Real Accounts"]
os.makedirs(RAW, exist_ok=True); os.makedirs(OUT, exist_ok=True)
log = []


def san(s):
    return re.sub(r"[^A-Za-z0-9_]+", "_", (s or "el"))[:18].strip("_") or "el"


def shot(page, name):
    try:
        page.screenshot(path=os.path.join(RAW, name + ".png"), full_page=False, timeout=8000)
    except Exception:
        pass


def open_tab(page, tab):
    page.goto(BASE, wait_until="domcontentloaded", timeout=30000)
    time.sleep(4.5)   # let the journal's API fetches (trades, KPIs, charts) resolve before shooting
    page.get_by_text(tab, exact=True).first.click(timeout=8000)
    time.sleep(4.0)


with sync_playwright() as pw:
    br = pw.chromium.launch(headless=True)
    page = br.new_page(viewport={"width": 1600, "height": 1000})
    seen = set()   # GLOBAL — the shared MetricStrip cards are captured once, not re-shot on every tab

    for tab in TABS:
        slug = san(tab).lower()
        try:
            open_tab(page, tab)
        except Exception as e:
            log.append({"tab": tab, "status": "open-failed", "err": str(e)[:60]})
            print(f"  {tab}: open-failed", flush=True); continue
        shot(page, f"{slug}_00_overview")
        clicks = 0
        deadline = time.time() + 40   # per-tab budget
        def big_overlay():   # the drawer (zIndex 1000) / replay modal (zIndex 50) are position:fixed, full-width
            for o in page.query_selector_all("[style*='position: fixed']"):
                b = o.bounding_box() or {}
                if b.get("width", 0) > 400 and b.get("height", 0) > 300:
                    return True
            return False
        # all onClick targets right of the nav rail (skip nav x<230); JS-click bypasses actionability timeouts
        els = [e for e in page.query_selector_all("[style*='cursor: pointer'], button")
               if (e.bounding_box() or {}).get("x", 0) > 230 and (e.bounding_box() or {}).get("width", 0) > 20]
        for el in els:
            if clicks >= 8 or time.time() > deadline:
                break
            try:
                box = el.bounding_box()
                if not box:
                    continue
                key = f"{round(box['x']/12)},{round(box['y']/12)}"
                if key in seen:
                    continue
                seen.add(key)
                txt = (el.inner_text() or "").strip()[:24]
                el.evaluate("e => e.click()")   # JS click — never times out on overlap/animation
                time.sleep(1.0)
                if big_overlay():
                    clicks += 1
                    shot(page, f"{slug}_{clicks:02d}_{san(txt)}")
                    # close: click the LEFT-side backdrop (drawer panel sits on the right) + Escape
                    page.mouse.click(300, 520)
                    time.sleep(0.4); page.keyboard.press("Escape"); time.sleep(0.4)
                if "/journal" not in page.url:   # a click navigated away — recover the tab
                    open_tab(page, tab)
                    els = []   # handles are stale after re-nav; stop this tab
                    break
            except Exception:
                continue
        log.append({"tab": tab, "status": "ok", "interactions_captured": clicks})
        print(f"  {tab}: ok ({clicks} interactions)", flush=True)

    br.close()

# compress all PNG -> JPEG
manifest = []
for f in sorted(os.listdir(RAW)):
    if f.endswith(".png"):
        try:
            im = Image.open(os.path.join(RAW, f)).convert("RGB")
            if im.width > 1400:
                im = im.resize((1400, int(im.height * 1400 / im.width)))
            dst = os.path.join(OUT, f.replace(".png", ".jpg"))
            im.save(dst, "JPEG", quality=42, optimize=True)
            manifest.append({"file": os.path.basename(dst), "bytes": os.path.getsize(dst)})
        except Exception:
            continue
json.dump({"log": log, "images": manifest}, open(os.path.join(OUT, "_manifest.json"), "w"), indent=2)
print(json.dumps({"tabs": log, "images": len(manifest), "total_kb": round(sum(m["bytes"] for m in manifest) / 1024)}))
