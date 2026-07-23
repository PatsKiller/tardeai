from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_classification_states_are_explicit_and_colorable():
    shared = read("apps/command-center-v3/src/lib/reentrySharedContext.ts")
    workbench = read("apps/command-center-v3/src/components/reentry/ReEntryExitWorkbench.tsx")
    current = read("apps/command-center-v3/src/components/reentry/ReEntryCurrentIntelligence.tsx")
    for token in ("CLASSIFIED", "AUTO-TAGGED", "UNCLASSIFIED"):
        assert token in shared
        assert token in workbench or token in current
    assert "EDIT CLASSIFICATION" in workbench
    assert "is now CLASSIFIED" in workbench
    assert "classificationTone" in current


def test_stopped_out_and_shared_annotations_prefill_the_modal():
    shared = read("apps/command-center-v3/src/lib/reentrySharedContext.ts")
    workbench = read("apps/command-center-v3/src/components/reentry/ReEntryExitWorkbench.tsx")
    assert "inferExitEvent" in shared
    assert "stopped_out" in shared
    assert "suggestedNotes" in workbench
    assert "AUTO-TAGGED STARTING EVIDENCE" in workbench
    assert "Watch/regime/earnings/resistance evidence" in workbench


def test_rows_expand_and_bulk_classification_is_reachable_from_primary_table():
    current = read("apps/command-center-v3/src/components/reentry/ReEntryCurrentIntelligence.tsx")
    workbench = read("apps/command-center-v3/src/components/reentry/ReEntryExitWorkbench.tsx")
    for token in ("setExpanded", "SELECT VISIBLE", "EDIT SELECTED", "reentry:classify-symbol"):
        assert token in current
    for token in ("setExpanded", "CLASSIFY SELECTED", "detail.symbols"):
        assert token in workbench
    assert "Click to" in current
    assert "Click to" in workbench


def test_summary_tiles_are_clickable_filters_with_tooltips():
    current = read("apps/command-center-v3/src/components/reentry/ReEntryCurrentIntelligence.tsx")
    for token in ("EXITED SYMBOLS", "CLASSIFIED", "READY NOW", "NEAR ENTRY", "MISSING / STALE"):
        assert token in current
    assert "onClick={kpi.action}" in current
    assert "title={kpi.tip}" in current
    assert "ⓘ" in current


def test_resistance_reports_primary_fallback_or_missing_evidence():
    current = read("apps/command-center-v3/src/components/reentry/ReEntryCurrentIntelligence.tsx")
    for token in ("CLOSED-SESSION CACHE", "WATCH FALLBACK", "MISSING EVIDENCE", "parseResistanceText", "no valid closed-session resistance row"):
        assert token in current


def test_shared_context_refreshes_in_existing_rth_evaluator():
    runner = read("scripts/watch_alerts_eval.py")
    backend = read("scripts/lib/reentry_shared_context.py")
    assert "refresh_shared_symbol_context" in runner
    assert "portfolio.shared-symbol-context.v1" in backend
    for token in ("journal_annotation", "earnings", "catalyst", "resistance", "watchlist_items"):
        assert token in backend.lower()


def test_watch_and_journal_mount_the_same_shared_context_bridge():
    app = read("apps/command-center-v3/src/App.tsx")
    bridge = read("apps/command-center-v3/src/components/SharedIntelligenceBridge.tsx")
    assert "SharedIntelligenceBridge" in app
    assert "<SharedIntelligenceBridge />" in app
    assert "location.pathname === '/watch'" in bridge
    assert "location.pathname === '/journal'" in bridge
    assert "RE-ENTRY CONTEXT ON WATCH" in bridge
    assert "RE-ENTRY / WATCH JOURNAL ANNOTATIONS" in bridge
    assert "OPEN RE-ENTRY" in bridge


def test_safety_boundary_remains_advisory_only():
    runner = read("scripts/watch_alerts_eval.py")
    backend = read("scripts/lib/reentry_shared_context.py")
    assert "no proposal, approval, broker order, or 2FA" in runner
    assert "no trading" in backend.lower()
