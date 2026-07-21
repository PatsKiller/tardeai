#!/usr/bin/env python3
"""Phase 206 — Diagnose why the existing advisory engine missed profit-protection on winners.

For every measurable winner that gave back profit, answers the 10 diagnostic questions and
assigns a primary root cause. READ-ONLY: no writes to any table, no broker/order/stop/strategy
changes. Pure analysis over trade_profit_capture_analysis + paper_trades + advisory tables.

Root causes:
  PAPER_ONLY_EXCLUSION   — Schwab/Fidelity import; the advisory engine only scans paper_trades.
  CLOSED_BEFORE_ENGINE   — trade closed before the advisory engine existed (started 2026-06-02).
  CRON_WINDOW_MISS       — open-trade scan never caught it with a fresh quote during the
                           protectable-profit window.
  THRESHOLD_TOO_HIGH     — peak gain never reached the engine's review threshold (3%).
  STOP_METADATA_MISSING  — no planned stop -> engine cannot compute give-back / R.
  STRATEGY_METADATA_MISSING — no/unknown strategy -> trailing policy disabled (requires_review).
  OPERATOR_ACTION_GAP    — advisory existed and urged protection but operator took no action.
"""
import os, sys, json, argparse
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

GAIN_PCT_REVIEW = 3.0   # mirrors profit_protection_advisory.GAIN_PCT_REVIEW


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


def family_first_tier(strategy_id):
    try:
        from strategy_trailing_policy import get_trailing_policy
        pol = get_trailing_policy(strategy_id or "")
        tiers = pol.get("tiers") or []
        return pol.get("family"), (tiers[0][0] if tiers else None)
    except Exception:
        return "unknown", None


def run(json_path, md_path):
    load_env()
    import psycopg2.extras
    conn = db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT min(created_at) m FROM atm_profit_protection_advisories")
    engine_start = cur.fetchone()["m"]

    # measurable winners that gave back profit (the protectable population) + all winners for context
    cur.execute("""
        SELECT c.*, pt.planned_stop, pt.stop_loss, pt.take_profit_price, pt.entry_time pt_entry,
               pt.exit_time pt_exit, pt.hold_time_min,
               (SELECT count(*) FROM atm_profit_protection_advisories ap
                 WHERE c.source_table='paper_trades' AND c.source_trade_id ~ '^[0-9]+$'
                   AND ap.paper_trade_id = c.source_trade_id::int) adv_count,
               (SELECT bool_or(data_state='QUOTE_STALE') FROM atm_profit_protection_advisories ap
                 WHERE c.source_table='paper_trades' AND c.source_trade_id ~ '^[0-9]+$'
                   AND ap.paper_trade_id = c.source_trade_id::int) any_stale
        FROM trade_profit_capture_analysis c
        LEFT JOIN paper_trades pt ON c.source_table='paper_trades' AND c.source_trade_id ~ '^[0-9]+$'
                                 AND pt.id = c.source_trade_id::int
        WHERE c.winner = true AND c.measurable = true AND coalesce(c.money_left_usd,0) > 0
        ORDER BY c.money_left_usd DESC NULLS LAST
    """)
    measurable = [dict(r) for r in cur.fetchall()]

    # schwab/imported winners excluded entirely from paper-only advisory logic
    cur.execute("""SELECT count(*) n FROM trade_profit_capture_analysis
                   WHERE winner=true AND source_system <> 'tradeai_automated'""")
    paper_excluded_winners = cur.fetchone()["n"]
    conn.close()

    per_trade = []
    for r in measurable:
        strat = r["strategy_id"]
        fam, first_tier = family_first_tier(strat)
        mfe_pct = f(r["mfe_pct"])
        mfe_r = f(r["mfe_r"])
        adv_count = r["adv_count"] or 0
        is_paper = r["source_system"] == "tradeai_automated"
        closed_before_engine = bool(engine_start and r["exit_time"] and r["exit_time"] < engine_start)
        peak_reached_threshold = mfe_pct is not None and mfe_pct >= GAIN_PCT_REVIEW
        trailing_tier_too_high = bool(first_tier is not None and mfe_r is not None and mfe_r < first_tier)

        q = {
            "1_open_long_enough_for_cron": (None if r["hold_time_min"] is None
                                            else bool(f(r["hold_time_min"]) and f(r["hold_time_min"]) >= 5)),
            "2_cron_ran_during_protectable_profit": adv_count > 0,
            "3_quote_fresh_at_relevant_time": (None if adv_count == 0 else (not bool(r["any_stale"]))),
            "4_thresholds_failed_to_trigger": bool(peak_reached_threshold and adv_count == 0),
            "5_planned_stop_missing": r["planned_stop"] is None and r["stop_loss"] is None,
            "6_strategy_metadata_missing": (not strat) or fam == "unknown",
            "7_take_profit_existed": r["take_profit_price"] is not None,
            "8_trailing_threshold_too_high": trailing_tier_too_high,
            "9_advisory_generated_not_acted": bool(r["advisory_existed"] and not r["operator_acted"]),
            "10_imported_excluded_from_paper_only": not is_paper,
        }

        # primary root cause (ordered)
        if not is_paper:
            root = "PAPER_ONLY_EXCLUSION"
        elif r["advisory_existed"] and not r["operator_acted"]:
            root = "OPERATOR_ACTION_GAP"
        elif closed_before_engine:
            root = "CLOSED_BEFORE_ENGINE"
        elif not peak_reached_threshold:
            root = "THRESHOLD_TOO_HIGH"
        elif q["5_planned_stop_missing"]:
            root = "STOP_METADATA_MISSING"
        elif q["6_strategy_metadata_missing"]:
            root = "STRATEGY_METADATA_MISSING"
        else:
            root = "CRON_WINDOW_MISS"

        per_trade.append({
            "trade_instance_id": r["trade_instance_id"], "symbol": r["symbol"],
            "source_system": r["source_system"], "strategy_id": strat,
            "money_left_usd": f(r["money_left_usd"]), "mfe_pct": mfe_pct, "mfe_r": mfe_r,
            "advisory_count": adv_count, "closed_before_engine": closed_before_engine,
            "primary_root_cause": root, "questions": q,
            "failure_class": r["failure_class"],
        })

    from collections import Counter
    agg = dict(Counter(t["primary_root_cause"] for t in per_trade))
    agg_money = {}
    for t in per_trade:
        agg_money[t["primary_root_cause"]] = round(agg_money.get(t["primary_root_cause"], 0) + (t["money_left_usd"] or 0), 2)

    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "advisory_engine_start": str(engine_start) if engine_start else None,
        "measurable_giveback_winners": len(per_trade),
        "paper_only_excluded_winners_total": paper_excluded_winners,
        "root_cause_breakdown": agg,
        "money_left_by_root_cause": agg_money,
        "threshold_miss_examples": [t for t in per_trade if t["questions"]["4_thresholds_failed_to_trigger"]][:10],
        "cron_window_miss_examples": [t for t in per_trade if t["primary_root_cause"] == "CRON_WINDOW_MISS"][:10],
        "paper_only_exclusion_examples": [t for t in per_trade if t["primary_root_cause"] == "PAPER_ONLY_EXCLUSION"][:10],
        "operator_action_gap_examples": [t for t in per_trade if t["primary_root_cause"] == "OPERATOR_ACTION_GAP"][:10],
        "per_trade": per_trade,
    }

    if json_path:
        json.dump(report, open(json_path, "w"), indent=2, default=str)
    if md_path:
        L = ["# Profit-Protection Advisory Gap Diagnosis", "",
             f"Advisory engine started: {engine_start}", "",
             f"Measurable give-back winners analyzed: {len(per_trade)}", "",
             f"Paper-only excluded winners (Schwab/Fidelity, total): {paper_excluded_winners}", "",
             "## Root-cause breakdown", ""]
        for k, v in sorted(agg.items(), key=lambda x: -x[1]):
            L.append(f"- {k}: {v} trades, ${agg_money.get(k,0)} left")
        L += ["", "## Per-trade", "",
              "| sym | source | strat | $left | mfe% | root cause |",
              "|-----|--------|-------|-------|------|-----------|"]
        for t in per_trade:
            L.append(f"| {t['symbol']} | {t['source_system']} | {t['strategy_id']} | "
                     f"{t['money_left_usd']} | {t['mfe_pct']} | {t['primary_root_cause']} |")
        open(md_path, "w").write("\n".join(L) + "\n")
    print(json.dumps({k: report[k] for k in
                      ["advisory_engine_start", "measurable_giveback_winners",
                       "paper_only_excluded_winners_total", "root_cause_breakdown",
                       "money_left_by_root_cause"]}, indent=2, default=str))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    ap.add_argument("--markdown", default=None)
    a = ap.parse_args()
    run(a.json, a.markdown)
