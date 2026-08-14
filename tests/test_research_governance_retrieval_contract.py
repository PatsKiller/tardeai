"""Research governance — retrieval contract tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import retrieval_contract  # noqa: E402
from scripts.lib.research_governance.enums import (  # noqa: E402
    EvidenceGrade,
    EvidenceType,
    InfluenceClass,
    ResearchStatus,
)
from scripts.lib.research_governance.models import ResearchEvidence  # noqa: E402


def _evidence(**kw):
    base = dict(
        fact_id="f1", fact="a fact", source_id="s1",
        evidence_type=EvidenceType.SOURCE_NARRATIVE,
        research_status=ResearchStatus.SOURCE_CLAIM,
        evidence_grade=EvidenceGrade.D,
        influence_class=InfluenceClass.CONTEXT_MODIFIER,
    )
    base.update(kw)
    return ResearchEvidence(**base)


def test_protocol_declares_three_methods():
    assert hasattr(retrieval_contract.ResearchRetriever, "retrieve")
    assert hasattr(retrieval_contract.ResearchRetriever, "retrieve_by_source")
    assert hasattr(retrieval_contract.ResearchRetriever, "search_contradictions")


def test_valid_evidence_passes():
    assert retrieval_contract.validate_retrieval_result(_evidence()) == []


def test_oos_requires_grade_a_or_b():
    ev = _evidence(research_status=ResearchStatus.OOS_SUPPORTED,
                   evidence_grade=EvidenceGrade.D)
    problems = retrieval_contract.validate_retrieval_result(ev)
    assert any("grade" in p for p in problems)


def test_reproduced_requires_reproduction_ids():
    ev = _evidence(research_status=ResearchStatus.IN_SAMPLE_REPRODUCED,
                   evidence_grade=EvidenceGrade.A, reproduction_ids=[])
    problems = retrieval_contract.validate_retrieval_result(ev)
    assert any("reproduction_ids" in p for p in problems)


def test_missing_required_string_fails():
    ev = _evidence(fact_id="")
    assert retrieval_contract.validate_retrieval_result(ev)
