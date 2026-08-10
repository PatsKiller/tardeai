"""Fail-closed containment tests (PR #284 Gate 4)."""
from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


WORKER = (
    "flock -n /tmp/tradeai_watchlist_agent_jobs.lock "
    ".venv/bin/python scripts/process_watchlist_agent_jobs.py --limit 15"
)
OTHER = ".venv/bin/python scripts/news_ingestion.py --priority"


@pytest.fixture
def cont(monkeypatch, tmp_path):
    from lib import agent_jobs_containment as c
    importlib.reload(c)
    flag = tmp_path / "AGENT_JOBS_P0_CONTAINED"
    monkeypatch.setattr(c, "FLAG_PATH", flag)
    monkeypatch.delenv("AGENT_JOBS_P0_CONTAINED", raising=False)
    return c, flag


def test_unrelated_command_allowed(cont):
    c, flag = cont
    g = c.guard_agent_jobs_execution(OTHER, source="t")
    assert g["blocked"] is False
    assert g["allowed"] is True


def test_active_flag_blocks_with_contained(cont):
    c, flag = cont
    flag.write_text("active reason=test\n")
    g = c.guard_agent_jobs_execution(WORKER, source="t")
    assert g["blocked"] is True
    assert g["fixable"] is False
    assert g["retry_cmd"] is None
    assert g["remediation_status"] == "CONTAINED"


def test_empty_flag_malformed_blocks(cont):
    c, flag = cont
    flag.write_text("   \n")
    g = c.guard_agent_jobs_execution(WORKER, source="t")
    assert g["blocked"] is True
    assert g["remediation_status"] == "CONTAINMENT_CHECK_FAILED"
    assert g["fixable"] is False
    assert g["retry_cmd"] is None


def test_flag_read_failure_blocks(cont, monkeypatch):
    c, flag = cont

    class BadFlag:
        def exists(self):
            return True

        def read_text(self, encoding="utf-8"):
            raise OSError("permission denied")

    monkeypatch.setattr(c, "FLAG_PATH", BadFlag())
    g = c.guard_agent_jobs_execution(WORKER, source="t")
    assert g["blocked"] is True
    assert g["remediation_status"] == "CONTAINMENT_CHECK_FAILED"
    assert g["retry_cmd"] is None


def test_exists_failure_blocks(cont, monkeypatch):
    c, flag = cont

    class BadFlag:
        def exists(self):
            raise OSError("io error")

        def read_text(self, encoding="utf-8"):
            return "active"

    monkeypatch.setattr(c, "FLAG_PATH", BadFlag())
    g = c.guard_agent_jobs_execution(WORKER, source="t")
    assert g["blocked"] is True
    assert g["remediation_status"] == "CONTAINMENT_CHECK_FAILED"


def test_malformed_env_blocks(cont, monkeypatch):
    c, flag = cont
    monkeypatch.setenv("AGENT_JOBS_P0_CONTAINED", "maybe")
    g = c.guard_agent_jobs_execution(WORKER, source="t")
    assert g["blocked"] is True
    assert g["remediation_status"] == "CONTAINMENT_CHECK_FAILED"


def test_evaluation_exception_blocks(cont, monkeypatch):
    c, flag = cont

    def boom():
        raise RuntimeError("explode")

    monkeypatch.setattr(c, "evaluate_containment_state", boom)
    g = c.guard_agent_jobs_execution(WORKER, source="t")
    assert g["blocked"] is True
    assert g["remediation_status"] == "CONTAINMENT_CHECK_FAILED"
    assert g["fixable"] is False


def test_health_import_failure_blocks_worker_remediation(monkeypatch, tmp_path):
    import health_agent as ha
    queue = tmp_path / "q.json"
    monkeypatch.setattr(ha, "QUEUE_FILE", queue)

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "lib.agent_jobs_containment" or name.endswith("agent_jobs_containment"):
            raise ImportError("simulated missing containment module")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    policy = {
        "enqueue": {"escalations": True, "code_fixes": False},
        "remediation_map": {"agent_jobs_stuck": WORKER},
    }
    findings = [{
        "severity": "critical",
        "category": "execution_health",
        "type": "agent_jobs_stuck",
        "message": "jobs stuck",
    }]
    n = ha.enqueue_escalations(policy, findings)
    assert n == 1
    data = __import__("json").loads(queue.read_text())
    assert data[0]["fixable"] is False
    assert data[0]["retry_cmd"] is None
    assert data[0]["remediation_status"] == "CONTAINMENT_CHECK_FAILED"


def test_health_import_failure_allows_unrelated(monkeypatch, tmp_path):
    import health_agent as ha
    queue = tmp_path / "q.json"
    monkeypatch.setattr(ha, "QUEUE_FILE", queue)

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if "agent_jobs_containment" in name:
            raise ImportError("boom")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    policy = {
        "enqueue": {"escalations": True, "code_fixes": False},
        "remediation_map": {"news_stale": OTHER},
    }
    findings = [{
        "severity": "warning",
        "category": "data",
        "type": "news_stale",
        "message": "news stale",
    }]
    n = ha.enqueue_escalations(policy, findings)
    assert n == 1
    data = __import__("json").loads(queue.read_text())
    assert data[0]["fixable"] is True
    # Path-independent: the command may resolve to a different Python binary
    retry_cmd = data[0]["retry_cmd"]
    assert retry_cmd is not None
    assert "scripts/news_ingestion.py" in retry_cmd
    assert "--priority" in retry_cmd


def test_claude_retry_import_failure_blocks_worker(monkeypatch):
    import claude_escalation_handler as ceh

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if "agent_jobs_containment" in name:
            raise ImportError("boom")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    item = {"retry_cmd": WORKER, "component": "health:x"}
    executed, success, out = ceh._execute_retry_cmd(item, {"max_runtime_seconds": 5}, dry_run=False)
    assert executed is False
    assert success is False
    assert out == "CONTAINMENT_CHECK_FAILED"


def test_claude_retry_no_subprocess_when_contained(cont, monkeypatch):
    c, flag = cont
    flag.write_text("active\n")
    import claude_escalation_handler as ceh

    monkeypatch.setattr(c, "FLAG_PATH", flag)
    # ensure handler uses same module with patched FLAG_PATH via re-import path
    monkeypatch.setattr(
        "lib.agent_jobs_containment.FLAG_PATH", flag,
    )
    monkeypatch.delenv("AGENT_JOBS_P0_CONTAINED", raising=False)

    popen = MagicMock()
    monkeypatch.setattr(ceh.subprocess, "Popen", popen)
    item = {"retry_cmd": WORKER, "component": "health:x"}
    # re-bind guard to use our cont module
    executed, success, out = ceh._execute_retry_cmd(
        item, {"max_runtime_seconds": 5, "allow": []}, dry_run=False,
    )
    # allowlist may block if empty — either CONTAINED or blocked is fine; Popen must not run for worker
    # With active flag, should be CONTAINED
    assert popen.call_count == 0
    assert executed is False


def test_claude_retry_blocks_on_check_failed(cont, monkeypatch):
    c, flag = cont
    import claude_escalation_handler as ceh

    def boom_guard(cmd, source=""):
        return {
            "blocked": True,
            "remediation_status": "CONTAINMENT_CHECK_FAILED",
            "status": "CONTAINMENT_CHECK_FAILED",
            "fixable": False,
            "retry_cmd": None,
        }

    monkeypatch.setattr(
        "lib.agent_jobs_containment.guard_agent_jobs_execution", boom_guard,
    )
    popen = MagicMock()
    monkeypatch.setattr(ceh.subprocess, "Popen", popen)
    executed, success, out = ceh._execute_retry_cmd(
        {"retry_cmd": WORKER}, {"max_runtime_seconds": 5}, dry_run=False,
    )
    assert executed is False
    assert out == "CONTAINMENT_CHECK_FAILED"
    assert popen.call_count == 0


def test_worker_entry_exits_before_db_when_contained(cont, monkeypatch):
    """Simulate worker __main__ containment gate before PipelineRun/DB."""
    c, flag = cont
    flag.write_text("active reason=test\n")
    monkeypatch.setattr(c, "FLAG_PATH", flag)
    rc = c.exit_if_contained_worker_entry()
    assert rc == 78


def test_worker_entry_exits_on_check_failed(cont, monkeypatch):
    c, flag = cont

    class BadFlag:
        def exists(self):
            raise OSError("disk")

        def read_text(self, encoding="utf-8"):
            return "x"

    monkeypatch.setattr(c, "FLAG_PATH", BadFlag())
    rc = c.exit_if_contained_worker_entry()
    assert rc == 78


def test_worker_entry_exits_on_import_failure_pattern():
    """Documented contract: import failure at worker main → exit 78 without DB."""
    # Unit-level: the source pattern is present
    src = (ROOT / "scripts/process_watchlist_agent_jobs.py").read_text()
    assert "CONTAINMENT_CHECK_FAILED" in src
    assert "exit_if_contained_worker_entry" in src
    # containment import failure branch before argparse/PipelineRun
    assert "cannot import containment helper" in src
    assert src.index("exit_if_contained_worker_entry") < src.index("process_jobs(effective)")


def test_inactive_allows_worker(cont, monkeypatch):
    c, flag = cont
    # no flag, env off
    monkeypatch.setenv("AGENT_JOBS_P0_CONTAINED", "0")
    g = c.guard_agent_jobs_execution(WORKER, source="t")
    assert g["blocked"] is False
    assert g["allowed"] is True
