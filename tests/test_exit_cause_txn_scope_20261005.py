"""Shutdown record carries the signal and exit code, and the ATM protection
pass releases its read transaction before apply() (quote + broker HTTP).
"""

from __future__ import annotations

import signal
from io import StringIO

import pytest

import apply_paper_protection_adjustment as ap_mod
import lib.portfolio_server_shutdown as shutdown
import protection_atm_pass as prot


_ROW = (1, "AAA", "MOVE_STOP_TO_BREAKEVEN", 10.0, 2, "alpaca_paper", "open")
_COLS = (
    ("id",),
    ("symbol",),
    ("action",),
    ("proposed_stop",),
    ("trade_id",),
    ("acct",),
    ("trade_status",),
)


class _Cursor:
    def __init__(self, rows):
        self._rows = rows
        self.description = _COLS

    def execute(self, _sql, _params=None):
        return None

    def fetchall(self):
        return list(self._rows)


class _Conn:
    def __init__(self, rows, events, *, closed=0):
        self._rows = rows
        self.events = events
        self.closed = closed

    def cursor(self):
        return _Cursor(self._rows)

    def rollback(self):
        self.events.append("rollback")


class _DeadCursor:
    def execute(self, _sql, _params=None):
        raise RuntimeError("connection already closed")


class _DeadConn:
    closed = 0

    def cursor(self):
        return _DeadCursor()

    def rollback(self):
        raise AssertionError("rollback on the dead handle")


def test_shutdown_record_includes_signal_and_exit_code():
    line = shutdown.shutdown_record(signum=signal.SIGTERM, exit_code=128 + signal.SIGTERM)
    assert "signal=SIGTERM(15)" in line
    assert "exit_code=143" in line

    buf = StringIO()
    seen = []
    logged = shutdown.log_shutdown(
        signal.SIGTERM,
        143,
        sink=buf,
        syslog_fn=seen.append,
    )
    assert "signal=SIGTERM(15)" in logged
    assert "exit_code=143" in logged
    assert logged in buf.getvalue()
    assert seen == [logged]


def test_sigterm_handler_records_signal_and_exit_code():
    prev_term = signal.getsignal(signal.SIGTERM)
    prev_int = signal.getsignal(signal.SIGINT)
    seen = {}

    def _capture(signum, exit_code):
        seen["line"] = shutdown.shutdown_record(signum=signum, exit_code=exit_code)

    try:
        handler = shutdown.install_shutdown_logging(log_fn=_capture)
        with pytest.raises(SystemExit) as raised:
            handler(signal.SIGTERM, None)
    finally:
        signal.signal(signal.SIGTERM, prev_term)
        signal.signal(signal.SIGINT, prev_int)

    assert raised.value.code == 143
    assert "signal=SIGTERM(15)" in seen["line"]
    assert "exit_code=143" in seen["line"]


def _arm_apply(monkeypatch, events):
    monkeypatch.setenv("ALPACA_MODE", "paper")
    monkeypatch.setenv("PROTECTION_ATM_AUTO_APPLY_PAPER", "1")
    monkeypatch.setattr(prot, "_is_paper_account", lambda _acct: True)

    def _apply(*_args, **_kwargs):
        events.append("apply")
        return {"ok": True, "applied": True}

    monkeypatch.setattr(ap_mod, "apply", _apply)


def test_protection_pass_releases_transaction_before_apply(monkeypatch):
    events = []
    _arm_apply(monkeypatch, events)
    conn = _Conn([_ROW], events)
    out = prot.run_protection_pass(conn, mode="active", dry_run=False)
    assert events == ["rollback", "apply"]
    assert out["considered"] == 1
    assert out["auto_applied"] == 1


def test_protection_pass_reconnects_closed_handle_then_releases(monkeypatch):
    events = []
    _arm_apply(monkeypatch, events)
    live = _Conn([_ROW], events)

    def _ensure():
        events.append("ensure")
        return live

    monkeypatch.setattr("db_adapter.ensure_conn", _ensure)
    out = prot.run_protection_pass(_DeadConn(), mode="active", dry_run=False)
    assert events == ["ensure", "rollback", "apply"]
    assert out["considered"] == 1
    assert out["auto_applied"] == 1


def test_protection_pass_does_not_swallow_other_db_errors(monkeypatch):
    events = []
    _arm_apply(monkeypatch, events)

    class _Boom:
        closed = 0

        def cursor(self):
            raise RuntimeError("syntax error at or near SELECT")

    with pytest.raises(RuntimeError, match="syntax error"):
        prot.run_protection_pass(_Boom(), mode="active", dry_run=False)
    assert "apply" not in events
    assert "rollback" not in events
