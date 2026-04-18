#!/usr/bin/env python3
# phase2_coverage_audit.py
# Audits ticker_snapshot_latest.json and reports which fields are populated
# vs missing per symbol. Produces a JSON report for review.
# Run after enrichment to see coverage gaps.

from __future__ import annotations
import argparse, json
from pathlib import Path

FIELD_GROUPS = {
    "quote":          ["price", "change_pct", "prev_close", "volume", "rvol"],
    "performance":    ["perf_week", "perf_month", "perf_quarter",
                       "perf_halfyr", "perf_ytd", "perf_year"],
    "technicals":     ["atr", "rsi", "sma20", "sma50", "sma200", "beta",
                       "tech_score", "tech_grade", "macd_signal"],
    "analyst":        ["analyst", "target"],
    "fundamentals":   ["marketCap", "trailingPE", "dividendYield", "beta"],
    "classification": ["sector", "industry"],
}


def _has_value(val) -> bool:
    if val is None:
        return False
    if isinstance(val, str) and val.strip() in ("", "-", "N/A", "None"):
        return False
    if isinstance(val, float) and val == 0.0:
        return False
    return True


def _check_group(rec: dict, fields: list) -> bool:
    """Return True if any of the fields exist with a real value."""
    all_spaces = [
        rec.get("quote", {}),
        rec.get("performance", {}),
        rec.get("technicals", {}),
        rec.get("analyst", {}),
        rec.get("fundamentals", {}),
        rec.get("classification", {}),
        rec.get("resolved", {}),
    ]
    for f in fields:
        for space in all_spaces:
            if not isinstance(space, dict):
                continue
            for key, val in space.items():
                if f.lower() in str(key).lower() and _has_value(val):
                    return True
    return False


def main():
    ap = argparse.ArgumentParser(description="Phase 2 field coverage audit")
    ap.add_argument("--project-root", required=True)
    args = ap.parse_args()
    project_root = Path(args.project_root)
    state_dir = project_root / "data" / "portfolios" / "state"
    log_dir = project_root / "logs" / "phase2"
    log_dir.mkdir(parents=True, exist_ok=True)

    snap_path = state_dir / "ticker_snapshot_latest.json"
    if not snap_path.exists():
        print(f"ERROR: {snap_path} not found")
        return

    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    tickers = snap.get("tickers", {})

    rows = []
    summary = {k: 0 for k in FIELD_GROUPS}
    missing_by_group = {k: [] for k in FIELD_GROUPS}

    for sym, rec in tickers.items():
        row = {"symbol": sym}
        for group, fields in FIELD_GROUPS.items():
            has = _check_group(rec, fields)
            row[group] = has
            if has:
                summary[group] += 1
            else:
                missing_by_group[group].append(sym)
        rows.append(row)

    total = len(rows)
    pct_summary = {
        k: {"count": v, "pct": round(v / total * 100, 1) if total else 0}
        for k, v in summary.items()
    }

    out = {
        "symbol_count":     total,
        "summary":          pct_summary,
        "missing_by_group": missing_by_group,
        "rows":             rows,
    }

    out_path = log_dir / "phase2_field_coverage_audit.json"
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")

    print(f"[phase2_audit] {total} symbols audited")
    print(f"[phase2_audit] Coverage:")
    for group, data in pct_summary.items():
        bar = "█" * int(data["pct"] / 5)
        print(f"  {group:16s}: {data['pct']:5.1f}%  {bar}")
    print(f"[phase2_audit] Report: {out_path}")


if __name__ == "__main__":
    main()
