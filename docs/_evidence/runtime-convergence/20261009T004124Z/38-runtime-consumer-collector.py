#!/usr/bin/env python3
"""Read-only consumer/output inspection with explicit API envelope handling."""

import hashlib
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

OUT = Path(__file__).resolve().parent
STATE = Path.home() / "trade-ai-releases/persistent-state"
LANES = {
    "n8n-pilot-dispatch",
    "n8n-incident-fanin",
    "n8n-research-intake-consumer",
    "crontab-snapshot-for-health-agent",
    "n8n-lab-watchdog",
}


def main():
    result = {
        "schema": "IndependentN1ConsumerObservation@v1",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "evidence_class": "OBSERVED_CURRENT",
        "mutations_performed": False,
    }
    with urlopen("http://127.0.0.1:7777/api/v2/scheduler-operations", timeout=15) as response:
        envelope = json.loads(response.read(4000000))
    data = envelope.get("data", envelope)
    result["operations_projection"] = {
        "envelope_ok": envelope.get("ok"),
        "schema": data.get("schema"),
        "as_of": data.get("as_of"),
        "rows": [
            {
                k: row.get(k)
                for k in [
                    "lane_id",
                    "scheduler_type",
                    "runtime_state",
                    "schedule",
                    "receipt",
                    "output_signal",
                    "output_age",
                    "freshness",
                    "scheduler_drift",
                    "evidence_class",
                    "consumer",
                    "code_sha",
                ]
            }
            for row in data.get("rows", [])
            if row.get("lane_id") in LANES
        ],
    }
    connection = sqlite3.connect(
        (STATE / "data/governance/n8n_coordination_ledger.sqlite").as_uri() + "?mode=ro", uri=True
    )
    connection.row_factory = sqlite3.Row
    # Gateway coordination events use LedgerReceiptStore, not CoordinationLedger.accept's events table.
    sql = "SELECT lane_id,state,count(*) AS count,count(json_extract(receipt_json,'$.consumer_receipt_id')) AS consumer_receipt_count,max(updated_at) AS last_updated FROM receipts GROUP BY lane_id,state ORDER BY lane_id,state"
    result["coordination_receipt_states"] = {"query": sql, "rows": [dict(row) for row in connection.execute(sql)]}
    connection.close()
    result["outputs"] = []
    for name in ["n8n_pilot_dispatch_last.json", "n8n_incident_fanin_last.json", "n8n_research_intake_last.json"]:
        path = STATE / "data/runtime" / name
        doc = json.loads(path.read_text())
        result["outputs"].append(
            {
                "file": str(path.relative_to(STATE)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                **{
                    k: doc.get(k)
                    for k in ["schema", "as_of", "mode", "served_sha", "ok", "fired", "listed", "enqueued_today"]
                },
                "gateway": {k: doc.get("gateway", {}).get(k) for k in ["url", "has_key", "list"]},
                "pilot_rows": [
                    {k: row.get(k) for k in ["lane_id", "fired", "outcome", "observation_status"]}
                    for row in doc.get("lanes", [])
                ],
                "request_count": len(doc.get("requests", [])),
            }
        )
    snapshot = STATE / "data/runtime/crontab_snapshot.txt"
    p = subprocess.run(["crontab", "-l"], capture_output=True, timeout=15)
    snap = snapshot.read_bytes()
    result["snapshot"] = {
        "path": str(snapshot),
        "mtime": datetime.fromtimestamp(snapshot.stat().st_mtime, timezone.utc).isoformat(),
        "sha256": hashlib.sha256(snap).hexdigest(),
        "line_count": len(snap.splitlines()),
        "current_crontab_exit": p.returncode,
        "matches_current_crontab": snap == p.stdout,
        "natural_health_agent_consumption_proof": "NOT_MEASURED: source reader exists; no per-read snapshot/run id receipt",
    }
    target = OUT / "38-runtime-consumer-observation.json"
    if target.exists():
        raise FileExistsError(target)
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "artifact": str(target),
                "as_of": result["as_of"],
                "projection_rows": len(result["operations_projection"]["rows"]),
                "receipt_state_groups": len(result["coordination_receipt_states"]["rows"]),
                "snapshot_matches_current": result["snapshot"]["matches_current_crontab"],
            }
        )
    )


if __name__ == "__main__":
    main()
