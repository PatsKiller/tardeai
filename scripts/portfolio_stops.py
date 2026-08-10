"""portfolio_stops.py — Trade AI v12 Portfolio Intelligence
Stop-loss management and risk tracking across all accounts.

Features:
  - Persistent stop storage per symbol (data/portfolios/state/stops.json)
  - Risk metrics: max loss at stop, distance to stop, portfolio heat
  - Position sizer: max shares given risk % per trade
  - Stop alerts: fires Telegram when price within 3% of stop
  - CLI: python scripts/portfolio_stops.py set TICKER 280.00 "Below 200d MA"
          python scripts/portfolio_stops.py list
          python scripts/portfolio_stops.py remove TICKER
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


# ── Stop storage ──────────────────────────────────────────────────────────────

def _stops_path(state_dir: Path) -> Path:
    return state_dir / "stops.json"


def load_stops(state_dir: Path) -> Dict[str, Dict]:
    """Load all stops. Returns {SYMBOL: {stop, trail_pct, notes, set_date, account}}"""
    p = _stops_path(state_dir)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}


def save_stops(state_dir: Path, stops: Dict[str, Dict]) -> None:
    _stops_path(state_dir).write_text(json.dumps(stops, indent=2))


def _publish_stop_mutation(
    symbol: str,
    account_id: str,
    previous_state: Optional[str] = None,
    new_state: str = "updated",
    old_stop_price: Optional[float] = None,
    new_stop_price: Optional[float] = None,
    notes: str = "",
) -> None:
    """Publish a stop mutation event to CIOEventBus after file persistence.

    Best-effort: failures are logged but never raised so the mutation
    (set/remove) always completes even if the event bus is unavailable.
    """
    try:
        from scripts.lib.cio_mutation_publisher import (
            publish_stop_triggered,
            publish_stop_updated,
            publish_stop_removed,
        )

        if new_state == "removed":
            publish_stop_removed(symbol=symbol, account_id=account_id)
        elif new_state == "created":
            publish_stop_triggered(
                symbol=symbol,
                account_id=account_id,
                stop_id=f"stop-{symbol.lower()}",
                previous_state="none",
                new_state="created",
                trigger_price=new_stop_price,
                extra_meta={"notes": notes} if notes else None,
            )
        elif old_stop_price is not None and new_stop_price is not None:
            publish_stop_updated(
                symbol=symbol,
                account_id=account_id,
                old_stop_price=old_stop_price,
                new_stop_price=new_stop_price,
                notes=notes,
            )
        else:
            publish_stop_triggered(
                symbol=symbol,
                account_id=account_id,
                stop_id=f"stop-{symbol.lower()}",
                previous_state=previous_state or "unknown",
                new_state=new_state,
            )
    except Exception:
        pass  # Event bus is best-effort; never fail a mutation for it


def set_stop(state_dir: Path, symbol: str, stop_price: float,
             notes: str = "", trail_pct: float = 0.0,
             account: str = "all") -> Dict:
    """Set or update a stop for a symbol."""
    stops = load_stops(state_dir)
    symbol = symbol.upper().strip()

    previous = stops.get(symbol)
    old_stop = previous.get("stop") if previous else None

    stops[symbol] = {
        "stop":       round(stop_price, 4),
        "trail_pct":  trail_pct,   # % trailing stop (0 = hard stop)
        "notes":      notes,
        "set_date":   datetime.now().strftime("%Y-%m-%d"),
        "account":    account,
    }
    save_stops(state_dir, stops)

    # Publish mutation event via CIOEventBus
    _publish_stop_mutation(
        symbol=symbol,
        account_id=account,
        previous_state="active" if previous else None,
        new_state="updated" if previous else "created",
        old_stop_price=old_stop,
        new_stop_price=round(stop_price, 4),
        notes=notes,
    )

    return stops[symbol]


def remove_stop(state_dir: Path, symbol: str) -> None:
    stops = load_stops(state_dir)
    sym = symbol.upper().strip()
    previous = stops.get(sym)
    stops.pop(sym, None)
    save_stops(state_dir, stops)

    # Publish removal event via CIOEventBus
    if previous:
        _publish_stop_mutation(
            symbol=sym,
            account_id=previous.get("account", "all"),
            previous_state="active",
            new_state="removed",
            old_stop_price=previous.get("stop"),
            new_stop_price=None,
        )


# ── Risk calculations ─────────────────────────────────────────────────────────

def compute_risk_metrics(portfolio: Dict, state_dir: Path) -> Dict:
    """
    For each holding with a stop set, compute:
      - distance_to_stop ($, %)
      - max_loss_at_stop ($)
      - risk_pct_portfolio (%)
    Also computes total portfolio heat and unprotected exposure.
    Enriches positions with RSI and day_change_pct from enrichment cache and holdings.
    """
    stops        = load_stops(state_dir)
    holdings     = portfolio.get("holdings", [])
    total_mv     = portfolio.get("portfolio_totals", {}).get("total_value", 0)

    # Load enrichment data for RSI
    enrichment = {}
    try:
        enrich_path = state_dir / "ticker_enrichment_cache.json"
        if enrich_path.exists():
            enrichment = json.load(open(enrich_path))
    except Exception:
        pass

    # Build day_change_pct lookup from holdings
    day_changes = {}
    for h in holdings:
        sym = h.get("symbol", "").upper()
        if h.get("day_change_pct") is not None:
            day_changes[sym] = h["day_change_pct"]

    positions: List[Dict] = []
    total_risk_dollars    = 0.0
    total_protected_mv    = 0.0
    total_unprotected_mv  = 0.0

    for h in holdings:
        sym   = h.get("symbol","").upper()
        price = h.get("price", 0) or 0
        shares= h.get("shares", 0) or 0
        mv    = h.get("market_value", 0) or 0
        acct  = h.get("account_display", h.get("account",""))
        gl    = h.get("gain_loss", 0) or 0

        if mv < 100 or price <= 0 or h.get("is_loan") or h.get("is_cash") or sym in ("CASH", "CASH & CASH INVESTMENTS", "MMKT"):
            continue

        stop_data = stops.get(sym)

        if stop_data and stop_data.get("stop_price_unavailable"):
            # A live broker trailing stop that has not armed yet publishes no
            # absolute stopPrice. The position IS protected, but the trigger
            # level is unknowable — so report protection honestly and refuse to
            # compute a risk number rather than treating stop=0 as a real level
            # (which would book the entire position value as max_loss).
            _enr = enrichment.get(sym, {})
            positions.append({
                "symbol": sym, "account": acct, "shares": shares, "price": price,
                "market_value": mv, "gain_loss": gl,
                "stop_price": None, "trail_pct": stop_data.get("trail_pct", 0),
                "dist_dollar": None, "dist_pct": None,
                "max_loss_dollar": None, "risk_pct_port": None,
                "notes": stop_data.get("notes", ""),
                "set_date": stop_data.get("set_date", ""),
                "status": "PROTECTED (LEVEL PENDING)",
                "protected": True,
                "risk_not_computable": True,
                "broker_order_id": stop_data.get("broker_order_id", ""),
                "order_type": stop_data.get("order_type", ""),
                "rsi": _enr.get("rsi"),
                "day_change_pct": day_changes.get(sym),
            })
            total_protected_mv += mv      # protected, but adds no quantified risk
            continue

        if stop_data:
            stop_price      = stop_data.get("stop", 0)
            trail_pct       = stop_data.get("trail_pct", 0)

            # Trailing stop: adjust if price has moved up
            if trail_pct > 0:
                trail_stop = price * (1 - trail_pct / 100)
                stop_price = max(stop_price, trail_stop)
                stop_data = {**stop_data, "stop": round(trail_stop, 2),
                             "effective_stop": round(trail_stop, 2)}

            dist_dollar = price - stop_price
            dist_pct    = (dist_dollar / price * 100) if price > 0 else 0
            max_loss    = dist_dollar * shares
            risk_pct    = (max_loss / total_mv * 100) if total_mv > 0 else 0

            # Status
            if price <= stop_price:
                status = "TRIGGERED"
            elif dist_pct <= 2:
                status = "DANGER"    # within 2% of stop
            elif dist_pct <= 5:
                status = "WARNING"   # within 5% of stop
            else:
                status = "OK"

            _enr = enrichment.get(sym, {})
            positions.append({
                "symbol":          sym,
                "account":         acct,
                "shares":          shares,
                "price":           price,
                "market_value":    mv,
                "gain_loss":       gl,
                "stop_price":      stop_price,
                "trail_pct":       trail_pct,
                "dist_dollar":     round(dist_dollar, 2),
                "dist_pct":        round(dist_pct, 2),
                "max_loss_dollar": round(max_loss, 2),
                "risk_pct_port":   round(risk_pct, 2),
                "notes":           stop_data.get("notes",""),
                "set_date":        stop_data.get("set_date",""),
                "status":          status,
                "protected":       True,
                "rsi":             _enr.get("rsi"),
                "day_change_pct":  day_changes.get(sym),
            })
            total_risk_dollars  += max(0, max_loss)
            total_protected_mv  += mv
        else:
            _enr = enrichment.get(sym, {})
            positions.append({
                "symbol":       sym,
                "account":      acct,
                "shares":       shares,
                "price":        price,
                "market_value": mv,
                "gain_loss":    gl,
                "stop_price":   None,
                "status":       "NO STOP",
                "protected":    False,
                "risk_pct_port": round(mv / total_mv * 100, 2) if total_mv else 0,
                "rsi":          _enr.get("rsi"),
                "day_change_pct": day_changes.get(sym),
            })
            total_unprotected_mv += mv

    # Sort: triggered → danger → warning → ok → no stop
    order = {"TRIGGERED": 0, "DANGER": 1, "WARNING": 2, "OK": 3,
             "PROTECTED (LEVEL PENDING)": 3, "NO STOP": 4}
    positions.sort(key=lambda x: (order.get(x.get("status",""), 5),
                                  -(x.get("market_value",0))))

    portfolio_heat = round(total_risk_dollars / total_mv * 100, 2) if total_mv else 0

    # Positions with NO stop, sorted by size (biggest unprotected risk first)
    unprotected = sorted(
        [p for p in positions if not p["protected"]],
        key=lambda x: -x.get("market_value", 0)
    )

    return {
        "positions":            positions,
        "total_risk_dollars":   round(total_risk_dollars, 2),
        "portfolio_heat_pct":   portfolio_heat,
        "total_protected_mv":   round(total_protected_mv, 2),
        "total_unprotected_mv": round(total_unprotected_mv, 2),
        "pct_protected":        round(total_protected_mv / total_mv * 100, 2) if total_mv else 0,
        "triggered":            [p for p in positions if p.get("status") == "TRIGGERED"],
        "danger":               [p for p in positions if p.get("status") == "DANGER"],
        "warning":              [p for p in positions if p.get("status") == "WARNING"],
        "unprotected":          unprotected,
        "stop_count":           len(stops),
        "total_mv":             total_mv,
    }


# ── Position sizer ────────────────────────────────────────────────────────────

def position_size(portfolio_value: float, risk_pct: float,
                  entry_price: float, stop_price: float) -> Dict:
    """
    Calculate max position size given risk tolerance.
    risk_pct = max % of portfolio willing to lose on this trade (e.g. 1.0 = 1%)
    """
    if entry_price <= stop_price or risk_pct <= 0:
        return {}
    max_risk_dollars  = portfolio_value * risk_pct / 100
    risk_per_share    = entry_price - stop_price
    max_shares        = int(max_risk_dollars / risk_per_share)
    position_value    = max_shares * entry_price
    return {
        "max_shares":       max_shares,
        "position_value":   round(position_value, 2),
        "risk_per_share":   round(risk_per_share, 2),
        "max_risk_dollars": round(max_risk_dollars, 2),
        "position_pct_port":round(position_value / portfolio_value * 100, 2),
    }


# ── Stop alert check ──────────────────────────────────────────────────────────

def _get_overridden_symbols() -> set:
    """Get symbols with active HOLD_OVERRIDE decisions (last 24h)."""
    try:
        import psycopg2
        pw = ""
        for line in (Path(__file__).resolve().parent.parent / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        cur.execute("""SELECT DISTINCT symbol FROM stop_decisions
            WHERE decision = 'HOLD_OVERRIDE'
            AND decided_at > NOW() - INTERVAL '96 hours'""")
        syms = {r[0] for r in cur.fetchall()}
        # Also check snooze table
        cur.execute("SELECT symbol FROM stop_snooze WHERE snoozed_until > NOW()")
        syms.update(r[0] for r in cur.fetchall())
        conn.close()
        return syms
    except Exception:
        return set()


def check_stop_alerts(risk_data: Dict) -> List[Dict]:
    """Return list of alert-worthy stop events. Respects operator overrides."""
    overridden = _get_overridden_symbols()
    alerts = []
    for p in risk_data.get("positions", []):
        status = p.get("status","")
        sym = p.get("symbol", "")
        if sym in overridden:
            continue  # operator chose HOLD_OVERRIDE — suppress alert
        if status == "TRIGGERED":
            alerts.append({
                "type":    "STOP_TRIGGERED",
                "severity":"CRITICAL",
                "symbol":  sym,
                "msg": (f"🚨 STOP TRIGGERED: {sym} @ ${p['price']:.2f} "
                        f"— stop was ${p['stop_price']:.2f} | "
                        f"Max loss: ${p.get('max_loss_dollar',0):,.0f}")
            })
        elif status == "DANGER":
            alerts.append({
                "type":    "STOP_NEAR",
                "severity":"HIGH",
                "symbol":  sym,
                "msg": (f"⚠️ STOP ALERT: {sym} within {p['dist_pct']:.1f}% of stop "
                        f"(price: ${p['price']:.2f} | stop: ${p['stop_price']:.2f})")
            })
    return alerts


# ── Save to state ─────────────────────────────────────────────────────────────

def save_risk_state(risk_data: Dict, state_dir: Path) -> None:
    out = state_dir / "risk_management.json"
    out.write_text(json.dumps(risk_data, indent=2, default=str))


# ── CLI interface ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os

    root = Path(".")
    state_dir = root / "data" / "portfolios" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python scripts/portfolio_stops.py set TICKER STOP_PRICE [notes]")
        print("  python scripts/portfolio_stops.py trail TICKER TRAIL_PCT [notes]")
        print("  python scripts/portfolio_stops.py remove TICKER")
        print("  python scripts/portfolio_stops.py list")
        print()
        print("Examples:")
        print("  python scripts/portfolio_stops.py set V 280.00 \"Below 200d MA\"")
        print("  python scripts/portfolio_stops.py trail KTOS 8.0 \"8% trailing\"")
        print("  python scripts/portfolio_stops.py set LMT 590.00")
        sys.exit(0)

    cmd = sys.argv[1].lower()

    if cmd == "set" and len(sys.argv) >= 4:
        sym   = sys.argv[2].upper()
        price = float(sys.argv[3])
        notes = sys.argv[4] if len(sys.argv) > 4 else ""
        s = set_stop(state_dir, sym, price, notes=notes)
        print(f"✅ Stop set: {sym} @ ${s['stop']:.2f}  [{notes}]")

    elif cmd == "trail" and len(sys.argv) >= 4:
        sym   = sys.argv[2].upper()
        trail = float(sys.argv[3])
        notes = sys.argv[4] if len(sys.argv) > 4 else f"{trail}% trailing"
        # Current price unknown at CLI, set stop=0 to signal trail-only
        s = set_stop(state_dir, sym, 0.0, notes=notes, trail_pct=trail)
        print(f"✅ Trailing stop: {sym} @ {trail}% trail  [{notes}]")

    elif cmd == "remove" and len(sys.argv) >= 3:
        sym = sys.argv[2].upper()
        remove_stop(state_dir, sym)
        print(f"✅ Stop removed: {sym}")

    elif cmd == "list":
        stops = load_stops(state_dir)
        if not stops:
            print("No stops set. Use: python scripts/portfolio_stops.py set TICKER PRICE")
        else:
            print(f"{'SYMBOL':<8} {'STOP':>8} {'TRAIL%':>7} {'SET':>12}  NOTES")
            print("-" * 55)
            for sym, s in sorted(stops.items()):
                trail = f"{s.get('trail_pct',0):.1f}%" if s.get('trail_pct') else "—"
                print(f"{sym:<8} ${s['stop']:>7.2f} {trail:>7} {s.get('set_date',''):>12}  {s.get('notes','')}")
    else:
        print("Unknown command. Run without args for usage.")
