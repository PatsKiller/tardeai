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
    # LQ-1663 (2026-11-09): re-pinned after 303128d68 / c0064c838. The per-row "is now
    # CLASSIFIED" toast was replaced by the shared event contract: the workbench dispatches
    # reentry:classify-symbol, ReEntryClassificationOverlay owns the dialog and emits
    # reentry:classification-saved. The state still rides every row as a colour-coded label.
    assert "reentry:classify-symbol" in workbench
    assert "classificationLabel(state)" in workbench
    overlay = read("apps/command-center-v3/src/components/reentry/ReEntryClassificationOverlay.tsx")
    assert "reentry:classification-saved" in overlay
    assert "classTone" in current


def test_stopped_out_and_shared_annotations_prefill_the_modal():
    shared = read("apps/command-center-v3/src/lib/reentrySharedContext.ts")
    overlay = read("apps/command-center-v3/src/components/reentry/ReEntryClassificationOverlay.tsx")
    assert "inferExitEvent" in shared
    assert "stopped_out" in shared
    # LQ-1663 (2026-11-09): the evidence-prefilled modal moved into the overlay in 303128d68
    # ("make classification modal evidence-complete"). The seed is `startingNotes`, built from
    # the watch context (recommendation/sector/regime/earnings/catalyst/RSI/valuation) and used
    # only when no saved notes exist — an operator's own note is never overwritten.
    assert "startingNotes" in overlay
    assert "savedEvent.notes || startingNotes" in overlay
    assert "reentry:classify-symbol" in overlay


def test_rows_expand_and_bulk_classification_is_reachable_from_primary_table():
    current = read("apps/command-center-v3/src/components/reentry/ReEntryCurrentIntelligence.tsx")
    workbench = read("apps/command-center-v3/src/components/reentry/ReEntryExitWorkbench.tsx")
    for token in ("setExpanded", "SELECT VISIBLE", "EDIT SELECTED", "reentry:classify-symbol"):
        assert token in current
    # LQ-1663 (2026-11-09): the bulk action dispatches the same custom event; its payload is
    # `detail: { symbols }`, not a `detail.symbols` property read.
    for token in ("setExpanded", "CLASSIFY SELECTED", "detail: { symbols }"):
        assert token in workbench
    # rows expand on click in both tables (303128d68 replaced the literal "Click to" hint)
    assert "onClick={() => setExpanded" in current
    assert "onClick={() => setExpanded" in workbench


def test_summary_tiles_are_clickable_filters():
    current = read("apps/command-center-v3/src/components/reentry/ReEntryCurrentIntelligence.tsx")
    # LQ-1663 (2026-11-09): 303128d68 re-pinned the tiles — EVIDENCE GAPS replaces the
    # "MISSING / STALE" tile, and the tile buttons carry their count + active state instead
    # of a kpi.tip tooltip/ⓘ affordance that no longer exists.
    for token in ("EXITED SYMBOLS", "CLASSIFIED", "READY NOW", "NEAR ENTRY", "EVIDENCE GAPS"):
        assert token in current
    assert "onClick={action}" in current
    assert "background: active ? BB.blueDim" in current


def test_resistance_reports_primary_fallback_or_missing_evidence():
    current = read("apps/command-center-v3/src/components/reentry/ReEntryCurrentIntelligence.tsx")
    # LQ-1663 (2026-11-09): the missing-evidence state is typed, not a heading: resistanceFor
    # returns state UNAVAILABLE with source MISSING and the reason spelled out, so the page can
    # never render a blank where a resistance should be.
    for token in ("CLOSED-SESSION CACHE", "WATCH FALLBACK", "resistanceFor", "'UNAVAILABLE'",
                  "source: 'MISSING'", "No valid resistance cache row or parsable Watch trigger."):
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
