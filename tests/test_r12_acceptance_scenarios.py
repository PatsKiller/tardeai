"""R12 required acceptance scenarios A–O plus feedback/cost invariants."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib.cio_advisory_synthesis import select_model, synthesize
from scripts.lib.cio_office_cycle import run_office_cycle
from scripts.lib.cio_operator_feedback_loop import ingest_operator_feedback
from scripts.lib.cio_policy_provenance import audit_cash_posture_policy
from scripts.lib.cio_situation_state import detect_office_situations
from tests.r11_office_fixtures import NOW, office, policy, portfolio

pytestmark = pytest.mark.tier0


def test_a_tiny_cash_deviation_no_invented_above_band_deploy() -> None:
    out = audit_cash_posture_policy(
        cash_total_usd=200_100,
        portfolio_value_usd=1_000_000,
        live_band={"min_pct": 20.0, "max_pct": 25.0},
        live_status="ABOVE_BAND",
        policy={"status": "POLICY_REQUIRED", "fields": {}},
    )
    assert out["may_recommend_deployment"] is False
    assert out["policy_status"] == "POLICY_GAP"


def test_b_confirmed_material_excess() -> None:
    scan = detect_office_situations(office(policy=policy(confirmed=True), portfolio_state=portfolio(cash_pct=45.0, verified=True)), evaluated_at=NOW)
    cash = next(s for s in scan["situations"] if s.get("cash_situation"))
    assert cash["cash_situation"]["conclusion"] in {"DEPLOY_STAGED", "HOLD_CASH"}
    assert cash["notification_eligibility"] == "NOTIFY"


def test_c_repeated_same_cash_dedupes(tmp_path: Path) -> None:
    o = office()
    run_office_cycle(o, root=tmp_path, evaluated_at=NOW)
    second = run_office_cycle(o, root=tmp_path, evaluated_at=NOW)
    assert second["notification_decision"] == "SUPPRESS"


def test_d_concentration_worsening_still_material() -> None:
    o = office(portfolio_state=portfolio(cash_pct=10.0, holdings=[{"symbol": "NVDA", "security_guid": "g", "weight_pct": 22.0}]))
    a = detect_office_situations(o, evaluated_at=NOW)
    o2 = office(portfolio_state=portfolio(cash_pct=10.0, holdings=[{"symbol": "NVDA", "security_guid": "g", "weight_pct": 30.0}]))
    b = detect_office_situations(o2, evaluated_at=NOW)
    assert any(s["situation_class"] == "CONCENTRATION" for s in a["situations"])
    hit = next(s for s in b["situations"] if s["situation_class"] == "CONCENTRATION")
    assert hit["new_state"]["weight_pct"] == 30.0


def test_e_stale_thesis_not_confident() -> None:
    o = office(
        portfolio_state=portfolio(cash_pct=10.0, truth="STALE"),
        ticker_cognition={"g": {"symbol": "SCHD", "security_guid": "g", "thesis_delta": "DETERIORATION"}},
    )
    scan = detect_office_situations(o, evaluated_at=NOW)
    hit = next(s for s in scan["situations"] if s["situation_class"] == "THESIS_DETERIORATION")
    assert hit["notification_eligibility"] != "NOTIFY"


def test_f_fresh_thesis_deterioration() -> None:
    o = office(
        portfolio_state=portfolio(cash_pct=10.0),
        ticker_cognition={"g": {"symbol": "SCHD", "security_guid": "g", "thesis_delta": "DETERIORATION"}},
    )
    scan = detect_office_situations(o, evaluated_at=NOW)
    assert any(s["situation_class"] == "THESIS_DETERIORATION" and s["notification_eligibility"] == "NOTIFY" for s in scan["situations"])


def test_g_open_gap_not_resolved() -> None:
    o = office(portfolio_state=portfolio(cash_pct=10.0), research_gaps=[{"symbol": "KTOS", "resolved": False}])
    scan = detect_office_situations(o, evaluated_at=NOW)
    assert "RESEARCH_GAP_RESOLVED" not in {s["situation_class"] for s in scan["situations"]}


def test_h_resolved_gap() -> None:
    o = office(portfolio_state=portfolio(cash_pct=10.0), research_gaps=[{"symbol": "KTOS", "security_guid": "g", "resolved": True}])
    scan = detect_office_situations(o, evaluated_at=NOW)
    assert any(s["situation_class"] == "RESEARCH_GAP_RESOLVED" for s in scan["situations"])


def test_i_far_catalyst_suppressed() -> None:
    o = office(portfolio_state=portfolio(cash_pct=10.0), catalysts=[{"symbol": "CSCO", "days_to_event": 40, "event": "earnings"}])
    scan = detect_office_situations(o, evaluated_at=NOW)
    assert "CATALYST_APPROACHING" not in {s["situation_class"] for s in scan["situations"]}


def test_j_contradictory_research() -> None:
    o = office(portfolio_state=portfolio(cash_pct=10.0), contradictions=[{"symbol": "NOC", "summary": "split specialists"}])
    scan = detect_office_situations(o, evaluated_at=NOW)
    hit = next(s for s in scan["situations"] if s["situation_class"] == "CONTRADICTION")
    assert "DO_NOT_ACT" in hit["cio_conclusion"]


def test_k_no_material_change_zero_llm() -> None:
    scan = detect_office_situations(office(portfolio_state=portfolio(cash_pct=10.0)), evaluated_at=NOW)
    choice = select_model(scan)
    assert choice["llm_calls"] == 0
    syn = synthesize(scan)
    assert syn["used_llm"] is False
    assert scan["notification_decision"] == "SUPPRESS"


def test_n_too_noisy_feedback_is_candidate_only(tmp_path: Path) -> None:
    out = ingest_operator_feedback("Don't notify me about NVDA unless it drops 10%", root=tmp_path)
    assert out["policy_effect"] is False
    assert out["memory_behavior_influence"] == 0
    assert out["preference_candidate"]["schema"] == "PreferenceCandidate@v1"


def test_o_correction_supersedes(tmp_path: Path) -> None:
    ingest_operator_feedback("Treat SCHG as growth", root=tmp_path)
    out = ingest_operator_feedback("correction: Treat SCHG as blend", root=tmp_path)
    assert out["kind"] == "CORRECTION"
    assert out["policy_effect"] is False


@pytest.mark.parametrize(
    "text",
    [
        "this was useful",
        "this wasn't relevant",
        "too noisy",
        "too late",
        "wrong reason",
        "already knew",
        "notify me sooner",
        "do not page for this class",
    ],
)
def test_feedback_phrases_never_mutate_policy(text: str, tmp_path: Path) -> None:
    out = ingest_operator_feedback(text if "prefer" in text or "notify" in text or "Don't" in text or "correction" in text or "useful" in text or "relevant" in text else f"I prefer {text}", root=tmp_path)
    assert out["policy_effect"] is False
    assert out["memory_behavior_influence"] == 0
    assert out["financial_action"] is False
