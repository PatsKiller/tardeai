"""Refactor wave 2 (cron -> n8n, 2026-10-10): signal_fusion.py (cron:L409 --full, cron:L411 --active).

- --dry-run computes every fused score on a READ ONLY session (compute_fused: SELECTs only) and returns
  before _persist (the two INSERTs) or commit is reachable; no receipt; the report tracks the data.
- The connection comes from db_adapter, never an inline parse of PROJECT_ROOT/.env.
- A real --full/--active run writes signal_fusion_{full,active}_last.json (ok_at only on success) and
  exits 1 when the per-symbol error rate is above ERROR_RATE_FAIL.
Hermetic: fake connection, TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import signal_fusion as sf  # noqa: E402
from lib import lane_last_receipt as llr  # noqa: E402


class FakeConn:
    """Answers statements by substring (first match wins); records everything."""

    def __init__(self, answers, fail_on=None):
        self.answers = answers
        self.fail_on = fail_on  # (substring, symbol) -> raise
        self.log: list = []
        self.closed = 0

    def cursor(self, *a, **k):
        conn = self

        class C:
            def execute(self, sql, params=None):
                flat = " ".join(sql.split())
                conn.log.append(("execute", flat, params))
                if conn.fail_on and conn.fail_on[0] in flat and params and conn.fail_on[1] in params:
                    raise RuntimeError("boom")
                self._rows = next((rows for sub, rows in conn.answers if sub in flat), [])

            def fetchall(self):
                return list(self._rows)

            def fetchone(self):
                return self._rows[0] if self._rows else None

        return C()

    def commit(self):
        self.log.append(("commit",))

    def rollback(self):
        self.log.append(("rollback",))

    def set_session(self, **kw):
        self.log.append(("set_session", kw))

    def close(self):
        self.log.append(("close",))

    def writes(self):
        return [e[1] for e in self.log if e[0] == "execute" and e[1].lstrip().upper().startswith("INSERT")]


def _answers(critical=True):
    cat = [
        {
            "catalyst_type": "earnings",
            "confidence": 0.9,
            "impact_score": 0.9,
            "severity": "critical" if critical else "low",
        }
    ]
    return [
        ("SELECT symbol FROM ticker_strategy_classifications", [{"symbol": "AAA"}, {"symbol": "BBB"}]),
        ("SELECT DISTINCT symbol FROM (", [{"symbol": "AAA"}]),
        ("SELECT strategy_type FROM ticker_strategy_classifications", [{"strategy_type": "swing_trade"}]),
        ("FROM catalyst_events", cat),
    ]


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    conn = FakeConn(_answers())
    monkeypatch.setattr(sf, "_get_conn", lambda: conn)
    monkeypatch.setattr(sf, "_dict_cursor", lambda c: c.cursor())
    return conn


def _forbid(monkeypatch, obj, name):
    def boom(*a, **k):
        raise AssertionError(f"dry run reached {name}")

    monkeypatch.setattr(obj, name, boom)


@pytest.mark.parametrize("mode", ["--full", "--active"])
def test_dry_run_reaches_no_write(env, monkeypatch, capsys, tmp_path, mode):
    _forbid(monkeypatch, sf, "_persist")
    _forbid(monkeypatch, llr, "write_receipt")
    assert sf.main([mode, "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    n = 2 if mode == "--full" else 1
    assert out["mode"] == "dry_run" and out["computed"] == n and out["errors"] == 0
    assert out["would_write"] == {"fused_signals": n, "portfolio_intelligence_events": n}
    assert env.writes() == [] and ("commit",) not in env.log
    assert ("set_session", {"readonly": True}) in env.log
    assert not (tmp_path / "state").exists()


def test_dry_run_report_tracks_state(env, capsys):
    sf.main(["--full", "--dry-run"])
    before = json.loads(capsys.readouterr().out)["would_write"]["portfolio_intelligence_events"]
    env.answers[3] = ("FROM catalyst_events", [])  # no catalysts -> nothing high/critical
    sf.main(["--full", "--dry-run"])
    after = json.loads(capsys.readouterr().out)["would_write"]["portfolio_intelligence_events"]
    assert (before, after) == (2, 0)


def test_symbol_dry_run_reaches_no_write(env, monkeypatch, capsys):
    _forbid(monkeypatch, sf, "_persist")
    assert sf.main(["--symbol", "aaa", "--dry-run"]) == 0
    assert "not written" in capsys.readouterr().out
    assert env.writes() == [] and ("set_session", {"readonly": True}) in env.log


def test_source_order_compute_is_select_only_and_dry_returns_before_persist():
    compute = inspect.getsource(sf.compute_fused)
    assert "INSERT" not in compute and "commit" not in compute
    src = inspect.getsource(sf.fuse_signals)
    assert src.index("if dry_run:\n            conn.rollback()\n            return result") < src.index("_persist(cur")
    persist = inspect.getsource(sf._persist)
    assert persist.count("INSERT INTO") == 2


def test_no_inline_password_parse():
    src = inspect.getsource(sf._get_conn)
    assert "read_text" not in src and "psycopg2.connect" not in src and "from db_adapter import _get_conn" in src


def test_real_full_run_writes_rows_and_receipt(env):
    assert sf.main(["--full"]) == 0
    assert len([w for w in env.writes() if "INTO fused_signals" in w]) == 2
    assert len([w for w in env.writes() if "INTO portfolio_intelligence_events" in w]) == 2
    assert env.log.count(("commit",)) == 2  # one commit per symbol, as before
    rc = json.loads(llr.receipt_path("signal_fusion_full").read_text())
    assert rc["status"] == "ok" and rc["ok_at"] and rc["summary"]["fused"] == 2


def test_real_active_run_writes_its_own_receipt(env):
    assert sf.main(["--active"]) == 0
    assert llr.receipt_path("signal_fusion_active").exists()
    assert not llr.receipt_path("signal_fusion_full").exists()


def test_real_run_with_symbol_errors_exits_1_and_keeps_ok_at_stale(env, capsys):
    env.fail_on = ("FROM catalyst_events", "BBB")
    assert sf.main(["--full"]) == 1  # 1/2 failed > ERROR_RATE_FAIL
    rc = json.loads(llr.receipt_path("signal_fusion_full").read_text())
    assert rc["status"] == "failed" and rc["ok_at"] is None and rc["summary"]["errors"] == 1
    assert ("rollback",) in env.log


def test_empty_set_is_a_finding_not_a_failure(env):
    env.answers[0] = ("SELECT symbol FROM ticker_strategy_classifications", [])
    assert sf.main(["--full"]) == 0
    assert json.loads(llr.receipt_path("signal_fusion_full").read_text())["status"] == "ok"


def test_symbol_query_failure_exits_nonzero_with_failed_receipt(env, monkeypatch):
    def broken():
        raise RuntimeError("password authentication failed")

    monkeypatch.setattr(sf, "_get_conn", broken)
    with pytest.raises(RuntimeError):
        sf.main(["--active"])
    rc = json.loads(llr.receipt_path("signal_fusion_active").read_text())
    assert rc["status"] == "failed" and rc["error"] == "RuntimeError"  # helper scrubs the message
