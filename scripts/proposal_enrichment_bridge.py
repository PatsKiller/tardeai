#!/usr/bin/env python3
"""proposal_enrichment_bridge.py — Single source for broker-proposal technicals from Finviz enrichment.

Watchlist / broker-queue proposals are not momentum-scanned, so indicator_confluence_cache is often
empty while ticker_enrichment_cache.json (same feed as Entry helper) has RSI/ATR/RVOL/SMA data.
All proposal technical surfaces should hydrate from here before grading or agent review.
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENRICH_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "ticker_enrichment_cache.json"


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def load_enrichment(symbol: str) -> dict:
    sym = str(symbol or "").upper().strip()
    if not sym:
        return {}
    try:
        if ENRICH_PATH.exists():
            row = json.loads(ENRICH_PATH.read_text()).get(sym, {})
            return row if isinstance(row, dict) else {}
    except Exception:
        pass
    return {}


def enrichment_technicals(symbol: str, *, live_price: float | None = None) -> dict:
    """Normalized technical fields from Finviz enrichment cache."""
    e = load_enrichment(symbol)
    if not e:
        return {"available": False, "source": "finviz_enrichment"}

    px = _f(live_price)
    atr = _f(e.get("atr"))
    rsi = _f(e.get("rsi"))
    rvol = _f(e.get("rvol"))
    gap = _f(e.get("gap_pct"))
    atr_pct = round(atr / px * 100, 2) if atr and px and px > 0 else _f(e.get("volatility_w_pct"))

    mas = []
    for label, pk in (("SMA20", "sma20_pct"), ("SMA50", "sma50_pct"), ("SMA200", "sma200_pct")):
        pct = _f(e.get(pk))
        if pct is None:
            continue
        ma_price = round(px / (1 + pct / 100), 2) if (px and pct != -100) else None
        mas.append({"label": label, "pct_above": round(pct, 2), "price": ma_price, "above": pct >= 0})

    above_ct = sum(1 for m in mas if m.get("above"))
    trend = e.get("trend") or (
        "uptrend" if mas and above_ct == len(mas)
        else "downtrend" if mas and above_ct == 0
        else "mixed" if mas else None
    )

    return {
        "available": bool(rsi is not None or atr is not None or rvol is not None),
        "source": "finviz_enrichment",
        "rsi": rsi,
        "atr": atr,
        "atr_pct": atr_pct,
        "rvol": rvol,
        "gap_pct": gap,
        "trend": trend,
        "rsi_status": e.get("rsi_status"),
        "sma20_pct": _f(e.get("sma20_pct")),
        "sma50_pct": _f(e.get("sma50_pct")),
        "sma200_pct": _f(e.get("sma200_pct")),
        "week52_high_pct": _f(e.get("week52_high_pct")),
        "week52_low_pct": _f(e.get("week52_low_pct")),
        "beta": _f(e.get("beta")),
        "mas": mas,
        "cached_at": e.get("cached_at"),
    }


def _classify_rsi(rsi: float | None) -> str | None:
    if rsi is None:
        return None
    if rsi >= 80:
        return "extremely overbought"
    if rsi >= 70:
        return "overbought"
    if rsi >= 55:
        return "bullish momentum"
    if rsi >= 45:
        return "neutral"
    if rsi >= 30:
        return "weak"
    return "oversold"


def _classify_rvol(rvol: float | None) -> str | None:
    if rvol is None:
        return None
    if rvol >= 10:
        return "exceptional attention"
    if rvol >= 5:
        return "high attention"
    if rvol >= 2:
        return "elevated"
    return "normal / weak"


def grade_from_enrichment(tech: dict, *, adx_regime: str | None = None) -> tuple[str, int, list[str]]:
    """Score technical grade from enrichment fields (aligned with proposal_technical_snapshot tiers)."""
    concerns: list[str] = []
    rsi = tech.get("rsi")
    rvol = tech.get("rvol")
    atr_pct = tech.get("atr_pct")
    trend = str(tech.get("trend") or "").lower()
    rsi_state = _classify_rsi(rsi)

    if rsi is None:
        concerns.append("RSI missing — run enrich_proposal_technicals")
    if tech.get("atr") is None:
        concerns.append("ATR missing — run enrich_proposal_technicals")

    score = 0
    if rsi is not None and rsi_state not in ("overbought", "extremely overbought"):
        score += 20
    elif rsi is not None:
        score += 5
        concerns.append(f"RSI {rsi_state}")

    if trend == "uptrend":
        score += 20
    elif trend == "mixed":
        score += 8
    elif trend:
        score += 3
        concerns.append(f"Trend {trend}")

    mas = tech.get("mas") or []
    if mas:
        above = sum(1 for m in mas if m.get("above"))
        if above == len(mas):
            score += 15
        elif above >= 2:
            score += 10
        else:
            score += 4

    if atr_pct is not None:
        if 2 <= atr_pct <= 8:
            score += 15
        elif atr_pct < 15:
            score += 8
        else:
            score += 3
            concerns.append("Highly volatile — wide stops needed")

    if rvol is not None:
        if rvol >= 2:
            score += 10
        else:
            score += 3
            concerns.append(f"RVOL {_classify_rvol(rvol)}")

    if adx_regime and "trend" in str(adx_regime).lower():
        score += 10

    if score >= 80:
        grade = "TECH_STRONG"
    elif score >= 60:
        grade = "TECH_OK"
    elif score >= 40:
        grade = "TECH_MIXED"
    elif score >= 20:
        grade = "TECH_WEAK"
    else:
        grade = "TECH_INCOMPLETE"

    return grade, score, concerns


GRADE_VERDICTS = {
    "TECH_STRONG": "Favorable setup",
    "TECH_OK": "Acceptable setup",
    "TECH_MIXED": "Mixed — caution warranted",
    "TECH_WEAK": "Weak — avoid chasing",
    "TECH_INCOMPLETE": "Insufficient data",
}

GRADE_ACTIONS = {
    "TECH_STRONG": "Technicals support entry if thesis band and oversight gates pass.",
    "TECH_OK": "Proceed with normal size after catalyst and band confirmation.",
    "TECH_MIXED": "Reduce size or wait for pullback — setup is not clean.",
    "TECH_WEAK": "Do not chase — wait for RSI cool-off, VWAP reclaim, or better band entry.",
    "TECH_INCOMPLETE": "Run ↻ Refresh prices + recalibrate — Finviz enrichment has not populated yet.",
}

GRADE_METHODOLOGY = (
    "Score 0–100 from RSI posture, MA trend stack, ATR%, RVOL, ADX. "
    "≥80 TECH_STRONG · ≥60 TECH_OK · ≥40 TECH_MIXED · ≥20 TECH_WEAK · else INCOMPLETE. "
    "Same Finviz feed as Entry helper."
)

REFRESH_CADENCE = "Re-graded every 2h (cron) and on ↻ Refresh prices + recalibrate"


def build_technical_narrative(
    tech: dict,
    grade: str,
    concerns: list[str],
    *,
    adx_regime: str | None = None,
) -> str:
    """Plain-English technical assessment — one paragraph the operator can act on."""
    parts: list[str] = []
    rsi = tech.get("rsi")
    rvol = tech.get("rvol")
    gap = tech.get("gap_pct")
    trend = tech.get("trend")
    rsi_state = _classify_rsi(rsi)

    if grade == "TECH_INCOMPLETE":
        return "Technical data not yet available — enrichment cron or manual refresh required before grading."

    if rsi is not None:
        if rsi_state in ("overbought", "extremely overbought"):
            parts.append(f"RSI {rsi:.0f} is {rsi_state} — extended move, poor reward/risk for new longs")
        elif rsi_state == "oversold":
            parts.append(f"RSI {rsi:.0f} oversold — potential bounce zone if trend intact")
        elif rsi >= 55:
            parts.append(f"RSI {rsi:.0f} shows bullish momentum")
        else:
            parts.append(f"RSI {rsi:.0f} neutral-to-weak")

    mas = tech.get("mas") or []
    if mas:
        above = sum(1 for m in mas if m.get("above"))
        if above == len(mas):
            parts.append("price above SMA20/50/200 (uptrend stack)")
        elif above == 0:
            parts.append("price below all major MAs (downtrend)")
        else:
            parts.append("mixed MA stack — chop, no clean trend break")

    if rvol is not None:
        if rvol >= 10:
            parts.append(f"RVOL {rvol:.1f}× exceptional attention — high noise, size down")
        elif rvol < 1:
            parts.append(f"RVOL {rvol:.1f}× weak participation — breakout lacks volume confirmation")
        elif rvol >= 2:
            parts.append(f"RVOL {rvol:.1f}× elevated interest")

    if gap is not None and abs(float(gap)) >= 5:
        parts.append(f"gap {float(gap):+.1f}% — gap-fade risk on longs")

    if trend and trend not in str(parts):
        parts.append(f"trend: {trend}")

    if adx_regime:
        parts.append(f"ADX {adx_regime}")

    if concerns:
        parts.append(f"flags: {'; '.join(concerns[:3])}")

    verdict = GRADE_VERDICTS.get(grade, grade)
    body = ". ".join(parts) if parts else "Limited indicator coverage."
    return f"{verdict} — {body}."


def build_technical_assessment(
    tech: dict,
    grade: str,
    score: int,
    concerns: list[str],
    *,
    adx_regime: str | None = None,
    data_sources: list[str] | None = None,
    graded_at: str | None = None,
) -> dict:
    return {
        "verdict": GRADE_VERDICTS.get(grade, grade),
        "grade": grade,
        "score": score,
        "narrative": build_technical_narrative(tech, grade, concerns, adx_regime=adx_regime),
        "action": GRADE_ACTIONS.get(grade, "Review technicals before routing."),
        "concerns": concerns[:6],
        "methodology": GRADE_METHODOLOGY,
        "refresh_cadence": REFRESH_CADENCE,
        "graded_at": graded_at,
        "data_sources": data_sources or [],
    }


def build_technical_summary(tech: dict, *, adx_regime: str | None = None) -> str:
    parts = []
    if tech.get("rsi") is not None:
        parts.append(f"RSI {float(tech['rsi']):.1f}")
    if tech.get("atr") is not None:
        if tech.get("atr_pct") is not None:
            parts.append(f"ATR {float(tech['atr_pct']):.1f}%")
        else:
            parts.append(f"ATR ${float(tech['atr']):.2f}")
    if tech.get("rvol") is not None:
        parts.append(f"RVOL {float(tech['rvol']):.1f}x")
    if tech.get("gap_pct") is not None:
        parts.append(f"Gap {float(tech['gap_pct']):+.1f}%")
    if adx_regime:
        parts.append(f"ADX {adx_regime}")
    if tech.get("trend"):
        parts.append(str(tech["trend"]))
    return " · ".join(parts)


def snapshot_from_enrichment(symbol: str, *, live_price: float | None = None, adx_regime: str | None = None) -> dict:
    """proposal_technical_snapshot-compatible dict from enrichment."""
    tech = enrichment_technicals(symbol, live_price=live_price)
    grade, score, concerns = grade_from_enrichment(tech, adx_regime=adx_regime)
    rsi = tech.get("rsi")
    atr = tech.get("atr")
    rvol = tech.get("rvol")
    return {
        "rsi": rsi,
        "rsi_state": _classify_rsi(rsi),
        "atr": atr,
        "atr_pct": tech.get("atr_pct"),
        "atr_state": (
            "normal active" if tech.get("atr_pct") and 2 <= float(tech["atr_pct"]) <= 8
            else "volatile" if tech.get("atr_pct") and float(tech["atr_pct"]) > 8
            else ("ATR missing" if not atr else "low volatility")
        ),
        "rvol": rvol,
        "rvol_state": _classify_rvol(rvol),
        "gap_pct": tech.get("gap_pct"),
        "trend": tech.get("trend"),
        "technical_grade": grade,
        "technical_score": score,
        "technical_concerns": concerns,
        "enrichment_source": tech.get("source"),
        "sma20_distance_pct": tech.get("sma20_pct"),
        "sma50_distance_pct": tech.get("sma50_pct"),
    }


def compute_proposal_intel_readiness(
    symbol: str,
    conn,
    *,
    catalyst: str | None = None,
    catalyst_verified: bool = False,
    has_technical_snapshot: bool = False,
) -> int:
    """Broker-proposal intel readiness — does not require trade_ai_scans."""
    sym = str(symbol or "").upper()
    score = 0
    tech = enrichment_technicals(sym)
    if tech.get("rsi") is not None and tech.get("atr") is not None:
        score += 30
    elif tech.get("available"):
        score += 15

    if catalyst:
        score += 20 if catalyst_verified else 10

    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM news_articles WHERE symbol=%s AND created_at > NOW() - INTERVAL '14 days'",
            (sym,),
        )
        news_n = int((cur.fetchone() or [0])[0] or 0)
        if news_n >= 3:
            score += 20
        elif news_n >= 1:
            score += 12

        cur.execute(
            """SELECT 1 FROM yahoo_analyst_targets_history WHERE symbol=%s
               AND created_at > NOW() - INTERVAL '30 days' LIMIT 1""",
            (sym,),
        )
        if cur.fetchone():
            score += 15

        cur.execute(
            "SELECT 1 FROM indicator_confluence_cache WHERE symbol=%s LIMIT 1",
            (sym,),
        )
        if cur.fetchone():
            score += 10
    except Exception:
        pass

    if has_technical_snapshot:
        score += 5

    return min(100, score)