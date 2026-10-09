#!/usr/bin/env python3
"""check_retention_policy.py — the retention registry is a governed surface (CI gate).

    python3 scripts/check_retention_policy.py --fail-on-new

Rules (exit 1 on violation, 2 if the gate cannot run):
  1. config/data_retention_policy.json parses, schema DataRetentionPolicy@v1, every row has
     table, ts_column, class ∈ {DELETE, ARCHIVE_THEN_DELETE, KEEP_FOREVER, EXTERNAL_POLICY}, owner, reason, since.
  2. DELETE / ARCHIVE_THEN_DELETE rows need an integer window_days ≥ 7; ARCHIVE_THEN_DELETE
     rows need archive=true; KEEP_FOREVER rows need window_days null and a reason ≥ 20 chars.
  3. The four tax/brokerage tables are KEEP_FOREVER (a DELETE row on them is the 2026-10-07 defect).
  4. No duplicate table rows. 5. size_budget_gb present and > 0.
  6. Every table db_retention.py would delete from must be in the registry (db_retention reads
     the registry, so this is a self-consistency check on the fallback list if one remains).
Same shape as check_lane_registry.py: declare, gate, let it only shrink.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REG = ROOT / "config" / "data_retention_policy.json"
TAX = {"trade_transactions", "trade_closed", "portfolio_snapshots", "dividend_history"}
CLASSES = {"DELETE", "ARCHIVE_THEN_DELETE", "KEEP_FOREVER", "EXTERNAL_POLICY"}
NO_CONSUMER_REASON = "this IS a CI gate; run_cio_hardening_ci.py invokes it"


def validate(doc: dict) -> list[str]:
    errs: list[str] = []
    if doc.get("schema") != "DataRetentionPolicy@v1":
        errs.append("schema must be DataRetentionPolicy@v1")
    if not isinstance(doc.get("size_budget_gb"), (int, float)) or doc["size_budget_gb"] <= 0:
        errs.append("size_budget_gb missing or <= 0")
    seen = set()
    for r in doc.get("policies") or []:
        t = r.get("table")
        if not t:
            errs.append("row without table"); continue
        if t in seen:
            errs.append(f"{t}: duplicate row")
        seen.add(t)
        for k in ("ts_column", "class", "owner", "reason", "since"):
            if not r.get(k):
                errs.append(f"{t}: missing {k}")
        cls = r.get("class")
        if cls not in CLASSES:
            errs.append(f"{t}: class {cls!r} not in {sorted(CLASSES)}")
        if cls in {"DELETE", "ARCHIVE_THEN_DELETE"}:
            w = r.get("window_days")
            if not isinstance(w, int) or w < 7:
                errs.append(f"{t}: window_days must be an int >= 7 for {cls}")
            if cls == "ARCHIVE_THEN_DELETE" and r.get("archive") is not True:
                errs.append(f"{t}: ARCHIVE_THEN_DELETE requires archive=true")
        if cls == "EXTERNAL_POLICY" and len(str(r.get("reason") or "")) < 20:
            errs.append(f"{t}: EXTERNAL_POLICY must name the job that enforces it (reason >= 20 chars)")
        if cls == "KEEP_FOREVER":
            if r.get("window_days") is not None:
                errs.append(f"{t}: KEEP_FOREVER must have window_days null")
            if len(str(r.get("reason") or "")) < 20:
                errs.append(f"{t}: KEEP_FOREVER needs a reason (>= 20 chars)")
        if t in TAX and cls != "KEEP_FOREVER":
            errs.append(f"{t}: tax/brokerage table must be KEEP_FOREVER, not {cls}")
        if r.get("status"):
            errs.append(f"{t}: unresolved status {r['status']!r}")
        sw = r.get("source_windows")
        if sw is not None:
            # 2026-10-09: per-source windows are enforced (db_retention.enforced_source_windows),
            # always archive-first, and must be shorter than the row's own window to mean anything.
            if not isinstance(sw, dict) or not sw:
                errs.append(f"{t}: source_windows must be a non-empty object")
                sw = {}
            if not r.get("source_column"):
                errs.append(f"{t}: source_windows requires source_column")
            if r.get("source_windows_class") != "ARCHIVE_THEN_DELETE":
                errs.append(f"{t}: source_windows_class must be ARCHIVE_THEN_DELETE")
            for src, days in sw.items():
                if not isinstance(days, int) or isinstance(days, bool) or days < 7:
                    errs.append(f"{t}: source_windows[{src}] must be an int >= 7")
                elif isinstance(r.get("window_days"), int) and days >= r["window_days"]:
                    errs.append(f"{t}: source_windows[{src}] {days} d is not shorter than window_days")
            for k in ("source_windows_batch_rows", "source_windows_max_rows_per_run"):
                v = r.get(k)
                if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v <= 0):
                    errs.append(f"{t}: {k} must be a positive int")
    for t in TAX:
        if t not in seen:
            errs.append(f"{t}: tax/brokerage table must be declared KEEP_FOREVER")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fail-on-new", action="store_true")
    ap.add_argument("--registry", default=str(REG))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        doc = json.loads(Path(a.registry).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"retention-policy gate CANNOT RUN: {e}", file=sys.stderr)
        return 2
    errs = validate(doc)
    rows = doc.get("policies") or []
    summary = {"rows": len(rows), "keep_forever": sum(1 for r in rows if r.get("class") == "KEEP_FOREVER"),
               "archive_then_delete": sum(1 for r in rows if r.get("class") == "ARCHIVE_THEN_DELETE"),
               "delete": sum(1 for r in rows if r.get("class") == "DELETE"), "errors": errs}
    print(json.dumps(summary, indent=1) if a.json else f"retention registry: {summary['rows']} rows "
          f"({summary['keep_forever']} KEEP_FOREVER, {summary['archive_then_delete']} ARCHIVE_THEN_DELETE, {summary['delete']} DELETE); "
          f"errors {len(errs)}")
    for e in errs:
        print(f"    ✗ {e}")
    if errs and a.fail_on_new:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
