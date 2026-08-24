"""Six-spec-defect remediation tests. READ_ONLY_ADVISORY. Zero paid. No Neo4j."""
from __future__ import annotations

import pytest

from scripts.lib.decision_rationale import build_rationale, reject_private_reasoning
from scripts.lib.embedding_policy import assert_memory_path_allowed, default_policy
from scripts.lib.memory_fact import (
    AS_KNOWN_AT,
    AS_KNOWN_NOW,

    VALID_AT_AND_KNOWN_AT,
    MemoryFactStore,
    build_fact,
    subject_from_security,
)
from scripts.lib.memory_namespace import DEFAULT_TENANT, build_namespace, require_tenant, visible
from scripts.lib.memory_retrieval_unit import from_fact as mru_from_fact
from scripts.lib.memory_vector_index_benchmark import run_synthetic_exact
from scripts.lib.similarity_candidate import from_similarity, promote


def test_cloud_embedding_disabled_by_default():
    p = default_policy()
    assert p["mode"] == "LOCAL_ONLY"
    assert p["model"] == "nomic-embed-text"
    assert p["generative"] is False
    assert p["cloud_embeddings"] == "DISABLED_BY_DEFAULT"
    assert_memory_path_allowed(p)
    with pytest.raises(RuntimeError, match="CLOUD_EMBEDDING_DISABLED_BY_DEFAULT"):
        assert_memory_path_allowed({**p, "provider": "amazon.titan", "local": False})
    with pytest.raises(RuntimeError, match="GENERATIVE_MODEL_FORBIDDEN_ON_MEMORY_PATH"):
        assert_memory_path_allowed({**p, "generative": True})
    with pytest.raises(RuntimeError, match="CLOUD_EMBEDDING_UNAUTHORIZED"):
        assert_memory_path_allowed({**p, "mode": "CLOUD_AUTHORIZED", "cloud_authorization": {}})


def test_similarity_cannot_self_ratify():
    c = from_similarity(
        source_entity_guid="a",
        target_entity_guid="b",
        relationship_hypothesis="RELATED_TO",
        similarity=0.99,
        embedding_model="nomic-embed-text",
        embedding_version="test",
    )
    assert c["status"] == "CANDIDATE"
    assert c["authoritative"] is False
    with pytest.raises(RuntimeError, match="SIMILARITY_CANNOT_SELF_RATIFY"):
        promote(c, mechanism="COSINE_THRESHOLD", actor="ann")
    ratified = promote(c, mechanism="LIBRARIAN_RATIFICATION", actor="librarian")
    assert ratified["status"] == "RATIFIED"
    assert ratified["authoritative"] is True


def test_tenant_isolation_fail_closed():
    with pytest.raises(RuntimeError, match="TENANT_SCOPE_REQUIRED"):
        require_tenant("")
    a = build_namespace(tenant_id="tenant-a", namespace="OPERATOR_PRIVATE")
    b = build_namespace(tenant_id="tenant-b", namespace="OPERATOR_PRIVATE")
    assert visible(viewer_tenant="tenant-a", record_tenant=a["tenant_id"], record_namespace="OPERATOR_PRIVATE") is True
    assert visible(viewer_tenant="tenant-a", record_tenant=b["tenant_id"], record_namespace="OPERATOR_PRIVATE") is False
    assert visible(
        viewer_tenant="tenant-a",
        record_tenant="tenant-a",
        record_namespace="OPERATOR_PRIVATE",
        viewer_namespace="SHARED_ENTITY",
    ) is False
    store = MemoryFactStore()
    with pytest.raises(RuntimeError, match="TENANT_SCOPE_REQUIRED"):
        store.query(tenant_id="", mode=AS_KNOWN_NOW)


def test_chain_of_thought_rejected():
    with pytest.raises(RuntimeError, match="PRIVATE_REASONING_FORBIDDEN"):
        reject_private_reasoning({"raw_chain_of_thought": "must never survive"})
    ok = build_rationale(decision_id="d1", conclusion="hold", structured_reason_codes=["NO_NEW_INFO"])
    assert "raw_chain_of_thought" not in ok
    with pytest.raises(RuntimeError, match="PRIVATE_REASONING_FORBIDDEN"):
        reject_private_reasoning({"scratchpad": "let me think step by step: secret"})


def test_bitemporal_correction_and_history():
    store = MemoryFactStore()
    ids = subject_from_security(symbol="SCHD", company="Schwab US Dividend Equity ETF")
    assert ids["subject_guid"]
    assert ids["ticker_alias_guid"] != ids["subject_guid"]
    f1 = build_fact(
        tenant_id=DEFAULT_TENANT,
        namespace="POLICY_BELIEF",
        subject_guid=ids["subject_guid"],
        predicate="operator_preference",
        value="wants_income",
        category="SEMANTIC_OPERATOR",
        valid_from="2026-01-01T00:00:00+00:00",
        source_type="operator_feedback",
        source_id="fb-1",
        source_as_of="2026-01-01T00:00:00+00:00",
        asserted_by="test",
        status="CONFIRMED",
    )
    store.write(f1, now="2026-02-01T00:00:00+00:00")
    f2 = build_fact(
        tenant_id=DEFAULT_TENANT,
        namespace="POLICY_BELIEF",
        subject_guid=ids["subject_guid"],
        predicate="operator_preference",
        value="wants_growth_tilt",
        category="SEMANTIC_OPERATOR",
        valid_from="2026-03-01T00:00:00+00:00",
        source_type="operator_feedback",
        source_id="fb-2",
        source_as_of="2026-03-01T00:00:00+00:00",
        asserted_by="test",
        status="CONFIRMED",
        memory_id=f1["memory_id"],
    )
    store.write(f2, now="2026-04-01T00:00:00+00:00")
    past = store.query(
        tenant_id=DEFAULT_TENANT,
        mode=VALID_AT_AND_KNOWN_AT,
        valid_at="2026-02-15T00:00:00+00:00",
        tx_at="2026-02-15T00:00:00+00:00",
        subject_guid=ids["subject_guid"],
    )
    assert past[0]["object"] == "wants_income"
    later = store.query(
        tenant_id=DEFAULT_TENANT,
        mode=AS_KNOWN_AT,
        tx_at="2026-05-01T00:00:00+00:00",
        subject_guid=ids["subject_guid"],
    )
    assert later[-1]["object"] == "wants_growth_tilt"
    other = store.query(tenant_id="tenant-b", mode=AS_KNOWN_NOW, subject_guid=ids["subject_guid"])
    assert other == []
    unit = mru_from_fact(later[-1], mode="WHAT_CHANGED", why_selected="latest confirmed preference")
    assert unit["overrides_office_truth"] is False
    assert unit["mode"] == "WHAT_CHANGED"


def test_late_arriving_fact_uses_valid_time_not_tx_time():
    store = MemoryFactStore()
    f = build_fact(
        tenant_id=DEFAULT_TENANT,
        namespace="RESEARCH_EVIDENCE",
        subject_guid="sec-1",
        predicate="filing_exists",
        value="10-K",
        category="EVIDENCE",
        valid_from="2025-12-01T00:00:00+00:00",
        source_type="sec",
        source_id="10k",
        source_as_of="2025-12-01T00:00:00+00:00",
        asserted_by="test",
        status="CONFIRMED",
    )
    store.write(f, now="2026-08-01T00:00:00+00:00")
    known_early = store.query(
        tenant_id=DEFAULT_TENANT,
        mode=VALID_AT_AND_KNOWN_AT,
        valid_at="2026-01-01T00:00:00+00:00",
        tx_at="2026-01-01T00:00:00+00:00",
        subject_guid="sec-1",
    )
    assert known_early == []
    known_late = store.query(
        tenant_id=DEFAULT_TENANT,
        mode=VALID_AT_AND_KNOWN_AT,
        valid_at="2026-01-01T00:00:00+00:00",
        tx_at="2026-08-02T00:00:00+00:00",
        subject_guid="sec-1",
    )
    assert len(known_late) == 1


def test_vector_benchmark_does_not_fabricate_hnsw_or_neo4j():
    rec = run_synthetic_exact(n=16, dim=4)
    assert rec["recommendation"] == "INSUFFICIENT_DATA"
    assert rec["measured"]["HNSW"] == "UNMEASURED"
    assert rec["neo4j_shadow_poc_decision"] == "INSUFFICIENT_DATA"
    assert rec["longmemeval_style_numbers"] == "REFERENCE_TARGET_NOT_MEASURED"
    assert rec["measured"]["EXACT"]["top1_self"] is True


def test_schd_identity_stable():
    a = subject_from_security(symbol="SCHD", company="Schwab US Dividend Equity ETF")
    b = subject_from_security(symbol="SCHD", company="Schwab US Dividend Equity ETF")
    assert a["security_guid"] == b["security_guid"]
    assert a["subject_guid"] == a["security_guid"]
