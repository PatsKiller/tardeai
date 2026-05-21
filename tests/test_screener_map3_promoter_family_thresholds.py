"""Tests for SCREENER-MAP-3 promoter family thresholds."""
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def test_policy_compiles():
    import importlib
    mod = importlib.import_module("promoter_family_threshold_policy")
    assert hasattr(mod, "evaluate_candidate")
    assert hasattr(mod, "get_family_thresholds")


def test_dividend_no_momentum_gap():
    from promoter_family_threshold_policy import get_family_thresholds
    th = get_family_thresholds("income_add")
    assert th["require_catalyst"] is False
    assert th["min_rvol"] == 0.0
    assert th["max_spread_pct"] >= 5.0


def test_dividend_allows_wide_spread():
    from promoter_family_threshold_policy import evaluate_candidate
    result = evaluate_candidate({"spread_pct": 6.0, "rvol": 0.5, "score": 15}, "income_add")
    assert result["readiness_status"] in ("READY_SHADOW", "NEEDS_DATA")


def test_earnings_requires_date():
    from promoter_family_threshold_policy import get_family_thresholds
    th = get_family_thresholds("earnings_pre_buildup")
    assert th["require_earnings_date"] is True


def test_earnings_blocked_without_date():
    from promoter_family_threshold_policy import evaluate_candidate
    result = evaluate_candidate({"score": 30, "rvol": 2.0}, "earnings_pre_buildup")
    assert result["readiness_status"] == "BLOCKED"
    assert any("earnings" in f for f in result["failed"])


def test_options_requires_chain():
    from promoter_family_threshold_policy import get_family_thresholds
    th = get_family_thresholds("covered_call_income")
    assert th["require_options_chain"] is True


def test_options_provider_missing():
    from promoter_family_threshold_policy import evaluate_candidate
    result = evaluate_candidate({"score": 20}, "covered_call_income")
    assert result["readiness_status"] == "PROVIDER_MISSING"


def test_momentum_strict():
    from promoter_family_threshold_policy import get_family_thresholds
    th = get_family_thresholds("momentum_scalp")
    assert th["max_spread_pct"] <= 3.0
    assert th["min_rvol"] >= 3.0
    assert th["require_catalyst"] is True


def test_all_outputs_shadow():
    from promoter_family_threshold_policy import evaluate_candidate
    result = evaluate_candidate({"score": 50, "rvol": 5.0, "catalyst": True}, "momentum_scalp")
    assert result["human_review_only"] is True
    assert result["proposal_eligible"] is False


def test_env_safety():
    env = (PROJ / ".env").read_text()
    assert "ALPACA_MODE=paper" in env
    assert "LLM_DISABLE_LIVE_EXECUTION=true" in env
