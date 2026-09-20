"""enrich-all must not hand an LLM-spending child an unset global cap.

The pipeline at /api/v2/paper-proposals/enrich-all spawns the watchlist agent worker
(and six other scripts) as subprocesses. It passed no env, so the children inherited
whatever portfolio-server.service happened to carry. When LLM_GLOBAL_DAILY_USD_CAP was
absent there, every governed call failed COST_CONFIGURATION_INVALID and eight of them
opened the agent_flash circuit breaker for 900s — which also blocked the healthy cron
drains that had the cap set correctly.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

API_V2 = ROOT / "scripts" / "api_v2.py"


def _extract_governed_child_env():
    """Pull _governed_child_env out of api_v2 without importing the whole server."""
    tree = ast.parse(API_V2.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_governed_child_env":
            module = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(module)
            ns: dict = {"os": os, "PROJECT_ROOT": ROOT}
            exec(compile(module, str(API_V2), "exec"), ns)  # noqa: S102
            return ns["_governed_child_env"]
    raise AssertionError("_governed_child_env not found in api_v2.py")


@pytest.fixture()
def governed_child_env():
    return _extract_governed_child_env()


def test_inherited_cap_is_kept(governed_child_env, monkeypatch):
    monkeypatch.setenv("LLM_GLOBAL_DAILY_USD_CAP", "2.00")
    env, reason = governed_child_env()
    assert reason is None
    assert env["LLM_GLOBAL_DAILY_USD_CAP"] == "2.00"


def test_missing_cap_is_resolved_from_host_cap_file(governed_child_env, monkeypatch):
    monkeypatch.delenv("LLM_GLOBAL_DAILY_USD_CAP", raising=False)
    env, reason = governed_child_env()
    if env is None:  # host without the cap file — must fail closed, not run uncapped
        assert "cap" in reason.lower()
        return
    assert float(env["LLM_GLOBAL_DAILY_USD_CAP"]) > 0


@pytest.mark.parametrize("bad", ["", "abc", "0", "-1"])
def test_malformed_inherited_cap_is_not_passed_through(governed_child_env, monkeypatch, bad):
    monkeypatch.setenv("LLM_GLOBAL_DAILY_USD_CAP", bad)
    env, reason = governed_child_env()
    if env is None:
        assert reason
        return
    assert float(env["LLM_GLOBAL_DAILY_USD_CAP"]) > 0, "a child must never inherit a dead cap"


def test_fails_closed_when_no_cap_anywhere(governed_child_env, monkeypatch):
    monkeypatch.delenv("LLM_GLOBAL_DAILY_USD_CAP", raising=False)
    import lib.llm_spend as llm_spend

    monkeypatch.setattr(llm_spend, "configured_global_cap", lambda: None)
    env, reason = governed_child_env()
    assert env is None and reason, "no cap anywhere must skip the steps, not run them uncapped"


def test_pipeline_passes_the_env_and_skips_when_unresolved():
    src = API_V2.read_text(encoding="utf-8")
    assert "env=child_env," in src, "subprocess must receive the resolved env"
    assert 'results[key] = f"skipped: {env_reason}"' in src, "steps must be skipped, not run"
