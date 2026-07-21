#!/usr/bin/env python3
"""Phase 191 — ATM profit-protection advisory engine (ADVISORY ONLY).

For each open paper trade, computes the full profit-protection audit (191B), runs
the TradeAI scoring model (191D), consults strategy_trailing_policy v2.3, and emits
an operator-reviewed advisory. It NEVER moves/cancels stops, creates take-profit
orders, or modifies any broker order. Read-only on the broker; writes only the
advisory table `atm_profit_protection_advisories` for inline-panel/Hermes consumption.

Actions (TradeAI scoring output):
  NO_ACTION, REVIEW_STOP, MOVE_TO_BREAKEVEN_ADVISORY, LOCK_PROFIT_ADVISORY,
  TRAILING_STOP_ADVISORY, TAKE_PROFIT_ADVISORY, PARTIAL_PROFIT_ADVISORY,
  URGENT_PROTECTION_REVIEW
Data states: OK, QUOTE_STALE, STRATEGY_METADATA_MISSING
"""
import os, sys, json, argparse
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# Advisory thresholds (documented in PHASE191D)
GAIN_PCT_REVIEW = 3.0       # start paying attention
GAIN_PCT_LOCK = 8.0         # meaningful gain → lock/breakeven advisory
LARGE_GAIN_USD = 250.0      # large $ gain → take-profit advisory
GIVEBACK_FRACTION_URGENT = 0.5   # giving back >50% of unrealized gain if stopped → urgent
QUOTE_FRESH_MIN = 30        # minutes


def load_env():
    for line in open(os.path.join(ROOT, ".env")):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def db():
    import psycopg2
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


def ensure_table(cur):
    cur.execute("""create table if not exists atm_profit_protection_advisories (
        id bigserial primary key,
        paper_trade_id bigint not null,
        symbol text,
        created_at timestamptz default now(),
        data_state text,
        tradeai_action text,
        tradeai_reason text,
        supporting_actions jsonb,
        audit_json jsonb,
        hermes_opinion text,
        hermes_reason text,
        operator_action_required boolean
    )""")


def fresh_quote(sym):
    try:
        from market_quote_provider import get_best_quote
        q = get_best_quote(sym) or {}
    except Exception as e:
        return {"error": str(e)}
    qt = q.get("quote_timestamp"); age = None
    if qt:
        try:
            age = round((datetime.now(timezone.utc) - datetime.fromisoformat(qt)).total_seconds() / 60, 1)
        except Exception:
            pass
    q["age_min"] = age
    return q


def trailing_eval(strategy, entry, planned_stop, current_stop, price):
    try:
        from strategy_trailing_policy import recommend_stop, get_strategy_family
        rec = recommend_stop(strategy, entry, planned_stop, current_stop, price, market_hours=True)
        return get_strategy_family(strategy), rec
    except Exception as e:
        return "unknown", {"action": "error", "reason": str(e)}


def audit_trade(row, q):
    (tid, sym, strat, entry, shares, planned_stop, stop_loss, stop_oid, cur_stop,
     tp_px, upnl_db, mfe, mae, entry_time, regime, vix) = row
    entry = float(entry) if entry else None
    shares = int(shares) if shares else 0
    cur_stop = float(cur_stop) if cur_stop else (float(stop_loss) if stop_loss else None)
    price = q.get("last_price")
    fresh = q.get("age_min") is not None and q["age_min"] <= QUOTE_FRESH_MIN
    a = {"trade_id": tid, "symbol": sym, "strategy": strat, "entry_price": entry,
         "current_price": price, "quote_age_min": q.get("age_min"), "quote_fresh": fresh,
         "shares": shares, "planned_stop": float(planned_stop) if planned_stop else None,
         "current_broker_stop": cur_stop, "stop_order_id": stop_oid,
         "take_profit_exists": tp_px is not None, "mfe": float(mfe) if mfe else None,
         "mae": float(mae) if mae else None, "market_regime": regime}
    if entry and price and shares:
        a["unrealized_pnl"] = round((price - entry) * shares, 2)
        a["unrealized_pct"] = round((price - entry) / entry * 100, 2)
    else:
        a["unrealized_pnl"] = float(upnl_db) if upnl_db else None
        a["unrealized_pct"] = None
    if cur_stop and price:
        a["stop_distance_pct"] = round((price - cur_stop) / price * 100, 2)
        a["stop_distance_usd"] = round((price - cur_stop) * shares, 2)
        a["giveback_to_stop_usd"] = round((price - cur_stop) * shares, 2)
    if cur_stop and entry:
        a["stop_locks_profit"] = cur_stop > entry
        a["profit_locked_usd"] = round((cur_stop - entry) * shares, 2) if cur_stop > entry else 0.0
        risk = entry - cur_stop
        a["unrealized_r_vs_stop"] = round((price - entry) / risk, 2) if (price and risk > 0) else None
    if entry and planned_stop and price and (entry - float(planned_stop)) > 0:
        a["unrealized_r"] = round((price - entry) / (entry - float(planned_stop)), 2)
    else:
        a["unrealized_r"] = a.get("unrealized_r_vs_stop")
    fam, rec = trailing_eval(strat, entry, float(planned_stop) if planned_stop else None,
                             cur_stop, price)
    a["strategy_family"] = fam
    a["trailing_active"] = False
    a["trailing_policy_action"] = rec.get("action")
    a["trailing_policy_reason"] = rec.get("reason")
    a["trailing_threshold_met"] = rec.get("action") in ("recommend_trail", "recommend_deferred")
    return a


def score(a):
    """TradeAI profit-protection scoring (191D). Advisory only."""
    supporting = []
    if not a.get("quote_fresh"):
        return "REVIEW_STOP", "Quote stale — cannot advise on live giveback; verify at next fresh quote.", ["QUOTE_STALE"], "QUOTE_STALE"
    pct = a.get("unrealized_pct")
    pnl = a.get("unrealized_pnl") or 0
    locks = a.get("stop_locks_profit")
    tp = a.get("take_profit_exists")
    giveback = a.get("giveback_to_stop_usd")
    data_state = "OK"
    if a.get("planned_stop") is None and a.get("strategy", "").startswith("unknown"):
        data_state = "STRATEGY_METADATA_MISSING"
    if pct is None:
        return "REVIEW_STOP", "Unrealized % uncomputable (missing entry/price).", supporting, data_state

    # supporting advisories
    if not tp and (pnl >= LARGE_GAIN_USD or pct >= GAIN_PCT_LOCK):
        supporting.append("TAKE_PROFIT_ADVISORY")
    if a.get("trailing_threshold_met"):
        supporting.append("TRAILING_STOP_ADVISORY")
    if pct >= GAIN_PCT_LOCK and not locks:
        supporting.append("LOCK_PROFIT_ADVISORY")
    elif GAIN_PCT_REVIEW <= pct < GAIN_PCT_LOCK and not locks:
        supporting.append("MOVE_TO_BREAKEVEN_ADVISORY")

    # urgency: large gain, stop gives back most of it
    urgent = False
    if pnl > 0 and giveback is not None and pnl >= LARGE_GAIN_USD:
        # giveback measured as profit surrendered relative to entry if stopped now
        surrender = (a["current_price"] - a["current_broker_stop"]) * a["shares"] if a.get("current_broker_stop") else None
        locked = a.get("profit_locked_usd") or 0
        gain_at_risk = (pnl - locked)
        if gain_at_risk > 0 and pnl > 0 and (gain_at_risk / pnl) >= GIVEBACK_FRACTION_URGENT:
            urgent = True

    # primary action
    if urgent:
        return "URGENT_PROTECTION_REVIEW", (
            f"Large gain ${pnl:.0f} ({pct:.1f}%) with stop not protecting it — "
            f"most of the gain is given back if stopped. Review stop/TP now."), supporting, data_state
    if "LOCK_PROFIT_ADVISORY" in supporting:
        return "LOCK_PROFIT_ADVISORY", (
            f"Gain {pct:.1f}% (${pnl:.0f}); stop {'locks profit' if locks else 'below entry'} — "
            f"advise moving stop up to lock profit."), supporting, data_state
    if "MOVE_TO_BREAKEVEN_ADVISORY" in supporting:
        return "MOVE_TO_BREAKEVEN_ADVISORY", (
            f"Gain {pct:.1f}% (${pnl:.0f}); consider moving stop toward breakeven."), supporting, data_state
    if "TAKE_PROFIT_ADVISORY" in supporting:
        return "TAKE_PROFIT_ADVISORY", (
            f"Meaningful gain (${pnl:.0f}) with no take-profit set."), supporting, data_state
    if "TRAILING_STOP_ADVISORY" in supporting:
        return "TRAILING_STOP_ADVISORY", "Trailing policy threshold met — consider trailing stop.", supporting, data_state
    if pct >= GAIN_PCT_REVIEW:
        return "REVIEW_STOP", f"Gain {pct:.1f}% — worth a stop review.", supporting, data_state
    return "NO_ACTION", f"Gain {pct:.1f}% — below review threshold; no action.", supporting, data_state


def load_shadow_rules(cur):
    """Phase 206 — load latest shadow threshold recommendations by family (DIAGNOSTIC ONLY).

    Read-only. These are supporting evidence surfaced in the audit; they NEVER change the
    advisory thresholds, stop movement, or execution. Returns {} if the table is absent."""
    try:
        cur.execute("""select strategy_family, graft_verdict, proposed_thresholds, confidence
                       from profit_protection_shadow_recommendations
                       where run_id = (select max(run_id) from profit_protection_shadow_recommendations)""")
        return {r[0]: {"graft_verdict": r[1], "proposed_thresholds": r[2], "confidence": r[3]}
                for r in cur.fetchall()}
    except Exception:
        return {}


def canonical_link(cur, paper_trade_id):
    """Phase 206 — map an open paper trade to its canonical trade_instance (read-only)."""
    try:
        cur.execute("""select id, source_system, execution_account, execution_environment, execution_broker
                       from trade_instances
                       where source_table='paper_trades' and source_trade_id = %s::text
                       limit 1""", (str(paper_trade_id),))
        r = cur.fetchone()
        if r:
            return {"trade_instance_id": r[0], "source_system": r[1],
                    "execution_account": r[2], "execution_environment": r[3], "execution_broker": r[4]}
    except Exception:
        pass
    return {"trade_instance_id": None, "source_system": "tradeai_automated",
            "execution_account": None, "execution_environment": "paper", "execution_broker": "alpaca"}


def enrich_audit(a, shadow_rules):
    """Phase 206 — additive audit fields. Pure analytics; no execution side effects."""
    pnl = a.get("unrealized_pnl") or 0
    locked = a.get("profit_locked_usd") or 0
    protectable = round(max(0.0, pnl), 2)
    gain_at_risk = round(max(0.0, pnl - locked), 2)
    a["protectable_profit"] = protectable
    a["gain_at_risk"] = gain_at_risk
    a["giveback_pct_if_stopped"] = round(gain_at_risk / protectable, 4) if protectable > 0 else None
    a["current_capture_ratio"] = round(locked / pnl, 4) if pnl > 0 else None
    # threshold_reason: which advisory threshold band the position sits in
    pct = a.get("unrealized_pct")
    if pct is None:
        a["threshold_reason"] = "pct_uncomputable"
    elif pct >= GAIN_PCT_LOCK:
        a["threshold_reason"] = f"gain {pct:.1f}% >= lock threshold {GAIN_PCT_LOCK:.0f}%"
    elif pct >= GAIN_PCT_REVIEW:
        a["threshold_reason"] = f"gain {pct:.1f}% in review band [{GAIN_PCT_REVIEW:.0f}%,{GAIN_PCT_LOCK:.0f}%)"
    else:
        a["threshold_reason"] = f"gain {pct:.1f}% below review threshold {GAIN_PCT_REVIEW:.0f}%"
    # shadow_rule_triggered: diagnostic-only evidence for this family (never grafted)
    fam = a.get("strategy_family")
    sr = shadow_rules.get(fam)
    a["shadow_rule_triggered"] = ({"family": fam, "verdict": sr["graft_verdict"],
                                   "confidence": sr["confidence"]} if sr else None)
    return a


def hermes_second_opinion(a, action):
    """Lightweight rule-based second opinion (full Hermes rules in 191E)."""
    if not a.get("quote_fresh"):
        return "needs_evidence", "Quote stale — Hermes cannot confirm; await fresh data."
    if a.get("strategy", "").startswith("unknown") and a.get("planned_stop") is None:
        return "caution", "Strategy/risk metadata missing — advisory based on stop-vs-entry only; classify position."
    if action in ("LOCK_PROFIT_ADVISORY", "URGENT_PROTECTION_REVIEW", "TAKE_PROFIT_ADVISORY"):
        return "agree", "Concurs: meaningful unrealized gain with insufficient profit protection."
    if action == "NO_ACTION":
        return "agree", "Concurs: gain below protection threshold."
    return "caution", "Reasonable, but confirm against strategy timeframe and catalyst status."


def run(persist=True):
    load_env()
    conn = db(); cur = conn.cursor()
    if persist:
        ensure_table(cur); conn.commit()
    cur.execute("""select id,symbol,strategy_id,entry_price,shares,planned_stop,stop_loss,
                          stop_order_id,current_stop,take_profit_price,unrealized_pnl,
                          max_favorable_excursion,max_adverse_excursion,entry_time,
                          market_regime,vix_at_entry
                   from paper_trades where status='open' order by id""")
    rows = cur.fetchall()
    shadow_rules = load_shadow_rules(cur)   # Phase 206: diagnostic-only evidence
    advisories = []
    counts = {"reviewed": len(rows), "take_profit_missing": 0, "stop_quality_advisory": 0,
              "trailing_eligible": 0, "profit_lock_advisory": 0, "action_required": 0}
    for row in rows:
        sym = row[1]
        q = fresh_quote(sym)
        a = audit_trade(row, q)
        # Phase 206: canonical all-trades linkage + additive audit fields (no execution change)
        a.update(canonical_link(cur, a["trade_id"]))
        a = enrich_audit(a, shadow_rules)
        action, reason, supporting, data_state = score(a)
        hop, hreason = hermes_second_opinion(a, action)
        op_req = action not in ("NO_ACTION",)
        if not a["take_profit_exists"]:
            counts["take_profit_missing"] += 1
        if action in ("REVIEW_STOP", "MOVE_TO_BREAKEVEN_ADVISORY", "LOCK_PROFIT_ADVISORY", "URGENT_PROTECTION_REVIEW"):
            counts["stop_quality_advisory"] += 1
        if a["trailing_threshold_met"]:
            counts["trailing_eligible"] += 1
        if "LOCK_PROFIT_ADVISORY" in supporting or action == "LOCK_PROFIT_ADVISORY":
            counts["profit_lock_advisory"] += 1
        if op_req:
            counts["action_required"] += 1
        rec = {"trade_id": a["trade_id"], "symbol": sym, "data_state": data_state,
               "tradeai_action": action, "tradeai_reason": reason,
               "supporting_actions": supporting, "hermes_opinion": hop,
               "hermes_reason": hreason, "operator_action_required": op_req, "audit": a}
        advisories.append(rec)
        if persist:
            cur.execute("""insert into atm_profit_protection_advisories
                (paper_trade_id,symbol,data_state,tradeai_action,tradeai_reason,
                 supporting_actions,audit_json,hermes_opinion,hermes_reason,operator_action_required)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (a["trade_id"], sym, data_state, action, reason, json.dumps(supporting),
                 json.dumps(a, default=str), hop, hreason, op_req))
    if persist:
        conn.commit()
    conn.close()
    report = {"run_at": datetime.now(timezone.utc).isoformat(), "counts": counts, "advisories": advisories}
    print(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-persist", action="store_true")
    a = ap.parse_args()
    run(persist=not a.no_persist)
