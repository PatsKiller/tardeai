"""P0 Telegram feed gates — R:R, invalidation, quote withhold, no double-send."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lib.telegram_card_gate import (
    RR_UNAVAILABLE,
    compute_rr,
    idempotency_key,
    intelligence_card_gate,
    invalidation_ok,
    proposal_send_gate,
    quote_allows_sized_proposal,
)
from telegram_transport import deliver_text


def test_aspen_rr_is_two_not_zero():
    # Audit: Entry $5.42 Stop $5.15 Target $5.96 printed 0.0:1; true is 2.0:1
    r = compute_rr(5.42, 5.15, 5.96)
    assert r["ok"] is True
    assert r["rr"] == 2.0
    assert r["display"] == "2.0:1"
    assert "0.0" not in r["display"]


def test_missing_leg_never_zero_token():
    r = compute_rr(5.42, None, 5.96)
    assert r["ok"] is False
    assert r["display"] == RR_UNAVAILABLE
    assert r["promote_actionable"] is False


def test_zero_stored_rr_does_not_print_zero(monkeypatch):
    from telegram_proposal_alert_policy import build_proposal_alert_packet, format_telegram_message

    pkt = build_proposal_alert_packet({
        "symbol": "ASPN",
        "id": 107,
        "status": "PENDING",
        "proposed_entry": 5.42,
        "proposed_stop": 5.15,
        "proposed_target1": 5.96,
        "proposed_rr": 0,
        "proposed_shares": 100,
        "approval_blockers": [],
        "execution_readiness": {
            "quote_provider": "alpaca",
            "quote_execution_eligible": True,
        },
    })
    msg = format_telegram_message(pkt)
    assert "0.0:1" not in msg
    assert "2.0:1" in msg


def test_quote_fail_withholds_proposal():
    g = proposal_send_gate({
        "symbol": "KDK",
        "proposed_entry": 10,
        "proposed_stop": 9,
        "proposed_target1": 12,
        "execution_readiness": {
            "quote_provider": "alpaca",
            "quote_execution_eligible": False,
        },
    })
    assert g["send"] is False
    assert "quote_fail" in g["suppress"]


def test_quote_ok_allows_send():
    g = proposal_send_gate({
        "symbol": "ASPN",
        "proposed_entry": 5.42,
        "proposed_stop": 5.15,
        "proposed_target1": 5.96,
        "execution_readiness": {
            "quote_provider": "alpaca",
            "quote_execution_eligible": True,
        },
    })
    assert g["send"] is True
    assert g["promote_actionable"] is True


def test_should_send_quote_fail():
    from telegram_proposal_alert_policy import should_send_alert

    d = should_send_alert({
        "id": 1,
        "symbol": "KDK",
        "status": "PENDING",
        "proposed_entry": 10,
        "proposed_stop": 9,
        "proposed_target1": 12,
        "execution_readiness": {
            "quote_provider": "alpaca",
            "quote_execution_eligible": False,
        },
    })
    assert d["send"] is False
    assert d["reason"] == "PRICE_UNAVAILABLE_WITHHELD"


def test_jtai_invalidation_above_price_suppresses():
    # Audit: Price $1.59 · Invalidation $1.60 on a long
    g = intelligence_card_gate({
        "symbol": "JTAI",
        "technical": {"price": 1.59, "stop_invalidation": 1.60},
    })
    assert g["send"] is False
    assert g["invalidation"]["suppress"] is True


def test_valid_long_invalidation_sends():
    g = intelligence_card_gate({
        "symbol": "UBER",
        "technical": {"price": 72.5, "stop_invalidation": 68.0},
    })
    assert g["send"] is True


def _strict_reentry(*, price=1.59, low=1.68, high=1.83, distance=-5.36, stop=1.50, as_of=None):
    return {
        "symbol": "JTAI",
        "action_class": "REENTRY_WATCH",
        "change": {"kind": "reentry_added", "to": "NEAR"},
        "technical": {
            "price": price,
            "support_or_zone_low": low,
            "resistance_or_zone_high": high,
            "stop_invalidation": stop,
            "distance_pct": distance,
            "near_threshold_pct": 3.0,
            "price_source": "finviz",
            "price_as_of": as_of or datetime.now(timezone.utc).isoformat(),
            "status": "NEAR",
            "data_conflicts": [],
        },
    }


def test_near_beyond_threshold_suppresses():
    g = intelligence_card_gate(_strict_reentry())
    assert g["send"] is False
    assert "NEAR_THRESHOLD_EXCEEDED" in g["failures"]


def test_stale_quote_suppresses_reentry_card():
    old = (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat()
    g = intelligence_card_gate(_strict_reentry(price=1.70, distance=0, as_of=old))
    assert g["send"] is False
    assert "QUOTE_SOURCE_STALE_OR_UNAVAILABLE" in g["failures"]


def test_conflicting_prices_suppress_reentry_card():
    obj = _strict_reentry(price=1.70, distance=0)
    obj["technical"]["data_conflicts"] = [{"low": 1.59, "high": 1.70}]
    g = intelligence_card_gate(obj)
    assert g["send"] is False
    assert "DATA_CONFLICT" in g["failures"]


def test_consistent_near_card_passes_strict_gate():
    g = intelligence_card_gate(_strict_reentry(price=1.66, distance=-1.19, stop=1.50))
    assert g["send"] is True
    assert g["failures"] == []


def test_render_inverted_returns_empty():
    from scripts.lib.cio_symbol_intelligence import render_telegram_card

    body = render_telegram_card({
        "symbol": "JTAI",
        "change": {"kind": "reentry_added", "to": "NEAR"},
        "technical": {"price": 1.59, "stop_invalidation": 1.60,
                      "support_or_zone_low": 1.68, "resistance_or_zone_high": 1.83},
        "thesis": {},
        "why_now": ["x"],
        "causality": {},
        "provenance": {},
        "memory": {},
    })
    assert body == ""


def test_short_invalidation_above_spot_ok():
    assert invalidation_ok(10, 12, side="short")["ok"] is True
    assert invalidation_ok(10, 8, side="short")["suppress"] is True


def test_idempotency_key_shape():
    assert idempotency_key("proposal", "aspn", 107) == "proposal:ASPN:107"


def test_deliver_plain_fallback_is_one_visible_message(tmp_path, monkeypatch):
    """Markdown 400 then plaintext 200 = one posted message, not two."""
    from lib import telegram_send_idempotency as idm
    monkeypatch.setattr(idm, "_DEFAULT", tmp_path / "idemp.json")
    # deliver_text interdicts when PYTEST_CURRENT_TEST is set — clear for this unit.
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "")
    monkeypatch.delenv("CIO_TELEGRAM_INTERDICT", raising=False)
    calls = []

    def post(url, payload):
        calls.append({"url": url, "parse_mode": payload.get("parse_mode")})
        if payload.get("parse_mode"):
            return {"ok": False, "status_code": 400, "response": {"ok": False, "description": "can't parse entities"}}
        return {
            "ok": True,
            "status_code": 200,
            "response": {"ok": True, "result": {"message_id": 99}},
        }

    r = deliver_text(
        token="t", chat_id="1", text="*Paper Proposal: ASPN*",
        parse_mode="Markdown", post=post,
        idempotency_key="proposal:ASPN:fallback-test",
    )
    assert r["ok"] is True
    assert r.get("plain_fallback") is True
    send_calls = [c for c in calls if "sendMessage" in c["url"]]
    assert len(send_calls) == 2  # 400 then 200 — Telegram only posted the 200
    assert send_calls[0]["parse_mode"] == "Markdown"
    assert send_calls[1]["parse_mode"] is None


def test_second_send_edits_not_posts(tmp_path, monkeypatch):
    store = tmp_path / "idemp.json"
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "")  # deliver_text itself is not send_message
    from lib import telegram_send_idempotency as idm
    monkeypatch.setattr(idm, "_DEFAULT", store)

    calls = []

    def post(url, payload):
        calls.append(url)
        if "editMessageText" in url:
            return {"ok": True, "status_code": 200, "response": {"ok": True, "result": {"message_id": payload.get("message_id")}}}
        return {"ok": True, "status_code": 200, "response": {"ok": True, "result": {"message_id": 42}}}

    k = "proposal:ASPN:107"
    r1 = deliver_text(token="t", chat_id="9", text="first", parse_mode="Markdown",
                      idempotency_key=k, post=post)
    r2 = deliver_text(token="t", chat_id="9", text="retry plain", parse_mode=None,
                      idempotency_key=k, post=post)
    assert r1["ok"] and r1.get("message_id") == 42
    assert r2.get("edited") is True
    assert sum(1 for u in calls if "sendMessage" in u) == 1
    assert sum(1 for u in calls if "editMessageText" in u) == 1


def test_first_success_does_not_fallback_send(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "")
    monkeypatch.delenv("CIO_TELEGRAM_INTERDICT", raising=False)
    calls = []

    def post(url, payload):
        calls.append(payload.get("parse_mode"))
        return {"ok": True, "status_code": 200, "response": {"ok": True, "result": {"message_id": 1}}}

    r = deliver_text(token="t", chat_id="1", text="ok", parse_mode="Markdown", post=post)
    assert r["ok"] is True
    assert calls == ["Markdown"]
