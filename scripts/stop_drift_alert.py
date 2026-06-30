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


def detect_lockin(cur):
    """LOCK-IN drift: a position holds a LIVE FIXED stop, but a trailing stop at the advised width would
    sit ABOVE that fixed trigger right now — so switching fixed→trailing locks a higher floor and keeps
    ratcheting up. Mirrors the Portfolio-card 'Lock in profits — switch to trailing' banner. Advisory."""
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, evidence_json FROM hermes_research_intelligence
                   WHERE research_type='protection_advisory' AND created_at > now()-interval '5 days'
                   ORDER BY symbol, created_at DESC""")
    adv = {}
    for sym, ev in cur.fetchall():
        ev = ev if isinstance(ev, dict) else json.loads(ev or "{}")
        rec = ev.get("recommendation") or {}; inp = ev.get("inputs") or {}
        try:
            price = float(inp.get("price") or 0)
        except Exception:
            price = 0.0
        # trail width = explicit PERCENT offset, else the advised fixed-stop distance (same width, ratcheting)
        tpct = None
        if rec.get("trail_type") == "PERCENT" and rec.get("trail_offset") is not None:
            try: tpct = float(rec["trail_offset"])
            except Exception: tpct = None
        if tpct is None and rec.get("stop_pct_below") is not None:
            try: tpct = float(rec["stop_pct_below"])
            except Exception: tpct = None
        if price and tpct:
            adv[sym.upper()] = {"price": price, "trail_pct": tpct}
    # live FIXED stops only (skip stops already trailing)
    live_fixed = {}
    for tbl, col in (("fidelity_monitored_stops", "COALESCE(effective_stop, stop_price)"),
                     ("manual_broker_stops", "stop_price")):
        try:
            cur.execute(f"SELECT UPPER(symbol), {col}, COALESCE(order_type,'') FROM {tbl} "
                        f"WHERE lower(COALESCE(status,'')) = ANY(%s) AND {col} IS NOT NULL", (list(LIVE_STATUS),))
            for sym, s, ot in cur.fetchall():
                if s is None or "trail" in str(ot).lower():
                    continue
                live_fixed[sym] = max(live_fixed.get(sym, 0.0), float(s))
        except Exception:
            pass
    out = []
    for sym, a in adv.items():
        ls = live_fixed.get(sym)
        if ls is None or ls <= 0:
            continue
        floor = a["price"] * (1 - a["trail_pct"] / 100)
        if floor > ls + max(0.01 * a["price"], 0.01):          # trailing locks a materially higher floor
            out.append({"symbol": sym, "live_fixed_stop": round(ls, 2), "trail_pct": round(a["trail_pct"], 1),
                        "trailing_floor": round(floor, 2), "price": round(a["price"], 2),
                        "gain_above_fixed_pct": round(100 * (floor - ls) / ls, 1)})
    return out


def _recently_alerted(cur, sym, kind="stop_drift"):
    try:
        cur.execute("""SELECT 1 FROM alert_events WHERE symbol=%s AND source_script='stop_drift_alert'
                       AND parsed_payload->>'kind' = %s
                       AND created_at > now() - %s * interval '1 hour' LIMIT 1""", (sym, kind, DEDUP_HOURS))
        return cur.fetchone() is not None
    except Exception:
        return False


def run(send=False):
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    drifts = detect(cur)
    lockins = detect_lockin(cur)
    emitted, lock_emitted, sent = [], [], 0

    def _emit(msg, sym, payload, kind):
        nonlocal sent
        try:
            from alert_event_writer import save_alert_event
            save_alert_event(alert_type="strategic_alert", severity="info", source_script="stop_drift_alert",
                             symbol=sym, raw_text=msg, parsed_payload={"kind": kind, **payload, "advisory_only": True})
        except Exception:
            pass
        if send:
            try:
                from telegram_alert import send_telegram
                send_telegram(msg); sent += 1
            except Exception:
                pass

    for d in drifts:
        if _recently_alerted(cur, d["symbol"], "stop_drift"):
            continue
        msg = (f"↑ Raise stop: {d['symbol']} advised stop ${d['advised_stop']} is "
               f"${d['raise_by']} above the live stop ${d['live_stop']} "
               f"({d['raise_pct']}% of price) — consider ratcheting up (advisory).")
        _emit(msg, d["symbol"], d, "stop_drift")
        emitted.append(d)

    for d in lockins:
        if _recently_alerted(cur, d["symbol"], "stop_lockin"):
            continue
        broker = "Schwab API · 2FA" if d["symbol"] not in _fidelity_syms(cur) else "manual @ Fidelity"
        msg = (f"📈 Lock in profits: {d['symbol']} — a {d['trail_pct']}% trailing stop now sits at "
               f"${d['trailing_floor']} ({d['gain_above_fixed_pct']}% above your fixed ${d['live_fixed_stop']}). "
               f"Switch fixed→trailing to lock the higher floor ({broker}) — advisory.")
        _emit(msg, d["symbol"], d, "stop_lockin")
        lock_emitted.append(d)

    return {"checked": len(drifts), "alerted": len(emitted),
            "lockin_checked": len(lockins), "lockin_alerted": len(lock_emitted),
            "telegram_sent": sent if send else 0, "drifts": emitted, "lockins": lock_emitted,
            "dry_run": not send, "note": "advisory only — never places/modifies a stop"}


def _fidelity_syms(cur):
    """Symbols whose live fixed stop is at Fidelity (manual switch) vs Schwab (API)."""
    try:
        cur.execute("SELECT DISTINCT UPPER(symbol) FROM fidelity_monitored_stops "
                    "WHERE lower(COALESCE(status,'')) = ANY(%s)", (list(LIVE_STATUS),))
        return {r[0] for r in cur.fetchall()}
    except Exception:
        return set()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--send", action="store_true"); a = ap.parse_args()
    print(json.dumps(run(send=a.send), indent=2, default=str))


if __name__ == "__main__":
    main()
