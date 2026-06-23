#!/usr/bin/env python3
"""schwab_broker_trade_monitor.py — Post-fill monitoring for Schwab broker queue entries.

Mirrors paper_trade_monitor R-trailing logic for open paper_trades routed to Schwab accounts.
When a higher stop is warranted, requests a protective-stop MODIFY (cancel + replace) via 2FA —
the operator approves on web/Telegram before any broker write.

Schedule: */5 9-16 * * 1-5 (alongside paper_trade_monitor.py)

Usage:
    .venv/bin/python scripts/schwab_broker_trade_monitor.py
    .venv/bin/python scripts/schwab_broker_trade_monitor.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger("schwab_broker_trade_monitor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def _f(v):
    return float(v) if isinstance(v, Decimal) else v


def _get_conn():
    from session13_db import get_conn
    return get_conn()


def _fresh_quote(sym: str) -> tuple[float | None, dict]:
    try:
        from market_quote_provider import get_best_quote
        q = get_best_quote(sym) or {}
        px = q.get("last_price") or q.get("price")
        return (float(px) if px else None), q
    except Exception as e:
        log.warning(f"[{sym}] quote unavailable: {e}")
        return None, {}


def _compute_trailing_stop(db_entry: float, risk: float, r_mult: float, strategy_id: str) -> tuple[float | None, str]:
    try:
        from strategy_trailing_policy import get_trailing_policy
        policy = get_trailing_policy(strategy_id or "unknown")
        tiers = policy.get("tiers", [])
        for r_thresh, lock_r, desc in reversed(tiers):
            if r_mult >= r_thresh:
                new_stop = round(db_entry + risk * lock_r, 2)
                return new_stop, f"R={r_mult:.1f} [{policy.get('family', '?')}] ≥{r_thresh}R → {desc}"
    except ImportError:
        pass
    if r_mult >= 3.0:
        return round(db_entry + risk * 2.0, 2), f"R={r_mult:.1f} → lock 2.0R"
    if r_mult >= 2.0:
        return round(db_entry + risk * 1.0, 2), f"R={r_mult:.1f} → lock 1.0R"
    if r_mult >= 1.5:
        return round(db_entry + risk * 0.5, 2), f"R={r_mult:.1f} → lock 0.5R"
    if r_mult >= 1.0:
        return round(db_entry, 2), f"R={r_mult:.1f} → breakeven"
    return None, ""


def _pending_protective_intent(cur, trade_id: int) -> bool:
    cur.execute(
        """SELECT 1 FROM broker_order_intents boi
           JOIN broker_order_approvals boa ON boa.intent_id = boi.intent_id
           WHERE boi.intent_json->'meta'->>'strategy_id' = 'PROTECTIVE_STOP_2C'
             AND (boi.intent_json->'meta'->'signal_evidence'->>'trade_id')::text = %s
             AND boa.consumed_at IS NULL
             AND boa.expires_at > NOW()
           LIMIT 1""",
        (str(trade_id),),
    )
    return cur.fetchone() is not None


def _request_stop_modify(acct: str, sym: str, qty: int, new_stop: float, old_stop_id: str,
                         advised_stop: float, current_price: float, held_qty: float) -> dict | None:
    from brokers import protective_stop_pilot as psp
    intent = psp.build_intent(
        acct, sym, qty, "STOP", stop_price=new_stop, advised_stop=advised_stop,
        current_price=current_price, held_qty=held_qty, replace_order_id=old_stop_id,
    )
    try:
        return psp.request_2fa(intent)
    except Exception as e:
        log.error(f"[{sym}] stop-modify 2FA request failed: {e}")
        return None


def monitor(*, dry_run: bool = False) -> list[dict]:
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """SELECT id, symbol, shares, entry_price, stop_loss, planned_stop, current_stop,
                  stop_order_id, stop_type, target_1, strategy_id, target_account, account,
                  max_favorable_excursion, max_adverse_excursion, broker_order_id
           FROM paper_trades
           WHERE status = 'open'
             AND COALESCE(target_account, account, '') LIKE 'schwab%%'
             AND COALESCE(broker_order_id, '') <> ''
           ORDER BY id"""
    )
    trades = cur.fetchall()
    if not trades:
        log.info("No open Schwab broker trades to monitor")
        return []

    results = []
    for trade in trades:
        sym = str(trade["symbol"] or "").upper()
        tid = trade["id"]
        acct = trade.get("target_account") or trade.get("account") or ""
        qty = int(trade.get("shares") or 0)
        db_entry = _f(trade.get("entry_price")) or 0
        stop = _f(trade.get("current_stop") or trade.get("stop_loss") or trade.get("planned_stop")) or 0
        target = _f(trade.get("target_1")) or 0
        stop_oid = trade.get("stop_order_id")
        strategy_id = trade.get("strategy_id") or "momentum_scalp"

        price, _q = _fresh_quote(sym)
        if not price or not db_entry:
            results.append({"trade_id": tid, "symbol": sym, "action": "skip", "reason": "no quote or entry"})
            continue

        risk = abs(db_entry - stop) if stop and stop < db_entry else db_entry * 0.05
        r_mult = (price - db_entry) / risk if risk > 0 else 0
        pnl = round((price - db_entry) * qty, 2) if qty else 0

        excursion_pct = ((price - db_entry) / db_entry * 100) if db_entry else 0
        prev_mfe = _f(trade.get("max_favorable_excursion")) or 0
        prev_mae = _f(trade.get("max_adverse_excursion")) or 0
        new_mfe = max(prev_mfe, excursion_pct) if excursion_pct > 0 else prev_mfe
        new_mae = min(prev_mae, excursion_pct) if excursion_pct < 0 else prev_mae

        action = "hold"
        reason = f"R={r_mult:.1f} P&L=${pnl:+.0f}"
        new_stop = stop
        stop_type_change = None

        if target and price >= target:
            action = "target_hit"
            reason = f"TARGET HIT ${price:.2f} >= ${target:.2f}"
        elif target and db_entry and target > db_entry:
            move = target - db_entry
            pct = (price - db_entry) / move if move > 0 else 0
            if pct >= 0.80:
                cand = round(db_entry + move * 0.65, 2)
                if cand > stop:
                    new_stop = cand
                    action = "tighten_near_target"
                    reason = f"NEAR TARGET ({pct*100:.0f}%) → stop ${new_stop:.2f}"
        else:
            cand, tier_reason = _compute_trailing_stop(db_entry, risk, r_mult, strategy_id)
            if cand and cand > stop:
                new_stop = cand
                action = "adjust_stop"
                reason = tier_reason

        # Stop type: fixed → trailing when strategy recommends trail and stop has ratcheted above entry
        if (trade.get("stop_type") or "fixed").lower() != "trailing" and new_stop > db_entry and r_mult >= 1.5:
            try:
                from strategy_trailing_policy import get_trailing_policy
                pol = get_trailing_policy(strategy_id)
                if pol.get("prefer_trailing_after_lock"):
                    stop_type_change = "TRAILING_STOP"
            except Exception:
                pass

        if not dry_run:
            cur.execute(
                """UPDATE paper_trades SET current_price=%s, r_multiple=%s, unrealized_pnl=%s,
                          max_favorable_excursion=%s, max_adverse_excursion=%s, monitored_at=NOW(),
                          updated_at=NOW() WHERE id=%s""",
                [price, round(r_mult, 2), pnl, new_mfe, new_mae, tid],
            )
            conn.commit()

        if action in ("adjust_stop", "tighten_near_target") and new_stop > stop and stop_oid:
            if _pending_protective_intent(cur, tid):
                results.append({"trade_id": tid, "symbol": sym, "action": "pending_2fa",
                                  "reason": "stop adjust already awaiting approval"})
                continue
            if dry_run:
                results.append({"trade_id": tid, "symbol": sym, "action": action,
                                  "new_stop": new_stop, "old_stop": stop, "reason": reason, "dry_run": True})
                continue
            req = _request_stop_modify(
                acct, sym, qty, new_stop, str(stop_oid), stop, price, float(qty),
            )
            if req and req.get("intent_id"):
                log.info(f"[{sym}] stop adjust 2FA requested: ${stop:.2f} → ${new_stop:.2f} ({reason})")
                try:
                    from alert_event_writer import save_alert_event
                    save_alert_event(
                        alert_type="strategic_alert", severity="warning",
                        source_script="schwab_broker_trade_monitor", symbol=sym,
                        raw_text=f"[schwab-monitor] {sym} stop ${stop:.2f}→${new_stop:.2f} — approve 2FA",
                        parsed_payload={"trade_id": tid, "intent_id": req["intent_id"],
                                        "old_stop": stop, "new_stop": new_stop, "reason": reason},
                    )
                except Exception:
                    pass
                results.append({"trade_id": tid, "symbol": sym, "action": "2fa_requested",
                                  "intent_id": req["intent_id"], "new_stop": new_stop, "reason": reason})
            else:
                results.append({"trade_id": tid, "symbol": sym, "action": "2fa_failed", "reason": reason})
        elif stop_type_change:
            results.append({"trade_id": tid, "symbol": sym, "action": "stop_type_advisory",
                              "suggest": stop_type_change, "reason": "consider trailing after profit lock"})
        else:
            results.append({"trade_id": tid, "symbol": sym, "action": action, "reason": reason,
                              "r_multiple": round(r_mult, 2), "price": price})

    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    results = monitor(dry_run=args.dry_run)
    actions = [r for r in results if r.get("action") not in ("hold", "skip")]
    if actions:
        log.info(f"actions: {len(actions)}")
        for a in actions:
            log.info(f"  {a}")
    print(f"[schwab_broker_trade_monitor] {datetime.now(timezone.utc).isoformat()} — {len(results)} trades")


if __name__ == "__main__":
    main()