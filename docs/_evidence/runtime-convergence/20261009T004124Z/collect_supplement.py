#!/usr/bin/env python3
"""Read-only supplemental census. Output contains metadata, never secret values.

Consumer: this campaign's inventory/report. Every database transaction is read-only.
No requests go to broker APIs and no scheduler or firewall is changed.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
STATE = Path("/home/johnclaw/trade-ai-releases/persistent-state")
sys.path.insert(0, str(ROOT))
from scripts.lib.scheduler_operations import collect_host, redact_command

NOW = datetime.now(timezone.utc).isoformat()


def command(argv, timeout=15):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return {
            "command": argv,
            "exit": p.returncode,
            "stdout": redact_command(p.stdout),
            "error_class": "command_failed" if p.returncode else None,
        }
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"command": argv, "exit": None, "stdout": "", "error_class": type(e).__name__}


def save(name, data):
    (OUT / name).write_text(json.dumps({"as_of": NOW, **data}, indent=2, default=str) + "\n")


obs = collect_host()
save("01-live-scheduler-observations.json", {"evidence_class": "OBSERVED_HOST", "observations": obs})

# Actual process cwd/executable and ancestry. Arguments are redacted before writing.
listed = command(["ps", "-eo", "pid=,ppid=,args="])
all_processes = {}
for line in listed["stdout"].splitlines():
    parts = line.split(None, 2)
    if len(parts) != 3 or not parts[0].isdigit():
        continue
    pid = int(parts[0])
    all_processes[pid] = {"pid": pid, "ppid": int(parts[1]), "command": parts[2]}
selected = []
for pid, row in all_processes.items():
    if not re.search(r"tradeai|trade-ai|openclaw|n8n|hermes|portfolio_server|cio_", row["command"], re.I):
        continue
    for key in ("cwd", "exe"):
        try:
            row[key] = str((Path("/proc") / str(pid) / key).resolve(strict=True))
        except OSError:
            row[key] = None
    parent = row["ppid"]
    row["ancestry"] = []
    for _ in range(10):
        ancestor = all_processes.get(parent)
        if not ancestor:
            break
        row["ancestry"].append({"pid": parent, "command": ancestor["command"]})
        parent = ancestor["ppid"]
    selected.append(row)
save("04-process-roots.json", {"evidence_class": "OBSERVED_HOST", "processes": selected})

# Unit links and launcher source are metadata. Source traces are separate from PID proof.
links = []
for p in (Path.home() / ".config/systemd/user").glob("*"):
    if p.name in obs["systemd"]["units"]:
        links.append(
            {
                "unit": p.name,
                "path": str(p),
                "is_symlink": p.is_symlink(),
                "target": str(p.resolve()),
                "target_exists": p.exists(),
            }
        )
save("04-unit-links.json", {"evidence_class": "OBSERVED_HOST", "links": links})

# Tcp connect only: never issue an API request or authenticate to these services.
node = """const net=require('net');const ports=[18092,18091,7777,7776,5432,11434,55432];
Promise.all(ports.map(port=>new Promise(resolve=>{const s=net.connect({host:'172.19.0.1',port});
const end=result=>{s.destroy();resolve({host:'172.19.0.1',port,result})};s.setTimeout(1500);
s.once('connect',()=>end('REACHABLE'));s.once('error',()=>end('REFUSED'));s.once('timeout',()=>end('TIMEOUT'));})))
.then(rows=>process.stdout.write(JSON.stringify(rows)));"""
net = command(["docker", "exec", "m8m-n8n", "node", "-e", node], timeout=20)
save(
    "07-network-probes.json",
    {
        "evidence_class": "OBSERVED_N8N",
        "tcp_probe": net,
        "firewall": command(["sudo", "-n", "ufw", "status", "numbered"]),
    },
)

# Backups: actual dump filenames, timestamps and selected receipt metadata only.
backups = []
for p in (STATE / "backups/n8n").glob("**/*"):
    if p.is_file():
        row = {
            "path": str(p),
            "size_bytes": p.stat().st_size,
            "mtime": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
        }
        if p.suffix == ".json":
            try:
                d = json.loads(p.read_text())
                row["receipt"] = {
                    k: d[k]
                    for k in (
                        "schema",
                        "ok",
                        "started_at",
                        "finished_at",
                        "dump_file",
                        "size_bytes",
                        "sha256",
                        "exit_code",
                        "restored",
                        "checked_at",
                        "counts_match",
                    )
                    if k in d
                }
            except (ValueError, OSError):
                row["receipt"] = "unreadable"
        backups.append(row)
save("06-backups-current.json", {"evidence_class": "OBSERVED_HOST", "files": backups})

# Scope-limited env load, no value appears in the output or command arguments.
db = {"evidence_class": "NOT_MEASURED", "queries": {}}
try:
    from scripts.lib.env_bootstrap import load_env

    load_env()
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME", "trade_ai"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        connect_timeout=5,
    )
    conn.set_session(readonly=True, autocommit=False)
    db["evidence_class"] = "OBSERVED_DB"

    def query(name, sql):
        t = time.perf_counter()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='10s'")
                cur.execute(sql)
                rows = [dict(x) for x in cur.fetchall()]
            conn.rollback()
            db["queries"][name] = {"query": sql, "rows": rows, "elapsed_s": round(time.perf_counter() - t, 4)}
            return rows
        except psycopg2.Error as e:
            conn.rollback()
            db["queries"][name] = {"query": sql, "error_class": type(e).__name__}
            return []

    query("identity", "SELECT version(), pg_database_size(current_database()) AS size_bytes")
    columns = query(
        "queue_columns",
        "SELECT table_schema,table_name,column_name,data_type FROM information_schema.columns WHERE table_schema NOT IN ('pg_catalog','information_schema') AND (table_name ~ '(queue|outbox|wake|jobs|proposal)' OR table_name IN ('content_embeddings','embedding')) ORDER BY table_schema,table_name,ordinal_position",
    )
    tables = {}
    for row in columns:
        tables.setdefault((row["table_schema"], row["table_name"]), {})[row["column_name"]] = row["data_type"]
    for (schema, table), cols in tables.items():
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*", schema + table):
            continue
        ident = f'"{schema}"."{table}"'
        status = next((c for c in ("status", "state") if c in cols), None)
        at = next(
            (c for c in ("created_at", "requested_at", "enqueued_at", "ts") if c in cols and "timestamp" in cols[c]),
            None,
        )
        if status:
            extra = f',min("{at}") AS oldest,max("{at}") AS newest' if at else ""
            query(
                "queue:" + schema + "." + table,
                f'SELECT "{status}" AS status,count(*) AS n{extra} FROM {ident} GROUP BY "{status}"',
            )
    query(
        "embedding_storage",
        "SELECT count(*) AS rows,min(created_at) AS oldest,max(created_at) AS newest,count(*) FILTER (WHERE created_at > NOW()-INTERVAL '1 day') AS writes_24h,pg_total_relation_size('content_embeddings') AS total_bytes,pg_relation_size('content_embeddings') AS heap_bytes FROM content_embeddings",
    )
    query(
        "pipeline_24h_metrics",
        "SELECT pipeline_key,trigger_source,status,count(*) AS n,min(started_at) AS first,max(finished_at) AS last,percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_seconds) AS p50_s,percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_seconds) AS p95_s FROM pipeline_runs WHERE started_at>NOW()-INTERVAL '1 day' GROUP BY pipeline_key,trigger_source,status",
    )
    query("vector_extension", "SELECT extname,extversion FROM pg_extension WHERE extname='vector'")
    query(
        "embedding_columns",
        "SELECT table_schema,table_name,column_name,data_type,udt_name FROM information_schema.columns WHERE table_name IN ('content_embeddings','embedding') ORDER BY table_schema,table_name,ordinal_position",
    )
    query(
        "embedding_indexes",
        "SELECT schemaname,tablename,indexname,indexdef FROM pg_indexes WHERE tablename IN ('content_embeddings','embedding')",
    )
    if "embedding_vec" in tables.get(("public", "content_embeddings"), {}):
        query(
            "native_vector_population",
            "SELECT count(*) AS rows,count(embedding_vec) AS populated FROM content_embeddings",
        )
    query(
        "retrieval_candidate_plan",
        "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT id,source_type FROM content_embeddings ORDER BY created_at DESC LIMIT 200",
    )
    conn.close()
except Exception as e:
    db["error_class"] = type(e).__name__
save("17-19-database-load.json", db)
print(
    json.dumps(
        {
            "as_of": NOW,
            "sources": {k: v.get("measured") for k, v in obs.items()},
            "processes": len(selected),
            "backups": len(backups),
            "db_class": db["evidence_class"],
            "failed_queries": [k for k, v in db["queries"].items() if "error_class" in v],
        }
    )
)
