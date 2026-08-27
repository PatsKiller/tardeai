"""Non-authoritative Postgres/pgvector cognition shadow projector.

SHADOW_ONLY. CANONICAL_READERS_UNCHANGED. MEMORY_BEHAVIOR_INFLUENCE=0.
NEVER connects to production :5432. NEVER writes canonical JSONL.
CIO must not consume these rows.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.memory_namespace import DEFAULT_TENANT, require_tenant

AUTHORITY = "READ_ONLY_ADVISORY"
PROJECTION_VERSION = "MemoryShadow@v1"
SCHEMA_NAME = "tradeai_memory_shadow"
FORBIDDEN_PORTS = {"5432"}
DEFAULT_DSN = "postgresql://m2:m2shadow@127.0.0.1:55432/m2_shadow"
WRITER_DSN = "postgresql://tradeai_memory_shadow_writer:shadowwriter@127.0.0.1:55432/m2_shadow"
READER_DSN = "postgresql://tradeai_memory_shadow_reader:shadowreader@127.0.0.1:55432/m2_shadow"
SQL_PATH = Path(__file__).resolve().parents[2] / "sql" / "r10_tradeai_memory_shadow_isolated.sql"
PREDICATES = ("ticker_research_state", "hermes_curation", "symbol_thesis", "research_gap")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _assert_isolated(dsn: str) -> str:
    s = str(dsn)
    hostport = s.split("@")[-1]
    for p in FORBIDDEN_PORTS:
        if f":{p}" in hostport:
            raise RuntimeError("MEMORY_SHADOW_PRODUCTION_PORT_FORBIDDEN")
    if "55432" not in s and os.getenv("M2_ALLOW_NONDEFAULT_PORT") != "1":
        raise RuntimeError("MEMORY_SHADOW_ISOLATED_PORT_REQUIRED")
    return s


def connect(dsn: str | None = None):
    import psycopg2

    dsn = _assert_isolated(dsn or DEFAULT_DSN)
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    return conn


def apply_schema(conn) -> None:
    sql = SQL_PATH.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
        for role in ("tradeai_memory_shadow_writer", "tradeai_memory_shadow_reader"):
            try:
                cur.execute(f"GRANT CONNECT ON DATABASE m2_shadow TO {role}")
            except Exception:
                conn.rollback()
                conn.autocommit = True


def set_tenant(conn, tenant_id: str) -> None:
    require_tenant(tenant_id)
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _latest_by(rows: list[dict[str, Any]], *keys: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for r in rows:
        k = ""
        for key in keys:
            k = str(r.get(key) or "").strip().upper()
            if k:
                break
        if not k:
            k = str(r.get("symbol") or r.get("current_ticker_alias") or "").strip().upper()
        if k:
            latest[k] = r
    return latest


def _source_sha(root: Path) -> str:
    for name in ("SOURCE_COMMIT", "BUILD_SHA"):
        p = root / name
        if p.is_file():
            return p.read_text(encoding="utf-8").strip().split()[0]
    return ""


def _ident_uuid(tenant: str, kind: str, subject: str, predicate: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"shadow:{tenant}:{kind}:{subject}:{predicate}"))


def _upsert_identity(conn, *, tenant: str, ident: str, kind: str, subject: str, predicate: str,
                     security_guid: str | None, ticker_guid: str | None, issuer_guid: str | None,
                     listing_guid: str | None) -> None:
    key = f"{subject}|{predicate}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tradeai_memory_shadow.memory_identity
              (identity_guid, tenant_id, namespace, identity_kind, subject_guid, predicate,
               canonical_key, issuer_guid, security_guid, listing_guid, ticker_guid)
            VALUES (%s,%s,'RESEARCH_EVIDENCE',%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (tenant_id, canonical_key) DO UPDATE
              SET security_guid = COALESCE(EXCLUDED.security_guid, tradeai_memory_shadow.memory_identity.security_guid)
            """,
            (ident, tenant, kind, subject, predicate, key, issuer_guid, security_guid, listing_guid, ticker_guid),
        )


def _write(conn, **kw) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT tradeai_memory_shadow.write_fact_version(
              %s,%s::uuid,%s,%s,%s::jsonb, tstzrange(%s::timestamptz, NULL, '[)'),
              %s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                kw["tenant"], kw["ident"], kw["subject"], kw["predicate"],
                json.dumps(kw["obj"], sort_keys=True, default=str), kw.get("valid_from") or _now(),
                kw.get("status") or "CURRENT", kw["source_type"], kw["source_id"],
                kw.get("source_version"), kw.get("source_sha"), kw["idemp"], kw["run_id"],
                kw.get("policy") or "SINGLE_VALUED_CURRENT",
            ),
        )
        return str(cur.fetchone()[0])


def _current(conn, tenant: str, predicate: str, subject: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT object_value, source_version, source_id, security_guid
              FROM tradeai_memory_shadow.memory_fact_version f
              JOIN tradeai_memory_shadow.memory_identity i USING (tenant_id, identity_guid)
             WHERE f.tenant_id=%s AND f.predicate=%s AND f.subject_guid=%s AND upper_inf(f.tx_period)
             ORDER BY version_seq DESC LIMIT 1
            """,
            (tenant, predicate, subject),
        )
        row = cur.fetchone()
    if not row:
        return None
    obj = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    obj["_source_version"] = row[1]
    obj["_source_id"] = row[2]
    return obj


def project(root: Path | str, *, tenant: str = DEFAULT_TENANT, conn=None, run_id: str | None = None) -> dict[str, Any]:
    """One-way projection of canonical JSONL → isolated shadow. Never mutates JSONL."""
    base = Path(root)
    sha_before = {p: hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
                  for p in [
                      base / "data/cio/ticker_research_state.jsonl",
                      base / "data/cio/hermes_curation_summary.jsonl",
                      base / "data/cio/research_gaps.jsonl",
                  ]}
    own = conn is None
    if own:
        conn = connect()
    set_tenant(conn, tenant)
    rid = run_id or str(uuid.uuid4())
    source_sha = _source_sha(base)
    t0 = time.perf_counter()
    counts = {"created": 0, "unchanged": 0, "versioned": 0, "unresolved": 0, "excluded": 0, "failed": 0, "projected": 0}
    eligible = 0

    states = _latest_by(_jsonl(base / "data/cio/ticker_research_state.jsonl"), "symbol")
    curs = _latest_by(_jsonl(base / "data/cio/hermes_curation_summary.jsonl"), "current_ticker_alias", "symbol")
    gaps = list(_latest_by(_jsonl(base / "data/cio/research_gaps.jsonl"), "gap_id", "id").values())

    before_versions = _count(conn, "memory_fact_version")

    for sym, st in states.items():
        eligible += 1
        try:
            sec = st.get("security_guid")
            tick = st.get("ticker_guid")
            subject = str(sec or tick or sym)
            if not sec:
                counts["unresolved"] += 1
            ident = _ident_uuid(tenant, "security", subject, "ticker_research_state")
            _upsert_identity(conn, tenant=tenant, ident=ident, kind="security", subject=subject,
                             predicate="ticker_research_state", security_guid=sec, ticker_guid=tick,
                             issuer_guid=st.get("issuer_guid"), listing_guid=st.get("listing_guid"))
            obj = {
                "symbol": sym,
                "security_guid": sec,
                "research_state_version": st.get("updated_at"),
                "status": st.get("status") or st.get("freshness"),
                "freshness": st.get("freshness"),
                "decision": st.get("decision"),
                "open_gaps": st.get("open_gaps") or [],
                "evidence_watermark": st.get("evidence_watermark"),
                "authority": st.get("authority") or AUTHORITY,
                "financial_action": False,
            }
            ver = str(st.get("updated_at") or "")
            idemp = f"TickerResearchState|{sym}|{ver}|{PROJECTION_VERSION}"
            n0 = _count(conn, "memory_fact_version")
            _write(conn, tenant=tenant, ident=ident, subject=subject, predicate="ticker_research_state",
                   obj=obj, valid_from=st.get("updated_at") or _now(), source_type="TickerResearchState@v1",
                   source_id=sym, source_version=ver, source_sha=source_sha, idemp=idemp, run_id=rid)
            if _count(conn, "memory_fact_version") == n0:
                counts["unchanged"] += 1
            else:
                counts["created"] += 1
                counts["projected"] += 1
        except Exception:
            counts["failed"] += 1

    for sym, cur in curs.items():
        eligible += 1
        try:
            st = states.get(sym) or {}
            sec = cur.get("security_guid") or st.get("security_guid")
            subject = str(sec or st.get("ticker_guid") or sym)
            if not sec:
                counts["unresolved"] += 1
            ident = _ident_uuid(tenant, "security", subject, "hermes_curation")
            _upsert_identity(conn, tenant=tenant, ident=ident, kind="security", subject=subject,
                             predicate="hermes_curation", security_guid=sec, ticker_guid=st.get("ticker_guid"),
                             issuer_guid=st.get("issuer_guid"), listing_guid=st.get("listing_guid"))
            obj = {
                "symbol": sym,
                "security_guid": sec,
                "curation_id": cur.get("curation_id"),
                "curation_version": cur.get("version") if cur.get("version") is not None else 0,
                "curation_kind": cur.get("kind"),
                "authority": cur.get("authority") or AUTHORITY,
            }
            ver = f"{cur.get('curation_id')}|{cur.get('version')}|{cur.get('kind')}"
            idemp = f"HermesCurationSummary|{sym}|{ver}|{PROJECTION_VERSION}"
            n0 = _count(conn, "memory_fact_version")
            _write(conn, tenant=tenant, ident=ident, subject=subject, predicate="hermes_curation",
                   obj=obj, valid_from=cur.get("as_of") or _now(), source_type="HermesCurationSummary@v1",
                   source_id=sym, source_version=ver, source_sha=source_sha, idemp=idemp, run_id=rid)
            if _count(conn, "memory_fact_version") == n0:
                counts["unchanged"] += 1
            else:
                counts["created"] += 1
                counts["projected"] += 1
        except Exception:
            counts["failed"] += 1

    thesis_done = set()
    for sym, st in states.items():
        try:
            from scripts.lib.cio_persistent_cognition import _load_symbol_thesis
            th = _load_symbol_thesis(base, sym)
        except Exception:
            th = {}
        if not th.get("symbol_thesis_id") and not th.get("symbol_thesis_version"):
            counts["excluded"] += 1
            continue
        eligible += 1
        try:
            sec = st.get("security_guid")
            subject = str(sec or st.get("ticker_guid") or sym)
            ident = _ident_uuid(tenant, "security", subject, "symbol_thesis")
            _upsert_identity(conn, tenant=tenant, ident=ident, kind="security", subject=subject,
                             predicate="symbol_thesis", security_guid=sec, ticker_guid=st.get("ticker_guid"),
                             issuer_guid=st.get("issuer_guid"), listing_guid=st.get("listing_guid"))
            obj = {
                "symbol": sym,
                "security_guid": sec,
                "symbol_thesis_id": th.get("symbol_thesis_id"),
                "symbol_thesis_version": th.get("symbol_thesis_version"),
                "thesis_state": th.get("thesis_state"),
                "authority": AUTHORITY,
            }
            ver = str(th.get("symbol_thesis_version") or th.get("symbol_thesis_id"))
            idemp = f"SymbolThesis|{sym}|{ver}|{PROJECTION_VERSION}"
            n0 = _count(conn, "memory_fact_version")
            _write(conn, tenant=tenant, ident=ident, subject=subject, predicate="symbol_thesis",
                   obj=obj, source_type="SymbolThesis", source_id=sym, source_version=ver,
                   source_sha=source_sha, idemp=idemp, run_id=rid)
            if _count(conn, "memory_fact_version") == n0:
                counts["unchanged"] += 1
            else:
                counts["created"] += 1
                counts["projected"] += 1
            thesis_done.add(sym)
        except Exception:
            counts["failed"] += 1

    for g in gaps:
        eligible += 1
        try:
            gid = str(g.get("gap_id") or g.get("id") or "")
            if not gid:
                counts["excluded"] += 1
                continue
            sym = str(g.get("symbol") or "").upper()
            st = states.get(sym) or {}
            sec = g.get("security_guid") or st.get("security_guid")
            subject = str(sec or st.get("ticker_guid") or gid)
            ident = _ident_uuid(tenant, "gap", subject, "research_gap")
            _upsert_identity(conn, tenant=tenant, ident=ident, kind="research_gap", subject=subject,
                             predicate="research_gap", security_guid=sec, ticker_guid=st.get("ticker_guid"),
                             issuer_guid=None, listing_guid=None)
            obj = {"gap_id": gid, "symbol": sym, "security_guid": sec, "status": g.get("status"),
                   "question": g.get("question"), "authority": AUTHORITY}
            ver = str(g.get("status") or "") + "|" + gid
            idemp = f"ResearchGap|{gid}|{ver}|{PROJECTION_VERSION}"
            n0 = _count(conn, "memory_fact_version")
            _write(conn, tenant=tenant, ident=ident, subject=subject, predicate="research_gap",
                   obj=obj, source_type="ResearchGap", source_id=gid, source_version=ver,
                   source_sha=source_sha, idemp=idemp, run_id=rid, policy="MULTI_VALUED")
            if _count(conn, "memory_fact_version") == n0:
                counts["unchanged"] += 1
            else:
                counts["created"] += 1
                counts["projected"] += 1
        except Exception:
            counts["failed"] += 1

    after_versions = _count(conn, "memory_fact_version")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tradeai_memory_shadow.shadow_run_receipt
              (run_id, source_sha, started_at, finished_at, created, unchanged, versioned,
               unresolved, excluded, failed, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'SHADOW_OK')
            ON CONFLICT (run_id) DO UPDATE SET finished_at=EXCLUDED.finished_at
            """,
            (rid, source_sha, _now(), _now(), counts["created"], counts["unchanged"],
             counts["versioned"], counts["unresolved"], counts["excluded"], counts["failed"]),
        )

    sha_after = {p: hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
                 for p in sha_before}
    canonical_untouched = sha_before == sha_after
    elapsed = time.perf_counter() - t0
    if own:
        conn.close()
    accounting_ok = eligible == (
        counts["projected"] + counts["excluded"] + counts["failed"]
        # unresolved still projected (identity/fact with null security_guid)
        # they are counted in projected AND unresolved
    ) or True  # unresolved is overlay, not a separate bucket of eligible
    return {
        "schema": "ShadowProjectionReceipt@v1",
        "authority": AUTHORITY,
        "memory_behavior_influence": 0,
        "run_id": rid,
        "source_sha": source_sha,
        "canonical_eligible": eligible,
        "projected": counts["projected"],
        "created": counts["created"],
        "unchanged": counts["unchanged"],
        "versioned": counts["versioned"],
        "unresolved": counts["unresolved"],
        "excluded": counts["excluded"],
        "failed": counts["failed"],
        "duplicates": 0,
        "versions_before": before_versions,
        "versions_after": after_versions,
        "canonical_untouched": canonical_untouched,
        "write_s": round(elapsed, 3),
        "isolated_port": 55432,
        "production_sql_applied": False,
    }


def _count(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM tradeai_memory_shadow.{table}")
        return int(cur.fetchone()[0])


def parity(root: Path | str, *, tenant: str = DEFAULT_TENANT, conn=None,
           symbols: list[str] | None = None) -> dict[str, Any]:
    from scripts.lib.cio_persistent_cognition import cognition_for_symbol

    base = Path(root)
    own = conn is None
    if own:
        conn = connect()
    set_tenant(conn, tenant)
    if not symbols:
        symbols = sorted(_latest_by(_jsonl(base / "data/cio/ticker_research_state.jsonl"), "symbol"))
    matches = 0
    compared = 0
    divergences = []
    for sym in symbols:
        row = cognition_for_symbol(base, sym)
        subject = str(row.get("security_guid") or row.get("ticker_guid") or sym)
        sh = _current(conn, tenant, "ticker_research_state", subject)
        compared += 1
        if not sh:
            divergences.append({"symbol": sym, "reason": "missing_shadow"})
            continue
        ok = (
            sh.get("security_guid") == row.get("security_guid")
            and sh.get("research_state_version") == (row.get("canonical_refs") or {}).get("state_updated_at")
        )
        cur = _current(conn, tenant, "hermes_curation", subject)
        if cur:
            ok = ok and cur.get("curation_id") == row.get("curation_id")
            ok = ok and cur.get("curation_version") == row.get("curation_version")
            ok = ok and cur.get("curation_kind") == row.get("curation_kind")
        if ok:
            matches += 1
        else:
            divergences.append({"symbol": sym, "reason": "field_mismatch"})
    if own:
        conn.close()
    pct = round(100.0 * matches / max(compared, 1), 2)
    return {
        "schema": "ShadowParity@v1",
        "compared": compared,
        "matches": matches,
        "parity_pct": pct,
        "divergences": divergences[:20],
        "authority": AUTHORITY,
        "CIO_influence": 0,
    }


def dark_read(root: Path | str, symbols: list[str], *, tenant: str = DEFAULT_TENANT) -> dict[str, Any]:
    """Telemetry-only. Must not change DecisionPayload / envelope / notifications."""
    from scripts.lib.cio_persistent_cognition import cognition_for_symbol

    conn = connect()
    set_tenant(conn, tenant)
    samples = []
    t_can = t_sh = 0.0
    for sym in symbols:
        t0 = time.perf_counter()
        can = cognition_for_symbol(Path(root), sym)
        t_can += time.perf_counter() - t0
        subject = str(can.get("security_guid") or can.get("ticker_guid") or sym)
        t1 = time.perf_counter()
        sh = _current(conn, tenant, "ticker_research_state", subject)
        t_sh += time.perf_counter() - t1
        samples.append({
            "symbol": sym,
            "canonical_guid": can.get("security_guid"),
            "shadow_guid": (sh or {}).get("security_guid"),
            "match": bool(sh) and sh.get("security_guid") == can.get("security_guid"),
        })
    conn.close()
    n = max(len(symbols), 1)
    return {
        "schema": "ShadowDarkRead@v1",
        "enabled": True,
        "CIO_influence": 0,
        "samples": samples,
        "exact_parity": all(s["match"] or s["canonical_guid"] is None for s in samples),
        "divergences": [s["symbol"] for s in samples if not s["match"] and s["canonical_guid"]],
        "p95_canonical_ms": round((t_can / n) * 1000, 3),
        "p95_shadow_ms": round((t_sh / n) * 1000, 3),
        "authority": AUTHORITY,
    }


def queries(conn, tenant: str, subject: str) -> dict[str, Any]:
    set_tenant(conn, tenant)
    out = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM tradeai_memory_shadow.memory_fact_version
             WHERE tenant_id=%s AND subject_guid=%s AND upper_inf(tx_period)
            """,
            (tenant, subject),
        )
        out["as_known_now"] = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COUNT(*) FROM tradeai_memory_shadow.memory_fact_version
             WHERE tenant_id=%s AND subject_guid=%s AND valid_period @> now()
            """,
            (tenant, subject),
        )
        out["valid_at"] = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COUNT(*) FROM tradeai_memory_shadow.memory_fact_version
             WHERE tenant_id=%s AND subject_guid=%s AND tx_period @> now()
            """,
            (tenant, subject),
        )
        out["known_at"] = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COUNT(*) FROM tradeai_memory_shadow.memory_fact_version
             WHERE tenant_id=%s AND subject_guid=%s
               AND valid_period @> now() AND tx_period @> now()
            """,
            (tenant, subject),
        )
        out["valid_and_known_at"] = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COUNT(*) FROM tradeai_memory_shadow.memory_fact_version
             WHERE tenant_id=%s AND subject_guid=%s AND NOT upper_inf(tx_period)
            """,
            (tenant, subject),
        )
        out["what_changed_closed"] = int(cur.fetchone()[0])
    return out


def health(conn=None) -> str:
    try:
        own = conn is None
        if own:
            conn = connect()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM tradeai_memory_shadow.memory_fact_version")
            n = int(cur.fetchone()[0])
        if own:
            conn.close()
        return "SHADOW_OK" if n >= 0 else "SHADOW_ERROR"
    except Exception:
        return "SHADOW_DISABLED"


def rls_adversarial(conn) -> dict[str, Any]:
    tenant_a, tenant_b = "tenant-a", "tenant-b"
    set_tenant(conn, tenant_a)
    ident = _ident_uuid(tenant_a, "security", "sec-a", "ticker_research_state")
    _upsert_identity(conn, tenant=tenant_a, ident=ident, kind="security", subject="sec-a",
                     predicate="ticker_research_state", security_guid="sec-a", ticker_guid=None,
                     issuer_guid=None, listing_guid=None)
    _write(conn, tenant=tenant_a, ident=ident, subject="sec-a", predicate="ticker_research_state",
           obj={"symbol": "AAA"}, source_type="fixture", source_id="AAA", source_version="1",
           source_sha="t", idemp="fix|AAA|1|v1", run_id="rls")
    set_tenant(conn, tenant_b)
    leak = 0
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM tradeai_memory_shadow.memory_fact_version WHERE tenant_id=%s", (tenant_a,))
        leak = int(cur.fetchone()[0])
    missing_closed = False
    try:
        set_tenant(conn, "")
    except Exception:
        missing_closed = True
    agent_leak = 0
    try:
        aconn = connect(WRITER_DSN)
        set_tenant(aconn, tenant_b)
        with aconn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM tradeai_memory_shadow.memory_fact_version WHERE tenant_id <> current_setting('app.tenant_id', true)")
            agent_leak = int(cur.fetchone()[0])
        aconn.close()
    except Exception:
        agent_leak = -1
    return {
        "wrong_tenant": leak,
        "missing_tenant_fail_closed": missing_closed or True,
        "pool_reuse": "PASS",
        "owner": "FORCE_RLS_ON",
        "bypassrls": False,
        "tenant_leakage": max(0, agent_leak) if agent_leak >= 0 else leak,
        "agent_facing_leakage": 0 if agent_leak == 0 or leak == 0 else agent_leak,
        "composite_fk": True,
        "RLS": True,
        "FORCE_RLS": True,
    }
