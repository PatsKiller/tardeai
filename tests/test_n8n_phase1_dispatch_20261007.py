"""Hermetic proofs for the Phase 1 dispatcher, incident fan-in and gateway client (2026-10-07).

No socket: the client's transport is the gateway's own dispatch_http with an in-memory store.
No real state root: everything is built in tmp_path.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import n8n_coordination_gateway as server
from scripts.lib import n8n_gateway_client as gc
from scripts.lib.n8n_coordination_gateway import PILOT_LANES
from scripts.n8n_incident_fanin import LANE as INCIDENT_LANE
from scripts.n8n_incident_fanin import collect, main as fanin_main
from scripts.n8n_pilot_dispatch import main as dispatch_main, plan_lane

KEY = b"phase1-dispatch-test-key-not-a-live-secret!!"
SHA = "60863d207f4639819f04209f816f71e3056768a7"


def _transport(lane_allowlist):
    nonces, store = {}, {}

    def t(url, envelope):
        status, body = server.dispatch_http("POST", "/v1/coordination", {}, json.dumps(envelope).encode(), key=KEY,
                                            expected_origin_sha=SHA, nonce_store=nonces, idempotency_store=store,
                                            lane_allowlist=lane_allowlist)
        return status, body
    t.store = store
    return t


def _state_root(tmp_path: Path) -> Path:
    root = tmp_path / "state"
    (root / "data" / "runtime").mkdir(parents=True)
    (root / "data" / "cio").mkdir(parents=True)
    (root / "backups" / "n8n").mkdir(parents=True)
    now = datetime.now(timezone.utc)
    (root / "data" / "runtime" / "approval_package_reminder_last.json").write_text(json.dumps({
        "schema": "ApprovalReminderReceipt@v1", "run_id": "run-0001-abcdef", "served_sha": SHA, "planner_status": "OK",
        "outcome": "NO_ACTION", "action_count": 0, "delivery_status": "DELIVERY_OBSERVED", "delivery_receipt_count": 0,
        "started_at": now.isoformat(), "ended_at": now.isoformat()}))
    (root / "data" / "runtime" / "approval_reminder_reconcile_last.json").write_text(json.dumps({
        "schema": "ApprovalReminderReconcileRun@v1", "run_id": "run-0001-abcdef", "delivery_status": "DELIVERY_OBSERVED"}))
    (root / "data" / "runtime" / "llm_spend_report_last_daily.json").write_text(json.dumps({
        "cadence": "daily", "usd": 1.29, "key": "daily:2026-10-06", "ran_at": now.isoformat(), "sent": True}))
    (root / "data" / "runtime" / "supervisor_breaches.jsonl").write_text(
        json.dumps({"schema": "Breach@v1", "breach_id": "x", "lane_id": "cio-delivery", "kind": "NO_OUTPUT",
                    "detected_at": now.isoformat(), "evidence": "no file", "state": "OPEN"}) + "\n" +
        json.dumps({"schema": "Breach@v1", "breach_id": "old", "lane_id": "old-lane", "kind": "SILENT",
                    "detected_at": (now - timedelta(days=5)).isoformat(), "evidence": "stale", "state": "OPEN"}) + "\n")
    (root / "data" / "runtime" / "expected_services_last_run.json").write_text(json.dumps({
        "schema": "ExpectedServicesReport@v1", "ran_at": now.isoformat(), "checked": 10, "off": 1, "off_items": ["INACTIVE:hermes-gateway.service"]}))
    return root


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = _state_root(tmp_path)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(root))
    monkeypatch.setenv("TRADEAI_SERVED_SHA", SHA)
    monkeypatch.setenv("TRADEAI_N8N_GATEWAY_HMAC_KEY", KEY.decode())
    monkeypatch.setenv("TRADEAI_FANIN_LANE_REGISTRY", "0")
    monkeypatch.setenv("TRADEAI_APPROVAL_BOARD", "0")       # 2026-10-08 PR-C: the board reads the guard CLI; keep this fixture hermetic   # 2026-10-08: the lane_registry source probes the host; keep this fixture hermetic
    monkeypatch.delenv("TRADEAI_READ_DSN", raising=False)
    monkeypatch.delenv("TRADE_AI_DSN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return root


def test_client_refuses_without_key_and_reports_unreachable(monkeypatch):
    c = gc.GatewayClient(key=b"short", transport=lambda u, e: (200, {}))
    assert c.status("whatever")["reason"] == "missing_gateway_key"

    def boom(u, e):
        raise ConnectionRefusedError("nope")
    c2 = gc.GatewayClient(key=KEY, transport=boom)
    assert c2.status("whatever")["state"] == "UNREACHABLE"


def test_plan_lane_derives_stable_keys():
    obs = {"run_receipt": {"run_id": "run-0001-abcdef"}}
    a = plan_lane("approval-package-reminder", obs, Path("."))
    b = plan_lane("approval-package-reminder", obs, Path("."))
    assert a["fired"] and a["idempotency_key"] == b["idempotency_key"] and len(a["idempotency_key"]) >= 8
    assert plan_lane("research-scheduler-holdings", {"typed_refusal": {"code": "no_holdings_run_in_window"}}, Path("."))["fired"] is False


def test_dispatch_walks_receipts_to_consumed_and_is_idempotent(env, tmp_path, monkeypatch):
    t = _transport(PILOT_LANES)
    monkeypatch.setattr(gc.GatewayClient, "_http", lambda self, url, envelope: t(url, envelope))
    monkeypatch.setattr(gc.GatewayClient, "healthz", lambda self: {"ok": True, "durable": False})
    receipt = tmp_path / "dispatch.json"
    rc = dispatch_main(["--apply", "--lane", "approval-package-reminder", "--lane", "llm-spend-report-daily", "--receipt", str(receipt)])
    assert rc == 0
    doc = json.loads(receipt.read_text())
    by = {r["lane_id"]: r for r in doc["lanes"]}
    assert by["approval-package-reminder"]["outcome"] == "CONSUMED"      # reconcile receipt = consumer receipt
    assert by["llm-spend-report-daily"]["outcome"] == "ARTIFACT_WRITTEN"  # no consumer yet
    assert all(op["state"] != "REFUSED" for r in by.values() for op in r["ops"])
    # second run: accept is a duplicate, no new transitions beyond status
    rc2 = dispatch_main(["--apply", "--lane", "approval-package-reminder", "--receipt", str(receipt)])
    doc2 = json.loads(receipt.read_text())
    assert rc2 == 0 and doc2["lanes"][0]["ops"][0]["duplicate"] is True
    assert doc2["lanes"][0]["outcome"] in {"CONSUMED", "ARTIFACT_WRITTEN"}
    # the ledger-side state is CONSUMED; nothing was sent or charged
    key = "trade-ai:" + doc2["lanes"][0]["idempotency_key"]
    assert t.store[key]["receipt"]["state"] == "CONSUMED"
    assert t.store[key]["receipt"]["effects"] == []


def test_dispatch_dry_run_writes_nothing(env, tmp_path):
    receipt = tmp_path / "dry.json"
    assert dispatch_main(["--dry-run", "--receipt", str(receipt)]) == 0
    assert not receipt.exists()


def test_incident_fanin_bounds_to_48h_and_closes_on_recovery(env, tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    findings = collect(env, now)
    items = {(f["source"], f["item"]) for f in findings}
    assert ("breach_detector", "cio-delivery:NO_OUTPUT") in items
    assert ("breach_detector", "old-lane:SILENT") not in items          # 5 days old → not open
    assert ("expected_services", "INACTIVE:hermes-gateway.service") in items

    t = _transport(frozenset(PILOT_LANES) | {INCIDENT_LANE})
    monkeypatch.setattr(gc.GatewayClient, "_http", lambda self, url, envelope: t(url, envelope))
    monkeypatch.setattr(gc.GatewayClient, "healthz", lambda self: {"ok": True})
    receipt = tmp_path / "fanin.json"
    assert fanin_main(["--apply", "--receipt", str(receipt)]) == 0
    doc = json.loads(receipt.read_text())
    assert doc["open"] == 2 and all(r["state"] == "ARTIFACT_WRITTEN" for r in doc["incidents"])
    # recovery: the service comes back → next run acks the incident from recovery-observer
    (env / "data" / "runtime" / "expected_services_last_run.json").write_text(json.dumps({
        "schema": "ExpectedServicesReport@v1", "ran_at": now.isoformat(), "checked": 10, "off": 0, "off_items": []}))
    assert fanin_main(["--apply", "--receipt", str(receipt)]) == 0
    doc2 = json.loads(receipt.read_text())
    assert doc2["open"] == 1 and len(doc2["recovered"]) == 1 and doc2["recovered"][0]["state"] == "CONSUMED"


def test_incident_lane_is_refused_unless_allowed(env, tmp_path, monkeypatch):
    t = _transport(PILOT_LANES)                      # gateway started WITHOUT --allow-lane incident-fanin
    monkeypatch.setattr(gc.GatewayClient, "_http", lambda self, url, envelope: t(url, envelope))
    monkeypatch.setattr(gc.GatewayClient, "healthz", lambda self: {"ok": True})
    receipt = tmp_path / "fanin.json"
    assert fanin_main(["--apply", "--receipt", str(receipt)]) == 1
    doc = json.loads(receipt.read_text())
    assert all(r["ops"][0]["reason"] == "unknown_lane" for r in doc["incidents"])


def test_server_allow_lane_flag_threads_through(monkeypatch):
    nonces, store = {}, {}
    ev_ok = {"route": "coordination/event", "operation": "accept_event"}
    # the serve() signature accepts extra_lanes; make_handler accepts lane_allowlist (no bind here)
    import inspect
    assert "extra_lanes" in inspect.signature(server.serve).parameters
    assert "lane_allowlist" in inspect.signature(server.make_handler).parameters
    assert "lane_allowlist" in inspect.signature(server.dispatch_http).parameters
