#!/usr/bin/env python3
"""deterministic_thesis.py — V5 LOCAL_QUANT long-term thesis engine (Section 5A).

Pure function of RAW, whitelisted evidence (the shadow facts dict — growth,
profitability, balance-sheet, valuation, dilution/short, trend, event risk,
data coverage). NO network, NO DB, NO model call, NO pre-chewed opinions:
analyst recommendations, CIO verdicts, and model verdicts are structurally
absent from the whitelist (shadow_decision_service.FUNDAMENTAL_KEYS) and this
module never reads them.

Instrument-aware: operating company · pre-profit company · ETF/fund · recent
listing. Output shows per-factor contributions and what evidence was MISSING —
confidence means evidence coverage and rule stability, never predicted success.

States: CONSTRUCTIVE · SPECULATIVE_CONSTRUCTIVE · NEUTRAL ·
        FUNDAMENTALLY_UNATTRACTIVE · INSUFFICIENT_EVIDENCE

Deterministic: identical facts → identical output (dict-order independent).
"""
from __future__ import annotations

ENGINE_VERSION = "1.0.0"

STATES = ("CONSTRUCTIVE", "SPECULATIVE_CONSTRUCTIVE", "NEUTRAL",
          "FUNDAMENTALLY_UNATTRACTIVE", "INSUFFICIENT_EVIDENCE")

# Factor weights; the weighted score maps to states via fixed bands below.
_W = {"growth": 1.0, "profitability": 1.0, "balance_sheet": 0.8, "valuation": 0.8,
      "dilution_short": 0.6, "trend": 0.6, "event_risk": 0.4}


def _num(v):
    try:
        f = float(v)
        return f if f == f else None  # NaN guard
    except (TypeError, ValueError):
        return None


def _factor(name, signal, contribution, evidence):
    return {"factor": name, "signal": signal, "weight": _W.get(name, 0.5),
            "contribution": round(contribution, 2), "evidence": evidence}


def classify_instrument(facts: dict, instrument_type: str | None = None) -> str:
    it = str(instrument_type or facts.get("instrument_type") or "").upper()
    if it in ("ETF", "FUND", "MUTUAL_FUND", "CEF") or facts.get("quote_type") in ("ETF", "MUTUALFUND"):
        return "etf_fund"
    f = facts.get("fundamentals") or {}
    eps = _num(f.get("eps_ttm"))
    pm = _num(f.get("profit_margin_pct"))
    bars = _num(facts.get("bars_used")) or 0
    if bars and bars < 60:
        return "recent_listing"
    # pre-profit only on the AUTHORITATIVE signal (negative net margin). A lone
    # negative eps_ttm with no margin corroboration is treated as unverified —
    # the enrichment cache has known misparses (QCOM eps_ttm=-10.46 while
    # strongly profitable), and a wrong pre-profit class distorts valuation.
    if pm is not None and pm < 0:
        return "pre_profit"
    if eps is not None and eps <= 0 and pm is None:
        return "operating_company"  # unverified conflict — noted in missing_evidence
    if not f:
        return "unknown"
    return "operating_company"


def evaluate(facts: dict, instrument_type: str | None = None) -> dict:
    """facts = shadow_decision_service.gather_facts output (raw evidence only)."""
    f = (facts or {}).get("fundamentals") or {}
    inst = classify_instrument(facts or {}, instrument_type)
    factors: list[dict] = []
    missing: list[str] = []
    score = 0.0
    _eps = _num(f.get("eps_ttm"))
    if _eps is not None and _eps <= 0 and _num(f.get("profit_margin_pct")) is None:
        missing.append("profitability conflict — eps_ttm negative but margin unverified (possible cache misparse)")

    def add(fac):
        nonlocal score
        factors.append(fac)
        score += fac["contribution"] * fac["weight"]

    # ── growth ────────────────────────────────────────────────────────────────
    # Magnitude sanity: the enrichment cache misparses some growth fields by
    # orders of magnitude (observed sales_qoq=164877). Anything with |v|>400%
    # is implausible for these ratios — excluded as misparsed, never averaged.
    def _plaus(v):
        return v if (v is not None and abs(v) <= 400) else None
    eps5 = _plaus(_num(f.get("eps_past_5y"))); sales5 = _plaus(_num(f.get("sales_past_5y")))
    epsn = _plaus(_num(f.get("eps_next_y"))); sq = _plaus(_num(f.get("sales_qoq")))
    if inst == "etf_fund":
        missing.append("growth (not applicable to funds)")
    elif eps5 is None and sales5 is None and sq is None:
        missing.append("growth (eps_past_5y / sales_past_5y / sales_qoq absent or misparsed)")
    else:
        g = [v for v in (eps5, sales5, sq) if v is not None]
        avg = sum(g) / len(g)
        fwd = f" · next-yr EPS {epsn:+.0f}%" if epsn is not None else ""
        if avg >= 15:
            add(_factor("growth", "STRONG", 1.0, f"hist growth avg {avg:+.0f}%{fwd}"))
        elif avg >= 5:
            add(_factor("growth", "POSITIVE", 0.5, f"hist growth avg {avg:+.0f}%{fwd}"))
        elif avg >= -5:
            add(_factor("growth", "FLAT", 0.0, f"hist growth avg {avg:+.0f}%{fwd}"))
        else:
            add(_factor("growth", "DECLINING", -1.0, f"hist growth avg {avg:+.0f}%{fwd}"))

    # ── profitability ────────────────────────────────────────────────────────
    om = _num(f.get("oper_margin_pct")); pm = _num(f.get("profit_margin_pct"))
    roic = _num(f.get("roic_pct")); roe = _num(f.get("roe_pct"))
    if inst == "etf_fund":
        pass
    elif om is None and pm is None and roic is None and roe is None:
        missing.append("profitability (margins / roic / roe)")
    else:
        ret = roic if roic is not None else roe
        m = pm if pm is not None else om
        ev = " · ".join(x for x in (
            f"net margin {m:.0f}%" if m is not None else None,
            f"ROIC {roic:.0f}%" if roic is not None else (f"ROE {roe:.0f}%" if roe is not None else None),
        ) if x)
        if (m is not None and m >= 15) or (ret is not None and ret >= 15):
            add(_factor("profitability", "STRONG", 1.0, ev))
        elif (m is not None and m > 0) or (ret is not None and ret > 0):
            add(_factor("profitability", "PROFITABLE", 0.5, ev))
        else:
            add(_factor("profitability", "UNPROFITABLE", -1.0, ev or "negative margins"))

    # ── balance sheet / liquidity ────────────────────────────────────────────
    de = _num(f.get("total_debt_equity")) or _num(f.get("lt_debt_equity"))
    cr = _num(f.get("current_ratio")) or _num(f.get("quick_ratio"))
    if inst == "etf_fund":
        pass
    elif de is None and cr is None:
        missing.append("balance sheet (debt/equity, current_ratio)")
    else:
        ev = " · ".join(x for x in (
            f"D/E {de:.2f}" if de is not None else None,
            f"current ratio {cr:.1f}" if cr is not None else None) if x)
        if (de is not None and de > 2.0) or (cr is not None and cr < 1.0):
            add(_factor("balance_sheet", "STRETCHED", -1.0, ev))
        elif (de is not None and de < 0.5) and (cr is None or cr >= 1.5):
            add(_factor("balance_sheet", "STRONG", 1.0, ev))
        else:
            add(_factor("balance_sheet", "ADEQUATE", 0.2, ev))

    # ── valuation (skip for pre-profit: P/E is meaningless there) ────────────
    pe = _num(f.get("pe")); peg = _num(f.get("peg")); ps = _num(f.get("ps"))
    if inst in ("etf_fund",):
        pass
    elif inst == "pre_profit":
        if ps is not None:
            sig = "RICH" if ps > 15 else "ELEVATED" if ps > 8 else "REASONABLE"
            add(_factor("valuation", sig, -0.8 if ps > 15 else -0.3 if ps > 8 else 0.2,
                        f"P/S {ps:.1f} (pre-profit — P/E not meaningful)"))
        else:
            missing.append("valuation (P/S for pre-profit)")
    elif pe is None and peg is None and ps is None:
        missing.append("valuation (pe / peg / ps)")
    else:
        if peg is not None and 0 < peg <= 1.5:
            add(_factor("valuation", "ATTRACTIVE", 0.8, f"PEG {peg:.2f}"))
        elif pe is not None and 0 < pe <= 18:
            add(_factor("valuation", "REASONABLE", 0.5, f"P/E {pe:.1f}"))
        elif pe is not None and pe > 45:
            add(_factor("valuation", "RICH", -0.8, f"P/E {pe:.1f}"))
        elif peg is not None and peg > 3:
            add(_factor("valuation", "RICH", -0.6, f"PEG {peg:.2f}"))
        else:
            add(_factor("valuation", "FULL", 0.0,
                        f"P/E {pe:.1f}" if pe is not None else f"P/S {ps:.1f}" if ps is not None else "mixed"))

    # ── dilution / short interest / ownership structure ──────────────────────
    sf = _num(facts.get("short_float_pct")) or _num(f.get("short_float_pct"))
    io = _num(f.get("insider_own_pct")); inst_own = _num(f.get("inst_own_pct"))
    if sf is None and io is None and inst_own is None:
        if inst not in ("etf_fund",):
            missing.append("ownership/short structure")
    else:
        ev = " · ".join(x for x in (
            f"short float {sf:.1f}%" if sf is not None else None,
            f"insider {io:.0f}%" if io is not None else None,
            f"institutional {inst_own:.0f}%" if inst_own is not None else None) if x)
        if sf is not None and sf >= 15:
            add(_factor("dilution_short", "CROWDED_SHORT", -0.8, ev))
        elif sf is not None and sf >= 8:
            add(_factor("dilution_short", "ELEVATED_SHORT", -0.4, ev))
        else:
            add(_factor("dilution_short", "CLEAN", 0.3, ev or "no elevated short interest"))

    # ── trend (works for every instrument incl. funds) ───────────────────────
    price = _num(facts.get("live_price")) or _num(facts.get("enriched_price"))
    sma50 = _num(facts.get("sma50")); rsi = _num(facts.get("rsi"))
    if price is None or (sma50 is None and rsi is None):
        missing.append("trend (price / sma50 / rsi)")
    else:
        above = sma50 is not None and price > sma50
        ev = " · ".join(x for x in (
            f"px {'above' if above else 'below'} SMA50" if sma50 is not None else None,
            f"RSI {rsi:.0f}" if rsi is not None else None) if x)
        if above and rsi is not None and rsi >= 50:
            add(_factor("trend", "UPTREND", 0.7, ev))
        elif above or (rsi is not None and rsi >= 50):
            add(_factor("trend", "MIXED", 0.2, ev))
        else:
            add(_factor("trend", "DOWNTREND", -0.7, ev))

    # ── event risk (earnings proximity from normalized events, if present) ───
    ev_state = str((facts.get("event_state") or {}).get("state")
                   if isinstance(facts.get("event_state"), dict) else facts.get("event_state") or "").upper()
    days = _num((facts.get("event_state") or {}).get("days_to_event")
                if isinstance(facts.get("event_state"), dict) else facts.get("days_to_earnings"))
    if "BLOCK" in ev_state or (days is not None and 0 <= days <= 7):
        add(_factor("event_risk", "IMMINENT", -0.5,
                    f"event in {days:.0f}d" if days is not None else ev_state))
    elif days is not None:
        add(_factor("event_risk", "CLEAR", 0.1, f"next event {days:.0f}d out"))
    else:
        missing.append("event calendar")

    # ── coverage + state mapping ─────────────────────────────────────────────
    applicable = 7 - (4 if inst == "etf_fund" else 0)   # funds: trend/event/short only-ish
    covered = len(factors)
    coverage = covered / max(1, applicable)
    if inst == "etf_fund":
        # funds are judged on trend + structure, not corporate fundamentals
        state = ("CONSTRUCTIVE" if score >= 0.5 else
                 "NEUTRAL" if score > -0.5 else "FUNDAMENTALLY_UNATTRACTIVE")
    elif coverage < 0.45 or inst == "unknown":
        state = "INSUFFICIENT_EVIDENCE"
    elif score <= -1.6:
        state = "FUNDAMENTALLY_UNATTRACTIVE"
    elif inst == "pre_profit":
        state = ("SPECULATIVE_CONSTRUCTIVE" if score >= 0.8 else
                 "NEUTRAL" if score > -1.6 else "FUNDAMENTALLY_UNATTRACTIVE")
    elif inst == "recent_listing":
        state = ("SPECULATIVE_CONSTRUCTIVE" if score >= 1.2 else
                 "NEUTRAL" if score > -1.6 else "FUNDAMENTALLY_UNATTRACTIVE")
    elif score >= 2.0:
        state = "CONSTRUCTIVE"
    elif score >= 0.8:
        state = "SPECULATIVE_CONSTRUCTIVE"
    else:
        state = "NEUTRAL"

    return {
        "engine": "deterministic_thesis", "engine_version": ENGINE_VERSION,
        "thesis_state": state, "instrument_class": inst,
        "score": round(score, 2),
        "factors": factors,
        "missing_evidence": missing,
        "evidence_coverage_pct": round(coverage * 100),
        # honesty: this is coverage + rule stability, NOT predicted success
        "confidence_basis": "evidence coverage and fixed-rule stability — not outcome probability",
    }
