#!/usr/bin/env python3
"""m2_substrate_check.py — the bitemporal memory substrate (memory_r10_m2) checked against what is deployed.

Two modes, one JSON report (M2SubstrateCheck@v1):

  --shadow   five suites through the REAL API on the isolated TEST database (m2_shadow_test), in one
             transaction that is always rolled back; a row count before/after proves nothing persisted.
             Refuses any production port and the live shadow database. Suites: exclusion (GiST,
             temporal_policy SINGLE_VALUED_CURRENT), version closure (write_fact_version closes the prior
             tx_period → row_kind audit in the @v2 view), immutability (direct UPDATE/DELETE refused by
             trg_block_fact_manipulation; the SQLSTATE actually raised is recorded), adjudication receipt +
             provenance edge through the real columns and the @v views, identity spine (canonical key
             dedup, security_guid carried, tenant split). RLS as the agent role via
             memory_m2_v2.adversarial_rls_suite.
  --parity   READ-ONLY structural comparison of production (:5432, via db_adapter, BEGIN READ ONLY) with
             the shadow: view + base-table columns, function definitions, triggers, the exclusion
             constraint, RLS enablement + policies, and per-tenant row counts base vs view. Structural
             drift exits 1; findings (RLS absent, views empty while the base is populated) are listed, exit 0.

The third-party harness pasted 2026-09-28 assumed columns (entity_type, is_single_valued, version_guid),
a save_bitemporal_fact_version signature and a CONTRADICTED_BY edge type that do not exist here; this
file is the harness wired to the schema on disk. Authority: READ_ONLY_ADVISORY; no production write.
"""
NO_CONSUMER_REASON = (
    "M2SubstrateCheck@v1 reports are read by the operator and quoted in the Wave closeout; the check is run by "
    "hand (or from ai_local_acceptance), not by a scheduled lane"
)

import argparse
import datetime as _dt
import json
import os
import sys
import uuid
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "scripts"))
sys.path.insert(0, str(PROJ / "scripts" / "lib"))

SCHEMA = "M2SubstrateCheck@v1"
NS = "memory_r10_m2"
VIEWS = {"MemoryIdentity@v1": "memory_identity", "MemoryFactVersion@v2": "memory_fact_version",
         "AdjudicationReceipt@v1": "adjudication_receipt", "ProvenanceEdge@v1": "provenance_edge"}
FUNCTIONS = ("write_fact_version", "save_bitemporal_fact_version", "block_bitemporal_manipulation")
FORBIDDEN_PORTS = ("5432",)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ── pure helpers (unit-tested without a database) ─────────────────────────────

def refuse_production(dsn: str) -> None:
    """URL (host:port/db) and keyword (port=NNNN) DSNs alike; the production port is never accepted."""
    s = str(dsn)
    host_part = s.split("@")[-1]
    for p in FORBIDDEN_PORTS:
        if f":{p}/" in host_part or host_part.endswith(f":{p}") or f"port={p}" in s.replace(" ", "").replace(f"port={p}", f"port={p} ").split(" ")[0] or f"port={p} " in s + " ":
            raise RuntimeError(f"M2_SUBSTRATE_CHECK_PRODUCTION_PORT_FORBIDDEN:{p}")


def diff_structure(a: dict, b: dict, *, label_a: str = "production", label_b: str = "shadow") -> list[dict]:
    """Named differences between two captured structures ({section: {name: value}})."""
    out: list[dict] = []
    for section in sorted(set(a) | set(b)):
        sa, sb = a.get(section) or {}, b.get(section) or {}
        for name in sorted(set(sa) | set(sb)):
            va, vb = sa.get(name), sb.get(name)
            if va is None:
                out.append({"section": section, "name": name, "kind": f"missing_in_{label_a}"})
            elif vb is None:
                out.append({"section": section, "name": name, "kind": f"missing_in_{label_b}"})
            elif va != vb:
                out.append({"section": section, "name": name, "kind": "differs", label_a: va, label_b: vb})
    return out


def findings_from(rls: dict, counts: dict) -> list[dict]:
    """RLS_POLICIES_ABSENT:<table> when a base table has RLS off or zero policies; VIEW_EMPTY_BASE_POPULATED:<view>
    when the base table has rows for the tenant but the view returns none."""
    out: list[dict] = []
    for table, r in sorted((rls or {}).items()):
        if not r.get("enabled") or not r.get("forced") or int(r.get("policies") or 0) == 0:
            out.append({"finding": f"RLS_POLICIES_ABSENT:{table}", "enabled": r.get("enabled"), "forced": r.get("forced"), "policies": r.get("policies")})
    for view, c in sorted((counts or {}).items()):
        if int(c.get("base") or 0) > 0 and int(c.get("view") or 0) == 0:
            out.append({"finding": f"VIEW_EMPTY_BASE_POPULATED:{view}", "base": c.get("base"), "view": c.get("view"), "tenant": c.get("tenant")})
    return out


# ── capture ───────────────────────────────────────────────────────────────────

def capture(conn, *, tenant: str) -> dict:
    """Structure + RLS + counts for one database (read-only queries)."""
    cur = conn.cursor()
    cols: dict = {}
    for rel in list(VIEWS) + list(VIEWS.values()):
        cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position", (NS, rel))
        cols[rel] = [f"{n}:{t}" for n, t in cur.fetchall()]
    funcs: dict = {}
    for fn in FUNCTIONS:
        cur.execute("SELECT pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=%s AND p.proname=%s", (NS, fn))
        r = cur.fetchone()
        funcs[fn] = " ".join(str(r[0]).split()) if r else None
    trig: dict = {}
    cur.execute("SELECT t.tgname, c.relname, pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND NOT t.tgisinternal", (NS,))
    for name, rel, d in cur.fetchall():
        trig[f"{rel}.{name}"] = " ".join(str(d).split())
    cons: dict = {}
    cur.execute("SELECT conname, conrelid::regclass::text, pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace=(SELECT oid FROM pg_namespace WHERE nspname=%s) AND contype IN ('x','u','f')", (NS,))
    for name, rel, d in cur.fetchall():
        cons[f"{rel}.{name}"] = " ".join(str(d).split())
    rls: dict = {}
    cur.execute("SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, (SELECT count(*) FROM pg_policy WHERE polrelid=c.oid), "
                "(SELECT string_agg(polname || ':' || pg_get_expr(polqual, polrelid), ' | ' ORDER BY polname) FROM pg_policy WHERE polrelid=c.oid) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relkind='r'", (NS,))
    for rel, en, forced, n, pol in cur.fetchall():
        rls[rel] = {"enabled": bool(en), "forced": bool(forced), "policies": int(n), "policy": pol}
    cur.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
    counts: dict = {}
    for view, base in VIEWS.items():
        cur.execute(f'SELECT count(*) FROM {NS}.{base} WHERE tenant_id = %s', (tenant,)); b = cur.fetchone()[0]
        cur.execute(f'SELECT count(*) FROM {NS}."{view}" WHERE tenant_id = %s', (tenant,)); v = cur.fetchone()[0]
        counts[view] = {"base": int(b), "view": int(v), "tenant": tenant}
    cur.execute("SELECT current_user, (SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user), version()")
    who = cur.fetchone()
    return {"structure": {"columns": cols, "functions": funcs, "triggers": trig, "constraints": cons,
                          "rls_shape": {k: {"enabled": v["enabled"], "forced": v["forced"], "policy": v["policy"]} for k, v in rls.items()}},
            "rls": rls, "counts": counts, "role": {"user": who[0], "bypassrls": bool(who[1])}, "server": str(who[2])[:40]}


# ── shadow suites ─────────────────────────────────────────────────────────────

def run_shadow(dsn: str, *, tenant: str) -> dict:
    import psycopg2
    from psycopg2 import errors as pgerr
    # The substrate is reached THROUGH the façade (intelligence_client.substrate), never by a bare
    # silo import: PR #1337 (e2dcfce1a) shipped this file with `import memory_m2_v2` and broke the
    # memory chokepoint ratchet on main (LIVEPROOF-20260928 CI run 36442022000). Repaired here.
    try:
        from intelligence_client import substrate  # type: ignore
    except ImportError:
        from lib.intelligence_client import substrate  # type: ignore
    m2 = substrate("memory_m2_v2")
    from m2_live_shadow_guard import dsn_database, live_shadow_databases  # type: ignore
    refuse_production(dsn)
    if dsn_database(dsn) in live_shadow_databases():
        raise RuntimeError(f"M2_SUBSTRATE_CHECK_LIVE_SHADOW_REFUSED:{dsn_database(dsn)} (use the m2_shadow_test database)")
    conn = psycopg2.connect(dsn); conn.autocommit = False
    suites: dict = {}
    t = f"{tenant}:substrate-check:{uuid.uuid4().hex[:8]}"   # a throwaway tenant: nothing it writes can collide
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (t,))
        cur.execute(f"SELECT count(*) FROM {NS}.memory_fact_version"); before = cur.fetchone()[0]
    try:
        now = _dt.datetime.now(_dt.timezone.utc)
        vf, vt = now.isoformat(), (now + _dt.timedelta(days=10)).isoformat()
        vf2, vt2 = (now + _dt.timedelta(days=2)).isoformat(), (now + _dt.timedelta(days=8)).isoformat()
        subj = f"subject:{uuid.uuid4()}"
        # 1. exclusion
        ident = m2.insert_identity(conn, tenant_id=t, subject_guid=subj, predicate="portfolio_thesis", security_guid=str(uuid.uuid4()))
        with conn.cursor() as cur:
            cur.execute("SAVEPOINT s1")
            cur.execute(f"INSERT INTO {NS}.memory_fact_version (tenant_id, identity_guid, subject_guid, predicate, object_value, valid_period, tx_period, status, confidence, source_type, source_id, source_as_of, temporal_policy) "
                        "VALUES (%s,%s::uuid,%s,'portfolio_thesis','{\"thesis\":\"bullish\"}'::jsonb, tstzrange(%s::timestamptz,%s::timestamptz,'[)'), tstzrange(statement_timestamp(),NULL,'[)'), 'CANDIDATE','low','check','c1',statement_timestamp(),'SINGLE_VALUED_CURRENT')",
                        (t, ident, subj, vf, vt))
            excl = None
            try:
                cur.execute(f"INSERT INTO {NS}.memory_fact_version (tenant_id, identity_guid, subject_guid, predicate, object_value, valid_period, tx_period, status, confidence, source_type, source_id, source_as_of, temporal_policy) "
                            "VALUES (%s,%s::uuid,%s,'portfolio_thesis','{\"thesis\":\"bearish\"}'::jsonb, tstzrange(%s::timestamptz,%s::timestamptz,'[)'), tstzrange(statement_timestamp(),NULL,'[)'), 'CANDIDATE','low','check','c2',statement_timestamp(),'SINGLE_VALUED_CURRENT')",
                            (t, ident, subj, vf2, vt2))
            except pgerr.ExclusionViolation as exc:
                excl = exc.pgcode
            cur.execute("ROLLBACK TO SAVEPOINT s1")
            ident_m = m2.insert_identity(conn, tenant_id=t, subject_guid=subj, predicate="catalyst_tag")
            for i, (a, b) in enumerate(((vf, vt), (vf2, vt2))):
                cur.execute(f"INSERT INTO {NS}.memory_fact_version (tenant_id, identity_guid, subject_guid, predicate, object_value, valid_period, tx_period, status, confidence, source_type, source_id, source_as_of, temporal_policy) "
                            "VALUES (%s,%s::uuid,%s,'catalyst_tag',%s::jsonb, tstzrange(%s::timestamptz,%s::timestamptz,'[)'), tstzrange(statement_timestamp(),NULL,'[)'), 'CANDIDATE','low','check',%s,statement_timestamp(),'GAPS_ALLOWED')",
                            (t, ident_m, subj, json.dumps({"tag": ["earnings", "launch"][i]}), a, b, f"m{i}"))
            cur.execute(f"SELECT count(*) FROM {NS}.memory_fact_version WHERE tenant_id=%s AND identity_guid=%s::uuid", (t, ident_m)); multi = cur.fetchone()[0]
        suites["exclusion"] = {"pass": excl == "23P01" and multi == 2, "single_valued_sqlstate": excl, "multi_valued_rows": int(multi)}
        # 2. closure through the real function (memory_m2_v2.write_fact → write_fact_version)
        ident2 = m2.insert_identity(conn, tenant_id=t, subject_guid=subj, predicate="target_allocation")
        v1 = m2.write_fact(conn, tenant_id=t, identity_guid=ident2, subject_guid=subj, predicate="target_allocation", obj={"v": 1}, valid_from=vf, valid_to=vt, temporal_policy="SINGLE_VALUED_CURRENT")
        v2 = m2.write_fact(conn, tenant_id=t, identity_guid=ident2, subject_guid=subj, predicate="target_allocation", obj={"v": 2}, valid_from=vf, valid_to=vt, temporal_policy="SINGLE_VALUED_CURRENT")
        with conn.cursor() as cur:
            cur.execute(f'SELECT memory_version_id::text, row_kind, upper_inf(tx_period), supersedes_id::text FROM {NS}."MemoryFactVersion@v2" WHERE tenant_id=%s AND identity_guid=%s::uuid ORDER BY version_seq', (t, ident2))
            rows = cur.fetchall()
        by = {r[0]: r for r in rows}
        suites["closure"] = {"pass": len(rows) == 2 and by[v1][1] == "audit" and by[v1][2] is False and by[v2][1] == "current" and by[v2][3] == v1,
                             "rows": [{"id": r[0][:8], "row_kind": r[1], "tx_open": r[2], "supersedes": (r[3] or "")[:8]} for r in rows]}
        # 3. immutability — what the trigger promises (block_bitemporal_manipulation): content columns and the valid
        #    period of a CURRENT row never change; a CLOSED row never changes; DELETE never happens. Non-content
        #    columns (confidence, status, source_*) on a CURRENT row MAY change — by design, so that is recorded,
        #    not failed. The agent role has no UPDATE/DELETE privilege at all (checked separately below).
        codes = {}
        with conn.cursor() as cur:
            for label, sql, target in (("update_object_current", f"UPDATE {NS}.memory_fact_version SET object_value='{{\"v\": 9}}'::jsonb WHERE memory_version_id=%s::uuid", v2),
                                       ("update_valid_period_current", f"UPDATE {NS}.memory_fact_version SET valid_period=tstzrange(now(), NULL, '[)') WHERE memory_version_id=%s::uuid", v2),
                                       ("update_closed_row", f"UPDATE {NS}.memory_fact_version SET confidence='high' WHERE memory_version_id=%s::uuid", v1),
                                       ("delete_current", f"DELETE FROM {NS}.memory_fact_version WHERE memory_version_id=%s::uuid", v2),
                                       ("delete_closed", f"DELETE FROM {NS}.memory_fact_version WHERE memory_version_id=%s::uuid", v1),
                                       ("update_confidence_current", f"UPDATE {NS}.memory_fact_version SET confidence='high' WHERE memory_version_id=%s::uuid", v2)):
                cur.execute(f"SAVEPOINT {label}")
                try:
                    cur.execute(sql, (target,)); codes[label] = "ALLOWED"
                except Exception as exc:  # noqa: BLE001
                    codes[label] = f"{type(exc).__name__}:{getattr(exc, 'pgcode', '?')}"
                cur.execute(f"ROLLBACK TO SAVEPOINT {label}")
        must_refuse = ("update_object_current", "update_valid_period_current", "update_closed_row", "delete_current", "delete_closed")
        suites["immutability"] = {"pass": all(codes[k] != "ALLOWED" for k in must_refuse), **codes,
                                  "by_design": "confidence/status/source_* on a CURRENT row may change; the agent role cannot UPDATE or DELETE at all (42501)"}
        # 3b. the agent role: no direct write privilege on the base table (privilege, not trigger)
        try:
            from m2_live_shadow_guard import with_database, dsn_database as _dbn  # type: ignore
            agent_dsn = with_database(m2.AGENT_DSN, _dbn(dsn))
            ac = psycopg2.connect(agent_dsn); ac.autocommit = False
            agent = {}
            try:
                with ac.cursor() as cur:
                    cur.execute("SELECT set_config('app.tenant_id', %s, false)", (t,))
                    cur.execute("SELECT (SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user), (SELECT rolsuper FROM pg_roles WHERE rolname=current_user)")
                    agent["bypassrls"], agent["superuser"] = cur.fetchone()
                    for label, sql in (("update", f"UPDATE {NS}.memory_fact_version SET confidence='high' WHERE tenant_id=%s"), ("delete", f"DELETE FROM {NS}.memory_fact_version WHERE tenant_id=%s")):
                        cur.execute(f"SAVEPOINT a_{label}")
                        try:
                            cur.execute(sql, (t,)); agent[label] = "ALLOWED"
                        except Exception as exc:  # noqa: BLE001
                            agent[label] = f"{type(exc).__name__}:{getattr(exc, 'pgcode', '?')}"
                        cur.execute(f"ROLLBACK TO SAVEPOINT a_{label}")
            finally:
                ac.rollback(); ac.close()
            suites["agent_role_privileges"] = {"pass": agent.get("update") != "ALLOWED" and agent.get("delete") != "ALLOWED" and not agent.get("bypassrls") and not agent.get("superuser"), **agent}
        except Exception as exc:  # noqa: BLE001
            suites["agent_role_privileges"] = {"pass": False, "error": f"{type(exc).__name__}:{str(exc)[:120]}"}
        # 4. adjudication receipt + provenance edge through the real columns and the @v views
        from adjudication_receipt import build_receipt  # type: ignore
        rec = build_receipt(tenant_id=t, subject_guid=subj, predicate="target_allocation", candidate_fact_ids=[v1, v2], selected_fact_id=v2,
                            rejected_fact_ids=[v1], policy="NEWER_TX_WINS", conflict_id=f"conflict:{uuid.uuid4().hex[:8]}", provider="deterministic", model=None)
        adj_id = rec.get("adjudication_id") or str(uuid.uuid4())
        with conn.cursor() as cur:
            cur.execute(f"INSERT INTO {NS}.adjudication_receipt (adjudication_id, tenant_id, subject_guid, predicate, conflict_id, candidate_fact_ids, selected_fact_id, rejected_fact_ids, deterministic_policy, policy_version, provider, model, prompt_version, evidence_refs, trace_id, source_sha, chain_of_thought) "
                        "VALUES (%s::uuid,%s,%s,%s,%s,%s::uuid[],%s::uuid,%s::uuid[],%s,%s,%s,%s,%s,%s,%s,%s,false)",
                        (adj_id, t, subj, "target_allocation", rec.get("conflict_id"), [v1, v2], v2, [v1], rec.get("policy") or "NEWER_TX_WINS", rec.get("policy_version") or "v1",
                         "deterministic", None, None, [f"fact:{v1}", f"fact:{v2}"], f"trace:{uuid.uuid4().hex[:8]}", "0" * 64))
            cur.execute(f"INSERT INTO {NS}.provenance_edge (edge_id, tenant_id, from_object_id, to_object_id, relation, source, trace_id) VALUES (%s::uuid,%s,%s::uuid,%s::uuid,'SUPERSEDES','substrate-check',%s)",
                        (str(uuid.uuid4()), t, v2, v1, "trace:x"))
            cur.execute(f'SELECT selected_fact_id::text, array_length(rejected_fact_ids,1), deterministic_policy FROM {NS}."AdjudicationReceipt@v1" WHERE tenant_id=%s AND adjudication_id=%s::uuid', (t, adj_id)); a = cur.fetchone()
            cur.execute(f'SELECT relation, to_object_id::text FROM {NS}."ProvenanceEdge@v1" WHERE tenant_id=%s AND from_object_id=%s::uuid', (t, v2)); e = cur.fetchone()
        suites["adjudication_provenance"] = {"pass": bool(a) and a[0] == v2 and a[1] == 1 and bool(e) and e[0] == "SUPERSEDES" and e[1] == v1,
                                             "receipt": {"selected": (a[0] if a else None) == v2, "rejected": (a[1] if a else None), "policy": a[2] if a else None}, "edge": {"relation": e[0] if e else None, "walks_to_parent": (e[1] if e else None) == v1}}
        # 5. identity spine
        again = m2.insert_identity(conn, tenant_id=t, subject_guid=subj, predicate="portfolio_thesis")
        other = m2.insert_identity(conn, tenant_id=t + ":other", subject_guid=subj, predicate="portfolio_thesis")
        with conn.cursor() as cur:
            cur.execute(f'SELECT security_guid FROM {NS}."MemoryIdentity@v1" WHERE tenant_id=%s AND identity_guid=%s::uuid', (t, ident)); sg = cur.fetchone()
            cur.execute(f"SELECT count(*) FROM {NS}.memory_identity WHERE tenant_id=%s AND subject_guid=%s AND predicate='portfolio_thesis'", (t, subj)); n_same = cur.fetchone()[0]
        suites["identity_spine"] = {"pass": again == ident and other != ident and n_same == 1 and bool(sg and sg[0]),
                                    "dedup": again == ident, "tenant_split": other != ident, "rows_same_key": int(n_same), "security_guid_carried": bool(sg and sg[0])}
        # RLS as the agent role (existing suite; connection-independent)
        try:
            rls = m2.adversarial_rls_suite(conn)
        except Exception as exc:  # noqa: BLE001
            rls = {"error": f"{type(exc).__name__}:{str(exc)[:120]}"}
        suites["rls_as_agent"] = {"pass": rls.get("bypassrls") == "PASS" and not rls.get("agent_facing_leakage"), **{k: v for k, v in rls.items() if k in ("bypassrls", "security_definer", "agent_facing_leakage", "cross_tenant_rows", "error")}}
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {NS}.memory_fact_version"); after = cur.fetchone()[0]
        conn.close()
    return {"database": dsn.split("@")[-1], "tenant": t, "suites": suites, "rows_before": int(before), "rows_after": int(after),
            "rolled_back": int(before) == int(after), "pass": all(s.get("pass") for s in suites.values()) and int(before) == int(after)}


# ── parity ────────────────────────────────────────────────────────────────────

def run_parity(shadow_dsn: str, *, tenant: str) -> dict:
    import psycopg2
    import db_adapter  # type: ignore
    refuse_production(shadow_dsn)
    prod = db_adapter._get_conn()
    with prod.cursor() as cur:
        cur.execute("BEGIN READ ONLY")
    try:
        p = capture(prod, tenant=tenant)
    finally:
        prod.rollback()
    sh = psycopg2.connect(shadow_dsn); sh.autocommit = False
    try:
        s = capture(sh, tenant=tenant)
    finally:
        sh.rollback(); sh.close()
    drift = diff_structure(p["structure"], s["structure"])
    return {"tenant": tenant, "production": {"role": p["role"], "server": p["server"], "rls": p["rls"], "counts": p["counts"]},
            "shadow": {"database": shadow_dsn.split("@")[-1], "role": s["role"], "server": s["server"], "rls": s["rls"], "counts": s["counts"]},
            "drift": drift, "parity": "PARITY_OK" if not drift else "DRIFT",
            "findings": {"production": findings_from(p["rls"], p["counts"]), "shadow": findings_from(s["rls"], s["counts"])}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shadow", action="store_true"); ap.add_argument("--parity", action="store_true")
    ap.add_argument("--dsn", help="isolated test DSN for --shadow / shadow side of --parity (default: DEFAULT_DSN on the m2_shadow_test database)")
    ap.add_argument("--tenant", default=None); ap.add_argument("--out")
    a = ap.parse_args(argv)
    from memory_namespace import DEFAULT_TENANT  # type: ignore
    from memory_m2_benchmark import DEFAULT_DSN  # type: ignore
    from m2_live_shadow_guard import with_database, shadow_test_database, ensure_test_database  # type: ignore
    tenant = a.tenant or DEFAULT_TENANT
    dsn = a.dsn or with_database(DEFAULT_DSN, shadow_test_database())
    report = {"schema": SCHEMA, "as_of": _now(), "authority": "READ_ONLY_ADVISORY"}
    rc = 0
    if a.shadow:
        if not a.dsn:
            ensure_test_database()
        report["shadow"] = run_shadow(dsn, tenant=tenant)
        rc |= 0 if report["shadow"]["pass"] else 1
    if a.parity:
        report["parity"] = run_parity(dsn, tenant=tenant)
        rc |= 0 if report["parity"]["parity"] == "PARITY_OK" else 1
    if not (a.shadow or a.parity):
        ap.error("choose --shadow and/or --parity")
    print(json.dumps(report, indent=1, default=str))
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
