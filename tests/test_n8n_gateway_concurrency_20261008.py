"""Gateway handler threads share ONE ledger connection (2026-10-08, first N1 shadow burst).

Measured live at 17:15:00Z: four n8n workflows posted coordination/run within 60 ms; two
ThreadingHTTPServer handler threads both ran ``BEGIN IMMEDIATE`` on the ledger's single sqlite
connection, the second raised ``cannot start a transaction within a transaction``, that handler
died with a traceback, the client saw a dropped connection and the relay logged
relay_gateway_unreachable. The fix is one RLock owned by the ledger that every transaction (and
every read on the shared connection) holds, plus the nonce read-then-consume in _verify_claim
held under the same lock so two claims with the same nonce cannot both pass.

Hermetic: tmp_path ledger and allowlist, 127.0.0.1 port 0, keys that are not live secrets, the
server is shut down by the fixture. The burst sizes mirror the live defect at 4x.

Measured while writing this (probe, not asserted): the stock ThreadingHTTPServer listens with
request_queue_size=5, so a 16-wide simultaneous connect overflows the accept backlog and the
overflowed clients sit on the kernel's 1 s SYN retransmit (wall 1.05 s) although every request is
served. With backlog 64 the same burst takes 24 ms and a 64-wide burst 99 ms. That is a separate
finding (the gateway's listen backlog), not this fix; the fixture raises the backlog on the server
class it hands to ``serve`` so the latency assertions measure the ledger lock, not the SYN timer.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
from http.server import ThreadingHTTPServer
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from scripts import n8n_coordination_gateway as SRV
from scripts.lib import n8n_coordination_gateway as G
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerNonceStore

KEY = b"dispatch-key-not-a-live-secret-0123456"
N8N = b"relay-key-not-a-live-secret-9876543210"
SHA = "a" * 40
LANE = "n8n-research-intake-consumer"
BURST = 16
#: generous ceiling on the mean client-observed latency of one request inside a 16-wide burst;
#: the lock serializes ~1.5 ms of sqlite work per request (measured 2026-10-08: 16-wide wall 24 ms,
#: handler mean 8.5 ms including lock wait), so even a slow CI box stays far below it.
MAX_MEAN_LATENCY_S = 0.25

MEASURED: dict[str, float] = {}


class _WideBacklogServer(ThreadingHTTPServer):
    """Same server, listen backlog wide enough that a 16-wide connect never waits on a SYN retransmit."""

    request_queue_size = 64


def _claim(nonce: str, *, caller: str, scope: str, key: bytes, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    claim = {
        "v": 1,
        "caller_id": caller,
        "project": "trade-ai",
        "iat": now,
        "exp": now + 120,
        "nonce": nonce,
        "scope": scope,
    }
    return {"claim": claim, "signature": hmac.new(key, G.canonical(claim), hashlib.sha256).hexdigest()}


def _run_body(nonce: str, run_id: str) -> bytes:
    return json.dumps(
        {
            **_claim(nonce, caller="n8n-relay", scope=G.SCOPE_RUN, key=N8N),
            "route": "coordination/run",
            "operation": "run",
            "lane_id": LANE,
            "mode": "dry_run",
            "idempotency_key": run_id,
            "requested_by": "n8n:wf-burst",
        }
    ).encode()


def _event_body(nonce: str, idem: str) -> bytes:
    event = {
        "event_id": "evt-" + idem,
        "source_project": "trade-ai",
        "lane_id": "approval-package-reminder",
        "schema_version": G.SCHEMA_VERSION,
        "origin_sha": SHA,
        "subject_key": "BOOK",
        "source_timestamp": "2026-10-08T17:15:00+00:00",
        "deadline": "2026-10-08T18:15:00+00:00",
        "artifact_ref": "data/runtime/approval_package_reminder_last.json",
        "authority_class": "coordination_read",
        "correlation_id": "corr-" + idem,
        "idempotency_key": idem,
    }
    return json.dumps(
        {
            **_claim(nonce, caller="n8n-lab", scope=G.SCOPE_READ, key=KEY),
            "route": "coordination/event",
            "operation": "accept_event",
            "event": event,
        }
    ).encode()


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    monkeypatch.setattr(SRV, "ThreadingHTTPServer", _WideBacklogServer)
    server_side: list[float] = []
    real_dispatch = SRV.dispatch_http

    def timed_dispatch(*args, **kwargs):  # handler-side cost: HMAC + ledger work, including any lock wait
        started = time.perf_counter()
        try:
            return real_dispatch(*args, **kwargs)
        finally:
            server_side.append(time.perf_counter() - started)

    monkeypatch.setattr(SRV, "dispatch_http", timed_dispatch)
    allow = tmp_path / "allow.json"
    allow.write_text(
        json.dumps({"schema": SRV.RUN_ALLOWLIST_SCHEMA, "lanes": [{"lane_id": LANE, "command": ["true"]}]})
    )
    httpd = SRV.serve(
        "127.0.0.1",
        0,
        key=KEY,
        expected_origin_sha=SHA,
        ledger_path=tmp_path / "ledger.sqlite",
        n8n_key=N8N,
        run_allowlist_path=allow,
    )
    tracebacks: list[str] = []

    def record_handler_error(request, client_address):  # a handler thread died: that is the live defect
        tracebacks.append(traceback.format_exc())

    httpd.handle_error = record_handler_error  # type: ignore[method-assign]
    httpd.server_side_s = server_side  # type: ignore[attr-defined]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd, tracebacks
    finally:
        httpd.shutdown()
        httpd.server_close()
        httpd.coordination_ledger.close()


def _post(port: int, body: bytes) -> tuple[int | None, dict | None, float]:
    """One request on its own connection; a dropped connection comes back as (None, None, latency)."""
    started = time.perf_counter()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("POST", "/v1/coordination", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read()), time.perf_counter() - started
    except (http.client.HTTPException, ConnectionError, OSError):
        return None, None, time.perf_counter() - started
    finally:
        conn.close()


def _burst(port: int, bodies: list[bytes]) -> list[tuple[int | None, dict | None, float]]:
    gate = threading.Barrier(len(bodies))

    def fire(body: bytes):
        gate.wait(timeout=10)
        return _post(port, body)

    with ThreadPoolExecutor(max_workers=len(bodies)) as pool:
        return list(pool.map(fire, bodies))


def test_sixteen_concurrent_run_requests_all_land_as_requested_rows(gateway):
    httpd, tracebacks = gateway
    port = httpd.server_address[1]
    bodies = [_run_body(f"nonce-run-{i:04d}", f"run-20261008-burst-{i:04d}") for i in range(BURST)]
    wall = time.perf_counter()
    results = _burst(port, bodies)
    wall = time.perf_counter() - wall
    dropped = [r for r in results if r[0] is None]
    assert not dropped, f"{len(dropped)} dropped connections; tracebacks={tracebacks}"
    assert tracebacks == []
    assert all(
        status == 200 and out["state"] == "REQUESTED" and out["duplicate"] is False for status, out, _ in results
    )
    rows = httpd.coordination_ledger._conn.execute("SELECT state, COUNT(*) AS n FROM runs GROUP BY state").fetchall()
    assert [(r["state"], r["n"]) for r in rows] == [("REQUESTED", BURST)]
    latencies = [lat for _, _, lat in results]
    MEASURED["run_burst_client_mean_s"] = sum(latencies) / len(latencies)
    MEASURED["run_burst_client_max_s"] = max(latencies)
    MEASURED["run_burst_wall_s"] = wall
    MEASURED["run_burst_wall_per_request_ms"] = wall / BURST * 1e3  # the serialized cost of one request
    handler = httpd.server_side_s
    MEASURED["run_burst_handler_mean_ms"] = sum(handler) / len(handler) * 1e3
    MEASURED["run_burst_handler_max_ms"] = max(handler) * 1e3
    assert len(handler) == BURST
    assert MEASURED["run_burst_client_mean_s"] < MAX_MEAN_LATENCY_S


def test_sixteen_concurrent_event_accepts_with_distinct_nonces_all_commit(gateway):
    httpd, tracebacks = gateway
    port = httpd.server_address[1]
    bodies = [_event_body(f"nonce-evt-{i:04d}", f"idem-burst-{i:04d}") for i in range(BURST)]
    results = _burst(port, bodies)
    dropped = [r for r in results if r[0] is None]
    assert not dropped, f"{len(dropped)} dropped connections; tracebacks={tracebacks}"
    assert tracebacks == []
    assert all(status == 200 and out["state"] == "ACCEPTED" and out["durable"] is True for status, out, _ in results)
    conn = httpd.coordination_ledger._conn
    assert conn.execute("SELECT COUNT(*) AS n FROM receipts").fetchone()["n"] == BURST
    assert conn.execute("SELECT COUNT(*) AS n FROM nonces").fetchone()["n"] == BURST
    latencies = [lat for _, _, lat in results]
    MEASURED["event_burst_client_mean_s"] = sum(latencies) / len(latencies)
    handler = httpd.server_side_s
    MEASURED["event_burst_handler_mean_ms"] = sum(handler) / len(handler) * 1e3
    assert MEASURED["event_burst_client_mean_s"] < MAX_MEAN_LATENCY_S


def test_two_concurrent_requests_with_the_same_nonce_yield_one_accept_and_one_replay_refusal(gateway):
    httpd, tracebacks = gateway
    port = httpd.server_address[1]
    for round_no in range(8):  # the live race is a sub-millisecond window; eight rounds, never two accepts
        nonce = f"nonce-same-{round_no:04d}"
        bodies = [_run_body(nonce, f"run-20261008-same-{round_no:04d}-{k}") for k in range(2)]
        results = _burst(port, bodies)
        assert all(status is not None for status, _, _ in results), tracebacks
        statuses = sorted(status for status, _, _ in results)
        reasons = sorted(out.get("reason", "") for _, out, _ in results)
        assert statuses == [200, 403], (statuses, reasons)
        assert reasons == ["", "replayed_nonce"]
    assert tracebacks == []
    assert httpd.coordination_ledger._conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"] == 8


class _SlowNonceStore(LedgerNonceStore):
    """Holds the read-then-consume window open so the interleaving the live race depends on is forced."""

    def get(self, nonce, default=None):
        value = super().get(nonce, default)
        time.sleep(0.05)
        return value


def test_verify_claim_consumes_the_nonce_atomically_under_the_ledger_lock(tmp_path):
    ledger = CoordinationLedger(tmp_path / "race.sqlite")
    store = _SlowNonceStore(ledger)
    keys = G.build_caller_keys(KEY, n8n_key=N8N)
    request = _claim("nonce-atomic-0001", caller="n8n-relay", scope=G.SCOPE_RUN, key=N8N)
    gate = threading.Barrier(2)
    outcomes: list[str] = []

    def verify():
        gate.wait(timeout=5)
        try:
            G._verify_claim(request, key=KEY, now=datetime.now(timezone.utc), nonce_store=store, caller_keys=keys)
            outcomes.append("accepted")
        except G.GatewayError as exc:
            outcomes.append(exc.reason)

    threads = [threading.Thread(target=verify) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    try:
        assert sorted(outcomes) == ["accepted", "replayed_nonce"]
    finally:
        ledger.close()


def test_lock_cost_is_negligible_against_one_sqlite_transaction(tmp_path):
    """The number the PR reports: RLock acquire/release versus one nonce transaction on the same ledger."""
    ledger = CoordinationLedger(tmp_path / "cost.sqlite")
    store = LedgerNonceStore(ledger)
    try:
        assert isinstance(ledger.lock, type(threading.RLock())) and store.lock is ledger.lock
        rounds = 2000
        started = time.perf_counter()
        for _ in range(rounds):
            with ledger.lock:
                pass
        MEASURED["lock_acquire_release_us"] = (time.perf_counter() - started) / rounds * 1e6
        started = time.perf_counter()
        for i in range(200):
            store[f"nonce-cost-{i:04d}"] = time.time() + 120
        MEASURED["nonce_txn_us"] = (time.perf_counter() - started) / 200 * 1e6
        assert MEASURED["lock_acquire_release_us"] < 50  # microseconds; the transaction itself is ~100x that
    finally:
        ledger.close()
    print("\nMEASURED", json.dumps({k: round(v, 6) for k, v in MEASURED.items()}, sort_keys=True))
