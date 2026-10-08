"""Hermetic proofs for the research intake chain (Phase 2 PR-D, 2026-10-08).

No socket: the client transport is the gateway's own dispatch_http over an in-memory store (the phase-1
pattern). No DB: the queue writer is a stub that records calls. No Hermes, no LLM, no send.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import n8n_coordination_gateway as server
from scripts import n8n_research_intake_consumer as consumer
from scripts import n8n_research_intake_request as producer
from scripts.lib import n8n_gateway_client as gc
from scripts.lib import n8n_research_intake as contract
from scripts.lib.n8n_coordination_gateway import PILOT_LANES

KEY = b"research-intake-test-key-not-a-live-secret!!"
SHA = "60863d207f4639819f04209f816f71e3056768a7"
NOW = datetime(2026, 10, 8, 2, 0, tzinfo=timezone.utc)


def _transport(lane_allowlist):
    nonces, store = {}, {}

    def t(url, envelope):
        return server.dispatch_http("POST", "/v1/coordination", {}, json.dumps(envelope).encode(), key=KEY,
                                    expected_origin_sha=SHA, nonce_store=nonces, idempotency_store=store,
                                    lane_allowlist=lane_allowlist)
    t.store = store
    return t


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "state"
    (root / "data" / "runtime").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(root))
    monkeypatch.setenv("TRADEAI_SERVED_SHA", SHA)
    monkeypatch.setenv("TRADEAI_N8N_GATEWAY_HMAC_KEY", KEY.decode())
    monkeypatch.delenv(consumer.DAILY_CAP_ENV, raising=False)
    return root


class _Queue:
    """Stand-in for research_intelligence_queue.enqueue: known topics only, dedupes like the real one."""

    def __init__(self, known=("TOPIC-A", "TOPIC-B")):
        self.known = set(known)
        self.rows: list[tuple[str, str]] = []

    def __call__(self, topic_id, requested_by):
        if topic_id not in self.known:
            return {"ok": False, "error": f"unknown topic_id: {topic_id}"}
        if any(t == topic_id for t, _ in self.rows):
            return {"ok": True, "queued": False, "already": "queued", "queue_id": 1}
        self.rows.append((topic_id, requested_by))
        return {"ok": True, "queued": True, "queue_id": len(self.rows), "note": "queued for after close"}


def _client(t):
    return gc.GatewayClient(transport=t, key=KEY, caller_id="test")


def _post(t, subject, rtype="topic", by="operator", now=NOW):
    rc = producer.main(["--subject", subject, "--type", rtype, "--by", by, "--reason", "unit test", "--apply"],
                       client=_client(t), now=now)
    return rc


def test_contract_is_typed_and_round_trips():
    event, sidecar = contract.build_request(subject="TOPIC-A", request_type="topic", requested_by="operator",
                                            reason="why", origin_sha=SHA, now=NOW)
    assert event["lane_id"] == contract.LANE and event["idempotency_key"].startswith("rq-")
    assert contract.parse_subject_key(event["subject_key"]) == {"subject": "TOPIC-A", "request_type": "topic",
                                                                "requested_by": "operator", "priority": "P2"}
    assert event["artifact_ref"].endswith(f"/{event['idempotency_key']}.json") and sidecar["reason"] == "why"
    # same subject+type+day → same key; another day → another key
    assert contract.idempotency_key("TOPIC-A", "topic", now=NOW) == event["idempotency_key"]
    assert contract.idempotency_key("TOPIC-A", "topic", now=NOW.replace(day=9)) != event["idempotency_key"]
    with pytest.raises(contract.RequestError) as exc:
        contract.validate("TOPIC-A", "wizardry", "operator")
    assert exc.value.reason == "typed_refusal:unknown_request_type"
    with pytest.raises(contract.RequestError):
        contract.parse_subject_key("type=topic;subject=TOPIC-A;by=stranger")


def test_request_to_gateway_to_consumer_to_consumed_with_artifact(env, tmp_path):
    t = _transport(frozenset(PILOT_LANES) | {contract.LANE})
    assert _post(t, "TOPIC-A") == 0
    sidecar = env / "data" / "runtime" / contract.sidecar_rel(contract.idempotency_key("TOPIC-A", "topic", now=NOW))
    assert sidecar.exists() and json.loads(sidecar.read_text())["subject"] == "TOPIC-A"
    q = _Queue()
    receipt = tmp_path / "intake.json"
    assert consumer.main(["--apply", "--receipt", str(receipt)], client=_client(t), enqueue=q) == 0
    doc = json.loads(receipt.read_text())
    assert q.rows == [("TOPIC-A", "operator")]
    row = doc["requests"][0]
    assert row["action"] == "enqueue" and row["state"] == "CONSUMED"
    ops = [o["op"] for o in row["ops"]]
    assert ops == ["status", "claim", "start", "artifact", "consumer_ack"]
    ledger = next(s["receipt"] for s in t.store.values())
    assert ledger["state"] == "CONSUMED" and ledger["artifact_ref"]["store"] == "ri_research_queue"
    assert ledger["artifact_ref"]["ref"] == "queue_id=1" and ledger["consumer"] == consumer.CONSUMER
    assert doc["enqueued_today"] == 1 and doc["ok"] is True


def test_same_day_duplicate_is_one_queue_row(env, tmp_path):
    t = _transport(frozenset(PILOT_LANES) | {contract.LANE})
    assert _post(t, "TOPIC-A") == 0
    assert _post(t, "TOPIC-A") == 0                 # gateway replays the receipt with duplicate=True
    assert len(t.store) == 1
    q = _Queue()
    receipt = tmp_path / "intake.json"
    assert consumer.main(["--apply", "--receipt", str(receipt)], client=_client(t), enqueue=q) == 0
    assert consumer.main(["--apply", "--receipt", str(receipt)], client=_client(t), enqueue=q) == 0   # nothing open any more
    assert q.rows == [("TOPIC-A", "operator")]
    assert json.loads(receipt.read_text())["listed"] == 0


def test_unknown_type_is_refused_before_the_gateway_and_no_enqueue_path_is_refused_on_the_ledger(env, tmp_path, capsys):
    t = _transport(frozenset(PILOT_LANES) | {contract.LANE})
    with pytest.raises(SystemExit):
        producer.main(["--subject", "NVDA", "--type", "wizardry", "--by", "operator", "--reason", "x", "--apply"], client=_client(t))
    assert _post(t, "NVDA", rtype="scalp") == 0     # a hermes subject type: accepted as a request, no writer exists
    q = _Queue()
    receipt = tmp_path / "intake.json"
    assert consumer.main(["--apply", "--receipt", str(receipt)], client=_client(t), enqueue=q) == 0
    row = json.loads(receipt.read_text())["requests"][0]
    assert row["action"] == "refuse" and row["reason"] == "typed_refusal:no_enqueue_path:scalp"
    assert row["state"] == "REFUSED" and q.rows == []
    ledger = next(s["receipt"] for s in t.store.values())
    assert ledger["state"] == "REFUSED" and ledger["reason"] == "typed_refusal:no_enqueue_path:scalp"


def test_unknown_topic_is_a_typed_refusal(env, tmp_path):
    t = _transport(frozenset(PILOT_LANES) | {contract.LANE})
    assert _post(t, "TOPIC-ZZ") == 0
    q = _Queue()
    receipt = tmp_path / "intake.json"
    assert consumer.main(["--apply", "--receipt", str(receipt)], client=_client(t), enqueue=q) == 0
    row = json.loads(receipt.read_text())["requests"][0]
    assert row["action"] == "enqueue" and row["reason"] == "typed_refusal:unknown_topic" and row["state"] == "REFUSED"
    assert q.rows == [] and next(s["receipt"] for s in t.store.values())["state"] == "REFUSED"


def test_the_daily_intake_cap_refuses_the_rest_and_counts_across_runs(env, tmp_path, monkeypatch):
    t = _transport(frozenset(PILOT_LANES) | {contract.LANE})
    assert _post(t, "TOPIC-A") == 0
    assert _post(t, "TOPIC-B") == 0
    monkeypatch.setenv(consumer.DAILY_CAP_ENV, "1")
    q = _Queue()
    receipt = tmp_path / "intake.json"
    assert consumer.main(["--apply", "--receipt", str(receipt)], client=_client(t), enqueue=q) == 0
    doc = json.loads(receipt.read_text())
    states = sorted((r["action"], r["state"], r.get("reason")) for r in doc["requests"])
    assert states == [("enqueue", "CONSUMED", None), ("refuse", "REFUSED", "typed_refusal:intake_cap:1")]
    assert len(q.rows) == 1 and doc["enqueued_today"] == 1
    # a later run the same day starts from the receipt's count: still capped, nothing new enqueued
    assert consumer.main(["--apply", "--receipt", str(receipt)], client=_client(t), enqueue=q) == 0
    assert json.loads(receipt.read_text())["enqueued_today"] == 1 and len(q.rows) == 1


def test_dry_run_lists_and_plans_but_writes_nothing(env, tmp_path):
    t = _transport(frozenset(PILOT_LANES) | {contract.LANE})
    assert _post(t, "TOPIC-A") == 0
    q = _Queue()
    receipt = tmp_path / "intake.json"
    assert consumer.main(["--dry-run", "--receipt", str(receipt)], client=_client(t), enqueue=q) == 0
    assert not receipt.exists() and q.rows == []
    assert next(s["receipt"] for s in t.store.values())["state"] == "ACCEPTED"
    # producer dry-run: no sidecar, no post
    before = len(t.store)
    assert producer.main(["--subject", "TOPIC-B", "--type", "topic", "--by", "maria", "--reason", "x", "--dry-run"], client=_client(t), now=NOW) == 0
    assert len(t.store) == before
    assert not (env / "data" / "runtime" / contract.sidecar_rel(contract.idempotency_key("TOPIC-B", "topic", now=NOW))).exists()


def test_the_lane_is_not_a_pilot_lane_and_needs_the_allow_list():
    assert contract.LANE not in PILOT_LANES
    t = _transport(frozenset(PILOT_LANES))            # gateway without --allow-lane research-intake
    event, _ = contract.build_request(subject="TOPIC-A", request_type="topic", requested_by="operator", reason="x", origin_sha=SHA, now=NOW)
    assert _client(t).accept_event(event)["reason"] == "unknown_lane"
    unit = (Path(__file__).resolve().parents[1] / "config" / "systemd" / "user" / "tradeai-n8n-coordination-gateway.service").read_text()
    line = next(l for l in unit.splitlines() if "TRADEAI_N8N_GATEWAY_EXTRA_LANES=" in l)
    assert "research-intake" in line.split("TRADEAI_N8N_GATEWAY_EXTRA_LANES=", 1)[1].strip('"').split()


def test_an_event_without_its_sidecar_is_refused_not_guessed(env, tmp_path):
    t = _transport(frozenset(PILOT_LANES) | {contract.LANE})
    event, _ = contract.build_request(subject="TOPIC-A", request_type="topic", requested_by="operator", reason="x", origin_sha=SHA, now=NOW)
    assert _client(t).accept_event(event)["state"] == "ACCEPTED"     # posted without the producer → no sidecar
    q = _Queue()
    receipt = tmp_path / "intake.json"
    assert consumer.main(["--apply", "--receipt", str(receipt)], client=_client(t), enqueue=q) == 0
    row = json.loads(receipt.read_text())["requests"][0]
    assert row["reason"] == "typed_refusal:missing_request_sidecar" and row["state"] == "REFUSED" and q.rows == []
