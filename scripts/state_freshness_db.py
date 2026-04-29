#!/usr/bin/env python3
"""Dual-write state freshness audit results into Postgres.

JSON files remain the fast app state. This table stores historical freshness
checks so the system can trend stale producers, monitor failures, and audit
which script last asserted a state file was fresh.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "data/portfolios/state"


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for raw in env.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k.startswith("DB_"):
            os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(errors="ignore"))
            return data if isinstance(data, dict) else {"_root_type": type(data).__name__}
    except Exception as exc:
        return {"_json_error": str(exc)}
    return {}


def _parse_ts(value: Any) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, str):
        return value
    return None


def _get_conn():
    _load_env()
    try:
        import psycopg2  # type: ignore
        return psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            port=os.environ.get("DB_PORT", "5432"),
            dbname=os.environ.get("DB_NAME", "trade_ai"),
            user=os.environ.get("DB_USER", "trade_ai"),
            password=os.environ.get("DB_PASSWORD", ""),
        )
    except Exception as exc:
        print(f"[state_freshness_db] DB connection failed: {exc}", file=sys.stderr)
        return None


def _ensure_table(conn) -> None:
    sql_path = ROOT / "sql/005_state_freshness_history.sql"
    with conn.cursor() as cur:
        cur.execute(sql_path.read_text())
    conn.commit()


def _normalize_audit(audit: Dict[str, Any]) -> List[Dict[str, Any]]:
    checked_at = audit.get("checked_at") or datetime.now(timezone.utc).isoformat()
    mode = audit.get("mode") or "unknown"
    global_issues = audit.get("issues") or []
    rows: List[Dict[str, Any]] = []
    for item in audit.get("files_checked", []) or []:
        if not isinstance(item, dict):
            continue
        file_name = item.get("file") or item.get("state_file") or "unknown"
        path = STATE_DIR / str(file_name)
        meta = _load_json(path).get("_agent_metadata", {})
        stat = path.stat() if path.exists() else None
        row = {
            "checked_at": checked_at,
            "state_file": str(file_name),
            "exists_flag": bool(item.get("exists", path.exists())),
            "ok": bool(item.get("ok", False)),
            "age_hours": item.get("age_hours"),
            "max_age_hours": item.get("max_age_hours"),
            "source_script": item.get("source_script") or meta.get("source_script"),
            "agent_checked_at": item.get("agent_checked_at") or meta.get("agent_checked_at"),
            "producer_status": meta.get("producer_status") or meta.get("status"),
            "file_mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat() if stat else None,
            "file_size_bytes": stat.st_size if stat else None,
            "mode": mode,
            "issues": [x for x in global_issues if str(file_name) in str(x)],
            "metadata": {"audit_item": item, "agent_metadata": meta},
        }
        rows.append(row)
    return rows


def save_audit(audit: Dict[str, Any]) -> int:
    rows = _normalize_audit(audit)
    if not rows:
        return 0
    conn = _get_conn()
    if conn is None:
        return 0
    try:
        _ensure_table(conn)
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    """
                    INSERT INTO state_freshness_history
                    (checked_at, state_file, exists_flag, ok, age_hours, max_age_hours,
                     source_script, agent_checked_at, producer_status, file_mtime,
                     file_size_bytes, mode, issues, metadata)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
                    """,
                    (
                        r["checked_at"], r["state_file"], r["exists_flag"], r["ok"],
                        r["age_hours"], r["max_age_hours"], r["source_script"],
                        _parse_ts(r["agent_checked_at"]), r["producer_status"],
                        _parse_ts(r["file_mtime"]), r["file_size_bytes"], r["mode"],
                        json.dumps(r["issues"]), json.dumps(r["metadata"]),
                    ),
                )
        conn.commit()
        return len(rows)
    except Exception as exc:
        conn.rollback()
        print(f"[state_freshness_db] insert failed: {exc}", file=sys.stderr)
        return 0
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit-json", help="Path to audit JSON file. If omitted, read stdin.")
    ap.add_argument("--print-count", action="store_true")
    args = ap.parse_args()
    try:
        if args.audit_json:
            audit = json.loads(Path(args.audit_json).read_text())
        else:
            audit = json.load(sys.stdin)
    except Exception as exc:
        print(f"ERROR: failed to load audit JSON: {exc}", file=sys.stderr)
        return 2
    count = save_audit(audit)
    if args.print_count:
        print(json.dumps({"ok": count > 0, "rows_inserted": count}, indent=2))
    return 0 if count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
