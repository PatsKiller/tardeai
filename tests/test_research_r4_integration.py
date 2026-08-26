"""R4 retrieval adapter + decision-use audit + degradation dry tests."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.research_governance import acceptance  # noqa: E402
from scripts.lib.research_governance.cio_retriever_adapter import retrieve_for_decision  # noqa: E402
from scripts.lib.research_governance.decision_use_audit import (  # noqa: E402
    DecisionUseLedger,
    is_authentic_audit,
)
from scripts.lib.research_governance.degradation import apply_degradation, evaluate_fact  # noqa: E402
from scripts.lib.research_governance.enums import (  # noqa: E402
    EvidenceGrade,
    EvidenceType,
    GateState,
    InfluenceClass,
    ResearchStatus,
)
from scripts.lib.research_governance.memory_retriever import InMemoryRetriever  # noqa: E402
from scripts.lib.research_governance.models import ResearchEvidence  # noqa: E402
from scripts.lib.research_governance.promotion_gate import run_promotion_gate  # noqa: E402
from scripts.lib.research_governance.retrieval_contract import ResearchQuery, ResearchRetriever  # noqa: E402


def test_memory_retriever_is_protocol():
    r = InMemoryRetriever()
    assert isinstance(r, ResearchRetriever)


def test_retrieve_for_decision_writes_audit():
    ledger = DecisionUseLedger()
    ev, rec = retrieve_for_decision(decision_id="dec_dry_1", ledger=ledger)
    assert ev
    assert rec.verify()
    assert is_authentic_audit(rec)
    assert rec.decision_id == "dec_dry_1"
    assert rec.influence_cap_pct <= 10.0
    assert "standalone_sell" in rec.forbidden_actions
    assert ledger.for_decision("dec_dry_1")


def test_live_use_without_audit_fails_rg10():
    ctx = {
        "source_id": "stock_traders_almanac",
        "evidence_type": EvidenceType.SEASONALITY.value,
        "evidence_grade": EvidenceGrade.C.value,
        "influence_class": InfluenceClass.CONTEXT_MODIFIER.value,
        "live_research_use": True,
    }
    rep = run_promotion_gate(ctx)
    assert rep["gate_results"]["RG-10"]["state"] == GateState.FAIL.value
    assert rep["gate_results"]["RG-11"]["state"] == GateState.FAIL.value


def test_live_use_with_audit_and_degradation_passes_rg10_11():
    ledger = DecisionUseLedger()
    ev, rec = retrieve_for_decision(decision_id="dec_dry_2", ledger=ledger)
    deg = evaluate_fact(ev[0])
    ctx = {
        "source_id": "stock_traders_almanac",
        "evidence_type": EvidenceType.SEASONALITY.value,
        "evidence_grade": EvidenceGrade.C.value,
        "influence_class": InfluenceClass.CONTEXT_MODIFIER.value,
        "live_research_use": True,
        "decision_use_audit": rec,
        "degradation_decision": {"action": deg.action, "reason": deg.reason},
    }
    rep = run_promotion_gate(ctx)
    assert rep["gate_results"]["RG-10"]["state"] == GateState.PASS.value
    assert rep["gate_results"]["RG-11"]["state"] == GateState.PASS.value


def test_degrade_consumed_oos():
    e = ResearchEvidence(
        fact_id="oos1", fact="x", source_id="stock_traders_almanac",
        evidence_type=EvidenceType.SEASONALITY,
        research_status=ResearchStatus.OOS_SUPPORTED,
        evidence_grade=EvidenceGrade.B,
        influence_class=InfluenceClass.CONTEXT_MODIFIER,
        reproduction_ids=["r"],
    )
    d = evaluate_fact(e, oos_consumed=True)
    assert d.action == "degrade"
    apply_degradation(e, d)
    assert e.research_status != ResearchStatus.OOS_SUPPORTED


def test_retire_grade_x():
    e = ResearchEvidence(
        fact_id="x", fact="bad", source_id="stock_traders_almanac",
        evidence_type=EvidenceType.SEASONALITY,
        research_status=ResearchStatus.FAILED_REPRODUCTION,
        evidence_grade=EvidenceGrade.X,
        influence_class=InfluenceClass.CONTEXT_MODIFIER,
    )
    d = evaluate_fact(e)
    assert d.action == "retire"
    apply_degradation(e, d)
    assert e.research_status == ResearchStatus.RETIRED


def test_query_roundtrip():
    e = ResearchEvidence(
        fact_id="f1", fact="September seasonality", source_id="stock_traders_almanac",
        evidence_type=EvidenceType.SEASONALITY,
        research_status=ResearchStatus.IN_SAMPLE_REPRODUCED,
        evidence_grade=EvidenceGrade.C,
        influence_class=InfluenceClass.CONTEXT_MODIFIER,
        reproduction_ids=["r3-september_general"],
    )
    store = InMemoryRetriever([e])
    hits = store.retrieve(ResearchQuery(free_text="September", max_facts=5))
    assert hits and hits[0].fact_id == "f1"


def test_r4_acceptance_profile():
    rep = acceptance.run_acceptance("R4_integration")
    assert "RGA-15" in rep["required_runtime_pass"], rep
    assert "RGA-16" in rep["required_runtime_pass"], rep
    assert rep["overall"] == "PASS", rep


def test_r1_still_does_not_require_r3_r4():
    rep = acceptance.run_acceptance("R1_foundation")
    assert "RGA-15" in rep["not_in_scope"]
    assert "RGA-16" in rep["not_in_scope"]
    assert rep["overall"] == "PASS"
