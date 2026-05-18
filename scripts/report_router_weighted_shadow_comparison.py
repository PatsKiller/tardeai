#!/usr/bin/env python3
"""report_router_weighted_shadow_comparison.py — Compare old flat vs new weighted scoring.

Read-only. No proposal mutation. No strategy activation.

Usage:
    .venv/bin/python scripts/report_router_weighted_shadow_comparison.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

DEFAULT_FLAT_WEIGHT = 10


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


def _flat_score(config, signal):
    """Reproduce old flat +10 scoring for comparison."""
    score = 0
    for criterion in (config.get("entry_criteria") or []):
        metric = criterion.get("metric", "")
        operator = criterion.get("operator", "gte")
        value = criterion.get("value")
        actual = signal.get(metric)
        if actual is None:
            continue
        try:
            actual_num = float(actual) if not isinstance(actual, bool) else (1 if actual else 0)
            value_num = float(value) if value is not None else 0
            passed = False
            if operator == "gte": passed = actual_num >= value_num
            elif operator == "lte": passed = actual_num <= value_num
            elif operator == "gt": passed = actual_num > value_num
            elif operator == "lt": passed = actual_num < value_num
            elif operator == "eq": passed = actual_num == value_num
            elif operator == "exists": passed = actual is not None and actual != ""
            elif operator == "in": passed = str(actual) in (value if isinstance(value, list) else [value])
            if passed:
                score += DEFAULT_FLAT_WEIGHT
        except (ValueError, TypeError):
            pass
    # Flat bonuses
    universe = config.get("universe", {})
    if not isinstance(universe, dict): universe = {}
    price_cfg = universe.get("price", {})
    if not isinstance(price_cfg, dict): price_cfg = {}
    price = signal.get("price") or signal.get("proposed_entry")
    if price and price_cfg.get("min") and float(price) >= float(price_cfg["min"]): score += 5
    if price and price_cfg.get("max") and float(price) <= float(price_cfg["max"]): score += 5
    rvol_cfg = universe.get("rvol", {})
    if not isinstance(rvol_cfg, dict): rvol_cfg = {}
    rvol = signal.get("rvol")
    if rvol and rvol_cfg.get("min") and float(rvol) >= float(rvol_cfg["min"]): score += 15
    if signal.get("catalyst") and signal.get("catalyst_verified"): score += 10
    elif signal.get("catalyst"): score += 5
    return score


def main():
    p = argparse.ArgumentParser(description="Router weighted shadow comparison (read-only)")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.since_days)

    try:
        from strategy_config_loader import load_all_strategy_configs
        from multi_setup_router import evaluate_strategy_match
        configs = load_all_strategy_configs()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    proposals = _db_query("""
        SELECT ptp.id, ptp.symbol, ptp.strategy_id,
               scan.price, scan.rvol, scan.float_m, scan.gap_pct, scan.change_pct,
               scan.catalyst, scan.catalyst_verified, scan.catalyst_confidence,
               scan.score as scan_score, scan.decision
        FROM paper_trade_proposals ptp
        LEFT JOIN LATERAL (
            SELECT * FROM trade_ai_scans WHERE symbol = ptp.symbol
            ORDER BY scanned_at DESC LIMIT 1
        ) scan ON true
        WHERE ptp.created_at > %s
        ORDER BY ptp.created_at DESC LIMIT 100
    """, [since]) or []

    results = []
    old_top_counts = {}
    new_top_counts = {}
    changed_count = 0

    for pr in proposals:
        signal = {k: v for k, v in pr.items() if k not in ("id", "strategy_id")}
        if not signal.get("price"):
            continue

        # Old flat scoring
        old_scores = {}
        for sid, cfg in configs.items():
            old_scores[sid] = _flat_score(cfg, signal)
        old_top = max(old_scores, key=old_scores.get) if old_scores else None

        # New weighted scoring
        new_scores = {}
        for sid, cfg in configs.items():
            result = evaluate_strategy_match(cfg, signal)
            new_scores[sid] = result["match_score"]
        new_top = max(new_scores, key=new_scores.get) if new_scores else None

        changed = old_top != new_top
        if changed:
            changed_count += 1

        old_top_counts[old_top] = old_top_counts.get(old_top, 0) + 1
        new_top_counts[new_top] = new_top_counts.get(new_top, 0) + 1

        results.append({
            "proposal_id": pr["id"], "symbol": pr["symbol"],
            "original_strategy": pr["strategy_id"],
            "old_flat_top": old_top, "old_flat_score": old_scores.get(old_top, 0),
            "new_weighted_top": new_top, "new_weighted_score": new_scores.get(new_top, 0),
            "original_new_score": new_scores.get(pr["strategy_id"], 0),
            "top_changed": changed,
        })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_proposals": len(results),
        "top_match_changed": changed_count,
        "old_top_distribution": dict(sorted(old_top_counts.items(), key=lambda x: -x[1])),
        "new_top_distribution": dict(sorted(new_top_counts.items(), key=lambda x: -x[1])),
        "scoring_model": "yaml_weighted_v1",
        "proposals": results[:60],
    }

    if args.verbose:
        print(f"Shadow Comparison — {len(results)} proposals, {changed_count} top-match changed")
        print(f"\n  Old flat top distribution:")
        for s, c in sorted(old_top_counts.items(), key=lambda x: -x[1])[:10]:
            print(f"    {s}: {c}")
        print(f"\n  New weighted top distribution:")
        for s, c in sorted(new_top_counts.items(), key=lambda x: -x[1])[:10]:
            print(f"    {s}: {c}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Router Weighted Shadow Comparison\n",
              f"Proposals: {len(results)} | Top changed: {changed_count}\n",
              "## Old Flat Distribution\n",
              "| Strategy | Count |", "|----------|-------|"]
        for s, c in sorted(old_top_counts.items(), key=lambda x: -x[1]):
            md.append(f"| {s} | {c} |")
        md.append("\n## New Weighted Distribution\n")
        md.append("| Strategy | Count |")
        md.append("|----------|-------|")
        for s, c in sorted(new_top_counts.items(), key=lambda x: -x[1]):
            md.append(f"| {s} | {c} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
