"""Research governance — enums + models dry tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance.enums import (  # noqa: E402
    EvidenceGrade,
    EvidenceType,
    GateState,
    InfluenceClass,
    ResearchStatus,
)
from scripts.lib.research_governance.models import (  # noqa: E402
    ResearchClaim,
    ResearchEvidence,
    ResearchHypothesis,
    ResearchSource,
    _stable_hash,
)


def test_enum_dimensions_are_orthogonal():
    assert EvidenceType.SEASONALITY != ResearchStatus.OOS_SUPPORTED
    assert ResearchStatus.OOS_SUPPORTED != EvidenceGrade.B
    # status is not a grade, grade is not a type
    assert ResearchStatus.OOS_SUPPORTED.value != EvidenceGrade.B.value


def test_claim_status_coerced_from_string():
    c = ResearchClaim(claim_id="c", source_id="s", claim="x", claim_type="t",
                      source_status="SOURCE_CLAIM")
    assert c.source_status == ResearchStatus.SOURCE_CLAIM


def test_hypothesis_protocol_hash_deterministic():
    h1 = ResearchHypothesis(hypothesis_id="h", signal_definition="s", sample_start="2000")
    h2 = ResearchHypothesis(hypothesis_id="h", signal_definition="s", sample_start="2000")
    assert h1.compute_protocol_hash() == h2.compute_protocol_hash()


def test_hypothesis_protocol_hash_sensitive_to_content():
    h1 = ResearchHypothesis(hypothesis_id="h", signal_definition="s")
    h2 = ResearchHypothesis(hypothesis_id="h", signal_definition="s2")
    assert h1.compute_protocol_hash() != h2.compute_protocol_hash()


def test_stable_hash_is_stable_and_order_independent():
    assert _stable_hash({"a": 1, "b": 2}) == _stable_hash({"b": 2, "a": 1})
    assert _stable_hash({"a": 1}) != _stable_hash({"a": 2})


def test_source_full_text_is_honest():
    s = ResearchSource(source_id="s", source_type="book", title="T")
    assert s.full_text_status == "NOT_FOUND_IN_FILE_LIBRARY"


def test_evidence_defaults_are_conservative():
    ev = ResearchEvidence(fact_id="f", fact="x", source_id="s")
    assert ev.evidence_grade == EvidenceGrade.D
    assert ev.research_status == ResearchStatus.SOURCE_CLAIM
    assert ev.influence_class == InfluenceClass.CONTEXT_MODIFIER
