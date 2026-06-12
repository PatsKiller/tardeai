#!/usr/bin/env python3
"""holding_protection_advisor.py — LLM stop / trailing-stop advisory for REAL-account holdings.

Operator requirement (2026-06-12): "when LLMs analyze they should also advise from technicals and
analyst predictions on stop and/or trailing-stop amounts needed."

For each held real-account equity (default: top-N by value + anything large-gain-unprotected) the
advisor builds a CURATED, versioned prompt from:
  • position state    — qty, basis (single-source-of-truth), unrealized P&L%
  • technicals        — RSI(14), ATR(14), 20d swing low, 50d SMA distance (daily bars, read-only)
  • analyst layer     — Yahoo consensus (target mean/low/high, recommendation, analyst count)
and asks for a STRICT-JSON protection recommendation: initial stop, trailing type/offset, rationale.

ADVISORY ONLY — output lands in hermes_research_intelligence (research_type='protection_advisory'),
which feeds the Portfolio card 🤖/🛡 badges and the monthly Claude meta-review. It never places,
modifies, or proposes an order. Lanes: local gemma (default) or grok (--lane grok). READ-ONLY APIs.

  python3 scripts/holding_protection_advisor.py [--lane local|grok] [--symbols V,SCHG] [--limit 12]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

PROMPT_VERSION = "protection_advisor_v1"

# ── CURATED PROMPT (operator: "prompts well curated for the best answers") ─────────────────────
# Structure: role → hard rules → labeled inputs → exact output contract. Identical for local and
# external lanes so recommendations are comparable in the monthly meta-review.
PROMPT_V1 = """You are a risk-management analyst. Your ONLY job: recommend protective stop placement
for an EXISTING long stock position. You never recommend buying, selling more, or new positions.

HARD RULES
- Use the swing low and ATR to place stops OUTSIDE normal noise (typically 1.5-2.5x ATR or just
  below the recent swing low, whichever is more sensible for this volatility).
- A trailing stop is preferred when the position is in profit and trending; a fixed stop when basis
  protection matters more. You may recommend both (initial stop now, trail once price advances).
- Respect the analyst context: if price is far above the analyst mean target, protection should be
  tighter; far below, allow more room only if technicals support it.
- Output STRICT JSON only. No prose outside the JSON. Numbers as numbers, not strings.

POSITION
symbol: {symbol} · account: {account}
shares: {qty} · avg cost: ${basis_ps:.2f} · current: ${price:.2f} · unrealized: {pnl_pct:+.1f}%

TECHNICALS (daily)
RSI14: {rsi} · ATR14: ${atr:.2f} ({atr_pct:.1f}% of price) · 20d swing low: ${swing_low:.2f}
50d SMA: ${sma50:.2f} ({sma50_dist:+.1f}% from price)

ANALYST CONSENSUS (Yahoo)
mean target: {tgt_mean} · range: {tgt_low}-{tgt_high} · rating: {rec_key} · analysts: {n_analysts}

OUTPUT (strict JSON):
{{"stop_price": <number>, "stop_pct_below": <number>, "trail_recommended": <true|false>,
  "trail_type": "PERCENT"|"VALUE", "trail_offset": <number>, "rationale": "<max 40 words>",
  "confidence": <0.0-1.0>}}"""


def _bars(symbol, days=70):
    import schwab_transport as st
    import datetime as dt
    end = dt.date.today()
    start = end - dt.timedelta(days=days * 2)
    r = st.get_price_history(symbol, start.isoformat(), end.isoformat(), timeframe="1Day")
    bars = r if isinstance(r, list) else []
    if not bars:
        # mutual funds / cred-less contexts: yfinance NAV/close fallback (same fields, read-only)
        try:
            import yfinance as yf
            h = yf.Ticker(symbol).history(period="1y")
            bars = [{"open": float(o), "high": float(hi), "low": float(lo), "close": float(c)}
                    for o, hi, lo, c in zip(h["Open"], h["High"], h["Low"], h["Close"])]
        except Exception:
            return None
    return bars[-days:] if bars else None


def _technicals(bars):
    closes = [float(b.get("close") or b.get("c") or 0) for b in bars]
    highs = [float(b.get("high") or b.get("h") or 0) for b in bars]
    lows = [float(b.get("low") or b.get("l") or 0) for b in bars]
    # RSI14
    gains = losses = 0.0
    for i in range(-14, 0):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0); losses += max(-d, 0)
    rsi = round(100 - 100 / (1 + (gains / losses)), 1) if losses else 100.0
    # ATR14 (simple TR mean)
    trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
           for i in range(-14, 0)]
    atr = sum(trs) / len(trs)
    swing_low = min(lows[-20:])
    sma50 = sum(closes[-50:]) / min(50, len(closes))
    return {"rsi": rsi, "atr": atr, "swing_low": swing_low, "sma50": sma50, "price": closes[-1]}


def _analyst(cur, symbol):
    cur.execute("""SELECT target_mean_price, target_low_price, target_high_price, recommendation_key,
                          number_of_analyst_opinions FROM yahoo_analyst_targets_history
                   WHERE symbol=%s ORDER BY created_at DESC LIMIT 1""", (symbol,))
    r = cur.fetchone()
    if not r:
        return {"tgt_mean": "n/a", "tgt_low": "n/a", "tgt_high": "n/a", "rec_key": "n/a", "n_analysts": 0}
    return {"tgt_mean": f"${float(r[0]):.2f}" if r[0] else "n/a",
            "tgt_low": f"${float(r[1]):.2f}" if r[1] else "n/a",
            "tgt_high": f"${float(r[2]):.2f}" if r[2] else "n/a",
            "rec_key": r[3] or "n/a", "n_analysts": int(r[4] or 0)}


def _parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        p = json.loads(m.group(0))
        return p if "stop_price" in p else None
    except Exception:
        return None


def _candidates(limit):
    h = json.loads((PROJECT_ROOT / "data/portfolios/state/holdings.json").read_text())
    rows = [x for x in h.get("holdings", [])
            if str(x.get("account", "")).startswith("schwab") and not x.get("is_cash")
            and (x.get("symbol") or "").upper() != "CASH"
            and re.fullmatch(r"[A-Z]{1,5}", (x.get("symbol") or "").upper())   # equities/ETFs, skip CUSIPs
            and float(x.get("market_value") or 0) > 500]
    rows.sort(key=lambda x: -float(x.get("market_value") or 0))
    return rows[:limit]


def run(lane="local", symbols=None, limit=12):
    import llm_lane
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    if not llm_lane.available(lane):
        lane = "local"
    cands = _candidates(limit)
    if symbols:
        want = {s.strip().upper() for s in symbols}
        cands = [c for c in cands if (c.get("symbol") or "").upper() in want] or \
                [{"symbol": s, "account": "schwab", "shares": 0, "cost_basis": 0, "market_value": 0} for s in want]
    done = failed = 0
    for c in cands:
        sym = (c.get("symbol") or "").upper()
        bars = _bars(sym)
        if not bars or len(bars) < 50:
            print(f"  {sym}: no daily bars (skipped)"); failed += 1; continue
        t = _technicals(bars)
        qty = float(c.get("shares") or 0)
        basis = float(c.get("cost_basis") or 0)
        basis_ps = basis / qty if qty and basis else t["price"]
        pnl_pct = (t["price"] - basis_ps) / basis_ps * 100 if basis_ps else 0.0
        prompt = PROMPT_V1.format(
            symbol=sym, account=c.get("account"), qty=qty, basis_ps=basis_ps, price=t["price"],
            pnl_pct=pnl_pct, rsi=t["rsi"], atr=t["atr"], atr_pct=t["atr"] / t["price"] * 100,
            swing_low=t["swing_low"], sma50=t["sma50"],
            sma50_dist=(t["price"] - t["sma50"]) / t["sma50"] * 100, **_analyst(cur, sym))
        try:
            out = llm_lane.generate(prompt, lane=lane, timeout=120)
        except Exception as e:
            print(f"  {sym}: lane error {str(e)[:60]}"); failed += 1; continue
        rec = _parse(out)
        if not rec:
            print(f"  {sym}: unparseable response"); failed += 1; continue
        model = "grok-3-mini" if lane == "grok" else getattr(__import__("local_llm"), "model_used", None) or "gemma3:12b"
        cur.execute("""INSERT INTO hermes_research_intelligence
                         (source, hermes_agent_name, research_type, symbol, topic, summary, thesis,
                          thesis_type, evidence_json, confidence_score, model_used, prompt_hash,
                          freshness_date)
                       VALUES ('hermes','protection_advisor','protection_advisory',%s,
                          'stop/trailing-stop recommendation', %s, %s, 'neutral', %s, %s, %s, %s,
                          CURRENT_DATE)""",
                    (sym, rec.get("rationale", "")[:400],
                     f"stop ${rec.get('stop_price')} ({rec.get('stop_pct_below')}% below)"
                     + (f" · trail {rec.get('trail_offset')}{'%' if rec.get('trail_type') == 'PERCENT' else '$'}"
                        if rec.get("trail_recommended") else " · no trail yet"),
                     json.dumps({"prompt_version": PROMPT_VERSION, "inputs": {**t, "basis_ps": basis_ps,
                                 "pnl_pct": pnl_pct}, "recommendation": rec, "lane": lane}),
                     rec.get("confidence"), model, PROMPT_VERSION))
        conn.commit()
        print(f"  {sym}: stop ${rec.get('stop_price')} ({rec.get('stop_pct_below')}% below) · "
              f"trail={'%s %s' % (rec.get('trail_offset'), rec.get('trail_type')) if rec.get('trail_recommended') else 'no'} "
              f"· conf {rec.get('confidence')} · {model}")
        done += 1
    print(json.dumps({"lane": lane, "advised": done, "failed": failed,
                      "note": "advisory only — surfaced on Portfolio cards + monthly Claude meta-review"}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", default="local", choices=["local", "grok"])
    ap.add_argument("--symbols", help="comma-separated override")
    ap.add_argument("--limit", type=int, default=12)
    a = ap.parse_args()
    run(lane=a.lane, symbols=a.symbols.split(",") if a.symbols else None, limit=a.limit)


if __name__ == "__main__":
    main()
