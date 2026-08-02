"""Sector Momentum — Data Broker read model for sector ETF vs SPY relative strength.

Computes sector momentum from market_quotes (XLK, XLF, XLE, XLI, XLB, XLRE, XLUC, XLV,
XLY, XLC, XLU, XLP, SMH, IBB vs SPY day_change_pct). Used by Hermes scorer's _sector_momentum factor.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SNAPSHOT_DIR = PROJECT_ROOT / "state" / "data_broker"
SNAPSHOT_PATH = SNAPSHOT_DIR / "sector_momentum.json"
DEFAULT_MAX_AGE_S = 300  # 5 min

SECTOR_ETFS = [
    "XLK", "XLF", "XLE", "XLI", "XLB", "XLRE", "XLV",
    "XLY", "XLC", "XLU", "XLP", "SMH", "IBB",
]


def _build(db_query) -> dict[str, Any]:
    """Recompute sector momentum from market_quotes."""
    all_syms = SECTOR_ETFS + ["SPY"]
    rows = db_query(
        """SELECT upper(symbol) AS symbol, day_change_pct, price, fetched_at
           FROM market_quotes
           WHERE upper(symbol) = ANY(%s)
             AND fetched_at > now() - interval '1 hour'
           ORDER BY fetched_at DESC""",
        (all_syms,),
        fetch="all",
    ) or []
    by_sym: dict[str, float] = {}
    seen: set[str] = set()
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        chg = row.get("day_change_pct")
        if sym not in seen and chg is not None:
            try:
                by_sym[sym] = float(chg)
            except (TypeError, ValueError):
                pass
            seen.add(sym)

    spy_chg = by_sym.get("SPY", 0)
    sectors: dict[str, Any] = {}
    for etf in SECTOR_ETFS:
        etf_chg = by_sym.get(etf)
        if etf_chg is None:
            sectors[etf] = {"chg_pct": None, "rel": None, "label": "missing"}
            continue
        rel = etf_chg - spy_chg
        if rel > 0.5:
            label = "leading"
        elif rel < -0.5:
            label = "lagging"
        else:
            label = "neutral"
        sectors[etf] = {"chg_pct": round(etf_chg, 2), "rel_pct": round(rel, 2), "label": label}

    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "spy_chg_pct": round(spy_chg, 2),
        "sectors": sectors,
        "source": "market_quotes",
    }


def get_sector_momentum(db_query=None, max_age_s: float = DEFAULT_MAX_AGE_S) -> dict[str, Any]:
    """Return cached sector momentum if fresh, else recompute from market_quotes.

    Args:
        db_query: a callable(sql, params, fetch="all"|"one") — required for recompute.
        max_age_s: max age before recompute (default 300s).
    """
    cached = None
    if SNAPSHOT_PATH.exists() and max_age_s > 0:
        try:
            cached = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
            age = (time.time() - datetime.fromisoformat(cached["computed_at"]).timestamp())
            if age <= max_age_s:
                cached["_cache"] = {"hit": True, "age_seconds": round(age, 1)}
                return cached
        except Exception:
            cached = None

    if db_query is None:
        if cached:
            cached["_cache"] = {"hit": True, "age_seconds": 0, "stale": True}
            return cached
        return {"computed_at": "", "spy_chg_pct": 0, "sectors": {}, "source": "unavailable"}

    fresh = _build(db_query)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SNAPSHOT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(fresh, indent=2, default=str), encoding="utf-8")
    tmp.replace(SNAPSHOT_PATH)
    fresh["_cache"] = {"hit": False, "age_seconds": 0}
    return fresh
