#!/usr/bin/env python3
"""Phase 191E — Hermes profit-protection second-opinion rule (advisory only).

Reads the latest TradeAI advisory per open trade from atm_profit_protection_advisories
and writes Hermes advisory findings (hermes_validation_findings) that give a SECOND
OPINION on profit protection — comparing TradeAI's view, the stop's profit-lock state,
and the trailing policy. Advisory only; never mutates trades/stops/orders.

Rules → finding_type:
  large gain, stop below entry (no lock)      -> large_gain_loose_stop                       (urgent)
  large gain, stop only ~breakeven            -> stop_only_breakeven_on_large_gain            (urgent)
  giveback of unrealized gain too high        -> profit_giveback_too_high                     (urgent)
  large gain, no take-profit                  -> large_gain_no_take_profit                    (urgent)
  trailing policy not triggered, review needed-> trailing_policy_not_triggered_but_review_needed(warning)
  strategy/risk metadata missing              -> strategy_metadata_missing_cannot_advise      (warning)
  quote stale                                 -> stale_quote_blocking_protection_review       (warning)
"""
import os, json
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LARGE_GAIN_USD = 250.0
GIVEBACK_FRACTION = 0.5


def load_env():
    for line in open(os.path.join(ROOT, ".env")):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def db():
    import psycopg2, psycopg2.extras
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


def rules_for(a, action, data_state):
    """Return list of (finding_type, severity, description, action)."""
    out = []
    pnl = a.get("unrealized_pnl") or 0
    pct = a.get("unrealized_pct")
    sym = a.get("symbol")
    locks = a.get("stop_locks_profit")
    locked = a.get("profit_locked_usd") or 0
    tp = a.get("take_profit_exists")
    if data_state == "QUOTE_STALE" or a.get("quote_fresh") is False:
        out.append(("stale_quote_blocking_protection_review", "warning",
                    f"{sym}: quote stale — cannot give a live profit-protection second opinion.",
                    "Re-evaluate at next fresh quote."))
        return out
    if data_state == "STRATEGY_METADATA_MISSING":
        out.append(("strategy_metadata_missing_cannot_advise", "warning",
                    f"{sym}: strategy/risk metadata missing — advisory limited to stop-vs-entry.",
                    "Classify position to a strategy family; set planned_stop."))
    big = (pnl is not None and pnl >= LARGE_GAIN_USD) or (pct is not None and pct >= 8.0)
    if big and not locks:
        out.append(("large_gain_loose_stop", "urgent",
                    f"{sym}: large gain ${pnl:.0f} ({pct}%) but stop is below entry — no profit locked.",
                    "Operator review: move stop to lock profit / breakeven."))
    if big and not tp:
        out.append(("large_gain_no_take_profit", "urgent",
                    f"{sym}: large gain ${pnl:.0f} with no take-profit set.",
                    "Operator review: set take-profit or trailing stop."))
    if big and pnl > 0:
        at_risk = pnl - locked
        if at_risk > 0 and (at_risk / pnl) >= GIVEBACK_FRACTION:
            out.append(("profit_giveback_too_high", "urgent",
                        f"{sym}: {at_risk/pnl*100:.0f}% of unrealized gain (${at_risk:.0f}) given back if stopped now.",
                        "Operator review: tighten stop to reduce giveback."))
    if a.get("trailing_threshold_met") and action not in ("TRAILING_STOP_ADVISORY",):
        out.append(("trailing_policy_not_triggered_but_review_needed", "warning",
                    f"{sym}: trailing policy threshold met but trailing inactive.",
                    "Operator review: convert to trailing stop."))
    return out


def has_open(cur, ftype, tid):
    cur.execute("""select 1 from hermes_validation_findings where finding_type=%s
                   and affected_table='paper_trades' and affected_id=%s and status='open' limit 1""",
                (ftype, tid))
    return cur.fetchone() is not None


def run():
    load_env()
    import psycopg2.extras
    conn = db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT DISTINCT ON (paper_trade_id)
                     paper_trade_id, symbol, tradeai_action, data_state, audit_json
                   FROM atm_profit_protection_advisories ORDER BY paper_trade_id, created_at DESC""")
    rows = cur.fetchall()
    w = conn.cursor()
    written = []
    for r in rows:
        a = r["audit_json"]
        if isinstance(a, str):
            a = json.loads(a)
        a = a or {}
        a.setdefault("symbol", r["symbol"])
        for ftype, sev, desc, act in rules_for(a, r["tradeai_action"], r["data_state"]):
            if has_open(w, ftype, r["paper_trade_id"]):
                continue
            w.execute("""insert into hermes_validation_findings
                (source,hermes_agent_name,finding_type,severity,symbol,affected_table,affected_id,
                 description,evidence_json,recommended_action,auto_fixable,status,created_at,updated_at)
                values('hermes','profit_protection_check',%s,%s,%s,'paper_trades',%s,%s,%s,%s,false,'open',%s,%s)
                returning id""",
                (ftype, sev, r["symbol"], r["paper_trade_id"], desc,
                 json.dumps({"tradeai_action": r["tradeai_action"], "pnl": a.get("unrealized_pnl")}),
                 act, datetime.now(timezone.utc), datetime.now(timezone.utc)))
            written.append({"id": w.fetchone()[0], "type": ftype, "sev": sev, "symbol": r["symbol"]})
    conn.commit(); conn.close()
    report = {"run_at": datetime.now(timezone.utc).isoformat(),
              "trades_checked": len(rows), "findings_written": written}
    print(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
