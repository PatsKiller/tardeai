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
import os
import re
from datetime import date, datetime, timezone
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

ENGINE_VERSION = "candidate_research_1.2.0"

_CUSIP_RE = re.compile(r"^[0-9]{2}")

# Ticker shape: 1-5 uppercase letters, optional class suffix (BRK.B style).
_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")

# Common English words / financial jargon that pass the ticker regex but arrive
# as prose tokens from hermes_discovery_candidates.extracted_symbols (observed:
# FORUM, WOULD, OWN, TOO, UNI). Corroboration in the security-master sets
# OVERRIDES this list — real tickers that happen to be words (e.g. ALL, IT)
# stay valid whenever any live system source already tracks them.
PROSE_BLACKLIST = frozenset({
    "FORUM", "WOULD", "OWN", "TOO", "UNI", "THE", "AND", "FOR", "ARE", "ALL",
    "NEW", "NOW", "CAN", "ONE", "TWO", "BUY", "SELL", "HOLD", "GOOD", "BEST",
    "WILL", "HAVE", "THIS", "THAT", "WITH", "FROM", "JUST", "LIKE", "VERY",
    "MUCH", "WELL", "ALSO", "INTO", "OVER", "DOWN", "ONLY", "SOME", "WHAT",
    "WHEN", "MORE", "LESS", "HIGH", "LOW", "BIG", "TOP", "USA", "USD", "ETF",
    "IPO", "CEO", "CFO", "SEC", "FED", "GDP", "CPI", "AI", "EV", "IT", "US",
    "UK", "EU", "PM", "AM", "Q1", "Q2", "Q3", "Q4", "YOY", "EPS", "PE",
})

# Auto-backfill cost cap per build_candidates run (defect 19).
AUTO_BACKFILL_MAX = 15

# ticker_prices.source values written by the deep 5Y backfill. Everything else
# (market_quotes, finviz, holdings, portfolio_repricer) is live-quote drip that
# starts accumulating whenever capture first saw the symbol — MSFT with 72
# finviz drip rows is NOT a young instrument, it was simply never backfilled.
_BACKFILL_SOURCES = ("yfinance", "price_cache_backfill")

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


_ROSTER_SYMBOLS = frozenset(s for syms in REFERENCE_ROSTER.values() for s in syms)


def _corroborated_symbols(cur) -> dict[str, set[str]]:
    """Security-master corroboration sets, built once per assemble_universe
    call (one cheap SELECT DISTINCT per table).

    'market' (hard): holdings, roster, market_quotes, ticker_prices,
      instrument_facts — a provider actually returned data for the symbol.
    'text' (soft): watchlist_items — symbol text written downstream of the
      same discovery pipeline that produces prose tokens (FORUM/WOULD/UNI were
      observed IN watchlist_items), so it corroborates ordinary symbols but
      cannot override the prose blacklist."""
    market: set[str] = set(_ROSTER_SYMBOLS)
    for h in _holdings():
        s = str(h.get("symbol") or "").upper().strip()
        if s:
            market.add(s)
    for sql in (
        "SELECT DISTINCT upper(symbol) FROM market_quotes WHERE symbol IS NOT NULL",
        "SELECT DISTINCT upper(symbol) FROM ticker_prices WHERE symbol IS NOT NULL",
        "SELECT DISTINCT upper(symbol) FROM instrument_facts WHERE symbol IS NOT NULL",
    ):
        cur.execute(sql)
        market.update(r[0] for r in cur.fetchall() if r[0])
    cur.execute("SELECT DISTINCT upper(symbol) FROM watchlist_items WHERE symbol IS NOT NULL")
    text = {r[0] for r in cur.fetchall() if r[0]}
    return {"market": market, "text": text}


def validate_symbol(cur, sym: str,
                    corroborated: dict[str, set[str]] | None = None) -> tuple[bool, str]:
    """Security-master validation for intake symbols (defect 18).

    Returns (valid, detail). When valid, detail is the provenance tag
    'corroborated' or 'uncorroborated'; when invalid, detail is the reason.
    Decision order: regex → market-data corroboration (wins over the prose
    blacklist — real tickers that are words, e.g. OWN, stay valid) → prose
    blacklist → text corroboration → uncorroborated-but-plausible."""
    sym = str(sym or "").upper().strip()
    if not sym or not _SYMBOL_RE.match(sym):
        return False, "fails ticker pattern (1-5 letters, optional .X class suffix)"
    if corroborated is None:
        corroborated = _corroborated_symbols(cur)
    if sym in corroborated["market"]:
        return True, "corroborated"
    if sym in PROSE_BLACKLIST:
        return False, ("prose token — common English word with no market-data "
                       "corroboration (text-only sources cannot vouch: the "
                       "watchlist inherits discovery's extraction noise)")
    if sym in corroborated["text"]:
        return True, "corroborated"
    return True, "uncorroborated"


def assemble_universe(cur) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Union of live sources; provenance kept per candidate.

    Returns (universe, excluded_at_intake): symbols rejected at intake are
    reported, never silently dropped."""
    seen: dict[str, dict[str, Any]] = {}
    excluded: dict[str, dict[str, Any]] = {}
    corroborated = _corroborated_symbols(cur)

    def _exclude(sym: str, source: str, code: str, reason: str):
        row = excluded.setdefault(
            sym, {"symbol": sym, "code": code, "reason": reason, "sources": []})
        if source not in row["sources"]:
            row["sources"].append(source)

    def add(sym: str, source: str, extra: dict[str, Any] | None = None):
        sym = str(sym or "").upper().strip()
        if not sym:
            return
        if sym in excluded:
            _exclude(sym, source, excluded[sym]["code"], excluded[sym]["reason"])
            return
        if _CUSIP_RE.match(sym) or "-" in sym:
            # CUSIPs / private-fund tickers have no market data lane
            _exclude(sym, source, "UNSUPPORTED_INSTRUMENT",
                     "CUSIP / private-fund identifier — no market data lane")
            return
        row = seen.get(sym)
        if row is None:
            ok, detail = validate_symbol(cur, sym, corroborated)
            if not ok:
                _exclude(sym, source, "INVALID_SYMBOL", detail)
                return
            row = seen[sym] = {"symbol": sym, "sources": [], "role_hint": None,
                               "symbol_provenance": detail}
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

    return list(seen.values()), list(excluded.values())


def profile_candidate(cur, cand: dict[str, Any], *,
                      sold_closes: list, bench_closes: list,
                      facts_map: dict[str, dict[str, Any]],
                      held_by_symbol: dict[str, float],
                      lookthrough: dict[str, Any]) -> dict[str, Any]:
    sym = cand["symbol"]
    from lib.redeploy_price_history import clean_after_breaks
    raw_closes = load_closes(cur, sym)
    closes, integrity_notes = clean_after_breaks(raw_closes)
    facts = facts_map.get(sym, {})
    out = dict(cand)
    out["history_days"] = len(closes)
    if integrity_notes:
        out["series_integrity_notes"] = integrity_notes

    if len(closes) < MIN_HISTORY_DAYS:
        # Classified exclusion (defect 19) — one bucket hid three distinct
        # truths: never-backfilled, genuinely young, and gapped cache.
        out["rejected"] = True
        cur.execute(
            "SELECT COUNT(*) FROM ticker_prices WHERE symbol=%s AND source = ANY(%s)",
            (sym, list(_BACKFILL_SOURCES)),
        )
        backfill_rows = int(cur.fetchone()[0])
        if not raw_closes or backfill_rows == 0:
            out["rejection_code"] = "HISTORY_NOT_LOADED"
            out["rejection_reason"] = (
                "5Y local backfill has never loaded this symbol"
                + (" (cache rows are live-quote drip only)" if raw_closes else "")
                + " — not an instrument judgment; retry backfill"
            )
        else:
            first_date = raw_closes[0][0]
            age_days = (date.today() - first_date).days
            if age_days < MIN_HISTORY_DAYS * 1.5:
                out["rejection_code"] = "INSUFFICIENT_TRADING_HISTORY"
                out["rejection_reason"] = (
                    f"young instrument — first cached bar {first_date} "
                    f"({age_days} calendar days ago; {len(closes)}d < {MIN_HISTORY_DAYS}d)"
                )
            elif integrity_notes:
                out["rejection_code"] = "HISTORY_GAPPED"
                out["rejection_reason"] = (
                    f"price-basis break in cached series (mixed adjusted/unadjusted "
                    f"sources) — only {len(closes)}d usable after the last break "
                    f"< {MIN_HISTORY_DAYS}d; cache repair needed, not an instrument judgment"
                )
            else:
                out["rejection_code"] = "HISTORY_GAPPED"
                out["rejection_reason"] = (
                    f"cache has old fragments — backfill incomplete "
                    f"(first bar {first_date}, only {len(closes)}d usable "
                    f"< {MIN_HISTORY_DAYS}d)"
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


def _attempt_auto_backfill(cur, profiled: list[dict[str, Any]],
                           universe: list[dict[str, Any]],
                           profile_kwargs: dict[str, Any],
                           facts_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Auto-backfill HISTORY_NOT_LOADED candidates that a non-discovery source
    vouches for (holding/watchlist/cio_decision/roster), cap AUTO_BACKFILL_MAX
    per run, then re-profile just those. This is the one sanctioned write path
    (existing yfinance price/dividend/facts cache). Discovery-only symbols are
    never auto-backfilled (cost control)."""
    provider_status: dict[str, Any] = {"attempted": [], "filled": [], "failed": []}

    def _vouched(p: dict[str, Any]) -> bool:
        return any(s in ("holding", "watchlist", "cio_decision") or s.startswith("roster:")
                   for s in (p.get("sources") or []))

    needs = [p for p in profiled
             if p.get("rejection_code") == "HISTORY_NOT_LOADED" and _vouched(p)]
    # Under the cap, spend the budget on the most-vouched symbols first.
    needs.sort(key=lambda p: (-len(p.get("sources") or []), p["symbol"]))
    needs = needs[:AUTO_BACKFILL_MAX]

    # Annotate the not-attempted remainder honestly.
    attempted_syms = {p["symbol"] for p in needs}
    for p in profiled:
        if p.get("rejection_code") != "HISTORY_NOT_LOADED" or p["symbol"] in attempted_syms:
            continue
        if not _vouched(p) and p.get("symbol_provenance") == "uncorroborated":
            p["rejection_reason"] += (
                " — uncorroborated discovery symbol — backfill on operator request")

    if not needs or os.environ.get("TRADE_AI_CI"):
        return provider_status

    from lib.redeploy_price_history import backfill_symbol_history
    syms = sorted(attempted_syms)
    provider_status["attempted"] = syms
    try:
        bf = backfill_symbol_history(syms)
    except Exception as e:  # provider blow-up must not kill the research run
        bf = {"error": f"{type(e).__name__}: {e}", "filled": []}
    filled_syms = {f["symbol"] for f in (bf.get("filled") or []) if isinstance(f, dict)}
    provider_error = bf.get("error")

    if filled_syms:
        facts_map.update(get_instrument_facts(cur, sorted(filled_syms)))
    uni_by_sym = {c["symbol"]: c for c in universe}
    idx_by_sym = {p["symbol"]: i for i, p in enumerate(profiled)}
    for p in needs:
        sym = p["symbol"]
        if sym in filled_syms:
            rep = profile_candidate(
                cur, uni_by_sym[sym], facts_map=facts_map, **profile_kwargs)
            if rep.get("rejection_code") == "HISTORY_NOT_LOADED":
                # Provider answered but no usable price rows landed
                # (empty/zero-price data) — that is a provider failure.
                rep["rejection_code"] = "HISTORY_PROVIDER_FAILED"
                rep["rejection_reason"] = (
                    "auto-backfill ran but the provider returned no usable "
                    "price rows for this symbol"
                )
                provider_status["failed"].append(sym)
            else:
                provider_status["filled"].append(sym)
            profiled[idx_by_sym[sym]] = rep
        else:
            provider_status["failed"].append(sym)
            p["rejection_code"] = "HISTORY_PROVIDER_FAILED"
            p["rejection_reason"] = (
                "auto-backfill attempted and the provider failed: "
                + (str(provider_error) if provider_error
                   else "yfinance returned no data for this symbol")
            )
    return provider_status


def build_candidates(cur, *, sold_symbol: str | None = None,
                     bench_symbol: str = "SPY",
                     auto_backfill: bool = True) -> dict[str, Any]:
    universe, excluded_at_intake = assemble_universe(cur)
    universe = universe[:MAX_CANDIDATES * 3]
    sold_closes = load_closes(cur, sold_symbol) if sold_symbol else []
    bench_closes = load_closes(cur, bench_symbol)
    facts_map = get_instrument_facts(cur, [c["symbol"] for c in universe])
    held = {str(h.get("symbol") or "").upper(): _as_float(h.get("market_value"))
            for h in _holdings() if not h.get("is_cash")}
    lookthrough = _lookthrough()
    profile_kwargs = dict(sold_closes=sold_closes, bench_closes=bench_closes,
                          held_by_symbol=held, lookthrough=lookthrough)

    profiled = [
        profile_candidate(cur, c, facts_map=facts_map, **profile_kwargs)
        for c in universe
    ]

    provider_status: dict[str, Any] = {"attempted": [], "filled": [], "failed": []}
    if auto_backfill:
        provider_status = _attempt_auto_backfill(
            cur, profiled, universe, profile_kwargs, facts_map)

    accepted = [p for p in profiled if not p.get("rejected")]
    rejected = [p for p in profiled if p.get("rejected")]

    if sold_symbol:
        for p in accepted:
            if p["symbol"] == sold_symbol.upper():
                p["rejected"] = True
                p["rejection_code"] = "SOLD_INSTRUMENT"
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
             "code": p.get("rejection_code"),
             "reason": p["rejection_reason"]} for p in rejected
        ],
        "excluded_at_intake": excluded_at_intake,
        "provider_status": provider_status,
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
