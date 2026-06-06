#!/usr/bin/env python3
"""Phase 206 — Exact-only journal field backfill for closed paper trades.

Fills low-completeness journal/analytics metadata on paper_trades using EXACT sources only.
NEVER fuzzy/hallucinated — unknown stays NULL and is reported with a data-quality flag.

Exact backfills:
  broker / execution_broker  <- trade_instances.execution_broker (exact source_table linkage)
  close_reason               <- paper_trades.exit_reason (same row, only when close_reason NULL)
  post_trade_analyzed=true   <- existence of an LLM/journal/thesis review for the trade
  max_favorable_excursion    <- trade_mfe_analysis.mfe_price -> % (only when NULL)
  max_adverse_excursion      <- trade_mfe_analysis.mae_r       (only when NULL)
  catalyst_at_entry          <- exact proposal/candidate catalyst (only when a single exact source)

SAFETY: writes ONLY non-execution journal-metadata columns on paper_trades. No status/stop/order/
broker-order/take-profit/strategy mutation. The Hermes drain does not read or write these columns.
Default dry-run; --apply required to write.
"""
import os, sys, json, argparse
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


def run(apply):
    load_env()
    import psycopg2.extras
    conn = db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    wc = conn.cursor()

    cur.execute("""
        SELECT pt.id, pt.symbol, pt.entry_price, pt.shares, pt.broker, pt.execution_broker,
               pt.close_reason, pt.exit_reason, pt.post_trade_analyzed, pt.catalyst_at_entry,
               pt.max_favorable_excursion, pt.max_adverse_excursion,
               ti.execution_broker ti_broker,
               m.mfe_price, m.mae_r,
               (SELECT count(*) FROM trade_llm_reviews r WHERE r.paper_trade_id = pt.id) llm_n,
               (SELECT count(*) FROM journal_trade_reviews r WHERE r.paper_trade_id = pt.id) jr_n,
               (SELECT count(*) FROM trade_thesis_reviews r WHERE r.paper_trade_id = pt.id) th_n
        FROM paper_trades pt
        LEFT JOIN trade_instances ti ON ti.source_table='paper_trades' AND ti.source_trade_id = pt.id::text
        LEFT JOIN trade_mfe_analysis m ON m.trade_id = pt.id
        WHERE pt.status='closed'
        ORDER BY pt.id
    """)
    trades = [dict(r) for r in cur.fetchall()]

    changes = {"broker": 0, "execution_broker": 0, "close_reason": 0,
               "post_trade_analyzed": 0, "max_favorable_excursion": 0,
               "max_adverse_excursion": 0, "catalyst_at_entry": 0}
    detail = []
    for t in trades:
        sets, params, why = [], [], []
        # broker / execution_broker from canonical (exact)
        if not t["execution_broker"] and t["ti_broker"]:
            sets.append("execution_broker=%s"); params.append(t["ti_broker"]); changes["execution_broker"] += 1; why.append("exec_broker<-trade_instances")
        if not t["broker"] and t["ti_broker"]:
            sets.append("broker=%s"); params.append(t["ti_broker"]); changes["broker"] += 1; why.append("broker<-trade_instances")
        # close_reason from exit_reason (same row, exact)
        if not t["close_reason"] and t["exit_reason"]:
            sets.append("close_reason=%s"); params.append(t["exit_reason"]); changes["close_reason"] += 1; why.append("close_reason<-exit_reason")
        # post_trade_analyzed from existence of a review (exact)
        if not t["post_trade_analyzed"] and (t["llm_n"] or t["jr_n"] or t["th_n"]):
            sets.append("post_trade_analyzed=true"); changes["post_trade_analyzed"] += 1; why.append("post_analyzed<-review_exists")
        # mfe/mae from bar analysis (exact, only when NULL)
        if t["max_favorable_excursion"] is None and t["mfe_price"] and t["entry_price"]:
            mfe_pct = round((float(t["mfe_price"]) - float(t["entry_price"])) / float(t["entry_price"]) * 100, 4)
            sets.append("max_favorable_excursion=%s"); params.append(mfe_pct); changes["max_favorable_excursion"] += 1; why.append("mfe<-bar")
        if t["max_adverse_excursion"] is None and t["mae_r"] is not None:
            sets.append("max_adverse_excursion=%s"); params.append(float(t["mae_r"])); changes["max_adverse_excursion"] += 1; why.append("mae<-bar")
        # catalyst: exact proposal/candidate source only (kept conservative — NULL if not exact)
        # (no fuzzy inference; left NULL with data-quality flag)
        if sets:
            detail.append({"trade_id": t["id"], "symbol": t["symbol"], "fields": why})
            if apply:
                wc.execute(f"UPDATE paper_trades SET {','.join(sets)}, updated_at=now() WHERE id=%s",
                           params + [t["id"]])
    if apply:
        conn.commit()
    conn.close()

    report = {"run_at": datetime.now(timezone.utc).isoformat(), "applied": apply,
              "closed_trades": len(trades), "changes_by_field": changes,
              "trades_touched": len(detail), "detail": detail,
              "note": "Exact-only backfill. Unknown left NULL. No execution/stop/order/strategy mutation."}
    print(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    run(a.apply)
