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

W1: financial totals/counts delegate to cio_truth.portfolio_for over one holdings valuation clock.
Status: existing consumers retain their envelope and cache semantics —
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
import os
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

#: Overrides the default when set. Read at CALL time, never at import.
STATE_DIR_ENV = "TRADEAI_DATA_BROKER_STATE_DIR"

#: The import-time default, kept so an explicit patch of SNAPSHOT_PATH is
#: distinguishable from the untouched default.
_DEFAULT_SNAPSHOT_PATH = SNAPSHOT_PATH


def _snapshot_path() -> Path:
    """Where the snapshot lives, resolved per call.

    SNAPSHOT_PATH was computed from PROJECT_ROOT at import, which made this
    module unredirectable once loaded. Not theoretical: a test suite reaching
    this writer created state/data_broker/ inside the repository, and on a fresh
    CI clone the next gate then read a state root that existed only because a
    test put it there (test_whole_site_truth, 2026-09-13).

    Precedence, and the order matters:

      1. SNAPSHOT_PATH, if a caller has rebound it. Existing tests monkeypatch
         that constant and expect the writer to follow -- a supported patch point
         that must keep working.
      2. TRADEAI_DATA_BROKER_STATE_DIR, if set.
      3. The import-time default.

    Rule 2 is an ENVIRONMENT VARIABLE rather than another constant on purpose.
    This package is importable as both `lib.data_broker.x` and
    `scripts.lib.data_broker.x` -- distinct module objects with distinct copies
    of every constant, which the repo enforces in test_scripts_lib_bootstrap.
    Patching a constant reaches one and silently misses the other; the
    environment is process-global and has no such ambiguity. Rule 1 still works
    because it is read from whichever module object is actually executing.
    """
    if SNAPSHOT_PATH != _DEFAULT_SNAPSHOT_PATH:
        return SNAPSHOT_PATH
    override = os.environ.get(STATE_DIR_ENV, "").strip()
    if override:
        return Path(override) / "portfolio_snapshot.json"
    return SNAPSHOT_PATH


def _snapshot_dir() -> Path:
    return _snapshot_path().parent


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _sector_allocation(h: dict, active_positions: list[dict]) -> list[tuple[str, float]]:
    """Prefer the pipeline's look-through breakdown (funds decomposed into underlying
    sectors); holding rows carry no sector field, so per-row aggregation alone collapses
    everything into 'Other'. Mirrors api_v2.overview()'s sector logic exactly."""
    resolved = h.get("resolved_sectors")
    if isinstance(resolved, list) and resolved:
        return [
            (r.get("sector") or "Other / Unclassified", r.get("value") or 0)
            for r in resolved
            if (r.get("value") or 0) > 0
        ][:13]
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

    from ..cio_truth import portfolio_for
    truth = portfolio_for(h)
    holdings = truth["holdings"]
    totals = h.get("portfolio_totals", {})
    active_positions = [p for p in holdings if not p.get("is_cash") and not p.get("is_loan")
                        and (p.get("shares") or p.get("quantity") or 0) > 0
                        and (p.get("market_value") or 0) >= 100]

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

    today_change, total_val, today_pct = truth["day_pl_usd"], truth["total_usd"], truth["day_pl_pct"]
    today_by_account = {}
    for account in truth["accounts"]:
        value, change = account["total_usd"], account["day_pl_usd"]
        base = value - change if value is not None and change is not None else None
        today_by_account[account["account_id"]] = {
            "value": value, "change": change, "account_label": account["account_label"],
            "pct": round(change / base * 100, 2) if base is not None and base > 0 else None,
        }

    # ── SoT Phase 6: per-account state, read from what the producer wrote ─────
    # A non-LIVE account renders its last known value with its date and a state
    # label; the total says by name what it left out. No shell, no invention.
    try:
        from lib.account_state import project_account_states

        account_states = project_account_states(h)
    except Exception as e:  # noqa: BLE001
        errors.append(f"account_states: {e}")
        account_states = {"accounts": {}, "excluded_accounts": [], "stale_accounts": [],
                          "unclassified_accounts": sorted((h.get("account_summaries") or {}).keys())}
    for a, d in today_by_account.items():
        st = (account_states.get("accounts") or {}).get(a) or {}
        d["state"] = st.get("state", "UNCLASSIFIED")
        d["display_value"] = st.get("display_value", d.get("value"))
        d["display_value_as_of"] = st.get("display_value_as_of")

    now = datetime.now(timezone.utc)
    holdings_mtime = None
    try:
        holdings_mtime = datetime.fromtimestamp(
            (STATE_DIR / "holdings.json").stat().st_mtime, tz=timezone.utc
        ).isoformat()
    except OSError:
        pass

    return {
        "version": SNAPSHOT_VERSION,
        "computed_at": now.isoformat(),
        "source": {
            "holdings_json_mtime": holdings_mtime,
            "holdings_count": len(holdings),
            "active_position_count": truth["position_count"],
        },
        "totals": {
            "total_value": total_val,
            "total_cash": truth["cash_usd"],
            "day_change": round(today_change, 2) if today_change is not None else None,
            "day_change_pct": today_pct,
            "portfolio_totals_raw": totals,
        },
        "sector_allocation": [{"sector": s, "value": v} for s, v in sector_list],
        "top_movers": [
            {
                "symbol": p.get("symbol"),
                "day_change": p.get("day_change"),
                "market_value": p.get("market_value"),
                "account": p.get("account"),
            }
            for p in movers
        ],
        "by_account": today_by_account,
        "position_counts": truth["position_counts"],
        "truth": {k: truth[k] for k in ("source", "as_of", "stale", "gap")},
        "account_states": account_states,
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
    try:
        from lib.data_broker.atomic_json import atomic_write_json

        atomic_write_json(_snapshot_path(), snap)
    except Exception:
        _snapshot_dir().mkdir(parents=True, exist_ok=True)
        _snapshot_path().write_text(
            json.dumps(snap, indent=2, default=str), encoding="utf-8"
        )
    return _snapshot_path()


def read_portfolio_snapshot() -> dict[str, Any] | None:
    path = _snapshot_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_portfolio_snapshot(
    max_age_s: float = DEFAULT_MAX_AGE_S,
    *,
    write_on_miss: bool = True,
) -> dict[str, Any]:
    """Return the on-disk snapshot if fresh enough, else recompute and return.

    ``write_on_miss=False`` recomputes in memory and publishes nothing. A read
    request must not mutate a store: the audit
    (cc-truth-v1-20260902T202759Z) found that ``GET /api/v2/overview`` wrote
    ``portfolio_snapshot.json`` on every cache miss, which means the snapshot
    was refreshed by whoever happened to browse rather than on a schedule, and
    a plain GET was not a read.

    The default stays ``True`` so the four existing callers keep their current
    behaviour exactly; only the overview read path opts out.
    """
    cached = read_portfolio_snapshot()
    if cached and max_age_s > 0:
        try:
            computed_at = datetime.fromisoformat(cached["computed_at"])
            age = (datetime.now(timezone.utc) - computed_at).total_seconds()
            if age <= max_age_s:
                cached["_cache"] = {"hit": True, "age_seconds": round(age, 1), "wrote": False}
                return cached
        except Exception:
            pass
    fresh = build_portfolio_snapshot()
    wrote = False
    if write_on_miss:
        write_portfolio_snapshot(fresh)
        wrote = True
    fresh["_cache"] = {"hit": False, "age_seconds": 0, "wrote": wrote}
    return fresh


if __name__ == "__main__":
    print(json.dumps(get_portfolio_snapshot(max_age_s=0), indent=2, default=str))
