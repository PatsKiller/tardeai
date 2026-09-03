"""portfolio_news.py — Portfolio News & Catalyst Intelligence
Fetches, scores, and synthesizes news for all portfolio holdings.
Stores 90-day rolling history for week-over-week and month-over-month comparison.

Surfaces:
  - Command Center AI Catalyst / AI Analyst
  - Weekly DOCX report
  - Monthly DOCX report

Uses: catalyst_enrichment.py (7 API sources), Finviz/Yahoo enrich (F2; not
      Brave search API), Ollama local LLM (scoring/curation), social_sentiment.py
"""

import json, os, time, hashlib, requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

# ═══════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════
HISTORY_DAYS = 90
from local_llm_config import get_local_llm_model, get_local_llm_base_url

OLLAMA_MODEL = get_local_llm_model()
OLLAMA_URL = get_local_llm_base_url().rstrip("/") + "/api/chat"
# F2: was Brave-enrich at score>=70. Search API is residual-web only;
# high-score enrichment now uses Finviz/Yahoo (RSS/export), same threshold.
NON_SEARCH_ENRICH_THRESHOLD = 70
BRAVE_SCORE_THRESHOLD = NON_SEARCH_ENRICH_THRESHOLD  # back-compat alias
MAX_PORTFOLIO_TICKERS = 40
FIDELITY_PREFIXES = ("FID-", "SS-", "TRP-", "JPM-", "VANG-", "WM-", "AB-", "SP500-")
SKIP_SYMBOLS = {"CASH", "--", "SNSXX", "SWVXX", "SPRXX", "VMFXX", "FDRXX"}


def _env(key, default=""):
    val = os.getenv(key, "").strip()
    if val:
        return val
    try:
        env_path = Path(__file__).resolve().parent.parent / ".env"
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except:
        pass
    return default


def _ollama(prompt, max_tokens=500):
    """Call local LLM for scoring/curation (routed through local_llm.generate)."""
    import re as _re

    try:
        from local_llm import generate

        text = generate(prompt, timeout=60, caller="portfolio_news", process_type="STANDARD")
        return _re.sub(r"<think>.*?</think>", "", text or "", flags=_re.DOTALL).strip()
    except Exception as e:
        return f"LLM error: {e}"


def _non_search_enrich(symbol: str, title: str = "", count: int = 3):
    """F2: enrich high-score catalysts via Finviz/Yahoo — not the search API.

    AGENTS.md: web search serves residual-web (≤1 hop/subject/day, N=3), not
    bulk news. News belongs on RSS and Finviz. Empty → [] (never fabricate;
    never fall through to an unbudgeted Brave client).
    """
    sym = (symbol or "").upper().strip()
    if not sym:
        return []
    out: List[Dict[str, Any]] = []
    try:
        from finviz_news import fetch_finviz_news

        for a in fetch_finviz_news(sym, lookback_hours=72)[:count]:
            out.append(
                {
                    "title": a.get("headline") or a.get("title") or "",
                    "url": a.get("url") or "",
                    "description": str(a.get("original_source") or a.get("source") or "")[:200],
                    "source": "finviz_news",
                    "age": "",
                }
            )
    except Exception:
        pass
    if len(out) < count:
        try:
            from yahoo_news import fetch_yahoo_news

            for a in fetch_yahoo_news(sym, lookback_hours=72)[: max(0, count - len(out))]:
                out.append(
                    {
                        "title": a.get("headline") or a.get("title") or "",
                        "url": a.get("url") or "",
                        "description": str(a.get("source") or "yahoo")[:200],
                        "source": "yahoo_news",
                        "age": "",
                    }
                )
        except Exception:
            pass
    return out[:count]


def _brave_search(query, count=3):
    """Deprecated alias — F2 re-points news enrichment off the search API."""
    # Best-effort: first token may be the symbol from "SYM title…"
    sym = str(query or "").split()[0] if query else ""
    return _non_search_enrich(sym, title=str(query or ""), count=count)


# ═══════════════════════════════════════════════════════════════════
# CORE: Collect news for portfolio holdings
# ═══════════════════════════════════════════════════════════════════


def collect_portfolio_news(portfolio: Dict, state_dir: Path, root: str = ".") -> Dict:
    """Fetch catalyst news for all portfolio holdings, score with LLM, store daily snapshot."""
    import sys

    sys.path.insert(0, str(Path(root) / "scripts"))

    holdings = portfolio.get("holdings", [])
    enrichment_cache = {}
    try:
        ec_path = state_dir / "ticker_enrichment_cache.json"
        if ec_path.exists():
            enrichment_cache = json.loads(ec_path.read_text())
    except:
        pass

    # Build ticker list (skip Fidelity internal, CASH, etc.)
    tickers = []
    seen = set()
    for h in holdings:
        sym = (h.get("symbol") or "").upper()
        if not sym or sym in SKIP_SYMBOLS or sym in seen:
            continue
        if any(sym.startswith(p) for p in FIDELITY_PREFIXES):
            continue
        if "-" in sym and len(sym) > 5:
            continue
        company = enrichment_cache.get(sym, {}).get("company", "")
        mv = h.get("market_value", 0) or 0
        tickers.append({"symbol": sym, "company": company, "market_value": mv})
        seen.add(sym)

    # Add user watchlist symbols not already in portfolio
    try:
        wl_path = state_dir / "watchlist.json"
        if wl_path.exists():
            _wl = json.loads(wl_path.read_text())
            for _ws, _wd in _wl.items():
                _ws = _ws.upper().strip()
                if _ws and _ws not in seen and _ws not in SKIP_SYMBOLS:
                    company = enrichment_cache.get(_ws, {}).get("company", "")
                    tickers.append({"symbol": _ws, "company": company, "market_value": 0, "source": "watchlist"})
                    seen.add(_ws)
    except Exception:
        pass

    # Add directive + AI/topic watchlist symbols from DB (canonical lifecycle statuses)
    try:
        from db_adapter import get_active_watchlist_symbols

        _db_wl_rows = get_active_watchlist_symbols(
            [
                "ai_discovered",
                "ai_watchlist",
                "topic_research",
                "hermes",
                "paper_proposal",
            ]
        )
        _ai_added = 0
        for _r in _db_wl_rows:
            _ws = (_r.get("symbol") or "").upper().strip()
            if _ws and _ws not in seen and _ws not in SKIP_SYMBOLS:
                company = enrichment_cache.get(_ws, {}).get("company", "")
                tickers.append({"symbol": _ws, "company": company, "market_value": 0, "source": "ai_watchlist"})
                seen.add(_ws)
                _ai_added += 1
        if _ai_added:
            print(f"  [portfolio-news] Added {_ai_added} AI/analyst watchlist symbols to news universe")
    except Exception as _e_wl_db:
        print(f"  [portfolio-news] DB watchlist lookup skipped: {_e_wl_db}")

    tickers.sort(key=lambda x: -x["market_value"])
    tickers = tickers[: MAX_PORTFOLIO_TICKERS + 15]  # allow room for watchlist additions
    print(f"  [portfolio-news] Scanning {len(tickers)} tickers for news...")

    # Fetch catalysts using existing catalyst_enrichment
    all_catalysts = []
    sources_summary = {}
    try:
        from catalyst_enrichment import enrich_ticker

        for t in tickers:
            sym = t["symbol"]
            try:
                result = enrich_ticker(sym, t.get("company", ""))
                catalysts = result.get("catalysts", [])
                _src = t.get("source", "")
                for c in catalysts:
                    c["portfolio_symbol"] = sym
                    c["market_value"] = t["market_value"]
                    if _src == "ai_watchlist":
                        c["_source_family"] = "ai_watchlist"
                    elif _src == "watchlist":
                        c["_source_family"] = "watchlist"
                all_catalysts.extend(catalysts)
                sources_summary[sym] = {
                    "count": result.get("catalyst_count", 0),
                    "tier": result.get("catalyst_tier", "none"),
                    "sources": result.get("sources_hit", []),
                }
                time.sleep(0.2)
            except Exception as e:
                print(f"  [portfolio-news] {sym}: {e}")
    except ImportError:
        print("  [portfolio-news] catalyst_enrichment not available")

    print(f"  [portfolio-news] Found {len(all_catalysts)} raw articles from {len(tickers)} tickers")

    # Deduplicate across tickers
    seen_fps = set()
    unique = []
    for c in all_catalysts:
        fp = hashlib.md5((c.get("title", "") + c.get("url", "")).encode()).hexdigest()[:12]
        if fp not in seen_fps:
            seen_fps.add(fp)
            unique.append(c)
    print(f"  [portfolio-news] {len(unique)} unique articles after dedup")

    # Score with local LLM (batch — top 30 by recency)
    unique.sort(key=lambda x: x.get("published", ""), reverse=True)
    scored = _score_catalysts(unique[:30], portfolio)

    # Also score a small batch of watchlist-only articles not already scored
    _scored_urls = set(c.get("url", "") for c in scored)
    _wl_unscored = [c for c in unique[30:] if c.get("url", "") not in _scored_urls and c.get("market_value", 0) == 0][
        :10
    ]  # cap at 10 extra
    if _wl_unscored:
        _wl_scored = _score_catalysts(_wl_unscored, portfolio)
        for _ws in _wl_scored:
            _ws["_source_family"] = "watchlist"
        scored.extend(_wl_scored)
        scored.sort(key=lambda x: -x.get("llm_score", 0))

    # F2: Finviz/Yahoo-enrich top-scoring catalysts (not Brave search API)
    brave_enriched = []  # name kept for snapshot schema back-compat
    for c in scored:
        if c.get("llm_score", 0) >= NON_SEARCH_ENRICH_THRESHOLD:
            sym = c.get("portfolio_symbol", "")
            enrich = _non_search_enrich(sym, title=c.get("title", "")[:50], count=2)
            if enrich:
                c["brave_context"] = enrich  # schema key retained; sources are finviz/yahoo
                c["enrich_sources"] = sorted({e.get("source") for e in enrich if e.get("source")})
                brave_enriched.append(sym)
    if brave_enriched:
        print(f"  [portfolio-news] RSS/Finviz-enriched {len(brave_enriched)} high-scoring catalysts")

    # Build daily snapshot
    today = datetime.now().strftime("%Y-%m-%d")
    # Tag source_family on articles that don't have it yet
    for c in scored:
        if "_source_family" not in c:
            c["_source_family"] = "portfolio" if c.get("market_value", 0) > 0 else "watchlist"

    snapshot = {
        "date": today,
        "generated_at": datetime.now().isoformat(),
        "ticker_count": len(tickers),
        "total_articles": len(unique),
        "scored_articles": len(scored),
        "catalysts": scored[:20],  # Top 20 scored for JSON/display
        "all_scored": scored[:50],  # Top 50 for article_index persistence (includes watchlist)
        "sources_summary": sources_summary,
        "brave_enriched_count": len(brave_enriched),
    }

    # Save daily snapshot
    history_dir = state_dir / "portfolio_news_history"
    history_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = history_dir / f"{today}.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2, default=str))

    # Save current state for CC.
    # Dual-written from this one snapshot object to every state root a reader
    # may use. This producer runs under `cd $PROJ`, while every deployed release
    # symlinks data/portfolios/state at the persistent root, so writing only the
    # checkout copy stranded the Command Center on an August file while this
    # process reported success every morning (measured 2026-09-03: served copy
    # 8 days behind the producer copy). Same fix as
    # portfolio_stops.save_risk_state and the orchestrator's _freshness /
    # performance_history writes.
    from lib.canonical_observation import write_state_json as _wsj

    _news_write = _wsj("portfolio_news.json", snapshot, checkout_root=root)
    if _news_write["errors"]:
        print(f"  [portfolio-news] Warning: {_news_write['errors'][0]}")

    # Prune history > 90 days
    _prune_history(history_dir)

    print(f"  [portfolio-news] ✅ {len(scored)} scored catalysts saved | {len(brave_enriched)} Brave-enriched")
    return snapshot


def _score_catalysts(catalysts: List[Dict], portfolio: Dict) -> List[Dict]:
    """Score catalysts using local LLM for portfolio relevance."""
    if not catalysts:
        return []

    totals = portfolio.get("portfolio_totals", {})
    tv = totals.get("total_value", 0)

    scored = []
    for c in catalysts:
        sym = c.get("portfolio_symbol", "")
        title = c.get("title", "")
        summary = c.get("summary", "")[:200]
        mv = c.get("market_value", 0)
        weight = (mv / tv * 100) if tv > 0 else 0

        prompt = f"""/no_think
Score this news article for portfolio relevance (0-100).
Ticker searched: {sym} ({weight:.1f}% of portfolio)
Headline: {title}
Summary: {summary}

IMPORTANT: Determine if this headline is actually about {sym} or just returned in search results.

Scoring criteria:
- 80-100: Material event directly about {sym} (earnings, FDA, merger, lawsuit, regulatory)
- 60-79: Significant development about {sym} (analyst upgrade/downgrade, major contract)
- 40-59: Sector/industry news relevant to {sym} but not specifically about it
- 20-39: Tangentially related (peer company, macro trend)
- 0-19: Not about {sym} at all — noise from search results

Respond with ONLY a JSON object: {{"score": <number>, "category": "<one of: earnings, regulatory, analyst, sector, macro, company, noise>", "urgency": "<one of: immediate, watch, monitor, ignore>", "relevance_type": "<one of: company_specific, sector_spillover, peer_related, macro, indirect, misattributed>", "one_line": "<why this matters to {sym} in 15 words>"}}"""

        try:
            response = _ollama(prompt, max_tokens=150)
            # Parse JSON from response
            import re

            json_match = re.search(r"\{[^}]+\}", response)
            if json_match:
                data = json.loads(json_match.group())
                c["llm_score"] = min(100, max(0, int(data.get("score", 30))))
                c["llm_category"] = data.get("category", "unknown")
                c["llm_urgency"] = data.get("urgency", "monitor")
                c["llm_summary"] = data.get("one_line", "")
                c["relevance_type"] = data.get("relevance_type", "unknown")
                # Downgrade misattributed articles
                if c["relevance_type"] == "misattributed":
                    c["llm_score"] = min(c["llm_score"], 15)
                    c["llm_urgency"] = "ignore"
            else:
                c["llm_score"] = 30
                c["llm_category"] = "unknown"
                c["llm_urgency"] = "monitor"
                c["llm_summary"] = ""
                c["relevance_type"] = "unknown"
        except:
            c["llm_score"] = 30
            c["llm_category"] = "unknown"
            c["llm_urgency"] = "monitor"
            c["llm_summary"] = ""
            c["relevance_type"] = "unknown"

        c["portfolio_weight"] = round(weight, 1)
        scored.append(c)

    scored.sort(key=lambda x: -x.get("llm_score", 0))
    return scored


def _prune_history(history_dir: Path):
    """Remove snapshots older than HISTORY_DAYS."""
    cutoff = datetime.now() - timedelta(days=HISTORY_DAYS)
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    for f in history_dir.glob("*.json"):
        if f.stem < cutoff_str:
            f.unlink()


# ═══════════════════════════════════════════════════════════════════
# SYNTHESIS: Weekly and Monthly summaries
# ═══════════════════════════════════════════════════════════════════


def build_weekly_summary(state_dir: Path) -> Dict:
    """Build weekly catalyst summary from last 7 days of snapshots."""
    history_dir = state_dir / "portfolio_news_history"
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    prev_cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")

    this_week = _load_range(history_dir, cutoff, datetime.now().strftime("%Y-%m-%d"))
    prev_week = _load_range(history_dir, prev_cutoff, cutoff)

    # Aggregate catalysts
    all_catalysts = []
    for snap in this_week:
        all_catalysts.extend(snap.get("catalysts", []))

    # Deduplicate
    seen = set()
    unique = []
    for c in all_catalysts:
        fp = (c.get("title", "") + c.get("portfolio_symbol", ""))[:80]
        if fp not in seen:
            seen.add(fp)
            unique.append(c)

    unique.sort(key=lambda x: -x.get("llm_score", 0))

    # Previous week's top catalysts for comparison
    prev_catalysts = []
    for snap in prev_week:
        prev_catalysts.extend(snap.get("catalysts", []))
    prev_symbols = set(c.get("portfolio_symbol", "") for c in prev_catalysts if c.get("llm_score", 0) >= 50)
    curr_symbols = set(c.get("portfolio_symbol", "") for c in unique if c.get("llm_score", 0) >= 50)

    # Synthesize with LLM
    top_5 = unique[:5]
    catalyst_text = "\n".join(
        f"- {c.get('portfolio_symbol', '?')} ({c.get('llm_score', 0)}): {c.get('title', '')[:80]} [{c.get('llm_category', '?')}]"
        for c in top_5
    )
    new_this_week = curr_symbols - prev_symbols
    resolved = prev_symbols - curr_symbols

    synthesis_prompt = f"""/no_think
You are a portfolio strategist writing a weekly news brief.

TOP CATALYSTS THIS WEEK:
{catalyst_text}

NEW THIS WEEK: {", ".join(new_this_week) if new_this_week else "None"}
RESOLVED FROM LAST WEEK: {", ".join(resolved) if resolved else "None"}
STILL ACTIVE: {", ".join(curr_symbols & prev_symbols) if curr_symbols & prev_symbols else "None"}

Respond with ONLY a JSON object:
{{"top_catalyst": "<ticker: one-line description of most important catalyst>",
"biggest_risk": "<ticker: one-line description of biggest risk this week>",
"biggest_positive": "<ticker: one-line description of most positive development>",
"what_changed": "<one sentence on what shifted from last week>",
"watch_next": "<what to monitor next week, cite tickers>",
"narrative": "<3 sentences: what mattered, what was noise, what to watch>"}}

Be specific. Cite tickers. No generic statements."""

    synthesis_raw = _ollama(synthesis_prompt, max_tokens=500)
    import re as _re

    synthesis = {}
    try:
        _jm = _re.search(r"\{[\s\S]*\}", synthesis_raw)
        if _jm:
            synthesis = json.loads(_jm.group())
    except:
        synthesis = {"narrative": synthesis_raw[:300]}

    return {
        "period": "weekly",
        "date_range": f"{cutoff} to {datetime.now().strftime('%Y-%m-%d')}",
        "generated_at": datetime.now().isoformat(),
        "top_catalysts": unique[:10],
        "total_articles": len(unique),
        "new_this_week": list(new_this_week),
        "resolved": list(resolved),
        "still_active": list(curr_symbols & prev_symbols),
        "highest_scoring": unique[0] if unique else None,
        "executive_strip": {
            "top_catalyst": synthesis.get("top_catalyst", ""),
            "biggest_risk": synthesis.get("biggest_risk", ""),
            "biggest_positive": synthesis.get("biggest_positive", ""),
            "what_changed": synthesis.get("what_changed", ""),
            "watch_next": synthesis.get("watch_next", ""),
        },
        "strategist_summary": synthesis.get("narrative", synthesis_raw[:300] if isinstance(synthesis_raw, str) else ""),
        "snapshots_used": len(this_week),
    }


def build_monthly_summary(state_dir: Path) -> Dict:
    """Build monthly catalyst summary from last 30 days of snapshots."""
    history_dir = state_dir / "portfolio_news_history"
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    prev_cutoff = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")

    this_month = _load_range(history_dir, cutoff, datetime.now().strftime("%Y-%m-%d"))
    prev_month = _load_range(history_dir, prev_cutoff, cutoff)

    # Aggregate and deduplicate
    all_catalysts = []
    for snap in this_month:
        all_catalysts.extend(snap.get("catalysts", []))
    seen = set()
    unique = []
    for c in all_catalysts:
        fp = (c.get("title", "") + c.get("portfolio_symbol", ""))[:80]
        if fp not in seen:
            seen.add(fp)
            unique.append(c)
    unique.sort(key=lambda x: -x.get("llm_score", 0))

    # Theme analysis
    from collections import Counter

    categories = Counter(c.get("llm_category", "unknown") for c in unique)
    by_symbol = Counter(c.get("portfolio_symbol", "?") for c in unique if c.get("llm_score", 0) >= 50)
    by_urgency = Counter(c.get("llm_urgency", "monitor") for c in unique)

    # Previous month comparison
    prev_cats = []
    for snap in prev_month:
        prev_cats.extend(snap.get("catalysts", []))
    prev_symbols = Counter(c.get("portfolio_symbol", "?") for c in prev_cats if c.get("llm_score", 0) >= 50)

    # Monthly synthesis
    top_10 = unique[:10]
    catalyst_text = "\n".join(
        f"- {c.get('portfolio_symbol', '?')} ({c.get('llm_score', 0)}, {c.get('llm_category', '?')}): {c.get('title', '')[:80]}"
        for c in top_10
    )

    synthesis_prompt = f"""/no_think
You are a portfolio strategist writing a monthly news intelligence summary.

TOP CATALYSTS THIS MONTH:
{catalyst_text}

DOMINANT THEMES: {dict(categories.most_common(5))}
MOST ACTIVE HOLDINGS: {dict(by_symbol.most_common(5))}
URGENCY BREAKDOWN: {dict(by_urgency)}
TOTAL SCORED ARTICLES: {len(unique)}

Write a 5-sentence monthly intelligence narrative:
1. What defined the month's news flow for this portfolio
2. Which holdings/sectors had the most important catalyst activity
3. What recurring themes or risks appeared across multiple sources
4. What unresolved risks carry forward to next month
5. What should be monitored or acted on next month

Be specific. Reference tickers and scores. No generic commentary."""

    synthesis = _ollama(synthesis_prompt, max_tokens=500)

    return {
        "period": "monthly",
        "date_range": f"{cutoff} to {datetime.now().strftime('%Y-%m-%d')}",
        "generated_at": datetime.now().isoformat(),
        "top_catalysts": unique[:15],
        "total_articles": len(unique),
        "dominant_themes": dict(categories.most_common(8)),
        "most_active_holdings": dict(by_symbol.most_common(8)),
        "urgency_breakdown": dict(by_urgency),
        "highest_scoring": unique[0] if unique else None,
        "strategist_summary": synthesis,
        "snapshots_used": len(this_month),
    }


def _load_range(history_dir: Path, start: str, end: str) -> List[Dict]:
    """Load snapshots in date range."""
    snapshots = []
    if not history_dir.exists():
        return snapshots
    for f in sorted(history_dir.glob("*.json")):
        if start <= f.stem <= end:
            try:
                snapshots.append(json.loads(f.read_text()))
            except:
                pass
    return snapshots


# ═══════════════════════════════════════════════════════════════════
# ENTRY POINT — called by orchestrator
# ═══════════════════════════════════════════════════════════════════


def run_portfolio_news(portfolio: Dict, state_dir: Path, run_type: str = "daily", root: str = ".") -> Dict:
    """Main entry point. Collects news, builds appropriate summary."""
    state_dir = Path(state_dir)

    # Always collect fresh news
    snapshot = collect_portfolio_news(portfolio, state_dir, root)

    # Build period summary based on run type
    summary = None
    if run_type == "weekly":
        print("  [portfolio-news] Building weekly synthesis...")
        summary = build_weekly_summary(state_dir)
        (state_dir / "portfolio_news_weekly.json").write_text(json.dumps(summary, indent=2, default=str))
        print(
            f"  [portfolio-news] ✅ Weekly summary: {summary.get('total_articles', 0)} articles, {len(summary.get('new_this_week', []))} new"
        )

    elif run_type in ("monthly", "manual"):
        print("  [portfolio-news] Building monthly synthesis...")
        summary = build_monthly_summary(state_dir)
        (state_dir / "portfolio_news_monthly.json").write_text(json.dumps(summary, indent=2, default=str))
        print(
            f"  [portfolio-news] ✅ Monthly summary: {summary.get('total_articles', 0)} articles, {len(summary.get('dominant_themes', {}))} themes"
        )

    return {"snapshot": snapshot, "summary": summary}
