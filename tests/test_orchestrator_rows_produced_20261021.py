"""trade_ai_orchestrator must report a true rows_produced (2026-10-21 alert).

Alert: "Pipeline produced NOTHING while reporting success: trade_ai_orchestrator -- 27 runs
with rows_produced=0 in 24h". Measured read-only the same morning:

  * 235 cron success rows in 7 days, every one with summary {"rows_produced": null}: the
    orchestrator never called PipelineRun.rows().
  * 27 rows in 24h with rows_produced=0 -- all trigger_source='health_agent_remediate',
    run_label='health_recovery': synthetic bookkeeping rows inserted by
    remediate_pipeline_failures.close_unrecovered_orchestrator.
  * Meanwhile trade_ai_scans got 0400/0700 rows today and strategy_signals 15 rows in 24h.

So the pipeline was producing; the only explicit counts under its key were fabricated
zeros, and no run had ever reported > 0, which is exactly the alarm's condition.

Fixed: db_persist records the number of trade_ai_scans rows actually committed and the
__main__ block hands it to PipelineRun.rows(); the synthetic recovery row writes null.
Hermetic: no DB, no network, no live paths.
"""
from __future__ import annotations

import ast
import importlib
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "scripts", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
if "dotenv" not in sys.modules:
    _d = types.ModuleType("dotenv")
    _d.load_dotenv = lambda *_a, **_k: False  # type: ignore[attr-defined]
    sys.modules["dotenv"] = _d

tao = importlib.import_module("trade_ai_orchestrator")
ORCH_SRC = (ROOT / "scripts" / "trade_ai_orchestrator.py").read_text()


class _RecordingRun:
    instances: list = []

    def __init__(self, *a, **k):
        self.rows_reported = None
        self.exit = None
        _RecordingRun.instances.append(self)

    def __enter__(self):
        return self

    def rows(self, n):
        self.rows_reported = n

    def __exit__(self, exc_type, exc, tb):
        self.exit = (exc_type, getattr(exc, "code", None))
        return False


def _main_block() -> ast.Module:
    tree = ast.parse(ORCH_SRC)
    for node in tree.body:
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and getattr(node.test.left, "id", "") == "__name__"):
            return ast.Module(body=node.body, type_ignores=[])
    raise AssertionError("no __main__ block in trade_ai_orchestrator.py")


def _exec_main(fake_main):
    _RecordingRun.instances.clear()
    ns = dict(vars(tao))
    ns["PipelineRun"] = _RecordingRun
    ns["main"] = fake_main
    with pytest.raises(SystemExit) as ei:
        exec(compile(_main_block(), "trade_ai_orchestrator.__main__", "exec"), ns)
    return ei.value.code, _RecordingRun.instances[-1]


def test_successful_run_reports_measured_rows_to_pipeline_run():
    def fake_main():
        tao._RUN_METRICS["rows_produced"] = 42  # what db_persist records
        return 0

    code, run = _exec_main(fake_main)
    assert code == 0
    assert run.rows_reported == 42


def test_unmeasured_run_reports_nothing_not_zero():
    def fake_main():
        tao._RUN_METRICS["rows_produced"] = None
        return 0

    code, run = _exec_main(fake_main)
    assert code == 0
    assert run.rows_reported is None


def test_market_closed_run_clears_a_stale_count(capsys):
    tao._RUN_METRICS["rows_produced"] = 99  # left over from an earlier in-process run
    # 2026-10-18 is a Sunday: run_pipeline returns before any stage.
    assert tao.run_pipeline(Path("/nonexistent-root"), "0900", "2026-10-18") == 0
    assert tao._RUN_METRICS["rows_produced"] is None


def test_db_persist_counts_only_committed_rows():
    i = ORCH_SRC.index('_ok("db_persist"')
    stage = ORCH_SRC[ORCH_SRC.index("# 18b. Persist to trade_ai_scans DB"):i]
    assert "_wrote = _execute(" in stage
    assert "if _wrote:\n                _inserted += 1" in stage
    assert '_RUN_METRICS["rows_produced"] = _inserted' in stage


def test_recovery_bookkeeping_row_does_not_claim_zero_rows(monkeypatch):
    rp = importlib.import_module("remediate_pipeline_failures")
    captured = {}

    class _Cur:
        def execute(self, sql, params=None):
            if "INSERT INTO pipeline_runs" in sql:
                captured["summary"] = json.loads(params[1])

        def fetchall(self):
            return []

        def fetchone(self):
            return (1,)

        def close(self):
            pass

    class _Conn:
        def cursor(self):
            return _Cur()

        def commit(self):
            pass

    monkeypatch.setattr(rp, "_conn", lambda: _Conn())
    out = rp.close_unrecovered_orchestrator()
    assert out["ok"] is True
    assert captured["summary"]["recovery"] is True
    assert captured["summary"]["rows_produced"] is None
