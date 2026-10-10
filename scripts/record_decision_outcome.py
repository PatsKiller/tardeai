#!/usr/bin/env python3
"""record_decision_outcome.py — Record and backfill decision outcomes.

Links synthesis recommendations to actual price outcomes for learning.

Usage:
    python3 scripts/record_decision_outcome.py [--backfill] [--json] [--dry-run]

Dry run (n8n refactor wave 3, 2026-10-10): ``--dry-run`` runs ONLY the read-only selections
(``_select_decisions`` and, with ``--backfill``, ``_select_unevaluated`` + the price lookups) on a session
made READ ONLY at the server, prints a ``DRY-RUN`` report and returns; ``record_current_decisions`` and
``backfill_prices`` (the INSERT / UPDATE / commit) are not reachable from it. It writes no receipt.

A REAL run (the cron form, no flags) writes LaneRunReceipt@v1
``<state_root>/data/runtime/record-decision-outcome_last.json`` (``ok_at`` only on success). Exit codes:
0 = ran (0 new outcomes is a finding, still 0); 1 = the run failed (DB unavailable or a statement
raised -- each step is one transaction, so a failed step is not half-applied); 2 = usage error (unknown
argument; previously ignored silently).
"""
import argparse
import json, os, sys
from datetime import datetime, date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LANE_ID = "record-decision-outcome"

_DECISIONS_SQL = """
        SELECT fs.symbol, fs.recommendation, fs.confidence, fs.updated_at,
               tsc.strategy_type,
               sc.latest_price
        FROM watchlist_final_synthesis fs
        LEFT JOIN ticker_strategy_classifications tsc ON tsc.symbol = fs.symbol
        LEFT JOIN watchlist_strategy_cards sc ON sc.symbol = fs.symbol
        WHERE fs.superseded IS NOT TRUE
        AND NOT EXISTS (SELECT 1 FROM decision_outcomes dout WHERE dout.symbol = fs.symbol AND dout.created_at > fs.updated_at - INTERVAL '1 day')
    """

_UNEVALUATED_SQL = """
        SELECT dout.id, dout.symbol, dout.created_at, dout.price_at_decision
        FROM decision_outcomes dout
        WHERE dout.evaluated_at IS NULL AND dout.price_at_decision IS NOT NULL
        AND dout.created_at < NOW() - INTERVAL '1 day'
        LIMIT 100
    """


def _receipt_lib():
    try:
        from scripts.lib import lane_last_receipt as lr
    except ImportError:  # scripts/ on sys.path, repo root not
        from lib import lane_last_receipt as lr
    return lr


def _select_decisions(cur) -> list:
    """Read-only: current syntheses without an outcome record."""
    cur.execute(_DECISIONS_SQL)
    return cur.fetchall()


def _select_unevaluated(cur) -> list:
    """Read-only: outcome records awaiting a price backfill."""
    cur.execute(_UNEVALUATED_SQL)
    return cur.fetchall()


def _price_points(cur, sym, decision_date) -> dict:
    """Read-only: closes nearest +1d/+7d/+30d from ticker_prices."""
    prices = {}
    for label, delta in [("1d", 1), ("7d", 7), ("30d", 30)]:
        target_date = decision_date + timedelta(days=delta)
        cur.execute("""
            SELECT close_price FROM ticker_prices
            WHERE symbol=%s AND price_date BETWEEN %s AND %s
            ORDER BY ABS(price_date - %s::date) LIMIT 1
        """, (sym, target_date - timedelta(days=3), target_date + timedelta(days=3), target_date))
        r = cur.fetchone()
        if r:
            prices[label] = float(r["close_price"])
    return prices


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def record_current_decisions(real_only: bool = True) -> int:
    """Record all current actionable synthesis decisions for real outcome tracking."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Find syntheses without outcome records
    decisions = _select_decisions(cur)

    recorded = 0
    for d in decisions:
        cur.execute("""
            INSERT INTO decision_outcomes
                (symbol, strategy_type, recommendation, price_at_decision, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (d["symbol"], d.get("strategy_type"), d["recommendation"],
              float(d["latest_price"]) if d.get("latest_price") else None,
              d["updated_at"]))
        recorded += 1

    conn.commit()
    conn.close()
    print(f"[outcomes] Recorded {recorded} new decision outcomes")
    return recorded


def backfill_prices(days: int = 30) -> int:
    """Backfill price outcomes for existing decision records."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    outcomes = _select_unevaluated(cur)

    updated = 0
    for o in outcomes:
        sym = o["symbol"]
        decision_date = o["created_at"].date() if hasattr(o["created_at"], "date") else o["created_at"]

        # Try to get prices at +1d, +7d, +30d from ticker_prices
        prices = _price_points(cur, sym, decision_date)

        if prices:
            p_at = float(o["price_at_decision"] or 0)
            p_1d = prices.get("1d")
            p_7d = prices.get("7d")
            p_30d = prices.get("30d")

            # Compute simple outcome score: did price go in recommended direction?
            outcome_score = None
            if p_7d and p_at > 0:
                change_pct = (p_7d - p_at) / p_at * 100
                # Positive score if BUY/ADD and price went up, or SELL/TRIM and price went down
                outcome_score = change_pct  # Simple: positive = good for BUY, bad for SELL

            cur.execute("""
                UPDATE decision_outcomes
                SET price_1d = %s, price_7d = %s, price_30d = %s,
                    outcome_score = %s, evaluated_at = NOW()
                WHERE id = %s
            """, (p_1d, p_7d, p_30d, outcome_score, o["id"]))
            updated += 1

    conn.commit()
    conn.close()
    print(f"[outcomes] Backfilled {updated} price outcomes")
    return updated


def dry_run(backfill: bool) -> dict:
    """Read-only preview. ``record_current_decisions`` / ``backfill_prices`` are not reachable from here."""
    import psycopg2.extras
    lr = _receipt_lib()
    conn = _get_conn()
    lr.enforce_readonly(conn)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    decisions = _select_decisions(cur)
    out = {"would_record": len(decisions),
           "would_record_no_price": sum(1 for d in decisions if not d.get("latest_price"))}
    print(f"[outcomes] DRY-RUN would record {len(decisions)} new decision outcomes")
    if backfill:
        outcomes = _select_unevaluated(cur)
        priced = 0
        for o in outcomes:
            dd = o["created_at"].date() if hasattr(o["created_at"], "date") else o["created_at"]
            if _price_points(cur, o["symbol"], dd):
                priced += 1
        out.update(unevaluated=len(outcomes), would_backfill=priced)
        print(f"[outcomes] DRY-RUN would backfill {priced} of {len(outcomes)} price outcomes")
    conn.close()
    would_write = ["decision_outcomes (INSERT) x would_record"]
    if backfill:
        would_write.append("decision_outcomes (UPDATE price_*/evaluated_at) x would_backfill")
    lr.dry_run_report(LANE_ID, out, would_write=would_write)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Record and backfill decision outcomes")
    ap.add_argument("--backfill", action="store_true", help="also backfill +1d/+7d/+30d prices")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="read-only preview; writes nothing")
    args = ap.parse_args(argv)

    if args.dry_run:
        out = dry_run(args.backfill)
        if args.json:
            print(json.dumps(out, indent=2))
        return 0

    from datetime import timezone
    lr = _receipt_lib()
    started = datetime.now(timezone.utc).isoformat()
    summary: dict = {}
    try:
        summary["recorded"] = record_current_decisions()
        if args.backfill:
            summary["backfilled"] = backfill_prices()
    except Exception as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="record_decision_outcome.py", summary=summary,
                              error=f"{type(exc).__name__}: {exc}")
        raise
    if args.json:
        print(json.dumps({"recorded": summary["recorded"]}, indent=2))
    lr.write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=started,
                          script="record_decision_outcome.py", summary=summary)
    return 0


if __name__ == "__main__":
    ROOT = PROJECT_ROOT
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    sys.exit(main())
