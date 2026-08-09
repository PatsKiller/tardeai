"""scoring.py — 7-pillar hybrid scoring engine.

Pipeline per ticker:
  1. Keyword rules score each pillar from Finviz data + catalyst enrichment
  2. If catalyst impact is ambiguous, Claude Haiku re-evaluates the catalyst pillar
  3. If score >= 40 OR RVOL >= 5 OR fresh high-impact catalyst → escalate to Sonnet
     for a full narrative analysis of the setup
  4. Returns ScoredTicker with grade, decision, per-pillar breakdown, and LLM narrative
"""
from __future__ import annotations
import json, logging, os
from typing import Any, Dict, List, Optional
import threading

logger = logging.getLogger(__name__)

# Ollama serialization lock — one call at a time, no timeout pile-up
_ollama_lock = threading.Lock()

def _ollama_serialized(prompt: str, num_predict: int = 500, timeout: int = 90, model: str = None) -> str:
    """Serialized LLM call via local_llm.generate() — toll gate provides serialization."""
    from local_llm import generate
    return generate(prompt, timeout=timeout,
                    caller="scoring", process_type="STANDARD") or ""
import yaml

# ── Load weights ──────────────────────────────────────────────────────────────

def _load_weights(project_root: str = ".") -> Dict[str, Any]:
    path = os.path.join(project_root, "assets", "weights.yaml")
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}

# ── LLM helpers ───────────────────────────────────────────────────────────────

def _anthropic_complete(prompt: str, model: str, max_tokens: int = 300) -> str:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        return f"[LLM error: {e}]"

def _haiku_score_catalyst(symbol: str, headlines: List[str], summary_blurb: str) -> int:
    """Score catalyst pillar using local Ollama (free) instead of Claude Haiku."""
    import urllib.request
    import urllib.error
    headlines_str = "\n".join(f"- {h}" for h in headlines[:5])
    prompt = (
        f"Stock catalyst analyst. Score the catalyst for {symbol} from 0 to 15.\n"
        f"15=FDA approval/earnings beat/M&A. 8=upgrade/partnership. 4=generic. 0=noise/dilution.\n"
        f"Headlines:\n{headlines_str}\n"
        f"Context: {summary_blurb or 'None.'}\n"
        f"Reply with ONLY a single integer 0-15."
    )
    try:
        text = _ollama_serialized(prompt, num_predict=5, timeout=90)
        if True:
            data = {"response": text}  # compat shim
            # Extract first integer from response
            import re
            nums = re.findall(r"\b(\d+)\b", text)
            if nums:
                return max(0, min(15, int(nums[0])))
    except Exception as e:
        print(f"  [ollama-catalyst] {symbol} error: {e} — falling back to Grok lane (free OAuth)")
        # Free-OAuth-only rule (operator, 2026-06-11): fallback is the Grok lane, never metered Anthropic.
        try:
            import llm_lane
            headlines_str2 = "\n".join(f"- {h}" for h in headlines[:5])
            prompt2 = (
                f"Score catalyst for {symbol} 0-15. "
                f"15=FDA/earnings/M&A. 8=upgrade. 4=generic. 0=noise.\n"
                f"Headlines:\n{headlines_str2}\nReply integer only."
            )
            import re as _re
            result = llm_lane.generate(prompt2, lane="grok", timeout=60)
            nums = _re.findall(r"\b(\d+)\b", result or "")
            if nums:
                return max(0, min(15, int(nums[0])))
        except Exception:
            pass
    return 4  # fallback score

def _sonnet_narrative(symbol: str, score: int, grade: str, decision: str,
                       pillar_breakdown: Dict[str, int], top_catalyst: Optional[Dict],
                       rvol: float, price: float, float_shares: float,
                       change_pct: float, gap_pct: float) -> str:
    """Scalper-focused narrative for GO/escalated tickers — Grok lane (free OAuth), local fallback.
    Migrated off metered Claude Sonnet 2026-06-11 (operator free-OAuth-only rule)."""
    catalyst_headline = (top_catalyst or {}).get("title", "No catalyst identified")
    catalyst_age = (top_catalyst or {}).get("hours_old", "N/A")
    prompt = (
        f"You are a professional day trader AI. Write a concise, actionable scalp setup brief for {symbol}.\n\n"
        f"Score: {score}/50 | Grade: {grade} | Decision: {decision}\n"
        f"RVOL: {rvol}x | Price: ${price} | Float: {float_shares:,.0f}M shares\n"
        f"Change: {change_pct:+.1f}% | Gap: {gap_pct:+.1f}%\n"
        f"Pillar scores: {json.dumps(pillar_breakdown)}\n"
        f"Top catalyst ({catalyst_age}h ago): {catalyst_headline}\n\n"
        f"Write 3-4 sentences maximum. Focus on: why it's moving, key risk, ideal entry context, "
        f"and one thing to watch. No generic disclaimers."
    )
    try:
        import llm_lane
        out = llm_lane.generate(prompt, lane="grok", timeout=90)
        if out and not out.startswith("["):
            return out.strip()
    except Exception:
        pass
    try:
        return _ollama_serialized(prompt, num_predict=220, timeout=120).strip()
    except Exception as e:
        return f"[narrative unavailable: {e}]"

def _ollama_preplan(symbol: str, score: int, decision: str,
                    top_catalyst: Optional[Dict], rvol: float,
                    price: float, change_pct: float) -> str:
    """Ollama pre-plan for tickers scoring 25-47 (below A+ threshold).
    Free alternative to Sonnet for developing setups."""
    import urllib.request
    catalyst_title = (top_catalyst or {}).get("title", "No catalyst")
    prompt = (
        f"Scalp trade pre-plan for {symbol}. Score: {score}/65 ({decision}).\n"
        f"Price: ${price} | Change: {change_pct:+.1f}% | RVOL: {rvol:.1f}x\n"
        f"Catalyst: {catalyst_title[:100]}\n\n"
        f"Write 2 sentences: key level to watch and main risk. Be specific. No disclaimers."
    )
    try:
        from local_llm_config import get_local_llm_model
        _model = get_local_llm_model()
        data_text = _ollama_serialized(prompt, num_predict=80, timeout=120, model=_model)
        return data_text.strip()
    except Exception as e:
        return f"[pre-plan unavailable: {e}]"




# ── Data Quality Hardening ────────────────────────────────────────────────────

import re as _re

def is_disqualified_ticker(symbol: str, ticker_row: Dict[str, Any]) -> tuple[bool, str]:
    """Hard pre-score disqualification. Reverse-split squeezes → MANUAL_REVIEW (not DQ)."""
    import sys
    from pathlib import Path
    _lib = Path(__file__).resolve().parent / "lib"
    if str(_lib) not in sys.path:
        sys.path.insert(0, str(_lib))
    from squeeze_manual_review import is_disqualified_hard
    return is_disqualified_hard(symbol, ticker_row)


_COMPANY_NAME_CACHE: dict = {}

def _get_company_name(symbol: str) -> str:
    """Get company name with yfinance, cached to avoid repeated API calls."""
    if symbol in _COMPANY_NAME_CACHE:
        return _COMPANY_NAME_CACHE[symbol]
    try:
        import yfinance as _yf
        _info = _yf.Ticker(symbol).info
        name = _info.get("shortName") or _info.get("longName") or symbol
        _COMPANY_NAME_CACHE[symbol] = name
        return name
    except Exception:
        _COMPANY_NAME_CACHE[symbol] = symbol
        return symbol


_GENERIC_CATALYST_PATTERNS = [
    _re.compile(p, _re.IGNORECASE) for p in [
        r"top gainers and losers",
        r"after.hours session",
        r"get insights into",
        r"stocks experiencing",
        r"biggest movers",
        r"market wrap",
        r"most active stocks",
        r"pre.?market movers",
        r"morning bell",
        r"weekly roundup",
    ]
]

def validate_catalyst_relevance(symbol: str, company_name: str, headline: str) -> tuple[bool, float, str]:
    """Check if a catalyst headline actually relates to this ticker.
    Returns (is_relevant, confidence, reason).
    """
    if not headline or not headline.strip():
        return False, 0.0, "empty_headline"

    # Strip source tags like [Yahoo], [Yahoo Finance], [Finnhub] before matching
    clean_headline = _re.sub(r'\s*\[.*?\]\s*$', '', headline).strip()
    hl = clean_headline.lower()
    sym_lower = symbol.lower()

    # Generic placeholder detection
    for pat in _GENERIC_CATALYST_PATTERNS:
        if pat.search(hl):
            return False, 0.1, f"generic_placeholder: {pat.pattern}"

    score = 0.0
    parts = []

    # Direct ticker mention
    if _re.search(r'\b' + _re.escape(sym_lower) + r'\b', hl):
        score += 0.6
        parts.append("ticker_in_headline")

    # First word of company name (handles "Rallybio Corporation" → "rallybio")
    company_first = _re.split(r'\s+', company_name.strip())[0].lower() if company_name else ""
    company_first = _re.sub(r'[^a-z]', '', company_first)
    if len(company_first) >= 3 and company_first not in ('the', 'inc', 'ltd') and company_first in hl:
        score += 0.5
        parts.append(f"company_first_word({company_first})")

    # Company name words (additional multi-word matching)
    company_words = [_re.sub(r'[^a-z]', '', w) for w in company_name.lower().split()]
    company_words = [w for w in company_words
                     if len(w) > 3 and w not in ('inc', 'corp', 'ltd', 'llc', 'the', 'and', 'for', 'holdings', 'group', 'corporation', 'technologies', 'limited')]
    matches = sum(1 for w in company_words if w in hl)
    if matches > 0 and score < 0.5:
        # Only add if first-word match didn't already cover it
        if company_words and matches == len(company_words):
            score += 0.4
        else:
            score += min(0.4, matches * 0.2)
        parts.append(f"company_match({matches}/{len(company_words)})")

    reason = ', '.join(parts) if parts else 'no_match'
    return score >= 0.3, score, reason


def get_verified_catalyst_fallback(symbol: str, company_name: str) -> str:
    """Fetch a verified headline from Yahoo Finance RSS when primary fails."""
    try:
        import feedparser
        feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US")
        if feed.entries:
            title = feed.entries[0].get('title', '')
            ok, _, _ = validate_catalyst_relevance(symbol, company_name, title)
            if ok:
                return f"{title} [Yahoo Finance]"
    except Exception:
        pass
    return "No verified catalyst — data quality check failed"


def get_industry_with_fallback(symbol: str, finviz_data: Dict[str, Any]) -> str:
    """Industry with yfinance fallback. Never returns empty."""
    industry = str(finviz_data.get('industry', '') or finviz_data.get('sector', '') or
                   finviz_data.get('Industry', '') or finviz_data.get('Sector', '') or '').strip()
    if industry and industry.lower() not in ('', 'unknown', 'n/a', '-'):
        return industry
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info
        yf_ind = info.get('industry', '') or info.get('sector', '')
        if yf_ind and yf_ind.lower() not in ('', 'unknown'):
            return yf_ind
    except Exception:
        pass
    return 'Unclassified'


_SECTOR_ETF_MAP = {
    'Technology': 'XLK', 'Financial Services': 'XLF', 'Healthcare': 'XLV',
    'Consumer Cyclical': 'XLY', 'Consumer Defensive': 'XLP', 'Industrials': 'XLI',
    'Energy': 'XLE', 'Utilities': 'XLU', 'Real Estate': 'XLRE',
    'Basic Materials': 'XLB', 'Communication Services': 'XLC',
}

def get_sector_context(symbol: str, industry: str) -> Dict[str, Any]:
    """Get sector, country, and 1M performance. Called during scoring (cached per run)."""
    result: Dict[str, Any] = {'country': '', 'sector': '', 'sector_etf': '',
              'ticker_perf_1m': None, 'sector_perf_1m': None, 'vs_sector_pct': None}
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info
        result['country'] = info.get('country', '')
        sector = info.get('sector', '')
        result['sector'] = sector
        result['sector_etf'] = _SECTOR_ETF_MAP.get(sector, '')

        hist = yf.Ticker(symbol).history(period='1mo')
        if len(hist) >= 2:
            s = float(hist['Close'].iloc[0]); e = float(hist['Close'].iloc[-1])
            if s > 0: result['ticker_perf_1m'] = round((e - s) / s * 100, 1)

        etf = result['sector_etf']
        if etf:
            eh = yf.Ticker(etf).history(period='1mo')
            if len(eh) >= 2:
                es = float(eh['Close'].iloc[0]); ee = float(eh['Close'].iloc[-1])
                if es > 0: result['sector_perf_1m'] = round((ee - es) / es * 100, 1)

        if result['ticker_perf_1m'] is not None and result['sector_perf_1m'] is not None:
            result['vs_sector_pct'] = round(result['ticker_perf_1m'] - result['sector_perf_1m'], 1)
    except Exception:
        pass
    return result


# ── Pillar scorers ────────────────────────────────────────────────────────────

def _score_catalyst_keywords(catalyst_tier: str, catalyst_count: int,
                              has_fresh: bool, top_catalyst: Optional[Dict]) -> tuple[int, bool]:
    """Score the catalyst pillar by keyword rules.
    Returns (score, is_ambiguous).
    Ambiguous means: we have some news but impact is genuinely unclear.
    """
    recency_mult = (top_catalyst or {}).get("recency_multiplier", 1.0)
    if catalyst_tier == "none" or catalyst_count == 0:
        return 0, False
    if catalyst_tier == "high_impact":
        base = 15 if catalyst_count >= 2 else 12
        return min(15, int(base * recency_mult)), False
    if catalyst_tier == "medium_impact":
        # De-bias (2026-06-11): keyword topic tiers favored tech/biotech narrative density (the GO tech-tilt
        # experiment: Tech GOed 1.3x Industrials on WEAKER inputs). For the ambiguous middle tier, weight by
        # the market's ACTUAL reaction (gap+change alignment with the news) instead of the topic.
        reaction = abs(float((top_catalyst or {}).get("_price_reaction") or 0))
        base = 6 + min(4, reaction / 5.0)   # 6..10 by |gap+change| up to 20%
        return min(15, int(base * recency_mult)), True   # still ambiguous → LLM review
    if catalyst_tier == "low_impact":
        base = 4
        return min(15, int(base * recency_mult)), False
    return 0, False

def _score_rvol(rvol: float, float_m: float = 0) -> int:
    # FIX 4: Cap RVOL score on micro-float to prevent manipulation-driven GO signals
    if 0 < float_m < 2.0 and rvol > 5.0:
        rvol = min(rvol, 3.0)  # cap contribution
    if rvol >= 8:   return 12
    if rvol >= 5:   return 10
    if rvol >= 3:   return 7
    if rvol >= 2:   return 4
    if rvol >= 1.5: return 2
    return 0

def _score_price_action(change_pct: float, gap_pct: float, rvol: float) -> int:
    """Infer price action structure from available Finviz signals.
    Full TDA (above PM high + above VWAP + at HOD) isn't available from Finviz alone,
    so we use gap%, change%, and RVOL as proxies.
    """
    strong_gap = gap_pct >= 10
    strong_change = change_pct >= 10
    high_rvol = rvol >= 5
    if strong_gap and strong_change and high_rvol:
        return 10  # all 3 aligned — proxy for above PM high + VWAP + HOD
    if strong_gap and strong_change:
        return 8
    if (strong_gap or strong_change) and rvol >= 2:
        return 6
    if gap_pct >= 3 or change_pct >= 5:
        return 3
    return 0

def _score_float(float_m: float) -> int:
    """float_m is float shares in millions."""
    if float_m <= 0:   return 4  # unknown float — give partial credit
    if float_m < 5:    return 8
    if float_m < 10:   return 7
    if float_m < 20:   return 6
    if float_m < 50:   return 4
    if float_m < 100:  return 2
    return 0

def _score_price_range(price: float) -> int:
    if 2 <= price <= 10:    return 5
    if 10 < price <= 20:    return 4
    if 1 <= price < 2:      return 3
    if 20 < price <= 30:    return 2
    if 0.5 <= price < 1:    return 1
    return 0

_VIX_CACHE = {"at": 0.0, "v": None}


def _vix_now():
    import time as _t
    if _t.time() - _VIX_CACHE["at"] > 900:
        try:
            import urllib.request, json as _j, os as _os
            base = _os.getenv("LOCAL_API_BASE", "http://127.0.0.1:7777")
            with urllib.request.urlopen(f"{base}/api/v2/trade-ai", timeout=5) as r:
                d = _j.load(r); d = d.get("data", d)
                _VIX_CACHE["v"] = float(d.get("vix")) if d.get("vix") is not None else None
        except Exception:
            pass
        _VIX_CACHE["at"] = _t.time()
    return _VIX_CACHE["v"]


def _grade(score: int, weights: Dict[str, Any]) -> tuple[str, str]:
    bands = weights.get("grade_bands", {})
    rules = weights.get("decision_rules", {})
    for grade_name, band in bands.items():
        if band["min"] <= score <= band["max"]:
            break
    else:
        grade_name = "D"
    decision = "AVOID"
    go_min = rules.get("GO", {}).get("min_score", 40)
    wait_min = rules.get("WAIT", {}).get("min_score", 30)
    # Regime-aware thresholds (2026-06-11): in fear regimes momentum follow-through degrades — demand more.
    vix = _vix_now()
    if vix is not None and vix > 32:
        go_min += 10
        wait_min += 5
    elif vix is not None and vix > 25:
        go_min += 5
        wait_min += 3
    if score >= go_min:
        decision = "GO"
    elif score >= wait_min:
        decision = "WAIT"
    return grade_name, decision


# ── Public scorer ─────────────────────────────────────────────────────────────



# ── Outcome feedback (2026-06-11): strategy-family scar from LIVE paper results ──────────────────────────
# The 65-pt rubric previously never saw realized outcomes. Now: a ticker's screener strategy_class maps to
# its consolidated strategy family; that family's live 30d paper win-rate scales the score (bounded, gentle).
# Advisory-grade: bounded 0.85..1.10, min sample 5, cached 10 min. Aliases follow the 2026-06-11 consolidation.
_CLASS_ALIAS = {"day_scalp": "momentum_scalp", "swing_trade": "swing_breakout",
                "gap_and_go": "momentum_scalp", "earnings_catalyst": "earnings_post_momentum"}
_SCAR_CACHE: dict = {"at": 0.0, "map": {}}


_SRCW_CACHE: dict = {"at": 0.0, "map": {}}


def _source_weight(screener_name: str) -> float:
    """Arbitration layer: bounded per-list weight from source_weights (computed daily from attributed
    candidates->GO->proposal->trade flow). Neutral 1.0 until a list earns >=5 closed trades."""
    if not screener_name:
        return 1.0
    import time as _t
    if _t.time() - _SRCW_CACHE["at"] > 600:
        try:
            from db_adapter import _get_conn
            cur = _get_conn().cursor()
            cur.execute("SELECT source_key, weight FROM source_weights WHERE window_days=30")
            _SRCW_CACHE["map"] = {k: float(w) for k, w in cur.fetchall()}
        except Exception:
            pass
        _SRCW_CACHE["at"] = _t.time()
    return _SRCW_CACHE["map"].get(screener_name, 1.0)


def _strategy_outcome_scar(strategy_class: str) -> float:
    if not strategy_class:
        return 1.0
    import time as _t
    if _t.time() - _SCAR_CACHE["at"] > 600:
        try:
            from db_adapter import _get_conn
            cur = _get_conn().cursor()
            cur.execute("""SELECT strategy_id, count(*) FILTER (WHERE pnl <> 0) n,
                                  count(*) FILTER (WHERE pnl > 0) wins
                           FROM paper_trades
                           WHERE status='closed' AND closed_at > NOW() - INTERVAL '30 days'
                           GROUP BY strategy_id""")
            m = {}
            for sid, n, wins in cur.fetchall():
                if n and n >= 5:
                    wr = wins / n
                    m[sid] = 0.85 if wr < 0.35 else 0.93 if wr < 0.45 else 1.10 if wr > 0.65 else 1.05 if wr > 0.55 else 1.0
            _SCAR_CACHE["map"] = m
            _SCAR_CACHE["at"] = _t.time()
        except Exception:
            _SCAR_CACHE["at"] = _t.time()   # don't retry every call on DB issues
    sid = _CLASS_ALIAS.get(strategy_class, strategy_class)
    return _SCAR_CACHE["map"].get(sid, 1.0)

def score_ticker(
    ticker_row: Dict[str, Any],
    enrichment: Dict[str, Any],
    weights: Dict[str, Any],
    use_llm: bool = True,
) -> Dict[str, Any]:
    """Score one ticker and return a full ScoredTicker dict."""
    symbol = str(ticker_row.get("symbol", "")).upper()

    # Raw Finviz fields
    price       = float(ticker_row.get("price", 0) or 0)
    change_pct  = float(ticker_row.get("change_percent", 0) or 0)
    gap_pct     = float(ticker_row.get("gap_percent", 0) or 0)
    rvol        = float(ticker_row.get("relative_volume", 0) or 0)
    if rvol == 0 and gap_pct == 0:
        print(f"  [scoring] ⚠️  {symbol}: RVOL and gap both zero — likely missing from screener export")
    # float_m injected from finviz_enrichment (millions), fallback to float_shares
    float_m_direct = float(ticker_row.get("float_m", 0) or 0)
    float_raw   = float(ticker_row.get("float_shares", 0) or 0)
    float_raw_m = float_raw / 1_000_000 if float_raw > 1_000 else float_raw
    float_m     = float_m_direct if float_m_direct > 0 else float_raw_m  # prefer enriched

    # Catalyst enrichment
    catalyst_tier  = enrichment.get("catalyst_tier", "none")
    catalyst_count = enrichment.get("catalyst_count", 0)
    has_fresh      = enrichment.get("has_fresh_catalyst", False)
    top_catalyst   = enrichment.get("top_catalyst")
    headlines      = [c.get("title", "") for c in enrichment.get("catalysts", [])[:5]]

    # Score pillars
    cat_score, is_ambiguous = _score_catalyst_keywords(catalyst_tier, catalyst_count, has_fresh, top_catalyst)

    # Use Ollama score from Stage 6 if available (overrides keyword + Haiku)
    if enrichment.get("ollama_catalyst_score") is not None:
        cat_score = int(enrichment["ollama_catalyst_score"])
    elif use_llm and is_ambiguous and headlines:
        cat_score = _haiku_score_catalyst(symbol, headlines, (top_catalyst or {}).get("summary", ""))

    # RAG catalyst confirmation bonus (+3, capped at pillar max 15)
    if enrichment.get("rag_catalyst_confirmed"):
        cat_score = min(cat_score + 3, 15)

    rvol_score   = _score_rvol(rvol, float_m)
    pa_score     = _score_price_action(change_pct, gap_pct, rvol)
    float_score  = _score_float(float_m)
    price_score  = _score_price_range(price)

    # ── 6th pillar: sector momentum (max 5 pts) ───────────────────────────
    # Provided by market_context.py via enrichment["sector_momentum_score"]
    # If sector is leading (in top 3 by % change), 5 pts; top half = 3 pts; else 0
    sector_mom_score: int = int(ticker_row.get("sector_momentum_score", 0) or 0)
    sector_mom_score = max(0, min(5, sector_mom_score))

    total = cat_score + rvol_score + pa_score + float_score + price_score + sector_mom_score

    # Scar factor: penalize symbols with poor scalp history (needs 3+ outcomes)
    scar = enrichment.get("scar_factor", 1.0)
    if scar < 1.0:
        total = int(total * scar)
    # outcome feedback: live strategy-family win-rate scar (bounded; logged in pillar breakdown)
    outcome_scar = _strategy_outcome_scar(str(ticker_row.get("strategy_class") or ""))
    if outcome_scar != 1.0:
        total = int(total * outcome_scar)
    _outcome_scar_applied = outcome_scar
    # arbitration: per-list source weight (bounded 0.9..1.1, evidence-gated)
    src_w = _source_weight(str(ticker_row.get("screener_name") or ""))
    if src_w != 1.0:
        total = int(total * src_w)

    # ── 7th pillar: technical confluence (max 10 pts) ─────────────────────
    # Non-fatal — Trade AI pipeline must never fail due to indicator engine issues
    confluence_score = 0
    confluence_tier = None
    strategy_badges = []
    try:
        from indicator_engine import analyze_confluence
        conf_result = analyze_confluence(symbol, profile='scalp')
        if conf_result.get('ok'):
            confluence_score = conf_result.get('confluence_score', 0)
            confluence_tier = conf_result.get('confluence_tier')
            strategy_badges = conf_result.get('strategy_badges', [])
    except Exception as e:
        logger.warning(f"Confluence pillar skipped for {symbol} (non-fatal): {e}")

    total = total + confluence_score
    total = max(0, min(65, total))   # new max is 65 (was 55)

    if top_catalyst is not None:
        try:
            top_catalyst["_price_reaction"] = abs(gap_pct) + abs(change_pct)
        except Exception:
            pass
    pillar_breakdown = {
        "catalyst":          cat_score,
        "relative_volume":   rvol_score,
        "price_action":      pa_score,
        "float":             float_score,
        "price_range":       price_score,
        "sector_momentum":   sector_mom_score,
        "confluence":        confluence_score,
        "outcome_scar":      locals().get("_outcome_scar_applied", 1.0),
    }

    grade, decision = _grade(total, weights)

    # Criteria flags (used by Word/PDF dashboard sections)
    criteria = {
        "has_catalyst":       catalyst_count > 0,
        "has_high_impact":    catalyst_tier == "high_impact",
        "has_fresh_catalyst": has_fresh,
        "rvol_above_3":       rvol >= 3,
        "rvol_above_5":       rvol >= 5,
        "float_under_50m":    0 < float_m <= 50,
        "price_in_range":     0.5 <= price <= 30,
        "gap_above_5pct":     gap_pct >= 5,
        "change_above_10pct": change_pct >= 10,
    }
    criteria_met = sum(criteria.values())
    criteria_total = len(criteria)

    # Ollama pre-plan for WAIT/developing tickers (score 25-54)
    ollama_preplan = ""
    if use_llm and 25 <= total < 55 and decision in ("WAIT", "GO"):
        try:
            ollama_preplan = _ollama_preplan(
                symbol, total, decision, top_catalyst,
                rvol, price, change_pct
            )
        except Exception:
            pass

    # Escalate strong setups to Sonnet for narrative
    llm_narrative = ""
    should_escalate = (
        use_llm and (
            decision == "GO"
            or rvol >= 5.0
            or catalyst_tier == "high_impact"
        )
    )
    if should_escalate:
        llm_narrative = _sonnet_narrative(
            symbol, total, grade, decision, pillar_breakdown,
            top_catalyst, rvol, price, float_m, change_pct, gap_pct,
        )

    return {
        "symbol":            symbol,
        "company":           ticker_row.get("company", ""),
        "sector":            ticker_row.get("sector", ""),
        "score":             total,
        "grade":             grade,
        "decision":          decision,
        "pillar_breakdown":  pillar_breakdown,
        "criteria":          criteria,
        "criteria_met":      criteria_met,
        "criteria_total":    criteria_total,
        "llm_narrative":     llm_narrative,
        "ollama_preplan":    ollama_preplan,
        "ollama_flag":       str(enrichment.get("ollama_flag","") or ""),
        "ollama_risk":       str(enrichment.get("ollama_risk","") or ""),
        "ollama_summary":    str(enrichment.get("ollama_summary","") or ""),
        "catalyst_type":     str(enrichment.get("catalyst_type","") or ""),
        "catalyst_tier":     catalyst_tier,
        "top_catalyst":      top_catalyst,
        "catalysts":         enrichment.get("catalysts", []),
        "catalyst_count":    catalyst_count,
        "has_fresh_catalyst": has_fresh,
        # Market data
        "price":             price,
        "change_percent":    change_pct,
        "gap_percent":       gap_pct,
        "relative_volume":   rvol,
        "float_m":           round(float_m, 2),
        "volume":            ticker_row.get("volume", 0),
        "avg_volume":        ticker_row.get("avg_volume", 0),
        "source_count":      ticker_row.get("source_count", 1),
        "source_lists":      ticker_row.get("source_lists", ""),
        "run_window":        ticker_row.get("run_window", ""),
        # Technical confluence pillar
        "confluence_score":  confluence_score,
        "confluence_tier":   confluence_tier,
        "strategy_badges":   strategy_badges,
    }




def pre_score(ticker_row: Dict[str, Any], weights: Dict[str, Any]) -> int:
    """Fast 4-pillar pre-score using only Finviz data — no catalyst API needed.

    Uses RVOL + float + price action + price range + sector momentum.
    Catalyst pillar is excluded (max possible without catalyst = 40).
    Used to filter candidates before expensive API enrichment.
    """
    price      = float(ticker_row.get("price", 0) or 0)
    change_pct = float(ticker_row.get("change_percent", 0) or 0)
    gap_pct    = float(ticker_row.get("gap_percent", 0) or 0)
    rvol       = float(ticker_row.get("relative_volume", 0) or 0)
    float_raw  = float(ticker_row.get("float_shares", 0) or 0)
    float_m    = float_raw / 1_000_000 if float_raw > 1_000 else float_raw
    sector_mom = int(ticker_row.get("sector_momentum_score", 0) or 0)

    return max(0, min(40,
        _score_rvol(rvol)
        + _score_float(float_m)
        + _score_price_action(change_pct, gap_pct, rvol)
        + _score_price_range(price)
        + min(5, sector_mom)
    ))

def score_all(
    tickers: List[Dict[str, Any]],
    enrichments: Dict[str, Dict],
    project_root: str = ".",
    use_llm: bool = True,
) -> List[Dict[str, Any]]:
    """Score all tickers, return sorted list (highest score first).
    Includes data quality hardening: disqualification, catalyst validation,
    industry fallback, RVOL micro-float cap.
    """
    weights = _load_weights(project_root)
    results = []
    disqualified_count = 0
    unverified_count = 0

    for row in tickers:
        sym = str(row.get("symbol", "")).upper()
        enrichment = enrichments.get(sym, {
            "catalyst_tier": "none", "catalyst_count": 0,
            "has_fresh_catalyst": False, "top_catalyst": None, "catalysts": [],
        })

        # ── FIX 1: Risk classification (squeeze manual vs hard DQ) ──
        import sys as _sys_sq
        from pathlib import Path as _Path_sq
        _sq_lib = _Path_sq(__file__).resolve().parent / "lib"
        if str(_sq_lib) not in _sys_sq.path:
            _sys_sq.path.insert(0, str(_sq_lib))
        from squeeze_manual_review import classify_ticker_risk, apply_squeeze_manual_fields
        from high_rvol_manual_review import qualifies_high_rvol_manual, apply_high_rvol_manual_fields
        from micro_float_manual_review import apply_micro_float_manual_fields
        from low_price_manual_review import apply_low_price_manual_fields
        from catalyst_exception import attach_catalyst_exception_tags

        risk = classify_ticker_risk(sym, row)
        if risk["action"] in ("hard_dq", "standard_dq"):
            disq_reason = risk["reasons"]
            disqualified_count += 1
            print(f"  [scoring] DISQUALIFIED {sym}: {disq_reason}")
            results.append({
                "symbol": sym, "score": 0, "grade": "DISQUALIFIED", "decision": "AVOID",
                "disqualified": True, "disqualification_reason": disq_reason,
                "catalyst": f"DISQUALIFIED: {disq_reason}",
                "catalyst_verified": False,
                "industry": get_industry_with_fallback(sym, row),
                "pillar_breakdown": {}, "criteria": {}, "criteria_met": 0, "criteria_total": 0,
                "price": float(row.get("price", 0) or 0),
                "change_pct": str(row.get("change_percent", row.get("change_pct", ""))),
                "gap_pct": str(row.get("gap_percent", row.get("gap_pct", ""))),
                "rvol": float(row.get("relative_volume", 0) or 0),
                "float_m": float(row.get("float_m", 0) or 0),
                "top_catalyst": enrichment.get("top_catalyst"),
            })
            continue

        squeeze_manual = risk["action"] == "squeeze_manual"
        micro_float_manual = risk["action"] == "micro_float_manual"
        low_price_manual = risk["action"] == "low_price_manual"

        # ── FIX 2: Catalyst relevance validation ──
        top_cat = enrichment.get("top_catalyst") or {}
        raw_headline = top_cat.get("title", "")
        company_name = (row.get("company") or row.get("Company Name") or "")
        if isinstance(company_name, str):
            company_name = company_name.strip()
        else:
            company_name = ""
        # If company name is missing or just the symbol, use yfinance cache
        if not company_name or company_name == sym or company_name == "None" or len(company_name) <= 5:
            company_name = _get_company_name(sym)
        catalyst_verified = None
        catalyst_confidence = None

        if raw_headline:
            is_rel, conf, rel_reason = validate_catalyst_relevance(sym, company_name, raw_headline)
            catalyst_verified = is_rel
            catalyst_confidence = conf
            if not is_rel:
                unverified_count += 1
                print(f"  [scoring] CATALYST_UNVERIFIED {sym}: conf={conf:.2f} reason={rel_reason} headline='{raw_headline[:60]}'")
                # Try Yahoo fallback
                fallback = get_verified_catalyst_fallback(sym, company_name)
                if fallback and "No verified" not in fallback:
                    top_cat["title"] = fallback
                    enrichment["top_catalyst"] = top_cat
                    catalyst_verified = True
                    print(f"  [scoring]   → Yahoo fallback: {fallback[:60]}")

        # ── FIX 3: Industry fallback ──
        industry = get_industry_with_fallback(sym, row)
        row["industry"] = industry

        # Sector context (country, 1M perf, vs sector)
        sector_ctx = get_sector_context(sym, industry)

        # Score normally
        scored = score_ticker(row, enrichment, weights, use_llm=use_llm)
        scored["disqualified"] = False
        scored["disqualification_reason"] = ""
        scored["catalyst_verified"] = catalyst_verified
        scored["catalyst_confidence"] = catalyst_confidence
        scored["industry"] = industry
        scored["country"] = sector_ctx.get("country", "")
        scored["sector"] = sector_ctx.get("sector", row.get("sector", ""))
        scored["sector_etf"] = sector_ctx.get("sector_etf", "")
        scored["ticker_perf_1m"] = sector_ctx.get("ticker_perf_1m")
        scored["sector_perf_1m"] = sector_ctx.get("sector_perf_1m")
        scored["vs_sector_pct"] = sector_ctx.get("vs_sector_pct")
        if squeeze_manual:
            apply_squeeze_manual_fields(scored, rs_reason=risk["reverse_split"] or risk["reasons"])
            print(f"  [scoring] SQUEEZE_MANUAL_REVIEW {sym}: {risk['reasons'][:80]}")
        elif micro_float_manual:
            apply_micro_float_manual_fields(scored, mf_reason=risk["reasons"])
            print(f"  [scoring] MICRO_FLOAT_MANUAL_REVIEW {sym}: {risk['reasons'][:80]}")
        elif low_price_manual:
            apply_low_price_manual_fields(scored, lp_reason=risk["reasons"])
            print(f"  [scoring] LOW_PRICE_MANUAL_REVIEW {sym}: {risk['reasons'][:80]}")
        elif qualifies_high_rvol_manual(scored):
            apply_high_rvol_manual_fields(scored)
            print(f"  [scoring] HIGH_RVOL_MANUAL_REVIEW {sym}: RVOL={scored.get('rvol')}")
        results.append(scored)

    attach_catalyst_exception_tags(results)

    if disqualified_count:
        print(f"  [scoring] Data quality: {disqualified_count} disqualified, {unverified_count} catalyst unverified")

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def filter_candidates(
    tickers: List[Dict[str, Any]],
    project_root: str = ".",
    min_pre_score: int = 8,
) -> tuple[List[str], List[Dict[str, Any]]]:
    """Two-pass filter: pre-score all tickers with no API calls, return candidates.

    Returns (candidate_symbols, all_tickers_with_pre_score).
    Only candidate_symbols need catalyst enrichment.
    Tickers below min_pre_score are scored 0 on catalyst and excluded from
    expensive API calls entirely.

    Typical result: 30-80 candidates out of 600+ tickers.
    """
    weights    = _load_weights(project_root)
    candidates = []
    for row in tickers:
        ps = pre_score(row, weights)
        boost = row.get("_pre_score")
        if boost is not None:
            try:
                ps = max(ps, int(boost))
            except (TypeError, ValueError):
                pass
        row["_pre_score"] = ps
        if ps >= min_pre_score:
            candidates.append(str(row.get("symbol", "")).upper())
    return candidates, tickers
