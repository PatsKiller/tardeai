"""Refactor wave 2 (cron -> n8n, 2026-10-10), bucket V3 -- proposal-pipeline lanes.

- run_afterhours_candidate_preparation.{sh,py} (cron:L196): served-tree PROJ + venv resolution, the
  python step's exit propagated through the log pipe, --dry-run (wins over --apply) that reaches no
  INSERT, no --output-* file, no log append, no telemetry row, no receipt; real run writes
  run-afterhours-candidate-preparation_last.json.
- multi_tier_trade_reviewer.py (cron:L401): --dry-run never calls a model or writes (READ ONLY session);
  a refused/empty model review is now exit 1 with a failed receipt (the lane exited 0 while reviewing
  nothing, 4/4 runs); success writes multi-tier-trade-reviewer-<tier>_last.json.
Hermetic: fake DB connections, fake python child, TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "CREATE", "ALTER", "DROP")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"w2v3_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeConn:
    """Tuple rows + cursor.description (the shape these scripts read); records every statement."""

    def __init__(self, responder=None, fail_on=None):
        self.responder = responder or (lambda sql, params: [])
        self.fail_on = fail_on
        self.sql: list[str] = []
        self.calls: list = []

    def cursor(self, *a, **k):
        conn = self

        class C:
            description = None

            def execute(self, sql, params=None):
                flat = " ".join(str(sql).split())
                conn.sql.append(flat)
                if conn.fail_on and flat.upper().startswith(conn.fail_on):
                    raise RuntimeError("simulated write failure")
                self._rows = list(conn.responder(flat, params) or [])
                self.description = [(k,) for k in self._rows[0]] if self._rows else [("x",)]

            def fetchall(self):
                return [tuple(r.values()) for r in self._rows]

            def fetchone(self):
                return tuple(self._rows[0].values()) if self._rows else None

        return C()

    def writes(self):
        return [s for s in self.sql if s.upper().startswith(WRITE_PREFIXES)]

    def commit(self):
        self.calls.append("commit")

    def rollback(self):
        self.calls.append("rollback")

    def set_session(self, **kw):
        self.calls.append(("set_session", kw))

    def close(self):
        self.calls.append("close")


def _receipt(tmp_path, name):
    p = tmp_path / "data" / "runtime" / f"{name}_last.json"
    return json.loads(p.read_text()) if p.exists() else None


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    return tmp_path / "state"


# ── run_afterhours_candidate_preparation.py (cron:L196) ───────────────────────


def _ah_rows(sql, params):
    if "FROM screener_symbol_membership" in sql:
        return [{"symbol": "AAA"}]
    if "FROM universe_strategy_fit_audit" in sql:
        return [
            {
                "audit_run_id": "A",
                "strategy_id": "swing",
                "match_strength": "STRONG",
                "normalized_score": 80,
                "recommendation": "r",
                "missing_fields": "",
                "family_gate_status": "PASS",
                "liquidity_gate_status": "PASS",
            }
        ]
    return []  # trade_ai_scans: quote missing


@pytest.fixture
def ah(monkeypatch):
    mod = _load("run_afterhours_candidate_preparation")

    def install(conn):
        monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn))
        return mod

    return install


def test_afterhours_dry_run_wins_over_apply_and_writes_nothing(ah, state, tmp_path):
    conn = FakeConn(_ah_rows)
    mod = ah(conn)
    out_json = tmp_path / "o.json"
    assert mod.main(["--apply", "--dry-run", "--output-json", str(out_json)]) == 0
    assert conn.writes() == [] and "commit" not in conn.calls
    assert ("set_session", {"readonly": True}) in conn.calls
    assert not out_json.exists()
    assert _receipt(state, "run-afterhours-candidate-preparation") is None


def test_afterhours_apply_writes_rows_and_receipt(ah, state, capsys):
    conn = FakeConn(_ah_rows)
    mod = ah(conn)
    assert mod.main(["--apply", "--session", "after_close"]) == 0
    w = conn.writes()
    assert w[0].startswith("INSERT INTO afterhours_candidate_snapshot")
    assert w[1].startswith("INSERT INTO afterhours_readiness_run")
    rec = _receipt(state, "run-afterhours-candidate-preparation")
    assert rec["status"] == "ok" and rec["summary"]["candidates_written"] == 1
    assert "wrote 1 candidate rows" in capsys.readouterr().out


def test_afterhours_failed_insert_is_failed_receipt(ah, state):
    conn = FakeConn(_ah_rows, fail_on="INSERT")
    mod = ah(conn)
    with pytest.raises(RuntimeError):
        mod.main(["--apply"])
    assert _receipt(state, "run-afterhours-candidate-preparation")["status"] == "failed"


# ── run_afterhours_candidate_preparation.sh ───────────────────────────────────


@pytest.fixture
def fake_proj(tmp_path):
    """A served-tree stand-in: the real wrapper, a fake python step, an .env, a weekday `date`."""
    proj = tmp_path / "release"
    (proj / "scripts").mkdir(parents=True)
    (proj / "logs").mkdir()
    shutil.copy(SCRIPTS / "run_afterhours_candidate_preparation.sh", proj / "scripts")
    (proj / ".env").write_text("ALPACA_MODE=paper\nLLM_DISABLE_LIVE_EXECUTION=true\n")
    (proj / "scripts" / "run_afterhours_candidate_preparation.py").write_text(
        "import os, sys\n"
        "open(os.environ['ARGV_OUT'], 'w').write(' '.join(sys.argv[1:]))\n"
        "print('step ran')\n"
        "sys.exit(int(os.environ.get('STEP_EXIT', '0')))\n"
    )
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "date").write_text('#!/bin/sh\n[ "$1" = "+%u" ] && { echo 3; exit 0; }\nexec /bin/date "$@"\n')
    (bindir / "date").chmod(0o755)
    return proj, bindir


def _run_wrapper(proj, bindir, tmp_path, *args, step_exit=0):
    env = dict(
        os.environ,
        PATH=f"{bindir}:{os.environ['PATH']}",
        TRADEAI_VENV_PYTHON=sys.executable,
        ARGV_OUT=str(tmp_path / "argv.txt"),
        STEP_EXIT=str(step_exit),
    )
    return subprocess.run(
        ["bash", str(proj / "scripts" / "run_afterhours_candidate_preparation.sh"), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_wrapper_dry_run_passes_dry_run_and_appends_no_log(fake_proj, tmp_path):
    proj, bindir = fake_proj
    r = _run_wrapper(proj, bindir, tmp_path, "--dry-run")
    assert r.returncode == 0, r.stderr
    argv = (tmp_path / "argv.txt").read_text()
    assert "--dry-run" in argv and "--apply" not in argv
    assert not (proj / "logs" / "afterhours_candidate_preparation.log").exists()
    assert "[dry-run]" in r.stdout


def test_wrapper_real_run_uses_served_tree_and_propagates_exit(fake_proj, tmp_path):
    proj, bindir = fake_proj
    r = _run_wrapper(proj, bindir, tmp_path, step_exit=3)
    assert r.returncode == 3  # was always 0 (`$?` of the `| while read` pipe)
    assert "--apply" in (tmp_path / "argv.txt").read_text()
    log = (proj / "logs" / "afterhours_candidate_preparation.log").read_text()
    assert "step ran" in log and "Finished (exit=3)" in log


def test_wrapper_has_no_dev_tree_proj():
    src = (SCRIPTS / "run_afterhours_candidate_preparation.sh").read_text()
    # no hard-coded checkout path at all: PROJ is derived from the script's own location (the served tree)
    assert 'PROJ="/home/' not in src
    assert 'PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in src
    assert "PIPESTATUS[0]" in src


# ── multi_tier_trade_reviewer.py (cron:L401) ──────────────────────────────────


def _rv_rows(sql, params):
    if "FROM paper_trades" in sql:
        return [
            {
                "id": 1,
                "symbol": "AAA",
                "strategy_id": "swing",
                "entry_price": 10,
                "exit_price": 11,
                "stop_loss": 9,
                "target_1": 12,
                "pnl": 1,
                "r_multiple": None,
            }
        ]
    return []


@pytest.fixture
def rv(monkeypatch):
    cwd = os.getcwd()
    mod = _load("multi_tier_trade_reviewer")  # chdirs to the repo root at import
    os.chdir(cwd)
    conn = FakeConn(_rv_rows)
    monkeypatch.setattr(mod, "_get_conn", lambda: conn)
    return mod, conn


def test_reviewer_dry_run_never_calls_a_model_or_writes(rv, state):
    mod, conn = rv
    gen = mock.Mock(side_effect=AssertionError("model call in dry run"))
    with mock.patch.object(mod, "_generate", gen), mock.patch.object(mod, "_save_review", gen):
        assert mod.main(["--tier", "overnight", "--dry-run"]) == 0
    assert not gen.called and conn.writes() == []
    assert ("set_session", {"readonly": True}) in conn.calls
    assert _receipt(state, "multi-tier-trade-reviewer-overnight") is None


def test_reviewer_refused_model_is_exit_1_and_failed_receipt(rv, state):
    mod, _ = rv
    with mock.patch.object(mod, "_generate", return_value=None):
        assert mod.main(["--tier", "overnight"]) == 1
    rec = _receipt(state, "multi-tier-trade-reviewer-overnight")
    assert rec["status"] == "failed" and rec["ok_at"] is None and rec["summary"]["failed"] == 1


def test_reviewer_success_writes_ok_receipt(rv, state):
    mod, _ = rv
    save = mock.Mock()
    with (
        mock.patch.object(mod, "_generate", return_value='{"summary": "fine"}'),
        mock.patch.object(mod, "_save_review", save),
    ):
        assert mod.main(["--tier", "overnight"]) == 0
    assert save.called
    rec = _receipt(state, "multi-tier-trade-reviewer-overnight")
    assert rec["status"] == "ok" and rec["summary"]["succeeded"] == 1


def test_reviewer_no_trades_is_clean_and_realtime_without_id_is_usage_error(rv, state):
    mod, conn = rv
    conn.responder = lambda sql, params: []
    assert mod.main(["--tier", "overnight"]) == 0
    assert _receipt(state, "multi-tier-trade-reviewer-overnight")["status"] == "ok"
    assert mod.run_outcome({"error": "trade_id required"}) == (False, 2)
