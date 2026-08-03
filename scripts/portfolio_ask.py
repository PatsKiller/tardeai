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


_STOP = {"R", "RR", "AI", "USD", "IRA", "ETF", "CIO", "BUY", "SELL", "P", "L", "RR"}


def _tickers(q: str, known: set | None = None) -> list[str]:
    """Extract ticker symbols. Case-INSENSITIVE: the operator types lowercase ('xlb', 'spcx').
    A lowercase token only counts as a ticker if it matches a symbol the operator actually holds /
    has analyst data for (the `known` set) — that filters out common words like 'trim'/'some'/'look'.
    An explicitly UPPERCASE-typed token (≥2 chars) is kept even if not held, so the operator can ask
    about a new name by capitalizing it."""
    known = known or set()
    tokens = set(t.upper() for t in re.findall(r"\b[A-Za-z]{1,5}\b", q))
    upper_typed = set(re.findall(r"\b[A-Z]{2,5}\b", q))   # symbols the operator capitalized themselves
    for k in _PRIVATE:
        if k in q.upper():
            tokens.add(k)
    out = []
    for c in tokens:
        if c in _STOP:
            continue
        if c in known or c in _PRIVATE or c in upper_typed:
            out.append(c)
    return out


def _position(sym, holdings, total):
    rows = [h for h in holdings if (h.get("symbol") or "").upper() == sym]
    if not rows:
        return None
    val = sum(float(r.get("market_value") or 0) for r in rows)
    sh = sum(float(r.get("shares") or 0) for r in rows)
    cb = sum(float(r.get("cost_basis") or 0) for r in rows)
    px = next((float(r["price"]) for r in rows if r.get("price")), None)
    by_acct = [{"account": r.get("account"), "shares": round(float(r.get("shares") or 0), 4),
                "value": round(float(r.get("market_value") or 0)),
                "price": (round(float(r["price"]), 2) if r.get("price") else None)} for r in rows]
    return {"value": round(val), "shares": round(sh, 4), "price": (round(px, 2) if px else None),
            "cost_basis": round(cb), "unrealized_pnl": round(val - cb),
            "pct": round(val / total * 100, 2) if total else 0,
            "accounts": sorted({r.get("account") for r in rows}), "by_account": by_acct}


def gather_context(question: str) -> dict:
    holdings = _load(STATE / "holdings.json", {}).get("holdings", [])
    total = sum(float(h.get("market_value") or 0) for h in holdings if not h.get("is_cash"))
    pills = {p["symbol"].upper(): p for p in _load(RUNTIME / "pro_analyst_pills_latest.json", {}).get("pills", [])}
    lt = _load(STATE / "lookthrough_themes.json", {})
    lt_top = {t["symbol"]: t for t in lt.get("top_underlying", [])}

    # symbols the operator actually has data for — lets lowercase tokens ('xlb') resolve to real tickers
    known = {(h.get("symbol") or "").upper() for h in holdings if h.get("symbol")}
    known |= set(pills.keys())
    known |= {str(s).upper() for s in lt_top.keys()}

    positions = []
    seen_private = set()
    for sym in _tickers(question, known):
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
            # prefer the live holdings price over the analyst snapshot's (stale) current_price for upside
            cur = (pos or {}).get("price") or pa.get("current_price"); tgt = pa.get("target_mean_price")
            analyst = {"rating": pa.get("recommendation_key"), "n": pa.get("number_of_analyst_opinions"),
                       "current": cur, "target_mean": tgt, "target_low": pa.get("target_low_price"),
                       "target_high": pa.get("target_high_price"),
                       "upside_pct": round((tgt - cur) / cur * 100, 1) if (cur and tgt) else None}
        lockup = None
        try:
            import ipo_lockups
            lockup = ipo_lockups.lockup_info(sym)
        except Exception:
            pass
        if pos or analyst or lockup:
            positions.append({"symbol": sym, "held": pos is not None, "position": pos,
                              "analyst": analyst, "lookthrough": lt_top.get(sym), "ipo_lockup": lockup})
    return {"portfolio_total": round(total), "positions": positions,
            "themes": {k: v.get("pct") for k, v in (lt.get("themes") or {}).items()}}


def ask(question: str, lane: str | None = None, manual_trigger: bool = False) -> dict:
    ctx = gather_context(question)
    try:
        import llm_lane
        use = (lane or "").strip().lower() or None
        if use not in ("deepseek-flash", "grok", "chatgpt", "local"):
            use = "deepseek-flash" if llm_lane.available("deepseek-flash") else ("grok" if llm_lane.available("grok") else "local")
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
            "the exact alert condition. If asked about INSIDER SELLING / lockup / supply unlock, use the "
            "'ipo_lockup' tranches in the context (dates + days_until) and flag which are confirmed vs "
            "estimates (confirm against the S-1).\n"
            + (f"PRIVATE-NAME FACTS (use verbatim, do not contradict):\n{private_facts}\n" if private_facts else "")
            + "Be concrete, 5-8 sentences.\n\n"
            f"QUESTION: {question}\n\nPORTFOLIO CONTEXT:\n{json.dumps(ctx, indent=2)}")
        gen_kw = dict(lane=use, timeout=90)
        if use in ("deepseek-flash", "grok", "chatgpt"):
            gen_kw.update(process_id="portfolio_ask", task_summary=question[:120],
                          manual_trigger=bool(manual_trigger or lane))
        out = llm_lane.generate(prompt, **gen_kw)
        answer = out if (out and not str(out).startswith("LLM error")) else "(LLM unavailable — try again)"
        model = {"grok": "grok-oauth", "chatgpt": "chatgpt-oauth"}.get(use, "local")
    except Exception as e:
        err = str(e)
        if "ManualRequired" in type(e).__name__ or "manual_mode" in err:
            return {"question": question, "ok": False, "manual_required": True,
                    "error": "portfolio_ask is Manual — pick ▶ Grok or ▶ ChatGPT", "context": ctx}
        answer, model = f"(error: {err[:80]})", "none"
    return {"question": question, "answer": str(answer).strip(), "model": model, "lane": use, "context": ctx}


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "What is the R:R of trimming 5% V to get SpaceX exposure? V is a strong buy."
    print(json.dumps(ask(q), indent=2))
