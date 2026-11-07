#!/usr/bin/env python3
"""defense_cash_alternatives.py — Defense Desk v10: cash deployment alternatives.

Screens defensive/low-vol ETFs, dividend funds, bond ETFs, balanced funds, money
market instruments, and covered-call income ETFs against live market data.
Produces a ranked JSON snapshot consumed by the defense desk frontend.

Scoring: Yield (30%), Capital preservation (35%), Liquidity (20%), Tax efficiency (15%).

Data (fixed 2026-11-06, operator decision "stale sources -> n8n lanes"):
  * price / day change / volume: ``market_quotes`` (latest row per symbol; columns ``price``,
    ``day_change_pct``, ``volume``, ``fetched_at``), else ``ticker_prices.close_price``.
  * yield: ``ticker_dividend_data.annual_dividend_per_share`` (yfinance, written by
    ``sync_dividend_data.py``, which now includes this universe) divided by the quote price. A
    missing, stale (> ``MAX_DIVIDEND_AGE_DAYS``), retired-provider or implausible row is a named
    ``yield_gap`` and the yield stays unknown -- never a number made up here.

``--dry-run`` (default) reads the DB and prints the ranking; nothing is written. ``--apply`` writes
``<TRADEAI_STATE_ROOT>/data/runtime/defense_cash_alternatives_latest.json`` and a LaneRunReceipt v2.
Read-only: no broker, order or notification code is reachable from this script.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANE_ID = "defense-cash-alternatives"
OUTPUT_NAME = "defense_cash_alternatives_latest.json"
MAX_DIVIDEND_AGE_DAYS = 14
MAX_PLAUSIBLE_YIELD_PCT = 25.0

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


def _scripts_on_path() -> None:
    for p in (str(ROOT / "scripts"), str(ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)


def universe_symbols() -> list[str]:
    return [e["symbol"] for entries in UNIVERSE.values() for e in entries]


def _db_query():
    """Read-only query callable ``(sql, params) -> list[dict]``; a failed SELECT is rolled back (never poisons)."""
    _scripts_on_path()
    import psycopg2.extras
    # session13_db, not db_adapter: db_adapter's module reaches holdings_guard -> schwab_position_sync ->
    # schwab_transport (tests/test_lane_transitive_capabilities_20261015.py); this lane must not.
    from session13_db import get_conn
    conn = get_conn(connect_timeout=10)

    def query(sql, params=None):
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]
            conn.rollback()  # read-only: end the transaction, write nothing
            return rows
        except Exception:
            conn.rollback()
            raise
    return query


def _num(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _aware(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load_prices(query, symbols: list[str]) -> dict:
    """{symbol: {price, change_pct, volume, as_of, source}} from market_quotes, else ticker_prices."""
    out = {}
    try:
        rows = query("SELECT DISTINCT ON (symbol) symbol, price, day_change_pct, volume, fetched_at "
                     "FROM market_quotes WHERE symbol = ANY(%s) AND price IS NOT NULL "
                     "ORDER BY symbol, fetched_at DESC", (symbols,))
    except Exception:
        rows = []
    for r in rows:
        price = _num(r.get("price"))
        if price and price > 0:
            out[r["symbol"]] = {"symbol": r["symbol"], "price": price, "change_pct": _num(r.get("day_change_pct")),
                                "volume": r.get("volume"), "as_of": _aware(r.get("fetched_at")), "source": "market_quotes"}
    missing = [s for s in symbols if s not in out]
    if missing:
        try:
            rows = query("SELECT DISTINCT ON (symbol) symbol, close_price, price_date FROM ticker_prices "
                         "WHERE symbol = ANY(%s) AND close_price IS NOT NULL ORDER BY symbol, price_date DESC",
                         (missing,))
        except Exception:
            rows = []
        for r in rows:
            price = _num(r.get("close_price"))
            if price and price > 0:
                out[r["symbol"]] = {"symbol": r["symbol"], "price": price, "change_pct": None, "volume": None,
                                    "as_of": _aware(r.get("price_date")), "source": "ticker_prices"}
    return out


def load_dividends(query, symbols: list[str]) -> dict:
    """{symbol: ticker_dividend_data row}; a read failure returns {} (every yield becomes a named gap)."""
    try:
        rows = query("SELECT symbol, annual_dividend_per_share, dividend_yield_pct, source, updated_at "
                     "FROM ticker_dividend_data WHERE symbol = ANY(%s)", (symbols,))
    except Exception:
        return {}
    return {r["symbol"]: r for r in rows}


def _retired(source) -> bool:
    _scripts_on_path()
    try:
        from lib.dividend_source_trust import is_retired_source
    except ImportError:  # pragma: no cover
        from scripts.lib.dividend_source_trust import is_retired_source
    return is_retired_source(source)


def yield_for(symbol: str, price_data: dict | None, row: dict | None, now: datetime) -> dict:
    """Trailing yield % = annual dividend / price, or a named gap. Never a guessed number."""
    out = {"div_yield": None, "annual_dividend": None, "source": None, "as_of": None, "yield_gap": None}
    if not row:
        out["yield_gap"] = "no dividend row (sync_dividend_data has not covered this symbol)"
        return out
    out["source"], out["as_of"] = row.get("source"), _aware(row.get("updated_at"))
    annual = _num(row.get("annual_dividend_per_share"))
    price = (price_data or {}).get("price")
    if _retired(row.get("source")):
        out["yield_gap"] = f"dividend row is from a retired provider ({row.get('source')})"
    elif out["as_of"] is None or now - out["as_of"] > timedelta(days=MAX_DIVIDEND_AGE_DAYS):
        out["yield_gap"] = f"dividend row older than {MAX_DIVIDEND_AGE_DAYS} days"
    elif not annual or annual <= 0:
        out["yield_gap"] = "no annual dividend on the dividend row"
    elif not price:
        out["yield_gap"] = "no price to divide the annual dividend by"
    else:
        value = round(annual / price * 100, 2)
        if value > MAX_PLAUSIBLE_YIELD_PCT:
            out["yield_gap"] = f"implausible yield {value}% (annual {annual} / price {price})"
        else:
            out["div_yield"], out["annual_dividend"] = value, annual
    return out


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


def screen(query, *, now: datetime | None = None) -> dict:
    """Score and rank every candidate. Pure given ``query``; writes nothing."""
    now = now or datetime.now(timezone.utc)
    symbols = universe_symbols()
    prices = load_prices(query, symbols)
    dividends = load_dividends(query, symbols)
    candidates = []
    for entries in UNIVERSE.values():
        for e in entries:
            c = dict(e)
            price_data = prices.get(c["symbol"])
            yield_data = yield_for(c["symbol"], price_data, dividends.get(c["symbol"]), now)
            c["price"] = price_data
            c["yield_data"] = yield_data
            c = score_candidate(c, price_data, yield_data)
            c = _generate_thesis(c)
            candidates.append(c)
    candidates.sort(key=lambda x: x.get("total_score", 0), reverse=True)
    with_yield = sum(1 for c in candidates if c["yield_data"]["div_yield"] is not None)
    return {
        "generated_at": now.isoformat(),
        "candidates": candidates,
        "top3": candidates[:3],
        "risk_free_rate": 4.5,  # approximate 4-week T-bill, update periodically
        "coverage": {"universe": len(candidates), "priced": sum(1 for c in candidates if c["price"]),
                     "with_yield": with_yield},
        "note": "Advisory only — the desk presents alternatives; allocation requires operator decision + 2FA.",
    }


def _receipt_lib():
    _scripts_on_path()
    try:
        from lib import lane_last_receipt
    except ImportError:  # pragma: no cover
        from scripts.lib import lane_last_receipt
    return lane_last_receipt


def output_path() -> Path:
    return _receipt_lib().runtime_dir() / OUTPUT_NAME


def write_output(result: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(result, default=str, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _line(result: dict) -> str:
    cov = result["coverage"]
    top = ", ".join(f"{c['symbol']} {c['total_score']} (yield {c['yield_data']['div_yield']})" for c in result["top3"])
    return (f"screened {cov['universe']} vehicles, priced {cov['priced']}, yield known {cov['with_yield']}; "
            f"top: {top}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="read and rank; write nothing (default)")
    mode.add_argument("--apply", action="store_true", help="write the snapshot + lane receipt")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = ap.parse_args(argv)
    lib = _receipt_lib()
    started = lib.now_iso()
    try:
        result = screen(_db_query())
    except Exception as exc:
        if args.apply:
            lib.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                                   script="defense_cash_alternatives.py", error=f"{type(exc).__name__}: {exc}")
        print(f"[cash-alternatives] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, default=str, indent=1))
    gaps = {}
    for c in result["candidates"]:
        gap = c["yield_data"]["yield_gap"]
        if gap:
            gaps[gap.split(" (")[0]] = gaps.get(gap.split(" (")[0], 0) + 1
    if not args.apply:
        print(f"DRY-RUN {LANE_ID}: {_line(result)}; yield gaps {gaps or 'none'}; would write {output_path()}; nothing written")
        return 0
    path = output_path()
    write_output(result, path)
    ok = result["coverage"]["priced"] > 0
    lib.write_lane_receipt(LANE_ID, ok=ok, exit_code=0 if ok else 1, started_at=started,
                           script="defense_cash_alternatives.py", summary={**result["coverage"], "yield_gaps": gaps},
                           produced_count=result["coverage"]["universe"] if ok else 0,
                           attempted_count=result["coverage"]["universe"], skipped_reasons=gaps,
                           output_evidence=[{"path": str(path), "kind": "file"}],
                           empty_reason=None if ok else "no candidate could be priced")
    print(f"[cash-alternatives] {_line(result)}; wrote {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
