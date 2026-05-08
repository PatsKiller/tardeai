#!/usr/bin/env python3
"""multi_strategy_classifier.py — Classify symbols against ALL strategies.

Tickers can match multiple strategies simultaneously. Two-phase approach:
  Phase 1: Deterministic filter matching (screen_filters in YAML)
  Phase 2: LLM-assisted classification for unmatched/ambiguous symbols

Fully dynamic — discovers strategies from config/strategies/*.yaml at runtime.
Scales to 40+ strategies without code changes.

Usage:
    .venv/bin/python scripts/multi_strategy_classifier.py --symbol AAPL
    .venv/bin/python scripts/multi_strategy_classifier.py --batch --limit 50
    .venv/bin/python scripts/multi_strategy_classifier.py --batch --llm --limit 20
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger("multi_strategy_classifier")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# Schema/utility files to exclude
_SKIP_YAMLS = {'strategy_schema', 'recommendation_schema', 'shared_risk_rules'}

ENRICHMENT_CACHE_PATH = PROJECT_ROOT / "data" / "state" / "ticker_enrichment_cache.json"


def load_enrichment_cache() -> dict[str, dict]:
    """Load the Finviz enrichment cache (60+ fields per symbol)."""
    try:
        with open(ENRICHMENT_CACHE_PATH) as f:
            cache = json.load(f)
        log.info("Loaded enrichment cache: %d symbols", len(cache))
        return cache
    except Exception as e:
        log.warning("Cannot load enrichment cache: %s", e)
        return {}


def merge_scan_with_enrichment(scan: dict, enrichment: dict) -> dict:
    """Merge scan data with enrichment cache data for richer classification.

    Enrichment data provides: div_yield_pct, market_cap_b, rsi, sma20_pct,
    sma50_pct, sma200_pct, week52_high_pct, week52_low_pct, roe_pct,
    pe, beta, atr, short_float_pct, sector, industry, perf_month_pct, etc.
    """
    merged = dict(scan)  # start with scan data
    sym = scan.get("symbol", "").upper()
    enrich = enrichment.get(sym, {})
    if not enrich:
        return merged

    # Only fill in fields the scan doesn't already have
    for key in enrich:
        if key in ('cached_at', 'ticker', 'symbol'):
            continue
        if key not in merged or merged[key] is None:
            merged[key] = enrich[key]

    return merged


# ── Dynamic strategy loading ──────────────────────────────────────────

def load_all_strategies() -> dict[str, dict]:
    """Load all strategy configs from config/strategies/*.yaml."""
    strategies = {}
    strategies_dir = PROJECT_ROOT / "config" / "strategies"
    for path in sorted(strategies_dir.glob("*.yaml")):
        if path.stem in _SKIP_YAMLS:
            continue
        try:
            with open(path) as f:
                cfg = yaml.safe_load(f) or {}
            cfg['_file'] = str(path)
            strategies[path.stem] = cfg
        except Exception as e:
            log.warning("Failed to load %s: %s", path.name, e)
    log.info("Loaded %d strategy configs", len(strategies))
    return strategies


# ── Phase 1: Deterministic filter matching ────────────────────────────

def match_filters(scan: dict, filters: dict) -> tuple[bool, list[str], list[str]]:
    """Check scan data against screen_filters using ALL available enrichment data.

    Uses: price, rvol, float, gap, score (from screener)
    Plus: div_yield, market_cap, rsi, sma50, week52_high_pct, roe, pe, sector,
          beta, short_float_pct, etc. (from Finviz enrichment cache)

    Requires at least 2 positive match criteria to avoid false positives.
    """
    match_reasons = []
    reject_reasons = []

    # ── Core screener fields ──
    price = float(scan.get("price") or 0)
    rvol = float(scan.get("rvol") or 0)
    float_m = float(scan.get("float_m") or 0)
    gap = abs(float(scan.get("gap_pct") or 0))
    score = float(scan.get("score") or 0)

    # ── Enrichment fields (from Finviz cache) ──
    div_yield = scan.get("div_yield_pct")
    market_cap_b = scan.get("market_cap_b")
    rsi = scan.get("rsi")
    sma20_pct = scan.get("sma20_pct")
    sma50_pct = scan.get("sma50_pct")
    sma200_pct = scan.get("sma200_pct")
    week52_high_pct = scan.get("week52_high_pct")
    week52_low_pct = scan.get("week52_low_pct")
    roe_pct = scan.get("roe_pct")
    pe = scan.get("pe")
    beta = scan.get("beta")
    sector = scan.get("sector")
    industry = scan.get("industry")
    short_float_pct = scan.get("short_float_pct")

    # ── Price range ──
    min_price = float(filters.get("min_price", 0))
    max_price = float(filters.get("max_price", 99999))
    if price > 0:
        if price < min_price:
            reject_reasons.append(f"price ${price:.2f} < min ${min_price}")
        elif price > max_price:
            reject_reasons.append(f"price ${price:.2f} > max ${max_price}")
        else:
            match_reasons.append(f"price ${price:.2f} in range")

    # ── RVOL ──
    min_rvol = float(filters.get("min_rvol", 0))
    if min_rvol > 0:
        if rvol > 0 and rvol < min_rvol:
            reject_reasons.append(f"rvol {rvol:.1f} < min {min_rvol}")
        elif rvol >= min_rvol:
            match_reasons.append(f"rvol {rvol:.1f}x")

    # ── Float ──
    max_float_m = float(filters.get("max_float_m", 99999))
    if max_float_m < 99999 and float_m > 0:
        if float_m > max_float_m:
            reject_reasons.append(f"float {float_m:.0f}M > max {max_float_m}")
        else:
            match_reasons.append(f"float {float_m:.0f}M")

    # ── Gap ──
    min_gap = float(filters.get("min_gap_pct", 0))
    if min_gap > 0:
        if gap > 0 and gap < min_gap:
            reject_reasons.append(f"gap {gap:.1f}% < min {min_gap}%")
        elif gap >= min_gap:
            match_reasons.append(f"gap {gap:.1f}%")

    # ── Score ──
    min_score = float(filters.get("min_score", 0))
    if min_score > 0:
        if score < min_score:
            reject_reasons.append(f"score {score:.0f} < min {min_score}")
        else:
            match_reasons.append(f"score {score:.0f}")

    # ── Dividend yield (income strategies) ──
    min_yield = filters.get("min_yield")
    if min_yield is not None:
        min_yield = float(min_yield)
        if div_yield is not None:
            div_yield_f = float(div_yield)
            if div_yield_f < min_yield:
                reject_reasons.append(f"yield {div_yield_f:.1f}% < min {min_yield}%")
            else:
                match_reasons.append(f"yield {div_yield_f:.1f}%")
        else:
            reject_reasons.append(f"yield data unavailable (need {min_yield}%)")

    # ── Market cap (core/large-cap strategies) ──
    min_cap = filters.get("min_market_cap_b")
    if min_cap is not None:
        min_cap = float(min_cap)
        if market_cap_b is not None:
            cap_f = float(market_cap_b)
            if cap_f < min_cap:
                reject_reasons.append(f"cap ${cap_f:.1f}B < min ${min_cap}B")
            else:
                match_reasons.append(f"cap ${cap_f:.1f}B")
        else:
            reject_reasons.append("market cap data unavailable")

    # ── RSI (entry timing) ──
    entry_rsi_max = filters.get("entry_rsi_max")
    if entry_rsi_max is not None and rsi is not None:
        rsi_f = float(rsi)
        if rsi_f > float(entry_rsi_max):
            reject_reasons.append(f"RSI {rsi_f:.0f} > max {entry_rsi_max}")
        else:
            match_reasons.append(f"RSI {rsi_f:.0f}")

    # ── SMA50 (below SMA = dip buy entry) ──
    if filters.get("entry_below_sma_50") and sma50_pct is not None:
        sma50_f = float(sma50_pct)
        if sma50_f > 0:
            reject_reasons.append(f"price above SMA50 ({sma50_f:+.1f}%)")
        else:
            match_reasons.append(f"below SMA50 ({sma50_f:+.1f}%)")

    # ── 52-week high distance (recovery candidates) ──
    max_pct_52w = filters.get("max_pct_from_52w_high")
    if max_pct_52w is not None and week52_high_pct is not None:
        w52_f = float(week52_high_pct)
        thresh = float(max_pct_52w)
        if w52_f > thresh:  # thresh is negative, e.g. -30
            reject_reasons.append(f"only {w52_f:.0f}% from 52w high (need {thresh}%+)")
        else:
            match_reasons.append(f"{w52_f:.0f}% from 52w high")

    # ── Sector filter ──
    sector_filter = filters.get("sector_filter")
    if sector_filter and isinstance(sector_filter, list):
        scan_sector = (sector or "").lower()
        scan_industry = (industry or "").lower()
        sector_match = any(
            sf.lower() in scan_sector or sf.lower() in scan_industry
            for sf in sector_filter
        )
        if sector_match:
            match_reasons.append(f"sector match: {sector}")
        else:
            reject_reasons.append(f"sector '{sector}' not in {sector_filter}")

    # ── Dividend growth years (from fundamental_data, not in cache — skip if missing) ──
    min_div_years = filters.get("min_dividend_growth_years")
    if min_div_years is not None:
        # Not available from Finviz enrichment — don't reject, just note
        # LLM phase can assess this
        pass

    # ── IV rank (for options strategies — not in Finviz cache) ──
    min_iv_rank = filters.get("min_iv_rank")
    if min_iv_rank is not None:
        # Not available — skip deterministic, defer to LLM
        pass

    # ── Quality focus (core growth) ──
    if filters.get("quality_focus") and roe_pct is not None:
        roe_f = float(roe_pct)
        if roe_f > 15:
            match_reasons.append(f"ROE {roe_f:.0f}%")
        elif roe_f < 0:
            reject_reasons.append(f"ROE {roe_f:.0f}% negative")

    # ── Payout ratio (income strategies) ──
    max_payout = filters.get("max_payout_ratio")
    if max_payout is not None:
        # Not directly in Finviz cache — defer to LLM
        pass

    # ── Strategies requiring portfolio context (not from scan data) ──
    if filters.get("requires_shares_owned"):
        reject_reasons.append("requires existing position")
    if filters.get("requires_unrealized_loss"):
        reject_reasons.append("requires unrealized loss")
    if filters.get("thesis_driven"):
        reject_reasons.append("thesis-driven: requires LLM classification")

    # ── Asset type filter (ETF/fund strategies) ──
    if filters.get("asset_type"):
        allowed = filters["asset_type"]
        scan_type = scan.get("asset_type", "equity")
        if scan_type not in allowed:
            reject_reasons.append(f"asset_type {scan_type} not in {allowed}")

    # ── Relative strength (sector rotation) ──
    min_rs = filters.get("min_relative_strength_vs_spy")
    if min_rs is not None:
        vs_sector = scan.get("vs_sector_pct")
        perf_month = scan.get("perf_month_pct")
        if vs_sector is not None:
            vs_f = float(vs_sector)
            if vs_f >= float(min_rs) * 100:
                match_reasons.append(f"relative strength +{vs_f:.1f}%")
            else:
                reject_reasons.append(f"relative strength {vs_f:.1f}% too low")
        elif perf_month is not None:
            # Fallback: use 1m performance as proxy
            perf_f = float(perf_month)
            if perf_f > float(min_rs) * 100:
                match_reasons.append(f"1m perf {perf_f:.1f}%")

    # ── Final verdict ──
    # Must have zero rejections AND at least 2 positive criteria
    has_rejections = len(reject_reasons) > 0
    has_enough_criteria = len(match_reasons) >= 2
    matches = not has_rejections and has_enough_criteria
    return matches, match_reasons, reject_reasons


def classify_deterministic(scan: dict, strategies: dict) -> list[dict]:
    """Phase 1: Match a scan against all strategy screen_filters.

    Returns list of {strategy_id, match_reasons, reject_reasons, confidence}.
    A symbol CAN match multiple strategies.
    """
    results = []
    for sid, cfg in strategies.items():
        filters = cfg.get("screen_filters")
        if not filters:
            continue
        matched, match_r, reject_r = match_filters(scan, filters)
        if matched:
            # Confidence based on how many criteria positively matched
            conf = min(0.95, 0.5 + len(match_r) * 0.1)
            results.append({
                "strategy_id": sid,
                "match_source": "deterministic",
                "match_reasons": match_r,
                "reject_reasons": [],
                "confidence": round(conf, 2),
                "display_name": cfg.get("display_name", sid),
                "timeframe_class": cfg.get("timeframe_class", "UNKNOWN"),
            })
    return results


# ── Phase 2: LLM-assisted classification ─────────────────────────────

def _build_llm_prompt(scan: dict, strategies: dict,
                      deterministic_matches: list[dict]) -> str:
    """Build a prompt for qwen3:14b to classify a symbol into strategies."""
    sym = scan.get("symbol", "?")
    det_strats = [m["strategy_id"] for m in deterministic_matches]

    # Build strategy catalog
    catalog_lines = []
    for sid, cfg in strategies.items():
        purpose = cfg.get("purpose", "")[:120]
        tf = cfg.get("timeframe_class", "?")
        catalog_lines.append(f"  - {sid} ({tf}): {purpose}")
    catalog = "\n".join(catalog_lines)

    # Build scan context
    scan_info = (
        f"Symbol: {sym}\n"
        f"Price: ${scan.get('price', '?')}\n"
        f"RVOL: {scan.get('rvol', '?')}x\n"
        f"Gap: {scan.get('gap_pct', '?')}%\n"
        f"Float: {scan.get('float_m', '?')}M\n"
        f"Score: {scan.get('score', '?')}\n"
        f"Sector: {scan.get('sector', '?')}\n"
        f"Industry: {scan.get('industry', '?')}\n"
        f"Catalyst: {scan.get('catalyst', 'none')}\n"
        f"Catalyst verified: {scan.get('catalyst_verified', False)}\n"
        f"Change %: {scan.get('change_pct', '?')}"
    )

    det_info = ", ".join(det_strats) if det_strats else "none"

    return f"""/no_think
You are a trading strategy classifier. Given a stock's data, determine which trading strategies it fits.

STRATEGY CATALOG:
{catalog}

STOCK DATA:
{scan_info}

DETERMINISTIC MATCHES (already confirmed by filters): {det_info}

TASK: Identify ALL strategies this stock could fit, including ones beyond the deterministic matches. A stock can match multiple strategies. Focus on strategies where the stock's characteristics align with the strategy's purpose.

Return ONLY a JSON array of objects. No explanation, no markdown, just the JSON:
[{{"strategy_id": "strategy_name", "confidence": 0.0-1.0, "reason": "brief reason"}}]

Rules:
- Include deterministic matches with confidence 0.9+
- Add new strategy matches you identify with confidence 0.5-0.85
- Do NOT include strategies that clearly don't fit
- Maximum 5 strategies per symbol
- JSON only, no other text"""


def _call_ollama(prompt: str, timeout: int = 360) -> str:
    """Call local qwen3:14b via Ollama."""
    import urllib.request
    from local_llm_config import get_local_llm_model, get_local_llm_base_url
    model = get_local_llm_model()
    base = get_local_llm_base_url().rstrip("/")

    payload = json.dumps({
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
        "think": False,
        "options": {"temperature": 0.1, "num_predict": 500},
    }).encode()

    try:
        req = urllib.request.Request(
            f"{base}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()).get("message", {}).get("content", "")
    except Exception as e:
        log.warning("Ollama error: %s", e)
        return ""


def _parse_llm_response(text: str, valid_sids: set) -> list[dict]:
    """Parse LLM JSON response into strategy matches."""
    # Try to extract JSON array from response
    import re
    text = text.strip()
    # Find JSON array
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if not match:
        return []
    try:
        items = json.loads(match.group())
    except json.JSONDecodeError:
        return []

    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        sid = item.get("strategy_id", "")
        if sid not in valid_sids:
            continue
        conf = min(0.95, max(0.1, float(item.get("confidence", 0.5))))
        results.append({
            "strategy_id": sid,
            "match_source": "llm",
            "confidence": round(conf, 2),
            "reason": str(item.get("reason", ""))[:200],
        })
    return results


def classify_with_llm(scan: dict, strategies: dict,
                      deterministic_matches: list[dict]) -> list[dict]:
    """Phase 2: Use qwen3:14b to find additional strategy matches."""
    prompt = _build_llm_prompt(scan, strategies, deterministic_matches)
    raw = _call_ollama(prompt)
    if not raw:
        return []
    valid_sids = set(strategies.keys())
    llm_matches = _parse_llm_response(raw, valid_sids)

    # Merge: LLM matches that aren't already in deterministic
    det_sids = {m["strategy_id"] for m in deterministic_matches}
    new_matches = []
    for m in llm_matches:
        if m["strategy_id"] not in det_sids:
            m["display_name"] = strategies[m["strategy_id"]].get("display_name", m["strategy_id"])
            m["timeframe_class"] = strategies[m["strategy_id"]].get("timeframe_class", "UNKNOWN")
            m["match_reasons"] = [m.pop("reason", "LLM classification")]
            m["reject_reasons"] = []
            new_matches.append(m)
    return new_matches


# ── Combined classifier ──────────────────────────────────────────────

def classify_symbol(scan: dict, strategies: dict,
                    use_llm: bool = False,
                    enrichment_cache: dict | None = None) -> list[dict]:
    """Full multi-strategy classification for a single symbol.

    Phase 0: Merge scan with enrichment cache (60+ Finviz fields + indicators)
    Phase 1: Deterministic filter matching using ALL available data
    Phase 2 (optional): LLM-assisted for additional matches

    Returns combined list of all matching strategies, sorted by confidence.
    """
    # Phase 0: Enrich scan data
    if enrichment_cache:
        scan = merge_scan_with_enrichment(scan, enrichment_cache)

    # Phase 1: Deterministic — fast, no external calls
    det_matches = classify_deterministic(scan, strategies)

    # Phase 2: LLM — runs for ALL symbols when enabled
    # LLM can identify strategies deterministic filters miss:
    # thesis-driven, sector-specific, portfolio-context strategies
    llm_matches = []
    if use_llm:
        llm_matches = classify_with_llm(scan, strategies, det_matches)

    # Combine and sort
    all_matches = det_matches + llm_matches
    all_matches.sort(key=lambda x: x["confidence"], reverse=True)

    # Cap at 5 strategies per symbol
    return all_matches[:5]


# ── Batch classification ─────────────────────────────────────────────

def classify_batch_from_db(limit: int = 50, use_llm: bool = False) -> list[dict]:
    """Classify symbols from trade_ai_scans in batch.

    Merges scan data with enrichment cache for full technical+fundamental context.
    """
    from session13_db import get_conn
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT ON (symbol)
            symbol, price, rvol, float_m, gap_pct, change_pct,
            score, decision, grade, catalyst, catalyst_verified,
            sector, industry, screener_label, run_label
        FROM trade_ai_scans
        WHERE scanned_at > NOW() - INTERVAL '7 days'
          AND (score >= 30 OR decision IN ('GO','WAIT') OR catalyst_verified = true)
        ORDER BY symbol, score DESC NULLS LAST
        LIMIT %s
    """, [limit])

    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    # Also pull indicator_confluence_cache for RSI/ATR/ADX
    indicator_data = {}
    try:
        cur.execute("""
            SELECT DISTINCT ON (symbol) symbol, atr, adx_regime, entry_quality,
                   confluence_score, confluence_tier, full_result
            FROM indicator_confluence_cache
            WHERE computed_at > NOW() - INTERVAL '7 days'
            ORDER BY symbol, computed_at DESC
        """)
        for row in cur.fetchall():
            icols = [d[0] for d in cur.description]
            irow = dict(zip(icols, row))
            sym = irow.pop("symbol")
            # Extract signals from full_result
            fr = irow.get("full_result") or {}
            if isinstance(fr, dict):
                sigs = fr.get("signals", {})
                if "rsi" in sigs:
                    irow["indicator_rsi"] = sigs["rsi"].get("value")
                if "vwap" in sigs:
                    irow["indicator_vwap_dist"] = sigs["vwap"].get("distance_pct")
                if "fib" in sigs:
                    irow["fib_context"] = sigs["fib"]
                if "sma20" in sigs:
                    irow["indicator_sma20_dist"] = sigs["sma20"].get("distance_pct")
            indicator_data[sym] = irow
    except Exception as e:
        log.warning("Could not load indicator data: %s", e)

    conn.close()

    strategies = load_all_strategies()
    enrichment = load_enrichment_cache()

    # Merge indicator data into enrichment
    for sym, idata in indicator_data.items():
        if sym not in enrichment:
            enrichment[sym] = {}
        enrichment[sym].update(idata)

    results = []

    for scan in rows:
        sym = scan["symbol"]
        matches = classify_symbol(scan, strategies, use_llm=use_llm,
                                  enrichment_cache=enrichment)
        if matches:
            results.append({
                "symbol": sym,
                "strategies": matches,
                "strategy_count": len(matches),
                "primary": matches[0]["strategy_id"] if matches else None,
            })
            strat_str = ", ".join(
                f"{m['strategy_id']}({m['confidence']:.0%})"
                for m in matches
            )
            log.info("  %s -> %s", sym, strat_str)
        else:
            log.info("  %s -> no matches", sym)

    return results


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Multi-strategy classifier — match symbols to ALL strategies"
    )
    parser.add_argument("--symbol", type=str, help="Classify a single symbol")
    parser.add_argument("--batch", action="store_true",
                        help="Classify all qualifying symbols from DB")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max symbols in batch mode (default 50)")
    parser.add_argument("--llm", action="store_true",
                        help="Enable Phase 2 LLM classification via qwen3:14b")
    args = parser.parse_args()

    strategies = load_all_strategies()

    if args.symbol:
        # Single symbol — fetch from DB + enrichment
        from session13_db import get_conn
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT symbol, price, rvol, float_m, gap_pct, change_pct,
                   score, decision, grade, catalyst, catalyst_verified,
                   sector, industry, screener_label
            FROM trade_ai_scans
            WHERE symbol = %s ORDER BY scanned_at DESC LIMIT 1
        """, [args.symbol.upper()])
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        conn.close()
        if not row:
            print(f"No scan data for {args.symbol}")
            return
        scan = dict(zip(cols, row))
        enrichment = load_enrichment_cache()
        matches = classify_symbol(scan, strategies, use_llm=args.llm,
                                  enrichment_cache=enrichment)
        print(f"\n{scan['symbol']} — {len(matches)} strategy matches:")
        for m in matches:
            src = m.get("match_source", "?")
            reasons = ", ".join(m.get("match_reasons", []))
            print(f"  {m['strategy_id']:30s} conf={m['confidence']:.0%}  "
                  f"src={src:14s} {reasons}")

    elif args.batch:
        results = classify_batch_from_db(
            limit=args.limit, use_llm=args.llm
        )
        print(f"\n=== BATCH RESULTS ===")
        print(f"Classified: {len(results)} symbols")
        multi = sum(1 for r in results if r["strategy_count"] > 1)
        print(f"Multi-strategy matches: {multi}")

        # Strategy distribution
        dist: dict[str, int] = {}
        for r in results:
            for s in r["strategies"]:
                dist[s["strategy_id"]] = dist.get(s["strategy_id"], 0) + 1
        print(f"\nStrategy distribution:")
        for sid, count in sorted(dist.items(), key=lambda x: -x[1]):
            print(f"  {sid:30s} {count}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
