"""Claim / evidence graph tests — provenance invariants, contradictions, cycles."""
from __future__ import annotations

from financial_senses.evidence_graph import (
    NODE_CLAIM,
    NODE_FACT,
    UNSUPPORTED,
    ClaimEvidenceGraph,
    build_graph,
)


def _fact(nid, source="PRIMARY_REGULATORY", observed="2024-01-01", quality="HIGH", freshness="FRESH"):
    return {
        "id": nid,
        "type": NODE_FACT,
        "text": f"fact {nid}",
        "source": source,
        "observed_at": observed,
        "quality": quality,
        "freshness": freshness,
    }


def _claim(nid, text="a claim"):
    return {"id": nid, "type": NODE_CLAIM, "text": text, "claim_type": "thesis"}


def _edge(eid, frm, to, rel="SUPPORTS"):
    return {"id": eid, "from_id": frm, "to_id": to, "relation": rel}


def test_fact_without_source_rejected():
    g = build_graph(
        [{"id": "f1", "type": NODE_FACT, "text": "x", "observed_at": "2024-01-01", "quality": "HIGH"}],
        [],
    )
    errs = g.validate()
    assert any("f1" in e for e in errs)


def test_fact_without_as_of_rejected():
    # Neither observed_at nor as_of -> provenance violation.
    g = build_graph(
        [{"id": "f1", "type": NODE_FACT, "text": "x", "source": "PRIMARY_REGULATORY", "quality": "HIGH"}],
        [],
    )
    assert any("f1" in e for e in g.validate())


def test_fact_with_only_as_of_is_ok():
    g = build_graph(
        [{"id": "f1", "type": NODE_FACT, "text": "x", "source": "PRIMARY_REGULATORY", "as_of": "2024-01-01", "quality": "HIGH"}],
        [],
    )
    assert not any("f1" in e for e in g.validate())


def test_memory_cannot_back_fact():
    g = build_graph(
        [
            {
                "id": "f1",
                "type": NODE_FACT,
                "text": "x",
                "source": "MEMORY_CONTEXT",
                "observed_at": "2024-01-01",
                "quality": "LOW",
            }
        ],
        [],
    )
    assert any("f1" in e for e in g.validate())


def test_claim_with_support_is_supported():
    g = build_graph([_fact("f1"), _claim("c1")], [_edge("e1", "f1", "c1", "SUPPORTS")])
    g.validate()
    assert g.nodes["c1"].status != UNSUPPORTED


def test_claim_without_evidence_is_unsupported():
    g = build_graph([_fact("f1"), _claim("c1")], [])
    g.validate()
    assert g.nodes["c1"].status == UNSUPPORTED


def test_contradiction_preserved():
    g = build_graph(
        [_fact("f1"), _fact("f2"), _claim("c1")],
        [_edge("e1", "f1", "c1", "SUPPORTS"), _edge("e2", "f2", "c1", "CONTRADICTS")],
    )
    ev = g.claim_evidence("c1")
    assert len(ev["supporting"]) == 1
    assert len(ev["contradicting"]) == 1
    assert g.nodes["f2"].type == NODE_FACT  # contradictory fact not deleted


def test_cycle_detection():
    g = build_graph(
        [_claim("c1"), _claim("c2")],
        [_edge("e1", "c1", "c2", "SUPPORTS"), _edge("e2", "c2", "c1", "SUPPORTS")],
    )
    cycles = g.detect_cycles()
    assert len(cycles) >= 1


def test_duplicate_edge_id_rejected():
    g = build_graph([_fact("f1"), _claim("c1")], [_edge("e1", "f1", "c1"), _edge("e1", "f1", "c1")])
    assert any("duplicate" in e for e in g.validate())


def test_invalid_relation_rejected():
    g = build_graph([_fact("f1"), _claim("c1")], [_edge("e1", "f1", "c1", "NOT_A_RELATION")])
    assert any("invalid relation" in e for e in g.validate())


def test_decision_used_by_claim():
    g = build_graph(
        [_claim("c1"), {"id": "d1", "type": "DECISION", "text": "trim"}],
        [_edge("e1", "c1", "d1", "USED_BY")],
    )
    assert g.validate() == []
    assert g.nodes["d1"].type == "DECISION"


def test_specialist_opinion_alone_not_actionable():
    g = build_graph(
        [
            {"id": "o1", "type": "SPECIALIST_OPINION", "text": "I think it will grow"},
            _claim("c1"),
        ],
        [_edge("e1", "o1", "c1", "SUPPORTS")],
    )
    g.validate()
    ev = g.claim_evidence("c1")
    assert not ev["authoritative_fact_support"]
    assert ev["opinion_support"]
    assert ev["actionable"] is False
    assert g.nodes["c1"].status == "CONTEXTUAL_ONLY"


def test_claim_alone_not_authoritative():
    g = build_graph(
        [_claim("c1"), _claim("c2")],
        [_edge("e1", "c2", "c1", "SUPPORTS")],
    )
    g.validate()
    ev = g.claim_evidence("c1")
    assert not ev["authoritative_fact_support"]
    assert ev["derived_claim_support"]
    assert ev["actionable"] is False


def test_case_ref_alone_not_authoritative():
    g = build_graph(
        [
            {"id": "k1", "type": "CASE_REF", "text": "similar past case"},
            _claim("c1"),
        ],
        [_edge("e1", "k1", "c1", "SUPPORTS")],
    )
    g.validate()
    ev = g.claim_evidence("c1")
    assert not ev["authoritative_fact_support"]
    assert ev["contextual_support"]
    assert ev["actionable"] is False


def test_source_node_alone_not_authoritative():
    g = build_graph(
        [
            {"id": "s1", "type": "SOURCE", "text": "SEC EDGAR"},
            _claim("c1"),
        ],
        [_edge("e1", "s1", "c1", "SUPPORTS")],
    )
    g.validate()
    ev = g.claim_evidence("c1")
    assert not ev["authoritative_fact_support"]
    assert ev["provenance_support"]
    assert ev["actionable"] is False


def test_fresh_fact_plus_contradiction_not_actionable():
    g = build_graph(
        [_fact("f1"), _fact("f2"), _claim("c1")],
        [_edge("e1", "f1", "c1", "SUPPORTS"), _edge("e2", "f2", "c1", "CONTRADICTS")],
    )
    g.validate()
    assert g.nodes["c1"].status == "CONTESTED"
    ev = g.claim_evidence("c1")
    assert ev["authoritative_fact_support"]
    assert ev["contradiction"]
    assert ev["actionable"] is False


def test_fresh_fact_plus_stale_historical_fact_actionable():
    # A fresh authoritative FACT governs; the stale historical FACT is preserved
    # but does not block actionability.
    g = build_graph(
        [
            _fact("f1"),
            {"id": "f2", "type": NODE_FACT, "text": "old revenue", "source": "PRIMARY_REGULATORY",
             "observed_at": "2023-01-01", "quality": "HIGH", "freshness": "STALE"},
            _claim("c1"),
        ],
        [_edge("e1", "f1", "c1", "SUPPORTS"), _edge("e2", "f2", "c1", "SUPPORTS")],
    )
    g.validate()
    ev = g.claim_evidence("c1")
    assert ev["authoritative_fact_support"]
    assert ev["stale_fact_support"]
    assert ev["actionable"] is True


def test_invalidation_blocks_actionability():
    g = build_graph(
        [_fact("f1"), _fact("f2"), _claim("c1")],
        [_edge("e1", "f1", "c1", "SUPPORTS"), _edge("e2", "f2", "c1", "INVALIDATES")],
    )
    g.validate()
    ev = g.claim_evidence("c1")
    assert ev["contradiction"]
    assert ev["actionable"] is False


def test_memory_ref_support_is_contextual_only():
    g = build_graph(
        [
            {"id": "m1", "type": "MEMORY_REF", "text": "past note"},
            _claim("c1"),
        ],
        [_edge("e1", "m1", "c1", "SUPPORTS")],
    )
    g.validate()
    assert g.nodes["c1"].status == "CONTEXTUAL_ONLY"
    ev = g.claim_evidence("c1")
    assert ev["contextual_support"]
    assert not ev["authoritative_fact_support"]
    assert ev["actionable"] is False


def test_fact_support_is_authoritative():
    g = build_graph([_fact("f1"), _claim("c1")], [_edge("e1", "f1", "c1", "SUPPORTS")])
    g.validate()
    ev = g.claim_evidence("c1")
    assert ev["authoritative_fact_support"]
    assert not ev["contextual_support"]
    assert ev["actionable"] is True


def test_stale_fact_preserved_not_actionable():
    g = build_graph(
        [
            {"id": "f1", "type": NODE_FACT, "text": "old revenue", "source": "PRIMARY_REGULATORY",
             "observed_at": "2024-01-01", "quality": "HIGH", "freshness": "STALE"},
            _claim("c1"),
        ],
        [_edge("e1", "f1", "c1", "SUPPORTS")],
    )
    g.validate()
    # Stale fact is preserved (not deleted) and marked stale.
    assert g.nodes["f1"].type == NODE_FACT
    d = g.to_dict()
    assert "f1" in d["stale_facts"]
    # The claim is non-actionable while its only support is stale.
    ev = g.claim_evidence("c1")
    assert ev["stale_fact_support"]
    assert ev["actionable"] is False


def _invalid_fact(nid, **overrides):
    base = {"id": nid, "type": NODE_FACT, "text": "invalid fact"}
    base.update(overrides)
    return base


def test_fact_missing_freshness_not_authoritative():
    # A FACT with full provenance but NO freshness is not fresh; it must not be
    # authoritative nor actionable. Missing freshness != fresh.
    g = build_graph(
        [_invalid_fact("f1", source="PRIMARY_REGULATORY", observed_at="2024-01-01", quality="HIGH"), _claim("c1")],
        [_edge("e1", "f1", "c1", "SUPPORTS")],
    )
    g.validate()
    ev = g.claim_evidence("c1")
    assert not ev["authoritative_fact_support"]
    assert ev["invalid_fact_support"]
    assert ev["actionable"] is False


def test_fact_none_freshness_not_authoritative():
    g = build_graph(
        [_invalid_fact("f1", source="PRIMARY_REGULATORY", observed_at="2024-01-01", quality="HIGH", freshness=None), _claim("c1")],
        [_edge("e1", "f1", "c1", "SUPPORTS")],
    )
    g.validate()
    ev = g.claim_evidence("c1")
    assert not ev["authoritative_fact_support"]
    assert ev["actionable"] is False


def test_fact_empty_freshness_not_authoritative():
    g = build_graph(
        [_invalid_fact("f1", source="PRIMARY_REGULATORY", observed_at="2024-01-01", quality="HIGH", freshness=""), _claim("c1")],
        [_edge("e1", "f1", "c1", "SUPPORTS")],
    )
    g.validate()
    ev = g.claim_evidence("c1")
    assert not ev["authoritative_fact_support"]
    assert ev["actionable"] is False


def test_fact_unknown_freshness_not_authoritative():
    g = build_graph(
        [_invalid_fact("f1", source="PRIMARY_REGULATORY", observed_at="2024-01-01", quality="HIGH", freshness="UNKNOWN"), _claim("c1")],
        [_edge("e1", "f1", "c1", "SUPPORTS")],
    )
    g.validate()
    ev = g.claim_evidence("c1")
    assert not ev["authoritative_fact_support"]
    assert ev["invalid_fact_support"]
    assert ev["actionable"] is False


def test_fact_invalid_freshness_enum_not_authoritative():
    g = build_graph(
        [_invalid_fact("f1", source="PRIMARY_REGULATORY", observed_at="2024-01-01", quality="HIGH", freshness="NOT_A_REAL_VALUE"), _claim("c1")],
        [_edge("e1", "f1", "c1", "SUPPORTS")],
    )
    g.validate()
    ev = g.claim_evidence("c1")
    assert not ev["authoritative_fact_support"]
    assert ev["invalid_fact_support"]
    assert ev["actionable"] is False


def test_fact_explicit_fresh_is_authoritative():
    g = build_graph(
        [_invalid_fact("f1", source="PRIMARY_REGULATORY", observed_at="2024-01-01", quality="HIGH", freshness="FRESH"), _claim("c1")],
        [_edge("e1", "f1", "c1", "SUPPORTS")],
    )
    g.validate()
    ev = g.claim_evidence("c1")
    assert ev["authoritative_fact_support"]
    assert ev["actionable"] is True


def test_fact_explicit_stale_is_stale_not_actionable():
    g = build_graph(
        [_invalid_fact("f1", source="PRIMARY_REGULATORY", observed_at="2024-01-01", quality="HIGH", freshness="STALE"), _claim("c1")],
        [_edge("e1", "f1", "c1", "SUPPORTS")],
    )
    g.validate()
    ev = g.claim_evidence("c1")
    assert not ev["authoritative_fact_support"]
    assert ev["stale_fact_support"]
    assert ev["actionable"] is False


def test_fact_invalid_quality_not_authoritative_not_actionable():
    # A fact-capable source + as_of + FRESH but BOGUS quality must not validate
    # and must not become authoritative.
    g = build_graph(
        [_invalid_fact("f1", source="PRIMARY_REGULATORY", observed_at="2024-01-01", quality="BOGUS", freshness="FRESH"), _claim("c1")],
        [_edge("e1", "f1", "c1", "SUPPORTS")],
    )
    errs = g.validate()
    assert any("invalid quality" in e and "f1" in e for e in errs)
    ev = g.claim_evidence("c1")
    assert not ev["authoritative_fact_support"]
    assert ev["invalid_fact_support"]
    assert ev["actionable"] is False


def test_fact_valid_quality_fresh_is_authoritative():
    for grade in ("HIGH", "MEDIUM", "LOW", "UNKNOWN"):
        g = build_graph(
            [_invalid_fact("f1", source="PRIMARY_REGULATORY", observed_at="2024-01-01", quality=grade, freshness="FRESH"), _claim("c1")],
            [_edge("e1", "f1", "c1", "SUPPORTS")],
        )
        g.validate()
        ev = g.claim_evidence("c1")
        assert ev["authoritative_fact_support"], grade
        assert ev["actionable"] is True, grade


def test_fact_missing_source_not_authoritative_not_actionable():
    g = build_graph(
        [_invalid_fact("f1", observed_at="2024-01-01", quality="HIGH"), _claim("c1")],
        [_edge("e1", "f1", "c1", "SUPPORTS")],
    )
    errs = g.validate()
    assert any("f1" in e for e in errs)
    ev = g.claim_evidence("c1")
    assert not ev["authoritative_fact_support"]
    assert ev["invalid_fact_support"]
    assert ev["actionable"] is False


def test_fact_model_inference_source_not_authoritative():
    g = build_graph(
        [_invalid_fact("f1", source="MODEL_INFERENCE", observed_at="2024-01-01", quality="HIGH"), _claim("c1")],
        [_edge("e1", "f1", "c1", "SUPPORTS")],
    )
    assert any("f1" in e for e in g.validate())
    ev = g.claim_evidence("c1")
    assert not ev["authoritative_fact_support"]
    assert ev["actionable"] is False


def test_fact_missing_quality_not_authoritative():
    g = build_graph(
        [_invalid_fact("f1", source="PRIMARY_REGULATORY", observed_at="2024-01-01"), _claim("c1")],
        [_edge("e1", "f1", "c1", "SUPPORTS")],
    )
    assert any("f1" in e for e in g.validate())
    ev = g.claim_evidence("c1")
    assert not ev["authoritative_fact_support"]
    assert ev["actionable"] is False


def test_fact_missing_observed_at_not_authoritative():
    g = build_graph(
        [_invalid_fact("f1", source="PRIMARY_REGULATORY", quality="HIGH"), _claim("c1")],
        [_edge("e1", "f1", "c1", "SUPPORTS")],
    )
    assert any("f1" in e for e in g.validate())
    ev = g.claim_evidence("c1")
    assert not ev["authoritative_fact_support"]
    assert ev["actionable"] is False


def test_specialist_opinion_plus_invalid_fact_not_actionable():
    g = build_graph(
        [
            {"id": "o1", "type": "SPECIALIST_OPINION", "text": "opinion"},
            _invalid_fact("f1", source="MODEL_INFERENCE", observed_at="2024-01-01", quality="HIGH"),
            _claim("c1"),
        ],
        [
            _edge("e1", "o1", "c1", "SUPPORTS"),
            _edge("e2", "f1", "c1", "SUPPORTS"),
        ],
    )
    g.validate()
    ev = g.claim_evidence("c1")
    assert not ev["authoritative_fact_support"]
    assert ev["opinion_support"]
    assert ev["invalid_fact_support"]
    assert ev["actionable"] is False
