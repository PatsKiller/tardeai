"""trade_plan.py — AI-generated trade plans for A+ setups (score >= 48).

Calls Claude Sonnet per ticker. Returns structured trade plan with:
  entry_zone    : suggested entry price range
  stop_loss     : technical stop level
  target_r1     : first target (1R)
  target_r2     : second target (2R+)
  risk_reward   : numeric R:R ratio
  max_loss_pct  : max % loss at stop from entry midpoint
  plan_text     : 3-4 sentence narrative (scalper-focused)
  disclaimer    : always present — AI analysis, not financial advice

Only runs on tickers with score >= 48 (A+) to control API cost.

Note: All plans are AI-generated technical analysis for informational
purposes only. They are not financial advice. Always conduct your own
research and use proper risk management before trading.
"""
from __future__ import annotations
import json, os
from typing import Any, Dict, List, Optional

APLUS_THRESHOLD = 48
DISCLAIMER = (
    "AI-generated technical analysis for informational purposes only. "
    "Not financial advice. Always conduct your own research and apply "
    "proper risk management before trading."
)


def _env(k: str) -> str:
    return os.getenv(k, "").strip()


def _sonnet(prompt: str, max_tokens: int = 400) -> str:
    """Now routed through the FREE Grok OAuth lane with local-Ollama fallback (operator free-OAuth-only
    rule, 2026-06-11). Name kept for call-site compatibility; metered Anthropic path removed."""
    try:
        import llm_lane
        out = llm_lane.generate(prompt, lane="deepseek-flash", timeout=120)
        if out and not str(out).startswith("["):
            return str(out).strip()
    except Exception:
        pass
    try:
        import urllib.request, json as _json, os as _os
        url = (_os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")) + "/api/generate"
        payload = _json.dumps({"model": _os.getenv("LOCAL_LLM_MODEL", "gemma3:12b"), "prompt": prompt,
                               "stream": False, "options": {"num_predict": max_tokens}}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            return (_json.load(r).get("response") or "").strip()
    except Exception as e:
        return f"[LLM error: {e}]"


def _sonnet_DISABLED_metered(prompt: str, max_tokens: int = 400) -> str:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=_env("ANTHROPIC_API_KEY"))
        msg = client.messages.create(
            model=_env("CLAUDE_ESCALATION_MODEL") or "claude-sonnet-4-5-20251015",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        return f"[trade_plan error: {e}]"


def _parse_json_block(text: str) -> Optional[Dict]:
    """Extract JSON from model response."""
    try:
        start = text.find("{")
        end   = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except Exception:
        pass
    return None


def generate_trade_plan(ticker: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a structured trade plan for one A+ ticker.

    Returns a dict with entry_zone, stop_loss, target_r1, target_r2,
    risk_reward, max_loss_pct, plan_text, disclaimer.
    Returns empty dict if score < APLUS_THRESHOLD.
    """
    score = ticker.get("score", 0)
    if score < APLUS_THRESHOLD:
        return {}

    sym         = ticker.get("symbol", "")
    price       = ticker.get("price", 0) or 0
    gap_pct     = ticker.get("gap_percent", 0) or 0
    change_pct  = ticker.get("change_percent", 0) or 0
    rvol        = ticker.get("relative_volume", 0) or 0
    float_m     = ticker.get("float_m", 0) or 0
    atr_est     = round(price * 0.08, 2)   # rough 8% ATR proxy for low-floats
    grade       = ticker.get("grade", "A+")
    top_cat     = ticker.get("top_catalyst") or {}
    cat_title   = (top_cat.get("title") or "No catalyst identified")[:120]
    cat_age     = top_cat.get("hours_old", 0)
    short_float = ticker.get("short_float_pct", 0) or 0
    squeeze     = ticker.get("squeeze_tier", "none")

    prompt = f"""You are a professional day trader specialising in low-float momentum scalps.
Analyse this setup and return ONLY a JSON object — no explanation, no markdown fences.

TICKER: {sym}
Grade: {grade} | Score: {score}/55 | RVOL: {rvol:.1f}x
Price: ${price:.2f} | Gap: {gap_pct:+.1f}% | Change: {change_pct:+.1f}%
Float: {float_m:.1f}M shares | Est. ATR: ${atr_est:.2f}
Short float: {short_float:.1f}% | Squeeze tier: {squeeze}
Catalyst ({cat_age:.1f}h ago): {cat_title}

Rules for this JSON output:
- entry_zone: string like "$8.10 - $8.40" (tight range just above key support/PM high)
- stop_loss: string like "$7.85" (below PM low or key support, max 5-8% from entry mid)
- target_r1: string like "$9.20" (first resistance / +1R)
- target_r2: string like "$10.50" (extended target / +2R)
- risk_reward: number like 2.1 (reward divided by risk)
- max_loss_pct: number like 4.5 (% loss from entry mid to stop)
- plan_text: string, 3 sentences max — entry trigger, key level to watch, and one risk factor

Return exactly this JSON shape:
{{"entry_zone":"...","stop_loss":"...","target_r1":"...","target_r2":"...","risk_reward":0.0,"max_loss_pct":0.0,"plan_text":"..."}}"""

    raw = _sonnet(prompt, max_tokens=300)
    parsed = _parse_json_block(raw)

    if parsed:
        parsed["symbol"]     = sym
        parsed["score"]      = score
        parsed["grade"]      = grade
        parsed["disclaimer"] = DISCLAIMER
        return parsed

    # Fallback: compute simple mechanical levels if LLM parse fails
    entry_mid  = price
    stop       = round(entry_mid * 0.94, 2)   # 6% stop
    r1         = round(entry_mid * 1.10, 2)   # +10%
    r2         = round(entry_mid * 1.20, 2)   # +20%
    rr         = round((r1 - entry_mid) / (entry_mid - stop), 2) if (entry_mid - stop) > 0 else 0
    return {
        "symbol":      sym,
        "score":       score,
        "grade":       grade,
        "entry_zone":  f"${round(entry_mid * 0.99, 2)} - ${round(entry_mid * 1.01, 2)}",
        "stop_loss":   f"${stop}",
        "target_r1":   f"${r1}",
        "target_r2":   f"${r2}",
        "risk_reward": rr,
        "max_loss_pct": 6.0,
        "plan_text":   raw[:300] if len(raw) < 400 else "Plan generation failed — review manually.",
        "disclaimer":  DISCLAIMER,
    }


def generate_all_plans(scored_tickers: List[Dict[str, Any]]) -> Dict[str, Dict]:
    """Generate trade plans for all A+ tickers. Returns {symbol: plan_dict}."""
    plans: Dict[str, Dict] = {}
    aplus = [t for t in scored_tickers if t.get("score", 0) >= APLUS_THRESHOLD]
    for ticker in aplus:
        sym = ticker.get("symbol", "")
        if sym:
            plans[sym] = generate_trade_plan(ticker)
    return plans
