"""Durable gateway (plan tranche B, 2026-10-07): nonces, receipts and artifact refs survive a restart;
list and artifact-ref operations; the refusal enum covers every literal; ledger transitions are enforced."""
from __future__ import annotations

import ast
import hashlib
import hmac
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_coordination_gateway as G  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerError, LedgerNonceStore, LedgerReceiptStore  # noqa: E402
from scripts import n8n_coordination_gateway as SRV  # noqa: E402

KEY = b"k" * 32
SHA = "c" * 40


def _claim(nonce: str, now: float) -> dict:
    claim = {"v": 1, "caller_id": "n8n-lab", "project": "trade-ai", "iat": now, "exp": now + 120, "nonce": "nonce-" + nonce, "scope": "coordination_read"}
    return {"claim": claim, "signature": hmac.new(KEY, G.canonical(claim), hashlib.sha256).hexdigest()}


def _event(idem: str, lane: str = "approval-package-reminder") -> dict:
    return {"event_id": "evt-" + idem, "source_project": "trade-ai", "lane_id": lane, "schema_version": G.SCHEMA_VERSION,
            "origin_sha": SHA, "subject_key": "BOOK", "source_timestamp": "2026-10-07T04:05:00+00:00",
            "deadline": "2026-10-07T05:05:00+00:00", "artifact_ref": "data/runtime/approval_package_reminder_last.json",
            "authority_class": "coordination_read", "correlation_id": "corr-" + idem, "idempotency_key": idem}


def _call(operation: str, nonce: str, *, nonces, store, now=None, **extra) -> dict:
    now = now or time.time()
    route = "coordination/status" if operation in ("status", "list") else "coordination/event"
    req = {**_claim(nonce, now), "route": route, "operation": operation, **extra}
    return G.handle_request(req, key=KEY, now=datetime.fromtimestamp(now, timezone.utc), nonce_store=nonces,
                            idempotency_store=store, expected_origin_sha=SHA)


def _stores(path):
    ledger = CoordinationLedger(path)
    return ledger, LedgerNonceStore(ledger), LedgerReceiptStore(ledger)


def test_accept_is_durable_across_a_restart_and_the_nonce_cannot_be_replayed(tmp_path):
    path = tmp_path / "ledger.sqlite"
    ledger, nonces, store = _stores(path)
    r = _call("accept_event", "n-1", nonces=nonces, store=store, event=_event("idem-0001"))
    assert r["state"] == "ACCEPTED" and r["durable"] is True
    ledger.close()
    ledger2, nonces2, store2 = _stores(path)                       # the process restarted
    replay = _call("accept_event", "n-1", nonces=nonces2, store=store2, event=_event("idem-0001"))
    assert replay["state"] == "REFUSED" and replay["reason"] == "replayed_nonce"
    dup = _call("accept_event", "n-2", nonces=nonces2, store=store2, event=_event("idem-0001"))
    assert dup["state"] == "ACCEPTED" and dup["duplicate"] is True
    status = _call("status", "n-3", nonces=nonces2, store=store2, idempotency_key="idem-0001")
    assert status["state"] == "ACCEPTED" and status["durable"] is True
    ledger2.close()


def test_transitions_and_artifact_refs_persist_and_list_reads_them_back(tmp_path):
    ledger, nonces, store = _stores(tmp_path / "l.sqlite")
    assert _call("accept_event", "a-1", nonces=nonces, store=store, event=_event("idem-0002"))["state"] == "ACCEPTED"
    assert _call("claim", "a-2", nonces=nonces, store=store, idempotency_key="idem-0002")["state"] == "CLAIMED"
    assert _call("start", "a-3", nonces=nonces, store=store, idempotency_key="idem-0002")["state"] == "STARTED"
    ref = {"store": "data/runtime", "ref": "approval_package_reminder_last.json", "sha256": "b" * 64, "as_of": "2026-10-07T04:05:30+00:00"}
    w = _call("artifact", "a-4", nonces=nonces, store=store, idempotency_key="idem-0002", artifact_ref=ref)
    assert w["state"] == "ARTIFACT_WRITTEN" and w["artifact_ref"] == ref and w["durable"] is True
    rows = ledger._conn.execute("SELECT store, ref, sha256 FROM artifact_refs").fetchall()
    assert len(rows) == 1 and rows[0]["ref"] == ref["ref"]
    listed = _call("list", "a-5", nonces=nonces, store=store, lane_id="approval-package-reminder")
    assert listed["schema"] == G.LIST_SCHEMA and listed["count"] == 1 and listed["items"][0]["state"] == "ARTIFACT_WRITTEN" and listed["durable"] is True
    assert _call("list", "a-6", nonces=nonces, store=store, state="CONSUMED")["count"] == 0
    assert _call("list", "a-7", nonces=nonces, store=store, since="not-a-time")["reason"] == "bad_time"
    ledger.close()


def test_memory_store_receipts_stay_not_durable_and_list_works_there_too():
    nonces: dict = {}
    store: dict = {}
    r = _call("accept_event", "m-1", nonces=nonces, store=store, event=_event("idem-0003"))
    assert r["durable"] is False
    assert _call("list", "m-2", nonces=nonces, store=store)["count"] == 1


def test_ledger_mark_terminal_enforces_the_transition_table(tmp_path):
    ledger = CoordinationLedger(tmp_path / "t.sqlite")
    ledger.accept(nonce="nonce-xx-1", nonce_exp=time.time() + 60, idempotency_key="k1", payload_hash="h", now=time.time(),
                  source_sha=SHA, served_sha=SHA, caller_id="c")
    with pytest.raises(LedgerError, match="illegal_transition:ACCEPTED->CONSUMED"):
        ledger.mark_terminal("k1", state="CONSUMED", now=time.time(), consumer="x", consumer_receipt_id="y")
    assert ledger.mark_terminal("k1", state="CLAIMED", now=time.time())["state"] == "CLAIMED"
    with pytest.raises(LedgerError, match="illegal_transition:CLAIMED->ARTIFACT_WRITTEN"):
        ledger.mark_terminal("k1", state="ARTIFACT_WRITTEN", now=time.time())
    ledger.close()


def test_every_refusal_literal_is_in_the_enum():
    src = (ROOT / "scripts" / "lib" / "n8n_coordination_gateway.py").read_text(encoding="utf-8")
    lits = set(re.findall(r'GatewayError\("([a-z_]+)"\)', src)) | set(re.findall(r'_refused\([^,]+,\s*"([a-z_]+)"', src))
    assert lits <= G.REFUSAL_REASONS, sorted(lits - G.REFUSAL_REASONS)
    with pytest.raises(G.GatewayError, match="unknown_refusal_reason"):
        G._refused(None, "made_up_reason", peer_ignored=None)
    tree = ast.parse(src)
    assert any(isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "REFUSAL_REASONS" for t in n.targets) for n in tree.body)


def test_http_server_uses_the_ledger_when_given_one(tmp_path):
    path = tmp_path / "srv.sqlite"
    httpd = SRV.serve("127.0.0.1", 0, key=KEY, expected_origin_sha=SHA, ledger_path=path)
    try:
        import threading
        import urllib.request
        t = threading.Thread(target=httpd.serve_forever, daemon=True); t.start()
        port = httpd.server_address[1]
        health = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5).read())
        assert health["ok"] is True and health["durable"] is True and health["ledger"].endswith("srv.sqlite")
        body = json.dumps({**_claim("h-1", time.time()), "route": "coordination/event", "operation": "accept_event", "event": _event("idem-http-1")}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/coordination", data=body, headers={"Content-Type": "application/json"})
        out = json.loads(urllib.request.urlopen(req, timeout=5).read())
        assert out["state"] == "ACCEPTED" and out["durable"] is True
    finally:
        httpd.shutdown(); httpd.server_close()
    again = CoordinationLedger(path)
    assert again._conn.execute("SELECT count(*) AS n FROM receipts").fetchone()["n"] == 1
    again.close()
