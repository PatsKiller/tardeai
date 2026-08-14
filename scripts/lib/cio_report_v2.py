"""cio_report_v2.py — Trade AI Institutional Report v2 (Phase 7).

"Morgan Stanley completeness + Trade AI CIO intelligence."

Composes the whole advisory surface into one report with two parts:

  Part A — CIO Investment Committee front matter (Trade AI's own addition):
           CIO Letter, Decisions Now, Capital Plan, Portfolio Posture,
           Opportunity Funnel, Counter-Thesis / Risks.

  Part B — Institutional portfolio book (Morgan Stanley completeness benchmark):
           accounts, summary, flows, performance, attribution, allocation,
           look-through, valuation, risk, income, tax/lots, realized, re-entry,
           watch/opportunity, rotation/defense, dispositions, methodology,
           disclosures.

Plus the two Phase 7 truth artifacts:

  * field-coverage matrix — every required Morgan Stanley field mapped to one of
    IMPLEMENTED_WITH_SOURCE_PROOF / EXPLICITLY_UNAVAILABLE /
    DOCUMENTED_METHODOLOGY_SUBSTITUTE, each carrying source/as_of/coverage/quality.
  * immutable report manifest — input hashes + source SHA + field counts.

Everything here is READ-ONLY and advisory. Pure functions are deterministic and
separated from the live readers so the report model, coverage matrix, manifest,
and Checkpoint 7 summary are dry-testable with no live DB / broker / LLM.

No numerical figure is ever printed without a source; a figure whose source is
flagged inconsistent is either excluded or printed with a data-quality footnote
immediately adjacent (never buried).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

Executor = Callable[..., Any]

REPORT_VERSION = "report_v2_1.4.0"  # Phase 7: output pipeline + immutable instance manifest

# ── Taxonomy ─────────────────────────────────────────────────────────────────

IMPLEMENTED = "IMPLEMENTED_WITH_SOURCE_PROOF"
UNAVAILABLE = "EXPLICITLY_UNAVAILABLE"
SUBSTITUTE = "DOCUMENTED_METHODOLOGY_SUBSTITUTE"
FIELD_STATUSES = frozenset({IMPLEMENTED, UNAVAILABLE, SUBSTITUTE})

NUMERIC = "numeric"
NON_NUMERIC = "non_numeric"

# Fields where Trade AI's version carries CIO intelligence the static Morgan
# Stanley reference does not: the two-way loop, capital-plan-aware constraints,
# realized-outcome loop, and risk heat. This drives `fields_improved_vs_reference`.
IMPROVED_VS_REFERENCE = frozenset({
    "investment_summary",              # CIO thesis/stance + priorities (vs static)
    "concentration_risk",              # single-name-cap aware (capital plan)
    "risk_heat",                       # drawdown/sharpe/sortino heat + stance
    "wash_sale_account_constraints",   # capital-plan tax-aware account constraints
    "closed_positions_realized_summary",  # realized-outcome loop
    "reentry_book",                    # two-way re-entry
    "watch_opportunity_book",          # two-way watch/opportunity queue
    "rotation_defense_posture",        # rotation/defense posture
    "decision_history_dispositions",   # operator disposition loop
})


def _now_iso(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Known gaps (from the prior completeness review) → mandatory resolution choice
# ─────────────────────────────────────────────────────────────────────────────

# Each gap must resolve to exactly one of the three statuses. Encoded once here
# so the coverage matrix and the report body never disagree.
KNOWN_GAPS: tuple[dict[str, Any], ...] = (
    {
        "gap_id": "gap_qtd_absent",
        "title": "QTD return absent in prior performance history",
        "resolution": UNAVAILABLE,
        "note": ("performance_history.json tracks 1D/1W/1M/3M/6M/YTD/1Y only; no "
                 "quarter-start valuation snapshot exists to derive QTD. Not estimated."),
        "field_ids": ("perf_QTD",),
    },
    {
        "gap_id": "gap_true_twr",
        "title": "True time-weighted return (TWR) previously a non-goal / unavailable",
        "resolution": UNAVAILABLE,
        "note": ("True TWR is a non-goal; money-weighted CAGR / IRR is the canonical "
                 "return metric and is reported instead (see perf_inception)."),
        "field_ids": ("perf_true_TWR",),
    },
    {
        "gap_id": "gap_per_lot_basis",
        "title": "Incomplete per-lot adjusted basis and acquisition-date coverage",
        "resolution": SUBSTITUTE,
        "note": ("tax_lots.json carries per-lot lot_date + cost_per_share + total_cost "
                 "for the lots it holds; adjusted-basis completeness is partial and is "
                 "flagged per symbol (basis_partial / _basis_ln_flagged)."),
        "field_ids": ("tax_per_lot_details", "tax_adjusted_basis_quality"),
    },
    {
        "gap_id": "gap_fund_lookthrough",
        "title": "Weak fund/ETF valuation/style look-through coverage",
        "resolution": SUBSTITUTE,
        "note": ("fund_lookthrough.json provides sector_weights + top_holdings for 30 "
                 "funds/ETFs; valuation multiples and style are direct-equity only "
                 "(~21% direct-equity coverage) — look-through wired separately."),
        "field_ids": ("valuation_pe", "valuation_pb", "valuation_ps",
                      "valuation_pcf", "valuation_forward", "style_value_blend_growth"),
    },
    {
        "gap_id": "gap_3m_1y_inconsistent",
        "title": "Inconsistent account-aggregated 3M/1Y performance fields",
        "resolution": SUBSTITUTE,
        "note": ("3M and 1Y are account-aggregated and internally inconsistent; they "
                 "are reported with an explicit quality flag and the snapshot-based "
                 "periods (1W/1M/6M/YTD) are preferred."),
        "field_ids": ("perf_3M", "perf_1Y"),
    },
    {
        "gap_id": "gap_style_box",
        "title": "No mature 3×3 style box",
        "resolution": UNAVAILABLE,
        "note": ("A mature value/blend/growth × large/mid/small style box is not "
                 "source-proven; market-cap/style exposure is reported from buckets "
                 "where available instead."),
        "field_ids": ("style_value_blend_growth",),
    },
)


def resolve_gap(gap_id: str) -> Optional[dict[str, Any]]:
    for g in KNOWN_GAPS:
        if g["gap_id"] == gap_id:
            return g
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Field template (canonical Morgan Stanley completeness benchmark)
# ─────────────────────────────────────────────────────────────────────────────
# field_id, section, label, kind, status, source, coverage, quality
# `status` is derived from the gap resolutions at build time; the base tuple
# carries the default and the field's kind.

_FIELDS: tuple[tuple[str, str, str, str, str, str, str], ...] = (
    # ── Accounts / household ──
    ("accounts_included", "Accounts", "Accounts included / household total", NUMERIC,
     IMPLEMENTED, "holdings.json account_summaries", "100%", "ok"),
    ("household_total", "Accounts", "Household total value", NUMERIC,
     IMPLEMENTED, "holdings.json portfolio_totals.total_value", "100%", "ok"),
    # ── Investment summary ──
    ("investment_summary", "Summary", "Investment summary / thesis stance", NON_NUMERIC,
     IMPLEMENTED, "cio_theses.jsonl desk@head (summary, stance, bullets)", "100%", "ok"),
    ("positions_count", "Summary", "Position count", NUMERIC,
     IMPLEMENTED, "holdings.json holdings (non-cash)", "100%", "ok"),
    # ── Contributions / withdrawals / change in value ──
    ("contributions_withdrawals", "Flows", "Contributions, withdrawals and change in value", NUMERIC,
     SUBSTITUTE, "performance_history.json change_value + cost_basis_transfer_events.json", "partial", "flagged"),
    ("change_in_value", "Flows", "Change in value (period)", NUMERIC,
     IMPLEMENTED, "performance_history.json periods", "100%", "ok"),
    # ── Performance ──
    ("perf_1M", "Performance", "1M return", NUMERIC,
     IMPLEMENTED, "performance_history.json periods.1M (snapshot)", "100%", "ok"),
    ("perf_3M", "Performance", "3M return", NUMERIC,
     SUBSTITUTE, "performance_history.json periods.3M (account-aggregated)", "100%", "flagged"),
    ("perf_QTD", "Performance", "QTD return", NUMERIC,
     UNAVAILABLE, "none", "0%", "unavailable"),
    ("perf_YTD", "Performance", "YTD return", NUMERIC,
     IMPLEMENTED, "performance_history.json periods.YTD (snapshot)", "100%", "ok"),
    ("perf_1Y", "Performance", "1Y return", NUMERIC,
     SUBSTITUTE, "performance_history.json periods.1Y (account-aggregated)", "100%", "flagged"),
    ("perf_3Y", "Performance", "3Y return", NUMERIC,
     UNAVAILABLE, "none", "0%", "unavailable"),
    ("perf_inception", "Performance", "Inception return (money-weighted CAGR)", NUMERIC,
     IMPLEMENTED, "performance_attribution.json inception_return (money-weighted)", "100%", "ok"),
    ("portfolio_vs_benchmark", "Performance", "Portfolio vs benchmark", NUMERIC,
     IMPLEMENTED, "performance_attribution.json (port_cagr vs bench_cagr, alpha)", "100%", "ok"),
    ("fee_flow_methodology_labels", "Performance", "Fee/flow methodology labels", NON_NUMERIC,
     IMPLEMENTED, "performance_attribution.json note + performance_history.json source tags", "100%", "ok"),
    ("perf_true_TWR", "Performance", "True time-weighted return (TWR)", NUMERIC,
     UNAVAILABLE, "none", "0%", "unavailable"),
    ("money_weighted_CAGR", "Performance", "Money-weighted CAGR / IRR", NUMERIC,
     IMPLEMENTED, "performance_attribution.json port_cagr (money-weighted)", "100%", "ok"),
    # ── Performance attribution ──
    ("attribution_security", "Attribution", "Security-level attribution", NUMERIC,
     SUBSTITUTE, "performance_attribution.json top_gainers/top_losers", "partial", "flagged"),
    ("attribution_sector", "Attribution", "Sector attribution", NUMERIC,
     SUBSTITUTE, "lookthrough_themes.json + fund_lookthrough.json sector_weights", "partial", "flagged"),
    ("attribution_allocation", "Attribution", "Allocation attribution", NUMERIC,
     SUBSTITUTE, "performance_attribution.json (asset-class level)", "partial", "flagged"),
    ("attribution_selection", "Attribution", "Selection attribution", NUMERIC,
     SUBSTITUTE, "performance_attribution.json rolling_alpha", "partial", "flagged"),
    ("realized_vs_unrealized", "Attribution", "Realized vs unrealized", NUMERIC,
     IMPLEMENTED, "tax_lots.json (unrealized) + realized_outcome on watchlist_items", "100%", "ok"),
    ("rolling_alpha", "Attribution", "Rolling alpha", NUMERIC,
     IMPLEMENTED, "performance_attribution.json rolling_alpha", "100%", "ok"),
    ("risk_adjusted_metrics", "Attribution", "Risk-adjusted metrics (Sharpe/Sortino)", NUMERIC,
     IMPLEMENTED, "performance_attribution.json port_sharpe/port_sortino", "100%", "ok"),
    # ── Allocation ──
    ("asset_allocation", "Allocation", "Asset allocation", NUMERIC,
     IMPLEMENTED, "holdings.json buckets (cash/equity/other)", "100%", "ok"),
    ("sector_allocation", "Allocation", "Sector allocation", NUMERIC,
     SUBSTITUTE, "lookthrough_themes.json + fund_lookthrough.json effective_sector_exposure", "partial", "flagged"),
    ("industry_allocation", "Allocation", "Industry allocation", NUMERIC,
     SUBSTITUTE, "ticker_enrichment_cache.json industry (direct-equity only)", "partial", "flagged"),
    # ── Look-through / holdings / concentration ──
    ("lookthrough_holdings_etf_fund", "Look-through", "Look-through holdings (ETF/fund)", NUMERIC,
     IMPLEMENTED, "fund_lookthrough.json top_holdings (30 funds)", "partial", "flagged"),
    ("top_underlying_holdings", "Look-through", "Top underlying holdings", NUMERIC,
     IMPLEMENTED, "lookthrough_themes.json top_underlying", "100%", "ok"),
    ("concentration", "Look-through", "Top-holding concentration", NUMERIC,
     IMPLEMENTED, "holdings.json portfolio_pct (top positions)", "100%", "ok"),
    # ── Style ──
    ("style_value_blend_growth", "Style", "3×3 style box (value/blend/growth)", NUMERIC,
     UNAVAILABLE, "none", "0%", "unavailable"),
    ("market_cap_style_exposure", "Style", "Market-cap / style exposure", NUMERIC,
     SUBSTITUTE, "holdings.json bucket labels (US Large Growth / US Dividend, etc.)", "partial", "flagged"),
    # ── Geographic ──
    ("geographic_exposure", "Geography", "Geographic exposure", NUMERIC,
     SUBSTITUTE, "fund_lookthrough.json fund labels (FID-DIVINTL, etc.)", "partial", "flagged"),
    # ── Valuation ──
    ("valuation_pe", "Valuation", "P/E", NUMERIC,
     SUBSTITUTE, "stock_intelligence.json / ticker_enrichment_cache.json (direct-equity only)", "partial", "flagged"),
    ("valuation_pb", "Valuation", "P/B", NUMERIC,
     SUBSTITUTE, "stock_intelligence.json / ticker_enrichment_cache.json (direct-equity only)", "partial", "flagged"),
    ("valuation_ps", "Valuation", "P/S", NUMERIC,
     SUBSTITUTE, "stock_intelligence.json / ticker_enrichment_cache.json (direct-equity only)", "partial", "flagged"),
    ("valuation_pcf", "Valuation", "P/CF", NUMERIC,
     SUBSTITUTE, "stock_intelligence.json / ticker_enrichment_cache.json (direct-equity only)", "partial", "flagged"),
    ("valuation_forward", "Valuation", "Forward metrics", NUMERIC,
     SUBSTITUTE, "stock_intelligence.json / ticker_enrichment_cache.json (direct-equity only)", "partial", "flagged"),
    ("valuation_coverage_pct", "Valuation", "Valuation coverage percentage", NUMERIC,
     IMPLEMENTED, "portfolio_report_ms analytics.valuation_coverage_pct", "100%", "ok"),
    # ── Factor / beta / correlation / scenario ──
    ("factor_exposure", "Factor", "Factor exposure", NUMERIC,
     SUBSTITUTE, "correlation.json (portfolio-level, if present)", "partial", "flagged"),
    ("beta", "Factor", "Beta", NUMERIC,
     SUBSTITUTE, "performance_attribution.json (benchmark-relative)", "partial", "flagged"),
    ("correlation", "Factor", "Correlation", NUMERIC,
     SUBSTITUTE, "correlation.json", "partial", "flagged"),
    ("scenario_exposure", "Factor", "Scenario exposure", NUMERIC,
     SUBSTITUTE, "defense_analysis / ai_defense_analysis.json (if present)", "partial", "flagged"),
    # ── Risk ──
    ("risk_heat", "Risk", "Risk heat", NUMERIC,
     SUBSTITUTE, "performance_attribution.json (max drawdown / Sharpe)", "100%", "flagged"),
    ("drawdown", "Risk", "Drawdown", NUMERIC,
     IMPLEMENTED, "performance_attribution.json port_maxdd", "100%", "ok"),
    ("volatility", "Risk", "Volatility", NUMERIC,
     IMPLEMENTED, "performance_attribution.json (risk-adjusted metrics)", "100%", "ok"),
    ("concentration_risk", "Risk", "Concentration risk", NUMERIC,
     IMPLEMENTED, "holdings.json portfolio_pct vs concentration_limits", "100%", "ok"),
    ("stress_scenario", "Risk", "Stress / scenario", NUMERIC,
     SUBSTITUTE, "ai_defense_analysis.json (if present)", "partial", "flagged"),
    ("protection_coverage", "Risk", "Protection coverage", NUMERIC,
     SUBSTITUTE, "options_monitor.json / defense posture (if present)", "partial", "flagged"),
    # ── Income ──
    ("dividends_distributions", "Income", "Dividends / distributions", NUMERIC,
     IMPLEMENTED, "income_ledger.json + dividend_calendar.json", "100%", "ok"),
    ("forward_income", "Income", "Forward income", NUMERIC,
     SUBSTITUTE, "dividend_calendar.json (estimated)", "partial", "flagged"),
    ("account_sleeve_contribution", "Income", "Account/sleeve income contribution", NUMERIC,
     SUBSTITUTE, "income_ledger.json by account", "partial", "flagged"),
    ("income_concentration", "Income", "Income concentration", NUMERIC,
     SUBSTITUTE, "income_ledger.json by payer", "partial", "flagged"),
    # ── Tax & lots ──
    ("unrealized_gain_loss", "Tax & lots", "Unrealized gain/loss", NUMERIC,
     IMPLEMENTED, "tax_lots.json + holdings.json cost_basis/gain_loss", "100%", "ok"),
    ("holding_periods", "Tax & lots", "Holding periods (LT/ST)", NUMERIC,
     SUBSTITUTE, "tax_lots.json lot_date (per-lot)", "partial", "flagged"),
    ("tax_per_lot_details", "Tax & lots", "Per-lot details", NUMERIC,
     SUBSTITUTE, "tax_lots.json (137 lots: lot_date, cost_per_share, total_cost)", "partial", "flagged"),
    ("tax_adjusted_basis_quality", "Tax & lots", "Adjusted-basis quality flag", NON_NUMERIC,
     SUBSTITUTE, "holdings.json basis_partial / _basis_ln_flagged", "100%", "flagged"),
    ("wash_sale_account_constraints", "Tax & lots", "Wash-sale / account constraints (advisory)", NON_NUMERIC,
     IMPLEMENTED, "cio_capital_plan tax_class + account constraints", "100%", "ok"),
    # ── Closed / realized ──
    ("closed_positions_realized_summary", "Realized", "Closed positions / realized outcome summary", NUMERIC,
     IMPLEMENTED, "redeploy_capital_book.build_history + realized_outcome", "100%", "ok"),
    # ── Re-entry / watch / rotation / defense ──
    ("reentry_book", "Opportunities", "Re-entry book", NON_NUMERIC,
     IMPLEMENTED, "reentry_decision_desk_latest.json + reentry staging", "100%", "ok"),
    ("watch_opportunity_book", "Opportunities", "Watch / opportunity book", NON_NUMERIC,
     IMPLEMENTED, "cio_opportunity_queue + watchlist_items", "100%", "ok"),
    ("rotation_defense_posture", "Opportunities", "Rotation / Defense posture", NON_NUMERIC,
     IMPLEMENTED, "cio_sector_opportunity + rotation_ladders.json", "100%", "ok"),
    # ── Decision history ──
    ("decision_history_dispositions", "Decisions", "Decision history / operator dispositions", NON_NUMERIC,
     IMPLEMENTED, "cio_action_ledger.jsonl + cio_outcome_store dispositions", "100%", "ok"),
    # ── Methodology & disclosures ──
    ("data_quality_methodology", "Methodology", "Data-quality and methodology appendix", NON_NUMERIC,
     IMPLEMENTED, "this report's coverage matrix + quality_flags", "100%", "ok"),
    ("disclosures_advisory_only", "Disclosures", "Disclosures / advisory-only statement", NON_NUMERIC,
     IMPLEMENTED, "authority constitution (READ_ONLY_ADVISORY)", "100%", "ok"),
)


def report_fields() -> list[dict[str, Any]]:
    """The canonical field list with gap resolutions applied (deterministic)."""
    gap_by_field: dict[str, str] = {}
    for g in KNOWN_GAPS:
        for fid in g["field_ids"]:
            gap_by_field[fid] = g["resolution"]

    rows: list[dict[str, Any]] = []
    for fid, section, label, kind, default_status, source, coverage, quality in _FIELDS:
        rows.append({
            "field_id": fid,
            "section": section,
            "label": label,
            "kind": kind,
            "status": gap_by_field.get(fid, default_status),
            "source": source,
            "coverage": coverage,
            "quality": quality,
        })
    return rows


def build_coverage_matrix(fields: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Aggregate the field list into the Checkpoint 7 coverage matrix.

    `source_traceability_pct` = reported numerical fields that carry a source,
    as a percentage of reported numerical fields (unavailable fields are not
    reported, so they do not dilute traceability).
    """
    fields = fields if fields is not None else report_fields()
    by_status = {IMPLEMENTED: 0, UNAVAILABLE: 0, SUBSTITUTE: 0}
    numeric_total = 0
    numeric_reported = 0
    numeric_with_source = 0
    for f in fields:
        by_status[f["status"]] = by_status.get(f["status"], 0) + 1
        if f["kind"] == NUMERIC:
            numeric_total += 1
            if f["status"] != UNAVAILABLE:
                numeric_reported += 1
                if f.get("source") and f["source"] != "none":
                    numeric_with_source += 1

    traceability = round(numeric_with_source / numeric_reported * 100.0, 2) \
        if numeric_reported > 0 else 100.0

    return {
        "field_count": len(fields),
        "numeric_field_count": numeric_total,
        "numeric_reported_count": numeric_reported,
        "by_status": by_status,
        "fields_present": [f["field_id"] for f in fields if f["status"] == IMPLEMENTED],
        "fields_improved_vs_reference": [
            f["field_id"] for f in fields if f["field_id"] in IMPROVED_VS_REFERENCE
        ],
        "fields_unavailable": [f["field_id"] for f in fields if f["status"] == UNAVAILABLE],
        "source_traceability_pct": traceability,
        "quality_flags": [f["field_id"] for f in fields if f["quality"] == "flagged"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Part A — CIO Investment Committee front matter (pure composition)
# ─────────────────────────────────────────────────────────────────────────────

def build_part_a(
    *,
    thesis: Optional[dict[str, Any]] = None,
    capital_plan: Optional[dict[str, Any]] = None,
    sector_opportunities: Optional[list[dict[str, Any]]] = None,
    opportunity_queue: Optional[dict[str, Any]] = None,
    performance_attribution: Optional[dict[str, Any]] = None,
    performance: Optional[dict[str, Any]] = None,
    dispositions: Optional[list[dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build the Part A front matter from canonical CIO state (all fail-soft)."""
    now = now or datetime.now(timezone.utc)
    thesis = thesis or {}
    cap = capital_plan or {}
    attr = performance_attribution or {}
    perf = performance or {}
    queue = opportunity_queue or {}
    dispositions = dispositions or []

    # 1. CIO Letter
    letter = {
        "thesis_summary": (thesis.get("summary") or "").strip() or None,
        "stance": (thesis.get("stance") or "").strip() or None,
        "bullets": list(thesis.get("bullets") or [])[:5],
        "risk_posture": (thesis.get("risk_posture") or "").strip() or None,
        "what_changed": _what_changed(thesis),
        "priorities": _priorities(cap, queue, sector_opportunities),
        "what_not_to_do": _what_not_to_do(thesis, attr),
    }

    # 2. Decisions Now
    decisions = _decisions_now(cap)

    # 3. Capital Plan (pass-through projection — Phase 2 earmark fields included)
    capital = {
        "cash_total_usd": cap.get("cash_total_usd"),
        "cash_reserved_usd": cap.get("cash_reserved_usd"),
        "cash_investable_usd": cap.get("cash_investable_usd"),
        "cash_earmarked_redeploy_usd": cap.get("cash_earmarked_redeploy_usd"),
        "cash_free_unearmarked_usd": cap.get("cash_free_unearmarked_usd"),
        "cash_policy_band": cap.get("cash_policy_band"),
        "recommended_deploy_usd": cap.get("net_recommended_deploy_usd"),
        "recommended_raise_usd": cap.get("net_recommended_raise_usd"),
        "deployable_usd": cap.get("deployable_usd"),
        "sources": _compact_sources(cap.get("capital_sources")),
        "uses": _compact_uses(cap.get("capital_uses")),
        "post_plan_cash_usd": cap.get("post_plan_cash_usd"),
        "post_plan_cash_pct": cap.get("post_plan_cash_pct"),
        "portfolio_value_usd": cap.get("portfolio_value_usd"),
        "plan_version": cap.get("plan_version"),
    }
    # 4. Portfolio Posture
    posture = _portfolio_posture(cap, attr, sector_opportunities, thesis, perf)

    # 5. Opportunity Funnel
    funnel = _opportunity_funnel(queue, sector_opportunities, dispositions)

    # 6. Counter-Thesis / Risks
    risks = _counter_thesis(thesis, attr, cap, sector_opportunities)

    return {
        "computed_at": _now_iso(now),
        "letter": letter,
        "decisions_now": decisions,
        "capital_plan": capital,
        "portfolio_posture": posture,
        "opportunity_funnel": funnel,
        "counter_thesis_risks": risks,
    }


def _what_changed(thesis: dict[str, Any]) -> list[dict[str, Any]]:
    log = thesis.get("learning_log") or []
    out = []
    for entry in log[-5:]:
        if not isinstance(entry, dict):
            continue
        out.append({
            "kind": entry.get("kind") or entry.get("ts"),
            "note": str(entry.get("note") or entry.get("summary") or entry.get("message") or "")[:200],
        })
    if not out and thesis.get("last_reviewed"):
        out.append({"kind": "last_reviewed", "note": str(thesis.get("last_reviewed"))})
    return out


def _priorities(cap: dict[str, Any], queue: dict[str, Any],
                sectors: Optional[list[dict[str, Any]]]) -> list[str]:
    pri: list[str] = []
    deploy = cap.get("net_recommended_deploy_usd") or 0
    if deploy > 0:
        pri.append(f"deploy up to ${float(deploy):,.0f} against explicit desk signals")
    try:
        from scripts.lib.cio_decision_semantics import (
            filter_sector_opportunities, professional_label, stance_from_queue_item,
            professional_stance, is_pseudo_sector,
        )
        clean = filter_sector_opportunities(sectors, require_canonical_gics=True)
        for opp in clean[:2]:
            if opp.get("opportunity"):
                pri.append(
                    f"watch {opp.get('sector')} ({opp.get('state_display') or professional_label(opp.get('state'))}): "
                    f"{opp.get('recommendation')}"
                )
        top = (queue.get("top") or (queue.get("items") or []))[:3]
        for it in top:
            st = professional_stance(stance_from_queue_item(it))
            pri.append(f"evaluate {it.get('symbol')} ({st})")
    except Exception:
        for opp in (sectors or [])[:2]:
            if opp.get("opportunity") and not str(opp.get("sector") or "").startswith("Iwm"):
                pri.append(
                    f"watch {opp.get('sector')} ({opp.get('state')}): {opp.get('recommendation')}"
                )
        top = (queue.get("top") or (queue.get("items") or []))[:3]
        for it in top:
            pri.append(
                f"evaluate {it.get('symbol')} ({it.get('verdict') or it.get('state') or 'signal'})"
            )
    if not pri:
        pri.append("preserve dry powder; no forced deployment without a desk signal")
    return pri[:5]


def _sector_posture_rows(sectors: Optional[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    try:
        from scripts.lib.cio_decision_semantics import filter_sector_opportunities
        clean = filter_sector_opportunities(sectors, require_canonical_gics=True)
        return [
            {
                "sector": o.get("sector"),
                "state": o.get("state_display") or o.get("state"),
                "state_code": o.get("state_code") or o.get("state"),
                "exposure_pct": o.get("current_exposure_pct") or o.get("exposure_pct"),
                "target_pct": o.get("target_posture_pct") or o.get("target_pct"),
                "recommendation": o.get("recommendation"),
                "recommendation_code": o.get("recommendation_code"),
            }
            for o in clean
        ][:6]
    except Exception:
        return [
            {
                "sector": o.get("sector"),
                "state": o.get("state"),
                "exposure_pct": o.get("current_exposure_pct"),
                "target_pct": o.get("target_posture_pct"),
                "recommendation": o.get("recommendation"),
            }
            for o in (sectors or [])
            if "−" not in str(o.get("sector") or "") and "-" not in str(o.get("sector") or "")
        ][:6]


def _sector_opportunity_rows(sectors: Optional[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    try:
        from scripts.lib.cio_decision_semantics import filter_sector_opportunities
        clean = filter_sector_opportunities(
            [o for o in (sectors or []) if o.get("opportunity")],
            require_canonical_gics=True,
        )
        return [
            {
                "sector": o.get("sector"),
                "state": o.get("state_display") or o.get("state"),
                "recommendation": o.get("recommendation"),
            }
            for o in clean
        ][:6]
    except Exception:
        return [
            {"sector": o.get("sector"), "state": o.get("state"),
             "recommendation": o.get("recommendation")}
            for o in (sectors or [])
            if o.get("opportunity") and "−" not in str(o.get("sector") or "")
        ][:6]

def _what_not_to_do(thesis: dict[str, Any], attr: dict[str, Any]) -> list[str]:
    out = list(thesis.get("escalation_rules") or [])[:4]
    if not out:
        out.append("do not chase a non-improving sector or a single-source trickle")
        out.append("do not force-deploy cash merely because it exists")
    out.append("no broker/order/stop authority — advisory only")
    return out


def _decisions_now(cap: dict[str, Any]) -> list[dict[str, Any]]:
    """Phase 3: aggregate, resolve HOLD+TRIM, professional stance labels."""
    try:
        from scripts.lib.cio_decision_semantics import sanitize_decisions_now
        return sanitize_decisions_now(
            cap.get("position_decisions") or [],
            portfolio_value=float(cap.get("portfolio_value_usd") or 0.0),
            limit=8,
        )
    except Exception:
        pass
    decisions = []
    neutral = "no new desk signal; hold"
    for d in (cap.get("position_decisions") or []):
        why = d.get("why_now") or ""
        risk = d.get("risk") or ""
        delta = d.get("recommended_delta_usd")
        has_delta = bool(delta)
        has_signal = bool(why) and neutral not in why
        has_breach = "concentration >" in risk.lower() or "breach" in risk.lower()
        if has_delta or has_signal or has_breach:
            decisions.append({
                "symbol": d.get("symbol"),
                "stance": d.get("stance") or d.get("cio_stance"),
                "current_value_usd": d.get("current_value_usd"),
                "current_weight_pct": d.get("current_weight_pct"),
                "recommended_delta_usd": delta,
                "why_now": why,
                "risk": risk,
                "next_review": d.get("next_review"),
            })
    decisions.sort(key=lambda d: (-1 if "concentration >" in (d.get("risk") or "").lower()
                                   else 0, -abs(d.get("recommended_delta_usd") or 0)))
    return decisions[:8]

def _compact_sources(sources: Optional[dict[str, Any]]) -> dict[str, Any]:
    s = sources or {}
    return {
        "trims_usd": s.get("trims_usd"),
        "exits_usd": s.get("exits_usd"),
        "maturities_usd": s.get("maturities_usd"),
        "earmarked_redeploy_usd": s.get("earmarked_redeploy_usd") or s.get("maturities_usd"),
        "total_prospective_raise_usd": s.get("total_prospective_raise_usd"),
        "total_raise_usd": s.get("total_raise_usd"),
        "double_count_guard": s.get("double_count_guard"),
    }

def _compact_uses(uses: Optional[dict[str, Any]]) -> dict[str, Any]:
    u = uses or {}
    return {
        "adds_usd": u.get("adds_usd"),
        "new_positions_usd": u.get("new_positions_usd"),
        "reentry_usd": u.get("reentry_usd"),
        "sector_rotation_usd": u.get("sector_rotation_usd"),
        "reserve_usd": u.get("reserve"),
        "total_deploy_request_usd": u.get("total_deploy_request_usd"),
    }


def _portfolio_posture(
    cap: dict[str, Any],
    attr: dict[str, Any],
    sectors: Optional[list[dict[str, Any]]],
    thesis: dict[str, Any],
    perf: dict[str, Any],
) -> dict[str, Any]:
    top = None
    for d in (cap.get("position_decisions") or []):
        w = d.get("current_weight_pct")
        if top is None or (w is not None and w > top["current_weight_pct"]):
            top = d
    return {
        "thesis_stance": thesis.get("stance") or None,
        "top_position": {
            "symbol": top.get("symbol") if top else None,
            "weight_pct": top.get("current_weight_pct") if top else None,
        } if top else None,
        "concentration_fire_pct": _num(cap.get("portfolio_constraints") and
                                       _constraint_value(cap, "concentration_fire_pct")),
        "risk_heat": {
            "max_drawdown_pct": attr.get("port_maxdd"),
            "sharpe": attr.get("port_sharpe"),
            "sortino": attr.get("port_sortino"),
        },
        "sector_posture": _sector_posture_rows(sectors),
        "benchmark_posture": {
            "label": attr.get("benchmark_label"),
            "port_cagr": attr.get("port_cagr"),
            "bench_cagr": attr.get("bench_cagr"),
            "alpha_annualized": attr.get("alpha_annualized"),
        },
        "defensive_offensive_stance": _defensive_stance(thesis, cap),
        "performance": {
            "periods": perf.get("periods") or perf.get("period_returns") or {},
        },
    }


def _constraint_value(cap: dict[str, Any], kind: str) -> Optional[float]:
    for c in (cap.get("portfolio_constraints") or []):
        if isinstance(c, dict) and c.get("kind") == kind:
            return c.get("value")
    return None


def _defensive_stance(thesis: dict[str, Any], cap: dict[str, Any]) -> str:
    stance = str(thesis.get("stance") or "").lower()
    if "defensive" in stance:
        return "defensive"
    if "offensive" in stance or "risk-on" in stance:
        return "offensive"
    status = cap.get("cash_posture_status")
    if status == "ABOVE_BAND":
        return "neutral (cash above policy floor)"
    if status == "BELOW_BAND":
        return "defensive (cash below policy floor)"
    return "neutral"


def _opportunity_funnel(
    queue: dict[str, Any],
    sectors: Optional[list[dict[str, Any]]],
    dispositions: list[dict[str, Any]],
) -> dict[str, Any]:
    items = queue.get("items") or queue.get("top") or []
    adds = [it for it in items if (it.get("verdict") or "") in ("ADD", "RE_ENTER")]
    reentry = [it for it in items if (it.get("state") or "") or (it.get("verdict") or "") == "RE_ENTER"]
    research_gaps = []
    for opp in (sectors or []):
        for c in opp.get("candidates") or []:
            if c.get("readiness") == "NEEDS_RESEARCH":
                research_gaps.append({"symbol": c.get("symbol"), "sector": opp.get("sector")})
    return {
        "watch_additions": [
            {"symbol": it.get("symbol"), "verdict": it.get("verdict"),
             "source": it.get("source"), "label": it.get("directive_label")}
            for it in adds[:8]
        ],
        "reentry_candidates": [
            {"symbol": it.get("symbol"), "state": it.get("state"),
             "source": it.get("source"), "label": it.get("directive_label")}
            for it in reentry[:8]
        ],
        "sector_opportunities": _sector_opportunity_rows(sectors),
        "research_gaps": research_gaps[:8],
        "prior_recommendation_status": [
            {
                "disposition": d.get("disposition") or d.get("status"),
                "ts": d.get("ts") or d.get("occurred_at"),
            }
            for d in dispositions[-5:]
        ],
    }


def _counter_thesis(
    thesis: dict[str, Any],
    attr: dict[str, Any],
    cap: dict[str, Any],
    sectors: Optional[list[dict[str, Any]]],
) -> dict[str, Any]:
    disagreements = []
    for d in (cap.get("position_decisions") or []):
        if d.get("counter_thesis") and "no Street/desk disagreement" not in str(d.get("counter_thesis")):
            disagreements.append({"symbol": d.get("symbol"), "counter_thesis": d.get("counter_thesis")})
    unknowns = []
    if attr.get("port_maxdd") is not None and float(attr["port_maxdd"]) < -20:
        unknowns.append("drawdown exceeds -20% — tail-risk scenario sensitivity is unresolved")
    for g in KNOWN_GAPS:
        if g["resolution"] == UNAVAILABLE:
            unknowns.append(g["title"])
    return {
        "where_alex_may_be_wrong": list(thesis.get("escalation_rules") or [])[:4],
        "guardian_hermes_disagreements": disagreements[:5],
        "highest_impact_unknowns": unknowns[:6],
    }


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Manifest (immutable) + Checkpoint 7
# ─────────────────────────────────────────────────────────────────────────────

def build_manifest(
    *,
    inputs: dict[str, Any],
    coverage: dict[str, Any],
    source_sha: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Immutable report manifest: input hashes + source SHA + field counts.

    `inputs` maps a canonical input name to (bytes | str | dict). Each is hashed
    deterministically; a name with a non-hashable payload is recorded as
    `provenance: "not_hashed"` rather than fabricating a hash.
    """
    now = now or datetime.now(timezone.utc)
    input_hashes: dict[str, Any] = {}
    for name, payload in sorted(inputs.items()):
        try:
            if isinstance(payload, bytes):
                input_hashes[name] = _sha256_bytes(payload)
            elif isinstance(payload, str):
                input_hashes[name] = _sha256_bytes(payload.encode("utf-8"))
            elif isinstance(payload, (dict, list)):
                input_hashes[name] = _sha256_bytes(
                    json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
                )
            else:
                input_hashes[name] = "not_hashed"
        except Exception:
            input_hashes[name] = "not_hashed"

    manifest = {
        "report_version": REPORT_VERSION,
        "generated_at": _now_iso(now),
        "authority": "READ_ONLY_ADVISORY",
        "source_sha": source_sha,
        "input_hashes": input_hashes,
        "coverage": {
            "field_count": coverage.get("field_count"),
            "by_status": coverage.get("by_status"),
            "source_traceability_pct": coverage.get("source_traceability_pct"),
        },
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, default=str).encode("utf-8")
    manifest["manifest_hash"] = _sha256_bytes(manifest_bytes)
    return manifest


def build_checkpoint(
    *,
    coverage: dict[str, Any],
    quality_flags: list[str],
    pdf_pages: Optional[int] = None,
    render_errors: Optional[list[str]] = None,
) -> dict[str, Any]:
    """The exact Checkpoint 7 return shape."""
    return {
        "fields_present": coverage.get("fields_present", []),
        "fields_improved_vs_reference": coverage.get("fields_improved_vs_reference", []),
        "fields_unavailable": coverage.get("fields_unavailable", []),
        "quality_flags": quality_flags,
        "pdf_pages": pdf_pages,
        "render_errors": render_errors or [],
        "source_traceability_pct": coverage.get("source_traceability_pct"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# HTML render (institutional, print-perfect, no raw JSON)
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
:root { --navy:#1F3864; --navy-dark:#16294D; --ink:#1A1A1A; --muted:#555555;
        --line:#D5DAE1; --panel:#F4F6F9; --green:#2E7D32; --red:#8B1A1A;
        --amber:#B8860B; }
* { box-sizing:border-box; }
body { font-family:"Source Sans Pro","Segoe UI",Helvetica,Arial,sans-serif;
       color:var(--ink); margin:0; line-height:1.45; font-size:12.5px;
       -webkit-print-color-adjust:exact; print-color-adjust:exact; }
h1,h2,h3 { color:var(--navy); font-weight:600; margin:0 0 .4rem; }
h1 { font-size:1.7rem; letter-spacing:.2px; }
h2 { font-size:1.15rem; border-bottom:2px solid var(--navy); padding-bottom:.25rem;
     margin-top:1.6rem; page-break-after:avoid; }
h3 { font-size:1rem; }
.section { margin-bottom:1.2rem; page-break-inside:avoid; }
.lede { color:var(--muted); font-size:.85rem; margin:.2rem 0 .8rem; }
.meta { display:flex; flex-wrap:wrap; gap:.5rem; font-size:.78rem; color:var(--muted);
        border-bottom:1px solid var(--line); padding-bottom:.4rem; margin-bottom:.8rem; }
.meta span { background:var(--panel); padding:.15rem .45rem; border-radius:3px; }
table { width:100%; border-collapse:collapse; font-size:.82rem; margin:.4rem 0 .8rem; }
th { text-align:left; background:var(--navy); color:#fff; padding:.35rem .5rem;
     font-weight:600; }
td { padding:.3rem .5rem; border-bottom:1px solid var(--line); vertical-align:top; }
tr:nth-child(even) td { background:var(--panel); }
.num { text-align:right; font-variant-numeric:tabular-nums; }
.pos { color:var(--green); } .neg { color:var(--red); }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:.6rem; }
.box { background:var(--panel); border:1px solid var(--line); border-radius:5px;
       padding:.55rem .7rem; }
.box .k { font-size:.72rem; color:var(--muted); text-transform:uppercase; letter-spacing:.4px; }
.box .v { font-size:1.15rem; font-weight:600; color:var(--navy); }
.badge { display:inline-block; font-size:.68rem; padding:.08rem .4rem; border-radius:999px;
         font-weight:600; letter-spacing:.3px; }
.badge.ok { background:#E6F4EA; color:var(--green); }
.badge.flag { background:#FDF3E0; color:var(--amber); }
.badge.unavail { background:#FBEAEA; color:var(--red); }
.badge.sub { background:#EEF1F6; color:var(--navy); }
.footnote { font-size:.72rem; color:var(--muted); font-style:italic; margin:.1rem 0 .7rem; }
.page { display:none; }
@page { size:letter; margin:1.6cm 1.4cm; @bottom-center { content:"Trade AI — Institutional Report v2  ·  page " counter(page) " of " counter(pages); font-size:8pt; color:#555; } }
@media print { .page { display:block; } body { font-size:11px; } .no-print { display:none; } }
"""

_STATUS_BADGE = {
    IMPLEMENTED: ('ok', "source proof"),
    SUBSTITUTE: ('sub', "methodology substitute"),
    UNAVAILABLE: ('unavail', "unavailable"),
}


def _e(v: Any) -> str:
    """HTML-escape a value."""
    return str(v if v is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_usd(v: Any) -> str:
    n = _num(v)
    if n is None:
        return "—"
    return f"${n:,.0f}"


def _fmt_pct(v: Any, signed: bool = False) -> str:
    n = _num(v)
    if n is None:
        return "—"
    return f"{n:+,.2f}%" if signed else f"{n:,.2f}%"


def render_html(model: dict[str, Any]) -> str:
    """Render the full v2 report (Part A + Part B) to self-contained HTML.

    Phase 4: prefers the shared view layer (`cio_report_render.render_html_from_view`)
    so HTML / DOCX / PDF never diverge on facts. Falls back to the legacy inline
    renderer only if the view package is unavailable.
    """
    try:
        from scripts.lib.cio_report_render import render_html_from_view
        from scripts.lib.cio_report_view import build_report_view
        view = model.get("view") if isinstance(model.get("view"), dict) else build_report_view(model)
        return render_html_from_view(view)
    except Exception:
        pass
    a = model.get("part_a") or {}
    b = model.get("part_b") or {}
    coverage = model.get("coverage") or {}
    manifest = model.get("manifest") or {}
    checkpoint = model.get("checkpoint") or {}
    as_of = model.get("as_of") or ""
    sections: list[str] = []
    sections.append(f"<h1>Trade AI — Institutional Report v2</h1>")
    sections.append(
        f"<div class='lede'>Private investment office · CIO advisory · "
        f"READ_ONLY_ADVISORY — no execution authority</div>"
    )
    sections.append(
        f"<div class='meta'><span>as_of {_e(as_of)}</span>"
        f"<span>source SHA {_e(manifest.get('source_sha') or '—')}</span>"
        f"<span>manifest {_e(str(manifest.get('manifest_hash') or '')[:12])}…</span>"
        f"<span>traceability {_e(coverage.get('source_traceability_pct'))}%</span></div>"
    )

    # ── Part A ──
    sections.append("<h2>Part A — CIO Investment Committee</h2>")

    letter = a.get("letter") or {}
    sections.append("<div class='section'><h3>CIO Letter / Executive Summary</h3>")
    if letter.get("thesis_summary"):
        sections.append(f"<p>{_e(letter['thesis_summary'])}</p>")
    if letter.get("stance"):
        sections.append(f"<p><strong>Stance:</strong> {_e(letter['stance'])}</p>")
    if letter.get("priorities"):
        sections.append("<p><strong>Priorities:</strong></p><ul>")
        for p in letter["priorities"]:
            sections.append(f"<li>{_e(p)}</li>")
        sections.append("</ul>")
    if letter.get("what_not_to_do"):
        sections.append("<p><strong>What not to do:</strong></p><ul>")
        for p in letter["what_not_to_do"]:
            sections.append(f"<li>{_e(p)}</li>")
        sections.append("</ul>")
    sections.append("</div>")

    decisions = a.get("decisions_now") or []
    sections.append("<div class='section'><h3>Decisions Now</h3>")
    if decisions:
        sections.append(
            "<table><thead><tr><th>Symbol</th><th>Stance</th><th class='num'>Weight</th>"
            "<th class='num'>Value</th><th class='num'>Δ $</th><th>Why now</th><th>Risk</th></tr></thead><tbody>"
        )
        for d in decisions:
            cls = "pos" if (d.get("recommended_delta_usd") or 0) > 0 else "neg"
            sections.append(
                f"<tr><td>{_e(d.get('symbol'))}</td><td>{_e(d.get('stance'))}</td>"
                f"<td class='num'>{_fmt_pct(d.get('current_weight_pct'))}</td>"
                f"<td class='num'>{_fmt_usd(d.get('current_value_usd'))}</td>"
                f"<td class='num {cls}'>{_fmt_usd(d.get('recommended_delta_usd'))}</td>"
                f"<td>{_e(d.get('why_now'))}</td><td>{_e(d.get('risk'))}</td></tr>"
            )
        sections.append("</tbody></table>")
    else:
        sections.append("<p class='lede'>No material position decisions at this time.</p>")
    sections.append("</div>")

    cap = a.get("capital_plan") or {}
    sections.append("<div class='section'><h3>Capital Plan</h3><div class='grid'>")
    for k, label in (
        ("cash_total_usd", "Total cash"), ("cash_reserved_usd", "Reserved"),
        ("cash_investable_usd", "Investable"), ("recommended_deploy_usd", "Recommended deploy"),
        ("recommended_raise_usd", "Recommended raise"), ("post_plan_cash_usd", "Post-plan cash"),
    ):
        v = _fmt_usd(cap.get(k)) if k != "recommended_raise_usd" else _fmt_usd(cap.get(k))
        sections.append(f"<div class='box'><div class='k'>{label}</div><div class='v'>{v}</div></div>")
    sections.append("</div>")
    if cap.get("post_plan_cash_pct") is not None:
        sections.append(f"<div class='footnote'>Post-plan cash {_fmt_pct(cap.get('post_plan_cash_pct'))} of portfolio.</div>")
    sections.append("</div>")

    posture = a.get("portfolio_posture") or {}
    sections.append("<div class='section'><h3>Portfolio Posture</h3><div class='grid'>")
    rh = posture.get("risk_heat") or {}
    for k, label in (
        ("max_drawdown_pct", "Max drawdown"), ("sharpe", "Sharpe"), ("sortino", "Sortino"),
    ):
        v = _fmt_pct(rh.get(k)) if k == "max_drawdown_pct" else f"{_num(rh.get(k)):.2f}" if _num(rh.get(k)) is not None else "—"
        sections.append(f"<div class='box'><div class='k'>{label}</div><div class='v'>{v}</div></div>")
    bp = posture.get("benchmark_posture") or {}
    sections.append(f"<div class='box'><div class='k'>Benchmark</div><div class='v' style='font-size:.9rem'>{_e(bp.get('label') or '—')}</div></div>")
    sections.append(f"<div class='box'><div class='k'>Portfolio CAGR</div><div class='v'>{_fmt_pct(bp.get('port_cagr'))}</div></div>")
    sections.append(f"<div class='box'><div class='k'>Alpha (ann.)</div><div class='v'>{_fmt_pct(bp.get('alpha_annualized'), signed=True)}</div></div>")
    sections.append(f"<div class='box'><div class='k'>Stance</div><div class='v' style='font-size:.85rem'>{_e(posture.get('defensive_offensive_stance') or '—')}</div></div>")
    sections.append("</div>")
    sectors = posture.get("sector_posture") or []
    if sectors:
        sections.append("<table><thead><tr><th>Sector</th><th>State</th><th class='num'>Exposure</th><th class='num'>Target</th><th>Recommendation</th></tr></thead><tbody>")
        for s in sectors:
            sections.append(
                f"<tr><td>{_e(s.get('sector'))}</td><td>{_e(s.get('state'))}</td>"
                f"<td class='num'>{_fmt_pct(s.get('exposure_pct'))}</td>"
                f"<td class='num'>{_fmt_pct(s.get('target_pct'))}</td>"
                f"<td>{_e(s.get('recommendation'))}</td></tr>"
            )
        sections.append("</tbody></table>")
    sections.append("</div>")

    funnel = a.get("opportunity_funnel") or {}
    sections.append("<div class='section'><h3>Opportunity Funnel</h3>")
    for key, title in (
        ("watch_additions", "Watch additions"), ("reentry_candidates", "Re-entry candidates"),
        ("sector_opportunities", "Sector opportunities"), ("research_gaps", "Research gaps"),
    ):
        rows = funnel.get(key) or []
        if rows:
            sections.append(f"<p><strong>{title}:</strong> {_e(', '.join(r.get('symbol') or r.get('sector') or '' for r in rows))}</p>")
    sections.append("</div>")

    risks = a.get("counter_thesis_risks") or {}
    sections.append("<div class='section'><h3>Counter-Thesis / Risks</h3>")
    if risks.get("highest_impact_unknowns"):
        sections.append("<ul>")
        for u in risks["highest_impact_unknowns"]:
            sections.append(f"<li>{_e(u)}</li>")
        sections.append("</ul>")
    if risks.get("guardian_hermes_disagreements"):
        sections.append("<ul>")
        for d in risks["guardian_hermes_disagreements"]:
            sections.append(f"<li>{_e(d.get('symbol'))}: {_e(d.get('counter_thesis'))}</li>")
        sections.append("</ul>")
    sections.append("</div>")

    # ── Part B ──
    sections.append("<h2>Part B — Institutional Portfolio Book</h2>")
    portfolio = b.get("portfolio") or {}
    sections.append("<div class='grid'>")
    for k, label in (
        ("total_value", "Household total"), ("cash_value", "Cash"),
        ("positions_count", "Positions"),
    ):
        sections.append(f"<div class='box'><div class='k'>{label}</div><div class='v'>{_fmt_usd(portfolio.get(k)) if k != 'positions_count' else _e(portfolio.get(k))}</div></div>")
    sections.append("</div>")

    accounts = b.get("accounts") or []
    if accounts:
        sections.append("<div class='section'><h3>Accounts</h3>")
        sections.append("<table><thead><tr><th>Account</th><th>Broker</th><th class='num'>Value</th><th class='num'>Weight</th><th class='num'>Gain/Loss</th></tr></thead><tbody>")
        for acct in accounts:
            sections.append(
                f"<tr><td>{_e(acct.get('display_name'))}</td><td>{_e(acct.get('broker'))}</td>"
                f"<td class='num'>{_fmt_usd(acct.get('total_value'))}</td>"
                f"<td class='num'>{_fmt_pct(acct.get('weight_pct'))}</td>"
                f"<td class='num'>{_fmt_usd(acct.get('gain_loss'))}</td></tr>"
            )
        sections.append("</tbody></table></div>")

    perf = b.get("performance") or {}
    periods = perf.get("periods") or perf.get("period_returns") or {}
    if periods:
        sections.append("<div class='section'><h3>Performance</h3>")
        sections.append("<table><thead><tr><th>Period</th><th class='num'>Change</th><th class='num'>Change %</th><th>Source</th></tr></thead><tbody>")
        for pname, p in periods.items():
            if not isinstance(p, dict):
                continue
            src = p.get("source") or "—"
            flag = "<span class='badge flag'>flagged</span>" if src == "account-aggregated" else ""
            sections.append(
                f"<tr><td>{_e(pname)}</td><td class='num'>{_fmt_usd(p.get('change'))}</td>"
                f"<td class='num'>{_fmt_pct(p.get('change_pct'), signed=True)}</td>"
                f"<td>{_e(src)} {flag}</td></tr>"
            )
        sections.append("</tbody></table></div>")

    bench = b.get("benchmark") or {}
    if bench.get("label"):
        sections.append(
            f"<div class='section'><h3>Portfolio vs Benchmark</h3><div class='grid'>"
            f"<div class='box'><div class='k'>Benchmark</div><div class='v' style='font-size:.8rem'>{_e(bench.get('label'))}</div></div>"
            f"<div class='box'><div class='k'>Portfolio CAGR</div><div class='v'>{_fmt_pct(bench.get('cagr'))}</div></div>"
            f"<div class='box'><div class='k'>Benchmark 3Y</div><div class='v'>{_fmt_pct(bench.get('3yr'))}</div></div>"
            f"</div></div>"
        )

    unreal = b.get("unrealized") or {}
    sections.append(
        f"<div class='section'><h3>Unrealized Gain / Loss</h3><div class='grid'>"
        f"<div class='box'><div class='k'>Long-term</div><div class='v'>{_fmt_usd(unreal.get('lt_unrealized'))}</div></div>"
        f"<div class='box'><div class='k'>Short-term</div><div class='v'>{_fmt_usd(unreal.get('st_unrealized'))}</div></div>"
        f"<div class='box'><div class='k'>Positions</div><div class='v'>{_e(unreal.get('count'))}</div></div>"
        f"</div></div>"
    )

    # ── Coverage matrix ──
    sections.append("<h2>Field-Coverage Matrix</h2>")
    fields = model.get("fields") or []
    sections.append("<table><thead><tr><th>Field</th><th>Section</th><th>Status</th><th>Source</th><th class='num'>Coverage</th></tr></thead><tbody>")
    for f in fields:
        badge_cls, badge_txt = _STATUS_BADGE.get(f.get("status"), ("unavail", "?"))
        sections.append(
            f"<tr><td>{_e(f.get('label'))}</td><td>{_e(f.get('section'))}</td>"
            f"<td><span class='badge {badge_cls}'>{badge_txt}</span></td>"
            f"<td>{_e(f.get('source'))}</td><td class='num'>{_e(f.get('coverage'))}</td></tr>"
        )
    sections.append("</tbody></table>")

    # ── Known-gap resolutions ──
    sections.append("<h2>Known-Gap Resolutions</h2>")
    sections.append("<table><thead><tr><th>Gap</th><th>Resolution</th><th>Note</th></tr></thead><tbody>")
    for g in KNOWN_GAPS:
        badge_cls, badge_txt = _STATUS_BADGE.get(g["resolution"], ("unavail", "?"))
        sections.append(
            f"<tr><td>{_e(g.get('title'))}</td>"
            f"<td><span class='badge {badge_cls}'>{badge_txt}</span></td>"
            f"<td>{_e(g.get('note'))}</td></tr>"
        )
    sections.append("</tbody></table>")

    # ── Quality flags + disclosures ──
    sections.append("<h2>Quality Flags & Disclosures</h2>")
    qflags = model.get("quality_flags") or checkpoint.get("quality_flags") or []
    for qf in qflags:
        sections.append(f"<div class='footnote'>⚠ {_e(qf)}</div>")
    sections.append(
        "<div class='footnote'>This report is generated by Trade AI and is "
        "READ_ONLY_ADVISORY. It does not constitute an order, a solicitation, or "
        "broker authority of any kind. No execution is performed.</div>"
    )

    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>Trade AI — Institutional Report v2</title>"
        f"<style>{_CSS}</style></head><body>"
        + "\n".join(sections)
        + "</body></html>"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Live builder (injectable loaders; separated from pure logic)
# ─────────────────────────────────────────────────────────────────────────────

def build_report_v2(
    *,
    part_b_ctx: Optional[dict[str, Any]] = None,
    part_a_inputs: Optional[dict[str, Any]] = None,
    source_sha: Optional[str] = None,
    input_payloads: Optional[dict[str, Any]] = None,
    quality_flags: Optional[list[str]] = None,
    pdf_pages: Optional[int] = None,
    render_errors: Optional[list[str]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Compose the full v2 report model + coverage matrix + manifest + checkpoint.

    All parts are pure; `part_b_ctx` and `part_a_inputs` are supplied by the live
    wrapper (or tests). The result is deterministic for fixed inputs.
    """
    now = now or datetime.now(timezone.utc)
    fields = report_fields()
    coverage = build_coverage_matrix(fields)
    part_a = build_part_a(**(part_a_inputs or {}), now=now)
    flags = quality_flags if quality_flags is not None else coverage["quality_flags"]
    manifest = build_manifest(
        inputs=input_payloads or {},
        coverage=coverage,
        source_sha=source_sha,
        now=now,
    )
    checkpoint = build_checkpoint(
        coverage=coverage,
        quality_flags=flags,
        pdf_pages=pdf_pages,
        render_errors=render_errors,
    )
    part_b = dict(part_b_ctx or {})
    # Phase 4: normalize allocation units on the model itself (USD + weight %).
    try:
        from scripts.lib.cio_report_view import normalize_allocation
        alloc_norm = normalize_allocation(part_b)
        if alloc_norm.get("allocation_usd"):
            part_b["allocation"] = {
                k: v for k, v in (alloc_norm["allocation_usd"] or {}).items() if v is not None
            }
        if alloc_norm.get("allocation_weight_pct"):
            part_b["allocation_weight_pct"] = alloc_norm["allocation_weight_pct"]
    except Exception:
        pass
    # Phase 6: methodology-truth analytics packet (never fabricates TWR/QTD/effects).
    try:
        from scripts.lib.cio_report_analytics import enrich_part_b
        hist = None
        if part_a_inputs and isinstance(part_a_inputs.get("performance"), dict):
            hist = (part_a_inputs["performance"].get("periods")
                    or part_a_inputs["performance"].get("period_returns"))
        part_b = enrich_part_b(
            part_b,
            performance_attribution=part_a_inputs.get("performance_attribution") if part_a_inputs else None,
            history_periods=hist,
            as_of=_now_iso(now),
        )
    except Exception:
        pass
    model = {
        "report_version": REPORT_VERSION,
        "architecture_version": "report_arch_1.0.0",
        "authority": "READ_ONLY_ADVISORY",
        "as_of": _now_iso(now),
        "part_a": part_a,
        "part_b": part_b,
        "fields": fields,
        "coverage": coverage,
        "manifest": manifest,
        "checkpoint": checkpoint,
        "quality_flags": flags,
    }
    # Shared view first — single fact surface for all formats
    try:
        from scripts.lib.cio_report_view import build_report_view
        view = build_report_view(model)
        model["view"] = view
        model["facts_fingerprint"] = view.get("facts_fingerprint")
    except Exception:
        model["view"] = None
        model["facts_fingerprint"] = None
    model["html"] = render_html(model)
    return model