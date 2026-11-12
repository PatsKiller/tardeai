"""LQ-20261107-2135: the proposal-technicals pattern lookup queried columns that do not exist
(``pattern_library.symbol`` / ``pattern_description``) and ``except Exception: pass`` hid ~695 PG errors.
A lookup that fails must be named, counted and logged, must not abort the caller's transaction, and must
reach the lane receipt. Synthetic table only; no database."""
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import proposal_technical_snapshot as S  # noqa: E402
import enrich_proposal_technicals as E  # noqa: E402

# The columns the real table has (information_schema, LQ-2135). There is no symbol / pattern_description.
COLUMNS = {"pattern_name", "strategy_id", "definition", "conditions", "notes", "status",
           "trade_count", "win_rate", "expectancy", "created_at"}


class UndefinedColumn(Exception):
    pass


class InFailedSqlTransaction(Exception):
    pass


class FakeCursor:
    """Models: the pattern_library table, SAVEPOINT / ROLLBACK TO, and the aborted-transaction state."""

    def __init__(self, rows=None, break_with=None):
        self.rows = rows or []
        self.break_with = break_with      # exception raised by the pattern query itself
        self.aborted = False
        self.savepoints = []
        self.log = []
        self._result = None

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.log.append(s)
        if s.startswith("ROLLBACK TO SAVEPOINT"):
            self.aborted = False
            return
        if self.aborted:
            raise InFailedSqlTransaction("current transaction is aborted, commands ignored until end of transaction block")
        if s.startswith("SAVEPOINT"):
            self.savepoints.append(s.split()[-1])
            return
        if s.startswith("RELEASE SAVEPOINT"):
            return
        if "FROM pattern_library" in s:
            if self.break_with is not None:
                self.aborted = True
                raise self.break_with
            self._validate_columns(s)
            self._result = self._pattern_rows(params)
            return
        self._result = [("ok",)]

    def _validate_columns(self, s):
        select = s.split("SELECT", 1)[1].split("FROM", 1)[0]
        for col in (c.strip() for c in select.split(",")):
            if col not in COLUMNS:
                self.aborted = True
                raise UndefinedColumn(f'column "{col}" does not exist')

    def _pattern_rows(self, params):
        symbol, strategy_id = params[0], params[1]
        hit = []
        for r in self.rows:
            if r["status"] not in ("PROVEN", "WATCH", "NEUTRAL"):
                continue
            by_sym = symbol in (r.get("definition") or {}).get("sample_symbols", [])
            by_strat = strategy_id is not None and r.get("strategy_id") == strategy_id
            if by_sym or by_strat:
                hit.append((not by_sym, -(r.get("trade_count") or 0), r))
        hit.sort(key=lambda t: t[:2])
        if not hit:
            return []
        r = hit[0][2]
        return [(r["pattern_name"], r.get("strategy_id"), r["status"], r.get("trade_count"),
                 r.get("win_rate"), r.get("expectancy"))]

    def fetchone(self):
        return self._result[0] if self._result else None


def _row(name, symbols=(), strategy="s1", status="PROVEN", trades=40, win=0.6, exp=12.5):
    return {"pattern_name": name, "strategy_id": strategy, "status": status, "trade_count": trades,
            "win_rate": win, "expectancy": exp, "definition": {"sample_symbols": list(symbols)}}


@pytest.fixture(autouse=True)
def _reset():
    S.PATTERN_LOOKUP_FAILURES = 0
    yield


def test_old_query_columns_do_not_exist_in_the_table_model():
    """The base query selected a non-existent column; the model raises exactly like Postgres did."""
    cur = FakeCursor([_row("p")])
    with pytest.raises(UndefinedColumn):
        cur.execute("SELECT pattern_description FROM pattern_library WHERE symbol = %s", ["AAPL"])
    assert cur.aborted


def test_symbol_match_is_available():
    cur = FakeCursor([_row("breakout_a", symbols=["AAPL"]), _row("other", symbols=["MSFT"], strategy="x")])
    out = S.lookup_normal_pattern(cur, "AAPL", None)
    assert out["status"] == "AVAILABLE"
    assert "breakout_a (PROVEN)" in out["text"] and "40 trades" in out["text"] and "win rate 60%" in out["text"]
    assert S.PATTERN_LOOKUP_FAILURES == 0


def test_strategy_fallback_when_symbol_unknown():
    cur = FakeCursor([_row("strat_pat", symbols=[], strategy="momentum_scalp")])
    out = S.lookup_normal_pattern(cur, "ZZZZ", "momentum_scalp")
    assert out["status"] == "AVAILABLE" and out["text"].startswith("strat_pat")


def test_symbol_match_beats_strategy_match():
    cur = FakeCursor([_row("by_strategy", strategy="s1", trades=500), _row("by_symbol", symbols=["AAPL"], strategy="s9", trades=5)])
    assert S.lookup_normal_pattern(cur, "AAPL", "s1")["text"].startswith("by_symbol")


def test_killed_pattern_is_not_offered():
    cur = FakeCursor([_row("dead", symbols=["AAPL"], status="KILLED")])
    assert S.lookup_normal_pattern(cur, "AAPL", None)["status"] == "NO_MATCH"


def test_no_match_is_distinct_from_unavailable():
    ok = S.lookup_normal_pattern(FakeCursor([]), "AAPL", None)
    assert ok["status"] == "NO_MATCH" and ok["text"] == S.PATTERN_UNAVAILABLE_TEXT
    assert S.PATTERN_LOOKUP_FAILURES == 0
    bad = S.lookup_normal_pattern(FakeCursor(break_with=UndefinedColumn('column "symbol" does not exist')), "AAPL", None)
    assert bad["status"] == "UNAVAILABLE" and bad["text"] != S.PATTERN_UNAVAILABLE_TEXT
    assert "UndefinedColumn" in bad["reason"] and "symbol" in bad["reason"]


def test_failed_lookup_is_counted_and_logged(caplog):
    cur = FakeCursor(break_with=UndefinedColumn('column "symbol" does not exist'))
    with caplog.at_level(logging.ERROR):
        S.lookup_normal_pattern(cur, "AAPL", None)
        S.lookup_normal_pattern(FakeCursor(break_with=UndefinedColumn("x")), "MSFT", None)
    assert S.PATTERN_LOOKUP_FAILURES == 2
    assert [r for r in caplog.records if "pattern_library lookup FAILED" in r.getMessage()]


def test_failed_lookup_does_not_abort_the_callers_transaction():
    """Base: the failed SELECT left the cursor aborted, so every following statement raised
    InFailedSqlTransaction. The SAVEPOINT rolls back only the lookup."""
    cur = FakeCursor(break_with=UndefinedColumn("boom"))
    assert S.lookup_normal_pattern(cur, "AAPL", None)["status"] == "UNAVAILABLE"
    assert cur.aborted is False
    cur.execute("SELECT 1")             # would raise InFailedSqlTransaction without the savepoint
    assert cur.fetchone() == ("ok",)


def test_dead_connection_is_unavailable_not_a_crash():
    class Dead:
        def execute(self, *a, **k):
            raise RuntimeError("connection already closed")
    out = S.lookup_normal_pattern(Dead(), "AAPL", None)
    assert out["status"] == "UNAVAILABLE" and "RuntimeError" in out["reason"]
    assert S.PATTERN_LOOKUP_FAILURES == 1


def test_query_uses_only_real_columns():
    cur = FakeCursor([_row("p", symbols=["AAPL"])])
    S.lookup_normal_pattern(cur, "AAPL", None)
    sql = next(s for s in cur.log if "FROM pattern_library" in s)
    assert "pattern_description" not in sql
    assert "WHERE symbol" not in sql and " symbol =" not in sql
    assert "'KILLED'" not in sql and "'PROVEN'" in sql   # the fake filters by status itself, so pin the SQL text


def test_receipt_outcome_all_pattern_lookups_failed_is_an_error():
    assert E.receipt_outcome(5, 5, 0, finviz_got=5, pattern_failed=5, pattern_checked=5) == (
        "error", "pattern_lookup_failed_for_all:5")


def test_receipt_outcome_partial_pattern_failure_is_named_but_ok():
    assert E.receipt_outcome(5, 5, 0, finviz_got=5, pattern_failed=2, pattern_checked=5) == (
        "ok", "pattern_lookup_failed:2/5")


def test_receipt_outcome_unchanged_without_pattern_failures():
    assert E.receipt_outcome(5, 4, 1, finviz_got=5) == ("ok", "partial_failures:1")
    assert E.receipt_outcome(5, 5, 0, finviz_got=5, pattern_failed=0, pattern_checked=5) == ("ok", None)


# ---- LQ-20261107-2159 (REVIEW-2156 C1 + N1): the chain from a failed lookup to a red receipt ----------

def test_unknown_or_empty_strategy_is_not_a_fallback_key():
    """N1: every library row has strategy_id 'UNKNOWN'; a proposal with that placeholder must not be told the
    highest-count bucket of an unrelated symbol is its normal pattern."""
    rows = [_row("float_mid", symbols=["PL"], strategy="UNKNOWN", trades=212)]
    for placeholder in ("UNKNOWN", "unknown", " ", "", None):
        out = S.lookup_normal_pattern(FakeCursor(rows), "ZZZZ", placeholder)
        assert out["status"] == "NO_MATCH", placeholder
    assert S.lookup_normal_pattern(FakeCursor(rows), "PL", "UNKNOWN")["status"] == "AVAILABLE"   # by symbol
    real = [_row("strat_pat", strategy="momentum_scalp")]
    assert S.lookup_normal_pattern(FakeCursor(real), "ZZZZ", "momentum_scalp")["status"] == "AVAILABLE"


def test_sql_text_pins_the_status_list_and_symbol_first_order():
    cur = FakeCursor([_row("p", symbols=["AAPL"])])
    S.lookup_normal_pattern(cur, "AAPL", None)
    sql = next(s for s in cur.log if "FROM pattern_library" in s)
    assert "status IN ('PROVEN', 'WATCH', 'NEUTRAL')" in sql          # no extra status can slip in
    order = sql.split("ORDER BY", 1)[1]
    assert order.lstrip().startswith("COALESCE((definition -> 'sample_symbols') @> to_jsonb(%s::text), false) DESC")
    assert "trade_count DESC" in order and order.index("sample_symbols") < order.index("trade_count")


class _Conn:
    def cursor(self):
        return self

    def execute(self, *a, **k):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture()
def lane(monkeypatch):
    """Run E.main() with every outside edge stubbed; returns (run, receipts). ``statuses`` drives each snapshot."""
    import types

    receipts = []
    from lib import lane_last_receipt as LR
    monkeypatch.setattr(LR, "write_lane_receipt", lambda lane_id, **kw: receipts.append(kw))

    def install(statuses):
        rows = [{"id": i + 1, "symbol": f"S{i}", "catalyst": None, "catalyst_verified": False} for i in range(len(statuses))]
        monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_execute=lambda *a, **k: rows, _get_conn=lambda: _Conn()))
        monkeypatch.setitem(sys.modules, "finviz_enrichment", types.SimpleNamespace(enrich_tickers=lambda syms, **k: {s: {} for s in syms}))
        monkeypatch.setitem(sys.modules, "proposal_enrichment_bridge",
                            types.SimpleNamespace(compute_proposal_intel_readiness=lambda *a, **k: "READY"))
        it = iter(statuses)
        monkeypatch.setattr(S, "generate_snapshot",
                            lambda conn, proposal_id=None, symbol=None: {"symbol": symbol, "normal_trading_pattern_status": next(it)})

    def run(statuses):
        install(statuses)
        return E.main(), receipts[-1]
    return run


def test_lane_counts_unavailable_snapshots_and_goes_red_when_all_failed(lane):
    code, r = lane(["UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE"])
    assert code == 1 and r["outcome"] == "error" and r["outcome_reason"] == "pattern_lookup_failed_for_all:3"
    assert r["summary"]["pattern_lookup_failed"] == 3 and r["summary"]["pattern_lookup_checked"] == 3


def test_lane_partial_pattern_failure_stays_ok_but_is_named(lane):
    code, r = lane(["AVAILABLE", "UNAVAILABLE", "NO_MATCH", "UNAVAILABLE"])
    assert code == 0 and r["outcome"] == "ok" and r["outcome_reason"] == "pattern_lookup_failed:2/4"
    assert (r["summary"]["pattern_lookup_failed"], r["summary"]["pattern_lookup_checked"]) == (2, 4)


def test_lane_no_match_is_not_a_failure(lane):
    code, r = lane(["NO_MATCH", "NO_MATCH"])
    assert code == 0 and r["outcome"] == "ok" and r["outcome_reason"] is None
    assert r["summary"]["pattern_lookup_failed"] == 0


def test_lane_counts_reset_between_runs(lane):
    """A bad run must not colour the next one (the module-level counter is reused in-process)."""
    lane(["UNAVAILABLE", "UNAVAILABLE"])
    code, r = lane(["AVAILABLE", "AVAILABLE"])
    assert code == 0 and r["outcome_reason"] is None
    assert (r["summary"]["pattern_lookup_failed"], r["summary"]["pattern_lookup_checked"]) == (0, 2)


def _cli(monkeypatch, fail):
    class Cur(_Conn):
        def fetchall(self):
            return [(1,), (2,)]

    class Conn(_Conn):
        def cursor(self):
            return Cur()

        def close(self):
            pass

    def snap(conn, proposal_id=None, symbol=None):
        if fail:
            S.PATTERN_LOOKUP_FAILURES += 1
        return {"symbol": "AAA"}

    monkeypatch.setattr(S, "get_conn", lambda: Conn())
    monkeypatch.setattr(S, "generate_snapshot", snap)
    monkeypatch.setattr(sys, "argv", ["proposal_technical_snapshot.py", "--pending"])
    return S.main()


def test_cli_exits_1_when_any_pattern_lookup_failed(monkeypatch, capsys):
    assert _cli(monkeypatch, fail=True) == 1
    assert json_out(capsys)["pattern_lookup_failures"] == 2


def test_cli_exits_0_when_no_lookup_failed(monkeypatch, capsys):
    assert _cli(monkeypatch, fail=False) == 0
    assert json_out(capsys)["pattern_lookup_failures"] == 0


def json_out(capsys):
    import json
    return json.loads(capsys.readouterr().out)
