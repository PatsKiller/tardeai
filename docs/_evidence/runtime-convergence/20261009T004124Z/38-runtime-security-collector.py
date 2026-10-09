#!/usr/bin/env python3
"""Read-only n8n security/runtime metadata, excluding secret values and payloads."""

import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

OUT = Path(__file__).resolve().parent
STATE = Path.home() / "trade-ai-releases/persistent-state"
ENV_KEYS = {
    "EXECUTIONS_DATA_SAVE_ON_SUCCESS",
    "EXECUTIONS_DATA_SAVE_ON_ERROR",
    "EXECUTIONS_DATA_PRUNE",
    "EXECUTIONS_DATA_MAX_AGE",
    "N8N_BLOCK_ENV_ACCESS_IN_NODE",
    "NODES_EXCLUDE",
    "N8N_COMMUNITY_PACKAGES_ENABLED",
    "N8N_PUBLIC_API_DISABLED",
    "EXECUTIONS_MODE",
    "N8N_RUNNERS_ENABLED",
    "N8N_RUNNERS_MODE",
    "N8N_LOG_LEVEL",
    "N8N_METRICS",
    "DB_TYPE",
    "N8N_DIAGNOSTICS_ENABLED",
}


def call(args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if p.returncode:
        return {"evidence_class": "BLOCKED", "exit": p.returncode}
    return {"exit": 0, "value": p.stdout}


def query(sql):
    r = call(
        [
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
            "BEGIN READ ONLY; SET LOCAL statement_timeout='10s'; " + sql + "; COMMIT;",
        ]
    )
    if r["exit"]:
        return r
    return {"exit": 0, "data": json.loads(r["value"])}


def main():
    result = {
        "schema": "IndependentN8nSecurityMetadata@v1",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "evidence_class": "OBSERVED_N8N",
        "mutations_performed": False,
    }
    r = call(["docker", "inspect", "m8m-n8n"])
    if not r["exit"]:
        c = json.loads(r["value"])[0]
        env = dict(item.split("=", 1) for item in c["Config"]["Env"] if "=" in item)
        result["container"] = {
            "image": c["Config"]["Image"],
            "image_digest": c["Image"],
            "restart_count": c["RestartCount"],
            "state": {
                k: c["State"].get(k) for k in ["Status", "Running", "StartedAt", "FinishedAt", "ExitCode", "OOMKilled"]
            },
            "healthcheck_configured": bool(c["Config"].get("Healthcheck")),
            "compose_file": c["Config"].get("Labels", {}).get("com.docker.compose.project.config_files"),
            "published_ports": c["NetworkSettings"]["Ports"],
            "networks": list(c["NetworkSettings"]["Networks"]),
            "encryption_key_configured": bool(env.get("N8N_ENCRYPTION_KEY")),
            "hardening_env": {k: env[k] for k in ENV_KEYS if k in env},
        }
    else:
        result["container"] = r
    ver = call(["docker", "exec", "m8m-n8n", "n8n", "--version"])
    result["version"] = ver["value"].strip() if not ver["exit"] else ver
    queries = {
        "database": "SELECT json_build_object('version',version(),'size_bytes',pg_database_size(current_database()),'role',(SELECT row_to_json(r) FROM (SELECT rolname,rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user) r))",
        "workflows": "SELECT json_build_object('total',count(*),'active',count(*) FILTER(WHERE active),'inactive',count(*) FILTER(WHERE NOT active)) FROM workflow_entity",
        "owner_mfa": 'SELECT json_agg(t) FROM (SELECT "roleSlug" AS role,"mfaEnabled",count(*) AS count FROM "user" GROUP BY "roleSlug","mfaEnabled") t',
        "credential_metadata_only": "SELECT json_agg(t) FROM (SELECT name,type,count(*) AS count FROM credentials_entity GROUP BY name,type) t",
        "public_api_keys": "SELECT json_build_object('count',count(*)) FROM user_api_keys",
        "community_packages": "SELECT json_build_object('packages',(SELECT count(*) FROM installed_packages),'nodes',(SELECT count(*) FROM installed_nodes))",
        "execution_metadata": 'SELECT json_agg(t) FROM (SELECT status,mode,count(*) AS count,min("startedAt") AS first,max("startedAt") AS last FROM execution_entity GROUP BY status,mode) t',
    }
    result["db_observations"] = {name: {"query": sql, **query(sql)} for name, sql in queries.items()}
    ledger = sqlite3.connect((STATE / "data/governance/n8n_coordination_ledger.sqlite").as_uri() + "?mode=ro", uri=True)
    ledger.row_factory = sqlite3.Row
    result["host_ledger_event_states"] = [
        dict(r)
        for r in ledger.execute(
            "SELECT state,count(*) AS count,count(consumer_receipt_id) AS attributed_consumer_receipts,max(updated_at) AS last_updated FROM events GROUP BY state"
        )
    ]
    ledger.close()
    result["journal"] = {}
    for unit in [
        "tradeai-n8n-coordination-gateway.service",
        "tradeai-n8n-run-relay.service",
        "tradeai-n8n-run-executor.service",
    ]:
        j = call(["journalctl", "--user", "-u", unit, "--since", "2026-10-09 01:58:20 UTC", "--no-pager", "-o", "cat"])
        result["journal"][unit] = {
            "exit": j["exit"],
            "since": "2026-10-09T01:58:20+00:00",
            "traceback_count": j.get("value", "").count("Traceback (most recent call last)"),
            "handler_error_count": j.get("value", "").count("Exception occurred during processing of request"),
            "observed_line_count": len(j.get("value", "").splitlines()),
        }
    try:
        with urlopen("http://127.0.0.1:7777/api/v2/scheduler-operations", timeout=15) as response:
            envelope = json.loads(response.read(4000000))
        payload = envelope.get("data", envelope)
        result["operations_projection"] = {
            "schema": payload.get("schema"),
            "as_of": payload.get("as_of"),
            "code_sha": payload.get("code_sha"),
            "keys": sorted(payload),
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
                    ]
                }
                for row in payload.get("rows", [])
                if row.get("lane_id")
                in [
                    "n8n-pilot-dispatch",
                    "n8n-incident-fanin",
                    "n8n-research-intake-consumer",
                    "crontab-snapshot-for-health-agent",
                    "n8n-lab-watchdog",
                ]
            ],
        }
    except Exception as exc:
        result["operations_projection"] = {"evidence_class": "BLOCKED", "error_class": type(exc).__name__}
    target = OUT / "38-runtime-security-metadata.json"
    if target.exists():
        raise FileExistsError(target)
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "artifact": str(target),
                "as_of": result["as_of"],
                "version": result["version"],
                "workflow_counts": result["db_observations"]["workflows"],
                "owner_mfa": result["db_observations"]["owner_mfa"],
            }
        )
    )


if __name__ == "__main__":
    main()
