#!/usr/bin/env python3
"""V3 route/subtab maturity probe — assert URL, heading, active tab before screenshot.

Screenshots written outside the repo. Results JSON/MD under docs/ops.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = "http://127.0.0.1:7777/v3"
OUT_SHOTS = Path("/tmp/deepseek-v4-mainline-v3-screenshots")
OUT_SHOTS.mkdir(parents=True, exist_ok=True)
REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "ops" / "deepseek-v4-mainline-2026-08-03"

# Canonical routes from App.tsx + known operator tabs (source-derived, not stale screenshot list)
ROUTES = [
    {"path": "", "heading_re": r"Home|Command|Portfolio|Desk|Today", "tabs": []},
    {"path": "portfolio", "heading_re": r"Portfolio|Holdings", "tabs": ["Holdings", "Allocation"]},
    {"path": "portfolio/re-entry", "heading_re": r"Re-?Entry|Entry", "tabs": []},
    {"path": "risk", "heading_re": r"Risk", "tabs": []},
    {"path": "trading", "heading_re": r"Trading|Proposals|Broker", "tabs": []},
    {"path": "active-trader", "heading_re": r"Active\s*Trader|Trader", "tabs": []},
    {"path": "strategy", "heading_re": r"Strategy", "tabs": []},
    {"path": "watch", "heading_re": r"Watch|Watchlist|MAIN", "tabs": []},
    {"path": "defense", "heading_re": r"Defense", "tabs": []},
    {"path": "agents", "heading_re": r"Agent|Runtime|Fleet", "tabs": []},
    {"path": "intelligence", "heading_re": r"Intelligence|Intel", "tabs": []},
    {"path": "research-intelligence", "heading_re": r"Research|Intel", "tabs": []},
    {"path": "hermes", "heading_re": r"Hermes", "tabs": []},
    {"path": "reports", "heading_re": r"Report", "tabs": []},
    {"path": "rotation", "heading_re": r"Rotation", "tabs": []},
    {"path": "health", "heading_re": r"Health", "tabs": []},
    {"path": "consumption", "heading_re": r"Consumption|LLM|Spend", "tabs": []},
    {"path": "system", "heading_re": r"System", "tabs": []},
    {"path": "journal", "heading_re": r"Journal|Trade", "tabs": []},
    {"path": "retirement", "heading_re": r"Retirement", "tabs": []},
]


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("PLAYWRIGHT_MISSING")
        return 2

    results = []
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(15000)
        console_errors: list[str] = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        for route in ROUTES:
            path = route["path"]
            url = f"{BASE}/{path}" if path else f"{BASE}/"
            rec = {
                "path": path or "/",
                "url_expected": url,
                "tabs": [],
                "pass": False,
                "errors": [],
                "screenshot": None,
            }
            try:
                console_errors.clear()
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(800)
                actual = page.url
                rec["url_actual"] = actual
                if f"/v3/{path}" not in actual and not (path == "" and actual.rstrip("/").endswith("/v3")):
                    # allow querystrings
                    if f"/v3/{path}" not in actual.split("?")[0] and path:
                        rec["errors"].append(f"url_mismatch: {actual}")
                body_text = page.inner_text("body")[:4000]
                if not re.search(route["heading_re"], body_text, re.I):
                    # try h1/h2
                    heads = page.locator("h1,h2,[data-testid='page-title']").all_inner_texts()
                    rec["headings"] = heads[:8]
                    if not any(re.search(route["heading_re"], h, re.I) for h in heads):
                        rec["errors"].append(f"heading_missing for /{path}: {route['heading_re']}")
                else:
                    rec["heading_ok"] = True

                for tab in route.get("tabs") or []:
                    tab_rec = {"tab": tab, "pass": False}
                    try:
                        # click by role or text
                        loc = page.get_by_role("tab", name=re.compile(re.escape(tab), re.I))
                        if loc.count() == 0:
                            loc = page.get_by_text(re.compile(f"^{re.escape(tab)}$", re.I))
                        if loc.count() == 0:
                            tab_rec["errors"] = ["tab_not_found"]
                        else:
                            loc.first.click()
                            page.wait_for_timeout(400)
                            # active marker heuristics
                            active = page.locator(
                                f"[aria-selected='true']:has-text('{tab}'), "
                                f"[data-state='active']:has-text('{tab}'), "
                                f".active:has-text('{tab}')"
                            )
                            if active.count() == 0:
                                # soft: if URL has tab=
                                if f"tab={tab.replace(' ', '+')}" in page.url or f"tab={tab}" in page.url:
                                    tab_rec["pass"] = True
                                    tab_rec["active_via"] = "url"
                                else:
                                    tab_rec["errors"] = ["active_marker_missing"]
                            else:
                                tab_rec["pass"] = True
                                tab_rec["active_via"] = "aria/data"
                    except Exception as e:
                        tab_rec["errors"] = [str(e)[:120]]
                    rec["tabs"].append(tab_rec)

                fatal = [e for e in console_errors if "Failed to fetch" not in e][:5]
                rec["console_errors"] = fatal
                if fatal:
                    rec["errors"].append(f"console:{fatal[0][:100]}")

                if not rec["errors"] and all(t.get("pass", True) for t in rec["tabs"] if "errors" in t or "pass" in t):
                    # screenshot only after pass
                    slug = (path or "home").replace("/", "_")
                    shot = OUT_SHOTS / f"{slug}.png"
                    page.screenshot(path=str(shot), full_page=False)
                    rec["screenshot"] = str(shot)
                    rec["screenshot_sha256"] = hashlib.sha256(shot.read_bytes()).hexdigest()[:16]
                    rec["pass"] = True
                else:
                    # tabs with only pass True and no errors at route level
                    if not rec["errors"] and all(t.get("pass") for t in rec["tabs"] if t.get("tab")):
                        rec["pass"] = True
                    if not rec["tabs"] and not rec["errors"]:
                        slug = (path or "home").replace("/", "_")
                        shot = OUT_SHOTS / f"{slug}.png"
                        page.screenshot(path=str(shot), full_page=False)
                        rec["screenshot"] = str(shot)
                        rec["screenshot_sha256"] = hashlib.sha256(shot.read_bytes()).hexdigest()[:16]
                        rec["pass"] = True
            except Exception as e:
                rec["errors"].append(str(e)[:200])
                rec["pass"] = False
            results.append(rec)
        browser.close()

    passed = sum(1 for r in results if r.get("pass"))
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE,
        "duration_s": round(time.time() - t0, 2),
        "passed": passed,
        "total": len(results),
        "all_pass": passed == len(results),
        "screenshot_dir": str(OUT_SHOTS),
        "results": results,
    }
    DOC.mkdir(parents=True, exist_ok=True)
    (DOC / "V3_ROUTE_TEST_RESULTS.json").write_text(json.dumps(summary, indent=2))
    md = [
        "# V3 route/subtab maturity results\n",
        f"- Generated: {summary['generated_at']}",
        f"- Pass: **{passed}/{len(results)}**",
        f"- Screenshots: `{OUT_SHOTS}` (outside git)\n",
        "| Path | Pass | Errors |",
        "|------|------|--------|",
    ]
    for r in results:
        err = "; ".join(r.get("errors") or [])[:80]
        md.append(f"| /{r['path'].lstrip('/')} | {r.get('pass')} | {err} |")
    (DOC / "V3_ROUTE_TEST_RESULTS.md").write_text("\n".join(md) + "\n")
    print(json.dumps({"passed": passed, "total": len(results), "all_pass": summary["all_pass"]}))
    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
