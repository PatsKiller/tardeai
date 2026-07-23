#!/usr/bin/env python3
"""Watch Desk operator-alert evaluation pass.

Deterministic conditions over data that already exists. Fires into alert_events
with daily dedupe and sends ONE batched Telegram per pass under the shared daily
cap. Re-Entry exit detail, rotation-back composite monitors, and closed-session
resistance intelligence are refreshed in this same RTH lane.

Advisory only: no proposal, approval, broker order, or 2FA path is reachable.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

CFG_PATH = ROOT / "config" / "watch_alerts.json"


def _cfg():
    try:
        return json.loads(CFG_PATH.read_text())
    except Exception:
        return {"daily_cap": 12}


def _evaluate_single_condition_alerts(ex, alerts, today: str) -> tuple[list[str], list[int]]:
    lines: list[str] = []
    fired_ids: list[int] = []
    for alert in alerts:
        uid = f"watch_alert:{alert['id']}:{today}"
        if ex("SELECT 1 FROM alert_events WHERE alert_uid=%s LIMIT 1", (uid,), fetch="one"):
            continue
        if alert.get("last_fired_at") and not alert.get("recurring"):
            continue
        if alert.get("recurring") and alert.get("last_fired_at"):
            cooldown = int(alert.get("cooldown_days") or 5)
            days = (dt.datetime.now(dt.timezone.utc) - alert["last_fired_at"]).days
            if days < cooldown * 1.4:  # trading-day approximation
                continue
        symbol = (alert.get("symbol") or "").upper()
        condition = alert["condition_type"]
        threshold = alert.get("threshold")
        hit, current = False, None
        if condition in ("price_cross_above", "price_cross_below") and symbol and threshold is not None:
            quote = ex(
                "SELECT price FROM market_quotes WHERE upper(symbol)=%s ORDER BY fetched_at DESC LIMIT 1",
                (symbol,), fetch="one",
            )
            current = float(quote["price"]) if quote and quote.get("price") else None
            hit = current is not None and (
                current >= float(threshold) if condition.endswith("above") else current <= float(threshold)
            )
        elif condition in ("rsi_above", "rsi_below") and symbol and threshold is not None:
            row = ex(
                """SELECT rsi FROM watchlist_items
                   WHERE upper(symbol)=%s AND rsi IS NOT NULL
                   ORDER BY first_seen_at DESC LIMIT 1""",
                (symbol,), fetch="one",
            )
            current = float(row["rsi"]) if row and row.get("rsi") is not None else None
            hit = current is not None and (
                current >= float(threshold) if condition.endswith("above") else current <= float(threshold)
            )
        elif condition == "directive_hit" and alert.get("directive_id"):
            row = ex(
                """SELECT count(*) AS n FROM watch_directive_hits
                   WHERE directive_id=%s
                     AND surfaced_at > COALESCE(%s, now() - interval '1 day')""",
                (alert["directive_id"], alert.get("last_fired_at")), fetch="one",
            )
            current = (row or {}).get("n") or 0
            hit = current > 0
        if not hit:
            continue
        message = (
            f"🔔 {symbol or ('directive #' + str(alert.get('directive_id')))} · "
            f"{condition.replace('_', ' ')} {threshold if threshold is not None else ''} · "
            f"now {current} · open Pullback/Watchlist card"
        )
        ex(
            """INSERT INTO alert_events
               (alert_uid, alert_type, symbol, severity, source_script, raw_text, created_at)
               VALUES (%s,'watch_alert',%s,'info','watch_alerts_eval',%s,NOW())
               ON CONFLICT (alert_uid) DO NOTHING""",
            (uid, symbol or None, message), fetch=None,
        )
        ex(
            "UPDATE watch_alerts SET last_fired_at=NOW(), active=%s WHERE id=%s",
            (bool(alert.get("recurring")), alert["id"]), fetch=None,
        )
        lines.append(message)
        fired_ids.append(alert["id"])
    return lines, fired_ids


def main() -> int:
    from db_adapter import _execute as ex, USE_DB
    if not USE_DB:
        return 2

    today = dt.date.today().isoformat()
    cap = int(_cfg().get("daily_cap") or 12)
    sent_today = (
        ex(
            """SELECT count(*) AS n FROM alert_events
               WHERE alert_type='watch_alert' AND created_at::date=CURRENT_DATE""",
            fetch="one",
        ) or {}
    ).get("n") or 0

    alerts = ex("SELECT * FROM watch_alerts WHERE active", fetch="all") or []
    lines, fired_ids = _evaluate_single_condition_alerts(ex, alerts, today)

    exit_count = 0
    try:
        from lib.reentry_exit_cache import refresh_exit_cache
        exit_payload = refresh_exit_cache(ex)
        exit_count = int((exit_payload.get("counts") or {}).get("exits_found") or 0)
    except Exception as error:
        print(f"[watch-alerts] re-entry exit-cache refresh error: {str(error)[:200]}")

    resistance_count = 0
    try:
        from lib.reentry_resistance import refresh_resistance_cache
        resistance = refresh_resistance_cache(ex)
        resistance_count = int(resistance.get("symbol_count") or 0)
    except Exception as error:
        print(f"[watch-alerts] re-entry resistance refresh error: {str(error)[:200]}")

    # Re-Entry v4: the six mandatory return-to-growth gates are recomputed from
    # primary DB evidence on every scheduled pass. The helper persists the same
    # alert_events evidence and returns lines for this shared Telegram batch.
    try:
        from lib.reentry_rotation_alerts import evaluate_armed_rotation_alerts
        composite = evaluate_armed_rotation_alerts(ex, today=today)
    except Exception as error:
        composite = {"lines": [], "fired": [], "error": str(error)[:200]}
        print(f"[watch-alerts] re-entry composite evaluator error: {composite['error']}")
    lines.extend(composite.get("lines") or [])

    if lines:
        room = max(0, cap - sent_today)
        shown = lines[:room]
        message = "🔔 Watch alerts\n" + "\n".join(shown)
        if len(lines) > len(shown):
            message += f"\n…and {len(lines) - len(shown)} more (daily cap {cap}; in next digest)"
        try:
            from telegram_alert import send_telegram
            send_telegram(message, bypass_router=True)
        except Exception:
            pass

    print(
        f"[watch-alerts] {len(alerts)} single-condition armed · "
        f"{len(fired_ids)} fired: {fired_ids} · "
        f"{len(composite.get('fired') or [])} re-entry composites fired: "
        f"{composite.get('fired') or []} · "
        f"{exit_count} full exit rows refreshed · "
        f"{resistance_count} resistance rows refreshed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
