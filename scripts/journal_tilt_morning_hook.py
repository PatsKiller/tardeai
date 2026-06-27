#!/usr/bin/env python3
"""After losing days / tilt tags — queue Morning Brief / cockpit review item."""
from __future__ import annotations
import json
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass


def main():
    import journal_trade_in_view as tiv
    from db_adapter import _execute as q

    beh = tiv.behavioral_analytics(days=7)
    tilt = beh.get("tilt") or {}
    after_loss = beh.get("after_losing_day") or {}
    needs_review = (
        (tilt.get("trades") or 0) >= 2
        or (after_loss.get("net_pnl") or 0) < -500
        or (after_loss.get("win_rate") or 100) < 40
    )
    if not needs_review:
        print("no tilt hook needed")
        return

    rid = f"tradeinview-tilt-{date.today().isoformat()}"
    existing = q("SELECT id FROM operator_review_queue WHERE review_item_id=%s", [rid], "one")
    if existing:
        print("already queued")
        return

    title = "TradeInView: review tilt / post-loss trading"
    summary = (
        f"Tilt-tagged trades: {tilt.get('trades', 0)} (${tilt.get('net_pnl', 0):,.0f}). "
        f"After losing days: {after_loss.get('trades', 0)}t, {after_loss.get('win_rate', 0)}% WR, "
        f"${after_loss.get('net_pnl', 0):,.0f}. Annotate recent trades and review Exit Intel."
    )
    q("""
        INSERT INTO operator_review_queue
          (review_item_id, source_domain, source_table, title, summary, severity, review_type,
           status, requires_action, action_label, action_url, linked_dashboard_route, payload)
        VALUES (%s, 'trade_in_view', 'journal_trade_reviews', %s, %s, 'warning', 'tilt_review',
                'open', true, 'Open TradeInView', '/v3/trade-in-view', '/v3/trade-in-view', %s::jsonb)
    """, [rid, title, summary, json.dumps({"tilt": tilt, "after_losing_day": after_loss})], "none")
    print(f"queued {rid}")


if __name__ == "__main__":
    main()