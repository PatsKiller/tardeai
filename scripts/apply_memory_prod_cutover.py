#!/usr/bin/env python3
"""Apply the M2 bitemporal v2 packaging to production -- safely, once.

Dry run is the default and opens a READ ONLY session:

    .venv/bin/python scripts/apply_memory_prod_cutover.py            # dry run
    .venv/bin/python scripts/apply_memory_prod_cutover.py --json     # dry run, JSON

Apply needs BOTH the flag and a confirmation naming the target database:

    TRADEAI_M2_PROD_CUTOVER_CONFIRM=trade_ai \\
        .venv/bin/python scripts/apply_memory_prod_cutover.py --apply

One transaction; never DROP / TRUNCATE / role DDL; post-checks and a rolled-back
smoke run before commit; a JSONL receipt either way. See
scripts/lib/memory_prod_cutover.py for the rails.

Target: the production DSN from DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD
(env, falling back to the repo .env), or --dsn. Credentials are never printed.

This does NOT enable production memory writes. That is a separate operator
step (TRADEAI_M2_PRODUCTION_MEMORY_AUTHORIZED=1 on the AEC cycle unit).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.memory_prod_cutover import (  # noqa: E402
    CONFIRM_ENV,
    CutoverRefused,
    apply,
    dry_run,
)


def _db_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD") if os.environ.get(k)}
    dotenv = ROOT / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                k = k.strip()
                if k in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"):
                    env.setdefault(k, v.strip())
    return env


def production_dsn() -> str:
    e = _db_env()
    user = quote(e.get("DB_USER", "trade_ai"), safe="")
    pw = e.get("DB_PASSWORD")
    auth = f"{user}:{quote(pw, safe='')}" if pw else user
    return (
        f"postgresql://{auth}@{e.get('DB_HOST', 'localhost')}:{e.get('DB_PORT', '5432')}/{e.get('DB_NAME', 'trade_ai')}"
    )


def _connect(dsn: str):
    import psycopg2  # noqa: PLC0415

    from scripts.lib.m2_live_shadow_guard import refuse_live_shadow_under_pytest  # noqa: PLC0415

    return psycopg2.connect(refuse_live_shadow_under_pytest(dsn), connect_timeout=10)


def _print_dry_run(report: dict) -> None:
    st = report["state"]
    print(f"== {report['schema']} DRY RUN (read-only session)")
    print(f"database={st['database']} user={st['current_user']} server={st['server_version']}")
    print(f"schema memory_r10_m2: exists={st['schema_exists']} owner={st['schema_owner']}")
    print(f"  comment: {st['schema_comment']}")
    print(f"extensions: {', '.join(st['extensions'])}")
    print(f"role m2_agent: {st['agent_role']}  role m2 exists: {st['role_m2_exists']}")
    print(f"CREATE on database: {st['db_create_privilege']}")
    print(f"row counts: {st['row_counts']}")
    print(
        f"tables={len(st['tables'])} views={len(st['views'])} indexes={len(st['indexes'])} "
        f"triggers={st['triggers']} functions={st['functions']}"
    )
    plan = report["plan"]
    print(f"\n== PLAN: {plan['run']} RUN, {plan['skip']} SKIP")
    for s in plan["steps"]:
        head = " ".join(s["sql"].split())[:110]
        print(f"  [{s['action']:<4}] {s['source']}#{s['index']:<3} {s['kind']:<22} {s['reason']}")
        if s["action"] == "RUN":
            print(f"         {head}")
    if plan["refusals"]:
        print("\n== REFUSALS (apply would refuse):")
        for r in plan["refusals"]:
            print(f"  - {r}")
    if report["rows_refusal"]:
        print(f"  - {report['rows_refusal']}")
    now = report["post_checks_now"]
    print("\n== POST-CHECKS asserted before commit (current status):")
    for k in report["post_checks_asserted"]:
        print(f"  {'ok ' if now.get(k) else 'NO '} {k}")
    print(
        "  + smoke (SAVEPOINT, rolled back): two SINGLE_VALUED assertions -> 2 current + 1 audit via "
        '"MemoryFactVersion@v2".row_kind; UPDATE of a closed version must raise BITEMPORAL_AUDIT_IMMUTABLE'
    )
    print(f"\nwould_apply={report['would_apply']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--apply", action="store_true", help=f"apply (also requires {CONFIRM_ENV}=<database>)")
    ap.add_argument("--dsn", help="target DSN (default: production from DB_* env / .env)")
    ap.add_argument("--allow-existing-rows", action="store_true", help="proceed although memory tables hold rows")
    ap.add_argument("--no-smoke", action="store_true", help="skip the rolled-back smoke run")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    conn = _connect(args.dsn or production_dsn())
    try:
        if not args.apply:
            report = dry_run(conn, allow_existing_rows=args.allow_existing_rows)
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True, default=str))
            else:
                _print_dry_run(report)
            return 0 if report["would_apply"] else 2
        try:
            receipt = apply(
                conn,
                confirm=os.environ.get(CONFIRM_ENV),
                allow_existing_rows=args.allow_existing_rows,
                run_smoke=not args.no_smoke,
            )
        except CutoverRefused as exc:
            print(json.dumps({"committed": False, "refused": str(exc)}, indent=2))
            return 3
        print(json.dumps(receipt, indent=2, sort_keys=True, default=str))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
