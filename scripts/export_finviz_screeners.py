#!/usr/bin/env python3
"""export_finviz_screeners.py — export the live finviz_screeners DB table as registry-shaped entries.

Read-only. Used to (a) seed/refresh config/finviz_screeners.yaml and (b) let
validate_finviz_screener_registry.py diff the DB against the checked-in registry. No broker writes.

    python3 scripts/export_finviz_screeners.py --json
    python3 scripts/export_finviz_screeners.py --yaml      # registry-shaped YAML for the DB screeners
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# strategy_type (DB) → (cadence_class, time_sensitivity). Conservative defaults: nothing here is a
# scalp_fast screen (the DB has NO momentum_scalp screen — that is why the broad --run was wrong for
# the 5-min lane). Income/fundamental → weekly/daily; swing → swing/scout; speculative → scout_intraday.
FAMILY_MAP = {
    "swing_trade": ("swing_intraday", "swing_intraday"),
    "swing_breakout": ("swing_daily", "swing_daily"),
    "fib_retracement_bounce": ("swing_intraday", "swing_intraday"),
    "sector_rotation": ("swing_daily", "swing_daily"),
    "recovery_watch": ("scout_intraday", "scout_intraday"),
    "speculative_growth": ("scout_intraday", "scout_intraday"),
    "defense_thesis": ("swing_daily", "swing_daily"),
    "core_growth_compounder": ("fundamental_daily", "fundamental_daily"),
    "core_index": ("fundamental_daily", "fundamental_daily"),
    "dividend_growth_compounder": ("fundamental_daily", "fundamental_daily"),
    "income_add": ("income_weekly", "income_weekly"),
    "bond_income": ("income_weekly", "income_weekly"),
    "covered_call_income": ("income_weekly", "income_weekly"),
    "high_yield_income_bdc": ("income_weekly", "income_weekly"),
    "international_dividend": ("income_weekly", "income_weekly"),
    "reit_income": ("income_weekly", "income_weekly"),
}


def _classify(strategy_type: str):
    return FAMILY_MAP.get((strategy_type or "").strip(), ("fundamental_daily", "needs_review"))


def export_db() -> list:
    from db_adapter import get_connection
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""SELECT screener_id, display_name, strategy_type, finviz_url, description,
                          active, last_run, results_count
                   FROM finviz_screeners ORDER BY strategy_type, screener_id""")
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        cadence_class, time_sens = _classify(d["strategy_type"])
        out.append({
            "screener_id": d["screener_id"],
            "preset_id": None,
            "name": d["display_name"],
            "strategy_family": d["strategy_type"],
            "time_sensitivity": time_sens,
            "cadence_class": cadence_class,
            "active": bool(d["active"]),
            "url": d["finviz_url"],
            "primary_use": (d["description"] or "")[:200] or None,
            "last_run": str(d["last_run"]) if d["last_run"] else None,
            "results_count": d["results_count"],
            "go_eligible_by_itself": False,
            "classification_status": "needs_review",
            "source": "db",
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--yaml", action="store_true")
    args = ap.parse_args()
    try:
        rows = export_db()
    except Exception as e:
        print(json.dumps({"ok": False, "warning": f"db unavailable: {str(e).splitlines()[0][:100]}"}))
        return 0
    if args.yaml:
        import yaml
        print(yaml.safe_dump({"db_screeners": rows}, sort_keys=False, default_flow_style=False))
    else:
        print(json.dumps({"ok": True, "count": len(rows),
                          "active": sum(1 for r in rows if r["active"]), "screeners": rows},
                         indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
