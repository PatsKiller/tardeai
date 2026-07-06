#!/usr/bin/env python3
"""stop_drift_alert.py — alert when the daily stop ADVISORY recommends RAISING a live stop.

Closes the "alert when to CHANGE a stop" gap: protection_alerts handles MISSING stops (naked / no-TP);
this handles RATCHET-UP drift — when holding_protection_advisor's advised stop sits materially ABOVE the
currently placed/monitored stop, surface an actionable "raise {SYM} {old}->{new}" alert (SIEM + Telegram).

Also surfaces LIVE-PRICE lock-in nudges (fixed stop → trailing when the trail floor now sits above the
fixed trigger) and trail-eligibility nudges at the +9% gain threshold (operator 2026-07-06).

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
_TERMINAL_MANUAL = ("cancelled", "canceled", "filled", "closed", "replaced", "closed_position")


def _live_holdings_map() -> dict[str, dict]:
    """Current holdings price + basis keyed by symbol (portfolio_holdings is the live quote source)."""
    out: dict[str, dict] = {}
    try:
        from api_v2 import portfolio_holdings
        for h in (portfolio_holdings() or {}).get("holdings") or []:
            sym = str(h.get("symbol") or "").upper()
            if not sym:
                continue
            px = h.get("current_price") or h.get("price")
            if px in (None, ""):
                continue
            sh = float(h.get("shares") or 0)
            cb = h.get("cost_basis")
            basis_ps = (float(cb) / sh) if sh and cb else None
            out[sym] = {
                "price": float(px),
                "shares": sh,
                "cost_basis": float(cb) if cb not in (None, "") else None,
                "basis_ps": basis_ps,
                "account": str(h.get("account") or ""),
            }
    except Exception:
        pass
    return out


def _trail_pct_from_rec(rec: dict) -> float | None:
    if rec.get("trail_type") == "PERCENT" and rec.get("trail_offset") is not None:
        try:
            return float(rec["trail_offset"])
        except (TypeError, ValueError):
            pass
    if rec.get("stop_pct_below") is not None:
        try:
            return float(rec["stop_pct_below"])
        except (TypeError, ValueError):
            pass
    return None


def _load_recent_advisories(cur, days: int = 5) -> dict[str, dict]:
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, evidence_json FROM hermes_research_intelligence
                   WHERE research_type='protection_advisory' AND created_at > now()-interval '%s days'
                   ORDER BY symbol, created_at DESC""" % int(days))
    adv: dict[str, dict] = {}
    for sym, ev in cur.fetchall():
        ev = ev if isinstance(ev, dict) else json.loads(ev or "{}")
        rec = ev.get("recommendation") or {}
        inp = ev.get("inputs") or {}
        tpct = _trail_pct_from_rec(rec)
        try:
            snap_px = float(inp.get("price") or 0)
        except (TypeError, ValueError):
            snap_px = 0.0
        try:
            sma50 = float(inp.get("sma50")) if inp.get("sma50") is not None else None
        except (TypeError, ValueError):
            sma50 = None
        if tpct:
            adv[sym.upper()] = {
                "trail_pct": tpct,
                "snap_price": snap_px,
                "sma50": sma50,
                "family": ev.get("family") or "position",
                "trail_recommended": bool(rec.get("trail_recommended")),
            }
    return adv


def _load_live_fixed_stops(cur) -> dict[str, dict]:
    """Active FIXED broker stops keyed by symbol (skips trailing orders)."""
    live_fixed: dict[str, dict] = {}
    try:
        cur.execute(
            """SELECT UPPER(symbol), stop_price, COALESCE(order_type,''), account
               FROM manual_broker_stops
               WHERE active=TRUE
                 AND stop_price IS NOT NULL
                 AND lower(COALESCE(status,'open')) NOT IN %s
                 AND COALESCE(order_type,'') NOT ILIKE '%%TRAIL%%'""",
            (tuple(_TERMINAL_MANUAL),),
        )
        for sym, s, ot, acct in cur.fetchall():
            if s is None or "trail" in str(ot).lower():
                continue
            prev = live_fixed.get(sym)
            sp = float(s)
            if prev is None or sp > prev["stop"]:
                live_fixed[sym] = {"stop": sp, "account": str(acct or "")}
    except Exception:
        pass
    try:
        cur.execute(
            f"""SELECT UPPER(symbol), COALESCE(effective_stop, stop_price), COALESCE(order_type,''), account
                FROM fidelity_monitored_stops
                WHERE lower(COALESCE(status,'')) = ANY(%s) AND COALESCE(effective_stop, stop_price) IS NOT NULL""",
            (list(LIVE_STATUS),),
        )
        for sym, s, ot, acct in cur.fetchall():
            if s is None or "trail" in str(ot).lower():
                continue
            sp = float(s)
            prev = live_fixed.get(sym)
            if prev is None or sp > prev["stop"]:
                live_fixed[sym] = {"stop": sp, "account": str(acct or "")}
    except Exception:
        pass
    return live_fixed


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
    for tbl, col, extra in (
        ("fidelity_monitored_stops", "COALESCE(effective_stop, stop_price)", ""),
        ("manual_broker_stops", "stop_price", "AND active=TRUE"),
    ):
        try:
            cur.execute(
                f"SELECT UPPER(symbol), {col} FROM {tbl} "
                f"WHERE lower(COALESCE(status,'open')) NOT IN %s AND {col} IS NOT NULL {extra}",
                (tuple(_TERMINAL_MANUAL),),
            )
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


def detect_lockin(cur, live_map: dict[str, dict] | None = None):
    """LOCK-IN drift using LIVE price: fixed stop at broker, but trailing floor (live px × (1−trail%))
    now sits above that fixed trigger — switch fixed→trailing to lock a higher floor."""
    import holding_family as hf
    live_map = live_map or _live_holdings_map()
    adv = _load_recent_advisories(cur)
    live_fixed = _load_live_fixed_stops(cur)
    out = []
    for sym, a in adv.items():
        ls_row = live_fixed.get(sym)
        if ls_row is None:
            continue
        ls = ls_row["stop"]
        hold = live_map.get(sym) or {}
        px = hold.get("price") or a.get("snap_price") or 0.0
        if not px:
            continue
        if not hf.lockin_eligible(live_price=px, trail_pct=a["trail_pct"], fixed_stop=ls):
            continue
        floor = hf.trailing_floor(px, a["trail_pct"])
        out.append({
            "symbol": sym, "live_fixed_stop": round(ls, 2), "trail_pct": round(a["trail_pct"], 1),
            "trailing_floor": floor, "price": round(px, 2), "advisory_snap_price": round(a.get("snap_price") or 0, 2),
            "gain_above_fixed_pct": round(100 * (floor - ls) / ls, 1),
            "account": ls_row.get("account") or hold.get("account") or "",
        })
    return out


def detect_trail_nudge(cur, live_map: dict[str, dict] | None = None):
    """Trail-eligibility nudge: live gain ≥ family threshold (+9% normal), fixed stop, not yet trailing."""
    import holding_family as hf
    live_map = live_map or _live_holdings_map()
    adv = _load_recent_advisories(cur)
    live_fixed = _load_live_fixed_stops(cur)
    out = []
    for sym, hold in live_map.items():
        ls_row = live_fixed.get(sym)
        if ls_row is None:
            continue
        px = hold.get("price") or 0.0
        basis_ps = hold.get("basis_ps")
        if not px or not basis_ps or basis_ps <= 0:
            continue
        pnl_pct = (px - basis_ps) / basis_ps * 100
        meta = adv.get(sym) or {}
        family = meta.get("family") or "position"
        sma50 = meta.get("sma50")
        if not hf.trail_recommended_for_state(family=family, pnl_pct=pnl_pct, price=px, sma50=sma50):
            continue
        tpct = meta.get("trail_pct")
        if not tpct:
            fb = hf.protection_bounds(family)
            tpct = float(fb.get("trail_min_pct") or 6)
        # lock-in path handles the stronger "switch now" case
        if hf.lockin_eligible(live_price=px, trail_pct=tpct, fixed_stop=ls_row["stop"]):
            continue
        out.append({
            "symbol": sym,
            "pnl_pct": round(pnl_pct, 1),
            "trail_pct": round(tpct, 1),
            "live_fixed_stop": round(ls_row["stop"], 2),
            "price": round(px, 2),
            "threshold_pct": hf.trail_pnl_threshold(family),
            "account": ls_row.get("account") or hold.get("account") or "",
        })
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
    live_map = _live_holdings_map()
    drifts = detect(cur)
    lockins = detect_lockin(cur, live_map)
    trail_nudges = detect_trail_nudge(cur, live_map)
    emitted, lock_emitted, trail_emitted, sent = [], [], [], 0

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
        broker = "manual @ Fidelity" if str(d.get("account", "")).startswith("fidelity") else "Schwab API · 2FA"
        msg = (f"📈 Lock in profits: {d['symbol']} @ ${d['price']} — a {d['trail_pct']}% trailing stop now sits at "
               f"${d['trailing_floor']} ({d['gain_above_fixed_pct']}% above your fixed ${d['live_fixed_stop']}). "
               f"Switch fixed→trailing to lock the higher floor ({broker}) — advisory.")
        _emit(msg, d["symbol"], d, "stop_lockin")
        lock_emitted.append(d)

    for d in trail_nudges:
        if _recently_alerted(cur, d["symbol"], "stop_trail_nudge"):
            continue
        broker = "manual @ Fidelity" if str(d.get("account", "")).startswith("fidelity") else "Schwab API · 2FA"
        msg = (f"📊 Trail eligible: {d['symbol']} is +{d['pnl_pct']}% (≥{d['threshold_pct']:.0f}% rule) with a "
               f"fixed stop at ${d['live_fixed_stop']} — consider a {d['trail_pct']}% trailing stop ({broker}).")
        _emit(msg, d["symbol"], d, "stop_trail_nudge")
        trail_emitted.append(d)

    return {
        "checked": len(drifts), "alerted": len(emitted),
        "lockin_checked": len(lockins), "lockin_alerted": len(lock_emitted),
        "trail_nudge_checked": len(trail_nudges), "trail_nudge_alerted": len(trail_emitted),
        "telegram_sent": sent if send else 0, "drifts": emitted, "lockins": lock_emitted,
        "trail_nudges": trail_emitted, "dry_run": not send,
        "note": "advisory only — never places/modifies a stop",
    }


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--send", action="store_true"); a = ap.parse_args()
    print(json.dumps(run(send=a.send), indent=2, default=str))


if __name__ == "__main__":
    main()