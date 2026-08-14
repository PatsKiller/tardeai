"""Research governance — retrieval contract dry tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import retrieval_contract as rc  # noqa: E402
from scripts.lib.research_governance.enums import (  # noqa: E402
    EvidenceGrade,
    EvidenceType,
    InfluenceClass,
    ResearchStatus,
)
from scripts.lib.research_governance.models import ResearchEvidence  # noqa: E402


def _valid(**overrides):
    kw = dict(
        fact_id="f1", fact="fact", source_id="s1",
        evidence_type=EvidenceType.SOURCE_NARRATIVE,
        research_status=ResearchStatus.SOURCE_CLAIM,
        evidence_grade=EvidenceGrade.C,
        influence_class=InfluenceClass.CONTEXT_MODIFIER,
    )
    kw.update(overrides)
    return ResearchEvidence(**kw)


def test_valid_evidence_passes():
    assert rc.validate_retrieval_result(_valid()) == []


def test_missing_required_field_fails():
    ev = _valid()
    ev.fact_id = ""
    problems = rc.validate_retrieval_result(ev)
    assert any("fact_id" in p for p in problems)


def test_oos_with_low_grade_fails():
    ev = _valid(
        research_status=ResearchStatus.OOS_SUPPORTED,
        evidence_grade=EvidenceGrade.D,
        reproduction_ids=["r1"],
    )
    problems = rc.validate_retrieval_result(ev)
    assert any("OOS_SUPPORTED requires" in p for p in problems)


def test_reproduced_requires_reproduction_ids():
    ev = _valid(
        research_status=ResearchStatus.IN_SAMPLE_REPRODUCED,
        evidence_grade=EvidenceGrade.B,
    )
    problems = rc.validate_retrieval_result(ev)
    assert any("reproduction_ids" in p for p in problems)


def test_protocol_surface_present():
    assert hasattr(rc, "ResearchRetriever")
    for method in ("retrieve", "retrieve_by_source", "search_contradictions"):
        assert hasattr(rc.ResearchRetriever, method)
