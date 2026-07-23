from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_exit_workbench_uses_full_fidelity_cache_before_redeploy_fallback():
    src = read("apps/command-center-v3/src/components/reentry/ReEntryExitWorkbench.tsx")
    assert "portfolio.reentry.exit-universe.v1" in src
    assert "cacheRows.length ? cacheRows : fallbackRows" in src
    assert "FULL-FIDELITY BROKER CACHE" in src
    assert "REDEPLOY SUMMARY FALLBACK" in src
    assert "quantity" in src
    assert "price" in src
    assert "avgExit" in src


def test_classification_control_is_in_the_symbol_column_and_opens_a_modal():
    src = read("apps/command-center-v3/src/components/reentry/ReEntryExitWorkbench.tsx")
    assert "Symbol / controls" in src
    assert ">CLASSIFY<" in src
    assert "role=\"dialog\"" in src
    assert "SAVE CLASSIFICATION" in src
    assert "CORE HOLDING" in src
    for flag in ("growth", "compounding", "dividend", "swing", "short", "defensive", "hedge", "rotation"):
        assert flag in src


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
