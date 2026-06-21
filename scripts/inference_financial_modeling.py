#!/usr/bin/env python3
"""Inference Layers — financial modeling sub-layer.

Valuation primitives for the higher-order layer, with a focus on the operator's
retirement-income use case: CEF/ETF premium/discount to NAV (PTY-style funds).

Refactor note (due diligence): the structure here is adapted from the open-source
finance-skills pattern (anthropics/financial-services "Market Researcher" +
valuation skills, Apache-2.0) — a structured, source-attributed valuation object
with an explicit confidence + data-quality flag — re-implemented in pure Python
against this repo's local data (no Claude plugin install; logic only).

HONESTY GUARANTEE: NAV is only reported as `measured=True` when it comes from a
real data source. When no NAV feed is available the module produces a *qualitative*
premium/discount read via the local LLM and marks `measured=False` with reduced
confidence — it never fabricates a precise NAV number.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

log = logging.getLogger("inference_financial_modeling")

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


def _f(x) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


# ── price discovery (reuse repo canonical sources) ────────────────────────────
def _held_price(symbol: str) -> tuple[Optional[float], bool, Optional[float]]:
    """Return (price, held, market_value) from canonical holdings.json."""
    try:
        h = json.loads((STATE_DIR / "holdings.json").read_text())
        for r in h.get("holdings", []) or []:
            if (r.get("symbol") or "").upper() == symbol.upper():
                return _f(r.get("price")), True, _f(r.get("market_value"))
    except Exception:
        pass
    return None, False, None


def _cache_price(symbol: str) -> Optional[float]:
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return None
        row = _execute(
            "SELECT close_price FROM price_cache WHERE symbol=%s ORDER BY price_date DESC LIMIT 1",
            (symbol.upper(),), fetch="one")
        return _f(row["close_price"]) if row else None
    except Exception:
        return None


def get_price(symbol: str) -> Optional[float]:
    p, _, _ = _held_price(symbol)
    return p if p else _cache_price(symbol)


# ── NAV discovery (measured) ──────────────────────────────────────────────────
_NAV_TABLE_CANDIDATES = [
    ("cef_nav", "nav", "symbol", "as_of"),
    ("fund_nav", "nav", "symbol", "as_of"),
    ("symbol_profiles", "nav", "symbol", "updated_at"),
]


def _measured_nav(symbol: str) -> tuple[Optional[float], Optional[str]]:
    """Best-effort NAV from any present table. Returns (nav, source) or (None, None)."""
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return None, None
        for table, navcol, symcol, tscol in _NAV_TABLE_CANDIDATES:
            exists = _execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name=%s AND column_name=%s LIMIT 1",
                (table, navcol), fetch="one")
            if not exists:
                continue
            row = _execute(
                f"SELECT {navcol} AS nav FROM {table} WHERE {symcol}=%s "
                f"ORDER BY {tscol} DESC LIMIT 1",
                (symbol.upper(),), fetch="one")
            nav = _f(row["nav"]) if row else None
            if nav and nav > 0:
                return nav, table
    except Exception as e:
        log.debug("measured nav probe failed for %s: %s", symbol, e)
    return None, None


# ── public: premium / discount to NAV ─────────────────────────────────────────
def nav_premium_discount(symbol: str, ctx=None, cfg: Optional[dict] = None,
                         force_lane: Optional[str] = None) -> dict:
    """Compute (or qualitatively infer) a fund's premium/discount to NAV.

    Returns a structured, source-attributed valuation object:
        {symbol, price, nav, premium_pct, measured, source, signal,
         direction, confidence, note, reasoning}
    `signal`: rich_premium | fair | attractive_discount | unknown
    """
    cfg = cfg or {}
    price, held, mv = _held_price(symbol)
    if price is None:
        price = _cache_price(symbol)
    nav, nav_src = _measured_nav(symbol)

    out = {
        "symbol": symbol.upper(),
        "price": price,
        "nav": nav,
        "premium_pct": None,
        "measured": bool(nav),
        "held": held,
        "market_value": mv,
        "source": nav_src or "none",
        "signal": "unknown",
        "direction": "neutral",
        "confidence": 0.3,
        "note": "",
        "reasoning": [],
        "lane": "measured" if nav else "local",   # actual LLM lane filled in below
    }

    # Measured path: exact premium/discount math
    if price and nav and nav > 0:
        prem = (price - nav) / nav * 100.0
        out["premium_pct"] = round(prem, 2)
        out["confidence"] = 0.85
        out["source"] = nav_src
        if prem >= 4.0:
            out["signal"], out["direction"] = "rich_premium", "bearish"
            out["note"] = (f"{symbol} trades at a {prem:.1f}% PREMIUM to NAV — rich; "
                           "income buyers risk premium compression. Prefer adds on pullbacks to NAV.")
        elif prem <= -6.0:
            out["signal"], out["direction"] = "attractive_discount", "bullish"
            out["note"] = (f"{symbol} trades at a {abs(prem):.1f}% DISCOUNT to NAV — "
                           "attractive entry for retirement income; mind distribution coverage / ROC.")
        else:
            out["signal"], out["direction"] = "fair", "neutral"
            out["note"] = f"{symbol} near NAV ({prem:+.1f}%) — fairly valued vs NAV."
        out["reasoning"] = [f"price={price}", f"nav={nav} ({nav_src})",
                            f"premium={prem:+.2f}%"]
        return out

    # Qualitative path: no NAV feed -> ask the local LLM, flag as estimate
    if ctx is not None:
        try:
            from inference_hermes_query import proactive_query
            q = (f"For the closed-end/ETF income fund {symbol}, is it currently trading at a "
                 f"PREMIUM or DISCOUNT to NAV, and is its distribution well covered? "
                 f"Current market price is approximately {price if price else 'unknown'}. "
                 f"Give a qualitative read for a retirement-income investor. Be explicit that "
                 f"this is a qualitative estimate, not a measured NAV.")
            ans = proactive_query(ctx, symbol, q, trigger="nav_estimate",
                                  salience=0.5, force_lane=force_lane,
                                  want_keys=["direction", "signal", "note", "confidence", "reasoning"])
            out["direction"] = ans.get("direction", "neutral")
            out["signal"] = ans.get("signal", "unknown")
            out["note"] = (ans.get("note") or ans.get("answer") or "")[:600]
            out["confidence"] = min(0.55, float(ans.get("confidence", 0.4) or 0.4))
            out["source"] = "llm_estimate"
            out["lane"] = ans.get("_lane", "local")   # real lane (grok when routed there)
            out["measured"] = False
            r = ans.get("reasoning")
            out["reasoning"] = r if isinstance(r, list) else [str(r)] if r else []
        except Exception as e:
            log.debug("qualitative nav inference failed for %s: %s", symbol, e)
            out["note"] = "No NAV feed and qualitative inference unavailable."
    else:
        out["note"] = "No NAV data source available; supply a NAV feed for measured premium/discount."
    return out


def scan_income_funds(symbols: list, ctx=None, cfg: Optional[dict] = None) -> list:
    """Run nav_premium_discount across a watch list, sorted by actionability."""
    results = []
    for sym in symbols:
        try:
            results.append(nav_premium_discount(sym, ctx=ctx, cfg=cfg))
        except Exception as e:
            log.warning("nav scan failed for %s: %s", sym, e)
    # actionable (rich/discount, measured first) float to the top
    order = {"attractive_discount": 0, "rich_premium": 1, "fair": 2, "unknown": 3}
    results.sort(key=lambda r: (order.get(r["signal"], 3), not r["measured"],
                                -(r.get("confidence") or 0)))
    return results
