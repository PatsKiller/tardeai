"""Risk Snapshot — Data Broker read model for portfolio risk overview.

Computes portfolio heat, position-level risk (delta, beta, VaR approximations),
stop health, and correlation data from risk_management.json, holdings.json,
and mark_quotes. Provides the structured risk data that /api/v2/risk needs,
replacing the repeated file loads in the risk() endpoint.

Data sources:
  - risk_management.json  (positions, portfolio_heat_pct, total_risk_dollars)
  - stops.json            (per-symbol stop levels)
  - holdings.json         (live prices, share counts)
  - mark_quotes DB        (beta, delta approximations from daily returns)
  - stop_confirmations DB (operator-confirmed stop levels)

Status: ADDITIVE. Does not replace the broker-protective-stop overlay (that still
requires the live open_trades_intelligence import in the endpoint handler). Covers
the JSON-file aggregation (risk heat, position risk, stop health, correlation)
which is ~70% of the endpoint's work.
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
SNAPSHOT_DIR = PROJECT_ROOT / "state" / "data_broker"
SNAPSHOT_PATH = SNAPSHOT_DIR / "risk_snapshot.json"
DEFAULT_MAX_AGE_S = 45


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _compute_beta(market_moves: list[float], stock_moves: list[float]) -> float | None:
    """Simple beta: cov(stock, market) / var(market)."""
    if not market_moves or not stock_moves or len(market_moves) < 5:
        return None
    n = min(len(market_moves), len(stock_moves))
    m = market_moves[:n]
    s = stock_moves[:n]
    m_avg = sum(m) / n
    s_avg = sum(s) / n
    cov = sum((mi - m_avg) * (si - s_avg) for mi, si in zip(m, s)) / n
    var = sum((mi - m_avg) ** 2 for mi in m) / n
    return round(cov / var, 2) if var != 0 else None


def _compute_correlation(matrix: dict[str, list[float]]) -> list[dict]:
    """Compute pairwise Pearson correlations from daily return series."""
    symbols = list(matrix.keys())
    pairs = []
    for i, s1 in enumerate(symbols):
        r1 = matrix[s1]
        if not r1 or len(r1) < 5:
            continue
        for j in range(i + 1, len(symbols)):
            s2 = symbols[j]
            r2 = matrix[s2]
            if not r2 or len(r2) < 5:
                continue
            n = min(len(r1), len(r2))
            r1s, r2s = r1[:n], r2[:n]
            avg1, avg2 = sum(r1s) / n, sum(r2s) / n
            cov = sum((r1s[k] - avg1) * (r2s[k] - avg2) for k in range(n)) / n
            std1 = math.sqrt(sum((v - avg1) ** 2 for v in r1s) / n)
            std2 = math.sqrt(sum((v - avg2) ** 2 for v in r2s) / n)
            if std1 > 0 and std2 > 0:
                corr = round(cov / (std1 * std2), 3)
                pairs.append({"symbol1": s1, "symbol2": s2, "correlation": corr})
    pairs.sort(key=lambda x: -(abs(x["correlation"])))
    return pairs[:15]


def _fetch_returns(db_query, symbols: list[str], days: int = 21) -> dict[str, list[float]]:
    """Fetch daily returns for symbols from market_quotes."""
    if not db_query or not symbols:
        return {}
    try:
        rows = db_query(
            """SELECT symbol, day_change_pct, fetched_at
               FROM market_quotes
               WHERE upper(symbol) = ANY(%s)
                 AND fetched_at > now() - interval '%s days'
                 AND day_change_pct IS NOT NULL
               ORDER BY symbol, fetched_at DESC""",
            (symbols, days + 1),
            fetch="all",
        ) or []
        result: dict[str, list[float]] = {}
        for row in rows:
            sym = str(row.get("symbol") or "").upper()
            chg = row.get("day_change_pct")
            if chg is not None:
                try:
                    result.setdefault(sym, []).append(float(chg))
                except (TypeError, ValueError):
                    pass
        return result
    except Exception:
        return {}


def build_risk_snapshot(db_query=None) -> dict[str, Any]:
    """Compute a fresh risk snapshot from current JSON state + DB.

    Never raises — returns a best-effort partial snapshot (with errors in `_errors`)
    rather than crashing a caller/timer.
    """
    errors: list[str] = []
    rm = _load_json(STATE_DIR / "risk_management.json") or {}
    stops = _load_json(STATE_DIR / "stops.json") or {}
    holdings = _load_json(STATE_DIR / "holdings.json") or {}

    positions = rm.get("positions", [])

    # ---- Price enrichment from holdings ----
    h_prices: dict[str, float] = {}
    for h in holdings.get("holdings", []):
        sym = (h.get("symbol") or "").upper()
        px = h.get("price", 0) or 0
        if sym and px > 0:
            h_prices[sym] = float(px)

    # ---- Position-level risk ----
    position_risk: list[dict] = []
    real_positions = [p for p in positions if not p.get("risk_excluded")]
    for p in positions:
        sym = (p.get("symbol") or "").upper()
        mv = float(p.get("market_value") or 0)
        px = float(p.get("current_price") or p.get("price") or 0)
        if px <= 0 and sym in h_prices:
            px = h_prices[sym]
        stop_px = p.get("stop_price")
        shares = mv / px if px > 0 else 0

        # Distance to stop
        distance_pct = None
        max_loss = None
        if px > 0 and stop_px and float(stop_px) > 0:
            distance_pct = round((px - float(stop_px)) / px * 100, 1)
            max_loss = round(shares * (px - float(stop_px)), 0) if shares > 0 else 0

        position_risk.append({
            "symbol": p.get("symbol", ""),
            "account": p.get("account", ""),
            "environment": p.get("environment", "real"),
            "risk_excluded": bool(p.get("risk_excluded")),
            "market_value": round(mv, 2),
            "current_price": round(px, 2) if px else None,
            "shares": round(shares, 4) if shares else None,
            "stop_price": stop_px,
            "distance_to_stop_pct": distance_pct,
            "max_loss_dollar": max_loss,
            "status": p.get("status", ""),
            "triggered": bool(p.get("triggered")) or (distance_pct is not None and distance_pct < 0),
            "rsi": p.get("rsi"),
            "day_change_pct": p.get("day_change_pct"),
        })

    # ---- Portfolio-level aggregates ----
    total_value = round(sum(
        pr["market_value"] for pr in position_risk if not pr["risk_excluded"]
    ), 2)
    total_at_risk = round(sum(
        abs(pr["max_loss_dollar"] or 0) for pr in position_risk
        if not pr["risk_excluded"] and pr["max_loss_dollar"] is not None
    ), 2)
    protected_mv = round(sum(
        pr["market_value"] for pr in position_risk
        if not pr["risk_excluded"] and pr["stop_price"] is not None
    ), 2)
    unprotected_mv = round(sum(
        pr["market_value"] for pr in position_risk
        if not pr["risk_excluded"] and pr["stop_price"] is None
    ), 2)

    # ---- Beta and VaR approximations ----
    # Collect symbols and fetch daily returns
    real_syms = [pr["symbol"] for pr in position_risk if not pr["risk_excluded"] and pr["symbol"]]
    all_syms = list(dict.fromkeys(real_syms + ["SPY"]))  # dedupe, SPY at end

    daily_returns: dict[str, list[float]] = {}
    if db_query and all_syms:
        try:
            daily_returns = _fetch_returns(db_query, all_syms, days=22)
        except Exception as e:
            errors.append(f"daily_returns: {e}")

    spy_returns = daily_returns.get("SPY", [])

    for pr in position_risk:
        if pr["risk_excluded"]:
            continue
        sym = pr["symbol"]
        returns = daily_returns.get(sym)
        if returns and spy_returns:
            beta = _compute_beta(spy_returns, returns)
            pr["beta"] = beta
            # Simple VaR: 1.645 * daily_stdev * market_value (95% confidence)
            if len(returns) >= 5:
                avg_r = sum(returns) / len(returns)
                stdev = math.sqrt(sum((r - avg_r) ** 2 for r in returns) / len(returns))
                pr["daily_var_95"] = round(1.645 * stdev / 100 * pr["market_value"], 2)
                pr["volatility_annualized"] = round(stdev * math.sqrt(252), 2)

    # ---- Stop health ----
    triggered_count = sum(1 for pr in position_risk
                          if pr.get("triggered") and not pr.get("risk_excluded"))
    protected_count = sum(1 for pr in position_risk
                          if pr.get("stop_price") is not None and not pr.get("risk_excluded"))
    unprotected_positions = [{"symbol": pr["symbol"], "market_value": pr["market_value"],
                              "account": pr["account"]}
                             for pr in position_risk
                             if not pr.get("risk_excluded") and pr.get("stop_price") is None][:10]

    # ---- Correlation data ----
    correlation_pairs = []
    if daily_returns and len(daily_returns) >= 2:
        try:
            correlation_pairs = _compute_correlation(
                {sym: rets for sym, rets in daily_returns.items()
                 if sym != "SPY" and len(rets) >= 5}
            )
        except Exception as e:
            errors.append(f"correlation: {e}")

    # ---- Escalation lanes ----
    danger_positions = [pr for pr in position_risk
                        if not pr.get("risk_excluded")
                        and pr.get("status") in ("TRIGGERED", "DANGER")]
    warning_positions = [pr for pr in position_risk
                         if not pr.get("risk_excluded")
                         and pr.get("status") == "WARNING"]

    # ---- Stops map ----
    stops_map = {}
    for sym, data in stops.items():
        if isinstance(data, dict):
            stops_map[sym] = {
                "stop_price": data.get("stop_price") or data.get("stop"),
                "triggered": data.get("triggered", False),
            }

    now = datetime.now(timezone.utc)

    return {
        "version": "risk-snapshot-v1",
        "computed_at": now.isoformat(),
        "portfolio": {
            "heat_pct": rm.get("portfolio_heat_pct", 0),
            "total_risk_dollars": rm.get("total_risk_dollars", 0),
            "pct_protected": rm.get("pct_protected", 0),
            "total_protected_mv": rm.get("total_protected_mv") or protected_mv,
            "total_unprotected_mv": rm.get("total_unprotected_mv") or unprotected_mv,
            "total_value": total_value or rm.get("portfolio_total_value", 0),
            "total_at_risk": total_at_risk,
            "position_count_real": len([p for p in position_risk if not p.get("risk_excluded")]),
            "position_count_paper": len([p for p in position_risk if p.get("risk_excluded")]),
        },
        "positions": position_risk,
        "stop_health": {
            "triggered_count": triggered_count,
            "protected_count": protected_count,
            "unprotected_count": len(unprotected_positions),
            "unprotected_positions": unprotected_positions,
        },
        "escalation": {
            "danger": [{"symbol": p["symbol"], "max_loss": p.get("max_loss_dollar", 0),
                        "distance_pct": p.get("distance_to_stop_pct", 0),
                        "account": p.get("account", "")}
                       for p in danger_positions[:4]],
            "warning": [{"symbol": p["symbol"], "max_loss": p.get("max_loss_dollar", 0),
                         "distance_pct": p.get("distance_to_stop_pct", 0),
                         "account": p.get("account", "")}
                        for p in warning_positions[:4]],
            "unprotected": [{"symbol": p["symbol"], "market_value": p["market_value"],
                             "account": p.get("account", "")}
                            for p in position_risk
                            if not p.get("risk_excluded") and p.get("stop_price") is None][:4],
        },
        "correlation": correlation_pairs,
        "stops_map": stops_map,
        "source_files": {
            "risk_management": bool(rm),
            "stops": bool(stops),
            "holdings": bool(holdings),
        },
        "errors": errors,
        "ok": not errors,
    }


def write_risk_snapshot(snapshot: dict[str, Any] | None = None) -> Path:
    """Atomically publish the snapshot."""
    snap = snapshot if snapshot is not None else build_risk_snapshot()
    try:
        from lib.data_broker.atomic_json import atomic_write_json
        atomic_write_json(SNAPSHOT_PATH, snap)
    except Exception:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(json.dumps(snap, indent=2, default=str), encoding="utf-8")
    return SNAPSHOT_PATH


def _read_cached() -> dict[str, Any] | None:
    if not SNAPSHOT_PATH.exists():
        return None
    try:
        return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_risk_snapshot(db_query=None, max_age_s: float = DEFAULT_MAX_AGE_S) -> dict[str, Any]:
    """Return the on-disk snapshot if fresh enough, else recompute + publish + return.

    Args:
        db_query: a callable(sql, params, fetch="all"|"one") — required for beta/VaR/correlation.
        max_age_s: max age before recompute (default 45s).
    """
    cached = _read_cached()
    if cached and max_age_s > 0:
        try:
            computed_at = datetime.fromisoformat(cached["computed_at"])
            age = (datetime.now(timezone.utc) - computed_at).total_seconds()
            if age <= max_age_s:
                cached["_cache"] = {"hit": True, "age_seconds": round(age, 1)}
                return cached
        except Exception:
            pass

    fresh = build_risk_snapshot(db_query=db_query)
    write_risk_snapshot(fresh)
    fresh["_cache"] = {"hit": False, "age_seconds": 0}
    return fresh


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from db_adapter import _execute as _db_q

    def db_query(sql, params=None, fetch="all"):
        from db_adapter import USE_DB
        if not USE_DB:
            return None
        return _db_q(sql, params, fetch=fetch)

    print(json.dumps(get_risk_snapshot(db_query=db_query, max_age_s=0), indent=2, default=str))
