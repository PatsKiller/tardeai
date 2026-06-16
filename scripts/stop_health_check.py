#!/usr/bin/env python3
"""Stop Health Check (Stage 2c) — the HEALTH-AGENT face of the stop lifecycle monitor.

Runs the stop_lifecycle_monitor scan, persists the snapshot, and escalates any alert-worthy stop condition
through the SAME surfaces the rest of the system uses:
  • SIEM      : save_alert_event(source_script='stop_health', ...) — visible in the security/alerts feed
                and consumable by Hermes (which reads alert_events per symbol).
  • Telegram  : central alert router (telegram_alert.send_telegram) — NEVER a direct bypass.
  • health log: system_health_events row so the system_health_agent watchdog sees this check ran.

Alert conditions (per the engine's health=alert): ORPHANED (a live stop with no matching holding —
on trigger it could short / reject), OVERSIZED (stop qty > shares held — a GTC stop does NOT auto-resize
when you trim), FILLED/TRIGGERED (the stop fired — the position may be flat now), and NEAR-TRIGGER within
0.75% (about to fire). Dedup: one Telegram per (symbol, condition) per 2h via the SIEM event history.

Run on cron during market hours (read-only on the broker side):
  python3 scripts/stop_health_check.py [--quiet]
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

_COMPONENT = "stop_health"


def _send_telegram(msg: str) -> bool:
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
        return True
    except Exception:
        return False


def _siem(symbol: str, severity: str, text: str, payload: dict) -> None:
    try:
        from alert_event_writer import save_alert_event
        save_alert_event(alert_type="strategic_alert", severity=severity, source_script=_COMPONENT,
                         symbol=symbol or "", raw_text=text, parsed_payload=payload)
    except Exception:
        pass


def _recently_alerted(symbol: str, condition: str, hours: int = 2) -> bool:
    """Dedup via alert_events: True if the same (symbol, condition) fired in the last `hours`."""
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("""SELECT 1 FROM alert_events
                       WHERE source_script=%s AND symbol=%s AND raw_text LIKE %s
                         AND created_at > NOW() - INTERVAL '%s hours' LIMIT 1""",
                    (_COMPONENT, symbol, f"%{condition}%", hours))
        return cur.fetchone() is not None
    except Exception:
        return False   # fail open ⇒ we alert (better a dup than a miss on a safety signal)


def _hermes_finding(symbol: str, condition: str, line: str, payload: dict) -> None:
    """Write the stop-health condition into Hermes' research stream so Hermes 'monitors' it — it surfaces
    on the Open Trades card's Hermes section and in the Hermes hub, same as any research finding."""
    conn = None
    try:
        import json
        from db_adapter import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        # research_type='stop_health' is the identity; thesis_type/status must satisfy the table's CHECKs
        # (thesis_type ∈ bullish/bearish/neutral/mixed → 'neutral'; status ∈ staged/.. → 'staged').
        cur.execute("""INSERT INTO hermes_research_intelligence
            (source, hermes_agent_name, research_type, symbol, topic, summary, thesis, thesis_type,
             evidence_json, confidence_score, model_used, status, category_lifecycle, freshness_date, created_at)
            VALUES (%s,%s,'stop_health',%s,%s,%s,%s,'neutral',%s::jsonb,%s,'stop_lifecycle_monitor',
                    'staged','stop', CURRENT_DATE, NOW())""",
            ("hermes", "StopHealthMonitor", symbol, f"Stop health: {condition}",
             f"{condition} — {line}", line, json.dumps(payload), 0.95))
        conn.commit()
    except Exception:
        if conn is not None:
            try:
                conn.rollback()   # never leave the shared connection in an aborted txn
            except Exception:
                pass


def _log_health_event(ok: bool, summary: dict) -> None:
    try:
        from db_adapter import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS system_health_events (
                         id SERIAL PRIMARY KEY, component TEXT, event_type TEXT, severity TEXT,
                         message TEXT, action_taken TEXT, success BOOLEAN, created_at TIMESTAMPTZ DEFAULT NOW())""")
        cur.execute("""INSERT INTO system_health_events (component, event_type, severity, message, success)
                       VALUES (%s,'STOP_HEALTH_SCAN',%s,%s,%s)""",
                    (_COMPONENT, "WARN" if not ok else "INFO",
                     f"{summary.get('total')} stops · health {summary.get('by_health')}", ok))
        conn.commit()
    except Exception:
        pass


def run(quiet: bool = False) -> dict:
    import stop_lifecycle_monitor as slm
    res = slm.scan(persist=True)
    summary, alerts = res["summary"], res["alerts"]
    fired = []
    for r in alerts:
        sym, acct = r["symbol"], r["account"]
        # the single most severe condition for the message
        if "orphaned" in r["flags"]:
            cond, sev, line = "ORPHANED", "high", f"stop with no matching {acct} holding (#{r['order_id']}) — on trigger it could short/reject. Cancel it."
        elif "oversized" in r["flags"]:
            cond, sev, line = "OVERSIZED", "high", f"stop covers {r['qty']} sh but you hold {r['held_qty']} — modify to {r['held_qty']} sh."
        elif "filled" in r["flags"]:
            cond, sev, line = "TRIGGERED", "high", f"stop FILLED (#{r['order_id']}) — position may be flat; review."
        else:
            cond, sev, line = "NEAR_TRIGGER", "medium", f"price within {r.get('proximity_pct')}% of stop ${r.get('stop_price')} — about to fire."
        payload = {"kind": "stop_health", "condition": cond, **{k: r.get(k) for k in
                   ("account", "symbol", "broker", "order_id", "order_type", "stop_price", "qty",
                    "held_qty", "current_price", "proximity_pct", "coverage", "lifecycle", "health")}}
        _siem(sym, sev, f"[stop-health] {cond} · {sym}@{acct} · {line}", payload)
        if not _recently_alerted(sym, cond):
            _send_telegram(f"{'🚨' if sev == 'high' else '⚠️'} STOP HEALTH — {cond}: *{sym}* ({acct})\n{line}")
            _hermes_finding(sym, cond, line, payload)   # enter Hermes' research stream (deduped via the same 2h window)
            fired.append(f"{sym}:{cond}")
    _log_health_event(ok=(not alerts), summary=summary)
    if not quiet:
        print(f"stop_health: {summary['total']} stops · health {summary['by_health']} · "
              f"alerts {len(alerts)} · telegram fired {fired or 'none'}")
    return {"summary": summary, "alert_count": len(alerts), "telegram_fired": fired}


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(str(PROJECT_ROOT / ".env"))
    run(quiet="--quiet" in sys.argv)
