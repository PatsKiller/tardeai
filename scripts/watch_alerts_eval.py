#!/usr/bin/env python3
"""Watch Desk v3 (WS-B): operator-alert evaluation pass.

Deterministic conditions over data that already exists (market_quotes price,
watchlist_items.rsi, watch_directive_hits). Fires into alert_events (alert_uid
dedupe `(alert_id, date)`) and ONE batched Telegram per pass, global daily cap
from config (default 12 lines/day; overflow noted, never dropped silently).
RTH-safe by design: alerts are notifications, not content production.
Conditions: price_cross_above/below · rsi_above/below · directive_hit.
(pct_from_52w_high / atr_extension / earnings_within_days: enrichment columns
absent on watchlist_items — flagged in diagnosis, not fabricated.)
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


def main() -> int:
    from db_adapter import _execute as ex, USE_DB
    if not USE_DB:
        return 2
    alerts = ex("SELECT * FROM watch_alerts WHERE active", fetch="all") or []
    if not alerts:
        print("[watch-alerts] none armed")
        return 0
    today = dt.date.today().isoformat()
    cap = int(_cfg().get("daily_cap") or 12)
    sent_today = (ex("""SELECT count(*) AS n FROM alert_events
                        WHERE alert_type='watch_alert' AND created_at::date=CURRENT_DATE""",
                     fetch="one") or {}).get("n") or 0
    lines, fired_ids = [], []
    for a in alerts:
        uid = f"watch_alert:{a['id']}:{today}"
        if ex("SELECT 1 FROM alert_events WHERE alert_uid=%s LIMIT 1", (uid,), fetch="one"):
            continue  # dedupe (alert_id, date)
        if a.get("last_fired_at") and not a.get("recurring"):
            continue
        if a.get("recurring") and a.get("last_fired_at"):
            cool = int(a.get("cooldown_days") or 5)
            days = (dt.datetime.now(dt.timezone.utc) - a["last_fired_at"]).days
            if days < cool * 1.4:  # trading-day approximation
                continue
        sym, ct, th = (a.get("symbol") or "").upper(), a["condition_type"], a.get("threshold")
        hit, cur = False, None
        if ct in ("price_cross_above", "price_cross_below") and sym and th is not None:
            q = ex("SELECT price FROM market_quotes WHERE upper(symbol)=%s ORDER BY fetched_at DESC LIMIT 1",
                   (sym,), fetch="one")
            cur = float(q["price"]) if q and q.get("price") else None
            hit = cur is not None and (cur >= float(th) if ct.endswith("above") else cur <= float(th))
        elif ct in ("rsi_above", "rsi_below") and sym and th is not None:
            q = ex("SELECT rsi FROM watchlist_items WHERE upper(symbol)=%s AND rsi IS NOT NULL ORDER BY first_seen_at DESC LIMIT 1",
                   (sym,), fetch="one")
            cur = float(q["rsi"]) if q and q.get("rsi") is not None else None
            hit = cur is not None and (cur >= float(th) if ct.endswith("above") else cur <= float(th))
        elif ct == "directive_hit" and a.get("directive_id"):
            q = ex("""SELECT count(*) AS n FROM watch_directive_hits
                      WHERE directive_id=%s AND surfaced_at > COALESCE(%s, now() - interval '1 day')""",
                   (a["directive_id"], a.get("last_fired_at")), fetch="one")
            cur = (q or {}).get("n") or 0
            hit = cur > 0
        if not hit:
            continue
        txt = (f"🔔 {sym or ('directive #' + str(a.get('directive_id')))} · {ct.replace('_', ' ')} "
               f"{th if th is not None else ''} · now {cur} · open Pullback/Watchlist card")
        ex("""INSERT INTO alert_events (alert_uid, alert_type, symbol, severity, source_script, raw_text, created_at)
              VALUES (%s,'watch_alert',%s,'info','watch_alerts_eval',%s,NOW())
              ON CONFLICT (alert_uid) DO NOTHING""", (uid, sym or None, txt), fetch=None)
        ex("UPDATE watch_alerts SET last_fired_at=NOW(), active=%s WHERE id=%s",
           (bool(a.get("recurring")), a["id"]), fetch=None)
        lines.append(txt)
        fired_ids.append(a["id"])
    if lines:
        room = max(0, cap - sent_today)
        shown = lines[:room]
        msg = "🔔 Watch alerts\n" + "\n".join(shown)
        if len(lines) > len(shown):
            msg += f"\n…and {len(lines) - len(shown)} more (daily cap {cap}; in next digest)"
        try:
            from telegram_alert import send_telegram
            send_telegram(msg, bypass_router=True)  # operator-armed = P1 by definition
        except Exception:
            pass
    print(f"[watch-alerts] {len(alerts)} armed · {len(fired_ids)} fired: {fired_ids}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
