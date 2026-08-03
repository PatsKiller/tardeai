"""Tests for governed agent_flash path (issue #283 / PR #284 Gate 2)."""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def test_legacy_ids_rejected():
    from lib.agent_flash_governance import reject_legacy_model_id, LEGACY_MODEL_IDS
    for mid in ("deepseek-chat", "deepseek-reasoner", "deepseek-v4", "deepseek_v4"):
        with pytest.raises(RuntimeError, match="LEGACY_MODEL_REJECTED"):
            reject_legacy_model_id(mid)
    assert "deepseek-chat" in LEGACY_MODEL_IDS


def test_process_matrix_mapping():
    from lib.agent_flash_governance import process_for_task, FLASH_MODEL
    assert process_for_task("agent_narrative") == "watchlist_maria_flash_narrative"
    assert process_for_task("agent_debate") == "watchlist_agent_debate_flash"
    assert process_for_task("cio_synthesis") == "watchlist_steph_flash_narrative"
    assert process_for_task("sector_correlation") == "watchlist_risk_flash_narrative"
    assert FLASH_MODEL == "deepseek-v4-flash"


def test_fast_default_think_only_on_deterministic_escalation():
    from lib.agent_flash_governance import policy_for_task, should_escalate_fast_think
    pol, reason = policy_for_task("agent_debate", metadata={}, prompt="ordinary debate prompt")
    assert pol == "FAST"
    assert reason is None
    esc, r = should_escalate_fast_think(
        "agent_debate",
        metadata={"conflicting_evidence": True},
        prompt="x",
    )
    assert esc is True
    assert r == "conflicting_evidence"
    pol2, reason2 = policy_for_task(
        "agent_debate",
        metadata={"severity": "critical"},
        prompt="",
    )
    assert pol2 == "FAST_THINK"
    assert reason2 == "elevated_severity"
    pol3, reason3 = policy_for_task(
        "agent_debate",
        metadata={},
        prompt="Please reconcile conflicting evidence between Maria and Risk",
    )
    assert pol3 == "FAST_THINK"
    assert reason3 and "marker" in reason3


def test_registry_processes_have_caps():
    import json
    reg = json.loads((ROOT / "config/llm_process_registry.json").read_text())
    needed = {
        "watchlist_maria_flash_narrative",
        "watchlist_risk_flash_narrative",
        "watchlist_steph_flash_narrative",
        "watchlist_agent_debate_flash",
        "watchlist_agent_flash_extract",
    }
    by_id = {p["id"]: p for p in reg["processes"]}
    for pid in needed:
        p = by_id[pid]
        assert p.get("daily_cost_cap_usd") and float(p["daily_cost_cap_usd"]) > 0, pid
        assert p.get("daily_soft_cap") and int(p["daily_soft_cap"]) > 0, pid
        assert p.get("fallback_allowed") is False
        assert "PRO" not in (p.get("deepseek_allowed_policies") or [])


def test_health_remediation_blocked_when_contained(tmp_path, monkeypatch):
    from lib import agent_jobs_containment as c
    flag = tmp_path / "CONTAINED"
    flag.write_text("active\n")
    monkeypatch.setattr(c, "FLAG_PATH", flag)
    monkeypatch.delenv("AGENT_JOBS_P0_CONTAINED", raising=False)
    assert c.is_contained() is True
    cmd = "flock -n /tmp/x .venv/bin/python scripts/process_watchlist_agent_jobs.py --limit 15"
    g = c.guard_remediation_command(cmd, source="test")
    assert g["blocked"] is True
    assert g["cmd"] is None
    assert "CONTAINED" in g["message"]
    # unrelated remediation allowed
    g2 = c.guard_remediation_command(".venv/bin/python scripts/news_ingestion.py", source="test")
    assert g2["blocked"] is False


def test_health_agent_enqueue_skips_worker_when_contained(monkeypatch, tmp_path):
    from lib import agent_jobs_containment as c
    flag = tmp_path / "CONTAINED"
    flag.write_text("1")
    monkeypatch.setattr(c, "FLAG_PATH", flag)
    monkeypatch.delenv("AGENT_JOBS_P0_CONTAINED", raising=False)

    import health_agent as ha
    queue = tmp_path / "q.json"
    monkeypatch.setattr(ha, "QUEUE_FILE", queue)
    policy = {
        "enqueue": {"escalations": True, "code_fixes": False},
        "remediation_map": {
            "agent_jobs_stuck": (
                "flock -n /tmp/tradeai_watchlist_agent_jobs.lock "
                ".venv/bin/python scripts/process_watchlist_agent_jobs.py --limit 15"
            ),
        },
    }
    findings = [{
        "severity": "critical",
        "category": "execution_health",
        "type": "agent_jobs_stuck",
        "message": "14 agent jobs stuck",
    }]
    n = ha.enqueue_escalations(policy, findings)
    assert n == 1
    data = __import__("json").loads(queue.read_text())
    assert data[0].get("remediation_status") == "CONTAINED"
    assert data[0].get("retry_cmd") is None
    assert data[0].get("fixable") is False


def test_aggregate_per_run_request_cap_multi_process(monkeypatch):
    from lib import agent_flash_governance as ag
    from lib import llm_consumption as lc

    monkeypatch.setattr(ag, "MAX_CALLS_PER_RUN_TOTAL", 3)
    monkeypatch.setattr(ag, "MAX_CALLS_PER_PROCESS", 50)
    monkeypatch.setattr(ag, "MAX_PROJECTED_USD_PER_RUN", 100.0)
    monkeypatch.setattr(ag, "already_completed", lambda *a, **k: False)
    monkeypatch.setattr(ag, "circuit_open", lambda: False)
    monkeypatch.setattr(
        "lib.agent_jobs_containment.is_contained", lambda: False,
    )
    monkeypatch.setattr(
        lc, "get_process_config",
        lambda pid: {
            "registered": True,
            "daily_cost_cap_usd": 5.0,
            "daily_soft_cap": 100,
            "max_output_tokens": 32,
            "max_input_tokens": 64,
            "allowed_lanes": ["fast"],
        },
    )
    monkeypatch.setattr(
        "lib.consumption_run_manual.projected_max_cost_usd",
        lambda **k: 0.01,
    )
    calls = {"n": 0}

    def fake_gate(*a, **k):
        calls["n"] += 1
        return "OK", {
            "returned_model": "deepseek-v4-flash",
            "requested_model_id": "deepseek-v4-flash",
            "estimated_cost_usd": 0.00001,
            "fallback_used": False,
            "usage": {"prompt_tokens": 5, "completion_tokens": 1},
            "request_id": f"r{calls['n']}",
        }

    monkeypatch.setattr(lc, "gate_and_generate", fake_gate)
    ag.reset_run_budget("test-run")
    tasks = [
        "agent_narrative",
        "sector_correlation",
        "cio_synthesis",
        "agent_debate",  # 4th should hit aggregate cap
    ]
    results = []
    for t in tasks:
        results.append(ag.governed_flash_call("hi", task_type=t, max_tokens=32, job_key=t))
    oks = [r for r in results if r.get("success")]
    fails = [r for r in results if not r.get("success")]
    assert len(oks) == 3
    assert any("aggregate per-run call cap" in (f.get("error") or "") for f in fails)
    assert calls["n"] == 3


def test_aggregate_per_run_usd_cap(monkeypatch):
    from lib import agent_flash_governance as ag
    from lib import llm_consumption as lc

    monkeypatch.setattr(ag, "MAX_CALLS_PER_RUN_TOTAL", 100)
    monkeypatch.setattr(ag, "MAX_CALLS_PER_PROCESS", 100)
    monkeypatch.setattr(ag, "MAX_PROJECTED_USD_PER_RUN", 0.025)
    monkeypatch.setattr(ag, "already_completed", lambda *a, **k: False)
    monkeypatch.setattr(ag, "circuit_open", lambda: False)
    monkeypatch.setattr("lib.agent_jobs_containment.is_contained", lambda: False)
    monkeypatch.setattr(
        lc, "get_process_config",
        lambda pid: {
            "registered": True,
            "daily_cost_cap_usd": 5.0,
            "daily_soft_cap": 100,
            "max_output_tokens": 32,
            "max_input_tokens": 64,
            "allowed_lanes": ["fast"],
        },
    )
    monkeypatch.setattr(
        "lib.consumption_run_manual.projected_max_cost_usd",
        lambda **k: 0.02,
    )
    n = {"c": 0}

    def fake_gate(*a, **k):
        n["c"] += 1
        return "OK", {
            "returned_model": "deepseek-v4-flash",
            "requested_model_id": "deepseek-v4-flash",
            "estimated_cost_usd": 0.001,
            "fallback_used": False,
            "usage": {},
            "request_id": "x",
        }

    monkeypatch.setattr(lc, "gate_and_generate", fake_gate)
    ag.reset_run_budget()
    r1 = ag.governed_flash_call("a", task_type="agent_narrative", max_tokens=32, job_key="a")
    r2 = ag.governed_flash_call("b", task_type="agent_debate", max_tokens=32, job_key="b")
    assert r1["success"] is True
    assert r2["success"] is False
    assert "projected USD cap" in (r2.get("error") or "")
    assert n["c"] == 1


def test_returned_model_mismatch_fails(monkeypatch):
    from lib import agent_flash_governance as ag
    from lib import llm_consumption as lc

    monkeypatch.setattr(ag, "already_completed", lambda *a, **k: False)
    monkeypatch.setattr(ag, "circuit_open", lambda: False)
    monkeypatch.setattr("lib.agent_jobs_containment.is_contained", lambda: False)
    monkeypatch.setattr(
        lc, "get_process_config",
        lambda pid: {
            "registered": True,
            "daily_cost_cap_usd": 1.0,
            "daily_soft_cap": 100,
            "max_output_tokens": 32,
            "max_input_tokens": 64,
            "allowed_lanes": ["fast"],
        },
    )
    monkeypatch.setattr(
        "lib.consumption_run_manual.projected_max_cost_usd",
        lambda **k: 0.001,
    )
    monkeypatch.setattr(
        lc, "gate_and_generate",
        lambda *a, **k: ("ok", {
            "returned_model": "deepseek-chat",
            "requested_model_id": "deepseek-v4-flash",
            "estimated_cost_usd": 0.001,
            "fallback_used": False,
            "usage": {},
        }),
    )
    ag.reset_run_budget()
    r = ag.governed_flash_call("hi", task_type="agent_narrative", max_tokens=32)
    assert r["success"] is False
    assert "MISMATCHED" in (r.get("error") or "")


def test_no_silent_fallback_flag(monkeypatch):
    from lib import agent_flash_governance as ag
    from lib import llm_consumption as lc

    monkeypatch.setattr(ag, "already_completed", lambda *a, **k: False)
    monkeypatch.setattr(ag, "circuit_open", lambda: False)
    monkeypatch.setattr("lib.agent_jobs_containment.is_contained", lambda: False)
    monkeypatch.setattr(
        lc, "get_process_config",
        lambda pid: {
            "registered": True,
            "daily_cost_cap_usd": 1.0,
            "daily_soft_cap": 100,
            "max_output_tokens": 32,
            "max_input_tokens": 64,
            "allowed_lanes": ["fast"],
        },
    )
    monkeypatch.setattr(
        "lib.consumption_run_manual.projected_max_cost_usd",
        lambda **k: 0.001,
    )
    monkeypatch.setattr(
        lc, "gate_and_generate",
        lambda *a, **k: ("ok", {
            "returned_model": "deepseek-v4-flash",
            "requested_model_id": "deepseek-v4-flash",
            "estimated_cost_usd": 0.001,
            "fallback_used": True,
            "usage": {},
        }),
    )
    ag.reset_run_budget()
    r = ag.governed_flash_call("hi", task_type="agent_narrative", max_tokens=32)
    assert r["success"] is False
    assert "FALLBACK_FORBIDDEN" in (r.get("error") or "")


def test_dedupe_skips_second_call(monkeypatch, tmp_path):
    from lib import agent_flash_governance as ag
    from lib import llm_consumption as lc

    monkeypatch.setattr(ag, "_DEDUPE_PATH", tmp_path / "dedupe.json")
    monkeypatch.setattr(ag, "_DEDUPE_CACHE", {})
    monkeypatch.setattr(ag, "circuit_open", lambda: False)
    monkeypatch.setattr("lib.agent_jobs_containment.is_contained", lambda: False)
    monkeypatch.setattr(
        lc, "get_process_config",
        lambda pid: {
            "registered": True,
            "daily_cost_cap_usd": 1.0,
            "daily_soft_cap": 100,
            "max_output_tokens": 32,
            "max_input_tokens": 64,
            "allowed_lanes": ["fast"],
        },
    )
    monkeypatch.setattr(
        "lib.consumption_run_manual.projected_max_cost_usd",
        lambda **k: 0.001,
    )
    calls = {"n": 0}

    def fake_gate(*a, **k):
        calls["n"] += 1
        return "OK", {
            "returned_model": "deepseek-v4-flash",
            "requested_model_id": "deepseek-v4-flash",
            "estimated_cost_usd": 0.00001,
            "fallback_used": False,
            "usage": {"prompt_tokens": 5, "completion_tokens": 1},
            "request_id": "req-1",
        }

    monkeypatch.setattr(lc, "gate_and_generate", fake_gate)
    ag.reset_run_budget()
    r1 = ag.governed_flash_call("same", task_type="agent_narrative", job_key="j1", max_tokens=32)
    r2 = ag.governed_flash_call("same", task_type="agent_narrative", job_key="j1", max_tokens=32)
    assert r1["success"] is True
    assert r2.get("dedupe") is True
    assert calls["n"] == 1


def test_circuit_breaker_opens(monkeypatch):
    from lib import agent_flash_governance as ag
    from lib import llm_consumption as lc

    monkeypatch.setattr(ag, "CIRCUIT_ERROR_THRESHOLD", 2)
    monkeypatch.setattr(ag, "CIRCUIT_COOLDOWN_SEC", 60)
    monkeypatch.setattr(ag, "_CIRCUIT", {"errors": 0, "open_until": 0.0, "last_error": None})
    monkeypatch.setattr(ag, "already_completed", lambda *a, **k: False)
    monkeypatch.setattr("lib.agent_jobs_containment.is_contained", lambda: False)
    monkeypatch.setattr(
        lc, "get_process_config",
        lambda pid: {
            "registered": True,
            "daily_cost_cap_usd": 1.0,
            "daily_soft_cap": 100,
            "max_output_tokens": 32,
            "max_input_tokens": 64,
            "allowed_lanes": ["fast"],
        },
    )
    monkeypatch.setattr(
        "lib.consumption_run_manual.projected_max_cost_usd",
        lambda **k: 0.001,
    )
    monkeypatch.setattr(
        lc, "gate_and_generate",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("PROVIDER_TIMEOUT")),
    )
    ag.reset_run_budget()
    r1 = ag.governed_flash_call("a", task_type="agent_narrative", job_key="1", max_tokens=32)
    r2 = ag.governed_flash_call("b", task_type="agent_narrative", job_key="2", max_tokens=32)
    assert r1["success"] is False
    assert r2["success"] is False
    # after threshold, circuit opens
    r3 = ag.governed_flash_call("c", task_type="agent_narrative", job_key="3", max_tokens=32)
    assert "CIRCUIT_OPEN" in (r3.get("error") or "")


def test_flock_overlap_blocks_second(tmp_path):
    from lib.agent_jobs_lock import acquire_jobs_lock, OverlapError, OVERLAP_EXIT
    lock = tmp_path / "jobs.lock"
    held = {}

    def holder():
        with acquire_jobs_lock(lock, blocking=False):
            held["ok"] = True
            time.sleep(0.4)

    t = threading.Thread(target=holder)
    t.start()
    time.sleep(0.05)
    with pytest.raises(OverlapError) as ei:
        with acquire_jobs_lock(lock, blocking=False):
            pass
    assert ei.value.exit_code == OVERLAP_EXIT
    t.join()
    # after release, acquire succeeds
    with acquire_jobs_lock(lock, blocking=False):
        pass
    assert held.get("ok")


def test_stale_lock_policy_documented():
    from lib import agent_jobs_lock as L
    assert "kernel" in L.STALE_NOTE.lower() or "advisory" in L.STALE_NOTE.lower()
    assert L.OVERLAP_EXIT == 99


def test_router_rejects_deepseek_v4_alias():
    import llm_router
    r = llm_router._call_deepseek_v4_legacy_rejected("x")
    assert r["success"] is False
    assert "LEGACY" in r["error"]


def test_router_no_local_fallback_in_agent_routes():
    import llm_router
    for table in (llm_router._TASK_ROUTING_PRE_GPU, llm_router._TASK_ROUTING_POST_GPU,
                  llm_router._HIGH_IMPACT_ROUTING):
        for task, chain in table.items():
            if task in ("agent_narrative", "agent_debate", "cio_synthesis",
                        "sector_correlation", "default"):
                assert chain == ["deepseek-flash"], (task, chain)


def test_exact_model_success_path(monkeypatch):
    from lib import agent_flash_governance as ag
    from lib import llm_consumption as lc

    monkeypatch.setattr(ag, "already_completed", lambda *a, **k: False)
    monkeypatch.setattr(ag, "circuit_open", lambda: False)
    monkeypatch.setattr("lib.agent_jobs_containment.is_contained", lambda: False)
    monkeypatch.setattr(
        lc, "get_process_config",
        lambda pid: {
            "registered": True,
            "daily_cost_cap_usd": 1.0,
            "daily_soft_cap": 100,
            "max_output_tokens": 32,
            "max_input_tokens": 64,
            "allowed_lanes": ["fast"],
        },
    )
    monkeypatch.setattr(
        "lib.consumption_run_manual.projected_max_cost_usd",
        lambda **k: 0.001,
    )
    monkeypatch.setattr(
        lc, "gate_and_generate",
        lambda *a, **k: ("OK", {
            "returned_model": "deepseek-v4-flash",
            "requested_model_id": "deepseek-v4-flash",
            "requested_policy": "FAST",
            "executed_policy": "FAST",
            "estimated_cost_usd": 1.5e-6,
            "fallback_used": False,
            "usage": {"prompt_tokens": 9, "completion_tokens": 1},
            "request_id": "req-exact",
        }),
    )
    ag.reset_run_budget()
    r = ag.governed_flash_call("Reply with exactly: OK", task_type="agent_narrative", max_tokens=32)
    assert r["success"] is True
    assert r["returned_model"] == "deepseek-v4-flash"
    assert r["provider_request_id"] == "req-exact"
    assert r["tokens"]["prompt_tokens"] == 9


def test_no_broker_authority_in_governance_module():
    src = (ROOT / "scripts/lib/agent_flash_governance.py").read_text()
    assert "place_order" not in src.lower()
    assert "schwab" not in src.lower()


def test_cost_registry_matches_estimate():
    from lib.llm_model_registry import estimate_usd_cost
    e = estimate_usd_cost(model_id="deepseek-v4-flash", prompt_tokens=1000, completion_tokens=300)
    assert e.get("estimated_cost_usd") is not None
    assert e["estimated_cost_usd"] < 0.01


def test_llm_router_source_forbids_deepseek_chat_label():
    src = (ROOT / "scripts/llm_router.py").read_text()
    assert 'model_used": "deepseek-chat"' not in src
