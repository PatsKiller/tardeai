"""iv_history.py — ATM-IV snapshot history + honest IV rank (advisory-only).

IV-rank context layer for the options pipeline (2026-07-06). Three jobs:

  1. ``snapshot_iv(symbols)`` — read each symbol's option chain through the
     AST-proven read-only research adapter (``options_chain.fetch_chain_snapshot``
     → ``schwab_transport.get_option_chain``, chain reads ONLY), extract an
     ATM IV (near-the-money contracts, ~30-60 DTE, averaged; defensive on
     missing/NaN greeks) and upsert ONE row per symbol per day into
     ``options_iv_history`` (unique on ``(symbol, snapshot_date)``).
  2. ``iv_rank(symbol)`` — current ATM IV vs the min/max of stored history
     (52-week window) plus a percentile. HONEST DEGRADATION (HARD RULE):
     fewer than ``MIN_HISTORY_DAYS`` snapshots returns
     ``{"available": False, "reason": "insufficient history", "days": N}`` —
     a rank is NEVER fabricated from thin data.
  3. Cheap/rich verdict bands: rank < 30 → "extrinsic cheap", 30-70 →
     "normal", > 70 → "extrinsic rich — pay-up warning".

ADVISORY ONLY — IV context informs (edge-score modifier, disclosed card
line), it never rejects: no gate anywhere reads these outputs to refuse a
proposal. This module's only DB write surface is the options_iv_history
market-data table (never queues, orders, flags, or execution state), and it
never imports schwab_transport or any broker/submit module directly
(test-enforced by tests/test_options_iv_rank.py).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, Optional, Sequence

# ── policy constants ─────────────────────────────────────────────────────────

MIN_HISTORY_DAYS = 20        # below this: honest {"available": False}
HISTORY_WINDOW_DAYS = 370    # ~52-week rank window
ATM_DTE_WINDOW = (25, 70)    # "~30-60 DTE" with listing slack
ATM_STRIKE_BAND_PCT = 0.05   # near-the-money: strike within ±5% of spot
ATM_FALLBACK_NEAREST = 4     # if the ±5% band is empty: 4 nearest strikes
RANK_CHEAP_BELOW = 30.0
RANK_RICH_ABOVE = 70.0
IV_SOURCE = "schwab_chain_atm_30_60dte"

VERDICT_LABELS = {
    "extrinsic_cheap": "extrinsic cheap",
    "normal": "normal",
    "extrinsic_rich": "extrinsic rich — pay-up warning",
}

UPSERT_SQL = (
    "INSERT INTO options_iv_history "
    "(symbol, snapshot_date, iv_pct, atm_strike, underlying, source, meta_json) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s) "
    "ON CONFLICT (symbol, snapshot_date) DO UPDATE SET "
    "iv_pct = EXCLUDED.iv_pct, atm_strike = EXCLUDED.atm_strike, "
    "underlying = EXCLUDED.underlying, source = EXCLUDED.source, "
    "meta_json = EXCLUDED.meta_json, captured_at = NOW()"
)

HISTORY_SQL = (
    "SELECT snapshot_date, iv_pct FROM options_iv_history "
    "WHERE symbol = %s AND snapshot_date >= CURRENT_DATE - %s "
    "ORDER BY snapshot_date"
)


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x  # NaN guard (Schwab pads greeks with NaN)


def _iv_pct(v: Any) -> Optional[float]:
    """Normalize a chain IV to percent. Schwab sometimes carries decimals
    (0.35) and sometimes percents (35.0); <=3 is treated as a decimal."""
    x = _f(v)
    if x is None or x <= 0:
        return None
    return round(x * 100.0, 4) if x <= 3.0 else round(x, 4)


# ── ATM-IV extraction over a parsed chain snapshot (pure) ────────────────────

def extract_atm_iv(snapshot: dict[str, Any] | None) -> Optional[dict[str, Any]]:
    """ATM IV (percent) from an ``options_chain.parse_chain`` snapshot.

    Contracts near the money (strike within ±5% of spot, calls AND puts) in
    the ~30-60 DTE window, IVs averaged. Fallbacks are disclosed via
    ``method``: no expiration in the window → nearest-to-45-DTE expiration;
    empty strike band → 4 nearest strikes with usable IV. Missing/zero/NaN
    IVs are skipped defensively; no usable IV anywhere → None (never a
    fabricated number).
    """
    if not isinstance(snapshot, dict) or not snapshot.get("available"):
        return None
    spot = _f(snapshot.get("underlying_price"))
    if not spot or spot <= 0:
        return None
    lo_dte, hi_dte = ATM_DTE_WINDOW
    exps = [e for e in snapshot.get("expirations") or []
            if lo_dte <= int(_f(e.get("dte")) or 0) <= hi_dte]
    method = "dte_window"
    if not exps:
        all_exps = snapshot.get("expirations") or []
        if not all_exps:
            return None
        exps = [min(all_exps, key=lambda e: abs(int(_f(e.get("dte")) or 0) - 45))]
        method = "nearest_expiration_fallback"

    def _usable(exp: dict) -> Iterable[tuple[float, float, float, int]]:
        for c in exp.get("contracts") or []:
            ivp = _iv_pct(c.get("iv"))
            strike = _f(c.get("strike"))
            if ivp is None or strike is None or strike <= 0:
                continue
            yield (abs(strike - spot), strike, ivp, int(_f(exp.get("dte")) or 0))

    rows = [r for e in exps for r in _usable(e)]
    if not rows:
        return None
    band = [r for r in rows if r[0] / spot <= ATM_STRIKE_BAND_PCT]
    if not band:
        band = sorted(rows)[:ATM_FALLBACK_NEAREST]
        method += "+nearest_strikes"
    atm_iv = round(sum(r[2] for r in band) / len(band), 3)
    return {
        "atm_iv": atm_iv,                      # percent, e.g. 35.2
        "atm_strike": min(band)[1],
        "underlying": spot,
        "contracts_used": len(band),
        "dtes_used": sorted({r[3] for r in band}),
        "method": method,
    }


# ── rank math (pure) + verdict bands ─────────────────────────────────────────

def verdict_for_rank(rank: float) -> tuple[str, str]:
    """(verdict, label): <30 cheap · 30-70 normal · >70 rich (pay-up warning)."""
    r = float(rank)
    if r < RANK_CHEAP_BELOW:
        v = "extrinsic_cheap"
    elif r > RANK_RICH_ABOVE:
        v = "extrinsic_rich"
    else:
        v = "normal"
    return v, VERDICT_LABELS[v]


def rank_from_series(history: Sequence[float], current: float) -> dict[str, Any]:
    """IV rank + percentile of ``current`` against a daily ATM-IV series.

    rank = (current − min) / (max − min) × 100 with current included in the
    range (so rank is always 0-100); percentile = share of stored days at or
    below current. HONEST: < MIN_HISTORY_DAYS stored days, or a degenerate
    zero-range series, returns {"available": False, ...} — never a number
    pretending to be a rank.
    """
    vals = [v for v in (_f(x) for x in history or []) if v is not None and v > 0]
    days = len(vals)
    cur = _f(current)
    if cur is None or cur <= 0:
        return {"available": False, "reason": "no current ATM IV", "days": days,
                "required_days": MIN_HISTORY_DAYS}
    if days < MIN_HISTORY_DAYS:
        return {"available": False, "reason": "insufficient history",
                "days": days, "required_days": MIN_HISTORY_DAYS,
                "atm_iv": round(cur, 3)}
    lo, hi = min(vals + [cur]), max(vals + [cur])
    if hi <= lo:
        return {"available": False, "reason": "degenerate history (zero IV range)",
                "days": days, "required_days": MIN_HISTORY_DAYS,
                "atm_iv": round(cur, 3)}
    rank = round((cur - lo) / (hi - lo) * 100.0, 1)
    percentile = round(sum(1 for v in vals if v <= cur) / days * 100.0, 1)
    verdict, label = verdict_for_rank(rank)
    return {
        "available": True,
        "atm_iv": round(cur, 3),
        "iv_rank": rank,
        "percentile": percentile,
        "iv_low": round(lo, 3),
        "iv_high": round(hi, 3),
        "days": days,
        "required_days": MIN_HISTORY_DAYS,
        "verdict": verdict,
        "verdict_label": label,
    }


# ── DB-backed rank lookup ────────────────────────────────────────────────────

def _read_history(symbol: str) -> Optional[list[float]]:
    """Stored daily ATM IVs (52-week window, date order); None = DB unavailable."""
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return None
        rows = _execute(HISTORY_SQL, ((symbol or "").upper(), HISTORY_WINDOW_DAYS),
                        fetch="all")
        if rows is None:
            return None
        return [v for v in (_f(dict(r).get("iv_pct")) for r in rows) if v is not None]
    except Exception:
        return None


def iv_rank(symbol: str, current_iv: Optional[float] = None, *,
            history: Optional[Sequence[float]] = None) -> dict[str, Any]:
    """IV-rank context for a symbol: {available, atm_iv, iv_rank, percentile,
    verdict, verdict_label, days, ...} or an honest {"available": False, ...}.

    ``current_iv`` (percent) usually comes from the live chain snapshot the
    caller already holds; when omitted, the most recent stored snapshot is
    used. ``history`` is injectable for tests.
    """
    sym = (symbol or "").strip().upper()
    base = {"symbol": sym, "source": IV_SOURCE,
            "window_days": HISTORY_WINDOW_DAYS,
            "generated_at": datetime.now(timezone.utc).isoformat()}
    series = list(history) if history is not None else _read_history(sym)
    if series is None:
        return {**base, "available": False, "days": 0,
                "required_days": MIN_HISTORY_DAYS,
                "reason": "iv history unavailable (no DB)"}
    cur = _f(current_iv)
    if cur is None and series:
        cur = _f(series[-1])
    return {**base, **rank_from_series(series, cur if cur is not None else 0.0)}


# ── daily snapshot writer (one upsert per symbol per day) ────────────────────

def _default_execute(sql: str, params: tuple) -> bool:
    from db_adapter import _execute, USE_DB
    if not USE_DB:
        raise RuntimeError("DB disabled (USE_DB=false)")
    if _execute(sql, params) is None:
        raise RuntimeError("db_adapter._execute returned None (SQL error)")
    return True


def snapshot_iv(symbols: Sequence[str], *,
                snapshot_date: Optional[str] = None,
                strike_count: int = 24,
                dry_run: bool = False,
                fetch_fn: Optional[Callable[..., dict]] = None,
                execute_fn: Optional[Callable[[str, tuple], Any]] = None) -> dict[str, Any]:
    """Capture today's ATM IV for each symbol → upsert into options_iv_history.

    Idempotent per day: re-running replaces the same (symbol, snapshot_date)
    row (ON CONFLICT upsert), never a duplicate. Chain-unavailable symbols are
    reported in ``skipped`` with honest reasons; nothing is fabricated.
    ``fetch_fn``/``execute_fn`` are injectable for tests; chain reads default
    to the read-only research adapter.
    """
    day = str(snapshot_date or date.today().isoformat())[:10]
    if fetch_fn is None:
        from .options_chain import fetch_chain_snapshot as fetch_fn  # noqa: F811
    execute = execute_fn or _default_execute

    captured: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    written = 0
    for raw_sym in symbols or []:
        sym = (raw_sym or "").strip().upper()
        if not sym:
            continue
        try:
            snap = fetch_fn(sym, strike_count=strike_count)
        except Exception as e:
            skipped.append({"symbol": sym, "reason": f"chain read error: {str(e)[:120]}"})
            continue
        if not (snap or {}).get("available"):
            skipped.append({"symbol": sym,
                            "reason": (snap or {}).get("reason") or "chain unavailable"})
            continue
        atm = extract_atm_iv(snap)
        if atm is None:
            skipped.append({"symbol": sym,
                            "reason": "no usable ATM IV (missing/zero greeks in the "
                                      "30-60 DTE near-the-money band)"})
            continue
        row = {"symbol": sym, "snapshot_date": day, "atm_iv": atm["atm_iv"],
               "atm_strike": atm["atm_strike"], "underlying": atm["underlying"],
               "iv_source": IV_SOURCE,
               "meta": {"contracts_used": atm["contracts_used"],
                        "dtes_used": atm["dtes_used"], "method": atm["method"]}}
        captured.append(row)
        if dry_run:
            continue
        try:
            execute(UPSERT_SQL, (sym, day, atm["atm_iv"], atm["atm_strike"],
                                 atm["underlying"], IV_SOURCE,
                                 json.dumps(row["meta"])))
            written += 1
        except Exception as e:
            skipped.append({"symbol": sym, "reason": f"db write failed: {str(e)[:120]}"})

    return {
        "ok": True,
        "snapshot_date": day,
        "dry_run": bool(dry_run),
        "symbols_requested": len(list(symbols or [])),
        "captured": captured,
        "skipped": skipped,
        "rows_written": written,
        "source": IV_SOURCE,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
