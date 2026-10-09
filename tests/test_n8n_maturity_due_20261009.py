"""N8N Maturity B5.3 — pure `compute_due` (design 02 §3.2) against a frozen clock and a tmp_path ledger.

Every state of the §3.2 table, the mode filter, catch-up (sub-hourly vs daily), limit/priority, DST spring
2026-03-08 and fall 2026-11-01 (one key per local minute), errors[] isolation, forbidden lanes, read-only,
and the DueResponse@v1 schema. Hermetic: tmp_path ledgers, fixed clock; the retry policies are the repo's
config/n8n_retry_policies.json read as data. No socket, no live ledger, no send.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib import n8n_due as D
from scripts.lib import n8n_retry_policy as RP
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs" / "implementation" / "n8n-maturity" / "schemas" / "due-response.schema.json"
NOW = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)          # 10:00 America/New_York (EDT)
POLICIES = RP.load_policies(ROOT / "config" / "n8n_retry_policies.json")


def _row(lane, cron, *, mode="dry_run", klass="monitor", priority=5, policy="transient-2", catchup=None,
         after=None, **extra):
    d = {"mode": mode, "cron": list(cron), "class": klass, "priority": priority, "retry_policy": policy,
         "wave": "W1"}
    if catchup is not None:
        d["catchup_min"] = catchup
    if after is not None:
        d["after"] = after
    row = {"lane_id": lane, "scheduler": {"kind": "cron", "expression": "x"}, "dispatch": d}
    row.update(extra)
    return row


def _allow(*lanes, dry=("--dry-run",), live=()):
    return {lane: {"lane_id": lane, "command": ["$PY", "scripts/x.py"], "dry_run_arg": None if dry is None else list(dry),
                   "live_arg": None if live is None else list(live)} for lane in lanes}


@pytest.fixture
def store(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    yield LedgerRunStore(ledger)
    ledger.close()


def _put(store, run_id, lane, mode, state, *, finished=None, exit_code=None, attempt=None, reason=None):
    """Insert a runs row with full control of state/finish time (the executor's job, simulated)."""
    store.request(run_id=run_id, lane_id=lane, mode=mode, requested_by="t", caller_id="t",
                  now=(finished or NOW).timestamp() - 5, attempt=attempt)
    if state != "REQUESTED":
        receipt = json.dumps({"reason": reason}) if reason else None
        store._l._conn.execute(
            "UPDATE runs SET state = ?, finished_at = ?, exit_code = ?, receipt_json = ? WHERE run_id = ?",
            (state, finished.isoformat() if finished else None, exit_code, receipt, run_id))
        store._l._conn.commit()


def _due(rows, allow, store=None, now=NOW, **kw):
    return D.compute_due(rows, allow, POLICIES, store, now, **kw)


def _keys(resp):
    return [i["idempotency_key"] for i in resp["items"]]


def _held(resp, state):
    return [h for h in resp["held"] if h["state"] == state]


# ── a minimal draft 2020-12 checker for the subset the schema uses (jsonschema is not installed here) ──

def _check(inst, sch, root, path="$"):
    if "$ref" in sch:
        return _check(inst, root["$defs"][sch["$ref"].split("/")[-1]], root, path)
    if "const" in sch:
        assert inst == sch["const"], path
    if "enum" in sch:
        assert inst in sch["enum"], (path, inst)
    t = sch.get("type")
    if t == "object":
        assert isinstance(inst, dict), path
        for k in sch.get("required", []):
            assert k in inst, (path, k)
        props = sch.get("properties", {})
        if sch.get("additionalProperties") is False:
            assert set(inst) <= set(props), (path, set(inst) - set(props))
        for k, v in inst.items():
            if k in props:
                _check(v, props[k], root, f"{path}.{k}")
    elif t == "array":
        assert isinstance(inst, list), path
        assert len(inst) <= sch.get("maxItems", 10**9), path
        for i, v in enumerate(inst):
            _check(v, sch.get("items", {}), root, f"{path}[{i}]")
    elif t == "integer":
        assert isinstance(inst, int) and not isinstance(inst, bool), path
        assert sch.get("minimum", -10**9) <= inst <= sch.get("maximum", 10**9), path
    elif t == "string":
        assert isinstance(inst, str), path
        assert sch.get("minLength", 0) <= len(inst) <= sch.get("maxLength", 10**9), path
        if "pattern" in sch:
            assert re.search(sch["pattern"], inst), (path, inst)
    elif t == "boolean":
        assert isinstance(inst, bool), path


def _validate(resp):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        import jsonschema  # type: ignore
    except ImportError:
        _check(resp, schema, schema)
    else:
        jsonschema.validate(resp, schema)
    for item in resp["items"]:                          # the gateway's own key regex too
        assert re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", item["idempotency_key"])
        assert set(item) == {"lane_id", "mode", "idempotency_key", "attempt", "slot_local", "reason", "priority"}


# ── states ──────────────────────────────────────────────────────────────────────────────────────

def test_due_slot_is_emitted_with_the_server_minted_key(store):
    resp = _due([_row("storage-watch", ["0 10 * * *"])], _allow("storage-watch"), store)
    assert resp["items"] == [{"lane_id": "storage-watch", "mode": "dry_run",
                              "idempotency_key": "d:storage-watch:dry_run:20261009T1000", "attempt": 1,
                              "slot_local": "20261009T1000", "reason": "schedule", "priority": 5}]
    assert resp["counts"]["DUE"] == 1 and resp["errors"] == [] and resp["truncated"] == 0
    _validate(resp)


def test_in_flight_and_done_are_not_emitted(store):
    rows = [_row("a-lane", ["30 9 * * *"]), _row("b-lane", ["30 9 * * *"]), _row("c-lane", ["30 9 * * *"])]
    _put(store, "d:a-lane:dry_run:20261009T0930", "a-lane", "dry_run", "RUNNING")
    _put(store, "d:b-lane:dry_run:20261009T0930", "b-lane", "dry_run", "RUN_DONE", finished=NOW - timedelta(minutes=20))
    _put(store, "d:c-lane:dry_run:20261009T0930", "c-lane", "dry_run", "RUN_SKIPPED_LOCK",
         finished=NOW - timedelta(minutes=20))
    resp = _due(rows, _allow("a-lane", "b-lane", "c-lane"), store)
    assert resp["items"] == []
    assert resp["counts"]["IN_FLIGHT"] == 1 and resp["counts"]["DONE"] == 2
    _validate(resp)


def test_retry_due_after_backoff_and_retry_wait_before(store):
    rows = [_row("r-lane", ["30 9 * * *"]), _row("w-lane", ["30 9 * * *"])]
    _put(store, "d:r-lane:dry_run:20261009T0930", "r-lane", "dry_run", "RUN_FAILED", exit_code=75,
         finished=NOW - timedelta(minutes=5))
    _put(store, "d:w-lane:dry_run:20261009T0930", "w-lane", "dry_run", "RUN_FAILED", exit_code=75,
         finished=NOW - timedelta(seconds=10))
    resp = _due(rows, _allow("r-lane", "w-lane"), store)
    assert resp["items"] == [{"lane_id": "r-lane", "mode": "dry_run",
                              "idempotency_key": "d:r-lane:dry_run:20261009T0930:a2", "attempt": 2,
                              "slot_local": "20261009T0930", "reason": "retry", "priority": 5}]
    wait = _held(resp, "RETRY_WAIT")
    assert len(wait) == 1 and wait[0]["lane_id"] == "w-lane" and wait[0]["retry_at"] == "2026-10-09T14:00:20Z"
    _validate(resp)


def test_attempt_three_follows_attempt_two_then_exhausts_to_dead_letter(store):
    rows = [_row("r-lane", ["30 9 * * *"])]
    _put(store, "d:r-lane:dry_run:20261009T0930", "r-lane", "dry_run", "RUN_FAILED", exit_code=75,
         finished=NOW - timedelta(minutes=20), attempt=1)
    _put(store, "d:r-lane:dry_run:20261009T0930:a2", "r-lane", "dry_run", "RUN_FAILED", exit_code=75,
         finished=NOW - timedelta(minutes=5), attempt=2)
    assert _keys(_due(rows, _allow("r-lane"), store)) == ["d:r-lane:dry_run:20261009T0930:a3"]
    _put(store, "d:r-lane:dry_run:20261009T0930:a3", "r-lane", "dry_run", "RUN_FAILED", exit_code=75,
         finished=NOW - timedelta(minutes=1), attempt=3)
    resp = _due(rows, _allow("r-lane"), store)
    assert resp["items"] == [] and resp["counts"]["DEAD_LETTER"] == 1      # max_attempts 3, not yet finalized


def test_terminal_failure_and_dead_letter_row_are_held(store):
    rows = [_row("t-lane", ["30 9 * * *"]), _row("x-lane", ["30 9 * * *"])]
    _put(store, "d:t-lane:dry_run:20261009T0930", "t-lane", "dry_run", "RUN_FAILED", exit_code=2,
         finished=NOW - timedelta(minutes=5))
    store.record_dead_letter(slot_key="d:x-lane:dry_run:20261009T0930", lane_id="x-lane", mode="dry_run",
                             slot_local="20261009T0930", attempts=3, last_run_id="d:x-lane:dry_run:20261009T0930:a3",
                             last_state="RUN_FAILED", last_reason=None, verdict="retryable", now=NOW.timestamp() - 60)
    resp = _due(rows, _allow("t-lane", "x-lane"), store)
    assert resp["items"] == []
    assert sorted(h["lane_id"] for h in _held(resp, "DEAD_LETTER")) == ["t-lane", "x-lane"]
    _validate(resp)


def test_released_dead_letter_rearms_as_retry_due_dlq_release(store):
    rows = [_row("x-lane", ["30 9 * * *"])]
    key = "d:x-lane:dry_run:20261009T0930"
    _put(store, key + ":a3", "x-lane", "dry_run", "RUN_FAILED", exit_code=75, finished=NOW - timedelta(minutes=3),
         attempt=3)
    store.record_dead_letter(slot_key=key, lane_id="x-lane", mode="dry_run", slot_local="20261009T0930", attempts=3,
                             last_run_id=key + ":a3", last_state="RUN_FAILED", last_reason=None, verdict="retryable",
                             now=NOW.timestamp() - 120, klass="monitor", max_attempts=3, policy="transient-2")
    assert _due(rows, _allow("x-lane"), store)["items"] == []
    store.release_dead_letter(key, "operator", "fixed disk", NOW.timestamp() - 30)
    resp = _due(rows, _allow("x-lane"), store)
    assert resp["items"][0]["idempotency_key"] == key + ":a4"
    assert resp["items"][0]["reason"] == "dlq_release" and resp["items"][0]["attempt"] == 4
    check = D.check_slot_key(key + ":a4", "x-lane", "dry_run", registry_rows=rows, allowlist=_allow("x-lane"),
                             policies=POLICIES, run_store=store, now=NOW)
    assert check.ok and check.parent_run_id == key + ":a3" and check.slot_key == key
    _validate(resp)


def test_released_but_not_rearmable_dead_letter_stays_dead(store):
    """B5.4 contract: a dead letter with unknown class/max_attempts (legacy) never re-arms, even if released."""
    rows = [_row("x-lane", ["30 9 * * *"])]
    key = "d:x-lane:dry_run:20261009T0930"
    store.record_dead_letter(slot_key=key, lane_id="x-lane", mode="dry_run", slot_local="20261009T0930", attempts=1,
                             last_run_id=key, last_state="RUN_FAILED", last_reason=None, verdict="terminal",
                             now=NOW.timestamp() - 120)
    store._l._conn.execute("UPDATE dead_letters SET released_at = ? WHERE slot_key = ?",
                           ((NOW - timedelta(seconds=30)).isoformat(), key))
    store._l._conn.commit()
    resp = _due(rows, _allow("x-lane"), store)
    assert resp["items"] == [] and resp["counts"]["DEAD_LETTER"] == 1


def test_breaker_open_holds_every_emittable_slot(store):
    rows = [_row("b-lane", ["30 9 * * *"])]
    store.open_breaker("b-lane", 3, NOW.timestamp() - 600)
    resp = _due(rows, _allow("b-lane"), store)
    assert resp["items"] == [] and _held(resp, "BREAKER_OPEN")[0]["slot_local"] == "20261009T0930"
    store.release_breaker("b-lane", "operator", NOW.timestamp() - 60)
    assert _keys(_due(rows, _allow("b-lane"), store)) == ["d:b-lane:dry_run:20261009T0930"]


def test_missed_is_reported_once_for_the_slot_before_the_window(store):
    rows = [_row("m-lane", ["30 9 * * *"], catchup=20)]             # window 09:40-10:00 ET: no fire inside
    resp = _due(rows, _allow("m-lane"), store)
    assert resp["items"] == [] and resp["counts"]["MISSED"] == 1
    assert _held(resp, "MISSED")[0]["slot_local"] == "20261009T0930"
    _put(store, "d:m-lane:dry_run:20261009T0930", "m-lane", "dry_run", "RUN_DONE", finished=NOW - timedelta(minutes=25))
    assert _due(rows, _allow("m-lane"), store)["counts"]["MISSED"] == 0
    _validate(resp)


# ── after-gates and the mode filter ─────────────────────────────────────────────────────────────

def _gated(mode="live", soft=False, deadline=90, same_day=True):
    up = _row("close-capture", ["0 9 * * *"], mode="off")
    edge = {"lane_id": "close-capture", "deadline_min": deadline, "same_day": same_day}
    if soft:
        edge["soft"] = True
    return [up, _row("planning", ["30 9 * * *"], mode=mode, after=[edge])]


def test_waiting_after_until_the_predecessor_has_a_live_run_done_today(store):
    rows = _gated()
    resp = _due(rows, _allow("planning", "close-capture"), store)
    w = _held(resp, "WAITING_AFTER")
    assert resp["items"] == [] and w[0]["waiting_on"] == ["close-capture"]
    assert w[0]["wait_deadline"] == "2026-10-09T15:00:00Z"                 # 09:30 ET + 90 min
    # a DRY-RUN RUN_DONE of the predecessor does not satisfy a live after-gate (mode filter, §3.2 step 4)
    _put(store, "d:close-capture:dry_run:20261009T0900", "close-capture", "dry_run", "RUN_DONE",
         finished=NOW - timedelta(minutes=50))
    assert _held(_due(rows, _allow("planning", "close-capture"), store), "WAITING_AFTER")
    # a live RUN_DONE YESTERDAY (ET) does not either
    _put(store, "legacy-close-capture-yesterday", "close-capture", "live", "RUN_DONE", finished=NOW - timedelta(hours=20))
    assert _held(_due(rows, _allow("planning", "close-capture"), store), "WAITING_AFTER")
    _put(store, "legacy-close-capture-today", "close-capture", "live", "RUN_DONE", finished=NOW - timedelta(minutes=40))
    assert _keys(_due(rows, _allow("planning", "close-capture"), store)) == ["d:planning:live:20261009T0930"]


def test_dry_run_lane_accepts_a_dry_run_predecessor(store):
    rows = _gated(mode="dry_run")
    _put(store, "d:close-capture:dry_run:20261009T0900", "close-capture", "dry_run", "RUN_DONE",
         finished=NOW - timedelta(minutes=50))
    assert _keys(_due(rows, _allow("planning", "close-capture"), store)) == ["d:planning:dry_run:20261009T0930"]


def test_soft_edge_emits_at_its_deadline_hard_edge_keeps_waiting(store):
    hard = _due(_gated(deadline=20), _allow("planning", "close-capture"), store)
    assert hard["items"] == [] and _held(hard, "WAITING_AFTER")[0]["wait_deadline"] == "2026-10-09T13:50:00Z"
    soft = _due(_gated(deadline=20, soft=True), _allow("planning", "close-capture"), store)
    assert _keys(soft) == ["d:planning:live:20261009T0930"]


def test_mode_filter_dry_run_row_never_satisfies_the_live_slot(store):
    rows = [_row("mf-lane", ["30 9 * * *"], mode="live")]
    _put(store, "d:mf-lane:dry_run:20261009T0930", "mf-lane", "dry_run", "RUN_DONE", finished=NOW - timedelta(minutes=10))
    assert _keys(_due(rows, _allow("mf-lane"), store)) == ["d:mf-lane:live:20261009T0930"]


# ── catch-up, ordering, limit ───────────────────────────────────────────────────────────────────

def test_sub_hourly_keeps_only_the_newest_slot_daily_replays_inside_catchup(store):
    sub = _due([_row("sub-lane", ["*/15 * * * *"])], _allow("sub-lane"), store)
    assert _keys(sub) == ["d:sub-lane:dry_run:20261009T1000"] and sub["counts"]["MISSED"] == 0
    daily = _due([_row("day-lane", ["0 9 * * *", "30 9 * * *"], catchup=90)], _allow("day-lane"), store)
    assert _keys(daily) == ["d:day-lane:dry_run:20261009T0900", "d:day-lane:dry_run:20261009T0930"]
    assert [i["reason"] for i in daily["items"]] == ["catchup", "schedule"]


def test_catchup_defaults_to_the_policy_and_block_overrides(store):
    rows = [_row("p-lane", ["0 9 * * *"])]                            # 60 min ago: policy transient-2 catchup 60
    assert _keys(_due(rows, _allow("p-lane"), store)) == []          # start exclusive: 09:00 is outside
    rows = [_row("p-lane", ["0 9 * * *"], catchup=61)]
    assert _keys(_due(rows, _allow("p-lane"), store)) == ["d:p-lane:dry_run:20261009T0900"]


def test_priority_order_then_slot_and_limit_truncation(store):
    rows = [_row(f"lane-{p}", ["30 9 * * *", "45 9 * * *"], priority=p) for p in (7, 1, 4)]
    resp = _due(rows, _allow(*[r["lane_id"] for r in rows]), store, limit=3)
    assert _keys(resp) == ["d:lane-1:dry_run:20261009T0930", "d:lane-1:dry_run:20261009T0945",
                           "d:lane-4:dry_run:20261009T0930"]
    assert resp["truncated"] == 3 and resp["limit"] == 3 and resp["counts"]["DUE"] == 6
    assert _due(rows, _allow(*[r["lane_id"] for r in rows]), store, limit=1000)["limit"] == 100
    _validate(resp)


# ── DST ─────────────────────────────────────────────────────────────────────────────────────────

def test_dst_spring_forward_gap_fires_once_at_the_first_valid_minute(store):
    now = datetime(2026, 3, 8, 7, 5, tzinfo=timezone.utc)          # 03:05 EDT, the gap was 02:00-03:00
    resp = _due([_row("spring", ["30 2 * * *"])], _allow("spring"), store, now=now)
    assert _keys(resp) == ["d:spring:dry_run:20260308T0300"]
    _validate(resp)


def test_dst_fall_back_fold_mints_one_key_per_local_minute(store):
    rows = [_row("fall", ["30 1 * * *"], catchup=120)]
    first = datetime(2026, 11, 1, 5, 45, tzinfo=timezone.utc)      # 01:45 EDT (fold 0)
    assert _keys(_due(rows, _allow("fall"), store, now=first)) == ["d:fall:dry_run:20261101T0130"]
    _put(store, "d:fall:dry_run:20261101T0130", "fall", "dry_run", "RUN_DONE", finished=first)
    later = datetime(2026, 11, 1, 7, 0, tzinfo=timezone.utc)       # 02:00 EST, after the repeated 01:30
    resp = _due(rows, _allow("fall"), store, now=later)
    assert resp["items"] == [] and resp["counts"]["DONE"] == 1
    assert sum(resp["counts"].values()) - resp["counts"]["MISSED"] == 1      # one slot for both 01:30s
    assert [h["slot_local"] for h in _held(resp, "MISSED")] == ["20261031T0130"]
    sub = _due([_row("fall-sub", ["*/30 * * * *"])], _allow("fall-sub"), store, now=later)
    assert len(sub["items"]) == 1


# ── errors, eligibility, sources, read-only ─────────────────────────────────────────────────────

def test_errors_are_isolated_per_lane(store):
    rows = [
        _row("good-lane", ["30 9 * * *"]),
        _row("bad-cron", ["61 9 * * *"]),
        _row("bad-policy", ["30 9 * * *"], policy="no-such-policy"),
        _row("no-entry", ["30 9 * * *"]),
        _row("no-live-arg", ["30 9 * * *"], mode="live"),
        _row("llm-lane", ["30 9 * * *"], klass="llm"),
        _row("heavy-default", ["30 9 * * *"], klass="heavy"),            # transient-2 does not permit heavy
        _row("orphan-after", ["30 9 * * *"], after=[{"lane_id": "nowhere"}]),
    ]
    allow = {**_allow("good-lane", "bad-cron", "bad-policy", "llm-lane", "heavy-default", "orphan-after"),
             **_allow("no-live-arg", live=None)}
    resp = _due(rows, allow, store)
    assert _keys(resp) == ["d:good-lane:dry_run:20261009T0930"]
    codes = {e["lane_id"]: e["code"] for e in resp["errors"]}
    assert codes == {"bad-cron": "bad_cron", "bad-policy": "unknown_retry_policy", "no-entry": "not_allowlisted",
                     "no-live-arg": "not_allowlisted", "llm-lane": "class_not_permitted",
                     "heavy-default": "class_not_permitted", "orphan-after": "after_unknown_lane"}
    _validate(resp)


def test_forbidden_and_stay_behind_lanes_are_never_emitted(store):
    rows = [_row("broker-sync", ["30 9 * * *"], mode="live"),
            _row("stops-lane", ["30 9 * * *"], mode="live", watch={"stay_behind": True}),
            _row("off-lane", ["30 9 * * *"], mode="off"),
            {"lane_id": "no-block", "scheduler": {"kind": "cron", "expression": "x"}}]
    resp = _due(rows, _allow("broker-sync", "stops-lane", "off-lane", "no-block"), store)
    assert resp["items"] == [] and resp["errors"] == [] and sum(resp["counts"].values()) == 0
    ok, state = D.validate_slot_key("d:broker-sync:live:20261009T0930", "broker-sync", "live", registry_rows=rows,
                                    allowlist=_allow("broker-sync"), policies=POLICIES, run_store=store, now=NOW)
    assert (ok, state) == (False, "LANE_NOT_DISPATCHED")


def test_lane_filter_and_event_digest_sources_return_the_shape(store):
    rows = [_row("a-lane", ["30 9 * * *"]), _row("b-lane", ["30 9 * * *"])]
    resp = _due(rows, _allow("a-lane", "b-lane"), store, lane_filter=["b-lane"])
    assert _keys(resp) == ["d:b-lane:dry_run:20261009T0930"] and resp["lane_filter"] == ["b-lane"]
    for source in ("event", "digest"):
        r = _due(rows, _allow("a-lane", "b-lane"), store, source=source)
        assert r["source"] == source and r["items"] == [] and r["ok"] is True
        _validate(r)
    with pytest.raises(ValueError):
        _due(rows, _allow("a-lane"), store, source="cron")


def test_shas_default_to_canonical_json_and_pass_through(store):
    rows = [_row("a-lane", ["30 9 * * *"])]
    resp = _due(rows, _allow("a-lane"), store)
    assert resp["registry_sha"] == D.canonical_sha(rows) and resp["policies_sha"] == POLICIES.sha256
    resp = _due(rows, _allow("a-lane"), store, registry_sha="1" * 64, allowlist_sha="2" * 64, policies_sha="3" * 64)
    assert (resp["registry_sha"], resp["allowlist_sha"], resp["policies_sha"]) == ("1" * 64, "2" * 64, "3" * 64)


def test_due_is_read_only(store):
    rows = [_row("a-lane", ["30 9 * * *"]), _row("r-lane", ["30 9 * * *"])]
    _put(store, "d:r-lane:dry_run:20261009T0930", "r-lane", "dry_run", "RUN_FAILED", exit_code=75,
         finished=NOW - timedelta(minutes=5))
    conn = store._l._conn
    before = conn.total_changes
    snapshot = [tuple(r) for r in conn.execute("SELECT * FROM runs ORDER BY run_id")]
    _due(rows, _allow("a-lane", "r-lane"), store)
    D.check_slot_key("d:a-lane:dry_run:20261009T0930", "a-lane", "dry_run", registry_rows=rows,
                     allowlist=_allow("a-lane", "r-lane"), policies=POLICIES, run_store=store, now=NOW)
    assert conn.total_changes == before
    assert [tuple(r) for r in conn.execute("SELECT * FROM runs ORDER BY run_id")] == snapshot


def test_none_run_store_is_an_empty_ledger():
    assert _keys(_due([_row("a-lane", ["30 9 * * *"])], _allow("a-lane"), None)) == ["d:a-lane:dry_run:20261009T0930"]


# ── validate_slot_key ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key,lane,mode,expected", [
    ("d:a-lane:dry_run:20261009T0930", "a-lane", "dry_run", (True, "DUE")),
    ("d:a-lane:dry_run:20261009T0945", "a-lane", "dry_run", (False, "NOT_A_SLOT")),     # forged minute
    ("d:a-lane:dry_run:20261010T0930", "a-lane", "dry_run", (False, "NOT_A_SLOT")),     # future slot
    ("d:a-lane:dry_run:20261008T0930", "a-lane", "dry_run", (False, "NOT_A_SLOT")),     # yesterday (MISSED)
    ("d:a-lane:dry_run:20261009T0930:a2", "a-lane", "dry_run", (False, "ATTEMPT_MISMATCH")),
    ("d:a-lane:live:20261009T0930", "a-lane", "live", (False, "MODE_MISMATCH")),
    ("d:a-lane:live:20261009T0930", "a-lane", "dry_run", (False, "KEY_MISMATCH")),
    ("d:b-lane:dry_run:20261009T0930", "a-lane", "dry_run", (False, "KEY_MISMATCH")),
    ("e:a-lane:dry_run:0123456789ab", "a-lane", "dry_run", (False, "MALFORMED_KEY")),
    ("e:a-lane:dry_run:20261009T0930", "a-lane", "dry_run", (False, "UNSUPPORTED_SOURCE")),
    ("d:a-lane:dry_run:2026", "a-lane", "dry_run", (False, "MALFORMED_KEY")),
])
def test_validate_slot_key(store, key, lane, mode, expected):
    rows = [_row("a-lane", ["30 9 * * *"])]
    assert D.validate_slot_key(key, lane, mode, registry_rows=rows, allowlist=_allow("a-lane"), policies=POLICIES,
                               run_store=store, now=NOW) == expected


def test_validate_slot_key_reports_the_slot_state_once_requested(store):
    rows = [_row("a-lane", ["30 9 * * *"])]
    _put(store, "d:a-lane:dry_run:20261009T0930", "a-lane", "dry_run", "REQUESTED")
    assert D.validate_slot_key("d:a-lane:dry_run:20261009T0930", "a-lane", "dry_run", registry_rows=rows,
                               allowlist=_allow("a-lane"), policies=POLICIES, run_store=store,
                               now=NOW) == (False, "IN_FLIGHT")


def test_file_sources_hash_file_bytes_and_type_their_failures(tmp_path):
    reg = tmp_path / "reg.json"
    reg.write_bytes(json.dumps({"lanes": [_row("a-lane", ["30 9 * * *"])]}).encode())
    allow = tmp_path / "allow.json"
    allow.write_bytes(json.dumps({"schema": D.ALLOWLIST_SCHEMA, "lanes": list(_allow("a-lane").values())}).encode())
    src = D.file_sources(reg, allow, ROOT / "config" / "n8n_retry_policies.json")
    rows, rsha = src.load_registry()
    import hashlib
    assert rsha == hashlib.sha256(reg.read_bytes()).hexdigest() and rows[0]["lane_id"] == "a-lane"
    assert set(src.load_allowlist()[0]) == {"a-lane"}
    bad = D.file_sources(tmp_path / "missing.json", tmp_path / "missing.json", tmp_path / "missing.json")
    for loader, code in ((bad.load_registry, "registry_unreadable"), (bad.load_allowlist, "allowlist_unreadable"),
                         (bad.load_policies, "policies_unreadable")):
        with pytest.raises(D.DueSourceError) as exc:
            loader()
        assert exc.value.code == code
