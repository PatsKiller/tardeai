"""Kill-switch enable/disable write path — hermetic (fake connection/cursor, no DB, no broker).

ANCHOR: KILL_SWITCH_DISABLE_AUDIT_20261022. Operator hit it 2026-10-22 21:53 ET:
``kill_switches.py --disable global --confirm "DISABLE GLOBAL KILL SWITCH 2026-10-22"`` raised
TypeError because ``disable()`` called ``_audit(..., confirm_phrase=confirm)`` while ``_audit``'s
parameter was named ``confirm``. The bug existed since the file was created (2026-06-26): the only
disable test used a WRONG phrase, which returns before ``_audit`` is reached, and that test file
(tests/test_kill_switches.py) uses print-only checks and is not in any CI gate.

These tests drive the success path, the refusal paths, the date binding, the enable path, and
the rollback-on-failure guarantee (state change and audit row commit together or not at all).
"""
from __future__ import annotations

import ast
import datetime as dt
import inspect
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from brokers import kill_switches as ks  # noqa: E402

KS_SRC = ROOT / "scripts" / "brokers" / "kill_switches.py"


class FakeCursor:
    def __init__(self, fail_on: str | None = None):
        self.calls: list[tuple[str, tuple | None]] = []
        self.fail_on = fail_on
        self.rowcount = 1

    def execute(self, sql, params=None):
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError(f"injected failure on {self.fail_on}")
        self.calls.append((" ".join(sql.split()), params))

    def fetchall(self):
        return []


class FakeConn:
    def __init__(self, fail_on: str | None = None):
        self.cur = FakeCursor(fail_on)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _forbidden_db(*_a, **_k):
    raise AssertionError("hermetic test reached the real db_adapter")


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    """No real DB and no real audit ledger: both are replaced by in-memory fakes."""
    events: list[tuple[tuple, dict]] = []
    ledger = types.ModuleType("audit_ledger")
    ledger.record_event = lambda *a, **k: events.append((a, k))
    monkeypatch.setitem(sys.modules, "audit_ledger", ledger)
    fake_db = types.ModuleType("db_adapter")
    fake_db._get_conn = _forbidden_db
    monkeypatch.setitem(sys.modules, "db_adapter", fake_db)
    return events


def _fixed_today(day: dt.date):
    class _D(dt.date):
        @classmethod
        def today(cls):
            return day
    return types.SimpleNamespace(date=_D, datetime=dt.datetime, timezone=dt.timezone)


def _writes(conn: FakeConn, table: str) -> list[tuple[str, tuple | None]]:
    return [c for c in conn.cur.calls if table in c[0] and not c[0].startswith("CREATE")]


DAY = dt.date(2026, 10, 22)
PHRASE = "DISABLE GLOBAL KILL SWITCH 2026-10-22"


# ── structural: the call sites match the signature (what would have caught the bug) ──────────

def test_every_audit_call_uses_parameters_audit_accepts():
    params = set(inspect.signature(ks._audit).parameters)
    assert "confirm_phrase" in params
    tree = ast.parse(KS_SRC.read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_audit"]
    assert len(calls) >= 2, "expected enable() and disable() to audit"
    for c in calls:
        for kw in c.keywords:
            assert kw.arg in params, f"_audit called with unknown keyword {kw.arg!r} (line {c.lineno})"


# ── disable ───────────────────────────────────────────────────────────────────────────────────

def test_disable_with_correct_phrase_succeeds_and_audits(_hermetic):
    conn = FakeConn()
    with mock.patch.object(ks, "dt", _fixed_today(DAY)), mock.patch.object(ks, "_conn", return_value=conn):
        r = ks.disable("global", confirm=PHRASE, actor="operator")
    assert r["ok"] is True, r
    assert r["rows_updated"] == 1
    upd = _writes(conn, "UPDATE kill_switch_state")
    assert len(upd) == 1 and upd[0][1] == ("global", "")
    aud = _writes(conn, "INSERT INTO kill_switch_audit")
    assert len(aud) == 1
    assert aud[0][1] == ("disable", "global", "", "operator_disabled", PHRASE, "operator")
    assert conn.commits == 1 and conn.rollbacks == 0
    assert _hermetic and _hermetic[0][1]["decision"] == "disabled"


def test_disable_wrong_phrase_refused_without_touching_db():
    conn_factory = mock.Mock(side_effect=AssertionError("must not open a connection"))
    with mock.patch.object(ks, "dt", _fixed_today(DAY)), mock.patch.object(ks, "_conn", conn_factory):
        for bad in ("wrong", "", PHRASE.lower(), PHRASE + " ", "DISABLE LIVE_SUBMIT KILL SWITCH 2026-10-22"):
            r = ks.disable("global", confirm=bad)
            assert r["ok"] is False and PHRASE in r["error"], (bad, r)
    conn_factory.assert_not_called()


def test_disable_phrase_is_date_bound():
    # Yesterday's (or tomorrow's) phrase is refused; today's is accepted.
    assert ks.expected_disable_phrase("global", DAY) == PHRASE
    assert ks.expected_disable_phrase("live_submit", DAY) == "DISABLE LIVE_SUBMIT KILL SWITCH 2026-10-22"
    for stale in ("DISABLE GLOBAL KILL SWITCH 2026-10-21", "DISABLE GLOBAL KILL SWITCH 2026-10-23"):
        with mock.patch.object(ks, "dt", _fixed_today(DAY)), \
             mock.patch.object(ks, "_conn", side_effect=AssertionError("no db")):
            assert ks.disable("global", confirm=stale)["ok"] is False
    conn = FakeConn()
    with mock.patch.object(ks, "dt", _fixed_today(DAY + dt.timedelta(days=1))), \
         mock.patch.object(ks, "_conn", return_value=conn):
        assert ks.disable("global", confirm="DISABLE GLOBAL KILL SWITCH 2026-10-23")["ok"] is True


def test_disable_scoped_level_audits_scope_and_phrase():
    conn = FakeConn()
    phrase = "DISABLE SYMBOL KILL SWITCH 2026-10-22"
    with mock.patch.object(ks, "dt", _fixed_today(DAY)), mock.patch.object(ks, "_conn", return_value=conn):
        r = ks.disable("symbol", scope="SPCX", confirm=phrase)
    assert r["ok"] is True
    assert _writes(conn, "UPDATE kill_switch_state")[0][1] == ("symbol", "SPCX")
    assert _writes(conn, "INSERT INTO kill_switch_audit")[0][1][4] == phrase


def test_disable_unknown_level_and_db_unavailable():
    assert ks.disable("nope", confirm="x")["ok"] is False
    with mock.patch.object(ks, "dt", _fixed_today(DAY)), mock.patch.object(ks, "_conn", return_value=None):
        r = ks.disable("global", confirm=PHRASE)
    assert r == {"ok": False, "error": "db_unavailable"}


# ── enable (unchanged behaviour) ──────────────────────────────────────────────────────────────

def test_enable_path_unchanged(_hermetic):
    conn = FakeConn()
    with mock.patch.object(ks, "_conn", return_value=conn):
        r = ks.enable("global", reason="drill", actor="operator")
    assert r["ok"] is True
    ins = _writes(conn, "INSERT INTO kill_switch_state")
    assert len(ins) == 1 and ins[0][1][:3] == ("global", "", "drill")
    aud = _writes(conn, "INSERT INTO kill_switch_audit")
    assert aud[0][1] == ("enable", "global", "", "drill", "", "operator")
    assert conn.commits == 1 and conn.rollbacks == 0
    assert _hermetic[0][1]["decision"] == "enabled"


# ── failure rolls back: never a half-written change ───────────────────────────────────────────

@pytest.mark.parametrize("fail_on", ["UPDATE kill_switch_state", "INSERT INTO kill_switch_audit"])
def test_disable_failure_rolls_back(fail_on, _hermetic):
    conn = FakeConn(fail_on=fail_on)
    with mock.patch.object(ks, "dt", _fixed_today(DAY)), mock.patch.object(ks, "_conn", return_value=conn):
        r = ks.disable("global", confirm=PHRASE)
    assert r["ok"] is False and "rolled_back" in r["error"]
    assert conn.commits == 0 and conn.rollbacks == 1
    assert _hermetic == []  # no ledger event for a change that did not happen


def test_original_typeerror_now_rolls_back_instead_of_leaving_txn_open():
    """Reproduce the 2026-10-22 signature mismatch: the UPDATE runs, then _audit raises TypeError.
    The pending UPDATE must be rolled back, not left open on the thread-local connection."""
    def _old_audit(cur, action, level, scope, reason, confirm="", actor="operator"):
        cur.execute("INSERT INTO kill_switch_audit ...", ())

    conn = FakeConn()
    with mock.patch.object(ks, "dt", _fixed_today(DAY)), mock.patch.object(ks, "_conn", return_value=conn), \
         mock.patch.object(ks, "_audit", _old_audit):
        r = ks.disable("global", confirm=PHRASE)
    assert r["ok"] is False and "TypeError" in r["error"]
    assert len(_writes(conn, "UPDATE kill_switch_state")) == 1
    assert conn.commits == 0 and conn.rollbacks == 1


@pytest.mark.parametrize("fail_on", ["INSERT INTO kill_switch_state", "INSERT INTO kill_switch_audit"])
def test_enable_failure_rolls_back(fail_on):
    conn = FakeConn(fail_on=fail_on)
    with mock.patch.object(ks, "_conn", return_value=conn):
        r = ks.enable("global", reason="drill")
    assert r["ok"] is False and "rolled_back" in r["error"]
    assert conn.commits == 0 and conn.rollbacks == 1


# ── CLI exit code: rc 0 only when the change applied (ops_controls reads rc 0 as APPLIED) ──────

def test_cli_exit_codes(capsys):
    with mock.patch.object(ks, "dt", _fixed_today(DAY)), mock.patch.object(ks, "_conn", return_value=None), \
         mock.patch.object(sys, "argv", ["kill_switches.py", "--disable", "global", "--confirm", "wrong"]):
        assert ks.main() == 1
    with mock.patch.object(ks, "_conn", return_value=None), \
         mock.patch.object(sys, "argv", ["kill_switches.py", "--enable", "global"]):
        assert ks.main() == 1  # db_unavailable is a failure, not APPLIED
    conn = FakeConn()
    with mock.patch.object(ks, "dt", _fixed_today(DAY)), mock.patch.object(ks, "_conn", return_value=conn), \
         mock.patch.object(sys, "argv", ["kill_switches.py", "--disable", "global", "--confirm", PHRASE]):
        assert ks.main() == 0
    capsys.readouterr()
