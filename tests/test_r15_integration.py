"""Integration: one delta through the full intelligence lifecycle."""
from __future__ import annotations

import pytest

from scripts.lib.cio_context_envelope_v2 import attach_v2, same_brain
from scripts.lib.cio_curation_run import (
    apply_material_version,
    build_curation_run,
    critique_before_memory,
    persist_curation_run,
)
from scripts.lib.cio_intelligence_fabric import (
    SAME_BRAIN_AGENTS,
    envelope_provider_statuses,
    lifecycle_projection,
    observe_from_scan,
    process_observation,
    same_brain_institutional,
)
from scripts.lib.cio_intelligence_outcomes import (
    lesson_candidate,
    link_research_decision,
    record_outcome,
    specialist_disagreement_memory,
)
from scripts.lib.cio_model_learning import record_performance, routing_candidate
from scripts.lib.cio_persistent_cognition import cross_agent_row
from scripts.lib.cio_r13_institution import specialist_artifact
from scripts.lib.free_first_circulation import circulate_symbol
from scripts.lib.security_identity import attach_identity_v2
from scripts.lib.ticker_knowledge_graph import build_profile, seed_profiles
from tests.r15_goldens import UNIVERSE, SYMBOLS

pytestmark = pytest.mark.tier0

VARIANTS = [
    {"id": f"I-{i:02d}", "symbol": SYMBOLS[i % len(SYMBOLS)], "hermes": i % 3 == 0, "unresolved": i % 5 == 0, "material": i % 2 == 0}
    for i in range(60)
]


def _hermes():
    return {
        "research": [{
            "id": 11, "topic": "defense", "summary": "backlog intact", "thesis": "HOLD durability",
            "status": "promoted", "research_type": "web",
            "source_urls_json": ["https://sec.gov/Archives/x"],
            "created_at": "2026-08-20T00:00:00+00:00",
        }],
        "external": [],
    }


@pytest.mark.parametrize("case", VARIANTS, ids=[c["id"] for c in VARIANTS])
def test_lifecycle_integration(case: dict, tmp_path) -> None:
    symbol = case["symbol"]
    profile = next(p for p in UNIVERSE if p["symbol"] == symbol)
    observation = {
        "source_domain": "catalysts",
        "source_ref": f"{symbol}-{case['id']}",
        "source_version": case["id"],
        "entity_guid": profile["ticker_guid"],
        "entity_type": "ticker",
        "change_type": "CATALYST",
        "before_hash": "0",
        "after_hash": case["id"] if case["material"] else "0",
        "material_fields_changed": case["material"],
        "freshness": "FRESH",
        "reason": "catalyst delta",
        "what_changed": "new catalyst evidence",
        "hermes_resolved": case["hermes"] and not case["unresolved"],
        "event_type": "CATALYST",
        "sector": profile.get("sector"),
        "industry": profile.get("industry"),
    }
    receipt = process_observation(tmp_path, observation, profiles=UNIVERSE)
    assert receipt["paid_dispatch"] == 0
    assert receipt["llm_calls"] == 0
    proj = lifecycle_projection(
        symbol=symbol,
        delta=receipt["delta"],
        impact=receipt["impact"],
        free_first=(receipt["wakes"][0]["free_first"] if receipt["wakes"] else None),
        unwired=["model_task_performance_live_n_below_min"],
    )
    assert proj["ingestion_bus"] is False
    assert proj["symbol"] == symbol
    run = build_curation_run(
        security_guid=profile.get("security_guid"),
        symbol=symbol,
        task_type="research_curation",
        prior_curation_id=None,
        prior_curation_version=0,
        evidence_delta_hash=case["id"],
        input_evidence_refs=["e1"],
        prompt_version="p1",
        process_id="hermes_external_research",
        requested_policy="FAST",
        executed_policy="FAST",
        model_id="deepseek-v4-flash",
        accepted=False,
        material_change=False,
    )
    critique = critique_before_memory(run)
    assert critique["may_admit"] is False
    persist_curation_run(tmp_path, run)
    status = envelope_provider_statuses({"OFFICE_TRUTH": {"ok": True}, "TICKER_RESEARCH_STATE": {"v": 1}})
    assert status["sections"]["OPERATOR_POLICY"] in {"NOT_CONFIGURED", "UNAVAILABLE", "EMPTY"}
    assert status["sections_total"] == 16
    link = link_research_decision(evidence_refs=["e1"], curation_id=None, thesis_id=None, decision_id=case["id"])
    out = record_outcome(decision_id=case["id"], outcome_id="o", elapsed=False)
    assert out["history_rewritten"] is False
    lesson = lesson_candidate(subject_guid="s", outcome_ids=["1"], statement="one trade")
    assert lesson["mature"] is False
    assert lesson["methodology_effect"] is False


def test_observe_from_scan_does_not_spend(tmp_path) -> None:
    scan = {
        "holdings_events": [{"symbol": "NVDA", "type": "WEIGHT_CHANGE", "as_of": "2026-08-25", "after_hash": "h1"}],
        "cash": {"cash_posture_status": "POLICY_GAP"},
        "at": "2026-08-25T00:00:00+00:00",
    }
    overlay = observe_from_scan(tmp_path, scan, profiles=UNIVERSE)
    assert overlay["paid_dispatch"] == 0
    assert overlay["llm_calls"] == 0
    assert overlay["memory_behavior_influence"] == 0


def test_specialist_same_brain_and_disagreement(tmp_path) -> None:
    seed_profiles(tmp_path, [{"symbol": "NOC", "company": "Northrop", "sector": "Industrials"}])
    circulate_symbol(
        tmp_path,
        attach_identity_v2(build_profile("NOC", metadata={"company": "Northrop"})),
        hermes_rows=_hermes(),
        rag_fn=lambda _s: {"ok": True, "supporting": [], "contradictory": []},
        allow_searx=False,
    )
    inst = same_brain_institutional(tmp_path, ["NOC"], held={"NOC"})
    assert inst["consistent"] is True
    assert inst["telegram_fork"] is False
    for agent in SAME_BRAIN_AGENTS:
        assert agent in inst["agents"]
    row = cross_agent_row(tmp_path, "NOC", held={"NOC"})
    assert row["consistent"] is True
    arts = [
        specialist_artifact(agent="guardian", claim="heat rising", evidence=["e"], confidence=0.4, uncertainty="data", contradictions=[], recommendation="TRIM"),
        specialist_artifact(agent="steph", claim="hold quality", evidence=["e"], confidence=0.6, uncertainty="data", contradictions=["guardian"], recommendation="HOLD"),
        specialist_artifact(agent="maria", claim="need filing", evidence=["e"], confidence=0.5, uncertainty="gap", contradictions=[], recommendation="RESEARCH"),
        specialist_artifact(agent="ledger", claim="tax lot wash", evidence=["e"], confidence=0.5, uncertainty="lots", contradictions=[], recommendation="HOLD"),
    ]
    mem = specialist_disagreement_memory(arts)
    assert mem["minority_overwritten"] is False
    assert mem["disagreements"]


def test_brain_same_brain_helpers_still_work(tmp_path) -> None:
    seed_profiles(tmp_path, [{"symbol": "NOC", "company": "Northrop", "sector": "Industrials"}])
    circulate_symbol(
        tmp_path,
        attach_identity_v2(build_profile("NOC", metadata={"company": "Northrop"})),
        hermes_rows=_hermes(),
        rag_fn=lambda _s: {"ok": True, "supporting": [], "contradictory": []},
        allow_searx=False,
    )
    sb = same_brain(tmp_path, ["NOC"], held={"NOC"})
    assert sb["consistent"] is True
    env = attach_v2({"office_truth": {}, "research_memory": {}}, {"cio_context_v2": {}})
    assert "cio_context_v2" in env["research_memory"]
