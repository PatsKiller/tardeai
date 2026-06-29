#!/usr/bin/env python3
"""finviz_screener_efficiency_audit.py — per-screener overlap / yield / cadence audit with a
keep / reduce / merge / disable / promote recommendation. Read-only. No broker writes.

    python3 scripts/finviz_screener_efficiency_audit.py --days 30 --json
    python3 scripts/finviz_screener_efficiency_audit.py --days 30 --markdown > docs/diligence/current/FINVIZ_SCREENER_EFFICIENCY_AUDIT.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
REGISTRY = ROOT / "config" / "finviz_screeners.yaml"

# cadence classes whose decay is SLOW — running them at intraday/fast cadence is wasteful.
SLOW_CLASSES = {"fundamental_daily", "income_weekly", "swing_daily"}
FAST_CLASSES = {"scalp_fast", "scout_intraday"}


def recommend(m: dict) -> str:
    """Pure: keep | reduce_cadence | merge_duplicate | disable_sunset | promote. m carries
    overlap_pct, unique_contribution, conversions_30d (GO/SCOUT/proposal), cadence_class,
    latency_ms, is_duplicate, runs_at_fast_cadence."""
    overlap = float(m.get("overlap_pct") or 0)
    unique = int(m.get("unique_contribution") or 0)
    conv = int(m.get("conversions_30d") or 0)
    cls = m.get("cadence_class") or ""
    latency = float(m.get("latency_ms") or 0)
    # Sunset: high overlap + no unique value, or zero conversions + low unique, or duplicate.
    if m.get("is_duplicate"):
        return "merge_duplicate"
    if overlap >= 70 and unique <= 2:
        return "disable_sunset"
    if conv == 0 and unique <= 2 and cls not in ("scalp_fast",):
        return "disable_sunset"
    # Reduce: slow-decay family running at fast cadence, or high latency / low yield.
    if cls in SLOW_CLASSES and m.get("runs_at_fast_cadence"):
        return "reduce_cadence"
    if latency > 8000 and unique <= 3:
        return "reduce_cadence"
    if 40 <= overlap < 70 and conv == 0:
        return "reduce_cadence"
    # Promote: low overlap, unique candidates, real conversions, fast/time-sensitive, low latency.
    if overlap < 30 and unique >= 5 and conv >= 1 and cls in FAST_CLASSES:
        return "promote"
    return "keep"


def build(days: int = 30) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    reg = yaml.safe_load(REGISTRY.read_text())
    screeners = list(reg.get("screeners", [])) + list(reg.get("db_screeners", []))

    # membership overlap from DB if available
    membership = {}
    warnings = []
    try:
        from db_adapter import get_connection
        conn = get_connection()
        cur = conn.cursor()
        # best-effort: results_count + last_run from finviz_screeners
        cur.execute("SELECT screener_id, results_count, last_run FROM finviz_screeners")
        for sid, rc, lr in cur.fetchall():
            membership[sid] = {"results_count": rc, "last_run": str(lr) if lr else None}
    except Exception as e:
        warnings.append(f"db metrics unavailable: {str(e).splitlines()[0][:80]}")

    rows = []
    for s in screeners:
        sid = s["screener_id"]
        dbm = membership.get(sid, {})
        rc = dbm.get("results_count")
        cls = s.get("cadence_class")
        # Heuristic metrics (real overlap/conversion need the membership+attribution join; flagged
        # needs_data where unavailable). Conservative so we never auto-sunset a scalp screen.
        m = {
            "overlap_pct": None, "unique_contribution": None, "conversions_30d": None,
            "cadence_class": cls, "latency_ms": None, "is_duplicate": False,
            "runs_at_fast_cadence": cls in FAST_CLASSES,
        }
        # large income screens with huge row counts + slow class = reduce candidate
        rec = "keep"
        if rc is not None:
            if cls in SLOW_CLASSES and rc and rc > 2000:
                rec = "reduce_cadence"   # huge slow-family universe; don't run intraday
            elif cls == "scalp_fast":
                rec = "keep"
        rows.append({
            "screener_id": sid, "name": s.get("name"), "strategy_family": s.get("strategy_family"),
            "cadence_class": cls, "active": s.get("active", True),
            "results_count": rc, "last_run": dbm.get("last_run"),
            "overlap_pct": "needs_data", "unique_contribution": "needs_data",
            "conversions_30d": "needs_data", "recommendation": rec,
        })
    return {
        "ok": True, "status": "PASS" if not warnings else "WARN", "generated_at": started,
        "window_days": days, "screener_count": len(rows),
        "by_recommendation": {r: sum(1 for x in rows if x["recommendation"] == r)
                              for r in ("keep", "reduce_cadence", "merge_duplicate", "disable_sunset", "promote")},
        "screeners": rows, "warnings": warnings,
        "note": "Read-only efficiency audit. Overlap/conversion metrics need the membership+attribution "
                "join (flagged needs_data); recommendations are conservative — no scalp screen is auto-sunset. "
                "Discovery only; no broker writes.",
    }


def to_markdown(r: dict) -> str:
    L = ["# Finviz Screener Efficiency Audit", "",
         f"**Status: {r['status']}** | {r['screener_count']} screeners | window {r['window_days']}d  ",
         f"_Generated: {r['generated_at']}_  ", "",
         "## Recommendations", "", "| Action | Count |", "|--------|------:|"]
    for k, v in r["by_recommendation"].items():
        L.append(f"| {k} | {v} |")
    L += ["", "## Per-screener", "",
          "| Screener | Family | Cadence class | Rows | Last run | Overlap | Conv 30d | Recommendation |",
          "|----------|--------|---------------|-----:|----------|---------|---------|----------------|"]
    for s in r["screeners"]:
        L.append(f"| {s['screener_id']} | {s['strategy_family']} | {s['cadence_class']} | "
                 f"{s.get('results_count') if s.get('results_count') is not None else '—'} | "
                 f"{(s.get('last_run') or '—')[:16]} | {s['overlap_pct']} | {s['conversions_30d']} | "
                 f"{s['recommendation']} |")
    L += ["", "> " + r["note"]]
    if r.get("warnings"):
        L += ["", "> WARN: " + "; ".join(r["warnings"])]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    r = build(args.days)
    print(to_markdown(r) if args.markdown else (json.dumps(r, indent=2, default=str) if args.json else
          f"efficiency: {r['status']} screeners={r['screener_count']} recs={r['by_recommendation']}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
