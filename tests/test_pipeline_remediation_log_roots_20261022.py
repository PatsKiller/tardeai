"""Pipeline remediation diagnostics must read CURRENT logs, not stale DEV logs."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace


def _module():
    return importlib.import_module("remediate_pipeline_failures")


def test_diagnostic_counters_read_live_logs_while_strategy_runs_from_dev(tmp_path, monkeypatch):
    rp = _module()
    dev = tmp_path / "dev"
    live = tmp_path / "live"
    (dev / "scripts").mkdir(parents=True)
    (live / "scripts").mkdir(parents=True)
    (dev / "logs").mkdir()
    (live / "logs").mkdir()
    monkeypatch.setattr(rp, "DEV_ROOT", dev)
    monkeypatch.setattr(rp, "get_live_project_root", lambda: live)

    # DEV has misleading/stale values; CURRENT has the production observations.
    (dev / "logs" / "watchlist_agent_jobs.log").write_text("CIRCUIT_OPEN\n" * 9)
    (live / "logs" / "watchlist_agent_jobs.log").write_text("CIRCUIT_OPEN\n" * 2)
    (dev / "logs" / "screener_pm.log").write_text("Rate limited\n" * 8)
    (live / "logs" / "screener_pm.log").write_text("Rate limited\nToo Many Requests\n")

    # The command strategy keeps using the approved DEV code + venv root.
    assert rp._root() == dev
    assert rp._diagnostic_log_root() == live
    assert rp._count_circuit_open_logs(hours=24 * 365) == 2
    assert rp._count_rate_limit_log_hits(hours=24 * 365) == 2


def test_run_cmd_uses_execution_root_not_diagnostic_root(tmp_path, monkeypatch):
    rp = _module()
    dev = tmp_path / "dev"
    live = tmp_path / "live"
    (dev / "scripts").mkdir(parents=True)
    live.mkdir()
    monkeypatch.setattr(rp, "DEV_ROOT", dev)
    monkeypatch.setattr(rp, "get_live_project_root", lambda: live)
    observed = {}

    def fake_run(*args, **kwargs):
        observed["cwd"] = kwargs["cwd"]
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(rp.subprocess, "run", fake_run)
    monkeypatch.setattr(rp, "_rewrite_cmd", lambda cmd: cmd)
    result = rp._run_cmd("approved-remediator --dry-run")

    assert result["ok"] is True
    assert observed["cwd"] == str(dev)
