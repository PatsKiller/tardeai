#!/usr/bin/env python3
"""run_full_universe_strategy_fit_audit.py — Evaluate full catalog against all strategies.

Audit/proof only. No trades. No orders. No proposals. No strategy changes.

Usage:
    .venv/bin/python scripts/run_full_universe_strategy_fit_audit.py --dry-run --limit 50 --verbose
    .venv/bin/python scripts/run_full_universe_strategy_fit_audit.py --apply --batch-size 250 --verbose
"""
import argparse, json, sys, os
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJ / ".env")


def _q(conn, sql, params=None, fetch="all"):
    cur = conn.cursor()
    cur.execute(sql, params or [])
    if fetch == "one":
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else {}
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def load_active_universe(conn, limit=None):
    """Load active symbols with latest scan data."""
    sql = """
        SELECT DISTINCT ON (s.symbol)
            s.symbol, s.score, s.grade, s.decision, s.rvol, s.price,
            s.change_pct, s.gap_pct, s.float_m, s.volume,
            s.catalyst, s.catalyst_verified, s.catalyst_confidence,
            s.sector, s.industry, s.country,
            s.source, s.screener_label,
            s.scanned_at
        FROM trade_ai_scans s
        JOIN screener_symbol_membership m ON m.symbol = s.symbol AND m.membership_status = 'present'
        WHERE s.scanned_at > NOW() - INTERVAL '7 days'
        ORDER BY s.symbol, s.scanned_at DESC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    return _q(conn, sql)


def load_strategy_configs():
    """Load all strategy YAMLs."""
    import yaml
    configs = {}
    strat_dir = PROJ / "config" / "strategies"
    skip = {"recommendation_schema.yaml", "strategy_schema.yaml", "shared_risk_rules.yaml"}
    for f in sorted(strat_dir.glob("*.yaml")):
        if f.name in skip:
            continue
        try:
            cfg = yaml.safe_load(f.read_text())
            if cfg and isinstance(cfg, dict) and cfg.get("strategy_id"):
                configs[cfg["strategy_id"]] = cfg
        except Exception:
            pass
    return configs


def evaluate_symbol(symbol_data, configs, conn):
    """Evaluate one symbol against all strategies. Returns list of audit rows."""
    from multi_setup_router import evaluate_strategy_match

    signal = dict(symbol_data)
    symbol = signal["symbol"]
    results = []

    # Try family classification
    try:
        from strategy_family_gate_policy import classify_candidate_family, family_gate_allows_strategy
        candidate_family_info = classify_candidate_family(signal)
        candidate_family = candidate_family_info.get("candidate_family", "UNKNOWN")
    except ImportError:
        candidate_family = "UNKNOWN"
        family_gate_allows_strategy = None

    # Try eligibility gates
    try:
        from strategy_eligibility_gate_policy import evaluate_basic_eligibility, evaluate_liquidity_eligibility
        basic_elig = evaluate_basic_eligibility(signal)
    except ImportError:
        basic_elig = {"eligible": True, "status": "PASS", "blockers": []}

    for sid, config in configs.items():
        strategy_family = config.get("timeframe_class", "UNKNOWN")

        # Family gate
        family_gate = "PASS"
        if family_gate_allows_strategy:
            try:
                fg = family_gate_allows_strategy(signal, config)
                family_gate = "PASS" if fg.get("allowed", True) else "FAIL"
            except Exception:
                family_gate = "ERROR"

        # Liquidity gate (basic eligibility)
        liq_gate = basic_elig.get("status", "PASS") if basic_elig.get("eligible", True) else "FAIL"

        # Quote status
        quote_age = None
        if signal.get("scanned_at"):
            try:
                from datetime import datetime, timezone
                scan_ts = signal["scanned_at"]
                if hasattr(scan_ts, 'timestamp'):
                    age_sec = (datetime.now(timezone.utc) - scan_ts.replace(tzinfo=timezone.utc if scan_ts.tzinfo is None else scan_ts.tzinfo)).total_seconds()
                    quote_age = int(age_sec)
            except Exception:
                pass
        quote_status = "fresh" if quote_age and quote_age < 86400 else "stale" if quote_age else "missing"

        # Required data check
        missing_fields = []
        if signal.get("price") is None: missing_fields.append("price")
        if signal.get("rvol") is None: missing_fields.append("rvol")
        if signal.get("float_m") is None: missing_fields.append("float_m")
        if signal.get("sector") is None: missing_fields.append("sector")
        if signal.get("volume") is None: missing_fields.append("volume")
        req_data = "COMPLETE" if not missing_fields else "PARTIAL" if len(missing_fields) < 3 else "MISSING"

        # Run router evaluation
        try:
            match = evaluate_strategy_match(config, signal)
        except Exception as e:
            match = {
                "strategy_id": sid, "match_score": 0, "raw_weighted_score": 0,
                "match_status": "ERROR", "criteria_met": [], "criteria_failed": [],
                "disqualifiers_hit": [], "missing_data": [str(e)],
                "is_blocked": False, "scoring_weights_used": False,
            }

        # Map match_status to match_strength
        ms = match.get("match_status", "NO_MATCH")
        strength_map = {
            "STRONG_MATCH": "STRONG", "MODERATE_MATCH": "MODERATE",
            "WEAK_MATCH": "WEAK", "NO_MATCH": "NO_MATCH",
            "BLOCKED": "BLOCKED", "ERROR": "NO_MATCH",
        }
        match_strength = strength_map.get(ms, "NO_MATCH")
        if req_data == "MISSING":
            match_strength = "MISSING_DATA"

        # Override with gate failures
        if family_gate == "FAIL":
            match_strength = "BLOCKED"
        if liq_gate == "FAIL":
            match_strength = "BLOCKED"

        # Recommendation
        if match_strength == "STRONG":
            rec = "watchpool_candidate"
        elif match_strength == "MODERATE":
            rec = "watchpool_candidate"
        elif match_strength == "WEAK":
            rec = "no_fit"
        elif match_strength == "MISSING_DATA":
            rec = "needs_data"
        elif match_strength == "BLOCKED" and liq_gate == "FAIL":
            rec = "blocked_by_liquidity"
        elif match_strength == "BLOCKED" and family_gate == "FAIL":
            rec = "blocked_by_strategy_fit"
        elif match_strength == "BLOCKED":
            rec = "blocked_by_strategy_fit"
        else:
            rec = "no_fit"

        results.append({
            "symbol": symbol,
            "strategy_id": sid,
            "strategy_family": strategy_family,
            "quote_status": quote_status,
            "liquidity_gate_status": liq_gate,
            "family_gate_status": family_gate,
            "required_data_status": req_data,
            "missing_fields": json.dumps(missing_fields + match.get("missing_data", [])),
            "scoring_weights_used": match.get("scoring_weights_used", False),
            "raw_score": match.get("raw_weighted_score", 0),
            "normalized_score": match.get("match_score", 0),
            "match_strength": match_strength,
            "criteria_met": json.dumps(match.get("criteria_met", [])),
            "criteria_failed": json.dumps(match.get("criteria_failed", [])),
            "blockers": json.dumps(match.get("disqualifiers_hit", [])),
            "recommendation": rec,
            "human_review_only": True,
        })

    # Mark top match
    non_blocked = [r for r in results if r["match_strength"] not in ("BLOCKED", "NO_MATCH", "MISSING_DATA")]
    if non_blocked:
        best = max(non_blocked, key=lambda r: r["normalized_score"])
        best["top_match_for_symbol"] = True
        best["recommendation"] = "proposal_candidate_pending_gates" if best["normalized_score"] >= 60 else "watchpool_candidate"
    else:
        # Mark highest scorer even if blocked
        if results:
            best = max(results, key=lambda r: r["normalized_score"])
            best["top_match_for_symbol"] = True

    return results


def main():
    p = argparse.ArgumentParser(description="Full universe strategy-fit audit (default: dry-run)")
    p.add_argument("--universe", default="active")
    p.add_argument("--limit", type=int)
    p.add_argument("--batch-size", type=int, default=250)
    p.add_argument("--audit-run-id", type=str)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    if args.apply:
        args.dry_run = False

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB connection"); sys.exit(1)

    audit_run_id = args.audit_run_id or f"arch4_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    mode = "DRY RUN" if args.dry_run else "APPLY"

    # Load universe
    symbols = load_active_universe(conn, args.limit)
    configs = load_strategy_configs()

    if args.verbose:
        print(f"[{mode}] Audit run: {audit_run_id}")
        print(f"  Universe: {len(symbols)} symbols | Strategies: {len(configs)}")

    stats = {
        "symbols_evaluated": 0,
        "strategies_evaluated": len(configs),
        "total_evaluations": 0,
        "STRONG": 0, "MODERATE": 0, "WEAK": 0,
        "NO_MATCH": 0, "MISSING_DATA": 0, "BLOCKED": 0,
        "watchpool_candidate": 0, "proposal_candidate_pending_gates": 0,
        "needs_data": 0, "no_fit": 0,
        "blocked_by_liquidity": 0, "blocked_by_strategy_fit": 0,
        "top_match_by_strategy": {},
        "family_gate_rejections": 0,
        "liquidity_rejections": 0,
    }

    all_results = []
    cur = conn.cursor()

    for i, sym_data in enumerate(symbols):
        results = evaluate_symbol(sym_data, configs, conn)
        stats["symbols_evaluated"] += 1
        stats["total_evaluations"] += len(results)

        for r in results:
            ms = r["match_strength"]
            stats[ms] = stats.get(ms, 0) + 1
            rec = r["recommendation"]
            stats[rec] = stats.get(rec, 0) + 1

            if r["family_gate_status"] == "FAIL":
                stats["family_gate_rejections"] += 1
            if r["liquidity_gate_status"] == "FAIL":
                stats["liquidity_rejections"] += 1

            if r.get("top_match_for_symbol"):
                sid = r["strategy_id"]
                stats["top_match_by_strategy"][sid] = stats["top_match_by_strategy"].get(sid, 0) + 1

            if not args.dry_run:
                cur.execute("""
                    INSERT INTO universe_strategy_fit_audit
                        (audit_run_id, symbol, strategy_id, strategy_family, quote_status,
                         liquidity_gate_status, family_gate_status, required_data_status,
                         missing_fields, scoring_weights_used, raw_score, normalized_score,
                         match_strength, criteria_met, criteria_failed, blockers,
                         top_match_for_symbol, recommendation, human_review_only)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)
                    ON CONFLICT (audit_run_id, symbol, strategy_id) DO UPDATE SET
                        normalized_score = EXCLUDED.normalized_score,
                        match_strength = EXCLUDED.match_strength,
                        recommendation = EXCLUDED.recommendation,
                        top_match_for_symbol = EXCLUDED.top_match_for_symbol
                """, [
                    audit_run_id, r["symbol"], r["strategy_id"], r["strategy_family"],
                    r["quote_status"], r["liquidity_gate_status"], r["family_gate_status"],
                    r["required_data_status"], r["missing_fields"], r["scoring_weights_used"],
                    r["raw_score"], r["normalized_score"], r["match_strength"],
                    r["criteria_met"], r["criteria_failed"], r["blockers"],
                    r.get("top_match_for_symbol", False), r["recommendation"],
                ])

        if args.verbose and (i + 1) % 100 == 0:
            print(f"  Progress: {i+1}/{len(symbols)} symbols...")

        if not args.dry_run and (i + 1) % args.batch_size == 0:
            conn.commit()

    if not args.dry_run:
        conn.commit()

    conn.close()

    # Zero-match strategies
    zero_match = [sid for sid in configs if stats["top_match_by_strategy"].get(sid, 0) == 0]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "audit_run_id": audit_run_id,
        "mode": "dry_run" if args.dry_run else "apply",
        **stats,
        "zero_match_strategies": zero_match,
    }

    if args.verbose:
        print(f"\n{'='*60}")
        print(f"[{mode}] Summary:")
        print(f"  Symbols: {stats['symbols_evaluated']} | Evaluations: {stats['total_evaluations']}")
        print(f"  STRONG: {stats['STRONG']} | MODERATE: {stats['MODERATE']} | WEAK: {stats['WEAK']}")
        print(f"  NO_MATCH: {stats['NO_MATCH']} | MISSING_DATA: {stats['MISSING_DATA']} | BLOCKED: {stats['BLOCKED']}")
        print(f"  Watchpool candidates: {stats['watchpool_candidate']}")
        print(f"  Proposal pending gates: {stats['proposal_candidate_pending_gates']}")
        print(f"  Needs data: {stats['needs_data']} | No fit: {stats['no_fit']}")
        print(f"  Family gate rejections: {stats['family_gate_rejections']}")
        print(f"  Liquidity rejections: {stats['liquidity_rejections']}")
        print(f"  Zero-match strategies: {zero_match}")
        if stats["top_match_by_strategy"]:
            print(f"  Top match distribution:")
            for sid, cnt in sorted(stats["top_match_by_strategy"].items(), key=lambda x: -x[1])[:10]:
                print(f"    {sid}: {cnt}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [f"# Strategy-Fit Audit {'DRY RUN' if args.dry_run else 'APPLIED'}\n",
              f"Run: {audit_run_id}\n",
              "| Metric | Value |", "|--------|-------|",
              f"| Symbols | {stats['symbols_evaluated']} |",
              f"| Strategies | {stats['strategies_evaluated']} |",
              f"| Total evaluations | {stats['total_evaluations']} |",
              f"| STRONG | {stats['STRONG']} |",
              f"| MODERATE | {stats['MODERATE']} |",
              f"| WEAK | {stats['WEAK']} |",
              f"| NO_MATCH | {stats['NO_MATCH']} |",
              f"| MISSING_DATA | {stats['MISSING_DATA']} |",
              f"| BLOCKED | {stats['BLOCKED']} |",
              f"| Watchpool candidates | {stats['watchpool_candidate']} |",
              f"| Proposal pending gates | {stats['proposal_candidate_pending_gates']} |",
              f"| Needs data | {stats['needs_data']} |",
              f"| Zero-match strategies | {len(zero_match)} |",
        ]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
