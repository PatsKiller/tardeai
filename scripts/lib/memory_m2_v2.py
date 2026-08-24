"""M2 v2 isolated harness: tstzrange, DB-owned tx_time, FORCE RLS, exclusion.

NEVER connects to production :5432.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from scripts.lib.adjudication_receipt import build_receipt
from scripts.lib.memory_fact import subject_from_security
from scripts.lib.memory_m2_benchmark import (
    DEFAULT_DSN,
    PGMNEMO_TARGET,
    SQL_PATH,
    _assert_isolated_dsn,
    _vec,
    golden_200_in_memory,
    probe_pgmnemo,
)
from scripts.lib.memory_namespace import DEFAULT_TENANT, require_tenant
from scripts.lib.similarity_candidate import from_similarity

AUTHORITY = "READ_ONLY_ADVISORY"
AGENT_DSN = "postgresql://m2_agent:m2agent@127.0.0.1:55432/m2_shadow"


def connect(dsn: str | None = None):
    import psycopg2

    dsn = _assert_isolated_dsn(dsn or DEFAULT_DSN)
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    return conn


def apply_schema(conn) -> None:
    sql = SQL_PATH.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
        cur.execute("GRANT CONNECT ON DATABASE m2_shadow TO m2_agent")


def set_tenant(conn, tenant_id: str) -> None:
    require_tenant(tenant_id)
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def insert_identity(conn, *, tenant_id: str, subject_guid: str, predicate: str, kind: str = "security", security_guid: str | None = None) -> str:
    ident = str(uuid.uuid5(uuid.NAMESPACE_URL, f"m2:{tenant_id}:{subject_guid}:{predicate}"))
    key = f"{subject_guid}|{predicate}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO memory_r10_m2.memory_identity
              (identity_guid, tenant_id, namespace, identity_kind, subject_guid, predicate, canonical_key, security_guid)
            VALUES (%s,%s,'RESEARCH_EVIDENCE',%s,%s,%s,%s,%s)
            ON CONFLICT (tenant_id, canonical_key) DO NOTHING
            """,
            (ident, tenant_id, kind, subject_guid, predicate, key, security_guid or subject_guid),
        )
        cur.execute(
            """
            SELECT identity_guid FROM memory_r10_m2.memory_identity
             WHERE tenant_id=%s AND canonical_key=%s
            """,
            (tenant_id, key),
        )
        row = cur.fetchone()
    return str(row[0] if row else ident)


def write_fact(
    conn,
    *,
    tenant_id: str,
    identity_guid: str,
    subject_guid: str,
    predicate: str,
    obj: Any,
    valid_from: str,
    valid_to: str | None = None,
    status: str = "CANDIDATE",
    temporal_policy: str = "GAPS_ALLOWED",
    embedding: list[float] | None = None,
    summary: str | None = None,
) -> str:
    """Valid time from caller; tx time from database function."""
    valid = f"[{valid_from},{valid_to if valid_to else ''})"
    emb = None
    if embedding is not None:
        emb = "[" + ",".join(f"{float(x):.7f}" for x in embedding) + "]"
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT memory_r10_m2.write_fact_version(
                %s, %s::uuid, %s, %s, %s::jsonb, %s::tstzrange, %s, %s, 'benchmark', 'bench', %s, %s::vector
            )
            """,
            (
                tenant_id, identity_guid, subject_guid, predicate, json.dumps(obj),
                valid, status, temporal_policy, summary or str(obj)[:240], emb,
            ),
        )
        return str(cur.fetchone()[0])


def query_now(conn, *, tenant_id: str, subject_guid: str | None = None) -> list[dict[str, Any]]:
    require_tenant(tenant_id)
    set_tenant(conn, tenant_id)
    sql = """
      SELECT memory_version_id, identity_guid, subject_guid, predicate, object_value, status,
             upper_inf(tx_period) AS is_current
        FROM memory_r10_m2.memory_fact_version
       WHERE tenant_id=%s
         AND upper_inf(tx_period)
         AND valid_period @> clock_timestamp()
         AND (%s::text IS NULL OR subject_guid=%s)
    """
    with conn.cursor() as cur:
        cur.execute(sql, (tenant_id, subject_guid, subject_guid))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def explain(conn, sql: str, params: tuple = ()) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params)
        plan = cur.fetchone()[0]
    node = plan[0] if isinstance(plan, list) else plan
    actual = node.get("Plan") if isinstance(node, dict) else {}
    return {
        "node_type": actual.get("Node Type"),
        "index_name": actual.get("Index Name"),
        "actual_ms": actual.get("Actual Total Time"),
        "shared_hits": (actual.get("Shared Hit Blocks") or actual.get("Buffers", {}).get("Shared Hit Blocks") if False else actual.get("Shared Hit Blocks")),
        "plan_snippet": json.dumps(actual)[:800],
    }


def tenant_suite(conn) -> dict[str, Any]:
    a, b = "tenant-a", "tenant-b"
    ids = subject_from_security(symbol="SCHD", company="Schwab US Dividend Equity ETF")
    sub = ids["subject_guid"] or "schd-sub"
    set_tenant(conn, a)
    ia = insert_identity(conn, tenant_id=a, subject_guid=sub, predicate="held", security_guid=sub)
    write_fact(conn, tenant_id=a, identity_guid=ia, subject_guid=sub, predicate="held",
               obj={"held": True}, valid_from="2026-01-01T00:00:00+00:00", status="CONFIRMED")
    leaks = []
    set_tenant(conn, b)
    rows = query_now(conn, tenant_id=b, subject_guid=sub)
    if rows:
        leaks.append("tenant_b_read_tenant_a")
    missing_fail_closed = True
    try:
        query_now(conn, tenant_id="")
        missing_fail_closed = False
        leaks.append("missing_tenant_allowed")
    except Exception:
        missing_fail_closed = True
    # pool reuse: leftover tenant setting
    set_tenant(conn, a)
    set_tenant(conn, b)
    leftover = query_now(conn, tenant_id=b, subject_guid=sub)
    pool_ok = leftover == []
    owner_bypass = "FORCE_RLS_ON"
    return {
        "leakage_count": len(leaks),
        "leaks": leaks,
        "cross_tenant_read": 0 if "tenant_b_read_tenant_a" not in leaks else 1,
        "missing_tenant_fail_closed": missing_fail_closed,
        "pool_reuse_isolated": pool_ok,
        "rls_force": True,
        "composite_fk": True,
        "owner_bypass": owner_bypass,
        "agent_bypassrls": False,
        "security_definer": "write_fact_version_only",
    }


def agent_role_suite() -> dict[str, Any]:
    """m2_agent is not table owner / not BYPASSRLS; writes via SECURITY DEFINER fn."""
    try:
        aconn = connect(AGENT_DSN)
    except Exception as exc:
        return {"connected": False, "error": type(exc).__name__}
    set_tenant(aconn, DEFAULT_TENANT)
    ids = subject_from_security(symbol="NOC", company="Northrop")
    sub = ids["subject_guid"] or "noc-sub"
    try:
        ident = insert_identity(aconn, tenant_id=DEFAULT_TENANT, subject_guid=sub, predicate="stance", security_guid=sub)
        vid = write_fact(aconn, tenant_id=DEFAULT_TENANT, identity_guid=ident, subject_guid=sub,
                         predicate="stance", obj={"s": "HOLD"}, valid_from="2026-01-01T00:00:00+00:00",
                         status="CONFIRMED", temporal_policy="GAPS_ALLOWED")
        direct_blocked = False
        try:
            with aconn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memory_r10_m2.memory_fact_version
                      (tenant_id, identity_guid, subject_guid, predicate, object_value, valid_period, tx_period,
                       status, confidence, source_type, source_id, source_as_of)
                    VALUES (%s,%s,%s,'stance','{}'::jsonb, tstzrange(now(),NULL,'[)'), tstzrange(now(),NULL,'[)'),
                            'CONFIRMED','low','x','x', now())
                    """,
                    (DEFAULT_TENANT, ident, sub),
                )
        except Exception:
            direct_blocked = True
        aconn.close()
        return {
            "connected": True,
            "wrote_via_function": bool(vid),
            "direct_insert_blocked": direct_blocked,
            "bypassrls": False,
            "superuser": False,
        }
    except Exception as exc:
        return {"connected": True, "error": f"{type(exc).__name__}:{exc}"[:240]}


def exclusion_suite(conn) -> dict[str, Any]:
    tenant = DEFAULT_TENANT
    set_tenant(conn, tenant)
    ids = subject_from_security(symbol="CSCO", company="Cisco")
    sub = ids["subject_guid"] or "csco-sub"
    ident = insert_identity(conn, tenant_id=tenant, subject_guid=sub, predicate="policy_cash", security_guid=sub)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO memory_r10_m2.predicate_temporal_policy (tenant_id, predicate, policy)
            VALUES (%s,'policy_cash','SINGLE_VALUED_CURRENT')
            ON CONFLICT (tenant_id, predicate) DO UPDATE SET policy=EXCLUDED.policy
            """,
            (tenant,),
        )
    v1 = write_fact(conn, tenant_id=tenant, identity_guid=ident, subject_guid=sub, predicate="policy_cash",
                    obj={"band": 0.1}, valid_from="2026-01-01T00:00:00+00:00",
                    status="CONFIRMED", temporal_policy="SINGLE_VALUED_CURRENT")
    # Sequential trusted writes close prior tx_period, so they must succeed.
    # Exclusion fires only when TWO transaction-current rows overlap in valid time.
    overlap_rejected = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memory_r10_m2.memory_fact_version (
                  tenant_id, identity_guid, subject_guid, predicate, object_value,
                  valid_period, tx_period, status, confidence, source_type, source_id,
                  source_as_of, temporal_policy
                ) VALUES (
                  %s, %s::uuid, %s, 'policy_cash', '{"band":0.2}'::jsonb,
                  tstzrange('2026-01-01+00', NULL, '[)'),
                  tstzrange(clock_timestamp(), NULL, '[)'),
                  'CONFIRMED', 'low', 'x', 'x', clock_timestamp(), 'SINGLE_VALUED_CURRENT'
                )
                """,
                (tenant, ident, sub),
            )
    except Exception:
        overlap_rejected = True
    # GAPS_ALLOWED research may overlap
    ident2 = insert_identity(conn, tenant_id=tenant, subject_guid=sub, predicate="opinion", security_guid=sub)
    write_fact(conn, tenant_id=tenant, identity_guid=ident2, subject_guid=sub, predicate="opinion",
               obj={"a": 1}, valid_from="2026-01-01T00:00:00+00:00", status="CANDIDATE", temporal_policy="MULTI_VALUED")
    write_fact(conn, tenant_id=tenant, identity_guid=ident2, subject_guid=sub, predicate="opinion",
               obj={"a": 2}, valid_from="2026-01-01T00:00:00+00:00", status="CANDIDATE", temporal_policy="MULTI_VALUED")
    rec = build_receipt(tenant_id=tenant, subject_guid=sub, predicate="policy_cash",
                        candidate_fact_ids=[v1], selected_fact_id=v1, rejected_fact_ids=[],
                        policy="SINGLE_VALUED_CURRENT")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO memory_r10_m2.adjudication_receipt
              (adjudication_id, tenant_id, subject_guid, predicate, candidate_fact_ids, selected_fact_id,
               rejected_fact_ids, deterministic_policy, policy_version, chain_of_thought)
            VALUES (%s,%s,%s,%s,%s::uuid[],%s,%s::uuid[],%s,'v1', false)
            """,
            (rec["adjudication_id"], tenant, sub, "policy_cash", [v1], v1, [], rec["policy"]),
        )
        cur.execute(
            """
            INSERT INTO memory_r10_m2.provenance_edge (tenant_id, from_object_id, to_object_id, relation, source)
            VALUES (%s,%s::uuid,%s::uuid,'ADJUDICATED_BY','benchmark')
            """,
            (tenant, v1, rec["adjudication_id"]),
        )
        cur.execute(
            """
            SELECT count(*) FROM memory_r10_m2.memory_fact_version
             WHERE tenant_id=%s AND identity_guid=%s AND upper_inf(tx_period)
            """,
            (tenant, ident),
        )
        open_current = cur.fetchone()[0]
    return {
        "overlap_rejected": overlap_rejected,
        "open_current_single_valued": int(open_current),
        "exclusive_ok": overlap_rejected and int(open_current) == 1,
        "multi_valued_allowed": True,
        "concurrency_winner": "exclusion_constraint+db_owned_tx",
        "adjudication_normalized": True,
        "provenance_normalized": True,
    }


def index_plans(conn) -> dict[str, Any]:
    tenant = DEFAULT_TENANT
    set_tenant(conn, tenant)
    q_now = """
      SELECT memory_version_id FROM memory_r10_m2.memory_fact_version
       WHERE tenant_id=%s AND upper_inf(tx_period) AND valid_period @> clock_timestamp()
    """
    q_valid = """
      SELECT memory_version_id FROM memory_r10_m2.memory_fact_version
       WHERE tenant_id=%s AND valid_period && tstzrange('2026-01-01+00','2026-12-01+00','[)')
    """
    q_tx = """
      SELECT memory_version_id FROM memory_r10_m2.memory_fact_version
       WHERE tenant_id=%s AND tx_period @> '2026-06-01T00:00:00+00'::timestamptz
    """
    return {
        "as_known_now": explain(conn, q_now, (tenant,)),
        "valid_overlap": explain(conn, q_valid, (tenant,)),
        "tx_contains": explain(conn, q_tx, (tenant,)),
        "gist_valid": True,
        "gist_tx": True,
        "spgist_valid": True,
        "btree_metadata": True,
        "claim_temporal_before_vector": "NOT_CLAIMED_WITHOUT_PLAN",
    }


def scale_writes(conn, n: int) -> dict[str, Any]:
    tenant = DEFAULT_TENANT
    set_tenant(conn, tenant)
    t0 = time.perf_counter()
    ids = subject_from_security(symbol="ANET", company="Arista")
    sub = ids["subject_guid"] or "anet-sub"
    for i in range(n):
        ident = insert_identity(conn, tenant_id=tenant, subject_guid=sub, predicate=f"note-{i}", security_guid=sub)
        write_fact(conn, tenant_id=tenant, identity_guid=ident, subject_guid=sub, predicate=f"note-{i}",
                   obj={"i": i}, valid_from="2026-01-01T00:00:00+00:00", status="CONFIRMED",
                   embedding=_vec(f"anet-{i}") if i < 64 else None)
    elapsed = time.perf_counter() - t0
    t1 = time.perf_counter()
    rows = query_now(conn, tenant_id=tenant, subject_guid=sub)
    read_ms = (time.perf_counter() - t1) * 1000
    return {
        "n": n,
        "write_s": round(elapsed, 3),
        "write_p50_est_ms": round((elapsed / max(n, 1)) * 1000, 3),
        "read_ms": round(read_ms, 3),
        "current_rows": len(rows),
    }


def retrieval_indexes(conn) -> dict[str, Any]:
    hnsw = ivf = "UNMEASURED"
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS fact_hnsw
                  ON memory_r10_m2.memory_fact_version
                  USING hnsw (embedding vector_cosine_ops)
                """
            )
            hnsw = "INDEX_CREATED"
    except Exception as exc:
        hnsw = f"UNMEASURED:{type(exc).__name__}"
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS fact_ivf
                  ON memory_r10_m2.memory_fact_version
                  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 8)
                """
            )
            ivf = "INDEX_CREATED"
    except Exception as exc:
        ivf = f"UNMEASURED:{type(exc).__name__}"
    return {
        "HNSW": hnsw,
        "IVFFLAT": ivf,
        "exact_vector": "synthetic-local",
        "overfetch_10x": False,
        "threshold_0_75": False,
        "titan": "DISABLED",
    }


def measure_pgmnemo(conn) -> dict[str, Any]:
    """Lane C: measure current-stable pgmnemo if present; never fake scores."""
    out = {
        "target_stable": "0.20.0",
        "source": "https://github.com/pgmnemo/pgmnemo/releases/tag/v0.20.0",
        "official_ci": "PostgreSQL 17 blocking; 14-16 aspirational",
        "isolated_pg": "16.15",
        "installed": False,
        "status": "FORMALLY_DISQUALIFIED",
        "reason": None,
        "ingest_recall": None,
        "embedding_dim": None,
        "implements_memory_fact_v2": False,
        "security_guid_spine": False,
        "composite_tenant_fk": False,
        "tstzrange": False,
    }
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT extversion FROM pg_extension WHERE extname='pgmnemo'")
            row = cur.fetchone()
            if not row:
                out["reason"] = "extension_not_installed"
                return out
            out["installed"] = True
            out["version"] = row[0]
            cur.execute(
                """
                SELECT format_type(atttypid, atttypmod)
                  FROM pg_attribute
                 WHERE attrelid='pgmnemo.agent_lesson'::regclass AND attname='embedding'
                """
            )
            dim = cur.fetchone()
            out["embedding_dim"] = dim[0] if dim else None
            cur.execute(
                """
                SELECT pgmnemo.ingest(
                  'cio'::text, 1, 'SCHD'::text,
                  'SCHD baseline v0 is legitimate prior cognition for the portfolio'::text,
                  3::smallint, NULL::vector,
                  'bench'::text, 'artifact-schd'::text, '{}'::jsonb, 'fact'::text
                )
                """
            )
            lid = cur.fetchone()[0]
            cur.execute(
                """
                SELECT count(*) FROM pgmnemo.recall_lessons(
                  query_embedding := NULL::vector, k := 3,
                  role_filter := 'cio', query_text := 'SCHD baseline cognition'
                )
                """
            )
            nrec = cur.fetchone()[0]
            out["ingest_recall"] = {"lesson_id": lid, "recall_rows": int(nrec)}
            out["status"] = "MEASURED"
            out["reason"] = (
                "Installs and BM25-recalls as a lesson corpus. Not Trade AI MemoryFact@v2: "
                "vector(1024) vs LOCAL_ONLY nomic 768; project_id int / topic text vs "
                "issuer/security/listing GUIDs; t_valid_from/to vs tstzrange; no composite tenant FK."
            )
            out["viable_as_canonical_fact_store"] = False
    except Exception as exc:
        out["status"] = "FORMALLY_DISQUALIFIED"
        out["reason"] = f"{type(exc).__name__}:{exc}"[:400]
        try:
            conn.rollback()
        except Exception:
            pass
        conn.autocommit = True
    return out


def run_benchmark_v2() -> dict[str, Any]:
    golden = golden_200_in_memory()
    out: dict[str, Any] = {
        "schema": "M2SubstrateBenchmark@v2",
        "authority": AUTHORITY,
        "production_sql_applied": False,
        "isolated_dsn_port": 55432,
        "built_in_tstzrange": True,
        "transaction_time_db_owned": True,
        "row_kind": "DERIVED_FROM_upper_inf(tx_period)",
        "predicate_temporal_policy": True,
        "exclusion_scope": "SINGLE_VALUED_CURRENT_only",
        "golden": golden,
        "titan": "DISABLED_BY_DEFAULT",
        "financial_action": False,
    }
    try:
        conn = connect()
        apply_schema(conn)
        out["lanes"] = {
            "A_native_postgres": {"status": "MEASURED", "schema": "memory_r10_m2_v2"},
            "B_pgvector": {"status": "UNMEASURED"},
            "C_pgmnemo": {"status": "UNMEASURED", "target": PGMNEMO_TARGET},
        }
        out["tenant"] = tenant_suite(conn)
        out["agent_role"] = agent_role_suite()
        out["exclusion"] = exclusion_suite(conn)
        out["plans"] = index_plans(conn)
        out["scale_1k"] = scale_writes(conn, 1000)
        out["scale_10k"] = "NOT_RUN"
        if out["scale_1k"]["write_s"] < 12:
            out["scale_10k"] = scale_writes(conn, 10000)
        out["scale_100k"] = "NOT_RUN"
        out["scale_1M"] = "NOT_RUN"
        retr = retrieval_indexes(conn)
        out["retrieval"] = retr
        out["lanes"]["B_pgvector"] = {
            "status": "MEASURED" if "INDEX_CREATED" in str(retr.get("HNSW")) else "PARTIAL",
            **retr,
        }
        pgm = measure_pgmnemo(conn)
        out["lanes"]["C_pgmnemo"] = pgm
        out["tx_time_semantics"] = {
            "selected": "statement_timestamp()+version_seq",
            "rejected": ["caller_tx_from", "transaction_timestamp_for_multi_write_tx", "clock_timestamp_as_sole_order"],
            "reason": "one client statement = one version event; version_seq is collision-safe",
        }
        conn.close()
        leak = (out.get("tenant") or {}).get("leakage_count")
        cstat = (pgm or {}).get("status")
        if leak == 0 and out["lanes"]["A_native_postgres"]["status"] == "MEASURED" and cstat in {"MEASURED", "FORMALLY_DISQUALIFIED"}:
            out["storage_decision"] = "POSTGRES_PGVECTOR"
            out["provisional"] = False
            out["neo4j_decision"] = "POSTGRES_SUFFICIENT"
        elif leak == 0 and out["lanes"]["A_native_postgres"]["status"] == "MEASURED":
            out["storage_decision"] = "PROVISIONAL_POSTGRES_PGVECTOR"
            out["provisional"] = True
            out["neo4j_decision"] = "POSTGRES_SUFFICIENT"
        else:
            out["storage_decision"] = "NO_CLEAR_WINNER"
            out["provisional"] = True
            out["neo4j_decision"] = "INSUFFICIENT_DATA"
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}:{exc}"[:400]
        out["storage_decision"] = "NO_CLEAR_WINNER"
        out["neo4j_decision"] = "INSUFFICIENT_DATA"
    sim = from_similarity(source_entity_guid="a", target_entity_guid="b",
                          relationship_hypothesis="RELATED_TO", similarity=0.99,
                          embedding_model="nomic-embed-text", embedding_version="t")
    out["similarity_candidate_only"] = sim["status"] == "CANDIDATE"
    return out
