"""Indicator Snapshot — Data Broker read model for computed technicals.

Batch-reads indicator_confluence_cache (canonical store per config/data_registry.yaml)
and normalizes rsi_14, sma_20_50_200, macd, atr_14 for portfolio/holdings overlay.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SNAPSHOT_VERSION = "indicator-snapshot-v1"
SNAPSHOT_DIR = PROJECT_ROOT / "state" / "data_broker"
SNAPSHOT_PATH = SNAPSHOT_DIR / "indicator_snapshot.json"
DEFAULT_MAX_AGE_S = 900
DEFAULT_PROFILE = "swing"


def _db_query(sql: str, params=None, fetch: str = "all"):
    scripts = str(PROJECT_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from db_adapter import _get_conn

    conn = _get_conn()
    if not conn:
        return [] if fetch == "all" else None
    cur = conn.cursor()
    cur.execute(sql, params or [])
    if fetch == "one":
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _parse_signals(full_result: Any) -> dict[str, Any]:
    if isinstance(full_result, str):
        try:
            full_result = json.loads(full_result)
        except Exception:
            return {}
    if not isinstance(full_result, dict):
        return {}
    return full_result.get("signals") or {}


def _normalize_symbol_row(symbol: str, full_result: Any, atr_col: Any = None) -> dict[str, Any]:
    sig = _parse_signals(full_result)
    rsi = (sig.get("rsi") or {})
    sma = (sig.get("sma") or {})
    macd = (sig.get("macd") or {})
    atr_sig = (sig.get("atr") or {})

    sma_details = sma.get("details") or {}
    macd_details = macd.get("details") or {}
    atr_details = atr_sig.get("details") or {}

    sma20 = sma_details.get("sma_20")
    sma50 = sma_details.get("sma_50")
    sma200 = sma_details.get("sma_200")
    price = sma_details.get("price") or sma_details.get("last_close")

    def _pct_above(sma_val):
        if price and sma_val:
            try:
                return round((float(price) - float(sma_val)) / float(sma_val) * 100, 2)
            except (TypeError, ValueError, ZeroDivisionError):
                return None
        return None

    atr_val = atr_col
    if atr_val is None:
        atr_val = atr_details.get("atr") or atr_sig.get("value")

    return {
        "symbol": symbol.upper(),
        "rsi": rsi.get("value"),
        "rsi_status": rsi.get("signal"),
        "sma20_pct": _pct_above(sma20),
        "sma50_pct": _pct_above(sma50),
        "sma200_pct": _pct_above(sma200),
        "sma_20": sma20,
        "sma_50": sma50,
        "sma_200": sma200,
        "macd_signal": macd.get("signal"),
        "macd_histogram_direction": macd_details.get("histogram_direction"),
        "macd_is_real": True,
        "atr": atr_val,
        "alignment": sma_details.get("alignment"),
        "source": "indicator_confluence_cache",
    }


def build_indicator_snapshot(symbols: list[str], profile: str = DEFAULT_PROFILE) -> dict[str, Any]:
    symbols = sorted({str(s).upper() for s in symbols if s})
    by_symbol: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    if not symbols:
        return {
            "version": SNAPSHOT_VERSION,
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "profile": profile,
            "symbols": [],
            "by_symbol": {},
            "ok": True,
            "errors": [],
        }

    try:
        rows = _db_query(
            """
            SELECT DISTINCT ON (symbol) symbol, full_result, atr, computed_at
            FROM indicator_confluence_cache
            WHERE symbol = ANY(%s) AND profile = %s
            ORDER BY symbol, computed_at DESC
            """,
            (symbols, profile),
        ) or []
        for row in rows:
            sym = str(row.get("symbol") or "").upper()
            if sym:
                by_symbol[sym] = _normalize_symbol_row(sym, row.get("full_result"), row.get("atr"))
    except Exception as e:
        errors.append(f"db_read: {e}")

    return {
        "version": SNAPSHOT_VERSION,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "symbols": symbols,
        "by_symbol": by_symbol,
        "ok": not errors,
        "errors": errors,
    }


def get_indicator_snapshot(
    symbols: list[str],
    profile: str = DEFAULT_PROFILE,
    max_age_s: float = DEFAULT_MAX_AGE_S,
) -> dict[str, Any]:
    """Cached indicator snapshot keyed by sorted symbol list + profile."""
    key = {"symbols": sorted({str(s).upper() for s in symbols if s}), "profile": profile}
    cached = None
    if SNAPSHOT_PATH.exists() and max_age_s > 0:
        try:
            cached = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
            age = (time.time() - datetime.fromisoformat(cached["computed_at"]).timestamp())
            if cached.get("_cache_key") == key and age <= max_age_s:
                cached["_cache"] = {"hit": True, "age_seconds": round(age, 1)}
                return cached
        except Exception:
            cached = None

    fresh = build_indicator_snapshot(symbols, profile=profile)
    fresh["_cache_key"] = key
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SNAPSHOT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(fresh, indent=2, default=str), encoding="utf-8")
    tmp.replace(SNAPSHOT_PATH)
    fresh["_cache"] = {"hit": False, "age_seconds": 0}
    return fresh
