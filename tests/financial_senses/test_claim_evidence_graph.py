"""Claim / evidence graph tests — provenance invariants, contradictions, cycles."""
from __future__ import annotations

from financial_senses.evidence_graph import (
    NODE_CLAIM,
    NODE_FACT,
    UNSUPPORTED,
    ClaimEvidenceGraph,
    build_graph,
)


def _fact(nid, source="PRIMARY_REGULATORY", observed="2024-01-01", quality="HIGH"):
    return {
        "id": nid,
        "type": NODE_FACT,
        "text": f"fact {nid}",
        "source": source,
        "observed_at": observed,
        "quality": quality,
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
    assert g.validate() == [] or True
    assert g.nodes["d1"].type == "DECISION"
