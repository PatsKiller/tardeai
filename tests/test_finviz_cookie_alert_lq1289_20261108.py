"""One operator alert per ET day while FINVIZ_COOKIE is dead (LQ-20261107-1289).

ANCHOR: FINVIZ_COOKIE_ALERT_LQ1289_20261108

2026-11-08: the operator got no Telegram and no text when the Finviz session cookie expired,
because a dead cookie with a working Elite API token was graded healthy. This covers the alert
module beside that change: the verdict→state mapping, at most one Telegram plus one email-to-text
per New York calendar day, the durable dedupe file, and the rule that no address reaches disk.

Every test injects `state_path` under tmp_path, `gateways=` synthetic addresses and a `send=`
recorder. Nothing here loads the operator contact file, reaches the communications gateway, or
writes the real persistent root. Pure: no network, no DB.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import finviz_cookie_alert as fca  # noqa: E402
from lib import finviz_cookie_features as fcf  # noqa: E402

FI = "fi-number@example.invalid"  # synthetic, unroutable by design


def _verdict(**over) -> dict:
    doc = {
        "ok": True,
        "status": "token_ok",
        "cookie_status": "expired",
        "severity": "amber",
        "degraded_features": fcf.labels(),
        "degraded_count": len(fcf.labels()),
        "show_banner": True,
        "detail": "cookie: login page or empty export; token: 37 screener rows",
    }
    doc.update(over)
    return doc


class _Fake:
    """Records each gateway call; the shape `send_via_gateway` returns, minus the address."""

    def __init__(self, delivered: bool = True):
        self.calls: list[dict] = []
        self.delivered = delivered

    def __call__(self, channel, *, body, subject, to, subject_key):
        self.calls.append({"channel": channel, "body": body, "subject": subject, "to": to,
                           "subject_key": subject_key})
        return {"ok": True, "delivered": self.delivered, "gateway_mode": "shadow"}


@pytest.fixture(autouse=True)
def _alert_switch_on(monkeypatch):
    """conftest disables the alert for every test; a test of the alert switches it back on."""
    monkeypatch.delenv(fca.DISABLE_ENV, raising=False)
    monkeypatch.delenv(fca.STATE_ENV, raising=False)


def _state(tmp_path: Path) -> Path:
    return tmp_path / "finviz_cookie_alert_state.json"


# ---------------------------------------------------------------- verdict mapping

@pytest.mark.parametrize("health, expected", [
    ({"cookie_status": "ok", "status": "token_ok"}, "ok"),
    ({"cookie_status": "expired", "status": "ok"}, "expired"),
    ({"cookie_status": "missing", "status": "ok"}, "missing"),
    ({"status": "token_ok"}, "expired"),
    ({"status": "ok"}, "ok"),
    ({"status": "expired"}, "expired"),
    ({"status": "error"}, "expired"),
    ({"status": "check_failed"}, "expired"),
    ({"status": "missing"}, "missing"),
    ({"status": "something_new"}, "unknown"),
    ({}, "unknown"),
    (None, "unknown"),
])
def test_cookie_state_mapping(health, expected):
    assert fca.cookie_state(health) == expected


def test_an_unknown_verdict_never_alerts(tmp_path):
    send = _Fake()
    out = fca.maybe_alert({}, state_path=_state(tmp_path), gateways=[FI], send=send)
    assert out["alerted"] is False and out["cookie_state"] == "unknown"
    assert send.calls == [] and not _state(tmp_path).exists()


def test_a_healthy_verdict_never_alerts_or_writes_state(tmp_path):
    send = _Fake()
    out = fca.maybe_alert(_verdict(status="ok", cookie_status="ok"), state_path=_state(tmp_path),
                          gateways=[FI], send=send)
    assert out["alerted"] is False and out["cookie_state"] == "ok"
    assert send.calls == [] and not _state(tmp_path).exists()


def test_the_disable_switch_wins_over_an_expired_cookie(tmp_path, monkeypatch):
    monkeypatch.setenv(fca.DISABLE_ENV, "0")
    send = _Fake()
    out = fca.maybe_alert(_verdict(), state_path=_state(tmp_path), gateways=[FI], send=send)
    assert out["alerted"] is False and "disabled" in out["reason"]
    assert send.calls == [] and not _state(tmp_path).exists()


# ---------------------------------------------------------------- send path and dedupe

def test_token_ok_sends_one_telegram_and_one_fi_text_and_records_the_et_day(tmp_path):
    send = _Fake()
    now = datetime(2026, 11, 8, 23, 30, tzinfo=timezone.utc)  # 18:30 ET on Nov 8
    out = fca.maybe_alert(_verdict(), state_path=_state(tmp_path), gateways=[FI], send=send, now=now)
    assert out["alerted"] is True and out["delivered"] is True and out["et_date"] == "2026-11-08"
    assert out["degraded_features"] == len(fcf.labels())
    tg, text = send.calls[0], send.calls[1:]
    assert tg["channel"] == "telegram" and tg["to"] is None
    assert tg["body"].startswith("🍪 <b>FINVIZ COOKIE EXPIRED</b>")
    assert "Elite API token OK" in tg["body"]
    assert "Renew: Command Center → System → Admin → FINVIZ_COOKIE" in tg["body"]
    for label in fcf.labels():
        assert label in tg["body"]
    assert len(text) == 1 and text[0]["channel"] == "email" and text[0]["to"] == FI
    assert "FINVIZ COOKIE EXPIRED (Elite token OK)" in text[0]["body"]
    assert "3 features degraded" in text[0]["body"]
    assert len(text[0]["body"]) <= 280
    doc = json.loads(_state(tmp_path).read_text(encoding="utf-8"))
    assert doc["last_alert_et_date"] == "2026-11-08" and doc["last_cookie_state"] == "expired"
    assert doc["last_alert"]["degraded_features"] == 3 and doc["last_alert"]["gateways"] == 1


def test_the_same_et_day_sends_at_most_once_however_many_polls_ask(tmp_path):
    send = _Fake()
    now = datetime(2026, 11, 8, 23, 30, tzinfo=timezone.utc)
    first = fca.maybe_alert(_verdict(), state_path=_state(tmp_path), gateways=[FI], send=send, now=now)
    assert first["alerted"] is True
    for _ in range(5):
        again = fca.maybe_alert(_verdict(), state_path=_state(tmp_path), gateways=[FI], send=send, now=now)
        assert again["alerted"] is False and "already alerted" in again["reason"]
    assert [c["channel"] for c in send.calls] == ["telegram", "email"]


def test_the_day_key_is_the_new_york_calendar_not_utc(tmp_path):
    send = _Fake()
    # 02:00Z on Nov 9 is 21:00 ET on Nov 8: the same operator day as the alert above.
    fca.maybe_alert(_verdict(), state_path=_state(tmp_path), gateways=[FI], send=send,
                    now=datetime(2026, 11, 8, 15, 0, tzinfo=timezone.utc))
    same_et_day = fca.maybe_alert(_verdict(), state_path=_state(tmp_path), gateways=[FI], send=send,
                                  now=datetime(2026, 11, 9, 2, 0, tzinfo=timezone.utc))
    assert same_et_day["alerted"] is False and same_et_day["et_date"] == "2026-11-08"
    # 05:30Z on Nov 9 is 00:30 ET on Nov 9: a new operator day, one more alert.
    next_day = fca.maybe_alert(_verdict(), state_path=_state(tmp_path), gateways=[FI], send=send,
                               now=datetime(2026, 11, 9, 5, 30, tzinfo=timezone.utc))
    assert next_day["alerted"] is True and next_day["et_date"] == "2026-11-09"
    assert [c["channel"] for c in send.calls] == ["telegram", "email", "telegram", "email"]
    keys = [c["subject_key"] for c in send.calls]
    assert len(set(keys)) == 4, keys  # one idempotency key per channel per day


def test_no_gateway_still_attempts_telegram(tmp_path):
    send = _Fake()
    out = fca.maybe_alert(_verdict(), state_path=_state(tmp_path), gateways=[], send=send,
                          now=datetime(2026, 11, 8, 23, 30, tzinfo=timezone.utc))
    assert out["alerted"] is True and out["delivered"] is True
    assert [c["channel"] for c in send.calls] == ["telegram"]


def test_an_undelivered_attempt_is_still_recorded_and_not_retried_that_day(tmp_path):
    send = _Fake(delivered=False)
    now = datetime(2026, 11, 8, 23, 30, tzinfo=timezone.utc)
    out = fca.maybe_alert(_verdict(), state_path=_state(tmp_path), gateways=[FI], send=send, now=now)
    assert out["alerted"] is True and out["delivered"] is False and out["reason"] == "attempted"
    doc = json.loads(_state(tmp_path).read_text(encoding="utf-8"))
    assert doc["last_alert_et_date"] == "2026-11-08"
    again = fca.maybe_alert(_verdict(), state_path=_state(tmp_path), gateways=[FI], send=send, now=now)
    assert again["alerted"] is False


def test_one_channel_raising_does_not_stop_the_other(tmp_path):
    calls = []

    def send(channel, *, body, subject, to, subject_key):
        calls.append(channel)
        if channel == "telegram":
            raise RuntimeError("telegram down")
        return {"ok": True, "delivered": True}

    out = fca.maybe_alert(_verdict(), state_path=_state(tmp_path), gateways=[FI], send=send)
    assert calls == ["telegram", "email"]
    assert out["alerted"] is True and out["delivered"] is True
    assert out["telegram"]["error"] == "RuntimeError"


def test_no_recipient_address_is_written_to_the_state_file(tmp_path):
    fca.maybe_alert(_verdict(), state_path=_state(tmp_path), gateways=[FI], send=_Fake())
    text = _state(tmp_path).read_text(encoding="utf-8")
    assert FI not in text and '"to"' not in text
    doc = json.loads(text)
    assert doc["last_alert"]["texts"] and all("to" not in row for row in doc["last_alert"]["texts"])


def test_a_missing_cookie_uses_the_not_set_wording(tmp_path):
    send = _Fake()
    fca.maybe_alert(_verdict(status="missing", cookie_status="missing", ok=False, severity="red"),
                    state_path=_state(tmp_path), gateways=[FI], send=send)
    assert send.calls[0]["body"].startswith("🍪 <b>FINVIZ_COOKIE NOT SET</b>")
    assert send.calls[1]["body"].startswith("FINVIZ_COOKIE is not set")


# ---------------------------------------------------------------- body bounds

def test_the_fi_text_names_three_features_and_counts_the_rest_within_280():
    names = [f"feature {i}" for i in range(10)]
    body = fca.text_body(_verdict(), count=len(names), names=names)
    assert len(body) <= 280
    assert "10 features degraded" in body and "+7 more" in body


def test_the_fi_text_survives_an_empty_feature_registry():
    body = fca.text_body(_verdict(), count=0, names=[])
    assert "3 features" not in body and len(body) <= 280
    assert "Renew FINVIZ_COOKIE in CC Admin" in body


# ---------------------------------------------------------------- the api_v2 call site

def test_credential_health_alerts_on_a_fresh_verdict_and_never_on_a_cached_hit(monkeypatch):
    import api_v2

    seen = []
    monkeypatch.setattr(api_v2, "_finviz_credential_health_live", lambda q=None: _verdict())
    monkeypatch.setattr(api_v2, "_finviz_cookie_verdict_alert",
                        lambda v: (seen.append(v), {"alerted": True})[1])
    api_v2._FINVIZ_CRED_HEALTH_CACHE.update(ts=0.0, result=None)
    out = api_v2._finviz_credential_health()
    assert out["status"] == "token_ok" and len(seen) == 1
    for _ in range(3):
        api_v2._finviz_credential_health()
    assert len(seen) == 1, "a cached hit re-entered the send path"
    api_v2._FINVIZ_CRED_HEALTH_CACHE.update(ts=0.0, result=None)


def test_a_failing_alert_never_breaks_the_health_route(monkeypatch):
    import api_v2

    def boom(_):
        raise RuntimeError("gateway exploded")

    monkeypatch.setattr(api_v2, "_finviz_credential_health_live", lambda q=None: _verdict())
    monkeypatch.setattr(fca, "maybe_alert", boom)
    api_v2._FINVIZ_CRED_HEALTH_CACHE.update(ts=0.0, result=None)
    out = api_v2._finviz_credential_health()
    assert out["status"] == "token_ok" and out["show_banner"] is True
    api_v2._FINVIZ_CRED_HEALTH_CACHE.update(ts=0.0, result=None)
