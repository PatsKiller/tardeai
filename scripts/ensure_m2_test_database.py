#!/usr/bin/env python3
"""Create this worktree's Postgres test database on the isolated :55432 cluster if it is missing.

ai_local_acceptance.sh gives every worktree its own ``m2_shadow_test_<sha12>`` so
concurrent acceptance runs never reset each other's memory schema. A database
that does not exist makes every ``m2_conn`` test SKIP, which would look green, so
the wrapper calls this first.

Refuses any name the test guard refuses (``m2_live_shadow_guard.TEST_DATABASE_RE``),
so it can never create -- or touch -- the live ``m2_shadow``. It only ever issues
``CREATE DATABASE``; it never drops. Exit 0 = exists or created; 3 = cluster not
reachable or psycopg2 missing (the tests will skip, and say so); 2 = refused name.

    python3 scripts/ensure_m2_test_database.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.m2_live_shadow_guard import (  # noqa: E402
    DEFAULT_TEST_DATABASE,
    SHADOW_ADMIN_DSN,
    TEST_DATABASE_ENV,
    TEST_DATABASE_RE,
    live_shadow_databases,
    with_database,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--name", default=os.environ.get(TEST_DATABASE_ENV) or DEFAULT_TEST_DATABASE)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    name = args.name.strip()
    if not TEST_DATABASE_RE.match(name) or name in live_shadow_databases():
        print(f"ensure_m2_test_database: REFUSED {name!r}")
        return 2
    try:
        import psycopg2
    except ImportError:
        print("ensure_m2_test_database: psycopg2 missing; m2_conn tests will skip")
        return 3
    try:
        conn = psycopg2.connect(with_database(SHADOW_ADMIN_DSN, DEFAULT_TEST_DATABASE), connect_timeout=3)
    except Exception as exc:  # noqa: BLE001 -- any connect failure means "not available"
        print(f"ensure_m2_test_database: :55432 not reachable ({type(exc).__name__}); m2_conn tests will skip")
        return 3
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if cur.fetchone():
                print(f"ensure_m2_test_database: {name} exists")
                return 0
            if args.dry_run:
                print(f"ensure_m2_test_database: DRY-RUN would CREATE DATABASE {name}")
                return 0
            cur.execute(f'CREATE DATABASE "{name}"')  # name matched TEST_DATABASE_RE above
            print(f"ensure_m2_test_database: created {name}")
            return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
