#!/usr/bin/env python3
"""trade_ai_restore_drill.py — monthly proof that the latest trade_ai dump restores (lane trade-ai-restore-drill).

Proposed schedule: first Sunday of the month, 03:30 ET — n8n cron ``30 3 * * 0`` with ``--first-week-only``
(a 5-field cron cannot say "first Sunday": ``30 3 1-7 * 0`` ORs day-of-month with day-of-week and fires
on days 1-7 AND every Sunday). n8n shadow first; the registry row stays NEVER_SCHEDULED until then.
Config: config/ops_lanes.json ``restore_drill``.

``--write`` (the drill):

  1. Find the latest trade_ai dump (same locator as scripts/backup_verify.py).
  2. Name a THROWAWAY database ``restore_drill_<YYYYMMDD>``; the name must fullmatch
     ``db_name_regex`` (``^restore_drill_\\d{8}$``) or the drill refuses.
  3. Disk-floor guard: estimate the restored size as live ``pg_database_size`` minus the schemas whose
     data the dump excludes (``excluded_data_schemas``), then refuse unless the free space on the
     cluster's filesystem is > ``disk_multiplier`` x estimate x (1 + ``disk_headroom_pct``/100).
  4. Refuse unless the drill role has CREATEDB, and refuse if a database of that name already exists
     (a leftover is reported, never dropped: only a database this run created may be dropped).
  5. CREATE DATABASE, mark it with a COMMENT carrying this run's id, restore (plain ``.sql.gz``:
     decompress | psql; custom ``.dump``: pg_restore --no-owner --no-acl), niced, with a timeout.
  6. Compare exact row counts of the ``compare_top_n`` largest live tables (outside the excluded
     schemas) with live ``reltuples`` estimates, within max(``row_tolerance_abs``,
     ``row_tolerance_pct``%).
  7. DROP DATABASE — only that database, only if its name fullmatches the regex, equals the name this
     run created, and its COMMENT carries this run's id. Always attempted after a create, also when a
     later step failed.

``--dry-run`` prints the plan (dump, name, estimate, free space, guard verdicts, tables to compare)
and touches nothing: catalog reads on a read-only session only, no CREATE, no receipt.

Receipt (``--write`` only): ``$TRADEAI_STATE_ROOT/data/runtime/trade_ai_restore_drill_last.json``
(``TradeAiRestoreDrill@v1``). Findings use the incident fan-in shape; nothing sends.
Exit codes: 0 drill passed or plan printed, 1 drill refused or failed (receipt says why), 2 cannot run.

AUTHORITY: READ_ONLY_ADVISORY for live data. The only writes are the throwaway database this run
creates (and then drops) and its own receipt. It never writes, alters or drops anything else.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import ops_lanes as ol  # noqa: E402
from scripts import backup_verify as bv  # noqa: E402

SCHEDULED_ENTRYPOINT = (
    "n8n lane trade-ai-restore-drill (config/lane_registry.json NEVER_SCHEDULED until shadow; proposed "
    "30 3 * * 0 + --first-week-only = first Sunday 03:30; config/n8n_run_allowlist.json entry, --dry-run / --write)"
)
SCHEMA = "TradeAiRestoreDrill@v1"
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
ROLE_SQL = "SELECT rolcreatedb, rolsuper FROM pg_roles WHERE rolname = %s"
DRILL_DBS_SQL = "SELECT datname FROM pg_database WHERE datname LIKE 'restore\\_drill\\_%' ORDER BY 1"
COMMENT_SQL = "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = %s"


class DrillRefused(Exception):
    pass


# ---------------------------------------------------------------------------- guards (pure)
def first_week(day: datetime) -> bool:
    return 1 <= day.day <= 7


def drill_db_name(day: datetime, cfg: dict) -> str:
    name = f"{cfg['db_name_prefix']}{day.strftime('%Y%m%d')}"
    if not re.fullmatch(cfg["db_name_regex"], name):
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


def assert_droppable(name: str, *, created_name: Optional[str], comment: Optional[str], run_id: str, regex: str) -> None:
    """Raise unless ``name`` is the throwaway database THIS run created. Pure; tested."""
    if not isinstance(name, str) or not re.fullmatch(regex, name):
        raise DrillRefused(f"refusing to drop {name!r}: does not match {regex}")
    if created_name is None or name != created_name:
        raise DrillRefused(f"refusing to drop {name!r}: not the database this run created ({created_name!r})")
    if comment != COMMENT_PREFIX + run_id:
        raise DrillRefused(f"refusing to drop {name!r}: marker comment {comment!r} is not this run's")


def compare_counts(rows: list[dict], cfg: dict) -> list[dict]:
    out = []
    for r in rows:
        est, got = int(r["live_estimate"]), r.get("restored_rows")
        tol = max(int(cfg["row_tolerance_abs"]), int(est * float(cfg["row_tolerance_pct"]) / 100.0))
        ok = got is not None and abs(int(got) - est) <= tol
        out.append({**r, "tolerance": tol, "ok": ok})
    return out


# ---------------------------------------------------------------------------- plan (read-only)
def plan(cfg: dict, *, now: datetime, live_params: dict, drill_params: dict, connect=None, env=None) -> dict:
    connect = connect or ol.pg_connect
    bcfg = ol.load_config()["backup_verify"]
    d = bv.dump_dir(bcfg, env)
    dumps = bv.list_dumps(d, bcfg["dump_globs"]) if d.is_dir() else []
    p: dict[str, Any] = {"dump_dir": str(d), "dump": dumps[0].name if dumps else None, "dump_bytes": dumps[0].stat().st_size if dumps else None}
    p["db_name"] = drill_db_name(now, cfg)
    excluded = list(cfg["excluded_data_schemas"])
    conn = connect(live_params)
    try:
        cur = conn.cursor()
        cur.execute(LIVE_SIZE_SQL)
        live_size = int(cur.fetchone()[0])
        cur.execute(EXCLUDED_SIZE_SQL, (excluded,))
        excluded_size = int(cur.fetchone()[0])
        cur.execute(TOP_TABLES_SQL, (excluded, int(cfg["compare_top_n"])))
        tables = [{"schema": r[0], "table": r[1], "bytes": int(r[2]), "live_estimate": int(r[3])} for r in cur.fetchall()]
        cur.execute(ROLE_SQL, (drill_params["user"],))
        role = cur.fetchone()
        cur.execute(DRILL_DBS_SQL)
        existing = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
    p["live_size_bytes"] = live_size
    p["excluded_schemas_bytes"] = excluded_size
    fs = ol.fs_usage(cfg["pg_data_fs_path"])
    p["disk_guard"] = disk_guard(max(live_size - excluded_size, 0), fs["avail_bytes"], cfg)
    p["drill_role"] = {"user": drill_params["user"], "createdb": bool(role and (role[0] or role[1])), "exists": role is not None}
    p["existing_drill_databases"] = existing
    p["tables_to_compare"] = tables
    checks = {
        "dump_present": p["dump"] is not None,
        "name_guard": True,
        "disk_guard": p["disk_guard"]["ok"],
        "role_createdb": p["drill_role"]["createdb"],
        "name_free": p["db_name"] not in existing,
    }
    p["preconditions"] = checks
    p["would_run"] = all(checks.values())
    return p


# ---------------------------------------------------------------------------- the drill
def restore(dump: Path, db_name: str, params: dict, *, timeout: int) -> dict:
    env = {**os.environ, "PGPASSWORD": params["password"] or "", "PGOPTIONS": "-c statement_timeout=0"}
    conn_args = ["-h", str(params["host"]), "-p", str(params["port"]), "-U", params["user"]]
    if dump.name.endswith(".sql.gz"):
        decomp = "pigz" if shutil.which("pigz") else "gzip"
        script = 'set -o pipefail; ' + decomp + ' -dc -- "$1" | psql -X -q -v ON_ERROR_STOP=0 "${@:3}" -d "$2"'
        argv = [*ol.nice_prefix(19), "bash", "-c", script, "restore", str(dump), db_name, *conn_args]
    else:
        argv = [*ol.nice_prefix(19), "pg_restore", "--no-owner", "--no-acl", *conn_args, "-d", db_name, str(dump)]
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errf:
        try:
            cp = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=errf, env=env, timeout=timeout, check=False)
            rc: Optional[int] = cp.returncode
        except subprocess.TimeoutExpired:
            rc = None
        errf.seek(0)
        errors, tail = 0, []
        for line in errf:
            if "ERROR:" in line:
                errors += 1
                if len(tail) < 10:
                    tail.append(line.strip()[:200])
    return {"rc": rc, "timed_out": rc is None, "error_lines": errors, "first_errors": tail}


def count_rows(params: dict, db_name: str, tables: list[dict], *, connect=None) -> list[dict]:
    from psycopg2 import sql

    connect = connect or ol.pg_connect
    conn = connect(params, dbname=db_name, read_only=True, timeout_ms=1800000)
    out = []
    try:
        cur = conn.cursor()
        for t in tables:
            try:
                cur.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(sql.Identifier(t["schema"]), sql.Identifier(t["table"])))
                out.append({**t, "restored_rows": int(cur.fetchone()[0])})
            except Exception as exc:  # noqa: BLE001 — a missing table is a finding
                out.append({**t, "restored_rows": None, "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
    finally:
        conn.close()
    return out


def run_drill(cfg: dict, p: dict, drill_params: dict, *, run_id: str, connect=None, restore_fn=None, count_fn=None) -> dict:
    from psycopg2 import sql

    connect = connect or ol.pg_connect
    restore_fn = restore_fn or restore
    count_fn = count_fn or count_rows
    name = p["db_name"]
    result: dict[str, Any] = {"created": False, "dropped": False}
    created_name: Optional[str] = None
    try:
        admin = connect(drill_params, dbname="postgres", read_only=False)
        try:
            cur = admin.cursor()
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            created_name = name
            result["created"] = True
            cur.execute(sql.SQL("COMMENT ON DATABASE {} IS {}").format(sql.Identifier(name), sql.Literal(COMMENT_PREFIX + run_id)))
        finally:
            admin.close()
        dump = Path(p["dump_dir"]) / p["dump"]
        result["restore"] = restore_fn(dump, name, drill_params, timeout=int(cfg["restore_timeout_s"]))
        result["comparison"] = compare_counts(count_fn(drill_params, name, p["tables_to_compare"]), cfg)
    finally:
        if created_name is not None:
            result["drop"] = drop_throwaway(name, created_name=created_name, run_id=run_id, params=drill_params, regex=cfg["db_name_regex"], connect=connect)
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
            assert_droppable(name, created_name=created_name, comment=row[0] if row else None, run_id=run_id, regex=regex)
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
        sev = "P1" if "dump_present" in failed else "P2"
        out.append(ol.finding(SOURCE, "refused:" + ",".join(failed), sev, f"restore drill refused: {', '.join(failed)}", rel))
        return out
    if result is None:
        return out
    r = result.get("restore") or {}
    if r.get("timed_out") or r.get("rc") not in (0,):
        out.append(ol.finding(SOURCE, "restore:failed", "P1", f"restore rc={r.get('rc')} timed_out={r.get('timed_out')} errors={r.get('error_lines')}", rel))
    elif r.get("error_lines"):
        out.append(ol.finding(SOURCE, "restore:errors", "P2", f"{r['error_lines']} ERROR lines; first: {(r.get('first_errors') or [''])[0]}", rel))
    bad = [c for c in result.get("comparison") or [] if not c["ok"]]
    if bad:
        out.append(ol.finding(SOURCE, "rows:mismatch", "P1", f"{len(bad)} of {len(result.get('comparison') or [])} tables outside tolerance: " + ", ".join(f"{c['schema']}.{c['table']}" for c in bad[:5]), rel))
    if result.get("created") and not result.get("dropped"):
        out.append(ol.finding(SOURCE, "throwaway:left_behind", "P1", f"{p['db_name']} not dropped: {(result.get('drop') or {}).get('error')}", rel))
    return out


def print_plan(p: dict) -> None:
    g = p["disk_guard"]
    gib = 1 << 30
    print("restore-drill PLAN (dry-run; nothing created, nothing written)")
    print(f"  dump: {p['dump_dir']}/{p['dump']} ({(p['dump_bytes'] or 0) // (1 << 20)} MiB)")
    print(f"  throwaway db: {p['db_name']} (regex guard ok); existing restore_drill_* dbs: {p['existing_drill_databases'] or 'none'}")
    print(f"  live trade_ai {p['live_size_bytes'] // gib} GiB, excluded-data schemas {p['excluded_schemas_bytes'] // gib} GiB")
    print(f"  disk guard: estimate {g['estimate_bytes'] // gib} GiB, required free {g['required_free_bytes'] // gib} GiB, avail {g['avail_bytes'] // gib} GiB -> {'OK' if g['ok'] else 'REFUSE'} ({g['rule']})")
    print(f"  drill role {p['drill_role']['user']}: createdb={p['drill_role']['createdb']}")
    print(f"  compare {len(p['tables_to_compare'])} tables: " + ", ".join(f"{t['schema']}.{t['table']}~{t['live_estimate']}" for t in p["tables_to_compare"][:6]) + (" ..." if len(p["tables_to_compare"]) > 6 else ""))
    print(f"  preconditions: {json.dumps(p['preconditions'])} -> would_run={p['would_run']}")
    print(f"  steps if run: CREATE DATABASE {p['db_name']}; COMMENT marker; restore; count rows; DROP DATABASE {p['db_name']} (regex + created-by-this-run + marker guard)")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print the plan only; create nothing, write nothing")
    mode.add_argument("--write", action="store_true", help="run the drill and write the receipt")
    ap.add_argument("--receipt", default=None, help="receipt path (default $STATE_ROOT/" + str(RECEIPT_REL) + ")")
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
        print(f"restore-drill SKIP: {now.date()} is not in the first week of the month (--first-week-only); nothing done")
        return 0
    try:
        cfg = ol.load_config()["restore_drill"]
        live = ol.db_params()
        drill = ol.db_params(user_env=cfg["role_user_env"], password_env=cfg["role_password_env"])
        p = plan(cfg, now=now, live_params=live, drill_params=drill)
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
            print_plan(p)
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
    print(json.dumps(receipt, indent=1, default=str) if a.json else f"restore-drill {outcome} run {run_id}; receipt {path}")
    return 0 if outcome == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
