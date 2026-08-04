"""Tests for --scheduled-canary one-call worker mode (no paid provider calls)."""
from __future__ import annotations

import builtins
import importlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture
def cont(monkeypatch, tmp_path):
    from lib import agent_jobs_containment as c
    from lib import agent_flash_governance as afg
    importlib.reload(c)
    flag = tmp_path / "AGENT_JOBS_P0_CONTAINED"
    flag.write_text("active reason=test\n")
    monkeypatch.setattr(c, "FLAG_PATH", flag)
    monkeypatch.delenv("AGENT_JOBS_P0_CONTAINED", raising=False)
    # process-scoped override path absent
    monkeypatch.setenv("AGENT_JOBS_P0_CONTAINMENT_FLAG", str(tmp_path / "absent_flag"))
    monkeypatch.setenv("AGENT_JOBS_P0_CONTAINED", "0")
    importlib.reload(c)
    # Isolate aggregate caps and always restore defaults after test (avoid suite pollution)
    prev = (
        afg.MAX_CALLS_PER_RUN_TOTAL,
        afg.MAX_CALLS_PER_PROCESS,
        getattr(afg, "MAX_CALLS_PER_RUN", afg.MAX_CALLS_PER_PROCESS),
    )
    afg.MAX_CALLS_PER_RUN_TOTAL = 1
    afg.MAX_CALLS_PER_PROCESS = 1
    afg.MAX_CALLS_PER_RUN = 1
    yield c, flag
    afg.MAX_CALLS_PER_RUN_TOTAL, afg.MAX_CALLS_PER_PROCESS, afg.MAX_CALLS_PER_RUN = prev


def _ok_flash_result(**extra):
    base = {
        "success": True,
        "process_id": "watchlist_maria_flash_narrative",
        "requested_policy": "FAST",
        "executed_policy": "FAST",
        "requested_model_id": "deepseek-v4-flash",
        "returned_model": "deepseek-v4-flash",
        "model_used": "deepseek-v4-flash",
        "provider_request_id": "req-test-1",
        "tokens": {"prompt_tokens": 10, "completion_tokens": 5},
        "cost_estimate": 0.00001,
        "fallback_used": False,
        "response": '{"recommendation":"HOLD","confidence":50,"summary":"ok"}',
    }
    base.update(extra)
    return base


def test_scheduled_canary_one_provider_call(cont, monkeypatch):
    """scheduled-canary mode makes exactly one governed_flash_call."""
    import process_watchlist_agent_jobs as pwaj
    from lib import agent_flash_governance as afg

    calls = {"n": 0}

    def fake_governed(*a, **k):
        calls["n"] += 1
        assert k.get("allow_fast_think") is False
        assert k.get("task_type") == "agent_narrative"
        # Consume one aggregate budget unit (simulates real governed path)
        afg._reserve_run_budget("watchlist_maria_flash_narrative", 0.0)
        return _ok_flash_result()

    monkeypatch.setattr(
        "lib.agent_flash_governance.governed_flash_call", fake_governed,
    )
    afg.MAX_CALLS_PER_RUN_TOTAL = 1
    afg.MAX_CALLS_PER_PROCESS = 1

    two_pass = MagicMock(side_effect=AssertionError("two-pass must not run"))
    process_jobs = MagicMock(side_effect=AssertionError("process_jobs must not run"))
    monkeypatch.setattr(pwaj, "_run_maria_two_pass", two_pass, raising=False)
    monkeypatch.setattr(pwaj, "process_jobs", process_jobs, raising=False)

    out = pwaj.run_scheduled_canary(max_provider_calls=1)
    assert calls["n"] == 1
    assert out["provider_calls"] == 1
    assert out["maria_two_pass_entered"] is False
    assert out["process_jobs_entered"] is False
    assert out["returned_model"] == "deepseek-v4-flash"
    assert two_pass.call_count == 0
    assert process_jobs.call_count == 0


def test_scheduled_canary_rejects_max_calls_not_one(cont):
    import process_watchlist_agent_jobs as pwaj
    with pytest.raises(RuntimeError, match="max_provider_calls must be 1"):
        pwaj.run_scheduled_canary(max_provider_calls=2)


def test_scheduled_canary_rejects_wrong_process(cont):
    import process_watchlist_agent_jobs as pwaj
    with pytest.raises(RuntimeError, match="only watchlist_maria_flash_narrative"):
        pwaj.run_scheduled_canary(process_id="llm_router")


def test_second_reservation_rejected_after_canary(cont, monkeypatch):
    import process_watchlist_agent_jobs as pwaj
    from lib import agent_flash_governance as afg

    def fake_governed(*a, **k):
        # Simulate budget consumption of one call via real reserve path
        afg._reserve_run_budget("watchlist_maria_flash_narrative", 0.0)
        return {
            "success": True,
            "process_id": "watchlist_maria_flash_narrative",
            "requested_policy": "FAST",
            "executed_policy": "FAST",
            "requested_model_id": "deepseek-v4-flash",
            "returned_model": "deepseek-v4-flash",
            "model_used": "deepseek-v4-flash",
            "provider_request_id": "req-2",
            "tokens": {"prompt_tokens": 1, "completion_tokens": 1},
            "cost_estimate": 0.0,
            "fallback_used": False,
            "response": "{}",
        }

    monkeypatch.setattr("lib.agent_flash_governance.governed_flash_call", fake_governed)
    afg.reset_run_budget()
    afg.MAX_CALLS_PER_RUN_TOTAL = 1
    afg.MAX_CALLS_PER_PROCESS = 1
    pwaj.run_scheduled_canary(max_provider_calls=1)
    with pytest.raises(RuntimeError, match="COST_CAP_EXCEEDED"):
        afg._reserve_run_budget("watchlist_maria_flash_narrative", 0.0)


def test_returned_model_must_be_flash(cont, monkeypatch):
    import process_watchlist_agent_jobs as pwaj
    from lib import agent_flash_governance as afg

    def bad(*a, **k):
        afg._reserve_run_budget("watchlist_maria_flash_narrative", 0.0)
        return _ok_flash_result(returned_model="deepseek-chat", model_used="deepseek-chat")

    monkeypatch.setattr("lib.agent_flash_governance.governed_flash_call", bad)
    afg.MAX_CALLS_PER_RUN_TOTAL = 1
    afg.MAX_CALLS_PER_PROCESS = 1
    with pytest.raises(RuntimeError, match="SCHEDULED_CANARY_MODEL"):
        pwaj.run_scheduled_canary(max_provider_calls=1)


def test_fallback_forbidden(cont, monkeypatch):
    import process_watchlist_agent_jobs as pwaj
    from lib import agent_flash_governance as afg

    def bad(*a, **k):
        afg._reserve_run_budget("watchlist_maria_flash_narrative", 0.0)
        return _ok_flash_result(fallback_used=True)

    monkeypatch.setattr("lib.agent_flash_governance.governed_flash_call", bad)
    afg.MAX_CALLS_PER_RUN_TOTAL = 1
    afg.MAX_CALLS_PER_PROCESS = 1
    with pytest.raises(RuntimeError, match="FALLBACK"):
        pwaj.run_scheduled_canary(max_provider_calls=1)


def test_overlap_lock_blocks_second_worker(tmp_path, monkeypatch):
    """Two non-blocking lock acquisitions cannot both succeed."""
    from lib.agent_jobs_lock import acquire_jobs_lock, OverlapError

    lock = tmp_path / "canary.lock"
    with acquire_jobs_lock(lock, blocking=False):
        with pytest.raises(OverlapError):
            with acquire_jobs_lock(lock, blocking=False):
                pass


def test_one_shot_wrapper_self_disable_logic(tmp_path):
    """Wrapper removes marker lines from a fake crontab file (no live crontab mutation)."""
    marker = "# TRADEAI_SCHEDULED_CANARY_ONCE"
    crontab = tmp_path / "crontab.txt"
    crontab.write_text(
        f"PROJ=/tmp\n"
        f"{marker} * * * * * /bin/true canary\n"
        f"*/5 * * * * /bin/echo keep\n"
    )
    # Simulate self_disable filter
    lines = [ln for ln in crontab.read_text().splitlines() if marker not in ln]
    assert any("keep" in ln for ln in lines)
    assert not any(marker in ln for ln in lines)
    assert not any("canary" in ln for ln in lines)


def test_containment_sibling_still_active(monkeypatch, tmp_path):
    """Process-scoped override does not clear host flag; sibling sees ACTIVE."""
    from lib import agent_jobs_containment as c
    import importlib

    host_flag = tmp_path / "HOST_FLAG"
    host_flag.write_text("active reason=host\n")
    # Sibling: no env override — only host flag path
    monkeypatch.delenv("AGENT_JOBS_P0_CONTAINED", raising=False)
    monkeypatch.setenv("AGENT_JOBS_P0_CONTAINMENT_FLAG", str(host_flag))
    importlib.reload(c)
    assert c.evaluate_containment_state()["status"] == "ACTIVE"

    # Canary: process-scoped override (env off + absent flag path)
    monkeypatch.setenv("AGENT_JOBS_P0_CONTAINED", "0")
    monkeypatch.setenv("AGENT_JOBS_P0_CONTAINMENT_FLAG", str(tmp_path / "absent"))
    importlib.reload(c)
    assert c.evaluate_containment_state()["status"] == "INACTIVE"
    # host file untouched
    assert "active" in host_flag.read_text()


def test_cli_scheduled_canary_does_not_call_process_jobs(cont, monkeypatch):
    """CLI path with --scheduled-canary never enters process_jobs."""
    import process_watchlist_agent_jobs as pwaj
    from lib import agent_flash_governance as afg

    called = {"jobs": 0, "two_pass": 0, "gov": 0}

    def fake_gov(*a, **k):
        called["gov"] += 1
        afg._reserve_run_budget("watchlist_maria_flash_narrative", 0.0)
        return _ok_flash_result(provider_request_id="cli-1")

    monkeypatch.setattr("lib.agent_flash_governance.governed_flash_call", fake_gov)
    afg.MAX_CALLS_PER_RUN_TOTAL = 1
    afg.MAX_CALLS_PER_PROCESS = 1
    monkeypatch.setattr(
        pwaj, "process_jobs", lambda *a, **k: called.__setitem__("jobs", called["jobs"] + 1)
    )
    if hasattr(pwaj, "_run_maria_two_pass"):
        monkeypatch.setattr(
            pwaj,
            "_run_maria_two_pass",
            lambda *a, **k: called.__setitem__("two_pass", called["two_pass"] + 1),
        )

    pwaj.run_scheduled_canary(max_provider_calls=1)
    assert called["gov"] == 1
    assert called["jobs"] == 0
    assert called["two_pass"] == 0


def test_no_llm_router_process_id_in_canary_result(cont, monkeypatch):
    import process_watchlist_agent_jobs as pwaj
    from lib import agent_flash_governance as afg

    def fake(*a, **k):
        afg._reserve_run_budget("watchlist_maria_flash_narrative", 0.0)
        return _ok_flash_result(provider_request_id="z")

    monkeypatch.setattr("lib.agent_flash_governance.governed_flash_call", fake)
    afg.MAX_CALLS_PER_RUN_TOTAL = 1
    afg.MAX_CALLS_PER_PROCESS = 1
    out = pwaj.run_scheduled_canary(max_provider_calls=1)
    assert out["process_id"] != "llm_router"
    assert out["process_id"] != "unregistered"
    assert out["process_id"] == "watchlist_maria_flash_narrative"
