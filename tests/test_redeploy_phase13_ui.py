#!/usr/bin/env python3
"""Phase 13 UI acceptance — RedeployDesk workstation source-level checks.
Typography floors + ADVISORY-ONLY language live in test_redeploy_ui_tokens.py;
this file covers the Phase-13 additions (PLAN LAB / PLAN COMPARISON tabs,
URL persistence, empty states, monitoring error state)."""
from __future__ import annotations

import re
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "apps" / "command-center-v3" / "src" / "pages" / "RedeployDesk.tsx"


def _src() -> str:
    return PAGE.read_text()


def test_tabs_include_plan_lab_and_comparison():
    src = _src()
    tabs = re.search(r"const TABS = \[(.*?)\] as const", src, re.S)
    assert tabs, "TABS constant missing"
    assert "'PLAN LAB'" in tabs.group(1)
    assert "'PLAN COMPARISON'" in tabs.group(1)
    # comparison empty state explains how to populate it — never a blank pane
    assert "Select 2–4 plans" in src, "comparison tab needs its select-2-4 empty-state explanation"
    assert "compareIds.length >= 2" in src, "comparison renders only with >=2 selections"


def test_legacy_plans_tab_alias():
    src = _src()
    assert re.search(r"raw === 'PLANS'.*return 'PLAN LAB'", src), "?tab=PLANS must alias to PLAN LAB"


def test_event_and_plan_selection_persist():
    src = _src()
    # selected event lives in the URL
    assert "params.get('event')" in src
    assert "p.set('event'" in src
    # selected tab lives in the URL
    assert "params.get('tab')" in src and "p.set('tab'" in src
    # selected plan persists per event across tabs
    assert "cc-v3-redeploy-plan-" in src, "per-event plan selection key missing"
    assert "localStorage.setItem(planKey" in src


def test_plan_legs_rendered_directly_on_cards():
    src = _src()
    assert "const legCols" in src, "legCols leg-table definition missing"
    # plan cards in PLAN LAB render their legs inline via legCols
    assert re.search(r"plans\.map\(\(p: any\) => \{.*?cols=\{legCols\(p\)\}", src, re.S), (
        "each plan card must render its legs table (legCols) directly"
    )


def test_empty_state_explanations():
    src = _src()
    for msg in (
        "No production fills recorded",           # monitoring fills
        "No rejected alternatives recorded",      # rejected tab
        "Select a sale event.",                   # event overview without event
        "No audit rows for this event.",          # audit tab
        "entries are always shown in the context of their plan",  # entries without plan
    ):
        assert msg in src, f"empty-state explanation missing: {msg!r}"


def test_monitoring_error_state_distinct_from_no_event():
    src = _src()
    assert "Monitoring failed to load" in src, "monitoring needs an explicit error branch"
    assert "Select an event first." in src, "monitoring needs a distinct no-event branch"
    # error branch offers a retry, not a dead end
    assert "monitoring.refetch()" in src


def test_no_execution_approval_language():
    src = _src()
    low = src.lower()
    for phrase in ("approve execution", "execute plan", "submit order", "execution approved"):
        assert phrase not in low, f"execution-approval language present: {phrase!r}"
    flat = " ".join(src.split())  # JSX wraps prose across lines
    assert "operator implementation" in flat
    assert "never execution approval" in flat


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"ALL {len(tests)} PASSED")
