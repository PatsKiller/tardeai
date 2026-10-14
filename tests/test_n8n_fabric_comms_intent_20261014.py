"""n8n fabric Phase 1 (2026-10-14): the comms/intent gateway op (n8n requests a send; the host decides).

Auth: only the relay key carries scope comms_intent, the scope opens exactly one operation on one route, and no
other scope reaches it. Host behaviour: exact bounded fields, closed (domain, kind) route table
(config/n8n_comms_intent_routes.json; unrouted = refused, no PAGE row), dedupe on (domain, kind, subject) inside the
window, an hourly cap, secret-shaped text refused, and nothing sent (outbound blocked, state QUEUED). The relay's
POST /intent cleans and forwards. Hermetic: tmp_path ledger, in-process gateway; no live relay, n8n or Telegram."""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_coordination_gateway as SRV  # noqa: E402
from scripts import n8n_run_relay as R  # noqa: E402
from scripts.lib import n8n_coordination_gateway as G  # noqa: E402
from scripts.lib import n8n_fabric_store as F  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerNonceStore, LedgerReceiptStore  # noqa: E402

KEY = b"dispatch-key-not-a-live-secret-0123456"
N8N = b"relay-key-not-a-live-secret-9876543210"
BEARER = "relay-bearer-not-a-live-secret-0123456789"
SHA = "a" * 40
NOW = datetime(2026, 10, 14, 14, 0, tzinfo=timezone.utc)
ROUTES_PATH = ROOT / "config" / "n8n_comms_intent_routes.json"
BODY = {
    "domain": "fabric",
    "kind": "workflow_error",
    "subject": "workflow tradeai-fabric-run-lane failed at Init",
    "summary": "run-lane: bad lane_id",
    "workflow_id": "tradeai-fabric-run-lane",
    "execution_id": "4242",
    "node": "Init",
}


@pytest.fixture
def led(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    yield SimpleNamespace(
        ledger=ledger,
        nonces=LedgerNonceStore(ledger),
        receipts=LedgerReceiptStore(ledger),
        intents=F.CommsIntentStore(ledger, routes_path=ROUTES_PATH),
        tmp=tmp_path,
    )
    ledger.close()


def _claim(nonce: str, *, caller: str, scope: str, key: bytes, at: datetime) -> dict:
    t = at.timestamp()
    claim = {
        "v": 1,
        "caller_id": caller,
        "project": "trade-ai",
        "iat": t,
        "exp": t + 120,
        "nonce": "nonce-" + nonce,
        "scope": scope,
    }
    return {"claim": claim, "signature": hmac.new(key, G.canonical(claim), hashlib.sha256).hexdigest()}


def _intent(
    led,
    nonce: str,
    *,
    caller="n8n-relay",
    scope=G.SCOPE_INTENT,
    key=N8N,
    route="comms/intent",
    operation="intent",
    at: datetime = NOW,
    intent_store="default",
    **override,
) -> dict:
    body = {**BODY, **override}
    body = {k: v for k, v in body.items() if v is not None}
    req = {**_claim(nonce, caller=caller, scope=scope, key=key, at=at), "route": route, "operation": operation, **body}
    return G.handle_request(
        req,
        key=KEY,
        now=at,
        nonce_store=led.nonces,
        idempotency_store=led.receipts,
        expected_origin_sha=SHA,
        caller_keys=G.build_caller_keys(KEY, n8n_key=N8N),
        intent_store=led.intents if intent_store == "default" else intent_store,
    )


def _count(led) -> int:
    return led.ledger._conn.execute("SELECT COUNT(*) FROM comms_intents").fetchone()[0]


# ── auth ────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_only_the_relay_key_carries_the_intent_scope():
    keys = G.build_caller_keys(KEY, n8n_key=N8N)
    assert G.SCOPE_INTENT in keys[G.RELAY_CALLER].scopes
    assert G.SCOPE_INTENT not in keys[G.DISPATCH_CALLER].scopes
    assert "comms/intent" in G.ALLOWED_ROUTES and G.route_forbidden("comms/intent") is None


def test_accepted_intent_is_queued_never_sent(led):
    out = _intent(led, "i1")
    assert out["schema"] == "CommsIntentReceipt@v1" and out["state"] == "ACCEPTED" and out["duplicate"] is False
    assert out["tier"] == "DIGEST" and out["delivery"] == "queued_for_host_comms_gateway"
    assert out["outbound"] == "blocked" and out["peer_used_as_auth"] is False
    row = led.intents.get(out["intent_id"])
    assert row["state"] == "QUEUED" and row["caller_id"] == "n8n-relay" and row["runbook_id"] == "n8n-workflow-error"
    assert (
        row["routes_sha256"]
        == hashlib.sha256(
            json.dumps(json.loads(ROUTES_PATH.read_text()), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert [r["intent_id"] for r in led.intents.list_queued()] == [out["intent_id"]]


@pytest.mark.parametrize(
    "kw,reason",
    [
        ({"key": b"z" * 40}, "bad_signature"),
        ({"caller": "tradeai-dispatch", "key": KEY}, "bad_scope"),  # dispatch key has no intent scope
        ({"scope": G.SCOPE_READ}, "bad_scope"),  # the relay's read scope cannot send intents
        ({"scope": G.SCOPE_RUN}, "bad_scope"),
        ({"operation": "accept_event"}, "unknown_operation"),
        ({"route": "coordination/status"}, "unknown_operation"),
        ({"route": "comms/send"}, "forbidden_route:send"),
        ({"intent_store": None}, "intent_scope_unavailable"),
    ],
)
def test_intent_auth_and_route_refusals_write_nothing(led, kw, reason):
    out = _intent(led, "a-" + reason.replace(":", "-"), **kw)
    assert out["state"] == "REFUSED" and out["reason"] == reason
    assert _count(led) == 0


def test_an_intent_scope_claim_cannot_read_or_run(led):
    req = {
        **_claim("x1", caller="n8n-relay", scope=G.SCOPE_INTENT, key=N8N, at=NOW),
        "route": "coordination/due",
        "operation": "due",
    }
    out = G.handle_request(
        req,
        key=KEY,
        now=NOW,
        nonce_store=led.nonces,
        idempotency_store=led.receipts,
        expected_origin_sha=SHA,
        caller_keys=G.build_caller_keys(KEY, n8n_key=N8N),
    )
    assert out["reason"] == "bad_scope"
    req = {
        **_claim("x2", caller="n8n-relay", scope=G.SCOPE_INTENT, key=N8N, at=NOW),
        "route": "coordination/run",
        "operation": "run",
        "lane_id": "x",
        "mode": "dry_run",
        "idempotency_key": "intent-cannot-run-0001",
    }
    out = G.handle_request(
        req,
        key=KEY,
        now=NOW,
        nonce_store=led.nonces,
        idempotency_store=led.receipts,
        expected_origin_sha=SHA,
        caller_keys=G.build_caller_keys(KEY, n8n_key=N8N),
        run_store=object(),
        run_allowlist=frozenset({"x"}),
    )
    assert out["reason"] == "bad_scope"


# ── validation and routing ──────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "override,reason",
    [
        ({"kind": "stop_triggered"}, "intent_unrouted"),  # well-formed but no row: n8n cannot invent a route
        ({"domain": "broker", "kind": "auth_down"}, "intent_unrouted"),  # no PAGE route from n8n at all
        ({"domain": "nowhere"}, "intent_unrouted"),
        ({"subject": "x" * 121}, "malformed_event"),
        ({"summary": "line\nbreak"}, "malformed_event"),
        ({"subject": "   "}, "malformed_event"),
        ({"execution_id": "bad id"}, "malformed_event"),
        ({"node": None}, "malformed_event"),
        ({"summary": "leaked Bearer abcdefghijklmnop"}, "secret_material"),
        ({"summary": "postgresql://u:p@h/db"}, "secret_material"),
        ({"chat_id": "123"}, "unexpected_field"),
    ],
)
def test_intent_validation(led, override, reason):
    out = _intent(led, "v-" + hashlib.sha1(json.dumps(override).encode()).hexdigest()[:10], **override)
    assert out["state"] == "REFUSED" and out["reason"] == reason
    assert _count(led) == 0


def test_dedupe_inside_the_window_then_a_new_row_after_it(led):
    a = _intent(led, "d1")
    b = _intent(led, "d2", execution_id="4243", summary="different text, same subject")
    c = _intent(led, "d3", subject="WORKFLOW   tradeai-fabric-run-lane failed at init")  # normalised: same key
    assert b["duplicate"] is True and c["duplicate"] is True and b["intent_id"] == c["intent_id"] == a["intent_id"]
    assert led.intents.get(a["intent_id"])["count"] == 3 and _count(led) == 1
    later = NOW + timedelta(seconds=3601)
    d = _intent(led, "d4", at=later)
    assert d["duplicate"] is False and d["intent_id"] != a["intent_id"] and _count(led) == 2
    other = _intent(led, "d5", subject="another subject")
    assert other["duplicate"] is False and _count(led) == 3


def test_hourly_cap_refuses_new_intents_but_not_duplicates(led, tmp_path):
    routes = json.loads(ROUTES_PATH.read_text())
    routes["max_per_hour"] = 2
    p = tmp_path / "routes.json"
    p.write_text(json.dumps(routes))
    led.intents = F.CommsIntentStore(led.ledger, routes_path=p)
    assert _intent(led, "c1", subject="s1")["state"] == "ACCEPTED"
    assert _intent(led, "c2", subject="s2")["state"] == "ACCEPTED"
    capped = _intent(led, "c3", subject="s3")
    assert capped["state"] == "REFUSED" and capped["reason"] == "intent_rate_limited"
    assert _intent(led, "c4", subject="s1")["duplicate"] is True  # a repeat of a queued intent still counts
    assert _intent(led, "c5", subject="s3", at=NOW + timedelta(seconds=3601))["state"] == "ACCEPTED"


def test_unreadable_route_table_refuses(led, tmp_path):
    p = tmp_path / "routes.json"
    p.write_text('{"schema": "N8nCommsIntentRoutes@v1", "routes": [{"domain": "fabric", "kind": "x", "tier": "PAGE"}]}')
    led.intents = F.CommsIntentStore(led.ledger, routes_path=p)
    assert _intent(led, "u1")["reason"] == "intent_routes_unreadable"


def test_committed_route_table_is_closed_and_has_no_page_row():
    routes = F.load_intent_routes(ROUTES_PATH)
    assert routes["routes"] and all(r["tier"] != "PAGE" for r in routes["routes"].values())
    assert all(domain == "fabric" for domain, _kind in routes["routes"])
    assert 60 <= routes["dedupe_window_s"] <= 86400


# ── relay: POST /intent ─────────────────────────────────────────────────────────────────────────────────────────


def _relay(led, tmp_path):
    keys = G.build_caller_keys(KEY, n8n_key=N8N)
    seen: list[dict] = []

    def transport(url, payload):
        seen.append(payload)
        return SRV.dispatch_http(
            "POST",
            "/v1/coordination",
            {},
            json.dumps(payload).encode(),
            key=KEY,
            expected_origin_sha=SHA,
            nonce_store=led.nonces,
            idempotency_store=led.receipts,
            caller_keys=keys,
            intent_store=led.intents,
        )

    env = {
        R.BEARER_ENV: BEARER,
        R.N8N_KEY_ENV: N8N.decode(),
        "TRADEAI_STATE_ROOT": str(tmp_path / "relay-state"),
        "TRADEAI_N8N_RELAY_LIVE_LANES": "",
    }
    return R.Relay(environ=env, allowlist=frozenset(), transport=transport, clock=time.time), seen


def test_relay_intent_forwards_cleaned_text_with_the_intent_scope(led, tmp_path):
    relay, seen = _relay(led, tmp_path)
    body = dict(BODY, summary="token sk-abcdefghijklmnop leaked\tand a tab", subject="x\x00y failed")
    status, reply = relay.intent("Bearer " + BEARER, json.dumps(body).encode())
    assert status == 200 and reply["state"] == "ACCEPTED", reply
    sent = seen[-1]
    assert sent["claim"]["scope"] == G.SCOPE_INTENT and sent["route"] == "comms/intent"
    assert "sk-abc" not in sent["summary"] and "[redacted]" in sent["summary"] and "\t" not in sent["summary"]
    assert sent["subject"] == "x y failed"
    assert set(sent) == {"route", "operation", "claim", "signature"} | R.INTENT_BODY_KEYS
    again_status, again = relay.intent("Bearer " + BEARER, json.dumps(body).encode())
    assert again_status == 200 and again["duplicate"] is True
    log = (tmp_path / "relay-state" / "data" / "runtime" / "n8n_relay" / "relay_log.jsonl").read_text()
    assert '"op":"intent"' in log and "leaked" not in log  # no free text in the relay log


@pytest.mark.parametrize(
    "body,code,reason",
    [
        (b"not json", 400, "relay_malformed_body"),
        (json.dumps({**BODY, "extra": "x"}).encode(), 400, "relay_bad_intent"),
        (json.dumps({k: v for k, v in BODY.items() if k != "node"}).encode(), 400, "relay_bad_intent"),
        (json.dumps({**BODY, "domain": "Fabric!"}).encode(), 400, "relay_bad_intent"),
        (json.dumps({**BODY, "subject": "\x00\x01"}).encode(), 400, "relay_bad_intent"),
        (json.dumps({**BODY, "summary": "x" * 2000}).encode(), 413, "relay_body_too_large"),
    ],
)
def test_relay_intent_refuses_before_the_gateway(led, tmp_path, body, code, reason):
    relay, seen = _relay(led, tmp_path)
    status, reply = relay.intent("Bearer " + BEARER, body)
    assert status == code and reply["reason"] == reason and seen == []


def test_relay_intent_passes_a_gateway_refusal_through_as_403(led, tmp_path):
    relay, _seen = _relay(led, tmp_path)
    status, reply = relay.intent("Bearer " + BEARER, json.dumps({**BODY, "kind": "unknown_kind"}).encode())
    assert status == 403 and reply["reason"] == "intent_unrouted"


def test_relay_intent_needs_the_bearer(led, tmp_path):
    relay, seen = _relay(led, tmp_path)
    status, reply = relay.intent(None, json.dumps(BODY).encode())
    assert status == 401 and reply["reason"] == "relay_bad_bearer" and seen == []
