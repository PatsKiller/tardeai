#!/usr/bin/env python3
"""backup_verify.py — Verify backup integrity.

Two entry points share the dump locator (config/ops_lanes.json ``backup_verify``):

* **Lane ``backup-verify``** (daily 06:40 ET, n8n shadow first) — ``--dry-run`` prints, ``--write``
  writes ``$TRADEAI_STATE_ROOT/data/runtime/backup_verify_last.json`` (``BackupVerifyReceipt@v1``).
  Neither mode sends. Checks:
    1. latest trade_ai dump in ``dump_dir`` (default ``~/db_backups``, env ``TRADEAI_DB_BACKUP_DIR``):
       age < ``max_age_hours``; size within ±``size_tolerance_pct`` of the median of the last
       ``size_median_days`` days (history from ``backup.log`` plus previous receipts);
       readable end to end with a table count >= ``table_count_floor``. A custom-format ``.dump`` is
       read with ``pg_restore --list``; the plain ``.sql.gz`` that run_pg_backup.sh writes cannot be,
       so it is streamed through ``pigz/gzip -dc`` (CRC verified) and its ``CREATE TABLE`` / ``COPY``
       statements and the ``-- PostgreSQL database dump complete`` trailer are counted.
    2. latest n8n lab dump (receipt ``backups/n8n/n8n_lab_backup_last.json`` under the state root):
       ok, fresh, file present with the recorded size, ``pg_restore --list`` table-data count >= the
       live table count it recorded.
    3. weekly Drive family receipts (the three stamps the portfolio backup cadence touches on success).
  A missing or failed dump is a P1 finding (incident fan-in shape, ``fanin_wired`` false).

* **Legacy monthly step** (platform-maintenance-monthly; no flag) — the original report plus its
  alert dispatch, now looking in the configured dump dir instead of ``<code root>/backups/db``
  (which never existed, so the step reported FAIL every month from release and dev tree alike).

Usage:
    .venv/bin/python scripts/backup_verify.py --dry-run     # lane: measure + print, write nothing
    .venv/bin/python scripts/backup_verify.py --write       # lane: measure + write the receipt
    .venv/bin/python scripts/backup_verify.py               # legacy monthly report + alert
"""
import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from scripts.lib import ops_lanes as ol  # noqa: E402

SCHEDULED_ENTRYPOINT = (
    "systemd tradeai-platform-maintenance-monthly.timer step backup_verify (legacy, no flag); "
    "n8n lane backup-verify (NEVER_SCHEDULED until shadow; proposed 40 6 * * *; --dry-run / --write)"
)
SCHEMA = "BackupVerifyReceipt@v1"
SOURCE = "backup_verify"
RECEIPT_REL = Path("data") / "runtime" / "backup_verify_last.json"
_TS_RE = re.compile(r"_(\d{8})_(\d{6})\.")
_COMPLETE_RE = re.compile(r"Backup complete: (\S+)")
_TOTAL_RE = re.compile(r'"total_bytes":\s*(\d+)')
_TOC_TABLE_RE = re.compile(r"^\d+; \d+ \d+ TABLE \S+ ")
_TOC_DATA_RE = re.compile(r"^\d+; \d+ \d+ TABLE DATA ")
TRAILER = "-- PostgreSQL database dump complete"


# ============================================================================ dump locator
def dump_dir(cfg: dict, env=None) -> Path:
    return ol.expand(cfg["dump_dir"], env, cfg.get("dump_dir_env"))


def list_dumps(directory: Path, globs) -> list[Path]:
    """Full dumps in the top level of ``directory`` (holds in subdirectories are not candidates), newest first."""
    found: dict[Path, float] = {}
    for pattern in globs:
        for p in directory.glob(pattern):
            if p.is_file() and not p.name.endswith((".partial", ".tmp")):
                found[p] = p.stat().st_mtime
    return sorted(found, key=lambda p: found[p], reverse=True)


def dump_date(path: Path) -> Optional[datetime]:
    m = _TS_RE.search(path.name)
    if not m:
        return None
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")


def size_history_from_log(log_path: Path) -> list[dict]:
    """[{date, bytes, name}] from run_pg_backup.sh's log: a 'Backup complete: <path>' line followed by the
    enforcer's 'total_bytes' (max_count 1, so the total is that one dump)."""
    out: list[dict] = []
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    pending: Optional[str] = None
    for line in text.splitlines():
        m = _COMPLETE_RE.search(line)
        if m:
            pending = m.group(1)
            continue
        if pending:
            t = _TOTAL_RE.search(line)
            if t:
                dt = dump_date(Path(pending))
                if dt:
                    out.append({"date": dt.strftime("%Y-%m-%d"), "bytes": int(t.group(1)), "name": Path(pending).name})
                pending = None
    return out


def merge_history(*sources: list) -> list[dict]:
    by_name: dict[str, dict] = {}
    for src in sources:
        for row in src or []:
            if isinstance(row, dict) and row.get("name") and isinstance(row.get("bytes"), int):
                by_name[row["name"]] = {"date": row["date"], "bytes": row["bytes"], "name": row["name"]}
    return sorted(by_name.values(), key=lambda r: r["name"])


def size_baseline(history: list[dict], *, exclude: str, now: datetime, days: int, min_samples: int) -> Optional[dict]:
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    sample = [r["bytes"] for r in history if r["name"] != exclude and r["date"] >= cutoff]
    if len(sample) < min_samples:
        return {"median_bytes": None, "samples": len(sample)}
    return {"median_bytes": int(statistics.median(sample)), "samples": len(sample)}


# ============================================================================ dump readers
def scan_plain_gz(path: Path, *, timeout: int, runner=None) -> dict:
    """Stream a plain .sql.gz end to end: CRC verified by the decompressor, statements counted."""
    decomp = "pigz" if shutil.which("pigz") else "gzip"
    script = (
        'set -o pipefail; ' + decomp + ' -dc -- "$1" | LC_ALL=C grep -E -o '
        '"^(CREATE TABLE |COPY |-- PostgreSQL database dump complete)" | LC_ALL=C sort | LC_ALL=C uniq -c'
    )
    argv = [*ol.nice_prefix(19), "bash", "-c", script, "scan", str(path)]
    try:
        cp = ol.run(argv, timeout=timeout, runner=runner)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reader": decomp, "error": f"timeout>{timeout}s"}
    counts = {"CREATE TABLE": 0, "COPY": 0, "trailer": 0}
    for line in (cp.stdout or "").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        n, what = int(parts[0]), parts[1].strip()
        if what.startswith("CREATE TABLE"):
            counts["CREATE TABLE"] += n
        elif what.startswith("COPY"):
            counts["COPY"] += n
        elif what.startswith(TRAILER):
            counts["trailer"] += n
    ok = cp.returncode == 0 and counts["trailer"] >= 1
    out = {
        "ok": ok,
        "reader": f"{decomp} -dc | grep",
        "tables": counts["CREATE TABLE"],
        "table_data": counts["COPY"],
        "trailer": counts["trailer"] >= 1,
        "rc": cp.returncode,
    }
    if not ok:
        out["error"] = (cp.stderr or "").strip()[-200:] or ("dump trailer missing (truncated?)" if cp.returncode == 0 else f"rc={cp.returncode}")
    return out


def scan_custom(path: Path, *, timeout: int, runner=None) -> dict:
    argv = [*ol.nice_prefix(19), "pg_restore", "--list", str(path)]
    try:
        cp = ol.run(argv, timeout=timeout, runner=runner)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reader": "pg_restore --list", "error": f"timeout>{timeout}s"}
    lines = (cp.stdout or "").splitlines()
    tables = sum(1 for ln in lines if _TOC_TABLE_RE.match(ln))
    data = sum(1 for ln in lines if _TOC_DATA_RE.match(ln))
    out = {"ok": cp.returncode == 0, "reader": "pg_restore --list", "tables": tables, "table_data": data, "rc": cp.returncode}
    if cp.returncode != 0:
        out["error"] = (cp.stderr or "").strip()[-200:]
    return out


def scan_dump(path: Path, *, timeout: int, runner=None) -> dict:
    if path.name.endswith(".sql.gz"):
        return scan_plain_gz(path, timeout=timeout, runner=runner)
    return scan_custom(path, timeout=timeout, runner=runner)


# ============================================================================ lane checks
def check_trade_ai(cfg: dict, *, now: datetime, previous: Optional[dict], env=None, runner=None) -> tuple[dict, list]:
    rel = str(RECEIPT_REL)
    findings: list[dict] = []
    d = dump_dir(cfg, env)
    section: dict = {"dump_dir": str(d)}
    if not d.is_dir():
        findings.append(ol.finding(SOURCE, "trade_ai:dump_dir_missing", "P1", f"dump dir {d} not found", rel))
        return section, findings
    dumps = list_dumps(d, cfg["dump_globs"])
    history = merge_history(size_history_from_log(d / cfg["backup_log"]), (previous or {}).get("trade_ai", {}).get("size_history"))
    if not dumps:
        findings.append(ol.finding(SOURCE, "trade_ai:no_dump", "P1", f"no trade_ai dump in {d}", rel))
        section["size_history"] = history
        return section, findings
    latest = dumps[0]
    st = latest.stat()
    age_h = round((now.timestamp() - st.st_mtime) / 3600, 2)
    history = merge_history(history, [{"date": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"), "bytes": st.st_size, "name": latest.name}])
    section.update({"latest": latest.name, "bytes": st.st_size, "mtime": ol.iso(datetime.fromtimestamp(st.st_mtime, timezone.utc)), "age_hours": age_h})
    if age_h >= cfg["max_age_hours"]:
        findings.append(ol.finding(SOURCE, "trade_ai:stale", "P1", f"{latest.name} is {age_h} h old (max {cfg['max_age_hours']} h)", rel))
    base = size_baseline(history, exclude=latest.name, now=now, days=int(cfg["size_median_days"]), min_samples=int(cfg["size_median_min_samples"]))
    section["size_baseline"] = base
    if base and base["median_bytes"]:
        dev = round(100.0 * (st.st_size - base["median_bytes"]) / base["median_bytes"], 2)
        section["size_deviation_pct"] = dev
        if abs(dev) > cfg["size_tolerance_pct"]:
            findings.append(ol.finding(SOURCE, "trade_ai:size_out_of_band", "P2", f"{latest.name} {st.st_size} B is {dev}% vs {base['samples']}-sample median", rel))
    else:
        section["size_deviation_pct"] = None
    scan = scan_dump(latest, timeout=int(cfg["scan_timeout_s"]), runner=runner)
    section["scan"] = scan
    if not scan.get("ok"):
        findings.append(ol.finding(SOURCE, "trade_ai:unreadable", "P1", f"{latest.name}: {scan.get('error')}", rel))
    elif scan.get("tables", 0) < cfg["table_count_floor"]:
        findings.append(ol.finding(SOURCE, "trade_ai:table_floor", "P1", f"{latest.name}: {scan['tables']} tables < floor {cfg['table_count_floor']}", rel))
    section["size_history"] = history[-60:]
    return section, findings


def check_n8n(cfg: dict, *, now: datetime, root: Path, runner=None) -> tuple[dict, list]:
    rel = str(RECEIPT_REL)
    findings: list[dict] = []
    receipt_path = root / cfg["n8n_receipt_rel"]
    doc = ol.read_json(receipt_path)
    section: dict = {"receipt": cfg["n8n_receipt_rel"]}
    if not doc:
        findings.append(ol.finding(SOURCE, "n8n_lab:no_receipt", "P1", f"{cfg['n8n_receipt_rel']} missing or unreadable", rel))
        return section, findings
    try:
        as_of = datetime.fromisoformat(str(doc.get("as_of")))
        age_h = round((now - as_of).total_seconds() / 3600, 2)
    except ValueError:
        age_h = None
    dump = Path(str(doc.get("dump") or ""))
    section.update({"as_of": doc.get("as_of"), "age_hours": age_h, "dump": dump.name, "receipt_ok": doc.get("ok") is True})
    if doc.get("ok") is not True:
        findings.append(ol.finding(SOURCE, "n8n_lab:failed", "P1", "n8n lab backup receipt ok != true", rel))
    if age_h is None or age_h >= cfg["n8n_max_age_hours"]:
        findings.append(ol.finding(SOURCE, "n8n_lab:stale", "P1", f"n8n lab dump age {age_h} h (max {cfg['n8n_max_age_hours']} h)", rel))
    if not dump.is_file():
        findings.append(ol.finding(SOURCE, "n8n_lab:dump_missing", "P1", f"{dump.name or '(none)'} not on disk", rel))
        return section, findings
    size = dump.stat().st_size
    section["bytes"] = size
    if doc.get("bytes") is not None and int(doc["bytes"]) != size:
        findings.append(ol.finding(SOURCE, "n8n_lab:size_mismatch", "P1", f"{dump.name}: {size} B on disk vs {doc['bytes']} B in receipt", rel))
    scan = scan_custom(dump, timeout=120, runner=runner)
    section["scan"] = scan
    floor = int(doc.get("live_public_tables") or 1)
    if not scan.get("ok"):
        findings.append(ol.finding(SOURCE, "n8n_lab:unreadable", "P1", f"{dump.name}: {scan.get('error')}", rel))
    elif scan.get("table_data", 0) < floor:
        findings.append(ol.finding(SOURCE, "n8n_lab:table_floor", "P1", f"{dump.name}: {scan['table_data']} table-data entries < {floor}", rel))
    return section, findings


def check_drive_family(cfg: dict, *, now: datetime, root: Path) -> tuple[dict, list]:
    rel = str(RECEIPT_REL)
    findings: list[dict] = []
    rows = []
    for stamp_rel in cfg["drive_family_stamps_rel"]:
        p = root / stamp_rel
        if not p.exists():
            rows.append({"stamp": stamp_rel, "present": False})
            findings.append(ol.finding(SOURCE, f"drive_family:{Path(stamp_rel).stem}:missing", "P1", f"{stamp_rel} missing (weekly Drive backup never succeeded here)", rel))
            continue
        age_d = round((now.timestamp() - p.stat().st_mtime) / 86400, 2)
        rows.append({"stamp": stamp_rel, "present": True, "age_days": age_d})
        if age_d > cfg["drive_family_max_age_days"]:
            findings.append(ol.finding(SOURCE, f"drive_family:{Path(stamp_rel).stem}:stale", "P2", f"{stamp_rel} last success {age_d} d ago (max {cfg['drive_family_max_age_days']} d)", rel))
    return {"stamps": rows}, findings


def build_receipt(cfg: dict, *, mode: str, previous: Optional[dict], env=None, runner=None, now: Optional[datetime] = None, root: Optional[Path] = None) -> dict:
    now = now or ol.utc_now()
    root = root or ol.state_root(env)
    trade_ai, f1 = check_trade_ai(cfg, now=now, previous=previous, env=env, runner=runner)
    n8n, f2 = check_n8n(cfg, now=now, root=root, runner=runner)
    drive, f3 = check_drive_family(cfg, now=now, root=root)
    findings = [*f1, *f2, *f3]
    worst = "FAIL" if any(f["severity"] == "P1" for f in findings) else ("WARN" if findings else "OK")
    return {
        "schema": SCHEMA,
        "authority": "READ_ONLY_ADVISORY",
        "lane": "backup-verify",
        "mode": mode,
        "as_of": ol.iso(now),
        "verdict": worst,
        "thresholds": {k: cfg[k] for k in ("max_age_hours", "size_tolerance_pct", "size_median_days", "table_count_floor", "n8n_max_age_hours", "drive_family_max_age_days")},
        "trade_ai": trade_ai,
        "n8n_lab": n8n,
        "drive_family": drive,
        "fanin_findings": findings,
        "fanin_wired": False,
    }


def lane_summary(r: dict) -> str:
    t = r["trade_ai"]
    s = t.get("scan") or {}
    lines = [
        f"backup-verify {r['verdict']} as_of {r['as_of']} mode {r['mode']}",
        f"  trade_ai: {t.get('latest')} {t.get('bytes')} B age {t.get('age_hours')} h; median {(t.get('size_baseline') or {}).get('median_bytes')} "
        f"({(t.get('size_baseline') or {}).get('samples')} samples) dev {t.get('size_deviation_pct')}%; scan {s.get('reader')} ok={s.get('ok')} "
        f"tables={s.get('tables')} data={s.get('table_data')} trailer={s.get('trailer')}",
        f"  n8n lab: {r['n8n_lab'].get('dump')} age {r['n8n_lab'].get('age_hours')} h; scan ok={(r['n8n_lab'].get('scan') or {}).get('ok')} "
        f"data={(r['n8n_lab'].get('scan') or {}).get('table_data')}",
        "  drive family: " + ", ".join(f"{Path(x['stamp']).stem}={x.get('age_days', 'MISSING')}d" for x in r["drive_family"]["stamps"]),
    ]
    for f in r["fanin_findings"]:
        lines.append(f"  [{f['severity']}] {f['item']}: {f['detail']}")
    return "\n".join(lines)


# ============================================================================ legacy monthly report
def verify_db_backup():
    """Check that a recent pg_dump backup exists (legacy monthly shape)."""
    findings = []
    try:
        cfg = ol.load_config()["backup_verify"]
    except Exception as e:  # noqa: BLE001
        return [{"check": "backup_config", "status": "FAIL", "detail": f"config/ops_lanes.json: {e}"}]
    backup_dir = dump_dir(cfg)
    if not backup_dir.exists():
        findings.append({"check": "backup_dir", "status": "FAIL", "detail": f"Backup directory not found: {backup_dir}"})
        return findings
    backups = [f for f in list_dumps(backup_dir, cfg["dump_globs"]) if f.stat().st_size > 1000]
    if not backups:
        findings.append({"check": "backup_exists", "status": "FAIL", "detail": "No trade_ai dump files found"})
        return findings

    latest = backups[0]
    age_days = (datetime.now() - datetime.fromtimestamp(latest.stat().st_mtime)).days
    size_mb = latest.stat().st_size / (1024 * 1024)

    findings.append({
        "check": "backup_exists",
        "status": "OK" if age_days <= 7 else "WARN",
        "detail": f"Latest: {latest.name}, {size_mb:.1f} MB, {age_days} days old"
    })

    if age_days > 7:
        findings.append({"check": "backup_age", "status": "WARN", "detail": f"Backup is {age_days} days old (>7 day threshold)"})

    if size_mb < 1:
        findings.append({"check": "backup_size", "status": "WARN", "detail": f"Backup is only {size_mb:.1f} MB — may be truncated"})

    return findings


def verify_state_files():
    """Check that key state files exist and are fresh."""
    state_dir = PROJECT_ROOT / "data" / "portfolios" / "state"
    critical_files = [
        "holdings.json",
        "risk_management.json",
        "technical_snapshot.json",
        "dividend_calendar.json",
        "_freshness.json",
    ]

    findings = []
    for fname in critical_files:
        fpath = state_dir / fname
        if not fpath.exists():
            findings.append({"check": f"state_{fname}", "status": "FAIL", "detail": f"Missing: {fname}"})
            continue
        age_hours = (datetime.now() - datetime.fromtimestamp(fpath.stat().st_mtime)).total_seconds() / 3600
        size_kb = fpath.stat().st_size / 1024
        status = "OK" if age_hours < 24 else ("WARN" if age_hours < 72 else "FAIL")
        findings.append({
            "check": f"state_{fname}",
            "status": status,
            "detail": f"{fname}: {size_kb:.0f} KB, {age_hours:.0f}h old"
        })

    return findings


def verify_db_connectivity():
    """Check database is accessible and has expected tables."""
    findings = []
    try:
        conn = ol.pg_connect(ol.db_params(), timeout_ms=60000)
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'")
        table_count = cur.fetchone()[0]
        findings.append({"check": "db_tables", "status": "OK", "detail": f"{table_count} tables"})

        # Check key tables have data
        for table, min_rows in [("trade_ai_scans", 10), ("paper_trade_proposals", 1), ("notification_log", 1)]:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            rows = cur.fetchone()[0]
            status = "OK" if rows >= min_rows else "WARN"
            findings.append({"check": f"db_{table}", "status": status, "detail": f"{rows} rows"})

        conn.close()
    except Exception as e:
        findings.append({"check": "db_connect", "status": "FAIL", "detail": str(e)})

    return findings


def legacy_main() -> None:
    print(f"[backup_verify] Starting — {datetime.now().isoformat()}")

    all_findings = []
    all_findings.extend(verify_db_backup())
    all_findings.extend(verify_state_files())
    all_findings.extend(verify_db_connectivity())

    ok = sum(1 for f in all_findings if f["status"] == "OK")
    warn = sum(1 for f in all_findings if f["status"] == "WARN")
    fail = sum(1 for f in all_findings if f["status"] == "FAIL")

    print(f"  Results: {ok} OK, {warn} WARN, {fail} FAIL")
    for f in all_findings:
        icon = {"OK": "+", "WARN": "!", "FAIL": "X"}[f["status"]]
        print(f"  [{icon}] {f['check']}: {f['detail']}")

    # Alert summary (legacy monthly step only; the backup-verify lane never sends)
    try:
        from alert_dispatcher import dispatch_alert
        severity = "URGENT" if fail > 0 else ("ALERT" if warn > 0 else "INFO")
        body_lines = ["*Backup Verification Report*", f"OK: {ok} | WARN: {warn} | FAIL: {fail}", ""]
        for f in all_findings:
            icon = {"OK": "OK", "WARN": "!!", "FAIL": "XX"}[f["status"]]
            body_lines.append(f"[{icon}] {f['check']}: {f['detail']}")
        dispatch_alert(
            alert_type="backup_verification",
            title=f"Backup Verify: {ok} OK, {warn} WARN, {fail} FAIL",
            body="\n".join(body_lines),
            tier=severity,
            source="backup_verify",
            dedupe_scope="global",
        )
    except Exception as e:
        print(f"  Alert dispatch failed: {e}")

    print(f"[backup_verify] Complete — {datetime.now().isoformat()}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Backup Verification")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="lane: measure and print; write nothing, send nothing")
    mode.add_argument("--write", action="store_true", help="lane: measure and write the receipt; send nothing")
    parser.add_argument("--receipt", default=None, help="receipt path (default $STATE_ROOT/" + str(RECEIPT_REL) + ")")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not (args.dry_run or args.write):
        legacy_main()
        return 0

    try:
        cfg = ol.load_config()["backup_verify"]
    except Exception as exc:  # noqa: BLE001
        print(f"backup-verify CANNOT RUN: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    path = Path(args.receipt) if args.receipt else ol.state_root() / RECEIPT_REL
    receipt = build_receipt(cfg, mode="write" if args.write else "dry_run", previous=ol.read_json(path), env=os.environ)
    if args.write:
        ol.write_receipt(receipt, path)
        receipt["receipt_path"] = str(path)
    print(json.dumps(receipt, indent=1, default=str) if args.json else lane_summary(receipt))
    if not args.write:
        print("  (dry-run: nothing written, nothing sent)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
