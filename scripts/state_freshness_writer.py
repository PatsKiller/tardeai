#!/usr/bin/env python3
"""State freshness writer for Trade AI agent pipelines.

Purpose:
- Ensure expected state JSON files carry explicit freshness metadata.
- Avoid relying only on filesystem mtimes.
- Preserve existing JSON structure and content.
- Never invent market/risk/news data; only stamps producer metadata after the producer script exits successfully.

Usage:
  python3 scripts/state_freshness_writer.py --file risk_management.json --source portfolio_risk.py
  python3 scripts/state_freshness_writer.py --mode audit --json
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "data" / "portfolios" / "state"

EXPECTED_MAX_AGE_HOURS = {
    "holdings.json": 24,
    "risk_management.json": 24,
    "stops.json": 24,
    "action_signals.json": 24,
    "technical_snapshot.json": 24,
    "portfolio_news.json": 48,
    "analyst_data.json": 48,
    "etf_intelligence.json": 168,
    "mutual_fund_intelligence.json": 168,
    "stock_intelligence.json": 168,
    "asset_intelligence.json": 168,
    "ai_watchlist.json": 168,
    "ai_watchlist_review.json": 168,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"_raw_parse_error": True, "_raw_size_bytes": path.stat().st_size}


def stamp_file(filename: str, source: str, status: str = "ok") -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / filename
    now = utc_now()
    data = load_json(path)

    if isinstance(data, dict):
        data.setdefault("_agent_metadata", {})
        data["_agent_metadata"].update({
            "generated_at": data.get("generated_at") or data.get("as_of") or now,
            "agent_checked_at": now,
            "source_script": source,
            "producer_status": status,
            "freshness_writer_version": "1.0",
        })
        # Also set generated_at when absent so readers have a stable top-level field.
        data.setdefault("generated_at", now)
    else:
        data = {
            "generated_at": now,
            "items": data,
            "_agent_metadata": {
                "agent_checked_at": now,
                "source_script": source,
                "producer_status": status,
                "freshness_writer_version": "1.0",
                "wrapped_original_non_dict": True,
            },
        }

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    os.replace(tmp, path)
    return {"file": str(path), "source": source, "status": status, "agent_checked_at": now}


def best_timestamp(data: Any, path: Path) -> datetime:
    candidates: List[str] = []
    if isinstance(data, dict):
        meta = data.get("_agent_metadata") or {}
        for k in ("agent_checked_at", "generated_at", "updated_at", "as_of", "last_updated"):
            v = meta.get(k) if k in meta else data.get(k)
            if isinstance(v, str) and v:
                candidates.append(v)
    for value in candidates:
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def audit() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    files = []
    issues = []
    for filename, max_age in EXPECTED_MAX_AGE_HOURS.items():
        path = STATE_DIR / filename
        if not path.exists():
            item = {"file": filename, "exists": False, "max_age_hours": max_age, "ok": False}
            files.append(item)
            issues.append(f"MISSING: {filename}")
            continue
        data = load_json(path)
        ts = best_timestamp(data, path)
        age_hours = round((now - ts).total_seconds() / 3600, 2)
        ok = age_hours <= max_age
        item = {"file": filename, "exists": True, "age_hours": age_hours, "max_age_hours": max_age, "ok": ok}
        if isinstance(data, dict) and data.get("_agent_metadata"):
            item["source_script"] = data["_agent_metadata"].get("source_script")
            item["agent_checked_at"] = data["_agent_metadata"].get("agent_checked_at")
        files.append(item)
        if not ok:
            issues.append(f"STALE: {filename} is {age_hours}h old, max {max_age}h")
    return {"checked_at": utc_now(), "freshness_ok": not issues, "issues": issues, "files_checked": files}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="State filename under data/portfolios/state")
    ap.add_argument("--source", default="unknown", help="Producer script name")
    ap.add_argument("--status", default="ok")
    ap.add_argument("--mode", choices=["stamp", "audit"], default="stamp")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.mode == "audit":
        result = audit()
    else:
        if not args.file:
            ap.error("--file is required for stamp mode")
        result = stamp_file(args.file, args.source, args.status)

    print(json.dumps(result, indent=2) if args.json else result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
