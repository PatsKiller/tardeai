"""Read-only Command Center projection of the coordination ledger (plan tranche B, 2026-10-07)."""
from __future__ import annotations

import ast
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_coordination_projection as P  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerReceiptStore  # noqa: E402


def test_no_ledger_is_an_honest_empty_page(tmp_path):
    out = P.project(tmp_path / "absent.sqlite")
    assert out["status"] == "NO_LEDGER" and out["count"] == 0


def test_projection_reads_receipts_in_plain_language(tmp_path):
    path = tmp_path / "l.sqlite"
    ledger = CoordinationLedger(path)
    store = LedgerReceiptStore(ledger)
    rec = {"schema": "N8nCoordinationReceipt@v1", "state": "ARTIFACT_WRITTEN", "reason": None, "event_id": "evt-1", "source_project": "trade-ai",
           "lane_id": "approval-package-reminder", "idempotency_key": "k1", "origin_sha": "e" * 40, "recorded_at": "2026-10-07T04:12:00+00:00",
           "artifact_ref": {"store": "data/runtime", "ref": "approval_package_reminder_last.json", "sha256": "f" * 64, "as_of": "2026-10-07T04:05:00+00:00"},
           "durable": True}
    store["trade-ai:k1"] = {"payload_hash": "h", "receipt": rec}
    ledger.close()
    out = P.project(path)
    assert out["status"] == "OK" and out["count"] == 1
    item = out["items"][0]
    assert item["state_text"] == "artifact written, waiting for a consumer" and item["artifact"]["ref"].endswith("last.json")
    assert item["evidence"] == "ledger:l.sqlite#trade-ai:k1" and item["age_s"] >= 0 and "n8n" not in item["evidence"]
    assert P.project(path, state="consumed")["count"] == 0 and P.project(path, lane_id="approval-package-reminder")["count"] == 1


def test_api_route_calls_the_projection_read_only():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    i = src.index('base_path == "/api/v2/coordination/events"')
    block = src[i:i + 700]
    assert "n8n_coordination_projection import project" in block and "sqlite" not in block
    ast.parse(src[src.rfind("\n", 0, i) + 1:i].rstrip() + "\n" + "pass\n") if False else None
