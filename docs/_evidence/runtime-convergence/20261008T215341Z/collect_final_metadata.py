#!/usr/bin/env python3
"""Read-only population and file-queue metadata supplement; never fetch payloads."""

import json, sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

P = Path(__file__).resolve().parent
ROOT = P.parents[3]
sys.path.insert(0, str(ROOT))
from scripts.lib.env_bootstrap import load_env

load_env()
import psycopg2, os

state = Path("/home/johnclaw/trade-ai-releases/persistent-state")
r = {"as_of": datetime.now(timezone.utc).isoformat(), "evidence_class": "OBSERVED_DB", "queries": {}, "file_queues": []}
conn = psycopg2.connect(
    host=os.getenv("DB_HOST", "localhost"),
    port=os.getenv("DB_PORT", "5432"),
    dbname=os.getenv("DB_NAME", "tradeai"),
    user=os.getenv("DB_USER", "johnclaw"),
    password=os.getenv("DB_PASS") or os.getenv("DB_PASSWORD"),
    connect_timeout=5,
)
conn.set_session(readonly=True)
for name, sql in {
    "native_vectors": "SELECT count(*) AS total_rows,count(*) FILTER(WHERE vec IS NOT NULL) AS vector_rows,pg_total_relation_size('intelligence.embedding') AS bytes FROM intelligence.embedding",
    "json_embedding_population": "SELECT count(*) AS total_rows,count(*) FILTER(WHERE embedding IS NOT NULL) AS json_embedding_rows,count(*) FILTER(WHERE embedding IS NULL) AS null_embedding_rows FROM content_embeddings",
}.items():
    try:
        with conn.cursor() as c:
            c.execute("SET LOCAL statement_timeout='10s'")
            c.execute(sql)
            names = [i.name for i in c.description]
            r["queries"][name] = {"sql": sql, "rows": [dict(zip(names, x)) for x in c.fetchall()]}
        conn.rollback()
    except Exception as e:
        conn.rollback()
        r["queries"][name] = {"sql": sql, "evidence_class": "BLOCKED", "error_class": type(e).__name__}
conn.close()
for rel in [
    "data/cio/hermes_research_requests.jsonl",
    "data/cio/hermes_challenge_queue.jsonl",
    "data/cio/agent_handoffs.jsonl",
    "data/cio/persistent_agent_wake.jsonl",
    "data/cio/approval_queue.jsonl",
    "logs/claude_escalation_queue.json",
    "data/watchlist_research_queue.json",
    "data/runtime/hermes_embedding_queue.json",
]:
    f = state / rel
    row = {"path": rel, "exists": f.exists(), "evidence_class": "NOT_MEASURED"}
    if f.is_file() and f.stat().st_size < 8 * 1024 * 1024:
        try:
            text = f.read_text()
            data = [json.loads(s) for s in text.splitlines() if s.strip()] if f.suffix == ".jsonl" else json.loads(text)
            if isinstance(data, dict):
                data = data.get("items", data.get("jobs", []))
            if not isinstance(data, list):
                raise ValueError()
            row.update(
                evidence_class="OBSERVED_HOST",
                record_count=len(data),
                status_counts=dict(
                    Counter(str(x.get("status") or x.get("state") or "UNKNOWN") for x in data if isinstance(x, dict))
                ),
                size_bytes=f.stat().st_size,
                mtime=datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(),
                note="Event row counts are not materialized pending queue lengths; payloads excluded.",
            )
        except Exception as e:
            row.update(error_class=type(e).__name__)
    r["file_queues"].append(row)
(P / "17-19-final-metadata.json").write_text(json.dumps(r, indent=2) + "\n")
print(json.dumps({"queries": r["queries"], "file_queue_sources": len(r["file_queues"])}))
