"""stop_consensus_check.py — Compare live protective stops to Street consensus mean targets."""
from __future__ import annotations

import json
from pathlib import Path

TOLERANCE_PCT = 0.5  # ignore sub-0.5% float noise above mean
MIN_ANALYSTS = 2
LIVE_STATUS = ("armed", "active", "live", "placed", "confirmed", "working", "new", "accepted", "held", "open")


def load_consensus_targets(project_root: Path | None = None, cur=None) -> dict[str, dict]:
    """Symbol → {target_mean, target_high, target_low, n_analysts, stale, source}."""
    root = project_root or Path(__file__).resolve().parent.parent.parent
    out: dict[str, dict] = {}
    try:
        data = json.loads((root / "data" / "runtime" / "pro_analyst_pills_latest.json").read_text())
        for p in data.get("pills") or []:
            sym = str(p.get("symbol") or "").upper()
            try:
                tgt = float(
                    p.get("target_mean_price") or p.get("target") or 0
                )
            except (TypeError, ValueError):
                tgt = 0.0
            n = int(
                p.get("number_of_analyst_opinions") or p.get("n") or p.get("analysts") or 0
            )
            if not p.get("has_professional_coverage", True) and n < MIN_ANALYSTS:
                continue
            if sym and tgt > 0 and n >= MIN_ANALYSTS:
                try:
                    hi = float(p.get("target_high_price") or 0) or None
                except (TypeError, ValueError):
                    hi = None
                try:
                    lo = float(p.get("target_low_price") or 0) or None
                except (TypeError, ValueError):
                    lo = None
                out[sym] = {
                    "target_mean": round(tgt, 2),
                    "target_high": round(hi, 2) if hi else None,
                    "target_low": round(lo, 2) if lo else None,
                    "n_analysts": n,
                    "stale": bool(p.get("stale")),
                    "upside_pct": p.get("upside_to_mean_target_pct") or p.get("upside"),
                    "source": "pro_analyst_pills",
                }
    except Exception:
        pass
    if cur is not None:
        try:
            cur.execute(
                """SELECT DISTINCT ON (symbol) UPPER(symbol), target_mean_price,
                          number_of_analyst_opinions
                   FROM yahoo_analyst_targets_history
                   WHERE target_mean_price IS NOT NULL AND target_mean_price > 0
                   ORDER BY symbol, snapshot_date DESC NULLS LAST, created_at DESC"""
            )
            for sym, mean, n in cur.fetchall():
                if sym in out:
                    continue
                n = int(n or 0)
                if n >= MIN_ANALYSTS:
                    out[str(sym).upper()] = {
                        "target_mean": round(float(mean), 2),
                        "n_analysts": n,
                        "stale": False,
                        "upside_pct": None,
                        "source": "yahoo_analyst_targets",
                    }
        except Exception:
            pass
    return out


def trailing_trigger(price: float | None, trail_pct: float | None) -> float | None:
    if price is None or trail_pct is None:
        return None
    try:
        return round(float(price) * (1 - float(trail_pct) / 100.0), 2)
    except (TypeError, ValueError):
        return None


def effective_stop_price(
    broker_stop: float | None,
    *,
    is_trailing: bool = False,
    trail_pct: float | None = None,
    current_price: float | None = None,
) -> float | None:
    """Best estimate of where a long stop would trigger."""
    if broker_stop is not None:
        return float(broker_stop)
    if is_trailing:
        return trailing_trigger(current_price, trail_pct)
    return None


def vs_consensus_pct(value: float | None, consensus_mean: float | None) -> float | None:
    """Signed % delta vs Street mean (+ above, − below)."""
    if value is None or not consensus_mean or float(consensus_mean) <= 0:
        return None
    return round(100.0 * (float(value) - float(consensus_mean)) / float(consensus_mean), 2)


def vs_consensus_dollars(value: float | None, consensus_mean: float | None) -> float | None:
    if value is None or consensus_mean is None:
        return None
    return round(float(value) - float(consensus_mean), 2)


def stop_vs_consensus_pct(stop_price: float | None, consensus_mean: float | None) -> float | None:
    return vs_consensus_pct(stop_price, consensus_mean)


def price_vs_consensus_pct(current_price: float | None, consensus_mean: float | None) -> float | None:
    return vs_consensus_pct(current_price, consensus_mean)


def check_stop_over_consensus(
    symbol: str,
    stop_price: float | None,
    current_price: float | None,
    consensus: dict | None,
    *,
    tolerance_pct: float = TOLERANCE_PCT,
) -> dict | None:
    """Return conflict payload when stop sits above Street mean (long positions)."""
    if not consensus or stop_price is None:
        return None
    mean = consensus.get("target_mean")
    if not mean or float(mean) <= 0:
        return None
    stop = float(stop_price)
    mean = float(mean)
    if current_price is not None and stop >= float(current_price):
        return None  # invalid / breached geometry for a protective long stop
    threshold = mean * (1 + tolerance_pct / 100.0)
    if stop <= threshold:
        return None
    gap_pct = round(100.0 * (stop - mean) / mean, 2)
    return {
        "symbol": str(symbol).upper(),
        "stop_price": round(stop, 2),
        "consensus_target_mean": round(mean, 2),
        "consensus_gap_pct": gap_pct,
        "consensus_analysts": consensus.get("n_analysts"),
        "consensus_source": consensus.get("source"),
        "current_price": round(float(current_price), 2) if current_price is not None else None,
        "advisory_only": True,
    }


def _merge_live_stop(live: dict[str, dict], sym: str, *, stop_price, order_type: str = "", trail_pct=None) -> None:
    sym = str(sym).upper()
    is_trail = "trail" in str(order_type).lower()
    sp = float(stop_price) if stop_price is not None else None
    if sp is None and not is_trail and trail_pct is None:
        return
    prev = live.get(sym)
    rank = sp if sp is not None else 0.0
    if prev is None or rank > (prev.get("stop_price") or 0):
        live[sym] = {
            "stop_price": sp,
            "is_trailing": is_trail or trail_pct is not None,
            "trail_pct": float(trail_pct) if trail_pct is not None else None,
        }


def _load_broker_live_stops(project_root: Path | None = None) -> dict[str, dict]:
    """Schwab/Alpaca live protective stops — same source as Stop Management tab."""
    root = project_root or Path(__file__).resolve().parent.parent.parent
    live: dict[str, dict] = {}
    try:
        import sys

        scripts = root / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        import open_trades_intelligence as oti

        holds = json.loads((root / "data" / "portfolios" / "state" / "holdings.json").read_text())
        broker_accts: list[str] = []
        for h in holds.get("holdings") or []:
            acct = str(h.get("account") or "")
            if acct.startswith("schwab") or "alpaca" in acct.lower():
                broker_accts.append(acct)
        for (_acct, sym), bs in (oti._broker_protective_stops(sorted(set(broker_accts))) or {}).items():
            _merge_live_stop(
                live,
                sym,
                stop_price=bs.get("stop_price"),
                order_type=str(bs.get("order_type") or ""),
                trail_pct=bs.get("trail_offset"),
            )
    except Exception:
        pass
    if not live:
        try:
            import urllib.request

            with urllib.request.urlopen("http://127.0.0.1:7777/api/v2/holdings/live-stops", timeout=20) as resp:
                payload = json.loads(resp.read().decode())
            for bs in ((payload.get("data") or payload).get("by_key") or {}).values():
                _merge_live_stop(
                    live,
                    bs.get("symbol"),
                    stop_price=bs.get("stop_price"),
                    order_type=str(bs.get("order_type") or ""),
                    trail_pct=bs.get("trail_offset"),
                )
        except Exception:
            pass
    return live


def load_live_stops_by_symbol(cur, project_root: Path | None = None) -> dict[str, dict]:
    """Max effective stop per symbol across broker API + monitored/confirmed DB stops."""
    live = _load_broker_live_stops(project_root)
    conn = getattr(cur, "connection", None)

    def _safe_query(fn):
        try:
            fn()
        except Exception:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass

    def _load_fidelity():
        cur.execute(
            """SELECT UPPER(symbol), COALESCE(effective_stop, stop_price), COALESCE(order_type,''), trail_pct
               FROM fidelity_monitored_stops
               WHERE lower(COALESCE(status,'')) = ANY(%s)
                 AND (COALESCE(effective_stop, stop_price) IS NOT NULL OR trail_pct IS NOT NULL)""",
            (list(LIVE_STATUS),),
        )
        for sym, sp, ot, trail in cur.fetchall():
            _merge_live_stop(live, sym, stop_price=sp, order_type=ot, trail_pct=trail)

    def _load_manual():
        cur.execute(
            """SELECT UPPER(symbol), stop_price, COALESCE(order_type,'')
               FROM manual_broker_stops
               WHERE lower(COALESCE(status,'')) = ANY(%s) AND stop_price IS NOT NULL""",
            (list(LIVE_STATUS),),
        )
        for sym, sp, ot in cur.fetchall():
            _merge_live_stop(live, sym, stop_price=sp, order_type=ot)

    def _load_confirmations():
        cur.execute(
            """SELECT UPPER(symbol), stop_price_confirmed FROM stop_confirmations
               WHERE stop_confirmed = true AND stop_price_confirmed IS NOT NULL"""
        )
        for sym, sp in cur.fetchall():
            _merge_live_stop(live, sym, stop_price=sp)

    def _load_lifecycle():
        cur.execute(
            """SELECT DISTINCT ON (UPPER(symbol)) UPPER(symbol), stop_price, COALESCE(order_type,'')
               FROM stop_lifecycle
               WHERE lower(COALESCE(status,'')) NOT IN ('rejected','canceled','cancelled','expired')
                 AND lower(COALESCE(lifecycle,'')) IN ('working','armed','active','live','placed')
               ORDER BY UPPER(symbol), snapshot_at DESC NULLS LAST"""
        )
        for sym, sp, ot in cur.fetchall():
            _merge_live_stop(live, sym, stop_price=sp, order_type=ot)

    for loader in (_load_fidelity, _load_manual, _load_confirmations, _load_lifecycle):
        _safe_query(loader)
    return live


def detect_conflicts(cur=None, project_root: Path | None = None) -> list[dict]:
    """Held symbols whose effective stop is above Street consensus mean."""
    from db_adapter import _get_conn

    conn = None
    if cur is None:
        conn = _get_conn()
        cur = conn.cursor()

    consensus = load_consensus_targets(project_root=project_root, cur=cur)
    live = load_live_stops_by_symbol(cur, project_root=project_root)
    prices: dict[str, float] = {}
    try:
        cur.execute(
            """SELECT DISTINCT ON (UPPER(symbol)) UPPER(symbol), price
               FROM market_quotes
               WHERE price IS NOT NULL AND fetched_at > NOW() - INTERVAL '24 hours'
               ORDER BY UPPER(symbol), fetched_at DESC"""
        )
        for sym, px in cur.fetchall():
            if px is not None:
                prices[str(sym).upper()] = float(px)
    except Exception:
        pass

    held: set[str] = set()
    root = project_root or Path(__file__).resolve().parent.parent.parent
    try:
        holds = json.loads((root / "data" / "portfolios" / "state" / "holdings.json").read_text())
        for h in holds.get("holdings") or []:
            sym = str(h.get("symbol") or "").upper()
            if sym and sym != "CASH" and not h.get("is_cash"):
                held.add(sym)
                px = h.get("current_price") or h.get("price")
                if px is not None:
                    prices.setdefault(sym, float(px))
    except Exception:
        pass

    out: list[dict] = []
    for sym in sorted(held):
        ls = live.get(sym)
        if not ls:
            continue
        px = prices.get(sym)
        stop = effective_stop_price(
            ls.get("stop_price"),
            is_trailing=bool(ls.get("is_trailing")),
            trail_pct=ls.get("trail_pct"),
            current_price=px,
        )
        hit = check_stop_over_consensus(sym, stop, px, consensus.get(sym))
        if hit:
            out.append(hit)
    if conn is not None:
        conn.close()
    return out