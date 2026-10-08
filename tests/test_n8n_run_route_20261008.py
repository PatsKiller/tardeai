"""Gateway `run` operation (n8n scheduler-of-record tranche N1, 2026-10-08).

Per-caller keys: the dispatch key keeps read scope and its previous-key overlap; only the n8n-relay key may
claim coordination_run, and without that key the run scope is unavailable. A run writes ONE ledger row
(REQUESTED) and returns RunRequested@v1; a repeated idempotency_key returns the row with duplicate:true;
nothing is spawned. Hermetic: tmp_path ledgers, no live port, no secret store."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import n8n_coordination_gateway as G
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerNonceStore, LedgerReceiptStore, LedgerRunStore
from scripts import n8n_coordination_gateway as SRV

ROOT = Path(__file__).resolve().parents[1]
KEY = b"dispatch-key-not-a-live-secret-0123456"
OLD = b"previous-dispatch-key-not-live-secret!"
N8N = b"relay-key-not-a-live-secret-9876543210"
SHA = "a" * 40
NOW = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)
ALLOW = frozenset({"n8n-lab-watchdog", "maturity-remeasure"})
RUN_ID = "run-20261008-watchdog-0001"


def _claim(nonce: str, *, caller: str, scope: str, key: bytes) -> dict:
    claim = {
        "v": 1,
        "caller_id": caller,
        "project": "trade-ai",
        "iat": NOW.timestamp(),
        "exp": NOW.timestamp() + 120,
        "nonce": "nonce-" + nonce,
        "scope": scope,
    }
    return {"claim": claim, "signature": hmac.new(key, G.canonical(claim), hashlib.sha256).hexdigest()}


@pytest.fixture
def stores(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    yield ledger, LedgerNonceStore(ledger), LedgerReceiptStore(ledger), LedgerRunStore(ledger)
    ledger.close()


def _run(
    stores,
    nonce: str,
    *,
    caller="n8n-relay",
    scope=G.SCOPE_RUN,
    key=N8N,
    route="coordination/run",
    operation="run",
    caller_keys=None,
    run_store="default",
    allow=ALLOW,
    **body,
) -> dict:
    _ledger, nonces, receipts, runs = stores
    req = {
        **_claim(nonce, caller=caller, scope=scope, key=key),
        "route": route,
        "operation": operation,
        "lane_id": "n8n-lab-watchdog",
        "mode": "dry_run",
        "idempotency_key": RUN_ID,
        "requested_by": "n8n:wf-1",
    }
    req.update(body)
    keys = caller_keys if caller_keys is not None else G.build_caller_keys(KEY, previous_key=OLD, n8n_key=N8N)
    return G.handle_request(
        req,
        key=KEY,
        now=NOW,
        nonce_store=nonces,
        idempotency_store=receipts,
        expected_origin_sha=SHA,
        previous_key=OLD,
        caller_keys=keys,
        run_store=runs if run_store == "default" else run_store,
        run_allowlist=allow,
    )


def test_run_writes_one_requested_row_and_returns_the_envelope_without_spawning(stores):
    ledger, _n, _r, runs = stores
    out = _run(stores, "r1")
    assert out["schema"] == "RunRequested@v1" and out["state"] == "REQUESTED" and out["duplicate"] is False
    assert out["run_id"] == RUN_ID and out["lane_id"] == "n8n-lab-watchdog" and out["mode"] == "dry_run"
    assert out["requested_by"] == "n8n:wf-1" and out["caller_id"] == "n8n-relay" and out["durable"] is True
    assert out["requested_at"].startswith("2026-10-08T14:00:00")
    assert out["peer_used_as_auth"] is False
    row = runs.get(RUN_ID)
    assert row["state"] == "REQUESTED" and row["started_at"] is None and row["receipt"] is None
    assert ledger._conn.execute("SELECT count(*) AS n FROM runs").fetchone()["n"] == 1
    assert ledger._conn.execute("SELECT count(*) AS n FROM receipts").fetchone()["n"] == 0  # not an event


def test_a_repeated_idempotency_key_returns_the_existing_row_as_a_duplicate_not_a_refusal(stores):
    ledger, _n, _r, runs = stores
    first = _run(stores, "d1")
    runs.claim_next(now=NOW.timestamp() + 5)  # the executor picked it up meanwhile
    again = _run(stores, "d2", mode="live")  # same key, even with a different mode
    assert again["duplicate"] is True and again["state"] == "RUNNING" and again["run_id"] == first["run_id"]
    assert again["mode"] == "dry_run"  # the recorded request wins; nothing was re-queued
    assert ledger._conn.execute("SELECT count(*) AS n FROM runs").fetchone()["n"] == 1


def test_dispatch_key_and_read_scope_cannot_run(stores):
    # read-scope claim on the run route: bad_scope, no row
    out = _run(stores, "s1", caller="tradeai-dispatch", scope=G.SCOPE_READ, key=KEY)
    assert out["state"] == "REFUSED" and out["reason"] == "bad_scope"
    # dispatch caller claiming run scope with the dispatch key: scope not in that caller's set
    out = _run(stores, "s2", caller="tradeai-dispatch", scope=G.SCOPE_RUN, key=KEY)
    assert out["reason"] == "bad_scope"
    # an unnamed Trade AI-side caller (falls back to the dispatch key) still cannot claim run scope
    out = _run(stores, "s3", caller="tradeai-incident-fanin", scope=G.SCOPE_RUN, key=KEY)
    assert out["reason"] == "bad_scope"
    # relay caller_id signed with the DISPATCH key: never verified against it
    out = _run(stores, "s4", caller="n8n-relay", scope=G.SCOPE_RUN, key=KEY)
    assert out["reason"] == "bad_signature"
    # a run-scope claim never reads or transitions an event, even from the relay identity
    out = _run(stores, "s5", scope=G.SCOPE_RUN, route="coordination/status", operation="status")
    assert out["reason"] == "bad_scope"
    assert stores[3].list() == []


def test_run_scope_is_unavailable_without_the_n8n_key_or_a_durable_run_store(stores):
    no_relay = G.build_caller_keys(KEY, previous_key=OLD)  # TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N unset
    assert "n8n-relay" not in no_relay
    out = _run(stores, "u1", caller_keys=no_relay)
    assert out["state"] == "REFUSED" and out["reason"] == "run_scope_unavailable"
    out = _run(stores, "u2", run_store=None)  # --no-ledger: nothing could drain the queue
    assert out["reason"] == "run_scope_unavailable"
    relay_only = {"n8n-relay": G.CallerKey(key=N8N, scopes=frozenset({G.SCOPE_RUN}))}  # no default entry
    out = _run(stores, "u3", caller="somebody-else", caller_keys=relay_only)
    assert out["reason"] == "unknown_caller"


def test_previous_key_overlap_still_works_for_the_dispatch_key_only(stores):
    _l, nonces, receipts, _runs = stores
    req = {
        **_claim("p1", caller="tradeai-dispatch", scope=G.SCOPE_READ, key=OLD),
        "route": "coordination/status",
        "operation": "status",
        "idempotency_key": "idem-00000001",
    }
    keys = G.build_caller_keys(KEY, previous_key=OLD, n8n_key=N8N)
    out = G.handle_request(
        req,
        key=KEY,
        now=NOW,
        nonce_store=nonces,
        idempotency_store=receipts,
        expected_origin_sha=SHA,
        previous_key=OLD,
        caller_keys=keys,
    )
    assert out["reason"] == "unknown_event"  # authenticated; the event just does not exist
    out = _run(stores, "p2", key=OLD)  # relay claim signed with the dispatch previous key
    assert out["reason"] == "bad_signature"


def test_lane_mode_and_idempotency_key_are_validated_against_the_allowlist(stores):
    assert _run(stores, "v1", lane_id="morning-brief-0730")["reason"] == "run_lane_not_allowlisted"
    assert _run(stores, "v2", lane_id="n8n-lab-watchdog", allow=frozenset())["reason"] == "run_lane_not_allowlisted"
    assert _run(stores, "v3", mode="apply")["reason"] == "run_bad_mode"
    assert _run(stores, "v4", mode="live", idempotency_key="short")["reason"] == "malformed_event"
    assert _run(stores, "v5", idempotency_key=None)["reason"] == "missing_idempotency_key"
    assert _run(stores, "v6", requested_by="x" * 200)["reason"] == "malformed_event"
    assert _run(stores, "v7", requested_by="Bearer abc")["reason"] == "secret_material"
    assert _run(stores, "v8", route="coordination/event")["reason"] == "unknown_operation"
    assert stores[3].list() == []  # every refusal wrote nothing
    assert _run(stores, "v9", mode="live")["state"] == "REQUESTED"


def test_run_route_is_allowlisted_and_forbidden_tokens_still_block():
    assert G.route_forbidden("coordination/run") is None
    assert "coordination/run" in G.ALLOWED_ROUTES
    for bad in ("coordination/run/order", "broker/run", "coordination/promote", "coordination/send"):
        assert G.route_forbidden(bad) is not None, bad


def test_new_refusal_literals_are_in_the_enum_and_scanned_by_the_source_test():
    src = (ROOT / "scripts" / "lib" / "n8n_coordination_gateway.py").read_text(encoding="utf-8")
    lits = set(re.findall(r'GatewayError\("([a-z_]+)"\)', src)) | set(
        re.findall(r'_refused\([^,]+,\s*"([a-z_]+)"', src)
    )
    for reason in ("run_lane_not_allowlisted", "run_bad_mode", "run_scope_unavailable", "unknown_caller"):
        assert reason in G.REFUSAL_REASONS and reason in lits, reason
    assert lits <= G.REFUSAL_REASONS, sorted(lits - G.REFUSAL_REASONS)


def test_http_envelope_is_unchanged_and_healthz_reports_the_run_scope(tmp_path):
    ledger = CoordinationLedger(tmp_path / "http.sqlite")
    nonces, receipts, runs = LedgerNonceStore(ledger), LedgerReceiptStore(ledger), LedgerRunStore(ledger)
    keys = G.build_caller_keys(KEY, previous_key=OLD, n8n_key=N8N)
    common = dict(
        key=KEY,
        expected_origin_sha=SHA,
        nonce_store=nonces,
        idempotency_store=receipts,
        now=NOW,
        previous_key=OLD,
        caller_keys=keys,
        run_store=runs,
        run_allowlist=ALLOW,
        ledger_path=tmp_path / "http.sqlite",
    )
    status, health = SRV.dispatch_http("GET", "/healthz", {}, b"", **common)
    assert status == 200 and health["run_scope"] is True and health["run_lanes"] == 2
    body = json.dumps(
        {
            **_claim("h1", caller="n8n-relay", scope=G.SCOPE_RUN, key=N8N),
            "route": "coordination/run",
            "operation": "run",
            "lane_id": "maturity-remeasure",
            "mode": "dry_run",
            "idempotency_key": "run-20261008-maturity-0001",
            "X-Forwarded-For": "203.0.113.5",
        }
    ).encode()
    status, out = SRV.dispatch_http("POST", "/v1/coordination", {"X-Forwarded-For": "203.0.113.5"}, body, **common)
    assert (
        status == 200 and out["schema"] == "RunRequested@v1" and out["state"] == "REQUESTED" and out["durable"] is True
    )
    assert out["proxy_headers_used_as_auth"] is False
    status, refused = SRV.dispatch_http("POST", "/v1/coordination", {}, body, **common)  # replayed nonce
    assert status == 403 and refused["reason"] == "replayed_nonce" and refused["durable"] is False
    # without the relay key the same gateway reports the scope absent and refuses the claim
    status, health = SRV.dispatch_http(
        "GET", "/healthz", {}, b"", **{**common, "caller_keys": G.build_caller_keys(KEY)}
    )
    assert health["run_scope"] is False
    ledger.close()


def test_server_loads_optional_n8n_key_and_the_run_allowlist(tmp_path):
    assert SRV.load_n8n_key({}) is None
    assert SRV.load_n8n_key({SRV.N8N_KEY_ENV: N8N.decode()}) == N8N
    with pytest.raises(SRV.BindRefused):
        SRV.load_n8n_key({SRV.N8N_KEY_ENV: "short"})
    lanes = SRV.load_run_allowlist(ROOT / "config" / "n8n_run_allowlist.json")
    assert {"n8n-lab-watchdog", "maturity-remeasure", "n8n-pilot-dispatch"} <= lanes
    assert SRV.load_run_allowlist(tmp_path / "absent.json") == frozenset()
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "Other@v1", "lanes": [{"lane_id": "x", "command": ["true"]}]}))
    assert SRV.load_run_allowlist(bad) == frozenset()
    httpd = SRV.serve(
        "127.0.0.1",
        0,
        key=KEY,
        expected_origin_sha=SHA,
        ledger_path=tmp_path / "srv.sqlite",
        n8n_key=N8N,
        run_allowlist_path=ROOT / "config" / "n8n_run_allowlist.json",
    )
    try:
        assert "n8n-lab-watchdog" in httpd.run_allowlist
    finally:
        httpd.server_close()
        httpd.coordination_ledger.close()
