#!/usr/bin/env python3
"""db_trim.py — archive-first trim of the production Postgres ("Trim 2026-10", design review §4).

Every destructive step (a) is a dry run by default, (b) writes what it is about to remove to
`persistent-state/archive/db_trim/<stamp>/` first (DDL for indexes, schema+data dump for tables,
jsonl.gz for rows), (c) records a tripwire entry so a later reader of the archived name fails
loudly, and (d) writes a receipt `data/runtime/db_trim_last.json` that would not exist had it not
run. Nothing here touches tax, trade, price, memory, journal or options tables.

    python3 scripts/db_trim.py inventory                    # read-only census of candidates
    python3 scripts/db_trim.py drop-duplicate-indexes [--apply]
    python3 scripts/db_trim.py archive-drop-tables   [--apply]
    python3 scripts/db_trim.py purge-dead-queues     [--apply]

AUTHORITY: READ_ONLY_ADVISORY without --apply. With --apply: db-write grant required (operator).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NO_CONSUMER_REASON = "operator-run maintenance tool; its receipt is read by the incident fan-in and the weekly report"
SCHEMA = "DbTrimReceipt@v1"
PROTECTED = re.compile(r"^(trade_transactions|trade_closed|portfolio_snapshots|dividend_history|tax_|memory_|journal_|options_|ticker_prices|price_cache|market_)")
DROPPABLE_NAME = re.compile(r"^(bak_|_bak_|_backup_|backup_|.*_bak_r\d+_\d{8}$|.*_backup_\d{8}.*|.*_legacy$|.*_dirfix_backup_\d{8}$|trade_closed_archived_probe$)")
QUEUE_RULES = {
    # table: (where-clause template, required columns); ORDER MATTERS for FK children
    "deep_overnight_llm_results": ("TRUE", []),      # child of the queue (FK queue_id); retired lane
    "deep_overnight_llm_queue": ("TRUE", []),
    "inference_ensemble_jobs": ("status = 'expired'", ["status"]),
    "watch_decision_refresh_jobs": ("created_at < now() - interval '30 days' AND stage NOT IN ('RUNNING','QUEUED')", ["created_at", "stage"]),
    "proposal_llm_review_queue": ("(status = 'EXPIRED') OR (status = 'PROCESSING' AND created_at < now() - interval '30 days')", ["status", "created_at"]),
    "alert_digest_queue": ("expires_at < now()", ["expires_at"]),
    "hermes_embedding_queue": ("status = 'completed' AND created_at < now() - interval '30 days'", ["status", "created_at"]),
}


def state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")


def dsn_env() -> dict:
    env = dict(os.environ)
    env.setdefault("PGHOST", env.get("DB_HOST", "127.0.0.1"))
    env.setdefault("PGUSER", env.get("DB_USER", "trade_ai"))
    env.setdefault("PGDATABASE", env.get("DB_NAME", "trade_ai"))
    if env.get("DB_PASSWORD"):
        env["PGPASSWORD"] = env["DB_PASSWORD"]
    env["PGOPTIONS"] = "-c statement_timeout=600s -c lock_timeout=120s"
    return env


def psql(sql: str, *, tuples=True, env=None) -> str:
    args = ["psql", "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    r = subprocess.run(args + ["-c", sql], capture_output=True, text=True, env=env or dsn_env())
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:400])
    return r.stdout.strip()


def rows(sql: str) -> list[list[str]]:
    out = psql(sql)
    return [ln.split("|") for ln in out.splitlines() if ln]


def columns(table: str) -> set[str]:
    return {r[0] for r in rows(f"SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='{table}'")}


def code_refs(name: str) -> int:
    """Count references to a table/schema name in the served code (scripts + apps), excluding this tool."""
    r = subprocess.run(["grep", "-rlI", "--exclude=db_trim.py", "--exclude-dir=node_modules", "--exclude-dir=.venv", "-w", name,
                        str(ROOT / "scripts"), str(ROOT / "apps")], capture_output=True, text=True)
    return len([ln for ln in r.stdout.splitlines() if ln])


# ---------------------------------------------------------------- inventory
def dup_index_pairs() -> list[dict]:
    sql = """
    SELECT a.indexrelid::regclass::text, b.indexrelid::regclass::text, a.indrelid::regclass::text,
           pg_relation_size(a.indexrelid), pg_relation_size(b.indexrelid),
           a.indisunique, b.indisunique, a.indisprimary, b.indisprimary
    FROM pg_index a JOIN pg_index b ON a.indrelid=b.indrelid AND a.indexrelid<b.indexrelid
         AND a.indkey::text=b.indkey::text AND coalesce(a.indexprs::text,'')=coalesce(b.indexprs::text,'')
         AND coalesce(a.indpred::text,'')=coalesce(b.indpred::text,'')
    JOIN pg_class c ON c.oid=a.indrelid JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' ORDER BY 4 DESC"""
    out = []
    for r in rows(sql):
        ia, ib, tbl, sa, sb, ua, ub, pa, pb = r
        # keep the primary/unique twin; drop the plain one. If both plain, drop the smaller name-wise second.
        if pa == "t" or (ua == "t" and ub != "t"):
            keep, drop, dsize = ia, ib, int(sb)
        elif pb == "t" or (ub == "t" and ua != "t"):
            keep, drop, dsize = ib, ia, int(sa)
        else:
            keep, drop, dsize = ia, ib, int(sb)
        out.append({"table": tbl, "keep": keep, "drop": drop, "drop_bytes": dsize})
    return out


def droppable_tables() -> list[dict]:
    out = []
    for name, live, bytes_ in rows("SELECT s.relname, s.n_live_tup, pg_total_relation_size(s.relid) FROM pg_stat_user_tables s WHERE s.schemaname='public'"):
        if PROTECTED.match(name) or not DROPPABLE_NAME.match(name):
            continue
        exact = int(rows(f'SELECT count(*) FROM "{name}"')[0][0])
        out.append({"table": name, "rows": exact, "bytes": int(bytes_), "code_refs": code_refs(name)})
    schemas = [r[0] for r in rows("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'crash\\_%'")]
    for s in schemas:
        out.append({"schema": s, "tables": int(rows(f"SELECT count(*) FROM pg_tables WHERE schemaname='{s}'")[0][0]), "code_refs": code_refs(s)})
    return out


def dead_queue_counts() -> list[dict]:
    out = []
    for table, (where, need) in QUEUE_RULES.items():
        cols = columns(table)
        if not cols:
            out.append({"table": table, "status": "ABSENT"}); continue
        missing = [c for c in need if c not in cols]
        if missing:
            out.append({"table": table, "status": f"SKIP missing columns {missing}"}); continue
        n = int(rows(f'SELECT count(*) FROM "{table}" WHERE {where}')[0][0])
        total = int(rows(f'SELECT count(*) FROM "{table}"')[0][0])
        out.append({"table": table, "where": where, "matching": n, "total": total, "status": "OK"})
    return out


def tax_table_ages() -> list[dict]:
    out = []
    for t in ("trade_transactions", "trade_closed", "portfolio_snapshots", "dividend_history"):
        cols = columns(t)
        if "created_at" not in cols:
            out.append({"table": t, "status": "no created_at"}); continue
        r = rows(f'SELECT count(*), count(*) FILTER (WHERE created_at < now() - interval \'180 days\'), min(created_at)::date FROM "{t}"')[0]
        out.append({"table": t, "rows": int(r[0]), "older_than_180d": int(r[1]), "oldest": r[2]})
    return out


# ---------------------------------------------------------------- actions
def archive_dir(stamp: str) -> Path:
    d = state_root() / "archive" / "db_trim" / stamp
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def tripwire(entries: list[dict]) -> None:
    p = state_root() / "archive" / "db_trim" / "TRIPWIRE.jsonl"
    with p.open("a", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")


def act_drop_dup_indexes(apply: bool, stamp: str) -> dict:
    pairs = dup_index_pairs()
    plan = [p for p in pairs if not PROTECTED.match(p["table"].strip('"'))]
    receipt = {"pairs": len(pairs), "planned": len(plan), "bytes": sum(p["drop_bytes"] for p in plan), "dropped": [], "errors": []}
    if not apply:
        receipt["dry_run"] = plan
        return receipt
    d = archive_dir(stamp)
    ddl_path = d / "dropped_indexes.sql"
    with ddl_path.open("a", encoding="utf-8") as fh:
        for p in plan:
            ddl = psql(f"SELECT pg_get_indexdef('{p['drop']}'::regclass)")
            fh.write(f"-- {p['table']} twin of {p['keep']}\n{ddl};\n")
            dropped = False
            for attempt in range(3):                      # lock_timeout under a busy writer: retry, then report
                try:
                    psql(f"DROP INDEX CONCURRENTLY IF EXISTS {p['drop']}")
                    dropped = True
                    break
                except RuntimeError as e:
                    last = str(e)
                    if "lock timeout" not in last:
                        break
            if dropped:
                receipt["dropped"].append(p["drop"])
            else:
                receipt["errors"].append({"index": p["drop"], "error": last})
    tripwire([{"kind": "index", "name": p["drop"], "ddl_file": str(ddl_path), "stamp": stamp} for p in plan])
    receipt["ddl_file"] = str(ddl_path)
    return receipt


def act_archive_drop_tables(apply: bool, stamp: str) -> dict:
    cands = droppable_tables()
    plan = [c for c in cands if c.get("code_refs", 1) == 0]
    skipped = [c for c in cands if c.get("code_refs", 1) != 0]
    receipt = {"candidates": len(cands), "planned": len(plan), "skipped_code_refs": skipped, "dropped": [], "errors": []}
    if not apply:
        receipt["dry_run"] = plan
        return receipt
    d = archive_dir(stamp)
    env = dsn_env()
    for c in plan:
        try:
            if "table" in c:
                dump = d / f"table_{c['table']}.sql.gz"
                r = subprocess.run(["pg_dump", "-t", f'public."{c["table"]}"', "--no-owner", "--no-privileges"], capture_output=True, env=env)
                if r.returncode != 0:
                    raise RuntimeError(r.stderr.decode()[:300])
                with gzip.open(dump, "wb") as fh:
                    fh.write(r.stdout)
                psql(f'DROP TABLE IF EXISTS "{c["table"]}"')
                receipt["dropped"].append(c["table"])
                tripwire([{"kind": "table", "name": c["table"], "dump": str(dump), "rows": c["rows"], "stamp": stamp}])
            else:
                dump = d / f"schema_{c['schema']}.sql.gz"
                r = subprocess.run(["pg_dump", "-n", c["schema"], "--no-owner", "--no-privileges"], capture_output=True, env=env)
                if r.returncode != 0:
                    raise RuntimeError(r.stderr.decode()[:300])
                with gzip.open(dump, "wb") as fh:
                    fh.write(r.stdout)
                psql(f'DROP SCHEMA IF EXISTS "{c["schema"]}" CASCADE')
                receipt["dropped"].append(c["schema"] + " (schema)")
                tripwire([{"kind": "schema", "name": c["schema"], "dump": str(dump), "stamp": stamp}])
        except RuntimeError as e:
            receipt["errors"].append({"target": c.get("table") or c.get("schema"), "error": str(e)})
    return receipt


def act_purge_dead_queues(apply: bool, stamp: str) -> dict:
    counts = dead_queue_counts()
    receipt = {"tables": counts, "deleted": {}, "errors": []}
    if not apply:
        return receipt
    d = archive_dir(stamp)
    env = dsn_env()
    for c in counts:
        if c.get("status") != "OK" or c["matching"] == 0:
            continue
        t, where = c["table"], c["where"]
        try:
            out = d / f"rows_{t}.jsonl.gz"
            r = subprocess.run(["psql", "-X", "-q", "-tA", "-v", "ON_ERROR_STOP=1", "-c",
                                f'COPY (SELECT row_to_json(q) FROM (SELECT * FROM "{t}" WHERE {where}) q) TO STDOUT'],
                               capture_output=True, env=env)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.decode()[:300])
            with gzip.open(out, "wb") as fh:
                fh.write(r.stdout)
            archived = r.stdout.count(b"\n")
            if archived != c["matching"]:
                raise RuntimeError(f"archived {archived} != matching {c['matching']}; not deleting")
            n = psql(f'WITH d AS (DELETE FROM "{t}" WHERE {where} RETURNING 1) SELECT count(*) FROM d')
            receipt["deleted"][t] = int(n)
            tripwire([{"kind": "rows", "name": t, "where": where, "archive": str(out), "rows": int(n), "stamp": stamp}])
        except RuntimeError as e:
            receipt["errors"].append({"table": t, "error": str(e)})
    return receipt


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["inventory", "drop-duplicate-indexes", "archive-drop-tables", "purge-dead-queues"])
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    size_before = psql("SELECT pg_database_size(current_database())")
    if a.action == "inventory":
        out = {"schema": SCHEMA, "action": "inventory", "as_of": stamp, "db_bytes": int(size_before),
               "duplicate_index_pairs": dup_index_pairs(), "droppable_tables": droppable_tables(),
               "dead_queues": dead_queue_counts(), "tax_tables": tax_table_ages()}
        print(json.dumps(out, indent=1, default=str))
        return 0
    fn = {"drop-duplicate-indexes": act_drop_dup_indexes, "archive-drop-tables": act_archive_drop_tables,
          "purge-dead-queues": act_purge_dead_queues}[a.action]
    result = fn(a.apply, stamp)
    size_after = psql("SELECT pg_database_size(current_database())")
    receipt = {"schema": SCHEMA, "action": a.action, "mode": "apply" if a.apply else "dry-run", "as_of": stamp,
               "db_bytes_before": int(size_before), "db_bytes_after": int(size_after), "result": result,
               "ok": not result.get("errors")}
    if a.apply:
        p = state_root() / "data" / "runtime" / "db_trim_last.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        hist = state_root() / "data" / "runtime" / "db_trim_history.jsonl"
        p.write_text(json.dumps(receipt, indent=1, default=str) + "\n", encoding="utf-8")
        with hist.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(receipt, default=str) + "\n")
    print(json.dumps(receipt, indent=1, default=str)[:6000])
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
