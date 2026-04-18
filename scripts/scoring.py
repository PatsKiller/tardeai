"""scoring.py — 5-pillar hybrid scoring engine.

Pipeline per ticker:
  1. Keyword rules score each pillar from Finviz data + catalyst enrichment
  2. If catalyst impact is ambiguous, Claude Haiku re-evaluates the catalyst pillar
  3. If score >= 40 OR RVOL >= 5 OR fresh high-impact catalyst → escalate to Sonnet
     for a full narrative analysis of the setup
  4. Returns ScoredTicker with grade, decision, per-pillar breakdown, and LLM narrative
"""
from __future__ import annotations
import json, os
from typing import Any, Dict, List, Optional
import threading

# Ollama serialization lock — one call at a time, no timeout pile-up
_ollama_lock = threading.Lock()

def _ollama_serialized(prompt: str, num_predict: int = 500, timeout: int = 90, model: str = "qwen3:14b") -> str:
    """Serialized Ollama call — acquires lock, runs, releases. No pile-up."""
    import urllib.request
    import json as _json
    payload = _json.dumps({
        "model": model, "stream": False, "prompt": prompt,
        "options": {"temperature": 0.1, "num_predict": num_predict}
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    with _ollama_lock:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _json.loads(resp.read()).get("response", "").strip()
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
        print(f"  [ollama-catalyst] {symbol} error: {e} — falling back to Haiku")
        # Fallback to Claude Haiku if Ollama unavailable
        try:
            model = os.getenv("CLAUDE_CHEAP_MODEL", "claude-haiku-4-5-20251001")
            headlines_str2 = "\n".join(f"- {h}" for h in headlines[:5])
            prompt2 = (
                f"Score catalyst for {symbol} 0-15. "
                f"15=FDA/earnings/M&A. 8=upgrade. 4=generic. 0=noise.\n"
                f"Headlines:\n{headlines_str2}\nReply integer only."
            )
            result = _anthropic_complete(prompt2, model, max_tokens=10)
            return max(0, min(15, int(result.strip())))
        except Exception:
            pass
    return 4  # fallback score

def _sonnet_narrative(symbol: str, score: int, grade: str, decision: str,
                       pillar_breakdown: Dict[str, int], top_catalyst: Optional[Dict],
                       rvol: float, price: float, float_shares: float,
                       change_pct: float, gap_pct: float) -> str:
    """Ask Claude Sonnet for a concise scalper-focused narrative for GO/escalated tickers."""
    model = os.getenv("CLAUDE_ESCALATION_MODEL", "claude-sonnet-4-5-20251015")
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
    return _anthropic_complete(prompt, model, max_tokens=200)

def _ollama_preplan(symbol: str, score: int, decision: str,
                    top_catalyst: Optional[Dict], rvol: float,
                    price: float, change_pct: float) -> str:
    """Ollama pre-plan for tickers scoring 25-47 (below A+ threshold).
    Free alternative to Sonnet for developing setups."""
    import urllib.request
    catalyst_title = (top_catalyst or {}).get("title", "No catalyst")
    prompt = (
        f"Scalp trade pre-plan for {symbol}. Score: {score}/55 ({decision}).\n"
        f"Price: ${price} | Change: {change_pct:+.1f}% | RVOL: {rvol:.1f}x\n"
        f"Catalyst: {catalyst_title[:100]}\n\n"
        f"Write 2 sentences: key level to watch and main risk. Be specific. No disclaimers."
    )
    try:
        payload = json.dumps({
            "model": "qwen3:14b",
            "stream": False,
            "prompt": prompt,
            "options": {"temperature": 0.2}
        }).encode()
        data = _ollama_call_serialized({
            "model": "qwen3:14b",
            "stream": False,
            "prompt": prompt,
            "options": {"temperature": 0.2, "num_predict": 80}
        }, timeout=120)
        return data.get("response", "").strip()
    except Exception as e:
        return f"[pre-plan unavailable: {e}]"




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
        base = 8
        return min(15, int(base * recency_mult)), True   # ambiguous → LLM review
    if catalyst_tier == "low_impact":
        base = 4
        return min(15, int(base * recency_mult)), False
    return 0, False

def _score_rvol(rvol: float) -> int:
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

def _grade(score: int, weights: Dict[str, Any]) -> tuple[str, str]:
    bands = weights.get("grade_bands", {})
    rules = weights.get("decision_rules", {})
    for grade_name, band in bands.items():
        if band["min"] <= score <= band["max"]:
            break
    else:
        grade_name = "D"
    decision = "AVOID"
    if score >= rules.get("GO", {}).get("min_score", 40):
        decision = "GO"
    elif score >= rules.get("WAIT", {}).get("min_score", 30):
        decision = "WAIT"
    return grade_name, decision


# ── Public scorer ─────────────────────────────────────────────────────────────

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

    rvol_score   = _score_rvol(rvol)
    pa_score     = _score_price_action(change_pct, gap_pct, rvol)
    float_score  = _score_float(float_m)
    price_score  = _score_price_range(price)

    # ── 6th pillar: sector momentum (max 5 pts) ───────────────────────────
    # Provided by market_context.py via enrichment["sector_momentum_score"]
    # If sector is leading (in top 3 by % change), 5 pts; top half = 3 pts; else 0
    sector_mom_score: int = int(ticker_row.get("sector_momentum_score", 0) or 0)
    sector_mom_score = max(0, min(5, sector_mom_score))

    total = cat_score + rvol_score + pa_score + float_score + price_score + sector_mom_score
    total = max(0, min(55, total))   # new max is 55

    pillar_breakdown = {
        "catalyst":          cat_score,
        "relative_volume":   rvol_score,
        "price_action":      pa_score,
        "float":             float_score,
        "price_range":       price_score,
        "sector_momentum":   sector_mom_score,
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

    # Ollama pre-plan for WAIT/developing tickers (score 25-47)
    ollama_preplan = ""
    if use_llm and 25 <= total < 48 and decision in ("WAIT", "GO"):
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
    """Score all tickers, return sorted list (highest score first)."""
    weights = _load_weights(project_root)
    results = []
    for row in tickers:
        sym = str(row.get("symbol", "")).upper()
        enrichment = enrichments.get(sym, {
            "catalyst_tier": "none", "catalyst_count": 0,
            "has_fresh_catalyst": False, "top_catalyst": None, "catalysts": [],
        })
        scored = score_ticker(row, enrichment, weights, use_llm=use_llm)
        results.append(scored)
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
        row["_pre_score"] = ps
        if ps >= min_pre_score:
            candidates.append(str(row.get("symbol", "")).upper())
    return candidates, tickers
