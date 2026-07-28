#!/usr/bin/env python3
"""Verbose exportable fire log for momentum-scalp tuning.

Dumps EVERY scalp fire/scan/ignition row for a date range to JSONL + CSV with the
full column set, plus a summary, so the operator can study and tune the engine during
a live period. Read-only; no order path, no mutation of source tables.

Sources:
  - scalp_scan_results   : the LIVE momentum-scalp scanner (runs 6am-noon incl. premarket;
                           score/grade/decision/route/rvol/gap/scout/etc.)
  - scalp_ignition_events: the RTH IGN/trigger shadow logger + setup taxonomy
                           (lane/ign_score/subscores/setup/gate/registry_hash)

Usage:
  python scripts/active_trader/export_scalp_fires.py                     # today (ET)
  python scripts/active_trader/export_scalp_fires.py --start 2026-07-20 --end 2026-07-28
  python scripts/active_trader/export_scalp_fires.py --actionable-only   # scanner: alerted/routed/GO only
  python scripts/active_trader/export_scalp_fires.py --out /path/to/dir

Output (under data/active_trader/fire_exports/<start>_<end>/ by default):
  scalp_scan_results.jsonl / .csv
  scalp_ignition_events.jsonl / .csv
  summary.json           (row counts, distributions by decision/route/grade/lane/setup)
  MANIFEST.txt           (what was exported, when, with what filters)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, date as _date
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db_adapter import get_connection  # noqa: E402

ET = ZoneInfo("America/New_York")
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_OUT_ROOT = os.path.join(REPO, "data", "active_trader", "fire_exports")

# (table, timestamp column, order column)
SOURCES = [
    ("scalp_scan_results", "scanned_at", "scanned_at"),
    ("scalp_ignition_events", None, None),  # ts column resolved below (session_date/fired_at)
]


def _columns(cur, table: str) -> list[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
        (table,))
    return [r[0] for r in cur.fetchall()]


def _json_default(o):
    if isinstance(o, (datetime, _date)):
        return o.isoformat()
    try:
        return float(o)
    except Exception:
        return str(o)


def _resolve_ts_column(cols: list[str]) -> str | None:
    for cand in ("scanned_at", "fired_at", "created_at", "session_date", "as_of"):
        if cand in cols:
            return cand
    return None


def _export_table(cur, table: str, start: str, end: str, out_dir: str, actionable_only: bool) -> dict:
    cols = _columns(cur, table)
    if not cols:
        return {"table": table, "rows": 0, "note": "table not found"}
    ts_col = _resolve_ts_column(cols)
    where = []
    params: list = []
    if ts_col:
        if ts_col == "session_date":
            where.append("session_date BETWEEN %s AND %s")
            params += [start, end]
        else:
            # timestamptz: [start 00:00 ET, end 23:59:59.999 ET]
            where.append(f"{ts_col} >= %s AND {ts_col} <= %s")
            params += [f"{start} 00:00:00-04", f"{end} 23:59:59.999-04"]
    if actionable_only and table == "scalp_scan_results":
        where.append("(alerted = true OR route IS NOT NULL OR decision IN ('GO','ENTER','TAKE'))")
    sql = f"SELECT {', '.join(cols)} FROM {table}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if ts_col:
        sql += f" ORDER BY {ts_col} ASC"
    cur.execute(sql, params)
    rows = cur.fetchall()

    jsonl_path = os.path.join(out_dir, f"{table}.jsonl")
    csv_path = os.path.join(out_dir, f"{table}.csv")
    with open(jsonl_path, "w") as jf, open(csv_path, "w", newline="") as cf:
        writer = csv.writer(cf)
        writer.writerow(cols)
        for r in rows:
            rec = dict(zip(cols, r))
            jf.write(json.dumps(rec, default=_json_default) + "\n")
            writer.writerow(["" if v is None else _json_default(v) if isinstance(v, (datetime, _date)) else v for v in r])
    return {"table": table, "ts_column": ts_col, "rows": len(rows),
            "columns": len(cols), "jsonl": jsonl_path, "csv": csv_path,
            "_rows_data": rows, "_cols": cols}


def _distribution(rows: list, cols: list[str], col: str) -> dict:
    if col not in cols:
        return {}
    idx = cols.index(col)
    dist: dict = {}
    for r in rows:
        k = r[idx]
        k = "∅" if k is None else str(k)
        dist[k] = dist.get(k, 0) + 1
    return dict(sorted(dist.items(), key=lambda kv: -kv[1]))


def main() -> int:
    ap = argparse.ArgumentParser(description="Export scalp fires for tuning.")
    today = datetime.now(ET).date().isoformat()
    ap.add_argument("--start", default=today)
    ap.add_argument("--end", default=today)
    ap.add_argument("--out", default=None, help="output dir (default: data/active_trader/fire_exports/<start>_<end>)")
    ap.add_argument("--actionable-only", action="store_true",
                    help="scanner: only alerted/routed/GO rows")
    args = ap.parse_args()

    out_dir = args.out or os.path.join(DEFAULT_OUT_ROOT, f"{args.start}_{args.end}")
    os.makedirs(out_dir, exist_ok=True)

    conn = get_connection()
    summary: dict = {"start": args.start, "end": args.end,
                     "generated_at_et": datetime.now(ET).isoformat(),
                     "actionable_only": args.actionable_only, "tables": {}}
    with conn.cursor() as cur:
        for table, _ts, _ord in SOURCES:
            res = _export_table(cur, table, args.start, args.end, out_dir, args.actionable_only)
            rows = res.pop("_rows_data", [])
            cols = res.pop("_cols", [])
            if table == "scalp_scan_results":
                res["by_decision"] = _distribution(rows, cols, "decision")
                res["by_route"] = _distribution(rows, cols, "route")
                res["by_grade"] = _distribution(rows, cols, "grade")
            elif table == "scalp_ignition_events":
                res["by_lane"] = _distribution(rows, cols, "lane")
                res["by_primary_setup"] = _distribution(rows, cols, "primary_setup_label")
                res["by_setup_state"] = _distribution(rows, cols, "setup_state")
            summary["tables"][table] = res
            print(f"  {table:24} rows={res['rows']:>6}  ts={res.get('ts_column')}  -> {os.path.basename(res.get('jsonl',''))}")

    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=_json_default)
    with open(os.path.join(out_dir, "MANIFEST.txt"), "w") as f:
        f.write(f"scalp fire export {args.start}..{args.end}\n")
        f.write(f"generated_et {summary['generated_at_et']}\n")
        f.write(f"actionable_only {args.actionable_only}\n")
        for t, r in summary["tables"].items():
            f.write(f"{t}: {r['rows']} rows, {r.get('columns')} cols\n")
    print(f"\nexport dir: {out_dir}")
    print(f"summary   : {os.path.join(out_dir, 'summary.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
