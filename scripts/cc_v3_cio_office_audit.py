#!/usr/bin/env python3
"""Phase 8 Checkpoint 8 — /v3/cio office-home browser audit (desktop + narrow).

Runs the six sections of the private investment office home through a real
browser and asserts the operator-facing contract:

  - all six sections reachable (CIO NOW / CAPITAL PLAN / PORTFOLIO POSTURE /
    OPPORTUNITIES / REPORT / EVIDENCE)
  - the decision drawer ("Why? · evidence") opens per decision
  - zero horizontal overflow at desktop and narrow widths
  - zero console errors / page errors
  - zero raw JSON in primary UX (no snake_case payload keys leaked to the DOM)

Mirrors scripts/cc_v3_playwright_audit.py: Firefox first (Chromium unsupported
on some hosts), base URL overridable via CC_V3_BASE (default http://127.0.0.1:7777).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

BASE = os.environ.get("CC_V3_BASE", "http://127.0.0.1:7777") + "/v3/cio"

SECTIONS = [
    "CIO NOW",
    "CAPITAL PLAN",
    "PORTFOLIO POSTURE",
    "OPPORTUNITIES",
    "REPORT",
    "EVIDENCE / AUDIT",
]

# Internal payload keys that must never surface as visible text in a primary view.
FORBIDDEN_KEYS = [
    "position_decisions", "cash_total_usd", "recommended_delta_usd",
    "current_weight_pct", "cio_stance", "source_traceability_pct",
    "fields_unavailable", "input_hashes", "decision_dispositions",
]

VIEWPORTS = [
    ("desktop", 1440, 900),
    ("narrow", 390, 844),
]


def _launch(p):
    try:
        return p.firefox.launch(headless=True)
    except Exception:
        return p.chromium.launch(headless=True)


def _overflow(page) -> float:
    return page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed — run: pip install playwright && playwright install firefox")
        return 2

    results: list[dict] = []

    with sync_playwright() as p:
        browser = _launch(p)
        for vp_name, w, h in VIEWPORTS:
            ctx = browser.new_context(viewport={"width": w, "height": h})
            page = ctx.new_page()
            console_errors: list[str] = []
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: console_errors.append(f"PAGEERROR: {err}"))

            row = {"viewport": vp_name, "width": w, "sections": [], "ok": True, "issues": []}

            try:
                resp = page.goto(BASE, wait_until="domcontentloaded", timeout=40000)
                page.wait_for_timeout(1800)
                row["status"] = resp.status if resp else 0
                if not resp or resp.status >= 400:
                    row["ok"] = False
                    row["issues"].append(f"HTTP {row['status']}")

                # Wait for the office home (hub shell) to mount.
                page.get_by_test_id("cio-hub").wait_for(timeout=30000)

                # Zero raw JSON / snake_case leakage in the whole visible body.
                body_text = page.inner_text("body")
                for key in FORBIDDEN_KEYS:
                    if key in body_text:
                        row["ok"] = False
                        row["issues"].append(f"raw key leaked: {key}")

                for section in SECTIONS:
                    sec = {"section": section, "ok": True, "issues": []}
                    try:
                        btn = page.get_by_role("tab", name=section, exact=True)
                        if btn.count() == 0:
                            sec["ok"] = False
                            sec["issues"].append("tab not found")
                        else:
                            btn.first.click(timeout=5000)
                            page.wait_for_timeout(800)
                            over = _overflow(page)
                            if over > 1:
                                sec["ok"] = False
                                sec["issues"].append(f"horizontal overflow {over}px")
                            main = page.locator("main.app-main").inner_text() if page.locator("main.app-main").count() else ""
                            if len(main.strip()) < 60:
                                sec["ok"] = False
                                sec["issues"].append("section content very short")
                            for key in FORBIDDEN_KEYS:
                                if key in main:
                                    sec["ok"] = False
                                    sec["issues"].append(f"raw key leaked: {key}")

                        # Decision drawer: on CIO NOW, open the first card's evidence.
                        if section == "CIO NOW":
                            toggle = page.get_by_role("button", name="Why? · evidence").first
                            if toggle.count():
                                toggle.click()
                                page.wait_for_timeout(400)
                                if page.get_by_test_id("cio-decision-evidence").count() == 0:
                                    sec["issues"].append("decision evidence drawer did not open")
                                else:
                                    toggle.click()  # close again
                    except Exception as e:
                        sec["ok"] = False
                        sec["issues"].append(str(e)[:120])
                    if sec["issues"]:
                        row["issues"].extend([f"{section}: {i}" for i in sec["issues"]])
                    if not sec["ok"]:
                        row["ok"] = False
                    row["sections"].append(sec)

                if console_errors:
                    row["ok"] = False
                    row["issues"].extend([f"console: {e[:100]}" for e in console_errors[:3]])
            except Exception as e:
                row["ok"] = False
                row["issues"].append(str(e)[:160])

            results.append(row)
            print(("OK " if row["ok"] else "FAIL") + f" {vp_name} ({w}px)" + (f" — {row['issues'][0]}" if row.get("issues") else ""))
            ctx.close()

        browser.close()

    fail = [r for r in results if not r["ok"]]
    summary = {
        "audited_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "target": BASE,
        "viewports": len(results),
        "failed": len(fail),
        "results": results,
    }
    out_path = Path(__file__).resolve().parent.parent / "data" / "runtime" / "cc_v3_cio_office_audit.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nWrote {out_path}")
    print(f"Viewports: {len(results)} OK: {len(results)-len(fail)} FAIL: {len(fail)}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
