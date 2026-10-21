"""n8n llm lanes on the governed bridge, batch 4 (2026-10-15; AGENTS.md §23.4, §23.18, §23.25; operator D10).

Lanes: run-watchlist-agent-jobs-offpeak and agent-event-router (process SET of the agent-jobs processes; the router
adds topic_ingestion for its --gaps-only ingest child), hermes-subject-enhance-dispatch (subjects -> researcher bridge
mode, process hermes_external_research). Chokepoints: llm_router.get_llm_response (bridge branch: ONE request as
lib.agent_flash_governance.process_for_task(task)), process_watchlist_agent_jobs._llm / _synthesis_llm /
_synthesis_lanes (one request / one vote, no OAuth preempt or soft fallback), hermes_subject_enhance.run (one
researcher call per subject). Same pins as batches 1-3; fixtures from tests/test_n8n_llm_bridge_routes_b1_20261015.py.

Hermetic: fake _call_bridge, poison provider modules, fake subprocess; no network, DB, key or model call.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.test_n8n_llm_bridge_routes_b1_20261015 import (  # noqa: E402,F401 -- fixtures must be in scope
    REGISTRY,
    ROUTING,
    X,
    Conn,
    Poison,
    bind,
    bridge,
    poison,
    route,
)

import hermes_subject_enhance as hse  # noqa: E402
import llm_router  # noqa: E402
import process_watchlist_agent_jobs as pwaj  # noqa: E402
from lib.agent_flash_governance import TASK_TO_PROCESS, process_for_task  # noqa: E402

from scripts.lib import governed_process_routes as R  # noqa: E402

AGENT_SET = sorted(set(TASK_TO_PROCESS.values()) | {"watchlist_cio_synthesis_cron"})
JOBS_ROUTE = {"via": "cio-governed-bridge", "process_ids": AGENT_SET}
ROUTER_ROUTE = {"via": "cio-governed-bridge", "process_ids": AGENT_SET + ["topic_ingestion"]}


@pytest.mark.parametrize("pid", AGENT_SET)
def test_agent_processes_routed_and_oauth_first(pid):
    from scripts.lib import cio_governed_model_bridge as B
    from scripts.lib.consumption_run_manual import validate_paid_cap_config

    assert R.route_for_process(pid) == ("advisory_desk", pid)
    assert B.resolve_caller("advisory_desk", pid) == pid
    row = REGISTRY[pid]
    validate_paid_cap_config(row)
    assert (
        row["tools_allowed"] is False
        and row["advisory_only"] is True
        and {"grok", "chatgpt"} <= set(row["allowed_lanes"])
    )
    rr = ROUTING[pid]
    assert [rr[k]["provider"] for k in ("primary", "secondary", "fallback")] == ["grok", "chatgpt", "deepseek"]
    assert rr["route_profile"] == B.OAUTH_FIRST_PROFILE


@pytest.mark.parametrize("route_", [JOBS_ROUTE, ROUTER_ROUTE, route("hermes_external_research")])
def test_lane_routes_validate_and_bind_the_set(route_):
    entry = {
        "lane_id": "x",
        "command": ["$PY", "x.py"],
        "lock": "/tmp/x.lock",
        "timeout_s": 60,
        "dry_run_arg": ["--dry-run"],
        "live_arg": None,
        "market_gate": False,
        "output_signal": None,
        "env_names": [],
        "llm_route": route_,
    }
    assert X.validate_entry(entry) is None
    env, _ = X.build_child_env({"PATH": "/usr/bin"}, "x", entry)
    assert env[X.LLM_BRIDGE_ENV] == "1"


# ── llm_router chokepoint ─────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def no_router_providers(monkeypatch):
    hits = []
    for name in ("_call_deepseek_flash_governed", "_call_openai", "_call_grok", "_call_anthropic"):
        monkeypatch.setattr(llm_router, name, lambda *a, _n=name, **k: hits.append(_n) or {"success": False})
    monkeypatch.setattr(
        llm_router,
        "_PROVIDERS",
        {k: (lambda *a, _k=k, **kw: hits.append(_k) or {"success": False}) for k in llm_router._PROVIDERS},
    )
    return hits


@pytest.mark.parametrize("task", ["agent_debate", "cio_synthesis", "agent_narrative", "sector_correlation"])
def test_router_on_the_bridge_is_one_request_as_the_task_process(
    task, bridge, poison, no_router_providers, monkeypatch
):
    bind(monkeypatch, JOBS_ROUTE)
    bridge.reply = "debate text"
    out = llm_router.get_llm_response(task, "prompt", max_tokens=500)
    assert out["success"] and out["response"] == "debate text" and out["provider"] == "bridge"
    assert [c["process_id"] for c in bridge.calls] == [process_for_task(task)] and no_router_providers == []


def test_router_refusal_tries_no_other_provider(bridge, poison, no_router_providers, monkeypatch):
    bind(monkeypatch, JOBS_ROUTE)
    bridge.refuse = True
    out = llm_router.get_llm_response("agent_debate", "prompt")
    assert out["success"] is False and out["error"].startswith("BRIDGE_ROUTE_REFUSED")
    assert len(bridge.calls) == 1 and no_router_providers == []


def test_router_without_the_flag_is_unchanged(bridge, no_router_providers, monkeypatch):
    for name in (X.LLM_BRIDGE_ENV, X.LLM_PROCESS_ENV, X.LLM_PROCESS_SET_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(llm_router, "_log_call", lambda *a, **k: None)
    llm_router.get_llm_response("agent_debate", "prompt")
    assert bridge.calls == [] and no_router_providers == ["_call_deepseek_flash_governed"]


# ── process_watchlist_agent_jobs ──────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def jobs(monkeypatch):
    lc = Poison("lib.llm_consumption")
    monkeypatch.setitem(sys.modules, "lib.llm_consumption", lc)
    monkeypatch.setitem(sys.modules, "llm_router", Poison("llm_router"))
    monkeypatch.setattr(pwaj, "_CURRENT_AGENT", "maria")
    yield
    assert lc.touched == [] and sys.modules["llm_router"].touched == []


@pytest.mark.parametrize("task", ["agent_narrative", "risk_review", "steph_review", "agent_debate"])
def test_agent_llm_is_one_bridge_request_no_oauth_preempt(task, jobs, bridge, poison, monkeypatch):
    bind(monkeypatch, JOBS_ROUTE)
    monkeypatch.setattr(pwaj, "_prefer_maria_oauth", lambda: pytest.fail("OAuth preempt reached"))
    bridge.reply = "Maria narrative: catalyst confirmed."
    assert pwaj._llm("prompt /no_think", task_type=task) == "Maria narrative: catalyst confirmed."
    assert bridge.calls == [{"process_id": process_for_task(task), "timeout_s": 180, "prompt": "prompt "}]
    assert pwaj._llm._last_model == "governed-bridge"


def test_agent_llm_refusal_is_an_llm_error(jobs, bridge, poison, monkeypatch):
    bind(monkeypatch, JOBS_ROUTE)
    bridge.refuse = True
    out = pwaj._llm("prompt", task_type="agent_narrative")
    assert out.startswith("LLM error: BRIDGE_ROUTE_REFUSED") and len(bridge.calls) == 1


def test_synthesis_llm_has_no_grok_fallback_on_the_bridge(jobs, bridge, poison, monkeypatch):
    bind(monkeypatch, JOBS_ROUTE)
    bridge.refuse = True
    assert pwaj._synthesis_llm("prompt").startswith("LLM error")
    assert [c["process_id"] for c in bridge.calls] == [process_for_task("cio_synthesis")]


def test_cio_synthesis_is_one_vote_never_a_consensus(jobs, bridge, poison, monkeypatch):
    bind(monkeypatch, JOBS_ROUTE)
    bridge.reply = json.dumps({"recommendation": "HOLD", "confidence": 0.6})
    monkeypatch.setattr(pwaj, "_rec_from", lambda raw: ("HOLD", 0.6))
    raw, meta = pwaj._synthesis_lanes("prompt", lanes=("grok", "chatgpt", "deepseek-flash"))
    assert meta["participating_lanes"] == ["bridge"] and meta["consensus"] == "HOLD"
    assert meta["agree"] is None and meta["majority"] is False and meta["consensus_kind"] == "single"
    assert [c["process_id"] for c in bridge.calls] == ["watchlist_cio_synthesis_cron"]


def test_cio_synthesis_refusal(jobs, bridge, poison, monkeypatch):
    bind(monkeypatch, JOBS_ROUTE)
    bridge.refuse = True
    raw, meta = pwaj._synthesis_lanes("prompt", manual_trigger=True)
    assert raw.startswith("LLM error: BRIDGE_ROUTE_REFUSED") and meta["consensus"] is None
    assert [c["process_id"] for c in bridge.calls] == ["watchlist_cio_synthesis_cron"]


def test_agent_jobs_runner_dry_run_is_offline(bridge):
    import subprocess

    r = subprocess.run(
        ["bash", str(ROOT / "scripts/run_watchlist_agent_jobs_offpeak.sh"), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=60,
        env={"PATH": "/usr/bin:/bin", X.LLM_BRIDGE_ENV: "1"},
    )
    assert r.returncode == 0 and r.stdout.startswith("DRY-RUN run-watchlist-agent-jobs-offpeak") and bridge.calls == []


def test_event_router_dry_run_processes_no_job(monkeypatch, bridge, poison):
    import agent_event_router as aer

    bind(monkeypatch, ROUTER_ROUTE)
    src = (ROOT / "scripts/agent_event_router.py").read_text()
    # every model-reaching step in drain_queue is behind `not dry_run`
    for step in (
        "process_created_jobs(conn, job_ids)",
        "handle_content_gap(conn, event)",
        "handle_sec_debate(conn, event)",
        "detect_sector_correlation(all_symbols)",
    ):
        i = src.index(step)
        assert "not dry_run" in src[max(0, i - 400) : i], step
    monkeypatch.setattr(aer, "process_created_jobs", lambda *a: pytest.fail("job processing in a dry run"))
    assert bridge.calls == []


# ── hermes-subject-enhance-dispatch ───────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def subjects(monkeypatch):
    spawned = []
    monkeypatch.setattr(hse, "_conn", lambda: Conn())
    monkeypatch.setitem(
        hse.GATHERERS,
        "position",
        lambda conn, limit: [{"key": "AAA", "question": "q"}, {"key": "BBB", "question": "q"}],
    )
    monkeypatch.setattr(hse, "_recent", lambda conn, key, lane, ttype: False)
    monkeypatch.setattr(
        hse.subprocess, "run", lambda argv, **k: spawned.append((argv, k)) or types.SimpleNamespace(returncode=0)
    )
    return spawned


def test_subject_enhance_one_researcher_call_per_subject(subjects, bridge, poison, monkeypatch):
    bind(monkeypatch, route("hermes_external_research"))
    rep = hse.run("position", ("grok", "chatgpt"), apply=True)
    assert rep["lanes"] == ["grok"] and rep["called"] == 2 and len(subjects) == 2
    assert all("env" not in kw for _a, kw in subjects)  # inherits the binding


def test_subject_enhance_cron_fan_out_unchanged(subjects, bridge, monkeypatch):
    for name in (X.LLM_BRIDGE_ENV, X.LLM_PROCESS_ENV, X.LLM_PROCESS_SET_ENV):
        monkeypatch.delenv(name, raising=False)
    assert hse.run("position", ("grok", "chatgpt"), apply=True)["called"] == 4


def test_subject_enhance_preview_calls_nothing(subjects, bridge, poison, monkeypatch):
    bind(monkeypatch, route("hermes_external_research"))
    assert hse.run("position", ("grok",), apply=False)["called"] == 0 and subjects == []


def test_subject_dispatch_env_reaches_the_children():
    src = (ROOT / "scripts/hermes_subject_enhance_dispatch.py").read_text()
    assert "env = dict(os.environ)" in src  # the executor's binding is copied into every subject child


def test_registered_in_the_cio_hardening_gates():
    text = (ROOT / "scripts" / "run_cio_hardening_ci.py").read_text(encoding="utf-8")
    assert "tests/test_n8n_llm_bridge_routes_b4_20261015.py" in text
