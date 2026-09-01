"""
catalyst_intelligence.py — Ollama-powered catalyst analysis.

Replaces Claude Haiku for catalyst scoring.
Adds: dilution detection, trap flagging, memory-aware context.
Runs on pre-market FULL runs only (not LIVE cycles — too slow).

Returns per-ticker:
  ollama_catalyst_score : int 0-15 (replaces haiku score)
  ollama_flag           : "GO" | "WATCH" | "TRAP" | "DILUTION" | "AVOID" | "NEUTRAL"
  ollama_risk           : str — one-line risk summary
  ollama_summary        : str — one-line catalyst summary
  catalyst_type         : "fda" | "earnings" | "ma" | "dilution" | "upgrade" | "other"
  memory_context        : dict | None — prior observations if ticker seen before
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add scripts dir to path
sys.path.insert(0, str(Path(__file__).parent))

from local_llm_config import get_local_llm_model, get_local_llm_base_url, apply_ollama_runtime_env

apply_ollama_runtime_env()

OLLAMA_URL = get_local_llm_base_url().rstrip("/") + "/api/chat"
OLLAMA_MODEL_FAST = get_local_llm_model()
OLLAMA_MODEL = get_local_llm_model()
OLLAMA_TIMEOUT = 120  # seconds per ticker — fail fast, don't block pipeline

# Dilution/trap keywords — Ollama confirms but we pre-flag these
DILUTION_KEYWORDS = [
    "private placement", "registered direct", "atm offering",
    "at-the-market offering", "shelf registration", "secondary offering",
    "warrant", "convertible note", "equity line", "dilutive",
]

TRAP_KEYWORDS = [
    "reverse split", "going concern", "default notice", "nasdaq deficiency",
    "sec investigation", "class action", "restatement", "audit failure",
    "delisting notice",
]


def _pre_flag(headlines: List[str]) -> tuple[str, str]:
    """
    Fast keyword pre-flag before sending to Ollama.
    Returns (flag, reason) or ("NEUTRAL", "")
    """
    combined = " ".join(headlines).lower()
    for kw in DILUTION_KEYWORDS:
        if kw in combined:
            return "DILUTION", f"Dilution signal: {kw}"
    for kw in TRAP_KEYWORDS:
        if kw in combined:
            return "TRAP", f"Trap signal: {kw}"
    return "NEUTRAL", ""


def _ollama_analyze(symbol: str, headlines: List[str],
                    memory_context: Optional[Dict] = None) -> Dict:
    """Send catalyst headlines to Ollama for analysis."""
    import urllib.request
    import urllib.error

    headlines_str = "\n".join(f"- {h}" for h in headlines[:5])

    # Build memory context string if available
    mem_str = ""
    if memory_context and memory_context.get("times_seen", 0) > 0:
        mem_str = (
            f"\nMEMORY: This ticker has appeared {memory_context['times_seen']} times. "
            f"Pattern: {memory_context['pattern']}. "
            f"Trust score: {memory_context['trust_score']}. "
        )
        if memory_context.get("recent"):
            last = memory_context["recent"][-1]
            mem_str += f"Last seen {last.get('date')}: score {last.get('score')}, flag {last.get('flag')}."

    # F2: Finviz/Yahoo enrich — Brave search API reserved for residual-web.
    # Consumer: trade_ai_orchestrator.analyze_all_catalysts. Empty → no WEB NEWS.
    brave_context = ""
    try:
        articles = []
        try:
            from finviz_news import fetch_finviz_news
            articles = list(fetch_finviz_news(symbol, lookback_hours=48) or [])[:3]
        except Exception:
            articles = []
        if not articles:
            try:
                from yahoo_news import fetch_yahoo_news
                articles = list(fetch_yahoo_news(symbol, lookback_hours=48) or [])[:3]
            except Exception:
                articles = []
        if articles:
            bits = []
            for a in articles:
                title = (a.get("headline") or a.get("title") or "")[:100]
                src = a.get("source") or a.get("original_source") or ""
                if title:
                    bits.append(f"{title} ({src})" if src else title)
            if bits:
                brave_context = "\nWEB NEWS: " + " | ".join(bits)[:400]
    except Exception:
        pass

    prompt = f"""/no_think
Analyze stock catalyst for {symbol} and output JSON only.
Headlines: {headlines_str[:200]}{mem_str}{brave_context}

Rules: catalyst_score 0-15 (15=FDA approval/earnings beat/M&A, 8=upgrade/partnership, 3=dilution/offering, 0=noise).
flag must be one of: GO, WATCH, TRAP, DILUTION, AVOID, NEUTRAL.
catalyst_type must be one of: fda, earnings, ma, dilution, upgrade, partnership, other.

Output valid JSON only, no other text:
{{"catalyst_score": <integer>, "flag": "<flag>", "catalyst_type": "<type>", "risk": "<10 words max>", "summary": "<10 words max>"}}"""

    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
        "think": False,
        "options": {"temperature": 0.1}
    }).encode()

    try:
        # Route through local_llm.generate() — provides serialization + fallback + audit
        from local_llm import generate
        text = generate(prompt, timeout=30,
                        caller="catalyst_intelligence", process_type="STANDARD") or ""
        if True:
            # Strip thinking tags from qwen3 responses
            import re as _re
            text = _re.sub(r'<think>.*?</think>', '', text, flags=_re.DOTALL).strip()
            # Parse JSON from response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    result = json.loads(text[start:end])
                    return {
                        "ollama_catalyst_score": max(0, min(15, int(result.get("catalyst_score", 4)))),
                        "ollama_flag": result.get("flag", "NEUTRAL"),
                        "catalyst_type": result.get("catalyst_type", "other"),
                        "ollama_risk": result.get("risk", ""),
                        "ollama_summary": result.get("summary", ""),
                        "ollama_ok": True,
                    }
                except (json.JSONDecodeError, ValueError):
                    pass
    except Exception as e:
        print(f"  [catalyst-intel] Ollama error for {symbol}: {e}")

    return {"ollama_ok": False, "ollama_catalyst_score": None}


def analyze_catalyst(symbol: str, enrichment: Dict,
                     memory: Dict, project_root: str = ".") -> Dict:
    """
    Main entry point. Analyze one ticker's catalyst.
    Returns enriched catalyst data.
    """
    from ticker_memory import get_ticker_context, add_observation, save_memory

    headlines = [
        item.get("title", "")
        for item in enrichment.get("catalysts", enrichment.get("articles", []))[:5]
        if item.get("title")
    ]

    if not headlines:
        return {"ollama_ok": False, "ollama_flag": "NEUTRAL", "ollama_catalyst_score": 0}

    # Fast pre-flag
    pre_flag, pre_reason = _pre_flag(headlines)

    # Get memory context
    mem_ctx = get_ticker_context(memory, symbol)

    # If pre-flagged as dilution/trap, still send to Ollama for confirmation
    # but set a low timeout since we're already suspicious
    result = _ollama_analyze(symbol, headlines, mem_ctx)

    # Pre-flag is authoritative — always apply if keyword matched
    if pre_flag in ("DILUTION", "TRAP"):
        result["ollama_flag"] = pre_flag
        result["ollama_risk"] = pre_reason
        result["ollama_catalyst_score"] = 3
        result["ollama_ok"] = True
        result["catalyst_type"] = "dilution" if pre_flag == "DILUTION" else "trap"
    elif result.get("ollama_flag") not in ("DILUTION", "TRAP") and not result.get("ollama_ok"):
        result["ollama_flag"] = "NEUTRAL"

    result["memory_context"] = mem_ctx
    result["pre_flag"] = pre_flag

    return result


def analyze_all_catalysts(tickers: List[Dict], enrichments: Dict,
                           project_root: str = ".") -> Dict[str, Dict]:
    """
    Analyze catalysts for all tickers that passed pre-score filter.
    Updates ticker_memory.json with observations.
    Returns {symbol: analysis_result}
    """
    from ticker_memory import load_memory, add_observation, save_memory

    memory = load_memory(project_root)
    results = {}
    today = __import__("datetime").date.today().isoformat()

    # Only analyze tickers with actual catalyst data
    candidates = [
        t for t in tickers
        if enrichments.get(t.get("symbol",""), {}).get("has_fresh_catalyst")
        or enrichments.get(t.get("symbol",""), {}).get("catalyst_count", 0) > 0
    ]

    # Ensure model is warm before batch
    try:
        import urllib.request as _ur, json as _j
        _p = _j.dumps({"model":OLLAMA_MODEL,"stream":False,"messages":[{"role":"user","content":"ready"}],"think":False,"options":{"num_predict":1}}).encode()
        _r = _ur.Request(OLLAMA_URL,data=_p,headers={"Content-Type":"application/json"},method="POST")
        with _ur.urlopen(_r, timeout=60): pass
    except Exception: pass
    print(f"  [catalyst-intel] Analyzing {len(candidates)} tickers with catalysts...")

    for t in candidates:
        sym = t["symbol"]
        enrichment = enrichments.get(sym, {})
        start = time.time()

        result = analyze_catalyst(sym, enrichment, memory, project_root)
        elapsed = round(time.time() - start, 1)

        flag = result.get("ollama_flag", "NEUTRAL")
        score = result.get("ollama_catalyst_score", "?")
        print(f"  [catalyst-intel] {sym}: flag={flag} score={score} ({elapsed}s)")

        results[sym] = result

        # Write to memory if Ollama succeeded
        if result.get("ollama_ok"):
            observation = {
                "date": today,
                "score": t.get("_pre_score", 0),
                "catalyst_type": result.get("catalyst_type", "other"),
                "catalyst_headline": enrichment.get("top_catalyst", {}).get("title", "")[:100],
                "ollama_flag": flag,
                "ollama_risk": result.get("ollama_risk", ""),
                "ollama_score": score,
                "decision": None,  # filled in after scoring
            }
            memory = add_observation(memory, sym, observation)

    save_memory(memory, project_root)
    print(f"  [catalyst-intel] Memory updated: {len(memory)} tickers tracked")
    return results
