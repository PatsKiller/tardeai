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


def get_sector_momentum_snapshot(*, runtime_dir: Path | None = None, now=None, registry=None) -> dict[str, Any]:
    """The sector_momentum_engine's disk snapshot (rows/states/transitions) + envelope.

    Returns {ok, snapshot: dict|None, <envelope>}. ``snapshot`` is the file's
    content untouched (the Defense desk renders it as-is); when the file is absent
    or has no rows, ``snapshot`` is None and the envelope says no_coverage.
    """
    from lib.data_broker.envelope import envelope

    snap = _read_runtime_json(SECTOR_SNAPSHOT_FILE, runtime_dir)
    has_rows = isinstance(snap, dict) and bool(snap.get("rows"))
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
