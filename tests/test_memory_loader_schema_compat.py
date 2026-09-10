"""MemoryLoader schema adapter — identity aliases + subject isolation.

Regression (2026-09-10): CURRENT defaulted the wake memory backend to
aif_memory.jsonl. That store writes memory_id + a human-readable subject title.
MemoryLoader accepted only fact_id/id and default-matched missing subject_guid
to the wake subject, so either (a) every snapshot was MEMORY_MALFORMED and the
wake refused, or (b) after an id-only alias every subject would load all rows.

This suite proves the adapter: accept unambiguous memory_id/fact_id/id; match
only via explicit subject_guid; never load title-only rows as relevant; fail
closed on matched-row poison (missing/conflicting/duplicate ids).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from scripts.lib.persistent_agent_wake import (  # noqa: E402
    MemoryLoader,
    _resolve_memory_identity,
    _row_subject_disposition,
)

NOW = datetime(2026, 9, 10, 19, 0, tzinfo=timezone.utc)
SG = "8228ea3f-8914-5772-950b-26a85d0b6fc4"
OTHER = "00000000-0000-0000-0000-000000000001"


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "mem.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def _as_of() -> str:
    return NOW.isoformat().replace("+00:00", "Z")


def test_memory_id_alias_loads_when_subject_guid_matches(tmp_path):
    p = _write(
        tmp_path,
        [{
            "memory_id": "mem_abc",
            "subject_guid": SG,
            "content": "ok",
            "as_of": _as_of(),
        }],
    )
    snap = MemoryLoader(p).load(SG, now=NOW)
    assert not snap.malformed
    assert [f.fact_id for f in snap.facts] == ["mem_abc"]
    assert snap.metrics is not None
    assert snap.metrics.loaded == 1


def test_title_only_durable_rows_do_not_refuse_or_load(tmp_path):
    """Production aif_memory shape: memory_id + subject title, no subject_guid."""
    rows = [
        {
            "memory_id": f"mem_{i}",
            "subject": "Program 3 canary: operator rejected stale valuation thesis",
            "content": "…",
            "as_of": _as_of(),
        }
        for i in range(5)
    ]
    snap = MemoryLoader(_write(tmp_path, rows)).load(SG, now=NOW)
    assert not snap.malformed
    assert snap.empty
    assert snap.facts == []
    assert snap.metrics is not None
    assert snap.metrics.unmatched == 5
    assert snap.metrics.loaded == 0


def test_never_loads_all_facts_for_unmatched_subject(tmp_path):
    rows = [
        {"memory_id": "mem_1", "subject": "title only", "as_of": _as_of(), "content": "a"},
        {
            "fact_id": "f-other",
            "subject_guid": OTHER,
            "as_of": _as_of(),
            "content": "b",
        },
        {
            "fact_id": "f-match",
            "subject_guid": SG,
            "as_of": _as_of(),
            "content": "c",
        },
    ]
    snap = MemoryLoader(_write(tmp_path, rows)).load(SG, now=NOW)
    assert not snap.malformed
    assert [f.fact_id for f in snap.facts] == ["f-match"]
    assert snap.metrics is not None
    assert snap.metrics.unmatched == 1
    assert snap.metrics.cross_subject_prevented == 1
    assert snap.metrics.loaded == 1


def test_conflicting_ids_on_matched_row_fail_closed(tmp_path):
    rows = [{
        "fact_id": "f-1",
        "memory_id": "mem_other",
        "subject_guid": SG,
        "as_of": _as_of(),
        "content": "x",
    }]
    snap = MemoryLoader(_write(tmp_path, rows)).load(SG, now=NOW)
    assert snap.malformed
    assert snap.facts == []
    assert snap.metrics is not None
    assert snap.metrics.malformed_rows == 1


def test_duplicate_ids_on_matched_rows_fail_closed(tmp_path):
    rows = [
        {"fact_id": "dup", "subject_guid": SG, "as_of": _as_of(), "content": "a"},
        {"id": "dup", "subject_guid": SG, "as_of": _as_of(), "content": "b"},
    ]
    snap = MemoryLoader(_write(tmp_path, rows)).load(SG, now=NOW)
    assert snap.malformed
    assert "duplicate" in (snap.error or "")


def test_missing_id_on_matched_row_fail_closed(tmp_path):
    rows = [{"subject_guid": SG, "as_of": _as_of(), "content": "x"}]
    snap = MemoryLoader(_write(tmp_path, rows)).load(SG, now=NOW)
    assert snap.malformed


def test_unambiguous_aliases_agree(tmp_path):
    rows = [{
        "fact_id": "same",
        "id": "same",
        "memory_id": "same",
        "subject_guid": SG,
        "as_of": _as_of(),
        "content": "x",
    }]
    snap = MemoryLoader(_write(tmp_path, rows)).load(SG, now=NOW)
    assert not snap.malformed
    assert [f.fact_id for f in snap.facts] == ["same"]


def test_resolve_identity_helpers():
    assert _resolve_memory_identity({"memory_id": "m1"}) == ("m1", None)
    assert _resolve_memory_identity({})[1] == "missing_id"
    assert _resolve_memory_identity({"fact_id": "a", "memory_id": "b"})[1] == "conflicting_ids"
    assert _row_subject_disposition({"subject": "title"}, SG) == "unmatched"
    assert _row_subject_disposition({"subject_guid": SG}, SG) == "match"
    assert _row_subject_disposition({"subject_guid": OTHER}, SG) == "cross"
