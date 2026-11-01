"""ANCHOR: JOBS_HEALTH_LOG_DIAGNOSTIC_20261031 — a host-cron failure shows the job log's last error line.

2026-10-30: the unified stop supervisor failed every run (``AssertionError: ALPACA_MODE must be paper``, the .env
was 0 bytes after the disk filled). safe_flock recorded only ``exit_code: 1``; the cron line sent stderr into
logs/unified_stop_supervisor.log, so the Jobs page said "stderr diagnostic was not retained". Hermetic: tmp files only.
"""
from datetime import datetime, timedelta, timezone
import os

from scripts.lib import jobs_health as J
from scripts.lib import n8n_dlq_disposition as DD

NOW = datetime(2026, 10, 30, 20, 58, tzinfo=timezone.utc)
FAIL_AT = datetime(2026, 10, 30, 20, 57, 2, tzinfo=timezone.utc)
TRACE = (
    "Traceback (most recent call last):\n"
    '  File "scripts/unified_stop_supervisor.py", line 33, in _safety_checks\n'
    '    assert os.environ.get("ALPACA_MODE") == "paper", "ALPACA_MODE must be paper"\n'
    "AssertionError: ALPACA_MODE must be paper\n"
)


def _lane():
    return {"lane_id": "unified-stop-supervisor", "state": "ACTIVE", "expected_cadence_hours": 0.05,
            "scheduler": {"kind": "cron", "expression": "*/3 9-16 * * 1-5"},
            "output_signal": {"kind": "file_mtime", "path": "logs/unified_stop_supervisor.log"},
            "watchdog_wrapper_component": "unified_stop_supervisor"}


def _event(**extra):
    return {"ts": FAIL_AT.isoformat(), "component": "unified_stop_supervisor", "event_type": "completed",
            "message": "safe_flock command completed", "exit_code": 1, "mode": "business", **extra}


def _row(log_errors=None, event=None):
    snap = {"events": [event or _event()], "successes": {}}
    if log_errors is not None:
        snap["log_errors"] = log_errors
    row, = J.build({"lanes": [_lane()]}, snap, [], {}, now=NOW, trading_day=lambda d: d.weekday() < 5)["rows"]
    return row


def _log(tmp_path, text, at=FAIL_AT):
    path = tmp_path / "unified_stop_supervisor.log"
    path.write_text(text)
    os.utime(path, (at.timestamp(), at.timestamp()))
    return path


def test_generic_text_matches_the_shared_cause_rule():
    assert DD.cause({"reason": "exit_1"}) == J.NO_DIAGNOSTIC


def test_last_error_line_is_read_from_the_log_tail(tmp_path):
    got = J.last_log_error(_log(tmp_path, "2026-10-30 16:54:02 ok\n" + TRACE))
    assert got["line"] == "AssertionError: ALPACA_MODE must be paper"
    assert got["at"] == FAIL_AT.replace(microsecond=0) or abs(got["at"] - FAIL_AT) < timedelta(seconds=1)


def test_log_without_an_error_line_gives_nothing(tmp_path):
    assert J.last_log_error(_log(tmp_path, "Reconciled: 0/0 | Critical: 0 | Protected: YES\n")) is None
    assert J.last_log_error(tmp_path / "absent.log") is None


def test_wrapper_failure_shows_the_log_error_not_the_gap(tmp_path):
    err = J.last_log_error(_log(tmp_path, TRACE))
    row = _row({"unified-stop-supervisor": err})
    assert row["result"] == "failed"
    assert "AssertionError: ALPACA_MODE must be paper" in row["cause"]
    assert "logs/unified_stop_supervisor.log" in row["cause"]


def test_stale_log_error_is_not_attributed_to_a_later_failure(tmp_path):
    err = J.last_log_error(_log(tmp_path, TRACE, at=FAIL_AT - timedelta(hours=3)))
    assert _row({"unified-stop-supervisor": err})["cause"] == J.NO_DIAGNOSTIC


def test_wrapper_stderr_or_reason_still_wins(tmp_path):
    err = J.last_log_error(_log(tmp_path, TRACE))
    row = _row({"unified-stop-supervisor": err}, _event(stderr_tail="safe_flock: refusing symlink_component"))
    assert "symlink_component" in row["cause"] and "ALPACA_MODE" not in row["cause"]


def test_no_log_errors_key_keeps_the_explicit_gap():
    assert _row()["cause"] == J.NO_DIAGNOSTIC


def test_load_attaches_log_errors_from_the_declared_log(tmp_path, monkeypatch):
    root = tmp_path / "state"
    (root / "logs").mkdir(parents=True)
    _log(root / "logs", TRACE)
    seen = {}
    real_build = J.build

    def spy(registry, snapshot, runs, watchdog, **kw):
        seen.update(snapshot.get("log_errors") or {})
        return real_build(registry, snapshot, runs, watchdog, **kw)

    import scripts.cron_outage_watchdog as COW
    monkeypatch.setattr(J, "build", spy)
    monkeypatch.setattr(J, "_json", lambda p, limit=0: {"lanes": [_lane()]} if str(p).endswith("lane_registry.json") else {})
    monkeypatch.setattr(COW, "collect", lambda registry, root: {"events": [_event()], "successes": {}})
    monkeypatch.setattr(COW, "bind_components", lambda registry, cfg: registry)
    import scripts.lib.scheduler_operations as SO
    monkeypatch.setattr(SO, "read_run_ledger", lambda p: ([], True, None))
    import scripts.lib.jobs_conflict_errors as JCE
    monkeypatch.setattr(JCE, "get_data_errors", lambda root: [])
    report = J._load(root, tmp_path / "lane_registry.json", NOW)
    assert seen["unified-stop-supervisor"]["line"] == "AssertionError: ALPACA_MODE must be paper"
    row, = report["rows"]
    assert "ALPACA_MODE must be paper" in row["cause"]
