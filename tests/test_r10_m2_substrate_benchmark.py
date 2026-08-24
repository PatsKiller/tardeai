"""Isolated M2 substrate benchmark. Never talks to production :5432."""
from __future__ import annotations

import os

import pytest

from scripts.lib.adjudication_receipt import build_receipt
from scripts.lib.memory_m2_benchmark import (
    DEFAULT_DSN,
    PGMNEMO_TARGET,
    _assert_isolated_dsn,
    golden_200_in_memory,
    run_benchmark,
)
from scripts.lib.similarity_candidate import from_similarity, promote


def test_refuse_production_port():
    with pytest.raises(RuntimeError, match="PRODUCTION_PORT"):
        _assert_isolated_dsn("postgresql://x@127.0.0.1:5432/trade_ai")


def test_isolated_dsn_ok():
    assert "55432" in _assert_isolated_dsn(DEFAULT_DSN)


def test_golden_200_oracle():
    g = golden_200_in_memory()
    assert g["cases"] == 200
    assert g["hits"] == 200
    assert g["Recall@1"] == 1.0


def test_adjudication_no_cot():
    r = build_receipt(
        tenant_id="t",
        subject_guid="s",
        predicate="p",
        candidate_fact_ids=["a", "b"],
        selected_fact_id="b",
        rejected_fact_ids=["a"],
        policy="exclusive_current",
    )
    assert r["chain_of_thought"] is False
    assert r["financial_action"] is False


def test_similarity_cannot_self_ratify():
    c = from_similarity(
        source_entity_guid="a",
        target_entity_guid="b",
        relationship_hypothesis="RELATED_TO",
        similarity=0.99,
        embedding_model="nomic-embed-text",
        embedding_version="t",
    )
    assert c["status"] == "CANDIDATE"
    with pytest.raises(RuntimeError, match="SELF_RATIFY"):
        promote(c, mechanism="COSINE", actor="agent")


@pytest.mark.skipif(os.getenv("M2_SKIP_DOCKER") == "1", reason="explicit skip")
def test_isolated_docker_benchmark():
    report = run_benchmark()
    assert report["production_sql_applied"] is False
    assert report["isolated_dsn_port"] == 55432
    assert report["golden"]["cases"] == 200
    assert report["lanes"]["A_native_postgres"]["status"] == "MEASURED"
    assert report["tenant"]["leakage_count"] == 0
    assert report["concurrency"]["exclusive_ok"] is True
    assert report["titan"] == "DISABLED_BY_DEFAULT"
    assert report["hnsw_mandate"] is False
    assert report["lanes"]["C_pgmnemo"]["target_stable"] == PGMNEMO_TARGET or report["lanes"]["C_pgmnemo"].get("target") == PGMNEMO_TARGET
    assert report["storage_decision"] in {"POSTGRES_NATIVE", "POSTGRES_PGVECTOR", "NO_CLEAR_WINNER"}
    assert report["neo4j_decision"] in {"POSTGRES_SUFFICIENT", "INSUFFICIENT_DATA"}
    assert report["financial_action"] is False
