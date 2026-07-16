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
STOCK_INTEL_PATH = STATE / "stock_intelligence.json"
OPTIONS_PROP_PATH = STATE / "options_proposals.json"

# Benchmark for relative strength (broad growth ETF widely held)
_BENCH = "SCHG"

# Data quality: fields that count toward "has security data"
_CORE_FIELDS = ("rsi", "perf_month_pct", "pe", "eps_next_y", "avg_vol_m", "beta")

# Gate for high-visibility adds: RSI + at least one RS metric
_MIN_ADD_REQUIRES = ("rsi", "rel_strength")


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


@lru_cache(maxsize=1)
def _load_stock_intel() -> dict[str, Any]:
    """Finnhub-backed analyst consensus from stock_intelligence.json."""
    if not STOCK_INTEL_PATH.exists():
        return {}
    try:
        d = json.loads(STOCK_INTEL_PATH.read_text(encoding="utf-8"))
        out: dict[str, Any] = {}
        for it in d.get("items") or []:
            if not isinstance(it, dict):
                continue
            sym = str(it.get("symbol") or "").upper()
            if not sym:
                continue
            out[sym] = it
        return out
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _load_options_by_underlying() -> dict[str, list[dict[str, Any]]]:
    """Options desk proposals keyed by underlying (IV rank, bias)."""
    if not OPTIONS_PROP_PATH.exists():
        return {}
    try:
        d = json.loads(OPTIONS_PROP_PATH.read_text(encoding="utf-8"))
        by: dict[str, list[dict[str, Any]]] = {}
        for p in d.get("proposals") or []:
            if not isinstance(p, dict):
                continue
            u = str(p.get("underlying") or p.get("symbol") or "").upper()
            if u:
                by.setdefault(u, []).append(p)
        return by
    except Exception:
        return {}


def clear_security_cache() -> None:
    _load_enrich.cache_clear()
    _load_tech.cache_clear()
    _load_finviz.cache_clear()
    _load_stock_intel.cache_clear()
    _load_options_by_underlying.cache_clear()
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

    # Finnhub consensus (stock_intelligence) — prefer over corrupted enrichment ratings
    si = _load_stock_intel().get(sym) or {}
    fh = si.get("analyst") if isinstance(si.get("analyst"), dict) else {}
    fh_buy = int(fh.get("buy") or 0) + int(fh.get("strong_buy") or 0)
    fh_hold = int(fh.get("hold") or 0)
    fh_sell = int(fh.get("sell") or 0) + int(fh.get("strong_sell") or 0)
    fh_n = fh_buy + fh_hold + fh_sell
    consensus_label = None
    if fh_n > 0:
        if fh_buy >= fh_hold and fh_buy >= fh_sell and fh_buy >= max(1, fh_n * 0.45):
            consensus_label = "Buy" if int(fh.get("strong_buy") or 0) < fh_buy * 0.6 else "Strong Buy"
            if int(fh.get("strong_buy") or 0) >= max(3, fh_buy * 0.4):
                consensus_label = "Strong Buy"
        elif fh_sell > fh_buy:
            consensus_label = "Sell"
        else:
            consensus_label = "Hold"
    # Override broken enrichment "Strong Sell" when Finnhub exists
    if consensus_label:
        analyst = consensus_label

    # Options desk: IV rank / bias from proposals
    opts = _load_options_by_underlying().get(sym) or []
    iv_rank = None
    opt_sentiment = "No unusual options activity detected"
    opt_note = "Options data incomplete or no desk proposals for this name."
    if opts:
        ivs = [_f(p.get("iv_rank")) for p in opts if _f(p.get("iv_rank")) is not None]
        iv_rank = round(sum(ivs) / len(ivs), 1) if ivs else None
        calls = sum(1 for p in opts if str(p.get("option_type") or "").lower() == "call")
        puts = sum(1 for p in opts if str(p.get("option_type") or "").lower() == "put")
        if calls > puts * 1.5:
            opt_sentiment = "Bullish bias (call-heavy desk proposals)"
        elif puts > calls * 1.5:
            opt_sentiment = "Bearish / hedge bias (put-heavy desk proposals)"
        else:
            opt_sentiment = "Mixed / income (covered-call style activity)"
        opt_note = (
            f"{len(opts)} desk proposal(s)"
            + (f"; IV rank ~{iv_rank}" if iv_rank is not None else "")
            + f"; call={calls} put={puts}."
        )

    has_rs = vs_spy_m is not None or vs_qqq_m is not None or rel_m is not None
    data_complete = bool(rsi is not None and has_rs)
    incomplete_reason = None
    if not data_complete:
        missing = []
        if rsi is None:
            missing.append("RSI")
        if not has_rs:
            missing.append("relative strength")
        incomplete_reason = "Incomplete data — missing " + " + ".join(missing)

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
        "analyst_consensus": consensus_label,
        "analyst_counts": {
            "buy": fh_buy, "hold": fh_hold, "sell": fh_sell, "n": fh_n,
            "provider": fh.get("provider"), "as_of": fh.get("recommendation_period"),
        } if fh_n else None,
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
        "data_complete": data_complete,
        "incomplete_reason": incomplete_reason,
        "data_coverage_pct": data_coverage,
        "data_fields": data_fields,
        "iv_rank": iv_rank,
        "options_sentiment": opt_sentiment,
        "options_note": opt_note,
        "intel_bucket": si.get("bucket"),
        "intel_score": si.get("score"),
    }
    score_pack = score_security(snap)
    snap.update(score_pack)
    # Structured snapshots for UI template
    snap["technical_snapshot"] = {
        "rsi": rsi,
        "rsi_zone": _rsi_bucket(rsi),
        "rs_spy_1m": vs_spy_m,
        "rs_qqq_1m": vs_qqq_m,
        "rs_schg_1m": rel_m,
        "sma50_pct": sma50,
        "sma200_pct": sma200,
        "rvol": rvol,
        "beta": beta,
    }
    snap["analyst_snapshot"] = {
        "consensus": consensus_label or ("No coverage" if not fh_n else analyst),
        "counts": snap.get("analyst_counts"),
        "target": snap.get("target"),
        "pe": pe,
        "peg": peg,
        "eps_next_y": eps_next_y,
        "earnings_momentum": earn,
        "coverage_flag": "ok" if fh_n else "no_finnhub_coverage",
    }
    snap["options_flow_snapshot"] = {
        "sentiment": opt_sentiment,
        "iv_rank": iv_rank,
        "note": opt_note,
        "source": "options_proposals desk" if opts else "none",
        "proposal_count": len(opts),
    }
    return snap


def score_security(snap: dict[str, Any]) -> dict[str, Any]:
    """Multi-factor conviction 0–100 with transparent component breakdown."""
    # Base 40; components sum toward 0–100 display
    components: dict[str, float] = {
        "rsi_momentum": 0.0,
        "relative_strength": 0.0,
        "valuation": 0.0,
        "analyst_consensus": 0.0,
        "earnings_revisions": 0.0,
        "trend_smas": 0.0,
        "options_flow": 0.0,
        "liquidity_vol": 0.0,
        "data_quality": 0.0,
    }
    why: list[str] = []
    risks: list[str] = []

    rsi = snap.get("rsi")
    if rsi is not None:
        if 35 <= rsi <= 65:
            components["rsi_momentum"] = 14.0
            why.append(f"RSI {rsi:.0f} constructive/neutral zone")
        elif rsi < 30:
            components["rsi_momentum"] = 8.0
            why.append(f"RSI {rsi:.0f} oversold — mean-reversion watch")
        elif rsi > 72:
            components["rsi_momentum"] = -12.0
            risks.append(f"RSI {rsi:.0f} overbought — reduce size / wait pullback")
        else:
            components["rsi_momentum"] = 6.0
            why.append(f"RSI {rsi:.0f} ({snap.get('rsi_status')})")
    else:
        components["rsi_momentum"] = -6.0
        risks.append("Missing RSI — incomplete technicals")

    rel_spy = snap.get("rel_strength_vs_spy_month_pct")
    rel = snap.get("rel_strength_month_pct")
    rel_use = rel_spy if rel_spy is not None else rel
    rel_label = "SPY" if rel_spy is not None else "SCHG"
    if rel_use is not None:
        if rel_use >= 3:
            components["relative_strength"] = 14.0
            why.append(f"Outperforming {rel_label} by {rel_use:+.1f}% (1M)")
        elif rel_use >= 0:
            components["relative_strength"] = 6.0
            why.append(f"In-line/slightly ahead of {rel_label} ({rel_use:+.1f}% 1M)")
        elif rel_use > -5:
            components["relative_strength"] = -4.0
            risks.append(f"Lagging {rel_label} by {rel_use:.1f}% (1M)")
        else:
            components["relative_strength"] = -12.0
            risks.append(f"Material underperformance vs {rel_label} ({rel_use:.1f}% 1M)")
    else:
        components["relative_strength"] = -5.0
        risks.append("Missing relative strength vs SPY/SCHG")
    rel_qqq = snap.get("rel_strength_vs_qqq_month_pct")
    if rel_qqq is not None and rel_spy is not None:
        if rel_qqq >= 3 and rel_spy >= 0:
            components["relative_strength"] += 3.0
            why.append(f"Also beating QQQ by {rel_qqq:+.1f}% (1M)")
        elif rel_qqq <= -5 and rel_spy <= -3:
            components["relative_strength"] -= 2.0
            risks.append(f"Lagging QQQ by {rel_qqq:.1f}% (1M)")

    earn = snap.get("earnings_momentum")
    if earn == "positive":
        components["earnings_revisions"] = 12.0
        bits = []
        if snap.get("eps_next_y") is not None:
            bits.append(f"EPS NY {snap['eps_next_y']:+.0f}%")
        why.append("Earnings momentum positive" + (f" ({', '.join(bits)})" if bits else ""))
    elif earn == "negative":
        components["earnings_revisions"] = -10.0
        risks.append("Earnings momentum negative")
    elif earn == "mixed":
        components["earnings_revisions"] = 2.0

    val = snap.get("valuation")
    if val in ("attractive", "cheap_pe"):
        components["valuation"] = 12.0
        why.append(
            f"Valuation {val}"
            + (f" PEG {snap['peg']:.2f}" if snap.get("peg") else "")
            + (f" P/E {snap['pe']:.1f}" if snap.get("pe") else "")
        )
    elif val in ("rich", "rich_pe"):
        components["valuation"] = -10.0
        risks.append(
            "Rich valuation"
            + (f" PEG {snap['peg']:.2f}" if snap.get("peg") else "")
            + " — size down"
        )
    elif val in ("fair", "fair_pe"):
        components["valuation"] = 4.0
        why.append("Valuation roughly fair")

    sma50 = snap.get("sma50_pct")
    sma200 = snap.get("sma200_pct")
    if sma50 is not None and sma200 is not None:
        if sma50 > 0 and sma200 > 0:
            components["trend_smas"] = 10.0
            why.append(f"Above SMA50/200 ({sma50:+.1f}% / {sma200:+.1f}%)")
        elif sma50 < 0 and sma200 < 0:
            components["trend_smas"] = -10.0
            risks.append(f"Below SMA50/200 ({sma50:+.1f}% / {sma200:+.1f}%)")
        else:
            components["trend_smas"] = 2.0
    if snap.get("trend") == "uptrend":
        components["trend_smas"] += 3.0
    elif snap.get("trend") == "downtrend":
        components["trend_smas"] -= 4.0
    if snap.get("tech_grade") == "green" or (snap.get("tech_score") or 0) >= 70:
        components["trend_smas"] += 4.0
    elif snap.get("tech_grade") == "red":
        components["trend_smas"] -= 6.0

    # Analyst — Finnhub consensus preferred
    counts = snap.get("analyst_counts") or {}
    n = int(counts.get("n") or 0)
    if n > 0:
        buy = int(counts.get("buy") or 0)
        sell = int(counts.get("sell") or 0)
        skew = (buy - sell) / max(n, 1)
        if skew >= 0.5:
            components["analyst_consensus"] = 14.0
            why.append(f"Analyst consensus bullish ({buy} buy / {sell} sell, n={n})")
        elif skew >= 0.2:
            components["analyst_consensus"] = 8.0
            why.append(f"Analyst lean positive (n={n})")
        elif skew <= -0.2:
            components["analyst_consensus"] = -12.0
            risks.append(f"Analyst lean negative (n={n})")
        else:
            components["analyst_consensus"] = 2.0
            why.append(f"Analyst mixed/hold (n={n})")
    else:
        components["analyst_consensus"] = 0.0
        risks.append("No Finnhub analyst coverage flag")

    # Options flow (confirming layer only)
    sent = (snap.get("options_sentiment") or "").lower()
    iv = snap.get("iv_rank")
    if "bullish" in sent:
        components["options_flow"] = 8.0
        why.append(snap.get("options_sentiment") or "Bullish options bias")
    elif "bearish" in sent or "put-heavy" in sent:
        components["options_flow"] = -8.0
        risks.append(snap.get("options_sentiment") or "Bearish options bias")
    elif "mixed" in sent or "income" in sent:
        components["options_flow"] = 2.0
    if iv is not None:
        if iv >= 60:
            components["options_flow"] -= 2.0
            risks.append(f"Elevated IV rank {iv}")
        elif iv <= 25:
            components["options_flow"] += 1.0

    if snap.get("liquidity") == "thin":
        components["liquidity_vol"] = -12.0
        risks.append("Thin liquidity")
    elif snap.get("liquidity") == "low":
        components["liquidity_vol"] = -5.0
    elif snap.get("liquidity") == "high":
        components["liquidity_vol"] = 3.0
    beta = snap.get("beta")
    if beta is not None:
        if beta >= 1.6:
            components["liquidity_vol"] -= 6.0
            risks.append(f"High beta {beta:.2f}")
        elif beta <= 0.8:
            components["liquidity_vol"] += 3.0

    if not snap.get("data_complete"):
        components["data_quality"] = -12.0
        risks.append(snap.get("incomplete_reason") or "Incomplete RSI/RS data")
    elif (snap.get("data_coverage_pct") or 0) >= 70:
        components["data_quality"] = 6.0
    else:
        components["data_quality"] = 2.0

    # Round components for display
    components = {k: round(v, 1) for k, v in components.items()}
    base = 40.0
    score = base + sum(components.values())
    score = max(0.0, min(100.0, score))
    if not snap.get("data_complete"):
        # Cap tier for incomplete adds
        score = min(score, 58.0)

    if score >= 72 and snap.get("data_complete"):
        tier = "A"
    elif score >= 52:
        tier = "B"
    else:
        tier = "C"

    headline_bits = why[:2] + risks[:1]
    headline = "; ".join(headline_bits) if headline_bits else "Limited security factors available"

    # Human-readable breakdown lines
    breakdown_lines = [
        f"RSI / Momentum: {components['rsi_momentum']:+.0f}",
        f"Relative Strength: {components['relative_strength']:+.0f}",
        f"Valuation: {components['valuation']:+.0f}",
        f"Analyst Consensus: {components['analyst_consensus']:+.0f}",
        f"Earnings / Growth: {components['earnings_revisions']:+.0f}",
        f"Trend / SMAs: {components['trend_smas']:+.0f}",
        f"Options Flow: {components['options_flow']:+.0f}",
        f"Liquidity / Vol: {components['liquidity_vol']:+.0f}",
        f"Data Quality: {components['data_quality']:+.0f}",
    ]

    return {
        "conviction_score": round(score, 1),
        "conviction_tier": tier,
        "conviction_base": base,
        "conviction_breakdown": components,
        "conviction_breakdown_lines": breakdown_lines,
        "why_selected": why[:5],
        "risk_flags": risks[:5],
        "conviction_headline": headline[:220],
        "vol_size_mult": _vol_size_mult(snap),
        "conviction_size_mult": {"A": 1.15, "B": 1.0, "C": 0.55}.get(tier, 0.7),
        "publishable_add": bool(snap.get("data_complete") and tier in ("A", "B") and score >= 52),
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
    portfolio_total_mv: float | None = None,
) -> dict[str, Any]:
    """Attach security snapshot + transparent conviction + action hints."""
    sym = (rec.get("symbol") or "").upper()
    if not sym:
        return rec
    snap = get_security_snapshot(sym)
    out = dict(rec)
    role = role or out.get("role") or "hold_review"

    # Data gate: demote incomplete adds to watchlist
    if role == "add_candidate" and not snap.get("data_complete"):
        out["role"] = "watchlist"
        out["suggested_weight_pct"] = "watch — incomplete RSI/RS data"
        role = "watchlist"
        out["data_gate"] = "blocked_incomplete"
    elif role == "add_candidate" and not snap.get("publishable_add"):
        out["role"] = "watchlist"
        out["suggested_weight_pct"] = (
            out.get("suggested_weight_pct") or "watch — low conviction / incomplete"
        )
        role = "watchlist"
        out["data_gate"] = "demoted_low_conviction"

    out["conviction_score"] = snap.get("conviction_score")
    out["conviction_tier"] = snap.get("conviction_tier")
    out["conviction_breakdown"] = snap.get("conviction_breakdown")
    out["conviction_breakdown_lines"] = snap.get("conviction_breakdown_lines")
    out["technical_snapshot"] = snap.get("technical_snapshot")
    out["analyst_snapshot"] = snap.get("analyst_snapshot")
    out["options_flow_snapshot"] = snap.get("options_flow_snapshot")
    out["data_complete"] = snap.get("data_complete")
    out["incomplete_reason"] = snap.get("incomplete_reason")
    out["security"] = {
        "rsi": snap.get("rsi"),
        "rsi_status": snap.get("rsi_status"),
        "rel_strength_month_pct": snap.get("rel_strength_month_pct"),
        "rel_strength_vs_spy_month_pct": snap.get("rel_strength_vs_spy_month_pct"),
        "rel_strength_vs_qqq_month_pct": snap.get("rel_strength_vs_qqq_month_pct"),
        "sma50_pct": snap.get("sma50_pct"),
        "sma200_pct": snap.get("sma200_pct"),
        "pe": snap.get("pe"),
        "peg": snap.get("peg"),
        "eps_next_y": snap.get("eps_next_y"),
        "earnings_momentum": snap.get("earnings_momentum"),
        "valuation": snap.get("valuation"),
        "beta": snap.get("beta"),
        "liquidity": snap.get("liquidity"),
        "analyst_rating": snap.get("analyst_consensus") or snap.get("analyst_rating"),
        "analyst_counts": snap.get("analyst_counts"),
        "iv_rank": snap.get("iv_rank"),
        "options_sentiment": snap.get("options_sentiment"),
        "trend": snap.get("trend"),
        "has_min_data": snap.get("has_min_data"),
        "data_complete": snap.get("data_complete"),
        "data_coverage_pct": snap.get("data_coverage_pct"),
    }

    bits = list(snap.get("why_selected") or [])[:2]
    risks = list(snap.get("risk_flags") or [])[:1]
    base_r = (out.get("rationale") or "").strip()
    extra = []
    if bits:
        extra.append("; ".join(bits))
    if risks and role in ("add_candidate", "watchlist", "trim_candidate"):
        extra.append(risks[0])
    if snap.get("conviction_tier"):
        extra.append(f"Conviction {snap['conviction_tier']} ({snap.get('conviction_score')})")
    if not snap.get("data_complete"):
        extra.append(snap.get("incomplete_reason") or "Incomplete data")
    if extra:
        joined = " · ".join(extra)
        out["rationale"] = (f"{base_r} {joined}" if base_r else joined)[:360]
    out["why_selected"] = snap.get("conviction_headline")

    # Action bar for CC UI
    actions = [
        {"id": "watchlist", "label": "Add to Watchlist", "href": f"/watch?symbol={sym}"},
        {"id": "open_trading", "label": "Open in Trading", "href": f"/trading?symbol={sym}"},
        {"id": "stop", "label": "Set / Refresh Stop", "href": f"/portfolio?tab=Stop%20Management&symbol={sym}"},
    ]
    if role == "add_candidate":
        actions.insert(0, {
            "id": "trade_ticket",
            "label": "Build Trade Ticket",
            "href": f"/trading?symbol={sym}&side=buy&intent=ri_add",
        })
    if role == "trim_candidate":
        actions.insert(0, {
            "id": "propose_trim",
            "label": f"Propose Trim {sym}",
            "href": f"/trading?symbol={sym}&side=sell&intent=ri_trim",
        })
    if role == "protect":
        actions.insert(0, {
            "id": "stop_first",
            "label": f"Protect {sym} Stop",
            "href": f"/portfolio?tab=Stop%20Management&symbol={sym}",
        })
    out["actions"] = actions[:5]
    return out


def filter_add_candidates(
    symbols: list[str],
    *,
    min_conviction: float = 52.0,
    require_rsi: bool = True,
    require_complete: bool = True,
    max_n: int = 4,
) -> list[dict[str, Any]]:
    """Rank symbols for adds; gate incomplete / low-conviction names."""
    ranked: list[tuple[float, dict[str, Any]]] = []
    incomplete: list[tuple[float, dict[str, Any]]] = []
    for sym in symbols:
        snap = get_security_snapshot(sym)
        score = float(snap.get("conviction_score") or 0)
        rsi = snap.get("rsi")
        if rsi is not None and rsi >= 78:
            score -= 15
        if snap.get("liquidity") == "thin":
            score -= 10
        if require_complete and not snap.get("data_complete"):
            incomplete.append((score, snap))
            continue
        if require_rsi and not snap.get("has_min_data"):
            incomplete.append((score, snap))
            continue
        if score < min_conviction:
            continue
        ranked.append((score, snap))
    ranked.sort(key=lambda x: -x[0])
    out = [s for _, s in ranked[:max_n]]
    # Fill with incomplete only as last resort (still returned for watchlist demotion)
    if len(out) < max_n and incomplete:
        incomplete.sort(key=lambda x: -x[0])
        for _, s in incomplete:
            if len(out) >= max_n:
                break
            out.append(s)
    if not out and symbols:
        soft = [(float(get_security_snapshot(s).get("conviction_score") or 0), get_security_snapshot(s)) for s in symbols]
        soft.sort(key=lambda x: -x[0])
        out = [s for _, s in soft[:max_n]]
    return out
