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

PROMPT_VERSION = "protection_advisor_v2_hermes"  # v2: Hermes intel block appended (Phase 6)

# ── CURATED PROMPT (operator: "prompts well curated for the best answers") ─────────────────────
# Structure: role → hard rules → labeled inputs → exact output contract. Identical for local and
# external lanes so recommendations are comparable in the monthly meta-review.
PROMPT_V1 = """You are a risk-management analyst. Your ONLY job: recommend protective stop placement
for an EXISTING long stock position. You never recommend buying, selling more, or new positions.

STRATEGY FAMILY: this is a {family_label} holding ({family_hold}). Size the protection to the family.

HARD RULES (these are BOUNDS, not suggestions — a number outside them is WRONG)
- stop_price MUST be BELOW current price (this is a long). NEVER at or above price.
- stop_price MUST sit AT or just BELOW the 20d swing low: between (swing_low − 1.0×ATR) and swing_low.
  Anchor to structure — do NOT place the stop above the swing low.
- Resulting stop distance MUST be between {stop_min_pct}% and {stop_max_pct}% below price (the
  {family_label} band). If swing_low is further than {stop_max_pct}% below, the position is extended —
  cap the stop at {stop_max_pct}% below price and say so in the rationale.
- stop_pct_below MUST EQUAL round((price − stop_price)/price × 100, 1). Compute it; do not guess.
- FIXED vs TRAILING (decided by family + position state — this is the rule, not a preference):
    {trail_rule}
    • When trailing: trail_type="PERCENT", trail_offset between {trail_min_pct} and {trail_max_pct}
      (percent). No $ offsets, no ATR-multiples — percent only, so it is unambiguous.
- Respect analyst context: if price is ABOVE the analyst mean target, bias the stop tighter (nearer
  the {stop_min_pct}% end); if below target with intact uptrend, the wider end is acceptable.
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
            bars = []
    if len(bars) < 15:
        # fund codes with no public series: asset-class proxy ETF bars (operator-approved 2026-06-12)
        try:
            from holding_proxies import HOLDING_PROXY_MAP
            px = HOLDING_PROXY_MAP.get(symbol.upper())
            if px:
                import yfinance as yf
                h = yf.Ticker(px[0]).history(period="1y")
                bars = [{"open": float(o), "high": float(hi), "low": float(lo), "close": float(c),
                         "_proxy": px[0]} for o, hi, lo, c in zip(h["Open"], h["High"], h["Low"], h["Close"])]
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


_LIFECYCLE_STAGES: dict | None = None


def _lifecycle_stage(symbol: str) -> str | None:
    """Holding's lifecycle stage from hermes_holdings_lifecycle state (fail-soft None)."""
    global _LIFECYCLE_STAGES
    if _LIFECYCLE_STAGES is None:
        try:
            import sys as _s
            from pathlib import Path as _P
            _lib = str(_P(__file__).resolve().parent / "lib")
            if _lib not in _s.path:
                _s.path.insert(0, _lib)
            from hermes_holdings_lifecycle.holdings_lifecycle import load_holdings_lifecycle_state
            st = load_holdings_lifecycle_state() or {}
            rows = st.get("holdings") or st.get("positions") or st.get("rows") or []
            if isinstance(rows, dict):
                rows = list(rows.values())
            _LIFECYCLE_STAGES = {
                str(r.get("symbol") or "").upper():
                    str(r.get("lifecycle_stage") or r.get("stage") or "").lower()
                for r in rows if isinstance(r, dict) and r.get("symbol")}
        except Exception:
            _LIFECYCLE_STAGES = {}
    return _LIFECYCLE_STAGES.get(str(symbol or "").upper()) or None


def _sanity_check(rec, t, bounds=None):
    """Validate the LLM advisory against the ACTUAL technicals (all current holdings are long) and the
    holding's FAMILY bounds. Returns {verdict, issues}: fail = internally wrong (stop at/above price) ·
    warn = questionable / out-of-family-band · ok = clean."""
    b = bounds or {}
    stop_max = float(b.get("stop_max_pct", 12.0))
    stop_min = float(b.get("stop_min_pct", 0.0))
    trail_max = float(b.get("trail_max_pct", 20.0))
    issues: list[str] = []
    fail = False
    try:
        price = float(t.get("price") or 0)
        swing_low = float(t.get("swing_low") or 0)
        atr = float(t.get("atr") or 0)
        stop = float(rec["stop_price"]) if rec.get("stop_price") is not None else None
    except Exception:
        return {"verdict": "warn", "issues": ["non-numeric stop/technicals"]}
    if not price or stop is None:
        return {"verdict": "warn", "issues": ["missing price or stop"]}
    if stop >= price:
        issues.append(f"stop ${stop:.2f} is AT/ABOVE price ${price:.2f} — would trigger immediately, not a protective stop")
        fail = True
    else:
        dist = (price - stop) / price * 100
        claimed = rec.get("stop_pct_below")
        if claimed is not None:
            try:
                if abs(float(claimed) - dist) > 1.0:
                    issues.append(f"claims {float(claimed):.1f}% below but stop is actually {dist:.1f}% below")
            except Exception:
                pass
        if dist < 0.5:
            issues.append(f"stop only {dist:.1f}% below — inside noise, will whipsaw")
        elif stop_min and dist < stop_min - 1.0:   # too TIGHT: below the family floor (whipsaws a core hold)
            issues.append(f"stop {dist:.1f}% below — TIGHTER than the {stop_min:.0f}% family floor (whipsaw risk; should be widened)")
        elif dist > stop_max + 1.0:   # 1% tolerance so a stop sitting AT the band edge isn't flagged
            issues.append(f"stop {dist:.1f}% below — beyond the {stop_max:.0f}% family band / weak protection")
        # anchor-to-structure: only demand the stop sit at/below the 20d swing low when that low is
        # REACHABLE (≤12% below price). For extended positions the stop is correctly capped above it.
        swing_reachable = bool(swing_low) and (price - swing_low) / price * 100 <= 12
        if swing_reachable and atr and stop > swing_low + 0.5 * atr:
            issues.append(f"stop ${stop:.2f} sits ABOVE the reachable 20d swing low ${swing_low:.2f} — not anchored to support")
    if rec.get("trail_recommended"):
        try:
            off = float(rec.get("trail_offset"))
            tp = off if rec.get("trail_type") == "PERCENT" else (off / price * 100 if price else None)
            if tp is not None and tp < 0.3:
                issues.append(f"trail {tp:.1f}% — too tight, trails out on noise")
            elif tp is not None and tp > trail_max + 1.0:
                issues.append(f"trail {tp:.1f}% — beyond the {trail_max:.0f}% family band")
        except Exception:
            issues.append("trail offset not numeric")
    return {"verdict": "fail" if fail else ("warn" if issues else "ok"), "issues": issues}


def _candidates(limit):
    """All real-account positions worth advising (operator 2026-06-12: full sweep — floor lowered
    500->100 so the small taxable names are covered; proxy-mapped 401k fund codes included; only
    CASH/dust/delisted-CUSIPs stay out)."""
    from holding_proxies import HOLDING_PROXY_MAP
    import holding_family as hf
    h = json.loads((PROJECT_ROOT / "data/portfolios/state/holdings.json").read_text())
    rows = []
    skipped_funds = []
    for x in h.get("holdings", []):
        sym = (x.get("symbol") or "").upper()
        acct = str(x.get("account", ""))
        if x.get("is_cash") or sym == "CASH":
            continue
        if not (acct.startswith("schwab") or acct.startswith("fidelity")):
            continue
        if not (re.fullmatch(r"[A-Z]{1,5}", sym) or sym in HOLDING_PROXY_MAP):
            continue
        if float(x.get("market_value") or 0) <= 100:
            continue
        # Funds with no exchange stop (open-end mutual funds AND 401k/separate-account proxy-mapped fund
        # codes) can't take a protective stop order — transact at NAV / inside the plan — so a stop
        # advisory is not actionable. Skip the sweep. (The Open Trades card frames them as "trim /
        # rebalance"; protection is a price-stop product for stocks/ETFs only.)
        if hf.is_unstoppable_fund(sym):
            skipped_funds.append(sym)
            continue
        rows.append(x)
    if skipped_funds:
        print(f"  [skip] {len(skipped_funds)} fund(s) excluded from protection sweep (no exchange stop "
              f"possible — mutual fund / 401k code): {', '.join(sorted(set(skipped_funds)))}")
    rows.sort(key=lambda x: -float(x.get("market_value") or 0))
    # one advisory per SYMBOL (largest position wins) — V/SCHD/SCHG live in several accounts
    seen, dedup = set(), []
    for x in rows:
        s = (x.get("symbol") or "").upper()
        if s in seen:
            continue
        seen.add(s); dedup.append(x)
    return dedup[:limit]


def protection_rec_for_symbol(symbol: str) -> dict | None:
    """UI-shaped protection advisory for one symbol (matches open-trades/intelligence)."""
    from db_adapter import _get_conn
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    cur = _get_conn().cursor()
    cur.execute("""SELECT symbol, thesis, summary, model_used, confidence_score,
                          evidence_json, created_at
                   FROM hermes_research_intelligence
                   WHERE research_type='protection_advisory' AND UPPER(symbol)=%s
                   ORDER BY created_at DESC LIMIT 1""", (sym,))
    row = cur.fetchone()
    if not row:
        return None
    cols = ["symbol", "thesis", "summary", "model_used", "confidence_score", "evidence_json", "created_at"]
    p = dict(zip(cols, row))
    ev = p.get("evidence_json") or {}
    if isinstance(ev, str):
        try:
            ev = json.loads(ev)
        except Exception:
            ev = {}
    rec = ev.get("recommendation") or {}
    px = (ev.get("inputs") or {}).get("price")
    stop = rec.get("stop_price")
    dist = (round((float(px) - float(stop)) / float(px) * 100, 2)
            if px and stop and float(px) > 0 else None)
    trail_rec = bool(rec.get("trail_recommended"))
    trail_off = rec.get("trail_offset")
    suggested_trail = None
    trail_matches_stop = False
    if trail_rec and trail_off is not None:
        suggested_trail = float(trail_off) if rec.get("trail_type") == "PERCENT" else None
    elif dist is not None and float(dist) >= 3:
        suggested_trail = round(float(dist), 1)
        trail_matches_stop = not trail_rec
    fb = ev.get("family_bounds") if isinstance(ev.get("family_bounds"), dict) else {}
    floor_pct = fb.get("stop_min_pct")
    fam = ev.get("family") or ""
    return {
        "rec": p.get("thesis"), "rationale": p.get("summary"), "model": p.get("model_used"),
        "confidence": p.get("confidence_score"), "at": str(p.get("created_at") or ""),
        "stop_price": stop, "trail_recommended": trail_rec,
        "trail_type": rec.get("trail_type"), "trail_offset": trail_off,
        "suggested_trail_pct": suggested_trail, "trail_matches_stop": trail_matches_stop,
        "price": px, "stop_distance_pct": dist,
        "sanity": ev.get("sanity"),
        "family": fam, "family_source": ev.get("family_source"),
        "family_bounds": fb,
        "family_floor_pct": floor_pct,
        "family_floor": (f"{fam} floor {floor_pct}%" if floor_pct is not None else fam) or None,
        "lane": ev.get("lane"),
    }


def run(lane="deepseek-flash", symbols=None, limit=12, manual_trigger=False, batch=False):
    # operator 2026-06-13: prefer the FREE Grok OAuth lane (tighter adherence to the bounded prompt
    # than gemma3:4b); auto-fall back to local gemma when the proxy isn't authenticated. Both free.
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
    done = failed = fellback = 0
    outcomes: list[dict] = []
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
        # classify the holding into a stop tier (stop_policy.yaml: buckets + asset class +
        # volatility + operator pins) → per-tier bounds, tightened by lifecycle stage
        import holding_family as hf
        atr_pct = t["atr"] / t["price"] * 100 if t["price"] else None
        family, fam_source = hf.classify_family(sym, atr_pct)
        _stage = _lifecycle_stage(sym)
        _is_stock = ((hf._cfg().get("asset_type_overrides") or {}).get(sym, "").lower() == "stock"
                     or fam_source.startswith("stock"))
        fb = hf.protection_bounds(family, lifecycle_stage=_stage,
                                  regime=hf.current_regime(),
                                  position_value_usd=qty * t["price"] if qty else None,
                                  is_stock=_is_stock)
        _trail_min = hf.trail_pnl_threshold(family)
        trail_rule = (f"• {fb['label']} is held through noise — trail_recommended = TRUE only on a LARGE "
                      f"gain (unrealized ≥ +{_trail_min:.0f}%) AND price > 50d SMA; otherwise FALSE (fixed stop)."
                      if not fb["trail_norm"] else
                      f"• trail_recommended = TRUE only if unrealized P&L ≥ +{_trail_min:.0f}% AND price > 50d SMA "
                      f"(real profit + uptrend); otherwise FALSE (fixed stop).")
        prompt = PROMPT_V1.format(
            symbol=sym, account=c.get("account"), qty=qty, basis_ps=basis_ps, price=t["price"],
            pnl_pct=pnl_pct, rsi=t["rsi"], atr=t["atr"], atr_pct=atr_pct,
            swing_low=t["swing_low"], sma50=t["sma50"],
            sma50_dist=(t["price"] - t["sma50"]) / t["sma50"] * 100,
            family_label=fb["label"], family_hold=fb["hold"], stop_min_pct=fb["stop_min_pct"],
            stop_max_pct=fb["stop_max_pct"], trail_min_pct=fb["trail_min_pct"],
            trail_max_pct=fb["trail_max_pct"], trail_rule=trail_rule, **_analyst(cur, sym))
        # Phase 6 (2026-07-02): stop advisory now CONSUMES Hermes intelligence. Kept short so the
        # curated prompt stays bounded, and explicitly subordinate to the HARD RULES above.
        try:
            from hermes_data_access import hermes_prompt_block
            _hb = hermes_prompt_block(sym)
            if _hb:
                prompt += ("\nHERMES INTEL (advisory color for the rationale ONLY — it never "
                           "overrides the HARD RULES or the family band):\n" + _hb[:700])
        except Exception:
            pass
        # 401k funds can't hold stop ORDERS — reframe as NAV alert/trim levels (proxy-based when noted)
        if str(c.get("account", "")).startswith("fidelity") or bars[0].get("_proxy"):
            proxy_note = f" Technicals are from the {bars[0].get('_proxy', 'fund NAV')} asset-class proxy." \
                if bars[0].get("_proxy") else ""
            prompt += ("\nNOTE: this is a retirement-plan FUND position — stop ORDERS are impossible. "
                       "Frame stop_price as a NAV ALERT level for a manual trim/rebalance decision, and "
                       "trail as a review trigger, not an order." + proxy_note)
        used_lane = lane
        try:
            pid = "holding_protection_advisor_batch" if batch else "holding_protection_advisor"
            out = llm_lane.generate(prompt, lane=lane, timeout=120,
                                    process_id=pid,
                                    task_summary=f"stop advisory {sym} {c.get('account')}",
                                    manual_trigger=bool(manual_trigger or batch))
        except Exception as e:
            if "manual approval required" in str(e).lower():
                print(f"  {sym}: Grok blocked (Manual mode) — enable Automated in Consumption or run manual")
                continue
            # Free-lane resilience: on a Grok/ChatGPT OAuth failure (e.g. 403 token-rotation blip) retry on
            # the LOCAL gemma lane — free, never a paid fallback (honours the no-paid-fallback policy).
            if lane != "local":
                try:
                    out = llm_lane.generate(prompt, lane="local", timeout=120)
                    used_lane = "local"; fellback += 1
                    print(f"  {sym}: {lane} lane failed ({str(e)[:40]}) -> local gemma fallback (free, no paid)")
                except Exception as e2:
                    print(f"  {sym}: lane error {lane}:{str(e)[:25]} / local:{str(e2)[:25]}"); failed += 1; continue
            else:
                print(f"  {sym}: lane error {str(e)[:60]}"); failed += 1; continue
        rec = _parse(out)
        if not rec:
            print(f"  {sym}: unparseable response"); failed += 1; continue
        # FAMILY-FLOOR enforcement (2026-06-29): the 20d-swing-low anchor can yield a stop TIGHTER than the
        # family minimum for low-volatility holdings (income ETFs near their range, e.g. SCHD/DIVI) — which
        # whipsaws a "held-through-noise" core position. Widen the recommended stop to the family floor and
        # record it in the rationale (mirrors the prompt's too-WIDE cap, applied to the too-TIGHT side).
        try:
            _px = float(t["price"]); _smin = float(fb.get("stop_min_pct") or 0)
            if _px > 0 and _smin and rec.get("stop_price") is not None:
                _dist = (_px - float(rec["stop_price"])) / _px * 100
                if _dist < _smin - 0.1:
                    rec["stop_price"] = round(_px * (1 - _smin / 100), 2)
                    rec["stop_pct_below"] = _smin
                    rec["_floored_from_pct"] = round(_dist, 1)
                    rec["rationale"] = (str(rec.get("rationale") or "")[:120]
                        + f" · widened to the {_smin:.0f}% {fb['label']} floor (20d swing low only "
                          f"{_dist:.1f}% below — too tight to hold through noise)").strip()
        except Exception:
            pass
        # Deterministic trail gate — don't rely on the LLM for the family profit threshold.
        try:
            if hf.trail_recommended_for_state(
                family=family, pnl_pct=pnl_pct, price=float(t["price"]), sma50=float(t["sma50"]),
            ):
                spb = float(rec.get("stop_pct_below") or 0)
                if not rec.get("trail_recommended"):
                    rec["trail_recommended"] = True
                    rec["trail_type"] = "PERCENT"
                    rec["trail_offset"] = round(
                        min(max(spb, float(fb.get("trail_min_pct", 6))), float(fb.get("trail_max_pct", 12))), 1)
                    rec["rationale"] = (str(rec.get("rationale") or "")[:120]
                                        + f" · trail at +{pnl_pct:.1f}% gain (≥{hf.trail_pnl_threshold(family):.0f}% "
                                          f"rule + above 50d SMA)").strip()
        except Exception:
            pass
        # Extended core at the family stop cap: offer a matching % trail (same width as fixed stop).
        try:
            spb = float(rec.get("stop_pct_below") or 0)
            if not rec.get("trail_recommended") and spb >= float(fb.get("trail_min_pct", 6)):
                if spb >= float(fb.get("stop_max_pct", 12)) - 1.0 or pnl_pct >= hf.TRAIL_PNL_PCT_RUNNER:
                    rec["trail_recommended"] = True
                    rec["trail_type"] = "PERCENT"
                    rec["trail_offset"] = round(min(spb, float(fb.get("trail_max_pct", 12))), 1)
                    rec["rationale"] = (str(rec.get("rationale") or "")[:120]
                                          + " · trail matches advised stop width for extended runner").strip()
        except Exception:
            pass
        sanity = _sanity_check(rec, t, fb)   # validate vs real structure + family bounds
        model = getattr(__import__("llm_lane"), "_DEEPSEEK_FLASH_MODEL", None) or getattr(__import__("local_llm"), "model_used", None) or "gemma3:12b"
        cur.execute("""INSERT INTO hermes_research_intelligence
                         (source, hermes_agent_name, research_type, symbol, topic, summary, thesis,
                          thesis_type, evidence_json, confidence_score, model_used, prompt_hash,
                          freshness_date)
                       VALUES ('hermes','protection_advisor','protection_advisory',%s,
                          'stop/trailing-stop recommendation', %s, %s, 'neutral', %s, %s, %s, %s,
                          CURRENT_DATE)""",
                    (sym, rec.get("rationale", "")[:400],
                     f"stop ${rec.get('stop_price')} ({rec.get('stop_pct_below')}% below)"
                     + ((f" · trail {rec.get('trail_offset')}%" if rec.get('trail_type') == 'PERCENT'
                         else f" · trail ${rec.get('trail_offset')}")   # $ BEFORE the value, never a suffix
                        if rec.get("trail_recommended") else " · no trail yet"),
                     json.dumps({"prompt_version": PROMPT_VERSION, "inputs": {**t, "basis_ps": basis_ps,
                                 "pnl_pct": pnl_pct}, "recommendation": rec, "lane": used_lane, "sanity": sanity,
                                 "family": family, "family_source": fam_source, "family_bounds": fb,
                                 "volatility_tier": (hf.volatility_tier(sym) or {}).get("tier"),
                                 "regime": hf.current_regime(),
                                 # explicit floor-clamp marker so the monthly Claude meta-review sanity-checks
                                 # widenings (rec._floored_from_pct = original too-tight %, now at the floor).
                                 "floored": ({"from_pct": rec.get("_floored_from_pct"),
                                              "to_floor_pct": fb.get("stop_min_pct")}
                                             if rec.get("_floored_from_pct") is not None else False)}),
                     rec.get("confidence"), model, PROMPT_VERSION))
        conn.commit()
        sflag = '' if sanity['verdict'] == 'ok' else f" · ⚠{sanity['verdict'].upper()}: {'; '.join(sanity['issues'])[:70]}"
        print(f"  {sym}: [{family}] stop ${rec.get('stop_price')} ({rec.get('stop_pct_below')}% below) · "
              f"trail={'%s%%' % rec.get('trail_offset') if rec.get('trail_recommended') else 'no'} "
              f"· conf {rec.get('confidence')} · {model}{sflag}")
        done += 1
        outcomes.append({"symbol": sym, "ok": True, "lane": used_lane, "model": model,
                         "stop_price": rec.get("stop_price"), "trail_recommended": rec.get("trail_recommended")})
    summary = {"lane": lane, "advised": done, "failed": failed, "fellback_to_local": fellback,
               "outcomes": outcomes,
               "note": "advisory only — surfaced on Portfolio cards + monthly Claude meta-review"}
    print(json.dumps(summary))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", default="grok", choices=["local", "grok"])   # free Grok OAuth by default
    ap.add_argument("--symbols", help="comma-separated override")
    ap.add_argument("--limit", type=int, default=50)   # full-portfolio default (operator 2026-06-12)
    ap.add_argument("--batch", action="store_true",
                    help="Manual-batch mode: uses holding_protection_advisor_batch process_id + manual_trigger (for cron/UI top-N)")
    a = ap.parse_args()
    run(lane=a.lane, symbols=a.symbols.split(",") if a.symbols else None, limit=a.limit,
        manual_trigger=bool(a.batch), batch=bool(a.batch))


if __name__ == "__main__":
    main()
