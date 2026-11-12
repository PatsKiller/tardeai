"""LQ-20261107-2458: proposal-backtest-engine's pattern_library query and its silent SQL failures.

Synthetic connection only — no DB, no network, no live receipt path (``TRADEAI_STATE_ROOT`` is a tmp dir).
What is pinned:

* BEFORE: the pattern query selected ``pattern_description`` and matched ``symbol`` — neither exists — so
  Postgres raised for every processed item, left the transaction ABORTED, made the next query fail with
  "current transaction is aborted", and both errors were swallowed: the receipt said ``status ok`` with
  ``load_errors 0`` (PG log 2026-11-12: 14 errors at 10:13, 13 at 12:08, 7 at 14:13, receipt ok each time).
* AFTER: the real columns (``pattern_name``/``status``/``notes``, symbol via
  ``definition -> 'sample_symbols'``), a rollback per failed item, and any SQL failure carried out as the
  item's error: the run exits 1 and the receipt is written failed with the failure named.

The mutants at the bottom put the BEFORE back into the fixed module (old SQL alone; silent handler alone) and
show the tests fail on them — that is how the fix is shown to be load-bearing rather than incidental.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Required CI has no psycopg2 (these tests use fake connections only). Stand-in only when the real driver is
# absent, so this file still runs in CI.
try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")
    _pg_extras = types.ModuleType("psycopg2.extras")
    _pg_extras.RealDictCursor = object
    _pg.extras = _pg_extras

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must use fake connections")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)
    sys.modules.setdefault("psycopg2.extras", _pg_extras)

import proposal_backtest_engine as bt  # noqa: E402

SRC = (ROOT / "scripts/proposal_backtest_engine.py").read_text()

PROPOSAL_COLS = ["id", "symbol", "strategy_id", "setup_type", "rvol", "float_m", "gap_pct", "catalyst",
                 "catalyst_verified", "catalyst_confidence", "critic_verdict", "sector"]
PROPOSAL_ROW = (101, "OKTA", "pullback_macd_reversal", "PULLBACK", 2.0, 50.0, 5.0,
                None, None, None, None, "Technology")


class UndefinedColumn(Exception):
    """The shape of psycopg2.errors.UndefinedColumn."""


class InFailedSqlTransaction(Exception):
    """The shape of psycopg2.errors.InFailedSqlTransaction."""


def _norm(sql: str) -> str:
    return " ".join(str(sql).split())


def _rows_for(doc: str):
    """Canned answers, matched most-specific first."""
    if "FROM paper_trade_proposals WHERE id = %s" in doc:
        return [PROPOSAL_ROW]
    if "FROM trade_ai_scans WHERE symbol = %s GROUP BY decision" in doc:
        return [("GO", 3)]
    if "FROM trade_ai_scans WHERE symbol = %s" in doc:
        return [(3,)]
    if "ORDER BY closed_at DESC LIMIT 1" in doc:
        return [(-10.0, "STOP")]
    if "FROM paper_trades WHERE symbol = %s AND status = 'closed'" in doc:
        return [(4, 2, 120.5)]
    if "FROM trade_closed WHERE symbol = %s" in doc:
        return [(2, 1, 40.0)]
    if "FROM paper_trades WHERE strategy_id = %s AND status = 'closed'" in doc:
        return [(12, 7, 5, 700.0, 300.0, 58.3, 1.2)]
    if "FROM paper_trades pt" in doc:
        return []
    if "FROM pattern_library" in doc:
        return [("float_small", "PROVEN", "Auto-extracted 2026-11-01. 5 trades, WR=40%")]
    if "FROM agent_recommendation_outcomes" in doc:
        return [(3, 2)]
    if "SELECT id FROM paper_trade_proposals WHERE status = ANY(%s)" in doc:
        return [(101,)]
    return []


class Cursor:
    def __init__(self, db: "DB") -> None:
        self.db, self.description, self._rows = db, None, []

    def execute(self, sql, params=None):
        doc = _norm(sql)
        self.db.statements.append(doc)
        if self.db.aborted:
            self.db.aborted_ignored += 1
            raise InFailedSqlTransaction(
                "current transaction is aborted, commands ignored until end of transaction block")
        exc = self.db.failing(doc)
        if exc is not None:
            self.db.failures.append((doc, exc))
            self.db.aborted = True
            raise exc
        self.description = ([(c,) for c in PROPOSAL_COLS]
                            if "FROM paper_trade_proposals WHERE id = %s" in doc else None)
        self._rows = _rows_for(doc)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class DB:
    """A connection that behaves like Postgres in the one property that matters here: a failed statement
    leaves the transaction aborted until rollback()."""

    def __init__(self, failing=None):
        self.failing = failing or (lambda doc: None)
        self.aborted = False
        self.failures = []
        self.statements = []
        self.rollbacks = 0
        self.commits = 0
        self.aborted_ignored = 0

    def cursor(self):
        return Cursor(self)

    def rollback(self):
        self.aborted, self.rollbacks = False, self.rollbacks + 1

    def commit(self):
        self.commits += 1

    def close(self):
        pass

    def executed(self, needle: str):
        return [s for s in self.statements if needle in s]


def pattern_query_fails(doc: str):
    return UndefinedColumn('column "pattern_description" does not exist') if "FROM pattern_library" in doc else None


@pytest.fixture
def no_live_state(monkeypatch, tmp_path):
    """Nothing a test does may resolve to the production receipt path."""
    state = tmp_path / "state"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    return state


# ------------------------------------------------------------------ the query

def test_pattern_query_names_only_real_columns():
    db = DB()
    result = bt.backtest_proposal(db, 101, persist=False)
    query = db.executed("FROM pattern_library")[0]
    assert "pattern_description" not in query
    assert "SELECT pattern_name, status, COALESCE(notes, '')" in query
    assert "WHERE (definition -> 'sample_symbols' ? %s OR strategy_id = %s)" in query
    assert "error" not in result
    assert result["patterns"]["proven"] == ["float_small: Auto-extracted 2026-11-01. 5 trades, WR=40%"]


def test_source_has_no_reference_to_the_missing_column():
    """The read-only schema check says pattern_library has no pattern_description; the module's SQL must not
    name it (the PG-log error the issue reports can then no longer be produced by this script). The word
    survives only in the comment that records why it was removed."""
    assert "SELECT pattern_name, status, pattern_description" not in SRC
    assert "WHERE (symbol = %s OR strategy_id = %s)" not in SRC


# ------------------------------------------------------------------ a failed query is not silent

def test_failed_query_rolls_back_and_fails_the_item():
    db = DB(failing=pattern_query_fails)
    result = bt.backtest_proposal(db, 101, persist=False)
    assert result["error"].startswith("sql_error: 1 enrichment query failure(s)")
    assert result["sql_errors"] and "pattern_library" in result["sql_errors"][0]
    assert result["persisted"] is False
    assert db.rollbacks >= 1
    assert db.aborted_ignored == 0, "the next query must not meet the aborted transaction"
    assert db.executed("FROM agent_recommendation_outcomes"), "later enrichment still runs"


def test_failed_query_item_is_not_persisted():
    db = DB(failing=pattern_query_fails)
    bt.backtest_proposal(db, 101, persist=True)
    assert db.executed("INSERT INTO proposal_backtest_snapshots") == []
    assert db.commits == 0


def test_many_failures_are_all_named():
    db = DB(failing=lambda d: UndefinedColumn("boom")
            if ("FROM pattern_library" in d or "FROM agent_recommendation_outcomes" in d) else None)
    result = bt.backtest_proposal(db, 101, persist=False)
    assert len(result["sql_errors"]) == 2
    assert "2 enrichment query failure(s)" in result["error"]


# ------------------------------------------------------------------ the receipt

def _patch_receipt(monkeypatch, sink, dry_sink=None):
    """Capture the receipt writer on every module instance `_receipt_lib()` may resolve to."""
    mods = []
    for name in ("lib.lane_last_receipt", "scripts.lib.lane_last_receipt"):
        try:
            m = importlib.import_module(name)
        except Exception:  # noqa: BLE001 - a name that does not resolve is simply not used
            continue
        if all(m is not x for x in mods):
            mods.append(m)
    assert mods, "the receipt library must be importable"
    for m in mods:
        monkeypatch.setattr(m, "write_lane_receipt", lambda lane_id, **kw: sink.append((lane_id, kw)))
        monkeypatch.setattr(m, "dry_run_report",
                            lambda lane_id, summary, **kw: (dry_sink.append((lane_id, summary, kw))
                                                            or {"dry_run": True}))


def test_receipt_says_failed_when_an_enrichment_query_fails(monkeypatch, no_live_state):
    db = DB(failing=pattern_query_fails)
    receipts: list = []
    monkeypatch.setattr(bt, "get_conn", lambda: db)
    monkeypatch.setattr(bt, "_write_strategy_backtest_result", lambda conn, result: True)
    _patch_receipt(monkeypatch, receipts)

    rc = bt.main(["--all-pending", "--apply"])

    assert rc == 1
    lane_id, kw = receipts[-1]
    assert lane_id == "proposal-backtest-engine"
    assert kw["ok"] is False and kw["exit_code"] == 1
    assert kw["summary"] == {"processed": 0, "load_errors": 1, "persist_failures": 0}
    assert "sql_error: 1 enrichment query failure(s)" in (kw.get("error") or "")
    assert "pattern_library" in kw["error"]
    assert kw["output"]["produced_count"] == 0
    assert kw["output"]["attempted_count"] == 1
    assert kw["output"]["skipped_reasons"]["load_error"] == 1
    assert kw["output"]["empty_reason"] is None


def test_green_run_still_reports_ok(monkeypatch, no_live_state):
    db = DB()
    receipts: list = []
    monkeypatch.setattr(bt, "get_conn", lambda: db)
    monkeypatch.setattr(bt, "_write_strategy_backtest_result", lambda conn, result: True)
    _patch_receipt(monkeypatch, receipts)

    rc = bt.main(["--all-pending", "--apply"])

    assert rc == 0
    lane_id, kw = receipts[-1]
    assert kw["ok"] is True and kw["exit_code"] == 0
    assert kw["summary"] == {"processed": 1, "load_errors": 0, "persist_failures": 0}
    assert kw["error"] is None
    assert kw["output"]["produced_count"] == 1 and kw["output"]["attempted_count"] == 1
    assert kw["output"]["skipped_reasons"] == {"load_error": 0, "persist_failed": 0}
    assert db.executed("INSERT INTO proposal_backtest_snapshots")


def test_dry_run_against_the_mock_reports_the_failure(monkeypatch, no_live_state):
    """The queue's AFTER evidence: the dry run (read-only path) against a mock DB."""
    db = DB(failing=pattern_query_fails)
    receipts: list = []
    dry: list = []
    monkeypatch.setattr(bt, "get_conn", lambda: db)
    monkeypatch.setattr(bt, "_write_strategy_backtest_result", lambda conn, result: True)
    _patch_receipt(monkeypatch, receipts, dry)

    rc = bt.main(["--all-pending", "--dry-run"])

    assert rc == 1
    assert receipts == [], "a dry run writes no receipt"
    lane_id, summary, kw = dry[-1]
    assert summary == {"processed": 0, "load_errors": 1, "persist_failures": 0}
    assert kw["would_write"] and "proposal_backtest_snapshots" in kw["would_write"][0]
    assert db.executed("INSERT INTO proposal_backtest_snapshots") == []


def test_a_dry_run_writes_nothing_under_the_state_root(monkeypatch, no_live_state):
    """LQ-2230 lesson: an offline run must not write a receipt. Real receipt library, tmp state root."""
    db = DB(failing=pattern_query_fails)
    monkeypatch.setattr(bt, "get_conn", lambda: db)

    rc = bt.main(["--all-pending", "--dry-run"])

    assert rc == 1
    assert not list(no_live_state.rglob("*")), "a dry run created files under the state root"


# ------------------------------------------------------------------ mutants: the BEFORE

OLD_SQL = (
    "            SELECT pattern_name, status, COALESCE(notes, '')\n"
    "            FROM pattern_library\n"
    "            WHERE (definition -> 'sample_symbols' ? %s OR strategy_id = %s)\n"
)
BROKEN_SQL = (
    "            SELECT pattern_name, status, pattern_description\n"
    "            FROM pattern_library\n"
    "            WHERE (symbol = %s OR strategy_id = %s)\n"
)
RECORDING_HANDLER = (
    '        sql_errors.append(f"{section}: {type(exc).__name__}: {str(exc)[:160]}")\n'
    "        try:\n"
    "            conn.rollback()\n"
    "        except Exception:\n"
    "            pass  # a broken connection is the caller's problem; the run still fails on sql_errors\n"
)


def load_mutant(tmp_path, name, pairs):
    src = SRC
    for old, new in pairs:
        assert src.count(old) == 1, f"{name}: anchor not unique: {old!r}"
        src = src.replace(old, new)
    path = tmp_path / f"mutant_{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(f"mutant_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_mutant_old_query_and_silent_handler_reproduces_the_before(tmp_path):
    mod = load_mutant(tmp_path, "swallowed", [(OLD_SQL, BROKEN_SQL), (RECORDING_HANDLER, "        pass\n")])
    db = DB(failing=pattern_query_fails)

    result = mod.backtest_proposal(db, 101, persist=True)

    # BEFORE: the query failed, the transaction stayed aborted, the next query failed too, and the result
    # reported no error at all — the item was persisted from partial evidence.
    assert db.failures, "the broken query really failed"
    assert db.aborted_ignored >= 1, "the next query met the aborted transaction"
    assert "error" not in result and not result.get("sql_errors")
    assert result.get("persisted") is True
    assert db.executed("INSERT INTO proposal_backtest_snapshots")

    # AFTER, same inputs: the fixed module's query does not fail at all and the item persists cleanly.
    fixed_db = DB()
    fixed = bt.backtest_proposal(fixed_db, 101, persist=True)
    assert fixed_db.failures == [] and "error" not in fixed and fixed["persisted"] is True


def test_mutant_silent_handler_alone_keeps_the_receipt_green(tmp_path, monkeypatch, no_live_state):
    """Real columns fixed, handler still silent: a future schema drift would be invisible — the receipt would
    say ok with load_errors 0, exit 0. The shipped handler fails it instead."""
    mod = load_mutant(tmp_path, "silent_only", [(RECORDING_HANDLER, "        pass\n")])
    receipts: list = []
    monkeypatch.setattr(mod, "get_conn", lambda: DB(failing=pattern_query_fails))
    monkeypatch.setattr(mod, "_write_strategy_backtest_result", lambda conn, result: True)
    _patch_receipt(monkeypatch, receipts)

    rc = mod.main(["--all-pending", "--apply"])

    assert rc == 0, "BEFORE: a SQL error still yields exit 0"
    assert receipts[-1][1]["ok"] is True
    assert receipts[-1][1]["summary"] == {"processed": 1, "load_errors": 0, "persist_failures": 0}
    assert receipts[-1][1]["error"] is None
