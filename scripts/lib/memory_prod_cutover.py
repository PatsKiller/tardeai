"""Production cutover for the M2 bitemporal memory substrate (memory_r10_m2).

Why this exists: the isolated apply paths (``apply_bitemporal_schema_v2``, the
packaging heal) refuse production by design, and the base SQL refuses to run at
all once the schema exists. Production :5432 already holds the base tables
(created by the 09-19/09-20 attempts) but never received the v2 packaging, so
there was no safe way to finish it. This module is that way.

It does NOT fork the reviewed SQL. It reads ``sql/r10_m2_isolated_benchmark.sql``
and ``sql/trade-ai-bitemporal-schema-v2.sql``, splits them into statements,
classifies every statement, and turns each into RUN or SKIP against the live
catalog. Anything it cannot classify refuses the whole plan (fail closed).

Rails, enforced in code, not by convention:

* never DROP / TRUNCATE / DELETE, never CREATE or ALTER a ROLE -- the base
  file's destructive-reset block and role block are always skipped, and the v2
  file's ``DROP TRIGGER IF EXISTS`` is never run (the CREATE TRIGGER that
  follows it runs only when the trigger is missing);
* ADD-only for tables, indexes, constraints, triggers, policies, RLS flags;
  CREATE OR REPLACE only for the reviewed function and view definitions;
* ONE transaction with ``lock_timeout`` / ``statement_timeout``; post-checks and
  a rolled-back smoke run BEFORE commit -- any failure rolls everything back;
* refuses when the memory tables hold rows unless explicitly allowed;
* the dry run uses a READ ONLY session.

This module never reads or sets TRADEAI_M2_PRODUCTION_MEMORY_AUTHORIZED: the
cutover prepares the schema, it does not turn production writes on.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
BASE_SQL = ROOT / "sql" / "r10_m2_isolated_benchmark.sql"
V2_SQL = ROOT / "sql" / "trade-ai-bitemporal-schema-v2.sql"
SCHEMA = "memory_r10_m2"
SCHEMA_VERSION = "MemoryProdCutover@v1"

MEMORY_TABLES = (
    "memory_identity",
    "memory_fact_version",
    "adjudication_receipt",
    "provenance_edge",
    "relationship_candidate",
    "predicate_temporal_policy",
)
V2_VIEWS = ("MemoryIdentity@v1", "MemoryFactVersion@v2", "AdjudicationReceipt@v1", "ProvenanceEdge@v1")
AGENT_ROLE = "m2_agent"
# Extensions the base file needs but trade_ai cannot create (not trusted).
SUPERUSER_ONLY_EXTENSIONS = {"vector"}

PRODUCTION_COMMENT = (
    "M2 v2 bitemporal cognitive memory. tstzrange, DB-owned tx_time, FORCE RLS. "
    "Production packaging applied by scripts/apply_memory_prod_cutover.py; the "
    "base file's destructive reset is refused here by its isolated-database allowlist."
)

LOCK_TIMEOUT_ENV = "TRADEAI_M2_CUTOVER_LOCK_TIMEOUT"
STATEMENT_TIMEOUT_ENV = "TRADEAI_M2_CUTOVER_STATEMENT_TIMEOUT"
RECEIPTS_ENV = "TRADEAI_M2_PROD_CUTOVER_RECEIPTS"
CONFIRM_ENV = "TRADEAI_M2_PROD_CUTOVER_CONFIRM"
DEFAULT_LOCK_TIMEOUT = "5s"
DEFAULT_STATEMENT_TIMEOUT = "60s"
DEFAULT_RECEIPTS = Path.home() / ".local" / "state" / "tradeai" / "memory_prod_cutover_receipts.jsonl"

_FORBIDDEN_HEAD = re.compile(
    r"^\s*(DROP|TRUNCATE|DELETE|ALTER\s+ROLE|CREATE\s+ROLE|ALTER\s+TABLE\s+\S+\s+DROP)\b", re.I
)


class CutoverRefused(RuntimeError):
    """Raised when a precondition or rail refuses the cutover."""


# ---------------------------------------------------------------------------
# SQL splitting and classification (pure; no database)
# ---------------------------------------------------------------------------


def split_sql(text: str) -> list[str]:
    """Split a SQL script on top-level ``;``.

    Honours dollar-quoted bodies (``$$`` / ``$tag$``) and single-quoted strings;
    drops ``--`` comments outside them. Good enough for the two reviewed files;
    anything it mis-splits fails classification and refuses the plan.
    """
    out: list[str] = []
    buf: list[str] = []
    i, n = 0, len(text)
    dollar: Optional[str] = None
    in_sq = False
    while i < n:
        c = text[i]
        if dollar is not None:
            if text.startswith(dollar, i):
                buf.append(dollar)
                i += len(dollar)
                dollar = None
            else:
                buf.append(c)
                i += 1
            continue
        if in_sq:
            buf.append(c)
            if c == "'":
                if i + 1 < n and text[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                in_sq = False
            i += 1
            continue
        if text.startswith("--", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "'":
            in_sq = True
            buf.append(c)
            i += 1
            continue
        if c == "$":
            m = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", text[i:])
            if m:
                dollar = m.group(0)
                buf.append(dollar)
                i += len(dollar)
                continue
        if c == ";":
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def _flat(stmt: str) -> str:
    return re.sub(r"\s+", " ", stmt).strip()


def classify(stmt: str) -> dict[str, Any]:
    """Name what a statement is. ``kind='unclassified'`` refuses the plan."""
    s = _flat(stmt)
    m = re.match(r'^CREATE EXTENSION IF NOT EXISTS "?([\w-]+)"?$', s, re.I)
    if m:
        return {"kind": "extension", "name": m.group(1)}
    if re.match(r"^DO \$\w*\$", s, re.I):
        if re.search(r"\bDROP\s+SCHEMA\b", s, re.I):
            return {"kind": "do_destructive_reset"}
        if re.search(r"\bCREATE\s+ROLE\b|\bALTER\s+ROLE\b", s, re.I):
            return {"kind": "do_role"}
        if re.search(r"\bGRANT\b.*\bTO m2'", s, re.I | re.S):
            return {"kind": "do_grant_m2"}
        return {"kind": "unclassified"}
    m = re.match(rf"^CREATE SCHEMA IF NOT EXISTS {SCHEMA}$", s, re.I)
    if m:
        return {"kind": "schema"}
    m = re.match(rf"^CREATE TABLE (?:IF NOT EXISTS )?{SCHEMA}\.(\w+)\b", s, re.I)
    if m:
        return {"kind": "table", "name": m.group(1)}
    m = re.match(rf"^CREATE (?:UNIQUE )?INDEX (?:IF NOT EXISTS )?(\w+) ON {SCHEMA}\.", s, re.I)
    if m:
        return {"kind": "index", "name": m.group(1)}
    m = re.match(rf"^ALTER TABLE {SCHEMA}\.(\w+) ADD CONSTRAINT (\w+)\b", s, re.I)
    if m:
        return {"kind": "constraint", "table": m.group(1), "name": m.group(2)}
    m = re.match(rf"^ALTER TABLE {SCHEMA}\.(\w+) (ENABLE|FORCE) ROW LEVEL SECURITY$", s, re.I)
    if m:
        return {"kind": "rls", "table": m.group(1), "mode": m.group(2).upper()}
    m = re.match(rf"^CREATE OR REPLACE FUNCTION {SCHEMA}\.(\w+)\s*\(", s, re.I)
    if m:
        return {"kind": "function", "name": m.group(1)}
    if re.match(r"^(REVOKE|GRANT)\b", s, re.I):
        return {"kind": "grant"}
    m = re.match(rf"^CREATE TRIGGER (\w+) .* ON {SCHEMA}\.(\w+) ", s, re.I)
    if m:
        return {"kind": "trigger", "name": m.group(1), "table": m.group(2)}
    m = re.match(rf"^DROP TRIGGER IF EXISTS (\w+) ON {SCHEMA}\.(\w+)$", s, re.I)
    if m:
        return {"kind": "drop_trigger", "name": m.group(1), "table": m.group(2)}
    m = re.match(rf"^CREATE POLICY (\w+) ON {SCHEMA}\.(\w+) ", s, re.I)
    if m:
        return {"kind": "policy", "name": m.group(1), "table": m.group(2)}
    m = re.match(rf'^CREATE OR REPLACE VIEW {SCHEMA}\."([^"]+)"', s, re.I)
    if m:
        return {"kind": "view", "name": m.group(1)}
    if re.match(rf"^COMMENT ON SCHEMA {SCHEMA} IS ", s, re.I):
        return {"kind": "schema_comment"}
    if re.match(rf"^COMMENT ON FUNCTION {SCHEMA}\.", s, re.I):
        return {"kind": "comment"}
    return {"kind": "unclassified"}


# ---------------------------------------------------------------------------
# Catalog state (read-only)
# ---------------------------------------------------------------------------

_STATE_QUERIES: dict[str, str] = {
    "database": "SELECT current_database()",
    "current_user": "SELECT current_user",
    "server_version": "SHOW server_version",
    "extensions": "SELECT extname FROM pg_extension",
    "schema_owner": ("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = %(s)s"),
    "schema_comment": ("SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname = %(s)s"),
    "tables": (
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %(s)s AND c.relkind = 'r'"
    ),
    "views": (
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %(s)s AND c.relkind = 'v'"
    ),
    "indexes": (
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %(s)s AND c.relkind = 'i'"
    ),
    "constraints": (
        "SELECT conname FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace WHERE n.nspname = %(s)s"
    ),
    "triggers": (
        "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = %(s)s AND NOT t.tgisinternal"
    ),
    "policies": "SELECT tablename || '.' || policyname FROM pg_policies WHERE schemaname = %(s)s",
    "rls_enabled": (
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %(s)s AND c.relkind = 'r' AND c.relrowsecurity"
    ),
    "rls_forced": (
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %(s)s AND c.relkind = 'r' AND c.relforcerowsecurity"
    ),
    "functions": (
        "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = %(s)s"
    ),
    "roles": (
        "SELECT rolname || ':' || rolsuper::text || ':' || rolbypassrls::text || ':' || rolcanlogin::text "
        "FROM pg_roles WHERE rolname IN ('m2_agent', 'm2')"
    ),
    "db_create_privilege": "SELECT has_database_privilege(current_user, current_database(), 'CREATE')",
}

_SET_KEYS = {
    "extensions",
    "tables",
    "views",
    "indexes",
    "constraints",
    "triggers",
    "policies",
    "rls_enabled",
    "rls_forced",
    "functions",
    "roles",
}


def read_state(cur) -> dict[str, Any]:
    """Catalog snapshot of the memory schema. SELECT-only."""
    state: dict[str, Any] = {}
    for key, sql in _STATE_QUERIES.items():
        cur.execute(sql, {"s": SCHEMA})
        rows = cur.fetchall()
        if key in _SET_KEYS:
            state[key] = sorted(str(r[0]) for r in rows)
        else:
            state[key] = rows[0][0] if rows else None
    state["schema_exists"] = state["schema_owner"] is not None
    counts: dict[str, Optional[int]] = {}
    for table in MEMORY_TABLES:
        if table in state["tables"]:
            cur.execute(f"SELECT count(*) FROM {SCHEMA}.{table}")  # noqa: S608 -- fixed allowlist
            counts[table] = int(cur.fetchone()[0])
        else:
            counts[table] = None
    state["row_counts"] = counts
    roles = {r.split(":")[0]: r.split(":")[1:] for r in state["roles"]}
    agent = roles.get(AGENT_ROLE)
    state["agent_role"] = {
        "exists": agent is not None,
        "safe": bool(agent) and agent[0] == "false" and agent[1] == "false",
        "can_login": bool(agent) and agent[2] == "true",
    }
    state["role_m2_exists"] = "m2" in roles
    return state


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


@dataclass
class Step:
    source: str
    index: int
    kind: str
    action: str  # RUN | SKIP
    reason: str
    sql: str
    name: Optional[str] = None


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)

    @property
    def run_steps(self) -> list[Step]:
        return [s for s in self.steps if s.action == "RUN"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "refusals": list(self.refusals),
            "run": len(self.run_steps),
            "skip": len(self.steps) - len(self.run_steps),
            "steps": [asdict(s) for s in self.steps],
        }


def _production_comment_sql() -> str:
    lit = PRODUCTION_COMMENT.replace("'", "''")
    return f"COMMENT ON SCHEMA {SCHEMA} IS '{lit}'"


def build_plan(state: dict[str, Any], *, base_sql: Optional[str] = None, v2_sql: Optional[str] = None) -> Plan:
    """Turn the reviewed SQL into RUN/SKIP steps against ``state``. Pure."""
    plan = Plan()
    ext = set(state.get("extensions") or [])
    tables = set(state.get("tables") or [])
    indexes = set(state.get("indexes") or [])
    constraints = set(state.get("constraints") or [])
    triggers = set(state.get("triggers") or [])
    policies = set(state.get("policies") or [])
    rls_enabled = set(state.get("rls_enabled") or [])
    rls_forced = set(state.get("rls_forced") or [])
    functions = set(state.get("functions") or [])
    views = set(state.get("views") or [])

    if not (state.get("agent_role") or {}).get("exists"):
        plan.refusals.append(
            "M2_AGENT_ROLE_MISSING: provision m2_agent first (scripts/secrets/ensure_m2_agent_dsn.py, operator)"
        )
    elif not state["agent_role"].get("safe"):
        plan.refusals.append("M2_AGENT_ROLE_UNSAFE: m2_agent must be NOSUPERUSER NOBYPASSRLS")
    if not state.get("db_create_privilege"):
        plan.refusals.append("NO_CREATE_ON_DATABASE: current user cannot CREATE in this database")

    sources = (
        ("base", base_sql if base_sql is not None else BASE_SQL.read_text(encoding="utf-8")),
        ("v2", v2_sql if v2_sql is not None else V2_SQL.read_text(encoding="utf-8")),
    )
    for source, text in sources:
        for idx, stmt in enumerate(split_sql(text)):
            c = classify(stmt)
            kind, name = c["kind"], c.get("name")
            action, reason, sql = "RUN", "", stmt

            if kind == "unclassified":
                plan.refusals.append(f"UNCLASSIFIED_STATEMENT {source}#{idx}: {_flat(stmt)[:120]}")
                action, reason = "SKIP", "unclassified -- plan refused"
            elif kind == "extension":
                if name in ext:
                    action, reason = "SKIP", "extension installed"
                elif name in SUPERUSER_ONLY_EXTENSIONS:
                    plan.refusals.append(f"EXTENSION_NEEDS_SUPERUSER: {name} (operator: CREATE EXTENSION {name})")
                    action, reason = "SKIP", "needs superuser -- plan refused"
                else:
                    reason = "install trusted extension"
            elif kind == "do_destructive_reset":
                action, reason = "SKIP", "destructive reset never runs in production"
            elif kind == "do_role":
                action, reason = "SKIP", "roles are operator-provisioned; repo SQL never creates/alters them here"
            elif kind == "do_grant_m2":
                reason = "conditional grant (no-op unless role m2 exists)"
            elif kind == "schema":
                if state.get("schema_exists"):
                    action, reason = "SKIP", "schema exists"
                else:
                    reason = "create schema"
            elif kind == "table":
                if name in tables:
                    action, reason = "SKIP", "table exists"
                else:
                    reason = "create missing table"
            elif kind == "index":
                if name in indexes:
                    action, reason = "SKIP", "index exists"
                else:
                    reason = "create missing index"
            elif kind == "constraint":
                if name in constraints:
                    action, reason = "SKIP", "constraint exists"
                else:
                    reason = "add missing constraint"
            elif kind == "rls":
                have = rls_enabled if c["mode"] == "ENABLE" else rls_forced
                if c["table"] in have:
                    action, reason = "SKIP", f"RLS already {c['mode'].lower()}d"
                else:
                    reason = f"{c['mode'].lower()} RLS"
            elif kind == "function":
                reason = "replace with reviewed definition" if name in functions else "create reviewed function"
            elif kind == "grant":
                reason = "idempotent privilege statement"
            elif kind == "drop_trigger":
                action, reason = "SKIP", "never DROP; the CREATE TRIGGER step runs only if the trigger is missing"
            elif kind == "trigger":
                if name in triggers:
                    action, reason = "SKIP", "trigger exists (function checked post-apply)"
                else:
                    reason = "create missing trigger"
            elif kind == "policy":
                if f"{c['table']}.{name}" in policies:
                    action, reason = "SKIP", "policy exists"
                else:
                    reason = "create missing policy"
            elif kind == "view":
                reason = (
                    "replace with reviewed definition" if name in views else "create reviewed view (security_invoker)"
                )
            elif kind == "schema_comment":
                sql, reason = _production_comment_sql(), "replace the 'do not apply to production' comment"
            elif kind == "comment":
                reason = "function comment"

            if action == "RUN" and _FORBIDDEN_HEAD.match(sql):
                plan.refusals.append(f"FORBIDDEN_STATEMENT {source}#{idx}: {_flat(sql)[:120]}")
                action, reason = "SKIP", "forbidden head -- plan refused"
            plan.steps.append(
                Step(source=source, index=idx, kind=kind, action=action, reason=reason, sql=sql, name=name)
            )
    return plan


# ---------------------------------------------------------------------------
# Post-checks (read-only) and smoke (rolled back)
# ---------------------------------------------------------------------------

_EXTRA_POST_SQL = f"""
SELECT
  (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = '{SCHEMA}' AND c.relkind = 'v'
      AND c.relname = ANY (ARRAY['MemoryIdentity@v1','MemoryFactVersion@v2','AdjudicationReceipt@v1','ProvenanceEdge@v1'])
      AND coalesce(c.reloptions, '{{}}') @> ARRAY['security_invoker=true']) = 4 AS views_security_invoker_ok,
  to_regclass('{SCHEMA}.identity_tenant_subject_idx') IS NOT NULL
    AND to_regclass('{SCHEMA}.adj_tenant_subject_idx') IS NOT NULL AS subject_indexes_ok,
  (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = '{SCHEMA}' AND c.relkind = 'r' AND c.relrowsecurity AND c.relforcerowsecurity) = 6
    AS rls_forced_ok,
  (SELECT count(*) FROM pg_policies WHERE schemaname = '{SCHEMA}') >= 6 AS policies_ok,
  EXISTS (SELECT 1 FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
    JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = '{SCHEMA}' AND t.tgname = 'trg_block_fact_manipulation'
      AND p.proname = 'block_bitemporal_manipulation') AS block_trg_fn_ok,
  EXISTS (SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = '{SCHEMA}' AND t.tgname = 'trg_no_agent_direct_insert') AS insert_trg_ok,
  coalesce(has_function_privilege('{AGENT_ROLE}', to_regprocedure(
    '{SCHEMA}.save_bitemporal_fact_version(text,uuid,text,text,jsonb,tstzrange,text,text,text,text,text,vector)'),
    'EXECUTE'), false) AS agent_save_exec_ok,
  coalesce(has_function_privilege('{AGENT_ROLE}', to_regprocedure(
    '{SCHEMA}.supersede_single_valued_fact(text,uuid,text,text,jsonb,tstzrange,text,text,text,text,uuid)'),
    'EXECUTE'), false) AS agent_supersede_exec_ok,
  NOT has_table_privilege('{AGENT_ROLE}', '{SCHEMA}.memory_fact_version', 'INSERT') AS agent_no_direct_fact_insert_ok,
  EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'uuid-ossp') AS uuid_ossp_ok,
  coalesce(obj_description('{SCHEMA}'::regnamespace, 'pg_namespace'), '')
    NOT ILIKE '%%do not apply to production%%' AS schema_comment_ok
"""


def post_checks(cur) -> dict[str, Any]:
    """Every assertion the cutover must satisfy before commit. SELECT-only."""
    from scripts.lib.bitemporal_schema_heal import PACKAGING_HEALTH_SQL  # noqa: PLC0415

    out: dict[str, Any] = {}
    for sql in (PACKAGING_HEALTH_SQL, _EXTRA_POST_SQL):
        cur.execute(sql)
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
        out.update({k: bool(v) for k, v in zip(cols, row, strict=True)})
    out["healthy"] = all(out.values())
    return out


POST_CHECK_NAMES = (
    "identity_ok",
    "fact_ok",
    "adj_ok",
    "prov_ok",
    "view_fact_ok",
    "save_fn_ok",
    "block_fn_ok",
    "block_trg_ok",
    "excl_ok",
    "supersede_fn_ok",
    "view_row_kind_ok",
    "views_security_invoker_ok",
    "subject_indexes_ok",
    "rls_forced_ok",
    "policies_ok",
    "block_trg_fn_ok",
    "insert_trg_ok",
    "agent_save_exec_ok",
    "agent_supersede_exec_ok",
    "agent_no_direct_fact_insert_ok",
    "uuid_ossp_ok",
    "schema_comment_ok",
)

SMOKE_TENANT = "tradeai:tenant:cutover-smoke"


def smoke(cur) -> dict[str, Any]:
    """Exercise the writers inside a SAVEPOINT that is always rolled back.

    Leaves no rows. Consumes a few version_seq values (sequences are not
    transactional) -- harmless, order keys only.
    """
    cur.execute("SAVEPOINT m2_cutover_smoke")
    try:
        cur.execute("SELECT set_config('app.tenant_id', %s, true)", (SMOKE_TENANT,))
        cur.execute(
            f"INSERT INTO {SCHEMA}.memory_identity (identity_guid, tenant_id, namespace, identity_kind, "
            "subject_guid, predicate, canonical_key) VALUES (gen_random_uuid(), %s, 'cutover_smoke', "
            "'smoke', 'cutover-smoke', 'thesis', 'cutover-smoke:' || gen_random_uuid()::text) "
            "RETURNING identity_guid",
            (SMOKE_TENANT,),
        )
        guid = cur.fetchone()[0]
        for days, value in ((2, 1), (1, 2)):
            cur.execute(
                f"SELECT {SCHEMA}.supersede_single_valued_fact(%s, %s, 'cutover-smoke', 'thesis', "
                "%s::jsonb, tstzrange(now() - make_interval(days => %s), NULL, '[)'), 'ACTIVE', "
                "'cutover_smoke', 'smoke')",
                (SMOKE_TENANT, guid, json.dumps({"v": value}), days),
            )
        cur.execute(
            f'SELECT row_kind, count(*) FROM {SCHEMA}."MemoryFactVersion@v2" '
            "WHERE identity_guid = %s GROUP BY row_kind",
            (guid,),
        )
        kinds = {k: int(n) for k, n in cur.fetchall()}
        cur.execute("SAVEPOINT m2_cutover_immutable")
        immutable = False
        try:
            cur.execute(
                f"UPDATE {SCHEMA}.memory_fact_version SET object_value = '{{}}'::jsonb "
                "WHERE identity_guid = %s AND NOT upper_inf(tx_period)",
                (guid,),
            )
        except Exception as exc:  # noqa: BLE001 -- the trigger MUST raise here
            immutable = "BITEMPORAL_AUDIT_IMMUTABLE" in str(exc)
        cur.execute("ROLLBACK TO SAVEPOINT m2_cutover_immutable")
        ok = kinds.get("current") == 2 and kinds.get("audit") == 1 and immutable
        return {"ok": ok, "row_kinds": kinds, "closed_version_immutable": immutable}
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT m2_cutover_smoke")
        cur.execute("RELEASE SAVEPOINT m2_cutover_smoke")


# ---------------------------------------------------------------------------
# Dry run / apply
# ---------------------------------------------------------------------------


def _source_sha() -> Optional[str]:
    sha = os.environ.get("SOURCE_COMMIT")
    if sha:
        return sha
    try:
        return (
            subprocess.run(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            ).stdout.strip()
            or None
        )
    except Exception:  # noqa: BLE001
        return None


def receipts_path() -> Optional[Path]:
    raw = str(os.environ.get(RECEIPTS_ENV) or "").strip()
    if raw:
        return Path(os.path.expanduser(raw))
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    return DEFAULT_RECEIPTS


def write_receipt(row: dict[str, Any]) -> Optional[Path]:
    path = receipts_path()
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    return path


def _refuse_rows(state: dict[str, Any], allow_existing_rows: bool) -> None:
    populated = {t: n for t, n in (state.get("row_counts") or {}).items() if n}
    if populated and not allow_existing_rows:
        raise CutoverRefused(f"M2_CUTOVER_SCHEMA_HAS_ROWS: {populated} (pass --allow-existing-rows)")


def dry_run(conn, *, allow_existing_rows: bool = False) -> dict[str, Any]:
    """READ ONLY session: snapshot, plan and current post-check status."""
    conn.set_session(readonly=True, autocommit=False)
    try:
        with conn.cursor() as cur:
            state = read_state(cur)
            plan = build_plan(state)
            current = post_checks(cur) if state.get("schema_exists") else {"healthy": False}
        rows_refusal = None
        try:
            _refuse_rows(state, allow_existing_rows)
        except CutoverRefused as exc:
            rows_refusal = str(exc)
        return {
            "schema": SCHEMA_VERSION,
            "mode": "dry_run",
            "state": state,
            "plan": plan.as_dict(),
            "post_checks_now": current,
            "post_checks_asserted": list(POST_CHECK_NAMES),
            "rows_refusal": rows_refusal,
            "would_apply": not plan.refusals and rows_refusal is None,
        }
    finally:
        conn.rollback()


def apply(conn, *, confirm: Optional[str], allow_existing_rows: bool = False, run_smoke: bool = True) -> dict[str, Any]:
    """One transaction: re-read state, run the plan, post-check, smoke, commit.

    ``confirm`` must equal the target database name (``TRADEAI_M2_PROD_CUTOVER_CONFIRM``).
    Any failure rolls back everything and is recorded in the receipt.
    """
    started = datetime.now(timezone.utc).isoformat()
    receipt: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "mode": "apply",
        "started_at": started,
        "source_sha": _source_sha(),
    }
    conn.set_session(readonly=False, autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            database = cur.fetchone()[0]
            receipt["database"] = database
            if not confirm or confirm != database:
                raise CutoverRefused(
                    f"M2_CUTOVER_CONFIRM_MISMATCH: set {CONFIRM_ENV}={database} to apply to this database"
                )
            lock_timeout = os.environ.get(LOCK_TIMEOUT_ENV) or DEFAULT_LOCK_TIMEOUT
            statement_timeout = os.environ.get(STATEMENT_TIMEOUT_ENV) or DEFAULT_STATEMENT_TIMEOUT
            cur.execute("SELECT set_config('lock_timeout', %s, true)", (lock_timeout,))
            cur.execute("SELECT set_config('statement_timeout', %s, true)", (statement_timeout,))
            state = read_state(cur)
            _refuse_rows(state, allow_existing_rows)
            plan = build_plan(state)
            if plan.refusals:
                raise CutoverRefused("M2_CUTOVER_PLAN_REFUSED: " + "; ".join(plan.refusals))
            executed = []
            for step in plan.run_steps:
                cur.execute(step.sql)
                executed.append(f"{step.source}#{step.index}:{step.kind}:{step.name or ''}")
            receipt["executed"] = executed
            checks = post_checks(cur)
            receipt["post_checks"] = checks
            if not checks["healthy"]:
                failed = sorted(k for k, v in checks.items() if k != "healthy" and not v)
                raise CutoverRefused(f"M2_CUTOVER_POST_CHECK_FAILED: {failed}")
            if run_smoke:
                s = smoke(cur)
                receipt["smoke"] = s
                if not s["ok"]:
                    raise CutoverRefused(f"M2_CUTOVER_SMOKE_FAILED: {s}")
            state_after = read_state(cur)
            receipt["row_counts_after"] = state_after["row_counts"]
        conn.commit()
        receipt["committed"] = True
    except Exception as exc:
        conn.rollback()
        receipt["committed"] = False
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        receipt["receipt_path"] = str(write_receipt(receipt) or "")
        raise
    receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
    receipt["receipt_path"] = str(write_receipt(receipt) or "")
    return receipt


__all__ = [
    "CONFIRM_ENV",
    "CutoverRefused",
    "POST_CHECK_NAMES",
    "Plan",
    "Step",
    "apply",
    "build_plan",
    "classify",
    "dry_run",
    "post_checks",
    "read_state",
    "smoke",
    "split_sql",
]
