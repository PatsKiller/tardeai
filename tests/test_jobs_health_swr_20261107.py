"""LQ-20261107-219: /api/v2/jobs-health serves the last good body and refreshes in the background."""
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib import jobs_health as jh

REG = "registry.json"


def _result(tag):
    return {"rows": [{"lane_id": tag, "job": tag, "result": "failed", "market_hours_only": False, "scheduler": "cron"}],
            "tag": tag}


@pytest.fixture(autouse=True)
def _clean():
    jh._CACHE.clear()
    jh._REFRESHING.clear()
    yield
    jh._CACHE.clear()
    jh._REFRESHING.clear()


def _call(tmp_path):
    return jh.get_jobs_health({}, state_root=tmp_path, registry_path=tmp_path / REG)


def test_cold_computes_once_then_serves_fresh(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(jh, "_load", lambda *a: calls.append(1) or _result("a"))
    first = _call(tmp_path)
    second = _call(tmp_path)
    assert len(calls) == 1
    assert first["_swr"]["source"] == "computed" and second["_swr"]["source"] == "memory"
    assert second["_swr"]["stale"] is False


def test_stale_body_is_served_at_once_and_one_refresh_runs(tmp_path, monkeypatch):
    gate = threading.Event()
    calls = []

    def slow(*a):
        calls.append(1)
        if len(calls) > 1:
            gate.wait(5)
        return _result("new" if len(calls) > 1 else "old")

    monkeypatch.setattr(jh, "_load", slow)
    _call(tmp_path)
    key = next(iter(jh._CACHE))
    t, res, as_of = jh._CACHE[key]
    jh._CACHE[key] = (t - 120, res, as_of)           # older than FRESH_S
    t0 = time.monotonic()
    a = _call(tmp_path)
    b = _call(tmp_path)
    assert time.monotonic() - t0 < 1.0                # nobody waited for the slow refresh
    assert a["tag"] == b["tag"] == "old"
    assert a["_swr"]["stale"] is True and a["_swr"]["refreshing"] is True
    assert len(calls) == 2                            # exactly one background refresh
    gate.set()
    for _ in range(50):
        if not jh._REFRESHING:
            break
        time.sleep(0.05)
    assert _call(tmp_path)["tag"] == "new"


def test_failed_refresh_keeps_last_good_body(tmp_path, monkeypatch):
    state = {"n": 0}

    def load(*a):
        state["n"] += 1
        if state["n"] > 1:
            raise RuntimeError("boom")
        return _result("good")

    monkeypatch.setattr(jh, "_load", load)
    _call(tmp_path)
    key = next(iter(jh._CACHE))
    t, res, as_of = jh._CACHE[key]
    jh._CACHE[key] = (t - 120, res, as_of)
    assert _call(tmp_path)["tag"] == "good"
    for _ in range(50):
        if not jh._REFRESHING:
            break
        time.sleep(0.05)
    assert _call(tmp_path)["tag"] == "good"


def test_restart_serves_the_disk_copy_without_computing_inline(tmp_path, monkeypatch):
    monkeypatch.setattr(jh, "_load", lambda *a: _result("disk"))
    _call(tmp_path)
    path = tmp_path / jh.LAST_GOOD_REL
    assert path.exists() and (path.stat().st_mode & 0o777) == 0o600
    jh._CACHE.clear()                                  # a restart
    gate = threading.Event()
    monkeypatch.setattr(jh, "_load", lambda *a: (gate.wait(5), _result("fresh"))[1])
    t0 = time.monotonic()
    body = _call(tmp_path)
    assert time.monotonic() - t0 < 1.0
    assert body["tag"] == "disk" and body["_swr"]["source"] == "disk"
    gate.set()
    for _ in range(50):
        if not jh._REFRESHING:
            break
        time.sleep(0.05)


def test_too_old_body_is_not_served(tmp_path, monkeypatch):
    monkeypatch.setattr(jh, "_load", lambda *a: _result("x"))
    _call(tmp_path)
    key = next(iter(jh._CACHE))
    t, res, as_of = jh._CACHE[key]
    jh._CACHE[key] = (t - jh.MAX_STALE_S - 10, res, as_of)
    monkeypatch.setattr(jh, "_load", lambda *a: _result("recomputed"))
    body = _call(tmp_path)
    assert body["tag"] == "recomputed" and body["_swr"]["source"] == "computed"


def test_explicit_now_bypasses_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(jh, "_load", lambda *a: _result("t"))
    out = jh.get_jobs_health({}, state_root=tmp_path, registry_path=tmp_path / REG, now=datetime.now(timezone.utc))
    assert "_swr" not in out and not jh._CACHE


def _stamp(moment):
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _seed_hour_old_board(tmp_path, *, embedded_at):
    """A jobs-board snapshot an hour old whose frozen monitor already failed the 180s check."""
    body_at = datetime.now(timezone.utc) - timedelta(hours=1)
    cause = "Independent monitor receipt missing, stale or a dry run"
    result = {
        "schema": "JobsHealth@v1",
        "as_of": _stamp(body_at),
        "rows": [],
        "summary": {"due_today": 0, "succeeded": 0, "failed": 0, "missed": 0, "skipped": 0,
                    "paused": 0, "retired": 0, "unknown": 0, "due": 0, "outside_window": 0},
        "monitor": {"observed_at": _stamp(embedded_at), "status": "UNKNOWN", "cause": cause, "notification": None},
        "watchers": [{"id": "missed-run-watchdog", "label": "Missed-run watchdog", "status": "degraded", "cause": cause}],
        "incidents": [{"id": "job_monitor_unmeasured", "severity": "warning", "title": "Job monitoring needs attention",
                       "message": cause, "href": "/ops/jobs", "source": "job_execution"}],
        "incident_count": 1,
    }
    path = tmp_path / jh.LAST_GOOD_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"as_of": body_at.isoformat(), "result": result}))


def _live_receipt(tmp_path, observed, *, status="OK", mode="monitor"):
    path = tmp_path / "data/runtime/cron_outage_watchdog_latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": "CronOutageWatchdog@v1", "mode": mode, "status": status,
        "observed_at": _stamp(observed),
        "notification": {"status": "NOT_REQUIRED", "delivered": False},
    }))


def _hold_refresh(monkeypatch):
    """The hour-old body is stale, so a serve starts one background rebuild. Hold it so the
    assertion reads the served snapshot, not the rebuild."""
    gate = threading.Event()

    def slow(*a):
        gate.wait(5)
        return _result("should-not-serve")

    monkeypatch.setattr(jh, "_load", slow)
    return gate


def test_hour_old_board_grades_the_live_receipt_not_the_frozen_monitor(tmp_path, monkeypatch):
    """Page walk: the watchdog receipt is fresh, the jobs-board snapshot is ~1 h old, and line 436's
    180 s window had already marked that snapshot UNKNOWN. Serving it must re-grade the live receipt."""
    gate = _hold_refresh(monkeypatch)
    try:
        now = datetime.now(timezone.utc)
        observed = now - timedelta(seconds=30)
        _seed_hour_old_board(tmp_path, embedded_at=now - timedelta(hours=1))
        _live_receipt(tmp_path, observed, status="OK")
        body = _call(tmp_path)
        assert body.get("tag") != "should-not-serve"
        assert body["_swr"]["source"] == "disk" and body["_swr"]["stale"] is True
        assert body["monitor"]["status"] == "OK" and body["monitor"]["cause"] is None
        assert body["monitor"]["observed_at"] == _stamp(observed)
        light = {row["id"]: row for row in body["watchers"]}["missed-run-watchdog"]
        assert light["status"] == "ok" and light["cause"] is None
        assert all(row["id"] != "job_monitor_unmeasured" for row in body["incidents"])
        assert body["incident_count"] == 0
    finally:
        gate.set()


def test_receipt_stamped_during_the_build_still_arms_when_served(tmp_path, monkeypatch):
    """A receipt rewritten 17 s after the board clock (the live negative-age shape) is fresh."""
    gate = _hold_refresh(monkeypatch)
    try:
        now = datetime.now(timezone.utc)
        _seed_hour_old_board(tmp_path, embedded_at=now - timedelta(hours=1))
        _live_receipt(tmp_path, now + timedelta(seconds=17), status="CRIT")
        body = _call(tmp_path)
        assert body["monitor"]["status"] == "CRIT" and body["monitor"]["cause"] is None
    finally:
        gate.set()


def test_served_board_still_rejects_a_receipt_older_than_180s(tmp_path, monkeypatch):
    gate = _hold_refresh(monkeypatch)
    try:
        now = datetime.now(timezone.utc)
        _seed_hour_old_board(tmp_path, embedded_at=now - timedelta(hours=1))
        _live_receipt(tmp_path, now - timedelta(seconds=181), status="OK")
        body = _call(tmp_path)
        assert body["monitor"]["status"] == "UNKNOWN"
        assert body["monitor"]["cause"] == "Independent monitor receipt missing, stale or a dry run"
        light = {row["id"]: row for row in body["watchers"]}["missed-run-watchdog"]
        assert light["status"] == "degraded"
    finally:
        gate.set()


def test_served_board_rejects_a_dry_run_and_a_far_future_receipt(tmp_path, monkeypatch):
    gate = _hold_refresh(monkeypatch)
    try:
        now = datetime.now(timezone.utc)
        _seed_hour_old_board(tmp_path, embedded_at=now - timedelta(hours=1))
        _live_receipt(tmp_path, now - timedelta(seconds=10), mode="dry_run")
        assert _call(tmp_path)["monitor"]["status"] == "UNKNOWN"
        _live_receipt(tmp_path, now + timedelta(minutes=5), status="OK")
        assert _call(tmp_path)["monitor"]["status"] == "UNKNOWN"
    finally:
        gate.set()
