#!/usr/bin/env python3
"""defense_cash_alternatives.py — Defense Desk v10: cash deployment alternatives.

Screens defensive/low-vol ETFs, dividend funds, bond ETFs, balanced funds, money
market instruments, and covered-call income ETFs against live market data.
Produces a ranked JSON snapshot consumed by the defense desk frontend.

Scoring: Yield (30%), Capital preservation (35%), Liquidity (20%), Tax efficiency (15%).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "data" / "runtime" / "defense_cash_alternatives_latest.json"

# Universe: conservative vehicles suitable as cash substitutes
UNIVERSE = {
    "low_vol": [
        {"symbol": "USMV", "name": "iShares MSCI USA Min Vol", "category": "low_vol"},
        {"symbol": "SPLV", "name": "Invesco S&P 500 Low Vol", "category": "low_vol"},
        {"symbol": "LVHD", "name": "Legg Mason Low Vol High Div", "category": "low_vol"},
    ],
    "dividend": [
        {"symbol": "SCHD", "name": "Schwab US Dividend Equity", "category": "dividend"},
        {"symbol": "VYM", "name": "Vanguard High Dividend Yield", "category": "dividend"},
        {"symbol": "HDV", "name": "iShares Core High Dividend", "category": "dividend"},
        {"symbol": "DGRO", "name": "iShares Core Dividend Growth", "category": "dividend"},
    ],
    "bond": [
        {"symbol": "BND", "name": "Vanguard Total Bond Market", "category": "bond"},
        {"symbol": "AGG", "name": "iShares Core US Aggregate Bond", "category": "bond"},
        {"symbol": "LQD", "name": "iShares iBoxx Inv Grade Corp Bond", "category": "bond"},
        {"symbol": "MUB", "name": "iShares National Muni Bond", "category": "bond"},
        {"symbol": "VTIP", "name": "Vanguard Short-Term TIPS", "category": "bond"},
        {"symbol": "SGOV", "name": "iShares 0-3 Month Treasury", "category": "money_market"},
        {"symbol": "BIL", "name": "SPDR Bloomberg 1-3 Month T-Bill", "category": "money_market"},
    ],
    "balanced": [
        {"symbol": "AOK", "name": "iShares Core Conservative Allocation", "category": "balanced"},
    ],
    "covered_call": [
        {"symbol": "JEPI", "name": "JPMorgan Equity Premium Income", "category": "covered_call"},
        {"symbol": "JEPQ", "name": "JPMorgan Nasdaq Equity Premium Income", "category": "covered_call"},
    ],
}


def _load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _get_price(symbol: str) -> dict | None:
    """Get latest price + dividend data from market quotes DB."""
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("""SELECT close_price, day_change_pct, volume, symbol
                       FROM market_quotes WHERE symbol=%s
                       ORDER BY date_scraped DESC LIMIT 1""", (symbol,))
        row = cur.fetchone()
        if row:
            return {"price": float(row[0]), "change_pct": float(row[1]) if row[1] else None,
                    "volume": row[2], "symbol": row[3]}
    except Exception:
        pass
    # Fallback: try ticker_prices table
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("""SELECT close_price FROM ticker_prices WHERE symbol=%s
                       ORDER BY price_date DESC LIMIT 1""", (symbol,))
        row = cur.fetchone()
        if row:
            return {"price": float(row[0]), "change_pct": None, "volume": None, "symbol": symbol}
    except Exception:
        pass
    return None


def _get_yield_data(symbol: str) -> dict | None:
    """Get dividend yield from broker or Finviz snapshots."""
    result = {"div_yield": None, "sec_yield": None, "payout_ratio": None}
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        # Check market_quote_snapshots for yield data
        cur.execute("""SELECT dividend_yield, pe_ratio FROM market_quote_snapshots
                       WHERE symbol=%s ORDER BY created_at DESC LIMIT 1""", (symbol,))
        row = cur.fetchone()
        if row:
            result["div_yield"] = float(row[0]) if row[0] else None
            result["pe_ratio"] = float(row[1]) if row[1] else None
    except Exception:
        pass
    # Bond/MM ETF yield from Finviz
    try:
        snap = _load_json(ROOT / "data" / "runtime" / "finviz_etfs_latest.json")
        if snap:
            etfs = {e["symbol"]: e for e in (snap.get("etfs") or [])}
            if symbol in etfs:
                e = etfs[symbol]
                result["div_yield"] = result["div_yield"] or (float(e["div_yield"]) if e.get("div_yield") else None)
    except Exception:
        pass
    return result


def score_candidate(c: dict, price_data: dict | None, yield_data: dict | None) -> dict:
    """Score 0-100 across four dimensions."""
    scores = {}
    cat = c.get("category", "")

    # Yield adequacy (30%) — meaningful yield vs risk-free rate (~4.5% T-bill)
    div_yield = yield_data.get("div_yield") if yield_data else None
    if div_yield is not None and div_yield > 0:
        rf = 4.5  # approximate 4-week T-bill
        ratio = div_yield / rf
        scores["yield"] = min(100, max(0, ratio * 50))  # 4.5% = 50, 9% = 100
    else:
        scores["yield"] = 25  # unknown but not zero — neutral

    # Capital preservation (35%) — volatility, drawdown resistance
    if cat in ("bond", "money_market"):
        scores["preservation"] = 90  # bonds are inherently defensive
    elif cat == "low_vol":
        scores["preservation"] = 80
    elif cat == "balanced":
        scores["preservation"] = 70
    elif cat == "dividend":
        scores["preservation"] = 65
    elif cat == "covered_call":
        scores["preservation"] = 50
    else:
        scores["preservation"] = 50

    # Deduct for high volatility if we have price data
    change_pct = abs(price_data.get("change_pct") or 0) if price_data else 0
    if change_pct > 2:
        scores["preservation"] -= 10

    # Liquidity (20%) — ADV / bid-ask spread
    vol = price_data.get("volume") if price_data else None
    if vol and vol > 1000000:
        scores["liquidity"] = 95
    elif vol and vol > 100000:
        scores["liquidity"] = 75
    elif vol:
        scores["liquidity"] = 50
    else:
        scores["liquidity"] = 40

    # Tax efficiency (15%) — municipal for taxable, qualified dividends
    if cat == "bond" and "MUB" in str(c.get("symbol", "")):
        scores["tax"] = 95  # municipal bonds
    elif cat in ("money_market",):
        if "MUB" in str(c.get("symbol", "")):
            scores["tax"] = 95
        else:
            scores["tax"] = 60  # Treasury interest is state-tax exempt
    elif cat in ("dividend", "covered_call"):
        scores["tax"] = 50  # qualified dividends somewhat efficient
    elif cat == "low_vol":
        scores["tax"] = 40  # mostly qualified but some ordinary
    elif cat == "balanced":
        scores["tax"] = 35  # bond interest is ordinary income
    else:
        scores["tax"] = 40

    # Weighted total
    weights = {"yield": 0.30, "preservation": 0.35, "liquidity": 0.20, "tax": 0.15}
    total = sum(scores[k] * weights[k] for k in weights)
    c["scores"] = {k: round(v, 1) for k, v in scores.items()}
    c["total_score"] = round(total, 1)
    return c


def _generate_thesis(c: dict) -> str:
    """Generate a one-paragraph thesis using DeepSeek Flash."""
    cat = c.get("category", "")
    taglines = {
        "low_vol": "Low-volatility equity ETF — designed to capture market returns with reduced drawdown risk. Beta under 0.85 provides downside protection while maintaining some upside participation. Suitable as a conservative equity sleeve within a cash-alternative framework.",
        "dividend": "Dividend-focused ETF providing income yield above the risk-free rate while maintaining equity exposure. The yield premium over T-bills compensates for the modest equity beta. Best held in taxable or IRA accounts depending on qualified dividend status.",
        "bond": "Fixed-income ETF offering credit-quality-filtered bond exposure with moderate duration. Provides ballast against equity drawdowns while generating income above money market rates. Duration risk is the primary concern in rising-rate environments.",
        "money_market": "Ultra-short Treasury or T-bill ETF — essentially a cash equivalent with near-zero credit and duration risk. SEC yield tracks the Fed funds rate. The most conservative option; suitable for the portion of cash that must remain extremely liquid.",
        "balanced": "Conservative allocation fund blending equity (typically <40%) with investment-grade bonds. The mixed-asset structure smooths volatility while generating moderate total returns. A set-and-forget option for cash that doesn't need same-week liquidity.",
        "covered_call": "Covered-call income ETF that writes out-of-the-money calls on an equity portfolio to generate premium income. Yield is typically well above the risk-free rate but comes with capped upside and modest NAV erosion over very long holds. Best in sideways or mildly bullish markets.",
    }
    c["thesis"] = taglines.get(cat, "Conservative cash-alternative vehicle suitable for defensive portfolio allocation.")
    c["thesis_lane"] = "defined"  # structured by category; LLM refinement opt-in
    return c


def screen() -> dict:
    """Screen all candidates, score them, rank by total score, and save."""
    candidates = []
    for group, entries in UNIVERSE.items():
        for e in entries:
            c = dict(e)
            price_data = _get_price(c["symbol"])
            yield_data = _get_yield_data(c["symbol"])
            c["price"] = price_data
            c["yield_data"] = yield_data
            c = score_candidate(c, price_data, yield_data)
            c = _generate_thesis(c)
            candidates.append(c)

    candidates.sort(key=lambda x: x.get("total_score", 0), reverse=True)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidates": candidates,
        "top3": candidates[:3],
        "risk_free_rate": 4.5,  # approximate 4-week T-bill, update periodically
        "note": "Advisory only — the desk presents alternatives; allocation requires operator decision + 2FA.",
    }
    OUTPUT.write_text(json.dumps(result, default=str, indent=1))
    return result


def main() -> int:
    result = screen()
    print(f"[cash-alternatives] screened {len(result['candidates'])} vehicles, top: "
          f"{', '.join(c['symbol'] for c in result['top3'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
