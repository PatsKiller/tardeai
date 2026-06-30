#!/usr/bin/env python3
"""stop_drift_alert.py — alert when the daily stop ADVISORY recommends RAISING a live stop.

Closes the "alert when to CHANGE a stop" gap: protection_alerts handles MISSING stops (naked / no-TP);
this handles RATCHET-UP drift — when holding_protection_advisor's advised stop sits materially ABOVE the
currently placed/monitored stop, surface an actionable "raise {SYM} {old}->{new}" alert (SIEM + Telegram).

RATCHET-UP ONLY (advised > live, and below price) — never suggests lowering a stop. ADVISORY: reads
advisories + live-stop tables, writes only alert_events; never places/modifies/cancels an order.

  python3 scripts/stop_drift_alert.py [--send]   (default: dry-run; --send routes Telegram)
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

DEDUP_HOURS = 12          # one raise-your-stop nudge per symbol per ~half-day
LIVE_STATUS = ("armed", "active", "live", "placed", "confirmed", "working", "new", "accepted", "held", "open")


def detect(cur):
    # latest advisory per symbol (last 3 days)
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, evidence_json FROM hermes_research_intelligence
                   WHERE research_type='protection_advisory' AND created_at > now()-interval '3 days'
                   ORDER BY symbol, created_at DESC""")
    advised = {}
    for sym, ev in cur.fetchall():
        ev = ev if isinstance(ev, dict) else json.loads(ev or "{}")
        rec = ev.get("recommendation") or {}; inp = ev.get("inputs") or {}
        try:
            sp = float(rec.get("stop_price")) if rec.get("stop_price") is not None else None
        except Exception:
            sp = None
        if sp:
            advised[sym.upper()] = {"stop": sp, "atr": float(inp.get("atr") or 0), "price": float(inp.get("price") or 0)}
    # live / monitored stops (max across sources)
    live = {}
    for tbl, col in (("fidelity_monitored_stops", "COALESCE(effective_stop, stop_price)"),
                     ("manual_broker_stops", "stop_price")):
        try:
            cur.execute(f"SELECT UPPER(symbol), {col} FROM {tbl} "
                        f"WHERE lower(COALESCE(status,'')) = ANY(%s) AND {col} IS NOT NULL", (list(LIVE_STATUS),))
            for sym, s in cur.fetchall():
                if s is not None:
                    live[sym] = max(live.get(sym, 0.0), float(s))
        except Exception:
            pass
    drifts = []
    for sym, a in advised.items():
        ls = live.get(sym)
        if ls is None:                                   # no live stop = "not placed" → protection_alerts' job
            continue
        thr = max(0.5 * a["atr"], 0.01 * a["price"]) if a["price"] else max(0.5 * a["atr"], 0.0)
        if a["stop"] > ls + thr and (not a["price"] or a["stop"] < a["price"]):
            drifts.append({"symbol": sym, "live_stop": round(ls, 2), "advised_stop": round(a["stop"], 2),
                           "raise_by": round(a["stop"] - ls, 2),
                           "raise_pct": round(100 * (a["stop"] - ls) / a["price"], 2) if a["price"] else None})
    return drifts


def _recently_alerted(cur, sym):
    try:
        cur.execute("""SELECT 1 FROM alert_events WHERE symbol=%s AND source_script='stop_drift_alert'
                       AND created_at > now() - %s * interval '1 hour' LIMIT 1""", (sym, DEDUP_HOURS))
        return cur.fetchone() is not None
    except Exception:
        return False


def run(send=False):
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    drifts = detect(cur)
    emitted, sent = [], 0
    for d in drifts:
        if _recently_alerted(cur, d["symbol"]):
            continue
        msg = (f"↑ Raise stop: {d['symbol']} advised stop ${d['advised_stop']} is "
               f"${d['raise_by']} above the live stop ${d['live_stop']} "
               f"({d['raise_pct']}% of price) — consider ratcheting up (advisory).")
        try:
            from alert_event_writer import save_alert_event
            save_alert_event(alert_type="strategic_alert", severity="info", source_script="stop_drift_alert",
                             symbol=d["symbol"], raw_text=msg,
                             parsed_payload={"kind": "stop_drift", **d, "advisory_only": True})
        except Exception:
            pass
        if send:
            try:
                from telegram_alert import send_telegram
                send_telegram(msg); sent += 1
            except Exception:
                pass
        emitted.append(d)
    return {"checked": len(drifts), "alerted": len(emitted), "telegram_sent": sent if send else 0,
            "drifts": emitted, "dry_run": not send, "note": "advisory only — never places/modifies a stop"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--send", action="store_true"); a = ap.parse_args()
    print(json.dumps(run(send=a.send), indent=2, default=str))


if __name__ == "__main__":
    main()
