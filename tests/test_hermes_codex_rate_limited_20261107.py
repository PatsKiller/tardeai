"""A ChatGPT OAuth quota refusal must be reported as rate limiting, never as a re-auth failure.

Live shape (2026-11-06, `hermes-deep-research-local.service`, every tick 22:00-05:35 ET): the OAuth proxy at
:8646 answered ``/health`` with ``authenticated: true, token_expired: false`` and
``last_upstream.state: "rate_limited"``. The proxy POST carried the upstream refusal, `raise_for_status()`
raised, `_call_codex_proxy` swallowed it into ``None``, `call_codex_cli` fell through to the CLI (the same
OAuth session) and raised ``CODEX_HEADLESS_UNAVAILABLE … re-login``. The lane then printed
``FAILED (CODEX_HEADLESS_UNAVAILABLE: openai-codex is authed but did not finalize a respon)`` for all three
targets, exited 1 and had its row graded RUN_FAILED — an operator reading it would re-authenticate a session
that was never logged out.

Synthetic fixtures only: no network, no credential, no live lane.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_external_researcher as H  # noqa: E402


class _Resp:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = {} if body is None else body
        self.text = text

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _install_proxy(monkeypatch, *, health=None, post=None, sent=None):
    """Stand in for the `requests` module the proxy path imports inside itself."""

    def _get(url, timeout=0):
        return _Resp(200, health if health is not None else {"authenticated": True, "token_expired": False})

    def _post(url, json=None, timeout=0):
        if sent is not None:
            sent.append({"url": url, "json": json, "timeout": timeout})
        return post

    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=_get, post=_post))


def _forbid_cli(monkeypatch):
    def _boom():
        raise AssertionError("the pseudo-TTY CLI fallback must not be attempted on a rate limit")

    monkeypatch.setattr(H, "_codex_authed", _boom)


def test_a_429_from_the_proxy_is_rate_limiting_with_the_proxy_explanation(monkeypatch):
    _install_proxy(
        monkeypatch,
        post=_Resp(429, {"detail": "upstream 429: usage limit reached (session 20261106_223029_87da6c)"}),
    )
    with pytest.raises(H.CodexRateLimited) as exc:
        H._call_codex_proxy("gpt-5.4", "synthetic prompt")
    assert "usage limit reached" in str(exc.value)
    assert "session 20261106_223029_87da6c" in str(exc.value)


def test_the_generic_unreachable_proxy_path_is_untouched(monkeypatch):
    """A 401 stays the auth path (None → CLI/auth hint); a 5xx stays the generic fallback path."""
    for status in (401, 503):
        _install_proxy(monkeypatch, post=_Resp(status, {"detail": "nope"}))
        assert H._call_codex_proxy("gpt-5.4", "synthetic prompt") is None


def test_a_healthy_answer_still_comes_back_even_if_the_last_upstream_was_rate_limited(monkeypatch):
    """`last_upstream` is history: it must explain an empty answer, never veto a real one."""
    _install_proxy(
        monkeypatch,
        health={"authenticated": True, "last_upstream": {"state": "rate_limited", "detail": "older event"}},
        post=_Resp(200, {"choices": [{"message": {"content": "synthetic report"}}]}),
    )
    assert H._call_codex_proxy("gpt-5.4", "synthetic prompt") == "synthetic report"


def test_an_empty_answer_while_the_upstream_says_rate_limited_is_rate_limiting(monkeypatch):
    _install_proxy(
        monkeypatch,
        health={
            "authenticated": True,
            "token_expired": False,
            "last_upstream": {"state": "rate_limited", "detail": "session_id: synthetic"},
        },
        post=_Resp(200, {"choices": []}),
    )
    with pytest.raises(H.CodexRateLimited) as exc:
        H._call_codex_proxy("gpt-5.4", "synthetic prompt")
    assert "rate_limited" in str(exc.value)


def test_call_codex_cli_names_rate_limiting_keeps_the_lane_failure_class_and_skips_the_cli(monkeypatch):
    _install_proxy(monkeypatch, post=_Resp(429, {"detail": "upstream 429"}))
    _forbid_cli(monkeypatch)
    with pytest.raises(RuntimeError) as exc:
        H.call_codex_cli("gpt-5.4", "synthetic prompt")
    msg = str(exc.value)
    assert msg.startswith("CODEX_UNAVAILABLE_RATE_LIMITED:")
    assert "re-login will not help" in msg
    # The researcher classifies by token: "AUTH_PENDING" → auth_pending, "UNAVAILABLE" → unavailable,
    # everything else → error (scripts/hermes_external_researcher.py, the run-lane status mapping).
    # A quota refusal must stay a lane-level failure, so the token must remain present.
    assert "UNAVAILABLE" in msg and "AUTH_PENDING" not in msg
    assert isinstance(exc.value.__cause__, H.CodexRateLimited)
