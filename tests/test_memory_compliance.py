"""MemoryCompliance@v1 builder (01 §6) — hermetic."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import memory_compliance as mc  # noqa: E402

NOW = dt.datetime(2026, 9, 27, 20, 0, tzinfo=dt.timezone.utc)


def test_build_measures_per_lane(tmp_path):
    t = (NOW - dt.timedelta(hours=1)).isoformat()
    ctx = tmp_path / "ctx.jsonl"; rr = tmp_path / "rr.jsonl"
    ctx.write_text("\n".join(json.dumps(r) for r in [
        {"event": "OPENED", "context_id": "c1", "lane_id": "persistent-wake", "purpose": "DECIDE", "opened_at": t, "degraded": False, "contradiction_state": "NONE"},
        {"event": "COMMITTED", "context_id": "c1", "lane_id": "persistent-wake", "committed_at": t, "delta_count": 0, "influence": {"consulted": True}},
        {"event": "OPENED", "context_id": "c2", "lane_id": "persistent-wake", "purpose": "DECIDE", "opened_at": t, "degraded": True, "contradiction_state": "UNKNOWN"},
        {"event": "OPENED", "context_id": "c3", "lane_id": "hermes-cio-worker", "purpose": "RESEARCH", "opened_at": t, "degraded": False, "contradiction_state": "OPEN"},
        {"event": "COMMITTED", "context_id": "c3", "lane_id": "hermes-cio-worker", "committed_at": t, "delta_count": 1, "freshness_updates": [{"x": 1}]},
        {"event": "REFUSED", "context_id": "c9", "lane_id": "persistent-wake", "opened_at": t},
        {"event": "OPENED", "context_id": "old", "lane_id": "persistent-wake", "purpose": "DECIDE", "opened_at": (NOW - dt.timedelta(days=3)).isoformat()}]) + "\n")
    rr.write_text(json.dumps({"context_id": "c3", "lane_id": "hermes-cio-worker", "decision": "HIT_FRESH", "generated": True, "created_at": t}) + "\n")
    rep = mc.build(contexts_path=ctx, receipts_path=rr, heartbeats=[{"lane_id": "persistent-wake", "work_claimed": 4}],
                   ring1_baseline={"total": 137, "files": {"a": 1}}, now=NOW)
    assert rep["totals"] == {"contexts_opened": 3, "contexts_refused": 1, "contexts_committed": 2, "retrieval_receipts": 1,
                             "lanes_with_contexts": 2, "decisions_by_ladder": {"HIT_FRESH": 1}, "duplicate_generation_shadow": 1}
    by = {l["lane_id"]: l for l in rep["lanes"]}
    pw = by["persistent-wake"]["measures"]
    assert pw["read_before_act"] == 0.5 and pw["write_after_act"] == 0.5 and pw["blind_runs"] == 0.5 and pw["blind_runs_decide"] == 0.5
    assert "read_before_act" in by["persistent-wake"]["below_threshold"] and "blind_runs_decide" in by["persistent-wake"]["below_threshold"]
    hw = by["hermes-cio-worker"]["measures"]
    assert hw["write_after_act"] == 1.0 and hw["delta_published"] == 1.0 and hw["freshness_updated"] == 1.0 and hw["retrieval_receipt_share"] == 1.0
    assert hw["read_before_act"] is None and rep["orphan_writes"]["direct_silo_imports"] == 137
