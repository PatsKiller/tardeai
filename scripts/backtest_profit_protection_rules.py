#!/usr/bin/env python3
"""Phase 206 / 206b — Backtest candidate profit-protection rules on closed trades.

EVIDENCE ONLY. No rule is ever applied to live trading; no order/stop/strategy/GO-WAIT mutation.

Phase 206b hardening (after the rule-quality review found the raw signal NOT decision-grade):
  * Data-quality gate: drop trades with too-few MFE bars, outlier mfe_r, or no planned stop.
  * Winners-only give-back scope: separate genuine winner give-back from loser/breakeven risk-control.
  * Multi-tier sample reporting: raw / quality-eligible / triggered / winner / reliable.
  * Confidence is derived from RELIABLE sample size, never raw n.
  * Honest premature-exit cost: under single-peak MFE it CANNOT be priced — flagged unknown and the
    recovery estimate is labelled an upper bound.

Path limitation (stated honestly): we have summary MFE/MAE (peak/trough R + peak price), not the
full intrabar path. A lock/trailing floor is therefore modelled as binding only AFTER the favorable
peak (single-peak approximation). This systematically UNDER-states premature-exit cost, so simulated
recovery is an UPPER BOUND, not a fill-accurate result.

Writes `profit_protection_rule_backtests` only with --apply.
"""
import os, sys, json, argparse
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# Reliable-evidence floor (mirrors shadow-threshold gate).
RELIABLE_FLOOR = 20
# Quality-gate defaults
DEFAULT_MIN_BARS = 10
DEFAULT_MAX_MFE_R = 20.0


def load_env():
    for line in open(os.path.join(ROOT, ".env")):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def db():
    import psycopg2
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ.get("DB_PORT", "5432"),
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


def f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def family_of(strategy_id):
    try:
        from strategy_trailing_policy import get_strategy_family
        return get_strategy_family(strategy_id or "")
    except Exception:
        return "unknown"


# ---- candidate rules -------------------------------------------------------
def rule_lock_fraction(trigger_r, fraction):
    def sim(t):
        if t["mfe_r"] is None or t["mfe_r"] < trigger_r:
            return t["realized_pnl"]
        return max(t["realized_pnl"], fraction * (t["max_profit_usd"] or 0))
    return sim


def rule_breakeven(trigger_r):
    def sim(t):
        if t["mfe_r"] is None or t["mfe_r"] < trigger_r:
            return t["realized_pnl"]
        return max(t["realized_pnl"], 0.0)
    return sim


def rule_trail_pct(trigger_r, pct):
    def sim(t):
        if t["mfe_r"] is None or t["mfe_r"] < trigger_r or not t["mfe_price"] or not t["entry_price"]:
            return t["realized_pnl"]
        floor_usd = (t["mfe_price"] * (1 - pct) - t["entry_price"]) * (t["shares"] or 0)
        floor_usd = min(floor_usd, t["max_profit_usd"] or floor_usd)
        return max(t["realized_pnl"], floor_usd)
    return sim


def rule_partial_tp(trigger_r):
    def sim(t):
        if t["mfe_r"] is None or t["mfe_r"] < trigger_r or t["initial_risk_usd"] is None:
            return t["realized_pnl"]
        return 0.5 * (trigger_r * t["initial_risk_usd"]) + 0.5 * t["realized_pnl"]
    return sim


def triggers(trigger_r):
    return lambda t: t["mfe_r"] is not None and t["mfe_r"] >= trigger_r


# (rule_name, sim_fn, family_filter, trigger_fn, scope)
#   scope 'giveback'   -> winner give-back capture (the canonical protection problem)
#   scope 'risk_control' -> breakeven/loss-prevention (reported separately, includes losers)
RULES = [
    ("breakeven_after_1R",   rule_breakeven(1.0),        None, triggers(1.0), "risk_control"),
    ("lock25_after_1_5R",    rule_lock_fraction(1.5, 0.25), None, triggers(1.5), "giveback"),
    ("lock50_after_2R",      rule_lock_fraction(2.0, 0.50), None, triggers(2.0), "giveback"),
    ("trail5_after_2R",      rule_trail_pct(2.0, 0.05),  None, triggers(2.0), "giveback"),
    ("trail8_after_3R",      rule_trail_pct(3.0, 0.08),  None, triggers(3.0), "giveback"),
    ("partial_tp_1_5R",      rule_partial_tp(1.5),       None, triggers(1.5), "giveback"),
    ("partial_tp_2R",        rule_partial_tp(2.0),       None, triggers(2.0), "giveback"),
    ("scalp_fast_trail3_after_1_5R", rule_trail_pct(1.5, 0.03), "momentum", triggers(1.5), "giveback"),
    ("scalp_partial_tp_1R",  rule_partial_tp(1.0),       "momentum", triggers(1.0), "giveback"),
    ("swing_lock50_after_2R", rule_lock_fraction(2.0, 0.50), "swing", triggers(2.0), "giveback"),
    ("income_wide_trail8_after_3R", rule_trail_pct(3.0, 0.08), "income", triggers(3.0), "giveback"),
    ("position_lock50_after_3R", rule_lock_fraction(3.0, 0.50), "position", triggers(3.0), "giveback"),
]


def annotate_eligibility(t, min_bars, max_mfe_r, require_stop):
    """Row-level eligibility flags + excluded_reason for give-back rules.

    Phase 206c: the bar-detail gate uses the REAL intrabar path bar count where available
    (t['path_bars']), falling back to the MFE summary count (t['bars_analyzed']). A real path is
    what makes premature-exit cost measurable, so 'reliable' now requires a real path."""
    mfe_bars = t.get("bars_analyzed") or 0
    path_bars = t.get("path_bars") or 0
    eff_bars = max(mfe_bars, path_bars)
    t["has_bar_path"] = bool(t.get("has_path"))     # real intrabar path present
    t["has_planned_stop"] = t["initial_risk_usd"] is not None
    t["has_valid_mfe"] = t["mfe_r"] is not None and t["max_profit_usd"] is not None
    t["mfe_outlier"] = bool(t["mfe_r"] is not None and t["mfe_r"] > max_mfe_r)
    t["is_winner"] = bool(t["realized_pnl"] is not None and t["realized_pnl"] > 0)

    reasons = []
    if not t["has_valid_mfe"]:
        reasons.append("no_valid_mfe")
    if eff_bars < min_bars:
        reasons.append(f"bars_lt_{min_bars}")
    if t["mfe_outlier"]:
        reasons.append(f"mfe_r_gt_{max_mfe_r:g}")
    if require_stop and not t["has_planned_stop"]:
        reasons.append("no_planned_stop")
    if not (t["max_profit_usd"] and t["max_profit_usd"] > 0):
        reasons.append("max_profit_le_0")

    # give-back rules additionally require a winner
    gb_reasons = list(reasons)
    if not t["is_winner"]:
        gb_reasons.append("not_winner")

    t["eligible_for_breakeven_rule"] = (len(reasons) == 0)        # winners + losers (risk-control)
    t["eligible_for_giveback_rule"] = (len(gb_reasons) == 0)      # winners only
    t["excluded_reason"] = (",".join(gb_reasons) or None)
    # 'reliable' = passes the give-back gate AND has a REAL intrabar path (premature cost measurable)
    t["reliable"] = bool(t["eligible_for_giveback_rule"] and t["has_bar_path"])
    return t


def confidence_from_reliable(n):
    if n < 10:
        return "insufficient"
    if n < 20:
        return "weak"
    if n < 50:
        return "moderate"
    return "stronger"


def evaluate(rule_name, single_peak_fn, trigger_fn, trades, bars_by_tid):
    """Evaluate a rule. When a trade has a real intrabar path, the simulated capture and the
    premature-exit decision are PATH-MEASURED (replaying the rule against the actual bars);
    otherwise we fall back to the single-peak MFE approximation (upper bound)."""
    try:
        from profit_protection_path_pricer import price_rule, RULE_SPECS
        spec = RULE_SPECS.get(rule_name)
    except Exception:
        spec = None

    base_ml = sim_ml = avoided = premature = 0.0
    base_wins = sim_wins = 0
    base_gw = base_gl = sim_gw = sim_gl = 0.0
    triggered = path_priced = 0
    for t in trades:
        realized = t["realized_pnl"]
        if trigger_fn(t):
            triggered += 1
        bars = bars_by_tid.get(t["trade_instance_id"])
        pr = price_rule(t, bars, spec) if (spec and bars) else None
        if pr and pr.get("priced"):
            sim = pr["simulated_capture"]; path_priced += 1
        else:
            sim = single_peak_fn(t)
        delta = sim - realized
        if delta > 0:
            avoided += delta
        elif delta < 0:
            premature += -delta
        base_ml += t["money_left_usd"] or 0
        sim_ml += max((t["max_profit_usd"] or 0) - sim, 0.0)
        if realized > 0:
            base_wins += 1; base_gw += realized
        elif realized < 0:
            base_gl += -realized
        if sim > 0:
            sim_wins += 1; sim_gw += sim
        elif sim < 0:
            sim_gl += -sim
    n = len(trades)
    base_pf = (base_gw / base_gl) if base_gl > 0 else None
    sim_pf = (sim_gw / sim_gl) if sim_gl > 0 else None
    # premature cost is KNOWN only when every evaluated trade was priced on its real path
    premature_known = bool(n > 0 and path_priced == n)
    return {
        "baseline_money_left": round(base_ml, 2),
        "simulated_money_left": round(sim_ml, 2),
        "avoided_giveback": round(avoided, 2),
        "premature_exit_cost": round(premature, 2),
        "net_improvement": round(avoided - premature, 2),
        "win_rate_delta": round((sim_wins - base_wins) / n, 4) if n else 0.0,
        "profit_factor_delta": (round(sim_pf - base_pf, 4) if (base_pf is not None and sim_pf is not None) else None),
        "triggered_sample_size": triggered,
        "path_priced_count": path_priced,
        "premature_exit_cost_known": premature_known,
    }


def run(args, run_id):
    load_env()
    import psycopg2.extras
    conn = db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT c.trade_instance_id, c.symbol, c.source_system, c.strategy_id,
               c.entry_price, c.shares, c.realized_pnl, c.max_profit_usd, c.money_left_usd,
               c.mfe_price, c.mfe_r, m.mae_r, m.bars_analyzed, pt.planned_stop
        FROM trade_profit_capture_analysis c
        LEFT JOIN paper_trades pt ON c.source_table='paper_trades' AND c.source_trade_id ~ '^[0-9]+$'
                                 AND pt.id = c.source_trade_id::int
        LEFT JOIN trade_mfe_analysis m ON c.source_table='paper_trades' AND c.source_trade_id ~ '^[0-9]+$'
                                      AND m.trade_id = c.source_trade_id::int
        WHERE c.measurable = true
    """)
    rows = cur.fetchall()

    # Load real intrabar paths (Phase 206c) FIRST so premature-exit cost can be PATH-MEASURED and
    # so the data-quality gate can use the REAL path bar count, not the stale MFE summary count.
    bars_by_tid = {}
    cur.execute("""SELECT trade_instance_id, open, high, low, close
                   FROM trade_intrabar_bars ORDER BY trade_instance_id, bar_seq""")
    for b in cur.fetchall():
        bars_by_tid.setdefault(b["trade_instance_id"], []).append(
            {"open": f(b["open"]), "high": f(b["high"]), "low": f(b["low"]), "close": f(b["close"])})
    conn.close()
    path_trades = len(bars_by_tid)

    trades = []
    for r in rows:
        d = dict(r)
        entry = f(d["entry_price"]); ps = f(d["planned_stop"]); shares = f(d["shares"])
        initial_risk = ((entry - ps) * shares) if (entry and ps and shares and entry > ps) else None
        tid = d["trade_instance_id"]
        path_bars = len(bars_by_tid.get(tid, []))
        t = {
            "trade_instance_id": tid, "source_system": d["source_system"],
            "strategy_id": d["strategy_id"], "family": family_of(d["strategy_id"]),
            "entry_price": entry, "shares": shares, "planned_stop": ps,
            "realized_pnl": f(d["realized_pnl"]) or 0.0,
            "max_profit_usd": f(d["max_profit_usd"]) or 0.0,
            "money_left_usd": f(d["money_left_usd"]) or 0.0,
            "mfe_price": f(d["mfe_price"]), "mfe_r": f(d["mfe_r"]),
            "bars_analyzed": d["bars_analyzed"], "path_bars": path_bars,
            "has_path": path_bars > 0, "initial_risk_usd": initial_risk,
        }
        annotate_eligibility(t, args.min_bars_analyzed, args.max_mfe_r, args.require_planned_stop)
        trades.append(t)

    raw_n = len(trades)
    quality_gated = args.quality_gated or args.winners_only

    results = []
    for rule_name, fn, family_filter, trigger_fn, scope in RULES:
        pop = [t for t in trades if (family_filter is None or t["family"] == family_filter)]

        # Choose eligibility per scope + flags
        if quality_gated:
            if scope == "giveback" or args.winners_only:
                eligible = [t for t in pop if t["eligible_for_giveback_rule"]]
            else:  # risk_control breakeven — winners+losers but quality-gated
                eligible = [t for t in pop if t["eligible_for_breakeven_rule"]]
                if args.winners_only:
                    eligible = [t for t in eligible if t["is_winner"]]
            result_scope = ("winners_only_quality_gated" if scope == "giveback"
                            else "risk_control_quality_gated")
        else:
            eligible = pop  # legacy: no gate
            result_scope = "legacy_ungated"

        # Optionally drop losers entirely from the reported scope
        if args.separate_losers and scope == "giveback":
            eligible = [t for t in eligible if t["is_winner"]]

        if not pop:
            continue

        ev = evaluate(rule_name, fn, trigger_fn, eligible, bars_by_tid)

        # sample tiers
        quality_eligible_n = len(eligible)
        winner_n = sum(1 for t in eligible if t["is_winner"])
        reliable_n = sum(1 for t in eligible if t["reliable"])
        excluded = [t for t in pop if not (t["eligible_for_giveback_rule"] if scope == "giveback"
                                           else t["eligible_for_breakeven_rule"])]
        excluded_count = len(excluded)
        excl_reasons = {}
        for t in excluded:
            for rsn in (t["excluded_reason"] or "unknown").split(","):
                excl_reasons[rsn] = excl_reasons.get(rsn, 0) + 1

        confidence = confidence_from_reliable(reliable_n)

        # premature-exit honesty: PATH-MEASURED when every eligible trade had a real intrabar path
        # (Phase 206c); else single-peak MFE upper bound (cannot order stop-trigger vs later profit).
        path_priced = ev["path_priced_count"]
        premature_known = ev["premature_exit_cost_known"]
        if premature_known:
            premature_method = "intrabar_path_replay"
            premature_warning = None
            estimate_quality = "path_measured"
        elif path_priced > 0:
            premature_method = "mixed_path_and_single_peak"
            premature_warning = f"premature cost path-measured for {path_priced}/{quality_eligible_n} trades; rest single-peak"
            estimate_quality = "partial_path"
        else:
            premature_method = "single_peak_mfe_floor_after_peak"
            premature_warning = "single_peak_mfe_cannot_order_stop_trigger_vs_later_profit"
            estimate_quality = "upper_bound_single_peak"

        # recommendation requires positive net AND a met reliable floor AND known premature cost
        recommended = bool(ev["net_improvement"] > 0
                           and reliable_n >= RELIABLE_FLOOR
                           and premature_known)
        if reliable_n < RELIABLE_FLOOR:
            graft_verdict = "DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE"
        elif ev["net_improvement"] <= 0:
            graft_verdict = "REJECTED_NEGATIVE_EDGE"
        elif not premature_known:
            graft_verdict = "DO_NOT_GRAFT_PREMATURE_COST_UNKNOWN"
        else:
            graft_verdict = "ELIGIBLE_FOR_OPERATOR_REVIEW"

        results.append({
            "run_id": run_id, "rule_name": rule_name,
            "strategy_family": family_filter or "ALL", "source_system": "ALL",
            "scope": scope, "result_scope": result_scope,
            # legacy compat
            "sample_size": quality_eligible_n,
            "baseline_money_left": ev["baseline_money_left"],
            "simulated_money_left": ev["simulated_money_left"],
            "avoided_giveback": ev["avoided_giveback"],
            "premature_exit_cost": ev["premature_exit_cost"],
            "net_improvement": ev["net_improvement"],
            "win_rate_delta": ev["win_rate_delta"], "profit_factor_delta": ev["profit_factor_delta"],
            "recommended": recommended, "recommendation_confidence": confidence,
            "data_quality": ("quality_gated" if quality_gated else "approx_single_peak"),
            # hardened fields
            "raw_sample_size": len(pop),
            "quality_eligible_sample_size": quality_eligible_n,
            "triggered_sample_size": ev["triggered_sample_size"],
            "winner_sample_size": winner_n,
            "reliable_sample_size": reliable_n,
            "excluded_count": excluded_count,
            "excluded_reasons": excl_reasons,
            "premature_exit_cost_known": premature_known,
            "premature_exit_cost_method": premature_method,
            "premature_exit_cost_warning": premature_warning,
            "estimate_quality": estimate_quality,
            "graft_verdict": graft_verdict,
            "path_priced_count": path_priced,   # report-only (not a DB column)
        })

    written = 0
    if args.apply:
        conn = db(); wc = conn.cursor()
        # idempotent per run_id: a re-run with the same run_id replaces its rows (no duplicate snapshots)
        wc.execute("DELETE FROM profit_protection_rule_backtests WHERE run_id=%s", (run_id,))
        cols = ["run_id", "rule_name", "strategy_family", "source_system", "sample_size",
                "baseline_money_left", "simulated_money_left", "avoided_giveback",
                "premature_exit_cost", "net_improvement", "win_rate_delta", "profit_factor_delta",
                "recommended", "recommendation_confidence", "data_quality",
                "raw_sample_size", "quality_eligible_sample_size", "triggered_sample_size",
                "winner_sample_size", "reliable_sample_size", "excluded_count", "excluded_reasons",
                "premature_exit_cost_known", "premature_exit_cost_method", "premature_exit_cost_warning",
                "estimate_quality", "result_scope", "graft_verdict"]
        for r in results:
            vals = dict(r); vals["excluded_reasons"] = json.dumps(r["excluded_reasons"])
            wc.execute(f"""INSERT INTO profit_protection_rule_backtests ({','.join(cols)})
                VALUES ({','.join('%('+c+')s' for c in cols)})""", {c: vals.get(c) for c in cols})
            written += 1
        conn.commit(); conn.close()

    report = {"run_at": datetime.now(timezone.utc).isoformat(), "run_id": run_id,
              "applied": args.apply, "written": written, "raw_measurable_trades": raw_n,
              "trades_with_intrabar_path": path_trades,
              "gate": {"quality_gated": quality_gated, "winners_only": args.winners_only,
                       "min_bars_analyzed": args.min_bars_analyzed, "max_mfe_r": args.max_mfe_r,
                       "require_planned_stop": args.require_planned_stop,
                       "reliable_floor": RELIABLE_FLOOR},
              "results": results}
    if args.json:
        json.dump(report, open(args.json, "w"), indent=2, default=str)
    if args.markdown:
        L = ["# Profit-Protection Rule Backtests — quality-gated (evidence only)", "",
             f"run_id: {run_id}  |  raw measurable: {raw_n}  |  trades with intrabar path: "
             f"{path_trades}  |  gate: {report['gate']}", "",
             "**No rule applied to live trading. Where a trade has a real intrabar path, "
             "premature-exit cost is PATH-MEASURED (estimate_quality=path_measured); otherwise it is a "
             "single-peak upper bound. Confidence uses reliable n, not raw n.**", "",
             "| rule | scope | raw | qual | reliable | path | avoided$ | premature$ | net$ | estimate | conf | graft |",
             "|------|-------|-----|------|----------|------|----------|------------|------|----------|------|-------|"]
        for r in sorted(results, key=lambda x: -x["net_improvement"]):
            L.append(f"| {r['rule_name']} | {r['scope']} | {r['raw_sample_size']} | "
                     f"{r['quality_eligible_sample_size']} | {r['reliable_sample_size']} | "
                     f"{r['path_priced_count']} | {r['avoided_giveback']} | {r['premature_exit_cost']} | "
                     f"{r['net_improvement']} | {r['estimate_quality']} | "
                     f"{r['recommendation_confidence']} | {r['graft_verdict']} |")
        open(args.markdown, "w").write("\n".join(L) + "\n")

    best = max(results, key=lambda x: x["net_improvement"]) if results else None
    print(json.dumps({"run_id": run_id, "raw_measurable": raw_n,
                      "trades_with_intrabar_path": path_trades, "rules": len(results),
                      "gate": report["gate"],
                      "best_by_net": ({"rule": best["rule_name"], "reliable_n": best["reliable_sample_size"],
                                       "avoided": best["avoided_giveback"], "premature": best["premature_exit_cost"],
                                       "net": best["net_improvement"], "estimate_quality": best["estimate_quality"],
                                       "premature_known": best["premature_exit_cost_known"],
                                       "confidence": best["recommendation_confidence"],
                                       "graft": best["graft_verdict"]} if best else None),
                      "all_do_not_graft": all(r["graft_verdict"].startswith(("DO_NOT_GRAFT", "REJECTED"))
                                              for r in results)}, indent=2))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--quality-gated", action="store_true", help="apply data-quality gate")
    ap.add_argument("--winners-only", action="store_true", help="give-back scope = winners only")
    ap.add_argument("--separate-losers", action="store_true", help="drop losers from give-back scope")
    ap.add_argument("--min-bars-analyzed", type=int, default=DEFAULT_MIN_BARS)
    ap.add_argument("--max-mfe-r", type=float, default=DEFAULT_MAX_MFE_R)
    ap.add_argument("--require-planned-stop", action="store_true")
    ap.add_argument("--json", default=None)
    ap.add_argument("--markdown", default=None)
    a = ap.parse_args()
    rid = a.run_id or "ppbt_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run(a, rid)
