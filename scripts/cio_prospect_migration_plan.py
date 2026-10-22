#!/usr/bin/env python3
"""Plan (dry run) for the CIO prospect P1 migration — never applies it, never connects.

    .venv/bin/python scripts/cio_prospect_migration_plan.py           # human-readable plan
    .venv/bin/python scripts/cio_prospect_migration_plan.py --json    # machine-readable plan

AGENTS.md §26 (18.0.0, ACTIVE), §17 and §0 rule 7. The migration
(migrations/2026_10_22_cio_prospect.sql) creates a new authoritative Postgres store, which is an
operator decision. This tool is the quoted dry run that decision is made on: it reads the up and
down files, proves they are additive / archive-only by static analysis (no DROP, no DELETE, no
TRUNCATE, no ALTER of an existing table, no UPDATE), lists every table, constraint, trigger and
grant, states whether the registry row is granted, and prints the exact grant strings, each bound
to the files' sha256. It has no ``--apply``: the operator applies the file with psql.

Exit codes: 0 plan produced and the files pass the static checks; 1 a static check failed;
2 could not read the files.

AUTHORITY: READ_ONLY_ADVISORY. No database connection, no network, no write.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / "migrations" / "2026_10_22_cio_prospect.sql"
DOWN = ROOT / "migrations" / "2026_10_22_cio_prospect.down.sql"
REGISTRY = ROOT / "config" / "data_source_authority.json"
NEW_TABLES = ("cio_prospect", "cio_prospect_events")
EXPECTED_GRANTS = (
    "GRANT SELECT, INSERT, UPDATE ON cio_prospect TO trade_ai;",
    "GRANT SELECT, INSERT ON cio_prospect_events TO trade_ai;",
    "GRANT USAGE ON SEQUENCE cio_prospect_events_id_seq TO trade_ai;",
)


def _code(text: str) -> str:
    """SQL with -- comments removed (static checks look at statements, not prose)."""
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def static_checks(up_sql: str, down_sql: str) -> list[str]:
    """Return failures (empty = pass)."""
    up, down = _code(up_sql), _code(down_sql)
    fails: list[str] = []
    for label, sql in (("up", up), ("down", down)):
        if re.search(r"\bDROP\b", sql, re.I):
            fails.append(f"{label}: DROP present (never delete, §0 rule 6)")
        if re.search(r"\bDELETE\s+FROM\b", sql, re.I):
            fails.append(f"{label}: DELETE FROM present")
        if re.search(r"^\s*TRUNCATE\s+(TABLE\s+)?\w", sql, re.I | re.M):  # a trigger's "BEFORE TRUNCATE ON" is not one
            fails.append(f"{label}: TRUNCATE statement present")
        if re.search(r"^\s*UPDATE\s+\w", sql, re.I | re.M):
            fails.append(f"{label}: UPDATE statement present (no data is moved in P1)")
    for m in re.finditer(r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(\w+)", up, re.I):
        fails.append(f"up: ALTER TABLE {m.group(1)} (P1 alters nothing existing)")
    created = re.findall(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)", up, re.I)
    if tuple(created) != NEW_TABLES:
        fails.append(f"up: creates {created}, expected exactly {list(NEW_TABLES)}")
    if re.search(r"CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS)", up, re.I):
        fails.append("up: CREATE TABLE without IF NOT EXISTS (not idempotent)")
    grants = tuple(" ".join(g.split()) for g in re.findall(r"GRANT[^;]+;", up, re.I))
    if grants != EXPECTED_GRANTS:
        fails.append(f"up: grants {list(grants)} differ from the least-privilege set {list(EXPECTED_GRANTS)}")
    for t in NEW_TABLES:
        if f"RENAME TO {t}_archived_20261022" not in down:
            fails.append(f"down: {t} is not archived by rename")
    if "GRANT " in down:
        fails.append("down: grants something (reverse only withdraws)")
    return fails


def inventory(up_sql: str) -> dict:
    up = _code(up_sql)
    return {
        "tables": re.findall(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)", up, re.I),
        "indexes": re.findall(r"CREATE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+(\w+)", up, re.I),
        "constraints": re.findall(r"CONSTRAINT\s+(\w+)", up, re.I),
        "triggers": re.findall(r"CREATE\s+TRIGGER\s+(\w+)", up, re.I),
        "functions": re.findall(r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+(\w+)", up, re.I),
        "grants": [" ".join(g.split()) for g in re.findall(r"GRANT[^;]+;", up, re.I)],
        "revokes": [" ".join(g.split()) for g in re.findall(r"REVOKE[^;]+;", up, re.I)],
    }


def registry_state(path: Path = REGISTRY) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"readable": False, "error": str(exc)}
    granted = next((r for r in doc.get("domains") or [] if r.get("domain") == "cio_prospect"), None)
    proposed = next((r for r in doc.get("proposed_domains") or [] if r.get("domain") == "cio_prospect"), None)
    return {
        "readable": True,
        "granted": bool(granted and (granted.get("approval") or {}).get("approved_by")),
        "proposed": proposed is not None,
        "approval": (granted or {}).get("approval"),
    }


def build_plan() -> dict:
    up_sql, down_sql = UP.read_text(encoding="utf-8"), DOWN.read_text(encoding="utf-8")
    fails = static_checks(up_sql, down_sql)
    up_sha, down_sha = _sha(UP), _sha(DOWN)
    reg = registry_state()
    return {
        "schema": "CioProspectMigrationPlan@v1",
        "mode": "plan_only",
        "applies": False,
        "db_contact": False,
        "files": {
            "up": {"path": str(UP.relative_to(ROOT)), "sha256": up_sha},
            "down": {"path": str(DOWN.relative_to(ROOT)), "sha256": down_sha},
        },
        "static_checks": {"ok": not fails, "failures": fails},
        "inventory": inventory(up_sql),
        "registry_row": reg,
        "preconditions": [
            "operator grants registry row cio_prospect (§17) — recorded by scripts/lib/data_dictionary.promote",
            "operator grants the P1 migration naming the up file sha256 below (§17: a new authoritative store)",
            "role trade_ai exists on the target database",
        ],
        "operator_grants": [
            "registry row cio_prospect: an operator approval {approved_by, approved_on, reference, scope} recorded "
            "by scripts/lib/data_dictionary.promote (scope e.g. 'P1 shadow: InstrumentRecordStore dual-write; "
            "jsonl stays store of record')",
            f"P1 migration: operator grant naming migrations/2026_10_22_cio_prospect.sql sha256={up_sha}",
        ],
        "apply": 'psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_22_cio_prospect.sql',
        "verify": ("psql \"$DB\" -c \"SELECT to_regclass('public.cio_prospect'), "
                   "to_regclass('public.cio_prospect_events')\""),
        "enable_dual_write": ("after verify: TRADEAI_CIO_PROSPECT_PG_DUAL_WRITE=1 in the CIO lanes' environment "
                              "(operator); until then InstrumentRecordStore.upsert_prospect reports pg.mode=inert"),
        "rollback": 'psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_22_cio_prospect.down.sql '
                    "(archives by rename; jsonl store of record untouched; unset the dual-write flag first)",
        "memory_behavior_influence": 0,
    }


def _text(plan: dict) -> str:
    inv = plan["inventory"]
    lines = [
        "CIO prospect P1 migration — PLAN ONLY (no database contact, nothing applied)",
        f"  up   {plan['files']['up']['path']}  sha256 {plan['files']['up']['sha256']}",
        f"  down {plan['files']['down']['path']}  sha256 {plan['files']['down']['sha256']}",
        f"  static checks: {'PASS' if plan['static_checks']['ok'] else 'FAIL'}",
    ]
    lines += [f"    - {f}" for f in plan["static_checks"]["failures"]]
    lines += [
        f"  tables:      {', '.join(inv['tables'])}",
        f"  indexes:     {', '.join(inv['indexes'])}",
        f"  triggers:    {', '.join(inv['triggers'])}",
        f"  constraints: {len(inv['constraints'])}",
        "  grants:",
    ]
    lines += [f"    {g}" for g in inv["grants"]]
    reg = plan["registry_row"]
    lines.append(f"  registry row cio_prospect: {'GRANTED' if reg.get('granted') else 'NOT GRANTED (proposed)'}")
    lines.append("  operator grants required (§17):")
    lines += [f"    {g}" for g in plan["operator_grants"]]
    lines += [f"  apply:    {plan['apply']}", f"  verify:   {plan['verify']}",
              f"  enable:   {plan['enable_dual_write']}", f"  rollback: {plan['rollback']}"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        plan = build_plan()
    except OSError as exc:
        print(f"could not read migration files: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(plan, indent=2) if args.json else _text(plan))
    return 0 if plan["static_checks"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
