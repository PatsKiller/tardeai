"""Hermetic proofs for the coordination gateway. No live port and no secret store."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from scripts.lib import n8n_coordination_gateway as gw
from scripts.n8n_coordination_gateway import BindRefused, guard_bind, load_key, serve

KEY = b"test-gateway-key-not-a-live-secret!!"
SHA = "18a27ff288894c4e428151d5f385e68522ecd47b"
NOW = datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc)


def _claim(nonce: str, project: str = "trade-ai") -> tuple[dict, str]:
    body = {
        "v": 1,
        "caller_id": "n8n-lab",
        "project": project,
        "iat": NOW.timestamp(),
        "exp": (NOW + timedelta(seconds=120)).timestamp(),
        "nonce": nonce,
        "scope": "coordination_read",
    }
    return body, gw.sign_claim(body, KEY)


def _event(lane: str = "morning-brief-0730", **overrides) -> dict:
    body = {
        "event_id": "evt-morning-0001",
        "source_project": "trade-ai",
        "lane_id": lane,
        "schema_version": "event-reference/v0",
        "origin_sha": SHA,
        "subject_key": "morning-brief",
        "source_timestamp": "2026-10-07T11:30:00+00:00",
        "deadline": "2026-10-07T12:00:00+00:00",
        "artifact_ref": "logs/morning_brief.log",
        "authority_class": "coordination_read",
        "correlation_id": "corr-0001",
        "idempotency_key": "idem-0001",
    }
    body.update(overrides)
    return body


def _call(nonce: str, event: dict | None = None, **extra) -> dict:
    event = _event() if event is None else event
    claim, signature = _claim(nonce, event.get("source_project", "trade-ai"))
    request = {
        "route": "coordination/event",
        "operation": "accept_event",
        "claim": claim,
        "signature": signature,
        "event": event,
        "peer": "127.0.0.1",
    }
    request.update(extra)
    return gw.handle_request(
        request,
        key=KEY,
        now=NOW,
        nonce_store=extra.pop("_nonces", request.pop("_nonces", {})),
        idempotency_store=extra.pop("_store", request.pop("_store", {})),
        expected_origin_sha=SHA,
    )


def test_accept_ignores_localhost():
    nonces, store = {}, {}
    event = _event()
    claim, signature = _claim("nonce-accept-1")
    receipt = gw.handle_request(
        {
            "route": "coordination/event",
            "operation": "accept_event",
            "claim": claim,
            "signature": signature,
            "event": event,
            "peer": "127.0.0.1",
        },
        key=KEY,
        now=NOW,
        nonce_store=nonces,
        idempotency_store=store,
        expected_origin_sha=SHA,
    )
    assert receipt["state"] == "ACCEPTED"
    assert receipt["effects"] == []
    assert receipt["outbound"] == "blocked"
    assert receipt["mutation"] == "blocked"
    assert receipt["durable"] is False
    assert receipt["peer_used_as_auth"] is False
    assert "nonce-accept-1" in nonces


def test_missing_signature_is_unauthenticated_even_from_localhost():
    receipt = gw.handle_request(
        {"route": "coordination/event", "operation": "accept_event", "event": _event(), "peer": "127.0.0.1"},
        key=KEY,
        now=NOW,
        nonce_store={},
        idempotency_store={},
        expected_origin_sha=SHA,
    )
    assert receipt["state"] == "REFUSED"
    assert receipt["reason"] == "missing_signature"
    assert receipt["peer_used_as_auth"] is False
    assert receipt["peer_ignored"] is True


def test_bad_signature_replay_stale_sha_and_unknown_lane():
    nonces, store = {}, {}
    claim, _signature = _claim("nonce-bad-1")
    bad = gw.handle_request(
        {
            "route": "coordination/event",
            "operation": "accept_event",
            "claim": claim,
            "signature": "0" * 64,
            "event": _event(),
        },
        key=KEY,
        now=NOW,
        nonce_store=nonces,
        idempotency_store=store,
        expected_origin_sha=SHA,
    )
    assert bad["reason"] == "bad_signature"
    assert nonces == {}

    first = _call("nonce-replay-1", _nonces=nonces, _store=store)
    assert first["state"] == "ACCEPTED"
    replay = _call("nonce-replay-1", _nonces=nonces, _store=store)
    assert replay["reason"] == "replayed_nonce"

    stale = _call("nonce-stale-1", _event(origin_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), _nonces={}, _store={})
    assert stale["reason"] == "stale_origin_sha"
    unknown = _call("nonce-lane-1", _event(lane_id="not-a-pilot", event_id="evt-unknown-01", idempotency_key="idem-lane-1"), _nonces={}, _store={})
    assert unknown["reason"] == "unknown_lane"


def test_forbidden_routes_cover_broker_grant_2fa_promote_and_bid():
    for route in ("broker/order", "grant/activate", "2fa/verify", "promote", "bid", "title_status", "payment"):
        claim, signature = _claim("nonce-" + route)
        receipt = gw.handle_request(
            {
                "route": route,
                "operation": "accept_event",
                "claim": claim,
                "signature": signature,
                "event": _event(),
                "peer": "127.0.0.1",
            },
            key=KEY,
            now=NOW,
            nonce_store={},
            idempotency_store={},
            expected_origin_sha=SHA,
        )
        assert receipt["state"] == "REFUSED", route
        assert receipt["reason"].startswith("forbidden_route:"), route


def test_duplicate_and_conflict_and_secret_and_project():
    nonces, store = {}, {}
    event = _event()
    first = _call("nonce-dup-1", event, _nonces=nonces, _store=store)
    again = _call("nonce-dup-2", event, _nonces=nonces, _store=store)
    assert first["state"] == "ACCEPTED"
    assert again["duplicate"] is True
    assert again["event_id"] == first["event_id"]
    conflict = _call(
        "nonce-dup-3",
        _event(event_id="evt-morning-0002"),
        _nonces=nonces,
        _store=store,
    )
    assert conflict["reason"] == "idempotency_conflict"

    planted = "super-secret-value"
    secret = _call(
        "nonce-secret-1",
        _event(idempotency_key="idem-secret", event_id="evt-secret-001", password=planted),
        _nonces={},
        _store={},
    )
    assert secret["reason"] == "secret_material"
    assert planted not in json.dumps(secret)

    claim, signature = _claim("nonce-proj-1", project="nyc-dof-auction")
    mismatch = gw.handle_request(
        {
            "route": "coordination/event",
            "operation": "accept_event",
            "claim": claim,
            "signature": signature,
            "event": _event(),
        },
        key=KEY,
        now=NOW,
        nonce_store={},
        idempotency_store={},
        expected_origin_sha=SHA,
    )
    assert mismatch["reason"] == "project_mismatch"


def test_consumer_ack_requires_a_receipt_and_does_not_send():
    nonces, store = {}, {}
    event = _event(idempotency_key="idem-ack-01", event_id="evt-ack-0001")
    assert _call("nonce-ack-1", event, _nonces=nonces, _store=store)["state"] == "ACCEPTED"
    claim, signature = _claim("nonce-ack-2")

    def step(operation: str, nonce: str, **extra) -> dict:
        body, sig = _claim(nonce)
        request = {
            "route": "coordination/status",
            "operation": operation,
            "claim": body,
            "signature": sig,
            "idempotency_key": event["idempotency_key"],
        }
        request.update(extra)
        return gw.handle_request(
            request,
            key=KEY,
            now=NOW,
            nonce_store=nonces,
            idempotency_store=store,
            expected_origin_sha=SHA,
        )

    assert step("claim", "nonce-ack-2")["state"] == "CLAIMED"
    assert step("start", "nonce-ack-3")["state"] == "STARTED"
    # 2026-10-07: an artifact is a REFERENCE (store + ref + sha256), never bytes
    assert step("artifact", "nonce-ack-4a")["reason"] == "artifact_ref_required"
    assert step("artifact", "nonce-ack-4b", artifact_ref={"store": "x", "ref": "y"}, content="...")["reason"] == "artifact_bytes_refused"
    written = step("artifact", "nonce-ack-4", artifact_ref={"store": "data/runtime", "ref": "approval_package_reminder_last.json",
                                                            "sha256": "a" * 64, "as_of": "2026-10-07T04:05:00+00:00"})
    assert written["state"] == "ARTIFACT_WRITTEN" and written["artifact_ref"]["ref"].endswith("last.json")
    missing = step("consumer_ack", "nonce-ack-5")
    assert missing["reason"] == "no_consumer_receipt"
    status = step("status", "nonce-ack-6")
    assert status["state"] == "ARTIFACT_WRITTEN"
    done = step(
        "consumer_ack",
        "nonce-ack-7",
        consumer_receipt={"consumer": "operator-desk", "receipt_id": "rcpt-0001"},
    )
    assert done["state"] == "CONSUMED"
    assert done["effects"] == []
    assert done["outbound"] == "blocked"


def test_bind_guard_and_loopback_server():
    try:
        guard_bind("0.0.0.0", 8791)
        raise AssertionError("public bind was allowed")
    except BindRefused:
        pass
    try:
        guard_bind("127.0.0.1", 7777)
        raise AssertionError("portfolio port was allowed")
    except BindRefused:
        pass
    try:
        load_key({})
        raise AssertionError("empty key was allowed")
    except BindRefused:
        pass

    httpd = serve("127.0.0.1", 0, key=KEY, expected_origin_sha=SHA)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        health = urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=3)
        assert health.status == 200
        assert json.loads(health.read().decode())["ok"] is True   # 2026-10-07: healthz also reports durable + ledger
        claim, signature = _claim("nonce-http-1")
        payload = json.dumps(
            {
                "route": "broker/order",
                "operation": "accept_event",
                "claim": claim,
                "signature": signature,
                "event": _event(),
                "peer": "127.0.0.1",
            }
        ).encode()
        try:
            urllib.request.urlopen(
                urllib.request.Request(
                    f"http://127.0.0.1:{port}/v1/coordination",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                ),
                timeout=3,
            )
            raise AssertionError("broker route returned success")
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode())
            assert exc.code == 403
            assert body["reason"].startswith("forbidden_route:")
    finally:
        httpd.shutdown()
        thread.join(timeout=3)
        httpd.server_close()
