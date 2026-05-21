#!/usr/bin/env python3
"""dividend_income_scoring_policy.py — Dividend/income-specific candidate scoring.

Replaces momentum-style scoring for DIVIDEND_INCOME family candidates.
Pure functions. No DB writes. No proposal creation. No trades/orders.
"""
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

SCORE_FLOOR = 15  # Lowered from 30 (momentum default)
YIELD_TRAP_THRESHOLD = 12.0  # Yield above this triggers warning


def get_enrichment(symbol: str) -> dict:
    """Get enrichment data for a symbol from the cache."""
    try:
        ec = json.loads((STATE_DIR / "ticker_enrichment_cache.json").read_text())
        return ec.get(symbol, {})
    except Exception:
        return {}


def score_dividend_income_candidate(candidate: dict) -> dict:
    """Score a dividend/income candidate. Returns scoring breakdown.

    Uses available data — does NOT fake missing fields.
    Total possible: 100 points.
    """
    symbol = candidate.get("symbol", "?")
    enrichment = candidate.get("enrichment") or get_enrichment(symbol)

    passed = []
    failed = []
    warnings = []
    missing = []

    # ── Dividend Yield (0-25 pts) ──
    div_yield = (candidate.get("dividend_yield") or
                 enrichment.get("div_yield_pct") or  # Finviz enrichment field name
                 enrichment.get("dividend_yield") or
                 enrichment.get("dividendYield") or
                 enrichment.get("forwardDividendYield"))
    yield_score = 0
    yield_trap = False

    if div_yield is not None:
        div_yield = float(div_yield)
        if div_yield >= YIELD_TRAP_THRESHOLD:
            yield_score = 10  # Penalize extremely high yield
            yield_trap = True
            warnings.append(f"yield_trap_warning: {div_yield:.1f}% exceeds {YIELD_TRAP_THRESHOLD}% — verify sustainability")
        elif div_yield >= 5.0:
            yield_score = 25
            passed.append(f"yield {div_yield:.1f}% (strong)")
        elif div_yield >= 3.0:
            yield_score = 20
            passed.append(f"yield {div_yield:.1f}% (acceptable)")
        elif div_yield >= 1.5:
            yield_score = 12
            passed.append(f"yield {div_yield:.1f}% (moderate)")
        elif div_yield > 0:
            yield_score = 5
            warnings.append(f"yield {div_yield:.1f}% (low for income strategy)")
    else:
        missing.append("dividend_yield")
        warnings.append("dividend yield unavailable — cannot confirm income suitability")
        yield_score = 5  # Small credit for being classified as income

    # ── Payout Quality (0-20 pts) ──
    payout = candidate.get("payout_ratio") or enrichment.get("payout_ratio") or enrichment.get("payoutRatio")
    payout_score = 0

    if payout is not None:
        payout = float(payout)
        if payout <= 60:
            payout_score = 20
            passed.append(f"payout {payout:.0f}% (healthy)")
        elif payout <= 80:
            payout_score = 15
            passed.append(f"payout {payout:.0f}% (acceptable)")
        elif payout <= 100:
            payout_score = 8
            warnings.append(f"payout {payout:.0f}% (stretched)")
        else:
            payout_score = 0
            warnings.append(f"payout {payout:.0f}% (unsustainable)")
    else:
        missing.append("payout_ratio")
        payout_score = 5  # Small credit — don't hard fail

    # ── Dividend Growth (0-20 pts) ──
    growth_years = candidate.get("dividend_growth_years") or enrichment.get("dividend_growth_years")
    growth_score = 0

    if growth_years is not None:
        growth_years = int(growth_years)
        if growth_years >= 25:
            growth_score = 20
            passed.append(f"dividend aristocrat ({growth_years}yr)")
        elif growth_years >= 10:
            growth_score = 15
            passed.append(f"dividend grower ({growth_years}yr)")
        elif growth_years >= 5:
            growth_score = 10
            passed.append(f"dividend history ({growth_years}yr)")
        else:
            growth_score = 5
    else:
        missing.append("dividend_growth_years")
        growth_score = 5  # Don't hard fail

    # ── Income Safety / Fundamentals (0-15 pts) ──
    pe = enrichment.get("pe") or enrichment.get("trailingPE")
    market_cap = enrichment.get("market_cap_b")
    roe = enrichment.get("roe_pct")
    debt_eq = enrichment.get("total_debt_equity") or enrichment.get("lt_debt_equity")
    safety_score = 0

    if pe is not None and float(pe) > 0:
        pe_val = float(pe)
        if pe_val <= 20:
            safety_score += 5
            passed.append(f"PE {pe_val:.1f} (value)")
        elif pe_val <= 35:
            safety_score += 3
        else:
            warnings.append(f"PE {pe_val:.1f} (expensive for income)")

    if roe is not None and float(roe) > 10:
        safety_score += 3
        passed.append(f"ROE {float(roe):.1f}% (profitable)")

    if market_cap is not None and float(market_cap) >= 2.0:
        safety_score += 5
        passed.append(f"market cap ${float(market_cap):.1f}B (institutional)")
    elif market_cap is not None:
        safety_score += 2
    else:
        missing.append("market_cap")

    if debt_eq is not None and float(debt_eq) < 1.5:
        safety_score += 2
        passed.append(f"debt/equity {float(debt_eq):.1f} (manageable)")

    # ── Liquidity (0-10 pts) ──
    avg_vol = (candidate.get("avg_volume") or enrichment.get("avg_vol_m") or
               enrichment.get("volume_base"))
    liq_score = 0

    if avg_vol is not None:
        vol = float(avg_vol)
        # avg_vol_m is in millions for the enrichment cache
        if vol >= 1.0:  # 1M+ shares/day
            liq_score = 10
            passed.append(f"avg volume {vol:.1f}M (liquid)")
        elif vol >= 0.1:
            liq_score = 6
        else:
            liq_score = 2
            warnings.append(f"avg volume {vol:.2f}M (thin)")
    else:
        missing.append("avg_volume")
        liq_score = 2

    # ── Quote Readiness (0-10 pts) ──
    has_quote = bool(candidate.get("has_quote") or candidate.get("current_price") or
                     candidate.get("scan_price"))
    quote_score = 10 if has_quote else 0
    if not has_quote:
        missing.append("quote")
        warnings.append("no quote — cannot evaluate execution readiness")

    # ── Total ──
    total = yield_score + payout_score + growth_score + safety_score + liq_score + quote_score

    # Determine status
    if total >= SCORE_FLOOR and not yield_trap:
        status = "READY_PROMOTER"
    elif total >= SCORE_FLOOR and yield_trap:
        status = "REVIEW_REQUIRED"
    elif len(missing) >= 3:
        status = "NEEDS_DATA"
    elif total < 10:
        status = "BLOCKED"
    else:
        status = "READY_SHADOW"

    return {
        "symbol": symbol,
        "score": total,
        "score_floor": SCORE_FLOOR,
        "score_breakdown": {
            "yield": yield_score,
            "payout": payout_score,
            "growth": growth_score,
            "safety": safety_score,
            "liquidity": liq_score,
            "quote": quote_score,
        },
        "readiness_status": status,
        "passed": passed,
        "failed": failed,
        "warnings": warnings,
        "missing_fields": missing,
        "yield_trap_warning": yield_trap,
        "dividend_yield": div_yield,
        "human_review_only": True,
        "proposal_eligible": False,
        "policy_version": "dividend_income_scoring_v1",
    }


def dividend_income_readiness_status(candidate: dict) -> dict:
    """Quick readiness check for a dividend/income candidate."""
    return score_dividend_income_candidate(candidate)
