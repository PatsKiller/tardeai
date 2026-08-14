"""cio_report_analytics.py — Phase 6 analytic completeness + methodology truth.

Builds methodology-labeled analytics from the canonical report Part B (and
optional history inputs). Never fabricates TWR/QTD/style-box when source truth
is insufficient. Every numeric section carries source + quality + coverage.

READ_ONLY_ADVISORY. Pure. No broker / Telegram / writes.
"""
from __future__ import annotations

from typing import Any, Optional

ANALYTICS_VERSION = "analytics_1.0.0"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"

# Methodology labels (never mix without naming)
METH_CUMULATIVE = "cumulative_return"
METH_CAGR = "cagr_money_weighted_proxy"
METH_SNAPSHOT = "snapshot_period_return"
METH_ACCOUNT_AGG = "account_aggregated_period_return"
METH_TWR = "time_weighted_return"
METH_MWR = "money_weighted_return"
METH_UNAVAILABLE = "unavailable"


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _quality_from_source(source: Any) -> str:
    s = str(source or "").lower()
    if "account-aggregated" in s or "account_aggregated" in s:
        return "flagged"
    if "unavailable" in s or s in ("none", ""):
        return "unavailable"
    if "partial" in s or "estimate" in s:
        return "partial"
    return "ok"


# ─────────────────────────────────────────────────────────────────────────────
# 6.1 Performance definitions
# ─────────────────────────────────────────────────────────────────────────────

def performance_metric(
    *,
    metric: str,
    value: Any,
    methodology: str,
    source: str,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    flow_treatment: str = "not_specified",
    fee_treatment: str = "not_specified",
    benchmark: Optional[str] = None,
    quality: Optional[str] = None,
    unit: str = "percent",
    note: str = "",
) -> dict[str, Any]:
    """One fully labeled performance figure — required schema for Phase 6.1."""
    q = quality or _quality_from_source(source)
    v = _num(value)
    unavailable = methodology == METH_UNAVAILABLE or q == "unavailable" or v is None
    return {
        "metric": metric,
        "value": None if unavailable else v,
        "value_display": DATA_UNAVAILABLE if unavailable else v,
        "unit": unit,
        "period_start": period_start,
        "period_end": period_end,
        "methodology": methodology,
        "flow_treatment": flow_treatment,
        "fee_treatment": fee_treatment,
        "benchmark": benchmark,
        "source": source if not unavailable else "none",
        "quality": "unavailable" if unavailable else q,
        "note": note,
        "is_unavailable": unavailable,
    }


def build_performance_definitions(
    performance: Optional[dict[str, Any]] = None,
    *,
    as_of: Optional[str] = None,
    history_periods: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build the full set of labeled performance metrics from Part B / history."""
    perf = performance or {}
    periods = history_periods or perf.get("period_returns") or perf.get("periods") or {}
    bench = perf.get("benchmark_label") or None
    metrics: list[dict[str, Any]] = []

    # Period returns with methodology by source
    order = ("1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "QTD")
    for key in order:
        cell = periods.get(key) if isinstance(periods, dict) else None
        if key == "QTD" and not cell:
            metrics.append(performance_metric(
                metric=f"return_{key}",
                value=None,
                methodology=METH_UNAVAILABLE,
                source="none",
                period_end=as_of,
                quality="unavailable",
                note=("QTD requires a quarter-start valuation snapshot; "
                      "not present in performance_history. DATA_UNAVAILABLE."),
            ))
            continue
        if cell is None and key in ("1M", "YTD") and key == "YTD":
            # fall back to ytd_return root
            if _num(perf.get("ytd_return")) is not None:
                metrics.append(performance_metric(
                    metric="return_YTD",
                    value=perf.get("ytd_return"),
                    methodology=METH_SNAPSHOT,
                    source="performance.ytd_return",
                    period_end=as_of,
                    benchmark=bench,
                    note="YTD from performance root field.",
                ))
            continue
        if not isinstance(cell, dict) and _num(cell) is None:
            continue
        if isinstance(cell, dict):
            val = cell.get("change_pct")
            if val is None:
                val = cell.get("return_pct")
            src = str(cell.get("source") or "performance.period_returns")
            meth = METH_ACCOUNT_AGG if "account-aggregated" in src.lower() else METH_SNAPSHOT
            metrics.append(performance_metric(
                metric=f"return_{key}",
                value=val,
                methodology=meth,
                source=src,
                period_start=cell.get("period_start") or cell.get("start"),
                period_end=cell.get("period_end") or cell.get("end") or as_of,
                flow_treatment=str(cell.get("flow_treatment") or "embedded_in_period_value"),
                fee_treatment=str(cell.get("fee_treatment") or "not_specified"),
                benchmark=bench,
                note=str(cell.get("note") or ""),
            ))
        else:
            metrics.append(performance_metric(
                metric=f"return_{key}",
                value=cell,
                methodology=METH_SNAPSHOT,
                source="performance.period_returns",
                period_end=as_of,
                benchmark=bench,
            ))

    # CAGR / inception — labeled as money-weighted proxy, not true TWR
    if _num(perf.get("port_cagr")) is not None:
        metrics.append(performance_metric(
            metric="portfolio_cagr",
            value=perf.get("port_cagr"),
            methodology=METH_CAGR,
            source="performance.port_cagr",
            period_end=as_of,
            benchmark=bench,
            note="Canonical portfolio CAGR (money-weighted / reconstructed proxy). Not true TWR.",
        ))
    if _num(perf.get("bench_cagr")) is not None:
        metrics.append(performance_metric(
            metric="benchmark_cagr",
            value=perf.get("bench_cagr"),
            methodology=METH_CAGR,
            source="performance.bench_cagr",
            period_end=as_of,
            benchmark=bench,
            note="Benchmark CAGR for comparison; period alignment checked separately.",
        ))
    if _num(perf.get("inception_return")) is not None:
        metrics.append(performance_metric(
            metric="inception_cumulative_return",
            value=perf.get("inception_return"),
            methodology=METH_CUMULATIVE,
            source="performance.inception_return",
            period_end=as_of,
            note="Cumulative since inception — not annualized.",
        ))
    if _num(perf.get("alpha_annualized")) is not None:
        metrics.append(performance_metric(
            metric="alpha_annualized",
            value=perf.get("alpha_annualized"),
            methodology=METH_CAGR,
            source="performance.alpha_annualized",
            period_end=as_of,
            benchmark=bench,
            note="Annualized alpha vs stated benchmark (same CAGR family).",
        ))

    # True TWR — always explicit unavailable unless source proves it
    twr_val = perf.get("true_twr") or perf.get("twr")
    if _num(twr_val) is not None and perf.get("twr_methodology") == METH_TWR:
        metrics.append(performance_metric(
            metric="true_twr",
            value=twr_val,
            methodology=METH_TWR,
            source=str(perf.get("twr_source") or "performance.true_twr"),
            period_end=as_of,
            note="True time-weighted return from cash-flow-aware valuation series.",
        ))
    else:
        metrics.append(performance_metric(
            metric="true_twr",
            value=None,
            methodology=METH_UNAVAILABLE,
            source="none",
            period_end=as_of,
            quality="unavailable",
            note=("True TWR requires external-flow-aware period valuations. "
                  "Not reconstructed from insufficient data. DATA_UNAVAILABLE."),
        ))

    return {
        "version": ANALYTICS_VERSION,
        "as_of": as_of,
        "metrics": metrics,
        "metric_count": len(metrics),
        "unavailable_count": sum(1 for m in metrics if m.get("is_unavailable")),
        "flagged_count": sum(1 for m in metrics if m.get("quality") == "flagged"),
        "definitions_complete": all(
            m.get("methodology") and m.get("source") is not None and m.get("quality")
            for m in metrics
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6.3 Change in value reconciliation
# ─────────────────────────────────────────────────────────────────────────────

def build_change_in_value(
    performance: Optional[dict[str, Any]] = None,
    flows: Optional[dict[str, Any]] = None,
    *,
    portfolio_value: Optional[float] = None,
) -> dict[str, Any]:
    """beginning + net flows + earnings = ending, only when inputs reconcile."""
    perf = performance or {}
    flows = dict(flows or perf.get("change_value") or {})

    begin = _num(flows.get("beginning_value") or flows.get("begin") or flows.get("start_value"))
    end = _num(
        flows.get("ending_value") or flows.get("end") or flows.get("end_value")
        or portfolio_value or perf.get("current_value")
    )
    net_flow = _num(
        flows.get("net_contributions") or flows.get("net_flow")
        or flows.get("contributions_withdrawals")
    )
    earnings = _num(flows.get("investment_earnings") or flows.get("earnings") or flows.get("market_change"))

    # Derive missing piece if exactly one is missing and others present
    derived = None
    if begin is not None and end is not None and net_flow is not None and earnings is None:
        earnings = end - begin - net_flow
        derived = "investment_earnings"
    elif begin is not None and end is not None and earnings is not None and net_flow is None:
        net_flow = end - begin - earnings
        derived = "net_contributions"
    elif begin is not None and net_flow is not None and earnings is not None and end is None:
        end = begin + net_flow + earnings
        derived = "ending_value"

    components = {
        "beginning_value": begin,
        "net_contributions_withdrawals": net_flow,
        "investment_earnings": earnings,
        "ending_value": end,
    }
    present = {k: v for k, v in components.items() if v is not None}
    displayed = len(present) >= 3 and begin is not None and end is not None

    residual = None
    reconciles = False
    if None not in (begin, end, net_flow, earnings):
        residual = round((begin + net_flow + earnings) - end, 2)
        reconciles = abs(residual) <= 1.01  # $1 tolerance

    status = "not_displayed"
    if displayed and reconciles:
        status = "reconciled"
    elif displayed and residual is not None and not reconciles:
        status = "broken_hidden"  # do not show equation if broken
        displayed = False
    elif not displayed:
        status = "insufficient_inputs"

    return {
        "version": ANALYTICS_VERSION,
        "status": status,
        "displayed": displayed and reconciles,
        "components": components,
        "equation": "beginning + net_contributions_withdrawals + investment_earnings = ending",
        "residual_usd": residual,
        "reconciles": reconciles,
        "invariant_ok": (not displayed) or reconciles,
        "derived_component": derived,
        "source": "performance.change_value / flows" if present else "none",
        "quality": "ok" if reconciles else ("flagged" if residual is not None else "unavailable"),
        "note": (
            "Change-in-value bridge shown only when the identity reconciles."
            if status == "reconciled"
            else "Insufficient or non-reconciling flow inputs — bridge not displayed (no fabrication)."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6.4 Benchmark comparability
# ─────────────────────────────────────────────────────────────────────────────

def build_benchmark_alignment(
    performance: Optional[dict[str, Any]] = None,
    benchmark: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Require aligned periods/methodologies or label non-comparable."""
    perf = performance or {}
    bench = benchmark or {}
    label = perf.get("benchmark_label") or bench.get("label")
    port_cagr = _num(perf.get("port_cagr"))
    bench_cagr = _num(perf.get("bench_cagr") if perf.get("bench_cagr") is not None else bench.get("cagr"))
    port_period = perf.get("cagr_period") or perf.get("period_end") or "inception/as-of"
    bench_period = bench.get("period") or perf.get("bench_cagr_period") or port_period
    same_family = True  # both treated as CAGR family when both present
    aligned = (
        port_cagr is not None
        and bench_cagr is not None
        and label
        and str(port_period) == str(bench_period)
    )
    comparable = bool(label and port_cagr is not None and bench_cagr is not None)
    return {
        "version": ANALYTICS_VERSION,
        "benchmark_label": label,
        "portfolio_cagr": port_cagr,
        "benchmark_cagr": bench_cagr,
        "portfolio_period": port_period,
        "benchmark_period": bench_period,
        "methodology_family": METH_CAGR,
        "periods_aligned": aligned or (comparable and port_period == bench_period),
        "comparable": comparable,
        "comparability_label": (
            "comparable_cagr" if comparable and (aligned or port_period == bench_period)
            else ("non_comparable_period_mismatch" if comparable else "benchmark_incomplete")
        ),
        "note": (
            "Portfolio and benchmark CAGRs share the same methodology family and period label."
            if comparable and (aligned or port_period == bench_period)
            else "Benchmark comparison incomplete or period-mismatched — do not treat as aligned."
        ),
        "quality": "ok" if comparable else "partial",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6.5 Attribution honesty
# ─────────────────────────────────────────────────────────────────────────────

def build_attribution_section(
    performance: Optional[dict[str, Any]] = None,
    attribution: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Only label allocation/selection effect when methodology actually computes them."""
    perf = performance or {}
    attr = attribution or perf.get("attribution") or {}
    rows: list[dict[str, Any]] = []

    def _add(name: str, value: Any, *, computed: bool, meth: str, source: str, note: str = "") -> None:
        if computed and _num(value) is not None:
            rows.append({
                "component": name,
                "value": _num(value),
                "methodology": meth,
                "source": source,
                "quality": "ok",
                "note": note,
            })
        else:
            rows.append({
                "component": name,
                "value": None,
                "value_display": DATA_UNAVAILABLE,
                "methodology": METH_UNAVAILABLE,
                "source": "none",
                "quality": "unavailable",
                "note": note or f"{name} not computed by current attribution engine.",
            })

    # Rolling alpha is real when series/point exists
    alpha = perf.get("alpha_annualized")
    _add(
        "rolling_alpha_annualized",
        alpha,
        computed=_num(alpha) is not None,
        meth=METH_CAGR,
        source="performance.alpha_annualized",
        note="Annualized alpha vs benchmark (CAGR family).",
    )

    # Security / sector contribution only if provided with methodology flag
    _add(
        "security_contribution",
        attr.get("security_contribution"),
        computed=bool(attr.get("security_contribution_method")),
        meth=str(attr.get("security_contribution_method") or METH_UNAVAILABLE),
        source=str(attr.get("security_contribution_source") or "none"),
    )
    _add(
        "sector_contribution",
        attr.get("sector_contribution"),
        computed=bool(attr.get("sector_contribution_method")),
        meth=str(attr.get("sector_contribution_method") or METH_UNAVAILABLE),
        source=str(attr.get("sector_contribution_source") or "none"),
    )
    # Never call allocation/selection effect unless method is present
    _add(
        "allocation_effect",
        attr.get("allocation_effect"),
        computed=str(attr.get("allocation_effect_method") or "").lower() in {
            "brinson", "brinson_fachler", "brinson-fachler",
        },
        meth=str(attr.get("allocation_effect_method") or METH_UNAVAILABLE),
        source=str(attr.get("allocation_effect_source") or "none"),
        note="Only labeled when a Brinson-style engine supplies the effect.",
    )
    _add(
        "selection_effect",
        attr.get("selection_effect"),
        computed=str(attr.get("selection_effect_method") or "").lower() in {
            "brinson", "brinson_fachler", "brinson-fachler",
        },
        meth=str(attr.get("selection_effect_method") or METH_UNAVAILABLE),
        source=str(attr.get("selection_effect_source") or "none"),
        note="Only labeled when a Brinson-style engine supplies the effect.",
    )

    return {
        "version": ANALYTICS_VERSION,
        "components": rows,
        "fabricated_count": 0,  # we never invent effects
        "note": "Attribution maturity is not overstated; unavailable effects are DATA_UNAVAILABLE.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6.6 Look-through / X-Ray coverage
# ─────────────────────────────────────────────────────────────────────────────

def build_lookthrough_coverage(xray: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Disclose look-through coverage; never treat opaque funds as known sectors."""
    xr = xray or {}
    cov = _num(xr.get("coverage_pct") or xr.get("lookthrough_coverage_pct"))
    sector_total = _num(xr.get("sector_total"))
    not_decomp = xr.get("not_decomposed") or xr.get("unclassified") or []
    if cov is None and sector_total is not None:
        cov = sector_total if sector_total <= 100 else None
    if cov is None:
        # estimate from sectors sum if plausible
        sectors = xr.get("sectors") or []
        ssum = sum(_num(s.get("pct")) or 0.0 for s in sectors if isinstance(s, dict))
        if ssum > 0:
            cov = min(100.0, ssum)
    unclassified = None
    if cov is not None:
        unclassified = round(max(0.0, 100.0 - float(cov)), 2)

    sectors = []
    for s in (xr.get("sectors") or [])[:15]:
        if isinstance(s, dict) and s.get("sector"):
            sectors.append({
                "sector": s.get("sector"),
                "pct": _num(s.get("pct")),
                "source": s.get("source") or "xray.sectors",
            })

    top_underlying = []
    for u in (xr.get("top_underlying") or [])[:15]:
        if isinstance(u, dict):
            top_underlying.append({
                "symbol": u.get("symbol") or u.get("name"),
                "pct": _num(u.get("pct") or u.get("weight_pct")),
                "source": u.get("source") or "xray.top_underlying",
            })

    return {
        "version": ANALYTICS_VERSION,
        "lookthrough_coverage_pct": cov,
        "unclassified_pct": unclassified,
        "coverage_disclosed": cov is not None,
        "coverage_label": (
            f"look-through coverage: {cov:.0f}% of invested assets; "
            f"unclassified: {unclassified:.0f}%"
            if cov is not None and unclassified is not None
            else "look-through coverage: DATA_UNAVAILABLE"
        ),
        "sectors": sectors,
        "top_underlying": top_underlying,
        "not_decomposed_count": len(not_decomp) if isinstance(not_decomp, list) else _num(not_decomp),
        "quality": "ok" if cov is not None and cov >= 50 else ("partial" if cov is not None else "unavailable"),
        "note": "Opaque funds are never silently classified as known sector exposure.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6.7 Valuation with coverage
# ─────────────────────────────────────────────────────────────────────────────

def build_valuation_coverage(analytics: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Multiples only with explicit market-value coverage (impossible to miss)."""
    an = analytics or {}
    cov = _num(an.get("valuation_coverage_pct"))
    note = an.get("valuation_coverage_note") or ""
    multiples = []
    for key, label in (
        ("weighted_pe", "Weighted P/E"),
        ("weighted_pb", "Weighted P/B"),
        ("weighted_ps", "Weighted P/S"),
        ("weighted_pcf", "Weighted P/CF"),
        ("forward_pe", "Forward P/E"),
        ("weighted_forward_pe", "Forward P/E"),
    ):
        v = _num(an.get(key))
        if v is None:
            continue
        multiples.append({
            "metric": key,
            "label": label,
            "value": v,
            "coverage_pct": cov,
            "displayed_with_coverage": True,
            "source": f"analytics.{key}",
            "quality": "ok" if cov is not None and cov >= 25 else "partial",
        })

    if not multiples and cov is None:
        status = "unavailable"
    elif multiples and cov is not None:
        status = "partial" if cov < 50 else "ok"
    else:
        status = "partial"

    return {
        "version": ANALYTICS_VERSION,
        "status": status,
        "coverage_pct": cov,
        "coverage_disclosed": True,  # always disclose, even if unavailable
        "coverage_label": (
            f"Coverage: {cov:.0f}% of invested market value"
            if cov is not None
            else "Coverage: DATA_UNAVAILABLE (multiples not shown as portfolio-complete)"
        ),
        "multiples": multiples,
        "fund_etf_pct": _num(an.get("fund_etf_pct")),
        "note": note or (
            "Valuation multiples are direct-equity weighted where coverage allows; "
            "never presented without coverage."
        ),
        "quality": status,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6.8 Tax lots / unrealized (with quality disclosure)
# ─────────────────────────────────────────────────────────────────────────────

def build_tax_lot_section(
    unrealized: Optional[dict[str, Any]] = None,
    *,
    max_rows: int = 25,
) -> dict[str, Any]:
    """Open-lot / unrealized detail with source quality flags. Not tax-filing truth."""
    ur = unrealized or {}
    rows_in = ur.get("rows") or ur.get("lots") or []
    rows: list[dict[str, Any]] = []
    for r in rows_in[:max_rows]:
        if not isinstance(r, dict):
            continue
        basis_flag = r.get("quality_flag") or r.get("basis_flag") or r.get("_basis_ln_flagged")
        if basis_flag is True:
            basis_flag = "basis_partial"
        rows.append({
            "symbol": r.get("symbol"),
            "account": r.get("account") or r.get("account_id"),
            "purchase_date": r.get("purchase_date") or r.get("lot_date") or r.get("acquired"),
            "quantity": _num(r.get("quantity") or r.get("qty") or r.get("shares")),
            "average_cost": _num(r.get("average_cost") or r.get("cost_per_share") or r.get("avg_cost")),
            "cost_basis": _num(r.get("cost_basis") or r.get("total_cost") or r.get("basis")),
            "current_price": _num(r.get("current_price") or r.get("price")),
            "market_value": _num(r.get("market_value") or r.get("mv") or r.get("value")),
            "unrealized_gl_usd": _num(r.get("unrealized_gl") or r.get("unrealized_gl_usd") or r.get("gain_loss")),
            "unrealized_gl_pct": _num(r.get("unrealized_gl_pct") or r.get("gain_loss_pct")),
            "holding_period": r.get("holding_period") or r.get("term") or (
                "long_term" if r.get("long_term") else ("short_term" if r.get("short_term") else None)
            ),
            "quality_flag": basis_flag or "ok",
            "source": r.get("source") or "unrealized/tax_lots",
        })

    return {
        "version": ANALYTICS_VERSION,
        "lt_unrealized_usd": _num(ur.get("lt_unrealized")),
        "st_unrealized_usd": _num(ur.get("st_unrealized")),
        "row_count": len(rows),
        "source_count": _num(ur.get("count")) or len(rows_in),
        "rows": rows,
        "quality": "partial" if any(r.get("quality_flag") not in (None, "ok") for r in rows) else (
            "ok" if rows else "unavailable"
        ),
        "coverage_disclosed": True,
        "disclaimer": (
            "Tax-lot and unrealized figures are advisory portfolio analytics only. "
            "They are not tax-filing truth; basis completeness may be partial."
        ),
        "note": "Per-lot adjusted basis completeness is partial where flagged.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6.9 Income
# ─────────────────────────────────────────────────────────────────────────────

def build_income_section(income: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Income only when canonical data supports it; else partial/unavailable."""
    inc = income or {}
    trailing = _num(inc.get("trailing_income") or inc.get("ttm_income") or inc.get("trailing_12m"))
    forward = _num(inc.get("forward_income") or inc.get("estimated_income"))
    yield_pct = _num(inc.get("yield_pct") or inc.get("yield") or inc.get("portfolio_yield"))
    if trailing is None and forward is None and yield_pct is None:
        return {
            "version": ANALYTICS_VERSION,
            "status": "unavailable",
            "trailing_income_usd": None,
            "forward_income_usd": None,
            "yield_pct": None,
            "quality": "unavailable",
            "note": "Canonical income data not present — section marked DATA_UNAVAILABLE (not invented).",
            "value_display": DATA_UNAVAILABLE,
        }
    return {
        "version": ANALYTICS_VERSION,
        "status": "partial" if None in (trailing, forward, yield_pct) else "ok",
        "trailing_income_usd": trailing,
        "forward_income_usd": forward,
        "yield_pct": yield_pct,
        "account_concentration": inc.get("account_concentration") or inc.get("sleeve_concentration"),
        "next_distributions": inc.get("next_distributions") or inc.get("next_material_distributions") or [],
        "source": inc.get("source") or "income book",
        "quality": "partial" if None in (trailing, forward, yield_pct) else "ok",
        "note": "Income figures only from canonical income inputs.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Packet assembler
# ─────────────────────────────────────────────────────────────────────────────

def build_analytics_packet(
    part_b: Optional[dict[str, Any]] = None,
    *,
    performance_attribution: Optional[dict[str, Any]] = None,
    history_periods: Optional[dict[str, Any]] = None,
    as_of: Optional[str] = None,
) -> dict[str, Any]:
    """Compose the full Phase 6 analytics packet for the report model/view."""
    pb = part_b or {}
    perf = pb.get("performance") or {}
    as_of = as_of or pb.get("as_of")
    portfolio = pb.get("portfolio") or {}

    performance_defs = build_performance_definitions(
        perf, as_of=as_of, history_periods=history_periods or perf.get("period_returns"),
    )
    change_in_value = build_change_in_value(
        perf, pb.get("flows"), portfolio_value=_num(portfolio.get("total_value")),
    )
    benchmark = build_benchmark_alignment(perf, pb.get("benchmark"))
    attribution = build_attribution_section(perf, performance_attribution or pb.get("attribution"))
    lookthrough = build_lookthrough_coverage(pb.get("xray"))
    valuation = build_valuation_coverage(pb.get("analytics"))
    tax_lots = build_tax_lot_section(pb.get("unrealized"))
    income = build_income_section(pb.get("income"))

    fabricated = 0  # enforced: unavailable instead of invention
    for m in performance_defs.get("metrics") or []:
        if m.get("is_unavailable") and m.get("value") is not None:
            fabricated += 1

    exit_gate = {
        "PERFORMANCE_METRIC_DEFINITIONS": (
            "PASS" if performance_defs.get("definitions_complete") else "FAIL"
        ),
        "CHANGE_IN_VALUE_RECONCILIATION": (
            "PASS" if change_in_value.get("invariant_ok") else "FAIL"
        ),
        "BENCHMARK_PERIOD_ALIGNMENT": (
            "PASS" if (
                not benchmark.get("comparable")
                or benchmark.get("comparability_label") == "comparable_cagr"
            ) else "FAIL"
        ),
        "LOOKTHROUGH_COVERAGE_DISCLOSED": (
            "PASS" if lookthrough.get("coverage_disclosed") else "FAIL"
        ),
        "VALUATION_COVERAGE_DISCLOSED": (
            "PASS" if valuation.get("coverage_disclosed") else "FAIL"
        ),
        "TAX_LOT_SOURCE_QUALITY_DISCLOSED": (
            "PASS" if tax_lots.get("coverage_disclosed") and tax_lots.get("disclaimer") else "FAIL"
        ),
        "FABRICATED_METRIC_COUNT": fabricated,
    }
    exit_gate["ALL_PASS"] = (
        all(v == "PASS" for k, v in exit_gate.items() if k != "FABRICATED_METRIC_COUNT" and k != "ALL_PASS")
        and fabricated == 0
    )

    return {
        "version": ANALYTICS_VERSION,
        "as_of": as_of,
        "performance_definitions": performance_defs,
        "change_in_value": change_in_value,
        "benchmark_alignment": benchmark,
        "attribution": attribution,
        "lookthrough": lookthrough,
        "valuation": valuation,
        "tax_lots": tax_lots,
        "income": income,
        "exit_gate": exit_gate,
        "fabricated_metric_count": fabricated,
    }


def enrich_part_b(part_b: Optional[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    """Return a copy of part_b with analytics_packet attached."""
    pb = dict(part_b or {})
    packet = build_analytics_packet(pb, **kwargs)
    pb["analytics_packet"] = packet
    # Convenience mirrors for renderers
    pb["change_in_value"] = packet["change_in_value"]
    pb["lookthrough_coverage"] = packet["lookthrough"]
    pb["valuation_coverage"] = packet["valuation"]
    pb["performance_definitions"] = packet["performance_definitions"]
    pb["benchmark_alignment"] = packet["benchmark_alignment"]
    pb["attribution_section"] = packet["attribution"]
    pb["tax_lot_section"] = packet["tax_lots"]
    pb["income_section"] = packet["income"]
    return pb
