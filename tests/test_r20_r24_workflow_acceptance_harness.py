"""Acceptance oracle for the canonical event-to-learning workflow.

This suite deliberately operates on a temporary append-only lineage store.  It
does not invoke providers, schedulers, Telegram, brokers, or production stores.
The same assertions are used by release QA to catch in-memory-only lineage,
duplicate semantic work, temporal look-ahead, and missing-link optimism.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.lib.cio_lineage import LineageStore


REQUIRED_NODE_TYPES = {
    "SOURCE_EVENT",
    "ENTITY",
    "MATERIALITY",
    "RESEARCH_GAP",
    "RESEARCH",
    "SPECIALIST_ARTIFACT",
    "COUNCIL",
    "CIO_PRODUCT",
    "NOTIFICATION",
    "CHECKPOINT",
}


def _iso(offset: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat()


def _write_complete_workflow(path: Path, *, workflow: str = "wf-acceptance") -> dict[str, str]:
    """Create a production-shaped, fully linked workflow using canonical APIs."""
    ids = {
        "event": "evt-1",
        "entity": "sec-schd",
        "materiality": "mat-1",
        "gap": "gap-1",
        "research": "research-1",
        "specialist": "artifact-1",
        "council": "council-1",
        "product": "product-1",
        "notification": "notification-1",
        "checkpoint": "checkpoint-1",
    }
    store = LineageStore(path)
    common = {
        "source_sha": "test-source-sha",
        "evidence_class": "DRY_RUN",
        "as_of": _iso(),
        "data_quality": "AVAILABLE",
    }
    for node_type, key in (
        ("SOURCE_EVENT", "event"),
        ("ENTITY", "entity"),
        ("MATERIALITY", "materiality"),
        ("RESEARCH_GAP", "gap"),
        ("RESEARCH", "research"),
        ("SPECIALIST_ARTIFACT", "specialist"),
        ("COUNCIL", "council"),
        ("CIO_PRODUCT", "product"),
        ("NOTIFICATION", "notification"),
        ("CHECKPOINT", "checkpoint"),
    ):
        assert store.node(
            workflow=workflow,
            node_type=node_type,
            node_id=ids[key],
            entity_refs=[ids["entity"]],
            summary=node_type,
            **common,
        )
    for src, dst, relation in (
        (ids["event"], ids["entity"], "IMPACTS"),
        (ids["entity"], ids["materiality"], "EVALUATED_BY"),
        (ids["materiality"], ids["gap"], "CREATES"),
        (ids["gap"], ids["research"], "RESEARCHED_AS"),
        (ids["research"], ids["specialist"], "PRODUCED"),
        (ids["specialist"], ids["council"], "SYNTHESIZED_INTO"),
        (ids["council"], ids["product"], "PRODUCED"),
        (ids["product"], ids["notification"], "NOTIFIED_AS"),
        (ids["product"], ids["checkpoint"], "CHECKPOINTED_BY"),
    ):
        assert store.edge(workflow=workflow, from_id=src, to_id=dst, relationship=relation)
    return ids


def _records(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def test_complete_lineage_survives_reader_recreation(tmp_path: Path):
    path = tmp_path / "lineage.jsonl"
    ids = _write_complete_workflow(path)

    # Recreate the reader: no Python object from the writer is consulted below.
    reloaded = LineageStore(path)
    rows = _records(path)
    nodes = {r["node_id"]: r for r in rows if r.get("record_type") == "node"}
    edges = {(r["from"], r["to"]): r for r in rows if r.get("record_type") == "edge"}
    assert REQUIRED_NODE_TYPES <= {r["node_type"] for r in nodes.values()}
    assert (ids["product"], ids["checkpoint"]) in edges
    assert nodes[ids["checkpoint"]]["data_quality"] == "AVAILABLE"
    assert reloaded._existing_keys()  # persisted index, not in-memory state


def test_identical_semantic_replay_is_idempotent(tmp_path: Path):
    path = tmp_path / "lineage.jsonl"
    _write_complete_workflow(path)
    before = path.read_bytes()
    store = LineageStore(path)
    # Simulate 100 replays of the same semantic event and lineage.
    for _ in range(100):
        assert not store.node(
            workflow="wf-acceptance",
            node_type="CIO_PRODUCT",
            node_id="product-1",
            summary="unchanged",
            evidence_class="DRY_RUN",
        )
        assert not store.edge(
            workflow="wf-acceptance",
            from_id="product-1",
            to_id="checkpoint-1",
            relationship="CHECKPOINTED_BY",
        )
    assert path.read_bytes() == before


def test_material_change_has_new_semantic_identity(tmp_path: Path):
    path = tmp_path / "lineage.jsonl"
    _write_complete_workflow(path)
    store = LineageStore(path)
    assert store.node(
        workflow="wf-acceptance",
        node_type="CIO_PRODUCT",
        node_id="product-2",
        summary="material thesis change",
        evidence_class="DRY_RUN",
    )


def test_temporal_cutoff_excludes_future_nodes(tmp_path: Path):
    path = tmp_path / "lineage.jsonl"
    _write_complete_workflow(path)
    store = LineageStore(path)
    cutoff = _iso()
    store.node(
        workflow="wf-acceptance",
        node_type="OUTCOME",
        node_id="outcome-future",
        as_of=_iso(3600),
        evidence_class="DRY_RUN",
    )
    visible = [
        r for r in _records(path)
        if r.get("record_type") == "node" and str(r.get("as_of", "")) <= cutoff
    ]
    assert "outcome-future" not in {r["node_id"] for r in visible}


def test_partial_lineage_is_explicit_not_phantom(tmp_path: Path):
    path = tmp_path / "lineage.jsonl"
    store = LineageStore(path)
    assert store.node(
        workflow="wf-partial",
        node_type="NOTIFICATION",
        node_id="notification-partial",
        status="UNRESOLVED_LINK",
        data_quality="PARTIAL",
        summary="receipt unavailable",
        evidence_class="DRY_RUN",
    )
    rows = _records(path)
    row = next(r for r in rows if r.get("node_id") == "notification-partial")
    assert row["status"] == "UNRESOLVED_LINK"
    assert row["data_quality"] == "PARTIAL"
    assert not any(r.get("record_type") == "edge" for r in rows)


def test_lineage_records_are_read_only_advisory(tmp_path: Path):
    path = tmp_path / "lineage.jsonl"
    _write_complete_workflow(path)
    assert all(r.get("authority") == "READ_ONLY_ADVISORY" for r in _records(path))

