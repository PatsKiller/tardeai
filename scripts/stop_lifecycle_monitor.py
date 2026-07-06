#!/usr/bin/env python3
"""Stop Lifecycle & Proximity Monitor (Stage 2c) — the maturing monitoring engine for protective stops.

Scans the BROKER'S live working stops (source of truth) across every account that has a trading API —
Schwab (taxable + the 2 IRAs) and Alpaca paper — cross-references them against shares held now, and
classifies each stop's lifecycle + health:

  lifecycle : working | near_trigger | triggered | filled | cancelled | orphaned
  coverage  : full | oversized | partial | orphaned   (stop qty vs shares held now — a GTC stop does NOT
              auto-resize when you trim/add, so an oversized stop can short the excess / a partial leaves
              shares unprotected)
  proximity : distance % from the current price down to the stop (how close it is as the ticker moves);
              for trailing stops the trail offset is the live cushion.

Each scan persists a fresh snapshot to the stop_lifecycle table for the health agent + Hermes to consume,
and returns {generated_at, stops:[...], summary:{...}, alerts:[...]}. READ-ONLY — never places/cancels.

Run: python3 scripts/stop_lifecycle_monitor.py [--json]
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
_TERMINAL_CANCEL = {"canceled", "cancelled", "rejected", "expired", "replaced"}
_TERMINAL_FILL = {"filled"}
_NEAR_TRIGGER_PCT = 2.0     # within 2% of the stop ⇒ near_trigger (warn); within 0.75% ⇒ alert
_NEAR_ALERT_PCT = 0.75
_FILLED_ALERT_HOURS = 12.0  # only a FRESH stop-out (filled within this window) is alert-worthy; older fills
                            # stay lifecycle='filled' but health<alert so the broker's recent-order window
                            # can't re-ping a days-old stop-out.


def _holdings_map() -> dict:
    """(account, SYMBOL) -> {shares, price} from canonical holdings.json (covers Schwab + Alpaca paper rows)."""
    out = {}
    try:
        import json
        h = json.loads((STATE_DIR / "holdings.json").read_text())
        for r in (h.get("holdings", []) or []):
            if not isinstance(r, dict):
                continue
            acct = str(r.get("account", ""))
            sym = str(r.get("symbol", r.get("ticker", ""))).upper()
            if not sym:
                continue
            try:
                sh = float(r.get("shares", r.get("qty")) or 0)
            except Exception:
                sh = None
            try:
                px = float(r.get("current_price", r.get("price")) or 0) or None
            except Exception:
                px = None
            out[(acct, sym)] = {"shares": sh, "price": px}
    except Exception:
        pass
    return out


def _alpaca_positions_map() -> dict:
    """('alpaca_paper', SYMBOL) -> {shares, price} from the live Alpaca paper positions (paper held shares
    are NOT in holdings.json — they come from the Alpaca API), so paper stops aren't falsely 'orphaned'."""
    out = {}
    try:
        import alpaca_paper_reconciler as apr
        env = apr.get_env()
        for p in (apr.get_alpaca_positions(env) or []):
            sym = str(p.get("symbol", "")).upper()
            if not sym:
                continue
            try:
                sh = float(p.get("qty") or 0)
            except Exception:
                sh = None
            try:
                px = float(p.get("current_price") or 0) or None
            except Exception:
                px = None
            out[("alpaca_paper", sym)] = {"shares": sh, "price": px}
    except Exception:
        pass
    return out


def _schwab_stops() -> list[dict]:
    """Live working SELL stop/trailing orders across all verified Schwab accounts."""
    rows = []
    try:
        import schwab_transport as st
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("SELECT account_key FROM schwab_account_links WHERE verified=TRUE")
        accts = [r[0] for r in cur.fetchall()]
        for acct in accts:
            raw = st.get_orders_raw(acct)
            if not isinstance(raw, list):
                continue
            for o in raw:
                leg = (o.get("orderLegCollection") or [{}])[0]
                if str(leg.get("instruction", "")).upper() not in ("SELL", "SELL_SHORT"):
                    continue
                otype = str(o.get("orderType", "")).upper()
                if "STOP" not in otype and "TRAILING" not in otype:
                    continue
                sp = o.get("stopPrice")
                try:
                    sp = float(sp) if sp not in (None, "", 0, "0") else None
                except Exception:
                    sp = None
                try:
                    qty = float(leg.get("quantity") or 0)
                except Exception:
                    qty = None
                rows.append({"broker": "schwab", "account": acct,
                             "symbol": str((leg.get("instrument") or {}).get("symbol", "")).upper(),
                             "order_id": str(o.get("orderId") or ""), "order_type": otype.replace(" ", "_"),
                             "stop_price": sp, "trail_offset": o.get("stopPriceOffset"),
                             "trail_link": o.get("stopPriceLinkType"), "qty": qty,
                             "status": str(o.get("status", "")).lower(),
                             "closed_at": o.get("closeTime")})
    except Exception:
        pass
    return rows


def _alpaca_stops() -> list[dict]:
    """Live open SELL stop/stop_limit/trailing_stop orders on the Alpaca paper account."""
    rows = []
    try:
        import alpaca_paper_reconciler as apr
        env = apr.get_env()
        for o in (apr.get_alpaca_orders(env, status="open") or []):
            if str(o.get("side", "")).lower() != "sell":
                continue
            otype = str(o.get("type", "")).lower()
            if "stop" not in otype and "trailing" not in otype:
                continue
            try:
                sp = float(o.get("stop_price")) if o.get("stop_price") not in (None, "") else None
            except Exception:
                sp = None
            try:
                qty = float(o.get("qty") or 0)
            except Exception:
                qty = None
            rows.append({"broker": "alpaca", "account": "alpaca_paper",
                         "symbol": str(o.get("symbol", "")).upper(), "order_id": str(o.get("id") or ""),
                         "order_type": otype.upper(), "stop_price": sp,
                         "trail_offset": o.get("trail_percent") or o.get("trail_price"),
                         "trail_link": "PERCENT" if o.get("trail_percent") else ("VALUE" if o.get("trail_price") else None),
                         "qty": qty, "status": str(o.get("status", "")).lower(),
                         "closed_at": o.get("filled_at") or o.get("updated_at")})
    except Exception:
        pass
    return rows


def _age_hours(ts) -> float | None:
    """Hours since an ISO timestamp (Schwab closeTime / Alpaca filled_at). None if unparseable — callers
    treat None as 'recent' (fail-open: never miss a fresh stop-out)."""
    if not ts:
        return None
    try:
        import datetime as _dt
        s = str(ts).replace("Z", "+00:00")
        dt = _dt.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return (_dt.datetime.now(_dt.timezone.utc) - dt).total_seconds() / 3600.0
    except Exception:
        return None


def _classify(stop: dict, held: dict | None) -> dict:
    """Attach coverage, proximity, lifecycle, health + flags to one stop record."""
    flags = []
    status = (stop.get("status") or "").lower()
    held_qty = held.get("shares") if held else None
    price = held.get("price") if held else None
    sq = stop.get("qty")
    sp = stop.get("stop_price")
    is_trail = "TRAILING" in (stop.get("order_type") or "")

    # coverage — only meaningful for a WORKING stop. A filled/cancelled stop legitimately has no holding
    # (it already closed the position), so don't mis-flag it as 'orphaned'.
    _is_terminal = status in _TERMINAL_FILL or status in _TERMINAL_CANCEL
    coverage = "full"
    if _is_terminal:
        coverage = "closed"
    elif held is None or not held_qty:
        coverage = "orphaned"
        flags.append("orphaned")            # a WORKING stop with no matching held position (dangerous)
    elif sq and held_qty:
        if sq > held_qty + 1e-6:
            coverage = "oversized"; flags.append("oversized")
        elif sq < held_qty - 1e-6:
            coverage = "partial"; flags.append("partial")

    # proximity (fixed stops only — trailing is dynamic; report the offset as the cushion)
    proximity_pct = None
    if sp is not None and price:
        proximity_pct = round((price - sp) / price * 100, 2)

    # lifecycle
    if status in _TERMINAL_FILL:
        lifecycle = "filled"
        # only a FRESH stop-out is alert-worthy ("filled" flag → alert). The broker's recent-order window
        # can include days-old fills; gate the flag on fill recency so a stale fill can't re-ping.
        age_h = _age_hours(stop.get("closed_at"))
        if age_h is None or age_h <= _FILLED_ALERT_HOURS:
            flags.append("filled")
        else:
            flags.append("filled_stale")   # informational only; not in the alert set below
    elif status in _TERMINAL_CANCEL:
        lifecycle = "cancelled"
    elif coverage == "orphaned":
        lifecycle = "orphaned"
    elif proximity_pct is not None and proximity_pct <= _NEAR_TRIGGER_PCT:
        lifecycle = "near_trigger"; flags.append("near_trigger")
    else:
        lifecycle = "working"

    # health
    if "orphaned" in flags or "oversized" in flags or "filled" in flags or \
            (proximity_pct is not None and proximity_pct <= _NEAR_ALERT_PCT):
        health = "alert"
    elif "partial" in flags or lifecycle == "near_trigger":
        health = "warn"
    else:
        health = "ok"

    return {**stop, "held_qty": held_qty, "current_price": price, "coverage": coverage,
            "proximity_pct": proximity_pct, "is_trailing": is_trail, "lifecycle": lifecycle,
            "health": health, "flags": flags}


def _manual_stops() -> list[dict]:
    """Operator-recorded broker stops for accounts WITHOUT an order API (Fidelity via SnapTrade is
    read-only, so its GTC stops can't be auto-pulled like Schwab/Alpaca). Persisted in
    manual_broker_stops and re-merged into every snapshot, since stop_lifecycle is rebuilt each run.
    Active, still-working rows only."""
    rows = []
    try:
        from db_adapter import _get_conn
        import psycopg2.extras
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""CREATE TABLE IF NOT EXISTS manual_broker_stops (
                         id SERIAL PRIMARY KEY, account TEXT, symbol TEXT, broker TEXT,
                         order_id TEXT, order_type TEXT DEFAULT 'STOP', stop_price NUMERIC,
                         qty NUMERIC, status TEXT DEFAULT 'open', placed_date DATE, note TEXT,
                         active BOOLEAN DEFAULT TRUE, created_at TIMESTAMPTZ DEFAULT NOW(),
                         updated_at TIMESTAMPTZ DEFAULT NOW())""")
        conn.commit()
        cur.execute("""SELECT account, symbol, broker, order_id, order_type, stop_price, qty, status,
                              trail_pct, trail_link
                       FROM manual_broker_stops
                       WHERE active = TRUE
                         AND lower(COALESCE(status,'open')) NOT IN ('cancelled','canceled','filled','closed')""")
        for r in cur.fetchall():
            trail = float(r["trail_pct"]) if r.get("trail_pct") is not None else None
            rows.append({
                "broker": r["broker"] or "manual",
                "account": r["account"],
                "symbol": str(r["symbol"] or "").upper(),
                "order_id": str(r["order_id"] or f"manual-{r['symbol']}"),
                "order_type": str(r["order_type"] or "STOP").upper(),
                "stop_price": float(r["stop_price"]) if r["stop_price"] is not None else None,
                "trail_offset": trail,
                "trail_link": str(r.get("trail_link") or ("PERCENT" if trail else "")).upper() or None,
                "qty": float(r["qty"]) if r["qty"] is not None else None,
                "status": str(r["status"] or "open").lower(),
                "manual": True,
            })
    except Exception:
        pass
    return rows


def _persist(records: list[dict]) -> None:
    try:
        import json
        from db_adapter import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS stop_lifecycle (
                         id SERIAL PRIMARY KEY, account TEXT, symbol TEXT, broker TEXT, order_id TEXT,
                         order_type TEXT, status TEXT, stop_price NUMERIC, qty NUMERIC, held_qty NUMERIC,
                         current_price NUMERIC, proximity_pct NUMERIC, coverage TEXT, lifecycle TEXT,
                         health TEXT, flags JSONB, snapshot_at TIMESTAMPTZ DEFAULT NOW())""")
        cur.execute("DELETE FROM stop_lifecycle")   # snapshot table — latest scan only
        for r in records:
            cur.execute("""INSERT INTO stop_lifecycle
                (account,symbol,broker,order_id,order_type,status,stop_price,qty,held_qty,current_price,
                 proximity_pct,coverage,lifecycle,health,flags)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (r["account"], r["symbol"], r["broker"], r["order_id"], r["order_type"], r["status"],
                 r.get("stop_price"), r.get("qty"), r.get("held_qty"), r.get("current_price"),
                 r.get("proximity_pct"), r["coverage"], r["lifecycle"], r["health"], json.dumps(r["flags"])))
        conn.commit()
    except Exception:
        pass


def scan(persist: bool = True) -> dict:
    """Run a full scan: read broker stops, classify, (persist), summarize. Pure read on the broker side."""
    import datetime as _dt
    hmap = _holdings_map()
    hmap.update(_alpaca_positions_map())   # add paper held shares so paper stops aren't false-orphaned
    stops = _schwab_stops() + _alpaca_stops() + _manual_stops()
    records = [_classify(s, hmap.get((s["account"], s["symbol"]))) for s in stops]
    summary = {
        "total": len(records),
        "by_health": {h: sum(1 for r in records if r["health"] == h) for h in ("ok", "warn", "alert")},
        "by_lifecycle": {},
        "orphaned": [f"{r['symbol']}@{r['account']}" for r in records if "orphaned" in r["flags"]],
        "oversized": [f"{r['symbol']}@{r['account']}" for r in records if "oversized" in r["flags"]],
        "near_trigger": [f"{r['symbol']} ({r['proximity_pct']}%)" for r in records if r["lifecycle"] == "near_trigger"],
    }
    for r in records:
        summary["by_lifecycle"][r["lifecycle"]] = summary["by_lifecycle"].get(r["lifecycle"], 0) + 1
    alerts = [r for r in records if r["health"] == "alert"]
    if persist:
        _persist(records)
    return {"generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "stops": records, "summary": summary, "alerts": alerts}


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(str(PROJECT_ROOT / ".env"))
    import json
    res = scan(persist="--no-persist" not in sys.argv)
    if "--json" in sys.argv:
        print(json.dumps(res, indent=2, default=str))
    else:
        s = res["summary"]
        print(f"Stop lifecycle scan @ {res['generated_at'][:19]}")
        print(f"  {s['total']} live stops · health {s['by_health']} · lifecycle {s['by_lifecycle']}")
        if s["orphaned"]:
            print(f"  ⚠ ORPHANED (stop, no holding): {s['orphaned']}")
        if s["oversized"]:
            print(f"  ⚠ OVERSIZED (stop qty > held): {s['oversized']}")
        if s["near_trigger"]:
            print(f"  ⚠ NEAR TRIGGER: {s['near_trigger']}")
        for r in res["stops"]:
            lvl = f"${r['stop_price']}" if r.get("stop_price") is not None else f"trail {r.get('trail_offset')}"
            print(f"  {r['health']:5} {r['symbol']:6} {r['account']:20} {r['order_type']:14} {lvl:10} "
                  f"prox={r['proximity_pct']} cov={r['coverage']} {r['lifecycle']}")
