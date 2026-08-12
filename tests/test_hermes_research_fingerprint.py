"""Unit tests: Hermes research fingerprint + enqueue de-dupe + TTL reuse."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lib.hermes_research_fingerprint import (
    FINGERPRINT_VERSION,
    canonical_fingerprint_payload,
    compute_fingerprint,
    compute_fingerprint_from_parts,
)
from lib.hermes_research_policy import (
    is_result_reusable,
    resolve_ttl_seconds,
    result_age_seconds,
    try_reuse_completed_result,
)
from lib.hermes_research_queue import (
    EnqueueResult,
    enqueue_research_request,
    find_in_flight_by_fingerprint,
)


# ── fingerprint normalization ────────────────────────────────────────────────


def _base_request(**overrides):
    req = {
        "plan_id": "plan_schd_s1",
        "situation_type": "S1_POSITION_LIFECYCLE",
        "symbol": "SCHD",
        "thesis_version": "desk@v5",
        "questions": [
            {"text": "What catalysts could change the SCHD drawdown thesis?"},
            {"text": "Does multi-domain evidence still support hold?"},
        ],
    }
    req.update(overrides)
    return req


def test_same_questions_punctuation_case_same_fingerprint():
    a = compute_fingerprint(_base_request(questions=[
        {"text": "What catalysts could change the SCHD drawdown thesis?"},
        {"text": "Does multi-domain evidence still support hold?"},
    ]))
    b = compute_fingerprint(_base_request(questions=[
        {"text": "  WHAT CATALYSTS COULD CHANGE THE SCHD DRAWDOWN THESIS???"},
        {"text": "does multi-domain evidence still support hold!!!"},
    ]))
    assert a == b
    assert a.startswith("sha256:")


def test_question_order_swapped_same_fingerprint():
    a = compute_fingerprint(_base_request(questions=[
        {"text": "Question alpha about SCHD"},
        {"text": "Question beta about SCHD"},
    ]))
    b = compute_fingerprint(_base_request(questions=[
        {"text": "Question beta about SCHD"},
        {"text": "Question alpha about SCHD"},
    ]))
    assert a == b


def test_different_question_text_different_fingerprint():
    a = compute_fingerprint(_base_request(questions=[{"text": "Is weight drift price-driven?"}]))
    b = compute_fingerprint(_base_request(questions=[{"text": "What catalysts land next week?"}]))
    assert a != b


def test_priority_and_needed_by_excluded_from_fingerprint():
    a = compute_fingerprint(_base_request(priority="low", needed_by="2026-08-12T00:00:00Z"))
    b = compute_fingerprint(_base_request(priority="critical", needed_by="2026-08-20T00:00:00Z"))
    assert a == b


def test_missing_plan_id_raises():
    with pytest.raises(ValueError, match="plan_id"):
        compute_fingerprint(_base_request(plan_id=""))


def test_empty_questions_raises():
    with pytest.raises(ValueError, match="question"):
        compute_fingerprint(_base_request(questions=[]))


def test_fp_version_in_payload():
    payload = canonical_fingerprint_payload(_base_request())
    assert payload["fp_version"] == FINGERPRINT_VERSION
    assert payload["symbol"] == "SCHD"
    assert payload["scope"] == "symbol"
    assert sorted(payload["questions"]) == payload["questions"]


def test_from_parts_matches_request_shape():
    qs = ["What research would change the advisory on SCHD?"]
    a = compute_fingerprint_from_parts(
        plan_id="plan_x",
        situation_type="S1_POSITION_LIFECYCLE",
        symbol="SCHD",
        thesis_version="desk@v5",
        questions=qs,
    )
    b = compute_fingerprint({
        "plan_id": "plan_x",
        "situation_type": "S1_POSITION_LIFECYCLE",
        "symbol": "SCHD",
        "thesis_version": "desk@v5",
        "questions": qs,
    })
    assert a == b


# ── policy / TTL ─────────────────────────────────────────────────────────────


def test_resolve_ttl_by_priority_and_situation():
    assert resolve_ttl_seconds({"priority": "critical"}) == 2 * 3600
    assert resolve_ttl_seconds({"priority": "high"}) == 6 * 3600
    assert resolve_ttl_seconds({"priority": "normal"}) == 12 * 3600
    assert resolve_ttl_seconds({"priority": "low"}) == 24 * 3600
    # situation override wins
    assert resolve_ttl_seconds({
        "priority": "low",
        "situation_type": "S1_POSITION_LIFECYCLE",
    }) == 6 * 3600


def test_result_age_prefers_as_of():
    now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
    age = result_age_seconds(
        {
            "as_of": "2026-08-12T10:00:00+00:00",
            "completed_ts": "2026-08-11T00:00:00+00:00",
        },
        now=now,
    )
    assert age == 2 * 3600


def test_is_result_reusable_empty_and_low_confidence():
    req = _base_request()
    ok, why = is_result_reusable({"status": "failed"}, req)
    assert not ok and why == "not_completed"

    ok, why = is_result_reusable({"status": "completed", "answers": [], "findings": []}, req)
    assert not ok and why == "empty_result"

    ok, why = is_result_reusable({
        "status": "completed",
        "answers": [{"confidence": 0.1, "status": "answered"}],
        "findings": ["x"],
    }, req)
    assert not ok and why == "low_confidence"

    ok, why = is_result_reusable({
        "status": "completed",
        "findings": ["hold still valid"],
        "answers": [{"confidence": 0.7}],
    }, req)
    assert ok and why == "ok"


def test_try_reuse_fresh_vs_expired():
    now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
    fresh_ts = (now - timedelta(hours=1)).isoformat()
    stale_ts = (now - timedelta(hours=20)).isoformat()
    result_row = {
        "status": "completed",
        "result_id": "rr_1",
        "research_id": "res_1",
        "as_of": fresh_ts,
        "findings": ["ok"],
        "answers": [{"confidence": 0.8}],
    }
    req = _base_request(priority="high")  # TTL 6h

    d = try_reuse_completed_result(
        req, fingerprint="sha256:abc",
        find_completed=lambda fp: result_row,
        now=now,
    )
    assert d.reuse is True
    assert d.reason == "reused_fresh_result"

    result_row["as_of"] = stale_ts
    d2 = try_reuse_completed_result(
        req, fingerprint="sha256:abc",
        find_completed=lambda fp: result_row,
        now=now,
    )
    assert d2.reuse is False
    assert d2.reason == "ttl_expired"


def test_force_refresh_bypasses_ttl_reuse():
    now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
    result_row = {
        "status": "completed",
        "as_of": (now - timedelta(minutes=10)).isoformat(),
        "findings": ["ok"],
        "answers": [{"confidence": 0.9}],
    }
    req = _base_request(priority="high", force_refresh=True)
    d = try_reuse_completed_result(
        req, fingerprint="sha256:abc",
        find_completed=lambda fp: result_row,
        now=now,
    )
    assert d.reuse is False
    assert d.reason == "force_refresh"


# ── pure enqueue core ────────────────────────────────────────────────────────


class _MemStore:
    def __init__(self):
        self.by_fp_open: dict = {}
        self.by_fp_completed: dict = {}
        self.saved: list = []
        self.patches: list = []
        self.reuse_events: list = []
        self._n = 0

    def find_in_flight(self, fp):
        return find_in_flight_by_fingerprint(fp, self.by_fp_open)

    def find_completed(self, fp):
        return self.by_fp_completed.get(fp)

    def save(self, req):
        self.saved.append(dict(req))
        self.by_fp_open[req["fingerprint"]] = {
            "research_id": req["research_id"],
            "status": "queued",
            "priority": req.get("priority"),
            "fingerprint": req["fingerprint"],
            "plan_id": req.get("plan_id"),
        }

    def update(self, rid, patch):
        self.patches.append((rid, patch))
        for row in self.by_fp_open.values():
            if row.get("research_id") == rid:
                row.update(patch)

    def new_id(self):
        self._n += 1
        return f"res_test{self._n:03d}"

    def record_reuse(self, evt):
        self.reuse_events.append(evt)


def test_enqueue_in_flight_duplicate_and_priority_bump():
    store = _MemStore()
    req = _base_request(priority="normal")
    r1 = enqueue_research_request(
        dict(req),
        find_in_flight_by_fingerprint=store.find_in_flight,
        save_request=store.save,
        update_request=store.update,
        new_research_id=store.new_id,
        find_fresh_completed=store.find_completed,
    )
    assert r1.created is True
    assert r1.reason == "created"
    rid = r1.research_id

    r2 = enqueue_research_request(
        dict(req, priority="normal"),
        find_in_flight_by_fingerprint=store.find_in_flight,
        save_request=store.save,
        update_request=store.update,
        new_research_id=store.new_id,
        find_fresh_completed=store.find_completed,
    )
    assert r2.created is False
    assert r2.reason == "duplicate_in_flight"
    assert r2.research_id == rid

    r3 = enqueue_research_request(
        dict(req, priority="critical"),
        find_in_flight_by_fingerprint=store.find_in_flight,
        save_request=store.save,
        update_request=store.update,
        new_research_id=store.new_id,
        find_fresh_completed=store.find_completed,
    )
    assert r3.created is False
    assert r3.reason == "priority_bumped"
    assert r3.research_id == rid
    assert store.patches[-1][1]["priority"] == "critical"


def test_enqueue_ttl_reuse_and_after_completed_create():
    store = _MemStore()
    now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
    req = _base_request(priority="high")

    # Seed a fresh completed result under the fingerprint
    fp = compute_fingerprint(req)
    store.by_fp_completed[fp] = {
        "status": "completed",
        "result_id": "rr_old",
        "research_id": "res_old",
        "as_of": (now - timedelta(hours=1)).isoformat(),
        "findings": ["still hold"],
        "answers": [{"confidence": 0.75}],
    }

    r = enqueue_research_request(
        dict(req),
        find_in_flight_by_fingerprint=store.find_in_flight,
        save_request=store.save,
        update_request=store.update,
        new_research_id=store.new_id,
        find_fresh_completed=store.find_completed,
        record_reuse_event=store.record_reuse,
        now=now,
    )
    assert r.created is False
    assert r.reason == "reused_fresh_result"
    assert r.research_id == "res_old"
    assert store.reuse_events
    assert not store.saved

    # Expired → create new
    store.by_fp_completed[fp]["as_of"] = (now - timedelta(hours=10)).isoformat()
    r2 = enqueue_research_request(
        dict(req),
        find_in_flight_by_fingerprint=store.find_in_flight,
        save_request=store.save,
        update_request=store.update,
        new_research_id=store.new_id,
        find_fresh_completed=store.find_completed,
        now=now,
    )
    assert r2.created is True
    assert r2.reason == "created"
    assert r2.reuse_miss_reason == "ttl_expired"


def test_in_flight_blocks_before_ttl_path():
    store = _MemStore()
    now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
    # Same priority so path is duplicate_in_flight (not priority_bumped)
    req = _base_request(priority="high")
    fp = compute_fingerprint(req)
    store.by_fp_open[fp] = {
        "research_id": "res_inflight",
        "status": "running",
        "priority": "high",
        "fingerprint": fp,
    }
    store.by_fp_completed[fp] = {
        "status": "completed",
        "result_id": "rr_x",
        "research_id": "res_old",
        "as_of": (now - timedelta(minutes=5)).isoformat(),
        "findings": ["ok"],
        "answers": [{"confidence": 0.9}],
    }
    r = enqueue_research_request(
        dict(req),
        find_in_flight_by_fingerprint=store.find_in_flight,
        save_request=store.save,
        update_request=store.update,
        new_research_id=store.new_id,
        find_fresh_completed=store.find_completed,
        now=now,
    )
    assert r.reason == "duplicate_in_flight"
    assert r.research_id == "res_inflight"


# ── integration with cio_hermes_research store ───────────────────────────────


def test_cio_store_enqueue_dedupe_complete_reuse(tmp_path, monkeypatch):
    import lib.cio_hermes_research as hr

    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "cio").mkdir(parents=True)
    monkeypatch.setattr(hr, "REQUEST_PATH", Path("data/cio/hermes_research_requests.jsonl"))
    monkeypatch.setattr(hr, "RESULT_PATH", Path("data/cio/hermes_research_results.jsonl"))
    monkeypatch.setattr(hr, "PROJECTION_PATH", Path("data/cio/hermes_research_projection.json"))

    plan = {
        "plan_id": "plan_test_1",
        "situation_type": "S1_POSITION_LIFECYCLE",
        "symbols": ["SCHD"],
        "thesis_version": "desk@v5",
    }
    r1 = hr.enqueue_research_request(plan, priority="normal", reason="test")
    assert r1["ok"] and r1["created"] and r1["reason"] == "created"
    rid = r1["research_id"]
    fp = r1["fingerprint"]
    assert fp.startswith("sha256:")

    r2 = hr.enqueue_research_request(plan, priority="normal")
    assert r2["ok"] and r2["deduped"] and r2["research_id"] == rid
    assert r2["reason"] == "duplicate_in_flight"

    r3 = hr.enqueue_research_request(plan, priority="high")
    assert r3["reason"] == "priority_bumped"
    assert r3["research_id"] == rid

    # MVP-style answers without per-question status (coverage gate skips)
    done = hr.complete_research_result(
        rid,
        answers=[
            {"question_id": "q1", "confidence": 0.8, "text": "hold"},
            {"question_id": "q2", "confidence": 0.7, "text": "catalysts soft"},
            {"question_id": "q3", "confidence": 0.75, "text": "invalidation intact"},
        ],
        findings=["No thesis break"],
        summary="Hold with thesis remains valid.",
    )
    assert done["ok"]

    # Fresh completed → reuse
    r4 = hr.enqueue_research_request(plan, priority="high")
    assert r4["ok"], r4
    assert r4["reason"] == "reused_fresh_result", r4
    assert r4["reused"] is True
    assert r4["research_id"] == rid

    # Force refresh bypasses reuse
    r5 = hr.enqueue_research_request(plan, priority="high", force_refresh=True)
    assert r5["ok"] and r5["created"]
    assert r5["research_id"] != rid
