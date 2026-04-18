"""portfolio_risk.py — Trade AI v12 Portfolio Intelligence
Risk metrics (Beta, Sharpe, drawdown), benchmark comparison,
and Trade AI GO ticker correlation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import math


# ── Benchmark Data (approximate YTD) ─────────────────────────────────────────

BENCHMARKS = {
    "SPY":  {"name": "S&P 500",         "ytd_pct": -4.8,  "1yr_pct": 8.2,  "3yr_pct": 32.1},
    "QQQ":  {"name": "Nasdaq 100",      "ytd_pct": -7.2,  "1yr_pct": 9.8,  "3yr_pct": 38.4},
    "IWM":  {"name": "Russell 2000",    "ytd_pct": -9.4,  "1yr_pct": -1.2, "3yr_pct": 11.3},
    "AGG":  {"name": "US Bonds",        "ytd_pct": 1.4,   "1yr_pct": 3.2,  "3yr_pct": -4.1},
    "ITA":  {"name": "Defense ETF",     "ytd_pct": 2.8,   "1yr_pct": 18.6, "3yr_pct": 52.3},
    "VIG":  {"name": "Dividend Growth", "ytd_pct": -3.2,  "1yr_pct": 8.4,  "3yr_pct": 27.8},
}

# Approximate annual volatility (%) per symbol
STOCK_VOLATILITY: Dict[str, float] = {
    "V": 18.2, "PFE": 22.8, "AVAV": 42.5, "BAH": 24.3,
    "CACI": 26.1, "DRS": 31.8, "IRDM": 38.4, "KBR": 28.7,
    "KTOS": 52.3, "LDOS": 22.4, "LHX": 24.8, "LMT": 20.1,
    "NOC": 19.8, "RKLB": 68.4, "RTX": 21.6, "TDG": 28.9,
    "NEE": 24.2, "CSWC": 22.8, "PFLT": 18.6,
    "SCHG": 22.4, "SCHD": 14.8, "ARKG": 58.2, "ARKQ": 46.8,
    "DIV": 18.4, "BND": 8.2, "XLB": 22.1, "XLI": 18.6,
    "FCNTX": 22.8, "AMANX": 18.4,
}

RISK_FREE_RATE = 0.043  # 4.3% approximate (3-month T-bill)


# ── Portfolio Beta & Volatility ───────────────────────────────────────────────

def compute_risk_metrics(holdings: List[Dict]) -> Dict[str, Any]:
    """Compute weighted portfolio risk metrics."""
    from portfolio_analyzer import STOCK_BETA

    total_mv = sum(h.get("market_value") or 0 for h in holdings
                   if (h.get("market_value") or 0) > 0 and not h.get("is_loan"))

    weighted_beta = 0.0
    weighted_vol = 0.0
    beta_coverage = 0.0
    vol_coverage = 0.0

    for h in holdings:
        sym = h.get("symbol", "").upper()
        mv = h.get("market_value") or 0
        if mv <= 0 or h.get("is_loan") or h.get("is_cash"):
            continue

        w = mv / total_mv if total_mv > 0 else 0

        beta = STOCK_BETA.get(sym)
        if beta is not None:
            weighted_beta += w * beta
            beta_coverage += w

        vol = STOCK_VOLATILITY.get(sym)
        if vol is not None:
            weighted_vol += w * vol
            vol_coverage += w

    # Approximate Sharpe (using estimated portfolio return)
    # We use gain/loss % as a proxy for recent return
    valid = [h for h in holdings if h.get("gain_loss_pct") and not h.get("is_loan")]
    if valid:
        total_cost = sum(h.get("cost_basis") or 0 for h in valid)
        weighted_return = sum((h.get("gain_loss_pct") or 0) * (h.get("cost_basis") or 0)
                              for h in valid) / total_cost if total_cost > 0 else 0
    else:
        weighted_return = 0

    sharpe = (weighted_return / 100 - RISK_FREE_RATE) / (weighted_vol / 100) \
             if weighted_vol > 0 else None

    return {
        "weighted_beta": round(weighted_beta, 3),
        "weighted_volatility_pct": round(weighted_vol, 1),
        "beta_coverage_pct": round(beta_coverage * 100, 1),
        "approximate_sharpe": round(sharpe, 2) if sharpe is not None else None,
        "risk_free_rate": RISK_FREE_RATE,
        "risk_assessment": _risk_label(weighted_beta, weighted_vol),
    }


def _risk_label(beta: float, vol: float) -> str:
    if beta > 1.3 or vol > 35:
        return "HIGH RISK — Aggressive"
    elif beta > 1.0 or vol > 22:
        return "MODERATE-HIGH RISK"
    elif beta > 0.7 or vol > 15:
        return "MODERATE RISK"
    else:
        return "CONSERVATIVE"


# ── Benchmark Comparison ──────────────────────────────────────────────────────

def compute_benchmark_comparison(portfolio_totals: Dict, attribution: Dict) -> Dict[str, Any]:
    """Compare portfolio performance against standard benchmarks."""
    total_gain_pct = attribution.get("total_gain_pct", 0)

    comparisons = []
    for ticker, b in BENCHMARKS.items():
        comparisons.append({
            "benchmark": b["name"],
            "ticker": ticker,
            "ytd_pct": b["ytd_pct"],
            "1yr_pct": b["1yr_pct"],
            "vs_portfolio_ytd": None,  # Would need YTD portfolio return
        })

    return {
        "portfolio_total_gain_pct": round(total_gain_pct, 2),
        "benchmarks": comparisons,
        "benchmark_note": "Portfolio gain% is since-inception (cost basis), not YTD",
    }


# ── Position Risk Scoring ─────────────────────────────────────────────────────

HIGH_RISK_SYMBOLS = {"RKLB", "KTOS", "ARKG", "ARKQ", "SRNE"}
INCOME_SYMBOLS    = {"CSWC", "PFLT", "DIV", "SCHD", "BND", "PFE", "NEE"}
DEFENSE_SYMBOLS   = {"AVAV", "BAH", "CACI", "DRS", "IRDM", "KBR", "KTOS",
                     "LDOS", "LHX", "LMT", "NOC", "RKLB", "RTX", "TDG"}


def score_position_risk(symbol: str, market_value: float, portfolio_total: float) -> Dict:
    """Score individual position risk."""
    from portfolio_analyzer import STOCK_BETA
    sym = symbol.upper()
    pct = (market_value / portfolio_total * 100) if portfolio_total > 0 else 0
    beta = STOCK_BETA.get(sym, 1.0)
    vol = STOCK_VOLATILITY.get(sym, 25.0)

    risk_factors = []
    if pct > 15:
        risk_factors.append(f"High concentration ({pct:.1f}% of portfolio)")
    if beta > 1.5:
        risk_factors.append(f"High beta ({beta:.2f})")
    if sym in HIGH_RISK_SYMBOLS:
        risk_factors.append("High-risk / speculative category")
    if vol > 40:
        risk_factors.append(f"High volatility ({vol:.0f}% annualized)")

    risk_score = min(10, len(risk_factors) * 2.5 + (pct / 10))

    return {
        "symbol": symbol,
        "pct_of_portfolio": round(pct, 2),
        "beta": beta,
        "volatility_pct": vol,
        "risk_factors": risk_factors,
        "risk_score": round(risk_score, 1),
        "risk_label": "HIGH" if risk_score >= 6 else ("MEDIUM" if risk_score >= 3 else "LOW"),
    }


# ── Trade AI Correlation ──────────────────────────────────────────────────────

def correlate_with_trade_ai(
    holdings: List[Dict],
    scored_tickers: Optional[List[Dict]] = None,
    run_summary_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Cross-reference Trade AI scored tickers with portfolio holdings.
    If scored_tickers provided, use directly. Otherwise load from run_summary.
    """
    import json, os

    # Load scored tickers from Trade AI state if not provided
    if scored_tickers is None and run_summary_path:
        try:
            with open(run_summary_path) as f:
                data = json.load(f)
                scored_tickers = data.get("tickers", [])
        except Exception:
            scored_tickers = []

    scored_tickers = scored_tickers or []

    # Build lookup: symbol → score/decision
    trade_ai_map = {}
    for t in scored_tickers:
        sym = t.get("symbol", "").upper()
        trade_ai_map[sym] = {
            "score": t.get("score", 0),
            "decision": t.get("decision", ""),
            "rvol": t.get("relative_volume", 0),
            "gap_pct": t.get("gap_percent", 0),
            "top_catalyst": t.get("top_catalyst", {}).get("title", "") if t.get("top_catalyst") else "",
        }

    # Find overlap
    held_symbols = {h.get("symbol", "").upper() for h in holdings
                    if not h.get("is_loan") and not h.get("is_cash")}

    overlaps = []
    for sym in held_symbols:
        if sym in trade_ai_map:
            ta = trade_ai_map[sym]
            holding = next((h for h in holdings if h.get("symbol", "").upper() == sym), {})
            overlaps.append({
                "symbol": sym,
                "account": holding.get("account_display", ""),
                "account_type": holding.get("account_type", ""),
                "market_value": holding.get("market_value", 0),
                "portfolio_pct": holding.get("portfolio_pct", 0),
                "unrealized_gain": holding.get("gain_loss", 0),
                "trade_ai_score": ta["score"],
                "trade_ai_decision": ta["decision"],
                "rvol": ta["rvol"],
                "gap_pct": ta["gap_pct"],
                "catalyst": ta["top_catalyst"],
                "alert": _ta_alert(ta["decision"], ta["score"]),
            })

    go_tickers = [t.get("symbol") for t in scored_tickers if t.get("decision") == "GO"]
    wait_tickers = [t.get("symbol") for t in scored_tickers if t.get("decision") == "WAIT"]

    return {
        "go_tickers": go_tickers,
        "wait_tickers": wait_tickers,
        "holdings_in_screener": overlaps,
        "go_count": len(go_tickers),
        "wait_count": len(wait_tickers),
        "overlap_count": len(overlaps),
        "scan_date": None,
    }


def _ta_alert(decision: str, score: int) -> str:
    if decision == "GO":
        return "🎯 TRADE AI GO — You hold this position"
    elif decision == "WAIT" and score >= 35:
        return "⚡ NEAR-GO — Watch for upgrade"
    return ""


# ── Main Risk Analysis Entry Point ────────────────────────────────────────────

def analyze_risk(portfolio: Dict, trade_ai_state_path: Optional[str] = None) -> Dict[str, Any]:
    """Full risk analysis."""
    holdings = portfolio.get("holdings", [])
    portfolio_totals = portfolio.get("portfolio_totals", {})

    from portfolio_analyzer import compute_attribution
    attribution = compute_attribution(holdings, portfolio.get("account_summaries", {}))

    print("  [risk] Computing risk metrics...")
    risk = compute_risk_metrics(holdings)

    print("  [risk] Benchmark comparison...")
    benchmarks = compute_benchmark_comparison(portfolio_totals, attribution)

    print("  [risk] Scoring individual positions...")
    total_mv = portfolio_totals.get("total_value", 1)
    position_risk = [
        score_position_risk(h.get("symbol", ""), h.get("market_value") or 0, total_mv)
        for h in holdings
        if (h.get("market_value") or 0) > 500 and not h.get("is_loan") and not h.get("is_cash")
    ]
    position_risk.sort(key=lambda x: -x["risk_score"])

    print("  [risk] Trade AI correlation...")
    ta_correlation = correlate_with_trade_ai(holdings, run_summary_path=trade_ai_state_path)

    return {
        "risk_metrics": risk,
        "benchmark_comparison": benchmarks,
        "position_risk": position_risk[:15],
        "high_risk_positions": [p for p in position_risk if p["risk_label"] == "HIGH"],
        "trade_ai_correlation": ta_correlation,
    }
