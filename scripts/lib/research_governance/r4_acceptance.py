"""RGA-16 research decision-use audit acceptance."""
from __future__ import annotations

from .almanac import as_research_evidence, bundle
from .cio_retriever_adapter import retrieve_for_decision
from .decision_use_audit import DecisionUseLedger, FORBIDDEN_ACTIONS, is_authentic_audit
from .degradation import apply_degradation, evaluate_fact
from .enums import EvidenceGrade, EvidenceType, GateState, InfluenceClass, ResearchStatus
from .memory_retriever import InMemoryRetriever
from .models import ResearchEvidence
from .promotion_gate import run_promotion_gate
from .retrieval_contract import ResearchQuery, ResearchRetriever


def _pass(d: str) -> tuple[str, str]:
    return GateState.PASS.value, d


def _fail(d: str) -> tuple[str, str]:
    return GateState.FAIL.value, d


def check_decision_use_audit() -> tuple[str, str]:
    if not issubclass(InMemoryRetriever, ResearchRetriever) and not isinstance(InMemoryRetriever(), ResearchRetriever):
        # Protocol check via instance
        pass
    retr = InMemoryRetriever()
    if not isinstance(retr, ResearchRetriever):
        return _fail("InMemoryRetriever does not satisfy ResearchRetriever")
    ledger = DecisionUseLedger()
    ev, rec = retrieve_for_decision(decision_id="dec_r4_dry", ledger=ledger, as_of_year=2026)
    if not ev:
        return _fail("retrieve_for_decision returned no evidence")
    if not rec.verify() or not is_authentic_audit(rec):
        return _fail("audit record not authentic")
    if rec.influence_cap_pct > 10.0:
        return _fail("influence cap exceeded")
    if set(rec.forbidden_actions) < FORBIDDEN_ACTIONS:
        return _fail("forbidden actions incomplete")
    # Live use without audit must fail RG-10
    ctx = {
        "source_id": "stock_traders_almanac",
        "evidence_type": EvidenceType.SEASONALITY.value,
        "evidence_grade": EvidenceGrade.C.value,
        "influence_class": InfluenceClass.CONTEXT_MODIFIER.value,
        "live_research_use": True,
    }
    bare = run_promotion_gate(ctx)
    if bare["gate_results"]["RG-10"]["state"] != GateState.FAIL.value:
        return _fail("RG-10 must FAIL live use without audit")
    audited = run_promotion_gate(dict(
        ctx,
        decision_use_audit=rec,
        degradation_decision={"action": "keep", "reason": "fresh"},
    ))
    if audited["gate_results"]["RG-10"]["state"] != GateState.PASS.value:
        return _fail(f"RG-10 did not pass with audit: {audited['gate_results']['RG-10']}")
    if audited["gate_results"]["RG-11"]["state"] != GateState.PASS.value:
        return _fail("RG-11 did not pass with degradation decision")
    # Degradation retire X
    x = ResearchEvidence(
        fact_id="x1", fact="bad", source_id="stock_traders_almanac",
        evidence_type=EvidenceType.SEASONALITY, research_status=ResearchStatus.FAILED_REPRODUCTION,
        evidence_grade=EvidenceGrade.X, influence_class=InfluenceClass.CONTEXT_MODIFIER,
    )
    dec = evaluate_fact(x)
    if dec.action != "retire":
        return _fail("grade X must retire")
    apply_degradation(x, dec)
    if x.research_status != ResearchStatus.RETIRED:
        return _fail("retire did not set RETIRED")
    # Adapter must not claim execution
    if any(e.role_in_decision not in (None, "risk_modifier_or_context") for e in ev):
        return _fail("role escaped context modifier")
    q = ResearchQuery(calendar_context="seasonality", max_facts=5)
    pack = bundle(as_of_year=2026)
    store = InMemoryRetriever(as_research_evidence(s) for s in pack["slices"].values())
    hits = store.retrieve(q)
    if not hits:
        return _fail("memory retriever returned nothing")
    return _pass("decision-use audit, RG-10/11 live, degradation, retriever adapter")


CHECKS = {"RGA-16": check_decision_use_audit}
