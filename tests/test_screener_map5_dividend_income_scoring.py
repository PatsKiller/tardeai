"""Tests for SCREENER-MAP-5 dividend income scoring."""
import sys
from pathlib import Path
PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def test_scoring_compiles():
    from dividend_income_scoring_policy import score_dividend_income_candidate
    assert callable(score_dividend_income_candidate)


def test_yield_contributes():
    from dividend_income_scoring_policy import score_dividend_income_candidate
    r = score_dividend_income_candidate({"dividend_yield": 4.0})
    assert r["score_breakdown"]["yield"] >= 15


def test_high_yield_not_max():
    from dividend_income_scoring_policy import score_dividend_income_candidate
    r = score_dividend_income_candidate({"dividend_yield": 15.0})
    assert r["score_breakdown"]["yield"] <= 15
    assert r["yield_trap_warning"] is True


def test_excessive_yield_review():
    from dividend_income_scoring_policy import score_dividend_income_candidate
    r = score_dividend_income_candidate({"dividend_yield": 15.0})
    assert r["readiness_status"] == "REVIEW_REQUIRED"


def test_payout_contributes():
    from dividend_income_scoring_policy import score_dividend_income_candidate
    r = score_dividend_income_candidate({"payout_ratio": 50})
    assert r["score_breakdown"]["payout"] >= 15


def test_missing_yield_warns():
    from dividend_income_scoring_policy import score_dividend_income_candidate
    r = score_dividend_income_candidate({"symbol": "TEST"})
    assert "dividend_yield" in r["missing_fields"]


def test_score_floor_15():
    from dividend_income_scoring_policy import SCORE_FLOOR
    assert SCORE_FLOOR == 15


def test_floor_not_30():
    from promoter_family_threshold_policy import get_family_thresholds
    th = get_family_thresholds("income_add")
    assert th["min_score"] == 15


def test_spread_still_8():
    from promoter_family_threshold_policy import get_family_thresholds
    th = get_family_thresholds("income_add")
    assert th["max_spread_pct"] == 8.0


def test_readiness_not_approval():
    from dividend_income_scoring_policy import score_dividend_income_candidate
    r = score_dividend_income_candidate({"dividend_yield": 5.0, "current_price": 50.0,
        "enrichment": {"pe": 15, "market_cap_b": 10, "avg_vol_m": 5}})
    assert r["human_review_only"] is True
    assert r["proposal_eligible"] is False


def test_env_safety():
    env = (PROJ / ".env").read_text()
    assert "ALPACA_MODE=paper" in env
    assert "LLM_DISABLE_LIVE_EXECUTION=true" in env
