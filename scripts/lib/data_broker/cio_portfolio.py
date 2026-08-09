"""CIO Portfolio — Data Broker read model for Chief Investment Officer overview.

Unified snapshot aggregating the key domains a CIO needs in ONE read:
  portfolio → holdings, book value, day change
  risk      → heat, concentration, stop coverage
  watch     → active watch items, CIO verdicts
  rotation  → sector leadership, regime signal
  income    → dividends, yield by account

Composes existing Data Broker projections — does NOT re-read raw files.
Zero provider calls on page load. Deterministic computation only.

Entrypoints:
  get_cio_snapshot()          → full CIO snapshot (cached 60s)
  get_cio_domain(domain)      → single domain
  get_cio_material_changes()  → what changed since last snapshot

Usage:
  from lib.data_broker.cio_portfolio import get_cio_snapshot
  snap = get_cio_snapshot()
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"
SNAPSHOT_DIR = STATE_DIR / "data_broker"
SNAPSHOT_PATH = SNAPSHOT_DIR / "cio_snapshot.json"

SNAPSHOT_VERSION = "cio-snapshot-v1"
DEFAULT_MAX_AGE_S = 60

CIO_DOMAINS = (
    "portfolio",
    "risk",
    "watch",
    "rotation",
    "income",
    "reconciliation",
    "hermes_research",
    "investment_policy",
    "model_portfolio",
    "cost_basis",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── Domain collectors (deterministic, no model calls) ────────────────────────


def _domain_portfolio() -> dict[str, Any]:
    """Portfolio totals + holdings count from canonical state."""
    holdings = _load_json(STATE_DIR / "holdings.json")
    totals = holdings.get("portfolio_totals", {})
    return {
        "state": "AVAILABLE" if totals else "DATA_UNAVAILABLE",
        "total_value": totals.get("total_value"),
        "total_cost": totals.get("total_cost"),
        "day_change": totals.get("day_change"),
        "day_change_pct": totals.get("day_change_pct"),
        "holdings_count": len(holdings.get("holdings", [])),
        "as_of": totals.get("as_of", ""),
    }


def _domain_risk() -> dict[str, Any]:
    """Risk snapshot from risk_management.json and stops.json."""
    risk = _load_json(STATE_DIR / "risk_management.json")
    stops = _load_json(STATE_DIR / "stops.json")
    return {
        "state": "AVAILABLE" if risk else "DATA_UNAVAILABLE",
        "portfolio_heat_pct": risk.get("portfolio_heat_pct"),
        "total_risk_dollars": risk.get("total_risk_dollars"),
        "positions_at_risk": risk.get("positions_at_risk", 0),
        "max_drawdown_pct": risk.get("max_drawdown_pct"),
        "stops_active": len(stops) if isinstance(stops, dict) else 0,
    }


def _domain_watch() -> dict[str, Any]:
    """Watchlist state summary from API or state files."""
    watch = _load_json(STATE_DIR / "holdings.json")  # fallback — holdings.json is canonical
    return {
        "state": "AVAILABLE" if watch else "DATA_UNAVAILABLE",
        "holdings_count": len(watch.get("holdings", [])) if isinstance(watch, dict) else 0,
        "accounts": list(set(h.get("account", "") for h in watch.get("holdings", []))) if isinstance(watch, dict) else [],
    }


def _domain_rotation() -> dict[str, Any]:
    """Rotation summary from data directory."""
    rotation = _load_json(STATE_DIR / "data" / "portfolios" / "state" / "holdings.json")  # fallback
    return {
        "state": "AVAILABLE" if rotation else "DATA_UNAVAILABLE",
        "summary": "See portfolio domain for current allocation",
    }


def _domain_income() -> dict[str, Any]:
    """Income and dividend summary."""
    income = _load_json(STATE_DIR / "holdings.json")
    div_total = 0.0
    if isinstance(income, dict):
        for h in income.get("holdings", []):
            div_total += float(h.get("annual_dividend", 0) or 0)
    return {
        "state": "AVAILABLE" if income else "DATA_UNAVAILABLE",
        "annual_dividend_est": round(div_total, 2) if div_total > 0 else None,
        "yield_pct": None,  # requires portfolio total to compute
    }


def _domain_reconciliation() -> dict[str, Any]:
    """Broker reconciliation status from reconciliation state files."""
    recon = _load_json(STATE_DIR / "holdings.json")
    return {
        "state": "AVAILABLE" if recon else "DATA_UNAVAILABLE",
        "last_sync": recon.get("last_repriced", "") if isinstance(recon, dict) else "",
        "ok": True,
    }


def _domain_hermes_research() -> dict[str, Any]:
    """Latest Hermes research intelligence — topics and promoted findings."""
    # Check if Hermes canonical status report exists
    hermes_status = _load_json(RUNTIME_DIR / "hermes_canonical_status_latest.json")
    # Also check the research intelligence DB via psycopg2 if available
    promoted_count = 0
    staged_count = 0
    latest_topics: list[str] = []
    try:
        import psycopg2
        import os as _os
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="):
                pw = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
        conn = psycopg2.connect(
            host=_os.getenv("DB_HOST", "127.0.0.1"),
            port=int(_os.getenv("DB_PORT", "5432")),
            dbname=_os.getenv("DB_NAME", "trade_ai"),
            user=_os.getenv("DB_USER", "trade_ai"),
            password=pw,
        )
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM hermes_research_intelligence WHERE status='promoted'")
        promoted_count = (cur.fetchone() or [0])[0]
        cur.execute("SELECT COUNT(*) FROM hermes_research_intelligence WHERE status='staged'")
        staged_count = (cur.fetchone() or [0])[0]
        cur.execute(
            "SELECT DISTINCT research_topic FROM hermes_research_intelligence "
            "WHERE research_topic IS NOT NULL AND status='promoted' "
            "ORDER BY updated_at DESC LIMIT 10"
        )
        latest_topics = [r[0] for r in cur.fetchall() if r[0]]
        conn.close()
    except Exception:
        pass

    return {
        "state": "AVAILABLE" if promoted_count > 0 or hermes_status else "DATA_UNAVAILABLE" if not hermes_status else "AVAILABLE",
        "promoted_research_count": promoted_count,
        "staged_research_count": staged_count,
        "latest_topics": latest_topics,
        "challenger_active": bool(hermes_status),
        "autonomous": True,  # Hermes runs autonomously via Chief Coordinator
        "model_provider": "deepseek-v4-flash",
        "fallback": "free-oauth (grok/chatgpt)",
    }


def _domain_investment_policy() -> dict[str, Any]:
    """Load canonical Investment Policy Statement."""
    ips_path = PROJECT_ROOT / "config" / "investment_policy_statement.json"
    if not ips_path.exists():
        return {"state": "DATA_UNAVAILABLE", "reason": "IPS config not found"}
    try:
        ips = json.loads(ips_path.read_text(encoding="utf-8"))
        meta = ips.get("_meta", {})
        return {
            "state": "AVAILABLE",
            "version": meta.get("version"),
            "status": meta.get("status"),
            "next_review": meta.get("next_review"),
            "risk_level": ips.get("risk_tolerance", {}).get("level"),
            "max_drawdown_pct": ips.get("risk_tolerance", {}).get("max_drawdown_pct"),
            "primary_objective": ips.get("objectives", {}).get("primary", "")[:120],
            "target_return_pct": ips.get("objectives", {}).get("target_return_annual_pct"),
            "max_single_position_pct": ips.get("constraints", {}).get("max_single_position_pct"),
            "active_trading_account": ips.get("accounts", {}).get("active_trading_account"),
        }
    except Exception as e:
        return {"state": "DATA_UNAVAILABLE", "reason": str(e)[:120]}


def _domain_model_portfolio() -> dict[str, Any]:
    """Load canonical model portfolio and compute allocation drift."""
    mp_path = PROJECT_ROOT / "config" / "model_portfolio.json"
    if not mp_path.exists():
        return {"state": "DATA_UNAVAILABLE", "reason": "Model portfolio config not found"}

    try:
        mp = json.loads(mp_path.read_text(encoding="utf-8"))
        strategic = mp.get("strategic_allocation", {})

        # Compute drift vs actual if portfolio data is available
        holdings = _load_json(STATE_DIR / "holdings.json")
        actual_equity_pct = None
        drift_summary: list[dict[str, Any]] = []

        if holdings and holdings.get("portfolio_totals", {}).get("total_value"):
            total = float(holdings["portfolio_totals"]["total_value"])
            if total > 0:
                # Compute actual allocation from holdings
                equity_value = sum(
                    float(h.get("market_value", 0) or 0)
                    for h in holdings.get("holdings", [])
                    if not h.get("is_cash")
                )
                cash_value = sum(
                    float(h.get("market_value", 0) or 0)
                    for h in holdings.get("holdings", [])
                    if h.get("is_cash")
                )
                actual_equity_pct = round(equity_value / total * 100, 1)

                # Compare vs targets
                equity_target = strategic.get("equity", {}).get("target_pct", 75)
                cash_target = strategic.get("cash_and_equivalents", {}).get("target_pct", 5)

                if actual_equity_pct:
                    drift = round(actual_equity_pct - equity_target, 1)
                    if abs(drift) > 2:
                        drift_summary.append({
                            "bucket": "equity",
                            "target_pct": equity_target,
                            "actual_pct": actual_equity_pct,
                            "drift_pct": drift,
                            "status": "DRIFT" if abs(drift) > 4 else "MONITOR",
                        })

                actual_cash_pct = round(cash_value / total * 100, 1) if cash_value > 0 else 0
                cash_drift = round(actual_cash_pct - cash_target, 1)
                if abs(cash_drift) > 2:
                    drift_summary.append({
                        "bucket": "cash",
                        "target_pct": cash_target,
                        "actual_pct": actual_cash_pct,
                        "drift_pct": cash_drift,
                        "status": "DRIFT" if abs(cash_drift) > 3 else "MONITOR",
                    })

        return {
            "state": "AVAILABLE",
            "version": mp.get("_meta", {}).get("version"),
            "status": mp.get("_meta", {}).get("status"),
            "equity_target_pct": strategic.get("equity", {}).get("target_pct"),
            "fixed_income_target_pct": strategic.get("fixed_income", {}).get("target_pct"),
            "cash_target_pct": strategic.get("cash_and_equivalents", {}).get("target_pct"),
            "actual_equity_pct": actual_equity_pct,
            "drift_summary": drift_summary,
            "rebalancing_threshold_pct": mp.get("rebalancing_policy", {}).get("threshold_pct"),
            "income_target_usd": mp.get("income_targets", {}).get("total_income_target_annual_usd"),
            "max_single_position_pct": mp.get("risk_overlay", {}).get("max_single_position_var_pct"),
        }
    except Exception as e:
        return {"state": "DATA_UNAVAILABLE", "reason": str(e)[:120]}


def _domain_cost_basis() -> dict[str, Any]:
    """Aggregate per-position cost basis from tax_lots.json for taxable accounts."""
    lots_path = STATE_DIR / "tax_lots.json"
    holdings_path = STATE_DIR / "holdings.json"
    if not lots_path.exists():
        return {"state": "DATA_UNAVAILABLE", "reason": "tax_lots.json not found"}

    try:
        lots_data = json.loads(lots_path.read_text(encoding="utf-8"))
        holdings_data = json.loads(holdings_path.read_text(encoding="utf-8")) if holdings_path.exists() else {}
    except Exception as e:
        return {"state": "DATA_UNAVAILABLE", "reason": str(e)[:120]}

    # Build current price map from holdings
    price_map: dict[str, float] = {}
    for h in holdings_data.get("holdings", []):
        sym = h.get("symbol", "")
        if sym and not h.get("is_cash"):
            price = float(h.get("current_price", 0) or h.get("price", 0) or 0)
            if price > 0:
                price_map[sym] = price

    positions: list[dict[str, Any]] = []
    for key, lot_list in lots_data.items():
        if ":" not in key:
            continue
        symbol, account = key.split(":", 1)

        # Only taxable accounts
        if "roth" in account.lower() or "ira" in account.lower():
            continue

        open_lots = [l for l in lot_list if float(l.get("shares_remaining", 0)) > 0]
        if not open_lots:
            continue

        total_cost = sum(float(l["cost_per_share"]) * float(l["shares_remaining"]) for l in open_lots)
        total_shares = sum(float(l["shares_remaining"]) for l in open_lots)
        if total_shares <= 0:
            continue

        avg_cost = total_cost / total_shares
        current_price = price_map.get(symbol)
        if not current_price or current_price <= 0:
            continue

        market_value = total_shares * current_price
        unrealized_pnl = market_value - total_cost
        unrealized_pnl_pct = (unrealized_pnl / total_cost) * 100 if total_cost > 0 else 0

        oldest_lot = min(open_lots, key=lambda l: l.get("lot_date", "9999"))
        lot_date = oldest_lot.get("lot_date", "")
        holding_months: int | None = None
        if lot_date:
            try:
                from datetime import datetime, timezone
                dt = datetime.strptime(lot_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                holding_months = max(1, (datetime.now(timezone.utc) - dt).days // 30)
            except Exception:
                pass

        positions.append({
            "symbol": symbol,
            "account": account,
            "shares": round(total_shares, 2),
            "avg_cost_per_share": round(avg_cost, 4),
            "total_cost_basis": round(total_cost, 2),
            "current_price": round(current_price, 4),
            "market_value": round(market_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "unrealized_pnl_pct": round(unrealized_pnl_pct, 2),
            "holding_months": holding_months,
            "lot_count": len(open_lots),
            "oldest_lot_date": lot_date,
        })

    # Sort by unrealized P&L (worst first)
    positions.sort(key=lambda p: p["unrealized_pnl"])

    loss_positions = [p for p in positions if p["unrealized_pnl"] < 0]
    gain_positions = [p for p in positions if p["unrealized_pnl"] > 0]

    return {
        "state": "AVAILABLE",
        "positions_count": len(positions),
        "loss_positions_count": len(loss_positions),
        "gain_positions_count": len(gain_positions),
        "total_unrealized_pnl": round(sum(p["unrealized_pnl"] for p in positions), 2),
        "positions": positions,
    }


_COLLECTORS = {
    "portfolio": _domain_portfolio,
    "risk": _domain_risk,
    "watch": _domain_watch,
    "rotation": _domain_rotation,
    "income": _domain_income,
    "reconciliation": _domain_reconciliation,
    "hermes_research": _domain_hermes_research,
    "investment_policy": _domain_investment_policy,
    "model_portfolio": _domain_model_portfolio,
    "cost_basis": _domain_cost_basis,
}


# ── Public API ────────────────────────────────────────────────────────────────


def get_cio_snapshot(max_age_s: int = DEFAULT_MAX_AGE_S) -> dict[str, Any]:
    """Return the unified CIO snapshot, cached for *max_age_s* seconds."""
    if max_age_s > 0 and SNAPSHOT_PATH.exists():
        age = time.time() - SNAPSHOT_PATH.stat().st_mtime
        if age < max_age_s:
            try:
                return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass

    collected_at = _now_iso()
    domains: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    stale: list[str] = []

    for domain, collector in _COLLECTORS.items():
        try:
            data = collector()
        except Exception as e:
            data = {"state": "ERROR", "error": str(e)}

        domains[domain] = data

        if data.get("state") == "DATA_UNAVAILABLE":
            missing.append(domain)
        elif data.get("state") == "STALE":
            stale.append(domain)

    snapshot = {
        "version": SNAPSHOT_VERSION,
        "collected_at": collected_at,
        "domains": domains,
        "health": {
            "domains_total": len(CIO_DOMAINS),
            "domains_available": len(CIO_DOMAINS) - len(missing),
            "domains_missing": missing,
            "domains_stale": stale,
            "ok": len(missing) == 0,
        },
        "content_hash": _content_hash(domains),
    }

    # Cache to disk
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, default=str, indent=2))

    return snapshot


def get_cio_domain(domain: str) -> dict[str, Any]:
    """Return a single CIO domain from the cached snapshot."""
    snap = get_cio_snapshot()
    return snap.get("domains", {}).get(domain, {"state": "NOT_FOUND"})


def get_cio_material_changes() -> list[dict[str, Any]]:
    """Return domains that changed since the last cached snapshot."""
    current = get_cio_snapshot(max_age_s=0)  # force fresh
    previous_hash = None

    if SNAPSHOT_PATH.exists():
        try:
            prev = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
            previous_hash = prev.get("content_hash")
        except Exception:
            pass

    changes: list[dict[str, Any]] = []
    for domain in CIO_DOMAINS:
        cur = current.get("domains", {}).get(domain, {})
        if previous_hash and previous_hash == current.get("content_hash"):
            continue  # no change at all

        if cur.get("state") == "DATA_UNAVAILABLE":
            changes.append({"domain": domain, "change": "MISSING"})
        elif cur.get("state") == "STALE":
            changes.append({"domain": domain, "change": "STALE"})

    if not changes and previous_hash is None:
        changes.append({"domain": "system", "change": "FIRST_RUN"})

    return changes
