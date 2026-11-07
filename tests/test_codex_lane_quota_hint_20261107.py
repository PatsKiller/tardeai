"""ANCHOR: CODEX_LANE_QUOTA_HINT_20261107 — a quota wall is not an auth failure.

QUALITY ROUND 2 item 13 (hermes-deep-research-local, FAILED 13 runs in a row, 2026-11-05 22:35 →
2026-11-06 22:36). Every row of every run logged the same line:

    SPRC: FAILED (CODEX_HEADLESS_UNAVAILABLE: openai-codex is authed but did not finalize a
                 response even under a pseudo-TTY (proxy at :8646 also unavailable — re-login:
                 hermes auth add openai-codex --type oauth).)

The session was not the problem. The lane's own keepalive had been recording the truth for 28 hours:
``data/runtime/oauth_lane_status.json`` → ``chatgpt: {ok: false, kind: rate_limited, detail: "429
Client Error: Too Many Requests …", consec_fail: 56}``. The ChatGPT OAuth proxy is authenticated and
serving; its *upstream* answers 429, so ``_call_codex_proxy`` returns no content, the pseudo-TTY CLI
fallback (15-240 s per call) runs against the same rate-limited session, produces nothing, and the
empty output is reported as "re-login", which no operator action can fix and which the item-10 lane
fix (2026-11-07) already stopped doing one lane over.

This file pins: before the CLI fallback and before any re-login hint, the fresh lane verdict is read;
a quota wall is raised as CODEX_UNAVAILABLE_RATE_LIMITED, the CLI is not attempted, and the hint is
gone. A stale, absent, unparseable or unrelated verdict changes nothing. Synthetic fixtures only:
no network, no proxy, no CLI, no OAuth session, no quota spent.
"""
from __future__ import annotations

import json
import subprocess as sp
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_external_researcher as R  # noqa: E402


def _state(tmp_path: Path, **row) -> Path:
    path = tmp_path / "oauth_lane_status.json"
    body = {"chatgpt": {"lane": "chatgpt", "ok": False, "kind": "rate_limited",
                        "detail": "429 Client Error: Too Many Requests for url: "
                                  "http://127.0.0.1:8646/v1/chat/completions",
                        "last_check": int(time.time()), "consec_fail": 56}}
    body["chatgpt"].update(row)
    path.write_text(json.dumps(body))
    return path


@pytest.fixture()
def no_cli(monkeypatch):
    """Any attempt to reach the pseudo-TTY CLI is a failure of this module's contract."""
    calls = []

    def _boom(*a, **kw):
        calls.append(a)
        raise AssertionError("the pseudo-TTY CLI must not be attempted once the lane says rate_limited")

    monkeypatch.setattr(sp, "run", _boom)
    return calls


def test_a_rate_limited_lane_is_reported_as_a_quota_wall_not_a_login_problem(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "OAUTH_LANE_STATUS", _state(tmp_path))
    monkeypatch.setattr(R, "_call_codex_proxy", lambda model, prompt: None)
    with pytest.raises(RuntimeError) as exc:
        R.call_codex_cli("gpt-5.4", "prompt")
    msg = str(exc.value)
    assert "CODEX_UNAVAILABLE_RATE_LIMITED" in msg
    assert "re-login will not help" in msg.lower()
    assert "hermes auth add" not in msg          # the wrong ask is gone
    assert "429" in msg and "56 consecutive" in msg


def test_the_cli_fallback_is_not_burned_on_a_quota_wall(tmp_path, monkeypatch, no_cli):
    monkeypatch.setattr(R, "OAUTH_LANE_STATUS", _state(tmp_path))
    monkeypatch.setattr(R, "_call_codex_proxy", lambda model, prompt: None)
    with pytest.raises(RuntimeError):
        R.call_codex_cli("gpt-5.4", "prompt")
    assert no_cli == []


def test_the_same_verdict_covers_a_silent_cli(tmp_path, monkeypatch):
    """If the CLI was attempted (state looked healthy then), its silence is still judged by the state."""
    monkeypatch.setattr(R, "OAUTH_LANE_STATUS", _state(tmp_path))
    monkeypatch.setattr(R, "_call_codex_proxy", lambda model, prompt: None)
    monkeypatch.setattr(R, "_codex_authed", lambda: True)
    # Let the first (pre-CLI) check pass by making the state look healthy at that moment only.
    real = R._chatgpt_lane_rate_limited
    state = {"n": 0}

    def _once(now=None):
        state["n"] += 1
        return None if state["n"] == 1 else real(now)

    monkeypatch.setattr(R, "_chatgpt_lane_rate_limited", _once)
    monkeypatch.setattr(R, "_account_from_env", lambda *a, **kw: None)

    class _Done:
        stdout = "no final response"
        returncode = 1

    monkeypatch.setattr(sp, "run", lambda *a, **kw: _Done())
    with pytest.raises(RuntimeError) as exc:
        R.call_codex_cli("gpt-5.4", "prompt")
    assert "CODEX_UNAVAILABLE_RATE_LIMITED" in str(exc.value)
    assert "hermes auth add" not in str(exc.value)


# ── anything but a fresh quota verdict changes nothing ───────────────────────


def test_a_stale_verdict_is_not_a_quota_wall(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "OAUTH_LANE_STATUS", _state(tmp_path, last_check=int(time.time()) - 3 * 3600))
    monkeypatch.setattr(R, "_call_codex_proxy", lambda model, prompt: None)
    monkeypatch.setattr(R, "_codex_authed", lambda: False)
    with pytest.raises(RuntimeError) as exc:
        R.call_codex_cli("gpt-5.4", "prompt")
    assert "AUTH_PENDING" in str(exc.value)      # the login really is the next question here


def test_another_kind_is_not_a_quota_wall(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "OAUTH_LANE_STATUS", _state(tmp_path, kind="auth_expired"))
    monkeypatch.setattr(R, "_call_codex_proxy", lambda model, prompt: None)
    monkeypatch.setattr(R, "_codex_authed", lambda: False)
    with pytest.raises(RuntimeError) as exc:
        R.call_codex_cli("gpt-5.4", "prompt")
    assert "AUTH_PENDING" in str(exc.value)


def test_a_missing_status_file_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "OAUTH_LANE_STATUS", tmp_path / "absent.json")
    assert R._chatgpt_lane_rate_limited() is None


def test_an_unparseable_status_file_changes_nothing(tmp_path, monkeypatch):
    path = tmp_path / "broken.json"
    path.write_text("{not json")
    monkeypatch.setattr(R, "OAUTH_LANE_STATUS", path)
    assert R._chatgpt_lane_rate_limited() is None


def test_a_verdict_with_no_timestamp_is_not_trusted(tmp_path, monkeypatch):
    path = tmp_path / "no_clock.json"
    path.write_text(json.dumps({"chatgpt": {"kind": "rate_limited", "detail": "429"}}))
    monkeypatch.setattr(R, "OAUTH_LANE_STATUS", path)
    assert R._chatgpt_lane_rate_limited() is None


# ── the healthy path is untouched ───────────────────────────────────────────


def test_a_working_proxy_still_returns_its_content(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "OAUTH_LANE_STATUS", _state(tmp_path))
    monkeypatch.setattr(R, "_call_codex_proxy", lambda model, prompt: "the answer")
    assert R.call_codex_cli("gpt-5.4", "prompt") == "the answer"


def test_the_proxy_429_path_is_unchanged(monkeypatch):
    def _limited(model, prompt):
        raise R.CodexRateLimited("429 from upstream")

    monkeypatch.setattr(R, "_call_codex_proxy", _limited)
    with pytest.raises(RuntimeError) as exc:
        R.call_codex_cli("gpt-5.4", "prompt")
    assert "CODEX_UNAVAILABLE_RATE_LIMITED" in str(exc.value)
