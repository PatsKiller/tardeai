"""HTTP boundary of the lab gateway. No live port is left open."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.lib import n8n_coordination_gateway as gw
from scripts.n8n_coordination_gateway import canonical_path, dispatch_http

KEY = b"test-gateway-key-not-a-live-secret!!"
OLD = b"previous-gateway-key-not-live-secret"
SHA = "18a27ff288894c4e428151d5f385e68522ecd47b"
NOW = datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc)


def _stores():
    return {}, {}


def _body(nonce: str, *, key: bytes = KEY) -> bytes:
    claim = {
        "v": 1,
        "caller_id": "n8n-lab",
        "project": "trade-ai",
        "iat": NOW.timestamp(),
        "exp": (NOW + timedelta(seconds=120)).timestamp(),
        "nonce": nonce,
        "scope": "coordination_read",
    }
    event = {
        "event_id": "evt-http-0001",
        "source_project": "trade-ai",
        "lane_id": "morning-brief-0730",
        "schema_version": "event-reference/v0",
        "origin_sha": SHA,
        "subject_key": "morning-brief",
        "source_timestamp": "2026-10-07T11:30:00+00:00",
        "deadline": "2026-10-07T12:00:00+00:00",
        "artifact_ref": "logs/morning_brief.log",
        "authority_class": "coordination_read",
        "correlation_id": "corr-http-1",
        "idempotency_key": "idem-http-" + nonce,
    }
    import json

    return json.dumps(
        {
            "route": "coordination/event",
            "operation": "accept_event",
            "claim": claim,
            "signature": gw.sign_claim(claim, key),
            "event": event,
            "X-Forwarded-For": "203.0.113.5",
        }
    ).encode()


def test_unknown_method_and_encoded_path_are_refused():
    nonces, store = _stores()
    status, body = dispatch_http(
        "PUT",
        "/v1/coordination",
        {"X-Forwarded-For": "203.0.113.5"},
        b"{}",
        key=KEY,
        expected_origin_sha=SHA,
        nonce_store=nonces,
        idempotency_store=store,
        now=NOW,
    )
    assert status == 405
    assert body["reason"] == "unknown_method"
    assert body["proxy_headers_used_as_auth"] is False
    assert canonical_path("/v1/coordination%2F..%2Fhealthz") is None
    assert canonical_path("/v1/coordination/../broker") is None
    status, missing = dispatch_http(
        "POST",
        "/v1/%76coordination",
        {},
        _body("nonce-path-1"),
        key=KEY,
        expected_origin_sha=SHA,
        nonce_store=nonces,
        idempotency_store=store,
        now=NOW,
    )
    assert status == 404
    assert missing["reason"] == "not_found"


def test_proxy_header_does_not_authenticate():
    nonces, store = _stores()
    status, body = dispatch_http(
        "POST",
        "/v1/coordination",
        {"X-Forwarded-For": "127.0.0.1", "X-Real-Ip": "127.0.0.1"},
        b'{"route":"coordination/event","peer":"127.0.0.1"}',
        key=KEY,
        expected_origin_sha=SHA,
        nonce_store=nonces,
        idempotency_store=store,
        now=NOW,
    )
    assert status == 403
    assert body["reason"] == "missing_signature"
    assert body["proxy_headers_used_as_auth"] is False
    assert body["durable"] is False


def test_oversized_and_invalid_utf8():
    nonces, store = _stores()
    status, body = dispatch_http(
        "POST",
        "/v1/coordination",
        {},
        b"x" * 80,
        key=KEY,
        expected_origin_sha=SHA,
        nonce_store=nonces,
        idempotency_store=store,
        now=NOW,
        max_body=16,
    )
    assert status == 413
    assert body["reason"] == "body_too_large"
    status, bad = dispatch_http(
        "POST",
        "/v1/coordination",
        {},
        b"\xff\xfe not utf-8",
        key=KEY,
        expected_origin_sha=SHA,
        nonce_store=nonces,
        idempotency_store=store,
        now=NOW,
    )
    assert status == 400
    assert bad["reason"] == "malformed_event"


def test_previous_key_overlap_accepts_old_and_new():
    nonces, store = _stores()
    status, body = dispatch_http(
        "POST",
        "/v1/coordination",
        {"X-Forwarded-For": "10.1.1.1"},
        _body("nonce-old-key", key=OLD),
        key=KEY,
        previous_key=OLD,
        expected_origin_sha=SHA,
        nonce_store=nonces,
        idempotency_store=store,
        now=NOW,
    )
    assert status == 200
    assert body["state"] == "ACCEPTED"
    assert body["durable"] is False
    status, fresh = dispatch_http(
        "POST",
        "/v1/coordination",
        {},
        _body("nonce-new-key", key=KEY),
        key=KEY,
        previous_key=OLD,
        expected_origin_sha=SHA,
        nonce_store=nonces,
        idempotency_store=store,
        now=NOW,
    )
    assert status == 200
    assert fresh["state"] == "ACCEPTED"
