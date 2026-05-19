#!/usr/bin/env python3
"""report_screener_arch4_universe_strategy_baseline.py — Universe & strategy-fit baseline.

Read-only. No trades. No orders.
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

SKIP_YAML = {"recommendation_schema.yaml", "strategy_schema.yaml", "shared_risk_rules.yaml"}


def _q(conn, sql, params=None, fetch="all"):
    cur = conn.cursor()
    cur.execute(sql, params or [])
    if fetch == "one":
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else {}
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def _load_strategies():
    strat_dir = PROJ / "config" / "strategies"
    strategies = []
    if not strat_dir.is_dir():
        return strategies
    for yf in sorted(strat_dir.glob("*.yaml")):
        if yf.name in SKIP_YAML:
            continue
        try:
            doc = yaml.safe_load(yf.read_text()) or {}
        except Exception:
            doc = {}
        strategies.append({
            "strategy_id": doc.get("strategy_id", yf.stem),
            "file": yf.name,
            "status": doc.get("status"),
            "timeframe_class": doc.get("timeframe_class"),
            "has_scoring_weights": "scoring_weights" in doc,
            "has_entry_criteria": "entry_criteria" in doc,
            "has_auto_disqualifiers": "auto_disqualifiers" in doc,
        })
    return strategies


def main():
    p = argparse.ArgumentParser(description="ARCH-4 universe & strategy baseline (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB connection"); sys.exit(1)

    # ---- Catalog counts ----
    catalog_total = _q(conn, "SELECT count(*) AS c FROM incubator_universe", fetch="one")
    catalog_active = _q(conn, "SELECT count(*) AS c FROM incubator_universe WHERE status='ACTIVE'", fetch="one")

    # ---- Membership breakdown ----
    mem_by_status = _q(conn,
        "SELECT membership_status, count(*) AS c FROM screener_symbol_membership GROUP BY membership_status ORDER BY c DESC")
    mem_status = {r["membership_status"]: int(r["c"]) for r in mem_by_status}

    # ---- Reentered count ----
    reentered = _q(conn,
        "SELECT count(DISTINCT symbol) AS c FROM screener_symbol_membership_history WHERE event_type='reentered'",
        fetch="one")

    # ---- Scan coverage (last 3 days) ----
    scan_coverage = _q(conn,
        "SELECT count(DISTINCT symbol) AS c FROM trade_ai_scans WHERE scanned_at > NOW() - INTERVAL '3 days'",
        fetch="one")

    # ---- Missing key fields ----
    missing_rvol = _q(conn,
        "SELECT count(DISTINCT symbol) AS c FROM trade_ai_scans WHERE scanned_at > NOW() - INTERVAL '3 days' AND rvol IS NULL",
        fetch="one")
    missing_price = _q(conn,
        "SELECT count(DISTINCT symbol) AS c FROM trade_ai_scans WHERE scanned_at > NOW() - INTERVAL '3 days' AND price IS NULL",
        fetch="one")
    missing_sector = _q(conn,
        "SELECT count(DISTINCT symbol) AS c FROM trade_ai_scans WHERE scanned_at > NOW() - INTERVAL '3 days' AND sector IS NULL",
        fetch="one")
    missing_float = _q(conn,
        "SELECT count(DISTINCT symbol) AS c FROM trade_ai_scans WHERE scanned_at > NOW() - INTERVAL '3 days' AND float_m IS NULL",
        fetch="one")

    conn.close()

    # ---- Strategy inventory ----
    strategies = _load_strategies()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "catalog": {
            "total": int(catalog_total.get("c", 0)),
            "active": int(catalog_active.get("c", 0)),
        },
        "membership": mem_status,
        "reentered_symbols": int(reentered.get("c", 0)),
        "scan_coverage": {
            "symbols_scanned_last_3d": int(scan_coverage.get("c", 0)),
        },
        "missing_data": {
            "rvol_null": int(missing_rvol.get("c", 0)),
            "price_null": int(missing_price.get("c", 0)),
            "sector_null": int(missing_sector.get("c", 0)),
            "float_m_null": int(missing_float.get("c", 0)),
        },
        "strategy_inventory": strategies,
        "strategy_count": len(strategies),
    }

    if args.verbose:
        print("SCREENER-ARCH-4 Universe & Strategy Baseline")
        print(f"  catalog_total:  {report['catalog']['total']}")
        print(f"  catalog_active: {report['catalog']['active']}")
        print(f"  membership:     {report['membership']}")
        print(f"  reentered:      {report['reentered_symbols']}")
        print(f"  scan_coverage:  {report['scan_coverage']['symbols_scanned_last_3d']}")
        print(f"  missing_rvol:   {report['missing_data']['rvol_null']}")
        print(f"  missing_price:  {report['missing_data']['price_null']}")
        print(f"  missing_sector: {report['missing_data']['sector_null']}")
        print(f"  missing_float:  {report['missing_data']['float_m_null']}")
        print(f"  strategies:     {report['strategy_count']}")
        for s in strategies:
            flags = []
            if s["has_scoring_weights"]:
                flags.append("weights")
            if s["has_entry_criteria"]:
                flags.append("entry")
            if s["has_auto_disqualifiers"]:
                flags.append("disqual")
            print(f"    {s['strategy_id']:40s} status={s['status']!s:10s} tf={s['timeframe_class']!s:10s} [{', '.join(flags)}]")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))

    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [
            "# SCREENER-ARCH-4 Universe & Strategy Baseline\n",
            "## Catalog",
            "| Metric | Value |",
            "|--------|-------|",
            f"| total | {report['catalog']['total']} |",
            f"| active | {report['catalog']['active']} |",
            "",
            "## Membership",
            "| Status | Count |",
            "|--------|-------|",
        ]
        for k, v in report["membership"].items():
            md.append(f"| {k} | {v} |")
        md += [
            "",
            f"Reentered symbols: {report['reentered_symbols']}",
            "",
            "## Scan Coverage (last 3 days)",
            "| Metric | Value |",
            "|--------|-------|",
            f"| symbols_scanned | {report['scan_coverage']['symbols_scanned_last_3d']} |",
            f"| rvol_null | {report['missing_data']['rvol_null']} |",
            f"| price_null | {report['missing_data']['price_null']} |",
            f"| sector_null | {report['missing_data']['sector_null']} |",
            f"| float_m_null | {report['missing_data']['float_m_null']} |",
            "",
            "## Strategy Inventory",
            "| strategy_id | status | timeframe | weights | entry | disqual |",
            "|-------------|--------|-----------|---------|-------|---------|",
        ]
        for s in strategies:
            md.append(
                f"| {s['strategy_id']} | {s['status']} | {s['timeframe_class']} "
                f"| {s['has_scoring_weights']} | {s['has_entry_criteria']} | {s['has_auto_disqualifiers']} |"
            )
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
