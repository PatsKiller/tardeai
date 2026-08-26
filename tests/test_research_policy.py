"""R7 policy / regulatory + behavioral framework dry tests."""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.research_governance.behavioral import (  # noqa: E402
    AUTHORITY as BEHAVIORAL_AUTHORITY,
)
from scripts.lib.research_governance.behavioral import FRAMES, as_research_evidence as behavioral_evidence  # noqa: E402
from scripts.lib.research_governance.behavioral import bundle  # noqa: E402
from scripts.lib.research_governance.enums import (  # noqa: E402
    EvidenceGrade,
    EvidenceType,
    GateState,
    InfluenceClass,
    ResearchStatus,
)
from scripts.lib.research_governance.policy import AUTHORITY as POLICY_AUTHORITY  # noqa: E402
from scripts.lib.research_governance.policy import (  # noqa: E402
    POLICY_TYPE_GATE_KEYS,
    PolicyRule,
    as_research_evidence,
    evaluate_policy,
    promotion_ctx,
)
from scripts.lib.research_governance.promotion_gate import run_promotion_gate  # noqa: E402
from scripts.lib.research_governance.r7_acceptance import (  # noqa: E402
    CHECKS,
    check_policy_behavioral,
    complete_policy_rule,
)
from scripts.lib.research_governance.source_catalog import load_sources  # noqa: E402

_TYPE_KEYS = (
    "authoritative_source",
    "effective_date",
    "jurisdiction",
    "verified_at",
    "current_as_of",
    "next_reverify_at",
    "future_effective",
)


def test_authority_is_read_only_advisory():
    assert POLICY_AUTHORITY == "READ_ONLY_ADVISORY"
    assert BEHAVIORAL_AUTHORITY == "READ_ONLY_ADVISORY"


def test_complete_policy_evaluates_ok():
    evaluation = evaluate_policy(complete_policy_rule())
    assert evaluation["status"] == "OK"
    assert evaluation["reason"]
    assert isinstance(evaluation["ctx"], dict)


def test_promotion_type_gates_pass_when_complete():
    ctx = promotion_ctx(complete_policy_rule())
    for key in _TYPE_KEYS:
        assert key in ctx
    report = run_promotion_gate(ctx)
    for key in POLICY_TYPE_GATE_KEYS:
        assert report["gate_results"][key]["state"] == GateState.PASS.value, report["gate_results"][key]


def test_missing_jurisdiction_unavailable_and_type_gate_fails():
    rule = replace(complete_policy_rule(), jurisdiction="")
    evaluation = evaluate_policy(rule)
    assert evaluation["status"] == "UNAVAILABLE"
    assert "jurisdiction" in evaluation["reason"]
    report = run_promotion_gate(promotion_ctx(rule))
    assert report["gate_results"]["jurisdiction"]["state"] == GateState.FAIL.value


def test_missing_effective_date_unavailable():
    rule = replace(complete_policy_rule(), effective_date="")
    evaluation = evaluate_policy(rule)
    assert evaluation["status"] == "UNAVAILABLE"
    assert "effective_date" in evaluation["reason"]


def test_missing_authoritative_source_unavailable():
    rule = replace(complete_policy_rule(), authoritative_source="  ")
    evaluation = evaluate_policy(rule)
    assert evaluation["status"] == "UNAVAILABLE"
    assert "authoritative_source" in evaluation["reason"]


def test_future_effective_without_flag_unavailable():
    rule = replace(
        complete_policy_rule(),
        effective_date="2027-01-01",
        current_as_of="2026-08-01",
        future_effective=False,
    )
    evaluation = evaluate_policy(rule)
    assert evaluation["status"] == "UNAVAILABLE"
    report = run_promotion_gate(promotion_ctx(rule))
    assert report["gate_results"]["freshness"]["state"] == GateState.FAIL.value


def test_future_effective_declared_ok():
    rule = replace(
        complete_policy_rule(),
        effective_date="2027-01-01",
        current_as_of="2026-08-01",
        next_reverify_at="2027-06-01",
        future_effective=True,
    )
    evaluation = evaluate_policy(rule)
    assert evaluation["status"] == "OK"
    report = run_promotion_gate(promotion_ctx(rule))
    assert report["gate_results"]["freshness"]["state"] == GateState.PASS.value


def test_stale_reverify_unavailable():
    rule = replace(
        complete_policy_rule(),
        current_as_of="2026-08-01",
        next_reverify_at="2026-01-01",
    )
    evaluation = evaluate_policy(rule)
    assert evaluation["status"] == "UNAVAILABLE"
    assert "overdue" in evaluation["reason"]
    report = run_promotion_gate(promotion_ctx(rule))
    assert report["gate_results"]["freshness"]["state"] == GateState.FAIL.value


def test_as_research_evidence_grades_and_role():
    rule = complete_policy_rule()
    ok = evaluate_policy(rule)
    ev = as_research_evidence(rule, ok)
    assert ev.evidence_type == EvidenceType.POLICY_OR_REGULATORY
    assert ev.influence_class == InfluenceClass.CONTEXT_MODIFIER
    assert ev.evidence_grade == EvidenceGrade.C
    assert ev.role_in_decision == "risk_modifier_or_context"
    bad = as_research_evidence(rule, evaluate_policy(replace(rule, jurisdiction="")))
    assert bad.evidence_grade == EvidenceGrade.D


def test_policy_rule_is_frozen():
    rule = complete_policy_rule()
    assert isinstance(rule, PolicyRule)
    try:
        rule.jurisdiction = "XX"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("PolicyRule must be frozen")


def test_behavioral_bundle_citation_only_no_trim_no_partisan():
    pack = bundle()
    assert pack["authority"] == "READ_ONLY_ADVISORY"
    assert pack["partisan_conclusion"] is None
    assert pack["standalone_sell"] is False
    assert pack["creates_trim"] is False
    assert pack["citation_only"] is True
    assert pack["fulltext"] is False
    assert pack["influence"] == InfluenceClass.CONTEXT_MODIFIER.value
    assert pack["max_influence_pct"] <= 10.0


def test_behavioral_frames_are_catalog_source_ids():
    catalog = {s["source_id"] for s in load_sources()}
    expected = {
        "housel_psychology_of_money",
        "marks_most_important_thing",
        "malkiel_random_walk",
    }
    assert set(FRAMES) == expected
    pack = bundle()
    assert set(pack["frames"]) == expected
    for fid, meta in FRAMES.items():
        assert meta["source_id"] in catalog
        assert meta["citation_only"] is True
        assert meta["fulltext"] is False
        assert "Not a book extract" in meta["summary"]
        assert "p." not in meta["summary"].lower()
        assert "page" not in meta["summary"].lower()
        frame = pack["frames"][fid]
        claim = frame["layers"]["source_claim"]
        assert claim["citation_only"] is True
        assert claim["fulltext"] is False
        assert claim["page_or_section"] is None
        ev = behavioral_evidence(fid)
        assert ev.evidence_type == EvidenceType.BEHAVIORAL_FRAMEWORK
        assert ev.research_status == ResearchStatus.SOURCE_CLAIM
        assert ev.evidence_grade == EvidenceGrade.D
        assert ev.influence_class == InfluenceClass.CONTEXT_MODIFIER


def test_r7a1_acceptance_check():
    state, detail = check_policy_behavioral()
    assert state == GateState.PASS.value, detail
    assert CHECKS == {"R7A-1": check_policy_behavioral}
