"""ANCHOR: N8N_INCIDENT_FANIN_SLOT_LQ1405_20261109 — the */5 fan-in slot stays inside its duration bar.

Measured 2026-11-09T04:40:05Z, run n8n-wf-722fac0e043ea5c4-169960, code b14b1b48e, exit 0 in 24.806 s:
open 285 (P2 126, P1 15, P3 144), every row ARTIFACT_WRITTEN, recovered 4, occurrences
{0: 245, 1: 30, 2: 8, 3: 1, 4: 1}. The contract's degraded check is duration above the 2026-10-11 p95
of 5.021 s, and every recent success was over it. Each open incident was status-polled, then
walk_to_artifact status-polled it again, even though the receipts table already held ARTIFACT_WRITTEN.

Run n8n-wf-722fac0e043ea5c4-168817 (2026-11-09T00:00:06Z) is the exit-1 the earlier assignments chased:
attempted 258, produced 256, skipped dependency_unavailable 2, exit 1, dead letter terminal and
unreleased. Two gateway misses failed a report that had already landed.

Synthetic fixtures only. The isolated target is a temp state root and a temp ledger. No production
receipt, lock, or gateway is touched.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_incident_fanin as fanin  # noqa: E402
from scripts.lib.n8n_output_verdict import evaluate  # noqa: E402

# The 04:40Z slot's shape. Counts only; items are synthetic.
SLOT_SEVERITY = (["P2"] * 126) + (["P1"] * 15) + (["P3"] * 144)
SLOT_OCCURRENCES = ([0] * 245) + ([1] * 30) + ([2] * 8) + [3, 4]
SLOT_RECOVERED = 4
SHA = "b" * 40
RUN_ID = "synthetic-slot-169960"


class CountingGateway:
    """In-memory stand-in. A prefetched ARTIFACT_WRITTEN key must never reach status or accept."""

    url, has_key = "http://127.0.0.1:9", True

    def __init__(self, *, caller_id: str):
        self.status_calls: list[str] = []
        self.accepts: list[str] = []
        self.acks: list[str] = []
        self.unreachable: set[str] = set()
        self.refused: set[str] = set()

    def healthz(self):
        return {"ok": True, "durable": True}

    def status(self, key):
        self.status_calls.append(key)
        if key in self.unreachable:
            return {"state": "UNREACHABLE", "reason": "transport:TimeoutError", "transport": "http"}
        if key in self.refused:
            return {"state": "REFUSED", "reason": "unknown_lane"}
        return {"state": "REFUSED", "reason": "unknown_event"}

    def accept_event(self, ev):
        self.accepts.append(ev["idempotency_key"])
        return {"state": "ACCEPTED", "duplicate": False}

    def transition(self, operation, key, **fields):
        self.acks.append((operation, key))
        if operation == "consumer_ack":
            return {"state": "CONSUMED", "reason": None}
        return {"state": "REFUSED", "reason": f"unsupported:{operation}"}


def _findings(severities):
    return [
        {
            "source": "breach_detector",
            "item": f"synthetic-slot-{i:03d}:NO_OUTPUT",
            "severity": sev,
            "detail": "synthetic open incident",
            "detected_at": "2026-11-09T04:40:05+00:00",
            "artifact_rel": "data/runtime/synthetic_slot.json",
            "store": "data/runtime",
        }
        for i, sev in enumerate(severities)
    ]


def _seed(ledger: Path, keys: list[str]) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ledger)
    conn.execute(
        """CREATE TABLE receipts (
            store_key TEXT PRIMARY KEY,
            payload_hash TEXT,
            receipt_json TEXT NOT NULL,
            project TEXT,
            lane_id TEXT,
            state TEXT,
            updated_at TEXT NOT NULL
        )"""
    )
    now = datetime.now(timezone.utc).isoformat()
    for key in keys:
        body = json.dumps(
            {
                "state": "ARTIFACT_WRITTEN",
                "reason": None,
                "durable": True,
                "lane_id": "incident-fanin",
                "source_project": "trade-ai",
                "idempotency_key": key,
            }
        )
        conn.execute(
            "INSERT INTO receipts (store_key, payload_hash, receipt_json, project, lane_id, state, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"trade-ai:{key}", "synthetic", body, "trade-ai", "incident-fanin", "ARTIFACT_WRITTEN", now),
        )
    conn.commit()
    conn.close()


def _wire(monkeypatch, tmp_path, gateway, findings):
    fanin.NOTES.clear()
    monkeypatch.setattr(fanin, "state_root", lambda: tmp_path)
    monkeypatch.setattr(fanin, "served_sha", lambda: SHA)
    monkeypatch.setattr(fanin, "collect", lambda root, now, _f=list(findings): [dict(x) for x in _f])
    monkeypatch.setattr(fanin, "GatewayClient", lambda *, caller_id: gateway)
    monkeypatch.setenv("TRADEAI_RUN_ID", RUN_ID)
    monkeypatch.setenv("TRADEAI_RUN_ATTEMPT", "1")
    monkeypatch.setenv("TRADEAI_RUN_MODE", "live")
    monkeypatch.setenv("TRADEAI_CODE_SHA", SHA)
    ledger = tmp_path / fanin.LEDGER_REL
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(ledger))
    receipt = tmp_path / "data" / "runtime" / "n8n_incident_fanin_last.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    return receipt, ledger


def _contract_rule():
    doc = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text(encoding="utf-8"))
    contract = next(c for c in doc["contracts"] if c.get("id") == "n8n-incident-fanin")
    return contract["expected_output"]


def _verdict(tmp_path):
    attempt = tmp_path / "data" / "runtime" / "lane_attempts" / "n8n-incident-fanin" / f"{RUN_ID}.json"
    doc = json.loads(attempt.read_text(encoding="utf-8"))
    return evaluate(_contract_rule(), doc, run_id=RUN_ID, lane_id="n8n-incident-fanin", mode="live",
                    attempt=1, code_sha=SHA), doc


def test_receipt_statuses_reads_one_query_per_chunk_and_ignores_a_missing_ledger(tmp_path):
    ledger = tmp_path / "ledger.sqlite"
    keys = [f"inc-synthetic-{i:04d}" for i in range(401)]
    _seed(ledger, keys)
    found = fanin._receipt_statuses(ledger, keys)
    assert set(found) == set(keys)
    assert all(row["state"] == "ARTIFACT_WRITTEN" and row["duplicate"] is False for row in found.values())
    assert fanin._receipt_statuses(tmp_path / "absent.sqlite", ["inc-synthetic-0000"]) == {}


def test_publish_ok_fails_a_refusal_and_a_total_miss_and_keeps_a_partial_miss():
    assert fanin.publish_ok([], apply=True) is True
    assert fanin.publish_ok([{"state": "DRY_RUN"}], apply=False) is True
    assert fanin.publish_ok([{"state": "ARTIFACT_WRITTEN"}, {"state": "UNREACHABLE"}], apply=True) is True
    assert fanin.publish_ok([{"state": "UNREACHABLE"}, {"state": "UNKNOWN"}], apply=True) is False
    assert fanin.publish_ok([{"state": "ARTIFACT_WRITTEN"}, {"state": "REFUSED"}], apply=True) is False


def test_last_slot_shape_lands_from_one_ledger_read(monkeypatch, tmp_path):
    """Emulate run 169960: 285 already-landed incidents, 40 resumed occurrences, 4 recovered keys."""
    assert len(SLOT_SEVERITY) == len(SLOT_OCCURRENCES) == 285
    findings = _findings(SLOT_SEVERITY)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    previous = []
    landed_keys = []
    for finding, occ in zip(findings, SLOT_OCCURRENCES):
        key = fanin.occurrence_key(fanin.idem_key(finding, day), occ)
        landed_keys.append(key)
        row = {"idempotency_key": key, "state": "ARTIFACT_WRITTEN", "source": "breach_detector", "item": finding["item"]}
        if occ:
            row["occurrence"] = occ
        previous.append(row)
    for n in range(SLOT_RECOVERED):
        previous.append(
            {
                "idempotency_key": f"inc-recovered-synthetic-{n}",
                "state": "ARTIFACT_WRITTEN",
                "source": "breach_detector",
                "item": f"synthetic-gone-{n}:NO_OUTPUT",
            }
        )
    gateway = CountingGateway(caller_id="x")
    receipt, ledger = _wire(monkeypatch, tmp_path, gateway, findings)
    _seed(ledger, landed_keys)
    receipt.write_text(json.dumps({"incidents": previous}) + "\n", encoding="utf-8")

    started = time.perf_counter()
    assert fanin.main(["--apply", "--receipt", str(receipt)]) == 0
    elapsed = time.perf_counter() - started

    doc = json.loads(receipt.read_text(encoding="utf-8"))
    assert doc["ok"] is True
    assert doc["open"] == 285
    assert doc["by_severity"] == {"P2": 126, "P1": 15, "P3": 144}
    assert len(doc["recovered"]) == SLOT_RECOVERED
    assert {r["state"] for r in doc["incidents"]} == {"ARTIFACT_WRITTEN"}
    assert doc["source_notes"]["status_prefetch"] == "ok:asked=285:hit=285"
    assert gateway.status_calls == []
    assert gateway.accepts == []
    assert [op for op, _key in gateway.acks] == ["consumer_ack"] * SLOT_RECOVERED
    # The whole isolated slot, including the receipt write, stays under the contract's 5.021 s healthy bar.
    assert elapsed < 5.021, f"isolated slot took {elapsed:.3f}s"
    verdict, attempt = _verdict(tmp_path)
    assert verdict["verdict"] == "produced"
    assert attempt["produced_count"] == 285 and attempt["skipped_reasons"] == {}


def test_a_partial_gateway_miss_stays_ok_and_is_not_a_fatal_skip(monkeypatch, tmp_path):
    """The 168817 shape: most rows landed, two status calls come back UNREACHABLE."""
    findings = _findings(["P2"] * 8 + ["P1"] * 2)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    keys = [fanin.idem_key(f, day) for f in findings]
    gateway = CountingGateway(caller_id="x")
    gateway.unreachable.update(keys[-2:])
    receipt, ledger = _wire(monkeypatch, tmp_path, gateway, findings)
    _seed(ledger, keys[:-2])
    receipt.write_text("{}\n", encoding="utf-8")

    assert fanin.main(["--apply", "--receipt", str(receipt)]) == 0
    doc = json.loads(receipt.read_text(encoding="utf-8"))
    assert doc["ok"] is True and doc["open"] == 10
    assert gateway.status_calls == keys[-2:]
    assert gateway.accepts == []
    verdict, attempt = _verdict(tmp_path)
    assert attempt["produced_count"] == 8
    assert attempt["attempted_count"] == 10
    assert attempt["skipped_reasons"] == {"gateway_unreachable": 2}
    assert attempt["status"] == "ok" and attempt["exit"] == 0
    assert verdict["verdict"] == "produced"
    assert "dependency_unavailable" not in attempt["skipped_reasons"]


def test_every_row_missing_the_gateway_still_fails_the_slot(monkeypatch, tmp_path):
    findings = _findings(["P2"] * 3)
    gateway = CountingGateway(caller_id="x")
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    gateway.unreachable.update(fanin.idem_key(f, day) for f in findings)
    receipt, ledger = _wire(monkeypatch, tmp_path, gateway, findings)
    _seed(ledger, [])
    receipt.write_text("{}\n", encoding="utf-8")

    assert fanin.main(["--apply", "--receipt", str(receipt)]) == 1
    doc = json.loads(receipt.read_text(encoding="utf-8"))
    assert doc["ok"] is False
    lane = json.loads((tmp_path / "data" / "runtime" / "n8n-incident-fanin_last.json").read_text(encoding="utf-8"))
    assert lane["status"] == "failed" and lane["exit"] == 1
    assert lane["skipped_reasons"].get("dependency_unavailable") == 3
    assert "gateway_unreachable" not in lane["skipped_reasons"]


def test_a_gateway_refusal_still_fails_the_slot(monkeypatch, tmp_path):
    findings = _findings(["P1"])
    gateway = CountingGateway(caller_id="x")
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    gateway.refused.add(fanin.idem_key(findings[0], day))
    receipt, ledger = _wire(monkeypatch, tmp_path, gateway, findings)
    _seed(ledger, [])
    receipt.write_text("{}\n", encoding="utf-8")

    assert fanin.main(["--apply", "--receipt", str(receipt)]) == 1
    doc = json.loads(receipt.read_text(encoding="utf-8"))
    assert doc["ok"] is False
    assert doc["incidents"][0]["state"] == "REFUSED"
