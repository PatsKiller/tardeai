"""Offline regressions for the shared blockers in the 119-lane completion train."""
from __future__ import annotations

import ast
import importlib
import sys
import types
from pathlib import Path

import pytest

from scripts.lib import governed_process_routes as routes
from scripts.lib import llm_bridge_route as bridge
from scripts import n8n_run_executor as executor

ROOT = Path(__file__).resolve().parents[1]
PROCESS = "hermes_usefulness_score"


def test_client_route_snapshot_matches_authoritative_server_maps():
    """The server keeps authority; a stale client route must fail CI."""
    tree = ast.parse((ROOT / "scripts/lib/cio_governed_model_bridge.py").read_text())
    values = {
        node.target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        and node.target.id in {"CALLER_PROCESS_MAP", "CALLER_TASK_PROCESS_MAP"}
    }
    assert values["CALLER_PROCESS_MAP"] == routes.CALLER_PROCESS_MAP
    assert values["CALLER_TASK_PROCESS_MAP"] == routes.CALLER_TASK_PROCESS_MAP


def test_named_process_selects_existing_server_route(monkeypatch):
    from scripts.lib import n8n_model_job
    calls = []
    monkeypatch.setattr(n8n_model_job, "bridge_governed_call", lambda *a, **kw: calls.append(kw) or {})
    bridge._call_bridge([], process_id=PROCESS, timeout_s=3)
    assert calls[0]["caller"] == "advisory_desk"
    assert calls[0]["task_type"] == "usefulness_score"
    assert calls[0]["process_id"] == PROCESS


def test_unmapped_process_never_calls_transport(monkeypatch):
    monkeypatch.setattr(bridge, "_call_bridge", lambda *a, **kw: pytest.fail("transport reached"))
    assert bridge.text_via_bridge("unknown_process", "fixture") is None


@pytest.mark.parametrize("governance", [None, {}, {"governance_pass": False},
    {"governance_pass": True, "process_id": "n8n_material_digest_draft", "mock": True},
    {"governance_pass": True, "process_id": PROCESS}])
def test_missing_or_wrong_identity_cannot_be_consumed(monkeypatch, governance):
    result = {"choices": [{"message": {"content": "fixture"}}]}
    if governance is not None:
        result["_tradeai"] = governance
    monkeypatch.setattr(bridge, "_call_bridge", lambda *a, **kw: result)
    assert bridge.text_via_bridge(PROCESS, "fixture") is None


def test_exact_governed_response_is_accepted(monkeypatch):
    result = {"choices": [{"message": {"content": "fixture"}}], "_tradeai": {
        "governance_pass": True, "process_id": PROCESS, "reservation_id": "fake-reservation"}}
    monkeypatch.setattr(bridge, "_call_bridge", lambda *a, **kw: result)
    assert bridge.text_via_bridge(PROCESS, "fixture") == "fixture"


def test_executor_binding_refuses_another_process_before_transport(monkeypatch):
    monkeypatch.setenv("TRADEAI_LLM_PROCESS_ID", PROCESS)
    monkeypatch.setattr(bridge, "_call_bridge", lambda *a, **kw: pytest.fail("transport reached"))
    assert bridge.text_via_bridge("n8n_material_digest_draft", "fixture") is None


@pytest.mark.parametrize("mode", ["off", "report", "enforce"])
def test_executor_binds_validated_route_in_every_environment_mode(mode):
    original = {"PATH": "/fixture/bin", executor.ENV_ALLOWLIST_MODE_ENV: mode}
    entry = {"env_names": [], "llm_route": {"via": "cio-governed-bridge", "process_id": PROCESS}}
    child, evidence = executor.build_child_env(original, "fixture-lane", entry)
    assert child[executor.LLM_BRIDGE_ENV] == "1"
    assert child[executor.LLM_PROCESS_ENV] == PROCESS
    assert evidence["effective_mode"] == mode
    assert executor.LLM_BRIDGE_ENV not in original


def test_executor_refuses_unmapped_route_before_spawn():
    child, evidence = executor.build_child_env({}, "fixture-lane", {
        "llm_route": {"via": "cio-governed-bridge", "process_id": "unknown_process"}})
    assert child is None
    assert evidence["reason"] == "llm_process_route_not_registered"


@pytest.mark.parametrize("module_name", ["scripts.session13_db", "scripts.pipeline_registry"])
def test_shared_database_import_does_not_load_credentials(monkeypatch, module_name):
    from scripts.lib import env_bootstrap
    monkeypatch.setattr(env_bootstrap, "load_env", lambda *a, **kw: pytest.fail("loader reached on import"))
    module = importlib.import_module(module_name)
    importlib.reload(module)


def test_session_db_connection_loads_only_named_configuration(monkeypatch):
    from scripts.lib import env_bootstrap
    module = importlib.import_module("scripts.session13_db")
    calls = []
    monkeypatch.setattr(env_bootstrap, "load_env", lambda **kw: calls.append(kw) or {})
    monkeypatch.setenv("DB_PASSWORD", "synthetic-password")
    fake = types.ModuleType("psycopg2")
    fake.connect = lambda **kw: kw
    monkeypatch.setitem(sys.modules, "psycopg2", fake)
    result = module.get_conn()
    assert set(calls[0]["names"]) == {"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"}
    assert result["password"] == "synthetic-password"


def test_agent_preview_never_imports_operator_backend(monkeypatch, capsys):
    from scripts.agent_runtime.agents import run_once
    monkeypatch.setenv("AGENT_RUNTIME_QUEUE_MODULE", "must_not_import")
    assert run_once.main(["--agent", "sentinel", "--once", "--dry-run"]) == 0
    assert "must_not_import" not in sys.modules
    assert "DRY-RUN" in capsys.readouterr().out


def test_agent_preview_rejects_abbreviated_flags():
    from scripts.agent_runtime.agents import run_once
    with pytest.raises(SystemExit) as error:
        run_once.main(["--agent", "sentinel", "--dry"])
    assert error.value.code == 2
