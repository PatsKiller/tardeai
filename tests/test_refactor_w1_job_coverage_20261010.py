"""n8n refactor wave 1 (W2), 2026-10-10 — job_coverage_monitor.py (cron:L389).

The monitor is read-only; its one write is the ScheduledJobReceipt@v1 receipt. ``--dry-run`` evaluates
exactly as a real run and never enters the receipt wrapper. Exit is honest: 0 when the monitor ran (STALE
and NOT_SCHEDULED are findings), 2 when ``crontab -l`` is unreadable (the instrument is blind). The old
FAIL-count exit stays behind ``--exit-fail-count``. The shared receipt helper gains ``ok_at``.
"""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import job_coverage_monitor as jcm  # noqa: E402
from lib import scheduled_job_receipt as sjr  # noqa: E402

COVERS = ["scripts/job_coverage_monitor.py", "scripts/lib/scheduled_job_receipt.py"]

ROWS = [
    {"job": "a", "status": "OK", "detail": "", "age_hours": 1, "cadence_hours": 2, "idle_hours": 0, "scheduled": True},
    {
        "job": "b",
        "status": "STALE",
        "detail": "",
        "age_hours": 9,
        "cadence_hours": 2,
        "idle_hours": 0,
        "scheduled": True,
    },
]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    state = {"rows": list(ROWS), "blind": None}

    def fake_eval():
        jcm.CRONTAB_ERROR = state["blind"]
        return list(state["rows"])

    monkeypatch.setattr(jcm, "evaluate", fake_eval)
    return {"root": tmp_path, "state": state, "receipt": tmp_path / "data/runtime/job_coverage_monitor_last.json"}


def _cli(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["job_coverage_monitor.py", *argv])
    return jcm.cli()


def test_dry_run_never_enters_the_receipt_wrapper(env, monkeypatch, capsys):
    monkeypatch.setattr(sjr, "run_with_receipt", lambda *a, **k: pytest.fail("receipt wrapper reached"))
    monkeypatch.setattr(sjr, "atomic_write_json", lambda *a, **k: pytest.fail("write reached"))
    assert _cli(monkeypatch, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "1 FAIL (1/2 OK)" in out and "receipt not written" in out
    assert not env["receipt"].exists() and not any(env["root"].rglob("*"))


def test_dry_run_mutation_tested_report_follows_the_evaluation(env, monkeypatch, capsys):
    _cli(monkeypatch, "--dry-run", "--json")
    first = json.loads(capsys.readouterr().out.split("(dry run")[0])
    env["state"]["rows"] = [dict(r, status="OK") for r in ROWS]
    _cli(monkeypatch, "--dry-run", "--json")
    second = json.loads(capsys.readouterr().out.split("(dry run")[0])
    assert first["summary"]["fail"] == 1 and second["summary"]["fail"] == 0


def test_source_order_dry_run_returns_before_the_wrapper():
    src = inspect.getsource(jcm.cli)
    assert src.index('if "--dry-run" in sys.argv:') < src.index("return code") < src.index("run_with_receipt")


def test_findings_are_not_failure_exit_0_with_receipt_ok_at(env, monkeypatch):
    assert _cli(monkeypatch) == 0
    rc = json.loads(env["receipt"].read_text())
    assert rc["schema"] == "ScheduledJobReceipt@v1" and rc["exit"] == 0 and rc["ok_at"] == rc["as_of"]


def test_blind_crontab_exits_2_and_carries_ok_at(env, monkeypatch):
    assert _cli(monkeypatch) == 0
    ok_at = json.loads(env["receipt"].read_text())["ok_at"]
    env["state"]["blind"] = "crontab -l exit 1: boom"
    assert _cli(monkeypatch) == 2
    rc = json.loads(env["receipt"].read_text())
    assert rc["exit"] == 2 and rc["summary"]["state"] == "failed" and rc["ok_at"] == ok_at


def test_exit_fail_count_keeps_the_old_contract(env, monkeypatch):
    assert _cli(monkeypatch, "--exit-fail-count") == 1


def test_crontab_lines_sets_blind_on_unreadable_crontab(monkeypatch):
    monkeypatch.setattr(
        jcm.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="", stderr="no crontab")
    )
    assert jcm._crontab_lines() == [] and "exit 1" in jcm.CRONTAB_ERROR
    monkeypatch.setattr(
        jcm.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="0 * * * * x.py\n# c\n", stderr=""),
    )
    assert jcm._crontab_lines() == ["0 * * * * x.py"] and jcm.CRONTAB_ERROR is None


def test_log_bases_include_the_persistent_logs_root(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path))
    (tmp_path / "logs").mkdir()
    bases = [str(b) for b in jcm._log_bases()]
    assert str(tmp_path / "logs") in bases and len(bases) == len(set(bases))


def test_proposed_allowlist_argv_is_dispatcher_eligible():
    from tests.test_agents_policy_4_1_0_amendment import dispatcher_eligible

    entry = {
        "lane_id": "job-coverage-monitor",
        "command": ["$PY", "scripts/job_coverage_monitor.py"],
        "dry_run_arg": ["--dry-run"],
        "live_arg": [],
    }
    assert dispatcher_eligible(entry) == (True, "ok")
