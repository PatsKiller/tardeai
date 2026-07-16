"""Security-level snapshots for Research Intelligence recommendations.

Merges ticker_enrichment_cache, technical_snapshot, and finviz_quote_cache into
a per-symbol fact pack: RSI, relative strength, earnings momentum, valuation,
liquidity, volatility — plus a conviction score used by sizing/selection.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE = PROJECT_ROOT / "data" / "portfolios" / "state"
ENRICH_PATH = STATE / "ticker_enrichment_cache.json"
TECH_PATH = STATE / "technical_snapshot.json"
FINVIZ_PATH = STATE / "finviz_quote_cache.json"

# Benchmark for relative strength (broad growth ETF widely held)
_BENCH = "SCHG"

# Data quality: fields that count toward "has security data"
_CORE_FIELDS = ("rsi", "perf_month_pct", "pe", "eps_next_y", "avg_vol_m", "beta")


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        x = float(v)
        if x != x:  # NaN
            return None
        return x
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def _load_enrich() -> dict[str, Any]:
    if not ENRICH_PATH.exists():
        return {}
    try:
        d = json.loads(ENRICH_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _load_tech() -> dict[str, Any]:
    if not TECH_PATH.exists():
        return {}
    try:
        d = json.loads(TECH_PATH.read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if not str(k).startswith("_") and isinstance(v, dict)}
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _load_finviz() -> dict[str, Any]:
    if not FINVIZ_PATH.exists():
        return {}
    try:
        d = json.loads(FINVIZ_PATH.read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if isinstance(v, dict) and k not in ("_meta",)}
    except Exception:
        return {}


def clear_security_cache() -> None:
    _load_enrich.cache_clear()
    _load_tech.cache_clear()
    _load_finviz.cache_clear()
    get_security_snapshot.cache_clear()
    market_benchmark.cache_clear()


@lru_cache(maxsize=1)
def market_benchmark() -> dict[str, Any]:
    """SCHG (or SPY) as relative-strength baseline."""
    for sym in (_BENCH, "SPY", "QQQ"):
        snap = get_security_snapshot(sym)
        if snap.get("ok") and snap.get("perf_month_pct") is not None:
            return {
                "symbol": sym,
                "perf_week_pct": snap.get("perf_week_pct"),
                "perf_month_pct": snap.get("perf_month_pct"),
                "perf_quarter_pct": snap.get("perf_quarter_pct"),
                "rsi": snap.get("rsi"),
            }
    return {"symbol": _BENCH, "perf_month_pct": 0.0}


def _rsi_bucket(rsi: float | None) -> str:
    if rsi is None:
        return "unknown"
    if rsi >= 70:
        return "overbought"
    if rsi >= 60:
        return "strong"
    if rsi >= 45:
        return "neutral"
    if rsi >= 30:
        return "weak"
    return "oversold"


def _valid_analyst(rating: str | None, recom_score: float | None) -> str | None:
    """Finviz-style ratings only; drop clearly corrupted enrichment values."""
    if not rating:
        return None
    r = str(rating).strip()
    # Corrupted cache often stamps Strong Sell on everything with absurd recom_score
    if recom_score is not None and (recom_score > 10 or recom_score < 0):
        return None
    allowed = {
        "strong buy", "buy", "hold", "neutral", "sell", "strong sell",
        "outperform", "underperform", "overweight", "underweight", "equal-weight",
    }
    if r.lower() in allowed:
        return r
    return None


@lru_cache(maxsize=512)
def get_security_snapshot(symbol: str) -> dict[str, Any]:
    """Unified security fact pack for one ticker."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return {"ok": False, "symbol": sym}

    enr = _load_enrich().get(sym) or {}
    tech = _load_tech().get(sym) or {}
    fin = _load_finviz().get(sym) or {}

    rsi = _f(tech.get("rsi") if tech.get("rsi") is not None else enr.get("rsi"))
    beta = _f(tech.get("beta") if tech.get("beta") is not None else enr.get("beta"))
    # Prefer finviz monthly vol (% daily-ish) when sensible; enrichment vol_% is often mis-scaled
    vol_m = _f(fin.get("volatility_m"))
    if vol_m is None or vol_m > 80:
        vol_m = _f(tech.get("volatility_m"))
    if vol_m is not None and vol_m > 80:
        vol_m = None  # unusable scale

    pe = _f(enr.get("pe"))
    peg = _f(enr.get("peg"))
    forward_pe = _f(enr.get("forward_pe"))
    eps_qoq = _f(enr.get("eps_qoq"))
    eps_next_y = _f(enr.get("eps_next_y"))
    eps_next_5y = _f(enr.get("eps_next_5y"))

    perf_w = _f(tech.get("perf_week") if tech.get("perf_week") is not None else enr.get("perf_week_pct"))
    perf_m = _f(tech.get("perf_month") if tech.get("perf_month") is not None else enr.get("perf_month_pct"))
    perf_q = _f(tech.get("perf_quarter") if tech.get("perf_quarter") is not None else enr.get("perf_quarter_pct"))
    # finviz fallback
    if perf_m is None:
        perf_m = _f(fin.get("perf_month"))
    if perf_w is None:
        perf_w = _f(fin.get("perf_week"))
    if perf_q is None:
        perf_q = _f(fin.get("perf_quarter"))

    avg_vol = _f(enr.get("avg_vol_m"))  # typically thousands of shares
    rvol = _f(fin.get("rvol") if fin.get("rvol") is not None else enr.get("rvol"))
    if rvol is None:
        rvol = _f(tech.get("relative_volume"))

    analyst = _valid_analyst(
        enr.get("analyst_rating") or fin.get("analyst") or tech.get("analyst"),
        _f(enr.get("recom_score")),
    )
    target = _f(fin.get("target") if fin.get("target") else tech.get("target"))

    sma20 = _f(tech.get("sma20_pct") if tech.get("sma20_pct") is not None else enr.get("sma20_pct"))
    sma50 = _f(tech.get("sma50_pct") if tech.get("sma50_pct") is not None else enr.get("sma50_pct"))
    sma200 = _f(tech.get("sma200_pct") if tech.get("sma200_pct") is not None else enr.get("sma200_pct"))
    trend = enr.get("trend") or None
    tech_score = _f(tech.get("tech_score"))
    tech_grade = tech.get("tech_grade")
    sector = enr.get("sector")
    industry = enr.get("industry")
    is_etf = bool(industry and "exchange traded" in str(industry).lower()) or sym in {
        "SCHG", "SCHD", "QQQ", "SPY", "XAR", "XLI", "XLB", "JEPI", "JEPQ", "DIVI", "DIV", "BND", "TLT", "IEF", "AGG",
    }

    # Relative strength vs SCHG (book core) + multi-index (SPY / QQQ / IWM)
    rel_m = None
    if sym != _BENCH and perf_m is not None:
        bench_enr = _load_enrich().get(_BENCH) or {}
        bench_tech = _load_tech().get(_BENCH) or {}
        b_m = _f(bench_tech.get("perf_month") if bench_tech.get("perf_month") is not None else bench_enr.get("perf_month_pct"))
        if b_m is not None:
            rel_m = round(perf_m - b_m, 2)

    rs_multi: dict[str, Any] = {}
    try:
        from lib.portfolio_benchmarks import multi_relative_strength
        rs_multi = multi_relative_strength(perf_m, perf_w, perf_q) or {}
    except Exception:
        rs_multi = {}
    vs_spy_m = rs_multi.get("vs_spy_month_pct")
    vs_qqq_m = rs_multi.get("vs_qqq_month_pct")

    # Liquidity flag
    liq = "unknown"
    if avg_vol is not None:
        # avg_vol_m appears to be thousands of shares
        if avg_vol >= 1000:
            liq = "high"
        elif avg_vol >= 200:
            liq = "medium"
        elif avg_vol >= 50:
            liq = "low"
        else:
            liq = "thin"

    # Valuation stance (simple heuristics; ETFs skip hard PE)
    val = "n/a" if is_etf else "unknown"
    if not is_etf:
        if peg is not None and peg > 0:
            if peg < 1.0:
                val = "attractive"
            elif peg < 1.8:
                val = "fair"
            else:
                val = "rich"
        elif pe is not None and pe > 0:
            if pe < 15:
                val = "cheap_pe"
            elif pe < 28:
                val = "fair_pe"
            else:
                val = "rich_pe"

    # Earnings momentum
    earn = "unknown"
    if eps_qoq is not None or eps_next_y is not None:
        q = eps_qoq or 0.0
        y = eps_next_y or 0.0
        if q > 0.1 or y > 12:
            earn = "positive"
        elif q < -0.15 or y < -5:
            earn = "negative"
        else:
            earn = "mixed"

    data_fields = sum(1 for k, v in [
        ("rsi", rsi), ("perf_m", perf_m), ("pe", pe), ("eps", eps_next_y),
        ("vol", avg_vol), ("beta", beta), ("sma50", sma50),
    ] if v is not None)
    has_min_data = rsi is not None  # hard min for adds
    data_coverage = round(100.0 * data_fields / 7.0, 0)

    snap = {
        "ok": data_fields >= 2,
        "symbol": sym,
        "rsi": rsi,
        "rsi_status": _rsi_bucket(rsi),
        "beta": beta,
        "volatility_m": vol_m,
        "pe": pe,
        "peg": peg,
        "forward_pe": forward_pe,
        "eps_qoq": eps_qoq,
        "eps_next_y": eps_next_y,
        "eps_next_5y": eps_next_5y,
        "perf_week_pct": perf_w,
        "perf_month_pct": perf_m,
        "perf_quarter_pct": perf_q,
        "rel_strength_month_pct": rel_m,  # vs SCHG (book core)
        "rel_strength_vs_spy_month_pct": vs_spy_m,
        "rel_strength_vs_qqq_month_pct": vs_qqq_m,
        "rel_strength_multi": rs_multi.get("vs") or {},
        "avg_vol_m": avg_vol,
        "rvol": rvol,
        "liquidity": liq,
        "analyst_rating": analyst,
        "target": target if target and target > 0 else None,
        "sma20_pct": sma20,
        "sma50_pct": sma50,
        "sma200_pct": sma200,
        "trend": trend,
        "tech_score": tech_score,
        "tech_grade": tech_grade,
        "sector": sector,
        "industry": industry,
        "is_etf": is_etf,
        "valuation": val,
        "earnings_momentum": earn,
        "has_min_data": has_min_data,
        "data_coverage_pct": data_coverage,
        "data_fields": data_fields,
    }
    score_pack = score_security(snap)
    snap.update(score_pack)
    return snap


def score_security(snap: dict[str, Any]) -> dict[str, Any]:
    """Multi-factor conviction score 0–100 → tier A/B/C + why bullets."""
    score = 50.0
    why: list[str] = []
    risks: list[str] = []

    rsi = snap.get("rsi")
    if rsi is not None:
        if 35 <= rsi <= 65:
            score += 8
            why.append(f"RSI {rsi:.0f} constructive/neutral zone")
        elif rsi < 30:
            score += 4
            why.append(f"RSI {rsi:.0f} oversold — mean-reversion watch, not chase")
        elif rsi > 72:
            score -= 12
            risks.append(f"RSI {rsi:.0f} overbought — reduce size / wait pullback")
        else:
            why.append(f"RSI {rsi:.0f} ({snap.get('rsi_status')})")

    # Prefer SPY relative strength for market edge; SCHG remains portfolio context
    rel_spy = snap.get("rel_strength_vs_spy_month_pct")
    rel = snap.get("rel_strength_month_pct")
    rel_use = rel_spy if rel_spy is not None else rel
    rel_label = "SPY" if rel_spy is not None else "SCHG"
    if rel_use is not None:
        if rel_use >= 3:
            score += 10
            why.append(f"Outperforming {rel_label} by {rel_use:+.1f}% (1M)")
        elif rel_use >= 0:
            score += 4
            why.append(f"In-line/slightly ahead of {rel_label} ({rel_use:+.1f}% 1M)")
        elif rel_use > -5:
            score -= 4
            risks.append(f"Lagging {rel_label} by {rel_use:.1f}% (1M)")
        else:
            score -= 10
            risks.append(f"Material underperformance vs {rel_label} ({rel_use:.1f}% 1M)")
    rel_qqq = snap.get("rel_strength_vs_qqq_month_pct")
    if rel_qqq is not None and rel_spy is not None:
        if rel_qqq >= 3 and rel_spy >= 0:
            score += 3
            why.append(f"Also beating QQQ by {rel_qqq:+.1f}% (1M)")
        elif rel_qqq <= -5 and rel_spy <= -3:
            score -= 2
            risks.append(f"Lagging QQQ by {rel_qqq:.1f}% (1M)")

    earn = snap.get("earnings_momentum")
    if earn == "positive":
        score += 10
        bits = []
        if snap.get("eps_qoq") is not None:
            bits.append(f"EPS QoQ {snap['eps_qoq']:+.0%}" if abs(snap["eps_qoq"]) < 5 else f"EPS QoQ {snap['eps_qoq']:+.1f}")
        if snap.get("eps_next_y") is not None:
            bits.append(f"EPS NY {snap['eps_next_y']:+.0f}%")
        why.append("Earnings momentum positive" + (f" ({', '.join(bits)})" if bits else ""))
    elif earn == "negative":
        score -= 10
        risks.append("Earnings momentum negative — thesis needs extra proof")
    elif earn == "mixed":
        score += 1

    val = snap.get("valuation")
    if val in ("attractive", "cheap_pe"):
        score += 8
        why.append(
            f"Valuation {val}"
            + (f" PEG {snap['peg']:.2f}" if snap.get("peg") else "")
            + (f" P/E {snap['pe']:.1f}" if snap.get("pe") else "")
        )
    elif val in ("rich", "rich_pe"):
        score -= 8
        risks.append(
            "Rich valuation"
            + (f" PEG {snap['peg']:.2f}" if snap.get("peg") else "")
            + (f" P/E {snap['pe']:.1f}" if snap.get("pe") else "")
            + " — size down"
        )
    elif val in ("fair", "fair_pe"):
        score += 2
        why.append("Valuation roughly fair vs simple PEG/PE screen")

    # Trend / SMAs
    sma50 = snap.get("sma50_pct")
    sma200 = snap.get("sma200_pct")
    if sma50 is not None and sma200 is not None:
        if sma50 > 0 and sma200 > 0:
            score += 8
            why.append(f"Above SMA50/200 ({sma50:+.1f}% / {sma200:+.1f}%)")
        elif sma50 < 0 and sma200 < 0:
            score -= 8
            risks.append(f"Below SMA50/200 ({sma50:+.1f}% / {sma200:+.1f}%)")
    if snap.get("trend") == "uptrend":
        score += 4
        why.append("Trend up")
    elif snap.get("trend") == "downtrend":
        score -= 6
        risks.append("Trend down")

    if snap.get("tech_grade") == "green" or (snap.get("tech_score") or 0) >= 70:
        score += 6
        why.append(f"Tech grade {snap.get('tech_grade') or 'solid'} (score {snap.get('tech_score')})")
    elif snap.get("tech_grade") == "red":
        score -= 8
        risks.append("Tech grade red")

    ar = snap.get("analyst_rating")
    if ar:
        al = ar.lower()
        if "strong buy" in al or al == "buy" or "outperform" in al or "overweight" in al:
            score += 8
            why.append(f"Analyst {ar}")
        elif "sell" in al or "underperform" in al or "underweight" in al:
            score -= 10
            risks.append(f"Analyst {ar}")
        else:
            why.append(f"Analyst {ar}")

    # Liquidity
    if snap.get("liquidity") == "thin":
        score -= 12
        risks.append("Thin liquidity — cut size or skip")
    elif snap.get("liquidity") == "low":
        score -= 5
        risks.append("Low average volume — smaller starter")
    elif snap.get("liquidity") == "high":
        score += 3

    # Volatility penalty (beta)
    beta = snap.get("beta")
    if beta is not None:
        if beta >= 1.6:
            score -= 6
            risks.append(f"High beta {beta:.2f} — smaller risk unit")
        elif beta <= 0.8:
            score += 3
            why.append(f"Lower beta {beta:.2f}")

    # Data coverage
    cov = snap.get("data_coverage_pct") or 0
    if cov < 40:
        score -= 8
        risks.append("Sparse security data — lower conviction")
    elif cov >= 70:
        score += 4

    score = max(0.0, min(100.0, score))
    if score >= 72:
        tier = "A"
    elif score >= 52:
        tier = "B"
    else:
        tier = "C"

    # Human one-liner
    headline_bits = why[:2] + risks[:1]
    headline = "; ".join(headline_bits) if headline_bits else "Limited security factors available"

    return {
        "conviction_score": round(score, 1),
        "conviction_tier": tier,
        "why_selected": why[:5],
        "risk_flags": risks[:4],
        "conviction_headline": headline[:220],
        "vol_size_mult": _vol_size_mult(snap),
        "conviction_size_mult": {"A": 1.15, "B": 1.0, "C": 0.65}.get(tier, 0.8),
    }


def _vol_size_mult(snap: dict[str, Any]) -> float:
    beta = snap.get("beta")
    vol_m = snap.get("volatility_m")
    mult = 1.0
    if beta is not None:
        if beta >= 2.0:
            mult *= 0.55
        elif beta >= 1.5:
            mult *= 0.7
        elif beta >= 1.2:
            mult *= 0.85
        elif beta <= 0.7:
            mult *= 1.1
    if vol_m is not None:
        # finviz monthly vol often ~1–6% daily-ish annualized feel; treat >4 as hot
        if vol_m >= 5:
            mult *= 0.7
        elif vol_m >= 3.5:
            mult *= 0.85
    if snap.get("liquidity") == "thin":
        mult *= 0.5
    elif snap.get("liquidity") == "low":
        mult *= 0.75
    return round(max(0.35, min(1.2, mult)), 3)


def enrich_ticker_recommendation(
    rec: dict[str, Any],
    *,
    role: str | None = None,
) -> dict[str, Any]:
    """Attach security snapshot + conviction to a ticker recommendation dict."""
    sym = (rec.get("symbol") or "").upper()
    if not sym:
        return rec
    snap = get_security_snapshot(sym)
    out = dict(rec)
    role = role or out.get("role") or "hold_review"

    out["conviction_score"] = snap.get("conviction_score")
    out["conviction_tier"] = snap.get("conviction_tier")
    out["security"] = {
        "rsi": snap.get("rsi"),
        "rsi_status": snap.get("rsi_status"),
        "rel_strength_month_pct": snap.get("rel_strength_month_pct"),
        "rel_strength_vs_spy_month_pct": snap.get("rel_strength_vs_spy_month_pct"),
        "rel_strength_vs_qqq_month_pct": snap.get("rel_strength_vs_qqq_month_pct"),
        "pe": snap.get("pe"),
        "peg": snap.get("peg"),
        "eps_next_y": snap.get("eps_next_y"),
        "earnings_momentum": snap.get("earnings_momentum"),
        "valuation": snap.get("valuation"),
        "beta": snap.get("beta"),
        "liquidity": snap.get("liquidity"),
        "analyst_rating": snap.get("analyst_rating"),
        "trend": snap.get("trend"),
        "has_min_data": snap.get("has_min_data"),
        "data_coverage_pct": snap.get("data_coverage_pct"),
    }
    # Strengthen rationale with security why
    bits = list(snap.get("why_selected") or [])[:2]
    risks = list(snap.get("risk_flags") or [])[:1]
    base_r = (out.get("rationale") or "").strip()
    extra = []
    if bits:
        extra.append("; ".join(bits))
    if risks and role in ("add_candidate", "watchlist"):
        extra.append(risks[0])
    if snap.get("conviction_tier"):
        extra.append(f"Conviction {snap['conviction_tier']} ({snap.get('conviction_score')})")
    if extra:
        joined = " · ".join(extra)
        out["rationale"] = (f"{base_r} {joined}" if base_r else joined)[:320]
    out["why_selected"] = snap.get("conviction_headline")
    return out


def filter_add_candidates(
    symbols: list[str],
    *,
    min_conviction: float = 48.0,
    require_rsi: bool = True,
    max_n: int = 4,
) -> list[dict[str, Any]]:
    """Rank symbols for add/watchlist; drop sparse or toxic technicals when possible."""
    ranked: list[tuple[float, dict[str, Any]]] = []
    for sym in symbols:
        snap = get_security_snapshot(sym)
        if require_rsi and not snap.get("has_min_data"):
            # Still allow with heavy penalty if nothing better
            if snap.get("data_fields", 0) < 2:
                continue
        score = float(snap.get("conviction_score") or 0)
        # Soft-block extreme overbought adds
        rsi = snap.get("rsi")
        if rsi is not None and rsi >= 78:
            score -= 15
        if snap.get("liquidity") == "thin":
            score -= 10
        if score < min_conviction and snap.get("data_fields", 0) >= 3:
            continue
        ranked.append((score, snap))
    ranked.sort(key=lambda x: -x[0])
    out = []
    for score, snap in ranked[:max_n]:
        out.append(snap)
    # If filter emptied list, return top by score without min (degraded)
    if not out and symbols:
        soft = []
        for sym in symbols:
            snap = get_security_snapshot(sym)
            soft.append((float(snap.get("conviction_score") or 0), snap))
        soft.sort(key=lambda x: -x[0])
        out = [s for _, s in soft[:max_n]]
    return out
