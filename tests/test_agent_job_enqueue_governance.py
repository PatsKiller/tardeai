"""Queue enqueue governance: dedupe, stale, backpressure (no live DB)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from agent_job_enqueue_governance import (  # noqa: E402
    EnqueueRequest,
    EnqueueResult,
    backpressure_allows,
    classify_queued_age,
    govern_existing_queued,
    governed_enqueue,
    semantic_key,
)


class FakeCursor:
    def __init__(self, queued=900, active=None, fresh=None):
        self.queued = queued
        self.active = active or []
        self.fresh = fresh
        self.updates = []
        self.inserts = []
        self._last = None

    def execute(self, sql, params=None):
        s = " ".join(str(sql).split())
        self._last = s
        if "SELECT COUNT(*)" in s:
            self._result = [(self.queued,)]
        elif "status = ANY" in s or "queued" in s and "SELECT id, status" in s:
            self._result = list(self.active)
        elif "status='completed'" in s:
            self._result = [self.fresh] if self.fresh else []
        elif s.strip().upper().startswith("INSERT"):
            self.inserts.append((s, params))
            self._result = []
        elif s.strip().upper().startswith("UPDATE"):
            self.updates.append((s, params))
            self._result = []
        elif "FROM watchlist_agent_jobs" in s and "SELECT id, symbol" in s:
            self._result = list(self.active)
        else:
            self._result = []

    def fetchone(self):
        if not self._result:
            return None
        return self._result[0]

    def fetchall(self):
        return list(self._result)


def test_semantic_key_stable_for_auto_producers():
    a = EnqueueRequest("SCHG", "maria", "scheduled_research", submitted_from="research_scheduler")
    b = EnqueueRequest("SCHG", "maria", "scheduled_research", submitted_from="overnight_batch")
    assert semantic_key(a) == semantic_key(b)


def test_backpressure_defers_tail_keeps_t0(monkeypatch):
    import agent_job_enqueue_governance as g
    monkeypatch.setattr(g, "QUEUE_PRESSURE_HIGH", 200)
    ok, _ = g.backpressure_allows("T0", 900, material=True)
    assert ok
    allowed_t4, reason = g.backpressure_allows("T4", 900)
    assert allowed_t4 is False
    assert "t3_t4" in reason


def test_stale_tail():
    old = datetime.now(timezone.utc) - timedelta(hours=48)
    assert classify_queued_age(created_at=old, tier="T3") == "STALE"
    assert classify_queued_age(created_at=old, tier="T0") == "CURRENT_AND_MATERIAL"


def test_dedupe_active_equivalent():
    cur = FakeCursor(
        queued=10,
        active=[("job-1", "queued", datetime.now(timezone.utc), {})],
    )
    # same triple without stored key still matches
    req = EnqueueRequest("ANET", "maria", "scheduled_research", submitted_from="research_scheduler", universe_tier="T3")
    res = governed_enqueue(cur, req, queued_count=10)
    assert res.action == "DEDUPED"


def test_insert_when_clear():
    cur = FakeCursor(queued=10, active=[], fresh=None)
    req = EnqueueRequest("CSCO", "maria", "research_gap", submitted_from="thesis", priority=1, universe_tier="T0", material=True)
    res = governed_enqueue(cur, req, queued_count=10)
    assert res.action == "INSERT"
    assert cur.inserts


def test_govern_marks_duplicate_not_delete():
    now = datetime.now(timezone.utc)
    key_req = EnqueueRequest("CSCO", "maria", "scheduled_research")
    from agent_job_enqueue_governance import semantic_key as sk
    k = sk(key_req)
    cur = FakeCursor()
    cur.active = [
        ("a", "CSCO", "maria", "scheduled_research", "research_scheduler", 5, now, {"semantic_key": k}, ""),
        ("b", "CSCO", "maria", "scheduled_research", "overnight_batch", 5, now, {"semantic_key": k}, ""),
    ]
    counts = govern_existing_queued(cur, now=now)
    assert counts["superseded"] == 1
    assert counts["kept"] == 1
    assert any("superseded" in u[0] for u in cur.updates)
    assert not any("DELETE" in u[0].upper() for u in cur.updates)
