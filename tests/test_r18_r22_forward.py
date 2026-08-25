"""R18–R22 forward program: source/shadow only. Activation OFF. No LIVE fabrication."""
from __future__ import annotations

from scripts.lib.cio_forward_program import (
    ACTIVATION,
    refuse_mixed_maturity,
    gated_live_run,
    identity_roll_up,
    live_activation_allowed,
)
from scripts.lib.r18_calibration_fabric import (
    calibration_observation,
    cohort_aggregate,
    decision_quality_profile,
)
from scripts.lib.r19_learning_engine import advance_learning_stage, build_learning_record
from scripts.lib.r20_universe_propagation import impact_candidates
from scripts.lib.r21_portfolio_cognition import portfolio_cognition
from scripts.lib.r22_cio_loop import cio_loop_cycle
from scripts.lib.transferson_universe import build_universe


def _manifest():
    return build_universe(sources={
        "holdings": ["NOC", "RTX"],
        "symbol_profiles": [
            {"symbol": "NOC", "sector": "Industrials", "industry": "Aerospace", "company": "Northrop",
             "source": "yfinance", "updated_at": "2026-08-20T00:00:00+00:00"},
            {"symbol": "RTX", "sector": "Industrials", "industry": "Aerospace", "company": "RTX Corp",
             "source": "yfinance", "updated_at": "2026-08-20T00:00:00+00:00"},
            {"symbol": "LMT", "sector": "Industrials", "industry": "Aerospace", "company": "Lockheed",
             "source": "yfinance", "updated_at": "2026-08-20T00:00:00+00:00"},
            {"symbol": "AAPL", "sector": "Technology", "industry": "Consumer Electronics", "company": "Apple",
             "source": "yfinance", "updated_at": "2026-08-20T00:00:00+00:00"},
        ],
        "graph_profiles": [
            {"symbol": "NOC", "catalyst_guids": ["cat-e"], "security_guid": "sec-noc"},
            {"symbol": "RTX", "catalyst_guids": ["cat-e"], "security_guid": "sec-rtx"},
        ],
        "trs": [
            {"symbol": "NOC", "security_guid": "sec-noc"},
            {"symbol": "RTX", "security_guid": "sec-rtx"},
        ],
        "screener_active": [],
        "discovery_validated": [],
    })


def test_all_forward_activation_off() -> None:
    assert all(v is False for v in ACTIVATION.values())
    assert live_activation_allowed("R18") is False
    live = gated_live_run("R18", evidence_class="LIVE")
    assert live["ok"] is False
    assert live["reason"] == "LIVE_ACTIVATION_OFF"


def test_evidence_classes_not_mixed_into_maturity() -> None:
    g = refuse_mixed_maturity(["UNIT_TEST", "GOLDEN_SHADOW"])
    assert g["mixed"] is True
    assert g["may_not_blend_into_one_maturity_number"] is True


def test_identity_roll_up_never_mints_from_ticker() -> None:
    bare = identity_roll_up({"symbol": "NVDA"})
    assert bare["unresolved"] is True
    assert bare["security_guid"] is None
    resolved = identity_roll_up({"symbol": "NOC", "security_guid": "sec-noc"})
    assert resolved["security_guid"] == "sec-noc"
    assert resolved["ticker_guid_is_not_security"] is True


def test_r18_tiny_sample_is_not_truth() -> None:
    obs = []
    for i in range(3):
        obs.append(calibration_observation(
            outcome={"outcome_id": f"o{i}", "decision_id": f"d{i}", "observed_quality": 0.8, "horizon": "5_sessions"},
            decision={"decision_id": f"d{i}", "recommendation": "HOLD", "confidence": 0.9, "security_guid": "sec-noc"},
            universe_row={"symbol": "NOC", "security_guid": "sec-noc", "sector": "Industrials"},
            evidence_class="GOLDEN_SHADOW",
        ))
    cohort = cohort_aggregate(obs, "security_guid", evidence_class="GOLDEN_SHADOW")
    assert cohort["tiny_samples_are_not_truth"] is True
    assert cohort["cohorts"][0]["sufficient_for_truth"] is False
    assert cohort["cohorts"][0]["mean_quality"] is None
    prof = decision_quality_profile(obs, subject_guid="sec-noc", evidence_class="GOLDEN_SHADOW")
    assert prof["sufficient_for_truth"] is False


def test_r18_unresolved_excluded_from_cohort() -> None:
    row = calibration_observation(
        outcome={"outcome_id": "o1", "decision_id": "d1", "observed_quality": 0.9},
        decision={"decision_id": "d1", "symbol": "ZZZ", "recommendation": "WATCH"},
        universe_row={"symbol": "ZZZ", "identity_status": "UNRESOLVED_WITH_REASON"},
        evidence_class="UNIT_TEST",
    )
    assert row["unresolved_identity"] is True
    cohort = cohort_aggregate([row], "security_guid", evidence_class="UNIT_TEST")
    assert cohort["unresolved_excluded"] == 1
    assert cohort["cohorts"] == []


def test_r19_cannot_self_authorize() -> None:
    rec = build_learning_record(
        decision={"decision_id": "d1", "recommendation": "HOLD", "security_guid": "sec-noc", "runtime_source_sha": "abc"},
        outcome={"outcome_id": "o1", "decision_id": "d1", "security_guid": "sec-noc"},
        statement="high-confidence HOLD after defense catalyst tended to be timely",
        supporting_outcome_ids=[f"o{i}" for i in range(6)],
        counterexamples=[],
        searched_counterexamples=True,
        evidence_class="GOLDEN_SHADOW",
        universe_row={"symbol": "NOC", "sector": "Industrials", "industry": "Aerospace"},
    )
    assert rec["stage"] == "CANDIDATE"
    assert rec["auto_policy"] is False
    blocked = advance_learning_stage(rec, "OPERATOR_AUTHORIZED")
    assert blocked["ok"] is False
    assert blocked["reason"] == "PROMOTION_REQUIRES_SEPARATE_AUTHORITY"
    shadow = advance_learning_stage(rec, "SHADOW")
    assert shadow["ok"] is True
    assert shadow["stage"] == "SHADOW"
    ev = advance_learning_stage(
        shadow, "EVALUATED",
        control=[{"observed_quality": 0.5}] * 8,
        candidate=[{"observed_quality": 0.7}] * 8,
    )
    assert ev["ok"] is True
    assert ev["experiment"]["trading"] is False
    ready = advance_learning_stage(ev, "REVIEW_READY", control=[{"observed_quality": 0.5}]*8, candidate=[{"observed_quality": 0.7}]*8)
    assert ready["stage"] == "REVIEW_READY"


def test_r20_impact_is_bounded_and_not_supply_chain() -> None:
    m = _manifest()
    out = impact_candidates(m, "NOC", evidence_class="UNIT_TEST", materiality=0.8, max_n=10)
    assert out["auto_research_entire_universe"] is False
    assert out["not_supply_chain_from_shared_sector"] is True
    assert out["n"] <= 10
    assert any(c["symbol"] == "RTX" for c in out["candidates"])
    assert all("industry" in c["paths"] or "sector" in c["paths"] or "catalyst" in c["paths"] or "security" in c["paths"] for c in out["candidates"])


def test_r21_portfolio_cognition_is_advisory() -> None:
    m = _manifest()
    out = portfolio_cognition(m, held_symbols=["NOC", "RTX"], evidence_class="UNIT_TEST")
    assert out["advisory_only"] is True
    assert out["graph_proximity_is_not_an_action"] is True
    assert out["financial_action"] is False
    assert "Industrials" in out["duplicated_sector_exposure"]
    assert any(s["held"] == "NOC" for s in out["substitutes"])


def test_r22_loop_is_not_autonomous_trading() -> None:
    loop = cio_loop_cycle(evidence_class="SOURCE_ONLY", answers={"what_changed": "none"})
    assert loop["autonomous_trading"] is False
    assert loop["execution_separately_authorized"] is True
    assert "what_we_are_learning" in loop["questions"]
    assert loop["activated"] is False


def test_forward_modules_have_no_hardcoded_universe_denominators() -> None:
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "scripts/lib"
    banned = ("5409", "3105", "120", "126")
    for name in (
        "cio_forward_program.py",
        "r18_calibration_fabric.py",
        "r19_learning_engine.py",
        "r20_universe_propagation.py",
        "r21_portfolio_cognition.py",
        "r22_cio_loop.py",
        "cio_office_synthesizer.py",
        "institutional_knowledge_fabric.py",
        "investment_theory_engine.py",
        "reference_brain_audit.py",
    ):
        text = (root / name).read_text()
        for token in banned:
            assert token not in text, f"{name} contains banned denominator {token}"
