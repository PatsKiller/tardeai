#!/usr/bin/env python3
"""trade_ai_restore_drill.py — monthly proof that the latest trade_ai dump restores (lane trade-ai-restore-drill).

Proposed schedule: first Sunday of the month, 03:30 ET — n8n cron ``30 3 * * 0`` with ``--first-week-only``
(a 5-field cron cannot say "first Sunday": ``30 3 1-7 * 0`` ORs day-of-month with day-of-week and fires
on days 1-7 AND every Sunday). n8n shadow first; the registry row stays NEVER_SCHEDULED until then.
Config: config/ops_lanes.json ``restore_drill``.

``--write`` (the drill):

  1. Find the latest trade_ai dump (same locator as scripts/backup_verify.py).
  2. Name a THROWAWAY database ``restore_drill_<YYYYMMDD>``; the name must fullmatch
     ``db_name_regex`` (``^restore_drill_\\d{8}$``, ASCII digits only) or the drill refuses.
  3. Disk-floor guard: estimate the restored size as live ``pg_database_size`` minus the schemas whose
     data the dump excludes (``excluded_data_schemas``), then refuse unless the free space on the
     cluster's filesystem is > ``disk_multiplier`` x estimate x (1 + ``disk_headroom_pct``/100).
  4. Role guard. The drill connects as a DEDICATED role (``role_user_env`` / ``role_password_env``,
     from the environment or the operator-only 0600 ``role_credentials_file``; NO fallback to the live
     DB_USER). Refuse unless it has CREATEDB, is not superuser / CREATEROLE / REPLICATION / BYPASSRLS,
     is not the live user and is not a member of the live database's owner. Refuse unless the
     ``template_db`` (extensions the role may not create, e.g. pgvector) exists as a template, psql
     supports ``\\restrict``, and no database of the drill name exists (a leftover is reported, never
     dropped: only a database this run created may be dropped).
  5. Dump guard pre-scan (scripts/lib/restore_dump_guard.py): the whole SQL stream (``.sql.gz``
     decompressed; ``.dump`` via ``pg_restore --no-owner --no-acl -f -``) is scanned BEFORE anything is
     created. ``\\connect`` or any other psql meta-command, CREATE/DROP/ALTER DATABASE, ALTER SYSTEM,
     role DDL / SET ROLE / SESSION AUTHORIZATION, GRANT/REVOKE, COPY ... PROGRAM or a COPY that is not
     ``FROM stdin`` refuses the drill (P1). The same guard runs again on the restore stream.
  6. CREATE DATABASE ... TEMPLATE ``template_db``, mark it with a COMMENT carrying this run's id, and
     restore: producer | guard | ``psql -X -d <throwaway>`` whose first input line is
     ``\\restrict <random per-run key>`` (psql then refuses every backslash command), niced, with a
     timeout. A guard violation kills psql before the offending line is sent.
  7. Row counts: exact ``count(*)`` in the throwaway for the ``compare_top_n`` largest live tables plus
     the configured ``key_tables``. Each must EQUAL the rows the dump's COPY block for it carried (the
     source of truth for what the restore had to load); a table the dump had no COPY for falls back to
     the live ``reltuples`` estimate within max(``row_tolerance_abs``, ``row_tolerance_pct``%). The
     live drift is recorded either way.
  8. DROP DATABASE — only that database, only if its name fullmatches the regex, equals the name this
     run created, and its COMMENT carries this run's id. Always attempted after a create, also when a
     later step failed.

``--dry-run`` prints the plan (dump, name, estimate, free space, guard verdicts, tables to compare)
and touches nothing: catalog reads on a read-only session only, no CREATE, no receipt. ``--scan-dump``
adds the dump-guard pre-scan (reads the dump file end to end; minutes).

Receipt (``--write`` only): ``$TRADEAI_STATE_ROOT/data/runtime/trade_ai_restore_drill_last.json``
(``TradeAiRestoreDrill@v2``). Findings use the incident fan-in shape; nothing sends.
Exit codes: 0 drill passed or plan printed, 1 drill refused or failed (receipt says why), 2 cannot run.

AUTHORITY: READ_ONLY_ADVISORY for live data. The only writes are the throwaway database this run
creates (and then drops) and its own receipt. It never writes, alters or drops anything else.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import ops_lanes as ol  # noqa: E402
from scripts.lib import restore_dump_guard as rdg  # noqa: E402
from scripts import backup_verify as bv  # noqa: E402

SCHEDULED_ENTRYPOINT = (
    "n8n lane trade-ai-restore-drill (config/lane_registry.json NEVER_SCHEDULED until shadow; proposed "
    "30 3 * * 0 + --first-week-only = first Sunday 03:30; config/n8n_run_allowlist.json entry, --dry-run / --write)"
)
SCHEMA = "TradeAiRestoreDrill@v2"
SOURCE = "trade_ai_restore_drill"
RECEIPT_REL = Path("data") / "runtime" / "trade_ai_restore_drill_last.json"
COMMENT_PREFIX = "tradeai-restore-drill run "

LIVE_SIZE_SQL = "SELECT pg_database_size(current_database())"
EXCLUDED_SIZE_SQL = (
    "SELECT COALESCE(SUM(pg_total_relation_size(c.oid)), 0) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE c.relkind IN ('r','m','p') AND n.nspname = ANY(%s)"
)
TOP_TABLES_SQL = (
    "SELECT n.nspname, c.relname, pg_total_relation_size(c.oid) AS bytes, GREATEST(c.reltuples, 0)::bigint "
    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE c.relkind = 'r' AND n.nspname NOT IN ('pg_catalog','information_schema') "
    "AND n.nspname NOT LIKE 'pg_toast%%' AND NOT (n.nspname = ANY(%s)) ORDER BY 3 DESC LIMIT %s"
)
KEY_TABLES_SQL = (
    "SELECT n.nspname, c.relname, pg_total_relation_size(c.oid) AS bytes, GREATEST(c.reltuples, 0)::bigint "
    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE c.relkind = 'r' AND (n.nspname || '.' || c.relname) = ANY(%s)"
)
ROLE_SQL = (
    "SELECT r.rolcreatedb, r.rolsuper, r.rolcreaterole, r.rolreplication, r.rolbypassrls, "
    "pg_has_role(r.oid, d.datdba, 'MEMBER') FROM pg_roles r, pg_database d "
    "WHERE r.rolname = %s AND d.datname = current_database()"
)
TEMPLATE_SQL = "SELECT datistemplate FROM pg_database WHERE datname = %s"
DRILL_DBS_SQL = "SELECT datname FROM pg_database WHERE datname LIKE 'restore\\_drill\\_%' ORDER BY 1"
COMMENT_SQL = "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = %s"
_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?")


class DrillRefused(Exception):
    pass


# ---------------------------------------------------------------------------- guards (pure)
def first_week(day: datetime) -> bool:
    return 1 <= day.day <= 7


def _name_ok(name: Any, regex: str) -> bool:
    return isinstance(name, str) and re.fullmatch(regex, name, re.ASCII) is not None


def drill_db_name(day: datetime, cfg: dict) -> str:
    name = f"{cfg['db_name_prefix']}{day.strftime('%Y%m%d')}"
    if not _name_ok(name, cfg["db_name_regex"]):
        raise DrillRefused(f"name {name!r} does not match {cfg['db_name_regex']}")
    return name


def disk_guard(estimate_bytes: int, avail_bytes: int, cfg: dict) -> dict:
    required = int(estimate_bytes * float(cfg["disk_multiplier"]) * (1 + float(cfg["disk_headroom_pct"]) / 100.0))
    return {
        "estimate_bytes": int(estimate_bytes),
        "required_free_bytes": required,
        "avail_bytes": int(avail_bytes),
        "rule": f"avail > {cfg['disk_multiplier']} x estimate x (1 + {cfg['disk_headroom_pct']}%)",
        "ok": avail_bytes > required,
    }


def assert_droppable(
    name: str, *, created_name: Optional[str], comment: Optional[str], run_id: str, regex: str
) -> None:
    """Raise unless ``name`` is the throwaway database THIS run created. Pure; tested."""
    if not _name_ok(name, regex):
        raise DrillRefused(f"refusing to drop {name!r}: does not match {regex}")
    if created_name is None or name != created_name:
        raise DrillRefused(f"refusing to drop {name!r}: not the database this run created ({created_name!r})")
    if comment != COMMENT_PREFIX + run_id:
        raise DrillRefused(f"refusing to drop {name!r}: marker comment {comment!r} is not this run's")


def role_verdict(user: Optional[str], row: Optional[tuple], *, live_user: Optional[str]) -> dict:
    """Classify the drill role from ROLE_SQL's row. Pure; tested.

    ``row`` = (createdb, superuser, createrole, replication, bypassrls, member_of_live_owner) or None.
    """
    v: dict[str, Any] = {"user": user, "exists": row is not None}
    if row is not None:
        createdb, sup, createrole, repl, bypass, member = (bool(x) for x in row)
        v.update(
            createdb=createdb,
            superuser=sup,
            createrole=createrole,
            replication=repl,
            bypassrls=bypass,
            member_of_live_owner=member,
        )
    v["configured"] = bool(user)
    v["dedicated"] = bool(user) and row is not None and user != live_user and not v.get("member_of_live_owner", True)
    v["createdb"] = bool(v.get("createdb"))
    v["unprivileged"] = row is not None and not any(
        v.get(k) for k in ("superuser", "createrole", "replication", "bypassrls")
    )
    return v


def psql_restrict_supported(version_text: Optional[str], min_versions: Mapping[str, int]) -> bool:
    """True when this psql understands ``\\restrict`` (17.6+, 16.10+, ..., 18+). Pure; tested."""
    m = _VERSION_RE.search(version_text or "")
    if not m:
        return False
    major, minor = int(m.group(1)), int(m.group(2) or 0)
    if major > max(int(k) for k in min_versions):
        return True
    floor = min_versions.get(str(major))
    return floor is not None and minor >= int(floor)


def classify_errors(lines: list[str], tolerated: list[str]) -> tuple[int, int]:
    rx = [re.compile(t) for t in tolerated]
    tol = sum(1 for ln in lines if any(r.search(ln) for r in rx))
    return len(lines) - tol, tol


def compare_counts(rows: list[dict], cfg: dict, dump_rows: Optional[Mapping[str, int]] = None) -> list[dict]:
    """Restored rows must equal the dump's COPY rows for the table; no COPY -> live estimate tolerance."""
    out = []
    for r in rows:
        est, got = int(r["live_estimate"]), r.get("restored_rows")
        tol = max(int(cfg["row_tolerance_abs"]), int(est * float(cfg["row_tolerance_pct"]) / 100.0))
        live_ok = got is not None and abs(int(got) - est) <= tol
        d = None if dump_rows is None else dump_rows.get(rdg.copy_table_key(r["schema"], r["table"]))
        if d is None:
            basis, ok = "live_estimate", live_ok
        else:
            basis, ok = "dump_copy_rows", got is not None and int(got) == int(d)
        out.append({**r, "dump_rows": d, "tolerance": tol, "live_ok": live_ok, "basis": basis, "ok": ok})
    return out


# ---------------------------------------------------------------------------- credentials
def _read_env_file(path: Path, keys: tuple[str, ...]) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        k, sep, v = line.partition("=")
        if sep and k.strip() in keys:
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def drill_db_params(cfg: dict, live: dict, env: Optional[Mapping[str, str]] = None) -> tuple[dict, dict]:
    """Connection params for the dedicated drill role. NEVER falls back to the live DB_USER.

    Order: environment, then the operator-only credentials file (refused unless mode is 0600 or
    stricter). Returns (params, source) — ``source`` is printable; params carry the password.
    """
    env = os.environ if env is None else env
    ukey, pkey = cfg["role_user_env"], cfg["role_password_env"]
    cred = ol.expand(cfg["role_credentials_file"])
    src: dict[str, Any] = {"credentials_file": str(cred), "file_status": "absent", "user_from": None}
    vals: dict = {}
    if cred.is_file():
        if cred.stat().st_mode & 0o077:
            src["file_status"] = "refused_mode_not_0600"
        else:
            vals = _read_env_file(cred, (ukey, pkey))
            src["file_status"] = "read"
    user = env.get(ukey) or vals.get(ukey)
    password = env.get(pkey) or vals.get(pkey) or ""
    src["user_from"] = "env" if env.get(ukey) else ("file" if vals.get(ukey) else None)
    params = {
        "host": live["host"],
        "port": live["port"],
        "dbname": "postgres",
        "user": user or None,
        "password": password,
    }
    return params, src


# ---------------------------------------------------------------------------- dump stream
def producer_argv(dump: Path) -> list[str]:
    """The command that writes the dump's SQL script to stdout (never to a database)."""
    if dump.name.endswith(".sql.gz"):
        return ["pigz" if shutil.which("pigz") else "gzip", "-dc", "--", str(dump)]
    return ["pg_restore", "--no-owner", "--no-acl", "-f", "-", str(dump)]


def _kill(*procs) -> None:
    for pr in procs:
        try:
            if pr is not None and pr.poll() is None:
                pr.kill()
        except Exception:  # noqa: BLE001
            pass


def prescan(dump: Path, *, timeout: int, popen: Callable = subprocess.Popen) -> dict:
    """Read the whole SQL stream through the guard; create nothing. ok only if clean AND complete."""
    prod = popen([*ol.nice_prefix(19), *producer_argv(dump)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    timed_out = threading.Event()
    timer = threading.Timer(timeout, lambda: (timed_out.set(), _kill(prod)))
    timer.start()
    guard, violation = rdg.DumpGuard(), None
    try:
        for line in prod.stdout:
            guard.feed(line)
        if not timed_out.is_set():
            guard.finish()
    except rdg.DumpGuardViolation as exc:
        violation = exc
        _kill(prod)
    finally:
        timer.cancel()
        try:
            prod.stdout.close()
        except Exception:  # noqa: BLE001
            pass
        rc = prod.wait()
    out: dict[str, Any] = {
        "ok": violation is None and rc == 0 and not timed_out.is_set(),
        "producer_rc": rc,
        "timed_out": timed_out.is_set(),
        "violation": violation.as_dict() if violation else None,
        **guard.summary(),
    }
    out["copy_rows"] = dict(guard.copy_rows)
    return out


def restore(
    dump: Path,
    db_name: str,
    params: dict,
    *,
    timeout: int,
    name_regex: str,
    popen: Callable = subprocess.Popen,
    key: Optional[str] = None,
    tolerated: Optional[list] = None,
) -> dict:
    """producer | DumpGuard | psql -d <throwaway>, with psql in \\restrict mode under a per-run key."""
    if not _name_ok(db_name, name_regex):
        raise DrillRefused(f"restore target {db_name!r} is not a throwaway drill database")
    key = key or secrets.token_hex(16)
    env = {**os.environ, "PGPASSWORD": params.get("password") or "", "PGOPTIONS": "-c statement_timeout=0"}
    conn_args = ["-h", str(params["host"]), "-p", str(params["port"]), "-U", str(params["user"])]
    psql_argv = [*ol.nice_prefix(19), "psql", "-X", "-q", "-v", "ON_ERROR_STOP=0", *conn_args, "-d", db_name]
    guard, violation, broken = rdg.DumpGuard(), None, False
    timed_out = threading.Event()
    with tempfile.TemporaryFile(mode="w+b") as errf:
        psql = popen(psql_argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errf, env=env)
        prod = popen([*ol.nice_prefix(19), *producer_argv(dump)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        timer = threading.Timer(timeout, lambda: (timed_out.set(), _kill(prod, psql)))
        timer.start()
        try:
            psql.stdin.write(b"\\restrict " + key.encode("ascii") + b"\n")
            for line in prod.stdout:
                out = guard.feed(line)
                if out is not None:
                    psql.stdin.write(out)
            if not timed_out.is_set():
                guard.finish()
        except rdg.DumpGuardViolation as exc:
            # Kill psql FIRST: closing stdin would make psql execute a partial statement at EOF.
            violation = exc
            _kill(psql, prod)
        except (BrokenPipeError, OSError):
            broken = True
            _kill(prod)
        finally:
            for f in (psql.stdin, prod.stdout):
                try:
                    f.close()
                except Exception:  # noqa: BLE001
                    pass
            prod_rc = prod.wait()
            rc: Optional[int] = psql.wait()
            timer.cancel()
        errf.seek(0)
        errors = [ln.decode("utf-8", errors="replace").strip() for ln in errf if b"ERROR:" in ln]
    untolerated, tolerated_n = classify_errors(errors, list(tolerated or []))
    bad_first = [e[:200] for e in errors if not any(re.search(t, e) for t in (tolerated or []))][:10]
    if timed_out.is_set():
        rc = None
    return {
        "rc": rc,
        "producer_rc": prod_rc,
        "timed_out": timed_out.is_set(),
        "psql_pipe_broken": broken,
        "guard_violation": violation.as_dict() if violation else None,
        "guard": guard.summary(),
        "copy_rows": dict(guard.copy_rows),
        "error_lines": untolerated,
        "tolerated_error_lines": tolerated_n,
        "first_errors": bad_first,
    }


# ---------------------------------------------------------------------------- plan (read-only)
def plan(
    cfg: dict,
    *,
    now: datetime,
    live_params: dict,
    drill_params: dict,
    connect=None,
    env=None,
    psql_version: Optional[str] = None,
) -> dict:
    connect = connect or ol.pg_connect
    bcfg = ol.load_config()["backup_verify"]
    d = bv.dump_dir(bcfg, env)
    dumps = bv.list_dumps(d, bcfg["dump_globs"]) if d.is_dir() else []
    p: dict[str, Any] = {
        "dump_dir": str(d),
        "dump": dumps[0].name if dumps else None,
        "dump_bytes": dumps[0].stat().st_size if dumps else None,
    }
    p["db_name"] = drill_db_name(now, cfg)
    excluded = list(cfg["excluded_data_schemas"])
    key_names = [k for k in cfg.get("key_tables") or [] if k.split(".", 1)[0] not in excluded]
    template = cfg.get("template_db")
    role_row, template_row = None, None
    conn = connect(live_params)
    try:
        cur = conn.cursor()
        cur.execute(LIVE_SIZE_SQL)
        live_size = int(cur.fetchone()[0])
        cur.execute(EXCLUDED_SIZE_SQL, (excluded,))
        excluded_size = int(cur.fetchone()[0])
        cur.execute(TOP_TABLES_SQL, (excluded, int(cfg["compare_top_n"])))
        tables = [
            {"schema": r[0], "table": r[1], "bytes": int(r[2]), "live_estimate": int(r[3]), "key": False}
            for r in cur.fetchall()
        ]
        if key_names:
            cur.execute(KEY_TABLES_SQL, (key_names,))
            keyed = [
                {"schema": r[0], "table": r[1], "bytes": int(r[2]), "live_estimate": int(r[3]), "key": True}
                for r in cur.fetchall()
            ]
        else:
            keyed = []
        if drill_params.get("user"):
            cur.execute(ROLE_SQL, (drill_params["user"],))
            role_row = cur.fetchone()
        if template:
            cur.execute(TEMPLATE_SQL, (template,))
            template_row = cur.fetchone()
        cur.execute(DRILL_DBS_SQL)
        existing = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
    seen = {(t["schema"], t["table"]) for t in tables}
    for t in keyed:
        if (t["schema"], t["table"]) in seen:
            next(x for x in tables if (x["schema"], x["table"]) == (t["schema"], t["table"]))["key"] = True
        else:
            tables.append(t)
    found = {f"{t['schema']}.{t['table']}" for t in keyed}
    p["key_tables_missing"] = [k for k in key_names if k not in found]
    p["live_size_bytes"] = live_size
    p["excluded_schemas_bytes"] = excluded_size
    fs = ol.fs_usage(cfg["pg_data_fs_path"])
    p["disk_guard"] = disk_guard(max(live_size - excluded_size, 0), fs["avail_bytes"], cfg)
    p["drill_role"] = role_verdict(drill_params.get("user"), role_row, live_user=live_params.get("user"))
    p["template_db"] = {
        "name": template or "template0",
        "present": (template_row is not None and bool(template_row[0])) if template else True,
    }
    p["psql_version"] = psql_version
    p["existing_drill_databases"] = [e for e in existing if e != template]
    p["tables_to_compare"] = tables
    checks = {
        "dump_present": p["dump"] is not None,
        "name_guard": True,
        "disk_guard": p["disk_guard"]["ok"],
        "role_configured": p["drill_role"]["configured"],
        "role_dedicated": p["drill_role"]["dedicated"],
        "role_createdb": p["drill_role"]["createdb"],
        "role_unprivileged": p["drill_role"]["unprivileged"],
        "template_present": p["template_db"]["present"],
        "psql_restrict": psql_restrict_supported(psql_version, cfg["psql_restrict_min_versions"]),
        "name_free": p["db_name"] not in existing,
    }
    p["preconditions"] = checks
    p["would_run"] = all(checks.values())
    return p


def apply_prescan(p: dict, scan: dict) -> dict:
    """Fold a pre-scan into the plan: the dump guard becomes a precondition."""
    p["dump_guard"] = {k: v for k, v in scan.items() if k != "copy_rows"}
    p["preconditions"]["dump_guard"] = bool(scan["ok"])
    p["would_run"] = all(p["preconditions"].values())
    return p


def psql_version_text() -> Optional[str]:
    try:
        cp = subprocess.run(["psql", "--version"], capture_output=True, text=True, timeout=30, check=False)
        return cp.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


# ---------------------------------------------------------------------------- the drill
def count_rows(params: dict, db_name: str, tables: list[dict], *, connect=None) -> list[dict]:
    from psycopg2 import sql

    connect = connect or ol.pg_connect
    conn = connect(params, dbname=db_name, read_only=True, timeout_ms=1800000)
    out = []
    try:
        cur = conn.cursor()
        for t in tables:
            try:
                cur.execute(
                    sql.SQL("SELECT count(*) FROM {}.{}").format(
                        sql.Identifier(t["schema"]), sql.Identifier(t["table"])
                    )
                )
                out.append({**t, "restored_rows": int(cur.fetchone()[0])})
            except Exception as exc:  # noqa: BLE001 — a missing table is a finding
                out.append({**t, "restored_rows": None, "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
    finally:
        conn.close()
    return out


def run_drill(
    cfg: dict, p: dict, drill_params: dict, *, run_id: str, connect=None, restore_fn=None, count_fn=None
) -> dict:
    from psycopg2 import sql

    connect = connect or ol.pg_connect
    count_fn = count_fn or count_rows
    if restore_fn is None:

        def restore_fn(dump, name, params, timeout):
            return restore(
                dump,
                name,
                params,
                timeout=timeout,
                name_regex=cfg["db_name_regex"],
                tolerated=cfg.get("tolerated_error_regexes"),
            )

    name = p["db_name"]
    if not _name_ok(name, cfg["db_name_regex"]):
        raise DrillRefused(f"refusing to create {name!r}: does not match {cfg['db_name_regex']}")
    template = cfg.get("template_db") or "template0"
    result: dict[str, Any] = {"created": False, "dropped": False}
    created_name: Optional[str] = None
    try:
        admin = connect(drill_params, dbname="postgres", read_only=False)
        try:
            cur = admin.cursor()
            cur.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(name), sql.Identifier(template))
            )
            created_name = name
            result["created"] = True
            cur.execute(
                sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                    sql.Identifier(name), sql.Literal(COMMENT_PREFIX + run_id)
                )
            )
        finally:
            admin.close()
        dump = Path(p["dump_dir"]) / p["dump"]
        result["restore"] = restore_fn(dump, name, drill_params, timeout=int(cfg["restore_timeout_s"]))
        copy_rows = (result["restore"] or {}).pop("copy_rows", None)
        result["comparison"] = compare_counts(count_fn(drill_params, name, p["tables_to_compare"]), cfg, copy_rows)
    finally:
        if created_name is not None:
            result["drop"] = drop_throwaway(
                name,
                created_name=created_name,
                run_id=run_id,
                params=drill_params,
                regex=cfg["db_name_regex"],
                connect=connect,
            )
            result["dropped"] = result["drop"].get("ok", False)
    return result


def drop_throwaway(name: str, *, created_name: str, run_id: str, params: dict, regex: str, connect=None) -> dict:
    from psycopg2 import sql

    connect = connect or ol.pg_connect
    try:
        admin = connect(params, dbname="postgres", read_only=False)
        try:
            cur = admin.cursor()
            cur.execute(COMMENT_SQL, (name,))
            row = cur.fetchone()
            assert_droppable(
                name, created_name=created_name, comment=row[0] if row else None, run_id=run_id, regex=regex
            )
            cur.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
        finally:
            admin.close()
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001 — a throwaway left behind is a P1 finding, never a crash
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def findings_for(p: dict, result: Optional[dict]) -> list[dict]:
    rel = str(RECEIPT_REL)
    out = []
    if not p["would_run"]:
        failed = [k for k, v in p["preconditions"].items() if not v]
        sev = "P1" if {"dump_present", "dump_guard"} & set(failed) else "P2"
        detail = f"restore drill refused: {', '.join(failed)}"
        v = (p.get("dump_guard") or {}).get("violation")
        if v:
            detail += f" (dump guard: {v['rule']} at line {v['line_no']})"
        out.append(ol.finding(SOURCE, "refused:" + ",".join(failed), sev, detail, rel))
        return out
    if result is None:
        return out
    r = result.get("restore") or {}
    if r.get("guard_violation"):
        v = r["guard_violation"]
        out.append(
            ol.finding(
                SOURCE, "dump:guard_violation", "P1", f"restore stream refused at line {v['line_no']}: {v['rule']}", rel
            )
        )
    elif r.get("timed_out") or r.get("rc") not in (0,) or r.get("producer_rc") not in (0, None):
        out.append(
            ol.finding(
                SOURCE,
                "restore:failed",
                "P1",
                f"restore rc={r.get('rc')} producer_rc={r.get('producer_rc')} timed_out={r.get('timed_out')} errors={r.get('error_lines')}",
                rel,
            )
        )
    elif r.get("error_lines"):
        out.append(
            ol.finding(
                SOURCE,
                "restore:errors",
                "P2",
                f"{r['error_lines']} ERROR lines; first: {(r.get('first_errors') or [''])[0]}",
                rel,
            )
        )
    bad = [c for c in result.get("comparison") or [] if not c["ok"]]
    if bad:
        out.append(
            ol.finding(
                SOURCE,
                "rows:mismatch",
                "P1",
                f"{len(bad)} of {len(result.get('comparison') or [])} tables wrong: "
                + ", ".join(f"{c['schema']}.{c['table']}" for c in bad[:5]),
                rel,
            )
        )
    if result.get("created") and not result.get("dropped"):
        out.append(
            ol.finding(
                SOURCE,
                "throwaway:left_behind",
                "P1",
                f"{p['db_name']} not dropped: {(result.get('drop') or {}).get('error')}",
                rel,
            )
        )
    return out


def print_plan(p: dict, src: Optional[dict] = None) -> None:
    g = p["disk_guard"]
    gib = 1 << 30
    role = p["drill_role"]
    print("restore-drill PLAN (dry-run; nothing created, nothing written)")
    print(f"  dump: {p['dump_dir']}/{p['dump']} ({(p['dump_bytes'] or 0) // (1 << 20)} MiB)")
    print(
        f"  throwaway db: {p['db_name']} (regex guard ok); template {p['template_db']['name']} present={p['template_db']['present']}; existing restore_drill_* dbs: {p['existing_drill_databases'] or 'none'}"
    )
    print(
        f"  live trade_ai {p['live_size_bytes'] // gib} GiB, excluded-data schemas {p['excluded_schemas_bytes'] // gib} GiB"
    )
    print(
        f"  disk guard: estimate {g['estimate_bytes'] // gib} GiB, required free {g['required_free_bytes'] // gib} GiB, avail {g['avail_bytes'] // gib} GiB -> {'OK' if g['ok'] else 'REFUSE'} ({g['rule']})"
    )
    print(
        f"  drill role {role['user']!r}: configured={role['configured']} dedicated={role['dedicated']} createdb={role['createdb']} unprivileged={role['unprivileged']}"
        + (
            f" (credentials: {src['file_status']} {src['credentials_file']}, user from {src['user_from']})"
            if src
            else ""
        )
    )
    print(f"  psql: {p.get('psql_version')} (\\restrict supported={p['preconditions'].get('psql_restrict')})")
    dg = p.get("dump_guard")
    print(
        "  dump guard: "
        + (
            "not scanned (add --scan-dump)"
            if dg is None
            else f"ok={dg['ok']} lines={dg['lines']} copy_blocks={dg['copy_blocks']} violation={dg['violation']}"
        )
    )
    keys = [f"{t['schema']}.{t['table']}" for t in p["tables_to_compare"] if t.get("key")]
    print(
        f"  compare {len(p['tables_to_compare'])} tables (key: {', '.join(keys) or 'none'}; key tables missing live: {p.get('key_tables_missing') or 'none'}): "
        + ", ".join(f"{t['schema']}.{t['table']}~{t['live_estimate']}" for t in p["tables_to_compare"][:6])
        + (" ..." if len(p["tables_to_compare"]) > 6 else "")
    )
    print(f"  preconditions: {json.dumps(p['preconditions'])} -> would_run={p['would_run']}")
    print(
        f"  steps if run: pre-scan dump; CREATE DATABASE {p['db_name']} TEMPLATE {p['template_db']['name']}; COMMENT marker; guarded restore (psql \\restrict); exact row counts vs dump COPY rows; DROP DATABASE {p['db_name']} (regex + created-by-this-run + marker guard)"
    )


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print the plan only; create nothing, write nothing")
    mode.add_argument("--write", action="store_true", help="run the drill and write the receipt")
    ap.add_argument("--receipt", default=None, help="receipt path (default $STATE_ROOT/" + str(RECEIPT_REL) + ")")
    ap.add_argument(
        "--scan-dump", action="store_true", help="dry-run: also run the dump-guard pre-scan (reads the dump end to end)"
    )
    ap.add_argument(
        "--first-week-only",
        action="store_true",
        help="no-op (exit 0, nothing read or written) unless today is day 1-7 of the month; with a weekly "
        "Sunday schedule this is the first Sunday (cron/n8n cannot say 'first Sunday': 1-7 * 0 ORs the fields)",
    )
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    now = datetime.now()
    if a.first_week_only and not first_week(now):
        print(
            f"restore-drill SKIP: {now.date()} is not in the first week of the month (--first-week-only); nothing done"
        )
        return 0
    try:
        cfg = ol.load_config()["restore_drill"]
        live = ol.db_params()
        drill, src = drill_db_params(cfg, live)
        p = plan(cfg, now=now, live_params=live, drill_params=drill, psql_version=psql_version_text())
        p["credentials"] = src
        if p["dump"] and (a.write and p["would_run"] or a.dry_run and a.scan_dump):
            apply_prescan(p, prescan(Path(p["dump_dir"]) / p["dump"], timeout=int(cfg["prescan_timeout_s"])))
    except DrillRefused as exc:
        print(f"restore-drill REFUSED: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"restore-drill CANNOT RUN: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)
        return 2
    if a.dry_run:
        if a.json:
            print(json.dumps(p, indent=1, default=str))
        else:
            print_plan(p, p.get("credentials"))
        return 0
    run_id = uuid.uuid4().hex[:12]
    result = run_drill(cfg, p, drill, run_id=run_id) if p["would_run"] else None
    findings = findings_for(p, result)
    outcome = "REFUSED" if not p["would_run"] else ("PASS" if not findings else "FAIL")
    receipt = {
        "schema": SCHEMA,
        "authority": "READ_ONLY_ADVISORY",
        "lane": "trade-ai-restore-drill",
        "mode": "write",
        "run_id": run_id,
        "as_of": ol.iso(ol.utc_now()),
        "outcome": outcome,
        "plan": p,
        "result": result,
        "fanin_findings": findings,
        "fanin_wired": False,
    }
    path = Path(a.receipt) if a.receipt else ol.state_root() / RECEIPT_REL
    ol.write_receipt(receipt, path)
    print(
        json.dumps(receipt, indent=1, default=str)
        if a.json
        else f"restore-drill {outcome} run {run_id}; receipt {path}"
    )
    return 0 if outcome == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
