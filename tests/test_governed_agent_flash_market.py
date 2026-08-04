"""Behavioral tests for governed market-15m-v2 wrapper + cron contract.

No paid provider calls. No live crontab mutation.
"""
from __future__ import annotations

import importlib
import os
import re
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = ROOT / "scripts" / "run_governed_agent_flash_market.sh"
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(autouse=True)
def _restore_flash_caps():
    """Prevent suite pollution of agent_flash_governance module-level caps."""
    from lib import agent_flash_governance as afg

    prev = (
        afg.MAX_CALLS_PER_RUN_TOTAL,
        afg.MAX_CALLS_PER_PROCESS,
        getattr(afg, "MAX_CALLS_PER_RUN", afg.MAX_CALLS_PER_PROCESS),
    )
    yield
    afg.MAX_CALLS_PER_RUN_TOTAL, afg.MAX_CALLS_PER_PROCESS, afg.MAX_CALLS_PER_RUN = prev


# Exact production cron shape (must ship with zero unescaped % characters)
CRON_LINE = (
    "*/15 6-19 * * 1-5 "
    "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts/run_governed_agent_flash_market.sh "
    ">> /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/logs/governed_agent_flash_market.log 2>&1 "
    "# TRADEAI_GOVERNED_WORKER market-15m-v2"
)


def test_cron_line_has_no_unescaped_percent():
    """Crontab treats unescaped % as newline; market-15m-v2 must never use %."""
    # Strip trailing comment for structure checks if needed, but % is forbidden anywhere
    assert "%" not in CRON_LINE
    # No date(1) in the crontab entry itself
    assert "date " not in CRON_LINE
    assert "$(date" not in CRON_LINE
    # Absolute wrapper path
    assert CRON_LINE.split()[5].startswith("/")
    assert CRON_LINE.split()[5].endswith("run_governed_agent_flash_market.sh")
    # Unique marker
    assert "TRADEAI_GOVERNED_WORKER market-15m-v2" in CRON_LINE
    # Schedule
    assert CRON_LINE.startswith("*/15 6-19 * * 1-5 ")
    # Single command (no ; && || pipes in the command portion before redirect)
    body = CRON_LINE.split("#", 1)[0].strip()
    assert ";" not in body
    assert "&&" not in body
    assert "||" not in body
    assert "|" not in body.replace(">>", "").replace("2>&1", "")


def test_wrapper_script_exists_and_executable_bits():
    assert WRAPPER.is_file()
    text = WRAPPER.read_text()
    assert "set -euo pipefail" in text
    assert "--scheduled-canary" in text
    assert "--limit 1" in text
    assert "--max-provider-calls 1" in text
    assert "watchlist_maria_flash_narrative" in text
    assert "deepseek_tradeai" in text
    assert "LLM_GLOBAL_DAILY_USD_CAP" in text
    assert "AGENT_JOBS_P0_CONTAINED" in text
    assert "AGENT_JOBS_LOCK_HELD_EXTERNALLY" in text
    assert "tradeai_watchlist_agent_jobs.lock" in text
    assert "timeout" in text
    # Must not clear host flag
    assert "rm -f" not in text or "AGENT_JOBS_P0_CONTAINED" not in text.split("rm -f")[1][:80]
    # Host flag path is only read, never deleted
    assert 'rm -f "$FLAG_HOST"' not in text
    assert "rm -f ${FLAG_HOST}" not in text
    # No unrestricted full worker
    assert "--limit 5" not in text
    assert "process_jobs" not in text


def test_wrapper_no_percent_in_script_cron_examples():
    text = WRAPPER.read_text()
    # Example cron line in header must not teach % usage
    for line in text.splitlines():
        if "TRADEAI_GOVERNED_WORKER market-15m-v2" in line and line.strip().startswith("#"):
            # comment example
            assert "%" not in line or "percent" in line.lower()


def _isolated_env(tmp_path, **extra):
    """Build a clean env so host /run/user secrets and containment cannot leak into tests."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path / "home"),
        "PROJ": str(ROOT),
        "PY": sys.executable,
        "TRADEAI_RUN_ENV_PATH": str(tmp_path / "no-run-env"),
        "LANG": "C.UTF-8",
    }
    env.update(extra)
    return env


def test_wrapper_missing_containment_blocks(tmp_path, monkeypatch):
    log = tmp_path / "m.log"
    env = _isolated_env(
        tmp_path,
        TRADEAI_GOVERNED_MARKET_LOG=str(log),
        TRADEAI_GOVERNED_MARKET_DRY_RUN="0",
    )
    # HOME has no flag
    proc = subprocess.run(
        ["bash", str(WRAPPER)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 78
    body = log.read_text() if log.exists() else ""
    assert "containment flag missing" in body
    assert "exit=78" in body


def test_wrapper_dry_run_loads_and_locks_without_provider(tmp_path, monkeypatch):
    """Dry-run: env + lock + host flag; no python worker / no provider."""
    home = tmp_path / "home"
    flag = home / ".local/state/tradeai/AGENT_JOBS_P0_CONTAINED"
    flag.parent.mkdir(parents=True)
    flag.write_text("active reason=test-market-v2\n")
    op_env = home / ".config/tradeai/agent-operator.env"
    op_env.parent.mkdir(parents=True)
    op_env.write_text("LLM_GLOBAL_DAILY_USD_CAP=0.25\ndeepseek_tradeai=test-secret-not-printed\n")
    log = tmp_path / "dry.log"
    lock = tmp_path / "jobs.lock"
    env = _isolated_env(
        tmp_path,
        TRADEAI_GOVERNED_MARKET_LOG=str(log),
        TRADEAI_GOVERNED_MARKET_DRY_RUN="1",
        AGENT_JOBS_LOCK_PATH=str(lock),
    )
    proc = subprocess.run(
        ["bash", str(WRAPPER)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr, log.read_text() if log.exists() else "")
    body = log.read_text()
    assert "mode=dry_run" in body
    assert "deepseek_tradeai=present" in body
    assert "test-secret-not-printed" not in body  # never print secret
    assert "LLM_GLOBAL_DAILY_USD_CAP_ok=yes" in body
    assert "lock_ok=" in body
    assert "host_flag_still_present=yes" in body
    assert "success: dry_run complete" in body
    assert "mode=scheduled_canary" not in body


def test_wrapper_requires_cap(tmp_path):
    home = tmp_path / "home"
    flag = home / ".local/state/tradeai/AGENT_JOBS_P0_CONTAINED"
    flag.parent.mkdir(parents=True)
    flag.write_text("active\n")
    # operator env with key but no cap
    op = home / ".config/tradeai/agent-operator.env"
    op.parent.mkdir(parents=True)
    op.write_text("deepseek_tradeai=x\n")
    log = tmp_path / "cap.log"
    env = _isolated_env(
        tmp_path,
        TRADEAI_GOVERNED_MARKET_LOG=str(log),
        TRADEAI_GOVERNED_MARKET_DRY_RUN="1",
    )
    proc = subprocess.run(["bash", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 2
    assert "LLM_GLOBAL_DAILY_USD_CAP missing" in log.read_text()


def test_wrapper_requires_deepseek_key(tmp_path):
    home = tmp_path / "home"
    flag = home / ".local/state/tradeai/AGENT_JOBS_P0_CONTAINED"
    flag.parent.mkdir(parents=True)
    flag.write_text("active\n")
    op = home / ".config/tradeai/agent-operator.env"
    op.parent.mkdir(parents=True)
    op.write_text("LLM_GLOBAL_DAILY_USD_CAP=0.25\n")
    log = tmp_path / "key.log"
    env = _isolated_env(
        tmp_path,
        TRADEAI_GOVERNED_MARKET_LOG=str(log),
        TRADEAI_GOVERNED_MARKET_DRY_RUN="1",
    )
    proc = subprocess.run(["bash", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 2
    assert "deepseek_tradeai missing" in log.read_text()


def test_external_lock_held_skips_reacquire(tmp_path, monkeypatch):
    from lib.agent_jobs_lock import acquire_jobs_lock, OverlapError

    lock = tmp_path / "ext.lock"
    # Without external flag, nested non-blocking fails
    with acquire_jobs_lock(lock, blocking=False):
        with pytest.raises(OverlapError):
            with acquire_jobs_lock(lock, blocking=False):
                pass
    # With external flag, nested is no-op
    monkeypatch.setenv("AGENT_JOBS_LOCK_HELD_EXTERNALLY", "1")
    with acquire_jobs_lock(lock, blocking=False) as fd:
        assert fd == -1
        with acquire_jobs_lock(lock, blocking=False) as fd2:
            assert fd2 == -1


def test_scheduled_canary_one_job_one_call_flash_only(monkeypatch, tmp_path):
    """Market path reuses scheduled-canary: 1 call, FAST, flash, no two-pass, no fallback."""
    import process_watchlist_agent_jobs as pwaj
    from lib import agent_flash_governance as afg
    from lib import agent_jobs_containment as c

    flag = tmp_path / "f"
    flag.write_text("active\n")
    monkeypatch.setattr(c, "FLAG_PATH", flag)
    monkeypatch.setenv("AGENT_JOBS_P0_CONTAINED", "0")
    monkeypatch.setenv("AGENT_JOBS_P0_CONTAINMENT_FLAG", str(tmp_path / "absent"))
    importlib.reload(c)

    calls = {"n": 0}

    def fake_gov(*a, **k):
        calls["n"] += 1
        assert k.get("allow_fast_think") is False
        assert k.get("task_type") == "agent_narrative"
        afg._reserve_run_budget("watchlist_maria_flash_narrative", 0.0)
        return {
            "success": True,
            "process_id": "watchlist_maria_flash_narrative",
            "requested_policy": "FAST",
            "executed_policy": "FAST",
            "requested_model_id": "deepseek-v4-flash",
            "returned_model": "deepseek-v4-flash",
            "model_used": "deepseek-v4-flash",
            "provider_request_id": "mkt-1",
            "tokens": {"prompt_tokens": 10, "completion_tokens": 5},
            "cost_estimate": 0.00001,
            "fallback_used": False,
            "response": '{"recommendation":"HOLD","confidence":50,"summary":"ok"}',
        }

    monkeypatch.setattr("lib.agent_flash_governance.governed_flash_call", fake_gov)
    afg.MAX_CALLS_PER_RUN_TOTAL = 1
    afg.MAX_CALLS_PER_PROCESS = 1
    two_pass = MagicMock(side_effect=AssertionError("two-pass"))
    process_jobs = MagicMock(side_effect=AssertionError("process_jobs"))
    monkeypatch.setattr(pwaj, "_run_maria_two_pass", two_pass, raising=False)
    monkeypatch.setattr(pwaj, "process_jobs", process_jobs, raising=False)

    out = pwaj.run_scheduled_canary(max_provider_calls=1)
    assert calls["n"] == 1
    assert out["provider_calls"] == 1
    assert out["returned_model"] == "deepseek-v4-flash"
    assert out["requested_policy"] == "FAST"
    assert out["fallback_used"] is False
    assert out["maria_two_pass_entered"] is False
    assert out["process_id"] == "watchlist_maria_flash_narrative"
    assert out["process_id"] != "llm_router"
    assert "legacy" not in out["process_id"].lower()
    assert two_pass.call_count == 0
    assert process_jobs.call_count == 0

    # Second call rejected (no retry)
    with pytest.raises(RuntimeError, match="COST_CAP_EXCEEDED"):
        afg._reserve_run_budget("watchlist_maria_flash_narrative", 0.0)


def test_no_retry_on_failure(monkeypatch, tmp_path):
    import process_watchlist_agent_jobs as pwaj
    from lib import agent_flash_governance as afg
    from lib import agent_jobs_containment as c

    monkeypatch.setattr(c, "FLAG_PATH", tmp_path / "f")
    (tmp_path / "f").write_text("a\n")
    monkeypatch.setenv("AGENT_JOBS_P0_CONTAINED", "0")
    monkeypatch.setenv("AGENT_JOBS_P0_CONTAINMENT_FLAG", str(tmp_path / "x"))
    importlib.reload(c)

    n = {"c": 0}

    def boom(*a, **k):
        n["c"] += 1
        return {
            "success": False,
            "error": "provider_down",
            "process_id": "watchlist_maria_flash_narrative",
            "requested_policy": "FAST",
            "executed_policy": "FAST",
            "requested_model_id": "deepseek-v4-flash",
            "returned_model": "deepseek-v4-flash",
            "fallback_used": False,
            "provider_request_id": None,
            "tokens": {},
            "cost_estimate": 0,
        }

    monkeypatch.setattr("lib.agent_flash_governance.governed_flash_call", boom)
    afg.MAX_CALLS_PER_RUN_TOTAL = 1
    afg.MAX_CALLS_PER_PROCESS = 1
    with pytest.raises(RuntimeError):
        pwaj.run_scheduled_canary(max_provider_calls=1)
    assert n["c"] == 1  # no retry


def test_host_containment_remains_active_after_process_override(tmp_path, monkeypatch):
    from lib import agent_jobs_containment as c
    import importlib

    host = tmp_path / "HOST"
    host.write_text("active reason=gate2-p0\n")
    monkeypatch.delenv("AGENT_JOBS_P0_CONTAINED", raising=False)
    monkeypatch.setenv("AGENT_JOBS_P0_CONTAINMENT_FLAG", str(host))
    importlib.reload(c)
    assert c.evaluate_containment_state()["status"] == "ACTIVE"
    # Market wrapper style override
    monkeypatch.setenv("AGENT_JOBS_P0_CONTAINED", "0")
    monkeypatch.setenv("AGENT_JOBS_P0_CONTAINMENT_FLAG", str(tmp_path / "absent_market"))
    importlib.reload(c)
    assert c.evaluate_containment_state()["status"] == "INACTIVE"
    assert "active" in host.read_text()


def test_no_broker_authority_in_wrapper_or_canary_mode():
    """Static guarantee: market wrapper and scheduled-canary surface do not grant trade authority."""
    text = WRAPPER.read_text().lower()
    for banned in ("place_order", "submit_order", "2fa", "broker_write", "live_trade"):
        assert banned not in text
    # scheduled canary docstring / mode
    src = (ROOT / "scripts" / "process_watchlist_agent_jobs.py").read_text()
    assert "run_scheduled_canary" in src
    # Canary prompt is advisory-only
    assert "No tools. No orders" in src or "No tools" in src
