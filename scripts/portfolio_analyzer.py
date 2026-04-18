"""portfolio_analyzer.py — Trade AI v12 Portfolio Intelligence
Core analytics: allocation, sector exposure, concentration, dividends,
ETF look-through, portfolio vitals, attribution.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple
import json


# ── Sector classification for individual stocks ───────────────────────────────

STOCK_SECTORS: Dict[str, str] = {
    # Defense & Aerospace
    "AVAV": "Defense", "BAH": "Defense", "CACI": "Defense",
    "DRS": "Defense", "IRDM": "Defense", "KBR": "Defense",
    "KTOS": "Defense", "LDOS": "Defense", "LHX": "Defense",
    "LMT": "Defense", "NOC": "Defense", "RKLB": "Defense",
    "RTX": "Defense", "TDG": "Defense",
    # Financials
    "V": "Financials", "JPM": "Financials", "BAC": "Financials",
    "CSWC": "Financials",  # BDC
    "PFLT": "Financials",  # BDC
    # Healthcare
    "PFE": "Healthcare", "SRNE": "Healthcare",
    # Technology
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "GOOGL": "Technology", "META": "Technology", "TSLA": "Technology",
    # Energy
    "XOM": "Energy", "CVX": "Energy", "NEE": "Utilities",
    # Materials/Industrials
    "GE": "Industrials", "HON": "Industrials",
}

# Stock type classification
STOCK_TYPES: Dict[str, str] = {
    "CSWC": "BDC", "PFLT": "BDC", "DIV": "Income ETF",
    "SCHD": "Dividend ETF", "SCHG": "Growth ETF",
    "ARKG": "Thematic ETF", "ARKQ": "Thematic ETF",
    "BND": "Bond ETF", "XLB": "Sector ETF", "XLI": "Sector ETF",
    "AMANX": "Mutual Fund", "FCNTX": "Mutual Fund",
}

SECTOR_COLORS: Dict[str, str] = {
    "Defense": "#1565C0",
    "Financials": "#2E7D32",
    "Healthcare": "#7B1FA2",
    "Technology": "#E65100",
    "Energy": "#F57F17",
    "Utilities": "#00695C",
    "Industrials": "#4E342E",
    "Materials": "#37474F",
    "Consumer Discretionary": "#AD1457",
    "Consumer Staples": "#558B2F",
    "Real Estate": "#6D4C41",
    "Communication Services": "#283593",
    "Income/BDC": "#1A237E",
    "ETF/Fund": "#424242",
    "Bonds": "#5D4037",
    "Cash": "#616161",
    "Other": "#9E9E9E",
}


def _get_sector(symbol: str, asset_type: str = "") -> str:
    if symbol == "CASH":
        return "Cash"
    s = STOCK_SECTORS.get(symbol.upper())
    if s:
        return s
    if "ETF" in asset_type.upper():
        return "ETF/Fund"
    if "MUTUAL" in asset_type.upper() or "FUND" in asset_type.upper():
        return "ETF/Fund"
    if "BOND" in asset_type.upper():
        return "Bonds"
    return "Other"


# ── ETF Look-Through ──────────────────────────────────────────────────────────

def get_etf_sector_breakdown(symbol: str, config: Dict) -> Optional[Dict[str, float]]:
    """Return sector breakdown dict for a known ETF."""
    etf_cfg = config.get("etf_sectors", {})
    if symbol in etf_cfg:
        return etf_cfg[symbol].get("top_sectors", {})
    return None


def compute_etf_lookathrough(holdings: List[Dict], config: Dict) -> Dict[str, float]:
    """
    Compute blended sector exposure including ETF look-through.
    Returns sector → dollar exposure dict.
    """
    sector_exposure: Dict[str, float] = defaultdict(float)
    total_portfolio = sum(h.get("market_value") or 0 for h in holdings
                         if (h.get("market_value") or 0) > 0 and not h.get("is_loan"))

    for h in holdings:
        if h.get("is_loan") or h.get("is_cash"):
            continue
        sym = h.get("symbol", "")
        mv = h.get("market_value") or 0
        if mv <= 0:
            continue
        asset_type = h.get("asset_type", "")

        # ETF look-through
        etf_sectors = get_etf_sector_breakdown(sym, config)
        if etf_sectors:
            for sector, pct in etf_sectors.items():
                sector_exposure[sector] += mv * (pct / 100)
        elif h.get("is_fund") or h.get("asset_type", "").startswith("Mutual"):
            # 401k funds — classify by sector_type
            st = h.get("sector_type", "")
            if "intl" in st or "international" in st:
                sector_exposure["International Equity"] += mv
            elif "bond" in st:
                sector_exposure["Bonds"] += mv
            else:
                sector_exposure["US Equity Funds"] += mv
        else:
            sector = _get_sector(sym, asset_type)
            sector_exposure[sector] += mv

    return dict(sector_exposure)


# ── Concentration Analysis ────────────────────────────────────────────────────

def analyze_concentration(holdings: List[Dict], config: Dict) -> Dict[str, Any]:
    """Identify concentration risks — single stock, sector, account-level."""
    total = sum(h.get("market_value") or 0 for h in holdings
                if (h.get("market_value") or 0) > 0 and not h.get("is_loan"))

    targets = config.get("portfolio_targets", {})
    max_stock = targets.get("max_single_stock_pct", 15.0)
    max_sector = targets.get("max_single_sector_pct", 30.0)
    warn_pct = targets.get("concentration_warning_pct", 10.0)

    # Single-stock concentration (aggregate across accounts)
    stock_agg: Dict[str, float] = defaultdict(float)
    for h in holdings:
        sym = h.get("symbol", "")
        mv = h.get("market_value") or 0
        if mv > 0 and not h.get("is_loan") and sym not in ("CASH",):
            stock_agg[sym] += mv

    stock_flags = []
    for sym, mv in sorted(stock_agg.items(), key=lambda x: -x[1]):
        pct = (mv / total * 100) if total > 0 else 0
        if pct >= warn_pct:
            severity = "CRITICAL" if pct >= max_stock * 2 else ("HIGH" if pct >= max_stock else "WARNING")
            stock_flags.append({
                "symbol": sym,
                "market_value": mv,
                "pct_of_portfolio": round(pct, 2),
                "threshold": max_stock,
                "severity": severity,
            })

    # Sector concentration (direct holdings only, no ETF look-through for this)
    sector_direct: Dict[str, float] = defaultdict(float)
    for h in holdings:
        if h.get("is_loan") or h.get("is_cash"):
            continue
        mv = h.get("market_value") or 0
        if mv > 0:
            s = _get_sector(h.get("symbol", ""), h.get("asset_type", ""))
            sector_direct[s] += mv

    sector_flags = []
    for sector, mv in sorted(sector_direct.items(), key=lambda x: -x[1]):
        pct = (mv / total * 100) if total > 0 else 0
        if pct >= warn_pct:
            severity = "CRITICAL" if pct >= max_sector else ("HIGH" if pct >= max_sector * 0.7 else "WARNING")
            sector_flags.append({
                "sector": sector,
                "market_value": mv,
                "pct_of_portfolio": round(pct, 2),
                "threshold": max_sector,
                "severity": severity,
            })

    # Account-level concentration
    acct_agg: Dict[str, float] = defaultdict(float)
    for h in holdings:
        if h.get("is_loan"):
            continue
        mv = h.get("market_value") or 0
        if mv > 0:
            acct_agg[h.get("account", "unknown")] += mv

    return {
        "stock_concentration": stock_flags[:10],
        "sector_concentration": sector_flags[:10],
        "account_breakdown": dict(sorted(acct_agg.items(), key=lambda x: -x[1])),
        "total_portfolio": total,
    }


# ── Dividend Analytics ────────────────────────────────────────────────────────

DIVIDEND_YIELDS: Dict[str, float] = {
    # Approximate forward yields (%)
    "CSWC": 10.5,   # BDC — high yield + special dividends
    "PFLT": 11.2,   # BDC — monthly dividend
    "SCHD": 3.6,    "DIV": 5.8,
    "V": 0.8,       "PFE": 6.2,
    "LMT": 2.8,     "NOC": 1.6,    "RTX": 2.1,
    "LDOS": 1.4,    "LHX": 2.2,    "BAH": 1.8,
    "NEE": 3.2,     "TDG": 0.1,
    "AMANX": 1.8,   "FCNTX": 0.3,
    "BND": 3.4,     "XLB": 1.9,    "XLI": 1.7,
}

DIVIDEND_FREQUENCY: Dict[str, str] = {
    "CSWC": "monthly+special", "PFLT": "monthly",
    "SCHD": "quarterly", "DIV": "monthly",
    "V": "quarterly", "PFE": "quarterly",
    "LMT": "quarterly", "NOC": "quarterly", "RTX": "quarterly",
    "LDOS": "quarterly", "LHX": "quarterly", "BAH": "quarterly",
    "NEE": "quarterly", "BND": "monthly",
    "XLB": "quarterly", "XLI": "quarterly",
}


def compute_dividend_income(holdings: List[Dict]) -> Dict[str, Any]:
    """Estimate annual dividend income from current holdings."""
    total_annual = 0.0
    by_holding = []

    for h in holdings:
        sym = h.get("symbol", "")
        mv = h.get("market_value") or 0
        if mv <= 0 or h.get("is_loan") or h.get("is_cash"):
            continue

        yield_pct = DIVIDEND_YIELDS.get(sym)
        if yield_pct:
            annual = mv * yield_pct / 100
            total_annual += annual
            by_holding.append({
                "symbol": sym,
                "account": h.get("account_display", ""),
                "market_value": mv,
                "yield_pct": yield_pct,
                "annual_income": annual,
                "monthly_income": annual / 12,
                "frequency": DIVIDEND_FREQUENCY.get(sym, "quarterly"),
                "reinvest": h.get("reinvest_div", False),
            })

    by_holding.sort(key=lambda x: -x["annual_income"])
    return {
        "total_annual_income": total_annual,
        "total_monthly_income": total_annual / 12,
        "by_holding": by_holding,
        "drip_count": sum(1 for h in by_holding if h["reinvest"]),
        "cash_count": sum(1 for h in by_holding if not h["reinvest"]),
    }


# ── Portfolio Vitals ──────────────────────────────────────────────────────────

STOCK_PE: Dict[str, float] = {
    "V": 32.5, "PFE": 9.2, "AVAV": 42.1, "BAH": 15.8,
    "CACI": 18.3, "DRS": 28.6, "IRDM": 22.4, "KBR": 16.2,
    "KTOS": 54.8, "LDOS": 19.5, "LHX": 21.3, "LMT": 17.2,
    "NOC": 18.6, "RKLB": -99.0, "RTX": 28.4, "TDG": 38.2,
    "NEE": 21.8, "CSWC": 10.2, "PFLT": 8.8,
}

STOCK_BETA: Dict[str, float] = {
    "V": 0.95, "PFE": 0.55, "AVAV": 1.45, "BAH": 0.85,
    "CACI": 0.78, "DRS": 1.12, "IRDM": 1.38, "KBR": 0.92,
    "KTOS": 1.65, "LDOS": 0.72, "LHX": 0.88, "LMT": 0.75,
    "NOC": 0.72, "RKLB": 2.15, "RTX": 0.82, "TDG": 1.18,
    "NEE": 0.68, "CSWC": 0.78, "PFLT": 0.65,
    "SCHG": 1.15, "SCHD": 0.72, "ARKG": 1.45, "ARKQ": 1.38,
    "DIV": 0.78, "BND": -0.05, "XLB": 1.12, "XLI": 0.95,
}


def compute_portfolio_vitals(holdings: List[Dict]) -> Dict[str, Any]:
    """Compute weighted portfolio-level metrics."""
    total_mv = sum(h.get("market_value") or 0 for h in holdings
                   if (h.get("market_value") or 0) > 0 and not h.get("is_loan"))

    weighted_beta = 0.0
    weighted_pe = 0.0
    pe_weight = 0.0

    for h in holdings:
        sym = h.get("symbol", "")
        mv = h.get("market_value") or 0
        if mv <= 0 or h.get("is_loan"):
            continue
        w = mv / total_mv if total_mv > 0 else 0

        beta = STOCK_BETA.get(sym)
        if beta:
            weighted_beta += w * beta

        pe = STOCK_PE.get(sym)
        if pe and pe > 0:
            weighted_pe += pe * mv
            pe_weight += mv

    return {
        "weighted_beta": round(weighted_beta, 3),
        "weighted_pe": round(weighted_pe / pe_weight, 1) if pe_weight > 0 else None,
        "total_market_value": total_mv,
        "equity_pct": 100,  # to be refined
    }


# ── Performance Attribution ───────────────────────────────────────────────────

def compute_attribution(holdings: List[Dict], account_summaries: Dict) -> Dict[str, Any]:
    """Compute P&L attribution by account, sector, top contributors/detractors."""
    total_gain = sum(h.get("gain_loss") or 0 for h in holdings
                     if h.get("gain_loss") is not None and not h.get("is_loan"))

    # Top contributors / detractors
    with_gain = [h for h in holdings if h.get("gain_loss") is not None and not h.get("is_loan")]
    with_gain.sort(key=lambda x: x.get("gain_loss") or 0, reverse=True)

    contributors = []
    for h in with_gain[:5]:
        if (h.get("gain_loss") or 0) > 0:
            contributors.append({
                "symbol": h.get("symbol"),
                "account": h.get("account_display"),
                "gain": h.get("gain_loss"),
                "gain_pct": h.get("gain_loss_pct"),
            })

    detractors = []
    for h in reversed(with_gain[-10:]):
        if (h.get("gain_loss") or 0) < 0:
            detractors.append({
                "symbol": h.get("symbol"),
                "account": h.get("account_display"),
                "loss": h.get("gain_loss"),
                "loss_pct": h.get("gain_loss_pct"),
            })

    # By account
    by_account = {
        k: {"gain": v.get("total_gain", 0), "pct": v.get("total_gain_pct", 0)}
        for k, v in account_summaries.items()
    }

    # Total cost and gain
    total_cost = sum(h.get("cost_basis") or 0 for h in holdings
                     if h.get("cost_basis") and not h.get("is_loan"))

    return {
        "total_gain": total_gain,
        "total_cost": total_cost,
        "total_gain_pct": (total_gain / total_cost * 100) if total_cost > 0 else 0,
        "top_contributors": contributors,
        "top_detractors": detractors,
        "by_account": by_account,
    }


# ── Critical Flags ────────────────────────────────────────────────────────────

def generate_critical_flags(
    holdings: List[Dict],
    concentration: Dict,
    dividends: Dict,
    config: Dict,
) -> List[Dict]:
    """Generate actionable flags sorted by severity."""
    flags = []
    revoked = {r["symbol"].upper() for r in config.get("revoked_securities", [])}

    # Concentration flags
    for sc in concentration.get("stock_concentration", []):
        if sc["severity"] in ("CRITICAL", "HIGH"):
            sym = sc["symbol"]
            flags.append({
                "severity": sc["severity"],
                "category": "CONCENTRATION",
                "symbol": sym,
                "message": f"{sym}: {sc['pct_of_portfolio']:.1f}% of total portfolio "
                          f"(threshold {sc['threshold']:.0f}%) — ${sc['market_value']:,.0f}",
                "action": f"Consider trimming {sym} position to reduce single-stock risk",
            })

    # Revoked / worthless securities
    for h in holdings:
        sym = h.get("symbol", "").upper()
        if sym in revoked or h.get("is_revoked"):
            flags.append({
                "severity": "HIGH",
                "category": "REVOKED_SECURITY",
                "symbol": sym,
                "message": f"{sym}: Registration revoked — position is worthless",
                "action": "Contact broker to remove revoked security from account",
            })

    # Tax loss harvest candidates
    for h in holdings:
        if h.get("is_loan"):
            continue
        gl = h.get("gain_loss") or 0
        mv = h.get("market_value") or 0
        gl_pct = h.get("gain_loss_pct") or 0
        if gl < -1000 and gl_pct < -20 and not h.get("is_revoked"):
            flags.append({
                "severity": "WARNING",
                "category": "TAX_LOSS_HARVEST",
                "symbol": h.get("symbol"),
                "message": f"{h.get('symbol')}: ${abs(gl):,.0f} unrealized loss "
                          f"({gl_pct:.1f}%) — tax loss harvest candidate",
                "action": "Evaluate selling for tax loss, replace with similar exposure",
            })

    # DRIP in taxable account (tax drag)
    taxable_drip = [h for h in holdings
                    if h.get("account_type") == "taxable" and h.get("reinvest_div")]
    if taxable_drip:
        syms = ", ".join(h.get("symbol") for h in taxable_drip[:5])
        flags.append({
            "severity": "INFO",
            "category": "DRIP_TAXABLE",
            "symbol": None,
            "message": f"DRIP enabled in taxable account for: {syms}",
            "action": "DRIP in taxable accounts creates taxable events. Consider taking dividends as cash.",
        })

    # Outstanding 401k loan
    loan_h = next((h for h in holdings if h.get("is_loan")), None)
    if loan_h:
        loan_bal = abs(loan_h.get("market_value") or 0)
        flags.append({
            "severity": "WARNING",
            "category": "401K_LOAN",
            "symbol": "401K-LOAN",
            "message": f"401k loan outstanding: ${loan_bal:,.2f}",
            "action": "Consider accelerating repayment to restore compound growth potential",
        })

    # ETF overlap
    etf_syms = [h.get("symbol") for h in holdings if h.get("is_etf")]
    if "SCHG" in etf_syms and "FCNTX" in [h.get("symbol") for h in holdings]:
        flags.append({
            "severity": "WARNING",
            "category": "ETF_OVERLAP",
            "symbol": "SCHG/FCNTX",
            "message": "SCHG and FCNTX both heavily weighted in Apple/Microsoft/Nvidia — significant overlap",
            "action": "Review combined tech concentration via ETF look-through analysis",
        })

    # Sort: CRITICAL → HIGH → WARNING → INFO
    severity_order = {"CRITICAL": 0, "HIGH": 1, "WARNING": 2, "INFO": 3}
    flags.sort(key=lambda f: severity_order.get(f.get("severity", "INFO"), 3))
    return flags


# ── Main Analysis Entry Point ─────────────────────────────────────────────────

def analyze_portfolio(portfolio: Dict) -> Dict[str, Any]:
    """Run complete analytics on loaded portfolio."""
    holdings = portfolio.get("holdings", [])
    acct_summaries = portfolio.get("account_summaries", {})
    config = portfolio.get("config", {})

    print("  [analyzer] Running concentration analysis...")
    concentration = analyze_concentration(holdings, config)

    print("  [analyzer] Computing sector exposure + ETF look-through...")
    sector_exposure = compute_etf_lookathrough(holdings, config)

    print("  [analyzer] Computing dividend income...")
    dividends = compute_dividend_income(holdings)

    print("  [analyzer] Computing portfolio vitals...")
    vitals = compute_portfolio_vitals(holdings)

    print("  [analyzer] Computing attribution...")
    attribution = compute_attribution(holdings, acct_summaries)

    print("  [analyzer] Generating critical flags...")
    flags = generate_critical_flags(holdings, concentration, dividends, config)

    # Sector exposure as % of portfolio
    total_mv = concentration.get("total_portfolio", 1)
    sector_pct = {s: round(mv / total_mv * 100, 2) for s, mv in sector_exposure.items()}

    return {
        "concentration": concentration,
        "sector_exposure": sector_exposure,
        "sector_pct": sector_pct,
        "dividends": dividends,
        "vitals": vitals,
        "attribution": attribution,
        "critical_flags": flags,
        "flag_count": {"CRITICAL": sum(1 for f in flags if f["severity"] == "CRITICAL"),
                       "HIGH": sum(1 for f in flags if f["severity"] == "HIGH"),
                       "WARNING": sum(1 for f in flags if f["severity"] == "WARNING"),
                       "INFO": sum(1 for f in flags if f["severity"] == "INFO")},
    }
