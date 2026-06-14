#!/usr/bin/env python3
"""portfolio_ask.py — contextual "ask the agents" about YOUR portfolio.

Takes a natural-language question (e.g. "what's the R:R of trimming 5% V to get SpaceX exposure?"), gathers
the REAL context — positions held, analyst ratings/targets (pro_analyst), look-through theme exposure — and
routes it to the LLM (free Grok lane, local fallback) as a portfolio CIO/advisor. Returns a specific answer
plus the structured context it used, so the UI can show the receipts.

Private/pre-IPO names (SpaceX/SPCX) won't be in holdings or analyst data → flagged so the model addresses
access vehicles (ARK Venture, etc.) instead of pretending it's a normal ticker.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STATE = ROOT / "data" / "portfolios" / "state"
RUNTIME = ROOT / "data" / "runtime"

# Only GENUINELY private (no public ticker) names. NOTE: SpaceX IPO'd 2026-06-12 (SPCX, public) — NOT here.
# Keep current vs live quote data; do not assume private from stale knowledge.
_PRIVATE = {"STRIPE": "Stripe", "OPENAI": "OpenAI", "ANTHROPIC": "Anthropic", "DATABRICKS": "Databricks"}
_PRIVATE_FACTS = {
    "OpenAI": "OpenAI is private — no public stock. Indirect exposure only via Microsoft (MSFT).",
    "Stripe": "Stripe is private — no public stock/ticker.",
    "Anthropic": "Anthropic is private — indirect exposure only via Amazon (AMZN)/Google (GOOGL) stakes.",
    "Databricks": "Databricks is private — no public stock/ticker.",
}


def _load(p, d):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return d


def _tickers(q: str) -> list[str]:
    # uppercase 1-5 letter tokens + known private names
    cand = set(re.findall(r"\b[A-Z]{1,5}\b", q))
    for k in _PRIVATE:
        if k in q.upper():
            cand.add(k)
    stop = {"R", "RR", "AI", "USD", "IRA", "ETF", "CIO", "BUY", "SELL", "P", "L"}
    return [c for c in cand if c not in stop]


def _position(sym, holdings, total):
    rows = [h for h in holdings if (h.get("symbol") or "").upper() == sym]
    if not rows:
        return None
    val = sum(float(r.get("market_value") or 0) for r in rows)
    return {"value": round(val), "pct": round(val / total * 100, 2) if total else 0,
            "accounts": sorted({r.get("account") for r in rows})}


def gather_context(question: str) -> dict:
    holdings = _load(STATE / "holdings.json", {}).get("holdings", [])
    total = sum(float(h.get("market_value") or 0) for h in holdings if not h.get("is_cash"))
    pills = {p["symbol"].upper(): p for p in _load(RUNTIME / "pro_analyst_pills_latest.json", {}).get("pills", [])}
    lt = _load(STATE / "lookthrough_themes.json", {})
    lt_top = {t["symbol"]: t for t in lt.get("top_underlying", [])}

    positions = []
    seen_private = set()
    for sym in _tickers(question):
        if sym in _PRIVATE:
            if _PRIVATE[sym] in seen_private:
                continue
            seen_private.add(_PRIVATE[sym])
            positions.append({"symbol": sym, "name": _PRIVATE[sym], "private": True,
                              "note": _PRIVATE_FACTS.get(_PRIVATE[sym],
                                      "Private company — no public ticker; access via private vehicles only.")})
            continue
        pos = _position(sym, holdings, total)
        pa = pills.get(sym)
        analyst = None
        if pa:
            cur = pa.get("current_price"); tgt = pa.get("target_mean_price")
            analyst = {"rating": pa.get("recommendation_key"), "n": pa.get("number_of_analyst_opinions"),
                       "current": cur, "target_mean": tgt, "target_low": pa.get("target_low_price"),
                       "target_high": pa.get("target_high_price"),
                       "upside_pct": round((tgt - cur) / cur * 100, 1) if (cur and tgt) else None}
        if pos or analyst:
            positions.append({"symbol": sym, "held": pos is not None, "position": pos,
                              "analyst": analyst, "lookthrough": lt_top.get(sym)})
    return {"portfolio_total": round(total), "positions": positions,
            "themes": {k: v.get("pct") for k, v in (lt.get("themes") or {}).items()}}


def ask(question: str, lane: str | None = None) -> dict:
    ctx = gather_context(question)
    try:
        import llm_lane
        use = lane or ("grok" if llm_lane.available("grok") else "local")
        private_facts = "\n".join(f"- {p['name']}: {p['note']}" for p in ctx["positions"] if p.get("private"))
        prompt = (
            "You are the portfolio CIO/risk advisor. Answer the operator's question about THEIR portfolio "
            "with specific numbers and a clear recommendation. Use the analyst targets to frame reward:risk "
            "(R:R = upside to mean target vs downside to low target).\n"
            "CRITICAL — DEFER TO LIVE DATA OVER YOUR TRAINING KNOWLEDGE: your knowledge may be stale and "
            "companies IPO. If a name appears in the context with a live price/quote/position, it IS publicly "
            "traded NOW — never claim it is private based on prior knowledge (e.g. SpaceX/SPCX went public "
            "2026-06-12 and trades on Nasdaq). Only treat a name as private if it is explicitly marked "
            "'private' in the context below; for those, give the real access vehicles and don't invent a "
            "ticker. If unsure of a fact, say so rather than inventing it. If they ask for an alert, state "
            "the exact alert condition.\n"
            + (f"PRIVATE-NAME FACTS (use verbatim, do not contradict):\n{private_facts}\n" if private_facts else "")
            + "Be concrete, 5-8 sentences.\n\n"
            f"QUESTION: {question}\n\nPORTFOLIO CONTEXT:\n{json.dumps(ctx, indent=2)}")
        out = llm_lane.generate(prompt, lane=use, timeout=90)
        answer = out if (out and not str(out).startswith("LLM error")) else "(LLM unavailable — try again)"
        model = "grok-3-mini" if use == "grok" else "local"
    except Exception as e:
        answer, model = f"(error: {str(e)[:80]})", "none"
    return {"question": question, "answer": str(answer).strip(), "model": model, "context": ctx}


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "What is the R:R of trimming 5% V to get SpaceX exposure? V is a strong buy."
    print(json.dumps(ask(q), indent=2))
