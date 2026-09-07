"""Memory loading rails for Lane A wakes."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from scripts.lib.persistent_agent_wake import MemoryLoader  # noqa: E402

NOW = datetime(2026, 9, 7, 19, 0, tzinfo=timezone.utc)
SG = "97172f54-916c-5960-aa73-f16321f1cf3e"


def test_empty_memory_is_loaded_empty(tmp_path):
    p = tmp_path / "m.jsonl"
    p.write_text("")
    snap = MemoryLoader(p).load(SG, now=NOW)
    assert snap.empty and not snap.malformed


def test_conflicting_subject_filtered(tmp_path):
    p = tmp_path / "m.jsonl"
    rows = [
        {"fact_id": "a", "subject_guid": SG, "content": "x",
         "as_of": NOW.isoformat().replace("+00:00", "Z")},
        {"fact_id": "b", "subject_guid": "00000000-0000-0000-0000-000000000001",
         "content": "y", "as_of": NOW.isoformat().replace("+00:00", "Z")},
    ]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    snap = MemoryLoader(p).load(SG, now=NOW)
    assert [f.fact_id for f in snap.facts] == ["a"]
