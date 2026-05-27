"""stop_change_audit.py — Append-only stop-change audit via lifecycle_events."""
import json, logging
from datetime import datetime, timezone
from decimal import Decimal

log = logging.getLogger("stop_change_audit")


def safe_decimal(v):
    if v is None:
        return None
    try:
        return float(Decimal(str(v)))
    except Exception:
        return None


def safe_json(obj):
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return "{}"


def build_stop_change_payload(paper_trade_id, symbol, account, old_stop, new_stop,
                               change_type, source_script, source_actor="system",
                               reason="", stop_order_id_before=None, stop_order_id_after=None,
                               broker_confirmation=None, approved=True, strategy_id=None,
                               trailing_tier=None):
    return {
        "change_type": change_type,
        "paper_trade_id": paper_trade_id,
        "symbol": symbol,
        "account": account,
        "strategy_id": strategy_id,
        "old_stop": safe_decimal(old_stop),
        "new_stop": safe_decimal(new_stop),
        "stop_order_id_before": stop_order_id_before,
        "stop_order_id_after": stop_order_id_after,
        "source_script": source_script,
        "source_actor": source_actor,
        "reason": reason,
        "broker_confirmation": broker_confirmation,
        "approved": approved,
        "trailing_tier": trailing_tier,
        "audit_only": True,
    }


def append_stop_change_event(conn, paper_trade_id, symbol, old_stop, new_stop,
                              change_type, source_script, source_actor="system",
                              reason="", strategy_id=None, account=None,
                              stop_order_id_before=None, stop_order_id_after=None,
                              broker_confirmation=None, approved=True,
                              trailing_tier=None, dry_run=False):
    """Append a stop-change audit event to lifecycle_events. Never fails the caller."""
    payload = build_stop_change_payload(
        paper_trade_id, symbol, account, old_stop, new_stop,
        change_type, source_script, source_actor, reason,
        stop_order_id_before, stop_order_id_after,
        broker_confirmation, approved, strategy_id, trailing_tier)

    if dry_run:
        log.info(f"[DRY] stop_change {symbol} #{paper_trade_id}: {old_stop} -> {new_stop} ({change_type})")
        return True

    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO lifecycle_events
            (lifecycle_id, event_ts, stage, event_type, status, symbol, strategy_id,
             paper_trade_id, source_script, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [f"stop-{paper_trade_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
             datetime.now(timezone.utc), "stop_change", change_type,
             "recorded", symbol, strategy_id, paper_trade_id,
             source_script, safe_json(payload)])
        conn.commit()
        return True
    except Exception as e:
        log.warning(f"Stop change audit write failed (non-fatal): {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def classify_stop_change(old_stop, new_stop, source_script=None):
    """Classify a stop change type based on context."""
    if old_stop is None and new_stop is not None:
        return "initial_stop"
    if source_script and "repair" in (source_script or "").lower():
        return "repair"
    if source_script and "reconcil" in (source_script or "").lower():
        return "broker_reconcile"
    return "trailing_update"
