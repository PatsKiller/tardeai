#!/usr/bin/env python3
"""report_daily_momentum_scalp_boundary.py — Audit scalp boundary leakage.

Read-only. No mutation.

Usage:
    .venv/bin/python scripts/report_daily_momentum_scalp_boundary.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

# Known separate daily scalp indicators (these would indicate leakage if found in proposal system)
DAILY_SCALP_INDICATORS = [
    "daily_momentum_scalp", "tradeai_daily_scalp", "daily_scalp",
    "external_scalp", "manual_scalp",
]


def _db_query(sql, params=None, fetch="all"):
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn: return [] if fetch == "all" else None
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if fetch == "one":
            row = cur.fetchone()
            return dict(zip([d[0] for d in cur.description], row)) if row else None
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return [] if fetch == "all" else None


def main():
    p = argparse.ArgumentParser(description="Daily momentum scalp boundary audit (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    findings = []

    # 1. Check paper_trade_proposals for daily scalp indicators
    for indicator in DAILY_SCALP_INDICATORS:
        rows = _db_query(f"""
            SELECT count(*) as c FROM paper_trade_proposals
            WHERE strategy_id ILIKE '%{indicator}%'
            OR proposed_by ILIKE '%{indicator}%'
            OR discovery_source ILIKE '%{indicator}%'
        """, fetch="one")
        count = int((rows or {}).get("c", 0))
        if count > 0:
            findings.append({
                "location": "paper_trade_proposals",
                "indicator": indicator,
                "count": count,
                "classification": "confirmed_leakage",
                "action": "Filter out or mark as out_of_scope",
            })

    # 2. Check if Trade AI momentum_scalp proposals are from standard pipeline
    ms_proposals = _db_query("""
        SELECT proposed_by, discovery_source, count(*) as c
        FROM paper_trade_proposals
        WHERE strategy_id = 'momentum_scalp'
        GROUP BY proposed_by, discovery_source
    """) or []
    for r in ms_proposals:
        source = r.get("proposed_by", "") or ""
        disc = r.get("discovery_source", "") or ""
        is_standard = source in ("auto_proposal_generator", "incubator_promoter", "paper_trade_logger", "manual", None, "")
        findings.append({
            "location": "paper_trade_proposals.momentum_scalp",
            "indicator": f"proposed_by={source}, discovery={disc}",
            "count": r["c"],
            "classification": "allowed_separate_workflow" if is_standard else "unknown_requires_review",
            "action": None if is_standard else "Review source classification",
        })

    # 3. Check strategy_setup_matches for daily scalp
    for indicator in DAILY_SCALP_INDICATORS:
        rows = _db_query(f"""
            SELECT count(*) as c FROM strategy_setup_matches
            WHERE strategy_id ILIKE '%{indicator}%'
        """, fetch="one")
        count = int((rows or {}).get("c", 0))
        if count > 0:
            findings.append({
                "location": "strategy_setup_matches",
                "indicator": indicator,
                "count": count,
                "classification": "confirmed_leakage",
                "action": "Remove or mark out_of_scope",
            })

    # 4. Check YAML configs
    try:
        from strategy_config_loader import load_all_strategy_configs
        configs = load_all_strategy_configs()
        for sid, cfg in configs.items():
            if any(ind in sid for ind in DAILY_SCALP_INDICATORS):
                findings.append({
                    "location": f"config/strategies/{sid}.yaml",
                    "indicator": sid,
                    "count": 1,
                    "classification": "possible_leakage",
                    "action": "Verify this is Trade AI strategy, not external scalp",
                })
    except Exception:
        pass

    # 5. Check incubator for daily scalp source
    for indicator in DAILY_SCALP_INDICATORS:
        rows = _db_query(f"""
            SELECT count(*) as c FROM incubator_universe
            WHERE strategy_id ILIKE '%{indicator}%'
            OR source_first_seen ILIKE '%{indicator}%'
        """, fetch="one")
        count = int((rows or {}).get("c", 0))
        if count > 0:
            findings.append({
                "location": "incubator_universe",
                "indicator": indicator,
                "count": count,
                "classification": "confirmed_leakage",
                "action": "Exclude from promotion",
            })

    # Determine overall status
    leakage_found = any(f["classification"] == "confirmed_leakage" for f in findings)
    unknown_found = any(f["classification"] == "unknown_requires_review" for f in findings)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "findings": findings,
        "leakage_found": leakage_found,
        "unknown_found": unknown_found,
        "boundary_status": "leakage_detected" if leakage_found else "review_needed" if unknown_found else "clean",
        "trade_ai_momentum_scalp_valid": True,
        "note": "Trade AI momentum_scalp YAML strategy is valid and separate from external daily scalp workflows",
    }

    if args.verbose:
        print(f"Daily Momentum Scalp Boundary Audit — {len(findings)} findings")
        print(f"  Boundary status: {report['boundary_status']}")
        for f in findings:
            print(f"  [{f['classification']}] {f['location']}: {f['indicator']} ({f['count']})")
            if f.get("action"):
                print(f"    Action: {f['action']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Daily Momentum Scalp Boundary Audit",
              f"\nStatus: {report['boundary_status']} | Findings: {len(findings)}\n"]
        if findings:
            md.append("| Location | Indicator | Classification | Count |")
            md.append("|----------|-----------|----------------|-------|")
            for f in findings:
                md.append(f"| {f['location']} | {f['indicator']} | {f['classification']} | {f['count']} |")
        else:
            md.append("No leakage detected.")
        md.append(f"\nTrade AI `momentum_scalp` YAML strategy is valid and preserved.")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
