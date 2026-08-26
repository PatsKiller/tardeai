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
  - G9 office contract: four attention KPIs, ≤5 decision cards, advisory
    provenance wording, capital-raise copy that does not call earmarked cash
    a "new raise"

Mirrors scripts/cc_v3_playwright_audit.py: Firefox first (Chromium unsupported
on some hosts), base URL overridable via CC_V3_BASE (default http://127.0.0.1:7777).

Acceptance later should call `evaluate_g9_office_audit` / `audit_office_sources`
— those are pure and do not require a live browser.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parent.parent
BASE = os.environ.get("CC_V3_BASE", "http://127.0.0.1:7777") + "/v3/cio"

CIO_HUB_SOURCE = REPO / "apps/command-center-v3/src/pages/CioHub.tsx"
ADVISORY_SOURCE = REPO / "apps/command-center-v3/src/pages/AdvisoryDeskHub.tsx"
COMMAND_CENTER_SOURCE = REPO / "scripts/lib/cio_command_center.py"

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

# G9 office-home contract (selectors + copy). Invoked by acceptance later.
CIO_ATTENTION_KPI_LABELS = (
    "Investment decisions",
    "Workflow actions",
    "Open plans",
    "Material Today",
)
FORBIDDEN_ATTENTION_LABELS = (
    "Decisions needing you",
)
MAX_DECISION_CARDS = 5
ADVISORY_REQUIRED_PHRASES = (
    "Current mark",
    "Upside vs canonical current",
    "Upside vs provider snapshot",
)
CAPITAL_RAISE_HONEST_PHRASES = (
    "Earmarked redeploy already in cash is not new capital",
    "Earmarked redeploy (already in cash)",
)
BLIND_VS_CURRENT_RE = re.compile(
    r"""(?:label\s*[:=]\s*['"]vs current['"]|>\s*vs current\s*<|['"]vs current['"])""",
    re.I,
)
EARMARK_NEW_RAISE_RE = re.compile(
    r"earmark\w*.{0,80}new raise|new raise.{0,80}earmark\w*",
    re.I | re.S,
)
NEGATION_RE = re.compile(r"\b(?:not|never|isn't|is not|no longer)\b", re.I)


def g9_office_audit_contract() -> dict[str, Any]:
    """Declarative selectors/expectations. Safe to import from acceptance."""
    return {
        "gate": "G9_advisory_ui_provenance_live",
        "authority": "READ_ONLY_ADVISORY",
        "kpi_labels": list(CIO_ATTENTION_KPI_LABELS),
        "forbidden_labels": list(FORBIDDEN_ATTENTION_LABELS),
        "max_decision_cards": MAX_DECISION_CARDS,
        "advisory_required_phrases": list(ADVISORY_REQUIRED_PHRASES),
        "capital_raise_honest_phrases": list(CAPITAL_RAISE_HONEST_PHRASES),
        "selectors": {
            "hub": '[data-testid="cio-hub"]',
            "now_section": '[data-testid="cio-now-section"]',
            "decision_card": '[data-testid="cio-decision-card"]',
            "decision_evidence": '[data-testid="cio-decision-evidence"]',
            "capital_plan": '[data-testid="capital-plan-section"]',
            "why_evidence": 'role=button[name="Why? · evidence"]',
            "cio_now_tab": 'role=tab[name="CIO NOW"]',
            "capital_plan_tab": 'role=tab[name="CAPITAL PLAN"]',
        },
        "sources": {
            "cio_hub": "apps/command-center-v3/src/pages/CioHub.tsx",
            "advisory": "apps/command-center-v3/src/pages/AdvisoryDeskHub.tsx",
        },
    }


def _blob(*parts: str) -> str:
    return "\n".join(p for p in parts if p)


def _earmark_called_new_raise(text: str) -> bool:
    """True when earmarked cash is presented as a new raise (no negation)."""
    if not text:
        return False
    for m in EARMARK_NEW_RAISE_RE.finditer(text):
        window = m.group(0)
        if not NEGATION_RE.search(window):
            return True
    return False


def evaluate_g9_office_audit(
    *,
    body_text: str = "",
    cio_hub_source: str = "",
    advisory_source: str = "",
    command_center_source: str = "",
    decision_card_count: Optional[int] = None,
    selectors_present: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Pure G9 office-home evaluator. No browser, no network.

    Acceptance can pass live page text, the served bundle, or checked-in
    source. Missing optional inputs skip those checks rather than invent a pass
    from an empty string — callers that want a source-backed result should use
    `audit_office_sources`.
    """
    issues: list[str] = []
    checks: dict[str, Any] = {}
    contract = g9_office_audit_contract()
    ui = _blob(body_text, cio_hub_source)
    advisory = _blob(advisory_source, body_text)
    all_text = _blob(ui, advisory, command_center_source)

    kpi_found = {label: label in ui for label in CIO_ATTENTION_KPI_LABELS}
    checks["kpi_labels"] = kpi_found
    if ui:
        missing = [label for label, ok in kpi_found.items() if not ok]
        if missing:
            issues.append(f"missing_kpi_labels:{missing}")
    else:
        issues.append("no_ui_text_for_kpi_labels")

    forbidden = [label for label in FORBIDDEN_ATTENTION_LABELS if label in ui]
    checks["forbidden_labels_present"] = forbidden
    if forbidden:
        issues.append(f"forbidden_attention_label:{forbidden}")

    checks["max_decision_cards"] = MAX_DECISION_CARDS
    checks["decision_card_count"] = decision_card_count
    if decision_card_count is not None and decision_card_count > MAX_DECISION_CARDS:
        issues.append(f"decision_card_count:{decision_card_count}>{MAX_DECISION_CARDS}")
    if cio_hub_source and "Cards show at most 5" not in cio_hub_source:
        issues.append("cio_hub_missing_max_5_card_copy")
    if command_center_source and "needing[:5]" not in command_center_source:
        issues.append("command_center_missing_card_cap")

    phrase_found = {p: p in advisory for p in ADVISORY_REQUIRED_PHRASES}
    checks["advisory_phrases"] = phrase_found
    if advisory:
        missing_p = [p for p, ok in phrase_found.items() if not ok]
        if missing_p:
            issues.append(f"missing_advisory_phrases:{missing_p}")
        if BLIND_VS_CURRENT_RE.search(advisory):
            issues.append("blind_vs_current_label")
    elif advisory_source == "" and not body_text:
        issues.append("no_advisory_text")

    honest = {p: p in ui for p in CAPITAL_RAISE_HONEST_PHRASES}
    checks["capital_raise_honest_phrases"] = honest
    if ui:
        if not any(honest.values()):
            issues.append("capital_raise_missing_earmark_not_new_capital_copy")
        if _earmark_called_new_raise(ui):
            issues.append("earmarked_cash_called_new_raise")

    sel = selectors_present or {}
    checks["selectors_present"] = sel
    if sel:
        for key in ("hub", "now_section"):
            if key in sel and not sel[key]:
                issues.append(f"selector_missing:{key}")

    checks["raw_payload_keys"] = [k for k in FORBIDDEN_KEYS if k in all_text and k in (body_text or "")]
    if body_text:
        leaked = [k for k in FORBIDDEN_KEYS if k in body_text]
        if leaked:
            issues.append(f"raw_key_leaked:{leaked}")

    ok = len(issues) == 0
    return {
        "ok": ok,
        "gate": "G9_advisory_ui_provenance_live",
        "authority": "READ_ONLY_ADVISORY",
        "issues": issues,
        "checks": checks,
        "contract": contract,
        "mode": "evaluate_g9_office_audit",
    }


def collect_office_audit_from_page(page: Any) -> dict[str, Any]:
    """Extract a G9 snapshot from a Playwright page. Acceptance may call this."""
    body_text = ""
    try:
        body_text = page.inner_text("body")
    except Exception:
        body_text = ""
    card_count = 0
    try:
        card_count = page.get_by_test_id("cio-decision-card").count()
    except Exception:
        try:
            card_count = page.locator('[data-testid="cio-decision-card"]').count()
        except Exception:
            card_count = 0
    selectors_present = {}
    for key, testid in (
        ("hub", "cio-hub"),
        ("now_section", "cio-now-section"),
        ("capital_plan", "capital-plan-section"),
        ("decision_evidence", "cio-decision-evidence"),
    ):
        try:
            selectors_present[key] = page.get_by_test_id(testid).count() > 0
        except Exception:
            selectors_present[key] = False
    return {
        "body_text": body_text,
        "decision_card_count": card_count,
        "selectors_present": selectors_present,
    }


def evaluate_g9_office_audit_from_page(page: Any, **kwargs: Any) -> dict[str, Any]:
    """Page → G9 result. Used by the live browser path and by acceptance later."""
    snap = collect_office_audit_from_page(page)
    return evaluate_g9_office_audit(
        body_text=snap.get("body_text") or "",
        decision_card_count=snap.get("decision_card_count"),
        selectors_present=snap.get("selectors_present"),
        **kwargs,
    )


def audit_office_sources(
    *,
    cio_hub_path: Optional[Path] = None,
    advisory_path: Optional[Path] = None,
    command_center_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Read checked-in UI sources and evaluate the G9 office contract.

    No live browser. This is the function acceptance can invoke offline.
    """
    hub_p = cio_hub_path or CIO_HUB_SOURCE
    adv_p = advisory_path or ADVISORY_SOURCE
    cc_p = command_center_path or COMMAND_CENTER_SOURCE
    hub = hub_p.read_text(encoding="utf-8") if hub_p.is_file() else ""
    adv = adv_p.read_text(encoding="utf-8") if adv_p.is_file() else ""
    cc = cc_p.read_text(encoding="utf-8") if cc_p.is_file() else ""
    result = evaluate_g9_office_audit(
        cio_hub_source=hub,
        advisory_source=adv,
        command_center_source=cc,
    )
    result["mode"] = "sources_only"
    result["source_paths"] = {
        "cio_hub": str(hub_p),
        "advisory": str(adv_p),
        "command_center": str(cc_p),
        "cio_hub_present": hub_p.is_file(),
        "advisory_present": adv_p.is_file(),
        "command_center_present": cc_p.is_file(),
    }
    return result


def _launch(p):
    try:
        return p.firefox.launch(headless=True)
    except Exception:
        return p.chromium.launch(headless=True)


def _overflow(page) -> float:
    return page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )


def run_browser_audit() -> int:
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
                            g9 = evaluate_g9_office_audit_from_page(
                                page,
                                cio_hub_source=CIO_HUB_SOURCE.read_text(encoding="utf-8") if CIO_HUB_SOURCE.is_file() else "",
                                advisory_source=ADVISORY_SOURCE.read_text(encoding="utf-8") if ADVISORY_SOURCE.is_file() else "",
                                command_center_source=(
                                    COMMAND_CENTER_SOURCE.read_text(encoding="utf-8")
                                    if COMMAND_CENTER_SOURCE.is_file() else ""
                                ),
                            )
                            sec["g9"] = {"ok": g9.get("ok"), "issues": g9.get("issues")}
                            if not g9.get("ok"):
                                sec["ok"] = False
                                sec["issues"].extend(g9.get("issues") or [])
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


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="CIO office-home G9 / browser audit")
    parser.add_argument(
        "--sources-only",
        action="store_true",
        help="Evaluate checked-in CioHub/Advisory source (no live browser)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    args = parser.parse_args(argv)
    if args.sources_only:
        result = audit_office_sources()
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(("OK" if result.get("ok") else "FAIL") + " G9 office sources")
            for issue in result.get("issues") or []:
                print(f"  - {issue}")
        return 0 if result.get("ok") else 1
    return run_browser_audit()


if __name__ == "__main__":
    sys.exit(main())
