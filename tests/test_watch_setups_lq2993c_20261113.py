"""LQ-20261107-2993c: honest as_of for watchpool/sectors, durable alerts evaluator record + certified counts."""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import watch_alerts_record as rec  # noqa: E402
from lib import watch_setups_reads as ws  # noqa: E402
from lib import site_payload_reads as spr  # noqa: E402

NOW = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)


def test_append_then_read_is_liveness_from_last_run_not_alert_rows():
    with tempfile.TemporaryDirectory() as d:
        rec.append_run(armed=5, fired=1, composites=0, rc=0, root=d, now=NOW - timedelta(minutes=10))
        rec.append_run(armed=4, fired=0, composites=0, rc=0, root=d, now=NOW - timedelta(minutes=5))
        out = rec.read_record(root=d, now=NOW)
        assert out["readable"] is True
        assert out["last_run_at"] == (NOW - timedelta(minutes=5)).isoformat()
        assert out["age_s"] == 300
        assert out["certified"] == {"armed": 4, "fired_24h": 1, "runs_24h": 2, "ok_runs_24h": 2, "as_of": out["last_run_at"]}


def test_failed_run_does_not_advance_last_ok():
    with tempfile.TemporaryDirectory() as d:
        rec.append_run(armed=4, fired=0, composites=0, rc=0, root=d, now=NOW - timedelta(minutes=50))
        rec.append_run(armed=0, fired=0, composites=0, rc=1, error="boom", root=d, now=NOW - timedelta(minutes=5))
        out = rec.read_record(root=d, now=NOW)
        assert out["last_run_at"] == (NOW - timedelta(minutes=5)).isoformat()
        assert out["last_ok_at"] == (NOW - timedelta(minutes=50)).isoformat()
        assert out["last_rc"] == 1
        assert out["certified"]["armed"] == 4  # certified count comes from the last OK run only


def test_missing_and_corrupt_are_unknown_not_zero():
    with tempfile.TemporaryDirectory() as d:
        out = rec.read_record(root=d, now=NOW)
        assert out["readable"] is True and out["last_run_at"] is None and out["certified"] is None
        p = rec.record_path(d)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"ts": "x"\nnot json\n')
        bad = rec.read_record(root=d, now=NOW)
        assert bad["certified"] is None and bad["skipped_lines"] == 2


def test_unreadable_path_reports_readable_false():
    with tempfile.TemporaryDirectory() as d:
        p = rec.record_path(d)
        p.mkdir(parents=True)  # a directory where the file should be
        out = rec.read_record(root=d, now=NOW)
        assert out["readable"] is False and out["certified"] is None


def test_record_is_append_only_and_bounded_read():
    with tempfile.TemporaryDirectory() as d:
        for i in range(30):
            rec.append_run(armed=i, fired=0, composites=0, rc=0, root=d, now=NOW - timedelta(minutes=300 - i))
        assert len(rec.record_path(d).read_text().splitlines()) == 30
        out = rec.read_record(root=d, now=NOW, tail=10)
        assert out["certified"]["armed"] == 29


def test_append_never_raises():
    assert rec.append_run(armed=1, fired=0, composites=0, rc=0, root="/proc/nonexistent/x", now=NOW) is False


def test_sectors_as_of_is_newest_universe_row():
    calls = []

    def q(sql, *a, **k):
        calls.append(sql)
        if "max(" in sql:
            return [{"as_of": NOW - timedelta(hours=2), "n": 8781}]
        return [{"sector": "Tech", "n": 3, "sample": ["A"]}]

    out = ws.sectors_payload(q)
    assert out["as_of"] == (NOW - timedelta(hours=2)).isoformat()
    assert out["as_of_basis"] == "incubator_universe.updated_at"
    assert out["sectors"][0]["count"] == 3


def test_sectors_empty_universe_is_unknown_and_named_empty():
    # _db_required returns None for "ran, no rows" and raises on a failed read (503): None is EMPTY, not failed.
    out = ws.sectors_payload(lambda *a, **k: None)
    assert out["sectors"] == [] and out["as_of"] is None and out["status"] == "empty"


def test_watchpool_as_of_present_and_unavailable_paths():
    def q(sql, params=None, **k):
        if "GROUP BY 1,2" in sql:
            return [{"current_status": "ACTIVE", "origin_system": "screener", "n": 2}]
        if "max(entered_at)" in sql:
            return [{"as_of": NOW - timedelta(hours=1)}]
        return [{"id": 1, "symbol": "A", "entered_at": NOW}]

    out = spr.read_watchpool({}, db_query=q)
    assert out["as_of"] == (NOW - timedelta(hours=1)).isoformat()
    assert out["as_of_basis"] == "strategy_watchpool.entered_at"
    down = spr.read_watchpool({}, db_query=lambda *a, **k: None)
    assert down.get("as_of") is None and down["status"] == "unavailable"


def test_alerts_payload_liveness_separate_from_rows():
    with tempfile.TemporaryDirectory() as d:
        rec.append_run(armed=1, fired=0, composites=0, rc=0, root=d, now=NOW - timedelta(minutes=3))
        rows = [{"id": 1, "active": True, "created_at": NOW - timedelta(days=9), "last_fired_at": None}]
        out = ws.alerts_payload(rows, root=d, now=NOW)
        assert out["liveness_at"] == (NOW - timedelta(minutes=3)).isoformat()
        assert out["liveness_basis"] == "evaluator_last_run"
        assert out["as_of"] == (NOW - timedelta(days=9)).isoformat()  # WV-02 contract: store data time
        assert out["active_count"] == 1
        assert out["evaluator"]["certified"]["armed"] == 1
        assert out["rows_newest_at"] == (NOW - timedelta(days=9)).isoformat()


def test_alerts_payload_no_record_has_null_as_of():
    with tempfile.TemporaryDirectory() as d:
        out = ws.alerts_payload([], root=d, now=NOW)
        assert out["as_of"] is None and out["liveness_at"] is None and out["evaluator"]["certified"] is None
