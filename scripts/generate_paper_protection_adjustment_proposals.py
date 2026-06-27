#!/usr/bin/env python3
"""Phase 192D — Paper protection adjustment PROPOSAL generator (advisory; no execution).

For each open paper trade with a profit-protection advisory, generates paper-only
adjustment *candidates* (KEEP / BREAKEVEN / PROFIT_LOCK / TAKE_PROFIT / TRAILING) with
full before/after risk + profit-lock + giveback math. Writes to:
  - table  paper_protection_adjustment_proposals
  - file   data/atm/protection_adjustment_proposals/<date>_proposals.json

Generates proposals ONLY. requires_operator_approval=true, no_live_execution=true.
Never places, modifies, or cancels any broker order.
"""
import os, sys, json, argparse
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
PROFIT_LOCK_FRACTION = 0.5     # lock ~50% of the current unrealized gain
TAKE_PROFIT_FRACTION = 0.10    # fixed TP 10% above current (illustrative; operator can edit)


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
    cur.execute("""create table if not exists paper_protection_adjustment_proposals (
        id bigserial primary key,
        created_at timestamptz default now(),
        trade_id bigint, symbol text, action text,
        current_stop numeric, proposed_stop numeric,
        current_take_profit numeric, proposed_take_profit numeric,
        current_risk numeric, proposed_risk numeric,
        profit_locked_before numeric, profit_locked_after numeric,
        giveback_before numeric, giveback_after numeric,
        downside_protection_improvement numeric, upside_limitation text,
        tradeai_reason text, hermes_reason text, evidence_refs jsonb,
        quote_timestamp text, quote_price numeric,
        requires_operator_approval boolean default true,
        no_live_execution boolean default true,
        alpaca_supported boolean, expected_api text,
        status text default 'PROPOSED', expires_at timestamptz )""")


def candidates(a):
    """a = advisory audit dict. Returns list of proposal dicts (advisory only)."""
    entry = a.get("entry_price"); price = a.get("current_price"); sh = a.get("shares") or 0
    cur_stop = a.get("current_broker_stop"); tp = None  # take_profit_price not order-tracked yet
    out = []
    if not (entry and price and sh and cur_stop):
        return out
    gain_ps = price - entry
    def locked(stop):
        return round((stop - entry) * sh, 2) if stop > entry else 0.0
    def giveback(stop):
        return round((price - stop) * sh, 2)
    def risk(stop):
        return round((entry - stop) * sh, 2)  # +ve = risk below entry; -ve = locked profit

    base = dict(current_stop=cur_stop, current_take_profit=tp,
                profit_locked_before=locked(cur_stop), giveback_before=giveback(cur_stop),
                current_risk=risk(cur_stop), alpaca_supported=True)

    # KEEP
    out.append({**base, "action": "KEEP_CURRENT_STOP", "proposed_stop": cur_stop,
                "proposed_take_profit": tp, "profit_locked_after": locked(cur_stop),
                "giveback_after": giveback(cur_stop), "proposed_risk": risk(cur_stop),
                "upside_limitation": "none", "expected_api": "none",
                "tradeai_reason": "Baseline — no change."})

    # BREAKEVEN (only if it moves the stop UP and we're in profit)
    be = round(entry, 4)
    if gain_ps > 0 and be > cur_stop:
        out.append({**base, "action": "MOVE_STOP_TO_BREAKEVEN", "proposed_stop": be,
                    "proposed_take_profit": tp, "profit_locked_after": locked(be),
                    "giveback_after": giveback(be), "proposed_risk": risk(be),
                    "upside_limitation": "none (stop only)",
                    "expected_api": "PATCH /v2/orders/<stop_id> (replace, paper)",
                    "tradeai_reason": "Eliminate downside below entry."})

    # PROFIT_LOCK (lock ~50% of current gain; only if it raises the stop)
    pl = round(entry + PROFIT_LOCK_FRACTION * gain_ps, 4)
    if gain_ps > 0 and pl > cur_stop:
        out.append({**base, "action": "MOVE_STOP_TO_PROFIT_LOCK", "proposed_stop": pl,
                    "proposed_take_profit": tp, "profit_locked_after": locked(pl),
                    "giveback_after": giveback(pl), "proposed_risk": risk(pl),
                    "upside_limitation": "none (stop only)",
                    "expected_api": "PATCH /v2/orders/<stop_id> (replace, paper)",
                    "tradeai_reason": f"Lock ~{int(PROFIT_LOCK_FRACTION*100)}% of unrealized gain."})

    # FIXED TAKE_PROFIT (separate limit order; advisory)
    tp_px = round(price * (1 + TAKE_PROFIT_FRACTION), 4)
    out.append({**base, "action": "ADD_FIXED_TAKE_PROFIT", "proposed_stop": cur_stop,
                "proposed_take_profit": tp_px, "profit_locked_after": locked(cur_stop),
                "giveback_after": giveback(cur_stop), "proposed_risk": risk(cur_stop),
                "upside_limitation": f"caps upside at {tp_px}",
                "expected_api": "POST /v2/orders (sell limit, paper) — OCO if supported",
                "tradeai_reason": f"Set fixed take-profit ~{int(TAKE_PROFIT_FRACTION*100)}% above current."})

    # TRAILING — hybrid ATR×family trail%; only when R-multiple gate passes
    if gain_ps > 0:
        from protection_trail_calculator import compute_trail_percent
        trail = compute_trail_percent(
            a.get("strategy"), a.get("symbol"), entry, a.get("planned_stop"), price,
            current_stop=cur_stop,
        )
        if trail.get("eligible"):
            out.append({**base, "action": "CONVERT_TO_TRAILING_STOP", "proposed_stop": None,
                        "proposed_take_profit": tp, "profit_locked_after": locked(cur_stop),
                        "giveback_after": giveback(cur_stop), "proposed_risk": risk(cur_stop),
                        "upside_limitation": f"trails {trail['trail_percent']}% below high ({trail['trail_family']})",
                        "expected_api": "cancel+POST /v2/orders trailing_stop (paper) — replace",
                        "tradeai_reason": trail.get("reason") or "Convert to trailing stop to follow price up.",
                        "trail_meta": trail})
    return out


def run(persist=True):
    load_env()
    import psycopg2.extras
    conn = db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if persist:
        wc = conn.cursor(); ensure_table(wc)
        # Idempotent for cron: supersede prior open candidates before regenerating, so only the
        # latest candidate set per trade is PROPOSED (no duplicate bloat). The approve engine also
        # guards on live broker-stop state, so a stale proposal would be safely blocked anyway.
        wc.execute("update paper_protection_adjustment_proposals set status='SUPERSEDED' where status='PROPOSED'")
        conn.commit()
    cur.execute("""SELECT DISTINCT ON (paper_trade_id) paper_trade_id, symbol, tradeai_action,
                          tradeai_reason, hermes_opinion, hermes_reason, audit_json
                   FROM atm_profit_protection_advisories ORDER BY paper_trade_id, created_at DESC""")
    rows = cur.fetchall()
    all_props = []
    wc = conn.cursor()
    for r in rows:
        a = r["audit_json"]
        if isinstance(a, str):
            a = json.loads(a)
        a = a or {}
        # only generate for trades with an actionable advisory (skip pure NO_ACTION baselines? keep KEEP for all)
        for c in candidates(a):
            ev = {"advisory_action": r["tradeai_action"], "hermes_opinion": r["hermes_opinion"]}
            if c.get("trail_meta"):
                ev["trail"] = c.pop("trail_meta")
            prop = {**c, "trade_id": r["paper_trade_id"], "symbol": r["symbol"],
                    "tradeai_advisory_action": r["tradeai_action"],
                    "hermes_reason": r["hermes_reason"],
                    "evidence_refs": ev,
                    "quote_timestamp": str(a.get("quote_age_min")), "quote_price": a.get("current_price"),
                    "requires_operator_approval": True, "no_live_execution": True}
            prop.setdefault("tradeai_reason", r["tradeai_reason"])
            di = (prop.get("profit_locked_after") or 0) - (prop.get("profit_locked_before") or 0)
            prop["downside_protection_improvement"] = round(di, 2)
            all_props.append(prop)
            if persist:
                wc.execute("""insert into paper_protection_adjustment_proposals
                    (trade_id,symbol,action,current_stop,proposed_stop,current_take_profit,
                     proposed_take_profit,current_risk,proposed_risk,profit_locked_before,
                     profit_locked_after,giveback_before,giveback_after,downside_protection_improvement,
                     upside_limitation,tradeai_reason,hermes_reason,evidence_refs,quote_timestamp,
                     quote_price,alpaca_supported,expected_api,status)
                    values (%(trade_id)s,%(symbol)s,%(action)s,%(current_stop)s,%(proposed_stop)s,
                     %(current_take_profit)s,%(proposed_take_profit)s,%(current_risk)s,%(proposed_risk)s,
                     %(profit_locked_before)s,%(profit_locked_after)s,%(giveback_before)s,%(giveback_after)s,
                     %(downside_protection_improvement)s,%(upside_limitation)s,%(tradeai_reason)s,
                     %(hermes_reason)s,%(evidence_refs)s,%(quote_timestamp)s,%(quote_price)s,
                     %(alpaca_supported)s,%(expected_api)s,'PROPOSED')""",
                    {**prop, "evidence_refs": json.dumps(prop["evidence_refs"])})
    if persist:
        conn.commit()
    conn.close()
    # dump JSON file (date passed via arg to avoid Date.now ban is not needed here — file uses provided date)
    out_dir = os.path.join(ROOT, "data/atm/protection_adjustment_proposals")
    fname = os.path.join(out_dir, f"{os.environ.get('PROP_DATE','latest')}_proposals.json")
    with open(fname, "w") as f:
        json.dump({"generated": True, "count": len(all_props), "proposals": all_props}, f, indent=2, default=str)
    print(json.dumps({"trades": len(rows), "proposals_generated": len(all_props),
                      "file": fname, "by_action": _by_action(all_props)}, indent=2, default=str))
    return all_props


def _by_action(props):
    out = {}
    for p in props:
        out[p["action"]] = out.get(p["action"], 0) + 1
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-persist", action="store_true")
    a = ap.parse_args()
    run(persist=not a.no_persist)
