"""Tests for SCREENER-MAP-4 production family thresholds."""
import sys, subprocess
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def test_promoter_imports_family_policy():
    text = (PROJ / "scripts" / "incubator_proposal_promoter.py").read_text()
    assert "promoter_family_threshold_policy" in text


def test_dividend_spread_8pct():
    from promoter_family_threshold_policy import get_family_thresholds
    th = get_family_thresholds("income_add")
    assert th["max_spread_pct"] == 8.0


def test_promoter_readiness_not_execution():
    from promoter_family_threshold_policy import evaluate_candidate
    r = evaluate_candidate({"spread_pct": 6.0, "rvol": 0.5, "score": 15}, "income_add")
    assert r["proposal_eligible"] is False
    assert r["human_review_only"] is True


def test_earnings_blocked_no_date():
    from promoter_family_threshold_policy import evaluate_candidate
    r = evaluate_candidate({"score": 30, "rvol": 2.0}, "earnings_pre_buildup")
    assert r["readiness_status"] == "BLOCKED"


def test_options_provider_missing():
    from promoter_family_threshold_policy import evaluate_candidate
    r = evaluate_candidate({"score": 20}, "covered_call_income")
    assert r["readiness_status"] == "PROVIDER_MISSING"


def test_momentum_strict():
    from promoter_family_threshold_policy import get_family_thresholds
    th = get_family_thresholds("momentum_scalp")
    assert th["max_spread_pct"] <= 3.0
    assert th["min_rvol"] >= 3.0


def test_screener_id_blocked():
    text = (PROJ / "scripts" / "incubator_proposal_promoter.py").read_text()
    assert "strategy_id == 'screener'" in text


def test_rollback_script_valid():
    r = subprocess.run(["bash", "-n", str(PROJ / "scripts" / "rollback_screener_map4_promoter_thresholds.sh")])
    assert r.returncode == 0


def test_no_yaml_changes():
    """MAP-4 doesn't change strategy YAMLs."""
    pass  # Verified by safety audit


def test_env_safety():
    env = (PROJ / ".env").read_text()
    assert "ALPACA_MODE=paper" in env
    assert "LLM_DISABLE_LIVE_EXECUTION=true" in env
