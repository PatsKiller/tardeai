#!/usr/bin/env python3
"""Active Trader migration runner (Stage 1).

Versioned, tracked, reversible migrations for the active-trader schema ONLY.
Legacy repo migrations are untouched by design.

Hard guards — this runner refuses to run when:
  * the target database is named 'trade_ai' (production), under any circumstances;
  * the DSN points at port 5432 on localhost (production cluster);
  * no DSN is provided (there is no default).

DSN source order: --dsn flag, then ACTIVE_TRADER_TEST_DATABASE_DSN env var.
The DSN value is never printed.

Commands: up | down [--to N | --all] | status | reapply
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "active_trader"
TRACKING_TABLE = "active_trader_schema_migrations"
PRODUCTION_DB_NAMES = {"trade_ai"}
PRODUCTION_PORTS = {"5432"}


class MigrationError(RuntimeError):
    pass


def _resolve_dsn(cli_dsn: str | None) -> str:
    dsn = cli_dsn or os.environ.get("ACTIVE_TRADER_TEST_DATABASE_DSN")
    if not dsn:
        raise MigrationError(
            "No DSN. Pass --dsn or set ACTIVE_TRADER_TEST_DATABASE_DSN "
            "(stored in Bitwarden project trade-ai-lab)."
        )
    if dsn.strip() == "UNSET__OPERATOR_REQUIRED":
        raise MigrationError("Sentinel DSN value rejected: operator must provision the real secret.")
    m = re.match(r"^postgres(?:ql)?://[^@]+@([^:/]+):(\d+)/([^?]+)", dsn)
    if not m:
        raise MigrationError("DSN not in postgresql://user:pw@host:port/db form.")
    host, port, db = m.group(1), m.group(2), m.group(3)
    if db in PRODUCTION_DB_NAMES:
        raise MigrationError(f"REFUSED: target database '{db}' is production. This runner never migrates production.")
    if host in {"localhost", "127.0.0.1"} and port in PRODUCTION_PORTS:
        raise MigrationError("REFUSED: target is the production cluster port (5432).")
    return dsn


def _connect(dsn: str):
    import psycopg2

    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SELECT current_database()")
    db = cur.fetchone()[0]
    if db in PRODUCTION_DB_NAMES:
        conn.close()
        raise MigrationError("REFUSED: connected database is production.")
    return conn


def _discover() -> list[tuple[int, str, Path, Path]]:
    out = []
    for up in sorted(MIGRATIONS_DIR.glob("*.up.sql")):
        m = re.match(r"^(\d{4})_(.+)\.up\.sql$", up.name)
        if not m:
            raise MigrationError(f"Bad migration filename: {up.name}")
        down = up.with_name(up.name.replace(".up.sql", ".down.sql"))
        if not down.exists():
            raise MigrationError(f"Missing rollback pair for {up.name}")
        out.append((int(m.group(1)), m.group(2), up, down))
    if [v for v, *_ in out] != sorted({v for v, *_ in out}):
        raise MigrationError("Duplicate migration versions.")
    return out


def _ensure_tracking(cur) -> None:
    cur.execute(
        f"""CREATE TABLE IF NOT EXISTS {TRACKING_TABLE} (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                up_sha256 TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
    )


def _applied(cur) -> dict[int, str]:
    cur.execute(f"SELECT version, up_sha256 FROM {TRACKING_TABLE} ORDER BY version")
    return dict(cur.fetchall())


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def cmd_up(conn) -> int:
    cur = conn.cursor()
    _ensure_tracking(cur)
    applied = _applied(cur)
    ran = 0
    for version, name, up, _down in _discover():
        if version in applied:
            if applied[version] != _sha(up):
                raise MigrationError(f"Applied migration {version:04d} no longer matches its file (idempotency violation).")
            continue
        cur.execute(up.read_text())
        cur.execute(f"INSERT INTO {TRACKING_TABLE} (version, name, up_sha256) VALUES (%s, %s, %s)", (version, name, _sha(up)))
        ran += 1
        print(f"applied {version:04d}_{name}")
    conn.commit()
    print(f"up: {ran} applied, {len(applied)} already present")
    return 0


def cmd_down(conn, to: int | None, all_: bool) -> int:
    cur = conn.cursor()
    _ensure_tracking(cur)
    applied = _applied(cur)
    target = 0 if all_ else (to if to is not None else max(applied) - 1 if applied else 0)
    ran = 0
    for version, name, _up, down in sorted(_discover(), reverse=True):
        if version in applied and version > target:
            cur.execute(down.read_text())
            cur.execute(f"DELETE FROM {TRACKING_TABLE} WHERE version = %s", (version,))
            ran += 1
            print(f"rolled back {version:04d}_{name}")
    conn.commit()
    print(f"down: {ran} rolled back (target={target})")
    return 0


def cmd_status(conn) -> int:
    cur = conn.cursor()
    _ensure_tracking(cur)
    applied = _applied(cur)
    conn.commit()
    for version, name, up, _down in _discover():
        state = "applied" if version in applied else "pending"
        drift = "" if version not in applied or applied[version] == _sha(up) else " DRIFT"
        print(f"{version:04d} {name:32s} {state}{drift}")
    return 0


def cmd_reapply(conn) -> int:
    cmd_down(conn, to=None, all_=True)
    return cmd_up(conn)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["up", "down", "status", "reapply"])
    ap.add_argument("--dsn", help="explicit DSN (never printed); default env ACTIVE_TRADER_TEST_DATABASE_DSN")
    ap.add_argument("--to", type=int, default=None, help="down: rollback to this version")
    ap.add_argument("--all", action="store_true", help="down: rollback everything")
    args = ap.parse_args(argv)
    try:
        conn = _connect(_resolve_dsn(args.dsn))
    except MigrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        if args.command == "up":
            return cmd_up(conn)
        if args.command == "down":
            return cmd_down(conn, args.to, args.all)
        if args.command == "status":
            return cmd_status(conn)
        return cmd_reapply(conn)
    except Exception as exc:  # fail loud, roll back partial work
        conn.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
