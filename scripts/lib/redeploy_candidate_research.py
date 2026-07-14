"""redeploy_candidate_research — dynamic candidate universe for redeploy plans (Part C).

Replaces the hardcoded sector→ETF recipe as the *research* layer: candidates are
assembled from live system sources, scored on locally cached data, and every
exclusion carries a rejection reason. Advisory only.

Sources:
  holdings.json                     current positions (incl. overlap math)
  watchlist_items (DB)              active watchlist w/ Hermes composite scores
  hermes_discovery_candidates (DB)  approved discovery symbols
  cio_decisions (DB)                recent CIO actions/confidence per symbol
  reference ETF roster              sector/factor/income/bond vehicles (research
                                    starting set, not the answer — everything
                                    competes on the same metrics)
  ticker_prices/-dividends (DB)     5y local history (yfinance-backfilled)
  instrument_facts (DB)             expense ratio / yield / category, provenance-tagged
  fund_lookthrough.json             fund/ETF underlying holdings + sector weights
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.redeploy_data_truth import STATE, _as_float, _load_json
from lib.redeploy_price_history import (
    correlation,
    get_instrument_facts,
    load_closes,
    load_dividends,
    max_drawdown_pct,
    annualized_vol_pct,
    beta_vs,
    standard_windows,
    total_return_series,
)

ENGINE_VERSION = "candidate_research_1.1.0"

_CUSIP_RE = re.compile(r"^[0-9]{2}")

# Research starting roster — every candidate still competes on live metrics and
# can be rejected; this is coverage insurance so income/bond/factor lanes always
# have entrants even when the watchlist is equity-heavy.
REFERENCE_ROSTER = {
    "sector_etf": ["XLK", "XLC", "XLF", "XLY", "XLV", "XLI", "XLP", "XLE", "XLB", "XLU", "XLRE"],
    "broad_etf": ["SPY", "VOO", "VTI", "QQQ", "QQQM", "IWM", "SCHG"],
    "factor_etf": ["VTV", "VUG", "MTUM", "QUAL", "USMV"],
    "income_etf": ["SCHD", "VYM", "DVY", "HDV", "JEPI", "JEPQ"],
    "bond_cash": ["BND", "AGG", "SHY", "TLT", "SGOV", "BIL"],
    "theme_etf": ["ITA", "XAR", "PPA"],
    # Tradable index mutual funds — NTF at the brokers that hold the accounts
    # (Schwab SW*, Fidelity FXAIX/FZROX). They compete on the same live metrics.
    "mutual_fund": ["SWPPX", "SWTSX", "SWAGX", "FXAIX", "FZROX"],
}

MIN_HISTORY_DAYS = 120
MAX_CANDIDATES = 120


def _holdings() -> list[dict[str, Any]]:
    return _load_json(Path(STATE) / "holdings.json", {}).get("holdings") or []


def _lookthrough() -> dict[str, Any]:
    return _load_json(Path(STATE) / "fund_lookthrough.json", {}) or {}


def _asset_class(sym: str, facts: dict[str, Any], role_hint: str) -> str:
    qt = (facts.get("quote_type") or "").upper()
    cat = (facts.get("category") or "").lower()
    if role_hint == "bond_cash" or "bond" in cat or sym in ("BND", "AGG", "SHY", "TLT"):
        return "fixed_income"
    if sym in ("SGOV", "BIL"):
        return "cash_equivalent"
    if qt == "EQUITY":
        return "equity"
    if qt in ("ETF", "MUTUALFUND"):
        return "fund"
    return "unknown"


def assemble_universe(cur) -> list[dict[str, Any]]:
    """Union of live sources; provenance kept per candidate."""
    seen: dict[str, dict[str, Any]] = {}

    def add(sym: str, source: str, extra: dict[str, Any] | None = None):
        sym = str(sym or "").upper().strip()
        if not sym or _CUSIP_RE.match(sym) or "-" in sym:
            return  # CUSIPs / private-fund tickers have no market data lane
        row = seen.setdefault(sym, {"symbol": sym, "sources": [], "role_hint": None})
        if source not in row["sources"]:
            row["sources"].append(source)
        if extra:
            row.update({k: v for k, v in extra.items() if v is not None})

    for h in _holdings():
        if not h.get("is_cash"):
            add(h.get("symbol"), "holding", {"held_market_value": _as_float(h.get("market_value"))})

    cur.execute(
        """SELECT upper(symbol), asset_type, hermes_composite_score, score
           FROM watchlist_items WHERE status='active'"""
    )
    for sym, atype, hscore, score in cur.fetchall():
        add(sym, "watchlist", {"watch_asset_type": atype,
                               "hermes_score": float(hscore) if hscore is not None else None,
                               "watch_score": float(score) if score is not None else None})

    cur.execute(
        """SELECT DISTINCT unnest(extracted_symbols) FROM hermes_discovery_candidates
           WHERE status IN ('approved','promoted') AND extracted_symbols IS NOT NULL"""
    )
    for (sym,) in cur.fetchall():
        add(sym, "hermes_discovery")

    cur.execute(
        """SELECT DISTINCT ON (upper(symbol)) upper(symbol), action, confidence_calibrated
           FROM cio_decisions
           WHERE created_at > NOW() - INTERVAL '90 days' AND symbol IS NOT NULL
           ORDER BY upper(symbol), created_at DESC"""
    )
    for sym, action, conf in cur.fetchall():
        add(sym, "cio_decision", {"cio_action": action,
                                  "cio_confidence": float(conf) if conf is not None else None})

    for role, syms in REFERENCE_ROSTER.items():
        for sym in syms:
            add(sym, f"roster:{role}", {"role_hint": role})

    return list(seen.values())


def profile_candidate(cur, cand: dict[str, Any], *,
                      sold_closes: list, bench_closes: list,
                      facts_map: dict[str, dict[str, Any]],
                      held_by_symbol: dict[str, float],
                      lookthrough: dict[str, Any]) -> dict[str, Any]:
    sym = cand["symbol"]
    from lib.redeploy_price_history import clean_after_breaks
    closes, integrity_notes = clean_after_breaks(load_closes(cur, sym))
    facts = facts_map.get(sym, {})
    out = dict(cand)
    out["history_days"] = len(closes)
    if integrity_notes:
        out["series_integrity_notes"] = integrity_notes

    if len(closes) < MIN_HISTORY_DAYS:
        out["rejected"] = True
        out["rejection_reason"] = (
            f"insufficient local history ({len(closes)}d < {MIN_HISTORY_DAYS}d) — "
            "backfill failed or instrument not market-quoted"
        )
        return out

    divs = load_dividends(cur, sym)
    tr = total_return_series(closes, divs)
    lt = lookthrough.get(sym) or {}

    out.update({
        "rejected": False,
        "asset_class": _asset_class(sym, facts, str(cand.get("role_hint") or "")),
        "name": facts.get("instrument_name"),
        "category": facts.get("category"),
        "price": closes[-1][1],
        "price_as_of": str(closes[-1][0]),
        "expense_ratio_pct": facts.get("expense_ratio_pct"),
        "distribution_yield_pct": facts.get("distribution_yield_pct"),
        "price_return": standard_windows(closes),
        "total_return": standard_windows(tr) if divs else None,
        "volatility_1y_pct": annualized_vol_pct(closes),
        "max_drawdown": max_drawdown_pct(closes),
        "beta_1y_vs_spy": beta_vs(closes, bench_closes),
        "correlation_to_sold": correlation(closes, sold_closes) if sold_closes else None,
        "correlation_to_bench": correlation(closes, bench_closes),
        "held_overlap_usd": held_by_symbol.get(sym, 0.0),
        "lookthrough_sectors": lt.get("sector_weights") or facts.get("sector_weights"),
        "lookthrough_top_holdings": ((lt.get("top_holdings") or facts.get("top_holdings") or [])[:10]) or None,
        "data_provenance": {
            "prices": "ticker_prices (market_quotes + yfinance 5y backfill)",
            "distributions": f"ticker_dividends ({len(divs)} ex-dates)" if divs else "none cached",
            "facts_fetched_at": str(facts.get("fetched_at")) if facts.get("fetched_at") else None,
        },
    })
    return out


def build_candidates(cur, *, sold_symbol: str | None = None,
                     bench_symbol: str = "SPY") -> dict[str, Any]:
    universe = assemble_universe(cur)[:MAX_CANDIDATES * 3]
    sold_closes = load_closes(cur, sold_symbol) if sold_symbol else []
    bench_closes = load_closes(cur, bench_symbol)
    facts_map = get_instrument_facts(cur, [c["symbol"] for c in universe])
    held = {str(h.get("symbol") or "").upper(): _as_float(h.get("market_value"))
            for h in _holdings() if not h.get("is_cash")}
    lookthrough = _lookthrough()

    profiled = [
        profile_candidate(cur, c, sold_closes=sold_closes, bench_closes=bench_closes,
                          facts_map=facts_map, held_by_symbol=held, lookthrough=lookthrough)
        for c in universe
    ]
    accepted = [p for p in profiled if not p.get("rejected")]
    rejected = [p for p in profiled if p.get("rejected")]

    if sold_symbol:
        for p in accepted:
            if p["symbol"] == sold_symbol.upper():
                p["rejected"] = True
                p["rejection_reason"] = "this is the sold instrument"
        rejected += [p for p in accepted if p.get("rejected")]
        accepted = [p for p in accepted if not p.get("rejected")]

    accepted.sort(key=lambda p: (
        -(p.get("hermes_score") or 0),
        -(len(p.get("sources") or [])),
        p["symbol"],
    ))
    _attach_catalysts(cur, accepted[:MAX_CANDIDATES])
    for p in accepted[:MAX_CANDIDATES]:
        p["geopolitical_sensitivity"] = _geo_sensitivity(p["symbol"], p.get("role_hint"))
    return {
        "ok": True,
        "advisory_only": True,
        "engine_version": ENGINE_VERSION,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "sold_symbol": sold_symbol,
        "benchmark": bench_symbol,
        "universe_size": len(universe),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "candidates": accepted[:MAX_CANDIDATES],
        "rejected": [
            {"symbol": p["symbol"], "sources": p["sources"],
             "reason": p["rejection_reason"]} for p in rejected
        ],
        "source_breakdown": _source_breakdown(universe),
    }


def _attach_catalysts(cur, candidates: list[dict[str, Any]]) -> None:
    """Observed catalysts, last 30 days, top-3 by impact — from catalyst_events.

    This is a REALIZED catalyst record; no forward corporate calendar source is
    connected, so upcoming_events is reported unavailable rather than guessed."""
    syms = [c["symbol"] for c in candidates]
    by_sym: dict[str, list[dict[str, Any]]] = {}
    if syms:
        try:
            cur.execute(
                """SELECT symbol, catalyst_type, headline, impact_score, published_at
                   FROM (
                     SELECT upper(symbol) AS symbol, catalyst_type, headline, impact_score,
                            published_at,
                            ROW_NUMBER() OVER (PARTITION BY upper(symbol)
                                               ORDER BY impact_score DESC NULLS LAST,
                                                        published_at DESC) rn
                     FROM catalyst_events
                     WHERE upper(symbol) = ANY(%s)
                       AND published_at > NOW() - INTERVAL '30 days'
                   ) t WHERE rn <= 3""",
                (syms,),
            )
            for sym, ctype, headline, impact, pub in cur.fetchall():
                by_sym.setdefault(sym, []).append({
                    "type": ctype, "headline": (headline or "")[:160],
                    "impact_score": float(impact) if impact is not None else None,
                    "published_at": pub.isoformat() if pub else None,
                })
        except Exception:
            by_sym = {}
    for c in candidates:
        c["recent_catalysts_30d"] = by_sym.get(c["symbol"], [])
        c["upcoming_events"] = "unavailable — no forward corporate-calendar source connected"


def _geo_sensitivity(symbol: str, role_hint: str | None) -> dict[str, Any]:
    """Geopolitical sensitivity from the deploy intelligence sleeve map — honest 'unassessed' otherwise."""
    try:
        from lib.deploy_intelligence_engine import _ETF_SLEEVE_MAP, _GEOPOLITICAL_SLEEVE_BIAS
    except ImportError:
        return {"level": "unassessed", "basis": "sleeve map unavailable"}
    sleeve = _ETF_SLEEVE_MAP.get(symbol.upper())
    if sleeve is None and role_hint == "theme_etf":
        sleeve = "Defense / Aerospace"
    if sleeve is None:
        return {"level": "unassessed", "basis": "symbol not in the geopolitical sleeve map — not scored, not zero"}
    elevated = _GEOPOLITICAL_SLEEVE_BIAS.get("elevated", {})
    return {
        "level": "beneficiary_when_elevated" if sleeve in elevated else "mapped_neutral",
        "sleeve": sleeve,
        "basis": "deploy_intelligence_engine sleeve map (same source as the desk's geopolitical scoring)",
    }


def _source_breakdown(universe: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in universe:
        for s in c["sources"]:
            key = s.split(":")[0]
            counts[key] = counts.get(key, 0) + 1
    return counts
