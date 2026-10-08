#!/usr/bin/env python3
"""migrate_content_embeddings_pgvector.py — move content_embeddings from jsonb to a pgvector column.

Measured 2026-10-08 (read-only): 1,308,244 rows, 12.0 GB total (heap 230 MB, TOAST 11 GB, indexes
156 MB), every row nomic-embed-text 768-d stored as a jsonb array (~7,150 bytes each), ~16,900 new
rows/day, pgvector 0.8.6 installed on PostgreSQL 17.11 and unused by this table. Readers pull ≤200
candidates by title/source and score cosine in Python (scripts/rag_retrieval.py via
scripts/lib/embedding_reader.py); a vector(768) column (3,080 bytes/row) + HNSW index lets Postgres
rank and later lets the 11 GB jsonb go (operator decision, never this script).

Modes (default --plan; NOTHING is written unless --apply AND TRADEAI_PGVECTOR_MIGRATION_AUTHORIZED=1):
  --plan           print the exact DDL/DML and the size/time estimates from the live measurement
  --apply --batch N  add `embedding_vec vector(<dim>)`, backfill in keyset batches of N rows, then
                   CREATE INDEX CONCURRENTLY hnsw(vector_cosine_ops); resumable (WHERE embedding_vec IS NULL)
  --verify         sample rows: jsonb vs vector equality (max abs diff), index validity, NULL count
  --cutover-plan   how readers switch (TRADEAI_EMBEDDINGS_BACKEND), dual-read period, what the drop needs

Guards on every write path (typed refusals, exit 2): authorization env + --apply, disk free ≥
TRADEAI_PGVECTOR_MIN_FREE_PCT (default 25), uniform dimension across rows, extension present.

AUTHORITY: READ_ONLY_ADVISORY in --plan/--verify/--cutover-plan. No deletes, ever (AGENTS.md rail 6).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

TABLE = "content_embeddings"
VEC_COLUMN = "embedding_vec"
INDEX_NAME = "content_embeddings_embedding_vec_hnsw"
AUTH_ENV = "TRADEAI_PGVECTOR_MIGRATION_AUTHORIZED"
MIN_FREE_ENV = "TRADEAI_PGVECTOR_MIN_FREE_PCT"
DEFAULT_MIN_FREE_PCT = 25.0
VECTOR_BYTES_PER_DIM = 4
VECTOR_HEADER_BYTES = 8
HNSW_INDEX_FACTOR = 1.35       # observed pgvector HNSW (m=16) size ≈ 1.2–1.5× the raw vectors
BACKFILL_ROWS_PER_SEC = 2500   # conservative keyset UPDATE throughput on this host (TOAST reads dominate)
HNSW_BUILD_ROWS_PER_SEC = 900  # CONCURRENTLY, maintenance_work_mem default; ~25 min per 1.3 M rows


class Refused(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


@dataclass
class Measurement:
    rows: int
    total_bytes: int
    toast_bytes: int
    index_bytes: int
    dims: dict            # {dim: rows}
    rows_per_day: float
    ext_version: Optional[str]
    column_present: bool
    index_present: bool
    disk_free_pct: float
    disk_free_bytes: int

    @property
    def dim(self) -> Optional[int]:
        return int(next(iter(self.dims))) if len(self.dims) == 1 else None


# ── measurement (read-only) ───────────────────────────────────────────────────

def disk_free(path: str = "/") -> tuple[float, int]:
    u = shutil.disk_usage(path)
    return (u.free / u.total * 100.0, u.free)


def measure(q: Callable[[str], list], *, disk_path: str = "/") -> Measurement:
    """`q(sql)` runs a read-only query and returns rows. Everything here is SELECT."""
    total, toast, idx = q(f"""SELECT pg_total_relation_size('{TABLE}'),
        coalesce((SELECT pg_relation_size(reltoastrelid) FROM pg_class WHERE relname='{TABLE}'),0),
        pg_indexes_size('{TABLE}')""")[0]
    rows = int(q(f"SELECT count(*) FROM {TABLE}")[0][0])
    dims = {str(d): int(n) for d, n in q(f"SELECT embedding_dim, count(*) FROM {TABLE} GROUP BY 1") if d is not None}
    rpd = float(q(f"SELECT count(*)/14.0 FROM {TABLE} WHERE created_at > now() - interval '14 days'")[0][0] or 0)
    ext = q("SELECT extversion FROM pg_extension WHERE extname='vector'")
    col = q(f"SELECT 1 FROM information_schema.columns WHERE table_name='{TABLE}' AND column_name='{VEC_COLUMN}'")
    ix = q(f"SELECT 1 FROM pg_indexes WHERE tablename='{TABLE}' AND indexname='{INDEX_NAME}'")
    pct, free = disk_free(disk_path)
    return Measurement(rows=rows, total_bytes=int(total), toast_bytes=int(toast), index_bytes=int(idx), dims=dims,
                       rows_per_day=rpd, ext_version=(ext[0][0] if ext else None), column_present=bool(col),
                       index_present=bool(ix), disk_free_pct=round(pct, 1), disk_free_bytes=int(free))


# ── plan ──────────────────────────────────────────────────────────────────────

def estimates(m: Measurement) -> dict:
    dim = m.dim or 0
    vec_bytes = m.rows * (dim * VECTOR_BYTES_PER_DIM + VECTOR_HEADER_BYTES)
    hnsw_bytes = int(vec_bytes * HNSW_INDEX_FACTOR)
    return {
        "dim": dim,
        "vector_column_bytes": vec_bytes,
        "hnsw_index_bytes": hnsw_bytes,
        "peak_extra_bytes_during_migration": vec_bytes + hnsw_bytes,
        "net_after_jsonb_drop_bytes": vec_bytes + hnsw_bytes - m.toast_bytes,
        "backfill_minutes": round(m.rows / BACKFILL_ROWS_PER_SEC / 60, 1),
        "hnsw_build_minutes": round(m.rows / HNSW_BUILD_ROWS_PER_SEC / 60, 1),
        "daily_new_rows": round(m.rows_per_day),
    }


def ddl(dim: int, batch: int) -> dict:
    return {
        "add_column": f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS {VEC_COLUMN} vector({dim});",
        "backfill_batch": (
            f"WITH b AS (SELECT id FROM {TABLE} WHERE {VEC_COLUMN} IS NULL AND id > %(after_id)s "
            f"AND jsonb_typeof(embedding) = 'array' AND jsonb_array_length(embedding) = {dim} "
            f"ORDER BY id LIMIT {int(batch)}) "
            f"UPDATE {TABLE} t SET {VEC_COLUMN} = (SELECT array_agg(x::float4) FROM jsonb_array_elements_text(t.embedding) AS x)::vector({dim}) "
            f"FROM b WHERE t.id = b.id RETURNING t.id;"
        ),
        "create_index": f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} ON {TABLE} USING hnsw ({VEC_COLUMN} vector_cosine_ops);",
        "verify_sample": (
            f"SELECT id, embedding, {VEC_COLUMN} FROM {TABLE} TABLESAMPLE SYSTEM (0.1) "
            f"WHERE {VEC_COLUMN} IS NOT NULL LIMIT %(n)s;"
        ),
        "never_here": f"-- DROP COLUMN embedding / ALTER … SET NOT NULL: operator decision after the dual-read period, not this script",
    }


def plan(m: Measurement, batch: int) -> dict:
    est = estimates(m)
    guards = guard_report(m, authorized=False)
    return {"schema": "PgvectorMigrationPlan@v1", "authority": "READ_ONLY_ADVISORY",
            "as_of": datetime.now(timezone.utc).isoformat(), "table": TABLE, "measurement": asdict(m),
            "estimates": est, "ddl": ddl(est["dim"] or 768, batch), "guards": guards, "writes": False}


# ── guards ────────────────────────────────────────────────────────────────────

def guard_report(m: Measurement, *, authorized: bool, env: Optional[dict] = None) -> dict:
    env = os.environ if env is None else env
    min_free = float(env.get(MIN_FREE_ENV, DEFAULT_MIN_FREE_PCT))
    checks = {
        "authorized": authorized,
        "extension_present": m.ext_version is not None,
        "dimension_uniform": m.dim is not None,
        "disk_free_ok": m.disk_free_pct >= min_free,
        "min_free_pct": min_free,
        "disk_free_pct": m.disk_free_pct,
    }
    return checks


def refuse_unless_safe(m: Measurement, *, apply: bool, env: Optional[dict] = None) -> None:
    env = os.environ if env is None else env
    authorized = apply and env.get(AUTH_ENV) == "1"
    g = guard_report(m, authorized=authorized, env=env)
    if not g["authorized"]:
        raise Refused("not_authorized", f"need --apply and {AUTH_ENV}=1")
    if not g["extension_present"]:
        raise Refused("extension_missing", "pg_extension has no 'vector'")
    if not g["dimension_uniform"]:
        raise Refused("dimension_not_uniform", f"dims={m.dims}")
    if not g["disk_free_ok"]:
        raise Refused("disk_headroom", f"free {m.disk_free_pct}% < {g['min_free_pct']}% ({MIN_FREE_ENV})")


# ── apply (only after every guard) ────────────────────────────────────────────

def apply(conn: Any, m: Measurement, *, batch: int, env: Optional[dict] = None, log=print, sleep=time.sleep) -> dict:
    refuse_unless_safe(m, apply=True, env=env)
    d = ddl(m.dim, batch)
    cur = conn.cursor()
    conn.autocommit = False
    if not m.column_present:
        cur.execute(d["add_column"]); conn.commit(); log(f"[apply] added {VEC_COLUMN} vector({m.dim})")
    after_id, done, t0 = 0, 0, time.time()
    while True:
        cur.execute(d["backfill_batch"], {"after_id": after_id})
        ids = [r[0] for r in cur.fetchall()]
        conn.commit()
        if not ids:
            break
        after_id, done = max(ids), done + len(ids)
        if done % (batch * 20) == 0:
            log(f"[apply] backfilled {done:,} rows, last id {after_id}, {done / max(1, time.time() - t0):.0f} rows/s")
        sleep(0)
    log(f"[apply] backfill complete: {done:,} rows in {time.time() - t0:.0f}s")
    if not m.index_present:
        conn.autocommit = True        # CREATE INDEX CONCURRENTLY cannot run inside a transaction
        cur.execute(d["create_index"]); log(f"[apply] index {INDEX_NAME} created")
        conn.autocommit = False
    return {"backfilled": done, "last_id": after_id, "index": INDEX_NAME}


# ── verify (read-only) ────────────────────────────────────────────────────────

def verify(q: Callable[[str, Optional[dict]], list], *, sample: int = 200) -> dict:
    rows = q(f"SELECT id, embedding, {VEC_COLUMN}::text FROM {TABLE} TABLESAMPLE SYSTEM (0.1) WHERE {VEC_COLUMN} IS NOT NULL LIMIT %(n)s", {"n": sample})
    worst, checked = 0.0, 0
    for _id, js, vtxt in rows:
        a = [float(x) for x in (js if isinstance(js, list) else json.loads(js))]
        b = [float(x) for x in str(vtxt).strip("[]").split(",") if x]
        if len(a) != len(b):
            return {"ok": False, "reason": f"length_mismatch id={_id} {len(a)} vs {len(b)}"}
        worst = max(worst, max(abs(x - y) for x, y in zip(a, b)) if a else 0.0); checked += 1
    nulls = int(q(f"SELECT count(*) FROM {TABLE} WHERE {VEC_COLUMN} IS NULL", None)[0][0])
    ix = q(f"SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid WHERE c.relname=%(n)s", {"n": INDEX_NAME})
    return {"ok": checked > 0 and worst < 1e-6 and bool(ix) and bool(ix[0][0]) and nulls == 0,
            "sampled": checked, "max_abs_diff": worst, "null_vectors": nulls,
            "index_valid": bool(ix) and bool(ix[0][0]), "float4_note": "vector stores float4; jsonb carries float8 — expect ≤1e-7 diffs"}


CUTOVER_PLAN = """Cutover plan (readers switch, nothing dropped):
1. After --apply and a green --verify: set TRADEAI_EMBEDDINGS_BACKEND=pgvector in the rendered env for
   the retrieval consumers (scripts/rag_retrieval.py via scripts/lib/embedding_reader.py) and restart
   the units that import it (api_v2 / portfolio-server.service, the hermes/CIO wake units) — one env
   flip, one restart, under a config-write grant.
2. Dual-read period (≥ 7 days): rag_indexer.py keeps writing jsonb; a nightly step backfills new rows
   (`--apply --batch` is resumable: WHERE embedding_vec IS NULL). Compare rag_score tops between
   backends on the same queries (scripts/compare_phase2b_parallel_retrieval.py pattern).
3. Only then, by operator decision in a separate PR: make rag_indexer write the vector directly and
   stop writing jsonb; later DROP COLUMN embedding (frees ~11 GB TOAST). This script never drops.
Rollback at any step: unset the env flag (readers fall back to jsonb); DROP INDEX / DROP COLUMN
embedding_vec removes everything the migration added, jsonb was never touched."""


# ── CLI ───────────────────────────────────────────────────────────────────────

def _live_conn():
    from db_adapter import _get_conn  # type: ignore
    return _get_conn()


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--plan", action="store_true"); p.add_argument("--apply", action="store_true")
    p.add_argument("--verify", action="store_true"); p.add_argument("--cutover-plan", action="store_true")
    p.add_argument("--batch", type=int, default=2000); p.add_argument("--sample", type=int, default=200)
    p.add_argument("--disk-path", default="/")
    a = p.parse_args(argv)
    if a.cutover_plan:
        print(CUTOVER_PLAN); return 0
    conn = _live_conn(); cur = conn.cursor()
    cur.execute("SET statement_timeout = '10s'")

    def q(sql: str, params: Optional[dict] = None) -> list:
        cur.execute(sql, params or {}); return cur.fetchall()
    try:
        if a.verify:
            out = verify(q, sample=a.sample); conn.rollback(); print(json.dumps(out, indent=1)); return 0 if out["ok"] else 1
        m = measure(lambda s: q(s), disk_path=a.disk_path); conn.rollback()
        if a.apply:
            try:
                refuse_unless_safe(m, apply=True)
            except Refused as r:
                print(json.dumps({"refused": r.code, "detail": r.detail, "guards": guard_report(m, authorized=os.environ.get(AUTH_ENV) == "1")}, indent=1)); return 2
            cur.execute("SET statement_timeout = '0'")
            print(json.dumps(apply(conn, m, batch=a.batch), indent=1)); return 0
        print(json.dumps(plan(m, a.batch), indent=1)); return 0
    finally:
        try: conn.rollback()
        except Exception: pass


if __name__ == "__main__":
    raise SystemExit(main())
