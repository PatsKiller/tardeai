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

try:
    from lib.cio_domain_evidence import DomainEvidence, ReasonCode
except Exception:  # pragma: no cover - dev-tree fallback when scripts/ is on path but lib/ is not
    from scripts.lib.cio_domain_evidence import DomainEvidence, ReasonCode

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"
SNAPSHOT_DIR = STATE_DIR / "data_broker"
SNAPSHOT_PATH = SNAPSHOT_DIR / "cio_snapshot.json"

WATCHLIST_PATH = STATE_DIR / "watchlist.json"
RECONCILIATION_PATH = PROJECT_ROOT / "data" / "reconciliation" / "state" / "latest.json"
ROTATION_LADDERS_CACHE = PROJECT_ROOT / "state" / "data_broker" / "rotation_ladders.json"
RETIREMENT_ROADMAP_PATH = STATE_DIR / "retirement_roadmap.json"

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
    "transactions",
    "sectors",
    "holdings_detail",
    "cash_buying_power",
    "retirement",
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


def _domain_watch() -> DomainEvidence:
    """Watchlist state summary. Reads actual watchlist source, NOT holdings.json.

    Fallback order:
      1. data/watchlist/state/watchlist.json (canonical file source)
      2. DB-based watchlist table (existing approach)
      3. DATA_UNAVAILABLE with SOURCE_FILE_MISSING
    """
    # 1. Try canonical watchlist file
    if WATCHLIST_PATH.exists():
        watch_data = _load_json(WATCHLIST_PATH)
        if watch_data:
            as_of = watch_data.get("as_of", "") if isinstance(watch_data, dict) else ""
            return DomainEvidence.available(
                "watch_intelligence", watch_data,
                source_ref=str(WATCHLIST_PATH), as_of=as_of
            )

    # 2. Fallback: try DB-based watchlist
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
        cur.execute("SELECT COUNT(*) FROM watchlist")
        count = (cur.fetchone() or [0])[0]
        cur.execute(
            "SELECT symbol, rationale, conviction, last_review_at "
            "FROM watchlist ORDER BY last_review_at DESC NULLS LAST LIMIT 50"
        )
        rows = cur.fetchall()
        items = [
            {
                "symbol": r[0],
                "rationale": r[1],
                "conviction": r[2],
                "last_review_at": str(r[3]) if r[3] else None,
            }
            for r in rows
        ]
        conn.close()
        return DomainEvidence.available(
            "watch_intelligence",
            {"watchlist_count": count, "items": items},
            source_ref="DB:watchlist",
        )
    except Exception:
        pass

    # 3. No watchlist source available
    return DomainEvidence.unavailable(
        "watch_intelligence",
        reason_code=ReasonCode.SOURCE_FILE_MISSING,
        source_ref=str(WATCHLIST_PATH),
        gap_reason="No watchlist source available: watchlist.json missing and DB fallback failed",
    )


def _domain_rotation() -> DomainEvidence:
    """Rotation summary from rotation_ladders cache file.

    The old adapter used a malformed nested path that doubled up the
    data/portfolios/state prefix.  The canonical source is the
    rotation_ladders module cache at state/data_broker/rotation_ladders.json.
    If the cache is missing (as is normal when the DB-based rotation engine
    has not been run), the domain is DATA_UNAVAILABLE.
    """
    if ROTATION_LADDERS_CACHE.exists():
        rotation_data = _load_json(ROTATION_LADDERS_CACHE)
        if rotation_data:
            as_of = rotation_data.get("computed_at", "") if isinstance(rotation_data, dict) else ""
            return DomainEvidence.available(
                "rotation", rotation_data,
                source_ref=str(ROTATION_LADDERS_CACHE), as_of=as_of,
            )

    return DomainEvidence.unavailable(
        "rotation",
        reason_code=ReasonCode.SOURCE_FILE_MISSING,
        source_ref=str(ROTATION_LADDERS_CACHE),
        gap_reason="Rotation ladders cache not available: rotation_ladders.json missing",
    )


def _domain_income() -> DomainEvidence:
    """Income and dividend summary.

    yield_pct requires portfolio_total to compute (circular dependency) —
    marked as PARTIAL with gap_reason until the income collector provides it.
    """
    holdings_path = STATE_DIR / "holdings.json"
    if not holdings_path.exists():
        return DomainEvidence.unavailable(
            "income",
            reason_code=ReasonCode.SOURCE_FILE_MISSING,
            source_ref=str(holdings_path),
            gap_reason="holdings.json not found",
        )

    income = _load_json(holdings_path)
    if not income:
        return DomainEvidence.unavailable(
            "income",
            reason_code=ReasonCode.EMPTY_VALID_RESULT,
            source_ref=str(holdings_path),
            gap_reason="holdings.json is empty",
        )

    div_total = 0.0
    if isinstance(income, dict):
        for h in income.get("holdings", []):
            div_total += float(h.get("annual_dividend", 0) or 0)

    annual_income_estimate = round(div_total, 2) if div_total > 0 else None

    # Try to compute yield_pct if portfolio total is available
    yield_pct = None
    totals = income.get("portfolio_totals", {}) if isinstance(income, dict) else {}
    total_value = totals.get("total_value")
    if total_value and annual_income_estimate and float(total_value) > 0:
        yield_pct = round(annual_income_estimate / float(total_value) * 100, 2)

    data = {
        "annual_dividend_est": annual_income_estimate,
        "annual_income_estimate": annual_income_estimate,
        "yield_pct": yield_pct,
        "as_of": totals.get("as_of", ""),
    }

    if yield_pct is not None:
        return DomainEvidence.available(
            "income", data,
            source_ref=str(holdings_path),
            as_of=totals.get("as_of", ""),
        )

    return DomainEvidence.partial(
        "income", data,
        source_ref=str(holdings_path),
        as_of=totals.get("as_of", ""),
        partial_fields=["yield_pct"],
        gap_reason="yield_pct_not_yet_collected_by_income_collector",
    )


def _domain_reconciliation() -> DomainEvidence:
    """Broker reconciliation status from actual reconciliation result file.

    Does NOT hardcode ok=True.  Reads data/reconciliation/state/latest.json.
    If the file is missing the domain is DATA_UNAVAILABLE.
    """
    if RECONCILIATION_PATH.exists():
        recon_data = _load_json(RECONCILIATION_PATH)
        if recon_data:
            return DomainEvidence.available(
                "reconciliation", recon_data,
                source_ref=str(RECONCILIATION_PATH),
                as_of=recon_data.get("reconciled_at", "") if isinstance(recon_data, dict) else "",
            )

    return DomainEvidence.unavailable(
        "reconciliation",
        reason_code=ReasonCode.SOURCE_FILE_MISSING,
        source_ref=str(RECONCILIATION_PATH),
        gap_reason="Reconciliation result file not found",
    )


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
    # Build authoritative holdings map: symbol:account → {shares, cost_basis}
    holdings_map: dict[str, dict[str, Any]] = {}
    for h in holdings_data.get("holdings", []):
        sym = h.get("symbol", "")
        if sym and not h.get("is_cash"):
            price = float(h.get("current_price", 0) or h.get("price", 0) or 0)
            if price > 0:
                price_map[sym] = price
            acct = h.get("account", "")
            key = f"{sym}:{acct}"
            holdings_map[key] = {
                "shares": float(h.get("shares", 0) or 0),
                "cost_basis": float(h.get("cost_basis", 0) or 0),
                "market_value": float(h.get("market_value", 0) or 0),
                "gain_loss_pct": float(h.get("gain_loss_pct", 0) or 0) if h.get("gain_loss_pct") is not None else None,
            }

    SHARE_TOLERANCE = 0.05  # 5% tolerance for share divergence

    positions: list[dict[str, Any]] = []
    reconciled_count = 0
    for key, lot_list in lots_data.items():
        if ":" not in key:
            continue
        symbol, account = key.split(":", 1)

        # IRA accounts: tax_lots has no cost-basis relevance for tax-loss harvesting,
        # but shares and lot_dates are still consumed by downstream modules
        # (days_held, holding_period, behavioral detection).  Reconcile IRAs
        # exactly like taxable.  Retirement accounts carry no cost-basis
        # reporting requirement but the domain must not report fabricated sizes.

        open_lots = [l for l in lot_list if float(l.get("shares_remaining", 0)) > 0]
        if not open_lots:
            continue

        total_cost = sum(float(l["cost_per_share"]) * float(l["shares_remaining"]) for l in open_lots)
        total_shares = sum(float(l["shares_remaining"]) for l in open_lots)
        if total_shares <= 0:
            continue

        # ── DB-FIX-01: Reconcile against holdings.json authoritative shares ──
        # tax_lots.json shares_remaining was never decremented when positions
        # were sold down — 17/34 positions diverge, some by >49,000×.
        # holdings.json carries broker-verified shares and cost_basis.
        holding = holdings_map.get(key)
        reconciled = False
        if holding and holding["shares"] > 0:
            share_ratio = total_shares / holding["shares"]
            if abs(share_ratio - 1.0) > SHARE_TOLERANCE:
                # tax_lots is stale — use holdings.json as authority
                reconciled = True
                reconciled_count += 1
                total_shares = holding["shares"]
                # Preserve avg_cost_per_share from the surviving lots if possible,
                # but fall back to holdings cost_basis/shares
                if holding["cost_basis"] > 0:
                    total_cost = holding["cost_basis"]
                else:
                    total_cost = total_cost * (holding["shares"] / sum(float(l["shares_remaining"]) for l in open_lots))

        avg_cost = total_cost / total_shares if total_shares > 0 else 0
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
            "reconciled": reconciled,
            "lot_data_status": (
                "RECONCILED_FROM_HOLDINGS" if reconciled
                else "VERIFIED" if holding
                else "UNTRUSTED"
            ),
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
        "reconciled_count": reconciled_count,
        "positions": positions,
    }


def _domain_transactions() -> dict[str, Any]:
    """Recent trade history — buys, sells, closed positions from trade journal."""
    tj_path = STATE_DIR / "trade_journal.json"
    if not tj_path.exists():
        return {"state": "DATA_UNAVAILABLE", "reason": "trade_journal.json not found"}

    try:
        tj = json.loads(tj_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"state": "DATA_UNAVAILABLE", "reason": str(e)[:120]}

    closed = tj.get("closed_trades", [])
    open_lots = tj.get("open_lots", [])

    # Recent closed trades (last 30)
    recent_closed: list[dict[str, Any]] = []
    for t in closed[-30:]:
        recent_closed.append({
            "symbol": t.get("symbol", ""),
            "action": t.get("action", t.get("side", "")),
            "entry_date": t.get("entry_date", ""),
            "exit_date": t.get("exit_date", t.get("close_date", "")),
            "entry_price": t.get("entry_price"),
            "exit_price": t.get("exit_price"),
            "realized_pnl": t.get("realized_pnl", t.get("pnl")),
            "return_pct": t.get("return_pct"),
            "account": t.get("account", ""),
            "strategy": t.get("strategy", ""),
        })

    # Active open lots
    active_lots: list[dict[str, Any]] = []
    for lot in open_lots:
        active_lots.append({
            "symbol": lot.get("symbol", ""),
            "entry_date": lot.get("entry_date", ""),
            "entry_price": lot.get("entry_price"),
            "quantity": lot.get("quantity"),
            "account": lot.get("account", ""),
            "strategy": lot.get("strategy", ""),
        })

    return {
        "state": "AVAILABLE",
        "closed_trades_total": len(closed),
        "recent_closed": recent_closed,
        "open_lots_total": len(open_lots),
        "active_lots": active_lots,
        "last_updated": tj.get("last_updated", ""),
        "all_symbols_traded": tj.get("all_symbols", []),
        "all_accounts": tj.get("all_accounts", []),
    }


def _domain_sectors() -> dict[str, Any]:
    """Sector weights — current allocation by sector computed from holdings + sector cache."""
    holdings_path = STATE_DIR / "holdings.json"
    sector_cache_path = STATE_DIR / "sector_cache.json"

    if not holdings_path.exists():
        return {"state": "DATA_UNAVAILABLE", "reason": "holdings.json not found"}

    try:
        holdings = json.loads(holdings_path.read_text(encoding="utf-8"))
        sector_cache = json.loads(sector_cache_path.read_text(encoding="utf-8")) if sector_cache_path.exists() else {}
    except Exception as e:
        return {"state": "DATA_UNAVAILABLE", "reason": str(e)[:120]}

    # Compute sector weights
    sector_weights: dict[str, float] = {}
    sector_positions: dict[str, list[str]] = {}
    uncategorized_value = 0.0
    cash_value = 0.0
    total_value = 0.0

    for h in holdings.get("holdings", []):
        mv = float(h.get("market_value", 0) or 0)
        total_value += mv
        symbol = h.get("symbol", "")
        is_cash = h.get("is_cash") or h.get("asset_type") == "cash" or symbol == "CASH"

        if is_cash:
            cash_value += mv
            continue

        sector = sector_cache.get(symbol, "").strip()
        if not sector:
            uncategorized_value += mv
            continue

        sector_weights[sector] = sector_weights.get(sector, 0) + mv
        if sector not in sector_positions:
            sector_positions[sector] = []
        sector_positions[sector].append(symbol)

    # Build sorted sector list (largest first)
    sectors: list[dict[str, Any]] = []
    for sector_name, value in sorted(sector_weights.items(), key=lambda x: -x[1]):
        pct = round(value / total_value * 100, 2) if total_value > 0 else 0
        sectors.append({
            "sector": sector_name,
            "value": round(value, 2),
            "weight_pct": pct,
            "position_count": len(sector_positions.get(sector_name, [])),
            "symbols": sector_positions.get(sector_name, []),
        })

    concentration_flags: list[str] = []
    for s in sectors:
        if s["weight_pct"] > 25:
            concentration_flags.append(f"{s['sector']}: {s['weight_pct']}% (HIGH — over 25%)")
        elif s["weight_pct"] > 15:
            concentration_flags.append(f"{s['sector']}: {s['weight_pct']}% (ELEVATED — over 15%)")

    uncategorized_pct = round(uncategorized_value / total_value * 100, 2) if total_value > 0 else 0
    cash_pct = round(cash_value / total_value * 100, 2) if total_value > 0 else 0

    return {
        "state": "AVAILABLE",
        "total_value": round(total_value, 2),
        "sectors": sectors,
        "sector_count": len(sectors),
        "uncategorized_pct": uncategorized_pct,
        "cash_pct": cash_pct,
        "concentration_flags": concentration_flags,
        # Top 5 sectors
        "top_sectors": [
            {"sector": s["sector"], "weight_pct": s["weight_pct"]}
            for s in sectors[:5]
        ],
    }


def _domain_holdings_detail() -> dict[str, Any]:
    """Full holdings enumeration with sector, weight, day change, and P&L per position."""
    holdings_path = STATE_DIR / "holdings.json"
    sector_cache_path = STATE_DIR / "sector_cache.json"
    lots_path = STATE_DIR / "tax_lots.json"

    if not holdings_path.exists():
        return {"state": "DATA_UNAVAILABLE", "reason": "holdings.json not found"}

    try:
        holdings = json.loads(holdings_path.read_text(encoding="utf-8"))
        sector_cache = json.loads(sector_cache_path.read_text(encoding="utf-8")) if sector_cache_path.exists() else {}
        lots_data = json.loads(lots_path.read_text(encoding="utf-8")) if lots_path.exists() else {}
    except Exception as e:
        return {"state": "DATA_UNAVAILABLE", "reason": str(e)[:120]}

    total_value = sum(float(h.get("market_value", 0) or 0) for h in holdings.get("holdings", []))

    positions: list[dict[str, Any]] = []
    for h in holdings.get("holdings", []):
        symbol = h.get("symbol", "")
        mv = float(h.get("market_value", 0) or 0)
        is_cash = h.get("is_cash") or h.get("asset_type") == "cash" or symbol == "CASH"

        sector = sector_cache.get(symbol, "").strip() if not is_cash else "Cash"

        # Cost basis from tax lots
        cost_basis = None
        unrealized_pnl = None
        unrealized_pnl_pct = None
        if not is_cash and lots_data:
            for key, lot_list in lots_data.items():
                if key.startswith(f"{symbol}:"):
                    open_lots = [l for l in lot_list if float(l.get("shares_remaining", 0)) > 0]
                    if open_lots:
                        cost_basis = sum(
                            float(l["cost_per_share"]) * float(l["shares_remaining"])
                            for l in open_lots
                        )
                        unrealized_pnl = mv - cost_basis
                        unrealized_pnl_pct = round(unrealized_pnl / cost_basis * 100, 2) if cost_basis > 0 else None
                    break

        positions.append({
            "symbol": symbol,
            "name": h.get("name", ""),
            "account": h.get("account", ""),
            "sector": sector,
            "market_value": round(mv, 2),
            "weight_pct": round(mv / total_value * 100, 4) if total_value > 0 else 0,
            "day_change_pct": h.get("day_change_pct"),
            "quantity": h.get("quantity") or h.get("shares"),
            "current_price": h.get("current_price") or h.get("price"),
            "cost_basis": round(cost_basis, 2) if cost_basis else None,
            "unrealized_pnl": round(unrealized_pnl, 2) if unrealized_pnl else None,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "is_cash": is_cash,
            "asset_type": h.get("asset_type", ""),
        })

    # Sort: non-cash first, by weight descending
    positions.sort(key=lambda p: (p["is_cash"], -p["weight_pct"]))

    # Account breakdown
    accounts: dict[str, dict[str, Any]] = {}
    for p in positions:
        acct = p["account"]
        if acct not in accounts:
            accounts[acct] = {"value": 0.0, "position_count": 0, "symbols": []}
        accounts[acct]["value"] += p["market_value"]
        accounts[acct]["position_count"] += 1
        if not p["is_cash"]:
            accounts[acct]["symbols"].append(p["symbol"])

    # Sector breakdown
    sector_breakdown: dict[str, float] = {}
    for p in positions:
        s = p["sector"]
        sector_breakdown[s] = sector_breakdown.get(s, 0) + p["weight_pct"]

    return {
        "state": "AVAILABLE",
        "total_value": round(total_value, 2),
        "position_count": len(positions),
        "cash_positions": sum(1 for p in positions if p["is_cash"]),
        "equity_positions": sum(1 for p in positions if not p["is_cash"]),
        "positions": positions,
        "accounts": {
            acct: {
                "value": round(d["value"], 2),
                "weight_pct": round(d["value"] / total_value * 100, 2) if total_value > 0 else 0,
                "position_count": d["position_count"],
                "top_symbols": d["symbols"][:10],
            }
            for acct, d in sorted(accounts.items(), key=lambda x: -x[1]["value"])
        },
        "sector_breakdown": dict(sorted(sector_breakdown.items(), key=lambda x: -x[1])),
        "as_of": holdings.get("as_of", ""),
    }


def _domain_cash_buying_power() -> DomainEvidence:
    """Cash-like positions derived from holdings.json — NOT verified broker buying power.

    Holdings-derived cash positions are a PARTIAL proxy at best. Real broker
    buying power requires: settled cash, unsettled cash, margin, account type,
    pending orders, holds, settlement state, broker restrictions.

    This adapter returns PARTIAL, never AVAILABLE, because holdings.json cash
    positions do not and cannot prove actual broker-of-record buying power.
    A separate canonical adapter for verified broker buying power is needed
    before the BUY post-synthesis validator can rely on this domain.

    If holdings.json is unavailable, returns DATA_UNAVAILABLE.
    """
    holdings_path = STATE_DIR / "holdings.json"
    if not holdings_path.exists():
        return DomainEvidence.unavailable(
            "cash_buying_power",
            reason_code=ReasonCode.SOURCE_FILE_MISSING,
            source_ref=str(holdings_path),
            gap_reason="holdings.json not found",
        )

    holdings = _load_json(holdings_path)
    if not holdings:
        return DomainEvidence.unavailable(
            "cash_buying_power",
            reason_code=ReasonCode.EMPTY_VALID_RESULT,
            source_ref=str(holdings_path),
            gap_reason="holdings.json is empty",
        )

    cash_positions = []
    total_cash = 0.0
    if isinstance(holdings, dict):
        for h in holdings.get("holdings", []):
            is_cash = (
                h.get("is_cash")
                or h.get("asset_type") == "cash"
                or h.get("symbol") == "CASH"
            )
            if is_cash:
                mv = float(h.get("market_value", 0) or 0)
                total_cash += mv
                cash_positions.append({
                    "symbol": h.get("symbol", "CASH"),
                    "market_value": round(mv, 2),
                    "account": h.get("account", ""),
                })

    # NOTE: portfolio_totals may contain a "buying_power" field,
    # but this is a holdings-file projection, not a live broker API call.
    # It does not prove settled/unsettled cash, margin, or account-level
    # buying power.  The domain is PARTIAL until a real broker adapter exists.
    totals = holdings.get("portfolio_totals", {})
    total_buying_power = totals.get("buying_power", total_cash)
    if total_buying_power == 0 and total_cash > 0:
        total_buying_power = total_cash

    data = {
        "total_cash": round(total_cash, 2),
        "total_buying_power_estimate": round(float(total_buying_power), 2),
        "cash_positions": cash_positions,
        "cash_position_count": len(cash_positions),
        "as_of": totals.get("as_of", ""),
        "source": "derived_from_holdings_NOT_verified_broker_buying_power",
    }

    return DomainEvidence.partial(
        "cash_buying_power", data,
        source_ref=str(holdings_path),
        as_of=totals.get("as_of", ""),
        partial_fields=["verified_broker_buying_power"],
        gap_reason="holdings_derived_cash_not_verified_broker_buying_power",
    )


def _domain_retirement() -> DomainEvidence:
    """Retirement roadmap evidence.

    If retirement_roadmap.json exists, marks as AVAILABLE with authority
    class AUTHORITATIVE_POLICY.  Otherwise DATA_UNAVAILABLE.
    """
    # Try canonical path from registry: config/retirement_roadmap.json
    config_path = PROJECT_ROOT / "config" / "retirement_roadmap.json"
    # Also try the data/portfolios/state location
    state_path = RETIREMENT_ROADMAP_PATH

    for path in (config_path, state_path):
        if path.exists():
            roadmap = _load_json(path)
            if roadmap:
                as_of = roadmap.get("config_version_timestamp", "") if isinstance(roadmap, dict) else ""
                roadmap["_authority_class"] = "AUTHORITATIVE_POLICY"
                return DomainEvidence.available(
                    "retirement",
                    roadmap,
                    source_ref=str(path),
                    as_of=as_of,
                )

    return DomainEvidence.unavailable(
        "retirement",
        reason_code=ReasonCode.SOURCE_FILE_MISSING,
        source_ref=str(config_path),
        gap_reason="Retirement roadmap not found in config/ or data/portfolios/state/",
    )


_COLLECTORS = {
    "portfolio": _domain_portfolio,
    "risk": _domain_risk,
    "watch": _domain_watch,
    "watch_intelligence": _domain_watch,
    "rotation": _domain_rotation,
    "income": _domain_income,
    "reconciliation": _domain_reconciliation,
    "hermes_research": _domain_hermes_research,
    "investment_policy": _domain_investment_policy,
    "model_portfolio": _domain_model_portfolio,
    "cost_basis": _domain_cost_basis,
    "transactions": _domain_transactions,
    "sectors": _domain_sectors,
    "holdings_detail": _domain_holdings_detail,
    "cash_buying_power": _domain_cash_buying_power,
    "retirement": _domain_retirement,
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
            result = collector()
        except Exception as e:
            data = {"state": "ERROR", "error": str(e)}
        else:
            if isinstance(result, DomainEvidence):
                data = result.to_dict()
            else:
                data = result

        domains[domain] = data

        effective_state = data.get("quality_state") or data.get("state")
        if effective_state == "DATA_UNAVAILABLE":
            missing.append(domain)
        elif effective_state == "STALE":
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

        effective_state = cur.get("quality_state") or cur.get("state")
        if effective_state == "DATA_UNAVAILABLE":
            changes.append({"domain": domain, "change": "MISSING"})
        elif effective_state == "STALE":
            changes.append({"domain": domain, "change": "STALE"})

    if not changes and previous_hash is None:
        changes.append({"domain": "system", "change": "FIRST_RUN"})

    return changes
