"""A rate-limited lane is not a dead login — and the alert must not say it is.

WORK-QUEUE item 10, 2026-11-07: ``oauth-lane-keepalive`` failed 54 runs in a row. Its receipt says

    status failed · exit 1 · summary {"checked":4,"ok":3,"regressions":["chatgpt"],"alerts":0}

and the lane status says

    chatgpt · ok false · consec_fail 54 · last_ok 2026-11-06T00:00:30Z
    detail "429 Client Error: Too Many Requests for url: http://127.0.0.1:8646/v1/chat/completions"

The proxy's own /health, read at 2026-11-07T03:53Z, says ``authenticated: true``,
``token_expired: false``, ``serving: false``, ``last_upstream.state: rate_limited``. The account's
free Codex quota is exhausted; it heals by waiting. But every failing lane got the same alert line,
``fix: hermes auth add openai-codex --type oauth`` — a credential operation aimed at the wrong cause,
repeated for 54 runs.

So the keepalive now classifies WHY a lane is down (rate_limited / auth / other), says what to do
about that cause, records the kind in the status file and the receipt, and the dry run reads the
proxy's ``serving``/``last_upstream`` instead of trusting a 200. Hermetic: fake probes, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import oauth_lane_keepalive as keep   # noqa: E402

REAL_429 = ("429 Client Error: Too Many Requests for url: "
            "http://127.0.0.1:8646/v1/chat/completions")
RELOGIN = "hermes auth add openai-codex --type oauth"


# ── 1. the classification ───────────────────────────────────────────────────

@pytest.mark.parametrize("detail", [
    REAL_429,
    "RATE_LIMITED: upstream usage limit reached",
    "HTTP 429 from upstream",
    "quota exceeded for this account",
    "rate_limit_exceeded",
])
def test_a_rate_limit_is_recognised(detail):
    assert keep._failure_kind(detail) == "rate_limited"


@pytest.mark.parametrize("detail", [
    "AUTH_EXPIRED",
    "session expired — re-login required",
    "please log in again",
    "token refresh failed",
])
def test_an_auth_problem_is_recognised(detail):
    assert keep._failure_kind(detail) == "auth"


def test_anything_else_is_unclassified():
    assert keep._failure_kind("Connection refused") == "other"
    assert keep._failure_kind("") == "other"
    assert keep._failure_kind(None) == "other"


# ── 2. the alert says the right thing ───────────────────────────────────────

def _evaluate(probe, lanes=("chatgpt",), state=None, now=1_800_000_000):
    return keep._evaluate(list(lanes), state or {}, now, probe)


# The live shape: chatgpt was healthy on 2026-11-06T00:00:30Z and had failed 53 times since.
LIVE = {"chatgpt": {"last_ok": 1_791_331_230, "consec_fail": 53, "last_alert": 0}}


def test_a_rate_limited_lane_is_not_told_to_re_login():
    alerts, out, regressions = _evaluate(lambda lane: (False, REAL_429), state=dict(LIVE))
    assert regressions == ["chatgpt"]                       # still a real failure: exit stays 1
    assert out["chatgpt"]["kind"] == "rate_limited"
    assert out["chatgpt"]["consec_fail"] == 54              # the streak keeps counting
    assert out["chatgpt"]["last_ok"] == 1_791_331_230       # last_ok is not cleared by a quota wait
    line = alerts[0]
    assert "heals on its own" in line and "Do NOT re-login" in line
    assert RELOGIN not in line                              # the wrong operator action is gone


def test_an_auth_failure_still_gets_the_re_login_command():
    alerts, out, _ = _evaluate(lambda lane: (False, "session expired — re-login required"))
    assert out["chatgpt"]["kind"] == "auth"
    assert RELOGIN in alerts[0]


def test_an_unclassified_failure_still_names_what_it_saw():
    alerts, out, _ = _evaluate(lambda lane: (False, "Connection refused"))
    assert out["chatgpt"]["kind"] == "other"
    assert "Connection refused" in alerts[0] and RELOGIN in alerts[0]


def test_a_healthy_lane_carries_no_kind_and_no_alert():
    alerts, out, regressions = _evaluate(lambda lane: (True, "rolled token (ping ok)"))
    assert alerts == [] and regressions == []
    assert "kind" not in out["chatgpt"] and out["chatgpt"]["consec_fail"] == 0


def test_the_status_record_keeps_the_kind_across_runs():
    _, out, _ = _evaluate(lambda lane: (False, REAL_429), state=dict(LIVE))
    assert out["chatgpt"]["kind"] == "rate_limited" and out["chatgpt"]["consec_fail"] == 54


# ── 3. the dry run reads serving/last_upstream instead of trusting a 200 ────

def _fake_health(monkeypatch, snap):
    from lib import oauth_lane_status as ols
    monkeypatch.setattr(ols, "_probe_health", lambda lane: snap)


def test_the_dry_run_sees_a_rate_limited_lane(monkeypatch):
    _fake_health(monkeypatch, {"lane": "chatgpt", "ready": True, "status": "ready",
                               "serving": False,
                               "last_upstream": {"state": "rate_limited", "at": "2026-11-06T22:36:40-0500"}})
    ok, detail = keep._reach_lane("chatgpt")
    assert ok is False and detail.startswith("rate_limited upstream")
    assert "no generate" in detail


def test_the_dry_run_still_passes_a_healthy_lane(monkeypatch):
    _fake_health(monkeypatch, {"lane": "chatgpt", "ready": True, "status": "ready",
                               "serving": True, "last_upstream": {"state": "ok"}})
    ok, detail = keep._reach_lane("chatgpt")
    assert ok is True and "no generate" in detail


def test_an_unready_lane_is_still_reported_by_status(monkeypatch):
    _fake_health(monkeypatch, {"lane": "chatgpt", "ready": False, "status": "session expired"})
    ok, detail = keep._reach_lane("chatgpt")
    assert ok is False and "session expired" in detail


def test_a_proxy_that_omits_serving_is_not_judged(monkeypatch):
    """Grok's /health carries neither field; a missing ``serving`` must not read as False."""
    _fake_health(monkeypatch, {"lane": "grok", "ready": True, "status": "ready"})
    ok, _ = keep._reach_lane("grok")
    assert ok is True


def test_probe_health_passes_the_upstream_verdict_through():
    """The lib adds the two fields; without them the dry run cannot tell a quota wait from a logout."""
    from lib import oauth_lane_status as ols
    import inspect
    src = inspect.getsource(ols._probe_health)
    assert '"serving": body.get("serving")' in src
    assert '"last_upstream": body.get("last_upstream")' in src
