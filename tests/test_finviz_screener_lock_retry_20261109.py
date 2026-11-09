"""LQ-20261107-1577 — a transient watchlist_items lock must not lose a screener, and a run that produced
must not be graded empty_output.

Scenario, synthetic but the shape of a real weekday-morning dispatch burst:

  a sibling writer holds an uncommitted watchlist_items row while this lane inserts its own, so one
  screener's INSERT is cancelled by the session's lock_timeout (SQLSTATE 55P03) while the screeners around
  it commit. The run therefore wrote most of its screeners and failed a couple of writes. The receipt
  recorded status=failed for those write failures, and the executor graded it ``empty_violation`` /
  ``why=receipt_status_failed`` and dead-lettered the slot as terminal and non-retryable: a run that
  produced a large set of tickers was reported as an empty one.

The contract these tests pin:

  1. a lock timeout on one screener's write is retried with a lock wait sized for a batch writer, and the
     screener's rows still land — one screener never takes the whole run with it;
  2. a lock that outlives the retries is counted ONCE for that screener (not once per attempt) and the
     other screeners are unaffected;
  3. the receipt's status follows the contract's produced count (min_produced=1), with the non-fatal skips
     recorded in ``skipped_reasons`` — a run that produced nothing still fails.

Hermetic: fake connection that models commit/rollback/SAVEPOINT semantics and raises SQLSTATE 55P03 on
request; fake Finviz fetcher. No DB, no network, no credential read.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import db_adapter  # noqa: E402
import finviz_screener_runner as runner  # noqa: E402
from lib import lane_last_receipt  # noqa: E402

SCREENERS = [
    {"screener_id": "aaa_setups", "display_name": "A", "strategy_type": "core", "finviz_url": "u1"},
    {"screener_id": "bbb_value", "display_name": "B", "strategy_type": "value", "finviz_url": "u2"},
    {"screener_id": "ccc_income", "display_name": "C", "strategy_type": "income", "finviz_url": "u3"},
]
TICKERS = {"u1": ["AAA1", "AAA2"], "u2": ["BBB1"], "u3": ["CCC1", "CCC2"]}


class _LockTimeout(Exception):
    """psycopg2.errors.LockNotAvailable: the session lock_timeout fired."""

    pgcode = "55P03"


class _Cur:
    """Models the transaction structure the runner uses, plus a scriptable 55P03."""

    def __init__(self, conn):
        self.conn = conn
        self._rows = []

    def execute(self, sql, params=None):
        s = " ".join(str(sql).split())
        u = s.upper()
        if u.startswith("SET LOCAL LOCK_TIMEOUT"):
            self.conn.lock_timeouts.append(s)
            return
        if u.startswith("SAVEPOINT SP_SCR_"):
            name = s.split()[1]
            sid = name[len("sp_scr_"):]
            self.conn.current_screener = sid
            self.conn.attempts[sid] = self.conn.attempts.get(sid, 0) + 1  # nosemgrep: tq-py-missing-as-zero -- an attempt counter starts at 0; it counts executions, never a measurement
            self.conn.saves.append((name, len(self.conn.pending)))
            return
        if u.startswith("SAVEPOINT "):
            self.conn.saves.append((s.split()[1], len(self.conn.pending)))
            return
        if u.startswith("RELEASE SAVEPOINT "):
            name = s.split()[-1]
            for i in range(len(self.conn.saves) - 1, -1, -1):
                if self.conn.saves[i][0] == name:
                    del self.conn.saves[i]
                    break
            return
        if u.startswith("ROLLBACK TO SAVEPOINT "):
            name = s.split()[-1]
            for i in range(len(self.conn.saves) - 1, -1, -1):
                if self.conn.saves[i][0] == name:
                    del self.conn.pending[self.conn.saves[i][1]:]
                    del self.conn.saves[i + 1:]
                    break
            return
        if u.startswith("SELECT * FROM FINVIZ_SCREENERS"):
            self._rows = [dict(r) for r in self.conn.screeners]
            return
        if u.startswith("SELECT SYMBOL FROM TICKER_STRATEGY_CLASSIFICATIONS"):
            self._rows = []
            return
        sid, attempt = self.conn.current_screener, self.conn.attempts.get(self.conn.current_screener, 1)
        locked = (
            sid in self.conn.fail_always
            or attempt in self.conn.fail_attempts.get(sid, ())
            or self.conn.fail_every_statement_on in (sid,)
        )
        is_watchlist_insert = u.startswith("INSERT INTO WATCHLIST_ITEMS")
        if is_watchlist_insert and locked:
            self.conn.lock_hits.append((sid, attempt, params))
            raise _LockTimeout("canceling statement due to lock timeout")
        if self.conn.fail_not_lock_on == sid and is_watchlist_insert:
            raise RuntimeError('column "bogus" does not exist')
        self.conn.pending.append((s, params))     # every other statement is a write

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class _Conn:
    def __init__(self, screeners, *, fail_attempts=None, fail_always=(), fail_not_lock_on=None):
        self.screeners = screeners
        self.pending, self.committed, self.saves = [], [], []
        self.commits, self.rollbacks = 0, 0
        self.current_screener = None
        self.attempts = {}
        self.fail_attempts = {k: set(v) for k, v in (fail_attempts or {}).items()}
        self.fail_always = set(fail_always)
        self.fail_not_lock_on = fail_not_lock_on
        self.fail_every_statement_on = None
        self.lock_hits = []
        self.lock_timeouts = []

    def cursor(self, *a, **k):
        return _Cur(self)

    def commit(self):
        self.commits += 1
        self.committed.extend(self.pending)
        self.pending.clear()
        self.saves.clear()

    def rollback(self):
        self.rollbacks += 1
        self.pending.clear()
        self.saves.clear()

    def get_transaction_status(self):
        return 2                                  # psycopg2 TRANSACTION_STATUS_READY


def _stamps(conn):
    return [p[1] for s, p in conn.committed if s.startswith("UPDATE finviz_screeners SET last_run")]


def _classified(conn):
    return [p[0] for s, p in conn.committed if s.startswith("INSERT INTO ticker_strategy_classifications")]


@pytest.fixture
def env(monkeypatch):
    def use(conn, tickers=None):
        monkeypatch.setattr(runner, "_get_conn", lambda: conn)

        def _ensure():
            conn.rollback()
            return conn
        monkeypatch.setattr(db_adapter, "ensure_conn", _ensure)
        table = TICKERS if tickers is None else tickers
        monkeypatch.setattr(runner, "_fetch_screener_tickers",
                            lambda url, cookie, token="", *, deadline_monotonic=None: list(table.get(url, [])))
        monkeypatch.setattr(runner, "_update_screener_membership",
                            lambda cur, sid, present, run_id: _membership(cur, sid, present))
        monkeypatch.setattr(runner, "_get_finviz_cookie", lambda: "")
        monkeypatch.setattr(runner, "_get_finviz_token", lambda: "")
        monkeypatch.setattr(runner, "_fence_before_first_write", lambda: None)
        monkeypatch.setattr(runner.time, "sleep", lambda _s: None)
        return conn
    return use


def _membership(cur, sid, present):
    cur.execute("INSERT INTO screener_symbol_membership (symbol, screener_id) VALUES (%s, %s)",
                (sorted(present)[0] if present else None, sid))
    return len(present)


def test_a_lock_timeout_is_retried_and_the_screener_is_kept(env):
    """The first attempt of screener A hits 55P03 on its watchlist INSERT. The retry must land that
    screener: all three stamps present, 5 tickers committed, 0 write failures."""
    conn = env(_Conn(SCREENERS, fail_attempts={"aaa_setups": [1]}))
    out = runner.run_screener()

    assert _stamps(conn) == ["aaa_setups", "bbb_value", "ccc_income"], _stamps(conn)
    assert out["db_write_failures"] == 0, out
    assert out["total_new_tickers"] == 5
    assert len(_classified(conn)) == 5
    assert [h[0] for h in conn.lock_hits] == ["aaa_setups"]


def test_the_write_waits_longer_than_the_interactive_guard_and_reissues_it_per_attempt(env):
    """The lane's write carries its own lock_timeout (batch) rather than db_adapter's 3 s guard, re-issued
    before each attempt so a full rollback cannot leave the retry on the short guard."""
    conn = env(_Conn(SCREENERS, fail_attempts={"aaa_setups": [1]}))
    runner.run_screener()

    want = f"SET LOCAL lock_timeout = '{runner._write_lock_timeout()}'"
    assert runner._write_lock_timeout() == "10s"
    assert conn.lock_timeouts.count(want) == 4, conn.lock_timeouts   # 3 screeners + 1 retry


def test_an_unvalidated_override_falls_back_to_the_batch_wait(monkeypatch):
    monkeypatch.setenv("FINVIZ_SCREENER_LOCK_TIMEOUT", "10s; DROP TABLE watchlist_items")
    assert runner._write_lock_timeout() == "10s"


def test_a_lock_that_outlives_the_retries_fails_that_screener_once(env):
    """Screener B is locked on every attempt. It is ONE write failure (not one per attempt), it is not
    produced, and A and C are unaffected."""
    conn = env(_Conn(SCREENERS, fail_always={"bbb_value"}))
    out = runner.run_screener()

    assert out["db_write_failures"] == 1, out
    assert conn.attempts["bbb_value"] == runner._lock_retry_attempts() == 3
    by_id = {r["screener_id"]: r for r in out["results"]}
    assert by_id["bbb_value"]["db_ok"] is False
    assert by_id["aaa_setups"]["db_ok"] is True and by_id["ccc_income"]["db_ok"] is True
    assert _stamps(conn) == ["aaa_setups", "ccc_income"]
    assert out["total_new_tickers"] == 4
    assert "BBB1" not in _classified(conn)


def test_a_non_lock_error_is_not_retried(env):
    """Only 55P03 is retried: a missing column is deterministic and must not be attempted three times."""
    conn = env(_Conn(SCREENERS, fail_not_lock_on="bbb_value"))
    out = runner.run_screener()

    assert conn.attempts["bbb_value"] == 1, conn.attempts
    assert out["db_write_failures"] == 1, out


def _tracked(monkeypatch, result, *, deadline=None):
    receipts, pipeline = [], types.SimpleNamespace(done=[], failed=[])
    monkeypatch.setattr(lane_last_receipt, "write_lane_receipt", lambda *a, **kw: receipts.append(kw))
    mod = types.ModuleType("pipeline_registry")
    mod.run_complete = lambda run_id, **kw: pipeline.done.append((run_id, kw))
    mod.run_fail = lambda run_id, why: pipeline.failed.append((run_id, why))
    monkeypatch.setitem(sys.modules, "pipeline_registry", mod)
    monkeypatch.setattr(runner, "run_screener", lambda **kw: result)
    args = types.SimpleNamespace(screener=None, json=True, deadline_monotonic=deadline)
    rc = runner._run_tracked(args, "2026-01-05T15:00:00+00:00", "d:finviz-screener-runner:test:t0001")
    return rc, receipts, pipeline


def _partial_result():
    ok = {"total_found": 5, "new_tickers": 2, "membership_updated": 1, "db_ok": True}
    bad = {"total_found": 5, "new_tickers": 2, "db_ok": False, "db_error": "lock timeout"}
    empty = {"total_found": 0, "new_tickers": 0}
    results = [{**ok, "screener_id": f"s{i}"} for i in range(3)]
    results += [{**bad, "screener_id": "b1"}, {**empty, "screener_id": "e1"}]
    return {"mode": "live", "screeners_run": 5, "total_new_tickers": 6,
            "membership_failures": 0, "db_write_failures": 1, "results": results}


def test_partial_success_reports_ok_with_the_skips_recorded(monkeypatch):
    """3 of 5 produced, 1 write failure: the contract's min_produced is satisfied, so the receipt is ok
    and the failure stays visible in skipped_reasons — not a failed status the executor reads as empty."""
    rc, receipts, pipeline = _tracked(monkeypatch, _partial_result())

    assert rc == 0
    assert len(receipts) == 1, receipts
    r = receipts[0]
    assert r["ok"] is True, r
    assert r["output"]["produced_count"] == 3
    assert r["output"]["attempted_count"] == 5
    assert r["output"]["skipped_reasons"] == {"no_tickers": 1, "membership_failed": 0, "db_write_failed": 1}
    assert r["summary"]["db_write_failures"] == 1, r["summary"]
    assert pipeline.done and not pipeline.failed, pipeline


def test_a_run_that_produced_nothing_still_fails(monkeypatch):
    """Every screener's write failed: produced 0, so the receipt is failed and the run is reported as
    failed. Honesty cuts both ways."""
    result = _partial_result()
    for r in result["results"]:
        r["db_ok"] = False
        r.pop("membership_updated", None)
    result["db_write_failures"] = 5
    rc, receipts, pipeline = _tracked(monkeypatch, result)

    assert rc == 0                                 # no caller deadline: the dispatcher owns the exit code
    assert receipts[0]["ok"] is False, receipts[0]  # the contract signal the executor grades
    assert receipts[0]["output"]["produced_count"] == 0
    assert receipts[0]["output"]["skipped_reasons"]["db_write_failed"] == 5, receipts[0]["output"]


def test_retry_is_skipped_when_the_caller_budget_cannot_fit_it(env, monkeypatch):
    """A deadline-bound caller gets no retry it cannot finish: the screener is reported failed, not
    deferred into a deadline exception."""
    import time as _time
    conn = env(_Conn(SCREENERS, fail_always={"bbb_value"}))
    result = runner.run_screener(deadline_monotonic=_time.monotonic() + 0.5)

    assert conn.attempts["bbb_value"] == 1, conn.attempts
    assert result["db_write_failures"] == 1, result
