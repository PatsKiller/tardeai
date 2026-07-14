"""redeploy_data_truth — Phase A: proceeds reconciliation, exposure decomposition, context snapshots.

Advisory only. No broker execution.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATE = PROJECT_ROOT / "data" / "portfolios" / "state"

POLICY_VERSION = "2026-07-14-operator-review"
GENERATOR_VERSION = "phase_a_1.0.0"  # Phase B uses redeploy_plan_engine.GENERATOR_VERSION

MAJOR_PROCEEDS_USD = 25_000.0
MAJOR_PCT_OF_PORTFOLIO = 1.0
MAJOR_EXPOSURE_PCT = 1.0

OPERATOR_READY_MIN_CONFIDENCE = 70.0
OPERATOR_READY_MIN_EVIDENCE_FACTORS = 3

# Portfolio vol gate: absolute percentage points (not relative % change)
VOL_DELTA_ABS_PP_MAX = 1.5
# Reject when estimated max drawdown is WORSE than -15% (more negative)
DRAWDOWN_REJECT_THRESHOLD_PCT = -15.0

# Quote freshness for operator-ready EXPORT (display may show stale with watermark)
EXPORT_QUOTE_MAX_AGE_MINUTES = 15

PLAN_ARCHETYPES = {
    "A": ("strategic_replacement", "Closest benchmark / risk restoration"),
    "B": ("diversified_basket", "Multi-sector basket across removed exposure"),
    "C": ("income_oriented", "Income + partial growth (dual-label option-income)"),
    "D": ("defensive", "Risk reduction, bonds, low-beta"),
    "E": ("tactical_opportunity", "Portfolio underweight — any sector"),
    "F": ("staged_deployment", "Staged entry with explicit reserve (orthogonal to A–E)"),
    "G": ("hold_no_redeploy", "Hold cash / no immediate redeploy"),
}

INCOME_FALLBACK_FUNDS = ("FCNTX", "FID-CONTRA-F")


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        if v in (None, "", "—"):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def holdings_snapshot_id() -> str:
    p = STATE / "holdings.json"
    try:
        raw = p.read_bytes()
        return hashlib.sha256(raw).hexdigest()[:16]
    except Exception:
        return "missing"


def holdings_as_of_date() -> date | None:
    """Best-effort holdings.json freshness (not broker settlement truth)."""
    data = _load_json(STATE / "holdings.json", {})
    for key in ("as_of", "last_repriced"):
        raw = data.get(key)
        if not raw:
            continue
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
    return None


def account_cash_usd(account: str) -> float:
    hold = _load_json(STATE / "holdings.json", {}).get("holdings") or []
    return sum(
        _as_float(h.get("market_value"))
        for h in hold
        if h.get("is_cash") and str(h.get("account") or "") == account
    )


def _parse_sale_date(sold_at: Any) -> date | None:
    if not sold_at:
        return None
    try:
        if isinstance(sold_at, date):
            return sold_at
        return date.fromisoformat(str(sold_at)[:10])
    except ValueError:
        return None


def portfolio_totals() -> dict[str, float]:
    hold = _load_json(STATE / "holdings.json", {}).get("holdings") or []
    equity = sum(_as_float(h.get("market_value")) for h in hold if not h.get("is_cash"))
    total = sum(_as_float(h.get("market_value")) for h in hold)
    return {"equity_usd": equity, "total_with_cash_usd": total}


def reconcile_proceeds(
    *,
    account: str,
    proceeds_usd: float,
    cash_visible_usd: float | None = None,
    sold_at: Any = None,
    operator_settlement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """deployable_cash = min(net_proceeds, settled_available_cash in source account).

    Never label broker proceeds 'unsettled' solely because holdings.json predates the sale —
    that is holdings_stale (sync lag), not settlement failure.
    """
    net = round(proceeds_usd, 2)
    cash = round(cash_visible_usd if cash_visible_usd is not None else account_cash_usd(account), 2)
    hold_as_of = holdings_as_of_date()
    sale_date = _parse_sale_date(sold_at)
    op = operator_settlement or {}
    reason = None

    if op.get("verified"):
        cash = round(_as_float(op.get("settled_cash_usd"), cash), 2)
        deployable = round(min(net, cash), 2)
        status = "verified"
        reason = "operator_verified"
    elif sale_date and hold_as_of and hold_as_of < sale_date and cash < net * 0.95:
        # Sale posted in trade_transactions; holdings cash not refreshed yet.
        status = "holdings_stale"
        deployable = net
        reason = "holdings_snapshot_predates_sale"
    else:
        deployable = round(min(net, cash), 2)
        if cash >= net * 0.95:
            status = "verified"
        elif cash >= net * 0.50:
            status = "partial"
        else:
            status = "unsettled"
            reason = "cash_below_50pct_of_net_in_holdings"

    return {
        "net_proceeds_usd": net,
        "settled_available_cash_usd": cash,
        "deployable_cash_usd": deployable,
        "reconciliation_status": status,
        "planned_not_actionable_usd": round(max(0.0, net - deployable), 2),
        "source_account": account,
        "holdings_as_of": str(hold_as_of) if hold_as_of else None,
        "sale_date": str(sale_date) if sale_date else None,
        "reconciliation_reason": reason,
    }


def verify_operator_settlement(
    event: dict[str, Any],
    *,
    settled_cash_usd: float,
    note: str | None = None,
    verified_by: str = "operator",
) -> dict[str, Any]:
    """Operator attestation that proceeds are settled in the sale account (overrides stale holdings)."""
    account = str(event.get("account") or "")
    proceeds = _as_float(event.get("proceeds_usd"))
    cash_vis = event.get("cash_visible_usd")
    if cash_vis is not None:
        cash_vis = _as_float(cash_vis)
    op = {
        "verified": True,
        "settled_cash_usd": round(settled_cash_usd, 2),
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "verified_by": verified_by,
        "note": (note or "")[:500] or None,
    }
    recon = reconcile_proceeds(
        account=account,
        proceeds_usd=proceeds,
        cash_visible_usd=cash_vis,
        sold_at=event.get("sold_at"),
        operator_settlement=op,
    )
    meta = dict(event.get("metadata") or {})
    pa = dict(meta.get("phase_a") or {})
    pa["operator_settlement"] = op
    pa["reconciliation"] = recon
    meta["phase_a"] = pa
    event["metadata"] = meta
    event["deployable_cash_usd"] = recon["deployable_cash_usd"]
    event["reconciliation_status"] = recon["reconciliation_status"]
    event["proceeds_settled"] = recon["reconciliation_status"] == "verified"
    return recon


def _fund_lookthrough(symbol: str) -> dict[str, Any] | None:
    data = _load_json(STATE / "fund_lookthrough.json", {})
    sym = symbol.upper()
    if sym in data and sym != "_meta":
        return data[sym]
    return None


def _income_for_symbol(symbol: str, proceeds_usd: float) -> dict[str, Any]:
    sym = symbol.upper()
    payers = _load_json(STATE / "dividend_calendar.json", {}).get("payers") or []
    for p in payers:
        if (p.get("symbol") or "").upper() == sym:
            y = _as_float(p.get("yield_pct"))
            annual = round(proceeds_usd * y / 100.0, 2) if y else None
            return {
                "income_status": "known",
                "income_annual_usd": annual,
                "income_yield_pct": y,
                "income_source": "dividend_calendar.json",
                "income_as_of": _load_json(STATE / "dividend_calendar.json", {}).get("generated_at"),
            }
    # yfinance fund distribution hint from fund_lookthrough meta — estimated only
    flt = _fund_lookthrough(sym)
    if flt and sym in INCOME_FALLBACK_FUNDS:
        return {
            "income_status": "unknown",
            "income_annual_usd": None,
            "income_yield_pct": None,
            "income_source": None,
            "income_as_of": flt.get("fetched_date"),
            "note": "Growth mutual fund — trailing distributions not in dividend_calendar; do not report $0",
        }
    return {
        "income_status": "unknown",
        "income_annual_usd": None,
        "income_source": None,
        "note": "No authoritative income source for this symbol",
    }


def _share_class_note(ticker: str) -> str | None:
    t = ticker.upper()
    if t in ("BRK.A", "BRK-A", "BRK/A"):
        return (
            "yfinance top-holdings reports BRK.A; fund may hold BRK.B economically — "
            "treat as Berkshire exposure not precise share class"
        )
    return None


def decompose_exposure_loss(
    *,
    symbol: str,
    proceeds_usd: float,
    proxy_symbol: str | None = None,
) -> dict[str, Any]:
    sym = symbol.upper()
    flt = _fund_lookthrough(sym)
    if not flt and proxy_symbol:
        flt = _fund_lookthrough(str(proxy_symbol).upper())

    income = _income_for_symbol(sym, proceeds_usd)
    out: dict[str, Any] = {
        "symbol": sym,
        "proceeds_usd": round(proceeds_usd, 2),
        "asset_class": (flt or {}).get("asset_class"),
        "benchmark": "Fund prospectus / proxy sleeve",
        "source": "fund_lookthrough.json" if flt else "proxy_only",
        "source_as_of": (flt or {}).get("fetched_date"),
        "sectors": [],
        "top_holdings": [],
        **income,
    }
    if not flt:
        out["note"] = "No fund look-through row — sector decomposition unavailable"
        return out

    weights = flt.get("sector_weights") or {}
    sector_rows = []
    accounted = 0.0
    for sector, pct in sorted(weights.items(), key=lambda x: -_as_float(x[1])):
        p = _as_float(pct)
        accounted += p
        sector_rows.append({
            "sector": sector,
            "weight_pct": round(p, 2),
            "usd_removed": round(proceeds_usd * p / 100.0, 2),
        })
    residual = round(max(0.0, 100.0 - accounted), 2)
    out["sectors"] = sector_rows
    out["residual_sector_pct"] = residual
    out["residual_sector_usd"] = round(proceeds_usd * residual / 100.0, 2) if residual else 0.0

    for h in (flt.get("top_holdings") or [])[:12]:
        pct = _as_float(h.get("pct"))
        ticker = str(h.get("ticker") or "").upper()
        out["top_holdings"].append({
            "ticker": ticker,
            "name": h.get("name"),
            "weight_pct": round(pct, 2),
            "usd_removed": round(proceeds_usd * pct / 100.0, 2),
            "share_class_note": _share_class_note(ticker),
        })
    return out


def _issuer_overlap(holdings: list[dict], fund_lookthrough: dict) -> list[dict]:
    """Direct + indirect issuer exposure for overlap analysis."""
    direct: dict[str, float] = {}
    for h in holdings:
        if h.get("is_cash"):
            continue
        sym = str(h.get("symbol") or "").upper()
        direct[sym] = direct.get(sym, 0.0) + _as_float(h.get("market_value"))

    rows = []
    for fund_sym, entry in fund_lookthrough.items():
        if fund_sym == "_meta" or not isinstance(entry, dict):
            continue
        fund_mv = direct.get(fund_sym, 0.0)
        if fund_mv <= 0:
            continue
        for th in entry.get("top_holdings") or []:
            issuer = str(th.get("ticker") or "").upper()
            pct = _as_float(th.get("pct"))
            indirect = fund_mv * pct / 100.0
            if indirect > 0:
                rows.append({
                    "issuer": issuer,
                    "indirect_via": fund_sym,
                    "indirect_usd": round(indirect, 2),
                })
    return rows


def classify_major_sale(
    *,
    proceeds_usd: float,
    portfolio_equity_usd: float,
    instrument_type: str | None,
    exposure_pct_of_portfolio: float | None,
) -> dict[str, Any]:
    reasons = []
    if proceeds_usd >= MAJOR_PROCEEDS_USD:
        reasons.append(f"proceeds>={MAJOR_PROCEEDS_USD:.0f}")
    if str(instrument_type or "").lower() in ("mutual_fund", "fund"):
        reasons.append("mutual_fund")
    if portfolio_equity_usd > 0:
        pct = proceeds_usd / portfolio_equity_usd * 100.0
        if pct >= MAJOR_PCT_OF_PORTFOLIO:
            reasons.append(f"proceeds_pct_portfolio={pct:.2f}")
    if exposure_pct_of_portfolio is not None and exposure_pct_of_portfolio >= MAJOR_EXPOSURE_PCT:
        reasons.append(f"exposure_impact_pct={exposure_pct_of_portfolio:.2f}")
    return {"is_major_sale": bool(reasons), "reasons": reasons}


def build_portfolio_context(
    event: dict[str, Any],
    *,
    reconciliation: dict[str, Any],
    exposure: dict[str, Any],
) -> dict[str, Any]:
    totals = portfolio_totals()
    account = str(event.get("account") or "")
    hold = _load_json(STATE / "holdings.json", {}).get("holdings") or []
    acct_holdings = [h for h in hold if str(h.get("account") or "") == account and not h.get("is_cash")]
    proceeds = _as_float(event.get("proceeds_usd"))
    exp_pct = None
    if totals["equity_usd"] > 0:
        exp_pct = round(proceeds / totals["equity_usd"] * 100.0, 2)

    major = classify_major_sale(
        proceeds_usd=proceeds,
        portfolio_equity_usd=totals["equity_usd"],
        instrument_type=event.get("instrument_type"),
        exposure_pct_of_portfolio=exp_pct,
    )

    flt = _load_json(STATE / "fund_lookthrough.json", {})
    overlap = _issuer_overlap(hold, flt)

    same_account_mv = {
        str(h.get("symbol") or "").upper(): round(_as_float(h.get("market_value")), 2)
        for h in acct_holdings
    }

    return {
        "portfolio_equity_usd": round(totals["equity_usd"], 2),
        "portfolio_total_with_cash_usd": round(totals["total_with_cash_usd"], 2),
        "portfolio_equity_note": "Command Center Holdings tab uses equity MV; cash reported separately",
        "sale_account": account,
        "default_deployment_account": account,
        "cross_account_requires": "explicit_transfer_scenario",
        **reconciliation,
        **major,
        "same_account_holdings_mv": same_account_mv,
        "overlap_analysis": overlap[:40],
        "concentration_limits": {
            "single_position_pct": 8.0,
            "sector_pct": 25.0,
            "industry_pct": 15.0,
            "etf_pct": 12.0,
            "thematic_sleeve_pct": 22.0,
            "issuer_lookthrough_pct": 5.0,
        },
        "risk_math": {
            "vol_delta_unit": "absolute_percentage_points",
            "vol_delta_max_pp": VOL_DELTA_ABS_PP_MAX,
            "drawdown_reject_threshold_pct": DRAWDOWN_REJECT_THRESHOLD_PCT,
            "drawdown_rule": "reject when estimated_max_drawdown_pct <= -15",
            "lookback_days": 252,
            "frequency": "daily",
            "covariance_method": "sample_pairwise_on_portfolio_returns",
            "unavailable_data": "plan_stays_draft_with_RPL_DATA_GAP",
        },
        "operator_ready_thresholds": {
            "min_confidence": OPERATOR_READY_MIN_CONFIDENCE,
            "min_evidence_factors": OPERATOR_READY_MIN_EVIDENCE_FACTORS,
            "export_quote_max_age_minutes": EXPORT_QUOTE_MAX_AGE_MINUTES,
            "stale_display_allowed": True,
            "stale_export_blocked": True,
        },
        "exposure_summary": {
            "sector_count": len(exposure.get("sectors") or []),
            "residual_sector_pct": exposure.get("residual_sector_pct"),
            "income_status": exposure.get("income_status"),
        },
    }


def input_hash(event: dict[str, Any], exposure: dict[str, Any]) -> str:
    payload = json.dumps({
        "event_key": event.get("event_key"),
        "proceeds": _as_float(event.get("proceeds_usd")),
        "account": event.get("account"),
        "holdings_snapshot_id": holdings_snapshot_id(),
        "exposure_source": exposure.get("source_as_of"),
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def enrich_event_phase_a(event: dict[str, Any]) -> dict[str, Any]:
    """Attach Phase A truth to event dict (and metadata) — no plan generation."""
    account = str(event.get("account") or "")
    proceeds = _as_float(event.get("proceeds_usd"))
    cash_vis = event.get("cash_visible_usd")
    if cash_vis is not None:
        cash_vis = _as_float(cash_vis)
    else:
        cash_vis = account_cash_usd(account)

    op_settle = (event.get("metadata") or {}).get("phase_a", {}).get("operator_settlement")
    recon = reconcile_proceeds(
        account=account,
        proceeds_usd=proceeds,
        cash_visible_usd=cash_vis,
        sold_at=event.get("sold_at"),
        operator_settlement=op_settle,
    )
    exposure = decompose_exposure_loss(
        symbol=str(event.get("symbol") or ""),
        proceeds_usd=proceeds,
        proxy_symbol=event.get("proxy_symbol"),
    )
    context = build_portfolio_context(event, reconciliation=recon, exposure=exposure)

    event["net_proceeds_usd"] = recon["net_proceeds_usd"]
    event["deployable_cash_usd"] = recon["deployable_cash_usd"]
    event["reconciliation_status"] = recon["reconciliation_status"]
    event["proceeds_settled"] = recon["reconciliation_status"] == "verified"
    event["policy_version"] = POLICY_VERSION
    event["generator_version"] = GENERATOR_VERSION
    event["holdings_snapshot_id"] = holdings_snapshot_id()

    meta = dict(event.get("metadata") or {})
    meta["phase_a"] = {
        "reconciliation": recon,
        "exposure_loss": exposure,
        "portfolio_context": context,
        "input_hash": input_hash(event, exposure),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    event["metadata"] = meta
    return event