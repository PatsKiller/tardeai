"""LQ-20261107-2982 (SEV-1 silent failure): a lock timeout inside the sweep's write transaction aborted the batch,
every later statement raised InFailedSqlTransaction, each was swallowed as "non-fatal", the commit was a rollback, and the
lane receipt said RUN_DONE with the rolled-back rows still counted. Synthetic fixtures only (no DB, no real symbols)."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import psycopg2.errors as pge
import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import watchlist_enrichment_sweep as W  # noqa: E402


class _Cur:
    """Postgres abort semantics: after an error every statement fails until ROLLBACK TO SAVEPOINT / rollback."""

    def __init__(self, conn):
        self.c, self.rowcount = conn, 0

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        c = self.c
        if s.startswith(("SAVEPOINT", "ROLLBACK TO SAVEPOINT", "RELEASE SAVEPOINT")):
            self.rowcount = -1          # psycopg2/PG: a utility statement leaves rowcount -1 (truthy!)
        if s.startswith("SAVEPOINT"):
            if c.aborted:
                raise pge.InFailedSqlTransaction("current transaction is aborted")
            c.sp_pending = list(c.pending)
            return
        if s.startswith("ROLLBACK TO SAVEPOINT"):
            c.pending, c.aborted = list(c.sp_pending), False
            return
        if s.startswith("RELEASE SAVEPOINT"):
            return
        if c.aborted:
            raise pge.InFailedSqlTransaction("current transaction is aborted, commands ignored until end of transaction block")
        if s.startswith("UPDATE watchlist_items"):
            sym = params[-1]
            if sym in c.lock_timeout_on:
                c.aborted = True
                raise pge.LockNotAvailable("canceling statement due to lock timeout")
            if sym in c.zero_rows_on:   # the row vanished mid-sweep: the UPDATE matches nothing
                self.rowcount = 0
                return
            c.pending.append(sym)
            self.rowcount = 1


class _Conn:
    def __init__(self, lock_timeout_on=(), commit_fails=False, zero_rows_on=()):
        self.lock_timeout_on, self.commit_fails = set(lock_timeout_on), commit_fails
        self.zero_rows_on = set(zero_rows_on)
        self.pending, self.sp_pending, self.aborted, self.committed = [], [], False, []

    def cursor(self):
        return _Cur(self)

    def commit(self):
        if self.commit_fails:
            self.pending, self.aborted = [], False
            raise pge.InFailedSqlTransaction("commit failed")
        if self.aborted:                      # Postgres: COMMIT of an aborted txn is a ROLLBACK, no error
            self.pending, self.aborted = [], False
            return
        self.committed += self.pending
        self.pending = []

    def rollback(self):
        self.pending, self.aborted = [], False

    def close(self):
        pass


@pytest.fixture()
def harness(monkeypatch):
    mods = {
        "finviz_enrichment": types.SimpleNamespace(enrich_tickers=lambda *a, **k: None,
                                                   get_enriched=lambda *a, **k: {"rsi": "50"}),
        "open_trades_intelligence": types.SimpleNamespace(_trend_label=lambda a, b: "neutral"),
        "setup_quality_prior": types.SimpleNamespace(rsi_band=lambda r: "mid"),
        "directive_promotion": types.SimpleNamespace(classify_tradeable=lambda s, t: []),
        "price_db_sync": types.SimpleNamespace(sync_quotes_to_ticker_prices=lambda s: None),
    }
    for k, v in mods.items():
        monkeypatch.setitem(sys.modules, k, v)
    monkeypatch.setattr(W, "_price", lambda conn, sym, allow_fetch=True: (10.0, 1.0, "market_quotes"))
    monkeypatch.setattr(W, "price_capture_available", lambda cur: False)

    def run(conn, syms):
        monkeypatch.setattr(W, "_conn", lambda: conn)
        return W.enrich_symbols(syms)
    return run


def test_clean_run_has_no_db_errors(harness):
    conn = _Conn()
    res = harness(conn, ["AAA", "BBB", "CCC"])
    assert res["enriched"] == 3 and res.get("db_errors", 0) == 0
    assert conn.committed == ["AAA", "BBB", "CCC"]


def test_lock_timeout_on_one_row_is_counted_and_does_not_poison_the_batch(harness):
    conn = _Conn(lock_timeout_on={"BBB"})
    res = harness(conn, ["AAA", "BBB", "CCC", "DDD"])
    assert res["db_errors"] == 1
    assert "lock timeout" in res["db_error_sample"]
    assert conn.committed == ["AAA", "CCC", "DDD"]      # the rows after the failure still land
    assert res["enriched"] == 3                         # and the failed one is not counted


def test_failed_commit_removes_the_batch_from_enriched(harness):
    conn = _Conn(commit_fails=True)
    res = harness(conn, ["AAA", "BBB"])
    assert res["db_errors"] >= 1 and res["enriched"] == 0


def test_main_exits_nonzero_and_receipt_names_db_errors(monkeypatch, harness):
    seen = {}
    monkeypatch.setattr(W, "sweep", lambda **k: {"total": 4, "enriched": 3, "deferred": 0,
                                                 "db_errors": 1, "db_fatal": 1, "db_error_sample": "lock timeout"})
    fake = types.SimpleNamespace(write_lane_receipt=lambda lane, **kw: seen.update(kw))
    monkeypatch.setattr(W, "_receipt_lib", lambda: fake)
    rc = W.main(["--once"])
    assert rc == 1 and seen["ok"] is False and seen["exit_code"] == 1
    assert seen["summary"]["db_errors"] == 1 and seen["summary"]["db_error_sample"] == "lock timeout"
    assert seen["output"]["skipped_reasons"]["db_error"] == 1


def test_main_stays_zero_without_db_errors(monkeypatch):
    seen = {}
    monkeypatch.setattr(W, "sweep", lambda **k: {"total": 4, "enriched": 4, "deferred": 0, "db_errors": 0})
    monkeypatch.setattr(W, "_receipt_lib", lambda: types.SimpleNamespace(write_lane_receipt=lambda lane, **kw: seen.update(kw)))
    assert W.main(["--once"]) == 0 and seen["ok"] is True and "db_errors" not in seen["summary"]


def test_rowcount_is_read_before_release_so_a_zero_row_update_is_not_enriched(harness):
    """LQ-2991 F2: RELEASE SAVEPOINT leaves cursor.rowcount at -1 (truthy), which counted a 0-row UPDATE as enriched."""
    conn = _Conn(zero_rows_on={"BBB"})
    res = harness(conn, ["AAA", "BBB", "CCC"])
    assert res["enriched"] == 2 and conn.committed == ["AAA", "CCC"]


def test_every_update_matching_nothing_is_still_the_total_failure(harness, monkeypatch):
    conn = _Conn(zero_rows_on={"AAA", "BBB"})
    res = harness(conn, ["AAA", "BBB"])
    assert res["enriched"] == 0 and res["total"] == 2


def _run_main(monkeypatch, res):
    seen = {}
    monkeypatch.setattr(W, "sweep", lambda **k: res)
    monkeypatch.setattr(W, "_receipt_lib", lambda: types.SimpleNamespace(write_lane_receipt=lambda lane, **kw: seen.update(kw)))
    return W.main(["--once"]), seen


def test_rolled_back_row_lock_timeout_is_degraded_exit_zero_not_a_dead_letter(monkeypatch):
    """LQ-2991 F1: exit 1 is terminal under transient-1-ingest (dead letter, breaker). One lost row is not that."""
    rc, seen = _run_main(monkeypatch, {"total": 4, "enriched": 3, "deferred": 0, "db_errors": 1, "db_fatal": 0,
                                       "db_error_sample": "BBB: LockNotAvailable"})
    assert rc == 0 and seen["exit_code"] == 0
    assert seen["outcome"] == "degraded" and "rolled back" in seen["outcome_reason"]
    assert seen["summary"]["db_errors"] == 1 and seen["output"]["skipped_reasons"]["db_error"] == 1


def test_commit_failure_and_connection_loss_are_exit_one(monkeypatch, harness):
    conn = _Conn(commit_fails=True)
    res = harness(conn, ["AAA", "BBB"])
    assert res["db_fatal"] >= 1
    rc, seen = _run_main(monkeypatch, {"total": 2, "enriched": 1, "deferred": 0, "db_errors": 1, "db_fatal": 1})
    assert rc == 1 and seen["ok"] is False


def test_row_lock_timeout_alone_is_not_fatal_in_enrich_symbols(harness):
    res = harness(_Conn(lock_timeout_on={"BBB"}), ["AAA", "BBB", "CCC"])
    assert res["db_errors"] == 1 and res["db_fatal"] == 0


def test_all_rows_failing_is_exit_one(monkeypatch):
    rc, _ = _run_main(monkeypatch, {"total": 3, "enriched": 0, "deferred": 0, "db_errors": 3, "db_fatal": 0})
    assert rc == 1


def test_savepoint_failure_rolls_back_the_batch_and_uncounts_it(harness):
    """LQ-2991 F4: SAVEPOINT raising (aborted/dead txn) rolls the whole transaction back; earlier rows are not 'enriched'."""
    conn = _Conn()
    real = conn.cursor

    class _Boom(_Cur):
        def execute(self, sql, params=None):
            if " ".join(sql.split()).startswith("SAVEPOINT") and getattr(self.c, "boom_next", False):
                self.c.boom_next = False
                raise pge.InFailedSqlTransaction("aborted")
            return super().execute(sql, params)
    conn.cursor = lambda: _Boom(conn)
    orig = _Boom.execute
    n = {"i": 0}

    def exe(self, sql, params=None):
        if " ".join(sql.split()).startswith("SAVEPOINT"):
            n["i"] += 1
            if n["i"] == 3:
                self.c.boom_next = True
        return orig(self, sql, params)
    _Boom.execute = exe
    res = harness(conn, ["AAA", "BBB", "CCC"])
    assert res["db_errors"] == 1 and res["db_fatal"] == 1
    assert res["enriched"] == len(conn.committed)       # the counter equals what really landed
