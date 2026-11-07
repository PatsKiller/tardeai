"""Refactor wave 2 (cron -> n8n, 2026-10-10), bucket V4: backtest / outcome-linking lanes.

- scripts/strategy_backtester.py (cron L352): --dry-run wins over --apply (``--apply --dry-run`` used to
  apply); READ ONLY session; --apply runs leave strategy-backtester_last.json. A low sample is a finding.
- scripts/proposal_backtest_engine.py (cron L606): --dry-run used to be parsed and IGNORED (every run
  upserted). Now backtest_proposal(persist=False) returns before the upsert and the strategy_backtest_results
  insert is not called; the session is READ ONLY. Persist failures exit 1.
- scripts/agent_outcome_linker.py (cron L318): --dry-run wins over --apply; save_links is unreachable from a
  dry run; the SELECT caps are reported (proposal_cap_hit / trade_cap_hit).
Hermetic: fake connections, TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import inspect
import json
import re
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Required CI has no psycopg2 (these tests use fake connections only). Install a minimal stand-in ONLY when the real
# driver is absent, so the dry-run safety tests still run in CI instead of being skipped by importorskip.
try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    import types as _types

    _pg = _types.ModuleType("psycopg2")
    _pg_extras = _types.ModuleType("psycopg2.extras")
    _pg_extras.RealDictCursor = object
    _pg.extras = _pg_extras

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must use fake connections")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)
    sys.modules.setdefault("psycopg2.extras", _pg_extras)

import agent_outcome_linker as aol  # noqa: E402
import proposal_backtest_engine as pbe  # noqa: E402
import strategy_backtester as sbt  # noqa: E402
from lib import lane_last_receipt as llr  # noqa: E402

_WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "TRUNCATE")


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.rowcount, self.description = conn, 1, None
        self._one, self._all = (0,), []

    def execute(self, sql, params=None):
        norm = " ".join(sql.split())
        self.conn.sql.append(norm)
        self.conn.params.append(list(params) if params else [])
        if self.conn.fail_on and self.conn.fail_on in norm:
            raise RuntimeError("db failure")
        res = (self.conn.responder(norm, params) if self.conn.responder else None) or {}
        self.description = res.get("description")
        self._one, self._all = res.get("one", (0,)), res.get("all", [])
        self.rowcount = res.get("rowcount", 1)

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self._all)

    def close(self):
        pass


class FakeConn:
    def __init__(self, responder=None, fail_on=None):
        self.responder, self.fail_on = responder, fail_on
        self.sql, self.params, self.commits, self.readonly, self.closed = [], [], 0, None, False

    def cursor(self, *a, **k):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def set_session(self, readonly=None, **k):
        self.readonly = readonly

    def close(self):
        self.closed = True

    def writes(self):
        return [s for s in self.sql if s.split()[0].upper() in _WRITE_VERBS]


def _boom(*a, **k):
    raise AssertionError("dry run reached a write path")


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    return tmp_path / "state"


def _receipt(state, lane):
    return json.loads((state / "data" / "runtime" / f"{lane}_last.json").read_text())


def _dry_line(text):
    line = next(ln for ln in text.splitlines() if ln.startswith("DRY-RUN "))
    return json.loads(line[len("DRY-RUN ") :])


# ── strategy_backtester ──────────────────────────────────────────────────────────────────────────────
def _bt_env(monkeypatch, n_signals=3):
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    sigs = [(f"S{i}", 10.0 + i, t0, 70, "scan", 1.0, 3.0) for i in range(n_signals)]

    def responder(sql, params):
        if sql.startswith("SELECT symbol, price, scanned_at"):
            return {"all": sigs}
        return None

    conn = FakeConn(responder)
    monkeypatch.setattr(sbt, "_get_conn", lambda: conn)
    monkeypatch.setitem(
        sys.modules,
        "strategy_rule_adapter",
        types.SimpleNamespace(load_strategy_configs=lambda: {"momentum_scalp": {}}),
    )
    return conn


@pytest.mark.parametrize(
    "argv", [["--all-strategies", "--apply", "--dry-run", "--json"], ["--all-strategies", "--json"]]
)
def test_backtester_dry_run_writes_nothing(monkeypatch, capsys, argv):
    conn = _bt_env(monkeypatch)
    monkeypatch.setattr(llr, "write_lane_receipt", _boom)
    monkeypatch.setattr(sys, "argv", ["x", *argv])
    assert sbt.main() == 0
    assert conn.readonly is True and conn.writes() == [] and conn.commits == 0
    cap = capsys.readouterr()
    assert json.loads(cap.out)["mode"] == "dry_run"
    assert _dry_line(cap.err)["summary"]["trades"] == 3


def test_backtester_apply_inserts_and_writes_receipt(monkeypatch, _state):
    conn = _bt_env(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["x", "--all-strategies", "--apply"])
    assert sbt.main() == 0
    assert any(s.startswith("INSERT INTO strategy_backtest_runs") for s in conn.writes())
    rec = _receipt(_state, "strategy-backtester")
    assert rec["status"] == "ok" and rec["summary"]["low_sample_warning"] is True  # a finding, still ok
    assert rec["summary"]["trades"] == 3


def test_backtester_crash_leaves_failed_receipt(monkeypatch, _state):
    conn = _bt_env(monkeypatch)
    conn.fail_on = "INSERT INTO strategy_backtest_runs"
    monkeypatch.setattr(sys, "argv", ["x", "--all-strategies", "--apply"])
    with pytest.raises(RuntimeError):
        sbt.main()
    assert _receipt(_state, "strategy-backtester")["status"] == "failed"


# ── proposal_backtest_engine ─────────────────────────────────────────────────────────────────────────
_PROP_COLS = [
    "id",
    "symbol",
    "strategy_id",
    "setup_type",
    "rvol",
    "float_m",
    "gap_pct",
    "catalyst",
    "catalyst_verified",
    "catalyst_confidence",
    "critic_verdict",
    "sector",
]


def _pbe_env(monkeypatch, ids=(7,), fail_on=None):
    def responder(sql, params):
        if sql.startswith("SELECT id FROM paper_trade_proposals"):
            return {"all": [(i,) for i in ids]}
        if sql.startswith("SELECT id, symbol, strategy_id"):
            pid = params[0]
            if pid == 404:
                return {"description": [(c,) for c in _PROP_COLS], "one": None}
            return {
                "description": [(c,) for c in _PROP_COLS],
                "one": (pid, "AAA", "swing", "breakout", 3.0, 20.0, 4.0, None, None, None, None, "tech"),
            }
        if sql.startswith("SELECT COUNT(*), COALESCE"):
            return {"one": (0, 0, 0, 0, 0, 0, 0)}
        if sql.startswith("SELECT COUNT(*)"):
            return {"one": (0,)}
        if sql.startswith("SELECT pnl, outcome_verdict"):
            return {"one": None}
        return None

    conn = FakeConn(responder, fail_on=fail_on)
    monkeypatch.setattr(pbe, "get_conn", lambda: conn)
    return conn


@pytest.mark.parametrize("argv", [["--all-pending", "--apply", "--dry-run"], ["--proposal-id", "7", "--dry-run"]])
def test_proposal_backtest_dry_run_writes_nothing(monkeypatch, capsys, argv):
    conn = _pbe_env(monkeypatch)
    monkeypatch.setattr(pbe, "_write_strategy_backtest_result", _boom)
    monkeypatch.setattr(llr, "write_lane_receipt", _boom)
    assert pbe.main(argv) == 0
    assert conn.readonly is True and conn.writes() == [] and conn.commits == 0
    cap = capsys.readouterr()
    assert json.loads(cap.out)  # stdout stays JSON
    assert _dry_line(cap.err)["lane_id"] == "proposal-backtest-engine"


def test_proposal_backtest_dry_return_precedes_the_upsert_in_source():
    src = inspect.getsource(pbe.backtest_proposal)
    assert src.index("if not persist:") < src.index("INSERT INTO proposal_backtest_snapshots")


def test_proposal_backtest_live_run_unchanged_and_receipt(monkeypatch, _state):
    conn = _pbe_env(monkeypatch, ids=(7, 8))
    assert pbe.main(["--all-pending", "--apply"]) == 0
    w = conn.writes()
    assert sum(s.startswith("INSERT INTO proposal_backtest_snapshots") for s in w) == 2
    assert sum(s.startswith("UPDATE paper_trade_proposals") for s in w) == 2
    assert sum(s.startswith("INSERT INTO strategy_backtest_results") for s in w) == 2
    rec = _receipt(_state, "proposal-backtest-engine")
    assert rec["status"] == "ok" and rec["summary"] == {"processed": 2, "load_errors": 0, "persist_failures": 0}


def test_imported_backtest_proposal_still_persists_by_default(monkeypatch):
    conn = _pbe_env(monkeypatch)
    res = pbe.backtest_proposal(conn, 7)
    assert res["persisted"] is True and any(
        s.startswith("INSERT INTO proposal_backtest_snapshots") for s in conn.writes()
    )


def test_proposal_backtest_persist_failure_exits_1(monkeypatch, _state):
    _pbe_env(monkeypatch, ids=(7, 404), fail_on="INSERT INTO proposal_backtest_snapshots")
    assert pbe.main(["--all-pending", "--apply"]) == 1
    rec = _receipt(_state, "proposal-backtest-engine")
    assert rec["status"] == "failed" and rec["summary"]["persist_failures"] == 1
    assert rec["summary"]["load_errors"] == 1


# ── one sample per row + min-n gate (audit 2026-11-07, AMWL #12438 / KRO #12432) ─────────────────────
# The live table showed win_rate 1.0 beside profit_factor 2.63 under one sample_size 16: the 1.0 was
# 3 of 3 similar setups while the 2.63 came from all 16 strategy trades, and a 2-trade sample printed
# expectancy 241.4. Every metric a row reports must come from the sample its sample_size names, and a
# sample below MIN_METRIC_SAMPLE reports no risk metrics at all.

_STRATEGY_SAMPLE_16 = (16, 10, 6, 614.80, 233.44, 23.845, 0.97)  # trades, wins, losses, gains, losses, avg pnl, avg r
_STRATEGY_SAMPLE_2 = (2, 2, 0, 482.80, 0.0, 241.40, 2.03)
_SIMILAR_3_ALL_WINS = [(10.0, 1.0), (10.0, 1.0), (10.0, 1.0)]


def _pbe_sample_env(monkeypatch, strategy_row, similar_rows, ids=(7,)):
    def responder(sql, params):
        if sql.startswith("SELECT id FROM paper_trade_proposals"):
            return {"all": [(i,) for i in ids]}
        if sql.startswith("SELECT id, symbol, strategy_id"):
            return {
                "description": [(c,) for c in _PROP_COLS],
                "one": (params[0], "AMWL", "swing_breakout", "breakout", 3.0, 20.0, 4.0, None, None, None, None, "tech"),
            }
        if sql.startswith("SELECT COUNT(*), COALESCE") and "FROM paper_trades WHERE strategy_id" in sql:
            return {"one": strategy_row}
        if sql.startswith("SELECT COUNT(*), COALESCE"):
            return {"one": (0, 0, 0)}
        if sql.startswith("SELECT COUNT(*)"):
            return {"one": (0,)}
        if sql.startswith("SELECT pnl, outcome_verdict"):
            return {"one": None}
        if sql.startswith("SELECT pt.pnl, pt.r_multiple"):
            return {"all": list(similar_rows)}
        return None

    conn = FakeConn(responder)
    monkeypatch.setattr(pbe, "get_conn", lambda: conn)
    return conn


def _row_params(conn):
    for sql, params in zip(conn.sql, conn.params):
        if sql.startswith("INSERT INTO proposal_backtest_snapshots"):
            return params
    raise AssertionError("no proposal_backtest_snapshots insert")


def test_metrics_all_come_from_the_sample_the_row_reports(monkeypatch):
    """The similar-setup match (3 of 3) must not supply win_rate while the 16 strategy trades supply PF."""
    conn = _pbe_sample_env(monkeypatch, _STRATEGY_SAMPLE_16, _SIMILAR_3_ALL_WINS)
    res = pbe.backtest_proposal(conn, 7)

    assert res["metrics_sample"] == "strategy" and res["metrics_sample_size"] == 16
    assert res["sample_size"] == 16, "sample_size must be the n the metrics were computed on"
    assert res["win_rate"] == 0.625, "10 of 16 strategy trades — not 3 of 3 similar setups"
    assert res["profit_factor"] == 2.63 and res["expectancy"] == 23.84 and res["avg_r"] == 0.97
    assert res["metrics_suppressed"] is False
    # 3 similar matches are real evidence of a count and a PnL sum, not of a win rate
    assert "3 similar setups" in res["similar_setup_summary"]
    assert not re.search(r"win rate \d", res["similar_setup_summary"]), "no rate on 3 matches"
    assert "withheld" in res["similar_setup_summary"]


def test_persisted_snapshot_row_is_internally_consistent(monkeypatch):
    conn = _pbe_sample_env(monkeypatch, _STRATEGY_SAMPLE_16, _SIMILAR_3_ALL_WINS)
    assert pbe.backtest_proposal(conn, 7)["persisted"] is True
    p = _row_params(conn)  # pid, symbol, strategy, setup, sample_size, symbol_n, strategy_n, pattern_n, wr, pf, exp, r
    assert p[4] == 16 and p[8] == 0.625 and p[9] == 2.63 and p[10] == 23.84


def test_metrics_suppressed_below_the_minimum_sample(monkeypatch):
    """KRO #12432 printed win_rate 1.0 and expectancy 241.4 on two trades."""
    conn = _pbe_sample_env(monkeypatch, _STRATEGY_SAMPLE_2, [])
    res = pbe.backtest_proposal(conn, 7)

    assert res["metrics_suppressed"] is True and res["metrics_sample_size"] == 2
    assert res["sample_size"] == 2
    assert res["win_rate"] is None and res["profit_factor"] is None
    assert res["expectancy"] is None and res["avg_r"] is None
    assert res["strategy_history"]["win_rate"] is None
    assert any("withheld" in line and "10" in line for line in res["limitations"]), res["limitations"]
    assert res["backtest_quality"] == "INSUFFICIENT"


def test_minimum_sample_boundary_is_inclusive(monkeypatch):
    """10 trades exactly is the first sample that may report metrics."""
    ten = (10, 6, 4, 300.0, 120.0, 18.0, 0.5)
    res = pbe.backtest_proposal(_pbe_sample_env(monkeypatch, ten, []), 7)
    assert res["metrics_suppressed"] is False and res["sample_size"] == 10
    assert res["win_rate"] == 0.6 and res["profit_factor"] == 2.5 and res["expectancy"] == 18.0


# ── agent_outcome_linker ─────────────────────────────────────────────────────────────────────────────
def _aol_env(monkeypatch, n_props=2, n_trades=1):
    t = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def responder(sql, params):
        if "JOIN paper_trade_proposals" in sql:
            return {"all": [(f"R{i}", "AAA", t, "maria", i, "swing", t) for i in range(n_props)]}
        if "JOIN paper_trades" in sql:
            return {"all": [(f"T{i}", "BBB", t, "steph", i, "swing", t, "closed", 1, 0.5) for i in range(n_trades)]}
        return None

    conn = FakeConn(responder)
    monkeypatch.setattr(aol, "_get_conn", lambda: conn)
    return conn


def test_linker_dry_run_wins_over_apply(monkeypatch, capsys):
    conn = _aol_env(monkeypatch)
    monkeypatch.setattr(aol, "save_links", _boom)
    monkeypatch.setattr(llr, "write_lane_receipt", _boom)
    monkeypatch.setattr(sys, "argv", ["x", "--apply", "--dry-run", "--json"])
    assert aol.main() == 0
    assert conn.readonly is True and conn.writes() == []
    cap = capsys.readouterr()
    out = json.loads(cap.out)
    assert out["mode"] == "dry_run" and out["would_insert"] == 3 and out["inserted"] == 0
    assert _dry_line(cap.err)["summary"]["total_links"] == 3


def test_linker_reports_cap_hit(monkeypatch, capsys):
    monkeypatch.setattr(aol, "PROPOSAL_LINK_LIMIT", 2)
    _aol_env(monkeypatch, n_props=2)
    monkeypatch.setattr(sys, "argv", ["x", "--dry-run", "--json"])
    aol.main()
    out = json.loads(capsys.readouterr().out)
    assert out["proposal_cap_hit"] is True and out["trade_cap_hit"] is False


def test_linker_apply_inserts_and_writes_receipt(monkeypatch, _state):
    conn = _aol_env(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["x", "--apply"])
    assert aol.main() == 0
    assert len([s for s in conn.writes() if s.startswith("INSERT INTO agent_recommendation_outcome_links")]) == 3
    rec = _receipt(_state, "agent-outcome-linker")
    assert rec["status"] == "ok" and rec["summary"]["inserted"] == 3


def test_proposal_backtest_dry_run_survives_an_aborted_optional_query(monkeypatch, capsys):
    """Real-env finding 2026-10-10: pattern_library has no pattern_description column, so that optional query
    fails and leaves the transaction aborted. The live path rolls back before its upsert; the dry branch must
    end the read transaction too, or the next proposal's SELECT fails with InFailedSqlTransaction."""
    conn = _pbe_env(monkeypatch, ids=(7, 8))
    rollbacks = []
    monkeypatch.setattr(conn, "rollback", lambda: rollbacks.append(1))
    assert pbe.main(["--all-pending", "--dry-run"]) == 0
    assert len(rollbacks) >= 3  # enforce_readonly + one per dry-run proposal
    assert json.loads(capsys.readouterr().out)["processed"] == 2
