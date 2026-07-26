#!/usr/bin/env python3
"""catalyst_classifier.py — world-class hybrid catalyst classifier (Phase: catalyst quality).

ADVISORY-ONLY. classify(title, summary, symbol) -> structured dict:
    {catalyst_type, direction, impact_score, confidence, severity, method, rationale}

Design (operator-approved): HYBRID + outcome-calibrated.
  1. Deterministic layer (fast, offline): Hermes "<category>:" prefix → typed category; expanded regex
     taxonomy → directional catalyst_type; bull/bear cue refinement; confidence from match strength.
  2. Local-LLM residual (gemma3:4b, free): ONLY when deterministic confidence < threshold — structured JSON,
     health-gated + timeout, falls back to deterministic. Never blocks the pipeline.
  3. Outcome calibration: per-type weight multiplier learned from realized forward returns
     (data/runtime/catalyst_calibration.json, produced by catalyst_calibration.py) scales impact_score.

No schema change (direction/confidence/method are returned for storage in raw_payload). Feeds fusion
catalyst_score → advisory; never changes GO/WAIT or strategy scoring.
"""
import os, re, json, sys, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from llm_net import urlopen_retry
except Exception:
    def urlopen_retry(req, timeout=120, **_):  # fallback: no retry if helper missing
        return urllib.request.urlopen(req, timeout=timeout).read()

ROOT = Path(__file__).resolve().parent.parent
CALIB = ROOT / "data" / "runtime" / "catalyst_calibration.json"
MATURITY = ROOT / "data" / "runtime" / "source_maturity_latest.json"
OLLAMA = "http://127.0.0.1:11434/api/chat"

# source maturity tier → confidence multiplier (Gate 3): a catalyst from a trusted/core source is more
# reliable than one from an unvetted candidate / noisy demoted source. Bounded; confidence re-clamped [0,1].
_TIER_CONF = {"core": 1.15, "trusted": 1.10, "probationary": 1.0, "candidate": 0.95, "demoted": 0.80}
_MATURITY_CACHE = None


def _source_tier(source):
    if not source:
        return None
    try:
        from hermes_source_policy import get_source_tier
        return get_source_tier(source, for_promotion=True)
    except Exception:
        global _MATURITY_CACHE
        if _MATURITY_CACHE is None:
            try:
                _MATURITY_CACHE = {s["source"]: s["tier"] for s in json.loads(MATURITY.read_text()).get("sources", [])}
            except Exception:
                _MATURITY_CACHE = {}
        return _MATURITY_CACHE.get(source)

# --- directional catalyst taxonomy: catalyst_type -> (base_weight 0..1, direction, [regex]) ---
TYPE_PATTERNS = [
    ("earnings_beat",      0.85, "bullish", [r"\bbeat(s|ing)?\b.*\b(estimate|expectation|consensus|forecast)", r"\b(tops|exceed(s|ed)?)\b.*\bestimate", r"blowout quarter", r"record (revenue|earnings|profit)", r"earnings beat"]),
    ("earnings_miss",      0.72, "bearish", [r"\bmiss(es|ed)?\b.*\b(estimate|expectation|consensus)", r"\bfalls? short\b", r"below expectations", r"earnings miss", r"disappoint(s|ing|ed)?"]),
    ("guidance_raise",     0.90, "bullish", [r"rais(es|ed) (guidance|outlook|forecast|full-year)", r"ups? (forecast|guidance)", r"boost(s|ed)? (guidance|outlook)", r"increase(s|d)? forecast"]),
    ("guidance_lower",     0.66, "bearish", [r"low(ers|ered) (guidance|outlook|forecast)", r"cut(s|ting)? (outlook|forecast)", r"warns? on", r"disappointing outlook"]),
    ("fda_approval",       0.95, "bullish", [r"\bfda\b.*\b(approv|clear|grant)", r"regulatory approval", r"drug approved", r"clearance granted", r"\bbreakthrough\b.*designation"]),
    ("contract_win",       0.80, "bullish", [r"win(s|ning)? (a )?(contract|deal|award)", r"awarded (a )?contract", r"new partnership", r"strategic alliance", r"(billion|million)-dollar (contract|deal)", r"secures? (order|contract)"]),
    ("merger_acquisition", 0.78, "bullish", [r"acqui(re|res|red|sition)", r"\bmerger\b", r"takeover", r"buyout", r"to acquire", r"deal to buy", r"merge with"]),
    ("analyst_upgrade",    0.58, "bullish", [r"\bupgrad(e|es|ed)\b", r"price target (rais|increas|hik)", r"initiat(es|ed) (with )?(buy|outperform|overweight)", r"\boutperform\b rating"]),
    ("analyst_downgrade",  0.55, "bearish", [r"\bdowngrad(e|es|ed)\b", r"price target (cut|lower|reduc)", r"\bunderperform\b", r"\bsell\b rating"]),
    ("insider_buy",        0.60, "bullish", [r"insider (buy|purchas)", r"(ceo|cfo|director|officer) (buys|purchas)", r"insider buying"]),
    ("dividend_increase",  0.85, "bullish", [r"(rais|increas|hik|boost)(es|ed)? (the )?dividend", r"dividend (increase|hike|boost)", r"special dividend"]),
    ("dividend_cut",       0.88, "bearish", [r"(cut|suspend|eliminat|slash)(s|es|ed)? (the )?dividend", r"dividend (cut|suspension|reduction)"]),
    ("buyback",            0.55, "bullish", [r"buyback", r"share repurchase", r"repurchase program", r"buy back shares"]),
    ("short_squeeze",      0.50, "bullish", [r"short squeeze", r"high short interest", r"heavily shorted", r"days to cover"]),
    ("ceo_change",         0.45, "neutral", [r"new ceo", r"ceo (resign|steps down|departs)", r"executive shakeup", r"names? new chief"]),
    ("merger_terminated",  0.60, "bearish", [r"(deal|merger|acquisition) (terminat|call(ed)? off|collaps|fell through)"]),
    ("offering_dilution",  0.62, "bearish", [r"(public|secondary|stock|share) offering", r"dilut(es|ion|ive)", r"prices? .* offering", r"at-the-market offering"]),
    ("geopolitical",       0.42, "neutral", [r"tariff", r"sanction", r"trade war", r"embargo", r"export (ban|control)"]),
]

# Hermes "<category>:" bare prefixes → typed, NON-directional category + moderate weight.
HERMES_PREFIX_WEIGHTS = {
    "regulatory": 0.75, "fda": 0.85, "merger": 0.75, "contract": 0.70, "partnership": 0.65,
    "guidance": 0.65, "earnings": 0.60, "dividend": 0.55, "insider": 0.55, "buyback": 0.50,
    "analyst": 0.52, "product": 0.50, "news_momentum": 0.40, "sentiment": 0.35, "other": 0.30,
}
_BULL = re.compile(r"\b(surge|soar|jump|rally|gain|rise|spike|upgrade|beat|record|approval|wins?|raises?|boost|outperform|strong|bullish|growth)\b")
_BEAR = re.compile(r"\b(plunge|drop|fall|slump|crash|sink|downgrade|miss|cut|halt|recall|lawsuit|probe|investigation|bearish|warn|weak|decline|dilut)\b")


def _severity(impact):
    return "critical" if impact >= 8 else "high" if impact >= 6 else "medium" if impact >= 4 else "low"


def _calibration_mult(ctype):
    try:
        c = json.loads(CALIB.read_text()).get("by_type", {}).get(ctype)
        return float(c["weight_multiplier"]) if c and c.get("samples", 0) >= 10 else 1.0
    except Exception:
        return 1.0


def _refine_direction(text, base_dir):
    if base_dir != "neutral":
        return base_dir
    b, r = len(_BULL.findall(text)), len(_BEAR.findall(text))
    return "bullish" if b > r else "bearish" if r > b else "neutral"


def _deterministic(title, summary):
    text = f"{title or ''} {summary or ''}".lower()
    # 1) Hermes bare-category prefix
    if title and ":" in title:
        pfx = title.split(":", 1)[0].strip().lower().replace(" ", "_")
        if pfx in HERMES_PREFIX_WEIGHTS:
            w = HERMES_PREFIX_WEIGHTS[pfx]
            return {"catalyst_type": pfx, "direction": _refine_direction(text, "neutral"),
                    "base_weight": w, "confidence": 0.6 if pfx != "other" else 0.25, "method": "prefix"}
    # 2) directional regex taxonomy
    for ctype, w, direction, pats in TYPE_PATTERNS:
        for p in pats:
            if re.search(p, text):
                return {"catalyst_type": ctype, "direction": _refine_direction(text, direction),
                        "base_weight": w, "confidence": 0.8, "method": "regex"}
    # 3) fallback
    return {"catalyst_type": "other", "direction": _refine_direction(text, "neutral"),
            "base_weight": 0.30, "confidence": 0.2, "method": "fallback"}


_LLM_PROMPT = """Classify this stock-market catalyst headline. Be precise and conservative.
Headline: {title}
Summary: {summary}
Return ONLY JSON: {{"catalyst_type":"<one of: earnings_beat,earnings_miss,guidance_raise,guidance_lower,
fda_approval,contract_win,merger_acquisition,analyst_upgrade,analyst_downgrade,insider_buy,dividend_increase,
dividend_cut,buyback,short_squeeze,ceo_change,offering_dilution,geopolitical,news_momentum,other>",
"direction":"bullish|bearish|neutral","confidence":0.0-1.0,"rationale":"<=12 words"}}"""

# base weights for LLM-returned types (so impact stays calibrated)
_LLM_WEIGHTS = {t: w for (t, w, _d, _p) in TYPE_PATTERNS}
_LLM_WEIGHTS.update({"news_momentum": 0.40, "other": 0.30})


def _llm(title, summary, model="gemma3:4b", timeout=25):
    try:
        body = json.dumps({"model": model, "stream": False, "format": "json",
                           "messages": [{"role": "user", "content": _LLM_PROMPT.format(title=title, summary=(summary or "")[:400])}],
                           "options": {"num_ctx": 4096 if ("12b" in model or "27b" in model) else 8192,
                                       "num_predict": 160, "temperature": 0.1}}).encode()
        req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
        content = json.loads(urlopen_retry(req, timeout=timeout, attempts=2, base=0.5)).get("message", {}).get("content", "")
        d = json.loads(content[content.find("{"):content.rfind("}") + 1])
        ct = str(d.get("catalyst_type", "other")).strip().lower()
        return {"catalyst_type": ct, "direction": str(d.get("direction", "neutral")).lower(),
                "base_weight": _LLM_WEIGHTS.get(ct, 0.40),
                "confidence": max(0.0, min(1.0, float(d.get("confidence", 0.6)))),
                "method": "llm", "rationale": str(d.get("rationale", ""))[:120]}
    except Exception:
        return None


def classify(title, summary="", symbol=None, source=None, allow_llm=True, llm_threshold=0.55, model="gemma3:4b"):
    """Hybrid classify. Returns dict with catalyst_type, direction, impact_score (0-10, calibrated),
    confidence (source-maturity-adjusted), severity, method, rationale, source_tier."""
    r = _deterministic(title, summary)
    if allow_llm and r["confidence"] < llm_threshold and r["method"] != "regex":
        llm = _llm(title, summary, model=model)
        if llm and llm["confidence"] >= r["confidence"]:
            r = llm
    mult = _calibration_mult(r["catalyst_type"])
    impact = max(0.0, min(10.0, round(r["base_weight"] * 10 * mult, 1)))
    # Gate 3: adjust confidence by the surfacing source's maturity tier.
    tier = _source_tier(source)
    conf = r["confidence"] * _TIER_CONF.get(tier, 1.0)
    conf = round(max(0.0, min(1.0, conf)), 2)
    return {"catalyst_type": r["catalyst_type"], "direction": r.get("direction", "neutral"),
            "impact_score": impact, "confidence": conf, "severity": _severity(impact), "method": r["method"],
            "calibration_mult": round(mult, 3), "source_tier": tier, "rationale": r.get("rationale", "")}


if __name__ == "__main__":
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "earnings: NRIX"
    s = sys.argv[2] if len(sys.argv) > 2 else ""
    print(json.dumps(classify(t, s, allow_llm="--no-llm" not in sys.argv), indent=2))
