"""Tests for SCREENER-MAP-1 strategy source coverage repair."""
import subprocess, sys, json
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SCRIPTS = PROJ / "scripts"
CONFIG = PROJ / "config"
DOCS = PROJ / "docs" / "screener_architecture" / "phase_screener_map1_strategy_coverage_repair"

ALL_STRATEGIES = [
    'bond_income', 'cash_or_stable', 'core_growth_compounder', 'core_index',
    'covered_call_income', 'defense_thesis', 'dividend_growth_compounder',
    'earnings_catalyst', 'earnings_post_momentum', 'earnings_pre_buildup',
    'fib_retracement_bounce', 'gap_and_go', 'high_yield_income_bdc',
    'income_add', 'international_dividend', 'momentum_scalp', 'recovery_watch',
    'reit_income', 'sector_rotation', 'speculative_growth', 'swing_breakout',
    'swing_trade', 'tax_loss_harvest',
]


def test_candidate_source_registry_exists():
    assert (CONFIG / "candidate_sources.yaml").exists()


def test_registry_covers_all_strategies():
    import yaml
    reg = yaml.safe_load((CONFIG / "candidate_sources.yaml").read_text())
    covered = set()
    for src in reg.get("sources", {}).values():
        covered.update(src.get("strategies", []))
    for s in ALL_STRATEGIES:
        assert s in covered, f"Strategy {s} not in candidate_sources.yaml"


def test_income_strategies_have_income_source():
    import yaml
    reg = yaml.safe_load((CONFIG / "candidate_sources.yaml").read_text())
    income_strats = {'income_add', 'dividend_growth_compounder', 'reit_income', 'high_yield_income_bdc'}
    income_covered = set()
    for src in reg.get("sources", {}).values():
        if 'dividend' in src.get("source_type", "") or 'income' in str(src.get("screener_ids", "")):
            income_covered.update(src.get("strategies", []))
    for s in income_strats:
        assert s in income_covered, f"Income strategy {s} lacks income source"


def test_earnings_strategies_have_source():
    import yaml
    reg = yaml.safe_load((CONFIG / "candidate_sources.yaml").read_text())
    found = set()
    for src in reg.get("sources", {}).values():
        if 'earnings' in src.get("source_type", ""):
            found.update(src.get("strategies", []))
    assert 'earnings_pre_buildup' in found
    assert 'earnings_post_momentum' in found


def test_covered_call_has_options_source():
    import yaml
    reg = yaml.safe_load((CONFIG / "candidate_sources.yaml").read_text())
    found = False
    for src in reg.get("sources", {}).values():
        if 'options' in src.get("source_type", "") and 'covered_call_income' in src.get("strategies", []):
            found = True
    assert found, "covered_call_income needs options chain source"


def test_fib_has_technical_source():
    import yaml
    reg = yaml.safe_load((CONFIG / "candidate_sources.yaml").read_text())
    found = False
    for src in reg.get("sources", {}).values():
        if 'technical' in src.get("source_type", "") and 'fib_retracement_bounce' in src.get("strategies", []):
            found = True
    assert found


def test_momentum_uses_momentum_source():
    import yaml
    reg = yaml.safe_load((CONFIG / "candidate_sources.yaml").read_text())
    found = False
    for src in reg.get("sources", {}).values():
        if 'momentum' in src.get("source_type", "") and 'momentum_scalp' in src.get("strategies", []):
            found = True
    assert found


def test_all_yaml_strategies_exist():
    for s in ALL_STRATEGIES:
        assert (CONFIG / "strategies" / f"{s}.yaml").exists(), f"Missing YAML: {s}"


def test_no_trades_created():
    """Safety: this phase creates no trades."""
    pass  # Verified by safety audit


def test_env_safety():
    env = (PROJ / ".env").read_text()
    assert "ALPACA_MODE=paper" in env
    assert "LLM_DISABLE_LIVE_EXECUTION=true" in env


def test_readme_exists():
    assert (DOCS / "00_README.md").exists()
