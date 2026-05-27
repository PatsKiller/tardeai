"""stop_change_audit.py — Log every stop-loss change to lifecycle_events.

Usage:
    from stop_change_audit import log_stop_change
    log_stop_change(conn, trade_id, symbol, old_stop, new_stop,
                    change_type='trailing_update', source='unified_stop_supervisor',
                    reason='trailing tier lock 0.5R', broker_order_id=None)
"""
import json
import logging
from datetime import datetime, timezone

log = logging.getLogger("stop_audit")


def log_stop_change(conn, trade_id: int, symbol: str, old_stop: float, new_stop: float,
                    change_type: str = "unknown", source: str = "unknown",
                    reason: str = "", broker_order_id: str = None,
                    strategy_id: str = None) -> bool:
    """Write a stop-change audit event to lifecycle_events.

    change_type values:
        initial_stop, trailing_update, repair, manual_operator,
        broker_reconcile, stop_hit, target_hit, trailing_activate
    """
    if old_stop == new_stop:
        return False

    try:
        cur = conn.cursor()
        payload = {
            "old_stop": float(old_stop) if old_stop else None,
            "new_stop": float(new_stop) if new_stop else None,
            "change_pct": round((new_stop - old_stop) / old_stop * 100, 2) if old_stop else None,
            "change_type": change_type,
            "reason": reason,
            "broker_order_id": broker_order_id,
        }
        cur.execute("""
            INSERT INTO lifecycle_events
                (lifecycle_id, event_ts, stage, event_type, status, symbol, strategy_id,
                 paper_trade_id, stop_order_id, source_script, payload)
            VALUES (
                %s, NOW(), 'stop_change', %s, 'logged', %s, %s,
                %s, %s, %s, %s
            )
        """, [
            f"stop_{trade_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            change_type, symbol, strategy_id,
            trade_id, broker_order_id, source, json.dumps(payload),
        ])
        conn.commit()
        log.info(f"[stop_audit] {symbol} #{trade_id}: ${old_stop}→${new_stop} ({change_type}, {source})")
        return True
    except Exception as e:
        log.warning(f"[stop_audit] Failed to log stop change for {symbol} #{trade_id}: {e}")
        return False
