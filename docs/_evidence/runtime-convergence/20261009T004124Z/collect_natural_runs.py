#!/usr/bin/env python3
"""Read existing n8n event metadata and host receipts; never trigger a workflow."""

import argparse
import json
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent
STATE = Path.home() / "trade-ai-releases/persistent-state"
PIN = Path.home() / "trade-ai-releases/portfolio-server/CURRENT"
RECEIPT_KEYS = (
    "schema",
    "run_id",
    "lane_id",
    "mode",
    "state",
    "exit_code",
    "duration_s",
    "lock_skipped",
    "timed_out",
    "output_signal",
    "output_signal_mtime_before",
    "output_signal_mtime_after",
    "started_at",
    "finished_at",
    "code_sha",
    "authority",
)
EVENT_JS = r"""
const fs=require('fs'); const base='/home/node/.n8n';
const names=fs.readdirSync(base).filter(n=>/^n8nEventLog(?:-\d+)?\.log$/.test(n));
const events=[];const files=[];const since=process.argv[1];
for(const name of names){const p=base+'/'+name;const s=fs.statSync(p);
 if(s.size>16777216){files.push({name,size:s.size,blocked:'bounded_read_limit'});continue;}
 const lines=fs.readFileSync(p,'utf8').split('\n'); let invalid=0;
 for(const line of lines){if(!line.trim())continue;let x;try{x=JSON.parse(line)}catch{invalid++;continue;}
  if(!['n8n.workflow.started','n8n.workflow.success','n8n.workflow.failed','n8n.workflow.cancelled'].includes(x.eventName))continue;
  if(!x.ts || Date.parse(x.ts)<Date.parse(since))continue;
  const p=x.payload||{}; const e={ts:x.ts,eventName:x.eventName};
  for(const k of ['executionId','workflowId','isManual','mode','success'])if(k in p)e[k]=p[k];
  events.push(e);
 }
 files.push({name,size:s.size,invalid_lines:invalid});
}
console.log(JSON.stringify({files,events}));
"""


def call(args):
    run = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if run.returncode:
        return {"evidence_class": "BLOCKED", "exit_code": run.returncode}
    return json.loads(run.stdout)


def collect(since):
    current = (PIN.resolve() / "GIT_SHA").read_text().strip()
    journal = call(["docker", "exec", "m8m-n8n", "node", "-e", EVENT_JS, since])
    query = """SELECT json_agg(t) FROM (
      SELECT id,name,active,"updatedAt",
       (SELECT json_agg(json_build_object('name',n->>'name','type',n->>'type',
          'rule',n->'parameters'->'rule',
          'relay_credential',n->'credentials'->'httpHeaderAuth'->>'name',
          'run_request_expression_present',n->'parameters'->>'jsonBody' IS NOT NULL))
         FROM json_array_elements(nodes) n) AS nodes
      FROM workflow_entity ORDER BY name) t"""
    db_cmd = [
        "docker",
        "exec",
        "m8m-n8n-db",
        "psql",
        "-X",
        "-q",
        "-U",
        "n8n",
        "-d",
        "n8n",
        "-At",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        "BEGIN READ ONLY; SET LOCAL statement_timeout='10s'; " + query + "; COMMIT;",
    ]
    workflows = call(db_cmd)
    ledger = STATE / "data/governance/n8n_coordination_ledger.sqlite"
    conn = sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    runs = [
        dict(row)
        for row in conn.execute(
            "SELECT run_id,lane_id,mode,state,requested_by,caller_id,requested_at,started_at,"
            "finished_at,exit_code,duration_s,receipt_json FROM runs WHERE requested_at>=? "
            "ORDER BY requested_at,run_id",
            (since,),
        )
    ]
    conn.close()
    for row in runs:
        receipt = json.loads(row.pop("receipt_json") or "{}")
        row["receipt"] = {k: receipt.get(k) for k in RECEIPT_KEYS}
        file = STATE / "data/runtime/n8n_runs" / (row["run_id"] + ".json")
        persisted = json.loads(file.read_text()) if file.is_file() else {}
        row["durable_receipt_path"] = str(file.relative_to(STATE))
        row["durable_receipt_matches_ledger"] = bool(persisted) and all(
            persisted.get(k) == receipt.get(k) for k in RECEIPT_KEYS
        )
        m = re.fullmatch(r"n8n-wf-(.+)-(\d+)", row["run_id"])
        event_matches = [
            event
            for event in journal.get("events", [])
            if m and str(event.get("workflowId")) == m[1] and str(event.get("executionId")) == m[2]
        ]
        row["n8n_execution_events"] = event_matches
        started = [event for event in event_matches if event["eventName"] == "n8n.workflow.started"]
        green = [event for event in event_matches if event["eventName"] == "n8n.workflow.success"]
        row["natural_execution_green"] = bool(started and green) and all(
            event.get("isManual") is False
            and event.get("mode") == "trigger"
            and (event["eventName"] != "n8n.workflow.success" or event.get("success") is True)
            for event in started + green
        )
        row["host_completed_current"] = (
            row["state"] == "RUN_DONE"
            and row["exit_code"] == 0
            and receipt.get("code_sha") == current
            and not receipt.get("lock_skipped")
            and not receipt.get("timed_out")
            and row["durable_receipt_matches_ledger"]
        )
    result = {
        "schema": "NaturalRunObservation@v1",
        "evidence_class": "OBSERVED_CURRENT",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "since": since,
        "current_sha": current,
        "current_release": str(PIN.resolve()),
        "n8n_journal": journal,
        "workflows": workflows,
        "host_runs": runs,
        "manual_triggered": False,
        "successful_payload_retention_changed": False,
    }
    # The workflow JSON expressions are source metadata only; no headers or credential values are read.
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = collect(args.since)
    target = OUT / args.output
    if target.exists():
        raise FileExistsError("Observation artifacts are immutable; choose a new filename")
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "as_of": result["as_of"],
                "current_sha": result["current_sha"],
                "runs": len(result["host_runs"]),
                "green_natural_completed": sum(
                    row["natural_execution_green"] and row["host_completed_current"] for row in result["host_runs"]
                ),
                "journal_class": result["n8n_journal"].get("evidence_class", "OBSERVED_N8N"),
            }
        )
    )


if __name__ == "__main__":
    main()
