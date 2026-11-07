"""LQ-20261107-257: the grok and chatgpt OAuth proxies run hermes under the Trade AI profile.

Without ``-p``, hermes applies its default SOUL, which refuses trade research; 41 of 62 grok research rows
on 2026-11-07 were rejected as ``llm_refusal`` for that reason. These tests pin the argv, the env override,
the profile-scoped /health credential path and the re-login hint. Synthetic only: subprocess is faked, no
hermes, no network, no credential file is opened.

COVERS = ["scripts/grok_oauth_proxy.py", "scripts/chatgpt_oauth_proxy.py"]
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

PROXIES = [
    ("grok_oauth_proxy", "GROK_PROXY_HERMES_PROFILE", "_run_grok", "xai-oauth"),
    ("chatgpt_oauth_proxy", "CHATGPT_PROXY_HERMES_PROFILE", "_run_codex", "openai-codex"),
]


def _load(monkeypatch, name, env, value):
    if value is None:
        monkeypatch.delenv(env, raising=False)
    else:
        monkeypatch.setenv(env, value)
    mod = importlib.import_module(name)
    return importlib.reload(mod)


@pytest.fixture(autouse=True)
def _restore_modules():
    yield
    for name, *_ in PROXIES:  # leave the default-configured module behind for other tests
        if name in sys.modules:
            importlib.reload(sys.modules[name])


def _capture(monkeypatch, out="A synthetic answer about ZZZT."):
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, out + "\nsession_id: s-1\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


@pytest.mark.parametrize(("name", "env", "fn", "provider"), PROXIES)
def test_hermes_runs_under_the_tradeai_profile_by_default(monkeypatch, name, env, fn, provider):
    mod = _load(monkeypatch, name, env, None)
    calls = _capture(monkeypatch)
    assert getattr(mod, fn)("synthetic prompt", "model-x") == "A synthetic answer about ZZZT."
    [argv] = calls
    assert argv[1:4] == ["-p", "tradeai", "chat"], "the profile flag must precede the subcommand"
    assert argv[argv.index("--provider") + 1] == provider
    assert argv[argv.index("-m") + 1] == "model-x"


@pytest.mark.parametrize(("name", "env", "fn", "provider"), PROXIES)
def test_the_profile_is_env_overridable_and_empty_means_the_hermes_default(monkeypatch, name, env, fn, provider):
    mod = _load(monkeypatch, name, env, "example-profile")
    calls = _capture(monkeypatch)
    getattr(mod, fn)("p", "m")
    assert calls[-1][1:4] == ["-p", "example-profile", "chat"]

    mod = _load(monkeypatch, name, env, "  ")
    calls = _capture(monkeypatch)
    getattr(mod, fn)("p", "m")
    assert calls[-1][1] == "chat" and "-p" not in calls[-1]
    assert mod.AUTH_JSON.endswith("/.hermes/auth.json")


@pytest.mark.parametrize(("name", "env", "fn", "provider"), PROXIES)
def test_health_and_relogin_name_the_same_profile_the_calls_use(monkeypatch, name, env, fn, provider):
    mod = _load(monkeypatch, name, env, None)
    assert mod.AUTH_JSON.endswith("/.hermes/profiles/tradeai/auth.json")
    assert mod._RELOGIN.startswith(f"hermes -p tradeai auth add {provider} --type oauth")


@pytest.mark.parametrize(("name", "env", "fn", "provider"), PROXIES)
def test_an_auth_failure_is_still_detected_under_the_profile(monkeypatch, name, env, fn, provider):
    mod = _load(monkeypatch, name, env, None)
    _capture(monkeypatch, out="Your session has ended. Please log in again.")
    if hasattr(mod, "_note_upstream"):
        monkeypatch.setattr(mod, "_note_upstream", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="AUTH_EXPIRED"):
        getattr(mod, fn)("p", "m")
