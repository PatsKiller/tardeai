# Source Export: scripts/proposal_monitor.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/proposal_monitor.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `8d43b3ab4d5b8d15fb6d54ec708aae3d61aa85fc99e869db99461d5d6bf918f5` |
| **File Size** | 10440 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""proposal_monitor.py — AH/PM/market-hours proposal lifecycle monitoring.

For each pending proposal: checks current price, entry zone validity,
overnight news, and updates lifecycle status. Extends expiry if valid.
Never approves or submits orders.

Usage:
    .venv/bin/python scripts/proposal_monitor.py --pending --dry-run
    .venv/bin/python scripts/proposal_monitor.py --pending --apply
    .venv/bin/python scripts/proposal_monitor.py --symbol HIMX --apply
    .venv/bin/python scripts/proposal_monitor.py --include-intraday --apply
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
from proposal_lifecycle import (
    evaluate_lifecycle_status, get_expiry_hours, is_intraday, is_overnight,
    get_timeframe_class, get_price_drift_threshold, get_max_expiry_hours,
)

log = logging.getLogger("proposal_monitor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

EXTENSION_HOURS = 24  # extend by 24h when valid


def get_pending_proposals(conn, symbol=None, include_intraday=False):
    cur = conn.cursor()
    q = """
        SELECT id, symbol, strategy_id, proposed_entry, proposed_stop,
               proposed_target1, proposed_shares, status, created_at,
               expires_at, max_expires_at, base_expires_at,
               expiry_extended_count, lifecycle_status
        FROM paper_trade_proposals
        WHERE status = 'PENDING'
    """
    params = []
    if symbol:
        q += " AND symbol = %s"
        params.append(symbol.upper())
    if not include_intraday:
        q += " AND strategy_id NOT IN ('momentum_scalp', 'gap_and_go')"
    q += " ORDER BY created_at DESC"
    cur.execute(q, params)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return rows


def get_news_count(conn, symbol, hours=24):
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM news_articles
            WHERE symbol = %s AND published_at > NOW() - INTERVAL '%s hours'
        """, [symbol, hours])
        count = cur.fetchone()[0]
        cur.close()
        return count
    except Exception:
        return 0


def write_lifecycle_event(conn, proposal, event_type, lifecycle_status,
                          current_price, quote_result, news_count,
                          expiry_before=None, expiry_after=None, message=""):
    try:
        entry_price = float(proposal.get("proposed_entry") or 0)
        drift = ((current_price - entry_price) / entry_price * 100) if current_price and entry_price else None
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO proposal_lifecycle_events
                (proposal_id, symbol, strategy_id, event_type, lifecycle_status,
                 current_price, entry_price, price_drift_pct,
                 quote_provider, quote_is_delayed, quote_execution_eligible,
                 news_count, expiry_before, expiry_after, message, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, [
            proposal["id"], proposal["symbol"], proposal.get("strategy_id"),
            event_type, lifecycle_status,
            current_price, entry_price, round(drift, 2) if drift else None,
            quote_result.get("provider") if quote_result else None,
            quote_result.get("is_delayed") if quote_result else None,
            quote_result.get("is_execution_eligible") if quote_result else None,
            news_count, expiry_before, expiry_after, message,
            json.dumps({"quote_provider": quote_result.get("provider") if quote_result else None}, default=str),
        ])
        conn.commit()
    except Exception as e:
        log.warning(f"Failed to write lifecycle event: {e}")
        try:
            conn.rollback()
        except Exception:
            pass


def monitor_proposal(conn, proposal, apply=False):
    """Monitor a single proposal. Returns result dict."""
    symbol = proposal["symbol"]
    strategy_id = proposal.get("strategy_id", "momentum_scalp")
    entry_price = float(proposal.get("proposed_entry") or 0)

    # Get current quote
    from market_quote_provider import get_best_quote
    quote = get_best_quote(symbol)
    current_price = quote.get("last_price")
    if current_price is None and quote.get("bid"):
        current_price = quote["bid"]

    # Get news count
    news_count = get_news_count(conn, symbol, hours=24)

    # Evaluate lifecycle
    created_at = proposal.get("created_at")
    expires_at = proposal.get("expires_at")
    max_expires_at = proposal.get("max_expires_at")

    lifecycle = evaluate_lifecycle_status(
        strategy_id, current_price, entry_price,
        created_at, expires_at, max_expires_at,
        quote_context=quote,
    )

    result = {
        "proposal_id": proposal["id"],
        "symbol": symbol,
        "strategy_id": strategy_id,
        "timeframe_class": get_timeframe_class(strategy_id),
        "current_price": current_price,
        "entry_price": entry_price,
        "drift_pct": lifecycle.get("price_drift_pct"),
        "lifecycle_status": lifecycle.get("lifecycle_status"),
        "entry_zone_status": lifecycle.get("entry_zone_status"),
        "entry_zone_valid": lifecycle.get("entry_zone_valid"),
        "message": lifecycle.get("message"),
        "can_extend": lifecycle.get("can_extend"),
        "extension_reason": lifecycle.get("extension_reason"),
        "news_count": news_count,
        "quote_provider": quote.get("provider"),
        "quote_is_delayed": quote.get("is_delayed"),
        "expires_at": str(expires_at) if expires_at else None,
        "max_expires_at": str(max_expires_at) if max_expires_at else None,
        "expiry_extended_count": proposal.get("expiry_extended_count", 0),
        "expiry_action": "unchanged",
    }

    # Extension logic
    new_expires = None
    if lifecycle.get("can_extend") and is_overnight(strategy_id):
        ext_count = proposal.get("expiry_extended_count") or 0
        max_ext_dt = max_expires_at
        if max_ext_dt:
            proposed_new = (expires_at or datetime.now(timezone.utc)) + timedelta(hours=EXTENSION_HOURS)
            if proposed_new <= max_ext_dt:
                new_expires = proposed_new
                result["expiry_action"] = "extended"
                result["expiry_extended_count"] = ext_count + 1
            else:
                result["expiry_action"] = "max_window_reached"
        else:
            result["expiry_action"] = "no_max_set"

    if apply:
        cur = conn.cursor()
        update_fields = {
            "lifecycle_status": lifecycle.get("lifecycle_status"),
            "lifecycle_message": lifecycle.get("message"),
            "entry_zone_status": lifecycle.get("entry_zone_status"),
            "entry_zone_valid": lifecycle.get("entry_zone_valid"),
            "current_price": current_price,
            "price_drift_pct": lifecycle.get("price_drift_pct"),
            "last_price_source": quote.get("provider"),
            "last_price_checked_at": datetime.now(timezone.utc),
            "last_lifecycle_check_at": datetime.now(timezone.utc),
        }

        if new_expires:
            update_fields["expires_at"] = new_expires
            update_fields["expiry_extended_count"] = (proposal.get("expiry_extended_count") or 0) + 1

        if lifecycle.get("lifecycle_status") == "ENTRY_MISSED":
            update_fields["manual_review_required"] = True

        set_clause = ", ".join(f"{k} = %s" for k in update_fields)
        vals = list(update_fields.values()) + [proposal["id"]]
        cur.execute(f"UPDATE paper_trade_proposals SET {set_clause}, updated_at=NOW() WHERE id = %s", vals)
        conn.commit()

        # Write lifecycle event
        event_type = "LIFECYCLE_MONITORED"
        if new_expires:
            event_type = "EXPIRY_EXTENDED_ENTRY_ZONE_VALID"
        elif lifecycle.get("lifecycle_status") == "ENTRY_MISSED":
            event_type = "ENTRY_MISSED"
        elif lifecycle.get("lifecycle_status") in ("EXPIRED_INTRADAY", "EXPIRED_MAX_WINDOW"):
            event_type = lifecycle["lifecycle_status"]

        write_lifecycle_event(
            conn, proposal, event_type, lifecycle.get("lifecycle_status"),
            current_price, quote, news_count,
            expires_at, new_expires or expires_at,
            lifecycle.get("message", ""),
        )

    log.info(f"  #{proposal['id']} {symbol} {strategy_id} "
             f"entry={entry_price} current={current_price} "
             f"drift={lifecycle.get('price_drift_pct')}% "
             f"status={lifecycle.get('lifecycle_status')} "
             f"zone={lifecycle.get('entry_zone_status')} "
             f"expiry={result['expiry_action']} news={news_count} "
             f"provider={quote.get('provider')}")

    return result


def main():
    parser = argparse.ArgumentParser(description="Proposal lifecycle monitor")
    parser.add_argument("--pending", action="store_true")
    parser.add_argument("--symbol", type=str)
    parser.add_argument("--include-intraday", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_conn()
    try:
        if args.pending or args.symbol:
            proposals = get_pending_proposals(conn, symbol=args.symbol,
                                              include_intraday=args.include_intraday)
        else:
            print("Usage: --pending or --symbol TICK")
            return

        if not proposals:
            print("No pending proposals found.")
            return

        log.info(f"Monitoring {len(proposals)} proposal(s)...")
        results = []
        for p in proposals:
            r = monitor_proposal(conn, p, apply=args.apply)
            results.append(r)

        print(json.dumps({"monitored": len(results), "results": results}, indent=2, default=str))

        if args.dry_run:
            print("\n(dry-run — no DB writes)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```
