#!/usr/bin/env python3
"""storage_watch.py — daily read-only disk and database storage report (lane storage-watch, 06:10 ET).

Reports, from config/ops_lanes.json ``storage_watch`` (thresholds are config, never literals):

  * df for each configured filesystem: total, used, avail, free %, inodes; WARN at
    ``disk_warn_used_pct`` (P2), CRIT at ``disk_crit_used_pct`` (P1), same for inodes;
  * top growers since the last receipt: ``du -x -s`` of a FIXED list of known heavy roots
    (``heavy_roots``), niced (ionice -c3, nice 19), one root at a time with a timeout — never a full
    scan; the snapshot is saved in the receipt and diffed against the previous receipt's;
  * trade_ai database size and the top relations by total size (catalog queries only, read-only
    session, statement timeout);
  * leftover ``m2_shadow_test_*`` databases in the M2 shadow container (``docker exec … psql``,
    one catalog SELECT);
  * Postgres log dir size and the registered git worktree count.

Findings use the incident fan-in shape (scripts/n8n_incident_fanin.py) in ``fanin_findings``;
``fanin_wired`` is false. Nothing sends: no Telegram, no email (AGENTS.md §23.3).

    python3 scripts/storage_watch.py --dry-run     # measure, print the receipt, write nothing
    python3 scripts/storage_watch.py --write       # measure, write the receipt under the state root

Receipt: ``$TRADEAI_STATE_ROOT/data/runtime/storage_watch_last.json`` (``StorageWatchReceipt@v1``).
Exit codes: 0 report written/printed (findings are in the receipt, not the exit code), 2 cannot run.

AUTHORITY: READ_ONLY_ADVISORY. Reads only; the one write is its own receipt.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import ops_lanes as ol  # noqa: E402

SCHEDULED_ENTRYPOINT = (
    "n8n lane storage-watch (config/lane_registry.json NEVER_SCHEDULED until shadow; proposed 10 6 * * *; "
    "config/n8n_run_allowlist.json entry, --dry-run / --write)"
)
SCHEMA = "StorageWatchReceipt@v1"
SOURCE = "storage_watch"
RECEIPT_REL = Path("data") / "runtime" / "storage_watch_last.json"

DB_SIZE_SQL = "SELECT pg_database_size(current_database())"
TOP_RELATIONS_SQL = (
    "SELECT n.nspname, c.relname, c.relkind, pg_total_relation_size(c.oid) AS bytes, c.reltuples::bigint "
    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE c.relkind IN ('r','m','p') AND n.nspname NOT IN ('pg_catalog','information_schema') "
    "AND n.nspname NOT LIKE 'pg_toast%%' ORDER BY 4 DESC LIMIT %s"
)


# ---------------------------------------------------------------------------- measurements
def du_bytes(path: Path, *, timeout: int, nice: int, runner=None) -> dict:
    """``du -x -s -B1`` of one root, niced. Returns {bytes} or {error}."""
    if not path.exists():
        return {"error": "missing"}
    argv = [*ol.nice_prefix(nice), "du", "-x", "-s", "-B1", str(path)]
    try:
        cp = ol.run(argv, timeout=timeout, runner=runner)
    except subprocess.TimeoutExpired:
        return {"error": f"timeout>{timeout}s"}
    except OSError as exc:
        return {"error": f"{type(exc).__name__}"}
    m = re.match(r"^(\d+)\s", cp.stdout or "")
    if not m:
        return {"error": f"rc={cp.returncode}"}
    out: dict[str, Any] = {"bytes": int(m.group(1))}
    if cp.returncode != 0:
        out["partial"] = True  # permission-denied subtrees: the number is a floor
    return out


def growers(current: dict, previous: Optional[dict], top_n: int) -> list[dict]:
    if not previous:
        return []
    rows = []
    for root, now in current.items():
        before = previous.get(root) or {}
        if "bytes" not in now or "bytes" not in before:
            continue
        rows.append({"root": root, "bytes_before": before["bytes"], "bytes_now": now["bytes"], "delta_bytes": now["bytes"] - before["bytes"]})
    rows.sort(key=lambda r: r["delta_bytes"], reverse=True)
    return rows[:top_n]


def db_report(params: dict, top_n: int, *, connect=None) -> dict:
    connect = connect or ol.pg_connect
    conn = connect(params)
    try:
        cur = conn.cursor()
        cur.execute(DB_SIZE_SQL)
        size = int(cur.fetchone()[0])
        cur.execute(TOP_RELATIONS_SQL, (int(top_n),))
        rels = [
            {"schema": r[0], "relation": r[1], "kind": r[2], "bytes": int(r[3]), "est_rows": int(r[4] or 0)}
            for r in cur.fetchall()
        ]
    finally:
        conn.close()
    return {"database": params["dbname"], "size_bytes": size, "top_relations": rels}


def m2_test_dbs(container: str, user: str, regex: str, *, runner=None) -> dict:
    sql = "SELECT datname FROM pg_database WHERE datname ~ '" + regex.replace("'", "''") + "' ORDER BY 1"
    argv = ["docker", "exec", "-e", "PGOPTIONS=-c default_transaction_read_only=on", container, "psql", "-U", user, "-d", "postgres", "-XAt", "-v", "ON_ERROR_STOP=1", "-c", sql]
    try:
        cp = ol.run(argv, timeout=30, runner=runner)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"error": type(exc).__name__}
    if cp.returncode != 0:
        return {"error": f"rc={cp.returncode}: {(cp.stderr or '').strip()[:120]}"}
    names = [ln.strip() for ln in (cp.stdout or "").splitlines() if ln.strip()]
    return {"container": container, "count": len(names), "sample": names[:5]}


def worktree_count(repo: Path, *, runner=None) -> dict:
    try:
        cp = ol.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"], timeout=60, runner=runner)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"error": type(exc).__name__}
    if cp.returncode != 0:
        return {"error": f"rc={cp.returncode}"}
    n = sum(1 for ln in (cp.stdout or "").splitlines() if ln.startswith("worktree "))
    return {"repo": str(repo), "registered": n, "excluding_main": max(n - 1, 0)}


# ---------------------------------------------------------------------------- evaluation
def evaluate(report: dict, cfg: dict) -> list[dict]:
    rel = str(RECEIPT_REL)
    out: list[dict] = []
    for fs in report.get("filesystems", []):
        if "error" in fs:
            out.append(ol.finding(SOURCE, f"df:{fs.get('path')}", "P2", f"cannot stat: {fs['error']}", rel))
            continue
        for kind, pct_key, warn_key, crit_key in (
            ("disk", "used_pct", "disk_warn_used_pct", "disk_crit_used_pct"),
            ("inodes", "inodes_used_pct", "inode_warn_used_pct", "inode_crit_used_pct"),
        ):
            pct = fs[pct_key]
            if pct >= cfg[crit_key]:
                sev, level = "P1", "CRIT"
            elif pct >= cfg[warn_key]:
                sev, level = "P2", "WARN"
            else:
                continue
            out.append(
                ol.finding(
                    SOURCE,
                    f"{kind}:{fs['path']}:{level}",
                    sev,
                    f"{kind} {pct}% used on {fs['path']} (warn {cfg[warn_key]}%, crit {cfg[crit_key]}%); "
                    f"avail {fs['avail_bytes'] // (1 << 30)} GiB",
                    rel,
                )
            )
    pg_log = report.get("pg_log_dir") or {}
    if pg_log.get("bytes", 0) >= cfg["pg_log_warn_bytes"]:
        out.append(ol.finding(SOURCE, "pg_log_dir:large", "P3", f"Postgres log dir {pg_log['bytes'] // (1 << 20)} MiB", rel))
    m2 = report.get("m2_test_databases") or {}
    if "error" in m2:
        out.append(ol.finding(SOURCE, "m2_test_databases:unreadable", "P3", str(m2["error"]), rel))
    elif m2.get("count", 0) >= cfg["m2_test_db_warn_count"]:
        out.append(ol.finding(SOURCE, "m2_test_databases:leaked", "P3", f"{m2['count']} leftover m2_shadow_test_* databases", rel))
    wt = report.get("worktrees") or {}
    if wt.get("excluding_main", 0) >= cfg["worktree_warn_count"]:
        out.append(ol.finding(SOURCE, "worktrees:count", "P3", f"{wt['excluding_main']} registered worktrees", rel))
    db = report.get("database") or {}
    if "error" in db:
        out.append(ol.finding(SOURCE, "trade_ai:unreadable", "P2", str(db["error"]), rel))
    for g in report.get("growers", []):
        days = max(report.get("since_previous_hours") or 24, 1) / 24.0
        if g["delta_bytes"] / days >= cfg["grower_warn_bytes_per_day"]:
            out.append(
                ol.finding(SOURCE, f"grower:{g['root']}", "P3", f"{g['root']} grew {g['delta_bytes'] // (1 << 20)} MiB since the last receipt", rel)
            )
    return out


def measure(cfg: dict, previous: Optional[dict], *, runner=None, connect=None, env=None) -> dict:
    now = ol.utc_now()
    report: dict[str, Any] = {"filesystems": []}
    for path in cfg["filesystems"]:
        try:
            report["filesystems"].append(ol.fs_usage(path))
        except OSError as exc:
            report["filesystems"].append({"path": path, "error": type(exc).__name__})

    snapshot: dict[str, dict] = {}
    for raw in cfg["heavy_roots"]:
        snapshot[raw] = du_bytes(ol.expand(raw, env), timeout=int(cfg["du_timeout_s"]), nice=int(cfg["du_nice"]), runner=runner)
    report["du_snapshot"] = snapshot
    prev_snapshot = (previous or {}).get("du_snapshot") if previous else None
    report["previous_as_of"] = (previous or {}).get("as_of")
    if previous and previous.get("as_of"):
        try:
            prev_dt = datetime.fromisoformat(previous["as_of"])
            report["since_previous_hours"] = round((now - prev_dt).total_seconds() / 3600, 2)
        except ValueError:
            report["since_previous_hours"] = None
    report["growers"] = growers(snapshot, prev_snapshot, int(cfg["growers_top_n"]))

    try:
        report["database"] = db_report(ol.db_params(env), int(cfg["relations_top_n"]), connect=connect)
    except Exception as exc:  # noqa: BLE001 — unreadable is a finding, not a crash
        report["database"] = {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    report["m2_test_databases"] = m2_test_dbs(cfg["m2_container"], cfg["m2_container_user"], cfg["m2_test_db_regex"], runner=runner)
    report["pg_log_dir"] = du_bytes(Path(cfg["pg_log_dir"]), timeout=60, nice=int(cfg["du_nice"]), runner=runner)
    report["worktrees"] = worktree_count(ol.expand(cfg["worktree_main_repo"], env, cfg.get("worktree_main_repo_env")), runner=runner)
    report["as_of"] = ol.iso(now)
    return report


def build_receipt(report: dict, cfg: dict, *, mode: str) -> dict:
    findings = evaluate(report, cfg)
    worst = "P1" if any(f["severity"] == "P1" for f in findings) else ("P2" if any(f["severity"] == "P2" for f in findings) else None)
    return {
        "schema": SCHEMA,
        "authority": "READ_ONLY_ADVISORY",
        "lane": "storage-watch",
        "mode": mode,
        "as_of": report["as_of"],
        "thresholds": {k: cfg[k] for k in ("disk_warn_used_pct", "disk_crit_used_pct", "inode_warn_used_pct", "inode_crit_used_pct")},
        "verdict": {"P1": "CRIT", "P2": "WARN", None: "OK"}[worst],
        **{k: v for k, v in report.items() if k != "as_of"},
        "fanin_findings": findings,
        "fanin_wired": False,
    }


def summary(receipt: dict) -> str:
    lines = [f"storage-watch {receipt['verdict']} as_of {receipt['as_of']} mode {receipt['mode']}"]
    for fs in receipt.get("filesystems", []):
        if "error" not in fs:
            lines.append(
                f"  df {fs['path']}: {fs['used_pct']}% used, {fs['avail_bytes'] // (1 << 30)} GiB free, inodes {fs['inodes_used_pct']}%"
            )
    db = receipt.get("database") or {}
    if "size_bytes" in db:
        top = ", ".join(f"{r['schema']}.{r['relation']}={r['bytes'] // (1 << 20)}M" for r in db["top_relations"][:3])
        lines.append(f"  trade_ai {db['size_bytes'] // (1 << 20)} MiB; top: {top}")
    m2 = receipt.get("m2_test_databases") or {}
    lines.append(f"  m2 test dbs: {m2.get('count', m2.get('error'))}; pg log dir: {(receipt.get('pg_log_dir') or {}).get('bytes')} B; worktrees: {(receipt.get('worktrees') or {}).get('excluding_main')}")
    lines.append(f"  growers: {len(receipt.get('growers') or [])} (previous receipt {receipt.get('previous_as_of')})")
    for f in receipt["fanin_findings"]:
        lines.append(f"  [{f['severity']}] {f['item']}: {f['detail']}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="measure and print; write nothing")
    mode.add_argument("--write", action="store_true", help="measure and write the receipt under the state root")
    ap.add_argument("--config", default=None)
    ap.add_argument("--receipt", default=None, help="receipt path (default $STATE_ROOT/" + str(RECEIPT_REL) + ")")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        cfg = ol.load_config(Path(a.config) if a.config else None)["storage_watch"]
    except Exception as exc:  # noqa: BLE001
        print(f"storage-watch CANNOT RUN: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    path = Path(a.receipt) if a.receipt else ol.state_root() / RECEIPT_REL
    previous = ol.read_json(path)
    report = measure(cfg, previous)
    receipt = build_receipt(report, cfg, mode="write" if a.write else "dry_run")
    if a.write:
        ol.write_receipt(receipt, path)
        receipt["receipt_path"] = str(path)
    print(json.dumps(receipt, indent=1, default=str) if a.json else summary(receipt))
    if not a.write:
        print("  (dry-run: nothing written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
