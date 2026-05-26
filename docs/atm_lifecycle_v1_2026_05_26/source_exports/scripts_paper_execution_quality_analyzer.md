# Source Export: scripts/paper_execution_quality_analyzer.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/paper_execution_quality_analyzer.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `c00eff4374180bbd54c40f52e9819c9b3fc53e8f42c222364d61015d3527e8c4` |
| **File Size** | 11040 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""paper_execution_quality_analyzer.py — TCA: paper trade execution quality analysis.

Computes slippage, fill quality, and arrival-price analysis for paper trades.
Inserts results into paper_execution_quality table.

PAPER ONLY. No live trading.

Usage:
    .venv/bin/python scripts/paper_execution_quality_analyzer.py --recent --dry-run
    .venv/bin/python scripts/paper_execution_quality_analyzer.py --recent --apply
    .venv/bin/python scripts/paper_execution_quality_analyzer.py --paper-trade-id 123 --apply
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from session13_db import get_conn
from local_llm_config import get_local_llm_model  # noqa: F401

log = logging.getLogger("execution_quality")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# Fill quality thresholds (absolute slippage %)
QUALITY_THRESHOLDS = [
    (0.05, "EXCELLENT"),
    (0.15, "GOOD"),
    (0.50, "ACCEPTABLE"),
]


def classify_fill_quality(slippage_pct):
    """Classify fill quality based on slippage percentage."""
    if slippage_pct is None:
        return "UNKNOWN"
    abs_slip = abs(slippage_pct)
    for threshold, label in QUALITY_THRESHOLDS:
        if abs_slip < threshold:
            return label
    return "POOR"


def get_recent_paper_trades(conn, days=7, paper_trade_id=None):
    """Fetch recent paper trades not yet analyzed for execution quality."""
    cur = conn.cursor()
    if paper_trade_id:
        cur.execute("""
            SELECT pt.id, pt.symbol, pt.strategy_id, pt.proposal_id,
                   pt.entry_price, pt.planned_entry, pt.entry_time,
                   pt.broker_order_id, pt.shares, pt.dollar_size,
                   pt.stop_loss, pt.target_1, pt.account
            FROM paper_trades pt
            WHERE pt.id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM paper_execution_quality peq
                  WHERE peq.paper_trade_id = pt.id
              )
        """, [paper_trade_id])
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cur.execute("""
            SELECT pt.id, pt.symbol, pt.strategy_id, pt.proposal_id,
                   pt.entry_price, pt.planned_entry, pt.entry_time,
                   pt.broker_order_id, pt.shares, pt.dollar_size,
                   pt.stop_loss, pt.target_1, pt.account
            FROM paper_trades pt
            WHERE pt.created_at >= %s
              AND NOT EXISTS (
                  SELECT 1 FROM paper_execution_quality peq
                  WHERE peq.paper_trade_id = pt.id
              )
            ORDER BY pt.created_at DESC
        """, [cutoff])

    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_evidence_snapshot(conn, proposal_id):
    """Get evidence snapshot for a proposal at submit time."""
    if not proposal_id:
        return None
    cur = conn.cursor()
    cur.execute("""
        SELECT quote_snapshot, execution_snapshot
        FROM proposal_evidence_snapshots
        WHERE proposal_id = %s
        ORDER BY created_at ASC
        LIMIT 1
    """, [proposal_id])
    row = cur.fetchone()
    if not row:
        return None
    return {"quote_snapshot": row[0], "execution_snapshot": row[1]}


def get_market_quote_at_submit(conn, symbol, entry_time):
    """Get the closest market quote snapshot near entry time."""
    if not entry_time:
        return None
    cur = conn.cursor()
    cur.execute("""
        SELECT last_price, bid, ask, spread_pct, provider
        FROM market_quote_snapshots
        WHERE symbol = %s
          AND created_at <= %s
        ORDER BY created_at DESC
        LIMIT 1
    """, [symbol, entry_time])
    row = cur.fetchone()
    if not row:
        return None
    return {
        "last_price": float(row[0]) if row[0] else None,
        "bid": float(row[1]) if row[1] else None,
        "ask": float(row[2]) if row[2] else None,
        "spread_pct": float(row[3]) if row[3] else None,
        "provider": row[4],
    }


def analyze_trade(conn, trade):
    """Compute execution quality metrics for a single paper trade."""
    tid = trade["id"]
    symbol = trade["symbol"]
    proposal_id = trade.get("proposal_id")
    fill_price = float(trade["entry_price"]) if trade.get("entry_price") else None
    intended_entry = float(trade["planned_entry"]) if trade.get("planned_entry") else fill_price
    shares = int(trade["shares"]) if trade.get("shares") else 0

    # Get evidence and quote snapshots
    evidence = get_evidence_snapshot(conn, proposal_id)
    quote = get_market_quote_at_submit(conn, symbol, trade.get("entry_time"))

    # Determine arrival price (market price at time of submission)
    arrival_price = None
    quote_bid = None
    quote_ask = None
    spread_pct = None

    if quote:
        arrival_price = quote.get("last_price")
        quote_bid = quote.get("bid")
        quote_ask = quote.get("ask")
        spread_pct = quote.get("spread_pct")
    elif evidence and evidence.get("quote_snapshot"):
        qs = evidence["quote_snapshot"]
        if isinstance(qs, dict):
            arrival_price = qs.get("last_price") or qs.get("price")
            quote_bid = qs.get("bid")
            quote_ask = qs.get("ask")
            spread_pct = qs.get("spread_pct")

    # If no fill data, mark UNKNOWN
    if fill_price is None:
        return {
            "paper_trade_id": tid,
            "proposal_id": proposal_id,
            "symbol": symbol,
            "strategy_id": trade.get("strategy_id"),
            "order_id": trade.get("broker_order_id"),
            "intended_entry": intended_entry,
            "fill_price": None,
            "arrival_price": arrival_price,
            "quote_bid": quote_bid,
            "quote_ask": quote_ask,
            "spread_pct": spread_pct,
            "slippage_pct": None,
            "slippage_dollars": None,
            "fill_quality": "UNKNOWN",
            "tca_payload": {"reason": "no_fill_data"},
        }

    # Compute slippage
    slippage_pct = None
    slippage_dollars = None

    if intended_entry and intended_entry > 0:
        slippage_pct = round(((fill_price - intended_entry) / intended_entry) * 100, 4)
        slippage_dollars = round((fill_price - intended_entry) * shares, 2) if shares else None
    elif arrival_price and arrival_price > 0:
        slippage_pct = round(((fill_price - arrival_price) / arrival_price) * 100, 4)
        slippage_dollars = round((fill_price - arrival_price) * shares, 2) if shares else None

    fill_quality = classify_fill_quality(slippage_pct)

    liquidity = {}
    if quote_bid and quote_ask:
        liquidity["bid"] = quote_bid
        liquidity["ask"] = quote_ask
        if spread_pct:
            liquidity["spread_pct"] = spread_pct

    return {
        "paper_trade_id": tid,
        "proposal_id": proposal_id,
        "symbol": symbol,
        "strategy_id": trade.get("strategy_id"),
        "order_id": trade.get("broker_order_id"),
        "intended_entry": intended_entry,
        "fill_price": fill_price,
        "arrival_price": arrival_price,
        "quote_bid": quote_bid,
        "quote_ask": quote_ask,
        "spread_pct": spread_pct,
        "slippage_pct": slippage_pct,
        "slippage_dollars": slippage_dollars,
        "fill_quality": fill_quality,
        "liquidity_context": liquidity or None,
        "tca_payload": {
            "intended_entry": intended_entry,
            "fill_price": fill_price,
            "arrival_price": arrival_price,
            "slippage_pct": slippage_pct,
            "fill_quality": fill_quality,
        },
    }


def insert_result(conn, result):
    """Insert execution quality result into DB."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO paper_execution_quality
            (paper_trade_id, proposal_id, symbol, strategy_id, order_id,
             intended_entry, fill_price, arrival_price,
             quote_bid, quote_ask, spread_pct,
             slippage_pct, slippage_dollars, fill_quality,
             liquidity_context, tca_payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """, [
        result["paper_trade_id"], result.get("proposal_id"),
        result["symbol"], result.get("strategy_id"), result.get("order_id"),
        result.get("intended_entry"), result.get("fill_price"), result.get("arrival_price"),
        result.get("quote_bid"), result.get("quote_ask"), result.get("spread_pct"),
        result.get("slippage_pct"), result.get("slippage_dollars"), result["fill_quality"],
        json.dumps(result.get("liquidity_context"), default=str) if result.get("liquidity_context") else None,
        json.dumps(result.get("tca_payload"), default=str) if result.get("tca_payload") else None,
    ])
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Paper trade execution quality analyzer (TCA)")
    parser.add_argument("--recent", action="store_true", help="Analyze recent trades (last 7 days)")
    parser.add_argument("--paper-trade-id", type=int, help="Analyze a specific paper trade by ID")
    parser.add_argument("--dry-run", action="store_true", help="Compute but do not write to DB")
    parser.add_argument("--apply", action="store_true", help="Write results to DB")
    args = parser.parse_args()

    if not args.recent and not args.paper_trade_id:
        parser.error("Specify --recent or --paper-trade-id")
    if not args.dry_run and not args.apply:
        parser.error("Specify --dry-run or --apply")

    conn = get_conn()
    try:
        trades = get_recent_paper_trades(conn, paper_trade_id=args.paper_trade_id)

        if not trades:
            output = {"status": "no_data", "message": "No paper trades to analyze", "results": []}
            print(json.dumps(output, indent=2, default=str))
            return

        results = []
        for trade in trades:
            result = analyze_trade(conn, trade)
            results.append(result)

            if args.apply:
                insert_result(conn, result)
                log.info(f"Inserted TCA for trade {result['paper_trade_id']} "
                         f"({result['symbol']}): {result['fill_quality']}")

        output = {
            "status": "dry_run" if args.dry_run else "applied",
            "trades_analyzed": len(results),
            "quality_summary": {
                q: sum(1 for r in results if r["fill_quality"] == q)
                for q in ["EXCELLENT", "GOOD", "ACCEPTABLE", "POOR", "UNKNOWN"]
            },
            "results": results,
        }
        print(json.dumps(output, indent=2, default=str))

    finally:
        conn.close()


if __name__ == "__main__":
    main()
```
