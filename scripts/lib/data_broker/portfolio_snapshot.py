"""Portfolio Snapshot — the Data Broker's Phase 4 read model (outcome_bus pattern).

ONE versioned, atomically-published aggregate of holdings + live prices + day-change +
sector allocation + top movers + basic risk overlay, computed ONCE per refresh instead of
independently re-loaded/re-aggregated by every hot endpoint (/overview, /portfolio/holdings,
/risk, /portfolio/book-map each currently do their own holdings.json load + aggregation —
~83 independent loads inside api_v2.py alone; see docs/DATA_ARCHITECTURE_AUDIT_2026_07_31.md
sec 3 & 5, and config/data_registry.yaml:portfolio_snapshot).

Deliberately JSON-file-sourced (holdings.json, performance_history.json, risk_management.json,
finviz_quote_cache.json) — NOT a DB read — so it: (a) works in JSON-only mode exactly like the
rest of the read path it's replacing, (b) can be computed and unit-tested without a live
Postgres connection, and (c) matches the existing `data/runtime/*_latest.json` cron-materialization
pattern (warm_caches.py) already used by trade-ai/rotation/defense/symbol-cards.

Status: ADDITIVE. This module does not yet replace any existing endpoint's live code path —
see the migration note at the bottom of this docstring and config/data_registry.yaml. It is
served read-only via GET /api/v2/data/portfolio-snapshot for inspection/testing today; wiring
/overview, /portfolio/holdings, /risk, /portfolio/book-map to READ this instead of
re-aggregating holdings.json themselves is the next, higher-risk step (requires side-by-side
verification against live numbers before cutover — tracked in the registry, not done blind).

Usage:
    from lib.data_broker.portfolio_snapshot import get_portfolio_snapshot
    snap = get_portfolio_snapshot()               # cached (<=45s old) or freshly computed
    snap = get_portfolio_snapshot(max_age_s=0)     # force recompute
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
SNAPSHOT_VERSION = "portfolio-snapshot-v1"
SNAPSHOT_DIR = PROJECT_ROOT / "state" / "data_broker"
SNAPSHOT_PATH = SNAPSHOT_DIR / "portfolio_snapshot.json"
DEFAULT_MAX_AGE_S = 45


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _day_change(holdings: list[dict], finviz_cache: dict[str, Any]) -> float | None:
    """Mirrors api_v2._live_portfolio_day_change: recompute per-holding day $ from the fresh
    Finviz day % so a repricer-written $0 (prev_price == new_price at write time) doesn't
    silently under-count the header total. Same shared helper as /overview and
    /portfolio/performance so all three surfaces agree once this snapshot is adopted."""
    try:
        lib_dir = str(PROJECT_ROOT / "scripts" / "lib")
        if lib_dir not in sys.path:
            sys.path.insert(0, lib_dir)
        from holding_day_change import resolve_holding_day_change

        day_pct: dict[str, float] = {}
        px: dict[str, float] = {}
        for sym, row in (finviz_cache or {}).items():
            if not isinstance(row, dict):
                continue
            u = str(sym).upper()
            if row.get("change_pct") is not None:
                try:
                    day_pct[u] = float(row["change_pct"])
                except (TypeError, ValueError):
                    pass
            if row.get("price"):
                try:
                    px[u] = float(row["price"])
                except (TypeError, ValueError):
                    pass

        total = 0.0
        for p in holdings or []:
            if p.get("is_cash") or p.get("is_loan"):
                continue
            u = str(p.get("symbol") or "").upper()
            fv_px = px.get(u)
            shares = float(p.get("shares") or 0)
            mv = (shares * fv_px) if (fv_px and shares) else float(p.get("market_value") or 0)
            price = fv_px or float(p.get("price") or 0)
            dc, _ = resolve_holding_day_change(p, market_value=mv, price=price, stale_price=price,
                                                finviz_day_pct=day_pct.get(u))
            total += dc or 0
        return round(total, 2)
    except Exception:
        return None


def _sector_allocation(h: dict, active_positions: list[dict]) -> list[tuple[str, float]]:
    """Prefer the pipeline's look-through breakdown (funds decomposed into underlying
    sectors); holding rows carry no sector field, so per-row aggregation alone collapses
    everything into 'Other'. Mirrors api_v2.overview()'s sector logic exactly."""
    resolved = h.get("resolved_sectors")
    if isinstance(resolved, list) and resolved:
        return [(r.get("sector") or "Other / Unclassified", r.get("value") or 0)
                for r in resolved if (r.get("value") or 0) > 0][:13]
    sectors: dict[str, float] = {}
    for p in active_positions:
        s = p.get("sector_type") or "Other"
        sectors[s] = sectors.get(s, 0) + (p.get("market_value") or 0)
    return sorted(sectors.items(), key=lambda x: -x[1])[:10]


def build_portfolio_snapshot() -> dict[str, Any]:
    """Compute a fresh snapshot from current JSON state. Never raises -- returns a
    best-effort partial snapshot (with `errors`) rather than crashing a caller/timer."""
    errors: list[str] = []
    h = _load_json(STATE_DIR / "holdings.json")
    perf = _load_json(STATE_DIR / "performance_history.json")
    risk = _load_json(STATE_DIR / "risk_management.json")
    finviz_cache = _load_json(STATE_DIR / "finviz_quote_cache.json")

    holdings = h.get("holdings", [])
    totals = h.get("portfolio_totals", {})
    active_positions = [p for p in holdings if not p.get("is_cash") and (p.get("market_value") or 0) > 100]

    try:
        sector_list = _sector_allocation(h, active_positions)
    except Exception as e:
        errors.append(f"sector_allocation: {e}")
        sector_list = []

    try:
        movers = sorted(active_positions, key=lambda p: abs(p.get("day_change") or 0), reverse=True)[:6]
    except Exception as e:
        errors.append(f"movers: {e}")
        movers = []

    today_change = _day_change(holdings, finviz_cache)
    if today_change is None or today_change == 0:
        today_change = totals.get("day_change")
        if today_change is None:
            today_change = sum(p.get("day_change") or 0 for p in holdings)
    total_val = totals.get("total_value", 0) or 0
    today_pct = (today_change / (total_val - today_change) * 100) if total_val > abs(today_change or 0) else 0

    today_by_account: dict[str, dict[str, Any]] = {}
    for p in holdings:
        a = p.get("account") or "unknown"
        d = today_by_account.setdefault(a, {"change": 0.0, "value": 0.0})
        d["change"] += p.get("day_change") or 0
        d["value"] += p.get("market_value") or 0
    for a, d in today_by_account.items():
        base = d["value"] - d["change"]
        d["change"] = round(d["change"], 2)
        d["pct"] = round(d["change"] / base * 100, 2) if base > 0 else None
        d["value"] = round(d["value"], 2)

    now = datetime.now(timezone.utc)
    holdings_mtime = None
    try:
        holdings_mtime = datetime.fromtimestamp(
            (STATE_DIR / "holdings.json").stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        pass

    return {
        "version": SNAPSHOT_VERSION,
        "computed_at": now.isoformat(),
        "source": {
            "holdings_json_mtime": holdings_mtime,
            "holdings_count": len(holdings),
            "active_position_count": len(active_positions),
        },
        "totals": {
            "total_value": total_val,
            "day_change": round(today_change, 2) if today_change is not None else None,
            "day_change_pct": round(today_pct, 3) if today_pct else 0,
            "portfolio_totals_raw": totals,
        },
        "sector_allocation": [{"sector": s, "value": v} for s, v in sector_list],
        "top_movers": [{"symbol": p.get("symbol"), "day_change": p.get("day_change"),
                         "market_value": p.get("market_value"), "account": p.get("account")}
                        for p in movers],
        "by_account": today_by_account,
        "risk": {
            "portfolio_heat_pct": risk.get("portfolio_heat_pct", 0),
            "source_present": bool(risk),
        },
        "errors": errors,
        "ok": not errors,
    }


def write_portfolio_snapshot(snapshot: dict[str, Any] | None = None) -> Path:
    """Atomically publish the snapshot (tmp + replace), outcome_bus style. No history dir --
    this refreshes every 30-60s and callers only ever want the latest, unlike outcome_bus's
    audit-trail use case."""
    snap = snapshot if snapshot is not None else build_portfolio_snapshot()
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SNAPSHOT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snap, indent=2, default=str), encoding="utf-8")
    tmp.replace(SNAPSHOT_PATH)
    return SNAPSHOT_PATH


def read_portfolio_snapshot() -> dict[str, Any] | None:
    if not SNAPSHOT_PATH.exists():
        return None
    try:
        return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_portfolio_snapshot(max_age_s: float = DEFAULT_MAX_AGE_S) -> dict[str, Any]:
    """Return the on-disk snapshot if fresh enough, else recompute + publish + return."""
    cached = read_portfolio_snapshot()
    if cached and max_age_s > 0:
        try:
            computed_at = datetime.fromisoformat(cached["computed_at"])
            age = (datetime.now(timezone.utc) - computed_at).total_seconds()
            if age <= max_age_s:
                cached["_cache"] = {"hit": True, "age_seconds": round(age, 1)}
                return cached
        except Exception:
            pass
    fresh = build_portfolio_snapshot()
    write_portfolio_snapshot(fresh)
    fresh["_cache"] = {"hit": False, "age_seconds": 0}
    return fresh


if __name__ == "__main__":
    print(json.dumps(get_portfolio_snapshot(max_age_s=0), indent=2, default=str))
