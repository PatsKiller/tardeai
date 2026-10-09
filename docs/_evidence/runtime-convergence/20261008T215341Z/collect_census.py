#!/usr/bin/env python3
"""Read-only DB/receipt census; no payloads, credential data or user identity."""

import json
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
STATE = Path("/home/johnclaw/trade-ai-releases/persistent-state")
NOW = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sql(query):
    args = [
        "docker",
        "exec",
        "m8m-n8n-db",
        "psql",
        "-X",
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
    p = subprocess.run(args, capture_output=True, text=True, timeout=20)
    payload = "\n".join(s for s in p.stdout.splitlines() if s not in ("BEGIN", "SET", "COMMIT"))
    return {
        "query": query,
        "exit": p.returncode,
        "data": json.loads(payload) if payload.strip() else None,
        "error": p.stderr[:500] if p.returncode else None,
    }


queries = {
    "db": "SELECT json_build_object('version',version(),'size_bytes',pg_database_size(current_database()),'role',(SELECT row_to_json(r) FROM (SELECT rolname,rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user) r))",
    "columns": "SELECT json_agg(t) FROM (SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_schema='public' AND table_name IN ('workflow_entity','execution_entity','user','user_api_keys','workflow_published_version','workflow_history','webhook_entity','scheduled_job','scheduled_task') ORDER BY table_name,ordinal_position) t",
    "workflow_counts": "SELECT json_build_object('total',count(*),'active',count(*) FILTER(WHERE active),'inactive',count(*) FILTER(WHERE NOT active)) FROM workflow_entity",
    "workflow_metadata": """SELECT json_agg(t) FROM (SELECT id,name,active,"updatedAt",settings FROM workflow_entity ORDER BY name) t""",
    "workflow_nodes": """SELECT json_agg(json_build_object('workflow_id',id,'nodes',(SELECT json_agg(json_build_object('name',n->>'name','type',n->>'type','typeVersion',n->'typeVersion','disabled',n->'disabled','credentials',n->'credentials','schedule',n->'parameters'->'rule','authentication',n->'parameters'->'authentication','host_route',CASE WHEN n->'parameters'->>'url' LIKE 'http%' THEN substring(n->'parameters'->>'url' from '^https?://[^/?#]+') ELSE NULL END,'method',n->'parameters'->'method','lane_id',n->'parameters'->'lane_id','mode',n->'parameters'->'mode')) FROM json_array_elements(nodes) n))) FROM workflow_entity""",
    "execution_counts": 'SELECT json_agg(t) FROM (SELECT status,mode,count(*) AS count,min("startedAt") AS first,max("startedAt") AS last FROM execution_entity GROUP BY status,mode ORDER BY status,mode) t',
    "last_executions": """SELECT json_agg(t) FROM (SELECT id,"workflowId",status,mode,"startedAt","stoppedAt",finished FROM (SELECT *,row_number() OVER(PARTITION BY "workflowId" ORDER BY id DESC) AS rn FROM execution_entity) e WHERE rn<=5 ORDER BY "workflowId",id DESC) t""",
    "credentials": "SELECT json_agg(t) FROM (SELECT name,type,count(*) AS count FROM credentials_entity GROUP BY name,type) t",
    "webhooks": "SELECT json_build_object('count',count(*)) FROM webhook_entity",
    "community": "SELECT json_build_object('packages',(SELECT count(*) FROM installed_packages),'nodes',(SELECT count(*) FROM installed_nodes))",
    "public_api_keys": "SELECT json_build_object('count',count(*)) FROM user_api_keys",
}
results = {k: sql(q) for k, q in queries.items()}
columns = results["columns"].get("data") or []
usercols = {r["column_name"] for r in columns if r["table_name"] == "user"}
if "mfaEnabled" in usercols:
    role = '"roleSlug"' if "roleSlug" in usercols else "'NOT_MEASURED'"
    results["mfa"] = sql(
        "SELECT json_agg(t) FROM (SELECT "
        + role
        + ' AS role,"mfaEnabled",count(*) AS count FROM "user" GROUP BY '
        + role
        + ',"mfaEnabled") t'
    )
(OUT / "06-n8n-db.json").write_text(
    json.dumps({"as_of": NOW, "evidence_class": "OBSERVED_N8N", "results": results}, indent=2) + "\n"
)
ledger = STATE / "data/governance/n8n_coordination_ledger.sqlite"
observations = {"as_of": NOW, "evidence_class": "OBSERVED_DB", "path": str(ledger)}
if ledger.exists():
    conn = sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    observations["run_counts"] = [
        dict(x)
        for x in conn.execute(
            "SELECT lane_id,mode,state,count(*) AS n,max(requested_at) AS last_requested,max(finished_at) AS last_finished FROM runs GROUP BY lane_id,mode,state"
        )
    ]
    observations["runs"] = [
        dict(x)
        for x in conn.execute(
            "SELECT run_id,lane_id,mode,state,requested_by,caller_id,requested_at,started_at,finished_at,exit_code,duration_s,receipt_json FROM runs ORDER BY requested_at DESC LIMIT 1000"
        )
    ]
    for row in observations["runs"]:
        receipt = json.loads(row.pop("receipt_json") or "{}")
        row["receipt"] = {
            k: v
            for k, v in receipt.items()
            if k
            in (
                "schema",
                "run_id",
                "lane_id",
                "mode",
                "state",
                "reason",
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
        }
    observations["queues"] = [
        dict(x)
        for x in conn.execute(
            "SELECT state,count(*) AS n,min(requested_at) AS oldest FROM runs WHERE state IN ('REQUESTED','RUNNING') GROUP BY state"
        )
    ]
    conn.close()
else:
    observations.update(evidence_class="NOT_MEASURED", reason="ledger absent")
(OUT / "08-host-run-ledger.json").write_text(json.dumps(observations, indent=2) + "\n")
backup_files = []
for parent in [Path("/home/johnclaw/m8m-bakeoff-lab/backups"), STATE / "data/runtime", STATE / "data/audit"]:
    if parent.exists():
        for p in parent.glob("**/*n8n*"):
            if p.is_file():
                backup_files.append(
                    {
                        "path": str(p),
                        "size_bytes": p.stat().st_size,
                        "mtime": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
                    }
                )
(OUT / "06-backup-metadata.json").write_text(json.dumps({"as_of": NOW, "files": backup_files}, indent=2) + "\n")
print(
    json.dumps(
        {
            "as_of": NOW,
            "workflow_counts": results["workflow_counts"].get("data"),
            "db": results["db"].get("data"),
            "mfa": results.get("mfa", {}).get("data"),
            "host_runs": len(observations.get("runs", [])),
            "failed_queries": [k for k, v in results.items() if v["exit"]],
        }
    )
)
