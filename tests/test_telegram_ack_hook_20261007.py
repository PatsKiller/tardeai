"""ack:<idempotency_key> records an operator consumer receipt and nothing else (2026-10-07)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import n8n_coordination_gateway as server
from scripts.lib import n8n_gateway_client as gc
from scripts.lib.n8n_coordination_gateway import PILOT_LANES, sign_claim

KEY = b"telegram-ack-hook-test-key-not-a-live-secret!!"
SHA = "60863d207f4639819f04209f816f71e3056768a7"


def _transport():
    nonces, store = {}, {}

    def t(url, envelope):
        return server.dispatch_http("POST", "/v1/coordination", {}, json.dumps(envelope).encode(), key=KEY,
                                    expected_origin_sha=SHA, nonce_store=nonces, idempotency_store=store,
                                    lane_allowlist=PILOT_LANES)
    t.store = store
    return t


def _seed_artifact(t, idem: str) -> None:
    """ACCEPTED → CLAIMED → STARTED → ARTIFACT_WRITTEN with the test key, through the same transport."""
    now = datetime.now(timezone.utc)

    def call(op, route, **fields):
        claim = {"v": 1, "caller_id": "seed-test", "project": "trade-ai", "iat": now.timestamp(), "exp": now.timestamp() + 60,
                 "nonce": "seed" + op + idem[:8], "scope": "coordination_read"}
        status, body = t("x", {"route": route, "operation": op, "claim": claim, "signature": sign_claim(claim, KEY), **fields})
        assert body.get("state") != "REFUSED", body
        return body
    ev = {"event_id": "evt-approval-package-reminder-" + idem, "source_project": "trade-ai", "lane_id": "approval-package-reminder",
          "schema_version": "event-reference/v0", "origin_sha": SHA, "subject_key": "t", "source_timestamp": now.isoformat(),
          "deadline": (now + timedelta(hours=1)).isoformat(), "artifact_ref": "data/runtime/x.json",
          "authority_class": "coordination_read", "correlation_id": "corr-" + idem, "idempotency_key": idem}
    call("accept_event", "coordination/event", event=ev)
    call("claim", "coordination/status", idempotency_key=idem)
    call("start", "coordination/status", idempotency_key=idem)
    call("artifact", "coordination/status", idempotency_key=idem,
         artifact_ref={"store": "data/runtime", "ref": "x.json", "sha256": "a" * 64, "as_of": now.isoformat()})


@pytest.fixture
def hook(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111")
    monkeypatch.setenv("TRADEAI_OPERATOR_FROM_IDS", "42")
    monkeypatch.setenv("TRADEAI_N8N_GATEWAY_HMAC_KEY", KEY.decode())
    t = _transport()
    monkeypatch.setattr(gc.GatewayClient, "_http", lambda self, url, envelope: t(url, envelope))
    import telegram_callback_handler as h
    answers, edits = [], []
    monkeypatch.setattr(h, "answer_callback", lambda cb_id, text, show_alert=False: answers.append((text, show_alert)))
    monkeypatch.setattr(h, "edit_message", lambda chat, mid, text: edits.append(text))
    return h, t, answers, edits


def _cb(data: str, *, from_id: str = "42", chat: str = "111") -> dict:
    return {"id": "cb-1", "data": data, "from": {"id": from_id, "first_name": "John"},
            "message": {"chat": {"id": chat}, "message_id": 7, "text": "incident: cio-delivery NO_OUTPUT"}}


def test_ack_moves_artifact_to_consumed_with_operator_receipt(hook):
    h, t, answers, edits = hook
    idem = "inc-abcdef0123456789abcdef"
    _seed_artifact(t, idem)
    h.handle_callback_query(_cb(f"ack:{idem}"))
    rec = t.store["trade-ai:" + idem]["receipt"]
    assert rec["state"] == "CONSUMED" and rec["consumer"] == "operator-telegram:42" and rec["consumer_receipt_id"] == "cb-cb-1"
    assert rec["effects"] == [] and rec["outbound"] == "blocked"
    assert answers and answers[-1][0].startswith("Acknowledged") and edits and "acknowledged by John" in edits[-1]


def test_ack_is_refused_when_nothing_to_consume_and_for_strangers(hook):
    h, t, answers, edits = hook
    h.handle_callback_query(_cb("ack:inc-not-in-ledger-0001"))
    assert answers[-1][1] is True and "Not acknowledged" in answers[-1][0]
    h.handle_callback_query(_cb("ack:inc-abcdef0123456789abcdef", from_id="999"))
    assert answers[-1][0].startswith("Not authorized")
    h.handle_callback_query(_cb("ack:short"))
    assert answers[-1][0] == "Invalid ack target"
    assert edits == []


def test_ack_keyboard_respects_telegram_limit():
    kb = gc.ack_keyboard("inc-abcdef0123456789abcdef")
    assert kb["inline_keyboard"][0][0]["callback_data"] == "ack:inc-abcdef0123456789abcdef"
    with pytest.raises(ValueError):
        gc.ack_keyboard("x" * 70)
