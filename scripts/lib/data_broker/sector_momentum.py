"""Sector Momentum — one exact multi-session sector ETF vs SPY read model.

Stored ticker_prices closes supply 5/20/60-session return differences. The
20/60-session signs determine posture; stored one-day quotes are context only.
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


def get_sector_signals(db_query, *, symbols=None) -> dict[str, Any]:
    """Read-only canonical sector RS over exact SPY sessions; no cache writes."""
    from lib.sector_signals import relative_strength

    requested = list(dict.fromkeys(symbols if symbols is not None else SECTOR_ETFS))
    rows = db_query(
        """SELECT upper(symbol) AS symbol, price_date, max(close_price) AS close_price
             FROM ticker_prices
            WHERE upper(symbol) = ANY(%s) AND price_date > CURRENT_DATE - 200
              AND close_price > 0
            GROUP BY upper(symbol), price_date ORDER BY upper(symbol), price_date""",
        (requested + ["SPY"],), fetch="all",
    ) or []
    prices = {}
    for row in rows:
        prices.setdefault(str(row["symbol"]).upper(), []).append((row["price_date"], row["close_price"]))
    sectors = {etf: relative_strength(prices.get(etf, []), prices.get("SPY", [])) for etf in requested}
    as_of = max((r["as_of"] or "" for r in sectors.values()), default="") or None
    try:
        sector_names = json.loads((PROJECT_ROOT / "config" / "sector_momentum.json").read_text())["sectors"]
    except (OSError, ValueError, KeyError):
        sector_names = {}
    for etf, signal in sectors.items():
        signal["sector"] = sector_names.get(etf)
    measured = any(not signal.get("gap") for etf, signal in sectors.items() if etf in sector_names)
    favoured = ([sector_names[etf] for etf, signal in sectors.items()
                 if etf in sector_names and signal["cio_posture"] == "Favoured"]
                if measured and sector_names else None)
    return {"as_of": as_of, "sectors": sectors, "source": "ticker_prices",
            "posture_basis": "20d_60d_vs_spy", "provider_calls": 0,
            "favoured": favoured,
            "favoured_gap": None if favoured is not None else "Complete sector strength or sector names unavailable"}


def _build(db_query) -> dict[str, Any]:
    """Multi-session signals; market quotes supply one-day context only."""
    out = get_sector_signals(db_query)
    quotes = db_query(
        """SELECT upper(symbol) AS symbol, day_change_pct, fetched_at
             FROM market_quotes WHERE upper(symbol) = ANY(%s)
              AND fetched_at > now() - interval '1 hour' ORDER BY fetched_at DESC""",
        (SECTOR_ETFS + ["SPY"],), fetch="all",
    ) or []
    from lib.sector_signals import number
    by_sym = {}
    for row in quotes:
        by_sym.setdefault(str(row.get("symbol") or "").upper(), number(row.get("day_change_pct")))
    spy = by_sym.get("SPY")
    for etf, signal in out["sectors"].items():
        change = by_sym.get(etf)
        signal.update(chg_pct=change, rel_pct=round(change - spy, 2) if change is not None and spy is not None else None,
                      label=signal["momentum"])
    return {**out, "computed_at": datetime.now(timezone.utc).isoformat(), "spy_chg_pct": spy}


def get_sector_momentum(db_query=None, max_age_s: float = DEFAULT_MAX_AGE_S) -> dict[str, Any]:
    """Return cached sector momentum if fresh, else recompute from stored closes and quote context.

    Args:
        db_query: a callable(sql, params, fetch="all"|"one") — required for recompute.
        max_age_s: max age before recompute (default 300s).
    """
    cached = None
    if SNAPSHOT_PATH.exists() and max_age_s > 0:
        try:
            cached = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
            if cached.get("posture_basis") != "20d_60d_vs_spy":
                cached = None
                raise ValueError("legacy one-day sector cache")
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
        return {"computed_at": "", "spy_chg_pct": None, "sectors": {}, "source": "unavailable"}

    fresh = _build(db_query)
    try:
        from lib.data_broker.atomic_json import atomic_write_json_soft
        atomic_write_json_soft(SNAPSHOT_PATH, fresh)
    except Exception:
        try:
            SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
            SNAPSHOT_PATH.write_text(json.dumps(fresh, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass
    fresh["_cache"] = {"hit": False, "age_seconds": 0}
    return fresh


# ── One Source of Truth, Phase 4 (2026-09-13) ────────────────────────────────
# The Sectors and Defense hubs json.load'ed runtime/sector_momentum_latest.json and
# runtime/industry_momentum_latest.json directly and served them 436–454h old as
# current. These readers are the only path now; each carries the read envelope
# (as_of, age_hours, source, stale, gap) from the registry's stale windows
# (sector_momentum 26h · industry_momentum 26h). sector_rs_daily is the domain's
# table; its 95-day RS history read moved here from api_v2 verbatim.

RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"
SECTOR_SNAPSHOT_FILE = "runtime/sector_momentum_latest.json"
INDUSTRY_SNAPSHOT_FILE = "runtime/industry_momentum_latest.json"

RS_HISTORY_SQL = """SELECT symbol, rs_date, rs FROM sector_rs_daily
                            WHERE rs_date > CURRENT_DATE - %s AND rs IS NOT NULL
                            ORDER BY symbol, rs_date"""


def _read_runtime_json(rel: str, runtime_dir: Path | None = None):
    p = (runtime_dir or RUNTIME_DIR) / Path(rel).name
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except Exception:
        return None


def _snapshot_as_of(snap) -> Any:
    if not isinstance(snap, dict):
        return None
    return snap.get("generated_at") or snap.get("captured_at") or snap.get("computed_at") or snap.get("as_of")


def get_sector_momentum_snapshot(*, runtime_dir: Path | None = None, now=None, registry=None, db_query=None) -> dict[str, Any]:
    """The sector_momentum_engine's disk snapshot (rows/states/transitions) + envelope.

    Returns {ok, snapshot: dict|None, <envelope>}. ``snapshot`` is the file's
    content untouched (the Defense desk renders it as-is); when the file is absent
    or has no rows, ``snapshot`` is None and the envelope says no_coverage.
    """
    from lib.data_broker.envelope import envelope

    snap = _read_runtime_json(SECTOR_SNAPSHOT_FILE, runtime_dir)
    has_rows = isinstance(snap, dict) and bool(snap.get("rows"))
    if has_rows:
        from lib.sector_signals import normalize_signal_row
        snap = {**snap, "rows": [normalize_signal_row(row) for row in snap["rows"]]}
        if db_query is not None:
            signals = get_sector_signals(db_query)
            snap["rows"] = [{**row, **signals["sectors"].get(row.get("etf"), {})} for row in snap["rows"]]
            snap["signals_as_of"] = signals.get("as_of")
    env = envelope("sector_momentum", _snapshot_as_of(snap) if has_rows else None, now=now, registry=registry,
                   source={"file": SECTOR_SNAPSHOT_FILE})
    out = {"ok": True, "snapshot": snap if has_rows else None, "provider_calls": 0}
    out.update(env)
    return out


def get_industry_momentum_snapshot(*, runtime_dir: Path | None = None, now=None, registry=None) -> dict[str, Any]:
    """finviz_industry_groups' disk snapshot (144 industry groups) + envelope.

    Returns {ok, snapshot: dict|None, <envelope>}."""
    from lib.data_broker.envelope import envelope

    snap = _read_runtime_json(INDUSTRY_SNAPSHOT_FILE, runtime_dir)
    has = isinstance(snap, dict) and bool(snap.get("industries"))
    env = envelope("industry_momentum", _snapshot_as_of(snap) if has else None, now=now, registry=registry,
                   source={"file": INDUSTRY_SNAPSHOT_FILE})
    out = {"ok": True, "snapshot": snap if has else None, "provider_calls": 0}
    out.update(env)
    return out


def get_sector_rs_history(db_query, *, days: int = 95, now=None, registry=None) -> dict[str, Any]:
    """{ok, series: {ETF: [rs, ...]}, <envelope>} from sector_rs_daily (writer sector_rs_daily.py)."""
    from lib.data_broker.envelope import envelope

    series: dict[str, list[float]] = {}
    last_date = None
    error = None
    try:
        for r in db_query(RS_HISTORY_SQL, (int(days),)) or []:
            series.setdefault(r["symbol"], []).append(float(r["rs"]))
            d = r.get("rs_date")
            if d is not None and (last_date is None or d > last_date):
                last_date = d
    except Exception as e:  # noqa: BLE001
        error = str(e)[:200]
    env = envelope("sector_momentum", last_date, now=now, registry=registry, source={"table": "sector_rs_daily"})
    out = {"ok": error is None, "series": series, "provider_calls": 0}
    if error:
        out["error"] = error
    out.update(env)
    return out
