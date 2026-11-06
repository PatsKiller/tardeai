"""Injection triage 1 (2026-11-06): no request, store or file value reaches a shell.

ANCHOR: INJECTION_TRIAGE_1_20261106

Hermetic: subprocess is replaced by a spy; nothing runs, nothing is written, no network.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.yaml_apply_command import yaml_apply_argv  # noqa: E402

HOSTILE = "sug_001; touch /tmp/x"


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- POST /api/yaml-apply ---------------------------------------------------------------------------------------


def test_yaml_apply_ids_become_separate_arguments():
    argv = yaml_apply_argv("/py", "/w.py", ["sug_001", "sug_002"], "/root")
    assert argv == ["/py", "/w.py", "--apply", "sug_001", "sug_002", "--project-root", "/root"]


@pytest.mark.parametrize("ids", [
    [HOSTILE], ["$(id)"], ["a`id`"], ["a|b"], ["a b"], ["--rollback"], ["-x"], [""], [7], [None],
])
def test_yaml_apply_refuses_any_id_with_shell_syntax_or_an_option_shape(ids):
    with pytest.raises(ValueError):
        yaml_apply_argv("/py", "/w.py", ids, "/root")


@pytest.mark.parametrize("ids", [[], None, "sug_001", {"a": 1}, ["s"] * 201])
def test_yaml_apply_refuses_a_body_that_is_not_a_bounded_list(ids):
    with pytest.raises(ValueError):
        yaml_apply_argv("/py", "/w.py", ids, "/root")


def test_the_server_handler_uses_the_validated_argv_and_no_shell():
    import ast
    tree = ast.parse((ROOT / "scripts/portfolio_server.py").read_text(encoding="utf-8"))
    shell_calls = [
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Call) and any(
            k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True for k in n.keywords)
    ]
    assert shell_calls == [], f"portfolio_server.py still calls a shell at lines {shell_calls}"


# ---- stop-monitoring remediation ----------------------------------------------------------------------------------


def test_stop_health_symbols_never_reach_a_shell(monkeypatch):
    smh = _load("scripts/lib/stop_monitoring_health.py", "smh_injection_triage")
    calls = []

    def spy(argv, **kw):
        calls.append((argv, kw))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(smh.subprocess, "run", spy)
    monkeypatch.setattr(smh, "_fixes_today", lambda conn: 0)
    monkeypatch.setattr(smh, "_log_fix", lambda *a, **k: None)
    monkeypatch.setattr(smh, "_is_market_hours_et", lambda: False)
    boom = types.ModuleType("stop_lifecycle_monitor")

    def _no_scan(**_k):
        raise RuntimeError("not in this test")

    boom.scan = _no_scan
    monkeypatch.setitem(sys.modules, "stop_lifecycle_monitor", boom)

    out = smh.remediate({"stale_advisories": [HOSTILE], "issues": []}, conn=None)
    advisor = [c for c in calls if "scripts/holding_protection_advisor.py" in c[0]]
    assert advisor, (out, calls)
    argv, kw = advisor[0]
    assert isinstance(argv, list) and not kw.get("shell")
    assert argv[argv.index("--symbols") + 1] == HOSTILE  # one argument, never parsed by a shell


# ---- a1a compliance -------------------------------------------------------------------------------------------------


def test_a1a_git_runs_without_a_shell(monkeypatch):
    a1a = _load("scripts/check_a1a_compliance.py", "a1a_injection_triage")
    seen = []

    def spy(argv, **kw):
        seen.append((argv, kw))
        return b"ok\n"

    monkeypatch.setattr(a1a.subprocess, "check_output", spy)
    assert a1a._git("diff --name-only abc1234~1 abc1234") == "ok"
    argv, kw = seen[0]
    assert argv == ["git", "diff", "--name-only", "abc1234~1", "abc1234"] and not kw.get("shell")


def test_this_file_is_registered_in_a_ci_gate():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.lib import ci_gates  # noqa: PLC0415 -- needs ROOT on sys.path first

    assert "tests/test_injection_triage_1_20261106.py" in ci_gates.registry_text(ROOT)
