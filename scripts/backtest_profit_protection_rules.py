#!/usr/bin/env python3
"""Phase 206 — Backtest candidate profit-protection rules on closed measurable trades.

EVIDENCE ONLY. No rule is ever applied to live trading, no order/stop/strategy mutation.
Evaluates stop/TP/trailing candidate rules against closed trades that have bar-based MFE/MAE
(trade_mfe_analysis) joined to the canonical trade_profit_capture_analysis.

Path limitation (stated honestly): we have summary MFE/MAE (peak/trough R + peak price), not the
full intrabar path. We therefore use a SINGLE-PEAK approximation: a lock/trailing rule that has
triggered installs a profit floor; simulated capture = the floor when it exceeds the realized
exit, else the realized exit. data_quality is stamped 'approx_single_peak' and confidence is
de-rated accordingly. This is decision-support evidence, not a tick-accurate fill simulator.

Writes `profit_protection_rule_backtests` only with --apply.

Candidate rules:
  breakeven_after_1R, lock25_after_1_5R, lock50_after_2R, trail5_after_2R, trail8_after_3R,
  partial_tp_1_5R, partial_tp_2R, and strategy-family variants (scalp/swing/income/position).
"""
import os, sys, json, argparse
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

MIN_SAMPLE = 20   # below this -> low confidence (mirrors shadow-threshold gate)


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
# Each rule maps a trade's (mfe_r, realized_pnl, max_profit_usd, initial_risk_usd) to a
# simulated captured profit under the single-peak approximation.

def rule_lock_fraction(trigger_r, fraction):
    """Lock `fraction` of the favorable peak once mfe_r >= trigger_r."""
    def sim(t):
        if t["mfe_r"] is None or t["mfe_r"] < trigger_r:
            return t["realized_pnl"]          # never triggered -> unchanged
        floor = fraction * (t["max_profit_usd"] or 0)
        return max(t["realized_pnl"], floor)
    return sim


def rule_breakeven(trigger_r):
    """Move stop to breakeven after +trigger_r. Protects losers that first reached +R."""
    def sim(t):
        if t["mfe_r"] is None or t["mfe_r"] < trigger_r:
            return t["realized_pnl"]
        # breakeven floor = 0; winners already > 0 so unchanged, losers that peaked >=R -> ~0
        return max(t["realized_pnl"], 0.0)
    return sim


def rule_trail_pct(trigger_r, pct):
    """Trail `pct` below the favorable peak price once mfe_r >= trigger_r."""
    def sim(t):
        if t["mfe_r"] is None or t["mfe_r"] < trigger_r or not t["mfe_price"] or not t["entry_price"]:
            return t["realized_pnl"]
        floor_price = t["mfe_price"] * (1 - pct)
        floor_usd = (floor_price - t["entry_price"]) * (t["shares"] or 0)
        floor_usd = min(floor_usd, t["max_profit_usd"] or floor_usd)
        return max(t["realized_pnl"], floor_usd)
    return sim


def rule_partial_tp(trigger_r):
    """Take 50% off at +trigger_r; remaining half rides to the realized exit."""
    def sim(t):
        if t["mfe_r"] is None or t["mfe_r"] < trigger_r or t["initial_risk_usd"] is None:
            return t["realized_pnl"]
        locked_half = 0.5 * (trigger_r * t["initial_risk_usd"])
        return locked_half + 0.5 * t["realized_pnl"]
    return sim


RULES = {
    "breakeven_after_1R": (rule_breakeven(1.0), None),
    "lock25_after_1_5R": (rule_lock_fraction(1.5, 0.25), None),
    "lock50_after_2R": (rule_lock_fraction(2.0, 0.50), None),
    "trail5_after_2R": (rule_trail_pct(2.0, 0.05), None),
    "trail8_after_3R": (rule_trail_pct(3.0, 0.08), None),
    "partial_tp_1_5R": (rule_partial_tp(1.5), None),
    "partial_tp_2R": (rule_partial_tp(2.0), None),
    # strategy-family variants
    "scalp_fast_trail3_after_1_5R": (rule_trail_pct(1.5, 0.03), "momentum"),
    "scalp_partial_tp_1R": (rule_partial_tp(1.0), "momentum"),
    "swing_lock50_after_2R": (rule_lock_fraction(2.0, 0.50), "swing"),
    "income_wide_trail8_after_3R": (rule_trail_pct(3.0, 0.08), "income"),
    "position_lock50_after_3R": (rule_lock_fraction(3.0, 0.50), "position"),
}


def evaluate(rule_fn, trades):
    base_ml = sum(t["money_left_usd"] or 0 for t in trades)
    sim_ml = avoided = premature = 0.0
    base_wins = sim_wins = 0
    base_gross_win = base_gross_loss = sim_gross_win = sim_gross_loss = 0.0
    for t in trades:
        realized = t["realized_pnl"]
        sim = rule_fn(t)
        delta = sim - realized
        if delta > 0:
            avoided += delta
        elif delta < 0:
            premature += -delta
        # remaining money left after the rule = max(peak - sim, 0)
        sim_ml += max((t["max_profit_usd"] or 0) - sim, 0.0)
        if realized > 0:
            base_wins += 1; base_gross_win += realized
        elif realized < 0:
            base_gross_loss += -realized
        if sim > 0:
            sim_wins += 1; sim_gross_win += sim
        elif sim < 0:
            sim_gross_loss += -sim
    n = len(trades)
    base_pf = (base_gross_win / base_gross_loss) if base_gross_loss > 0 else None
    sim_pf = (sim_gross_win / sim_gross_loss) if sim_gross_loss > 0 else None
    return {
        "sample_size": n,
        "baseline_money_left": round(base_ml, 2),
        "simulated_money_left": round(sim_ml, 2),
        "avoided_giveback": round(avoided, 2),
        "premature_exit_cost": round(premature, 2),
        "net_improvement": round(avoided - premature, 2),
        "win_rate_delta": round((sim_wins - base_wins) / n, 4) if n else 0.0,
        "profit_factor_delta": (round(sim_pf - base_pf, 4) if (base_pf is not None and sim_pf is not None) else None),
    }


def run(apply, json_path, md_path, run_id):
    load_env()
    import psycopg2.extras
    conn = db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT c.trade_instance_id, c.symbol, c.source_system, c.strategy_id,
               c.entry_price, c.shares, c.realized_pnl, c.max_profit_usd, c.money_left_usd,
               c.mfe_price, c.mfe_r, m.mae_r,
               pt.planned_stop
        FROM trade_profit_capture_analysis c
        LEFT JOIN paper_trades pt ON c.source_table='paper_trades' AND c.source_trade_id ~ '^[0-9]+$'
                                 AND pt.id = c.source_trade_id::int
        LEFT JOIN trade_mfe_analysis m ON c.source_table='paper_trades' AND c.source_trade_id ~ '^[0-9]+$'
                                      AND m.trade_id = c.source_trade_id::int
        WHERE c.measurable = true
    """)
    trades = []
    for r in cur.fetchall():
        d = dict(r)
        entry = f(d["entry_price"]); ps = f(d["planned_stop"]); shares = f(d["shares"])
        initial_risk = ((entry - ps) * shares) if (entry and ps and shares and entry > ps) else None
        trades.append({
            "trade_instance_id": d["trade_instance_id"], "source_system": d["source_system"],
            "strategy_id": d["strategy_id"], "family": family_of(d["strategy_id"]),
            "entry_price": entry, "shares": shares,
            "realized_pnl": f(d["realized_pnl"]) or 0.0,
            "max_profit_usd": f(d["max_profit_usd"]) or 0.0,
            "money_left_usd": f(d["money_left_usd"]) or 0.0,
            "mfe_price": f(d["mfe_price"]), "mfe_r": f(d["mfe_r"]),
            "initial_risk_usd": initial_risk,
        })

    results = []
    for rule_name, (fn, family_filter) in RULES.items():
        # overall (or family-scoped) population
        for scope_name, pop in [("ALL", trades)]:
            target = [t for t in pop if (family_filter is None or t["family"] == family_filter)]
            if not target:
                continue
            ev = evaluate(fn, target)
            n = ev["sample_size"]
            recommended = bool(ev["net_improvement"] > 0 and ev["avoided_giveback"] > ev["premature_exit_cost"])
            conf = "high" if n >= MIN_SAMPLE and ev["net_improvement"] > 0 else (
                   "medium" if n >= max(5, MIN_SAMPLE // 2) else "low")
            results.append({
                "run_id": run_id, "rule_name": rule_name,
                "strategy_family": family_filter or "ALL",
                "source_system": "ALL", **ev,
                "recommended": recommended,
                "recommendation_confidence": conf,
                "data_quality": "approx_single_peak",
            })

    written = 0
    if apply:
        wc = conn.cursor()
        cols = ["run_id", "rule_name", "strategy_family", "source_system", "sample_size",
                "baseline_money_left", "simulated_money_left", "avoided_giveback",
                "premature_exit_cost", "net_improvement", "win_rate_delta", "profit_factor_delta",
                "recommended", "recommendation_confidence", "data_quality"]
        for r in results:
            wc.execute(f"""INSERT INTO profit_protection_rule_backtests ({','.join(cols)})
                VALUES ({','.join('%('+c+')s' for c in cols)})""", {c: r.get(c) for c in cols})
            written += 1
        conn.commit()
    conn.close()

    report = {"run_at": datetime.now(timezone.utc).isoformat(), "run_id": run_id, "applied": apply,
              "written": written, "measurable_trades": len(trades), "results": results}
    if json_path:
        json.dump(report, open(json_path, "w"), indent=2, default=str)
    if md_path:
        L = ["# Profit-Protection Rule Backtests (evidence only)", "",
             f"run_id: {run_id}  |  measurable trades: {len(trades)}", "",
             "**No rule is applied to live trading. Single-peak approximation — see header.**", "",
             "| rule | family | n | baseline$ | avoided$ | premature$ | net$ | wr Δ | rec | conf |",
             "|------|--------|---|-----------|----------|------------|------|------|-----|------|"]
        for r in sorted(results, key=lambda x: -x["net_improvement"]):
            L.append(f"| {r['rule_name']} | {r['strategy_family']} | {r['sample_size']} | "
                     f"{r['baseline_money_left']} | {r['avoided_giveback']} | {r['premature_exit_cost']} | "
                     f"{r['net_improvement']} | {r['win_rate_delta']} | {r['recommended']} | "
                     f"{r['recommendation_confidence']} |")
        open(md_path, "w").write("\n".join(L) + "\n")
    print(json.dumps({"run_id": run_id, "measurable_trades": len(trades), "rules": len(results),
                      "best": sorted(results, key=lambda x: -x["net_improvement"])[:3]}, indent=2, default=str))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--markdown", default=None)
    a = ap.parse_args()
    rid = a.run_id or "ppbt_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run(a.apply, a.json, a.markdown, rid)
