from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_exit_workbench_uses_full_fidelity_cache_before_redeploy_fallback():
    src = read("apps/command-center-v3/src/components/reentry/ReEntryExitWorkbench.tsx")
    # The cache key is owned by the shared lib so every Re-Entry surface reads one
    # constant; the workbench must import it rather than inline its own literal.
    assert "portfolio.reentry.exit-universe.v1" in read(
        "apps/command-center-v3/src/lib/reentrySharedContext.ts"
    )
    assert "EXIT_CACHE_KEY" in src
    assert "cacheRows.length ? cacheRows : fallbackRows" in src
    assert "FULL-FIDELITY BROKER CACHE" in src
    assert "REDEPLOY SUMMARY FALLBACK" in src
    assert "rowShares(row)" in src
    assert "rowPrice(row)" in src
    assert "avgExit" in src


def test_classification_control_is_in_the_symbol_column_and_opens_a_modal():
    src = read("apps/command-center-v3/src/components/reentry/ReEntryExitWorkbench.tsx")
    assert "Symbol / classification" in src
    assert "'EDIT CLASSIFICATION' : 'CLASSIFY'" in src
    assert "role=\"dialog\"" in src
    assert "SAVE CLASSIFICATION" in src
    assert "CORE HOLDING" in src
    # REENTRY_FLAGS is defined once in the shared lib and rendered by the workbench,
    # so the flag vocabulary is asserted where it is actually declared.
    flags_src = read("apps/command-center-v3/src/lib/reentrySharedContext.ts")
    assert "REENTRY_FLAGS" in src
    for flag in ("growth", "compounding", "dividend", "swing", "short", "defensive", "hedge", "rotation"):
        assert f"'{flag}'" in flags_src


def test_current_intelligence_is_restored_to_the_primary_page():
    src = read("apps/command-center-v3/src/components/reentry/ReEntryCurrentIntelligence.tsx")
    for token in (
        "CURRENT RE-ENTRY INTELLIGENCE",
        "Current status / action",
        "Last / avg exit",
        "RSI",
        "Pullback",
        "Candidate entry",
        "Resistance",
        "Portfolio flags",
        "Analyst",
        "Alerts",
        "reentry:classify-symbol",
    ):
        assert token in src


def test_reentry_and_redeploy_use_fixed_surfaces_instead_of_hidden_actions_table():
    reentry = read("apps/command-center-v3/src/pages/ReEntryPageV4.tsx")
    redeploy = read("apps/command-center-v3/src/pages/RedeployDeskIntegrated.tsx")
    for token in ("ReEntryCurrentIntelligence", "ReEntryExitWorkbench"):
        assert token in reentry
        assert token in redeploy
    assert "AuthoritativeExitUniverse" not in reentry
    assert "AuthoritativeExitUniverse" not in redeploy
