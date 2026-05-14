"""api_v2.py — Normalized API for Command Center v2.

All endpoints return stable, frontend-friendly JSON shapes.
Read-only aggregation + journal review write layer.
"""
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

from local_llm_config import get_local_llm_model, get_local_llm_base_url, get_local_llm_status




def _json_clean(obj):
    """Make Decimals, dates, datetimes JSON-serializable."""
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    return obj


def _load_json(path: Path):
    try:
        return json.loads(path.read_text()) if path.exists() else None
    except Exception:
        return None


_COUNTRY_FLAGS = {
    "usa": "🇺🇸", "united states": "🇺🇸", "us": "🇺🇸",
    "canada": "🇨🇦", "israel": "🇮🇱", "china": "🇨🇳",
    "united kingdom": "🇬🇧", "uk": "🇬🇧", "japan": "🇯🇵",
    "germany": "🇩🇪", "france": "🇫🇷", "south korea": "🇰🇷",
    "australia": "🇦🇺", "brazil": "🇧🇷", "india": "🇮🇳",
    "taiwan": "🇹🇼", "ireland": "🇮🇪", "netherlands": "🇳🇱",
    "switzerland": "🇨🇭", "singapore": "🇸🇬", "hong kong": "🇭🇰",
    "mexico": "🇲🇽", "malaysia": "🇲🇾", "bermuda": "🇧🇲",
    "cayman islands": "🇰🇾", "luxembourg": "🇱🇺", "norway": "🇳🇴",
    "sweden": "🇸🇪", "denmark": "🇩🇰", "finland": "🇫🇮",
    "spain": "🇪🇸", "italy": "🇮🇹", "argentina": "🇦🇷",
}
def _country_flag(c): return _COUNTRY_FLAGS.get((c or "").strip().lower(), "🇺🇸") if c else ""

def _db_query(sql, params=None, fetch="all"):
    """Run a read-only DB query. Returns list or dict or None."""
    try:
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return None
        return _execute(sql, params, fetch=fetch)
    except Exception:
        return None


# ── Endpoint handlers ─────────────────────────────────────────────────────

def _pi_score(d: dict) -> int:
    """Position Intelligence score — ports v1 piScore() exactly."""
    score = 50
    rsi = float(d.get("rsi") or 50)
    s50 = float(d.get("sma50_pct") or 0)
    s200 = float(d.get("sma200_pct") or 0)
    w52h = float(d.get("week52_high_pct") or 0)
    w52l = float(d.get("week52_low_pct") or 0)
    pos52 = 50
    if w52h != 0 or w52l != 0:
        rng = abs(w52h) + abs(w52l)
        pos52 = (abs(w52l) / rng * 100) if rng > 0 else 50
    short_flt = float(d.get("short_float_pct") or 0)
    eps_growth = float(d.get("eps_qoq") or d.get("eps_past_5y") or 0)
    # SMA alignment
    if s200 > 0 and s50 > 0: score += 12
    elif s200 > 0: score += 5
    elif s200 < -5: score -= 12
    # RSI zone
    if rsi > 70: score -= 8
    elif rsi > 55: score += 5
    elif rsi < 30: score -= 10
    elif rsi < 45: score -= 4
    # 52wk position
    if pos52 > 80: score += 8
    elif pos52 > 60: score += 3
    elif pos52 < 20: score -= 8
    # Short float
    if short_flt > 20: score -= 5
    # EPS growth
    if eps_growth > 15: score += 6
    elif eps_growth > 5: score += 3
    elif eps_growth < -10: score -= 5
    return max(0, min(100, score))


def _weighted_beta(positions):
    """Compute market-value-weighted beta from enrichment cache."""
    ec = _load_json(STATE_DIR / "ticker_enrichment_cache.json") or {}
    total_mv = sum(p.get("market_value", 0) for p in positions)
    if total_mv <= 0:
        return 0
    beta_sum = 0
    for p in positions:
        sym = p.get("symbol", "")
        beta = (ec.get(sym, {}) or {}).get("beta", 1.0) if isinstance(ec.get(sym), dict) else 1.0
        weight = p.get("market_value", 0) / total_mv
        beta_sum += beta * weight
    return round(beta_sum, 3)


def overview():
    h = _load_json(STATE_DIR / "holdings.json") or {}
    perf = _load_json(STATE_DIR / "performance_history.json") or {}
    fresh = _load_json(STATE_DIR / "_freshness.json") or {}
    news = _load_json(STATE_DIR / "portfolio_news.json") or {}

    holdings = h.get("holdings", [])
    totals = h.get("portfolio_totals", {})
    periods = perf.get("periods", {})
    active_positions = [p for p in holdings if not p.get("is_cash") and (p.get("market_value") or 0) > 100]

    # Sector allocation
    sectors = {}
    for p in active_positions:
        s = p.get("sector_type") or "Other"
        sectors[s] = sectors.get(s, 0) + (p.get("market_value") or 0)
    sector_list = sorted(sectors.items(), key=lambda x: -x[1])[:10]

    # Top movers
    movers = sorted(active_positions, key=lambda p: abs(p.get("day_change") or 0), reverse=True)[:6]

    # Notifications count
    notif_rows = _db_query("SELECT count(*) AS cnt FROM notification_log", fetch="one")
    aq_cnt = (_db_query("SELECT count(*) AS cnt FROM action_queue WHERE status='pending'", fetch="one") or {}).get("cnt", 0)
    jdq_cnt = (_db_query("SELECT count(*) AS cnt FROM john_decision_queue WHERE status='pending_john'", fetch="one") or {}).get("cnt", 0)
    pending_rows = {"cnt": aq_cnt + jdq_cnt}

    # Today's change = sum of per-holding day_change (actual market-hours move)
    today_change = sum(p.get("day_change") or 0 for p in holdings)
    total_val = totals.get("total_value", 0)
    today_pct = (today_change / (total_val - today_change) * 100) if total_val > abs(today_change) else 0

    # Trade AI run data
    import glob
    _runs = sorted(glob.glob(str(PROJECT_ROOT / "reports" / "2026-*" / "*" / "run_summary.json")))
    tai = {}
    if _runs:
        tai = _load_json(Path(_runs[-1])) or {}

    # Journal stats (exclude flat/zero-pnl trades from win rate, matching v1)
    journal = _load_json(STATE_DIR / "trade_journal.json") or {}
    j_all = journal.get("closed_trades") or journal.get("trades") or []
    j_total_pnl = sum(t.get("pnl") or t.get("realized_pnl") or 0 for t in j_all)
    j_real = [t for t in j_all if (t.get("pnl") or t.get("realized_pnl") or 0) != 0]
    j_wins = sum(1 for t in j_real if (t.get("pnl") or t.get("realized_pnl") or 0) > 0)
    j_win_rate = (j_wins / len(j_real) * 100) if j_real else 0
    # Use pre-computed stats if available
    j_stats = journal.get("stats", {})
    if j_stats.get("win_rate"):
        j_win_rate = j_stats["win_rate"]
    if j_stats.get("total_pnl") is not None:
        j_total_pnl = j_stats["total_pnl"]

    return {
        "portfolio_value": total_val,
        "total_cash": totals.get("total_cash", 0),
        "today_change": round(today_change, 2),
        "today_pct": round(today_pct, 2),
        "position_count": len(active_positions),
        "account_count": len(h.get("account_summaries", {})),
        "as_of": h.get("as_of", ""),
        "last_repriced": h.get("last_repriced", ""),
        "periods": {k: {"change_pct": v.get("change_pct"), "change": v.get("change"),
                        "estimated": v.get("source") == "repriced"}
                    for k, v in periods.items() if isinstance(v, dict)},
        "sectors": [{"name": n, "value": v} for n, v in sector_list],
        "top_movers": [{"symbol": m.get("symbol"), "name": (m.get("name") or "")[:30],
                        "day_change": m.get("day_change", 0), "day_change_pct": m.get("day_change_pct", 0)}
                       for m in movers],
        "trade_ai": {
            "vix": tai.get("vix"),
            "breadth": tai.get("breadth"),
            "go_count": tai.get("goCount", tai.get("go_count", 0)),
            "wait_count": tai.get("waitCount", tai.get("wait_count", 0)),
            "no_go_count": tai.get("noGoCount", tai.get("no_go_count", 0)),
            "run_date": tai.get("runDate", tai.get("date", "")),
            "run_label": tai.get("runLabel", tai.get("run_label", "")),
        },
        "journal": {
            "trade_count": len(j_all),
            "total_pnl": round(j_total_pnl, 2),
            "win_rate": round(j_win_rate, 1),
            "source": "journal",
        },
        "news_count": len(news.get("catalysts", [])),
        "notification_count": (notif_rows or {}).get("cnt", 0),
        "pending_approvals": (pending_rows or {}).get("cnt", 0),
        "pipeline_status": fresh.get("status", "unknown"),
        "pipeline_completed": fresh.get("completed_at", ""),
        # Sprint 4A additions
        "total_cash": totals.get("total_cash", 0),
        "weighted_beta": _weighted_beta(active_positions),
        "concentration_alerts": [{"symbol": p.get("symbol"), "pct": p.get("portfolio_pct", 0)}
                                  for p in active_positions if (p.get("portfolio_pct") or 0) > 20],
        "pending_pipeline": h.get("pending_pipeline_run", False),
        "last_repriced": h.get("last_repriced", ""),
        "index_tape": {
            "spy": tai.get("spy"), "qqq": tai.get("qqq"), "iwm": tai.get("iwm"),
        },
        "delta_events": tai.get("delta_events", 0),
    }


def portfolio_holdings():
    h = _load_json(STATE_DIR / "holdings.json") or {}
    ec = _load_json(STATE_DIR / "ticker_enrichment_cache.json") or {}
    ts = _load_json(STATE_DIR / "technical_snapshot.json") or {}
    holdings = h.get("holdings", [])

    # Load cost basis from DB for gain/loss calculation
    basis_map = {}
    basis_rows = _db_query("SELECT symbol, account_key, total_cost_basis FROM cost_basis_anchors") or []
    for br in (basis_rows or []):
        basis_map[(br.get("symbol",""), br.get("account_key",""))] = float(br.get("total_cost_basis", 0))

    # Load signals and dividend data for enrichment
    signals_data = _load_json(STATE_DIR / "action_signals.json") or {}
    sig_list = signals_data.get("signals", [])
    sig_map = {}
    if isinstance(sig_list, list):
        for s in sig_list:
            sig_map[s.get("symbol", "")] = s.get("signal", "")
    div_data = _load_json(STATE_DIR / "dividend_calendar.json") or {}
    div_map = {}
    for dp in div_data.get("payers", []):
        sym = dp.get("symbol", "")
        if sym not in div_map:
            div_map[sym] = dp.get("yield_pct", 0)

    # Load LLM health data from watchlist_items
    llm_health_map = {}
    llm_rows = _db_query("""
        SELECT symbol, holdings_llm_health, holdings_llm_action,
               holdings_llm_confidence, holdings_llm_summary, holdings_llm_at
        FROM watchlist_items
        WHERE source = 'portfolio' AND holdings_llm_health IS NOT NULL
    """) or []
    for lr in llm_rows:
        llm_health_map[lr['symbol']] = lr

    rows = []
    for p in holdings:
        if (p.get("market_value") or 0) < 50 and not p.get("is_cash"):
            continue
        sym = p.get("symbol", "")
        e_cache = ec.get(sym, {}) if isinstance(ec.get(sym), dict) else {}
        t_snap = ts.get(sym, {}) if isinstance(ts.get(sym), dict) else {}
        # Merge: enrichment cache wins, technical snapshot fills gaps
        def _pick(*sources, key):
            for src in sources:
                v = src.get(key)
                if v is not None:
                    return v
            return None
        merged_rsi = _pick(e_cache, t_snap, key="rsi")
        merged_beta = _pick(e_cache, t_snap, key="beta")
        merged_sma20 = _pick(e_cache, t_snap, key="sma20_pct")
        merged_sma50 = _pick(e_cache, t_snap, key="sma50_pct")
        merged_sma200 = _pick(e_cache, t_snap, key="sma200_pct")
        merged_atr = _pick(e_cache, t_snap, key="atr")
        # For pi_score, build a merged dict with all needed fields
        pi_input = {**t_snap, **{k: v for k, v in e_cache.items() if v is not None}}
        # Map technical snapshot field names to pi_score expected names
        if "pct_from_high" in t_snap and "week52_high_pct" not in pi_input:
            pi_input["week52_high_pct"] = t_snap["pct_from_high"]
        if "pct_from_low" in t_snap and "week52_low_pct" not in pi_input:
            pi_input["week52_low_pct"] = t_snap["pct_from_low"]
        rows.append({
            "symbol": sym,
            "name": (p.get("name") or "")[:40],
            "account": p.get("account", ""),
            "shares": p.get("shares", 0),
            "price": p.get("price", 0),
            "market_value": p.get("market_value", 0),
            "portfolio_pct": p.get("portfolio_pct", 0),
            "day_change": p.get("day_change", 0),
            "day_change_pct": p.get("day_change_pct", 0),
            "sector": e_cache.get("sector") or t_snap.get("sector") or p.get("sector_type", ""),
            "signal": sig_map.get(sym, "") or t_snap.get("tech_grade", ""),
            "yield_pct": div_map.get(sym),
            "rsi": merged_rsi,
            "beta": merged_beta,
            "pe": e_cache.get("pe"),
            "forward_pe": e_cache.get("forward_pe"),
            "eps_ttm": e_cache.get("eps_ttm"),
            "sma20_pct": merged_sma20,
            "sma50_pct": merged_sma50,
            "sma200_pct": merged_sma200,
            "atr": merged_atr,
            "short_float_pct": e_cache.get("short_float_pct"),
            "week52_high_pct": e_cache.get("week52_high_pct") or t_snap.get("pct_from_high"),
            "market_cap_b": e_cache.get("market_cap_b"),
            "company": e_cache.get("company") or t_snap.get("company", ""),
            "industry": e_cache.get("industry", ""),
            "cost_basis": basis_map.get((sym, p.get("account", "")), p.get("cost_basis")),
            "gain_loss": round(p.get("market_value", 0) - basis_map.get((sym, p.get("account", "")), p.get("cost_basis") or p.get("market_value", 0)), 2),
            "pi_score": _pi_score(pi_input) if (e_cache or t_snap) else None,
            "is_cash": bool(p.get("is_cash")),
            # LLM health assessment
            "llm_health": (llm_health_map.get(sym) or {}).get('holdings_llm_health'),
            "llm_action": (llm_health_map.get(sym) or {}).get('holdings_llm_action'),
            "llm_confidence": (llm_health_map.get(sym) or {}).get('holdings_llm_confidence'),
            "llm_summary": _json_clean((llm_health_map.get(sym) or {}).get('holdings_llm_summary')),
            "llm_at": _json_clean((llm_health_map.get(sym) or {}).get('holdings_llm_at')),
        })
    rows.sort(key=lambda r: -r["market_value"])

    # Equity curve from snapshot_index
    snap_idx = _load_json(STATE_DIR / "snapshot_index.json") or []
    equity_curve = []
    for s in snap_idx[-30:]:
        total = sum(v for k, v in s.items() if k != "date" and isinstance(v, (int, float)))
        if total > 0:
            equity_curve.append({"date": s["date"], "value": round(total, 0)})

    return {"count": len(rows), "holdings": rows, "as_of": h.get("as_of", ""), "equity_curve": equity_curve}


def portfolio_performance():
    perf = _load_json(STATE_DIR / "performance_history.json") or {}
    periods = perf.get("periods", {})
    accounts = perf.get("accounts", {})
    repriced_list = perf.get("reconstructed", [])

    result = {"current_value": perf.get("current_value", 0), "periods": {}, "accounts": {},
              "snapshot_count": perf.get("snapshot_count", 0),
              "warning": "Periods marked 'estimated' use repriced current holdings at historical prices. After position changes (buys/sells), these may be inaccurate." if repriced_list else None}
    for k, v in periods.items():
        if isinstance(v, dict):
            is_repriced = v.get("source") == "repriced"
            result["periods"][k] = {"change_pct": v.get("change_pct"), "change": v.get("change"),
                                     "start_value": v.get("start_value"), "start_date": v.get("start_date"),
                                     "source": v.get("source", "unknown"),
                                     "estimated": is_repriced}
    for acct, data in accounts.items():
        ap = {}
        for k, v in (data.get("periods") or {}).items():
            if isinstance(v, dict):
                ap[k] = {"change_pct": v.get("change_pct"), "change": v.get("change")}
        result["accounts"][acct] = {"current_value": data.get("current_value", 0), "periods": ap}
    return result


def research_ticker(symbol: str):
    ec = _load_json(STATE_DIR / "ticker_enrichment_cache.json") or {}
    news = _load_json(STATE_DIR / "portfolio_news.json") or {}

    enrich = ec.get(symbol.upper(), {}) if isinstance(ec.get(symbol.upper()), dict) else {}
    if not enrich:
        return {"found": False, "symbol": symbol}

    articles = [a for a in (news.get("all_scored") or news.get("catalysts") or [])
                if a.get("portfolio_symbol") == symbol.upper()]

    return {
        "found": True,
        "symbol": symbol.upper(),
        "company": enrich.get("company", ""),
        "sector": enrich.get("sector", ""),
        "industry": enrich.get("industry", ""),
        "technicals": {
            "rsi": enrich.get("rsi"), "beta": enrich.get("beta"), "atr": enrich.get("atr"),
            "rvol": enrich.get("rvol"),
            "sma20_pct": enrich.get("sma20_pct"), "sma50_pct": enrich.get("sma50_pct"),
            "sma200_pct": enrich.get("sma200_pct"),
            "week52_high_pct": enrich.get("week52_high_pct"), "week52_low_pct": enrich.get("week52_low_pct"),
            "volatility_w_pct": enrich.get("volatility_w_pct"),
        },
        "fundamentals": {
            "pe": enrich.get("pe"), "forward_pe": enrich.get("forward_pe"),
            "eps_ttm": enrich.get("eps_ttm"), "peg": enrich.get("peg"),
            "market_cap_b": enrich.get("market_cap_b"),
            "short_float_pct": enrich.get("short_float_pct"),
        },
        "performance": {
            "week": enrich.get("perf_week_pct"), "month": enrich.get("perf_month_pct"),
            "quarter": enrich.get("perf_quarter_pct"), "half_year": enrich.get("perf_halfyr_pct"),
            "ytd": enrich.get("perf_ytd_pct"), "year": enrich.get("perf_year_pct"),
        },
        "articles": [{"title": a.get("title", ""), "source": a.get("source", ""),
                       "llm_score": a.get("llm_score", 0), "published_at": a.get("published_at", ""),
                       "llm_category": a.get("llm_category", "")}
                      for a in articles[:12]],
    }


def _compute_rsi(closes: list, period: int = 14) -> float | None:
    """Compute RSI from a list of closing prices."""
    if not closes or len(closes) < period + 1:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes)) if closes[i] is not None and closes[i - 1] is not None]
    if len(changes) < period:
        return None
    gains = [max(c, 0) for c in changes[-period:]]
    losses = [max(-c, 0) for c in changes[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def _fetch_yahoo_quote(symbol: str) -> dict:
    """Fetch from Yahoo Finance v8 chart. Returns price, company, RSI, 52wk data."""
    try:
        import requests
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1mo&interval=1d"
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return {}
        data = resp.json()
        result = data.get("chart", {}).get("result", [{}])[0]
        meta = result.get("meta", {})
        # Extract close prices for RSI
        closes = []
        try:
            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            closes = [c for c in closes if c is not None]
        except Exception:
            pass
        rsi = _compute_rsi(closes)
        price = meta.get("regularMarketPrice")
        high52 = meta.get("fiftyTwoWeekHigh")
        low52 = meta.get("fiftyTwoWeekLow")
        pct_from_high = round(((price - high52) / high52) * 100, 1) if price and high52 else None
        return {
            "price": price,
            "company": meta.get("shortName") or meta.get("longName", ""),
            "exchange": meta.get("exchangeName", ""),
            "rsi": rsi,
            "week52_high": high52,
            "week52_low": low52,
            "pct_from_52wk_high": pct_from_high,
        }
    except Exception:
        return {}


def watchlist_combined():
    """Return all watchlist sources in one normalized list."""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    wl_json = _load_json(STATE_DIR / "watchlist.json") or {}
    ec = _load_json(STATE_DIR / "ticker_enrichment_cache.json") or {}
    ts = _load_json(STATE_DIR / "technical_snapshot.json") or {}
    # Build holdings lookup for company names and sectors
    h = _load_json(STATE_DIR / "holdings.json") or {}
    holdings_map = {}
    for pos in h.get("holdings", []):
        s = pos.get("symbol", "")
        if s and s not in holdings_map:
            holdings_map[s] = pos

    def _enrich(sym):
        """Merge enrichment from multiple sources: enrichment cache, technical snapshot, holdings, Yahoo."""
        e = ec.get(sym, {}) if isinstance(ec.get(sym), dict) else {}
        t = ts.get(sym, {}) if isinstance(ts.get(sym), dict) else {}
        hp = holdings_map.get(sym, {})
        company = e.get("company") or t.get("company") or hp.get("name", "")
        yq = {}
        if not company and not e and not t and not hp:
            yq = _fetch_yahoo_quote(sym)
        rsi = e.get("rsi") or t.get("rsi") or yq.get("rsi")
        rsi_signal = None
        if rsi is not None:
            rsi = float(rsi)
            rsi_signal = "oversold" if rsi < 30 else ("overbought" if rsi > 70 else ("bullish" if rsi > 50 else "neutral"))
        price = hp.get("price") or t.get("price") or yq.get("price")
        sma200 = t.get("sma200_pct")
        high52 = e.get("52w_high") or t.get("52w_high")
        pct_from_high = None
        if price and high52:
            try:
                pct_from_high = round((float(price) - float(high52)) / float(high52) * 100, 1)
            except Exception:
                pass
        return {
            "company": company or yq.get("company", ""),
            "sector": e.get("sector") or t.get("sector") or hp.get("sector", ""),
            "rsi": rsi,
            "rsi_signal": rsi_signal,
            "perf_week_pct": e.get("perf_week_pct") or t.get("perf_week_pct") or t.get("perf_week"),
            "perf_month_pct": e.get("perf_month_pct") or t.get("perf_month_pct") or t.get("perf_month"),
            "beta": t.get("beta") or hp.get("beta"),
            "market_cap_b": e.get("market_cap_b"),
            "current_price": price,
            "sma200_pct": sma200,
            "pct_from_52wk_high": pct_from_high or (yq.get("pct_from_52wk_high") if yq else None),
            "data_source": "yahoo" if yq.get("company") else ("enrichment_cache" if e else "technical_snapshot" if t else "holdings" if hp else "metadata_only"),
        }

    items = []
    for sym, meta in wl_json.items():
        enriched = _enrich(sym)
        items.append({"symbol": sym, "source": "user", "status": "active",
                       "company": enriched["company"], "sector": enriched["sector"],
                       "rsi": enriched["rsi"], "rsi_signal": enriched.get("rsi_signal"),
                       "perf_week_pct": enriched["perf_week_pct"],
                       "perf_month_pct": enriched.get("perf_month_pct"),
                       "beta": enriched["beta"], "market_cap_b": enriched["market_cap_b"],
                       "current_price": enriched.get("current_price"),
                       "sma200_pct": enriched.get("sma200_pct"),
                       "pct_from_52wk_high": enriched.get("pct_from_52wk_high"),
                       "notes": meta.get("notes") if isinstance(meta, dict) else None,
                       "intent": meta.get("target_intent") or meta.get("intent") if isinstance(meta, dict) else None,
                       "thesis": meta.get("thesis") if isinstance(meta, dict) else None,
                       "added": meta.get("added") if isinstance(meta, dict) else None,
                       "watching_since": meta.get("watching_since") if isinstance(meta, dict) else None})

    try:
        from db_adapter import load_watchlist_items
        for st in ("analyst_curated", "ai_generated"):
            for r in load_watchlist_items(source_type=st, status="active"):
                sym = r.get("symbol", "")
                enriched = _enrich(sym)
                items.append({"symbol": sym, "source": st, "status": r.get("status", "active"),
                               "company": enriched["company"], "sector": enriched["sector"],
                               "rsi": enriched["rsi"], "perf_week_pct": enriched["perf_week_pct"],
                               "beta": enriched["beta"], "market_cap_b": enriched["market_cap_b"],
                               "confidence": float(r["confidence"]) if r.get("confidence") else None,
                               "expires_at": str(r.get("data", {}).get("expires_at", "")) if r.get("data") else None,
                               "upside_pct": r.get("data", {}).get("upside_pct") if r.get("data") else None})
    except Exception:
        pass

    # ── Enrich all watchlist items with LLM intelligence + social + news ──
    all_syms = [i["symbol"] for i in items]
    llm_map = {}
    news_map = {}
    social_map = {}
    scan_map = {}

    if all_syms:
        # LLM health from holdings
        try:
            llm_rows = _db_query("""
                SELECT symbol, holdings_llm_health, holdings_llm_action, holdings_llm_confidence
                FROM watchlist_items WHERE symbol = ANY(%s) AND holdings_llm_health IS NOT NULL
            """, (all_syms,)) or []
            for r in llm_rows:
                llm_map[r["symbol"]] = {
                    "llm_health": r.get("holdings_llm_health"),
                    "llm_action": r.get("holdings_llm_action"),
                    "llm_confidence": _json_clean(r.get("holdings_llm_confidence")),
                }
        except Exception:
            pass

        # Recent news count per symbol
        try:
            news_rows = _db_query("""
                SELECT symbol, COUNT(*) as news_count,
                       MAX(quality_score) as top_score
                FROM news_articles WHERE symbol = ANY(%s)
                AND created_at > NOW() - INTERVAL '7 days'
                GROUP BY symbol
            """, (all_syms,)) or []
            for r in news_rows:
                news_map[r["symbol"]] = {
                    "news_7d": r.get("news_count", 0),
                    "news_top_score": r.get("top_score"),
                }
        except Exception:
            pass

        # Social sentiment
        try:
            social_rows = _db_query("""
                SELECT DISTINCT ON (symbol)
                    symbol, mention_count, sentiment_score
                FROM social_sentiment_history
                WHERE symbol = ANY(%s) AND observed_at > NOW() - INTERVAL '7 days'
                ORDER BY symbol, observed_at DESC
            """, (all_syms,)) or []
            for r in social_rows:
                social_map[r["symbol"]] = {
                    "social_mentions": r.get("mention_count", 0),
                    "social_sentiment": _json_clean(r.get("sentiment_score")),
                }
        except Exception:
            pass

        # Latest scan data (score, decision)
        try:
            scan_rows = _db_query("""
                SELECT DISTINCT ON (symbol) symbol, score, decision, catalyst,
                       social_stocktwits, social_sentiment, scanned_at
                FROM trade_ai_scans WHERE symbol = ANY(%s)
                ORDER BY symbol, scanned_at DESC
            """, (all_syms,)) or []
            for r in scan_rows:
                scan_map[r["symbol"]] = {
                    "scan_score": r.get("score"),
                    "scan_decision": r.get("decision"),
                    "catalyst": r.get("catalyst"),
                    "stocktwits_posts": r.get("social_stocktwits", 0),
                    "scan_sentiment": r.get("social_sentiment"),
                }
        except Exception:
            pass

    # Merge enrichment into items + compute conviction rating
    for item in items:
        sym = item["symbol"]
        if sym in llm_map:
            item.update(llm_map[sym])
        if sym in news_map:
            item.update(news_map[sym])
        if sym in social_map:
            item.update(social_map[sym])
        if sym in scan_map:
            item.update(scan_map[sym])

        # ── Conviction rating: 0-100 based on available intelligence ──
        conviction = 0
        signals = []
        if item.get("scan_score") and int(item["scan_score"]) >= 40:
            conviction += 25
            signals.append("high_score")
        if item.get("scan_decision") == "GO":
            conviction += 15
            signals.append("GO_decision")
        if item.get("llm_health") in ("strong", "healthy"):
            conviction += 15
            signals.append("llm_healthy")
        if item.get("news_7d") and int(item["news_7d"]) > 3:
            conviction += 10
            signals.append("active_news")
        if item.get("social_mentions") and int(item["social_mentions"]) > 5:
            conviction += 10
            signals.append("social_active")
        if item.get("catalyst"):
            conviction += 10
            signals.append("catalyst_present")
        rsi = item.get("rsi")
        if rsi and 30 < float(rsi) < 60:
            conviction += 10
            signals.append("rsi_favorable")
        if item.get("thesis"):
            conviction += 5
            signals.append("thesis_defined")
        item["conviction_score"] = min(conviction, 100)
        item["conviction_signals"] = signals

        # ── Alert flag for RSI extremes ──
        if item.get("rsi_signal") in ("oversold", "overbought"):
            item["alert"] = f"RSI {item.get('rsi_signal').upper()}: {item.get('rsi'):.0f}" if rsi else None

    return {"count": len(items), "items": items}


def notifications_recent():
    # Try with full body column first, fall back without it
    rows = _db_query(
        """SELECT notification_date, notification_type, channel, status, subject,
                  body_summary, body, sent_at::text, dedupe_key
           FROM notification_log ORDER BY created_at DESC LIMIT 30""",
        fetch="all"
    )
    if rows is None:
        # body column may not exist — fall back
        rows = _db_query(
            """SELECT notification_date, notification_type, channel, status, subject,
                      body_summary, sent_at::text, dedupe_key
               FROM notification_log ORDER BY created_at DESC LIMIT 30""",
            fetch="all"
        ) or []
    return {"count": len(rows), "notifications": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}


def _expire_stale_approvals():
    """Auto-transition expired pending items."""
    try:
        _db_write(
            """UPDATE action_queue SET status = 'expired', reviewed_at = NOW(), reviewed_by = 'system'
               WHERE status = 'pending' AND expires_at IS NOT NULL AND expires_at < CURRENT_DATE"""
        )
        # Also check linked recommendations
        _db_write(
            """UPDATE action_queue aq SET status = 'expired', reviewed_at = NOW(), reviewed_by = 'system'
               FROM advisor_recommendations ar
               WHERE aq.recommendation_id = ar.id AND aq.status = 'pending'
               AND ar.expires_at IS NOT NULL AND ar.expires_at < CURRENT_DATE"""
        )
    except Exception:
        pass


def approvals_pending():
    _expire_stale_approvals()
    rows = _db_query(
        """SELECT aq.id, aq.recommendation_id, aq.symbol, aq.action, aq.rationale, aq.confidence,
                  aq.urgency, aq.status, aq.expires_at, aq.dedupe_key, aq.created_at,
                  ar.recommendation_date as rec_date, ar.symbol as rec_symbol, ar.action as rec_action,
                  ar.rationale as rec_rationale, ar.confidence as rec_confidence, ar.model as rec_model,
                  ar.evidence_summary as rec_evidence, ar.expires_at as rec_expires
           FROM action_queue aq
           LEFT JOIN advisor_recommendations ar ON aq.recommendation_id = ar.id
           WHERE aq.status = 'pending'
           ORDER BY aq.urgency = 'urgent' DESC, aq.confidence DESC""",
        fetch="all"
    ) or []
    # Merge and clean
    items = []
    for r in rows:
        item = {k: _json_clean(v) for k, v in r.items()}
        # Parse evidence_summary JSONB
        ev = r.get("rec_evidence") or {}
        if isinstance(ev, str):
            try:
                ev = json.loads(ev)
            except Exception:
                ev = {}
        item["evidence"] = ev
        item["rec_symbol"] = r.get("rec_symbol") or r.get("symbol") or ""
        items.append(item)

    # Build live price map + account map from holdings + technical snapshot
    _h = _load_json(STATE_DIR / "holdings.json") or {}
    _ts = _load_json(STATE_DIR / "technical_snapshot.json") or {}
    price_map = {}  # sym -> {price, rsi, sma50_pct, sma200_pct, beta, market_value, ...}
    acct_map = {}   # sym -> account
    for pos in _h.get("holdings", []):
        s = pos.get("symbol", "")
        if s and s not in price_map:
            price_map[s] = {"price": pos.get("price", 0), "market_value": pos.get("market_value", 0), "shares": pos.get("shares", 0), "name": pos.get("name", "")}
        if s and s not in acct_map:
            acct_map[s] = pos.get("account", "")
    for s, td in _ts.items():
        if isinstance(td, dict):
            existing = price_map.get(s, {})
            existing["rsi"] = td.get("rsi")
            existing["sma50_pct"] = td.get("sma50_pct")
            existing["sma200_pct"] = td.get("sma200_pct")
            existing["beta"] = td.get("beta")
            existing["tech_grade"] = td.get("tech_grade")
            if td.get("price") and not existing.get("price"):
                existing["price"] = td["price"]
            price_map[s] = existing

    # Build risk context from risk_management.json merged with live prices
    risk_ctx = {}
    try:
        rm = _load_json(STATE_DIR / "risk_management.json") or {}
        for p in rm.get("positions", []):
            sym = p.get("symbol", "")
            live = price_map.get(sym, {})
            current_price = p.get("current_price") or live.get("price", 0)
            stop_price = p.get("stop_price")
            distance_pct = p.get("distance_pct")
            if distance_pct is None and stop_price and current_price:
                distance_pct = round(((current_price - stop_price) / stop_price) * 100, 1) if stop_price > 0 else None
            shares = live.get("shares", 0) or p.get("shares", 0)
            max_loss = p.get("max_loss", 0)
            if max_loss == 0 and stop_price and current_price and shares:
                max_loss = round((current_price - stop_price) * shares, 2) if current_price > stop_price else 0
            # P&L if stopped out: (stop_price - current_price) * shares (negative = loss)
            pnl_if_stopped = round((stop_price - current_price) * shares, 2) if stop_price and current_price and shares else None
            total_cost_at_current = round(current_price * shares, 2) if current_price and shares else None
            risk_ctx[sym] = {
                "current_price": current_price,
                "stop_price": stop_price,
                "distance_pct": distance_pct,
                "max_loss": max_loss,
                "shares": shares,
                "total_position_value": total_cost_at_current,
                "pnl_if_stopped": pnl_if_stopped,
                "market_value": live.get("market_value") or p.get("market_value", 0),
                "triggered": p.get("triggered") or (p.get("status") == "TRIGGERED"),
                "status": p.get("status", ""),
                "rsi": live.get("rsi"),
                "sma200_pct": live.get("sma200_pct"),
                "beta": live.get("beta"),
                "name": live.get("name", ""),
            }
    except Exception:
        pass

    # Attach context to approval items
    triggered_positions = [v | {"symbol": k} for k, v in risk_ctx.items() if v.get("triggered") or v.get("status") == "TRIGGERED"]
    danger_positions = [v | {"symbol": k} for k, v in risk_ctx.items() if v.get("status") == "DANGER"]
    warning_positions = [v | {"symbol": k} for k, v in risk_ctx.items() if v.get("status") == "WARNING"]
    for item in items:
        if item.get("action") == "STOP_REVIEW":
            item["risk_context"] = {
                "triggered": triggered_positions,
                "danger": danger_positions,
                "warning": warning_positions[:3],
                "total_positions": len(risk_ctx),
                "total_with_stops": len([v for v in risk_ctx.values() if v.get("stop_price")]),
            }
        elif item.get("action") == "ALLOCATION_REVIEW" and item.get("rec_symbol"):
            sym = item["rec_symbol"]
            pos_data = risk_ctx.get(sym) or {}
            pos_data.update({"symbol": sym})
            # Also add holdings-level detail
            h_data = price_map.get(sym, {})
            pos_data["rsi"] = pos_data.get("rsi") or h_data.get("rsi")
            pos_data["name"] = pos_data.get("name") or h_data.get("name", "")
            item["risk_context"] = {"position": pos_data}

    # Enrich each item with account from holdings
    for item in items:
        sym = item.get("symbol") or item.get("rec_symbol") or ""
        if sym and not item.get("account"):
            item["account"] = acct_map.get(sym, "")

    # Generate human-readable decision summaries
    for item in items:
        item["decision_summary"] = _build_decision_summary(item, risk_ctx)

    return {"count": len(items), "pending": items}


def _build_decision_summary(item: dict, risk_ctx: dict) -> dict:
    """Build a human-readable decision summary for an approval item."""
    action = item.get("action", "")
    sym = item.get("rec_symbol") or item.get("symbol") or ""
    ev = item.get("evidence", {})
    rc = item.get("risk_context", {})

    # What is being decided
    what = f"Review {action.replace('_', ' ').lower()}"
    if sym:
        what += f" for {sym}"

    # Why it matters
    why_parts = []
    if ev.get("severity"):
        why_parts.append(f"Severity {ev['severity']}")
    if ev.get("escalation_summary"):
        why_parts.append(ev["escalation_summary"])
    why = ". ".join(why_parts) if why_parts else item.get("rationale", "")[:120]

    # Risk being accepted
    risk_parts = []
    if action == "STOP_REVIEW":
        triggered = rc.get("triggered", [])
        for t in triggered:
            if t.get("current_price") and t.get("stop_price"):
                risk_parts.append(f"{t['symbol']} at ${t['current_price']:.2f} vs stop ${t['stop_price']:.2f} ({t.get('distance_pct', 0):.1f}%)")
        if not triggered:
            risk_parts.append("Prior trigger may have resolved — verify stop levels are current")
    elif action == "ALLOCATION_REVIEW":
        pos = rc.get("position", {})
        if pos.get("market_value"):
            risk_parts.append(f"{sym} position ${pos['market_value']:,.0f}")

    # Recommended follow-up
    if action == "STOP_REVIEW":
        followup = "After approval: verify stop levels in broker platform. After rejection: item will re-escalate on next pipeline run."
    elif action == "ALLOCATION_REVIEW":
        followup = "After approval: concentration accepted, continue monitoring. After rejection: consider trim via Rebalance."
    else:
        followup = "After decision: review audit trail in Notifications."

    # Exposure summary
    exposure_parts = []
    if action == "STOP_REVIEW":
        total_mv = sum(t.get("market_value", 0) for t in rc.get("triggered", []))
        total_loss = sum(t.get("max_loss", 0) for t in rc.get("triggered", []))
        accounts = list(set(t.get("account", "") for t in rc.get("triggered", []) if t.get("account")))
        if total_mv > 0:
            exposure_parts.append(f"Total exposure: ${total_mv:,.0f}")
        if total_loss != 0:
            exposure_parts.append(f"Max loss if stopped: ${abs(total_loss):,.0f}")
        if accounts:
            exposure_parts.append(f"Account{'s' if len(accounts) > 1 else ''}: {', '.join(a.replace('schwab_','') for a in accounts)}")
    elif action == "ALLOCATION_REVIEW":
        pos = rc.get("position", {})
        if pos.get("market_value"):
            exposure_parts.append(f"Position: ${pos['market_value']:,.0f}")
        if pos.get("stop_price"):
            exposure_parts.append(f"Stop: ${pos['stop_price']:.2f}")

    # Recommended next action
    next_action = "Review evidence and decide"
    if action == "STOP_REVIEW":
        triggered = rc.get("triggered", [])
        danger = rc.get("danger", [])
        if triggered:
            next_action = f"1. Verify {', '.join(t['symbol'] for t in triggered[:3])} stop levels in broker. 2. Check Risk page for danger positions. 3. Approve or escalate."
        else:
            next_action = "1. Confirm stops are current. 2. Check Risk page. 3. Approve."
        # Add correlated risk note
        if danger:
            risk_parts.append(f"Additionally {len(danger)} position(s) in danger zone: {', '.join(d['symbol'] for d in danger[:3])}")
    elif action == "ALLOCATION_REVIEW":
        next_action = f"1. Check {sym} in Rebalance page. 2. Review concentration vs target. 3. Decide: trim, accept, or defer."

    # Portfolio heat context
    total_heat = sum(r.get("max_loss", 0) for r in risk_ctx.values() if isinstance(r, dict))
    heat_note = ""
    if total_heat > 0:
        total_mv = sum(r.get("market_value", 0) for r in risk_ctx.values() if isinstance(r, dict))
        if total_mv > 0:
            heat_note = f"Portfolio heat: {total_heat/total_mv*100:.1f}% risk-to-value"

    return {
        "what": what,
        "why": why,
        "risk": ". ".join(risk_parts) if risk_parts else "No specific risk detail available",
        "exposure": ". ".join(exposure_parts) if exposure_parts else None,
        "next_action": next_action,
        "followup": followup,
        "positions_affected": len(rc.get("triggered", [])) + len(rc.get("danger", [])),
        "total_monitored": rc.get("total_positions", 0),
        "heat_note": heat_note,
    }



def approvals_all_states():
    """GET /api/v2/approvals/states — show all items across all states."""
    _expire_stale_approvals()
    rows = _db_query(
        """SELECT aq.id, aq.symbol, aq.action, aq.rationale, aq.confidence, aq.urgency,
                  aq.status, aq.created_at, aq.reviewed_at, aq.reviewed_by,
                  al.decision, al.notes as decision_notes, al.decided_at
           FROM action_queue aq
           LEFT JOIN approval_log al ON al.action_queue_id = aq.id
           ORDER BY aq.created_at DESC LIMIT 20""",
        fetch="all"
    ) or []
    # Group by status
    by_status = {"pending": [], "approved": [], "rejected": [], "expired": []}
    for r in rows:
        item = {k: _json_clean(v) for k, v in r.items()}
        status = item.get("status", "pending")
        by_status.setdefault(status, []).append(item)
    return {
        "total": len(rows),
        "by_status": {k: len(v) for k, v in by_status.items()},
        "items": [{k: _json_clean(v) for k, v in r.items()} for r in rows],
    }


def approvals_history():
    """GET /api/v2/approvals/history — recent decisions."""
    rows = _db_query(
        """SELECT al.id, al.action_queue_id, al.decision, al.decision_reason, al.decided_by,
                  al.decided_at, al.notes, aq.symbol, aq.action, aq.rationale, aq.confidence
           FROM approval_log al
           LEFT JOIN action_queue aq ON al.action_queue_id = aq.id
           ORDER BY al.decided_at DESC LIMIT 20""",
        fetch="all"
    ) or []
    return {"count": len(rows), "decisions": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}


def approval_decide(body: dict):
    """POST /api/v2/approvals/decision — approve or reject a pending item."""
    queue_id = body.get("queue_id")
    decision = body.get("decision", "").lower()
    note = body.get("note", "").strip()

    if not queue_id:
        return 400, {"ok": False, "error": "queue_id required"}
    if decision not in ("approved", "rejected", "deferred"):
        return 400, {"ok": False, "error": "decision must be 'approved', 'rejected', or 'deferred'"}
    if not note:
        return 400, {"ok": False, "error": "note/rationale required for all decisions"}

    # Verify item exists and is pending
    item = _db_query("SELECT id, status FROM action_queue WHERE id = %s", (queue_id,), fetch="one")
    if not item:
        return 404, {"ok": False, "error": f"queue item {queue_id} not found"}
    if item.get("status") != "pending":
        return 409, {"ok": False, "error": f"item already {item.get('status')}"}

    # Update action_queue status
    _db_write(
        "UPDATE action_queue SET status = %s, reviewed_at = NOW(), reviewed_by = 'john' WHERE id = %s",
        (decision, queue_id)
    )

    # Write to approval_log
    _db_write(
        """INSERT INTO approval_log (action_queue_id, decision, decision_reason, decided_by, notes)
           VALUES (%s, %s, %s, 'john', %s)""",
        (queue_id, decision, note, note)
    )

    # Get symbol from the queue item for feedback loop
    q_item = _db_query("SELECT aq.symbol, aq.action, ar.symbol as rec_symbol FROM action_queue aq LEFT JOIN advisor_recommendations ar ON aq.recommendation_id=ar.id WHERE aq.id=%s", (queue_id,), fetch="one") or {}
    sym = q_item.get("symbol") or q_item.get("rec_symbol") or ""

    # Write to agent_feedback_log (trains agents on John's decisions)
    if sym and note:
        try:
            _db_write(
                """INSERT INTO agent_feedback_log (symbol, decision, reason, john_decision, john_note, created_at)
                   VALUES (%s, %s, %s, %s, %s, NOW())""",
                (sym, decision, note, decision, note)
            )
        except Exception:
            pass

    # Generate immediate john_preferences lesson (agents read this)
    if sym and note:
        try:
            lesson_type = "human_override" if decision == "rejected" else "human_approved"
            lesson = f"{sym}: John {'REJECTED' if decision == 'rejected' else 'APPROVED'} — {note[:100]}"
            _db_write(
                """INSERT INTO agent_intelligence_rules (rule_type, rule_key, config, changed_by, updated_at)
                   VALUES ('john_preferences', %s, %s, 'john', NOW())
                   ON CONFLICT (rule_type, rule_key) DO UPDATE SET config=EXCLUDED.config, updated_at=NOW()""",
                (f"{sym}_{datetime.now().strftime('%Y%m%d')}", json.dumps({
                    "lesson": lesson, "symbol": sym, "decision": decision,
                    "note": note, "type": lesson_type,
                }))
            )
        except Exception:
            pass

    # ── On approval: run strategy criteria validation + live price check ──
    if decision == "approved" and sym:
        validation_result = None
        try:
            # Find the paper_trade_proposal for this symbol
            p_row = _db_query(
                "SELECT id FROM paper_trade_proposals WHERE symbol = %s AND status IN ('PENDING','APPROVED','APPROVED_FOR_PAPER_TEST') ORDER BY created_at DESC LIMIT 1",
                (sym,), fetch="one"
            )
            if p_row:
                from approval_revalidator import validate_at_approval
                from session13_db import get_conn
                conn = get_conn()
                validation_result = validate_at_approval(conn, p_row['id'])
                conn.close()

                if validation_result.get('status') == 'REJECTED':
                    # Block the approval — revert to pending
                    _db_write("UPDATE action_queue SET status = 'pending', reviewed_at = NULL WHERE id = %s", (queue_id,))
                    return 200, {
                        "ok": True, "action": "blocked",
                        "queue_id": queue_id,
                        "validation": validation_result,
                        "message": f"Trade blocked: {'; '.join(validation_result.get('blockers', []))}"
                    }
        except Exception as _val_err:
            log.warning(f"Approval validation failed (non-fatal): {_val_err}")
            validation_result = {"status": "validation_error", "error": str(_val_err)}

        return 200, {
            "ok": True, "action": decision, "queue_id": queue_id,
            "validation": validation_result
        }

    return 200, {"ok": True, "action": decision, "queue_id": queue_id}


def _orchestration():
    """GET /api/v2/orchestration — system timers, services, skills, scripts."""
    import subprocess

    # Parse systemd timers
    timers = []
    try:
        env = os.environ.copy()
        env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{os.getuid()}/bus")
        out = subprocess.run(["systemctl", "--user", "list-timers", "--no-pager"], capture_output=True, text=True, timeout=5, env=env)
        lines = out.stdout.strip().split("\n")
        for line in lines[1:]:
            # Format: NEXT LEFT LAST PASSED UNIT ACTIVATES
            # Match lines that end with .timer and .service
            if ".timer" not in line:
                continue
            # Find the timer name and activates service
            import re as _re
            m = _re.search(r'(\S+\.timer)\s+(\S+\.service)', line)
            if not m:
                continue
            timer_name = m.group(1)
            activates = m.group(2)
            # Extract NEXT (first 4 date/time fields before LEFT)
            next_run = ""
            date_match = _re.match(r'^(\w+ \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \S+)', line)
            if date_match:
                next_run = date_match.group(1)
            timers.append({"name": timer_name, "activates": activates,
                           "next": next_run, "last": "", "schedule": "", "status": "waiting"})
    except Exception:
        pass

    # Get schedule + last-run from systemd
    import configparser
    timer_dir = Path(os.path.expanduser("~/.config/systemd/user"))
    for t in timers:
        tf = timer_dir / t["name"]
        if tf.exists():
            try:
                cp = configparser.ConfigParser()
                cp.read(str(tf))
                t["schedule"] = cp.get("Timer", "OnCalendar", fallback="")
            except Exception:
                pass
        # Get last-run data from the service
        svc_name = t.get("activates", t["name"].replace(".timer", ".service"))
        try:
            props = subprocess.run(
                ["systemctl", "--user", "show", svc_name,
                 "--property=ExecMainStartTimestamp,ExecMainExitTimestamp,Result,ActiveState"],
                capture_output=True, text=True, timeout=3, env=env
            )
            for line in props.stdout.strip().split("\n"):
                k, _, v = line.partition("=")
                if k == "ExecMainStartTimestamp" and v:
                    t["last_start"] = v.strip()
                elif k == "ExecMainExitTimestamp" and v:
                    t["last_end"] = v.strip()
                elif k == "Result":
                    t["result"] = v.strip()
                elif k == "ActiveState":
                    t["status"] = v.strip() if v.strip() != "inactive" else "waiting"
        except Exception:
            pass

    # Filter to project-relevant timers
    relevant = {"portfolio-daily", "portfolio-weekly", "portfolio-monthly", "portfolio-backup",
                "portfolio-price-cache", "portfolio-lookthrough", "tradeai-continuous",
                "recovery-watch", "mcporter-token-refresh",
                "aegis-overnight", "aegis-surveillance", "trade-ai-news-monitor"}
    timers = [t for t in timers if any(r in t["name"] for r in relevant)]

    # Services
    services = []
    svc_names = ["portfolio-server", "openclaw-gateway"]
    for sn in svc_names:
        try:
            out = subprocess.run(["systemctl", "--user", "is-active", f"{sn}.service"], capture_output=True, text=True, timeout=3, env=env)
            status = out.stdout.strip() or "unknown"
            out2 = subprocess.run(["systemctl", "--user", "show", f"{sn}.service", "--property=Description"], capture_output=True, text=True, timeout=3, env=env)
            desc = out2.stdout.strip().replace("Description=", "")
            services.append({"name": f"{sn}.service", "status": status, "description": desc})
        except Exception:
            pass

    # Skills/agents from filesystem
    skills = []
    oc_base = Path(os.path.expanduser("~/.openclaw"))
    for d in sorted((oc_base / "skills").glob("*/")):
        skills.append({"name": d.name, "path": str(d), "type": "skill"})
    for d in sorted((oc_base / "agents").glob("*/")):
        skills.append({"name": d.name, "path": str(d), "type": "agent"})

    # Automation scripts
    scripts = [
        {"name": "aegis_overnight.py", "purpose": "Aegis — overnight intelligence orchestrator (20:00 primary): collection → synthesis → refinement"},
        {"name": "aegis_surveillance.py", "purpose": "Aegis — morning quick scan (08:00 secondary): stops, concentration, income, heat"},
        {"name": "recovery_watch_daily.py", "purpose": "Recovery watch — stop-out detection, analyst review, escalation, stop confirmation, allocation"},
        {"name": "telegram_reply_processor.py", "purpose": "Poll Telegram for stop-confirmation replies"},
        {"name": "alerting.py", "purpose": "Daily alerting pipeline — observations, recommendations, escalations"},
        {"name": "morning_digest.py", "purpose": "Morning Telegram digest with portfolio summary"},
        {"name": "continuous_runner.py", "purpose": "Trade AI continuous scalp screener"},
        {"name": "portfolio_performance_history.py", "purpose": "Performance returns computation from snapshots"},
        {"name": "finviz_ingestion.py", "purpose": "Finviz screener data ingestion for Trade AI"},
    ]
    # Filter to scripts that actually exist
    scripts = [s for s in scripts if (PROJECT_ROOT / "scripts" / s["name"]).exists()]

    # Environment / dependency readiness checks
    env_checks = []
    def _env_check(name, check_fn, fix_hint=""):
        try:
            ok, detail = check_fn()
            env_checks.append({"name": name, "ok": ok, "detail": detail, "fix": fix_hint if not ok else ""})
        except Exception as e:
            env_checks.append({"name": name, "ok": False, "detail": str(e), "fix": fix_hint})

    _env_check("PostgreSQL", lambda: (bool(_db_query("SELECT 1", fetch="one")), "Connected"), "Check DB_HOST/DB_NAME/DB_USER/DB_PASSWORD in .env")
    _env_check("Telegram Bot", lambda: (bool(os.getenv("TELEGRAM_BOT_TOKEN")), f"Token: ...{os.getenv('TELEGRAM_BOT_TOKEN','')[-8:]}"), "Add TELEGRAM_BOT_TOKEN to .env")
    _env_check("Finviz API", lambda: (bool(os.getenv("FINVIZ_API_TOKEN")), f"Token: ...{os.getenv('FINVIZ_API_TOKEN','')[-8:]}"), "Add FINVIZ_API_TOKEN to .env")
    _env_check("Finnhub API", lambda: (bool(os.getenv("FINNHUB_API_KEY")), "Configured"), "Add FINNHUB_API_KEY to .env")
    _env_check("gcloud CLI", lambda: (Path(os.path.expanduser("~/openclaw-skills-john718/google-cloud-sdk/bin/gcloud")).exists(), "Found"), "Install gcloud SDK")
    _env_check("Holdings data", lambda: ((STATE_DIR / "holdings.json").exists(), f"{(STATE_DIR / 'holdings.json').stat().st_size // 1024}KB"), "Run portfolio pipeline")
    _env_check("Risk data", lambda: ((STATE_DIR / "risk_management.json").exists(), "Present"), "Run portfolio pipeline")

    # Compute overall health
    failed_timers = [t for t in timers if t.get("result") == "exit-code" or t.get("result") == "failed"]
    failed_services = [s for s in services if s.get("status") not in ("active", "waiting", "inactive", "activating", "unknown", "")]
    failed_env = [e for e in env_checks if not e["ok"]]
    health = "healthy" if not failed_timers and not failed_services and not failed_env else "degraded" if len(failed_timers) + len(failed_env) <= 2 else "failing"

    return {"timers": timers, "services": services, "skills": skills, "scripts": scripts,
            "env_checks": env_checks, "health": health,
            "failed_timers": len(failed_timers), "failed_env": len(failed_env)}


def _last_import():
    """GET /api/v2/ops/last-import — return the most recent structured import result."""
    log_path = PROJECT_ROOT / "logs" / "import_audit_structured.jsonl"
    if not log_path.exists():
        return {"has_result": False}
    try:
        lines = log_path.read_text(errors="replace").strip().split("\n")
        if not lines:
            return {"has_result": False}
        last = json.loads(lines[-1])
        return {"has_result": True, "result": last}
    except Exception:
        return {"has_result": False}


def _aegis_nightly_deltas():
    """GET /api/v2/aegis/nightly-deltas — latest nightly symbol snapshots."""
    rows = _db_query(
        """SELECT run_id, symbol, universe_reason, primary_source, sources_used,
                  price, change_pct, rsi, sma200_pct, beta, company, sector,
                  market_cap_b, pct_from_52wk_high, analyst_recom,
                  field_count, confidence, observed_at
           FROM aegis_symbol_snapshot_nightly
           WHERE run_id = (SELECT run_id FROM aegis_symbol_snapshot_nightly ORDER BY observed_at DESC LIMIT 1)
           ORDER BY confidence DESC, symbol""",
        fetch="all"
    ) or []
    items = [{k: _json_clean(v) for k, v in r.items()} for r in rows]
    run_id = items[0].get("run_id") if items else None
    sources = {}
    for r in items:
        for s in (r.get("sources_used") or []):
            sources[s] = sources.get(s, 0) + 1
    return {
        "count": len(items), "run_id": run_id, "symbols": items,
        "source_coverage": sources,
        "last_run": items[0].get("observed_at") if items else None,
    }


def _aegis_briefs():
    """GET /api/v2/aegis/briefs — latest Aegis portfolio briefs."""
    rows = _db_query(
        """SELECT run_id, symbol, brief_type, thesis_status, what_changed, why_it_matters,
                  technical_drift, news_context, social_context, confidence,
                  needs_steph_review, escalation_reason, observed_at
           FROM aegis_portfolio_briefs
           WHERE run_id = (SELECT run_id FROM aegis_portfolio_briefs ORDER BY observed_at DESC LIMIT 1)
           ORDER BY needs_steph_review DESC, confidence DESC""",
        fetch="all"
    ) or []
    items = [{k: _json_clean(v) for k, v in r.items()} for r in rows]
    steph_items = [i for i in items if i.get("needs_steph_review")]
    summary = next((i for i in items if i.get("brief_type") == "summary"), None)
    return {
        "count": len(items), "run_id": items[0].get("run_id") if items else None,
        "briefs": [i for i in items if i.get("brief_type") != "summary"],
        "portfolio_summary": summary,
        "steph_review_count": len(steph_items),
        "last_run": str(items[0].get("observed_at")) if items else None,
    }


def _aegis_covered_calls():
    """GET /api/v2/aegis/covered-calls — latest covered-call candidate proposals."""
    rows = _db_query(
        """SELECT run_id, symbol, account, verdict, reasoning, strike_guidance,
                  time_horizon, risk_note, shares_available, current_price,
                  needs_steph_review, confidence, observed_at
           FROM aegis_covered_call_candidates
           WHERE run_id = (SELECT run_id FROM aegis_covered_call_candidates ORDER BY observed_at DESC LIMIT 1)
           ORDER BY verdict = 'candidate' DESC, confidence DESC""",
        fetch="all"
    ) or []
    items = [{k: _json_clean(v) for k, v in r.items()} for r in rows]
    by_verdict = {}
    for i in items:
        v = i.get("verdict", "?")
        by_verdict[v] = by_verdict.get(v, 0) + 1
    return {
        "count": len(items), "run_id": items[0].get("run_id") if items else None,
        "candidates": items,
        "by_verdict": by_verdict,
        "last_run": str(items[0].get("observed_at")) if items else None,
    }


def _aegis_rotations():
    """GET /api/v2/aegis/rotation-alternatives — capital rotation candidates."""
    rows = _db_query(
        """SELECT run_id, from_symbol, from_reason, to_symbol, to_reason, switch_verdict,
                  evidence, blocker, confidence, needs_steph_review, observed_at
           FROM aegis_rotation_candidates
           WHERE run_id = (SELECT run_id FROM aegis_rotation_candidates ORDER BY observed_at DESC LIMIT 1)
           ORDER BY confidence DESC""",
        fetch="all"
    ) or []
    return {"count": len(rows), "candidates": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}


def _aegis_steph_escalations():
    """GET /api/v2/aegis/steph-escalations — items needing Steph validation."""
    rows = _db_query(
        """SELECT run_id, symbol, category, reason, evidence_summary, unresolved_question, confidence, observed_at
           FROM aegis_steph_escalations
           WHERE run_id = (SELECT run_id FROM aegis_steph_escalations ORDER BY observed_at DESC LIMIT 1)
           ORDER BY confidence DESC""",
        fetch="all"
    ) or []
    categories = {}
    for r in rows:
        c = r.get("category", "other")
        categories[c] = categories.get(c, 0) + 1
    return {"count": len(rows), "escalations": [{k: _json_clean(v) for k, v in r.items()} for r in rows], "by_category": categories}


def _aegis_steph_review_queue():
    """GET /api/v2/aegis/steph-review-queue — full review queue with lifecycle states."""
    rows = _db_query(
        """SELECT id, run_id, symbol, category, reason, evidence_summary, unresolved_question,
                  confidence, review_status, steph_verdict, steph_reasoning, steph_confidence,
                  recommended_next_step, send_to_john, john_question, resolved_at, reviewed_by, observed_at
           FROM aegis_steph_escalations
           ORDER BY
                CASE review_status WHEN 'pending_review' THEN 0 WHEN 'in_review' THEN 1
                     WHEN 'needs_john' THEN 2 ELSE 3 END,
                observed_at DESC
           LIMIT 30""",
        fetch="all"
    ) or []
    items = [{k: _json_clean(v) for k, v in r.items()} for r in rows]
    by_status = {}
    for i in items:
        s = i.get("review_status", "?")
        by_status[s] = by_status.get(s, 0) + 1
    # Freshness + priority indicators
    newest = items[0].get("observed_at") if items else None
    blocked = [i for i in items if i.get("review_status") == "needs_john"]
    actionable = [i for i in items if i.get("review_status") == "pending_review"]
    by_category = {}
    for i in items:
        c = i.get("category", "other")
        by_category[c] = by_category.get(c, 0) + 1
    return {
        "count": len(items), "items": items, "by_status": by_status,
        "by_category": by_category,
        "pending_count": by_status.get("pending_review", 0),
        "needs_john_count": by_status.get("needs_john", 0),
        "blocked_count": len(blocked),
        "actionable_count": len(actionable),
        "newest_at": str(newest) if newest else None,
    }


def _steph_resolve(body: dict):
    """POST /api/v2/aegis/steph-resolve — Steph resolves an escalation item."""
    esc_id = body.get("id")
    new_status = body.get("status", "").strip()
    verdict = body.get("verdict", "").strip()
    reasoning = body.get("reasoning", "").strip()
    next_step = body.get("next_step", "").strip()
    john_q = body.get("john_question", "").strip()

    valid_statuses = ("resolved", "deferred", "rejected", "needs_john", "in_review", "superseded")
    if not esc_id:
        return 400, {"ok": False, "error": "id required"}
    if new_status not in valid_statuses:
        return 400, {"ok": False, "error": f"status must be one of: {', '.join(valid_statuses)}"}

    # Get current state
    current = _db_query("SELECT id, review_status, symbol, category FROM aegis_steph_escalations WHERE id=%s", (esc_id,), fetch="one")
    if not current:
        return 404, {"ok": False, "error": "escalation not found"}

    old_status = current.get("review_status", "pending_review")

    # Update
    _db_write(
        """UPDATE aegis_steph_escalations SET
              review_status=%s, steph_verdict=%s, steph_reasoning=%s, steph_confidence=%s,
              recommended_next_step=%s, send_to_john=%s, john_question=%s,
              resolved_at=%s, reviewed_by='steph'
           WHERE id=%s""",
        (new_status, verdict or None, reasoning or None, body.get("confidence"),
         next_step or None, new_status == "needs_john", john_q or None,
         datetime.now() if new_status in ("resolved", "rejected", "deferred") else None,
         esc_id)
    )

    # History
    _db_write(
        """INSERT INTO aegis_steph_resolution_history
           (escalation_id, changed_by, old_status, new_status, verdict, reasoning)
           VALUES (%s, 'steph', %s, %s, %s, %s)""",
        (esc_id, old_status, new_status, verdict, reasoning)
    )

    return 200, {"ok": True, "action": new_status, "id": esc_id}


def _aegis_chat_context():
    """GET /api/v2/aegis/chat-context — unified context for Aegis Chat conversations.

    This is the bridge between Aegis Core and Aegis Chat.
    Provides all the data Aegis Chat needs to answer questions.
    """
    # Portfolio summary — use LIVE holdings data, not stale Aegis brief
    _h = _load_json(STATE_DIR / "holdings.json") or {}
    _pt = _h.get("portfolio_totals", {})
    _pv = _pt.get("total_value", 0)
    _heat = _pt.get("day_change_pct", 0)
    # Risk data for stop count
    _risk = _load_json(STATE_DIR / "risk_management.json") or {}
    _triggered = len([p for p in _risk.get("positions", []) if p.get("status") == "TRIGGERED"])
    _unprotected = len([p for p in _risk.get("positions", []) if not p.get("has_stop") and not p.get("stop_price")])
    _live_summary = f"Portfolio ${_pv:,.0f}. Heat {_heat:.1f}%. {_triggered} stops triggered, {_unprotected} unprotected."
    # Also get Aegis brief for additional context
    summary = _db_query(
        "SELECT what_changed FROM aegis_portfolio_briefs WHERE brief_type='summary' ORDER BY observed_at DESC LIMIT 1",
        fetch="one"
    )
    # Append Aegis extras (Steph review, covered calls) if available
    _aegis_extra = (summary or {}).get("what_changed", "")
    # Strip stale portfolio/heat/stop data from Aegis extra — we already have live
    import re as _re
    _aegis_extra = _re.sub(r'Portfolio \$[\d,]+\.?\d*', '', _aegis_extra)
    _aegis_extra = _re.sub(r'Heat [\d.]+%\.?', '', _aegis_extra)
    _aegis_extra = _re.sub(r'\d+ stops? triggered,?\s*', '', _aegis_extra)
    _aegis_extra = _re.sub(r'\d+ unprotected\.?\s*', '', _aegis_extra)
    _aegis_extra = _aegis_extra.strip('. ')
    if _aegis_extra and len(_aegis_extra) > 10:
        _live_summary += " " + _aegis_extra
    # Top findings needing attention
    steph_items = _db_query(
        "SELECT symbol, category, reason, unresolved_question, review_status, steph_verdict, steph_reasoning, steph_confidence, send_to_john, john_question, reviewed_by, resolved_at FROM aegis_steph_escalations ORDER BY observed_at DESC LIMIT 10"
    ) or []
    # Latest CC candidates
    cc = _db_query(
        "SELECT symbol, verdict, reasoning FROM aegis_covered_call_candidates WHERE run_id=(SELECT run_id FROM aegis_covered_call_candidates ORDER BY observed_at DESC LIMIT 1) ORDER BY verdict='candidate' DESC LIMIT 5"
    ) or []
    # Rotation alternatives
    rot = _db_query(
        "SELECT from_symbol, to_symbol, switch_verdict, evidence FROM aegis_rotation_candidates ORDER BY observed_at DESC LIMIT 5"
    ) or []
    # Active recovery
    recovery = _db_query(
        "SELECT symbol, analyst_verdict, analyst_confidence, temp_allocation_verdict FROM stopped_out_watch WHERE is_active=true"
    ) or []
    # Improvement proposals
    proposals = _db_query(
        "SELECT id, category, title, status, created_at FROM aegis_improvement_proposals ORDER BY created_at DESC LIMIT 5"
    ) or []

    # Stop coverage summary
    stop_cov_row = _db_query(
        "SELECT what_changed, confidence FROM aegis_portfolio_briefs WHERE symbol='COVERAGE' AND brief_type='stop_coverage_summary' ORDER BY observed_at DESC LIMIT 1",
        fetch="one"
    )
    stop_coverage = {}
    if stop_cov_row and stop_cov_row.get("what_changed"):
        try:
            stop_coverage = json.loads(stop_cov_row["what_changed"])
        except (json.JSONDecodeError, TypeError):
            pass

    # Stop briefs for chat retrieval
    stop_briefs = _db_query(
        """SELECT symbol, thesis_status, what_changed, why_it_matters, confidence, needs_steph_review, provenance, observed_at
           FROM aegis_portfolio_briefs WHERE brief_type='stop_brief'
           AND run_id=(SELECT run_id FROM aegis_portfolio_briefs WHERE brief_type='stop_brief' ORDER BY observed_at DESC LIMIT 1)
           ORDER BY
             CASE thesis_status WHEN 'triggered' THEN 0 WHEN 'danger' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END""",
        fetch="all"
    ) or []

    # Event intelligence digest (Level 3)
    event_rows = _db_query(
        """SELECT event_type, status, array_agg(DISTINCT symbol) as symbols, count(*) as cnt
           FROM agent_event_queue
           WHERE created_at > NOW() - INTERVAL '24 hours'
           GROUP BY event_type, status
           ORDER BY cnt DESC"""
    ) or []
    event_digest = {}
    for er in event_rows:
        et = er["event_type"]
        if et not in event_digest:
            event_digest[et] = {"symbols": [], "count": 0, "done": 0, "pending": 0}
        event_digest[et]["symbols"] = list(set(event_digest[et]["symbols"] + [s for s in (er.get("symbols") or []) if s]))
        event_digest[et]["count"] += er["cnt"]
        if er["status"] == "done":
            event_digest[et]["done"] += er["cnt"]
        else:
            event_digest[et]["pending"] += er["cnt"]

    return {
        "portfolio_summary": _live_summary,
        "steph_escalations": [{k: _json_clean(v) for k, v in r.items()} for r in steph_items],
        "covered_calls": [{k: _json_clean(v) for k, v in r.items()} for r in cc],
        "rotations": [{k: _json_clean(v) for k, v in r.items()} for r in rot],
        "recovery": [{k: _json_clean(v) for k, v in r.items()} for r in recovery],
        "improvement_proposals": [{k: _json_clean(v) for k, v in r.items()} for r in proposals],
        "john_decisions": _john_decisions_summary(),
        "outcome_tracking": _outcome_summary(),
        "event_digest": event_digest,
        "event_total_24h": sum(d["count"] for d in event_digest.values()),
        "agent": "aegis",
        "layer": "chat",
        "core_status": "active",
        "evidence_summary": _evidence_summary(),
        "stop_coverage": stop_coverage,
        "stop_briefs": [{k: _json_clean(v) for k, v in r.items()} for r in stop_briefs],
        "morning_brief": _compose_morning_brief(
            _live_summary,
            [{k: _json_clean(v) for k, v in r.items()} for r in steph_items],
            [{k: _json_clean(v) for k, v in r.items()} for r in cc],
            [{k: _json_clean(v) for k, v in r.items()} for r in rot],
            [{k: _json_clean(v) for k, v in r.items()} for r in recovery],
        ),
    }


def _compose_morning_brief(summary_text, steph_items, cc_items, rotations, recovery_items):
    """Pre-compose a portfolio-specific morning brief from Aegis Core data."""
    sections = []

    # 1. Immediate risk
    risk_parts = []
    _rm = _load_json(STATE_DIR / "risk_management.json") or {}
    triggered = [p for p in _rm.get("positions", []) if p.get("status") == "TRIGGERED"]
    danger = [p for p in _rm.get("positions", []) if p.get("status") == "DANGER"]
    unprotected = [p for p in _rm.get("positions", []) if p.get("status") == "NO STOP" and (p.get("market_value") or 0) > 5000]
    if triggered:
        risk_parts.append(f"{len(triggered)} stop(s) TRIGGERED: {', '.join(p.get('symbol','') for p in triggered)}. Check /v2/risk immediately.")
    if danger:
        risk_parts.append(f"{len(danger)} in danger zone: {', '.join(p.get('symbol','') for p in danger)}.")
    if unprotected:
        risk_parts.append(f"{len(unprotected)} large positions without stops (${sum(p.get('market_value',0) for p in unprotected):,.0f} total).")
    if risk_parts:
        sections.append({"priority": 1, "title": "IMMEDIATE RISK", "items": risk_parts})

    # 2. Steph review
    if steph_items:
        steph_parts = []
        for s in steph_items[:3]:
            steph_parts.append(f"{s.get('symbol','?')}: {s.get('reason','')[:80]} → /v2/approvals")
        sections.append({"priority": 2, "title": "STEPH REVIEW NEEDED", "items": steph_parts})

    # 3. Recovery watch
    if recovery_items:
        rec_parts = []
        for r in recovery_items:
            rec_parts.append(f"{r.get('symbol','?')}: {r.get('analyst_verdict','?')} (alloc: {r.get('temp_allocation_verdict','?')}) → /v2/recovery")
        sections.append({"priority": 3, "title": "RECOVERY WATCH", "items": rec_parts})

    # 4. Covered calls
    review_cc = [c for c in cc_items if c.get("verdict") == "review_needed"]
    avoid_cc = [c for c in cc_items if c.get("verdict") == "avoid"]
    if review_cc or avoid_cc:
        cc_parts = []
        if review_cc:
            cc_parts.append(f"Review needed: {', '.join(c.get('symbol','') for c in review_cc[:5])}")
        if avoid_cc:
            cc_parts.append(f"Avoid: {', '.join(c.get('symbol','') for c in avoid_cc[:3])}")
        sections.append({"priority": 4, "title": "COVERED CALLS", "items": cc_parts})

    # 5. Rotations
    if rotations:
        rot_parts = []
        for r in rotations[:3]:
            rot_parts.append(f"{r.get('from_symbol','?')} → {r.get('to_symbol','?') or 'no alternative'}: {r.get('switch_verdict','?')}")
        sections.append({"priority": 5, "title": "ROTATION ALTERNATIVES", "items": rot_parts})

    # 6. Research findings (latest iterations from persistent research topics)
    _research = _db_query(
        "SELECT topic, latest_findings, priority, research_count FROM user_research_topics "
        "WHERE status='active' AND latest_findings IS NOT NULL "
        "ORDER BY priority DESC, latest_finding_at DESC LIMIT 5"
    ) or []
    if _research:
        rf_parts = []
        for rt in _research[:3]:
            _findings_preview = (rt.get("latest_findings") or "")[:120].replace("\n", " ")
            rf_parts.append(f"{rt.get('topic','?')} (iter #{rt.get('research_count',0)}): {_findings_preview}… → /v2/research-topics")
        sections.append({"priority": 6, "title": "RESEARCH ADVISORIES", "items": rf_parts})

    # 7. Summary line
    next_actions = []
    if triggered:
        next_actions.append(f"1. Verify {', '.join(p.get('symbol','') for p in triggered[:3])} stop levels in broker → /v2/risk")
    if steph_items:
        next_actions.append(f"{'2' if triggered else '1'}. Review Steph escalations → /v2/approvals")
    if review_cc:
        next_actions.append(f"{'3' if triggered and steph_items else '2' if triggered or steph_items else '1'}. Check covered-call candidates → /v2/actions")

    return {
        "sections": sections,
        "next_actions": next_actions[:5],
        "portfolio_summary": summary_text,
        "has_findings": len(sections) > 0,
    }


def _evidence_summary():
    """Quick evidence quality summary for chat context."""
    rows = _db_query(
        "SELECT evidence_sufficiency, bias_score, conflict_flag FROM aegis_evidence_ledger WHERE run_id=(SELECT run_id FROM aegis_evidence_ledger ORDER BY observed_at DESC LIMIT 1)"
    ) or []
    if not rows:
        return {"available": False}
    suff = {}
    for r in rows:
        s = r.get("evidence_sufficiency", "?")
        suff[s] = suff.get(s, 0) + 1
    flagged = sum(1 for r in rows if float(r.get("bias_score") or 0) > 0.3)
    conflicts = sum(1 for r in rows if r.get("conflict_flag"))
    return {
        "available": True, "symbols_checked": len(rows),
        "sufficiency": suff, "bias_flagged": flagged, "conflicts": conflicts,
    }


def _outcome_summary():
    """Quick outcome summary for Aegis Chat context."""
    rows = _db_query("SELECT status, outcome_label, outcome_score FROM aegis_outcome_tracking") or []
    evaluated = [r for r in rows if r.get("status") == "evaluated"]
    pending = sum(1 for r in rows if r.get("status") == "pending")
    avg_score = round(sum(float(r.get("outcome_score") or 0) for r in evaluated) / max(len(evaluated), 1), 2) if evaluated else None
    labels = {}
    for r in rows:
        l = r.get("outcome_label", "?")
        labels[l] = labels.get(l, 0) + 1
    return {
        "total": len(rows), "evaluated": len(evaluated), "pending": pending,
        "avg_score": avg_score, "labels": labels,
    }


def _aegis_outcomes():
    """GET /api/v2/aegis/outcomes — outcome tracking with scores and labels."""
    rows = _db_query(
        """SELECT id, source_layer, category, symbol, recommendation_text, decision_text,
                  status, outcome_label, outcome_score, timeliness, usefulness, reasoning,
                  who_evaluated, linked_route, evaluated_at, created_at
           FROM aegis_outcome_tracking
           ORDER BY created_at DESC LIMIT 30""",
        fetch="all"
    ) or []
    items = [{k: _json_clean(v) for k, v in r.items()} for r in rows]
    by_label = {}
    for i in items:
        l = i.get("outcome_label", "?")
        by_label[l] = by_label.get(l, 0) + 1
    by_layer = {}
    for i in items:
        l = i.get("source_layer", "?")
        by_layer[l] = by_layer.get(l, 0) + 1
    evaluated = [i for i in items if i.get("status") == "evaluated"]
    avg_score = round(sum(float(i.get("outcome_score") or 0) for i in evaluated) / max(len(evaluated), 1), 2) if evaluated else None
    return {
        "count": len(items), "items": items,
        "by_label": by_label, "by_layer": by_layer,
        "evaluated_count": len(evaluated),
        "pending_count": sum(1 for i in items if i.get("status") == "pending"),
        "avg_score": avg_score,
    }


def _john_decisions_summary():
    """Quick summary for Aegis Chat context."""
    rows = _db_query("SELECT status, count(*) as cnt FROM john_decision_queue GROUP BY status") or []
    by_status = {r["status"]: r["cnt"] for r in rows}
    pending = _db_query(
        "SELECT id, category, symbol, title, priority FROM john_decision_queue WHERE status='pending_john' ORDER BY priority, id LIMIT 5"
    ) or []
    revisit_due = _db_query(
        "SELECT id, symbol, title, revisit_on, john_decision FROM john_decision_queue WHERE status='revisit_later' AND revisit_on <= CURRENT_DATE ORDER BY revisit_on LIMIT 5"
    ) or []
    deferred = _db_query(
        "SELECT id, symbol, title, revisit_on, john_decision FROM john_decision_queue WHERE status='deferred' ORDER BY revisit_on NULLS LAST LIMIT 5"
    ) or []
    overdue = _db_query(
        "SELECT count(*) as cnt FROM john_decision_queue WHERE status IN ('revisit_later','deferred') AND revisit_on < CURRENT_DATE",
        fetch="one"
    ) or {}
    this_week = _db_query(
        "SELECT count(*) as cnt FROM john_decision_queue WHERE status IN ('revisit_later','deferred') AND revisit_on BETWEEN CURRENT_DATE AND CURRENT_DATE + 7",
        fetch="one"
    ) or {}
    return {
        "pending_count": by_status.get("pending_john", 0),
        "total": sum(by_status.values()),
        "by_status": by_status,
        "pending_items": [{k: _json_clean(v) for k, v in r.items()} for r in pending],
        "revisit_due": [{k: _json_clean(v) for k, v in r.items()} for r in revisit_due],
        "deferred_items": [{k: _json_clean(v) for k, v in r.items()} for r in deferred],
        "overdue_count": overdue.get("cnt", 0),
        "due_this_week": this_week.get("cnt", 0),
    }


def _john_decisions():
    """GET /api/v2/john/decisions — John's decision queue with lifecycle."""
    rows = _db_query(
        """SELECT id, category, symbol, title, description, steph_recommendation, steph_confidence,
                  priority, status, john_decision, john_reasoning, due_by, revisit_on,
                  required_followup, linked_route, linked_symbols, closure_note, decided_at, created_at
           FROM john_decision_queue
           ORDER BY
                CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,
                CASE status WHEN 'pending_john' THEN 0 WHEN 'revisit_later' THEN 1 ELSE 2 END,
                created_at DESC
           LIMIT 30""",
        fetch="all"
    ) or []
    items = [{k: _json_clean(v) for k, v in r.items()} for r in rows]
    by_status = {}
    for i in items:
        s = i.get("status", "?")
        by_status[s] = by_status.get(s, 0) + 1
    # Check for due/overdue revisits
    revisit_due = _db_query(
        "SELECT count(*) as cnt FROM john_decision_queue WHERE status='revisit_later' AND revisit_on <= CURRENT_DATE",
        fetch="one"
    ) or {}
    return {
        "count": len(items), "items": items, "by_status": by_status,
        "pending_count": by_status.get("pending_john", 0),
        "revisit_due_count": revisit_due.get("cnt", 0),
    }


def _apply_yaml_parameter_change(task_id: int, provenance: dict) -> dict:
    """Apply an approved YAML parameter change from john_decision_queue."""
    try:
        import yaml
        import shutil
        from pathlib import Path

        parameter = provenance.get('parameter', '')
        new_value = provenance.get('proposed_value')
        yaml_file = provenance.get('yaml_file', 'config/indicator_strategies.yaml')

        yaml_path = Path(yaml_file)
        if not yaml_path.exists():
            return {'ok': False, 'error': f'YAML file not found: {yaml_file}'}

        with open(yaml_path, 'r') as f:
            config = yaml.safe_load(f)

        # Navigate parameter path (e.g. 'rsi.entry_max' -> config['strategies']['rsi']['entry_max'])
        parts = parameter.split('.')
        obj = config
        if parts[0] in config.get('strategies', {}):
            obj = config['strategies'][parts[0]]
            param_key = parts[1] if len(parts) > 1 else parts[0]
        elif parts[0] in config.get('profiles', {}):
            obj = config['profiles'][parts[0]]
            param_key = parts[1] if len(parts) > 1 else parts[0]
        else:
            return {'ok': False, 'error': f'Parameter path not found: {parameter}'}

        old_value = obj.get(param_key)
        obj[param_key] = new_value

        # Backup before write
        backup_path = yaml_path.with_suffix(f'.yaml.bak_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        shutil.copy(yaml_path, backup_path)

        with open(yaml_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, indent=2)

        # Log to agent_intelligence_rules
        _db_write(
            """INSERT INTO agent_intelligence_rules (rule_type, rule_key, config, changed_by, updated_at)
               VALUES ('yaml_parameter_change', %s, %s, 'alex', NOW())
               ON CONFLICT (rule_type, rule_key) DO UPDATE SET config=EXCLUDED.config, updated_at=NOW()""",
            (parameter, json.dumps({
                'old_value': old_value, 'new_value': new_value,
                'approved_task_id': task_id,
                'evidence': provenance.get('evidence', '')[:200],
                'changed_at': datetime.now().isoformat(),
            }))
        )

        logger.info(f"[YAML TUNING] {parameter}: {old_value} -> {new_value} (backup: {backup_path.name})")
        return {'ok': True, 'parameter': parameter, 'old_value': old_value, 'new_value': new_value, 'backup': str(backup_path)}

    except Exception as e:
        logger.error(f"[YAML TUNING] apply failed: {e}")
        return {'ok': False, 'error': str(e)}


def _john_decide(body: dict):
    """POST /api/v2/john/decide — John makes a decision on a queue item."""
    item_id = body.get("id")
    new_status = body.get("status", "").strip()
    decision = body.get("decision", "").strip()
    reasoning = body.get("reasoning", "").strip()
    revisit_on = body.get("revisit_on")
    followup = body.get("followup", "").strip()

    valid = ("decided_action", "deferred", "rejected", "revisit_later", "closed")
    if not item_id:
        return 400, {"ok": False, "error": "id required"}
    if new_status not in valid:
        return 400, {"ok": False, "error": f"status must be: {', '.join(valid)}"}

    current = _db_query("SELECT id, status FROM john_decision_queue WHERE id=%s", (item_id,), fetch="one")
    if not current:
        return 404, {"ok": False, "error": "decision item not found"}

    old_status = current.get("status")

    _db_write(
        """UPDATE john_decision_queue SET
              status=%s, john_decision=%s, john_reasoning=%s,
              revisit_on=%s, required_followup=%s,
              closure_note=%s, decided_at=NOW()
           WHERE id=%s""",
        (new_status, decision or None, reasoning or None,
         revisit_on, followup or None,
         f"{decision}: {reasoning}" if decision else None,
         item_id)
    )

    _db_write(
        """INSERT INTO john_decision_history (decision_id, old_status, new_status, decision, reasoning)
           VALUES (%s, %s, %s, %s, %s)""",
        (item_id, old_status, new_status, decision, reasoning)
    )

    # Auto-apply YAML parameter changes on approval
    if new_status == "decided_action":
        item_full = _db_query("SELECT category, provenance FROM john_decision_queue WHERE id=%s", (item_id,), fetch="one")
        if item_full and item_full.get("category") == "yaml_parameter_change":
            yaml_result = _apply_yaml_parameter_change(item_id, item_full.get("provenance", {}))
            if yaml_result.get("ok"):
                logger.info(f"[YAML TUNING] Applied: {yaml_result.get('parameter')} {yaml_result.get('old_value')} -> {yaml_result.get('new_value')}")
                return 200, {"ok": True, "action": new_status, "id": item_id, "yaml_applied": yaml_result}
            else:
                logger.error(f"[YAML TUNING] Failed: {yaml_result.get('error')}")

    return 200, {"ok": True, "action": new_status, "id": item_id}


def _tasks_unified():
    """GET /api/v2/tasks — unified view of ALL John-visible tasks across both queues."""
    # John decision queue
    john_items = _db_query(
        """SELECT id, category, symbol, title, description, steph_recommendation, steph_confidence,
                  priority, status, john_decision, john_reasoning, due_by, revisit_on,
                  required_followup, linked_route, linked_symbols, decided_at, created_at, provenance
           FROM john_decision_queue
           WHERE status IN ('pending_john', 'revisit_later')
           ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,
                    created_at DESC
           LIMIT 20""",
        fetch="all"
    ) or []
    # Action queue (approvals)
    action_items = _db_query(
        """SELECT id, action, symbol, rationale, confidence, urgency, status, expires_at, created_at,
                  dedupe_key
           FROM action_queue
           WHERE status = 'pending'
           ORDER BY CASE urgency WHEN 'urgent' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                    created_at DESC
           LIMIT 10""",
        fetch="all"
    ) or []
    # Normalize into unified format
    tasks = []
    for r in john_items:
        tasks.append({
            "id": r["id"], "source": "john_decision_queue",
            "category": r.get("category"), "symbol": r.get("symbol"),
            "title": r.get("title"), "description": r.get("description"),
            "priority": r.get("priority"), "status": r.get("status"),
            "recommendation": r.get("steph_recommendation"),
            "confidence": float(r.get("steph_confidence") or 0),
            "due_by": str(r.get("due_by") or ""),
            "linked_route": r.get("linked_route"),
            "followup": r.get("required_followup"),
            "decided_at": str(r.get("decided_at") or ""),
            "created_at": str(r.get("created_at") or ""),
            "provenance": r.get("provenance") or {},
        })
    for r in action_items:
        tasks.append({
            "id": r["id"], "source": "action_queue",
            "category": r.get("action"), "symbol": r.get("symbol"),
            "title": f"{(r.get('action') or '').replace('_',' ')} — {r.get('symbol') or 'portfolio'}",
            "description": r.get("rationale"),
            "priority": r.get("urgency"), "status": "pending_john",
            "recommendation": r.get("rationale"),
            "confidence": float(r.get("confidence") or 0),
            "due_by": str(r.get("expires_at") or ""),
            "linked_route": "/approvals",
            "followup": None,
            "decided_at": "", "created_at": str(r.get("created_at") or ""),
            "provenance": {},
        })
    # Summary counts
    urgent = sum(1 for t in tasks if t["priority"] == "urgent")
    pending = sum(1 for t in tasks if t["status"] == "pending_john")
    failed_auto = sum(1 for t in tasks if t["category"] == "failed_stop_review")
    return {
        "count": len(tasks), "tasks": tasks,
        "urgent": urgent, "pending": pending, "failed_automation": failed_auto,
    }


def _tasks_pending():
    """GET /api/v2/tasks/pending — pending tasks with symbol lookup for cross-linking."""
    rows = _db_query(
        """SELECT id, symbol, category, title, description, priority, created_at
           FROM john_decision_queue
           WHERE status = 'pending_john'
           ORDER BY
             CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
                           WHEN 'normal' THEN 2 ELSE 3 END,
             created_at DESC""",
        fetch="all"
    ) or []
    return {
        "count": len(rows),
        "tasks": [{k: _json_clean(v) for k, v in r.items()} for r in rows],
    }


def _tasks_history():
    """GET /api/v2/tasks/history — recent John decision audit trail."""
    rows = _db_query(
        """SELECT h.id, h.decision_id, h.old_status, h.new_status, h.decision, h.reasoning, h.changed_at,
                  q.symbol, q.category, q.title, q.priority
           FROM john_decision_history h
           LEFT JOIN john_decision_queue q ON q.id = h.decision_id
           ORDER BY h.changed_at DESC LIMIT 20""",
        fetch="all"
    ) or []
    return {
        "count": len(rows),
        "history": [{k: _json_clean(v) for k, v in r.items()} for r in rows],
    }


def _aegis_evidence():
    """GET /api/v2/aegis/evidence — evidence ledger with bias scores and flags."""
    rows = _db_query(
        """SELECT run_id, output_type, symbol, source_families, source_count, tier_mix,
                  evidence_confidence, statement_type, bias_score, bias_flags,
                  needs_counterevidence, evidence_sufficiency, counterevidence_summary,
                  conflict_flag, steph_review_required, observed_at
           FROM aegis_evidence_ledger
           WHERE run_id = (SELECT run_id FROM aegis_evidence_ledger ORDER BY observed_at DESC LIMIT 1)
           ORDER BY bias_score DESC, symbol""",
        fetch="all"
    ) or []
    items = [{k: _json_clean(v) for k, v in r.items()} for r in rows]
    flagged = [i for i in items if i.get("bias_score", 0) > 0.3]
    conflicts = [i for i in items if i.get("conflict_flag")]
    sufficiency = {}
    for i in items:
        s = i.get("evidence_sufficiency", "?")
        sufficiency[s] = sufficiency.get(s, 0) + 1
    return {
        "count": len(items), "run_id": items[0].get("run_id") if items else None,
        "entries": items,
        "flagged_count": len(flagged),
        "conflict_count": len(conflicts),
        "sufficiency_breakdown": sufficiency,
    }


def _aegis_improvements():
    """GET /api/v2/aegis/improvements — improvement proposals with approval state."""
    rows = _db_query(
        "SELECT id, category, title, description, proposed_change, reasoning, confidence, status, approved_by, approved_at, created_at FROM aegis_improvement_proposals ORDER BY created_at DESC LIMIT 20"
    ) or []
    by_status = {}
    for r in rows:
        s = r.get("status", "?")
        by_status[s] = by_status.get(s, 0) + 1
    return {
        "count": len(rows),
        "proposals": [{k: _json_clean(v) for k, v in r.items()} for r in rows],
        "by_status": by_status,
    }


def _aegis_transcript_intel():
    """GET /api/v2/aegis/transcript-intel — latest transcript/commentary intelligence."""
    rows = _db_query(
        """SELECT run_id, symbol, theme, source_family, source_name, channel, title, summary,
                  stance, notable_themes, confidence, observed_at
           FROM transcript_intel_history
           WHERE run_id = (SELECT run_id FROM transcript_intel_history ORDER BY observed_at DESC LIMIT 1)
           ORDER BY confidence DESC""",
        fetch="all"
    ) or []
    return {
        "count": len(rows), "run_id": rows[0].get("run_id") if rows else None,
        "records": [{k: _json_clean(v) for k, v in r.items()} for r in rows],
        "last_run": str(rows[0].get("observed_at")) if rows else None,
    }


def _aegis_discovery():
    """GET /api/v2/aegis/discovery — latest bounded web discovery results."""
    rows = _db_query(
        """SELECT run_id, symbol, theme, query, source_url, source_title, source_description,
                  source_family, trust_tier, observed_at
           FROM aegis_discovery_index
           WHERE run_id = (SELECT run_id FROM aegis_discovery_index ORDER BY observed_at DESC LIMIT 1)
           ORDER BY trust_tier, symbol""",
        fetch="all"
    ) or []
    tiers = {}
    for r in rows:
        t = r.get("trust_tier", "E")
        tiers[t] = tiers.get(t, 0) + 1
    return {
        "count": len(rows), "run_id": rows[0].get("run_id") if rows else None,
        "records": [{k: _json_clean(v) for k, v in r.items()} for r in rows],
        "tier_breakdown": tiers,
        "last_run": str(rows[0].get("observed_at")) if rows else None,
    }


def _aegis_social_sentiment():
    """GET /api/v2/aegis/social-sentiment — latest social sentiment for tracked symbols."""
    rows = _db_query(
        """SELECT run_id, symbol, source_family, mention_count, bullish_count, bearish_count,
                  sentiment_score, unusual_spike, theme_tags, top_posts_summary, confidence, observed_at
           FROM social_sentiment_history
           WHERE run_id = (SELECT run_id FROM social_sentiment_history ORDER BY observed_at DESC LIMIT 1)
           ORDER BY mention_count DESC""",
        fetch="all"
    ) or []
    items = [{k: _json_clean(v) for k, v in r.items()} for r in rows]
    spikes = [i for i in items if i.get("unusual_spike")]
    return {
        "count": len(items), "run_id": items[0].get("run_id") if items else None,
        "symbols": items, "spike_count": len(spikes),
        "last_run": items[0].get("observed_at") if items else None,
    }


def _aegis_findings():
    """GET /api/v2/aegis/findings — Aegis observations, queryable by Steph or dashboard."""
    rows = _db_query(
        """SELECT id, observation_date, symbol, category, observation, evidence,
                  confidence, model, source, observed_at
           FROM advisor_observations WHERE model = 'aegis'
           ORDER BY observed_at DESC LIMIT 30""",
        fetch="all"
    ) or []
    items = []
    for r in rows:
        item = {k: _json_clean(v) for k, v in r.items()}
        ev = r.get("evidence")
        if isinstance(ev, str):
            try:
                item["evidence"] = json.loads(ev)
            except Exception:
                pass
        items.append(item)

    # Summary counts
    categories = {}
    for r in items:
        cat = r.get("category", "other")
        categories[cat] = categories.get(cat, 0) + 1

    return {
        "count": len(items), "findings": items,
        "categories": categories,
        "agent": "aegis",
        "last_run": items[0].get("observed_at") if items else None,
    }


def _ops_audit():
    """GET /api/v2/ops/audit — recent runs, imports, and action audit trail."""
    import glob as _glob

    # Recent UI-triggered runs
    run_dir = PROJECT_ROOT / "logs" / "ui_runs"
    recent_runs = []
    if run_dir.exists():
        for f in sorted(run_dir.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True)[:10]:
            size = f.stat().st_size
            lines = f.read_text(errors="replace").strip().split("\n") if size > 0 else []
            last_line = lines[-1][:100] if lines else ""
            recent_runs.append({
                "name": f.stem, "size_kb": round(size / 1024, 1),
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
                "last_line": last_line, "success": "error" not in last_line.lower(),
            })

    # Recent imports — prefer structured JSONL, fallback to raw log
    import_structured = PROJECT_ROOT / "logs" / "import_audit_structured.jsonl"
    import_log = PROJECT_ROOT / "logs" / "import_audit.log"
    recent_imports = []
    if import_structured.exists():
        for line in import_structured.read_text(errors="replace").strip().split("\n")[-10:]:
            try:
                recent_imports.append(json.loads(line))
            except Exception:
                recent_imports.append({"raw": line})
    elif import_log.exists():
        for line in import_log.read_text(errors="replace").strip().split("\n")[-10:]:
            recent_imports.append({"raw": line.strip()})

    # Recent notifications
    notifs = _db_query(
        "SELECT notification_type, channel, subject, status, sent_at::text FROM notification_log ORDER BY created_at DESC LIMIT 10"
    ) or []

    # Recovery watch runs
    recovery_log = PROJECT_ROOT / "logs" / "recovery-watch.log"
    recovery_lines = []
    if recovery_log.exists():
        for line in recovery_log.read_text(errors="replace").strip().split("\n")[-8:]:
            recovery_lines.append(line.strip())

    return {
        "recent_runs": recent_runs,
        "recent_imports": recent_imports,
        "recent_notifications": [{k: _json_clean(v) for k, v in r.items()} for r in notifs],
        "recovery_log": recovery_lines,
    }


def ops_summary():
    fresh = _load_json(STATE_DIR / "_freshness.json") or {}
    health_rows = _db_query("""
        SELECT s.relname AS name, s.n_live_tup AS live_rows, s.n_dead_tup AS dead_rows,
               pg_size_pretty(pg_total_relation_size(s.schemaname||'.'||s.relname)) AS size
        FROM pg_stat_user_tables s
        ORDER BY pg_total_relation_size(s.schemaname||'.'||s.relname) DESC
    """, fetch="all") or []

    return {
        "pipeline": {
            "status": fresh.get("status", "unknown"),
            "completed_at": fresh.get("completed_at", ""),
            "duration_seconds": fresh.get("pipeline_duration_seconds", 0),
            "steps": fresh.get("steps_completed", 0),
            "run_type": fresh.get("run_type", ""),
            "holdings_hash": fresh.get("holdings_hash", ""),
            "run_id": fresh.get("run_id", ""),
        },
        "database": {
            "table_count": len(health_rows),
            "total_rows": sum(r.get("live_rows", 0) for r in health_rows),
            "tables": [dict(r) for r in health_rows],
        },
    }


def journal_analytics():
    """GET /api/v2/journal/analytics — aggregated review metrics from journal_trade_reviews."""
    # Setup performance
    setup_rows = _db_query("""
        SELECT setup_name, COUNT(*) as n,
               AVG(realized_r) as avg_r,
               AVG(execution_quality_score) as avg_exec,
               AVG(sizing_quality_score) as avg_sizing,
               SUM(CASE WHEN well_executed THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) as well_exec_rate,
               SUM(CASE WHEN followed_plan THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) as plan_follow_rate
        FROM journal_trade_reviews WHERE setup_name IS NOT NULL AND setup_name != ''
        GROUP BY setup_name ORDER BY n DESC
    """) or []

    # Emotion breakdown
    emotion_rows = _db_query("""
        SELECT emotion_before, COUNT(*) as n FROM journal_trade_reviews
        WHERE emotion_before IS NOT NULL AND emotion_before != ''
        GROUP BY emotion_before ORDER BY n DESC
    """) or []
    emotion_during_rows = _db_query("""
        SELECT emotion_during, COUNT(*) as n FROM journal_trade_reviews
        WHERE emotion_during IS NOT NULL AND emotion_during != ''
        GROUP BY emotion_during ORDER BY n DESC
    """) or []

    # Mistake tag frequency
    mistake_rows = _db_query("""
        SELECT tag, COUNT(*) as n FROM (
            SELECT unnest(mistake_tags) as tag FROM journal_trade_reviews
            WHERE mistake_tags IS NOT NULL AND array_length(mistake_tags, 1) > 0
        ) sub GROUP BY tag ORDER BY n DESC
    """) or []

    # Strength tag frequency
    strength_rows = _db_query("""
        SELECT tag, COUNT(*) as n FROM (
            SELECT unnest(strength_tags) as tag FROM journal_trade_reviews
            WHERE strength_tags IS NOT NULL AND array_length(strength_tags, 1) > 0
        ) sub GROUP BY tag ORDER BY n DESC
    """) or []

    # Timeframe breakdown
    tf_rows = _db_query("""
        SELECT timeframe, COUNT(*) as n,
               AVG(execution_quality_score) as avg_exec,
               SUM(CASE WHEN well_executed THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) as well_exec_rate
        FROM journal_trade_reviews WHERE timeframe IS NOT NULL AND timeframe != ''
        GROUP BY timeframe ORDER BY n DESC
    """) or []

    # Overall stats
    totals = _db_query("""
        SELECT COUNT(*) as total_reviews,
               AVG(execution_quality_score) as avg_exec,
               AVG(sizing_quality_score) as avg_sizing,
               SUM(CASE WHEN well_executed THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) as well_exec_rate,
               SUM(CASE WHEN followed_plan THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) as plan_follow_rate
        FROM journal_trade_reviews
    """, fetch="one") or {}

    def _clean_rows(rows):
        return [{k: (float(v) if isinstance(v, Decimal) else _json_clean(v)) for k, v in r.items()} for r in (rows or [])]

    return {
        "total_reviews": totals.get("total_reviews", 0),
        "avg_execution": float(totals["avg_exec"]) if totals.get("avg_exec") else None,
        "avg_sizing": float(totals["avg_sizing"]) if totals.get("avg_sizing") else None,
        "well_executed_rate": float(totals["well_exec_rate"]) if totals.get("well_exec_rate") else None,
        "plan_follow_rate": float(totals["plan_follow_rate"]) if totals.get("plan_follow_rate") else None,
        "by_setup": _clean_rows(setup_rows),
        "by_timeframe": _clean_rows(tf_rows),
        "emotion_before": _clean_rows(emotion_rows),
        "emotion_during": _clean_rows(emotion_during_rows),
        "mistake_tags": _clean_rows(mistake_rows),
        "strength_tags": _clean_rows(strength_rows),
        "has_data": (totals.get("total_reviews") or 0) > 0,
        # Monthly execution quality trend
        "monthly_trend": _clean_rows(_db_query("""
            SELECT TO_CHAR(closed_date, 'YYYY-MM') as month, COUNT(*) as n,
                   AVG(execution_quality_score) as avg_exec,
                   AVG(sizing_quality_score) as avg_sizing,
                   SUM(CASE WHEN well_executed THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) as well_exec_rate
            FROM journal_trade_reviews WHERE closed_date IS NOT NULL
            GROUP BY TO_CHAR(closed_date, 'YYYY-MM') ORDER BY month
        """) or []),
        # Setup family rollups
        "by_setup_family": _clean_rows(_db_query("""
            SELECT COALESCE(setup_family, 'Unclassified') as family, COUNT(*) as n,
                   AVG(execution_quality_score) as avg_exec,
                   SUM(CASE WHEN well_executed THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) as well_exec_rate
            FROM journal_trade_reviews GROUP BY COALESCE(setup_family, 'Unclassified') ORDER BY n DESC
        """) or []),
        # Cross-reference: journal review data for specific symbols (for recovery integration)
        "reviewed_symbols": _clean_rows(_db_query("""
            SELECT symbol, COUNT(*) as review_count,
                   AVG(execution_quality_score) as avg_exec,
                   SUM(CASE WHEN well_executed THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) as well_exec_rate,
                   array_agg(DISTINCT setup_name) FILTER (WHERE setup_name IS NOT NULL) as setups_used
            FROM journal_trade_reviews WHERE symbol IS NOT NULL
            GROUP BY symbol ORDER BY review_count DESC
        """) or []),
        # Catalyst breakdown
        "by_catalyst": _clean_rows(_db_query("""
            SELECT catalyst_type, COUNT(*) as n,
                   AVG(execution_quality_score) as avg_exec,
                   SUM(CASE WHEN well_executed THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) as well_exec_rate
            FROM journal_trade_reviews WHERE catalyst_type IS NOT NULL AND catalyst_type != ''
            GROUP BY catalyst_type ORDER BY n DESC
        """) or []),
        # New dimension rollups (Tier 2L batch)
        "by_direction": _clean_rows(_db_query("""
            SELECT direction, COUNT(*) as n, AVG(execution_quality_score) as avg_exec,
                   SUM(CASE WHEN well_executed THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) as well_exec_rate
            FROM journal_trade_reviews WHERE direction IS NOT NULL AND direction != ''
            GROUP BY direction ORDER BY n DESC
        """) or []),
        "by_entry_type": _clean_rows(_db_query("""
            SELECT entry_type, COUNT(*) as n, AVG(execution_quality_score) as avg_exec
            FROM journal_trade_reviews WHERE entry_type IS NOT NULL AND entry_type != ''
            GROUP BY entry_type ORDER BY n DESC
        """) or []),
        "by_exit_type": _clean_rows(_db_query("""
            SELECT exit_type, COUNT(*) as n, AVG(execution_quality_score) as avg_exec
            FROM journal_trade_reviews WHERE exit_type IS NOT NULL AND exit_type != ''
            GROUP BY exit_type ORDER BY n DESC
        """) or []),
        "by_market_regime": _clean_rows(_db_query("""
            SELECT market_regime, COUNT(*) as n, AVG(execution_quality_score) as avg_exec,
                   SUM(CASE WHEN well_executed THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) as well_exec_rate
            FROM journal_trade_reviews WHERE market_regime IS NOT NULL AND market_regime != ''
            GROUP BY market_regime ORDER BY n DESC
        """) or []),
        "by_risk_management": _clean_rows(_db_query("""
            SELECT risk_management_score, COUNT(*) as n,
                   SUM(CASE WHEN well_executed THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) as well_exec_rate
            FROM journal_trade_reviews WHERE risk_management_score IS NOT NULL
            GROUP BY risk_management_score ORDER BY risk_management_score
        """) or []),
        # Pattern insights — best/worst performing dimensions
        "insights": _compute_journal_insights(totals, setup_rows, tf_rows, emotion_rows, mistake_rows),
    }


def _compute_journal_insights(totals, setup_rows, tf_rows, emotion_rows, mistake_rows):
    """Generate actionable pattern insights from journal review data."""
    insights = []
    total = totals.get("total_reviews", 0) or 0
    if total < 2:
        insights.append({"type": "guidance", "text": f"Only {total} review{'s' if total != 1 else ''} recorded. Add more reviews to unlock pattern insights. Aim for 10+ for meaningful analytics."})
        return insights

    # Best/worst setup
    if setup_rows and len(setup_rows) >= 2:
        best = max(setup_rows, key=lambda r: float(r.get("avg_exec") or 0))
        worst = min(setup_rows, key=lambda r: float(r.get("avg_exec") or 0))
        if best.get("setup_name") != worst.get("setup_name"):
            insights.append({"type": "setup", "text": f"Best setup: {best['setup_name']} (exec {float(best.get('avg_exec') or 0):.1f}/5, {best.get('n',0)} trades). Worst: {worst['setup_name']} (exec {float(worst.get('avg_exec') or 0):.1f}/5, {worst.get('n',0)} trades). Focus on setups where execution is strongest."})
    elif setup_rows and len(setup_rows) == 1:
        s = setup_rows[0]
        insights.append({"type": "setup", "text": f"Only setup used so far: {s['setup_name']} ({s.get('n',0)} trades, exec {float(s.get('avg_exec') or 0):.1f}/5). Add more setup variety to compare methodologies."})

    # Timeframe comparison
    if tf_rows and len(tf_rows) >= 2:
        best_tf = max(tf_rows, key=lambda r: float(r.get("well_exec_rate") or 0))
        worst_tf = min(tf_rows, key=lambda r: float(r.get("well_exec_rate") or 0))
        if best_tf.get("timeframe") != worst_tf.get("timeframe"):
            insights.append({"type": "timeframe", "text": f"Best timeframe: {best_tf['timeframe']} ({float(best_tf.get('well_exec_rate') or 0)*100:.0f}% well-executed). Weakest: {worst_tf['timeframe']} ({float(worst_tf.get('well_exec_rate') or 0)*100:.0f}%). Consider whether the weaker timeframe suits your decision style."})

    # Plan follow rate
    pfr = float(totals.get("plan_follow_rate") or 0)
    if pfr > 0:
        if pfr < 0.5:
            insights.append({"type": "discipline", "text": f"Plan follow rate is {pfr*100:.0f}% — less than half of trades follow the plan. This is the single highest-leverage improvement. Every trade should have a plan before entry."})
        elif pfr >= 0.8:
            insights.append({"type": "strength", "text": f"Plan follow rate is {pfr*100:.0f}% — strong discipline. Maintain this by writing the plan before entry."})

    # Execution vs sizing gap
    avg_exec = float(totals.get("avg_exec") or 0)
    avg_sizing = float(totals.get("avg_sizing") or 0)
    if avg_exec > 0 and avg_sizing > 0 and abs(avg_exec - avg_sizing) > 1.0:
        weaker = "sizing" if avg_sizing < avg_exec else "execution"
        insights.append({"type": "gap", "text": f"Execution ({avg_exec:.1f}/5) vs Sizing ({avg_sizing:.1f}/5) gap detected. Your {weaker} quality is lagging — focus improvement there."})

    # Emotion patterns
    if emotion_rows:
        negative_emotions = [e for e in emotion_rows if (e.get("emotion_before") or "").lower() in ("fomo", "revenge", "impatient", "anxious", "greedy", "distracted")]
        positive_emotions = [e for e in emotion_rows if (e.get("emotion_before") or "").lower() in ("calm", "confident", "focused")]
        if negative_emotions:
            top = negative_emotions[0]
            insights.append({"type": "warning", "text": f"Negative pre-trade emotion detected: {top.get('emotion_before','')} ({top.get('n',0)} trades). When you feel {top.get('emotion_before','').lower()}, pause and re-evaluate. Consider waiting 15 minutes before acting."})
        if positive_emotions:
            top = positive_emotions[0]
            insights.append({"type": "strength", "text": f"Most common positive state: {top.get('emotion_before','')} ({top.get('n',0)} trades). Aim to trade from this state."})

    # Mistake frequency
    if mistake_rows:
        top_mistake = mistake_rows[0]
        insights.append({"type": "mistake", "text": f"Most frequent mistake: {top_mistake.get('tag','')} ({top_mistake.get('n',0)} times). Write this on a sticky note near your screen. Every review that flags this pattern is a learning opportunity."})

    # Coaching summaries — Keep Doing / Stop Doing / Review Next
    keep_doing = []
    stop_doing = []
    review_next = []

    if setup_rows:
        best_s = max(setup_rows, key=lambda r: float(r.get("well_exec_rate") or 0))
        if float(best_s.get("well_exec_rate") or 0) >= 0.6:
            keep_doing.append(f"{best_s['setup_name']} setups ({float(best_s.get('well_exec_rate') or 0)*100:.0f}% well-executed)")

    if mistake_rows and len(mistake_rows) >= 1:
        stop_doing.append(f"{mistake_rows[0].get('tag','')} — your most frequent mistake")

    if emotion_rows:
        neg = [e for e in emotion_rows if (e.get("emotion_before") or "").lower() in ("fomo","revenge","impatient")]
        if neg:
            stop_doing.append(f"Trading from {neg[0].get('emotion_before','').lower()} state")

    if total >= 3:
        review_next.append("Trades with execution score < 3 — what went wrong?")
        if float(totals.get("plan_follow_rate") or 0) < 0.7:
            review_next.append("Trades where plan was not followed — what caused the deviation?")

    if keep_doing or stop_doing or review_next:
        coaching = []
        if keep_doing:
            coaching.append({"type": "keep", "text": "Keep doing: " + ". ".join(keep_doing)})
        if stop_doing:
            coaching.append({"type": "stop", "text": "Stop doing: " + ". ".join(stop_doing)})
        if review_next:
            coaching.append({"type": "review", "text": "Review next: " + ". ".join(review_next)})
        insights.extend(coaching)

    # Sample size guidance
    if total >= 5 and total < 10:
        insights.append({"type": "guidance", "text": f"{total} reviews — patterns are emerging but not yet statistically reliable. Keep reviewing trades. 20+ reviews will show strong methodology signals."})
    elif total >= 10 and total < 20:
        insights.append({"type": "guidance", "text": f"{total} reviews — enough for preliminary methodology comparison. The patterns above are directionally useful."})

    return insights


def journal():
    """GET /api/v2/journal — closed trades from DB (trade_closed table)."""
    import psycopg2.extras
    # Try DB first, fall back to JSON
    trades = []
    try:
        rows = _db_query(
            """SELECT symbol, account, open_date::text, close_date::text, trade_type,
                      shares, buy_price, sell_price, cost_basis, proceeds,
                      pnl, pnl_pct, hold_days
               FROM trade_closed
               WHERE buy_price > 0 OR pnl != 0
               ORDER BY close_date DESC, symbol
               LIMIT 500""",
            fetch="all"
        )
        if rows:
            for r in rows:
                item = {k: (float(v) if isinstance(v, Decimal) else v) for k, v in r.items()}
                # Construct trade_key for review linkage
                item["trade_key"] = f"{item.get('symbol','')}:{item.get('account','')}:{item.get('close_date','')}"
                trades.append(item)
    except Exception:
        pass

    # Fallback to JSON if DB empty
    if not trades:
        j = _load_json(STATE_DIR / "trade_journal.json") or {}
        raw = j.get("closed_trades", [])
        for t in raw[:500]:
            item = {
                "symbol": t.get("symbol", ""), "account": t.get("account", ""),
                "open_date": t.get("open_date", ""), "close_date": t.get("close_date", ""),
                "trade_type": t.get("trade_type", ""), "shares": t.get("shares", 0),
                "buy_price": t.get("buy_price", 0), "sell_price": t.get("sell_price", 0),
                "cost_basis": t.get("cost_basis", 0), "proceeds": t.get("proceeds", 0),
                "pnl": t.get("pnl", 0), "pnl_pct": t.get("pnl_pct", 0),
                "hold_days": t.get("hold_days", 0),
            }
            item["trade_key"] = f"{item['symbol']}:{item['account']}:{item['close_date']}"
            trades.append(item)

    real_trades = [t for t in trades if (t.get("pnl") or 0) != 0]

    # Compute stats from DB data
    total_pnl = sum(t.get("pnl", 0) for t in real_trades)
    winners = [t for t in real_trades if t["pnl"] > 0]
    losers = [t for t in real_trades if t["pnl"] < 0]
    win_rate = round(len(winners) / len(real_trades) * 100, 1) if real_trades else 0
    avg_winner = round(sum(t["pnl"] for t in winners) / len(winners), 2) if winners else 0
    avg_loser = round(sum(t["pnl"] for t in losers) / len(losers), 2) if losers else 0
    gross_profit = sum(t["pnl"] for t in winners)
    gross_loss = abs(sum(t["pnl"] for t in losers))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0
    expectancy = round(total_pnl / len(real_trades), 2) if real_trades else 0

    stats = {
        "total_pnl": round(total_pnl, 2),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_winner": avg_winner,
        "avg_loser": avg_loser,
        "trade_expectancy": expectancy,
    }

    return {
        "stats": stats,
        "trade_count": len(trades),
        "real_trade_count": len(real_trades),
        "trades": [{
            "trade_key": f"{t.get('symbol', '')}:{t.get('account', '')}:{t.get('close_date', '')}",
            **t,
        } for t in trades[:500]],
    }


def risk():
    rm = _load_json(STATE_DIR / "risk_management.json") or {}
    stops = _load_json(STATE_DIR / "stops.json") or {}
    positions = rm.get("positions", [])
    # Enrich with live prices from holdings if risk prices are $0
    holdings = _load_json(STATE_DIR / "holdings.json") or {}
    h_prices = {}
    for h in holdings.get("holdings", []):
        sym = h.get("symbol", "")
        if sym and h.get("price", 0) > 0:
            h_prices[sym] = h["price"]
    # Also try enrichment cache
    enrich = _load_json(STATE_DIR / "ticker_enrichment_cache.json") or {}
    for p in positions:
        sym = p.get("symbol", "")
        if not p.get("current_price") or p["current_price"] == 0:
            p["current_price"] = h_prices.get(sym, 0)
        if not p.get("current_price") or p["current_price"] == 0:
            ec = enrich.get(sym, {})
            if isinstance(ec, dict) and ec.get("price", 0) > 0:
                p["current_price"] = ec["price"]
        # Recompute distance_pct and max_loss with live price
        if p.get("current_price", 0) > 0 and p.get("stop_price"):
            dist = ((p["current_price"] - p["stop_price"]) / p["current_price"]) * 100
            p["distance_pct"] = round(dist, 1)
            shares = p.get("market_value", 0) / p["current_price"] if p["current_price"] > 0 else 0
            p["max_loss"] = round(shares * (p["current_price"] - p["stop_price"]), 0) if shares > 0 else p.get("max_loss", 0)
    # Load stop confirmations for enrichment
    conf_rows = _db_query("SELECT symbol, account, stop_status, stop_confirmed, stop_price_confirmed, stop_confirmed_at, reminder_count FROM stop_confirmations") or []
    conf_map = {}
    for cr in conf_rows:
        conf_map[(cr.get("symbol",""), cr.get("account",""))] = {
            "stop_conf_status": cr.get("stop_status", "unknown"),
            "stop_confirmed": cr.get("stop_confirmed", False),
            "stop_price_confirmed": float(cr["stop_price_confirmed"]) if cr.get("stop_price_confirmed") else None,
            "stop_confirmed_at": str(cr["stop_confirmed_at"])[:16] if cr.get("stop_confirmed_at") else None,
            "reminder_count": cr.get("reminder_count", 0),
        }
    return {
        "portfolio_heat_pct": rm.get("portfolio_heat_pct", 0),
        "total_risk_dollars": rm.get("total_risk_dollars", 0),
        "pct_protected": rm.get("pct_protected", 0),
        "total_protected_mv": rm.get("total_protected_mv", 0),
        "total_unprotected_mv": rm.get("total_unprotected_mv", 0),
        "position_count": len(positions),
        "positions": [{
            "symbol": p.get("symbol", ""), "market_value": p.get("market_value", 0),
            "account": p.get("account", ""),
            "stop_price": p.get("stop_price"), "current_price": p.get("current_price") or p.get("price", 0),
            "distance_pct": p.get("distance_pct"), "max_loss": p.get("max_loss") or p.get("max_loss_dollar", 0),
            "status": p.get("status", ""), "triggered": p.get("triggered", False),
            "has_stop": bool(p.get("stop_price")),
            "rsi": p.get("rsi"), "day_change_pct": p.get("day_change_pct"),
            "distance_to_stop_pct": p.get("distance_to_stop_pct") or p.get("distance_pct"),
            **(conf_map.get((p.get("symbol",""), p.get("account","")), {})),
        } for p in positions],
        "stops": {sym: {"stop_price": v.get("stop_price") or v.get("stop"), "triggered": v.get("triggered", False)}
                  for sym, v in stops.items() if isinstance(v, dict)},
        # Escalation lane
        "escalation": {
            "danger": [{"symbol": p.get("symbol",""), "max_loss": p.get("max_loss",0), "distance_pct": p.get("distance_pct",0), "account": p.get("account","")}
                       for p in positions if p.get("status") in ("TRIGGERED", "DANGER")][:4],
            "warning": [{"symbol": p.get("symbol",""), "max_loss": p.get("max_loss",0), "distance_pct": p.get("distance_pct",0), "account": p.get("account","")}
                        for p in positions if p.get("status") == "WARNING"][:4],
            "unprotected": [{"symbol": p.get("symbol",""), "market_value": p.get("market_value",0), "account": p.get("account","")}
                            for p in positions if not p.get("stop_price") and not p.get("protected")][:4],
        },
    }


def tax_lots():
    lots = _load_json(STATE_DIR / "tax_lots.json") or {}
    # Build price map from holdings for current_value computation
    holdings = _load_json(STATE_DIR / "holdings.json") or {}
    price_map = {}
    for h in holdings.get("holdings", []):
        sym = h.get("symbol", "")
        if sym and h.get("price", 0) > 0:
            price_map[sym] = h["price"]
    # Also try enrichment cache
    enrich = _load_json(STATE_DIR / "ticker_enrichment_cache.json") or {}
    for sym, ec in enrich.items():
        if isinstance(ec, dict) and sym not in price_map and ec.get("price", 0) > 0:
            price_map[sym] = ec["price"]

    flat = []
    seen = set()
    for key, lot_list in lots.items():
        if not isinstance(lot_list, list):
            continue
        for lot in lot_list:
            # Skip closed lots (shares_remaining = 0 or closed = True)
            shares_rem = lot.get("shares_remaining")
            if shares_rem is not None and shares_rem <= 0:
                continue
            if lot.get("closed"):
                continue
            shares = lot.get("shares", 0)
            if shares <= 0:
                continue

            symbol = lot.get("symbol", key.split(":")[0])
            account = lot.get("account", key.split(":")[-1] if ":" in key else "")
            cost_per = lot.get("cost_per_share", 0)
            cost_basis = lot.get("total_cost") or lot.get("cost_basis") or (cost_per * shares)
            current_price = price_map.get(symbol, 0)
            current_value = shares * current_price
            # If price is 0 but we have cost basis, it's a worthless security — loss = full basis
            unrealized_gain = current_value - cost_basis if (current_price > 0 or cost_basis > 0) else 0
            gain_pct = (unrealized_gain / cost_basis * 100) if cost_basis > 0 and current_price > 0 else 0

            # Determine holding period from lot_date
            lot_date = lot.get("lot_date") or lot.get("acquired", "")
            holding_period = "unknown"
            if lot_date:
                try:
                    from datetime import datetime, date
                    ld = datetime.strptime(lot_date[:10], "%Y-%m-%d").date()
                    days_held = (date.today() - ld).days
                    holding_period = "long" if days_held > 365 else "short"
                except Exception:
                    pass

            # Dedup key to avoid showing identical lots
            dk = f"{symbol}:{account}:{lot_date}:{shares}"
            if dk in seen:
                continue
            seen.add(dk)

            flat.append({
                "symbol": symbol, "account": account,
                "shares": shares, "cost_basis": round(cost_basis, 2),
                "current_value": round(current_value, 2),
                "unrealized_gain": round(unrealized_gain, 2),
                "gain_pct": round(gain_pct, 1),
                "acquired": lot_date,
                "holding_period": holding_period,
            })
    flat.sort(key=lambda x: abs(x.get("unrealized_gain", 0)), reverse=True)
    # Summary stats
    total_lots = len(flat)
    harvest = [l for l in flat if l["unrealized_gain"] < -100 and l["account"] in ("schwab_taxable", "taxable")]
    return {
        "count": total_lots,
        "lots": flat[:500],
        "harvest_candidates": len(harvest),
        "data_note": "Showing open lots only. Closed/sold lots excluded." if total_lots < 500 else None,
    }


def dividends():
    d = _load_json(STATE_DIR / "dividend_calendar.json") or {}
    payers = d.get("payers") or []
    for p in payers:
        p.setdefault("qualified", False)
        p.setdefault("safety", "watch")
    return {
        "has_data": d.get("has_data", bool(payers)),
        "payers": payers,
        "total_annual": d.get("total_annual", 0),
        "qualified_annual": d.get("qualified_annual", 0),
        "ordinary_annual": d.get("ordinary_annual", 0),
        "monthly_average": d.get("monthly_average", 0),
        "monthly_summary": d.get("monthly_summary", {}),
        "ex_div_alerts": d.get("ex_div_alerts", []),
        "last_updated": d.get("last_updated", ""),
    }


def retirement():
    r = _load_json(STATE_DIR / "retirement_roadmap.json") or {}
    div_cal = _load_json(STATE_DIR / "dividend_calendar.json") or {}
    accounts = r.get("accounts") or {}
    key_dates = r.get("key_dates") or {}
    loan = r.get("loan") or {}
    gw = r.get("golden_window") or {}
    tl = r.get("timeline") or []

    total = accounts.get("portfolio_total") or accounts.get("total") or 0
    roth = accounts.get("roth") or accounts.get("roth_balance") or 0
    traditional = accounts.get("traditional") or accounts.get("traditional_ira") or accounts.get("pre_tax") or 0
    taxable = accounts.get("taxable") or 0
    current_age = r.get("current_age", 0)
    annual_div = div_cal.get("total_annual", 0)
    gw_start = gw.get("start_age") or 68.5
    gw_conversion = gw.get("optimal_annual_conversion") or gw.get("sweet_spot_annual") or 50000
    loan_balance = loan.get("balance", 0)
    loan_days = loan.get("days_remaining") or key_dates.get("days_to_loan_deadline", 0)

    # ── Generate actionable narrative ──
    narrative_lines = []

    # Roth conversion guidance
    roth_pct = round(roth / total * 100, 1) if total else 0
    trad_pct = round(traditional / total * 100, 1) if total else 0
    narrative_lines.append(f"Portfolio: ${total:,.0f} — {trad_pct}% traditional (${traditional:,.0f}), {roth_pct}% Roth (${roth:,.0f}), taxable ${taxable:,.0f}.")

    if current_age and current_age < 62:
        years_to_gw = round(float(gw_start) - current_age, 1) if gw_start else 0
        if years_to_gw > 0:
            projected_roth = roth * (1.07 ** years_to_gw)  # 7% growth assumption
            narrative_lines.append(
                f"Golden Window starts in ~{years_to_gw} years (age {gw_start}). "
                f"At 7% growth, Roth projects to ~${projected_roth:,.0f} by then."
            )
            if gw_conversion:
                narrative_lines.append(
                    f"Optimal annual conversion: ${gw_conversion:,.0f}/year during the {gw.get('years_available', 4.5)}-year window. "
                    f"This targets converting ~${gw_conversion * float(gw.get('years_available', 4.5)):,.0f} total from traditional to Roth tax-free."
                )

    # SSDI context
    if current_age and current_age < 62:
        narrative_lines.append(
            "Current income: SSDI. Roth conversions during SSDI years benefit from lower tax bracket. "
            "Maximize conversions now while income is below standard deduction + SSDI thresholds."
        )

    # Loan urgency
    if loan_balance > 0 and loan_days > 0:
        monthly = loan.get("monthly_to_payoff", 0)
        urgency = "URGENT" if loan_days < 365 else ("MODERATE" if loan_days < 730 else "ON TRACK")
        narrative_lines.append(
            f"401k Loan: ${loan_balance:,.0f} due in {loan_days} days ({urgency}). "
            f"Monthly payment: ${monthly:,.0f}. Failure to repay triggers taxable distribution + 10% penalty if under 59.5."
        )

    # Dividend income in retirement context
    if annual_div > 0:
        monthly_div = annual_div / 12
        narrative_lines.append(
            f"Dividend income: ${annual_div:,.0f}/year (${monthly_div:,.0f}/month). "
            f"This covers {round(monthly_div / 4000 * 100, 0)}% of estimated $4,000/month retirement spending need."
        )
        qualified = div_cal.get("qualified_annual", 0)
        if qualified:
            narrative_lines.append(
                f"Qualified dividends: ${qualified:,.0f}/year — taxed at preferential long-term capital gains rates (0% if income under ~$44K)."
            )

    # Current month dividends
    current_month = _get_current_month_dividends(div_cal)
    if current_month.get("symbols"):
        narrative_lines.append(
            f"This month ({current_month['month_name']}): ${current_month['total']:,.0f} expected from {current_month['count']} positions — {', '.join(current_month['symbols'][:8])}."
        )

    return {
        "as_of": r.get("as_of", ""),
        "current_age": current_age,
        "key_dates": key_dates,
        "accounts": {
            "total": total, "roth": roth, "traditional": traditional, "taxable": taxable,
        },
        "loan": {
            "balance": loan_balance,
            "deadline": loan.get("deadline", key_dates.get("loan_deadline", "")),
            "days_remaining": loan_days,
            "monthly_to_payoff": loan.get("monthly_to_payoff", 0),
        },
        "timeline": tl,
        "golden_window": {
            "start_age": gw_start,
            "end_age": gw.get("end_age") or key_dates.get("golden_window_end", ""),
            "years_available": gw.get("years_available") or key_dates.get("years_to_golden", 0),
            "optimal_annual_conversion": gw_conversion,
            "projected_roth_at_start": gw.get("projected_roth_at_start") or roth,
            "narrative": gw.get("narrative") or "",
        },
        "dividend_income": {
            "annual": annual_div,
            "monthly_avg": round(annual_div / 12, 2) if annual_div else 0,
            "qualified_annual": div_cal.get("qualified_annual", 0),
            "current_month": current_month,
            "top_payers": [{"symbol": p.get("symbol"), "annual": p.get("annual_income"),
                            "yield_pct": p.get("yield_pct"), "safety": p.get("safety")}
                           for p in (div_cal.get("payers") or [])[:8]],
        },
        "intelligence_brief": narrative_lines,
    }


def ai_analyst():
    """GET /api/v2/ai-analyst — pre-generated AI analysis sections from daily pipeline."""
    cache = _load_json(STATE_DIR / "ai_analysis_cache.json") or {}
    sections = []
    section_keys = ["executive_summary", "deep_holdings", "dividend_strategy", "bond_strategy",
                    "ira_opportunities", "v_strategy", "defense_analysis"]
    for key in section_keys:
        content = cache.get(key)
        if content:
            sections.append({"key": key, "title": key.replace("_", " ").title(), "content": content})
    return {
        "has_data": len(sections) > 0,
        "sections": sections,
        "generated_at": cache.get("generated_at"),
        "run_type": cache.get("run_type"),
        "model": cache.get("model"),
    }


def ai_ask(body: dict):
    """POST /api/v2/ai-ask — live AI query via local Ollama."""
    _local_model = get_local_llm_model()
    question = (body.get("question") or "").strip()
    if not question:
        return 400, {"ok": False, "error": "question required"}
    context = body.get("context", "")
    # Build portfolio context from current data
    h = _load_json(STATE_DIR / "holdings.json") or {}
    totals = h.get("portfolio_totals", {})
    portfolio_ctx = f"Portfolio: ${totals.get('total_value',0):,.0f}. Heat: {totals.get('day_change_pct',0):.2f}%. "
    prompt = f"You are a portfolio analyst. Answer concisely based on this context:\n{portfolio_ctx}{context}\n\nQuestion: {question}"
    try:
        import urllib.request
        payload = json.dumps({"model": _local_model, "stream": False,
                              "messages": [{"role": "user", "content": prompt}], "think": False,
                              "options": {"temperature": 0.2, "num_predict": 500}}).encode()
        _base = get_local_llm_base_url().rstrip("/")
        req = urllib.request.Request(f"{_base}/api/chat",
                                     data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = json.loads(resp.read()).get("message", {}).get("content", "").strip()
            return 200, {"ok": True, "answer": raw, "model": _local_model, "question": question}
    except Exception as e:
        return 500, {"ok": False, "error": f"LLM unavailable: {e}"}


# ── Watchlist DB-Backed Endpoints ──────────────────────────────────────────────

def _wl_items(query: dict = None):
    """GET /api/v2/watchlist/items — DB-backed watchlist items with filters."""
    q = query or {}
    conditions = ["status <> 'removed'"]
    params = []
    if q.get("source"):
        conditions.append("source = %s")
        params.append(q["source"][0] if isinstance(q["source"], list) else q["source"])
    if q.get("bucket"):
        conditions.append("bucket = %s")
        params.append(q["bucket"][0] if isinstance(q["bucket"], list) else q["bucket"])
    if q.get("asset_type"):
        conditions.append("asset_type = %s")
        params.append(q["asset_type"][0] if isinstance(q["asset_type"], list) else q["asset_type"])
    if q.get("status"):
        conditions = [c for c in conditions if "status" not in c]
        conditions.append("status = %s")
        params.append(q["status"][0] if isinstance(q["status"], list) else q["status"])
    where = " AND ".join(conditions)
    sort = "updated_at DESC"
    if q.get("sort"):
        s = (q["sort"][0] if isinstance(q["sort"], list) else q["sort"])
        sort_map = {"score": "score DESC NULLS LAST", "symbol": "symbol", "updated": "updated_at DESC"}
        sort = sort_map.get(s, sort)

    rows = _db_query(f"""
        SELECT wi.*,
               sc.strategy_type, sc.latest_price, sc.support, sc.resistance,
               sc.ideal_entry, sc.stop_loss, sc.target_price, sc.risk_reward,
               sc.confidence as strategy_confidence, sc.account_fit,
               sc.technical_summary, sc.needs_iteration as strategy_needs_iteration,
               rc.latest_summary as research_summary, rc.latest_recommendation,
               rc.confidence as research_confidence,
               am.analysis_stage, am.maria_status, am.steph_status,
               am.risk_status, am.tax_status, am.full_chain_status,
               am.final_synthesis_status, am.required_agents, am.completed_agents,
               am.needs_iteration as maturity_needs_iteration,
               am.decision_quality_status, am.actionable as decision_actionable
        FROM watchlist_items wi
        LEFT JOIN watchlist_strategy_cards sc ON sc.symbol = wi.symbol
        LEFT JOIN watchlist_research_cards rc ON rc.symbol = wi.symbol
        LEFT JOIN watchlist_analysis_maturity am ON am.symbol = wi.symbol
        WHERE {where} ORDER BY {sort} LIMIT 200
    """, params) or []
    return {"count": len(rows), "items": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}


def _wl_summary():
    """GET /api/v2/watchlist/summary — counts by source and status."""
    by_source = _db_query("SELECT source, COUNT(DISTINCT symbol) as cnt FROM watchlist_items WHERE status <> 'removed' GROUP BY source") or []
    by_status = _db_query("SELECT status, COUNT(*) as cnt FROM watchlist_items GROUP BY status") or []
    jobs = _db_query("SELECT status, COUNT(*) as cnt FROM watchlist_agent_jobs GROUP BY status") or []
    cards = _db_query("SELECT COUNT(*) as cnt FROM watchlist_research_cards", fetch="one") or {}
    needs_iter = _db_query("SELECT COUNT(*) as cnt FROM watchlist_research_cards WHERE needs_iteration = true", fetch="one") or {}
    return {
        "by_source": {r["source"]: r["cnt"] for r in by_source},
        "by_status": {r["status"]: r["cnt"] for r in by_status},
        "jobs": {r["status"]: r["cnt"] for r in jobs},
        "total_active": sum(r["cnt"] for r in by_source),
        "research_cards": cards.get("cnt", 0),
        "needs_iteration": needs_iter.get("cnt", 0),
    }


def _wl_submit(body: dict):
    """POST /api/v2/watchlist/submit — submit symbols to agent for research."""
    symbols = body.get("symbols", [])
    agent = body.get("agent", "maria")
    request_type = body.get("request_type", "research")
    note = body.get("note", "")
    if not symbols:
        return 400, {"ok": False, "error": "symbols list required"}

    created = []
    for sym in symbols:
        job_id = f"wl-{sym.lower()}-{agent}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        ok = _db_write(
            """INSERT INTO watchlist_agent_jobs (id, symbol, requested_agent, request_type, note, status, payload)
               VALUES (%s, %s, %s, %s, %s, 'queued', %s)
               ON CONFLICT (id) DO NOTHING""",
            (job_id, sym, agent, request_type, note or None, json.dumps({"submitted_from": "api"}))
        )
        if ok:
            created.append(job_id)
            # Update item status
            _db_write("UPDATE watchlist_items SET status='queued', updated_at=now() WHERE symbol=%s AND status='active'", (sym,))
            # Event
            _db_write("INSERT INTO watchlist_events (event_type, symbol, agent, status, message) VALUES ('submitted', %s, %s, 'queued', %s)",
                      (sym, agent, f"Submitted to {agent} for {request_type}"))

    return 200, {"ok": True, "created_jobs": created, "count": len(created)}


def _wl_jobs():
    """GET /api/v2/watchlist/jobs — current agent jobs."""
    rows = _db_query("SELECT * FROM watchlist_agent_jobs ORDER BY created_at DESC LIMIT 50") or []
    return {"count": len(rows), "jobs": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}


def _wl_results():
    """GET /api/v2/watchlist/results — latest research results."""
    rows = _db_query("SELECT * FROM watchlist_agent_results ORDER BY created_at DESC LIMIT 30") or []
    return {"count": len(rows), "results": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}


def _wl_research_card(symbol: str):
    """GET /api/v2/watchlist/research-card/<symbol> — full audit cockpit with maturity."""
    sym = symbol.upper()
    card = _db_query("SELECT * FROM watchlist_research_cards WHERE symbol=%s", (sym,), fetch="one")
    strategy = _db_query("SELECT * FROM watchlist_strategy_cards WHERE symbol=%s", (sym,), fetch="one")
    maturity = _db_query("SELECT * FROM watchlist_analysis_maturity WHERE symbol=%s", (sym,), fetch="one")
    synthesis = _db_query("SELECT * FROM watchlist_final_synthesis WHERE symbol=%s", (sym,), fetch="one")
    items = _db_query("SELECT source, bucket, status, score, asset_type FROM watchlist_items WHERE symbol=%s", (sym,))
    # Full narratives, not just summaries
    results = _db_query("""
        SELECT agent, summary, full_narrative, recommendation, confidence,
               reason_codes, model_used, created_at, completed_at
        FROM watchlist_agent_results WHERE symbol=%s ORDER BY created_at DESC LIMIT 20
    """, (sym,))
    events = _db_query("SELECT event_type, status, message, created_at FROM watchlist_events WHERE symbol=%s ORDER BY created_at DESC LIMIT 30", (sym,))

    # Build maturity summary
    maturity_summary = None
    if maturity:
        m = {k: _json_clean(v) for k, v in maturity.items()}
        required = m.get("required_agents") or []
        completed = m.get("completed_agents") or []
        missing = m.get("missing_agents") or [a for a in required if a not in completed]
        maturity_summary = {
            "analysis_stage": m.get("analysis_stage", "raw_data_only"),
            "escalation_policy": m.get("escalation_policy"),
            "required_agents": required,
            "completed_agents": completed,
            "missing_agents": missing,
            "agent_statuses": {
                "maria": m.get("maria_status", "not_required"),
                "steph": m.get("steph_status", "not_required"),
                "risk": m.get("risk_status", "not_required"),
                "tax": m.get("tax_status", "not_required"),
                "full_chain": m.get("full_chain_status", "not_required"),
            },
            "final_synthesis_status": m.get("final_synthesis_status", "pending"),
            "needs_iteration": m.get("needs_iteration", True),
            "iteration_reason": m.get("iteration_reason"),
            "last_completed_agent": m.get("last_completed_agent"),
            "last_completed_at": m.get("last_completed_at"),
        }

    # Account-level holdings
    holdings_data = _load_json(STATE_DIR / "holdings.json") or {}
    acct_summaries = holdings_data.get("account_summaries", {})
    acct_display = {aid: info.get("display_name", aid) for aid, info in acct_summaries.items()}
    total_portfolio = sum(info.get("total_value", 0) for info in acct_summaries.values())
    sym_positions = [h for h in holdings_data.get("holdings", []) if h.get("symbol") == sym]

    account_holdings = []
    total_shares = 0
    total_mv = 0
    for h in sym_positions:
        aid = h.get("account_id") or h.get("account", "unknown")
        shares = float(h.get("shares", 0) or 0)
        mv = float(h.get("market_value", 0) or 0)
        total_shares += shares
        total_mv += mv
        account_holdings.append({
            "account_id": aid,
            "account_name": acct_display.get(aid, aid),
            "account_type": h.get("account_type") or _infer_account_type(aid),
            "shares": round(shares, 4),
            "market_value": round(mv, 2),
            "cost_basis": round(float(h.get("cost_basis", 0) or 0), 2) if h.get("cost_basis") else None,
            "gain_loss": round(float(h.get("gain_loss", 0) or 0), 2) if h.get("gain_loss") is not None else None,
            "gain_loss_pct": round(float(h.get("gain_loss_pct", 0) or 0), 2) if h.get("gain_loss_pct") is not None else None,
        })

    # Alert events for this symbol
    alerts = _db_query("""
        SELECT id, alert_type, severity, raw_text, price, stop_price, gap_pct,
               data_quality_status, requires_agent_review, created_at
        FROM alert_events WHERE symbol = %s ORDER BY created_at DESC LIMIT 20
    """, (sym,)) or []

    # Data quality warnings
    dq_blockers = [a for a in alerts if a.get("data_quality_status") not in ("valid", "unknown", None)]

    # Income profile
    income_profile = _db_query("SELECT * FROM income_asset_profiles WHERE symbol=%s", (sym,), fetch="one")
    income_goals = _db_query("SELECT * FROM portfolio_income_goals LIMIT 1", fetch="one")
    income_data = None
    if income_profile:
        ip = {k: _json_clean(v) for k, v in income_profile.items()}
        ig = {k: _json_clean(v) for k, v in income_goals.items()} if income_goals else {}
        income_data = {
            "layer": ip.get("layer_id"),
            "annual_income": ip.get("annual_income"),
            "yield_pct": ip.get("dividend_yield_pct"),
            "forward_yield_pct": ip.get("forward_yield_pct"),
            "yield_on_cost_pct": ip.get("yield_on_cost_pct"),
            "dividend_growth_5yr_pct": ip.get("dividend_growth_5yr_pct"),
            "payout_safety": ip.get("payout_safety"),
            "income_reliability": ip.get("income_reliability"),
            "preferred_account": ip.get("preferred_account"),
            "expense_ratio_pct": ip.get("expense_ratio_pct"),
            "portfolio_income_pct": ip.get("portfolio_income_pct"),
            "income_goal_contribution_pct": ip.get("income_goal_contribution_pct"),
            "target_income": ig.get("target_income"),
            "minimum_income": ig.get("minimum_income_target"),
        }

    # Decision QA (live assessment)
    try:
        import sys as _sys
        _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from decision_qa import assess_symbol
        qa = assess_symbol(sym)
    except Exception as _qa_err:
        import traceback
        traceback.print_exc()
        qa = {"decision_quality_status": "pending", "actionable": False,
              "human_review_required": False, "conflicts_detected": [],
              "gating_reasons": [], "missing_agents": []}

    return {
        "symbol": sym,
        "card": {k: _json_clean(v) for k, v in card.items()} if card else None,
        "strategy": {k: _json_clean(v) for k, v in strategy.items()} if strategy else None,
        "maturity": maturity_summary,
        "synthesis": {k: _json_clean(v) for k, v in synthesis.items()} if synthesis else None,
        "decision_qa": {
            "status": qa["decision_quality_status"],
            "actionable": qa["actionable"],
            "human_review_required": qa["human_review_required"],
            "conflicts": qa["conflicts_detected"],
            "gating_reasons": qa["gating_reasons"],
            "missing_agents": qa.get("missing_agents", []),
        },
        "holdings": {
            "accounts": account_holdings,
            "total_shares": round(total_shares, 4),
            "total_market_value": round(total_mv, 2),
            "portfolio_weight": round(total_mv / total_portfolio * 100, 2) if total_portfolio > 0 else 0,
        } if account_holdings else None,
        "items": [{k: _json_clean(v) for k, v in r.items()} for r in (items or [])],
        "results": [{k: _json_clean(v) for k, v in r.items()} for r in (results or [])],
        "events": [{k: _json_clean(v) for k, v in r.items()} for r in (events or [])],
        "alerts": [{k: _json_clean(v) for k, v in r.items()} for r in alerts],
        "income": income_data,
        "strategy_rules": ({k: _json_clean(v) for k, v in (_db_query("SELECT * FROM strategy_rule_evaluations WHERE symbol=%s", (sym,), fetch="one") or {}).items()} or None),
        "data_quality_warned": len(dq_blockers) > 0,
        "data_quality_issues": [{k: _json_clean(v) for k, v in r.items()} for r in dq_blockers],
    }


def _wl_debug():
    """GET /api/v2/watchlist/debug — DB row counts and last events."""
    tables = {}
    for t in ['watchlist_items', 'watchlist_agent_jobs', 'watchlist_agent_results', 'watchlist_research_cards', 'watchlist_events', 'watchlist_analysis_maturity', 'watchlist_strategy_cards', 'watchlist_final_synthesis']:
        row = _db_query(f"SELECT COUNT(*) as cnt FROM {t}", fetch="one") or {}
        tables[t] = row.get("cnt", 0)
    last_events = _db_query("SELECT event_type, symbol, status, message, created_at FROM watchlist_events ORDER BY created_at DESC LIMIT 20") or []
    return {
        "tables": tables,
        "last_events": [{k: _json_clean(v) for k, v in r.items()} for r in last_events],
    }


def _alerts(query: dict = None):
    """GET /api/v2/alerts — query alert events."""
    q = query or {}
    conditions = []
    params = []

    sym = (q.get("symbol", [None])[0] if isinstance(q.get("symbol"), list) else q.get("symbol"))
    if sym:
        conditions.append("symbol = %s")
        params.append(sym.upper())
    atype = (q.get("alert_type", [None])[0] if isinstance(q.get("alert_type"), list) else q.get("alert_type"))
    if atype:
        conditions.append("alert_type = %s")
        params.append(atype)
    sev = (q.get("severity", [None])[0] if isinstance(q.get("severity"), list) else q.get("severity"))
    if sev:
        conditions.append("severity = %s")
        params.append(sev)
    dq = (q.get("data_quality_status", [None])[0] if isinstance(q.get("data_quality_status"), list) else q.get("data_quality_status"))
    if dq:
        conditions.append("data_quality_status = %s")
        params.append(dq)

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    rows = _db_query(f"SELECT * FROM alert_events{where} ORDER BY created_at DESC LIMIT 100", params) or []
    return {"count": len(rows), "alerts": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}


def _alex_recent():
    """GET /api/v2/alex/recent — latest Alex analyses + top recommendations."""
    rows = _db_query("""
        SELECT symbol, strategy_type, severity, payload, created_at
        FROM portfolio_intelligence_events
        WHERE event_type = 'alex_analysis'
        ORDER BY created_at DESC LIMIT 15
    """) or []
    analyses = []
    for r in rows:
        p = r.get("payload") or {}
        if isinstance(p, str):
            import json as _j
            try: p = _j.loads(p)
            except Exception: p = {}
        analyses.append({
            "symbol": r.get("symbol"),
            "strategy_type": r.get("strategy_type"),
            "severity": r.get("severity"),
            "provider": p.get("provider"),
            "weight": p.get("weight"),
            "pnl": p.get("pnl"),
            "trigger": p.get("trigger"),
            "created_at": _json_clean(r.get("created_at")),
        })
    return {"analyses": analyses, "total": len(analyses)}


def _agents_summary():
    """GET /api/v2/agents/summary — cross-agent activity summary."""
    agent_counts = _db_query("""
        SELECT agent, count(*) as total,
               count(CASE WHEN recommendation IN ('BUY','ADD','STRONG_BUY') THEN 1 END) as buy_count,
               count(CASE WHEN recommendation IN ('SELL','TRIM','REDUCE') THEN 1 END) as sell_count,
               count(CASE WHEN recommendation IN ('HOLD','NEUTRAL') THEN 1 END) as hold_count,
               avg(confidence) as avg_confidence,
               max(created_at) as latest
        FROM watchlist_agent_results
        GROUP BY agent ORDER BY total DESC
    """) or []
    handoff_counts = _db_query("""
        SELECT from_agent, to_agent, count(*) as cnt
        FROM agent_handoffs
        WHERE from_agent NOT IN ('user','system')
        GROUP BY from_agent, to_agent ORDER BY cnt DESC LIMIT 10
    """) or []
    agents_out = [{k: _json_clean(v) for k, v in r.items()} for r in agent_counts]
    agent_names = {a.get('agent', '') for a in agents_out}

    # Add pipeline agents that don't write to watchlist_agent_results
    extra_agents = [
        {"agent": "scalp_critic", "display": "Scalp Critic (Iris)", "type": "trade_ai",
         "total": 0, "buy_count": 0, "sell_count": 0, "hold_count": 0, "avg_confidence": None,
         "latest": None, "description": "Post-Trade-AI inline critic: catalyst validation, reverse split detection, decision override"},
        {"agent": "social_scalp", "display": "Social Scalp Scanner", "type": "trade_ai",
         "total": 0, "buy_count": 0, "sell_count": 0, "hold_count": 0, "avg_confidence": None,
         "latest": None, "description": "Pre-market social mention scanner: GO/WAIT/AVOID from social signals"},
        {"agent": "iris", "display": "Iris Intelligence Librarian", "type": "intelligence",
         "total": 0, "buy_count": 0, "sell_count": 0, "hold_count": 0, "avg_confidence": None,
         "latest": None, "description": "Source integrity guardian: taxonomy, hygiene, RAG coverage, catalyst verification"},
        {"agent": "aegis", "display": "Aegis Portfolio Intelligence", "type": "surveillance",
         "total": 0, "buy_count": 0, "sell_count": 0, "hold_count": 0, "avg_confidence": None,
         "latest": None, "description": "Portfolio surveillance, covered calls, rotation alternatives"},
    ]
    # Enrich scalp_critic with actual DB data
    critic_row = _db_query("SELECT COUNT(*) as cnt, MAX(scanned_at) as latest FROM scalp_scan_results WHERE disqualified IS NOT NULL", fetch="one")
    if critic_row:
        for ea in extra_agents:
            if ea["agent"] == "scalp_critic":
                ea["total"] = int(critic_row.get("cnt", 0))
                ea["latest"] = _json_clean(critic_row.get("latest"))
    # Enrich social_scalp
    scalp_row = _db_query("SELECT COUNT(*) as cnt, MAX(scanned_at) as latest FROM scalp_scan_results", fetch="one")
    if scalp_row:
        for ea in extra_agents:
            if ea["agent"] == "social_scalp":
                ea["total"] = int(scalp_row.get("cnt", 0))
                ea["latest"] = _json_clean(scalp_row.get("latest"))
    # Enrich iris
    iris_row = _db_query("SELECT COUNT(*) as cnt, MAX(created_at) as latest FROM iris_run_log", fetch="one")
    if iris_row:
        for ea in extra_agents:
            if ea["agent"] == "iris":
                ea["total"] = int(iris_row.get("cnt", 0))
                ea["latest"] = _json_clean(iris_row.get("latest"))

    for ea in extra_agents:
        if ea["agent"] not in agent_names:
            agents_out.append(ea)

    return {
        "agents": agents_out,
        "handoffs": [{k: _json_clean(v) for k, v in r.items()} for r in handoff_counts],
    }


def _social_api_status():
    """GET /api/v2/social/status — which social APIs are configured."""
    import sys as _sys
    _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from social_monitor import check_api_status
    status = check_api_status()
    post_count = _db_query("SELECT count(*) as cnt FROM social_posts", fetch="one") or {}
    return {"apis": status, "total_posts": post_count.get("cnt", 0)}


def _agent_health():
    """GET /api/v2/agent-health — Agent system health: last run, avg confidence, escalation rate."""
    agents_data = _db_query("""
        SELECT agent,
               count(*) as total_analyses,
               AVG(confidence) as avg_confidence,
               MAX(created_at) as last_run,
               SUM(CASE WHEN confidence < 0.5 THEN 1 ELSE 0 END) as low_conf_count
        FROM watchlist_agent_results
        WHERE created_at > NOW() - INTERVAL '30 days'
        GROUP BY agent ORDER BY agent
    """) or []
    escalations = _db_query("""
        SELECT count(*) as cnt FROM agent_handoffs
        WHERE escalated=TRUE AND created_at > NOW() - INTERVAL '7 days'
    """) or [{"cnt": 0}]
    pending_proposals = _db_query("SELECT count(*) as cnt FROM watchlist_proposals WHERE status='proposed'") or [{"cnt": 0}]
    pending_instructions = _db_query("SELECT count(*) as cnt FROM trade_instructions WHERE status='pending'") or [{"cnt": 0}]
    outcomes = _db_query("""
        SELECT count(*) as total,
               SUM(CASE WHEN outcome_score > 0 THEN 1 ELSE 0 END) as correct,
               SUM(CASE WHEN outcome_score < 0 THEN 1 ELSE 0 END) as wrong
        FROM decision_outcomes WHERE outcome_score IS NOT NULL AND evaluated_at > NOW() - INTERVAL '30 days'
    """) or [{"total": 0, "correct": 0, "wrong": 0}]
    lessons = _db_query("SELECT config FROM agent_intelligence_rules WHERE rule_type='outcome_lessons' AND rule_key='latest'") or []
    lesson_text = ""
    if lessons and lessons[0].get("config"):
        cfg = lessons[0]["config"]
        if isinstance(cfg, str):
            import json as _j
            cfg = _j.loads(cfg)
        lesson_text = cfg.get("text", "")

    return {
        "agents": [{k: _json_clean(v) for k, v in a.items()} for a in agents_data],
        "escalations_7d": escalations[0].get("cnt", 0),
        "pending_proposals": pending_proposals[0].get("cnt", 0),
        "pending_instructions": pending_instructions[0].get("cnt", 0),
        "outcome_accuracy": {
            "total": outcomes[0].get("total", 0),
            "correct": outcomes[0].get("correct", 0),
            "wrong": outcomes[0].get("wrong", 0),
        },
        "latest_lessons": lesson_text,
    }


def _agent_detail():
    """GET /api/v2/agent-detail — Per-agent latest results with cross-agent dedup, escalation paths, and user context."""

    # Load user context once (holdings, tax, income gap)
    _h = _load_json(STATE_DIR / "holdings.json") or {}
    _totals = _h.get("portfolio_totals", {})
    _portfolio_value = _totals.get("total_value", 0)
    _holdings_syms = {p.get("symbol", ""): {
        "shares": float(p.get("shares", 0) or 0),
        "value": float(p.get("market_value", 0) or 0),
        "account": p.get("account_id", ""),
        "gain_loss": float(p.get("gain_loss", 0) or 0),
    } for p in _h.get("holdings", []) if p.get("symbol")}

    _ps = _load_json(STATE_DIR / "personal_situation.json") or {}
    _ps_fields = _ps.get("fields", {})
    _user_ctx = {
        "portfolio_value": round(_portfolio_value),
        "income_gap": round(55000 - float((_load_json(STATE_DIR / "dividend_calendar.json") or {}).get("total_annual", 14285))),
        "ssdi_monthly": float(_ps_fields.get("ssdi_annual", {}).get("current", 45600)) / 12,
        "tax_bracket": int(_ps_fields.get("current_tax_bracket_pct", {}).get("current", 12)),
        "roth_ytd": float(_ps_fields.get("roth_conversion_ytd_2026", {}).get("current", 35000)),
        "bracket_room": float(_ps_fields.get("next_bracket_ceiling", {}).get("current", 94300)) - float(_ps_fields.get("ssdi_annual", {}).get("current", 45600)) - float(_ps_fields.get("schedule_c_gross", {}).get("current", 20000)),
    }

    # Track symbols already shown by higher-priority agents (dedup across agents)
    _global_shown = set()

    result = {"_user_context": _user_ctx}
    for agent_name in ['maria', 'risk_agent', 'steph', 'tax_agent']:
        # Latest 5 analyses — mix of items WITH strategy targets + most recent
        latest = _db_query("""
            (SELECT DISTINCT ON (r.symbol) r.symbol, r.recommendation, r.confidence, r.summary,
                    LEFT(r.full_narrative, 500) as narrative, r.next_action, r.created_at
             FROM watchlist_agent_results r
             JOIN watchlist_strategy_cards sc ON sc.symbol = r.symbol AND sc.stop_loss IS NOT NULL
             WHERE r.agent = %s AND r.created_at > NOW() - INTERVAL '14 days'
             ORDER BY r.symbol, r.confidence DESC LIMIT 3)
            UNION ALL
            (SELECT symbol, recommendation, confidence, summary,
                    LEFT(full_narrative, 500) as narrative, next_action, created_at
             FROM watchlist_agent_results
             WHERE agent = %s AND created_at > NOW() - INTERVAL '3 days'
             ORDER BY created_at DESC LIMIT 3)
        """, (agent_name, agent_name)) or []
        # Dedup by symbol, keep first occurrence (targets prioritized)
        _seen_syms = set()
        _deduped = []
        for r in latest:
            s = r.get("symbol") if isinstance(r, dict) else r["symbol"]
            if s not in _seen_syms:
                _seen_syms.add(s)
                _deduped.append(r)
            if len(_deduped) >= 5:
                break
        latest = _deduped

        # Recommendation distribution (30d)
        dist = _db_query("""
            SELECT recommendation, count(*) as cnt
            FROM watchlist_agent_results
            WHERE agent = %s AND created_at > NOW() - INTERVAL '30 days'
            GROUP BY recommendation ORDER BY cnt DESC
        """, (agent_name,)) or []

        # Top symbols this agent analyzed recently
        top_symbols = _db_query("""
            SELECT symbol, recommendation, confidence, created_at
            FROM watchlist_agent_results
            WHERE agent = %s AND created_at > NOW() - INTERVAL '7 days'
            ORDER BY confidence DESC LIMIT 8
        """, (agent_name,)) or []

        # Enrich latest results with strategy card + escalation + holdings context
        enriched_latest = []
        for r in latest:
            item = {k: _json_clean(v) for k, v in r.items()}
            sym = item.get("symbol")
            if not sym or sym in _global_shown:
                continue  # Cross-agent dedup
            _global_shown.add(sym)

            # Strategy card data
            sc = _db_query("""SELECT strategy_type, latest_price, support, resistance,
                stop_loss, target_price, risk_reward, account_fit,
                position_size_note, time_horizon
                FROM watchlist_strategy_cards WHERE symbol=%s LIMIT 1""", (sym,))
            if sc:
                for k2, v2 in sc[0].items():
                    item[f"sc_{k2}"] = _json_clean(v2)

            # Escalation path: which agents reviewed this symbol
            esc = _db_query("""SELECT DISTINCT agent FROM watchlist_agent_results
                WHERE symbol=%s AND created_at > NOW() - INTERVAL '14 days'
                ORDER BY agent""", (sym,))
            item["reviewed_by"] = [e["agent"] for e in esc] if esc else [agent_name]

            # Holdings context: does John own this?
            h = _holdings_syms.get(sym)
            if h:
                item["held"] = True
                item["held_shares"] = h["shares"]
                item["held_value"] = round(h["value"])
                item["held_account"] = h["account"]
                item["held_gain_loss"] = round(h["gain_loss"])
            else:
                item["held"] = False

            enriched_latest.append(item)

        result[agent_name] = {
            "latest": enriched_latest,
            "distribution": [{k: _json_clean(v) for k, v in r.items()} for r in dist],
            "top_symbols": [{k: _json_clean(v) for k, v in r.items()} for r in top_symbols],
        }

    # ── Aegis: overnight surveillance data ──────────────────────────────
    aegis_items = _db_query("""
        SELECT symbol, event_type, severity, source, LEFT(payload::text, 300) as detail, created_at
        FROM portfolio_intelligence_events
        WHERE created_at > NOW() - INTERVAL '24 hours'
        ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
                 created_at DESC LIMIT 8
    """) or []
    # Overnight stops/triggers from risk
    risk_data = _db_query("""
        SELECT symbol, current_price, stop_price, distance_pct, status
        FROM risk_positions WHERE status IN ('TRIGGERED', 'DANGER')
        ORDER BY CASE status WHEN 'TRIGGERED' THEN 1 ELSE 2 END LIMIT 5
    """) or []
    # Macro snapshot
    macro = _db_query("""SELECT series_id, series_name, value, observation_date
        FROM fred_economic_series ORDER BY series_id, observation_date DESC""") or []

    result["aegis"] = {
        "latest": [{k: _json_clean(v) for k, v in e.items()} for e in aegis_items] if aegis_items else [],
        "risk_alerts": [{k: _json_clean(v) for k, v in r.items()} for r in risk_data] if risk_data else [],
        "macro": [{k: _json_clean(v) for k, v in m.items()} for m in macro],
        "distribution": [],
        "top_symbols": [],
        "overnight_healthy": len(aegis_items) == 0 and len(risk_data) == 0,
    }

    return result


def _autonomy_progress():
    """GET /api/v2/autonomy-progress — Learning curve, proposal acceptance, weekly lessons."""
    # Weekly learning curve: confidence trend over 4 weeks
    learning_curve = _db_query("""
        SELECT date_trunc('week', created_at)::date as week,
               AVG(confidence) as avg_conf,
               count(*) as analyses
        FROM watchlist_agent_results
        WHERE created_at > NOW() - INTERVAL '4 weeks'
        GROUP BY date_trunc('week', created_at)
        ORDER BY week
    """) or []

    # Proposal acceptance rate by week
    proposal_rate = _db_query("""
        SELECT date_trunc('week', COALESCE(reviewed_at, created_at))::date as week,
               SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) as approved,
               SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) as rejected,
               count(*) as total
        FROM watchlist_proposals
        WHERE created_at > NOW() - INTERVAL '4 weeks'
        GROUP BY date_trunc('week', COALESCE(reviewed_at, created_at))
        ORDER BY week
    """) or []

    # Debates this week
    debates = _db_query("""
        SELECT count(*) as cnt,
               AVG(consensus_score) as avg_consensus
        FROM agent_debate_log
        WHERE created_at > NOW() - INTERVAL '7 days'
    """) or [{"cnt": 0, "avg_consensus": None}]

    # Latest lessons text
    lessons = _db_query("SELECT config FROM agent_intelligence_rules WHERE rule_type='outcome_lessons' AND rule_key='latest'") or []
    lesson_text = ""
    if lessons and lessons[0].get("config"):
        cfg = lessons[0]["config"]
        if isinstance(cfg, str):
            import json as _j2
            cfg = _j2.loads(cfg)
        lesson_text = cfg.get("text", "")

    # Content embeddings count
    embeddings = _db_query("SELECT count(*) as cnt FROM content_embeddings") or [{"cnt": 0}]

    return {
        "learning_curve": [{k: _json_clean(v) for k, v in r.items()} for r in learning_curve],
        "proposal_acceptance": [{k: _json_clean(v) for k, v in r.items()} for r in proposal_rate],
        "debates_7d": {"count": debates[0].get("cnt", 0), "avg_consensus": _json_clean(debates[0].get("avg_consensus"))},
        "latest_lessons": lesson_text,
        "content_embeddings": embeddings[0].get("cnt", 0),
        "maturity_score": _compute_maturity(learning_curve, proposal_rate, embeddings[0].get("cnt", 0),
                                            debates[0].get("cnt", 0), lesson_text),
    }


def _compute_maturity(learning_curve, proposals, embedding_count, debate_count, lessons):
    """Compute live system maturity score (0-100%). Measures how autonomous the system is."""
    score = 0
    # Data sources (9 active = 15 pts)
    score += 15
    # Embedding coverage (667 items = 10 pts)
    score += min(10, int(embedding_count / 67))
    # Agent analyses (200+ = 10 pts)
    total_analyses = sum(w.get("analyses", 0) for w in learning_curve) if learning_curve else 0
    score += min(10, int(total_analyses / 20))
    # Confidence trend (avg > 0.5 = 10 pts)
    if learning_curve:
        avg = sum(float(w.get("avg_conf", 0) or 0) for w in learning_curve) / len(learning_curve)
        score += min(10, int(avg * 20))
    # Proposals reviewed (any decisions = 10 pts)
    total_decisions = sum(int(p.get("approved", 0) or 0) + int(p.get("rejected", 0) or 0) for p in proposals) if proposals else 0
    score += min(10, total_decisions * 2)
    # Debates active (5 pts)
    score += min(5, debate_count)
    # Outcome lessons (5 pts)
    score += 5 if lessons else 0
    # FRED live (5 pts)
    fred = _db_query("SELECT count(*) as cnt FROM fred_economic_series") or [{"cnt": 0}]
    score += 5 if fred[0].get("cnt", 0) > 0 else 0
    # Learning loop (feedback log entries = 5 pts)
    fb = _db_query("SELECT count(*) as cnt FROM agent_feedback_log") or [{"cnt": 0}]
    score += min(5, fb[0].get("cnt", 0))
    # Capped at 100
    return min(100, score)


def _search_sources_status():
    """GET /api/v2/search-sources — Status of all search/news sources."""
    sources = {}
    # Yahoo RSS
    yahoo = _db_query("SELECT count(*) as cnt, MAX(created_at) as last FROM news_articles WHERE source ILIKE '%yahoo%'") or [{}]
    sources["yahoo_rss"] = {"active": (yahoo[0].get("cnt", 0) or 0) > 0, "articles": yahoo[0].get("cnt", 0), "last": _json_clean(yahoo[0].get("last"))}
    # Google News RSS
    google = _db_query("SELECT count(*) as cnt, MAX(created_at) as last FROM news_articles WHERE source NOT ILIKE '%yahoo%' AND source NOT ILIKE '%finnhub%'") or [{}]
    sources["google_news"] = {"active": (google[0].get("cnt", 0) or 0) > 0, "articles": google[0].get("cnt", 0), "last": _json_clean(google[0].get("last"))}
    # Finnhub
    finnhub = _db_query("SELECT count(*) as cnt, MAX(created_at) as last FROM news_articles WHERE source ILIKE '%finnhub%'") or [{}]
    sources["finnhub"] = {"active": (finnhub[0].get("cnt", 0) or 0) > 0, "articles": finnhub[0].get("cnt", 0), "last": _json_clean(finnhub[0].get("last"))}
    # Brave Search
    brave_key = ""
    try:
        for line in PROJECT_ROOT.joinpath(".env").read_text().splitlines():
            if line.startswith("BRAVE_SEARCH_API_KEY="):
                brave_key = line.split("=", 1)[1].strip()
    except Exception:
        pass
    brave_today = _db_query("SELECT count(*) as cnt FROM content_embeddings WHERE source_type='brave_cache' AND created_at > CURRENT_DATE") or [{"cnt": 0}]
    sources["brave_search"] = {"active": False, "status": "402 — needs $5 credit", "key_present": bool(brave_key),
                               "calls_today": brave_today[0].get("cnt", 0), "daily_limit": 5}
    # YouTube
    yt = _db_query("SELECT count(*) as cnt FROM youtube_transcripts") or [{"cnt": 0}]
    sources["youtube"] = {"active": True, "transcripts": yt[0].get("cnt", 0)}
    # FRED
    fred = _db_query("SELECT count(*) as cnt FROM fred_economic_series") or [{"cnt": 0}]
    sources["fred"] = {"active": (fred[0].get("cnt", 0) or 0) > 0, "series": fred[0].get("cnt", 0)}
    # Embeddings health
    emb = _db_query("""SELECT count(*) as total,
           SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) as with_emb,
           MAX(created_at) as last_indexed
        FROM content_embeddings""") or [{"total": 0, "with_emb": 0}]
    total_content = _db_query("SELECT (SELECT count(*) FROM news_articles) + (SELECT count(*) FROM youtube_transcripts) as total") or [{"total": 0}]
    emb_count = emb[0].get("with_emb", 0) or 0
    content_total = total_content[0].get("total", 0) or 1
    sources["embeddings"] = {
        "active": emb_count > 0,
        "indexed": emb_count,
        "total_content": content_total,
        "coverage_pct": round(emb_count / content_total * 100) if content_total > 0 else 0,
        "last_indexed": _json_clean(emb[0].get("last_indexed")),
        "model": "nomic-embed-text", "dim": 768,
    }
    # Search efficiency: % routed to free sources today
    brave_calls = brave_today[0].get("cnt", 0) or 0
    total_news_today = _db_query("SELECT count(*) as cnt FROM news_articles WHERE created_at > CURRENT_DATE") or [{"cnt": 0}]
    free_queries = (total_news_today[0].get("cnt", 0) or 0)
    total_queries = free_queries + brave_calls
    sources["_efficiency"] = {
        "brave_calls_today": brave_calls,
        "free_source_queries": free_queries,
        "free_pct": round(free_queries / max(1, total_queries) * 100),
        "fallback_chain": "DB embeddings (RAG) → YouTube transcripts → Yahoo RSS + Finnhub + Google News → Brave (paid, last resort)",
    }
    return sources


def _tax_situation():
    """GET /api/v2/tax-situation — current tax context from DB."""
    try:
        import sys as _s
        _s.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from alex_retirement_advisor import get_tax_context
        raw = get_tax_context(2026)
        # Recursively clean date/Decimal values for JSON serialization
        def _deep_clean(obj):
            if isinstance(obj, dict):
                return {k: _deep_clean(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_deep_clean(i) for i in obj]
            return _json_clean(obj)
        return _deep_clean(raw)
    except Exception as e:
        return {"error": str(e)}


def _cost_dashboard():
    """GET /api/v2/cost-dashboard — LLM spend tracking (legacy, use /api/v2/llm-spend)."""
    return _llm_spend()


def _task_detail(task_id: int):
    """GET /api/v2/task-detail/<id> — Full task context with P&L for stop-triggered items."""
    task = _db_query("SELECT * FROM john_decision_queue WHERE id=%s", (task_id,), fetch="one")
    if not task:
        return {"error": "Task not found"}
    task = {k: _json_clean(v) for k, v in task.items()}
    symbol = (task.get("symbol") or "").upper()

    # Holdings from JSON
    h_data = _load_json(STATE_DIR / "holdings.json") or {}
    sym_h = [h for h in h_data.get("holdings", []) if h.get("symbol") == symbol]

    # Stop data
    rm = _load_json(STATE_DIR / "risk_management.json") or {}
    stop_data = {}
    for p in rm.get("positions", []):
        if p.get("symbol") == symbol:
            stop_data = {"stop_price": p.get("stop_price"), "current_price": p.get("price", p.get("current_price", 0)),
                         "distance_pct": p.get("distance_pct"), "triggered": p.get("triggered", False)}
            break

    # Also try provenance for stop data fallback
    prov = task.get("provenance", {})
    if isinstance(prov, str):
        try: prov = json.loads(prov)
        except Exception: prov = {}
    if not stop_data.get("stop_price") and prov.get("stop_price"):
        stop_data = {"stop_price": prov.get("stop_price"), "current_price": prov.get("current_price", 0)}

    # Compute P&L
    pnl_summary = {}
    if sym_h:
        total_shares = sum(h.get("shares", 0) for h in sym_h)
        total_cost = sum(h.get("cost_basis", 0) for h in sym_h)
        cost_per = total_cost / total_shares if total_shares > 0 else 0
        price = sym_h[0].get("price", 0)
        stop_p = float(stop_data.get("stop_price") or 0)
        if total_shares > 0 and cost_per > 0 and price > 0:
            cur_pnl = (price - cost_per) * total_shares
            pnl_summary = {
                "entry_price": round(cost_per, 4), "current_price": round(price, 4),
                "stop_price": round(stop_p, 4) if stop_p else None,
                "total_shares": round(total_shares, 4),
                "current_pnl_dollars": round(cur_pnl, 2),
                "current_pnl_pct": round((price - cost_per) / cost_per * 100, 2),
                "stop_pnl_dollars": round((stop_p - cost_per) * total_shares, 2) if stop_p else None,
                "stop_pnl_pct": round((stop_p - cost_per) / cost_per * 100, 2) if stop_p and cost_per else None,
                "distance_to_stop_pct": round((price - stop_p) / price * 100, 2) if stop_p and price else None,
                "stop_breached": price <= stop_p if stop_p else False,
                "total_market_value": round(price * total_shares, 2),
                "total_cost": round(total_cost, 2),
                "total_annual_income": 0,
            }
        # Income from dividend calendar
        dc = _load_json(STATE_DIR / "dividend_calendar.json") or {}
        for dp in dc.get("payers", []):
            if dp.get("symbol") == symbol:
                pnl_summary["total_annual_income"] = round(dp.get("annual_income", 0), 2)
                break

    # Agent results
    agents = _db_query(
        """SELECT DISTINCT ON (agent) agent AS agent_name, recommendation, confidence AS confidence_score, summary, created_at, rag_sources_used
           FROM watchlist_agent_results WHERE symbol=%s AND created_at > NOW() - INTERVAL '14 days'
           ORDER BY agent, created_at DESC""", (symbol,)) or []

    # News
    news = _db_query(
        """SELECT title, source, relevance_score, created_at FROM news_articles
           WHERE symbol=%s AND created_at > NOW() - INTERVAL '7 days'
           ORDER BY relevance_score DESC LIMIT 5""", (symbol,)) or []

    # Data quality
    data_quality = {"all_research_more": False, "analysis_count": 0, "avg_confidence": 0,
                     "enrichment_attempted": False, "enrichment_date": None, "missing_data": []}
    if symbol:
        try:
            qr = _db_query("""SELECT COUNT(*) as cnt, AVG(confidence) as avg_c,
                                     SUM(CASE WHEN recommendation='RESEARCH_MORE' THEN 1 ELSE 0 END) as rm_cnt
                              FROM watchlist_agent_results WHERE symbol=%s AND created_at > NOW() - INTERVAL '7 days'""",
                           (symbol,), fetch="one")
            if qr:
                data_quality["analysis_count"] = qr["cnt"] or 0
                data_quality["avg_confidence"] = round(float(qr["avg_c"] or 0), 2)
                data_quality["all_research_more"] = (qr["rm_cnt"] or 0) > 0 and qr["rm_cnt"] == qr["cnt"]
        except Exception:
            pass
        # Enrichment cache info
        try:
            er = _db_query("SELECT updated_at FROM enrichment_cache WHERE symbol=%s ORDER BY updated_at DESC LIMIT 1",
                           (symbol,), fetch="one")
            if er and er.get("updated_at"):
                from datetime import datetime as _dt
                age = (_dt.now() - er["updated_at"].replace(tzinfo=None)).total_seconds() / 3600
                data_quality["enrichment_age_hours"] = round(age, 1)
                data_quality["enrichment_date"] = str(er["updated_at"])[:16]
                data_quality["enrichment_attempted"] = age < 24  # enriched in last 24h
        except Exception:
            pass
        # Check for auto-enrichment jobs (from auto_enrich_research_more)
        try:
            ae = _db_query("""SELECT created_at FROM watchlist_agent_jobs
                              WHERE symbol=%s AND submitted_from='auto_enrichment'
                              ORDER BY created_at DESC LIMIT 1""", (symbol,), fetch="one")
            if ae and ae.get("created_at"):
                data_quality["enrichment_attempted"] = True
                data_quality["enrichment_date"] = str(ae["created_at"])[:16]
        except Exception:
            pass
        # Missing data detection
        missing = []
        try:
            nc = _db_query("SELECT count(*) as n FROM news_articles WHERE symbol=%s AND created_at > NOW() - INTERVAL '30 days'",
                           (symbol,), fetch="one")
            if not nc or (nc.get("n") or 0) == 0:
                missing.append("recent news")
        except Exception:
            pass
        try:
            sc = _db_query("SELECT count(*) as n FROM sec_form4 WHERE symbol=%s", (symbol,), fetch="one")
            if not sc or (sc.get("n") or 0) == 0:
                missing.append("SEC filings")
        except Exception:
            pass
        data_quality["missing_data"] = missing

    return {
        "task": task,
        "holdings": [{k: _json_clean(v) for k, v in h.items()} for h in sym_h],
        "pnl_summary": pnl_summary,
        "stop_data": stop_data,
        "agent_results": [{k: _json_clean(v) for k, v in a.items()} for a in agents],
        "news": [{k: _json_clean(v) for k, v in n.items()} for n in news],
        "data_quality": data_quality,
    }


def _watchlist_context(symbol: str):
    """GET /api/v2/watchlist/context/<symbol> — Full symbol context for watchlist view."""
    sym = symbol.upper()

    # 1. Agent analyses (latest per agent, 14 days)
    agents = _db_query(
        """SELECT DISTINCT ON (agent)
                  agent AS agent_name, recommendation, confidence AS confidence_score,
                  summary, full_narrative, reason_codes, created_at, status
           FROM watchlist_agent_results
           WHERE symbol = %s AND created_at > NOW() - INTERVAL '14 days'
           ORDER BY agent, created_at DESC""",
        (sym,)
    ) or []

    # 2. Synthesis
    synth = _db_query(
        """SELECT recommendation, confidence, action, synthesis_narrative,
                  conflicts, unresolved, reason_codes, next_review_date,
                  decision_quality_status, created_at
           FROM watchlist_final_synthesis
           WHERE symbol = %s ORDER BY created_at DESC LIMIT 1""",
        (sym,), fetch="one"
    )

    # 3. Strategy card
    strat = _db_query(
        """SELECT strategy_type, latest_price, support, resistance,
                  stop_loss, target_price, risk_reward, account_fit,
                  thesis, time_horizon, position_size_note, created_at
           FROM watchlist_strategy_cards
           WHERE symbol = %s ORDER BY created_at DESC LIMIT 1""",
        (sym,), fetch="one"
    )

    # 4. News (14 days)
    news = _db_query(
        """SELECT title, summary, source, relevance_score,
                  sentiment, published_at
           FROM news_articles
           WHERE symbol = %s AND created_at > NOW() - INTERVAL '14 days'
           ORDER BY relevance_score DESC, created_at DESC LIMIT 8""",
        (sym,)
    ) or []

    # 5. Holdings from JSON
    h_data = _load_json(STATE_DIR / "holdings.json") or {}
    sym_h = [h for h in h_data.get("holdings", []) if h.get("symbol") == sym]

    # 6. Intelligence whiteboard
    intel = _db_query(
        """SELECT title, summary, source_type, quality_score,
                  confidence, status, days_on_board, created_at
           FROM intelligence_whiteboard
           WHERE symbol = %s
           ORDER BY quality_score DESC, created_at DESC LIMIT 5""",
        (sym,)
    ) or []

    # 7. Past outcomes
    outcomes = _db_query(
        """SELECT recommendation, price_at_decision, price_7d, price_30d,
                  outcome_score, created_at
           FROM decision_outcomes
           WHERE symbol = %s AND price_7d IS NOT NULL
           ORDER BY created_at DESC LIMIT 5""",
        (sym,)
    ) or []

    # 8. Macro context
    # 8. Macro context — parse FRED text into structured dict
    macro = {}
    try:
        from external_market_data_ingest import get_macro_context
        raw_macro = get_macro_context() or ""
        # Parse "Key: value (date)" lines into dict
        import re as _re
        for line in raw_macro.split("\n"):
            line = line.strip()
            m = _re.match(r"(.+?):\s*([\d.]+)", line)
            if m:
                key = m.group(1).strip().lower().replace(" ", "_").replace("(", "").replace(")", "")[:30]
                macro[key] = float(m.group(2))
        if not macro:
            macro = {"raw": raw_macro[:500]}
    except Exception:
        pass

    # Detect real conflicts (opposing directions, both >40% confidence)
    conflict_info = _detect_real_conflict(agents)

    # 9. Symbol master data for trade_type + strategy card
    sym_master = _db_query(
        """SELECT strategy_type, escalation_policy, account_fit, ideal_entry,
                  stop_loss, target_price, risk_reward, support, resistance,
                  latest_price
           FROM watchlist_symbol_master WHERE symbol = %s""",
        (sym,), fetch="one"
    ) or {}

    # 9b. Trade type — check strategy_cards first, then symbol_master
    st = (strat or {}).get("strategy_type", "") or (sym_master.get("strategy_type") or "")
    th = (strat or {}).get("time_horizon", "") or ""
    ep = (sym_master.get("escalation_policy") or "")

    if any(x in st.lower() for x in ['income', 'dividend', 'yield', 'bdc', 'reit']):
        trade_type = "INCOME"
    elif any(x in st.lower() for x in ['swing', 'momentum', 'speculative', 'scalp']):
        trade_type = "SWING"
    elif "short" in st.lower() or "short" in th.lower():
        trade_type = "SHORT"
    elif any(x in st.lower() for x in ['growth', 'growth_etf', 'value', 'core', 'long_term', 'defense', 'thesis']):
        trade_type = "LONG"
    elif any(x in ep.lower() for x in ['income', 'dividend']):
        trade_type = "INCOME"
    elif any(x in ep.lower() for x in ['growth', 'long', 'defense', 'thesis']):
        trade_type = "LONG"
    else:
        trade_type = "WATCH"

    # 10. Sector comparison — ticker vs sector ETF
    sector_comparison = None
    sector_news_items = []
    try:
        ec = _load_json(STATE_DIR / "ticker_enrichment_cache.json") or {}
        sym_enrich = ec.get(sym) if isinstance(ec.get(sym), dict) else {}
        sector = sym_enrich.get("sector", "")
        SECTOR_ETFS = {
            "Healthcare": "XLV", "Technology": "XLK", "Financials": "XLF",
            "Energy": "XLE", "Industrials": "XLI", "Consumer Discretionary": "XLY",
            "Consumer Staples": "XLP", "Materials": "XLB", "Utilities": "XLU",
            "Real Estate": "XLRE", "Communication Services": "XLC",
            "Aerospace & Defense": "ITA", "Defense": "ITA",
        }
        sector_etf = SECTOR_ETFS.get(sector, "")
        ticker_perf = sym_enrich.get("perf_month", "")
        etf_perf = ""
        if sector_etf:
            etf_data = ec.get(sector_etf) if isinstance(ec.get(sector_etf), dict) else {}
            etf_perf = etf_data.get("perf_month", "")
        sector_comparison = {
            "sector": sector,
            "sector_etf": sector_etf,
            "ticker_perf_1m": ticker_perf,
            "sector_perf_1m": etf_perf,
        }
        # Sector news (last 7 days)
        if sector:
            sector_key = sector.lower().replace(" ", "_").replace("&", "")
            sn = _db_query(
                """SELECT title, source, published_at, sentiment
                   FROM news_articles
                   WHERE (strategy_type ILIKE %s OR symbol IN (
                       SELECT symbol FROM watchlist_items WHERE asset_type ILIKE %s AND status != 'removed'
                   ))
                   AND created_at > NOW() - INTERVAL '7 days'
                   ORDER BY published_at DESC LIMIT 5""",
                (f"%{sector_key}%", f"%{sector_key}%")
            ) or []
            sector_news_items = [{k: _json_clean(v) for k, v in n.items()} for n in sn]
    except Exception:
        pass

    # 11. Summary verdict — one-sentence synthesis for quick scanning
    summary_verdict = ""
    if conflict_info.get("is_conflict"):
        raw_buyers = conflict_info.get("buyers", [])
        raw_sellers = conflict_info.get("sellers", [])
        buyers = ", ".join(d["agent"] if isinstance(d, dict) else str(d) for d in raw_buyers)
        sellers = ", ".join(d["agent"] if isinstance(d, dict) else str(d) for d in raw_sellers)
        summary_verdict = f"Agent conflict: {buyers} bullish vs {sellers} bearish. {conflict_info.get('explanation', '')}"
    elif synth and synth.get("recommendation"):
        rec = synth["recommendation"]
        conf = synth.get("confidence")
        conf_str = f" ({int(float(conf)*100)}% confidence)" if conf else ""
        summary_verdict = f"Consensus: {rec}{conf_str}. {(synth.get('synthesis_narrative') or '')[:120]}"
    elif agents:
        recs = [a.get("recommendation", "?") for a in agents if a.get("recommendation")]
        summary_verdict = f"Agent views: {', '.join(recs)}. No synthesis yet."

    # Agent agreement ratio
    if agents:
        recs = [a.get("recommendation") for a in agents if a.get("recommendation")]
        from collections import Counter
        rc = Counter(recs)
        majority = rc.most_common(1)[0] if rc else ("?", 0)
        agent_agree = f"{majority[1]}/{len(recs)}"
    else:
        agent_agree = "0/0"

    return {
        "symbol": sym,
        "agent_results": [{k: _json_clean(v) for k, v in a.items()} for a in agents],
        "synthesis": {k: _json_clean(v) for k, v in synth.items()} if synth else None,
        "strategy": {k: _json_clean(v) for k, v in strat.items()} if strat else None,
        "news": [{k: _json_clean(v) for k, v in n.items()} for n in news],
        "holdings": [{k: _json_clean(v) for k, v in h.items()} for h in sym_h],
        "intel": [{k: _json_clean(v) for k, v in i.items()} for i in intel],
        "outcomes": [{k: _json_clean(v) for k, v in o.items()} for o in outcomes],
        "macro": macro,
        "conflict": conflict_info,
        "trade_type": trade_type,
        "strategy_card": {
            "trade_type": trade_type,
            "strategy_label": sym_master.get("strategy_type") or sym_master.get("escalation_policy") or (strat or {}).get("strategy_type") or "uncategorized",
            "account_fit": sym_master.get("account_fit") or (strat or {}).get("account_fit") or "",
            "ideal_entry": _json_clean(sym_master.get("ideal_entry") or (strat or {}).get("ideal_entry")),
            "stop_loss": _json_clean(sym_master.get("stop_loss") or (strat or {}).get("stop_loss")),
            "target_price": _json_clean(sym_master.get("target_price") or (strat or {}).get("target_price")),
            "risk_reward": _json_clean(sym_master.get("risk_reward") or (strat or {}).get("risk_reward")),
            "support": _json_clean(sym_master.get("support") or (strat or {}).get("support")),
            "resistance": _json_clean(sym_master.get("resistance") or (strat or {}).get("resistance")),
            "why_added": "",
            "days_watched": 0,
        },
        "sector_comparison": sector_comparison,
        "sector_news": sector_news_items,
        "summary_verdict": summary_verdict,
        "agent_agree": agent_agree,
        "in_portfolio": len(sym_h) > 0,
        "portfolio_weight": sum(float(h.get("portfolio_weight", 0) or 0) for h in sym_h),
        "portfolio_value": sum(float(h.get("market_value", 0) or 0) for h in sym_h),
    }


def _detect_real_conflict(agents: list) -> dict:
    """Detect REAL agent conflicts — not data gaps."""
    BUY_DIR = {"BUY", "ADD"}
    SELL_DIR = {"SELL", "TRIM", "AVOID"}
    SKIP = {"RESEARCH_MORE", "NEUTRAL"}

    directional = []
    for a in agents:
        rec = (a.get("recommendation") or "").upper()
        conf = float(a.get("confidence_score") or a.get("confidence") or 0)
        agent = a.get("agent_name") or a.get("agent", "")
        if rec in SKIP and conf < 0.4:
            continue  # Data gap, not a real opinion
        directional.append({"agent": agent, "rec": rec, "conf": conf})

    has_buy = any(d["rec"] in BUY_DIR and d["conf"] > 0.4 for d in directional)
    has_sell = any(d["rec"] in SELL_DIR and d["conf"] > 0.4 for d in directional)

    if has_buy and has_sell:
        buyers = [d for d in directional if d["rec"] in BUY_DIR]
        sellers = [d for d in directional if d["rec"] in SELL_DIR]
        return {
            "is_conflict": True,
            "type": "opposing_directions",
            "explanation": f"{', '.join(d['agent'] for d in buyers)} say BUY/ADD vs {', '.join(d['agent'] for d in sellers)} say TRIM/SELL — genuine disagreement on direction",
            "buyers": buyers,
            "sellers": sellers,
        }

    # Check for data gap (RESEARCH_MORE at low conf)
    data_gaps = [a for a in agents if (a.get("recommendation") or "").upper() in SKIP and float(a.get("confidence_score") or a.get("confidence") or 0) < 0.4]
    if data_gaps:
        return {
            "is_conflict": False,
            "type": "data_gap",
            "explanation": f"{', '.join(a.get('agent','') for a in data_gaps)} returned RESEARCH_MORE due to insufficient data — not a real conflict",
            "data_gaps": [{k: _json_clean(v) for k, v in g.items()} for g in data_gaps],
        }

    return {"is_conflict": False, "type": "none", "explanation": ""}


def _proposal_detail(proposal_id: int):
    """GET /api/v2/proposal-detail/<id> — Full context for one proposal."""
    # 1. The proposal + strategy card
    row = _db_query(
        """SELECT p.*, sc.thesis, sc.stop_loss as sc_stop, sc.target_price as sc_target,
                  sc.risk_reward as sc_rr, sc.account_fit as sc_account
           FROM watchlist_proposals p
           LEFT JOIN watchlist_strategy_cards sc ON sc.symbol = p.symbol
           WHERE p.id = %s""",
        (proposal_id,), fetch="one"
    )
    if not row:
        return {"error": "Proposal not found"}
    proposal = {k: _json_clean(v) for k, v in row.items()}
    symbol = proposal.get("symbol", "")

    # 2. Holdings from JSON (more reliable than DB for live positions)
    holdings_data = _load_json(STATE_DIR / "holdings.json") or {}
    sym_holdings = [h for h in holdings_data.get("holdings", []) if h.get("symbol") == symbol]
    position = {}
    if sym_holdings:
        total_shares = sum(h.get("shares", 0) for h in sym_holdings)
        total_mv = sum(h.get("market_value", 0) for h in sym_holdings)
        total_cost = sum(h.get("cost_basis", 0) for h in sym_holdings)
        total_gl = sum(h.get("gain_loss", 0) for h in sym_holdings)
        price = sym_holdings[0].get("price", 0)
        position = {
            "total_shares": round(total_shares, 4),
            "total_market_value": round(total_mv, 2),
            "total_cost_basis": round(total_cost, 2),
            "cost_per_share": round(total_cost / total_shares, 2) if total_shares > 0 else 0,
            "unrealized_pnl": round(total_gl, 2),
            "unrealized_pct": round((total_gl / total_cost * 100) if total_cost > 0 else 0, 1),
            "current_price": round(price, 2),
            "accounts": [h.get("account", "").replace("schwab_", "").replace("fidelity_", "") for h in sym_holdings],
        }
        # Income from dividend calendar
        dc = _load_json(STATE_DIR / "dividend_calendar.json") or {}
        for p_item in dc.get("payers", []):
            if p_item.get("symbol") == symbol:
                position["annual_income"] = round(p_item.get("annual_income", 0), 2)
                position["yield_pct"] = p_item.get("yield_pct", 0)
                position["income_pct_of_target"] = round(p_item.get("annual_income", 0) / 55000 * 100, 1)
                break
        # Portfolio weight
        pt = holdings_data.get("portfolio_totals", {})
        tv = pt.get("total_value", 0)
        if tv > 0:
            position["pct_of_portfolio"] = round(total_mv / tv * 100, 1)

    # 3. Agent results (last 7 days)
    agents = _db_query(
        """SELECT agent AS agent_name, recommendation, confidence AS confidence_score,
                  summary, created_at
           FROM watchlist_agent_results
           WHERE symbol = %s AND created_at > NOW() - INTERVAL '7 days'
           ORDER BY created_at DESC LIMIT 10""",
        (symbol,)
    ) or []

    # 4. Synthesis
    synth = _db_query(
        """SELECT recommendation, confidence, synthesis_narrative,
                  conflicts, decision_quality_status, created_at
           FROM watchlist_final_synthesis
           WHERE symbol = %s ORDER BY created_at DESC LIMIT 1""",
        (symbol,), fetch="one"
    )

    # 5. News
    news = _db_query(
        """SELECT title, source, relevance_score, published_at
           FROM news_articles
           WHERE symbol = %s AND created_at > NOW() - INTERVAL '7 days'
           ORDER BY relevance_score DESC LIMIT 5""",
        (symbol,)
    ) or []

    # 6. Stop data from risk_management.json
    rm = _load_json(STATE_DIR / "risk_management.json") or {}
    stop_data = {}
    for p_item in rm.get("positions", []):
        if p_item.get("symbol") == symbol:
            stop_data = {
                "stop_price": p_item.get("stop_price"),
                "current_price": p_item.get("price", p_item.get("current_price", 0)),
                "distance_pct": p_item.get("distance_pct"),
                "triggered": p_item.get("triggered", False),
                "status": p_item.get("status", ""),
            }
            break

    # 7. Past outcomes
    outcomes = _db_query(
        """SELECT recommendation, price_at_decision, price_7d, price_30d,
                  outcome_score, created_at
           FROM decision_outcomes
           WHERE symbol = %s AND price_7d IS NOT NULL
           ORDER BY created_at DESC LIMIT 3""",
        (symbol,)
    ) or []

    # 8. Compute P&L summary
    pnl_summary = {}
    if sym_holdings:
        h0 = sym_holdings[0]
        shares = float(h0.get("shares", 0))
        cost_basis = float(h0.get("cost_basis", 0))
        price = float(h0.get("price", 0))
        cost_per = round(cost_basis / shares, 4) if shares > 0 else 0
        stop_p = float(stop_data.get("stop_price", 0) or 0)
        if shares > 0 and cost_per > 0 and price > 0:
            current_pnl = (price - cost_per) * shares
            stop_pnl = (stop_p - cost_per) * shares if stop_p > 0 else None
            pnl_summary = {
                "entry_price": cost_per,
                "current_price": round(price, 4),
                "stop_price": round(stop_p, 4) if stop_p else None,
                "shares": round(shares, 4),
                "current_pnl_dollars": round(current_pnl, 2),
                "current_pnl_pct": round((price - cost_per) / cost_per * 100, 2),
                "stop_pnl_dollars": round(stop_pnl, 2) if stop_pnl is not None else None,
                "stop_pnl_pct": round((stop_p - cost_per) / cost_per * 100, 2) if stop_p and cost_per else None,
                "distance_to_stop_pct": round((price - stop_p) / price * 100, 2) if stop_p and price else None,
                "stop_breached": price <= stop_p if stop_p else False,
                "market_value": round(price * shares, 2),
                "total_cost": round(cost_per * shares, 2),
            }

    return {
        "proposal": proposal,
        "position": position,
        "pnl_summary": pnl_summary,
        "holdings": [{k: _json_clean(v) for k, v in h.items()} for h in sym_holdings],
        "agent_results": [{k: _json_clean(v) for k, v in a.items()} for a in agents],
        "synthesis": {k: _json_clean(v) for k, v in synth.items()} if synth else None,
        "news": [{k: _json_clean(v) for k, v in n.items()} for n in news],
        "stop_data": stop_data,
        "outcomes": [{k: _json_clean(v) for k, v in o.items()} for o in outcomes],
        "portfolio_value": holdings_data.get("portfolio_totals", {}).get("total_value", 0),
    }


def _iris_library_status():
    """GET /api/v2/iris/library-status — RAG + routing audit summary."""
    try:
        import sys as _s; _s.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from iris_taxonomy_agent import get_library_status
        return get_library_status()
    except Exception as e:
        return {"error": str(e)}


def _iris_stale_symbols():
    """GET /api/v2/iris/stale-symbols — Symbols not analyzed in >7 days."""
    try:
        import sys as _s; _s.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from iris_taxonomy_agent import get_stale_symbols
        return {"symbols": get_stale_symbols()}
    except Exception as e:
        return {"error": str(e)}


def _iris_content_gaps():
    """GET /api/v2/iris/content-gaps — Categories with thin content."""
    try:
        import sys as _s; _s.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from iris_taxonomy_agent import get_content_gaps
        return {"gaps": get_content_gaps()}
    except Exception as e:
        return {"error": str(e)}


def _iris_duplicates():
    """GET /api/v2/iris/duplicates — Duplicate article groups."""
    rows = _db_query("""
        SELECT LEFT(title, 80) as title, count(*) as cnt,
               array_agg(DISTINCT source) as sources, MAX(relevance_score) as best_quality
        FROM news_articles WHERE created_at > NOW() - INTERVAL '90 days' AND NOT COALESCE(is_duplicate, FALSE)
        GROUP BY LEFT(LOWER(TRIM(title)), 60)
        HAVING count(*) > 1 ORDER BY cnt DESC LIMIT 50
    """) or []
    return {"groups": [{k: _json_clean(v) for k, v in r.items()} for r in rows], "total": len(rows)}


def _iris_failures():
    """GET /api/v2/iris/failures — Recent Iris pipeline failures and errors."""
    rows = _db_query("""
        SELECT id, run_type, status, error_message, started_at, finished_at,
               symbols_processed, symbols_failed
        FROM iris_run_log
        WHERE status IN ('failed', 'partial_failure', 'error')
           OR symbols_failed > 0
        ORDER BY started_at DESC LIMIT 20
    """) or []
    return {
        "failures": [{k: _json_clean(v) for k, v in r.items()} for r in rows],
        "total": len(rows),
    }


def _iris_integrity():
    """GET /api/v2/iris/integrity — Data integrity checks for Iris content."""
    checks = []
    # Orphan transcripts (no matching channel)
    orphan_count = _db_query("""
        SELECT COUNT(*) as cnt FROM youtube_transcripts yt
        LEFT JOIN youtube_channels yc ON yc.channel_name = yt.channel_name
        WHERE yc.channel_name IS NULL
    """, fetch="one") or {}
    checks.append({"check": "orphan_transcripts", "count": int(orphan_count.get("cnt", 0)),
                    "status": "warn" if int(orphan_count.get("cnt", 0)) > 0 else "ok"})
    # Duplicate articles
    dup_count = _db_query("""
        SELECT COUNT(*) as cnt FROM (
            SELECT LEFT(LOWER(TRIM(title)), 60), count(*) as c
            FROM news_articles WHERE created_at > NOW() - INTERVAL '30 days'
            GROUP BY 1 HAVING count(*) > 1
        ) d
    """, fetch="one") or {}
    checks.append({"check": "duplicate_articles", "count": int(dup_count.get("cnt", 0)),
                    "status": "warn" if int(dup_count.get("cnt", 0)) > 10 else "ok"})
    # Stale symbols (watchlist items not analyzed in 7+ days)
    stale_count = _db_query("""
        SELECT COUNT(DISTINCT wi.symbol) as cnt
        FROM watchlist_items wi
        LEFT JOIN watchlist_agent_results war ON war.symbol = wi.symbol
            AND war.created_at > NOW() - INTERVAL '7 days'
        WHERE wi.status = 'active' AND war.id IS NULL
    """, fetch="one") or {}
    checks.append({"check": "stale_watchlist_symbols", "count": int(stale_count.get("cnt", 0)),
                    "status": "warn" if int(stale_count.get("cnt", 0)) > 5 else "ok"})
    # Missing embeddings
    embed_count = _db_query("""
        SELECT COUNT(*) as cnt FROM news_articles na
        LEFT JOIN content_embeddings ce ON ce.content_id = na.id::text AND ce.content_type = 'news'
        WHERE na.created_at > NOW() - INTERVAL '7 days' AND ce.id IS NULL
    """, fetch="one") or {}
    checks.append({"check": "missing_embeddings", "count": int(embed_count.get("cnt", 0)),
                    "status": "warn" if int(embed_count.get("cnt", 0)) > 20 else "ok"})

    overall = "ok" if all(c["status"] == "ok" for c in checks) else "warn"
    return {"checks": checks, "overall": overall}


def _iris_hygiene_status():
    """GET /api/v2/iris/hygiene-status — Hygiene pending decisions + recent actions."""
    pending = _db_query("""SELECT id, content_type, content_title, proposed_action,
                                  reason, confidence, expires_at, created_at
                           FROM iris_hygiene_pending WHERE status='pending_john'
                           ORDER BY confidence DESC, expires_at ASC LIMIT 20""") or []
    recent = _db_query("""SELECT content_type, content_title, action, reason, confidence, created_at
                          FROM iris_hygiene_log ORDER BY created_at DESC LIMIT 10""") or []
    health = _db_query("""SELECT source_type, count(*) as total,
                                 count(CASE WHEN hygiene_status='active' OR hygiene_status IS NULL THEN 1 END) as active,
                                 count(CASE WHEN hygiene_status='demoted' THEN 1 END) as demoted,
                                 count(CASE WHEN hygiene_status='archived' THEN 1 END) as archived
                          FROM intelligence_whiteboard GROUP BY source_type""") or []
    return {
        "pending_decisions": [{k: _json_clean(v) for k, v in r.items()} for r in pending],
        "recent_actions": [{k: _json_clean(v) for k, v in r.items()} for r in recent],
        "content_health": [{k: _json_clean(v) for k, v in r.items()} for r in health],
        "pending_count": len(pending),
    }


_YT_NAME_JOIN = """LEFT JOIN youtube_channels yc ON (
    yc.channel_name = yt.channel_name
    OR yc.channel_name = CASE yt.channel_name
        WHEN 'Joe F. Schmitz Jr. CFP\u00ae CKA\u00ae'          THEN 'Joe F. Schmitz Jr. CFP'
        WHEN 'ppcian'                                  THEN 'PPC Ian'
        WHEN 'Felix & Friends (Goat Academy)'          THEN 'Felix and Friends'
        WHEN 'Trader Talks: Schwab Coaching Webcasts'  THEN 'Trader Talks Schwab'
        WHEN 'Etienne Crete - Desire To TRADE'         THEN 'Desire To TRADE'
        WHEN 'Value Investing with Sven Carlin, Ph.D.' THEN 'Sven Carlin'
        ELSE yt.channel_name
    END
)"""


def _intelligence_library():
    """GET /api/v2/intelligence/library — Unified search across all intelligence."""
    q = getattr(_intelligence_library, '_query', {}) or {}
    def _qp(k, default=""):
        v = q.get(k, default)
        return (v[0] if isinstance(v, list) else v) or default

    search = _qp("q")
    source_type = _qp("source_type")
    symbol = _qp("symbol")
    limit = min(int(_qp("limit", "50")), 200)
    offset = int(_qp("offset", "0"))

    # Query each source type separately then merge
    SOURCES = [
        ("news", "SELECT id, title, symbol, strategy_type as strategy, CAST(relevance_score AS INT) as quality, source_url as url, created_at FROM news_articles"),
        ("youtube", "SELECT id, title, channel_name as symbol, content_category as strategy, quality_score as quality, url, ingested_at as created_at FROM youtube_transcripts"),
        ("agent_result", "SELECT abs(hashtext(id)) as id, COALESCE(symbol,'')||' '||COALESCE(agent,'')||': '||COALESCE(recommendation,'') as title, symbol, request_type as strategy, CAST(confidence*100 AS INT) as quality, NULL as url, created_at FROM watchlist_agent_results"),
        ("agent_synthesis", "SELECT abs(hashtext(symbol)) as id, symbol||' synthesis: '||COALESCE(recommendation,'') as title, symbol, 'synthesis' as strategy, CAST(confidence*100 AS INT) as quality, NULL as url, created_at FROM watchlist_final_synthesis"),
        ("cio_decision", "SELECT abs(hashtext(decision_id)) as id, symbol||' CIO: '||COALESCE(action,'') as title, symbol, strategy_type as strategy, CAST(confidence_raw*100 AS INT) as quality, NULL as url, created_at FROM cio_decisions"),
        ("fused_signal", "SELECT id, symbol||' signal: '||COALESCE(direction,'') as title, symbol, strategy_type as strategy, CAST(confidence*100 AS INT) as quality, NULL as url, created_at FROM fused_signals"),
        ("decision_outcome", "SELECT id, symbol||' outcome: '||COALESCE(recommendation,'') as title, symbol, strategy_type as strategy, CAST(outcome_score AS INT) as quality, NULL as url, created_at FROM decision_outcomes"),
        ("sec_form4", "SELECT id, symbol||' Form 4: '||COALESCE(filer_name,'') as title, symbol, 'sec_filing' as strategy, quality_score as quality, sec_url as url, created_at FROM sec_form4"),
        ("social_post", "SELECT id, LEFT(text,100) as title, NULL as symbol, 'social' as strategy, quality_score as quality, url, ingested_at as created_at FROM social_posts"),
    ]

    all_rows = []
    for src, sql in SOURCES:
        if source_type and source_type != src:
            continue
        where = []
        params = []
        if symbol:
            where.append("sub.symbol = %s"); params.append(symbol)
        if search:
            where.append("sub.title ILIKE %s"); params.append(f"%{search}%")
        w = ("WHERE " + " AND ".join(where)) if where else ""
        try:
            rows = _db_query(f"SELECT sub.*, '{src}' as source_type FROM ({sql}) sub {w} ORDER BY sub.created_at DESC LIMIT 100", tuple(params) if params else None) or []
            for r in rows:
                all_rows.append({k: _json_clean(v) for k, v in r.items()})
        except Exception:
            pass

    # Sort by date, paginate
    all_rows.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    total = len(all_rows)
    page_rows = all_rows[offset:offset + limit]

    # Check embedding status
    if page_rows:
        embedded_set = set()
        try:
            ids = [(r.get("source_type"), r.get("id")) for r in page_rows]
            for st, sid in ids:
                er = _db_query("SELECT 1 FROM content_embeddings WHERE source_type=%s AND source_id=%s LIMIT 1", (st, sid), fetch="one")
                if er:
                    embedded_set.add((st, sid))
        except Exception:
            pass
        for r in page_rows:
            r["is_embedded"] = (r.get("source_type"), r.get("id")) in embedded_set
            r["source_label"] = {"news": "News", "youtube": "YouTube", "agent_result": "Agent Memory", "agent_synthesis": "Synthesis", "cio_decision": "CIO Decision", "fused_signal": "Fused Signal", "decision_outcome": "Outcome", "sec_form4": "SEC Form 4", "social_post": "Social"}.get(r.get("source_type"), r.get("source_type"))

    return {"items": page_rows, "total": total, "page": (offset // limit) + 1}


def _rag_status():
    """GET /api/v2/rag/status — Embedding coverage per source type."""
    sources = {
        "news": "SELECT count(*) FROM news_articles",
        "youtube": "SELECT count(*) FROM youtube_transcripts",
        "social_post": "SELECT count(*) FROM social_posts",
        "sec_form4": "SELECT count(*) FROM sec_form4",
        "fred_series": "SELECT count(*) FROM fred_economic_series",
        "agent_result": "SELECT count(*) FROM watchlist_agent_results",
        "agent_synthesis": "SELECT count(*) FROM watchlist_final_synthesis",
        "cio_decision": "SELECT count(*) FROM cio_decisions",
        "fused_signal": "SELECT count(*) FROM fused_signals",
        "decision_outcome": "SELECT count(*) FROM decision_outcomes",
    }
    by_source = {}
    total_rows = 0
    total_embedded = 0
    for src, sql in sources.items():
        try:
            t = (_db_query(sql, fetch="one") or {}).get("count", 0)
            e = (_db_query("SELECT count(*) FROM content_embeddings WHERE source_type=%s", (src,), fetch="one") or {}).get("count", 0)
        except Exception:
            t, e = 0, 0
        pct = round(e / max(t, 1) * 100, 1) if t > 0 else 0
        by_source[src] = {"total": t, "embedded": e, "pct": pct}
        total_rows += t
        total_embedded += e
    last = _db_query("SELECT max(created_at) as t FROM content_embeddings", fetch="one")
    return {
        "total_rows": total_rows, "total_embedded": total_embedded,
        "coverage_pct": round(total_embedded / max(total_rows, 1) * 100, 1),
        "by_source": by_source, "model": "nomic-embed-text", "dims": 768,
        "last_indexed": _json_clean((last or {}).get("t")),
    }


def _news_articles_list():
    """GET /api/v2/news/articles — filterable paginated news list."""
    q = getattr(_news_articles_list, '_query', {}) or {}
    def _qp(k, default=""):
        v = q.get(k, default)
        return (v[0] if isinstance(v, list) else v) or default

    limit = min(int(_qp("limit", "50")), 200)
    offset = int(_qp("offset", "0"))
    strategy = _qp("strategy")
    source = _qp("source")
    relevance = _qp("relevance")
    search = _qp("search")

    where = []
    params: list = []
    if strategy:
        where.append("strategy_type = %s"); params.append(strategy)
    if source:
        where.append("source = %s"); params.append(source)
    if relevance:
        where.append("retirement_relevance = %s"); params.append(relevance)
    if search:
        where.append("(title ILIKE %s OR symbol ILIKE %s)"); params.extend([f"%{search}%", f"%{search}%"])
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    total = _db_query(f"SELECT count(*) as n FROM news_articles {where_sql}", tuple(params) if params else None, fetch="one")
    params_with_paging = list(params) + [limit, offset]
    rows = _db_query(f"""
        SELECT id, title, symbol, source, source_url, strategy_type,
               retirement_relevance, relevance_score, created_at
        FROM news_articles {where_sql}
        ORDER BY created_at DESC LIMIT %s OFFSET %s
    """, tuple(params_with_paging)) or []

    return {
        "articles": [{k: _json_clean(v) for k, v in r.items()} for r in rows],
        "total": (total or {}).get("n", 0),
        "page": (offset // limit) + 1,
    }


def _youtube_transcripts():
    """GET /api/v2/youtube/transcripts — with category/channel filter + name-variant JOIN."""
    url_q = getattr(_youtube_transcripts, '_query', {}) or {}
    category = (url_q.get("category") or [""])[0] if isinstance(url_q.get("category"), list) else url_q.get("category", "")
    channel = (url_q.get("channel") or [""])[0] if isinstance(url_q.get("channel"), list) else url_q.get("channel", "")
    limit_str = (url_q.get("limit") or ["200"])[0] if isinstance(url_q.get("limit"), list) else url_q.get("limit", "200")
    limit = min(int(limit_str) if limit_str.isdigit() else 200, 500)

    where = ["yt.validation_status != 'orphan'"]
    params: list = []
    if category:
        where.append("yc.category = %s")
        params.append(category)
    if channel:
        where.append("yt.channel_name ILIKE %s")
        params.append(f"%{channel}%")
    where_sql = "WHERE " + " AND ".join(where)
    params.append(limit)

    rows = _db_query(f"""
        SELECT yt.id, yt.video_id, yt.title, yt.channel_name, yt.publish_date, yt.url,
               yt.duration_seconds, yt.quality_score, yt.relevance_score, yt.validation_status,
               yt.matched_keywords, yt.added_by, yt.ingested_at, yt.strategy_tags, yt.agent_tags,
               yc.category AS channel_category, yc.priority AS channel_priority
        FROM youtube_transcripts yt
        {_YT_NAME_JOIN}
        {where_sql}
        ORDER BY yt.ingested_at DESC LIMIT %s
    """, tuple(params)) or []

    total = _db_query(f"""
        SELECT count(*) as n FROM youtube_transcripts yt
        {_YT_NAME_JOIN}
        {where_sql}
    """, tuple(params[:-1]) if params[:-1] else None, fetch="one")

    return {
        "transcripts": [{k: _json_clean(v) for k, v in r.items()} for r in rows],
        "total": (total or {}).get("n", 0),
    }


def _youtube_channel_lookup():
    """GET /api/v2/youtube/channel-lookup?url= — Look up a channel by URL."""
    import re as _re, urllib.parse as _up
    # query comes via handle() which passes query dict
    # but for GET routes in ROUTES dict, query params aren't passed — read from raw
    # This is called as a lambda, so we need to get the URL from somewhere
    # The handle() function doesn't pass query to ROUTES lambdas, so parse from env
    # Actually — the ROUTES handler doesn't pass query. Let's check the request path.
    # Workaround: this function reads from a module-level variable set by handle()
    url = getattr(_youtube_channel_lookup, '_url', '') or ''
    if not url:
        return {"found": False, "error": "url parameter required"}
    ch_match = _re.match(r'https?://(?:www\.)?youtube\.com/(?:channel/|@|c/|user/)([^/?&]+)', url)
    ch_id = ch_match.group(1) if ch_match else url.strip().lstrip('@')
    if not ch_id:
        return {"found": False, "error": "Could not parse channel from URL"}
    ch = _db_query("SELECT channel_name, channel_id, channel_url, category, priority, agent_tags, auto_promote_threshold FROM youtube_channels WHERE channel_id=%s OR channel_url LIKE %s OR channel_name ILIKE %s LIMIT 1",
                   (ch_id, f"%{ch_id}%", f"%{ch_id}%"), fetch="one")
    if ch:
        return {"found": True, "channel": {k: _json_clean(v) for k, v in ch.items()}}
    return {"found": False, "channel_id": ch_id, "channel_url": url}


def _rewrite_status():
    """GET /api/v2/rewrite-note/status — Check local LLM availability."""
    local_up = False
    _cfg_model = get_local_llm_model()
    try:
        import urllib.request
        _base = get_local_llm_base_url().rstrip("/")
        with urllib.request.urlopen(f"{_base}/api/tags", timeout=3) as r:
            import json as _j
            models = [m["name"] for m in _j.loads(r.read()).get("models", [])]
            local_up = any(_cfg_model.split(":")[0] in m for m in models)
    except Exception:
        pass
    return {"local_llm": local_up, "model": _cfg_model, "fallback": "claude-haiku-4-5"}


def _portfolio_intelligence():
    """GET /api/v2/portfolio-intelligence — Sector classification, cross-account, performance."""
    from datetime import datetime as _dt

    # Load holdings
    hp = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
    raw = json.loads(hp.read_text()) if hp.exists() else {}
    all_h = raw.get("holdings", [])
    if not all_h:
        return {"error": "No holdings found"}

    total_value = raw.get("portfolio_totals", {}).get("total_value", 0) or sum(float(h.get("market_value", 0) or 0) for h in all_h)

    # DB lookups for sector enrichment
    finviz = {}
    try:
        rows = _db_query("SELECT symbol, sector, industry, market_cap, beta, rsi FROM finviz_data WHERE symbol = ANY(%s)", (list(set(h.get("symbol", "") for h in all_h if h.get("symbol"))),))
        if rows:
            for r in rows:
                finviz[r["symbol"]] = {k: _json_clean(v) for k, v in r.items()}
    except Exception:
        pass

    # ETF / fund sector map
    ETF_MAP = {
        "SCHD": "US Dividend Equity", "JEPI": "US Covered Call Income", "SCHG": "US Large Cap Growth",
        "BND": "US Bond Market", "XLB": "Materials", "XLI": "Industrials",
        "ARKQ": "Autonomous Tech/Robotics", "ARKG": "Genomics/Biotech", "DIV": "High Dividend Income",
        "AMANX": "US Large Cap Blend", "FCNTX": "US Large Cap Growth", "PFLT": "BDC/Floating Rate",
        "CSWC": "BDC/Capital Southwest", "RKLB": "Aerospace/Space",
    }
    FUND_MAP = {
        "us_large_growth": "US Large Cap Growth", "us_large_blend": "US Large Cap Blend",
        "us_small_mid": "US Small/Mid Cap", "us_large_value": "US Large Cap Value",
        "international": "International Equity", "us_bond": "US Bond Market",
    }
    DEFENSE = {"LMT", "RTX", "NOC", "LHX", "TDG", "DRS", "AVAV", "KTOS", "HII", "GD", "BAH", "CACI", "LDOS", "KBR", "IRDM"}

    def classify(h):
        sym = h.get("symbol", "")
        # finviz real sector
        if sym in finviz and finviz[sym].get("sector"):
            return finviz[sym]["sector"], finviz[sym].get("industry", ""), "finviz"
        # ETF map
        if sym in ETF_MAP:
            return ETF_MAP[sym], "ETF/Fund", "etf_map"
        # Defense
        if sym in DEFENSE:
            return "Defense & Aerospace", "Defense Contractor", "known_stock"
        # 401k sector_type
        st = h.get("sector_type", "")
        if st and st in FUND_MAP:
            return FUND_MAP[st], "Mutual Fund", "sector_type"
        if st:
            return st.replace("_", " ").title(), "Mutual Fund", "sector_type"
        # Cash
        if h.get("is_cash") or sym == "CASH":
            return "Cash", "", "cash"
        # Specific names
        if sym == "V":
            return "Financial Services", "Payment Processing", "known_stock"
        if sym == "NEE":
            return "Utilities", "Renewable Energy", "known_stock"
        if sym in ("SRNE", "LPIH"):
            return "Healthcare/Biotech", "Small Cap Biotech", "known_stock"
        return "Unclassified", "", "none"

    # Build enriched positions
    enriched = []
    for h in all_h:
        sym = h.get("symbol", h.get("name", "?"))
        acct = h.get("account", "unknown")
        mv = float(h.get("market_value", 0) or 0)
        cost = float(h.get("cost_basis", 0) or h.get("total_cost_basis", 0) or 0)
        unrealized = mv - cost if cost > 0 else 0
        unrealized_pct = round(unrealized / cost * 100, 2) if cost > 0 else 0
        sector, industry, src = classify(h)
        shares = float(h.get("shares", 0) or 0)
        price = float(h.get("price", 0) or 0)
        sec_type = h.get("asset_type", "")
        if not sec_type:
            sec_type = "Mutual Fund" if h.get("is_fund") else "ETF" if sym in ETF_MAP else "Stock"
        tech = {}
        if sym in finviz:
            f = finviz[sym]
            tech = {k: f[k] for k in ("rsi", "beta") if f.get(k) is not None}

        enriched.append({
            "symbol": sym, "name": (h.get("name", "") or sym)[:40],
            "account": acct, "security_type": sec_type,
            "sector": sector, "industry": industry, "sector_source": src,
            "market_value": round(mv, 2), "cost_basis": round(cost, 2),
            "unrealized_gain_loss": round(unrealized, 2), "unrealized_pct": unrealized_pct,
            "shares": shares, "last_price": price,
            "weight_pct": round(mv / max(total_value, 1) * 100, 2),
            "technicals": tech,
        })
    enriched.sort(key=lambda x: x["market_value"], reverse=True)

    # Account performance
    accounts = {}
    for h in enriched:
        a = accounts.setdefault(h["account"], {"account": h["account"], "total_value": 0, "total_cost": 0, "total_gain_loss": 0, "position_count": 0})
        a["total_value"] += h["market_value"]
        a["total_cost"] += h["cost_basis"]
        a["total_gain_loss"] += h["unrealized_gain_loss"]
        a["position_count"] += 1
    for a in accounts.values():
        a["unrealized_pct"] = round(a["total_gain_loss"] / max(a["total_cost"], 1) * 100, 2) if a["total_cost"] > 0 else 0
        a["total_value"] = round(a["total_value"], 2)

    # Sector performance
    sectors = {}
    for h in enriched:
        s = sectors.setdefault(h["sector"], {"sector": h["sector"], "total_value": 0, "total_cost": 0, "total_gain_loss": 0, "position_count": 0, "symbols": [], "accounts": set()})
        s["total_value"] += h["market_value"]
        s["total_cost"] += h["cost_basis"]
        s["total_gain_loss"] += h["unrealized_gain_loss"]
        s["position_count"] += 1
        s["symbols"].append(h["symbol"])
        s["accounts"].add(h["account"])
    sector_list = []
    for s in sectors.values():
        sector_list.append({
            "sector": s["sector"], "total_value": round(s["total_value"], 2),
            "total_cost": round(s["total_cost"], 2), "total_gain_loss": round(s["total_gain_loss"], 2),
            "unrealized_pct": round(s["total_gain_loss"] / max(s["total_cost"], 1) * 100, 2) if s["total_cost"] > 0 else 0,
            "position_count": s["position_count"],
            "weight_pct": round(s["total_value"] / max(total_value, 1) * 100, 2),
            "symbols": sorted(set(s["symbols"])), "account_count": len(s["accounts"]),
        })
    sector_list.sort(key=lambda x: x["total_value"], reverse=True)

    # Cross-account symbols
    sym_accts = {}
    for h in enriched:
        sa = sym_accts.setdefault(h["symbol"], {"symbol": h["symbol"], "name": h["name"], "sector": h["sector"], "type": h["security_type"], "accounts": [], "total_value": 0, "total_shares": 0, "total_gain_loss": 0})
        sa["accounts"].append({"account": h["account"], "market_value": h["market_value"], "shares": h["shares"], "unrealized_pct": h["unrealized_pct"], "weight_in_account": h["weight_pct"]})
        sa["total_value"] += h["market_value"]
        sa["total_shares"] += h["shares"]
        sa["total_gain_loss"] += h["unrealized_gain_loss"]
    cross = sorted([v for v in sym_accts.values() if len(v["accounts"]) > 1], key=lambda x: x["total_value"], reverse=True)

    # Classification quality
    classified = sum(1 for h in enriched if h["sector"] not in ("Unclassified", "Cash"))
    unknown = [{"symbol": h["symbol"], "account": h["account"]} for h in enriched if h["sector"] == "Unclassified"]
    sources = {}
    for h in enriched:
        sources[h["sector_source"]] = sources.get(h["sector_source"], 0) + 1

    # Best/worst
    with_perf = [h for h in enriched if h["unrealized_pct"] != 0 and h["cost_basis"] > 0]
    best = sorted(with_perf, key=lambda x: x["unrealized_pct"], reverse=True)[:10]
    worst = sorted(with_perf, key=lambda x: x["unrealized_pct"])[:10]

    return {
        "generated_at": _dt.now().isoformat(),
        "total_positions": len(enriched), "total_value": round(total_value, 2),
        "positions": enriched,
        "accounts": list(accounts.values()),
        "sectors": sector_list,
        "cross_account_symbols": cross, "cross_account_count": len(cross),
        "classification": {"total": len(enriched), "classified": classified, "unclassified": len(unknown),
                           "classified_pct": round(classified / max(len(enriched), 1) * 100, 1),
                           "sources": sources, "unknown_symbols": unknown},
        "best_performers": best, "worst_performers": worst,
    }


def _transcript_audit():
    """GET /api/v2/transcript-audit — Per-transcript tagging quality audit."""
    stats_row = _db_query("""
        SELECT count(*) as total,
               count(CASE WHEN agent_tags IS NOT NULL AND agent_tags != '[]'::jsonb THEN 1 END) as tagged,
               count(CASE WHEN promoted_to_whiteboard THEN 1 END) as promoted,
               round(avg(quality_score)::numeric,1) as avg_quality,
               round(stddev(quality_score)::numeric,1) as quality_stddev
        FROM youtube_transcripts
    """, fetch="one") or {}

    # Agent distribution via jsonb
    agent_rows = _db_query("""
        SELECT a.agent, count(*) as count,
               round(avg(t.quality_score)::numeric,1) as avg_quality
        FROM youtube_transcripts t,
             jsonb_array_elements_text(t.agent_tags) a(agent)
        WHERE t.agent_tags IS NOT NULL AND t.agent_tags != '[]'::jsonb
        GROUP BY a.agent ORDER BY count DESC
    """) or []

    # Strategy distribution
    strat_rows = _db_query("""
        SELECT s.tag as strategy_tag, count(*) as count,
               round(avg(t.quality_score)::numeric,1) as avg_quality
        FROM youtube_transcripts t,
             jsonb_array_elements_text(t.strategy_tags) s(tag)
        WHERE t.strategy_tags IS NOT NULL AND t.strategy_tags != '[]'::jsonb
        GROUP BY s.tag ORDER BY count DESC
    """) or []

    # Quality distribution
    qual_rows = _db_query("""
        SELECT
          CASE WHEN quality_score >= 80 THEN 'excellent'
               WHEN quality_score >= 65 THEN 'good'
               WHEN quality_score >= 50 THEN 'moderate'
               WHEN quality_score >= 35 THEN 'low'
               ELSE 'minimal' END as bucket,
          count(*) as count
        FROM youtube_transcripts GROUP BY 1
    """) or []

    return {
        "stats": {k: _json_clean(v) for k, v in stats_row.items()},
        "agents": [{k: _json_clean(v) for k, v in r.items()} for r in agent_rows],
        "strategies": [{k: _json_clean(v) for k, v in r.items()} for r in strat_rows],
        "quality_distribution": [{k: _json_clean(v) for k, v in r.items()} for r in qual_rows],
    }


def _iris_status():
    """GET /api/v2/iris/status — Iris taxonomy agent status.
    Note: ROUTES handler wraps return in {"ok": True, "data": ...} automatically.
    """
    import sys as _sys
    _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from iris_taxonomy_agent import get_iris_status, iris_status_summary
    status = get_iris_status()
    status["summary"] = iris_status_summary()
    # Deep clean for JSON serialization
    def _clean(obj):
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_clean(v) for v in obj]
        return _json_clean(obj)
    return _clean(status)


def _youtube_audit():
    """GET /api/v2/youtube-audit — Channel inventory + transcript quality."""
    channels = _db_query("""
        SELECT c.channel_name, c.channel_id, c.category, c.priority,
               c.agent_tags, c.active, c.auto_promote_threshold,
               count(t.id) as transcript_count,
               count(CASE WHEN t.promoted_to_whiteboard THEN 1 END) as promoted_count,
               round(avg(COALESCE(t.quality_score,0))::numeric,1) as avg_quality
        FROM youtube_channels c
        LEFT JOIN youtube_transcripts t ON t.channel_name = c.channel_name
        GROUP BY c.channel_name, c.channel_id, c.category, c.priority,
                 c.agent_tags, c.active, c.auto_promote_threshold
        ORDER BY c.category, c.channel_name
    """) or []
    total_t = _db_query("SELECT count(*) as cnt FROM youtube_transcripts", fetch="one") or {}
    total_wb = _db_query("SELECT count(*) as cnt FROM intelligence_whiteboard WHERE source_type='youtube'", fetch="one") or {}
    # Name mismatches: transcripts with no matching channel (excluding already-flagged orphans)
    mismatches = _db_query("""
        SELECT yt.channel_name, count(*) as tx_count
        FROM youtube_transcripts yt
        LEFT JOIN youtube_channels yc ON yc.channel_name = yt.channel_name
        WHERE yc.channel_name IS NULL AND COALESCE(yt.validation_status,'') != 'orphan'
        GROUP BY yt.channel_name ORDER BY count(*) DESC
    """) or []
    orphan_count = _db_query("SELECT count(*) as n FROM youtube_transcripts WHERE validation_status='orphan'", fetch="one") or {}
    return {
        "channels": [{k: _json_clean(v) for k, v in c.items()} for c in channels],
        "stats": {"total_transcripts": total_t.get("cnt", 0), "whiteboard_youtube": total_wb.get("cnt", 0),
                  "total_channels": len(channels)},
        "name_mismatches": [{k: _json_clean(v) for k, v in m.items()} for m in mismatches],
        "orphan_tx_count": orphan_count.get("n", 0),
    }


def _proposals_with_pnl():
    """GET /api/v2/proposals-with-pnl — All pending proposals with P&L pre-computed."""
    proposals = _db_query(
        """SELECT id, symbol, action, strategy_type, confidence, status,
                  account_name, entry_price, shares_held, unrealized_pnl,
                  created_at
           FROM watchlist_proposals WHERE status='proposed'
           ORDER BY created_at DESC LIMIT 30"""
    ) or []

    # Merge with live prices from holdings + stops from risk_management
    h_data = _load_json(STATE_DIR / "holdings.json") or {}
    price_map = {}
    for h in h_data.get("holdings", []):
        s = h.get("symbol", "")
        if s:
            price_map[s] = {"price": h.get("price", 0), "shares": h.get("shares", 0),
                            "cost_basis": h.get("cost_basis", 0), "gain_loss": h.get("gain_loss", 0),
                            "market_value": h.get("market_value", 0)}

    rm = _load_json(STATE_DIR / "risk_management.json") or {}
    stop_map = {}
    for p in rm.get("positions", []):
        s = p.get("symbol", "")
        if s:
            stop_map[s] = {"stop_price": p.get("stop_price"), "distance_pct": p.get("distance_pct"),
                           "triggered": p.get("triggered", False)}

    result = []
    for prop in proposals:
        p = {k: _json_clean(v) for k, v in prop.items()}
        sym = p.get("symbol", "")
        live = price_map.get(sym, {})
        stop = stop_map.get(sym, {})
        p["current_price"] = live.get("price", 0)
        p["market_value"] = live.get("market_value", 0)
        p["live_pnl"] = live.get("gain_loss", 0)
        p["stop_price"] = stop.get("stop_price")
        p["distance_pct"] = stop.get("distance_pct")
        p["stop_breached"] = stop.get("triggered", False)
        # Compute days waiting
        try:
            from datetime import datetime
            created = str(p.get("created_at", ""))[:10]
            if created:
                days = (datetime.now() - datetime.strptime(created, "%Y-%m-%d")).days
                p["days_waiting"] = days
        except Exception:
            p["days_waiting"] = 0
        result.append(p)

    return {"proposals": result, "count": len(result)}


def _agent_pipeline():
    """GET /api/v2/agent-pipeline — Live agent job pipeline for orchestration dashboard.
    Returns: jobs, results, handoffs, events, proposals, debates, summary.
    Reads ?limit= from _agent_pipeline._query (default 50).
    """
    _q = getattr(_agent_pipeline, '_query', None) or {}
    _lim_raw = (_q.get('limit') or [50])
    lim = min(max(int(_lim_raw[0] if isinstance(_lim_raw, list) else _lim_raw), 10), 500)

    # 1. Active + recent agent jobs (last 24h)
    jobs = _db_query(
        """SELECT id, symbol, requested_agent, request_type, status,
                  priority, submitted_from, created_at, started_at, completed_at,
                  payload::text as payload_text
           FROM watchlist_agent_jobs
           WHERE created_at > NOW() - INTERVAL '24 hours'
           ORDER BY created_at DESC LIMIT %s""", [lim * 4]
    ) or []

    # 2. Recent agent analyses
    results = _db_query(
        """SELECT DISTINCT ON (symbol, agent)
                  symbol, agent, recommendation, confidence, summary,
                  created_at, model_used, status,
                  rag_sources_used, peer_notes_symbols
           FROM watchlist_agent_results
           WHERE created_at > NOW() - INTERVAL '24 hours'
           ORDER BY symbol, agent, created_at DESC"""
    ) or []

    # 3. Escalations / handoffs
    handoffs = _db_query(
        """SELECT symbol, from_agent, to_agent, reason, escalated, created_at
           FROM agent_handoffs
           WHERE created_at > NOW() - INTERVAL '24 hours'
           ORDER BY created_at DESC LIMIT %s""", [lim]
    ) or []

    # 4. Event queue (Level 3)
    events = _db_query(
        """SELECT id, event_type, symbol, priority, status,
                  agents_to_notify, trigger_data::text as trigger_text,
                  created_at, processed_at
           FROM agent_event_queue
           ORDER BY created_at DESC LIMIT %s""", [lim]
    ) or []

    # 5. Pending proposals
    proposals = _db_query(
        """SELECT symbol, action, strategy_type, confidence, status,
                  created_at
           FROM watchlist_proposals
           WHERE status = 'proposed'
           ORDER BY created_at DESC LIMIT %s""", [lim]
    ) or []

    # 6. Recent debates
    debates = _db_query(
        """SELECT symbol, consensus_recommendation, consensus_score,
                  participants, created_at, provider
           FROM agent_debate_log
           WHERE created_at > NOW() - INTERVAL '24 hours'
           ORDER BY created_at DESC LIMIT %s""", [lim]
    ) or []

    cj = [{k: _json_clean(v) for k, v in j.items()} for j in jobs]
    cr = [{k: _json_clean(v) for k, v in r.items()} for r in results]
    ch = [{k: _json_clean(v) for k, v in h.items()} for h in handoffs]
    ce = [{k: _json_clean(v) for k, v in e.items()} for e in events]
    cp = [{k: _json_clean(v) for k, v in p.items()} for p in proposals]
    cd = [{k: _json_clean(v) for k, v in d.items()} for d in debates]

    return {
        "jobs": cj,
        "results": cr,
        "handoffs": ch,
        "events": ce,
        "proposals": cp,
        "debates": cd,
        "summary": {
            "queued": sum(1 for j in cj if j.get("status") == "queued"),
            "processing": sum(1 for j in cj if j.get("status") == "processing"),
            "completed": sum(1 for j in cj if j.get("status") in ("completed", "done")),
            "failed": sum(1 for j in cj if j.get("status") == "failed"),
            "total_24h": len(cj),
            "events_pending": sum(1 for e in ce if e.get("status") == "pending"),
            "events_done": sum(1 for e in ce if e.get("status") == "done"),
            "handoffs_24h": len(ch),
            "analyses_24h": len(cr),
            "proposals_pending": len(cp),
            "debates_24h": len(cd),
        },
    }


def _intelligence_whiteboard():
    """GET /api/v2/intelligence-whiteboard — Full whiteboard view for standalone page."""
    items = _db_query(
        """SELECT id, symbol, title, summary, source_type, quality_score,
                  confidence, status, days_on_board, hygiene_status, created_at
           FROM intelligence_whiteboard
           ORDER BY quality_score DESC, created_at DESC
           LIMIT 500"""
    ) or []
    stats_raw = _db_query(
        """SELECT source_type, count(*) as cnt,
                  count(CASE WHEN hygiene_status='active' OR hygiene_status IS NULL THEN 1 END) as active,
                  count(CASE WHEN hygiene_status='demoted' THEN 1 END) as demoted,
                  count(CASE WHEN hygiene_status='archived' THEN 1 END) as archived
           FROM intelligence_whiteboard GROUP BY source_type"""
    ) or []
    total = _db_query("SELECT count(*) as cnt FROM intelligence_whiteboard", fetch="one") or {}
    by_source = {r["source_type"]: r["cnt"] for r in stats_raw}
    by_status = {"active": sum(r["active"] for r in stats_raw), "demoted": sum(r["demoted"] for r in stats_raw), "archived": sum(r["archived"] for r in stats_raw)}
    return {
        "items": [{k: _json_clean(v) for k, v in i.items()} for i in items],
        "stats": {"total": total.get("cnt", 0), "by_source": by_source, "by_status": by_status},
    }


def _llm_spend():
    """GET /api/v2/llm-spend — Full LLM spend analytics from llm_router.log."""
    import json as _j
    log_file = PROJECT_ROOT / "logs" / "llm_router.log"
    calls = []
    daily_spend = {}
    provider_spend = {}
    task_spend = {}
    provider_calls = {}
    task_calls = {}
    hourly_today = {}

    today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")

    if log_file.exists():
        for line in log_file.read_text().splitlines()[-500:]:
            try:
                entry = _j.loads(line)
                calls.append(entry)
                day = entry.get("timestamp", "")[:10]
                hour = entry.get("timestamp", "")[11:13]
                cost = float(entry.get("cost") or entry.get("cost_estimate") or 0)
                provider = entry.get("provider", "unknown")
                task = entry.get("task_type", "unknown")

                daily_spend[day] = daily_spend.get(day, 0) + cost
                provider_spend[provider] = provider_spend.get(provider, 0) + cost
                provider_calls[provider] = provider_calls.get(provider, 0) + 1
                task_spend[task] = task_spend.get(task, 0) + cost
                task_calls[task] = task_calls.get(task, 0) + 1

                if day == today and hour:
                    hourly_today[hour] = hourly_today.get(hour, 0) + cost
            except Exception:
                pass

    # Get budget from llm_router
    budget = 0.50
    try:
        from llm_router import DAILY_BUDGET_LIMIT
        budget = DAILY_BUDGET_LIMIT
    except Exception:
        pass

    today_total = daily_spend.get(today, 0)

    return {
        "today_spend": round(today_total, 4),
        "budget_limit": budget,
        "budget_remaining": round(budget - today_total, 4),
        "budget_pct_used": round((today_total / budget) * 100, 1) if budget > 0 else 0,
        "total_spend": round(sum(provider_spend.values()), 4),
        "total_calls": len(calls),
        "by_provider": {k: {"spend": round(v, 4), "calls": provider_calls.get(k, 0)}
                        for k, v in sorted(provider_spend.items())},
        "by_task": {k: {"spend": round(v, 4), "calls": task_calls.get(k, 0)}
                    for k, v in sorted(task_spend.items())},
        "by_day": {k: round(v, 4) for k, v in sorted(daily_spend.items())[-7:]},
        "hourly_today": {k: round(v, 4) for k, v in sorted(hourly_today.items())},
        "recent_calls": [{
            "timestamp": c.get("timestamp", ""),
            "provider": c.get("provider", ""),
            "task_type": c.get("task_type", ""),
            "model": c.get("model", c.get("model_used", "")),
            "cost": float(c.get("cost") or c.get("cost_estimate") or 0),
            "latency": c.get("latency", 0),
            "routing_reason": c.get("routing_reason", ""),
            "fallbacks": c.get("fallback_reasons", []),
        } for c in calls[-50:]],
    }


def _system_health_dashboard():
    """GET /api/v2/system-health — comprehensive system status."""
    import subprocess
    # LLM health
    llm = _llm_health()
    # DB counts
    key_tables = {}
    for t in ["watchlist_agent_results", "watchlist_final_synthesis", "cio_decisions",
              "news_articles", "fused_signals", "decision_outcomes", "ticker_strategy_classifications"]:
        row = _db_query(f"SELECT COUNT(*) as cnt FROM {t}", fetch="one") or {}
        key_tables[t] = row.get("cnt", 0)
    # CIO summary
    cio_summary = _db_query("SELECT action, COUNT(*) as cnt FROM cio_decisions GROUP BY action ORDER BY cnt DESC") or []
    # Cron status
    try:
        cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5).stdout
        cron_count = len([l for l in cron.splitlines() if l.strip() and not l.startswith("#")])
    except Exception:
        cron_count = 0
    # Screeners
    screeners = _db_query("SELECT COUNT(*) as cnt FROM finviz_screeners WHERE active=TRUE", fetch="one") or {}
    return {
        "llm": llm,
        "db_tables": key_tables,
        "cio_decisions": [{k: v for k, v in r.items()} for r in cio_summary],
        "cron_jobs": cron_count,
        "finviz_screeners": screeners.get("cnt", 0),
        "validation_suites": 7,
        "note": "System health dashboard. All data from DB.",
    }


def _llm_health():
    """GET /api/v2/llm/health — LLM router health + budget status."""
    try:
        import sys as _s
        _s.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from llm_router import health_check
        return health_check()
    except Exception as e:
        return {"error": str(e), "available": False}


def _cio_decisions_enriched():
    """GET /api/v2/cio-decisions — enriched with account from holdings."""
    rows = _db_query("SELECT * FROM cio_decisions ORDER BY CASE priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 ELSE 3 END, created_at DESC LIMIT 50") or []
    # Build symbol→account map from holdings
    holdings = _load_json(STATE_DIR / "holdings.json") or {}
    acct_map = {}
    for h in holdings.get("holdings", []):
        sym = h.get("symbol", "")
        if sym and sym not in acct_map:
            acct_map[sym] = h.get("account", "")
    decisions = []
    for r in rows:
        d = {k: _json_clean(v) for k, v in r.items()}
        if not d.get("account") and d.get("symbol"):
            d["account"] = acct_map.get(d["symbol"], "")
        decisions.append(d)
    return {"decisions": decisions}


def _cio_dashboard():
    """GET /api/v2/cio-dashboard — CIO-level intelligence summary."""
    decisions = _db_query("SELECT action, priority, COUNT(*) as cnt FROM cio_decisions GROUP BY action, priority ORDER BY COUNT(*) DESC") or []
    hr = _db_query("SELECT COUNT(*) as cnt FROM cio_decisions WHERE human_review_required=TRUE AND status='proposed'", fetch="one") or {}
    rotations = _db_query("SELECT COUNT(*) as cnt FROM strategy_rotation_recommendations WHERE status='proposed'", fetch="one") or {}
    plans = _db_query("SELECT COUNT(*) as cnt FROM rebalance_plans WHERE plan_status='draft'", fetch="one") or {}
    latest_plan = _db_query("SELECT plan_id, plan_summary, total_trade_value, human_review_required FROM rebalance_plans ORDER BY generated_at DESC LIMIT 1", fetch="one")
    marl = _db_query("SELECT COUNT(*) as cnt FROM marl_simulation_runs", fetch="one") or {}
    return {
        "decision_summary": [{k: _json_clean(v) for k, v in r.items()} for r in decisions],
        "human_review_pending": hr.get("cnt", 0),
        "pending_rotations": rotations.get("cnt", 0),
        "draft_plans": plans.get("cnt", 0),
        "latest_plan": {k: _json_clean(v) for k, v in latest_plan.items()} if latest_plan else None,
        "marl_simulations": marl.get("cnt", 0),
        "note": "CIO dashboard. All actions require human review. No broker execution.",
    }


def _rebalance_latest():
    plan = _db_query("SELECT * FROM rebalance_plans ORDER BY generated_at DESC LIMIT 1", fetch="one")
    if not plan:
        return {"plan": None, "actions": []}
    actions = _db_query("SELECT * FROM rebalance_plan_actions WHERE plan_id=%s ORDER BY human_review_required DESC", (plan["plan_id"],)) or []
    return {
        "plan": {k: _json_clean(v) for k, v in plan.items()},
        "actions": [{k: _json_clean(v) for k, v in r.items()} for r in actions],
    }


def _marl_diagnostics():
    latest = _db_query("SELECT * FROM marl_simulation_runs ORDER BY started_at DESC LIMIT 1", fetch="one")
    datasets = _db_query("SELECT dataset_id, row_count, status FROM marl_training_datasets ORDER BY generated_at DESC LIMIT 5") or []
    policies = _db_query("SELECT COUNT(*) as cnt FROM marl_policy_evaluations WHERE approved_for_live=TRUE", fetch="one") or {}
    return {
        "latest_simulation": {k: _json_clean(v) for k, v in latest.items()} if latest else None,
        "datasets": [{k: _json_clean(v) for k, v in r.items()} for r in datasets],
        "live_policies": policies.get("cnt", 0),
        "mode": "shadow_only",
        "note": "MARL is shadow-mode only. No live policy execution enabled.",
    }


def _strategy_rules_list():
    """GET /api/v2/strategy-rules — all strategy rule evaluations."""
    rows = _db_query("SELECT * FROM strategy_rule_evaluations ORDER BY strategy_type, symbol") or []
    return {"count": len(rows), "rules": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}


def _income_dashboard():
    """GET /api/v2/income-dashboard — income goals, layer allocations, top contributors."""
    goals = _db_query("SELECT * FROM portfolio_income_goals LIMIT 1", fetch="one") or {}
    latest_proj = _db_query("SELECT * FROM income_projection_history ORDER BY snapshot_date DESC LIMIT 1", fetch="one") or {}
    layers = _db_query("SELECT * FROM portfolio_layers ORDER BY target_min_pct DESC") or []
    top = _db_query("SELECT symbol, layer_id, annual_income, dividend_yield_pct, forward_yield_pct, payout_safety, income_reliability, income_goal_contribution_pct FROM income_asset_profiles WHERE annual_income > 0 ORDER BY annual_income DESC LIMIT 15") or []

    return {
        "goals": {k: _json_clean(v) for k, v in goals.items()} if goals else None,
        "current_income": _json_clean(latest_proj.get("total_annual_income")) if latest_proj else 0,
        "forward_income": _json_clean(latest_proj.get("forward_annual_income")) if latest_proj else 0,
        "target_pct": _json_clean(latest_proj.get("target_goal_pct")) if latest_proj else 0,
        "minimum_pct": _json_clean(latest_proj.get("minimum_goal_pct")) if latest_proj else 0,
        "stretch_pct": _json_clean(latest_proj.get("stretch_goal_pct")) if latest_proj else 0,
        "income_gap": _json_clean(latest_proj.get("income_gap_to_target")) if latest_proj else 0,
        "layers": [{k: _json_clean(v) for k, v in r.items()} for r in layers],
        "layer_breakdown": _json_clean(latest_proj.get("layer_breakdown")) if latest_proj else {},
        "top_contributors": [{k: _json_clean(v) for k, v in r.items()} for r in top],
        "disclosure": "Historical performance is not a guarantee of future results. All projections are scenario-based estimates using historical dividend growth rates as assumptions, not predictions.",
        "projection_assumptions": {
            "conservative": "0% dividend growth, no reinvestment",
            "base": "Historical 5-year dividend growth rate continues, no reinvestment",
            "aggressive": "Historical growth rate + full DRIP reinvestment at current prices",
        },
    }


def _alerts_debug():
    """GET /api/v2/alerts/debug — alert counts and data quality stats."""
    total = _db_query("SELECT COUNT(*) as cnt FROM alert_events", fetch="one") or {}
    by_type = _db_query("SELECT alert_type, COUNT(*) as cnt FROM alert_events GROUP BY alert_type ORDER BY cnt DESC") or []
    by_quality = _db_query("SELECT data_quality_status, COUNT(*) as cnt FROM alert_events GROUP BY data_quality_status") or []
    latest = _db_query("SELECT alert_type, symbol, severity, created_at FROM alert_events ORDER BY created_at DESC LIMIT 1", fetch="one")
    zero_errors = _db_query("SELECT COUNT(*) as cnt FROM alert_events WHERE data_quality_status = 'invalid_zero_price_or_stop'", fetch="one") or {}
    return {
        "total": total.get("cnt", 0),
        "by_type": {r["alert_type"]: r["cnt"] for r in by_type},
        "by_quality": {r["data_quality_status"]: r["cnt"] for r in by_quality},
        "zero_price_errors": zero_errors.get("cnt", 0),
        "latest": {k: _json_clean(v) for k, v in latest.items()} if latest else None,
    }


def _symbol_timeline(symbol: str):
    """GET /api/v2/symbol/{symbol}/timeline — unified symbol timeline."""
    sym = symbol.upper()
    # Alert events
    alerts = _db_query("""
        SELECT id, alert_type, severity, raw_text, price, stop_price, gap_pct,
               position_value, decision, data_quality_status, created_at
        FROM alert_events WHERE symbol = %s ORDER BY created_at DESC LIMIT 30
    """, (sym,)) or []
    # Watchlist events
    wl_events = _db_query("""
        SELECT event_type, agent, status, message, created_at
        FROM watchlist_events WHERE symbol = %s ORDER BY created_at DESC LIMIT 20
    """, (sym,)) or []
    # Agent jobs
    jobs = _db_query("""
        SELECT id, requested_agent, request_type, status, created_at, completed_at
        FROM watchlist_agent_jobs WHERE symbol = %s ORDER BY created_at DESC LIMIT 10
    """, (sym,)) or []
    # Agent results
    results = _db_query("""
        SELECT agent, recommendation, confidence, summary, created_at
        FROM watchlist_agent_results WHERE symbol = %s ORDER BY created_at DESC LIMIT 10
    """, (sym,)) or []
    # Strategy card
    strategy = _db_query("SELECT * FROM watchlist_strategy_cards WHERE symbol = %s", (sym,), fetch="one")
    # Maturity
    maturity = _db_query("SELECT analysis_stage, required_agents, completed_agents, needs_iteration FROM watchlist_analysis_maturity WHERE symbol = %s", (sym,), fetch="one")
    # Synthesis
    synthesis = _db_query("SELECT recommendation, confidence, action, conflicts, unresolved FROM watchlist_final_synthesis WHERE symbol = %s", (sym,), fetch="one")
    # Data quality warnings
    dq_warnings = _db_query("""
        SELECT alert_type, data_quality_status, raw_text, created_at
        FROM alert_events WHERE symbol = %s AND data_quality_status NOT IN ('valid', 'unknown')
        AND created_at > NOW() - INTERVAL '7 days'
        ORDER BY created_at DESC LIMIT 5
    """, (sym,)) or []

    return {
        "symbol": sym,
        "alerts": [{k: _json_clean(v) for k, v in r.items()} for r in alerts],
        "watchlist_events": [{k: _json_clean(v) for k, v in r.items()} for r in wl_events],
        "jobs": [{k: _json_clean(v) for k, v in r.items()} for r in jobs],
        "results": [{k: _json_clean(v) for k, v in r.items()} for r in results],
        "strategy": {k: _json_clean(v) for k, v in strategy.items()} if strategy else None,
        "maturity": {k: _json_clean(v) for k, v in maturity.items()} if maturity else None,
        "synthesis": {k: _json_clean(v) for k, v in synthesis.items()} if synthesis else None,
        "data_quality_warnings": [{k: _json_clean(v) for k, v in r.items()} for r in dq_warnings],
    }


def _wl_symbols(query: dict = None):
    """GET /api/v2/watchlist/symbols — deduplicated symbol master (one row per symbol)."""
    q = query or {}
    conditions = []
    params = []

    # Source filter — filter by membership boolean
    src = q.get("source", [None])[0] if isinstance(q.get("source"), list) else q.get("source")
    if src == "candidates":
        conditions.append("(in_ai_watchlist = true OR in_personal_watchlist = true)")
        conditions.append("in_portfolio = false")
    elif src == "curated":
        conditions.append("(in_ai_watchlist = true OR in_personal_watchlist = true OR in_portfolio = true)")
    elif src == "portfolio":
        conditions.append("in_portfolio = true")
    elif src == "ai_discovered":
        conditions.append("in_ai_discovered = true")
    elif src == "ai_watchlist":
        conditions.append("in_ai_watchlist = true")
    elif src == "personal_watchlist":
        conditions.append("in_personal_watchlist = true")

    # Stage filter
    stage = q.get("stage", [None])[0] if isinstance(q.get("stage"), list) else q.get("stage")
    if stage:
        conditions.append("analysis_stage = %s")
        params.append(stage)

    # Strategy filter
    strategy = q.get("strategy", [None])[0] if isinstance(q.get("strategy"), list) else q.get("strategy")
    if strategy:
        conditions.append("strategy_type = %s")
        params.append(strategy)

    where = " WHERE " + " AND ".join(conditions) if conditions else ""

    sort_col = "updated_at DESC"
    s = (q.get("sort", ["updated"])[0] if isinstance(q.get("sort"), list) else q.get("sort")) or "updated"
    sort_map = {"score": "score DESC NULLS LAST", "symbol": "symbol", "updated": "updated_at DESC", "price": "latest_price DESC NULLS LAST", "rr": "risk_reward DESC NULLS LAST"}
    sort_col = sort_map.get(s, sort_col)

    rows = _db_query(f"SELECT * FROM watchlist_symbol_master{where} ORDER BY {sort_col} LIMIT 200", params) or []

    # Enrich with account-level holdings from JSON
    holdings = _load_json(STATE_DIR / "holdings.json") or {}
    acct_summaries = holdings.get("account_summaries", {})
    acct_display = {aid: info.get("display_name", aid) for aid, info in acct_summaries.items()}
    total_portfolio = sum(info.get("total_value", 0) for info in acct_summaries.values())

    holdings_by_sym = {}
    for h in holdings.get("holdings", []):
        sym = h.get("symbol")
        if sym:
            holdings_by_sym.setdefault(sym, []).append(h)

    items = []
    for r in rows:
        item = {k: _json_clean(v) for k, v in r.items()}
        sym = item.get("symbol")
        # Add account holdings
        sym_holdings = holdings_by_sym.get(sym, [])
        if sym_holdings:
            acct_detail = []
            total_shares = 0
            total_mv = 0
            for h in sym_holdings:
                aid = h.get("account_id") or h.get("account", "unknown")
                shares = float(h.get("shares", 0) or 0)
                mv = float(h.get("market_value", 0) or 0)
                total_shares += shares
                total_mv += mv
                acct_detail.append({
                    "account_id": aid,
                    "account_name": acct_display.get(aid, aid),
                    "account_type": h.get("account_type") or _infer_account_type(aid),
                    "shares": round(shares, 4),
                    "market_value": round(mv, 2),
                    "cost_basis": round(float(h.get("cost_basis", 0) or 0), 2) if h.get("cost_basis") else None,
                    "gain_loss": round(float(h.get("gain_loss", 0) or 0), 2) if h.get("gain_loss") is not None else None,
                    "gain_loss_pct": round(float(h.get("gain_loss_pct", 0) or 0), 2) if h.get("gain_loss_pct") is not None else None,
                    "weight_in_account": round(float(h.get("portfolio_pct", 0) or 0), 2),
                })
            item["account_holdings"] = acct_detail
            item["total_shares"] = round(total_shares, 4)
            item["total_market_value"] = round(total_mv, 2)
            item["portfolio_weight"] = round(total_mv / total_portfolio * 100, 2) if total_portfolio > 0 else 0
        else:
            item["account_holdings"] = []
            item["total_shares"] = 0
            item["total_market_value"] = 0
            item["portfolio_weight"] = 0

        # Enrich: days watched + source agent + why added
        wi_rows = _db_query("SELECT source, first_seen_at, last_seen_at, LEFT(source_payload::text, 200) as why FROM watchlist_items WHERE symbol=%s AND status != 'removed' ORDER BY first_seen_at LIMIT 3", (sym,)) or []
        if wi_rows:
            first_seen = wi_rows[0].get("first_seen_at")
            if first_seen:
                from datetime import datetime as _dtx, timezone as _tzx
                try:
                    fs = first_seen if isinstance(first_seen, _dtx) else _dtx.fromisoformat(str(first_seen).replace("Z", "+00:00"))
                    item["days_watched"] = max(0, (_dtx.now(_tzx.utc) - fs.astimezone(_tzx.utc)).days)
                except Exception:
                    item["days_watched"] = 0
            item["added_by"] = wi_rows[0].get("source", "unknown")
            item["why_added"] = wi_rows[0].get("why", "")[:200] if wi_rows[0].get("why") else ""
            item["all_sources"] = list(set(r.get("source", "") for r in wi_rows))
        else:
            item["days_watched"] = 0
            item["added_by"] = "unknown"
            item["why_added"] = ""
            item["all_sources"] = []

        # Enrich: latest agent confidence + recommendation
        agent_row = _db_query("SELECT agent, recommendation, confidence, created_at FROM watchlist_agent_results WHERE symbol=%s ORDER BY created_at DESC LIMIT 1", (sym,))
        if agent_row:
            item["last_agent"] = agent_row[0].get("agent", "")
            item["last_recommendation"] = agent_row[0].get("recommendation", "")
            item["last_confidence"] = _json_clean(agent_row[0].get("confidence"))
            item["last_analyzed_at"] = _json_clean(agent_row[0].get("created_at"))
        # Curated badge: 2+ days watched or 2+ agent analyses
        agent_cnt = _db_query("SELECT count(*) as cnt FROM watchlist_agent_results WHERE symbol=%s AND created_at > NOW() - INTERVAL '7 days'", (sym,))
        item["is_curated"] = (item.get("days_watched", 0) >= 2) or ((agent_cnt[0]["cnt"] if agent_cnt else 0) >= 2)

        items.append(item)

    return {"count": len(items), "symbols": items}


def _infer_account_type(account_id: str) -> str:
    """Infer account type from account_id naming convention."""
    aid = (account_id or "").lower()
    if "roth" in aid: return "Roth IRA"
    if "rollover" in aid or "ira" in aid: return "Rollover IRA"
    if "401k" in aid: return "401k"
    if "taxable" in aid or "individual" in aid: return "Taxable"
    return "Unknown"


def attribution():
    a = _load_json(STATE_DIR / "performance_attribution.json") or {}
    def _clean_rows(rows, gain_key):
        out=[]
        for r in rows or []:
            if isinstance(r, dict):
                out.append({"symbol": r.get("symbol",""), gain_key: float(r.get(gain_key, r.get("gain", r.get("loss", 0))) or 0)})
        return out
    return {
        "has_data": a.get("has_data", False),
        "benchmark": a.get("benchmark", ""),
        "benchmark_label": a.get("benchmark_label", "Benchmark"),
        "port_cagr": a.get("port_cagr"),
        "bench_cagr": a.get("bench_cagr"),
        "alpha_annualized": a.get("alpha_annualized"),
        "inception_return": a.get("inception_return"),
        "bench_3yr_return": a.get("bench_3yr_return"),
        "port_sharpe": a.get("port_sharpe"),
        "bench_sharpe": a.get("bench_sharpe"),
        "port_sortino": a.get("port_sortino"),
        "bench_sortino": a.get("bench_sortino"),
        "port_maxdd": a.get("port_maxdd"),
        "bench_maxdd": a.get("bench_maxdd"),
        "rolling_alpha": a.get("rolling_alpha", []),
        "top_gainers": _clean_rows(a.get("top_gainers", []), "gain"),
        "top_losers": _clean_rows(a.get("top_losers", []), "loss"),
        "snapshot_count": a.get("snapshot_count", 0),
        "note": a.get("note", ""),
        "last_updated": a.get("last_updated", ""),
    }


def correlation():
    c = _load_json(STATE_DIR / "correlation.json") or {}
    matrix = c.get("correlation_matrix") or {}
    symbols = list(matrix.keys()) if isinstance(matrix, dict) else []
    return {
        "has_data": c.get("has_data", False),
        "sector_exposure": c.get("sector_exposure", {}),
        "geographic": c.get("geographic", {}),
        "rate_sensitivity": c.get("rate_sensitivity", {}),
        "rate_interpretation": c.get("rate_interpretation", ""),
        "defense_cluster_pct": c.get("defense_cluster_pct", 0),
        "correlation_matrix": matrix,
        "high_correlations": c.get("high_correlations", []),
        "symbols": symbols,
        "symbols_analyzed": len(c.get("symbols_analyzed", symbols)),
        "total_value": c.get("total_value", 0),
        "last_updated": c.get("last_updated", ""),
    }

def rebalance():
    yo = _load_json(STATE_DIR / "yaml_advisor_output.json") or {}
    opus = yo.get("opus_output") or {} if isinstance(yo.get("opus_output"), dict) else {}
    gt = yo.get("ground_truth_summary") or {}

    # Pull observations and suggestions from opus_output first, then top-level fallback
    observations = opus.get("observations") or yo.get("observations") or []
    suggestions = opus.get("suggestions") or yo.get("suggestions") or []
    yaml_health = opus.get("yaml_health_score")
    yaml_notes = opus.get("yaml_health_notes", "")

    executive_lines = []
    for obs in observations[:6]:
        msg = obs.get("message") if isinstance(obs, dict) else str(obs)
        if msg:
            executive_lines.append(msg)
    if not executive_lines:
        executive_lines = ["Use Rebalance to review concentration, income architecture, and validation links before making account-level changes."]

    v_strategy_lines = []
    bond_strategy_lines = []
    for item in suggestions:
        if not isinstance(item, dict):
            continue
        rationale = item.get("rationale", "")
        lower = rationale.lower()
        if "visa" in lower or "v " in lower[:10] or "single stock" in lower or "v_single" in lower:
            v_strategy_lines.append(rationale)
        if "bond" in lower or "fixed income" in lower or "treasury" in lower or "bnd" in lower:
            bond_strategy_lines.append(rationale)
    if not v_strategy_lines:
        v_strategy_lines = [m for m in executive_lines if "visa" in m.lower() or "single stock" in m.lower() or "v " in m.lower()[:10]][:3]

    # Build structured suggestion cards with account routing
    suggestion_cards = []
    for item in suggestions:
        if not isinstance(item, dict):
            continue
        suggestion_cards.append({
            "id": item.get("id", ""),
            "type": item.get("type", ""),
            "account": item.get("account", ""),
            "rationale": item.get("rationale", ""),
            "confidence": item.get("confidence", ""),
            "do_not_apply_if": item.get("do_not_apply_if", ""),
            "current_value": item.get("current_value"),
            "suggested_value": item.get("suggested_value"),
        })

    # Structured observations with account context
    obs_cards = []
    for obs in observations:
        if not isinstance(obs, dict):
            continue
        obs_cards.append({
            "type": obs.get("type", "info"),
            "account": obs.get("account", ""),
            "message": obs.get("message", ""),
            "data": obs.get("data"),
        })

    summary = opus.get("summary", "")
    recommendations = opus.get("recommendations", [])
    has_pipeline_recs = bool(recommendations)

    # If no pipeline recommendations, compute from live portfolio state
    if not recommendations:
        _rh = _load_json(STATE_DIR / "holdings.json") or {}
        _rrm = _load_json(STATE_DIR / "risk_management.json") or {}
        _rdc = _load_json(STATE_DIR / "dividend_calendar.json") or {}
        _rholdings = [p for p in _rh.get("holdings", []) if not p.get("is_cash") and (p.get("market_value") or 0) > 50]
        _rtotal = sum(p.get("market_value", 0) for p in _rholdings)
        computed = []
        for p in _rholdings:
            pct = (p.get("market_value", 0) / _rtotal * 100) if _rtotal > 0 else 0
            if pct > 20:
                computed.append({"symbol": p["symbol"], "action": "REVIEW TRIM", "rationale": f'{p["symbol"]} at {pct:.1f}% — exceeds 20% concentration threshold. Consider trimming to reduce single-name risk.', "severity": "high", "account": p.get("account", "")})
            elif pct > 15:
                computed.append({"symbol": p["symbol"], "action": "MONITOR", "rationale": f'{p["symbol"]} at {pct:.1f}% — approaching concentration limit.', "severity": "medium", "account": p.get("account", "")})
        for p in _rrm.get("positions", []):
            if p.get("status") == "NO STOP" and (p.get("market_value") or 0) > 10000 and p.get("account") != "fidelity_401k":
                computed.append({"symbol": p["symbol"], "action": "SET STOP", "rationale": f'{p["symbol"]} (${p["market_value"]:,.0f}) has no stop. Consider placing a trailing stop.', "severity": "medium", "account": p.get("account", "")})
        _rann = _rdc.get("total_annual", 0)
        if _rtotal > 0 and _rann / _rtotal < 0.01:
            computed.append({"symbol": "", "action": "INCOME REVIEW", "rationale": f'Portfolio yield {_rann/_rtotal*100:.2f}% — below 1% target. Consider adding income positions (SCHD, JEPI, BDCs).', "severity": "low"})
        # Sector concentration check
        _sector_map = {}
        for p in _rholdings:
            s = p.get("sector", "Other")
            _sector_map[s] = _sector_map.get(s, 0) + p.get("market_value", 0)
        for s, mv in _sector_map.items():
            spct = mv / _rtotal * 100 if _rtotal else 0
            if spct > 30:
                computed.append({"symbol": "", "action": "SECTOR CONCENTRATION", "rationale": f'{s} sector at {spct:.0f}% — over 30% threshold. Consider diversifying.', "severity": "high"})
        # Cash adequacy
        _cash = sum(p.get("market_value", 0) for p in _rh.get("holdings", []) if p.get("is_cash"))
        _cash_pct = _cash / _rtotal * 100 if _rtotal else 0
        if _cash_pct < 2:
            computed.append({"symbol": "CASH", "action": "LOW CASH", "rationale": f'Cash at {_cash_pct:.1f}% (${_cash:,.0f}) — below 2% buffer. Consider raising cash.', "severity": "medium"})
        # Portfolio heat
        _heat = _rrm.get("portfolio_heat_pct", 0)
        if _heat > 5:
            computed.append({"symbol": "", "action": "HEAT ELEVATED", "rationale": f'Portfolio heat at {_heat:.1f}% — above 5% threshold. Reduce risk exposure or add stops.', "severity": "high"})
        recommendations = computed

    # ── Staleness indicator ──
    generated_at = yo.get("generated_at", "")
    is_stale = False
    stale_days = None
    if generated_at:
        try:
            from datetime import datetime as _dt
            gen_dt = _dt.fromisoformat(str(generated_at).replace("Z", "+00:00"))
            stale_days = (datetime.now() - gen_dt.replace(tzinfo=None)).days
            is_stale = stale_days > 7
        except Exception:
            is_stale = True

    return {
        "generated_at": generated_at,
        "status": yo.get("status", ""),
        "is_stale": is_stale,
        "stale_days": stale_days,
        "stale_note": f"Rebalance data is {stale_days} days old. Refreshing requires Anthropic API credits or manual run of portfolio_yaml_advisor.py." if is_stale else None,
        "ground_truth": gt,
        "recommendations": recommendations,
        "summary": summary,
        "executive_lines": executive_lines,
        "v_strategy_lines": v_strategy_lines,
        "bond_strategy_lines": bond_strategy_lines,
        "computed": not has_pipeline_recs,
        "account_summary": _rebalance_account_summary(),
        "observations": obs_cards,
        "suggestions": suggestion_cards,
        "yaml_health_score": yaml_health,
        "yaml_health_notes": yaml_notes,
        "llm_suggestions": {k: _json_clean(v) for k, v in (_db_query("SELECT content, generated_at FROM llm_intelligence_cache WHERE section='rebalance_suggestions'", fetch="one") or {}).items()},
        "deep_analysis": _get_deep_rebalance_analysis(),
    }


def _get_deep_rebalance_analysis():
    """Get latest deep rebalance analysis from rebalance_analysis_results."""
    try:
        row = _db_query("""
            SELECT id, generated_at, yaml_health_score, executive_summary,
                   recommendations, v_concentration_plan, bond_ballast_assessment,
                   yaml_gaps, verification_passed, ssdi_irmaa_flags,
                   verified_at, model_primary, stale_days_at_run
            FROM rebalance_analysis_results
            ORDER BY generated_at DESC LIMIT 1
        """, fetch="one")
        if not row:
            return None
        return {k: _json_clean(v) for k, v in row.items()}
    except Exception:
        return None


def _rebalance_account_summary():
    """Build account-level summary for rebalance context."""
    h = _load_json(STATE_DIR / "holdings.json") or {}
    accts = {}
    for p in h.get("holdings", []):
        a = p.get("account", "unknown")
        if a not in accts:
            accts[a] = {"account": a, "total_value": 0, "position_count": 0, "cash": 0}
        if p.get("is_cash"):
            accts[a]["cash"] += p.get("market_value", 0)
        else:
            accts[a]["total_value"] += p.get("market_value", 0)
            accts[a]["position_count"] += 1
    return sorted(accts.values(), key=lambda x: -x["total_value"])

def _forecast():
    """Portfolio projection based on current yield, dividend income, and account values."""
    h = _load_json(STATE_DIR / "holdings.json") or {}
    dc = _load_json(STATE_DIR / "dividend_calendar.json") or {}
    ret = _load_json(STATE_DIR / "retirement_roadmap.json") or {}

    total = h.get("portfolio_totals", {}).get("total_value", 0)
    annual_div = dc.get("total_annual", 0)
    portfolio_yield = (annual_div / total * 100) if total > 0 else 0

    accts = h.get("account_summaries", {})
    scenarios = {
        "conservative": {"market_return": 4.0, "label": "Conservative (4% + divs)"},
        "moderate": {"market_return": 7.0, "label": "Moderate (7% + divs)"},
        "aggressive": {"market_return": 10.0, "label": "Aggressive (10% + divs)"},
    }

    projections = {}
    for scenario_key, scenario in scenarios.items():
        total_return = scenario["market_return"] + portfolio_yield
        years = {}
        for yr in [1, 2, 3, 5]:
            projected = total * ((1 + total_return / 100) ** yr)
            div_cumulative = annual_div * yr
            years[f"{yr}Y"] = {
                "projected_value": round(projected, 0),
                "growth": round(projected - total, 0),
                "cumulative_dividends": round(div_cumulative, 0),
                "total_return_pct": round(((projected / total) - 1) * 100, 1),
            }
        projections[scenario_key] = {"label": scenario["label"], "total_return_pct": round(total_return, 2), "years": years}

    account_detail = []
    for acct_key in ["fidelity_401k", "schwab_rollover_ira", "schwab_roth", "schwab_taxable"]:
        val = accts.get(acct_key, {}).get("total_value", 0)
        account_detail.append({"account": acct_key, "current_value": val, "pct_of_total": round(val / total * 100, 1) if total else 0})

    payers = dc.get("payers", [])
    top_payers = sorted(payers, key=lambda p: p.get("annual_income", 0), reverse=True)[:10]

    return {
        "portfolio_value": total,
        "annual_dividend_income": annual_div,
        "portfolio_yield_pct": round(portfolio_yield, 2),
        "monthly_dividend_avg": dc.get("monthly_average", 0),
        "projections": projections,
        "accounts": account_detail,
        "top_dividend_payers": [{"symbol": p.get("symbol"), "yield_pct": p.get("yield_pct", 0), "annual_income": p.get("annual_income", 0), "frequency": p.get("frequency", ""), "value": p.get("market_value",0)} for p in top_payers],
        "assumptions": {
            "basis": "Current portfolio value and dividend yield held constant. No contributions, withdrawals, or rebalancing assumed.",
            "market_scenarios": "Conservative=4%, Moderate=7%, Aggressive=10% annual appreciation",
            "dividend_basis": "Trailing 12-month dividend rates from current holdings",
            "limitations": "No tax impact. No inflation adjustment. Fidelity 401k yield may be understated for proprietary funds. Projections are estimates only.",
        },
        "retirement_age": ret.get("current_age"),
    }

def trade_ai():
    """Trade AI workspace — latest run data from run_summary + watchlist CSV."""
    import csv, io, glob

    # Find all runs for today + yesterday
    all_runs = []
    for pattern in ["reports/2026-*/*/run_summary.json"]:
        for fp in sorted(glob.glob(str(PROJECT_ROOT / pattern)), reverse=True)[:8]:
            rs = _load_json(Path(fp))
            if rs:
                rs["_path"] = fp
                all_runs.append(rs)

    latest = all_runs[0] if all_runs else {}

    # Read tickers from DB (primary) or CSV (fallback)
    tickers = []
    try:
        # Get the most recent scan per symbol from today's latest run
        _db_tickers = _db_query("""
            SELECT DISTINCT ON (symbol)
                symbol, score, grade, decision, original_decision,
                rvol, price, change_pct, gap_pct, float_m,
                catalyst, catalyst_verified, catalyst_confidence, catalyst_source,
                critic_verdict, critic_confidence, critic_reasoning, decision_changed,
                disqualified, disqualification_reason,
                sector, industry, country, sector_etf,
                ticker_perf_1m, sector_perf_1m, vs_sector_pct,
                social_sentiment, social_score, social_reddit, social_stocktwits,
                social_bullish_pct, social_wsb,
                source, source_detail, run_type, run_label as scan_run_label,
                intelligence_readiness,
                scanned_at
            FROM trade_ai_scans
            WHERE run_date >= CURRENT_DATE - INTERVAL '1 day'
            ORDER BY symbol, scanned_at DESC
        """)
        if _db_tickers:
            for r in _db_tickers:
                tickers.append({
                    "symbol": r["symbol"],
                    "score": int(r.get("score") or 0),
                    "grade": r.get("grade") or "",
                    "decision": r.get("decision") or "",
                    "rvol": float(r.get("rvol") or 0),
                    "price": float(r.get("price") or 0),
                    "change_pct": str(round(float(r["change_pct"]), 2)) if r.get("change_pct") is not None else "",
                    "gap_pct": str(round(float(r["gap_pct"]), 2)) if r.get("gap_pct") is not None else "",
                    "float_m": str(round(float(r["float_m"]), 2)) if r.get("float_m") is not None else "",
                    "catalyst": r.get("catalyst") or "",
                    "critic_verdict": r.get("critic_verdict"),
                    "critic_confidence": r.get("critic_confidence"),
                    "original_decision": r.get("original_decision"),
                    "decision_changed": bool(r.get("decision_changed")),
                    "catalyst_verified": r.get("catalyst_verified"),
                    "catalyst_confidence": r.get("catalyst_confidence"),
                    "industry": r.get("industry"),
                    "critic_reasoning": r.get("critic_reasoning"),
                    "disqualified": bool(r.get("disqualified")),
                    "disqualification_reason": r.get("disqualification_reason"),
                    "critic_flags": [],
                    "sector": r.get("sector"),
                    "country": _country_flag(r.get("country")),
                    "sector_etf": r.get("sector_etf"),
                    "ticker_perf_1m": r.get("ticker_perf_1m"),
                    "sector_perf_1m": r.get("sector_perf_1m"),
                    "vs_sector_pct": r.get("vs_sector_pct"),
                    # Social from DB scan record
                    "social_sentiment": r.get("social_sentiment") or None,
                    "social_score": r.get("social_score"),
                    "social_reddit": r.get("social_reddit") or 0,
                    "social_stocktwits": r.get("social_stocktwits") or 0,
                    "social_bullish_pct": r.get("social_bullish_pct"),
                    "social_wsb": r.get("social_wsb") or 0,
                    "source": r.get("source") or "screener",
                    "source_detail": r.get("source_detail") or "",
                    "run_type": r.get("run_type"),
                    "scan_run_label": r.get("scan_run_label"),
                    "intelligence_readiness": r.get("intelligence_readiness"),
                })
    except Exception:
        pass

    # CSV fallback if DB is empty (bootstrap period)
    if not tickers:
        csv_pattern = latest.get("_path", "").replace("run_summary.json", "").rstrip("/")
        if csv_pattern:
            csvs = sorted(glob.glob(csv_pattern + "/trade_ai_*_watchlist.csv"))
            if csvs:
                try:
                    rows = list(csv.DictReader(io.StringIO(Path(csvs[-1]).read_text())))
                    for r in rows:
                        tickers.append({
                            "symbol": r.get("Symbol", ""), "score": int(r.get("Score", 0) or 0),
                            "grade": r.get("Grade", ""), "decision": r.get("Decision", ""),
                            "rvol": float(r.get("RVOL", 0) or 0), "price": float(r.get("Price", 0) or 0),
                            "change_pct": r.get("Change%", ""), "gap_pct": r.get("Gap%", ""),
                            "float_m": r.get("Float_M", ""), "catalyst": r.get("Catalyst", ""),
                            "critic_verdict": r.get("CriticVerdict", "") or None,
                            "critic_confidence": float(r.get("CriticConf", 0) or 0) if r.get("CriticConf") else None,
                            "catalyst_verified": r.get("CatalystVerified", "").lower() == "true" if r.get("CatalystVerified") else None,
                            "industry": r.get("Industry", "") or None,
                            "critic_reasoning": r.get("CriticReasoning", "") or None,
                            "disqualified": r.get("Disqualified", "").lower() == "true" if r.get("Disqualified") else False,
                            "critic_flags": [], "sector": r.get("Sector", "") or None,
                            "country": r.get("Country", "") or None, "sector_etf": r.get("SectorETF", "") or None,
                            "ticker_perf_1m": float(r["TickerPerf1M"]) if r.get("TickerPerf1M") else None,
                            "sector_perf_1m": float(r["SectorPerf1M"]) if r.get("SectorPerf1M") else None,
                            "vs_sector_pct": float(r["VsSectorPct"]) if r.get("VsSectorPct") else None,
                        })
                except Exception:
                    pass

    # Enrich tickers with historical appearance data from DB
    try:
        _history = _db_query("""
            SELECT symbol,
                   COUNT(DISTINCT run_date) as days_appeared,
                   COUNT(DISTINCT run_date) FILTER (WHERE decision = 'GO') as days_go,
                   MIN(run_date) as first_seen,
                   MAX(run_date) as last_seen,
                   MAX(score) as peak_score
            FROM trade_ai_scans
            WHERE run_type = 'full'
            GROUP BY symbol
        """) or []
        _hist_map = {r["symbol"]: r for r in _history}
        for t in tickers:
            h = _hist_map.get(t["symbol"])
            if h:
                t["history_days"] = h.get("days_appeared", 1)
                t["history_go_days"] = h.get("days_go", 0)
                t["history_first_seen"] = str(h.get("first_seen", ""))
                t["history_peak_score"] = h.get("peak_score", 0)
    except Exception:
        pass

    # Social sentiment: served from DB (populated by continuous_runner each scan cycle)
    # No live API calls here — avoids 20-30s page load from per-ticker StockTwits lookups

    # Enrich tickers with source origin (Finviz screener vs Social scalp vs portfolio)
    try:
        wi_sources = {}
        for sr in (_db_query("SELECT symbol, array_agg(DISTINCT source ORDER BY source) as sources FROM watchlist_items WHERE status != 'removed' GROUP BY symbol") or []):
            wi_sources[sr["symbol"]] = sr["sources"]
        scalp_sources = {}
        for sr in (_db_query("SELECT symbol, sources FROM scalp_scan_results WHERE scanned_at > NOW() - INTERVAL '48 hours' ORDER BY scanned_at DESC") or []):
            if sr["symbol"] not in scalp_sources:
                scalp_sources[sr["symbol"]] = sr.get("sources") or []
        for t in tickers:
            sym = t["symbol"]
            ss = scalp_sources.get(sym)
            ws = wi_sources.get(sym)
            # Check if live social sentiment shows activity
            has_social = (t.get("social_reddit", 0) or 0) > 0 or (t.get("social_stocktwits", 0) or 0) >= 10
            if ss:
                t["source"] = "social"
                t["source_detail"] = ", ".join(str(s) for s in ss[:2]) if ss else ""
            elif ws:
                src = ws[0] if ws else "screener"
                t["source"] = src
                t["source_detail"] = ", ".join(ws[:2]) if len(ws) > 1 else ""
            elif has_social:
                # Finviz screener pick with social activity
                parts = []
                if t.get("social_reddit", 0) > 0: parts.append("Reddit")
                if t.get("social_stocktwits", 0) >= 10: parts.append("StockTwits")
                t["source"] = "screener"
                t["source_detail"] = " + ".join(parts)
            else:
                t["source"] = "screener"
                t["source_detail"] = ""
    except Exception:
        pass

    # LLM enrichment: incubator screen + holdings health + proposal reviews
    try:
        _ticker_syms = [t["symbol"] for t in tickers]
        # Incubator LLM screen grades
        _incub_llm = _db_query("""
            SELECT DISTINCT ON (symbol) symbol, llm_screen_grade, llm_screen_verdict,
                   llm_screen_confidence, llm_screen_at
            FROM incubator_universe
            WHERE symbol = ANY(%s) AND llm_screen_grade IS NOT NULL
            ORDER BY symbol, llm_screen_at DESC NULLS LAST
        """, [_ticker_syms]) or []
        _incub_map = {r["symbol"]: r for r in _incub_llm}

        # Holdings LLM health
        _hold_llm = _db_query("""
            SELECT symbol, holdings_llm_health, holdings_llm_action,
                   holdings_llm_confidence, holdings_llm_at
            FROM watchlist_items
            WHERE source = 'portfolio' AND symbol = ANY(%s) AND holdings_llm_health IS NOT NULL
        """, [_ticker_syms]) or []
        _hold_map = {r["symbol"]: r for r in _hold_llm}

        # Proposal LLM reviews (latest per symbol)
        _prop_llm = _db_query("""
            SELECT DISTINCT ON (symbol) symbol, llm_review_stage, llm_model_used,
                   confidence_score as llm_confidence,
                   llm_review_chunks
            FROM paper_trade_proposals
            WHERE symbol = ANY(%s) AND status = 'PENDING' AND llm_review_stage IS NOT NULL
            ORDER BY symbol, confidence_score DESC NULLS LAST
        """, [_ticker_syms]) or []
        _prop_map = {r["symbol"]: r for r in _prop_llm}

        for t in tickers:
            sym = t["symbol"]
            inc = _incub_map.get(sym)
            if inc:
                t["incubator_llm_grade"] = inc.get("llm_screen_grade")
                t["incubator_llm_verdict"] = inc.get("llm_screen_verdict")
            hld = _hold_map.get(sym)
            if hld:
                t["holdings_llm_health"] = hld.get("holdings_llm_health")
                t["holdings_llm_action"] = hld.get("holdings_llm_action")
            prp = _prop_map.get(sym)
            if prp:
                t["proposal_llm_stage"] = prp.get("llm_review_stage")
                t["proposal_llm_confidence"] = prp.get("llm_confidence")
                chunks = prp.get("llm_review_chunks")
                if chunks and isinstance(chunks, dict):
                    t["proposal_llm_decision"] = (chunks.get("decision") or {}).get("decision")
                    t["proposal_risk_grade"] = (chunks.get("risk") or {}).get("risk_grade")
                    t["proposal_catalyst_grade"] = (chunks.get("catalyst") or {}).get("catalyst_grade")
    except Exception:
        pass

    # Sector breakdown from tickers (basic)
    sectors: dict = {}
    for t in tickers:
        # Use enrichment cache for sector if available
        ec = _load_json(STATE_DIR / "ticker_enrichment_cache.json") or {}
        sec = (ec.get(t["symbol"], {}) or {}).get("sector", "Unknown") if isinstance(ec.get(t["symbol"]), dict) else "Unknown"
        sectors[sec] = sectors.get(sec, 0) + 1

    # Run history for sparkline
    run_history = []
    for rs in all_runs[:8]:
        run_history.append({
            "date": rs.get("date", ""),
            "label": rs.get("run_label", ""),
            "go": rs.get("go_count", 0),
            "wait": rs.get("wait_count", 0),
            "total": rs.get("ticker_count", 0),
            "top_ticker": rs.get("top_ticker", ""),
            "top_score": rs.get("top_score", 0),
        })

    # Recalculate counts from actual ticker decisions (reflects live overlay)
    go_count = sum(1 for t in tickers if t.get("decision") == "GO")
    wait_count = sum(1 for t in tickers if t.get("decision") == "WAIT")
    avoid_count = sum(1 for t in tickers if t.get("decision") not in ("GO", "WAIT"))

    # Run health enrichment
    _latest_run_label = latest.get("run_label", "")
    _latest_run_timestamp = latest.get("generated_at", "")
    _run_health_status = None
    _today_signal_count = 0
    try:
        _rh = _db_query("""
            SELECT status, symbols_scanned, go_count AS rh_go, wait_count AS rh_wait,
                   no_go_count, reason_codes, finished_at
            FROM screener_run_health
            WHERE run_date = CURRENT_DATE
            ORDER BY finished_at DESC NULLS LAST LIMIT 1
        """, fetch="one")
        if _rh:
            _run_health_status = _rh.get("status")
    except Exception:
        pass
    try:
        _sig = _db_query("""
            SELECT COUNT(*) AS cnt FROM strategy_signals
            WHERE fired_at::date = CURRENT_DATE
        """, fetch="one")
        if _sig:
            _today_signal_count = int(_sig.get("cnt") or 0)
    except Exception:
        pass

    return {
        "ok": True,
        "run_date": latest.get("date", ""),
        "run_label": latest.get("run_label", ""),
        "latest_run_label": _latest_run_label,
        "latest_run_timestamp": _latest_run_timestamp,
        "latest_run_symbols_scanned": latest.get("ticker_count", 0),
        "latest_run_go_count": go_count,
        "latest_run_wait_count": wait_count,
        "latest_run_no_go_count": avoid_count,
        "run_health_status": _run_health_status,
        "vix": latest.get("vix"),
        "breadth": latest.get("breadth", ""),
        "market_regime": latest.get("breadth", latest.get("market_regime", "Neutral")),
        "go_count": go_count,
        "wait_count": wait_count,
        "avoid_count": avoid_count,
        "ticker_count": latest.get("ticker_count", 0),
        "top_ticker": latest.get("top_ticker", ""),
        "top_score": latest.get("top_score", 0),
        "delta_events": latest.get("delta_events", 0),
        "today_strategy_signal_count": _today_signal_count,
        "tickers": tickers,
        "sectors": dict(sorted(sectors.items(), key=lambda x: -x[1])),
        "run_history": run_history,
    }


# ── Journal Review Layer ──────────────────────────────────────────────────

def _db_write(sql, params=None):
    """Run a DB write (INSERT/UPDATE). Returns row dict or None."""
    try:
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from db_adapter import _get_conn, USE_DB
        if not USE_DB:
            return None
        conn = _get_conn()
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        conn.commit()
        try:
            return dict(cur.fetchone()) if cur.description else None
        except Exception:
            return None
    except Exception as e:
        print(f"  [api_v2] _db_write error: {e}")
        return None


# ── Stopped-Out Recovery Watch ────────────────────────────────────────────

def stopped_out_watch_list():
    """GET /api/v2/stopped-out-watch — list all active watched names."""
    rows = _db_query(
        """SELECT id, symbol, account, stopped_out_at, exit_price, stop_price, reason,
                  setup_name, thesis_at_exit, realized_pnl, status, analyst_verdict,
                  analyst_confidence, analyst_summary, reentry_trigger, invalidated_if,
                  evidence_payload, escalated_to, escalated_at, escalation_reason,
                  next_review_at, last_reviewed_at,
                  is_active, auto_created, detection_source,
                  temp_allocation_verdict, temp_allocation_confidence,
                  temp_allocation_target, temp_allocation_reason,
                  temp_allocation_until, temp_allocation_exit_trigger,
                  created_at, updated_at
           FROM stopped_out_watch WHERE is_active = true
           ORDER BY stopped_out_at DESC""",
        fetch="all"
    ) or []
    # Enrich with current prices from holdings/technical snapshot
    _h = _load_json(STATE_DIR / "holdings.json") or {}
    _ts = _load_json(STATE_DIR / "technical_snapshot.json") or {}
    price_map = {}
    for pos in _h.get("holdings", []):
        s = pos.get("symbol", "")
        if s and s not in price_map:
            price_map[s] = {"price": pos.get("price", 0), "rsi": None, "sma200_pct": None}
    for s, td in _ts.items():
        if isinstance(td, dict):
            if s in price_map:
                price_map[s]["rsi"] = td.get("rsi")
                price_map[s]["sma200_pct"] = td.get("sma200_pct")
            else:
                price_map[s] = {"price": td.get("price"), "rsi": td.get("rsi"), "sma200_pct": td.get("sma200_pct")}

    items = []
    for r in rows:
        item = {k: _json_clean(v) for k, v in r.items()}
        sym = r.get("symbol", "")
        live = price_map.get(sym, {})
        item["current_price"] = live.get("price")
        item["current_rsi"] = live.get("rsi")
        item["current_sma200_pct"] = live.get("sma200_pct")
        exit_p = float(r.get("exit_price") or 0)
        curr_p = float(live.get("price") or 0)
        item["recovery_pct"] = round(((curr_p - exit_p) / exit_p) * 100, 1) if exit_p > 0 and curr_p > 0 else None
        item["days_since_stop"] = (datetime.now().date() - r["stopped_out_at"]).days if r.get("stopped_out_at") else None
        items.append(item)

    # Add portfolio context for strategic reasoning
    _rm = _load_json(STATE_DIR / "risk_management.json") or {}
    _fr = _load_json(STATE_DIR / "_freshness.json") or {}
    _wl = _load_json(STATE_DIR / "watchlist.json") or {}
    portfolio_context = {
        "heat_pct": _rm.get("portfolio_heat_pct", 0),
        "total_with_stops": len([p for p in _rm.get("positions", []) if p.get("stop_price")]),
        "total_unprotected": len([p for p in _rm.get("positions", []) if p.get("status") == "NO STOP"]),
        "watchlist_candidates": len(_wl),
        "pipeline_status": _fr.get("status", "unknown"),
        "regime": "Neutral",  # from latest trade AI if available
    }
    # Try to get regime from latest state
    try:
        tai_dirs = sorted((STATE_DIR / "data" / "runs").glob("*/state.json"), reverse=True)[:1]
        if tai_dirs:
            tai = json.loads(tai_dirs[0].read_text())
            portfolio_context["regime"] = tai.get("market_breadth", tai.get("regime", "Neutral"))
    except Exception:
        pass

    return {"count": len(items), "items": items, "portfolio_context": portfolio_context}


def stopped_out_watch_escalate(body: dict):
    """POST /api/v2/stopped-out-watch/escalate — escalate a watch item to Maria/Steph."""
    watch_id = body.get("watch_id")
    escalate_to = body.get("escalate_to", "").strip()
    note = body.get("note", "").strip()

    if not watch_id:
        return 400, {"ok": False, "error": "watch_id required"}
    if escalate_to not in ("maria", "steph"):
        return 400, {"ok": False, "error": "escalate_to must be 'maria' or 'steph'"}

    item = _db_query("SELECT id, symbol, analyst_verdict FROM stopped_out_watch WHERE id = %s", (watch_id,), fetch="one")
    if not item:
        return 404, {"ok": False, "error": "watch item not found"}

    _db_write(
        "UPDATE stopped_out_watch SET escalated_to = %s, updated_at = NOW() WHERE id = %s",
        (escalate_to, watch_id)
    )
    # Log history
    _db_write(
        """INSERT INTO stopped_out_watch_history (watch_id, symbol, changed_by, old_verdict, new_verdict, summary)
           VALUES (%s, %s, 'analyst', %s, %s, %s)""",
        (watch_id, item["symbol"], item.get("analyst_verdict"), item.get("analyst_verdict"), f"Escalated to {escalate_to}: {note}")
    )
    return 200, {"ok": True, "escalated_to": escalate_to, "watch_id": watch_id}


def _stop_confirmations_list():
    """GET /api/v2/stop-confirmations — list positions needing stop confirmation."""
    rows = _db_query(
        """SELECT id, symbol, account, stop_status, stop_confirmed, stop_confirmed_at,
                  stop_price_confirmed, stop_exception_reason, last_reminder_at,
                  reminder_count, market_value, position_pct, created_at, updated_at
           FROM stop_confirmations
           ORDER BY stop_status = 'unconfirmed' DESC, market_value DESC""",
        fetch="all"
    ) or []
    return {"count": len(rows), "items": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}


def stop_confirmation_respond(body: dict):
    """POST /api/v2/stop-confirmations/respond — user responds to stop confirmation."""
    conf_id = body.get("id")
    response = body.get("response", "").strip()
    stop_price = body.get("stop_price")
    reason = body.get("reason", "").strip()

    valid_responses = ("confirmed", "not_yet", "intentional_no_stop", "needs_recommendation")
    if not conf_id:
        return 400, {"ok": False, "error": "id required"}
    if response not in valid_responses:
        return 400, {"ok": False, "error": f"response must be one of: {', '.join(valid_responses)}"}

    status_map = {"confirmed": "confirmed", "not_yet": "unconfirmed",
                  "intentional_no_stop": "intentional_no_stop", "needs_recommendation": "needs_recommendation"}

    _db_write(
        """UPDATE stop_confirmations SET
                  stop_status = %s, stop_confirmed = %s, stop_confirmed_at = %s,
                  stop_confirmation_source = 'dashboard', stop_price_confirmed = %s,
                  stop_exception_reason = %s, updated_at = NOW()
           WHERE id = %s""",
        (status_map[response], response == "confirmed", datetime.now() if response == "confirmed" else None,
         stop_price, reason, conf_id)
    )
    return 200, {"ok": True, "response": response, "id": conf_id}


def stopped_out_watch_update_verdict(body: dict):
    """POST /api/v2/stopped-out-watch/verdict — update analyst verdict on a watch item."""
    watch_id = body.get("watch_id")
    verdict = body.get("verdict", "").strip()
    summary = body.get("summary", "").strip()
    confidence = body.get("confidence")
    reentry_trigger = body.get("reentry_trigger", "")
    invalidated_if = body.get("invalidated_if", "")

    if not watch_id:
        return 400, {"ok": False, "error": "watch_id required"}
    if verdict not in ("reentry_candidate", "wait_monitor", "do_not_reenter"):
        return 400, {"ok": False, "error": "verdict must be reentry_candidate, wait_monitor, or do_not_reenter"}

    item = _db_query("SELECT id, symbol, analyst_verdict FROM stopped_out_watch WHERE id = %s", (watch_id,), fetch="one")
    if not item:
        return 404, {"ok": False, "error": "watch item not found"}

    old_verdict = item.get("analyst_verdict")
    _db_write(
        """UPDATE stopped_out_watch SET analyst_verdict = %s, analyst_confidence = %s,
                  analyst_summary = %s, reentry_trigger = %s, invalidated_if = %s,
                  last_reviewed_at = NOW(), next_review_at = CURRENT_DATE + 1, updated_at = NOW()
           WHERE id = %s""",
        (verdict, confidence, summary, reentry_trigger, invalidated_if, watch_id)
    )
    _db_write(
        """INSERT INTO stopped_out_watch_history (watch_id, symbol, changed_by, old_verdict, new_verdict, summary)
           VALUES (%s, %s, 'analyst', %s, %s, %s)""",
        (watch_id, item["symbol"], old_verdict, verdict, summary)
    )
    return 200, {"ok": True, "verdict": verdict, "watch_id": watch_id}


# Review field whitelist — only these columns can be written
_REVIEW_FIELDS = {
    "setup_family", "setup_name", "timeframe", "direction",
    "entry_type", "exit_type", "market_regime", "catalyst_type",
    "planned_r", "realized_r", "followed_plan", "well_executed",
    "execution_quality_score", "sizing_quality_score", "risk_management_score",
    "emotion_before", "emotion_during", "emotion_after",
    "confidence_before", "stress_level",
    "mistake_tags", "strength_tags",
    "lesson_learned", "review_notes", "coach_notes",
    "entry_signals", "exit_signals", "setup_types",
}


def journal_review_read(trade_key: str):
    """GET /api/v2/journal/review?trade_key=... — return review for a trade."""
    row = _db_query(
        "SELECT * FROM journal_trade_reviews WHERE trade_key = %s",
        (trade_key,), fetch="one"
    )
    if row:
        # Convert to serializable dict
        out = {}
        for k, v in row.items():
            if k in ("created_at", "updated_at", "closed_date"):
                out[k] = str(v) if v else None
            elif isinstance(v, Decimal):
                out[k] = float(v)
            else:
                out[k] = v
        return {"exists": True, "review": out}
    return {"exists": False, "review": {}, "trade_key": trade_key}


def journal_review_write(body: dict):
    """POST /api/v2/journal/review — upsert review for a trade."""
    trade_key = body.get("trade_key")
    if not trade_key:
        return 400, {"ok": False, "error": "trade_key required"}

    # Filter to allowed fields only
    fields = {k: v for k, v in body.items() if k in _REVIEW_FIELDS}
    if not fields:
        return 400, {"ok": False, "error": "no valid review fields provided"}

    # Check if review exists
    existing = _db_query(
        "SELECT id FROM journal_trade_reviews WHERE trade_key = %s",
        (trade_key,), fetch="one"
    )

    if existing:
        # UPDATE — build SET clause dynamically
        set_parts = []
        vals = []
        for k, v in fields.items():
            set_parts.append(f"{k} = %s")
            vals.append(v)
        set_parts.append("updated_at = NOW()")
        vals.append(trade_key)

        # Save history before update
        old_row = _db_query(
            "SELECT * FROM journal_trade_reviews WHERE trade_key = %s",
            (trade_key,), fetch="one"
        )
        _db_write(
            "INSERT INTO journal_trade_review_history (review_id, trade_key, old_payload, new_payload) VALUES (%s, %s, %s, %s)",
            (existing["id"], trade_key, json.dumps({k: str(v) for k, v in (old_row or {}).items()}), json.dumps({k: str(v) if v is not None else None for k, v in fields.items()}))
        )

        sql = f"UPDATE journal_trade_reviews SET {', '.join(set_parts)} WHERE trade_key = %s RETURNING id"
        result = _db_write(sql, vals)
        return 200, {"ok": True, "action": "updated", "id": result["id"] if result else existing["id"]}
    else:
        # INSERT
        fields["trade_key"] = trade_key
        fields["symbol"] = body.get("symbol", "")
        fields["account"] = body.get("account", "")
        if body.get("closed_date"):
            fields["closed_date"] = body["closed_date"]

        cols = list(fields.keys())
        placeholders = ["%s"] * len(cols)
        vals = [fields[c] for c in cols]

        sql = f"INSERT INTO journal_trade_reviews ({', '.join(cols)}) VALUES ({', '.join(placeholders)}) RETURNING id"
        result = _db_write(sql, vals)
        return 200, {"ok": True, "action": "created", "id": result["id"] if result else None}


# ── Journal Annotation Helpers ─────────────────────────────────────────────

def _suggest_setup(t):
    """AI-suggest setup type(s) based on trade characteristics.
    Returns (primary, family, rationale, suggested_types_list).
    """
    days = t.get("hold_days", 0) or 0
    pnl_pct = float(t.get("pnl_pct", 0) or 0)
    shares = int(t.get("shares", 0) or 0)
    price = float(t.get("buy_price", 0) or 0)
    tt = (t.get("trade_type") or "").upper()

    if tt == "SHORT":
        if pnl_pct < -5:
            return "short_momentum", "Momentum", "SHORT, strong move", ["short_momentum"]
        if pnl_pct > 3:
            return "short_overextended", "Mean Reversion", "SHORT stopped out", ["short_overextended"]
        return "short_momentum", "Momentum", "SHORT trade", ["short_momentum"]

    if tt == "DAY" or days == 0:
        if pnl_pct > 5:
            return "day_momentum", "Momentum", "Day trade, strong move", ["day_momentum"]
        elif pnl_pct < -3:
            return "day_failed_breakout", "Momentum", "Day trade stopped out", ["day_failed_breakout"]
        else:
            # Multi-tag: scalp + momentum when the trade shows both characteristics
            # Momentum signal: decent % gain OR high share count on a low-priced stock
            has_momentum = pnl_pct >= 2 or (price < 10 and pnl_pct >= 1 and shares >= 200)
            if has_momentum:
                return "day_scalp", "Scalp", "Day scalp with momentum (+%.1f%%)" % pnl_pct, ["day_scalp", "day_momentum"]
            else:
                return "day_scalp", "Scalp", "Day trade, small move", ["day_scalp"]

    elif days <= 5:
        tags = ["swing_momentum"]
        if pnl_pct > 5:
            tags.append("breakout_retest")
        return "swing_momentum", "Swing", "Held %d days" % days, tags
    elif days <= 30:
        return "swing_position", "Swing", "Held %d days" % days, ["swing_position"]
    elif pnl_pct > 100:
        return "long_term_compounder", "Core Position", "Multi-month +%.0f%%" % pnl_pct, ["long_term_compounder"]
    else:
        return "position_trade", "Core Position", "Held %d days" % days, ["position_trade"]


def _journal_unannotated():
    """GET /api/v2/journal/unannotated — trades missing reviews with AI suggestions."""
    rows = _db_query("""
        SELECT (t.symbol || ':' || t.account || ':' || t.close_date::text) as trade_key,
               t.symbol, t.account, t.open_date, t.close_date,
               t.trade_type, t.shares, t.buy_price, t.sell_price,
               t.cost_basis, t.proceeds, t.pnl, t.pnl_pct, t.hold_days,
               r.id as review_id, r.setup_name, r.setup_family,
               r.execution_quality_score as execution_score, r.followed_plan, r.lesson_learned as lessons
        FROM trade_closed t
        LEFT JOIN journal_trade_reviews r
          ON r.trade_key = (t.symbol || ':' || t.account || ':' || t.close_date::text)
        WHERE t.buy_price > 0 OR t.pnl != 0
        ORDER BY t.close_date DESC
    """) or []

    unannotated, annotated = [], []
    for row in rows:
        item = {k: _json_clean(v) for k, v in row.items()}
        if item.get("review_id"):
            annotated.append(item)
        else:
            s, fam, rat, tags = _suggest_setup(item)
            item["suggested_setup"] = s
            item["suggested_family"] = fam
            item["suggestion_rationale"] = rat
            item["suggested_types"] = tags
            unannotated.append(item)

    return {
        "unannotated": unannotated,
        "annotated_count": len(annotated),
        "unannotated_count": len(unannotated),
        "total": len(rows),
        "coverage_pct": round(len(annotated) / len(rows) * 100, 1) if rows else 0,
    }


def _journal_review_get(trade_key_encoded):
    """GET /api/v2/journal/review/<encoded_key> — get review by encoded trade key."""
    trade_key = trade_key_encoded.replace("__", ":")
    row = _db_query(
        "SELECT * FROM journal_trade_reviews WHERE trade_key = %s ORDER BY created_at DESC LIMIT 1",
        (trade_key,), fetch="one"
    )
    return {"exists": bool(row), "review": {k: _json_clean(v) for k, v in row.items()} if row else {}}


def _journal_bulk_suggest():
    """POST /api/v2/journal/bulk-suggest — auto-classify all unannotated trades."""
    rows = _db_query("""
        SELECT t.*, (t.symbol || ':' || t.account || ':' || t.close_date::text) as trade_key
        FROM trade_closed t
        LEFT JOIN journal_trade_reviews r
          ON r.trade_key = (t.symbol || ':' || t.account || ':' || t.close_date::text)
        WHERE r.id IS NULL AND (t.buy_price > 0 OR t.pnl != 0)
    """) or []

    created = 0
    for t in rows:
        item = {k: _json_clean(v) for k, v in t.items()}
        setup, family, timeframe = _suggest_setup(item)
        _db_write("""
            INSERT INTO journal_trade_reviews
                (trade_key, setup_type, setup_family, timeframe,
                 entry_reason, execution_score, sizing_score,
                 followed_plan, well_executed, lessons, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (trade_key) DO NOTHING
        """, [item.get("trade_key"), setup, family, timeframe,
              "AI suggested: " + setup, 3, 3, False, False,
              "Auto-classified. Please review and update."])
        created += 1

    return {"created": created, "total": len(rows)}


def _journal_reminder():
    """POST /api/v2/journal/reminder — send Telegram reminder about unannotated trades."""
    rows = _db_query("""
        SELECT COUNT(*) as cnt FROM trade_closed t
        LEFT JOIN journal_trade_reviews r
          ON r.trade_key = (t.symbol || ':' || t.account || ':' || t.close_date::text)
        WHERE r.id IS NULL AND (t.buy_price > 0 OR t.pnl != 0)
    """, fetch="one") or {}
    unannotated = rows.get("cnt", 0)

    total_row = _db_query("SELECT COUNT(*) as cnt FROM trade_closed", fetch="one") or {}
    total = total_row.get("cnt", 0)

    if unannotated > 0:
        pct = round((total - unannotated) / total * 100, 1) if total else 0
        try:
            from telegram_alert import send_telegram
            send_telegram(
                f"*Trade Journal Reminder*\n\n*{unannotated} trades* need annotation ({total} total).\n"
                f"Coverage: {pct}%\n\nhttp://192.168.50.16:7777/v2/journal"
            )
        except Exception:
            pass

    return {"unannotated": unannotated, "total": total}


def _journal_backtest_summary():
    """GET /api/v2/journal/backtest-summary"""
    rows = _db_query("""
        SELECT COUNT(*) as total,
               COUNT(CASE WHEN data_quality='full' THEN 1 END) as full_count,
               COUNT(CASE WHEN data_quality='partial' THEN 1 END) as partial_count,
               COUNT(CASE WHEN data_quality='insufficient' THEN 1 END) as insufficient_count,
               SUM(left_on_table_20d) as total_left_on_table,
               AVG(left_on_table_20d) as avg_left_on_table,
               AVG(entry_rsi) as avg_entry_rsi,
               COUNT(CASE WHEN exit_was_early THEN 1 END) as early_exits
        FROM trade_backtest_results WHERE data_quality IN ('full','partial')
    """, fetch="one") or {}
    by_entry = _db_query("""
        SELECT entry_grade, COUNT(*) as count, AVG(actual_pnl) as avg_pnl,
               SUM(CASE WHEN actual_pnl>0 THEN 1 ELSE 0 END) as wins
        FROM trade_backtest_results WHERE entry_grade IS NOT NULL AND data_quality IN ('full','partial')
        GROUP BY entry_grade ORDER BY entry_grade
    """) or []
    by_exit = _db_query("""
        SELECT exit_grade, COUNT(*) as count, SUM(left_on_table_20d) as total_left
        FROM trade_backtest_results WHERE exit_grade IS NOT NULL AND data_quality IN ('full','partial')
        GROUP BY exit_grade ORDER BY exit_grade
    """) or []
    worst_exits = _db_query("""
        SELECT symbol, trade_key, actual_exit_price, max_price_20d_after, left_on_table_20d, actual_pnl_pct
        FROM trade_backtest_results WHERE left_on_table_20d IS NOT NULL AND data_quality IN ('full','partial')
        ORDER BY left_on_table_20d DESC LIMIT 5
    """) or []

    def ser(v):
        if hasattr(v, 'isoformat'): return str(v)
        if isinstance(v, Decimal): return float(v)
        return v
    return {
        "summary": {k: ser(v) for k, v in rows.items()},
        "by_entry_grade": [{k: ser(v) for k, v in r.items()} for r in by_entry],
        "by_exit_grade": [{k: ser(v) for k, v in r.items()} for r in by_exit],
        "worst_exits": [{k: ser(v) for k, v in r.items()} for r in worst_exits],
    }


def _journal_backtest_analytics():
    """GET /api/v2/journal/backtest-analytics — aggregated backtest insights for coaching."""
    by_type = _db_query("""
        SELECT t.trade_type, COUNT(*) as count,
               AVG(CASE b.entry_grade WHEN 'A' THEN 4 WHEN 'B' THEN 3 WHEN 'C' THEN 2 WHEN 'D' THEN 1 END) as avg_entry_score,
               AVG(b.entry_rsi) as avg_entry_rsi, AVG(b.entry_volume_ratio) as avg_volume_ratio,
               SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as wins, AVG(t.pnl) as avg_pnl
        FROM trade_backtest_results b JOIN trade_closed t ON t.symbol||':'||t.account||':'||t.close_date::text = b.trade_key
        WHERE b.data_quality IN ('full','partial') GROUP BY t.trade_type ORDER BY count DESC
    """) or []
    rsi_hist = _db_query("""
        SELECT CASE WHEN entry_rsi<30 THEN 'Oversold (<30)' WHEN entry_rsi<40 THEN 'Low (30-40)'
                    WHEN entry_rsi<55 THEN 'Neutral (40-55)' WHEN entry_rsi<70 THEN 'Elevated (55-70)'
                    ELSE 'Overbought (70+)' END as bucket,
               COUNT(*) as count, AVG(actual_pnl) as avg_pnl,
               SUM(CASE WHEN actual_pnl>0 THEN 1 ELSE 0 END) as wins
        FROM trade_backtest_results WHERE entry_rsi IS NOT NULL AND data_quality IN ('full','partial')
        GROUP BY 1 ORDER BY MIN(entry_rsi)
    """) or []
    left_by_type = _db_query("""
        SELECT t.trade_type, SUM(b.left_on_table_20d) as total_left, AVG(b.left_on_table_20d) as avg_left, COUNT(*) as count
        FROM trade_backtest_results b JOIN trade_closed t ON t.symbol||':'||t.account||':'||t.close_date::text = b.trade_key
        WHERE b.left_on_table_20d IS NOT NULL AND b.data_quality IN ('full','partial')
        GROUP BY t.trade_type ORDER BY total_left DESC NULLS LAST
    """) or []

    # Coaching bullets
    coaching = []
    if by_type:
        worst = min((t for t in by_type if t.get('avg_entry_score')), key=lambda x: float(x['avg_entry_score'] or 4), default=None)
        if worst and float(worst.get('avg_entry_rsi') or 0) > 60:
            coaching.append(f"Your {worst['trade_type']} trades enter with avg RSI {float(worst['avg_entry_rsi']):.0f}. Entries below RSI 50 produce better risk/reward.")
    if left_by_type and float(left_by_type[0].get('avg_left') or 0) > 500:
        coaching.append(f"Your {left_by_type[0]['trade_type']} trades leave avg ${float(left_by_type[0]['avg_left']):.0f} on the table per trade. Consider scaling out in tranches.")
    elevated = [b for b in rsi_hist if '55-70' in (b.get('bucket') or '') or '70+' in (b.get('bucket') or '')]
    if elevated:
        n = sum(int(e.get('count', 0)) for e in elevated)
        total = sum(int(b.get('count', 1)) for b in rsi_hist)
        if total > 0 and n / total > 0.3:
            coaching.append(f"{n}/{total} entries ({n/total*100:.0f}%) have RSI above 55. Set RSI < 50 as a pre-condition for new entries.")

    def ser(v):
        if hasattr(v, 'isoformat'): return str(v)
        if isinstance(v, Decimal): return float(v)
        return v

    best_entries = _db_query("""
        SELECT b.symbol, b.trade_key, b.entry_grade, b.exit_grade,
               b.entry_rsi, b.entry_volume_ratio, b.actual_pnl, b.actual_pnl_pct
        FROM trade_backtest_results b
        WHERE b.data_quality IN ('full','partial')
        ORDER BY b.actual_pnl DESC LIMIT 10
    """) or []
    worst_exits = _db_query("""
        SELECT b.symbol, b.trade_key, b.actual_exit_price,
               b.max_price_20d_after, b.left_on_table_20d,
               b.exit_grade, b.actual_pnl_pct
        FROM trade_backtest_results b
        WHERE b.left_on_table_20d IS NOT NULL AND b.data_quality IN ('full','partial')
        ORDER BY b.left_on_table_20d DESC LIMIT 5
    """) or []

    return {
        "by_trade_type": [{k: ser(v) for k, v in r.items()} for r in by_type],
        "rsi_histogram": [{k: ser(v) for k, v in r.items()} for r in rsi_hist],
        "left_on_table_by_type": [{k: ser(v) for k, v in r.items()} for r in left_by_type],
        "best_entries": [{k: ser(v) for k, v in r.items()} for r in best_entries],
        "worst_exits": [{k: ser(v) for k, v in r.items()} for r in worst_exits],
        "coaching_bullets": coaching,
        "has_data": len(by_type) > 0,
    }


def _journal_previously_traded():
    """GET /api/v2/journal/previously-traded"""
    rows = _db_query("""
        SELECT * FROM previously_traded_watchlist
        ORDER BY CASE reentry_signal WHEN 'IN_ZONE' THEN 0 WHEN 'WATCH' THEN 1
                                     WHEN 'BELOW_ZONE' THEN 2 ELSE 3 END,
                 best_pnl_pct DESC NULLS LAST
    """) or []
    items = []
    for r in rows:
        item = {}
        for k, v in r.items():
            if hasattr(v, 'isoformat'):
                item[k] = str(v)
            elif isinstance(v, Decimal):
                item[k] = float(v)
            else:
                item[k] = v
        items.append(item)
    return {"symbols": items, "count": len(items)}


def _journal_report():
    """GET /api/v2/journal/report — master reporting endpoint for Journal Reports page.
    Query params: ?account=X &from=YYYY-MM-DD &to=YYYY-MM-DD &type=DAY
    """
    import traceback
    try:
        q = getattr(_journal_report, '_query', {}) or {}
        account_filter = q.get('account') or None
        date_from = q.get('from') or None
        date_to = q.get('to') or None
        type_filter = q.get('type') or None

        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from db_adapter import _get_conn
        import psycopg2.extras
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        where_parts = ["1=1"]
        params = []
        if account_filter:
            where_parts.append("t.account = %s")
            params.append(account_filter)
        if date_from:
            where_parts.append("t.close_date >= %s")
            params.append(date_from)
        if date_to:
            where_parts.append("t.close_date <= %s")
            params.append(date_to)
        if type_filter:
            where_parts.append("t.trade_type = %s")
            params.append(type_filter)
        where = " AND ".join(where_parts)

        def _f(v):
            if isinstance(v, Decimal): return float(v)
            if hasattr(v, 'isoformat'): return str(v)
            return v

        # ── SECTION 1: Summary stats
        cur.execute(f"""
            SELECT COUNT(*) as total_trades,
                   SUM(t.pnl) as net_pnl,
                   SUM(CASE WHEN t.pnl > 0 THEN t.pnl ELSE 0 END) as gross_profit,
                   SUM(CASE WHEN t.pnl < 0 THEN t.pnl ELSE 0 END) as gross_loss,
                   COUNT(CASE WHEN t.pnl > 0 THEN 1 END) as wins,
                   COUNT(CASE WHEN t.pnl < 0 THEN 1 END) as losses,
                   COUNT(CASE WHEN t.pnl = 0 THEN 1 END) as breakeven,
                   AVG(CASE WHEN t.pnl > 0 THEN t.pnl END) as avg_winner,
                   AVG(CASE WHEN t.pnl < 0 THEN t.pnl END) as avg_loser,
                   MAX(t.pnl) as largest_win, MIN(t.pnl) as largest_loss,
                   AVG(t.pnl) as trade_expectancy,
                   AVG(t.hold_days) as avg_hold_days, MAX(t.hold_days) as max_hold_days,
                   COUNT(DISTINCT t.symbol) as symbols_traded,
                   COUNT(DISTINCT t.account) as accounts_active,
                   STDDEV(t.pnl) as stddev_pnl
            FROM trade_closed t WHERE {where}
        """, params)
        sr = dict(cur.fetchone())
        summary = {k: _f(v) for k, v in sr.items()}
        gp = float(sr['gross_profit'] or 0)
        gl = abs(float(sr['gross_loss'] or 0))
        wins = int(sr['wins'] or 0)
        total = max(int(sr['total_trades'] or 1), 1)
        aw = float(sr['avg_winner'] or 0)
        al = abs(float(sr['avg_loser'] or 0))
        wr = wins / total
        stddev = float(sr['stddev_pnl'] or 1) or 1
        avg_pnl = float(sr['trade_expectancy'] or 0)
        summary['profit_factor'] = round(gp / gl, 2) if gl > 0 else 0
        summary['win_rate_pct'] = round(wr * 100, 2)
        summary['trade_expectancy'] = round((wr * aw) - ((1 - wr) * al), 2)
        summary['sharpe_ratio'] = round(avg_pnl / stddev, 2) if stddev > 0 else 0
        summary['gross_profit'] = round(gp, 2)
        summary['gross_loss'] = round(-gl, 2)

        # ── SECTION 2: Cumulative P&L curve
        cur.execute(f"""
            SELECT close_date, SUM(pnl) OVER (ORDER BY close_date, t.symbol) as cum_pnl,
                   pnl, symbol, trade_type
            FROM trade_closed t WHERE {where} ORDER BY close_date, t.symbol
        """, params)
        cum_curve = [{'date': str(r['close_date']), 'cum_pnl': round(float(r['cum_pnl']), 2),
                      'trade_pnl': round(float(r['pnl']), 2), 'symbol': r['symbol'],
                      'trade_type': r['trade_type']} for r in cur.fetchall()]

        # ── SECTION 3: Monthly breakdown
        cur.execute(f"""
            SELECT TO_CHAR(close_date, 'YYYY-MM') as month, COUNT(*) as trades,
                   SUM(pnl) as net_pnl, COUNT(CASE WHEN pnl > 0 THEN 1 END) as wins,
                   COUNT(CASE WHEN pnl < 0 THEN 1 END) as losses,
                   AVG(pnl) as avg_pnl, MAX(pnl) as best_trade, MIN(pnl) as worst_trade
            FROM trade_closed t WHERE {where}
            GROUP BY TO_CHAR(close_date, 'YYYY-MM') ORDER BY month
        """, params)
        monthly = [{k: _f(v) for k, v in dict(r).items()} for r in cur.fetchall()]

        # ── SECTION 4: By trade type
        cur.execute(f"""
            SELECT trade_type, COUNT(*) as trades, SUM(pnl) as net_pnl,
                   COUNT(CASE WHEN pnl > 0 THEN 1 END) as wins, AVG(pnl) as avg_pnl,
                   AVG(hold_days) as avg_hold_days, MAX(pnl) as best_trade, MIN(pnl) as worst_trade,
                   SUM(CASE WHEN pnl>0 THEN pnl ELSE 0 END) as gross_profit,
                   SUM(CASE WHEN pnl<0 THEN pnl ELSE 0 END) as gross_loss
            FROM trade_closed t WHERE {where} GROUP BY trade_type ORDER BY net_pnl DESC NULLS LAST
        """, params)
        by_type = []
        for r in cur.fetchall():
            row = {k: _f(v) for k, v in dict(r).items()}
            tn = int(row.get('trades') or 1)
            wn = int(row.get('wins') or 0)
            row['win_rate_pct'] = round(wn / tn * 100, 1) if tn > 0 else 0
            rgp = abs(float(row.get('gross_profit') or 0))
            rgl = abs(float(row.get('gross_loss') or 0))
            row['profit_factor'] = round(rgp / rgl, 2) if rgl > 0 else 0
            by_type.append(row)

        # ── SECTION 5: By symbol (top 20)
        cur.execute(f"""
            SELECT symbol, COUNT(*) as trades, SUM(pnl) as net_pnl,
                   COUNT(CASE WHEN pnl > 0 THEN 1 END) as wins, AVG(pnl) as avg_pnl,
                   MAX(pnl) as best_trade, MIN(pnl) as worst_trade, AVG(hold_days) as avg_hold_days
            FROM trade_closed t WHERE {where} GROUP BY symbol ORDER BY net_pnl DESC NULLS LAST LIMIT 20
        """, params)
        by_symbol = []
        for r in cur.fetchall():
            row = {k: _f(v) for k, v in dict(r).items()}
            tn = int(row.get('trades') or 1); wn = int(row.get('wins') or 0)
            row['win_rate_pct'] = round(wn / tn * 100, 1) if tn > 0 else 0
            by_symbol.append(row)

        # ── SECTION 6: By hold duration
        cur.execute(f"""
            SELECT CASE WHEN hold_days = 0 THEN 'Same day'
                        WHEN hold_days <= 5 THEN '1-5 days'
                        WHEN hold_days <= 30 THEN '6-30 days'
                        WHEN hold_days <= 90 THEN '31-90 days'
                        ELSE '90+ days' END as duration_bucket,
                   COUNT(*) as trades, SUM(pnl) as net_pnl,
                   COUNT(CASE WHEN pnl > 0 THEN 1 END) as wins, AVG(pnl) as avg_pnl
            FROM trade_closed t WHERE {where} GROUP BY 1 ORDER BY MIN(hold_days)
        """, params)
        by_duration = []
        for r in cur.fetchall():
            row = {k: _f(v) for k, v in dict(r).items()}
            tn = int(row.get('trades') or 1); wn = int(row.get('wins') or 0)
            row['win_rate_pct'] = round(wn / tn * 100, 1) if tn > 0 else 0
            by_duration.append(row)

        # ── SECTION 7: Day of week
        cur.execute(f"""
            SELECT TRIM(TO_CHAR(close_date, 'Day')) as day_name,
                   EXTRACT(DOW FROM close_date) as day_num,
                   COUNT(*) as trades, SUM(pnl) as net_pnl,
                   COUNT(CASE WHEN pnl > 0 THEN 1 END) as wins, AVG(pnl) as avg_pnl
            FROM trade_closed t WHERE {where} GROUP BY 1, 2 ORDER BY 2
        """, params)
        by_dow = []
        for r in cur.fetchall():
            row = {k: _f(v) for k, v in dict(r).items()}
            tn = int(row.get('trades') or 1); wn = int(row.get('wins') or 0)
            row['win_rate_pct'] = round(wn / tn * 100, 1) if tn > 0 else 0
            by_dow.append(row)

        # ── SECTION 8: By account
        cur.execute(f"""
            SELECT account, COUNT(*) as trades, SUM(pnl) as net_pnl,
                   COUNT(CASE WHEN pnl > 0 THEN 1 END) as wins, AVG(pnl) as avg_pnl
            FROM trade_closed t WHERE {where} GROUP BY account ORDER BY net_pnl DESC
        """, params)
        by_account = []
        for r in cur.fetchall():
            row = {k: _f(v) for k, v in dict(r).items()}
            tn = int(row.get('trades') or 1); wn = int(row.get('wins') or 0)
            row['win_rate_pct'] = round(wn / tn * 100, 1) if tn > 0 else 0
            by_account.append(row)

        # ── SECTION 9: Streaks
        cur.execute(f"""
            SELECT pnl FROM trade_closed t WHERE {where} ORDER BY close_date, t.symbol
        """, params)
        max_win = max_loss = cw = cl = 0
        for r in cur.fetchall():
            if float(r['pnl']) > 0:
                cw += 1; cl = 0; max_win = max(max_win, cw)
            else:
                cl += 1; cw = 0; max_loss = max(max_loss, cl)
        streaks = {'max_win_streak': max_win, 'max_loss_streak': max_loss}

        # ── SECTION 10: Backtest grades
        cur.execute(f"""
            SELECT b.entry_grade, b.exit_grade, COUNT(*) as trades,
                   AVG(b.entry_rsi) as avg_entry_rsi,
                   AVG(b.entry_volume_ratio) as avg_volume_ratio,
                   SUM(b.left_on_table_20d) as total_left_on_table,
                   COUNT(CASE WHEN b.exit_was_early THEN 1 END) as early_exits
            FROM trade_backtest_results b
            JOIN trade_closed t ON (t.symbol || ':' || t.account || ':' || t.close_date::text) = b.trade_key
            WHERE b.data_quality IN ('full','partial') AND {where}
            GROUP BY b.entry_grade, b.exit_grade ORDER BY b.entry_grade, b.exit_grade
        """, params)
        backtest_grades = [{k: _f(v) for k, v in dict(r).items()} for r in cur.fetchall()]

        # ── SECTION 11: Top trades
        cur.execute(f"""
            SELECT symbol, trade_type, account, open_date, close_date,
                   buy_price, sell_price, pnl, pnl_pct, hold_days, shares
            FROM trade_closed t WHERE {where} ORDER BY pnl DESC LIMIT 5
        """, params)
        top_winners = [{k: _f(v) for k, v in dict(r).items()} for r in cur.fetchall()]
        cur.execute(f"""
            SELECT symbol, trade_type, account, open_date, close_date,
                   buy_price, sell_price, pnl, pnl_pct, hold_days, shares
            FROM trade_closed t WHERE {where} ORDER BY pnl ASC LIMIT 5
        """, params)
        top_losers = [{k: _f(v) for k, v in dict(r).items()} for r in cur.fetchall()]

        # ── SECTION 12: RSI histogram
        cur.execute("""
            SELECT bucket, count, avg_pnl, wins FROM (
              SELECT CASE WHEN b.entry_rsi < 30 THEN 'Oversold <30'
                          WHEN b.entry_rsi < 40 THEN '30-40'
                          WHEN b.entry_rsi < 50 THEN '40-50'
                          WHEN b.entry_rsi < 60 THEN '50-60'
                          WHEN b.entry_rsi < 70 THEN '60-70'
                          WHEN b.entry_rsi < 80 THEN '70-80'
                          ELSE 'Overbought 80+' END as bucket,
                     COUNT(*) as count, AVG(t.pnl) as avg_pnl,
                     SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as wins,
                     MIN(b.entry_rsi) as bucket_min
              FROM trade_backtest_results b
              JOIN trade_closed t ON (t.symbol || ':' || t.account || ':' || t.close_date::text) = b.trade_key
              WHERE b.entry_rsi IS NOT NULL AND b.data_quality IN ('full','partial')
              GROUP BY 1
            ) sub ORDER BY bucket_min
        """)
        rsi_histogram = [{k: _f(v) for k, v in dict(r).items()} for r in cur.fetchall()]

        # ── SECTION 13: Annotation coverage
        cur.execute("""
            SELECT COUNT(DISTINCT (t.symbol || ':' || t.account || ':' || t.close_date::text)) as total_trades,
                   COUNT(DISTINCT r.trade_key) as reviewed,
                   COUNT(CASE WHEN r.setup_types IS NOT NULL AND array_length(r.setup_types,1) > 0 THEN 1 END) as human_annotated,
                   COUNT(CASE WHEN r.execution_quality_score IS NOT NULL THEN 1 END) as has_execution_score,
                   COUNT(CASE WHEN r.lesson_learned IS NOT NULL AND r.lesson_learned != ''
                               AND r.lesson_learned != 'Auto-classified. Please review and update.' THEN 1 END) as has_lessons
            FROM trade_closed t
            LEFT JOIN journal_trade_reviews r ON r.trade_key = (t.symbol || ':' || t.account || ':' || t.close_date::text)
        """)
        annotation = {k: int(v) if v is not None else 0 for k, v in dict(cur.fetchone()).items()}

        # ── SECTION 14: Coaching insights
        coaching = []
        cur.execute("SELECT SUM(pnl) as v_pnl FROM trade_closed WHERE symbol='V'")
        v_pnl = float((cur.fetchone() or {}).get('v_pnl') or 0)
        total_pnl = float(sr.get('net_pnl') or 1)
        v_pct = (v_pnl / total_pnl * 100) if total_pnl > 0 else 0
        if v_pct > 80:
            coaching.append({'type': 'concentration_risk', 'severity': 'high',
                'title': 'Extreme P&L Concentration',
                'body': f'V (Visa) accounts for {v_pct:.0f}% of total P&L (+${v_pnl:,.0f}). Remove V from the dataset to see your actual trading performance. Without V, this journal is approximately break-even.',
                'action': 'Evaluate performance with V excluded using the account/type filters.'})

        cur.execute("""
            SELECT AVG(entry_rsi) as avg_rsi,
                   COUNT(CASE WHEN entry_rsi > 65 THEN 1 END) as high_rsi_count, COUNT(*) as total
            FROM trade_backtest_results WHERE data_quality IN ('full','partial')
        """)
        rsi_row = dict(cur.fetchone())
        avg_rsi = float(rsi_row.get('avg_rsi') or 0)
        high_rsi_pct = (int(rsi_row.get('high_rsi_count') or 0) / max(int(rsi_row.get('total') or 1), 1)) * 100
        if avg_rsi > 60:
            coaching.append({'type': 'entry_quality', 'severity': 'high',
                'title': 'Entering Overbought Consistently',
                'body': f'Average RSI at entry: {avg_rsi:.0f}. {high_rsi_pct:.0f}% of backtested entries had RSI above 65. You are typically chasing price, not buying pullbacks.',
                'action': 'Set RSI < 55 as a hard entry filter for new swing/position trades.'})

        cur.execute("""
            SELECT SUM(left_on_table_20d) as total_left, AVG(left_on_table_20d) as avg_left,
                   COUNT(CASE WHEN exit_was_early THEN 1 END) as early_exits, COUNT(*) as total
            FROM trade_backtest_results WHERE data_quality IN ('full','partial')
        """)
        exit_row = dict(cur.fetchone())
        early_pct = (int(exit_row.get('early_exits') or 0) / max(int(exit_row.get('total') or 1), 1)) * 100
        total_left = float(exit_row.get('total_left') or 0)
        avg_left = float(exit_row.get('avg_left') or 0)
        if early_pct > 40:
            coaching.append({'type': 'exit_timing', 'severity': 'medium',
                'title': 'Exiting Too Early',
                'body': f'{early_pct:.0f}% of trades had significant upside in the 5 days after exit. Total money left on table (20-day window): ${total_left:,.0f}. Average per trade: ${avg_left:,.0f}.',
                'action': 'Implement partial exits: sell 50% at +15%, trail stop on remainder.'})

        cur.execute("""
            SELECT TRIM(TO_CHAR(close_date, 'Day')) as day_name, AVG(pnl) as avg_pnl,
                   COUNT(CASE WHEN pnl > 0 THEN 1 END) as wins, COUNT(*) as total
            FROM trade_closed GROUP BY 1 HAVING COUNT(*) >= 3 ORDER BY avg_pnl ASC LIMIT 1
        """)
        worst_day = cur.fetchone()
        if worst_day:
            wd = dict(worst_day)
            wd_wr = int(wd.get('wins', 0)) / max(int(wd.get('total', 1)), 1) * 100
            if float(wd.get('avg_pnl', 0)) < 0:
                coaching.append({'type': 'timing_pattern', 'severity': 'low',
                    'title': f'{wd["day_name"].strip()} is Your Worst Trading Day',
                    'body': f'{wd["day_name"].strip()} shows avg P&L of ${float(wd["avg_pnl"]):.0f} with {wd_wr:.0f}% win rate across {wd["total"]} trades.',
                    'action': f'Track {wd["day_name"].strip()} trades separately for 30 days.'})

        # ── SECTION 15: Daily P&L for calendar (with per-ticker breakdown)
        cur.execute(f"""
            SELECT close_date::text as date, SUM(pnl) as daily_pnl,
                   COUNT(*) as trade_count, COUNT(CASE WHEN pnl>0 THEN 1 END) as wins,
                   MAX(pnl) as best_trade_pnl
            FROM trade_closed t WHERE {where} GROUP BY close_date ORDER BY close_date
        """, params)
        daily_pnl = [{k: _f(v) for k, v in dict(r).items()} for r in cur.fetchall()]

        # Per-ticker trades per day (for calendar drill-down)
        cur.execute(f"""
            SELECT close_date::text as date, symbol, pnl, buy_price, sell_price,
                   shares, trade_type, account
            FROM trade_closed t WHERE {where} ORDER BY close_date, symbol
        """, params)
        daily_trades_raw = cur.fetchall()
        daily_trades = {}
        for r in daily_trades_raw:
            row = {k: _f(v) for k, v in dict(r).items()}
            day = row['date']
            if day not in daily_trades:
                daily_trades[day] = []
            daily_trades[day].append(row)

        # Attach trades to daily_pnl entries
        for dp in daily_pnl:
            dp['trades'] = daily_trades.get(dp['date'], [])

        # ── SECTION 16: Signal analytics
        cur.execute("""
            SELECT UNNEST(r.entry_signals) as signal, COUNT(*) as count,
                   AVG(t.pnl) as avg_pnl, SUM(CASE WHEN t.pnl>0 THEN 1 ELSE 0 END) as wins
            FROM journal_trade_reviews r JOIN trade_closed t ON (t.symbol || ':' || t.account || ':' || t.close_date::text) = r.trade_key
            WHERE r.entry_signals IS NOT NULL AND array_length(r.entry_signals,1) > 0
            GROUP BY 1 HAVING COUNT(*) >= 2 ORDER BY avg_pnl DESC
        """)
        signal_perf = []
        for r in cur.fetchall():
            row = {k: _f(v) for k, v in dict(r).items()}
            row['win_rate_pct'] = round(int(row['wins']) / max(int(row['count']), 1) * 100, 1)
            signal_perf.append(row)

        # ── SECTION 17: Setup type performance
        cur.execute("""
            SELECT UNNEST(r.setup_types) as setup, COUNT(*) as count,
                   AVG(t.pnl) as avg_pnl, SUM(CASE WHEN t.pnl>0 THEN 1 ELSE 0 END) as wins,
                   AVG(r.execution_quality_score) as avg_execution,
                   AVG(r.realized_r) as avg_realized_r
            FROM journal_trade_reviews r JOIN trade_closed t ON (t.symbol || ':' || t.account || ':' || t.close_date::text) = r.trade_key
            WHERE r.setup_types IS NOT NULL AND array_length(r.setup_types,1) > 0
            GROUP BY 1 ORDER BY avg_pnl DESC
        """)
        setup_perf = [{k: _f(v) for k, v in dict(r).items()} for r in cur.fetchall()]

        # ── SECTION 18: Psychology correlation
        cur.execute("""
            SELECT r.emotion_before, COUNT(*) as count, AVG(t.pnl) as avg_pnl,
                   SUM(CASE WHEN t.pnl>0 THEN 1 ELSE 0 END) as wins,
                   AVG(r.execution_quality_score) as avg_execution
            FROM journal_trade_reviews r JOIN trade_closed t ON (t.symbol || ':' || t.account || ':' || t.close_date::text) = r.trade_key
            WHERE r.emotion_before IS NOT NULL GROUP BY 1 HAVING COUNT(*) >= 2 ORDER BY avg_pnl DESC
        """)
        emotion_perf = [{k: _f(v) for k, v in dict(r).items()} for r in cur.fetchall()]

        # ── SECTION 19: R-multiple tracking
        cur.execute("""
            SELECT AVG(r.planned_r) as avg_planned_r, AVG(r.realized_r) as avg_realized_r,
                   COUNT(CASE WHEN r.realized_r >= r.planned_r THEN 1 END) as met_target,
                   COUNT(CASE WHEN r.planned_r IS NOT NULL THEN 1 END) as has_plan,
                   AVG(r.execution_quality_score) as avg_execution,
                   AVG(r.risk_management_score) as avg_risk_mgmt
            FROM journal_trade_reviews r JOIN trade_closed t ON (t.symbol || ':' || t.account || ':' || t.close_date::text) = r.trade_key
        """)
        r_multiple = {k: _f(v) for k, v in dict(cur.fetchone() or {}).items()}

        # ── SECTION 20: Mistake / strength frequency
        cur.execute("""
            SELECT UNNEST(mistake_tags) as tag, COUNT(*) as count
            FROM journal_trade_reviews WHERE mistake_tags IS NOT NULL AND array_length(mistake_tags,1) > 0
            GROUP BY 1 ORDER BY count DESC LIMIT 10
        """)
        mistake_freq = [{k: _f(v) for k, v in dict(r).items()} for r in cur.fetchall()]
        cur.execute("""
            SELECT UNNEST(strength_tags) as tag, COUNT(*) as count
            FROM journal_trade_reviews WHERE strength_tags IS NOT NULL AND array_length(strength_tags,1) > 0
            GROUP BY 1 ORDER BY count DESC LIMIT 10
        """)
        strength_freq = [{k: _f(v) for k, v in dict(r).items()} for r in cur.fetchall()]

        conn.close()

        return {
            'summary': summary, 'cumulative_pnl': cum_curve, 'monthly': monthly,
            'by_trade_type': by_type, 'by_symbol': by_symbol,
            'by_hold_duration': by_duration, 'by_day_of_week': by_dow,
            'by_account': by_account, 'streaks': streaks,
            'backtest_grades': backtest_grades, 'top_winners': top_winners,
            'top_losers': top_losers, 'rsi_histogram': rsi_histogram,
            'annotation_coverage': annotation, 'coaching_insights': coaching,
            'daily_pnl': daily_pnl, 'signal_performance': signal_perf,
            'setup_performance': setup_perf, 'emotion_performance': emotion_perf,
            'r_multiple_tracking': r_multiple,
            'mistake_frequency': mistake_freq, 'strength_frequency': strength_freq,
            'filters_applied': {'account': account_filter, 'date_from': date_from,
                               'date_to': date_to, 'trade_type': type_filter}
        }
    except Exception as e:
        import traceback as _tb
        raise RuntimeError(f"journal_report error: {e}\n{_tb.format_exc()}")

_journal_report._query = {}


def _tradeai_critique_status():
    """GET /api/v2/trade-ai/critique — latest critique results from CSV data."""
    # The critique data is embedded in the trade_ai CSV. Return a summary.
    import csv, io, glob
    results = []
    for pattern in ["reports/2026-*/*/run_summary.json"]:
        for fp in sorted(glob.glob(str(PROJECT_ROOT / pattern)), reverse=True)[:2]:
            csv_dir = str(Path(fp).parent)
            csvs = sorted(glob.glob(csv_dir + "/trade_ai_*_watchlist.csv"))
            if csvs:
                try:
                    rows = list(csv.DictReader(io.StringIO(Path(csvs[-1]).read_text())))
                    for r in rows:
                        if r.get("CriticVerdict"):
                            results.append({
                                "symbol": r.get("Symbol", ""),
                                "decision": r.get("Decision", ""),
                                "original_decision": r.get("OrigDecision", ""),
                                "critic_verdict": r.get("CriticVerdict", ""),
                                "decision_changed": r.get("DecisionChanged", "").lower() == "true",
                                "disqualified": r.get("Disqualified", "").lower() == "true",
                                "catalyst_verified": r.get("CatalystVerified", ""),
                                "industry": r.get("Industry", ""),
                                "reasoning": r.get("CriticReasoning", ""),
                            })
                except Exception:
                    pass
            if results: break
    blocked = sum(1 for r in results if r.get("disqualified"))
    changed = sum(1 for r in results if r.get("decision_changed"))
    return {"results": results, "count": len(results), "blocked": blocked, "changed": changed}


def _tradeai_history():
    """GET /api/v2/trade-ai/history — historical scan data for trend analysis."""
    try:
        # Per-symbol aggregated history
        symbols = _db_query("""
            SELECT symbol,
                   COUNT(DISTINCT run_date) as days_appeared,
                   COUNT(DISTINCT run_date) FILTER (WHERE decision = 'GO') as go_days,
                   COUNT(DISTINCT run_date) FILTER (WHERE decision = 'WAIT') as wait_days,
                   COUNT(*) as total_scans,
                   MAX(score) as peak_score,
                   ROUND(AVG(score)::numeric, 1) as avg_score,
                   MIN(run_date) as first_seen,
                   MAX(run_date) as last_seen,
                   MAX(rvol) as peak_rvol,
                   ROUND(AVG(rvol)::numeric, 1) as avg_rvol
            FROM trade_ai_scans
            WHERE run_type = 'full'
            GROUP BY symbol
            ORDER BY days_appeared DESC, peak_score DESC
        """) or []

        # Recent daily summary (last 30 days)
        daily = _db_query("""
            SELECT run_date,
                   COUNT(DISTINCT symbol) as tickers,
                   COUNT(DISTINCT symbol) FILTER (WHERE decision = 'GO') as go_count,
                   COUNT(DISTINCT symbol) FILTER (WHERE decision = 'WAIT') as wait_count,
                   MAX(score) as top_score
            FROM trade_ai_scans
            WHERE run_type = 'full'
              AND run_date >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY run_date
            ORDER BY run_date DESC
        """) or []

        # Recurring symbols (appeared 3+ days)
        recurring = [s for s in symbols if (s.get("days_appeared") or 0) >= 3]

        return {
            "symbols": [{k: _json_clean(v) for k, v in s.items()} for s in symbols],
            "daily_summary": [{k: _json_clean(v) for k, v in d.items()} for d in daily],
            "recurring_count": len(recurring),
            "total_symbols_tracked": len(symbols),
            "total_scans": sum(s.get("total_scans", 0) for s in symbols),
        }
    except Exception as e:
        return {"error": str(e), "symbols": [], "daily_summary": []}


def _tradeai_symbol_history():
    """GET /api/v2/trade-ai/history/<symbol> — detailed history for one symbol."""
    return {"error": "Use query param: /api/v2/trade-ai/history?symbol=RLYB"}


def _journal_agent_coaching():
    """GET /api/v2/journal/agent-coaching — cached agent coaching insights."""
    try:
        rows = _db_query("""
            SELECT id, agent_name, coaching_type, severity, title, body,
                   action_item, supporting_trades, model_used,
                   trades_analyzed, created_at
            FROM journal_agent_coaching
            WHERE expires_at > NOW()
            ORDER BY
                CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                created_at DESC
        """) or []
        items = [{k: _json_clean(v) for k, v in r.items()} for r in rows]
        last_row = _db_query("SELECT MAX(created_at) as lr FROM journal_agent_coaching", fetch="one")
        return {
            'insights': items,
            'count': len(items),
            'last_run': str(last_row['lr']) if last_row and last_row.get('lr') else None,
            'agents': list(set(r.get('agent_name', '') for r in items))
        }
    except Exception as e:
        return {'error': str(e)}


_SCREENER_DISPLAY = {
    'day_scalp': 'Finviz Day Scalp (RVOL + Float)',
    'swing_trade': 'Finviz Swing Trade (Momentum)',
    'speculative_growth': 'Finviz Speculative Growth',
    'dividend_growth': 'Finviz Dividend Growth',
    'covered_call': 'Finviz Covered Call Income',
    'high_yield': 'Finviz High Yield BDC',
    'income_etf': 'Finviz Income ETF',
    'core_growth': 'Finviz Core Growth Compounder',
    'defense_thesis': 'Finviz Defense / Aerospace',
    'core_holding': 'Finviz Core Holding',
    'core_index': 'Finviz Core Index',
    'recovery': 'Finviz Recovery Watch',
    'international': 'Finviz International Dividend',
    'reit': 'Finviz REIT Income',
    'bond': 'Finviz Bond Income',
    'social_scalp': 'Social Scalp Scanner',
    'screener': 'Finviz Multi-Screener',
}


def _resolve_screener_display(screener_name, source_table=None):
    if source_table and 'incubator' in source_table.lower():
        return screener_name or 'Incubator'
    if screener_name:
        return _SCREENER_DISPLAY.get(screener_name, f"Screener: {screener_name}")
    return 'Orchestrator Auto-Scan'


def _expire_stale_proposals(conn):
    """Expire stale pending proposals: intraday>8h, past expires_at, entry missed>15%."""
    INTRADAY = ['gap_and_go', 'momentum_scalp']
    try:
        cur = conn.cursor()
        # 1. Intraday > 8 hours old
        cur.execute("""
            UPDATE paper_trade_proposals
            SET status='expired', lifecycle_status='EXPIRED',
                lifecycle_message='Intraday proposal: expired after market close'
            WHERE status='PENDING'
              AND (strategy_id = ANY(%s) OR proposal_timeframe_class='intraday')
              AND created_at < NOW() - INTERVAL '8 hours'
        """, [INTRADAY])
        # 2. expires_at for non-intraday
        cur.execute("""
            UPDATE paper_trade_proposals
            SET status='expired', lifecycle_status='EXPIRED',
                lifecycle_message='Proposal expired — past scheduled expiry window'
            WHERE status='PENDING'
              AND expires_at IS NOT NULL AND expires_at < NOW()
              AND strategy_id != ALL(%s)
        """, [INTRADAY])
        # 3. ENTRY_MISSED > 15% drift
        cur.execute("""
            UPDATE paper_trade_proposals
            SET status='expired', lifecycle_status='EXPIRED',
                lifecycle_message='Entry missed — price drifted beyond recovery (>15%%)'
            WHERE status='PENDING'
              AND entry_zone_status='ENTRY_MISSED'
              AND ABS(price_drift_pct) > 15
        """)
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.getLogger(__name__).warning(f"[expiry] {e}")


def _derive_pipeline_stages(prop):
    """Derive 8-stage pipeline status for a proposal."""
    source_table = prop.get('source_table') or ''
    stages = []
    # 1. Screener
    stages.append({
        'id': 'screener', 'label': 'Screened',
        'status': 'DONE',  # All proposals come from some screening process
        'detail': prop.get('screener_display_name') or 'Auto',
        'timestamp': _json_clean(prop.get('created_at')),
    })
    # 2. Incubator
    _from_incubator = 'incubator' in source_table.lower()
    stages.append({
        'id': 'incubator', 'label': 'Incubated',
        'status': 'DONE' if _from_incubator else 'SKIPPED',
        'detail': 'From incubator' if _from_incubator else 'Direct from screener',
        'timestamp': None,
    })
    # 3. Score
    stages.append({
        'id': 'score', 'label': 'Scored',
        'status': 'DONE' if prop.get('signal_score') else 'PENDING',
        'detail': f"{prop.get('signal_grade', '?')} {prop.get('signal_score', '?')}pts" if prop.get('signal_score') else None,
        'timestamp': None,
    })
    # 4. Catalyst
    cat = prop.get('catalyst_verified')
    stages.append({
        'id': 'catalyst', 'label': 'Catalyst',
        'status': 'DONE' if cat else ('ISSUE' if cat is False else 'PENDING'),
        'detail': 'Verified' if cat else ('Unverified' if cat is False else 'Not checked'),
        'timestamp': None,
    })
    # 5. Risk gate
    rg = prop.get('risk_gate_result')
    stages.append({
        'id': 'risk_gate', 'label': 'Risk Gate',
        'status': 'DONE' if rg in ('PASS', 'APPROVED') else ('ISSUE' if rg in ('FAIL', 'REJECTED') else 'PENDING'),
        'detail': rg or 'Not checked',
        'timestamp': None,
    })
    # 6. LLM Review
    llm = prop.get('llm_analysis')
    ns = prop.get('narrative_source', '')
    stages.append({
        'id': 'llm_review', 'label': 'AI Review',
        'status': 'DONE' if llm and 'fallback' not in str(ns).lower() and 'deterministic' not in str(ns).lower()
                  else ('ISSUE' if 'fallback' in str(ns).lower() or 'deterministic' in str(ns).lower() else 'PENDING'),
        'detail': str(ns)[:30] if ns else 'Not run',
        'timestamp': None,
    })
    # 7. Execution
    er = prop.get('execution_readiness') or {}
    rs = er.get('readiness_state', '')
    stages.append({
        'id': 'execution', 'label': 'Execution',
        'status': 'DONE' if rs in ('READY_FOR_PAPER_SUBMIT', 'READY_ORB_CONFIRMED', 'CAUTION_EXECUTABLE')
                  else ('ISSUE' if 'BLOCKED' in str(rs) else 'PENDING'),
        'detail': rs.replace('BLOCKED_', '').replace('_', ' ')[:25] if rs else 'Not checked',
        'timestamp': None,
    })
    # 8. Ready
    lc = prop.get('lifecycle_status', '')
    ez = prop.get('entry_zone_status', '')
    stages.append({
        'id': 'ready', 'label': 'Ready',
        'status': 'DONE' if ez == 'ENTRY_ZONE_VALID' else ('ISSUE' if lc in ('ENTRY_MISSED', 'STALE', 'EXPIRED') else 'PENDING'),
        'detail': (ez or lc or 'Unknown').replace('_', ' '),
        'timestamp': None,
    })
    return stages


def _paper_proposals_enriched():
    """GET /api/v2/paper-proposals — enriched decision packet proposals."""
    try:
        # Expire stale proposals before reading
        try:
            from db_adapter import _get_conn as _gc
            _conn = _gc()
            if _conn:
                _expire_stale_proposals(_conn)
                _conn.close()
        except Exception:
            pass

        # Read portfolio value for risk %
        portfolio_value = 1000000.0
        try:
            _hpath = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
            if _hpath.exists():
                _hd = json.loads(_hpath.read_text())
                portfolio_value = float(_hd.get('portfolio_totals', {}).get('total_value', 1000000))
        except Exception:
            pass

        rows = _db_query("""
            SELECT ptp.*,
                   -- Scan data
                   scan.score as scan_score, scan.decision as scan_decision,
                   scan.grade as scan_grade, scan.price as scan_price,
                   scan.rvol as scan_rvol, scan.float_m as scan_float_m,
                   scan.gap_pct as scan_gap_pct, scan.change_pct as scan_change_pct,
                   scan.catalyst as scan_catalyst,
                   scan.catalyst_verified as scan_catalyst_verified,
                   scan.catalyst_confidence as scan_catalyst_confidence,
                   scan.critic_verdict as scan_critic_verdict,
                   scan.critic_confidence as scan_critic_confidence,
                   scan.critic_reasoning as scan_critic_reasoning,
                   scan.sector as scan_sector, scan.industry as scan_industry,
                   scan.country as scan_country, scan.sector_etf as scan_sector_etf,
                   scan.ticker_perf_1m, scan.sector_perf_1m, scan.vs_sector_pct,
                   scan.intelligence_readiness as scan_intel,
                   scan.source as scan_source, scan.screener_label as scan_screener,
                   -- Indicator data
                   ind.atr as ind_atr, ind.confluence_score, ind.confluence_tier,
                   ind.adx_regime, ind.entry_quality,
                   ind.full_result as ind_full_result,
                   -- News
                   news_agg.headlines as recent_headlines,
                   -- Proposal analysis
                   pa.summary as pa_summary, pa.approve_case as pa_approve_case,
                   pa.reject_case as pa_reject_case, pa.invalidation as pa_invalidation,
                   pa.narrative_source as pa_narrative_source,
                   pa.confidence as pa_confidence,
                   pa.missing_data as pa_missing_data
            FROM paper_trade_proposals ptp
            LEFT JOIN LATERAL (
                SELECT * FROM trade_ai_scans
                WHERE symbol = ptp.symbol
                ORDER BY scanned_at DESC LIMIT 1
            ) scan ON true
            LEFT JOIN LATERAL (
                SELECT * FROM indicator_confluence_cache
                WHERE symbol = ptp.symbol
                ORDER BY computed_at DESC LIMIT 1
            ) ind ON true
            LEFT JOIN LATERAL (
                SELECT json_agg(json_build_object(
                    'title', title, 'source', source,
                    'published_at', published_at,
                    'sentiment', sentiment
                ) ORDER BY published_at DESC) as headlines
                FROM (
                    SELECT title, source, published_at, sentiment
                    FROM news_articles
                    WHERE symbol = ptp.symbol
                    AND published_at > NOW() - INTERVAL '3 days'
                    ORDER BY published_at DESC LIMIT 3
                ) sub
            ) news_agg ON true
            LEFT JOIN LATERAL (
                SELECT * FROM paper_proposal_analysis
                WHERE proposal_id = ptp.id
                ORDER BY created_at DESC LIMIT 1
            ) pa ON true
            ORDER BY
                CASE ptp.status WHEN 'PENDING' THEN 0 ELSE 1 END,
                COALESCE(ptp.confidence_score, 0) DESC,
                ptp.created_at DESC
            LIMIT 50
        """) or []

        proposals = []
        for r in rows:
            p = {k: _json_clean(v) for k, v in r.items()}

            # Merge scan data into proposal where proposal is empty
            rvol = p.get('rvol') or p.get('scan_rvol')
            float_m = p.get('float_m') or p.get('scan_float_m')
            gap_pct = p.get('gap_pct') or p.get('scan_gap_pct')
            catalyst = p.get('catalyst') or p.get('scan_catalyst')
            catalyst_verified = p.get('scan_catalyst_verified') if p.get('scan_catalyst_verified') else p.get('catalyst_verified')
            catalyst_confidence = p.get('catalyst_confidence') or p.get('scan_catalyst_confidence')
            critic_verdict = p.get('critic_verdict') or p.get('scan_critic_verdict')
            critic_confidence = p.get('critic_confidence') or p.get('scan_critic_confidence')
            critic_reasoning = p.get('critic_reasoning') or p.get('scan_critic_reasoning')
            sector = p.get('sector') or p.get('scan_sector')
            industry = p.get('industry') or p.get('scan_industry')
            country = p.get('country') or p.get('scan_country')
            intel = p.get('intel_readiness') or p.get('scan_intel')
            signal_grade = p.get('signal_grade') or p.get('scan_grade')
            signal_score = p.get('signal_score') or p.get('scan_score')

            entry = float(p.get('proposed_entry') or 0)
            stop = float(p.get('proposed_stop') or 0)
            t1 = float(p.get('proposed_target1') or 0)
            t2 = float(p.get('proposed_target2') or 0)
            shares = int(p.get('proposed_shares') or 0)

            # Risk/reward math
            dollar_risk = abs(entry - stop) * shares if entry and stop and shares else 0
            t1_reward = (t1 - entry) * shares if t1 and entry and shares else 0
            t2_reward = (t2 - entry) * shares if t2 and entry and shares else 0
            risk_pct = (dollar_risk / portfolio_value * 100) if dollar_risk and portfolio_value else 0
            rr_t1 = (t1 - entry) / (entry - stop) if entry > stop and t1 > entry else 0
            rr_t2 = (t2 - entry) / (entry - stop) if entry > stop and t2 > entry else 0

            # Technical state from indicators
            atr = p.get('atr') or p.get('ind_atr')
            atr_pct = (float(atr) / entry * 100) if atr and entry else None

            # Extract RSI/VWAP from indicator full_result
            rsi = p.get('rsi')
            vwap_dist = p.get('vwap_distance')
            above_vwap = p.get('above_vwap')
            sma20_dist = None
            squeeze = None
            fib_ctx = p.get('fib_context')

            ind_result = p.get('ind_full_result')
            if isinstance(ind_result, dict):
                signals = ind_result.get('signals', {})
                if 'rsi' in signals:
                    rsi = rsi or signals['rsi'].get('value')
                if 'vwap' in signals:
                    vwap_dist = vwap_dist or signals['vwap'].get('distance_pct')
                    if vwap_dist is not None:
                        above_vwap = float(vwap_dist) >= 0
                if 'sma20' in signals:
                    sma20_dist = signals['sma20'].get('distance_pct')
                if 'squeeze' in signals:
                    squeeze = signals['squeeze'].get('state')
                if 'fib' in signals:
                    fib_ctx = signals['fib']

            # RSI state
            rsi_state = None
            if rsi is not None:
                rsi_val = float(rsi)
                if rsi_val >= 70: rsi_state = 'overbought'
                elif rsi_val >= 60: rsi_state = 'near_overbought'
                elif rsi_val <= 30: rsi_state = 'oversold'
                elif rsi_val <= 40: rsi_state = 'near_oversold'
                else: rsi_state = 'neutral'

            # Technical state label
            tech_parts = []
            if rsi is not None:
                tech_parts.append(f"RSI {float(rsi):.1f} ({rsi_state})")
            if vwap_dist is not None:
                tech_parts.append(f"VWAP {float(vwap_dist):+.1f}%")
            if atr is not None:
                tech_parts.append(f"ATR ${float(atr):.2f}")
            if p.get('adx_regime'):
                tech_parts.append(f"ADX: {p['adx_regime']}")
            technical_state = " | ".join(tech_parts) if tech_parts else None

            # Missing data detection
            missing = []
            if atr is None: missing.append('ATR')
            if rsi is None: missing.append('RSI')
            if vwap_dist is None: missing.append('VWAP')
            if not fib_ctx: missing.append('Fib context')
            if not p.get('recent_headlines'): missing.append('News')
            if not p.get('pa_summary') and not catalyst: missing.append('LLM narrative')
            if not sector: missing.append('Sector')
            if not critic_verdict: missing.append('Critic verdict')

            # Fib context
            if not fib_ctx:
                fib_ctx = {'available': False, 'summary': 'Fib context unavailable — no fib indicator data populated'}

            # Deterministic narrative fallback
            narrative = p.get('pa_summary')
            narrative_source = p.get('pa_narrative_source')
            if not narrative:
                # Build deterministic fallback
                parts = []
                parts.append(f"{p.get('symbol')} is a {p.get('strategy_id') or 'unknown'} proposal")
                if p.get('scan_source'):
                    parts.append(f"sourced from {p['scan_source']}")
                scan_parts = []
                if rvol: scan_parts.append(f"RVOL {float(rvol):.1f}x")
                if float_m: scan_parts.append(f"float {float(float_m):.1f}M")
                if gap_pct: scan_parts.append(f"gap {float(gap_pct):+.1f}%")
                if catalyst_verified: scan_parts.append("verified catalyst")
                elif catalyst: scan_parts.append("unverified catalyst")
                if signal_grade and signal_score:
                    scan_parts.append(f"{signal_grade}-grade score {signal_score}")
                if scan_parts:
                    parts.append(f"showing {', '.join(scan_parts)}")
                if critic_verdict and critic_verdict != 'PASS':
                    parts.append(f"Critic: {critic_verdict}")
                    if critic_reasoning:
                        parts.append(str(critic_reasoning)[:120])
                vs = p.get('vs_sector_pct')
                if vs is not None:
                    direction = "outperforming" if float(vs) > 0 else "underperforming"
                    parts.append(f"Sector: {direction} by {abs(float(vs)):.1f}%")
                narrative = ". ".join(parts) + "."
                narrative_source = 'deterministic_fallback'

            # Approve/reject case
            # Use LLM case text only if it's actually text (not bool from bad LLM parse)
            _pa_approve = p.get('pa_approve_case')
            _pa_reject = p.get('pa_reject_case')
            approve_case = _pa_approve if isinstance(_pa_approve, str) and len(_pa_approve) > 5 else None
            reject_case = _pa_reject if isinstance(_pa_reject, str) and len(_pa_reject) > 5 else None
            if not approve_case:
                if catalyst_verified and (not critic_verdict or critic_verdict == 'PASS'):
                    approve_case = f"Verified catalyst with {signal_grade or '?'}-grade setup. Risk ${dollar_risk:.0f} ({risk_pct:.3f}% portfolio)."
                elif catalyst_verified:
                    approve_case = f"Verified catalyst exists but critic flags concerns. Consider as cautious paper test only."
                else:
                    approve_case = f"Limited conviction — unverified catalyst. Paper test only if testing system handling of this setup type."
            if not reject_case:
                reasons = []
                if critic_verdict == 'BLOCK': reasons.append("Critic BLOCKED this idea")
                if critic_verdict == 'DOWNGRADE': reasons.append(f"Critic downgraded: {str(critic_reasoning)[:80]}")
                if len(missing) >= 4: reasons.append(f"Too much missing data ({len(missing)} fields)")
                vs = p.get('vs_sector_pct')
                if vs is not None and float(vs) < -5: reasons.append(f"Weak sector relative: {float(vs):.1f}%")
                reject_case = ". ".join(reasons) if reasons else "No strong rejection signals detected."

            # Conviction label
            conviction = 'CAUTIOUS PAPER TEST'
            if critic_verdict == 'BLOCK':
                conviction = 'REJECT / DO NOT TEST'
            elif len(missing) >= 4:
                conviction = 'MISSING-DATA PROPOSAL'
            elif critic_verdict == 'DOWNGRADE':
                conviction = 'CAUTIOUS PAPER TEST'
            elif signal_grade in ('A', 'A+') and catalyst_verified and critic_verdict != 'DOWNGRADE':
                conviction = 'HIGH-CONVICTION PAPER TEST'

            # Decision state computation
            decision_state_computed = None
            if conviction == 'REJECT / DO NOT TEST':
                decision_state_computed = 'REJECT_RECOMMENDED'
            elif conviction == 'MISSING-DATA PROPOSAL':
                decision_state_computed = 'RESEARCH_INCOMPLETE'
            elif conviction == 'HIGH-CONVICTION PAPER TEST':
                decision_state_computed = 'APPROVE_READY_PAPER_TEST'
            else:
                decision_state_computed = 'CAUTIOUS_PAPER_TEST'
            # Override with stored decision state if available
            stored_ds = p.get('research_packet_id')  # has research packet
            if p.get('approval_blocked_reason'):
                if 'Risk gate' in str(p.get('approval_blocked_reason', '')):
                    decision_state_computed = 'BLOCKED_BY_RISK_GATE'
            if p.get('agent_review_status') == 'complete' and p.get('research_score') is not None:
                rs = float(p.get('research_score') or 0)
                cs = float(p.get('confidence_score') or 0)
                if rs >= 85 and cs >= 75:
                    decision_state_computed = 'APPROVE_READY_PAPER_TEST'
                elif rs >= 75:
                    decision_state_computed = 'CAUTIOUS_PAPER_TEST'
                else:
                    decision_state_computed = 'RESEARCH_INCOMPLETE'

            # Technical summary from stored context
            tech_ctx = p.get('technical_context')
            technical_summary_computed = technical_state
            if isinstance(tech_ctx, dict):
                parts = []
                if tech_ctx.get('atr'):
                    parts.append(f"ATR ${float(tech_ctx['atr']):.2f} ({tech_ctx.get('atr_state', '?')})")
                if tech_ctx.get('rsi'):
                    parts.append(f"RSI {float(tech_ctx['rsi']):.1f} ({tech_ctx.get('rsi_state', '?')})")
                if tech_ctx.get('vwap_state'):
                    parts.append(f"VWAP: {tech_ctx['vwap_state']}")
                if parts:
                    technical_summary_computed = " | ".join(parts)

            # Agent votes placeholder (enriched in post-processing)
            agent_votes_json = None

            # Minutes remaining
            mins_remaining = None
            if p.get('expires_at'):
                try:
                    from datetime import datetime, timezone
                    exp = datetime.fromisoformat(str(p['expires_at']))
                    mins_remaining = max(0, int((exp - datetime.now(timezone.utc)).total_seconds() / 60))
                except Exception:
                    pass

            proposals.append({
                'id': p.get('id'),
                'symbol': p.get('symbol'),
                'strategy_id': p.get('strategy_id'),
                'setup_type': p.get('setup_type'),
                'setup_description': p.get('setup_description'),
                'source_table': p.get('source_table') or p.get('scan_source'),
                'screener_name': p.get('screener_name') or p.get('scan_screener'),
                'discovery_source': p.get('discovery_source') or p.get('scan_source'),
                'proposed_by': p.get('proposed_by'),
                'proposed_account': p.get('proposed_account'),
                'proposed_entry': entry, 'proposed_stop': stop,
                'proposed_target1': t1, 'proposed_target2': t2,
                'proposed_shares': shares,
                'proposed_dollar_size': round(entry * shares, 2) if entry and shares else 0,
                'proposed_dollar_risk': round(dollar_risk, 2),
                'risk_pct_portfolio': round(risk_pct, 4),
                'target1_dollar_reward': round(t1_reward, 2),
                'target2_dollar_reward': round(t2_reward, 2),
                'proposed_rr': round(rr_t1, 2) if rr_t1 else p.get('proposed_rr'),
                'rr_t2': round(rr_t2, 2) if rr_t2 else None,
                'minutes_remaining': mins_remaining,
                'signal_grade': signal_grade,
                'signal_score': signal_score,
                'rvol': float(rvol) if rvol else None,
                'float_m': float(float_m) if float_m else None,
                'gap_pct': float(gap_pct) if gap_pct else None,
                'change_pct': p.get('scan_change_pct'),
                'catalyst': catalyst,
                'catalyst_verified': catalyst_verified,
                'catalyst_confidence': float(catalyst_confidence) if catalyst_confidence else None,
                'critic_verdict': critic_verdict,
                'critic_confidence': float(critic_confidence) if critic_confidence else None,
                'critic_reasoning': str(critic_reasoning)[:300] if critic_reasoning else None,
                'sector': sector,
                'industry': industry,
                'country': country,
                'sector_etf': p.get('scan_sector_etf'),
                'ticker_perf_1m': p.get('ticker_perf_1m'),
                'sector_perf_1m': p.get('sector_perf_1m'),
                'vs_sector_pct': p.get('vs_sector_pct'),
                'intel_readiness': intel,
                'atr': float(atr) if atr else None,
                'atr_pct': round(atr_pct, 2) if atr_pct else None,
                'rsi': float(rsi) if rsi else None,
                'rsi_state': rsi_state,
                'vwap_distance': float(vwap_dist) if vwap_dist is not None else None,
                'above_vwap': above_vwap,
                'sma20_distance': float(sma20_dist) if sma20_dist is not None else None,
                'squeeze_momentum': squeeze,
                'fib_context': fib_ctx,
                'technical_state': technical_state,
                'confluence_score': p.get('confluence_score'),
                'confluence_tier': p.get('confluence_tier'),
                'entry_quality': p.get('entry_quality'),
                'adx_regime': p.get('adx_regime'),
                'normal_pattern_summary': p.get('normal_pattern_summary') or 'Pattern comparison unavailable — no historical pattern data for this symbol/setup yet',
                'news': p.get('recent_headlines'),
                'agent_narrative': narrative,
                'narrative_source': narrative_source,
                'approve_case': approve_case,
                'reject_case': reject_case,
                'invalidation': p.get('pa_invalidation'),
                'missing_data': missing,
                'conviction_label': conviction,
                'risk_gate_result': p.get('risk_gate_result'),
                'risk_gate_codes': p.get('risk_gate_codes'),
                'tos_order_string': p.get('tos_order_string'),
                'quality_pass': p.get('quality_pass'),
                'quality_reason_codes': p.get('quality_reason_codes'),
                'status': p.get('status'),
                'expires_at': p.get('expires_at'),
                'created_at': p.get('created_at'),
                # Session 24A: Lifecycle fields
                'lifecycle_status': p.get('lifecycle_status'),
                'lifecycle_message': p.get('lifecycle_message'),
                'entry_zone_status': p.get('entry_zone_status'),
                'entry_zone_valid': p.get('entry_zone_valid'),
                'current_price': _json_clean(p.get('current_price')),
                'price_drift_pct': _json_clean(p.get('price_drift_pct')),
                'last_price_source': p.get('last_price_source'),
                'base_expires_at': _json_clean(p.get('base_expires_at')),
                'max_expires_at': _json_clean(p.get('max_expires_at')),
                'expiry_extended_count': p.get('expiry_extended_count') or 0,
                'proposal_timeframe_class': p.get('proposal_timeframe_class'),
                'overnight_monitoring_enabled': p.get('overnight_monitoring_enabled'),
                'manual_review_required': p.get('manual_review_required'),
                'last_price_checked_at': _json_clean(p.get('last_price_checked_at')),
                'last_lifecycle_check_at': _json_clean(p.get('last_lifecycle_check_at')),
                'quote_provider': p.get('last_price_source'),
                'source_run_label': p.get('source_run_label'),
                # Session 24B: Strategy config + setup stack
                'primary_strategy_id': p.get('primary_strategy_id'),
                'secondary_strategy_ids': _json_clean(p.get('secondary_strategy_ids')),
                'setup_stack': _json_clean(p.get('setup_stack')),
                'strategy_config_hash': p.get('strategy_config_hash'),
                # Session 17v3 research packet fields
                'decision_state': p.get('decision_state_computed'),
                'research_score': _json_clean(p.get('research_score')),
                'confidence_score': _json_clean(p.get('confidence_score')),
                'live_readiness_score': _json_clean(p.get('live_readiness_score')) or 0,
                'agent_review_status': p.get('agent_review_status') or 'not reviewed',
                'local_llm_review_status': p.get('local_llm_review_status') or 'not run',
                'backtest_status': p.get('backtest_status') or 'not run',
                'approval_allowed': p.get('approval_allowed'),
                'approval_blocked_reason': p.get('approval_blocked_reason'),
                'required_reviews': p.get('required_reviews'),
                'completed_reviews': p.get('completed_reviews'),
                'agent_votes': p.get('agent_votes_json'),
                'data_completeness_score': p.get('research_score'),
                'technical_summary': p.get('technical_summary_computed'),
                'stock_history_summary': p.get('stock_history_summary'),
                'backtest_summary': p.get('backtest_summary'),
                'source_lineage': {
                    'source': p.get('scan_source'),
                    'screener': p.get('scan_screener'),
                    'discovery_source': p.get('discovery_source'),
                },
                'risk_reward': {
                    'dollar_risk': round(dollar_risk, 2),
                    'dollar_reward_t1': round(t1_reward, 2),
                    'dollar_reward_t2': round(t2_reward, 2),
                    'rr': round(rr_t1, 2) if rr_t1 else p.get('proposed_rr'),
                    'risk_pct_portfolio': round(risk_pct, 4),
                },
                # Session 26: Packet state fields
                'packet_state': p.get('packet_state') or 'NEW',
                'packet_completion_pct': _json_clean(p.get('packet_completion_pct')) or 0,
                'packet_last_enriched_at': _json_clean(p.get('packet_last_enriched_at')),
                'missing_data_by_section': _json_clean(p.get('missing_data_by_section')),
                'action_state': p.get('action_state'),
                'action_label': p.get('action_label'),
                'top_blocker': p.get('top_blocker'),
                'next_actions': _json_clean(p.get('next_actions')),
                'llm_review_status': p.get('llm_review_status') or 'NOT_REQUESTED',
                'llm_model_used': p.get('llm_model_used'),
                'llm_review_stage': p.get('llm_review_stage'),
                'llm_review_chunks': _json_clean(p.get('llm_review_chunks')),
                'enrichment_attempt_count': p.get('enrichment_attempt_count') or 0,
            })

            # Session 23D: Enrich with technical snapshot + execution readiness from DB
            try:
                ts = _db_query("""
                    SELECT ema_8, ema_21, ema_50, ema_200,
                           ema_8_distance_pct, ema_21_distance_pct,
                           ema_50_distance_pct, ema_200_distance_pct,
                           ema_alignment, technical_grade,
                           swing_high, swing_low, nearest_fib_level, nearest_fib_distance_pct,
                           opening_range_high, opening_range_low,
                           opening_range_status, premarket_status, premarket_high, premarket_low,
                           ohlcv_data_status
                    FROM proposal_technical_snapshots
                    WHERE proposal_id = %s ORDER BY computed_at DESC LIMIT 1
                """, [proposals[-1]['id']], fetch="one")
                if ts:
                    proposals[-1]['technical_snapshot'] = {k: _json_clean(v) for k, v in ts.items()}
                er = _db_query("""
                    SELECT readiness_state, readiness_score, bracket_order_supported,
                           alpaca_account_mode, alpaca_base_url_type, market_hours,
                           paper_submit_test_result, bracket_dry_run_payload,
                           quote_provider, quote_price, quote_timestamp,
                           quote_is_delayed, quote_execution_eligible,
                           bid, ask, spread_pct, volume_source, spread_source,
                           quote_age_seconds, blockers, warnings
                    FROM proposal_execution_readiness
                    WHERE proposal_id = %s ORDER BY created_at DESC LIMIT 1
                """, [proposals[-1]['id']], fetch="one")
                if er:
                    proposals[-1]['execution_readiness'] = {k: _json_clean(v) for k, v in er.items()}
            except Exception:
                pass

        # Set defaults for enrichment fields
        for prop in proposals:
            prop.setdefault('agent_reviews', [])
            prop.setdefault('llm_analysis', None)
            prop.setdefault('quality_review', None)
            prop.setdefault('intelligence', None)
            prop.setdefault('recently_rejected', False)
            prop.setdefault('rejection_cooldown_until', None)
            prop.setdefault('rejection_reason', None)

        # Enrich with agent votes, LLM analysis, quality review, intelligence, cooldown
        try:
            for prop in proposals:
                pid = prop.get('id')
                symbol = prop.get('symbol')
                if pid:
                    # --- Agent reviews (detailed) ---
                    agent_rows = _db_query("""
                        SELECT agent_name, vote, confidence, summary, reviewed_by_model, reviewed_at, status
                        FROM proposal_agent_reviews
                        WHERE proposal_id = %s ORDER BY agent_name
                    """, [pid]) or []
                    votes = {}
                    agent_reviews_list = []
                    for ar in agent_rows:
                        votes[ar['agent_name']] = {
                            'vote': ar.get('vote'),
                            'confidence': _json_clean(ar.get('confidence')),
                            'summary': (ar.get('summary') or '')[:120],
                            'model': ar.get('reviewed_by_model'),
                        }
                        agent_reviews_list.append({
                            'agent_name': ar.get('agent_name'),
                            'verdict': ar.get('vote'),
                            'confidence': _json_clean(ar.get('confidence')),
                            'summary': (ar.get('summary') or '')[:200],
                            'created_at': _json_clean(ar.get('reviewed_at')),
                        })
                    prop['agent_votes'] = votes
                    prop['agent_reviews'] = agent_reviews_list

                    # --- LLM analysis ---
                    pa = _db_query("""
                        SELECT model_used, narrative_source, summary, approve_case, reject_case,
                               invalidation, confidence, catalyst_summary, risk_summary, technical_summary,
                               created_at
                        FROM paper_proposal_analysis
                        WHERE proposal_id = %s
                        ORDER BY created_at DESC LIMIT 1
                    """, [pid], fetch="one")
                    if pa:
                        prop['llm_analysis'] = {
                            'model_used': pa.get('model_used'),
                            'narrative_source': pa.get('narrative_source'),
                            'summary': pa.get('summary'),
                            'approve_case': pa.get('approve_case'),
                            'reject_case': pa.get('reject_case'),
                            'confidence': _json_clean(pa.get('confidence')),
                        }
                    else:
                        prop['llm_analysis'] = None

                    # --- Quality review ---
                    qr = _db_query("""
                        SELECT review_state, quality_score, missing_data, source_evidence,
                               llm_model, narrative_source, created_at
                        FROM proposal_quality_reviews
                        WHERE proposal_id = %s
                        ORDER BY created_at DESC LIMIT 1
                    """, [pid], fetch="one")
                    if qr:
                        prop['quality_review'] = {
                            'review_state': qr.get('review_state'),
                            'quality_score': _json_clean(qr.get('quality_score')),
                            'missing_data': qr.get('missing_data'),
                            'source_evidence': qr.get('source_evidence'),
                            'created_at': _json_clean(qr.get('created_at')),
                        }
                    else:
                        prop['quality_review'] = None

                    # --- Intelligence readiness ---
                    intel_row = _db_query("""
                        SELECT intelligence_readiness, intelligence_readiness_source,
                               intelligence_readiness_updated_at, intel_components
                        FROM trade_ai_scans
                        WHERE symbol = %s
                        ORDER BY scanned_at DESC LIMIT 1
                    """, [symbol], fetch="one")
                    if intel_row:
                        prop['intelligence'] = {
                            'intelligence_readiness': intel_row.get('intelligence_readiness'),
                            'readiness_source': intel_row.get('intelligence_readiness_source'),
                            'readiness_updated_at': _json_clean(intel_row.get('intelligence_readiness_updated_at')),
                        }
                    else:
                        prop['intelligence'] = None

                    # --- Rejection cooldown ---
                    rej_row = _db_query("""
                        SELECT id, status, rejection_reason, rejected_at, risk_gate_result
                        FROM paper_trade_proposals
                        WHERE symbol = %s AND status = 'REJECTED'
                        AND rejected_at > NOW() - INTERVAL '24 hours'
                        ORDER BY rejected_at DESC LIMIT 1
                    """, [symbol], fetch="one")
                    if rej_row:
                        from datetime import timedelta
                        cooldown_until = None
                        if rej_row.get('rejected_at'):
                            try:
                                cooldown_until = _json_clean(rej_row['rejected_at'] + timedelta(hours=24))
                            except Exception:
                                pass
                        prop['recently_rejected'] = True
                        prop['rejection_cooldown_until'] = cooldown_until
                        prop['rejection_reason'] = rej_row.get('rejection_reason') or rej_row.get('risk_gate_result')
                    else:
                        prop['recently_rejected'] = False
                        prop['rejection_cooldown_until'] = None
                        prop['rejection_reason'] = None

                    # Decision state from research packet
                    rp = _db_query("""
                        SELECT packet_status, research_score, confidence_score
                        FROM proposal_research_packets
                        WHERE proposal_id = %s
                        ORDER BY updated_at DESC LIMIT 1
                    """, [pid], fetch="one")
                    if rp:
                        prop['decision_state'] = rp.get('packet_status') or prop.get('decision_state')
                        if not prop.get('research_score'):
                            prop['research_score'] = _json_clean(rp.get('research_score'))
                        if not prop.get('confidence_score'):
                            prop['confidence_score'] = _json_clean(rp.get('confidence_score'))

                    # Technical summary
                    tech_ctx = prop.get('technical_context') or prop.get('technical_summary')
                    if isinstance(tech_ctx, str):
                        try: tech_ctx = json.loads(tech_ctx)
                        except: tech_ctx = None
                    if isinstance(tech_ctx, dict):
                        parts = []
                        if tech_ctx.get('atr'):
                            parts.append(f"ATR ${float(tech_ctx['atr']):.2f} ({tech_ctx.get('atr_state', '?')})")
                        if tech_ctx.get('rsi'):
                            parts.append(f"RSI {float(tech_ctx['rsi']):.1f} ({tech_ctx.get('rsi_state', '?')})")
                        if tech_ctx.get('vwap_state'):
                            parts.append(f"VWAP: {tech_ctx['vwap_state']}")
                        prop['technical_summary'] = " | ".join(parts) if parts else None
        except Exception as e:
            pass  # non-critical enrichment

        # Session 23: Paper trading approval gate override
        # Paper trades approve when: trade plan exists + intel >= 50
        # Live Ready gate only applies to live trading (not yet implemented)
        for prop in proposals:
            trade_plan_exists = bool(
                prop.get('proposed_entry') and
                prop.get('proposed_stop') and
                prop.get('proposed_shares')
            )
            intel = int(prop.get('intel_readiness') or 0)
            has_agent_reviews = len(prop.get('agent_reviews', [])) > 0
            has_llm = prop.get('llm_analysis') is not None

            # Paper ready: trade plan exists + (intel >= 50 OR catalyst verified OR has agent reviews)
            # For paper testing, a verified catalyst with valid levels is sufficient to approve.
            # Intel score is desirable but not a hard gate for paper validation.
            has_catalyst = bool(prop.get('catalyst_verified'))
            paper_ready = trade_plan_exists and (intel >= 50 or has_catalyst or has_agent_reviews)
            prop['paper_ready'] = paper_ready

            # Override approval_allowed for paper trading
            if paper_ready and not prop.get('approval_allowed'):
                prop['approval_allowed'] = True
            # Assign decision_state if missing but paper-ready
            if not prop.get('decision_state') and paper_ready:
                prop['decision_state'] = 'CAUTIOUS_PAPER_TEST'
            # Update blocked reason
            if not prop.get('approval_allowed'):
                if not trade_plan_exists:
                    prop['approval_blocked_reason'] = 'Missing trade plan (entry/stop/shares)'
                elif intel < 50:
                    prop['approval_blocked_reason'] = f'Intel {intel}/100 below minimum 50'

        # Session 23C: Enrich with institutional packet fields
        try:
            for prop in proposals:
                pid = prop.get('id')
                symbol = prop.get('symbol')
                if not pid:
                    continue

                # Technical snapshot (from proposal_technical_snapshots or technical_context)
                tech_row = _db_query("""
                    SELECT rsi_14, atr_14, atr_pct, vwap, vwap_distance_pct, above_vwap,
                           ema_8, ema_21, ema_50, ema_200,
                           ema_8_distance_pct, ema_21_distance_pct, ema_50_distance_pct, ema_200_distance_pct,
                           ema_alignment, macd_state, bollinger_position, squeeze_state,
                           support_1, support_2, resistance_1, resistance_2,
                           swing_high, swing_low, swing_high_date, swing_low_date,
                           fib_236, fib_382, fib_500, fib_618, fib_786, fib_1272, fib_1618,
                           nearest_fib_level, nearest_fib_distance_pct,
                           fib_context, confluence_score, technical_grade, missing_data,
                           opening_range_high, opening_range_low, opening_range_status,
                           premarket_high, premarket_low, premarket_status,
                           ohlcv_data_status, intraday_data_source,
                           computed_at
                    FROM proposal_technical_snapshots
                    WHERE proposal_id = %s ORDER BY computed_at DESC LIMIT 1
                """, [pid], fetch="one")
                if tech_row:
                    prop['technical_snapshot'] = {k: _json_clean(v) for k, v in tech_row.items()}
                else:
                    # Fallback to technical_context JSON on proposal
                    tc = prop.get('technical_context') or prop.get('technical_summary')
                    if isinstance(tc, str):
                        try:
                            tc = json.loads(tc)
                        except Exception:
                            tc = None
                    prop['technical_snapshot'] = tc

                # Strategy fit (from file)
                try:
                    import os as _os
                    fit_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                             '..', 'data', 'proposal_fit_results.json')
                    if _os.path.exists(fit_path):
                        fits = json.loads(open(fit_path).read())
                        for f in fits:
                            if f.get('proposal_id') == pid:
                                prop['strategy_fit'] = f
                                break
                except Exception:
                    pass
                prop.setdefault('strategy_fit', None)

                # Scan history
                scan_rows = _db_query("""
                    SELECT decision, signal_score, price, rvol, gap_pct, change_pct,
                           catalyst_verified, scanned_at
                    FROM trade_ai_scans WHERE symbol = %s
                    ORDER BY scanned_at DESC LIMIT 5
                """, [symbol]) or []
                prop['scan_history'] = [
                    {k: _json_clean(v) for k, v in r.items()} for r in scan_rows
                ]

                # Catalyst quality
                cat_row = _db_query("""
                    SELECT catalyst_quality_score, catalyst_grade, catalyst_type,
                           company_specific, duration_estimate, risk_note,
                           contradictory_signals
                    FROM catalyst_quality_results
                    WHERE proposal_id = %s ORDER BY created_at DESC LIMIT 1
                """, [pid], fetch="one")
                prop['catalyst_quality'] = {k: _json_clean(v) for k, v in cat_row.items()} if cat_row else None

                # Backtest summary
                bt_row = _db_query("""
                    SELECT backtest_quality, sample_size, win_rate, profit_factor,
                           expectancy, avg_r, similar_setup_summary,
                           repeat_pattern_detected, limitations
                    FROM proposal_backtest_snapshots
                    WHERE proposal_id = %s ORDER BY id DESC LIMIT 1
                """, [pid], fetch="one")
                prop['backtest_summary'] = {k: _json_clean(v) for k, v in bt_row.items()} if bt_row else None

                # Execution readiness
                er_row = _db_query("""
                    SELECT readiness_state, readiness_score, quote_price, quote_age_seconds,
                           spread_pct, price_vs_entry_pct, liquidity_ok, spread_ok,
                           quote_fresh, price_ok, risk_gate_ok, duplicate_ok,
                           blockers, warnings, execution_plan, created_at
                    FROM proposal_execution_readiness
                    WHERE proposal_id = %s ORDER BY created_at DESC LIMIT 1
                """, [pid], fetch="one")
                prop['execution_readiness'] = {k: _json_clean(v) for k, v in er_row.items()} if er_row else None

                # Paper submit state
                prop['paper_submit_state'] = {
                    'alpaca_mode': 'paper',
                    'live_blocked': True,
                    'live_blocked_reason': 'Live trading disabled pending six-month paper validation',
                    'readiness_state': (er_row or {}).get('readiness_state', 'NOT_CHECKED'),
                }

                # Missing data summary
                missing = []
                if not prop.get('technical_snapshot'):
                    missing.append('technical_snapshot')
                if not prop.get('strategy_fit'):
                    missing.append('strategy_fit')
                if not prop.get('catalyst_quality'):
                    missing.append('catalyst_quality')
                if not prop.get('backtest_summary'):
                    missing.append('backtest_summary')
                if not prop.get('execution_readiness'):
                    missing.append('execution_readiness')
                if not prop.get('llm_analysis'):
                    missing.append('llm_analysis')
                if not prop.get('agent_reviews') or len(prop.get('agent_reviews', [])) == 0:
                    missing.append('agent_reviews')
                prop['missing_data'] = missing
                prop['institutional_packet_ready'] = len(missing) == 0

        except Exception:
            pass  # non-critical institutional enrichment

        # Session 25: Add screener_display_name and pipeline_stages to each proposal
        for prop in proposals:
            prop['screener_display_name'] = _resolve_screener_display(
                prop.get('screener_name'), prop.get('source_table'))
            prop['pipeline_stages'] = _derive_pipeline_stages(prop)

        # Session 25: Expired today + summary
        expired_today = []
        incubator_ready_count = 0
        last_promotion_run = None
        try:
            _exp_rows = _db_query("""
                SELECT id, symbol, strategy_id, lifecycle_status, lifecycle_message, created_at
                FROM paper_trade_proposals
                WHERE status='expired' AND (rejected_at > NOW() - INTERVAL '24 hours'
                      OR created_at > NOW() - INTERVAL '24 hours')
                ORDER BY created_at DESC LIMIT 10
            """) or []
            expired_today = [{k: _json_clean(v) for k, v in r.items()} for r in _exp_rows]
            _ic = _db_query("""
                SELECT COUNT(*) as cnt FROM incubator_universe
                WHERE status='ACTIVE' AND latest_score>=38 AND promoted_to_proposal_at IS NULL
            """, fetch="one")
            incubator_ready_count = int((_ic or {}).get('cnt', 0))
            _lp = _db_query("""
                SELECT MAX(completed_at) as last_run FROM pipeline_runs
                WHERE script_name='incubator_proposal_promoter'
            """, fetch="one")
            last_promotion_run = _json_clean((_lp or {}).get('last_run'))
        except Exception:
            pass

        pending_list = [p for p in proposals if p.get('status') == 'PENDING']

        # Strategy performance from closed paper trades
        strategy_perf = {}
        try:
            _sp_rows = _db_query("""
                SELECT strategy_id,
                       count(*) as trade_count,
                       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                       ROUND(SUM(pnl)::numeric, 2) as total_pnl
                FROM paper_trades
                WHERE lifecycle_state = 'closed' AND strategy_id IS NOT NULL
                GROUP BY strategy_id
            """) or []
            for sr in _sp_rows:
                sid = sr['strategy_id']
                tc = sr['trade_count'] or 0
                w = sr['wins'] or 0
                strategy_perf[sid] = {
                    'trade_count': tc, 'wins': w,
                    'total_pnl': float(sr['total_pnl'] or 0),
                    'win_rate': round(w / tc * 100, 1) if tc > 0 else 0,
                }
        except Exception:
            pass

        # Add strategy perf, operator verdict, age to each proposal
        ready_count = 0; review_count = 0; stale_count = 0; missed_count = 0
        for prop in pending_list:
            sid = prop.get('strategy_id')
            if sid and sid in strategy_perf:
                prop['strategy_win_rate'] = strategy_perf[sid]['win_rate']
                prop['strategy_total_pnl'] = strategy_perf[sid]['total_pnl']
                prop['strategy_trade_count'] = strategy_perf[sid]['trade_count']
            else:
                prop['strategy_win_rate'] = None
                prop['strategy_total_pnl'] = None
                prop['strategy_trade_count'] = 0

            # Age
            age_hours = None
            if prop.get('created_at'):
                try:
                    from datetime import datetime as _dt, timezone as _tz
                    ca = prop['created_at']
                    if isinstance(ca, str):
                        ca = _dt.fromisoformat(ca.replace('Z', '+00:00'))
                    age_td = _dt.now(_tz.utc) - (ca.replace(tzinfo=_tz.utc) if ca.tzinfo is None else ca)
                    age_hours = round(age_td.total_seconds() / 3600, 1)
                except Exception:
                    pass
            prop['age_hours'] = age_hours
            if age_hours is not None:
                h = age_hours
                prop['age_display'] = f"{int(h * 60)} min ago" if h < 1 else f"{int(h)}h ago" if h < 24 else f"{int(h / 24)}d {int(h % 24)}h ago"
                prop['age_color'] = 'green' if h < 24 else 'yellow' if h < 72 else 'red'
            else:
                prop['age_display'] = '—'
                prop['age_color'] = 'gray'

            # Operator verdict
            ezs = prop.get('entry_zone_status') or ''
            ls = prop.get('lifecycle_status') or ''
            ds = prop.get('decision_state') or ''
            try:
                drift = float(prop.get('price_drift_pct') or 0) or None
            except (TypeError, ValueError):
                drift = None

            # Stop breach check — must come first
            _cp = None
            _sp = None
            try:
                _cp = float(prop.get('current_price') or prop.get('live_price_at_execution') or prop.get('scan_price') or 0)
                _sp = float(prop.get('proposed_stop') or 0)
            except (TypeError, ValueError):
                pass

            if _cp and _sp and _cp > 0 and _sp > 0 and _cp <= _sp:
                verdict = 'BLOCKED'
                verdict_color = 'red'
                verdict_reason = f"STOP BREACHED \u2014 price ${_cp:.2f} at or below stop ${_sp:.2f}"
                missed_count += 1
            elif 'MISSED' in ezs.upper() or 'MISSED' in ls.upper():
                verdict = 'ENTRY_MISSED'
                verdict_color = 'red'
                drift_str = f" {drift:+.1f}%" if drift else ""
                verdict_reason = f"Price moved{drift_str} out of entry zone"
                missed_count += 1
            elif 'STALE' in (prop.get('last_price_source') or '').upper() or 'STALE' in ls.upper():
                verdict = 'STALE_QUOTE'
                verdict_color = 'orange'
                verdict_reason = "Price data is stale — refresh before approving"
                stale_count += 1
            elif ds in ('BLOCKED_BY_RISK_GATE', 'RESEARCH_INCOMPLETE', 'AI_REVIEW_MISSING'):
                verdict = 'NEEDS_REVIEW'
                verdict_color = 'yellow'
                verdict_reason = ds.replace('_', ' ').title()
                review_count += 1
            elif ds == 'APPROVE_READY_PAPER_TEST':
                verdict = 'READY'
                verdict_color = 'green'
                verdict_reason = "Clean entry, all gates clear"
                ready_count += 1
            else:
                verdict = 'NEEDS_REVIEW'
                verdict_color = 'yellow'
                verdict_reason = "Review data completeness before approving"
                review_count += 1

            # Specific verdict reason (replaces generic "Review data completeness")
            if verdict == 'NEEDS_REVIEW':
                rg = prop.get('risk_gate_result')
                llm_s = prop.get('llm_review_status') or 'NOT_REQUESTED'
                ar_s = prop.get('agent_review_status') or 'not reviewed'
                if not rg or rg == 'not_checked':
                    verdict_reason = "Risk gate not checked \u2014 click Check Execution (10 sec)"
                elif llm_s in ('NOT_REQUESTED', 'deterministic_fallback', 'not run'):
                    verdict_reason = "AI not reviewed \u2014 click Run AI Review (30 sec)"
                elif ar_s in ('NOT_REQUESTED', 'not reviewed'):
                    verdict_reason = "Agent review missing \u2014 click Run AI Review"
                elif ds == 'RESEARCH_INCOMPLETE':
                    verdict_reason = "Research incomplete \u2014 click Enrich All to fill gaps"
                else:
                    verdict_reason = "Review flagged items before approving"
            elif verdict == 'ENTRY_MISSED':
                drift_str = f" {drift:+.1f}%" if drift else ""
                verdict_reason = f"Entry zone missed{drift_str} \u2014 price left the zone"
            elif verdict == 'STALE_QUOTE':
                verdict_reason = "Quote is stale \u2014 click Refresh Price"

            prop['operator_verdict'] = verdict
            prop['operator_verdict_color'] = verdict_color
            prop['operator_verdict_reason'] = verdict_reason
            prop['sort_order'] = {'READY': 1, 'NEEDS_REVIEW': 2, 'STALE_QUOTE': 3, 'ENTRY_MISSED': 4, 'BLOCKED': 5}.get(verdict, 2)
            prop['is_actionable'] = verdict in ('READY', 'NEEDS_REVIEW')
            prop['is_blocked'] = verdict == 'BLOCKED'

            # Timestamp display fields
            def _ts_display(ts_val, label=""):
                if not ts_val:
                    return {"text": "Never", "color": "red"}
                try:
                    from datetime import datetime as _ddt, timezone as _ttz
                    if isinstance(ts_val, str):
                        ts_val = _ddt.fromisoformat(ts_val.replace('Z', '+00:00'))
                    age_s = (_ddt.now(_ttz.utc) - (ts_val.replace(tzinfo=_ttz.utc) if ts_val.tzinfo is None else ts_val)).total_seconds()
                    mins = age_s / 60
                    hrs = age_s / 3600
                    if mins < 60:
                        return {"text": f"{int(mins)} min ago", "color": "green"}
                    elif hrs < 2:
                        return {"text": f"{int(hrs)}h {int(mins % 60)}m ago", "color": "green"}
                    elif hrs < 8:
                        return {"text": f"{int(hrs)}h ago", "color": "yellow"}
                    elif hrs < 24:
                        return {"text": f"{int(hrs)}h ago", "color": "red"}
                    else:
                        return {"text": f"{int(hrs / 24)}d ago", "color": "red"}
                except Exception:
                    return {"text": "Unknown", "color": "gray"}

            prop['live_price_timestamp_display'] = _ts_display(prop.get('live_price_timestamp'))
            prop['ai_review_completed_at_display'] = _ts_display(prop.get('packet_last_enriched_at'))
            prop['risk_gate_display'] = {"text": "Passed" if prop.get('risk_gate_result') == 'passed' else "Not checked", "color": "green" if prop.get('risk_gate_result') == 'passed' else "red"}

            # Current price + drift — fallback through multiple sources
            cp = prop.get('current_price') or prop.get('live_price_at_execution') or prop.get('scan_price')
            # Fallback: snapshot data
            if not cp:
                try:
                    _snap = _db_query("SELECT data->>'price' as p, rsi, data->>'rvol' as rvol FROM ticker_snapshot_daily WHERE symbol=%s ORDER BY snapshot_date DESC LIMIT 1", [prop.get('symbol')], fetch="one")
                    if _snap and _snap.get('p'):
                        cp = float(_snap['p'])
                    # Also grab RSI/RVOL from snapshot if missing
                    if _snap:
                        if not prop.get('rsi') and _snap.get('rsi'):
                            prop['rsi'] = float(_snap['rsi'])
                        if not prop.get('rvol') and _snap.get('rvol'):
                            prop['rvol'] = float(_snap['rvol'])
                except Exception:
                    pass
            # Fallback: trade_ai_scans price
            if not cp:
                try:
                    _sc = _db_query("SELECT price FROM trade_ai_scans WHERE symbol=%s ORDER BY scanned_at DESC LIMIT 1", [prop.get('symbol')], fetch="one")
                    if _sc and _sc.get('price'):
                        cp = float(_sc['price'])
                except Exception:
                    pass

            pe = prop.get('proposed_entry')
            if cp and pe and float(pe) > 0:
                try:
                    d_pct = (float(cp) - float(pe)) / float(pe) * 100
                    prop['current_price_display'] = float(cp)
                    prop['price_drift_display'] = round(d_pct, 1)
                    prop['price_drift_color'] = 'green' if abs(d_pct) < 2 else 'yellow' if abs(d_pct) < 5 else 'red'
                except Exception:
                    pass

            # RSI from snapshot if still missing
            if not prop.get('rsi'):
                try:
                    _rsi_row = _db_query("SELECT rsi FROM ticker_snapshot_daily WHERE symbol=%s ORDER BY snapshot_date DESC LIMIT 1", [prop.get('symbol')], fetch="one")
                    if _rsi_row and _rsi_row.get('rsi'):
                        prop['rsi'] = float(_rsi_row['rsi'])
                except Exception:
                    pass

            # RSI flag and overbought block
            _rsi_val = float(prop.get('rsi') or 0)
            _sid = prop.get('strategy_id') or ''
            _RSI_EXEMPT = {'income_add','dividend_growth_compounder','high_yield_income_bdc',
                           'covered_call_income','bond_income','cash_or_stable','recovery_watch'}
            _MOMENTUM = {'momentum_scalp','gap_and_go','earnings_catalyst','speculative_growth','core_growth_compounder'}
            _SWING = {'swing_breakout','swing_trade','sector_rotation','defense_thesis'}

            rsi_flag = None
            if _rsi_val >= 80: rsi_flag = 'OVERBOUGHT'
            elif _rsi_val >= 70: rsi_flag = 'ELEVATED'
            elif _rsi_val <= 20 and _rsi_val > 0: rsi_flag = 'OVERSOLD_EXTREME'
            elif _rsi_val <= 30 and _rsi_val > 0: rsi_flag = 'OVERSOLD'

            rsi_blocks = False
            if _sid not in _RSI_EXEMPT:
                if _sid in _MOMENTUM and _rsi_val >= 80: rsi_blocks = True
                elif _sid in _SWING and _rsi_val >= 75: rsi_blocks = True
                elif _rsi_val >= 85: rsi_blocks = True

            prop['rsi_flag'] = rsi_flag
            prop['rsi_flag_color'] = 'red' if rsi_flag in ('OVERBOUGHT','OVERSOLD_EXTREME') else 'orange' if rsi_flag == 'ELEVATED' else 'yellow' if rsi_flag == 'OVERSOLD' else 'green'
            prop['rsi_flag_blocks_approval'] = rsi_blocks

            # Override verdict if RSI blocks
            if rsi_blocks and verdict not in ('BLOCKED',):
                verdict = 'BLOCKED'
                verdict_color = 'red'
                verdict_reason = f"RSI {_rsi_val:.0f} \u2014 severely overbought, approval will be rejected"
                prop['operator_verdict'] = verdict
                prop['operator_verdict_color'] = verdict_color
                prop['operator_verdict_reason'] = verdict_reason
                prop['sort_order'] = 5
                prop['is_blocked'] = True

            # thesis_display — build from data if setup_thesis is generic
            thesis = prop.get('agent_narrative') or prop.get('approve_case') or ''
            st = str(prop.get('setup_type') or prop.get('strategy_id') or '')
            if len(thesis) < 50 or 'is a' in thesis[:60]:
                parts = []
                if prop.get('rvol'): parts.append(f"RVOL {float(prop['rvol']):.1f}x")
                if prop.get('signal_score'): parts.append(f"Score {prop['signal_score']}pts")
                if prop.get('catalyst_verified'): parts.append("Catalyst verified")
                elif prop.get('catalyst'): parts.append("Catalyst unverified")
                if prop.get('rsi'): parts.append(f"RSI {float(prop['rsi']):.0f}")
                if prop.get('gap_pct'): parts.append(f"Gap {float(prop['gap_pct']):+.1f}%")
                if prop.get('float_m'): parts.append(f"Float {float(prop['float_m']):.1f}M")
                prop['thesis_display'] = f"{prop.get('symbol')}: {st} | {' | '.join(parts)}" if parts else thesis
            else:
                prop['thesis_display'] = thesis[:160]

        # Multi-strategy symbol detection
        sym_strats: dict = {}
        for p in pending_list:
            s = p.get('symbol')
            sym_strats.setdefault(s, []).append(p.get('strategy_id'))
        multi_strategy_symbols = [
            {"symbol": s, "count": len(strats), "strategies": strats}
            for s, strats in sym_strats.items() if len(strats) > 1
        ]
        # Add badge count to each proposal
        for p in pending_list:
            others = len(sym_strats.get(p.get('symbol'), [])) - 1
            p['other_strategy_count'] = others

        # Sort: verdict priority, then strategy win rate, then score
        pending_list.sort(key=lambda p: (p.get('sort_order', 2), -(p.get('strategy_win_rate') or 0), -(p.get('signal_score') or 0)))

        # Build by_strategy summary
        by_strat = {}
        for p in pending_list:
            sid = p.get('strategy_id', 'unknown')
            by_strat.setdefault(sid, {'proposal_count': 0})
            by_strat[sid]['proposal_count'] += 1
            if sid in strategy_perf:
                by_strat[sid].update(strategy_perf[sid])

        return 200, {
            "ok": True,
            "proposals": pending_list,
            "expired_today": expired_today,
            "summary": {
                "pending": len(pending_list),
                "ready_count": ready_count,
                "needs_review_count": review_count,
                "stale_count": stale_count,
                "entry_missed_count": missed_count,
                "expired_today": len(expired_today) if isinstance(expired_today, list) else expired_today,
                "incubator_ready_count": incubator_ready_count,
                "last_promotion_run": last_promotion_run,
                "pipeline_health_message": (
                    f"{missed_count} missed entries, {stale_count} stale quotes. "
                    f"Refresh prices or dismiss stale proposals to unlock "
                    f"the {incubator_ready_count} candidates in the incubator."
                ) if ready_count == 0 and len(pending_list) > 0 else None,
                "by_strategy": [{**v, 'strategy_id': k}
                                for k, v in sorted(by_strat.items(),
                                                   key=lambda x: x[1].get('win_rate', 0),
                                                   reverse=True)],
                "multi_strategy_symbols": multi_strategy_symbols,
            },
            "pending_count": len(pending_list),
            "count": len(proposals),
            "portfolio_value": round(portfolio_value, 2),
        }
    except Exception as e:
        return 500, {"ok": False, "error": str(e)}


def _open_trade_monitor_api():
    """GET /api/v2/open-trade-monitor — open trade status and alerts."""
    try:
        open_trades = _db_query("""
            SELECT id, symbol, strategy_id, entry_price, shares, stop_loss, target_1,
                   current_price, unrealized_pnl, r_multiple, account,
                   entry_time, monitored_at, last_alert_at, stale_flag
            FROM paper_trades WHERE status='open'
            ORDER BY entry_time DESC
        """) or []
        alerts = _db_query("""
            SELECT id, paper_trade_id, symbol, alert_type, severity, title, message, created_at
            FROM open_trade_alerts
            WHERE created_at > NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC LIMIT 50
        """) or []
        total_unreal = sum(float(t.get('unrealized_pnl') or 0) for t in open_trades)
        total_risk = sum(float(t.get('dollar_risk') or 0) for t in open_trades if t.get('dollar_risk'))
        return {
            'ok': True,
            'open_trades': [{k: _json_clean(v) for k, v in t.items()} for t in open_trades],
            'alerts': [{k: _json_clean(v) for k, v in a.items()} for a in alerts],
            'summary': {
                'open_count': len(open_trades),
                'critical_alerts': sum(1 for a in alerts if a.get('severity') == 'CRITICAL'),
                'warn_alerts': sum(1 for a in alerts if a.get('severity') == 'WARN'),
                'stale_trades': sum(1 for t in open_trades if t.get('stale_flag')),
                'total_unrealized_pnl': round(total_unreal, 2),
                'total_open_risk': round(total_risk, 2),
            },
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _paper_trade_analysis_api():
    """GET /api/v2/paper-trade-analysis — recent LLM analyses."""
    try:
        analyses = _db_query("""
            SELECT id, paper_trade_id, symbol, strategy_id, model_used,
                   analysis_type, summary, worked_reasons, failed_reasons,
                   lessons, suggested_rule_changes, confidence, created_by, created_at
            FROM paper_trade_analysis
            ORDER BY created_at DESC LIMIT 30
        """) or []
        awaiting = _db_query("""
            SELECT COUNT(*) as cnt FROM paper_trades
            WHERE status='closed' AND (post_trade_analyzed IS NOT TRUE)
        """, fetch="one") or {}
        return {
            'ok': True,
            'analyses': [{k: _json_clean(v) for k, v in a.items()} for a in analyses],
            'count': len(analyses),
            'awaiting_analysis': awaiting.get('cnt', 0),
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _agent_curation_events_api():
    """GET /api/v2/agent-curation-events — recent Iris/Aegis/LLM events."""
    try:
        events = _db_query("""
            SELECT id, paper_trade_id, proposal_id, symbol, strategy_id,
                   agent_name, event_type, event_summary, created_at
            FROM agent_curation_events
            ORDER BY created_at DESC LIMIT 50
        """) or []
        return {
            'ok': True,
            'events': [{k: _json_clean(v) for k, v in e.items()} for e in events],
            'count': len(events),
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _local_llm_status_api():
    """GET /api/v2/local-llm-status — local LLM availability and run history."""
    try:
        # Central config
        _cfg_model = get_local_llm_model()
        _cfg_base = get_local_llm_base_url().rstrip("/")
        _llm_status = get_local_llm_status()

        # Check Ollama availability
        ollama_available = False
        ollama_models = []
        last_error = None
        try:
            import urllib.request as _ur
            req = _ur.Request(f"{_cfg_base}/api/tags", method="GET")
            with _ur.urlopen(req, timeout=5) as resp:
                import json as _j
                data = _j.loads(resp.read())
                ollama_models = [m.get('name', '') for m in data.get('models', [])]
                ollama_available = True
        except Exception as _e:
            last_error = str(_e)

        # Last run
        last_run = _db_query("""
            SELECT id, model_name, status, run_type, started_at, finished_at,
                   duration_sec, items_processed, items_failed, last_error
            FROM local_llm_runs ORDER BY started_at DESC LIMIT 1
        """, fetch="one")

        # Awaiting analysis
        awaiting_trades = _db_query("""
            SELECT COUNT(*) as cnt FROM paper_trades
            WHERE status='closed' AND (post_trade_analyzed IS NOT TRUE)
        """, fetch="one") or {}

        awaiting_proposals = _db_query("""
            SELECT COUNT(*) as cnt FROM paper_trade_proposals
            WHERE status IN ('EXPIRED', 'REJECTED')
        """, fetch="one") or {}

        result = {
            'ok': True,
            'local_llm': {
                'provider': _llm_status.get('provider', 'ollama'),
                'model': _cfg_model,
                'base_url': _cfg_base,
                'backend': _llm_status.get('backend', 'vulkan'),
                'require_gpu': _llm_status.get('require_gpu', True),
                'runtime_env': _llm_status.get('runtime_env', {}),
                'available': ollama_available,
                'loaded_models': ollama_models,
                'last_error': last_error,
            },
            'available': ollama_available,
            'model': _cfg_model,
            'ollama_host': _cfg_base,
            'trades_awaiting_analysis': awaiting_trades.get('cnt', 0),
            'proposals_awaiting_analysis': awaiting_proposals.get('cnt', 0),
        }
        if not ollama_available:
            result['reason'] = 'Ollama not reachable'
        if last_run:
            result['last_run'] = _json_clean(last_run.get('started_at'))
            result['last_status'] = last_run.get('status')
            result['items_processed_last_run'] = last_run.get('items_processed', 0)
        return result
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _incubator_api():
    """GET /api/v2/incubator — incubator universe with lifecycle state."""
    try:
        rows = _db_query("""
            SELECT id, symbol, strategy_id, status, lifecycle_state,
                   first_seen_at, last_seen_at, source_first_seen, source_latest,
                   source_run_label, baseline_score, latest_score, best_score,
                   score_delta, rvol_baseline, rvol_latest, gap_baseline, gap_latest,
                   catalyst, catalyst_verified, sector, industry,
                   days_active, promoted_to_signal_at, promoted_to_proposal_at,
                   last_paper_trade_id, last_outcome, rolloff_reason, notes,
                   created_at, updated_at
            FROM incubator_universe
            ORDER BY
                CASE status WHEN 'ACTIVE' THEN 0 ELSE 1 END,
                latest_score DESC NULLS LAST,
                updated_at DESC
            LIMIT 200
        """) or []
        return {
            'ok': True,
            'universe': [{k: _json_clean(v) for k, v in r.items()} for r in rows],
            'total': len(rows),
            'active': sum(1 for r in rows if r.get('status') == 'ACTIVE'),
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _incubator_events_api():
    """GET /api/v2/incubator-events — recent incubator lifecycle events."""
    try:
        rows = _db_query("""
            SELECT id, symbol, strategy_id, event_type,
                   reason_codes, old_score, new_score, payload, created_at
            FROM incubator_events
            ORDER BY created_at DESC
            LIMIT 100
        """) or []
        return {
            'ok': True,
            'events': [{k: _json_clean(v) for k, v in r.items()} for r in rows],
            'count': len(rows),
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _incubator_health_api():
    """GET /api/v2/incubator-health — incubator summary stats."""
    try:
        stats = _db_query("""
            SELECT
                COUNT(*) FILTER (WHERE status='ACTIVE') as active,
                COUNT(*) FILTER (WHERE status='ROLLED_OFF') as rolled_off_total,
                COUNT(*) FILTER (WHERE lifecycle_state='ROLLED_ON' AND status='ACTIVE') as rolled_on,
                COUNT(*) FILTER (WHERE lifecycle_state='IMPROVED' AND status='ACTIVE') as improved,
                COUNT(*) FILTER (WHERE lifecycle_state='DEGRADED' AND status='ACTIVE') as degraded,
                COUNT(*) FILTER (WHERE lifecycle_state='PROMOTED_TO_SIGNAL') as promoted_to_signal,
                COUNT(*) FILTER (WHERE lifecycle_state='PROMOTED_TO_PROPOSAL') as promoted_to_proposal
            FROM incubator_universe
        """, fetch="one") or {}

        today_events = _db_query("""
            SELECT event_type, COUNT(*) as cnt
            FROM incubator_events
            WHERE created_at > NOW() - INTERVAL '24 hours'
            GROUP BY event_type
        """) or []

        last_build = _db_query("""
            SELECT MAX(created_at) as ts FROM incubator_events WHERE event_type='ROLLED_ON'
        """, fetch="one") or {}
        last_refresh = _db_query("""
            SELECT MAX(created_at) as ts FROM incubator_events WHERE event_type IN ('IMPROVED', 'DEGRADED', 'STAYED_ACTIVE')
        """, fetch="one") or {}

        return {
            'ok': True,
            'active': stats.get('active', 0),
            'rolled_on': stats.get('rolled_on', 0),
            'improved': stats.get('improved', 0),
            'degraded': stats.get('degraded', 0),
            'promoted_to_signal': stats.get('promoted_to_signal', 0),
            'promoted_to_proposal': stats.get('promoted_to_proposal', 0),
            'rolled_off_total': stats.get('rolled_off_total', 0),
            'today_events': {e.get('event_type', ''): e.get('cnt', 0) for e in today_events},
            'last_weekly_build': _json_clean(last_build.get('ts')),
            'last_daily_refresh': _json_clean(last_refresh.get('ts')),
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _proposal_quality_review_api():
    """GET /api/v2/proposal-quality-review — proposal quality reviews."""
    try:
        rows = _db_query("""
            SELECT pqr.id, pqr.proposal_id, pqr.symbol, pqr.strategy_id,
                   pqr.review_state, pqr.quality_score, pqr.approve_case,
                   pqr.reject_case, pqr.missing_data, pqr.source_evidence,
                   pqr.llm_model, pqr.narrative_source, pqr.created_at
            FROM proposal_quality_reviews pqr
            ORDER BY pqr.created_at DESC
            LIMIT 50
        """) or []
        return {
            'ok': True,
            'reviews': [{k: _json_clean(v) for k, v in r.items()} for r in rows],
            'count': len(rows),
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _strategy_desk():
    """GET /api/v2/strategy-desk — full strategy desk view with per-strategy signals."""
    try:
        # Strategy registry with today's signals + new metadata columns
        strategies = _db_query("""
            SELECT sr.strategy_id, sr.strategy_type, sr.display_name,
                   sr.status, sr.min_win_rate, sr.target_win_rate,
                   sr.total_signals, sr.trades_taken, sr.active,
                   sr.objective, sr.description, sr.timeframe,
                   sr.account_fit, sr.min_price, sr.max_price,
                   sr.max_float_m, sr.min_rvol, sr.risk_per_trade,
                   sr.scoring_profile,
                   COUNT(DISTINCT ss.id) as signals_today,
                   COUNT(DISTINCT CASE WHEN ss.signal_grade = 'A+' THEN ss.id END) as aplus_today,
                   COUNT(DISTINCT CASE WHEN ss.signal_grade IN ('A+','A') THEN ss.id END) as high_grade_today
            FROM strategy_registry sr
            LEFT JOIN strategy_signals ss ON ss.strategy_id = sr.strategy_id
                AND ss.fired_at > NOW() - INTERVAL '24 hours'
                AND ss.status = 'active'
            WHERE sr.strategy_id IS NOT NULL AND sr.active = true
            GROUP BY sr.strategy_id, sr.strategy_type, sr.display_name,
                     sr.status, sr.min_win_rate, sr.target_win_rate,
                     sr.total_signals, sr.trades_taken, sr.active,
                     sr.objective, sr.description, sr.timeframe,
                     sr.account_fit, sr.min_price, sr.max_price,
                     sr.max_float_m, sr.min_rvol, sr.risk_per_trade,
                     sr.scoring_profile
            ORDER BY
                CASE sr.status
                    WHEN 'SCALING' THEN 0 WHEN 'VALIDATED' THEN 1
                    WHEN 'TESTING' THEN 2 WHEN 'UNVALIDATED' THEN 3
                    WHEN 'WATCHLIST' THEN 4 WHEN 'KILLING_REVIEW' THEN 5
                    WHEN 'KILLED' THEN 6 ELSE 7
                END
        """) or []

        # Performance summary (30d)
        perf_rows = _db_query("""
            SELECT strategy_type,
                   COUNT(*) as trade_count,
                   COUNT(CASE WHEN verdict='CORRECT' THEN 1 END) as wins,
                   ROUND(AVG(realized_pnl)::numeric, 2) as avg_pnl,
                   ROUND(SUM(realized_pnl)::numeric, 2) as total_pnl
            FROM agent_recommendation_outcomes
            WHERE scored_at > NOW() - INTERVAL '30 days'
            AND verdict IN ('CORRECT', 'WRONG')
            GROUP BY strategy_type
        """) or []
        perf_by_strategy = {}
        for r in perf_rows:
            sid = r.get('strategy_type')
            tc = r.get('trade_count', 0) or 0
            w = r.get('wins', 0) or 0
            perf_by_strategy[sid] = {
                'trade_count': tc, 'wins': w,
                'win_rate': round(w / tc, 3) if tc > 0 else None,
                'avg_pnl': r.get('avg_pnl'),
                'total_pnl': r.get('total_pnl'),
            }

        # Recent lifecycle transitions
        transitions = _db_query("""
            SELECT strategy_id, from_status, to_status, reason,
                   triggered_by, created_at
            FROM strategy_state_transitions
            WHERE created_at > NOW() - INTERVAL '30 days'
            ORDER BY created_at DESC LIMIT 10
        """) or []

        # Pattern library — full per-strategy
        pattern_rows = _db_query("""
            SELECT strategy_id, pattern_name, pattern_type,
                   win_rate, trade_count, expectancy
            FROM pattern_library
            ORDER BY strategy_id, trade_count DESC
        """) or []
        patterns_by_strategy = {}
        for r in pattern_rows:
            sid = r.get('strategy_id')
            if sid not in patterns_by_strategy:
                patterns_by_strategy[sid] = []
            patterns_by_strategy[sid].append({k: _json_clean(v) for k, v in r.items() if k != 'strategy_id'})

        # Pattern summary counts
        pattern_summary = {
            'proven': sum(1 for pp in patterns_by_strategy.values()
                         for p in pp if p.get('pattern_type') == 'PROVEN'),
            'killed': sum(1 for pp in patterns_by_strategy.values()
                         for p in pp if p.get('pattern_type') == 'KILLED'),
        }

        # Today's signals WITH trade plan data, grouped by strategy
        all_signals = _db_query("""
            SELECT ss.id, ss.strategy_id, ss.symbol,
                   ss.signal_type, ss.signal_grade, ss.signal_score,
                   ss.price, ss.rvol, ss.float_m, ss.gap_pct,
                   ss.catalyst, ss.catalyst_verified,
                   ss.entry_low, ss.entry_high,
                   ss.stop_loss, ss.target_1, ss.target_2,
                   ss.risk_reward, ss.shares, ss.dollar_risk,
                   ss.vix_at_signal, ss.market_regime, ss.sector,
                   ss.intel_readiness, ss.setup_description,
                   ss.status, ss.fired_at
            FROM strategy_signals ss
            WHERE ss.fired_at > NOW() - INTERVAL '24 hours'
            AND ss.status IN ('active', 'watch')
            ORDER BY ss.strategy_id,
                     CASE ss.signal_grade WHEN 'A+' THEN 0 WHEN 'A' THEN 1
                         WHEN 'B' THEN 2 ELSE 3 END,
                     ss.signal_score DESC NULLS LAST
        """) or []

        signals_by_strategy = {}
        top_signals = []
        for r in all_signals:
            row = {k: _json_clean(v) for k, v in r.items()}
            sid = row.get('strategy_id')
            if sid not in signals_by_strategy:
                signals_by_strategy[sid] = []
            signals_by_strategy[sid].append(row)
            top_signals.append(row)

        return {
            'ok': True,
            'strategies': [{k: _json_clean(v) for k, v in r.items()} for r in strategies],
            'signals_by_strategy': signals_by_strategy,
            'top_signals': top_signals[:20],
            'performance_30d': perf_by_strategy,
            'recent_transitions': [{k: _json_clean(v) for k, v in r.items()} for r in transitions],
            'pattern_summary': pattern_summary,
            'patterns_by_strategy': patterns_by_strategy,
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _strategy_registry_api():
    """GET /api/v2/strategy-registry — all strategies with status."""
    rows = _db_query("""
        SELECT strategy_type, display_name, active, version,
               target_accounts, objective, is_income_strategy, is_tactical
        FROM strategy_registry
        ORDER BY strategy_type""") or []
    return {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows],
            "count": len(rows)}


def _system_controls_api():
    """GET /api/v2/system-controls — all halt flags."""
    rows = _db_query("SELECT key, value, updated_at, updated_by FROM system_controls ORDER BY key") or []
    return {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}


def _scalp_live_poll():
    """Return recent scalp signals from ringbuffer file for HTTP polling."""
    sig_file = PROJECT_ROOT / "data" / "scalp_live_signals.json"
    if not sig_file.exists():
        return {"signals": [], "count": 0}
    try:
        signals = json.loads(sig_file.read_text())
        return {"signals": signals[:30], "count": len(signals)}
    except Exception:
        return {"signals": [], "count": 0}


# ── Indicator Engine Endpoints ─────────────────────────────────────────────

def _indicator_confluence_handler(query: dict) -> tuple:
    """GET /api/v2/indicators/confluence?symbol=X&profile=swing&force=true"""
    symbol = (query.get("symbol") or "").upper()
    if not symbol:
        return 400, {"ok": False, "error": "symbol required"}
    profile = query.get("profile", "swing")
    force = query.get("force", "false").lower() in ("true", "1", "yes")

    # Check cache first (unless force)
    if not force:
        cached = _db_query(
            "SELECT full_result FROM indicator_confluence_cache "
            "WHERE symbol=%s AND profile=%s AND expires_at > NOW()",
            (symbol, profile), fetch="one"
        )
        if cached and cached.get("full_result"):
            return 200, {"ok": True, "data": cached["full_result"], "cached": True}

    # Compute fresh
    try:
        import sys as _sys
        _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from indicator_engine import analyze_confluence
        result = analyze_confluence(symbol, profile)
        if not result.get("ok"):
            return 200, {"ok": False, "error": result.get("error", "analysis failed"), "symbol": symbol}

        # UPSERT into cache
        try:
            _db_write(
                """INSERT INTO indicator_confluence_cache
                   (symbol, profile, confluence_score, confluence_tier,
                    signals_bullish, signals_bearish, signals_neutral,
                    strategy_badges, bearish_badges, key_levels,
                    stop_price, target_price, atr, adx_regime, entry_quality,
                    full_result, computed_at, expires_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW()+INTERVAL '15 minutes')
                   ON CONFLICT (symbol, profile) DO UPDATE SET
                     confluence_score=EXCLUDED.confluence_score,
                     confluence_tier=EXCLUDED.confluence_tier,
                     signals_bullish=EXCLUDED.signals_bullish,
                     signals_bearish=EXCLUDED.signals_bearish,
                     signals_neutral=EXCLUDED.signals_neutral,
                     strategy_badges=EXCLUDED.strategy_badges,
                     bearish_badges=EXCLUDED.bearish_badges,
                     key_levels=EXCLUDED.key_levels,
                     stop_price=EXCLUDED.stop_price,
                     target_price=EXCLUDED.target_price,
                     atr=EXCLUDED.atr,
                     adx_regime=EXCLUDED.adx_regime,
                     entry_quality=EXCLUDED.entry_quality,
                     full_result=EXCLUDED.full_result,
                     computed_at=NOW(),
                     expires_at=NOW()+INTERVAL '15 minutes'""",
                (symbol, profile,
                 result.get("confluence_score", 0), result.get("confluence_tier"),
                 result.get("signals_bullish", 0), result.get("signals_bearish", 0),
                 result.get("signals_neutral", 0),
                 result.get("strategy_badges", []), result.get("bearish_badges", []),
                 json.dumps(result.get("key_levels", {})),
                 result.get("stop_price"), result.get("target_price"),
                 result.get("atr"), result.get("adx_regime"), result.get("entry_quality"),
                 json.dumps(result))
            )

            # Log signals to history
            for strat_name, sig_data in result.get("signals", {}).items():
                _db_write(
                    "INSERT INTO indicator_signal_history (symbol, strategy_name, signal, value, details) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (symbol, strat_name, sig_data.get("signal", "NEUTRAL"),
                     sig_data.get("value"), json.dumps(sig_data.get("details", {})))
                )
        except Exception as cache_err:
            print(f"  [indicators] Cache write failed (non-fatal): {cache_err}")

        return 200, {"ok": True, "data": result, "cached": False}
    except Exception as e:
        return 500, {"ok": False, "error": str(e)}


def _indicator_batch_handler(body: dict) -> tuple:
    """POST /api/v2/indicators/batch — batch confluence for up to 20 symbols."""
    symbols = body.get("symbols", [])
    profile = body.get("profile", "swing")
    if not symbols:
        return 400, {"ok": False, "error": "symbols list required"}
    symbols = symbols[:20]  # cap at 20

    import sys as _sys, time as _time
    _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from indicator_engine import analyze_confluence

    results = {}
    for sym in symbols:
        try:
            r = analyze_confluence(sym.upper(), profile)
            results[sym.upper()] = r
            # Cache result
            if r.get("ok"):
                try:
                    _db_write(
                        """INSERT INTO indicator_confluence_cache
                           (symbol, profile, confluence_score, confluence_tier,
                            signals_bullish, signals_bearish, signals_neutral,
                            strategy_badges, bearish_badges, key_levels,
                            stop_price, target_price, atr, adx_regime, entry_quality,
                            full_result, computed_at, expires_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW()+INTERVAL '15 minutes')
                           ON CONFLICT (symbol, profile) DO UPDATE SET
                             confluence_score=EXCLUDED.confluence_score,
                             confluence_tier=EXCLUDED.confluence_tier,
                             signals_bullish=EXCLUDED.signals_bullish,
                             strategy_badges=EXCLUDED.strategy_badges,
                             full_result=EXCLUDED.full_result,
                             computed_at=NOW(), expires_at=NOW()+INTERVAL '15 minutes'""",
                        (sym.upper(), profile,
                         r.get("confluence_score", 0), r.get("confluence_tier"),
                         r.get("signals_bullish", 0), r.get("signals_bearish", 0),
                         r.get("signals_neutral", 0),
                         r.get("strategy_badges", []), r.get("bearish_badges", []),
                         json.dumps(r.get("key_levels", {})),
                         r.get("stop_price"), r.get("target_price"),
                         r.get("atr"), r.get("adx_regime"), r.get("entry_quality"),
                         json.dumps(r))
                    )
                except Exception:
                    pass
            _time.sleep(0.3)  # avoid yfinance rate limits
        except Exception as e:
            results[sym.upper()] = {"ok": False, "error": str(e)}

    return 200, {"ok": True, "results": results, "count": len(results)}


def _indicator_history_handler(query: dict) -> tuple:
    """GET /api/v2/indicators/history?symbol=X&strategy=rsi&days=7"""
    symbol = (query.get("symbol") or "").upper()
    if not symbol:
        return 400, {"ok": False, "error": "symbol required"}
    strategy = query.get("strategy")
    days = int(query.get("days", 7))

    if strategy:
        rows = _db_query(
            "SELECT strategy_name, signal, value, details, computed_at "
            "FROM indicator_signal_history "
            "WHERE symbol=%s AND strategy_name=%s AND computed_at > NOW()-make_interval(days => %s) "
            "ORDER BY computed_at DESC LIMIT 100",
            (symbol, strategy, days)
        )
    else:
        rows = _db_query(
            "SELECT strategy_name, signal, value, details, computed_at "
            "FROM indicator_signal_history "
            "WHERE symbol=%s AND computed_at > NOW()-make_interval(days => %s) "
            "ORDER BY computed_at DESC LIMIT 200",
            (symbol, days)
        )

    return 200, {"ok": True, "data": {
        "symbol": symbol,
        "history": [{k: _json_clean(v) for k, v in r.items()} for r in (rows or [])]
    }}


def _indicator_levels_handler(query: dict) -> tuple:
    """GET /api/v2/indicators/levels?symbol=X — key price levels for dashboard."""
    symbol = (query.get("symbol") or "").upper()
    if not symbol:
        return 400, {"ok": False, "error": "symbol required"}

    # Try cache first
    cached = _db_query(
        "SELECT key_levels, stop_price, target_price FROM indicator_confluence_cache "
        "WHERE symbol=%s AND expires_at > NOW() ORDER BY computed_at DESC LIMIT 1",
        (symbol,), fetch="one"
    )

    levels_list = []

    if cached and cached.get("key_levels"):
        kl = cached["key_levels"]
        if isinstance(kl, str):
            kl = json.loads(kl)

        # Fibonacci levels
        fib = kl.get("fibonacci", {})
        for key, price in fib.items():
            if price:
                pct = key.replace("ret_", "").replace("ext_", "Ext ")
                levels_list.append({"type": f"fib_{pct}", "price": float(price),
                                    "label": f"Fib {float(pct)*100:.1f}%" if "ext" not in key else f"Ext {pct}",
                                    "color": "#F59E0B"})

        # Pivot levels
        for pivot_type in ("pivots_daily", "pivots_weekly", "pivots_fibonacci"):
            pdata = kl.get(pivot_type, {})
            prefix = {"pivots_daily": "D", "pivots_weekly": "W", "pivots_fibonacci": "F"}.get(pivot_type, "")
            for key, price in pdata.items():
                if price and key != "nearest":
                    color = "#EF4444" if key.startswith("r") else "#10B981" if key.startswith("s") else "#6B7280"
                    levels_list.append({"type": f"pivot_{prefix}_{key}", "price": float(price),
                                        "label": f"{prefix}{key.upper()}", "color": color})

        # Bollinger
        bb = kl.get("bollinger", {})
        if bb.get("upper"):
            levels_list.append({"type": "bb_upper", "price": float(bb["upper"]), "label": "BB Upper", "color": "#3B82F6"})
        if bb.get("lower"):
            levels_list.append({"type": "bb_lower", "price": float(bb["lower"]), "label": "BB Lower", "color": "#3B82F6"})
        if bb.get("middle"):
            levels_list.append({"type": "bb_middle", "price": float(bb["middle"]), "label": "BB Mid", "color": "#60A5FA"})

        # Stop / Target
        if cached.get("stop_price"):
            levels_list.append({"type": "stop", "price": float(cached["stop_price"]), "label": "Stop", "color": "#EF4444"})
        if cached.get("target_price"):
            levels_list.append({"type": "target", "price": float(cached["target_price"]), "label": "Target", "color": "#10B981"})
    else:
        # Compute fresh
        try:
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from indicator_engine import analyze_confluence
            result = analyze_confluence(symbol, "swing")
            if result.get("ok"):
                # Recursively call with cache now populated
                return _indicator_levels_handler(query)
        except Exception:
            pass

    return 200, {"ok": True, "symbol": symbol, "levels": levels_list}


# ── Prospects Endpoint ─────────────────────────────────────────────────────

def _prospects_handler(query: dict) -> tuple:
    """GET /api/v2/prospects?type=scalp&min_price=2&max_price=50&min_score=20&limit=50"""
    ptype = (query.get("type") or "all").lower()
    min_price = float(query.get("min_price") or 0) if query.get("min_price") else None
    max_price = float(query.get("max_price") or 9999) if query.get("max_price") else None
    min_score = int(query.get("min_score") or 0)
    limit = min(int(query.get("limit") or 50), 200)

    sql = """
        WITH latest_scans AS (
            SELECT DISTINCT ON (symbol)
                symbol, score, decision, price, rvol, float_m,
                gap_pct, change_pct, sector, industry,
                social_reddit, social_stocktwits, social_score,
                social_sentiment, mention_count, social_sources,
                source, screener_label, scanned_at,
                catalyst, catalyst_verified, catalyst_confidence,
                disqualified
            FROM trade_ai_scans
            WHERE scanned_at > NOW() - INTERVAL '3 days'
            AND (disqualified = false OR disqualified IS NULL)
            ORDER BY symbol, scanned_at DESC
        ),
        proposals AS (
            SELECT symbol, action, strategy_type as prop_strategy,
                   proposed_by, confidence, status
            FROM watchlist_proposals
            WHERE status = 'pending'
        ),
        confluence AS (
            SELECT DISTINCT ON (symbol)
                symbol, confluence_tier, confluence_score,
                strategy_badges, stop_price as conf_stop,
                target_price as conf_target, entry_quality, atr
            FROM indicator_confluence_cache
            WHERE profile = 'scalp'
            ORDER BY symbol, computed_at DESC
        ),
        paper_proposals AS (
            SELECT DISTINCT ON (symbol)
                symbol,
                proposed_entry AS pp_entry,
                proposed_stop AS pp_stop,
                proposed_target1 AS pp_target,
                proposed_target2 AS pp_target2,
                strategy_id AS pp_strategy,
                llm_review_stage AS pp_llm_stage,
                llm_review_status AS pp_llm_status,
                status AS pp_status
            FROM paper_trade_proposals
            WHERE proposed_entry IS NOT NULL AND proposed_entry > 0
              AND status NOT IN ('EXPIRED', 'expired')
            ORDER BY symbol, created_at DESC
        ),
        incubator AS (
            SELECT DISTINCT ON (symbol)
                symbol,
                strategy_id AS inc_strategy,
                llm_screen_grade AS inc_llm_grade,
                llm_screen_verdict AS inc_llm_verdict,
                llm_screen_confidence AS inc_llm_confidence,
                latest_score AS inc_score,
                days_active AS inc_days_active
            FROM incubator_universe
            WHERE status = 'ACTIVE'
            ORDER BY symbol, latest_score DESC NULLS LAST
        )
        SELECT
            s.symbol, s.score, s.decision, s.price, s.rvol, s.float_m,
            s.gap_pct, s.change_pct, s.sector, s.industry,
            s.social_reddit, s.social_stocktwits, s.mention_count,
            s.catalyst, s.catalyst_verified, s.scanned_at,
            s.source, s.screener_label,
            ARRAY_REMOVE(ARRAY[
                CASE WHEN s.source = 'screener' OR s.source LIKE '%%screener%%' THEN 'screener' END,
                CASE WHEN s.source = 'social' OR s.source LIKE '%%social%%'
                     OR COALESCE(s.social_reddit,0) > 0 OR COALESCE(s.social_stocktwits,0) > 0
                     THEN 'social' END,
                CASE WHEN p.symbol IS NOT NULL THEN 'agent' END,
                CASE WHEN w.in_ai_watchlist = true OR w.in_personal_watchlist = true THEN 'watchlist' END,
                CASE WHEN pp.symbol IS NOT NULL THEN 'proposal' END,
                CASE WHEN inc.symbol IS NOT NULL THEN 'incubator' END
            ], NULL) AS pipeline_sources,
            -- Strategy: cascade incubator > watchlist_master > proposal
            COALESCE(inc.inc_strategy, w.strategy_type, pp.pp_strategy) AS strategy_type,
            -- Entry/Stop/Target: cascade proposal > confluence > watchlist_master
            COALESCE(pp.pp_entry, w.ideal_entry, c.conf_stop * 1.03) AS ideal_entry,
            COALESCE(pp.pp_stop, c.conf_stop, w.stop_loss) AS stop_loss,
            COALESCE(pp.pp_target, c.conf_target, w.target_price) AS target_price,
            -- Risk/reward computed from entry/stop/target
            CASE WHEN COALESCE(pp.pp_entry, w.ideal_entry) > 0
                      AND COALESCE(pp.pp_stop, c.conf_stop, w.stop_loss) > 0
                      AND COALESCE(pp.pp_target, c.conf_target, w.target_price) > 0
                 THEN ROUND((
                    (COALESCE(pp.pp_target, c.conf_target, w.target_price) - COALESCE(pp.pp_entry, w.ideal_entry, s.price))
                    / NULLIF(COALESCE(pp.pp_entry, w.ideal_entry, s.price) - COALESCE(pp.pp_stop, c.conf_stop, w.stop_loss), 0)
                 )::numeric, 2)
                 ELSE w.risk_reward
            END AS risk_reward,
            w.in_portfolio, w.in_ai_watchlist,
            c.confluence_tier, c.confluence_score, c.strategy_badges,
            c.conf_stop, c.conf_target, c.entry_quality, c.atr,
            p.action AS proposal_action, p.proposed_by AS proposal_agent,
            p.confidence AS proposal_confidence,
            -- Incubator LLM intelligence
            inc.inc_llm_grade, inc.inc_llm_verdict, inc.inc_llm_confidence,
            inc.inc_score AS incubator_score, inc.inc_days_active,
            -- Proposal levels
            pp.pp_entry AS proposal_entry, pp.pp_stop AS proposal_stop,
            pp.pp_target AS proposal_target, pp.pp_target2 AS proposal_target2,
            pp.pp_strategy AS proposal_strategy, pp.pp_llm_stage, pp.pp_llm_status
        FROM latest_scans s
        LEFT JOIN watchlist_symbol_master w ON s.symbol = w.symbol
        LEFT JOIN confluence c ON s.symbol = c.symbol
        LEFT JOIN proposals p ON s.symbol = p.symbol
        LEFT JOIN paper_proposals pp ON s.symbol = pp.symbol
        LEFT JOIN incubator inc ON s.symbol = inc.symbol
        WHERE s.price IS NOT NULL
        ORDER BY s.score DESC, c.confluence_score DESC NULLS LAST
    """
    rows = _db_query(sql) or []

    # ── Post-query enrichment: LLM grades not already in SQL join ──
    # (The main SQL CTE now joins incubator + paper_proposals directly,
    #  but we still supplement with proposal LLM review grades which are
    #  not in the main query to keep the SQL manageable.)
    llm_enrichment = {}
    try:
        proposal_llm = _db_query("""
            SELECT DISTINCT ON (symbol) symbol, llm_model_used,
                   llm_review_stage, llm_review_status, llm_review_chunks
            FROM paper_trade_proposals
            WHERE llm_review_stage IS NOT NULL
              AND status NOT IN ('EXPIRED', 'expired')
            ORDER BY symbol, created_at DESC
        """) or []
        for r in proposal_llm:
            chunks = r.get("llm_review_chunks")
            grades = {}
            if chunks and isinstance(chunks, (dict, list)):
                # Extract grades from chunks if available
                if isinstance(chunks, dict):
                    grades = {
                        "proposal_decision_grade": chunks.get("decision_grade"),
                        "proposal_risk_grade": chunks.get("risk_grade"),
                        "proposal_catalyst_grade": chunks.get("catalyst_grade"),
                    }
            llm_enrichment[r["symbol"]] = {
                "proposal_llm_model": r.get("llm_model_used"),
                "proposal_llm_stage": r.get("llm_review_stage"),
                **{k: v for k, v in grades.items() if v is not None},
            }
    except Exception:
        pass

    # Social sentiment enrichment from social_sentiment_history
    social_enrichment = {}
    try:
        social_hist = _db_query("""
            SELECT DISTINCT ON (symbol)
                symbol, mention_count, bullish_count, bearish_count,
                sentiment_score, theme_tags
            FROM social_sentiment_history
            WHERE observed_at > NOW() - INTERVAL '3 days'
            ORDER BY symbol, observed_at DESC
        """) or []
        for r in social_hist:
            social_enrichment[r["symbol"]] = {
                "social_mentions": r.get("mention_count", 0),
                "social_bullish": r.get("bullish_count", 0),
                "social_bearish": r.get("bearish_count", 0),
                "social_sentiment_score": _json_clean(r.get("sentiment_score")),
                "social_themes": r.get("theme_tags"),
            }
    except Exception:
        pass

    # Load LLM prospect narratives from cache
    prospect_narratives = {}
    try:
        _pn_row = _db_query("SELECT content FROM llm_intelligence_cache WHERE section='prospect_narratives'", fetch="one")
        if _pn_row and _pn_row.get("content"):
            prospect_narratives = json.loads(_pn_row["content"]) if isinstance(_pn_row["content"], str) else _pn_row["content"]
    except Exception:
        pass

    # Apply type/price/score filters in Python
    filtered = []
    for r in rows:
        d = {k: _json_clean(v) for k, v in r.items()}
        price = float(d.get("price") or 0)
        score = int(d.get("score") or 0)

        if score < min_score:
            continue
        if min_price is not None and price < min_price:
            continue
        if max_price is not None and price > max_price:
            continue

        if ptype == "scalp" and (price < 2 or price > 50 or (d.get("float_m") and float(d["float_m"]) > 500)):
            continue
        elif ptype == "swing" and (price < 10 or price > 200):
            continue
        elif ptype == "income" and d.get("strategy_type") not in (None, "income", "growth_etf", "income_etf"):
            continue
        elif ptype == "position" and (price < 10 or price > 500):
            continue

        # ── Merge LLM + social enrichment ──
        sym = d.get("symbol", "")
        if sym in llm_enrichment:
            d.update(llm_enrichment[sym])
        if sym in social_enrichment:
            d.update(social_enrichment[sym])

        # ── ATR-based fallback: compute entry/stop/target when missing ──
        if price > 0 and not d.get("stop_loss"):
            atr_val = float(d.get("atr") or 0)
            if not atr_val and price > 0:
                # Estimate ATR as ~3% of price for small caps, ~1.5% for large
                atr_val = price * (0.03 if price < 20 else 0.015)
            if atr_val > 0:
                d["ideal_entry"] = d.get("ideal_entry") or round(price, 2)
                d["stop_loss"] = round(price - (1.5 * atr_val), 2)
                d["target_price"] = round(price + (2.0 * atr_val), 2)
                stop = d["stop_loss"]
                target = d["target_price"]
                entry = d["ideal_entry"]
                if entry > stop and entry != stop:
                    d["risk_reward"] = round((target - entry) / (entry - stop), 2)
                d["levels_source"] = "atr_computed"

        # ── RSI flag ──
        # Pull RSI from technical snapshot if not in scan data
        rsi = None
        try:
            _ts = _load_json(STATE_DIR / "technical_snapshot.json") or {}
            if isinstance(_ts, dict) and sym in _ts and isinstance(_ts[sym], dict):
                rsi = _ts[sym].get("rsi")
        except Exception:
            pass
        if rsi is not None:
            d["rsi"] = rsi
            if rsi < 30:
                d["rsi_signal"] = "oversold"
            elif rsi > 70:
                d["rsi_signal"] = "overbought"
            elif rsi > 50:
                d["rsi_signal"] = "bullish"
            else:
                d["rsi_signal"] = "neutral"

        # ── Action signal: actionable summary ──
        signals = []
        if d.get("decision") == "GO":
            signals.append("GO")
        if d.get("incubator_score") and float(d["incubator_score"]) >= 40:
            signals.append("INCUBATED")
        if d.get("proposal_entry"):
            signals.append("HAS_PROPOSAL")
        if d.get("inc_llm_grade") in ("A", "B"):
            signals.append("LLM_APPROVED")
        if d.get("rsi_signal") == "oversold":
            signals.append("OVERSOLD")
        if d.get("confluence_tier") in ("STRONG", "MODERATE"):
            signals.append("CONFLUENCE")
        d["action_signals"] = signals
        d["signal_strength"] = len(signals)

        # LLM narrative from cache
        if sym in prospect_narratives:
            d["llm_narrative"] = prospect_narratives[sym]

        # Serialize dates
        for k in ("scanned_at",):
            if d.get(k):
                d[k] = str(d[k])
        filtered.append(d)
        if len(filtered) >= limit:
            break

    # Get latest scan timestamp for freshness
    last_scan_info = _db_query("""
        SELECT scanned_at, run_label
        FROM trade_ai_scans
        WHERE (scanned_at AT TIME ZONE 'America/New_York')::date =
              (NOW() AT TIME ZONE 'America/New_York')::date
        ORDER BY scanned_at DESC LIMIT 1
    """, fetch="one")

    if not last_scan_info:
        last_scan_info = _db_query("""
            SELECT scanned_at, run_label
            FROM trade_ai_scans
            ORDER BY scanned_at DESC LIMIT 1
        """, fetch="one")
        scan_freshness_label = "stale_no_scan_today"
    else:
        scan_freshness_label = "fresh"

    last_scan = str(last_scan_info.get('scanned_at')) if last_scan_info else None
    run_label_val = last_scan_info.get('run_label') if last_scan_info else None

    # Compute data age and run health
    is_stale = scan_freshness_label != "fresh"
    stale_reason = None
    data_age_minutes = None
    symbols_scanned = 0
    go_count = 0
    wait_count = 0
    run_health_status = None
    run_health_reason_codes = []

    if last_scan:
        try:
            from datetime import datetime as _dt
            scan_ts = _dt.fromisoformat(str(last_scan).replace("+00:00", "+00:00"))
            data_age_minutes = int((datetime.now(timezone.utc) - scan_ts.astimezone(timezone.utc)).total_seconds() / 60)
        except Exception:
            pass

    if is_stale:
        stale_reason = "NO_CURRENT_DAY_SCAN"

    # Get today's scan stats
    _today_stats = _db_query("""
        SELECT COUNT(DISTINCT symbol) AS symbols,
               COUNT(CASE WHEN decision='GO' THEN 1 END) AS go_cnt,
               COUNT(CASE WHEN decision='WAIT' THEN 1 END) AS wait_cnt
        FROM trade_ai_scans
        WHERE (scanned_at AT TIME ZONE 'America/New_York')::date =
              (NOW() AT TIME ZONE 'America/New_York')::date
    """, fetch="one")
    if _today_stats:
        symbols_scanned = int(_today_stats.get("symbols") or 0)
        go_count = int(_today_stats.get("go_cnt") or 0)
        wait_count = int(_today_stats.get("wait_cnt") or 0)
        if symbols_scanned < 40 and symbols_scanned > 0:
            is_stale = True
            stale_reason = "RUN_UNDERFILLED"

    # Get run health from screener_run_health
    try:
        _health = _db_query("""
            SELECT status, reason_codes FROM screener_run_health
            WHERE run_date = CURRENT_DATE
            ORDER BY finished_at DESC NULLS LAST LIMIT 1
        """, fetch="one")
        if _health:
            run_health_status = _health.get("status")
            run_health_reason_codes = _health.get("reason_codes") or []
    except Exception:
        pass

    return 200, {
        "ok": True, "data": filtered, "count": len(filtered), "type": ptype,
        "last_scan": last_scan,
        "latest_scan": last_scan,
        "latest_scan_date": str(datetime.now(timezone.utc).date()),
        "scan_date": str(datetime.now(timezone.utc).date()),
        "run_label": run_label_val,
        "scan_freshness_label": scan_freshness_label,
        "data_age_minutes": data_age_minutes,
        "is_stale": is_stale,
        "stale_reason": stale_reason,
        "symbols_scanned": symbols_scanned,
        "go_count": go_count,
        "wait_count": wait_count,
        "run_health_status": run_health_status,
        "run_health_reason_codes": run_health_reason_codes,
    }


def _prospects_add_to_watchlist(body: dict) -> tuple:
    """POST /api/v2/prospects/add-to-watchlist"""
    symbol = (body.get("symbol") or "").upper()
    strategy_type = body.get("strategy_type", "scalp")
    source = body.get("source", "prospects")
    if not symbol:
        return 400, {"ok": False, "error": "symbol required"}
    try:
        conn = get_db()
        cur = conn.cursor()
        # Insert into watchlist_items if not exists
        cur.execute("""
            INSERT INTO watchlist_items (symbol, source, status)
            SELECT %s, %s, 'active'
            WHERE NOT EXISTS (SELECT 1 FROM watchlist_items WHERE symbol = %s)
        """, [symbol, source, symbol])
        # Update or insert into watchlist_symbol_master
        cur.execute("""
            INSERT INTO watchlist_symbol_master (symbol, strategy_type, sources, in_ai_watchlist, updated_at)
            VALUES (%s, %s, ARRAY[%s], true, NOW())
            ON CONFLICT (symbol) DO UPDATE SET
                strategy_type = COALESCE(NULLIF(watchlist_symbol_master.strategy_type, ''), EXCLUDED.strategy_type),
                in_ai_watchlist = true,
                sources = array_cat(watchlist_symbol_master.sources, ARRAY[%s]),
                updated_at = NOW()
        """, [symbol, strategy_type, source, source])
        conn.commit()
        conn.close()
        return 200, {"ok": True, "data": {"symbol": symbol, "strategy_type": strategy_type, "added": True}}
    except Exception as e:
        return 500, {"ok": False, "error": str(e)}


def _intelligence_entities():
    """GET /api/v2/intelligence-entities — browse all intelligence entity records."""
    rows = _db_query("""
        SELECT entity_id, entity_type, entity_subtype, display_name,
               intelligence_score, intelligence_grade,
               iris_freshness, iris_coverage, iris_notes, iris_action_needed,
               signal_count, pipeline_sources,
               current_price, rvol, confluence_tier, confluence_score,
               screener_decision, screener_score, social_mentions,
               last_enriched, last_agent_analysis, last_agent_verdict,
               rag_item_count,
               john_risk_level, john_impact, john_action_needed,
               thresholds_updated, strategy_type, sector
        FROM intelligence_entities
        WHERE active = true
        ORDER BY intelligence_score DESC NULLS LAST
        LIMIT 200
    """) or []

    stats = _db_query("""
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN entity_type='market' THEN 1 END) as market,
            COUNT(CASE WHEN entity_type='subject' THEN 1 END) as subject,
            COUNT(CASE WHEN iris_freshness='CRITICAL' THEN 1 END) as critical,
            COUNT(CASE WHEN iris_freshness='STALE' THEN 1 END) as stale,
            COUNT(CASE WHEN iris_coverage IN ('THIN','EMPTY') THEN 1 END) as thin,
            ROUND(AVG(intelligence_score)::numeric, 1) as avg_score
        FROM intelligence_entities WHERE active = true
    """, fetch="one") or {}

    return {
        "entities": [{k: _json_clean(v) for k, v in r.items()} for r in rows],
        "stats": {k: _json_clean(v) for k, v in stats.items()} if stats else {},
        "count": len(rows),
    }


def _pipeline_health():
    """GET /api/v2/pipeline-health — pipeline execution status last 24hr."""
    runs = _db_query("""SELECT script_name, status, rows_processed,
        ROUND(duration_sec::numeric,1) as duration_sec, error_message, run_type, triggered_by, started_at, completed_at
        FROM pipeline_runs WHERE started_at > NOW()-INTERVAL '24 hours' ORDER BY started_at DESC LIMIT 100""") or []
    actions = _db_query("""SELECT action_type, target, reason, success, result, created_at
        FROM watchdog_actions WHERE created_at > NOW()-INTERVAL '24 hours' ORDER BY created_at DESC LIMIT 50""") or []
    stats = _db_query("""SELECT COUNT(*) as total, COUNT(CASE WHEN status='success' THEN 1 END) as success,
        COUNT(CASE WHEN status='failed' THEN 1 END) as failed, COUNT(CASE WHEN run_type='retry' THEN 1 END) as retries
        FROM pipeline_runs WHERE started_at > NOW()-INTERVAL '24 hours'""", fetch="one") or {}
    schedule = _db_query("""SELECT ps.script_name, ps.display_name, ps.critical, ps.expected_hour, ps.expected_min,
        (SELECT status FROM pipeline_runs WHERE script_name=ps.script_name ORDER BY started_at DESC LIMIT 1) as last_status,
        (SELECT started_at FROM pipeline_runs WHERE script_name=ps.script_name ORDER BY started_at DESC LIMIT 1) as last_run
        FROM pipeline_schedule ps WHERE ps.active=true ORDER BY ps.expected_hour, ps.expected_min""") or []
    return {
        "stats": {k: _json_clean(v) for k, v in stats.items()} if stats else {},
        "runs": [{k: _json_clean(v) for k, v in r.items()} for r in runs],
        "watchdog_actions": [{k: _json_clean(v) for k, v in r.items()} for r in actions],
        "schedule": [{k: _json_clean(v) for k, v in r.items()} for r in schedule],
    }


def _pipeline_run_health():
    """GET /api/v2/pipeline-run-health — comprehensive pipeline run health status."""
    # Latest run from screener_run_health
    latest_run = {}
    try:
        _rh = _db_query("""
            SELECT run_label, run_date, status, symbols_scanned, expected_min_symbols,
                   go_count, wait_count, no_go_count, reason_codes, finished_at
            FROM screener_run_health
            WHERE run_date = CURRENT_DATE
            ORDER BY finished_at DESC NULLS LAST LIMIT 1
        """, fetch="one")
        if _rh:
            data_age = None
            if _rh.get("finished_at"):
                try:
                    data_age = int((datetime.now(timezone.utc) - _rh["finished_at"].astimezone(timezone.utc)).total_seconds() / 60)
                except Exception:
                    pass
            latest_run = {
                "run_label": _rh.get("run_label"),
                "run_date": str(_rh.get("run_date")),
                "status": _rh.get("status"),
                "symbols_scanned": _rh.get("symbols_scanned"),
                "expected_min_symbols": _rh.get("expected_min_symbols"),
                "go_count": _rh.get("go_count"),
                "wait_count": _rh.get("wait_count"),
                "no_go_count": _rh.get("no_go_count"),
                "reason_codes": _rh.get("reason_codes") or [],
                "data_age_minutes": data_age,
                "latest_scan": str(_rh.get("finished_at")) if _rh.get("finished_at") else None,
            }
    except Exception:
        pass

    # If no run health record, fall back to trade_ai_scans
    if not latest_run:
        _scan = _db_query("""
            SELECT run_label, MAX(scanned_at) AS latest,
                   COUNT(DISTINCT symbol) AS symbols,
                   COUNT(CASE WHEN decision='GO' THEN 1 END) AS go_cnt,
                   COUNT(CASE WHEN decision='WAIT' THEN 1 END) AS wait_cnt
            FROM trade_ai_scans
            WHERE (scanned_at AT TIME ZONE 'America/New_York')::date =
                  (NOW() AT TIME ZONE 'America/New_York')::date
            GROUP BY run_label ORDER BY latest DESC LIMIT 1
        """, fetch="one")
        if _scan:
            latest_run = {
                "run_label": _scan.get("run_label"),
                "run_date": str(datetime.now(timezone.utc).date()),
                "status": "RUN_HEALTHY" if (_scan.get("symbols") or 0) >= 40 else "RUN_UNDERFILLED",
                "symbols_scanned": _scan.get("symbols") or 0,
                "expected_min_symbols": 40,
                "go_count": _scan.get("go_cnt") or 0,
                "wait_count": _scan.get("wait_cnt") or 0,
            }

    # Prospects
    _prospects_info = _db_query("""
        SELECT COUNT(DISTINCT symbol) AS cnt, MAX(scanned_at) AS last_scan
        FROM trade_ai_scans
        WHERE (scanned_at AT TIME ZONE 'America/New_York')::date =
              (NOW() AT TIME ZONE 'America/New_York')::date
    """, fetch="one") or {}
    _is_stale = (_prospects_info.get("cnt") or 0) == 0
    prospects = {
        "count": _prospects_info.get("cnt") or 0,
        "is_stale": _is_stale,
        "last_scan": str(_prospects_info.get("last_scan")) if _prospects_info.get("last_scan") else None,
    }

    # Strategy signals
    _signals = _db_query("""
        SELECT strategy_id, COUNT(*) AS cnt
        FROM strategy_signals
        WHERE fired_at::date = CURRENT_DATE
        GROUP BY strategy_id
    """) or []
    strategy_signals = {
        "today_count": sum(r.get("cnt", 0) for r in _signals),
        "by_strategy": {r["strategy_id"]: r["cnt"] for r in _signals},
    }

    # Trade plans
    _plans = _db_query("""
        SELECT COUNT(*) AS proposal_worthy,
               COUNT(CASE WHEN entry_high IS NOT NULL AND stop_loss IS NOT NULL
                          AND target_1 IS NOT NULL AND shares IS NOT NULL THEN 1 END) AS planned
        FROM strategy_signals
        WHERE fired_at::date = CURRENT_DATE
        AND (signal_grade IN ('A','A+') OR signal_score >= 40)
    """, fetch="one") or {}
    pw = int(_plans.get("proposal_worthy") or 0)
    pl = int(_plans.get("planned") or 0)
    trade_plans = {
        "proposal_worthy": pw,
        "planned": pl,
        "coverage_pct": round(pl / pw * 100, 1) if pw > 0 else 0,
    }

    # Paper proposals
    _pp = _db_query("""
        SELECT COUNT(CASE WHEN status='pending' THEN 1 END) AS pending,
               COUNT(CASE WHEN status='eligible' THEN 1 END) AS eligible
        FROM paper_proposals
        WHERE created_at::date = CURRENT_DATE
    """, fetch="one") or {}

    paper_proposals = {
        "pending": int(_pp.get("pending") or 0),
        "eligible_not_created": 0,
        "blocked_reasons": [],
    }
    if not latest_run.get("status") or latest_run.get("status") in ("RUN_UNDERFILLED", "RUN_FAILED"):
        paper_proposals["blocked_reasons"].append(f"Latest run is {latest_run.get('status', 'UNKNOWN')}")
    if trade_plans["coverage_pct"] < 50 and pw > 0:
        paper_proposals["blocked_reasons"].append(f"Trade plan coverage only {trade_plans['coverage_pct']}%")

    # Auto-proposal diagnostics
    auto_proposals = {}
    try:
        _ap = _db_query("""
            SELECT run_label, status, signals_checked, proposals_created, proposals_skipped,
                   duplicates_skipped, risk_rejected, quality_rejected, source_cap_rejected,
                   sizing_adjusted, reason_summary, finished_at
            FROM auto_proposal_runs
            WHERE run_date = CURRENT_DATE
            ORDER BY finished_at DESC NULLS LAST LIMIT 1
        """, fetch="one")
        if _ap:
            auto_proposals = {k: _json_clean(v) for k, v in _ap.items()}
    except Exception:
        pass

    return {
        "ok": True,
        "latest_run": {k: _json_clean(v) for k, v in latest_run.items()} if latest_run else None,
        "prospects": prospects,
        "strategy_signals": strategy_signals,
        "trade_plans": trade_plans,
        "paper_proposals": paper_proposals,
        "auto_proposals": auto_proposals if auto_proposals else None,
    }


def _auto_proposal_diagnostics():
    """GET /api/v2/auto-proposal-diagnostics — latest auto-proposal run details."""
    runs = _db_query("""
        SELECT id, run_label, run_date, status, signals_checked, proposals_created,
               proposals_skipped, duplicates_skipped, risk_rejected, quality_rejected,
               source_cap_rejected, sizing_adjusted, reason_summary, finished_at
        FROM auto_proposal_runs
        WHERE run_date >= CURRENT_DATE - INTERVAL '7 days'
        ORDER BY finished_at DESC NULLS LAST LIMIT 10
    """) or []
    decisions = _db_query("""
        SELECT symbol, strategy_id, decision, reason_codes, proposal_id,
               original_shares, adjusted_shares, risk_gate_result, risk_gate_codes
        FROM auto_proposal_decisions
        WHERE created_at >= CURRENT_DATE
        ORDER BY created_at DESC LIMIT 50
    """) or []
    summary = {}
    for d in decisions:
        dec = d.get("decision", "UNKNOWN")
        summary[dec] = summary.get(dec, 0) + 1
    return {
        "ok": True,
        "runs": [{k: _json_clean(v) for k, v in r.items()} for r in runs],
        "decisions": [{k: _json_clean(v) for k, v in d.items()} for d in decisions],
        "summary": summary,
    }


def _agent_calibration():
    """GET /api/v2/agent-calibration — agent accuracy and source performance."""
    calibration = _db_query("""
        SELECT agent_name, strategy_type, window_days,
               accuracy_pct, correct_count, wrong_count,
               total_recommendations, trending, avg_pnl_pct, total_pnl,
               recent_accuracy_30d, computed_at
        FROM agent_calibration
        ORDER BY agent_name, window_days, strategy_type NULLS FIRST
    """) or []

    outcomes = _db_query("""
        SELECT agent_name, symbol, recommendation, verdict, verdict_score,
               pnl_pct, recommendation_date, exit_date, delta_days
        FROM agent_recommendation_outcomes
        ORDER BY scored_at DESC LIMIT 30
    """) or []

    sources = _db_query("""
        SELECT source_type, source_id, win_rate, scar_factor,
               trades_matched, total_signals, avg_pnl_pct
        FROM source_performance ORDER BY source_type, win_rate DESC NULLS LAST LIMIT 50
    """) or []

    total_outcomes = (_db_query("SELECT COUNT(*) as cnt FROM agent_recommendation_outcomes", fetch="one") or {}).get("cnt", 0)
    total_trades = (_db_query("SELECT COUNT(*) as cnt FROM trade_closed", fetch="one") or {}).get("cnt", 0)

    return {
        "has_data": len(calibration) > 0,
        "total_outcomes_scored": total_outcomes,
        "total_trades": total_trades,
        "calibration": [{k: _json_clean(v) for k, v in r.items()} for r in calibration],
        "recent_outcomes": [{k: _json_clean(v) for k, v in r.items()} for r in outcomes],
        "source_performance": [{k: _json_clean(v) for k, v in r.items()} for r in sources],
    }


# ── Recovery endpoint (was missing — frontend had no API) ──────────────────

def _recovery_dashboard():
    """GET /api/v2/recovery — Full recovery watch dashboard with exit classification."""
    items = _db_query("""
        SELECT id, symbol, account, stopped_out_at, exit_price, stop_price,
               reason, status, analyst_verdict, analyst_confidence, analyst_summary,
               reentry_trigger, invalidated_if, escalated_to, escalated_at,
               temp_allocation_verdict, temp_allocation_reason, temp_allocation_target,
               exit_type, explicit_stop_out, relisted_without_stop_out,
               market_reconnection_event, patience_score, relist_count,
               last_reviewed_at, created_at
        FROM stopped_out_watch WHERE is_active = true
        ORDER BY analyst_confidence DESC NULLS LAST, stopped_out_at DESC
    """) or []

    # Relist events
    relist_events = _db_query("""
        SELECT watch_id, symbol, relist_date, price_at_relist, relist_reason, classified_as
        FROM stopped_out_relist_events ORDER BY relist_date DESC LIMIT 20
    """) or []

    # History
    history = _db_query("""
        SELECT watch_id, symbol, old_verdict, new_verdict, summary, changed_at
        FROM stopped_out_watch_history ORDER BY changed_at DESC LIMIT 30
    """) or []

    # Summary stats
    true_stopouts = sum(1 for i in items if i.get("explicit_stop_out"))
    relists = sum(1 for i in items if i.get("relisted_without_stop_out"))
    reentry_candidates = sum(1 for i in items if i.get("analyst_verdict") == "reentry_candidate")
    avg_patience = sum(float(i.get("patience_score") or 0) for i in items) / max(1, len(items))

    return {
        "items": [{k: _json_clean(v) for k, v in r.items()} for r in items],
        "relist_events": [{k: _json_clean(v) for k, v in r.items()} for r in relist_events],
        "history": [{k: _json_clean(v) for k, v in r.items()} for r in history],
        "summary": {
            "total_active": len(items),
            "true_stopouts": true_stopouts,
            "relists_no_exit": relists,
            "reentry_candidates": reentry_candidates,
            "avg_patience_score": round(avg_patience, 2),
        },
        "classification_legend": {
            "true_stop_out": "Explicit exit — price breached stop or deliberate abandon",
            "relist_no_exit": "Vehicle relisted without us exiting — market behavior, not failure",
            "market_reconnection": "Auction/market mechanics shift — not a strategy failure",
            "unclassified": "Needs manual review to determine exit type",
        },
        "sector_context": _recovery_sector_context([i.get("symbol") for i in items]),
        "llm_analysis": {k: _json_clean(v) for k, v in (_db_query("SELECT content, generated_at FROM llm_intelligence_cache WHERE section='recovery_analysis'", fetch="one") or {}).items()},
    }


def _recovery_sector_context(symbols: list) -> dict:
    """Get sector and technical context for recovery watch symbols."""
    ts = _load_json(STATE_DIR / "technical_snapshot.json") or {}
    context = {}
    for sym in symbols:
        if not sym:
            continue
        tech = ts.get(sym, {}) if isinstance(ts, dict) else {}
        if tech:
            context[sym] = {
                "sector": tech.get("sector", ""),
                "industry": tech.get("industry", ""),
                "rsi": tech.get("rsi"),
                "sma50_pct": tech.get("sma50_pct"),
                "sma200_pct": tech.get("sma200_pct"),
                "perf_week": tech.get("perf_week"),
                "perf_month": tech.get("perf_month"),
                "beta": tech.get("beta"),
            }
    return context


# ── CIO unified endpoint (was missing) ────────────────────────────────────

def _cio_unified():
    """GET /api/v2/cio — Unified CIO intelligence: decisions, rotations, plans, signals.

    Deduplicates daily repeat decisions — shows only the latest per symbol.
    """
    decisions = _db_query("""
        SELECT action, priority, COUNT(DISTINCT symbol) as unique_symbols,
               COUNT(*) as total_decisions
        FROM cio_decisions GROUP BY action, priority
        ORDER BY CASE priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END, unique_symbols DESC
    """) or []

    pending_review = _db_query(
        "SELECT COUNT(DISTINCT symbol) as cnt FROM cio_decisions WHERE action='HUMAN_REVIEW'", fetch="one"
    ) or {}

    # Deduplicated: latest decision per symbol (not all daily repeats)
    recent_decisions = _db_query("""
        SELECT DISTINCT ON (symbol)
            symbol, action, priority, rationale, created_at
        FROM cio_decisions
        ORDER BY symbol, created_at DESC
    """) or []

    # Sort by priority then date for display
    priority_order = {'critical': 0, 'high': 1, 'normal': 2}
    recent_decisions = sorted(recent_decisions, key=lambda r: (
        priority_order.get(r.get('priority', 'normal'), 3),
        str(r.get('created_at', ''))
    ), reverse=False)
    recent_decisions = recent_decisions[:30]

    rotations = _db_query("""
        SELECT * FROM strategy_rotation_recommendations ORDER BY created_at DESC LIMIT 10
    """) or []

    latest_plan = _db_query("""
        SELECT plan_id, plan_summary, total_trade_value, human_review_required, generated_at
        FROM rebalance_plans ORDER BY generated_at DESC LIMIT 1
    """, fetch="one") or {}

    # Pipeline health (recent failures)
    pipeline_health = []
    try:
        pipeline_health = _db_query("""
            SELECT pipeline_key, COUNT(*) FILTER (WHERE status='failed') as failures,
                   MAX(started_at) as last_run
            FROM pipeline_runs WHERE started_at > NOW() - INTERVAL '7 days'
            GROUP BY pipeline_key
            HAVING COUNT(*) FILTER (WHERE status='failed') > 0
            ORDER BY failures DESC LIMIT 5
        """) or []
    except Exception:
        pass

    # Learning recommendations (deduplicated by title)
    learning_recs = _db_query("""
        SELECT DISTINCT ON (title) recommendation_id, domain, recommendation_type,
               title, summary, confidence, risk_level, status
        FROM learning_recommendations WHERE status = 'proposed'
        ORDER BY title, created_at DESC
    """) or []

    # ── Categorize decisions into actionable groups ──
    action_groups = {"rebalance": [], "income_research": [], "defense_thesis": [],
                     "holds": [], "other": []}
    for d in recent_decisions:
        dd = {k: _json_clean(v) for k, v in d.items()}
        action = dd.get("action", "")
        rationale = dd.get("rationale", "")
        strategy = ""
        # Extract strategy from rationale (format: "strategy_type ACTION...")
        if rationale:
            strategy = rationale.split(" ")[0] if " " in rationale else ""

        if "REBALANCE_TRIM" in rationale or action == "REBALANCE_TRIM":
            action_groups["rebalance"].append(dd)
        elif "defense_thesis" in strategy:
            action_groups["defense_thesis"].append(dd)
        elif "income" in strategy or "bdc" in strategy or "yield" in strategy:
            action_groups["income_research"].append(dd)
        elif action == "HOLD":
            action_groups["holds"].append(dd)
        else:
            action_groups["other"].append(dd)

    # Actionable summary
    actionable_summary = []
    if action_groups["rebalance"]:
        syms = [d["symbol"] for d in action_groups["rebalance"]]
        actionable_summary.append(f"REBALANCE: {len(syms)} positions flagged for trim — {', '.join(syms[:5])}")
    if action_groups["defense_thesis"]:
        syms = [d["symbol"] for d in action_groups["defense_thesis"]]
        actionable_summary.append(f"DEFENSE THESIS: {len(syms)} buy candidates — {', '.join(syms[:5])}")
    if action_groups["income_research"]:
        syms = [d["symbol"] for d in action_groups["income_research"]]
        actionable_summary.append(f"INCOME RESEARCH: {len(syms)} candidates — {', '.join(syms[:5])}")
    if action_groups["holds"]:
        actionable_summary.append(f"HOLDS: {len(action_groups['holds'])} positions confirmed — no action needed")

    return {
        "decision_summary": [{k: _json_clean(v) for k, v in r.items()} for r in decisions],
        "human_review_pending": pending_review.get("cnt", 0),
        "recent_decisions": [{k: _json_clean(v) for k, v in r.items()} for r in recent_decisions],
        "action_groups": {k: v for k, v in action_groups.items() if v},
        "actionable_summary": actionable_summary,
        "pending_rotations": [{k: _json_clean(v) for k, v in r.items()} for r in rotations],
        "latest_plan": {k: _json_clean(v) for k, v in latest_plan.items()} if latest_plan else None,
        "pipeline_issues": [{k: _json_clean(v) for k, v in r.items()} for r in pipeline_health],
        "learning_recommendations": [{k: _json_clean(v) for k, v in r.items()} for r in learning_recs],
        "news_context": _cio_news_context([d.get("symbol") for d in recent_decisions if d.get("symbol")]),
        "note": "CIO dashboard. All actions require human review. No broker execution.",
    }


def _cio_news_context(symbols: list) -> dict:
    """Get recent news for CIO decision symbols."""
    if not symbols:
        return {}
    unique = list(set(s for s in symbols if s))[:20]
    news = {}
    for sym in unique:
        rows = _db_query("""
            SELECT title, source, sentiment, created_at::date as date
            FROM news_articles
            WHERE symbol = %s AND created_at > NOW() - INTERVAL '7 days'
            ORDER BY created_at DESC LIMIT 2
        """, (sym,)) or []
        if rows:
            news[sym] = [{"title": r.get("title", ""), "source": r.get("source", ""),
                          "sentiment": r.get("sentiment"), "date": str(r.get("date", ""))}
                         for r in rows]
    return news


# ── Portfolio Monitor endpoint (was missing) ───────────────────────────────

def _portfolio_monitor():
    """GET /api/v2/portfolio-monitor — Real-time portfolio intelligence."""
    h = _load_json(STATE_DIR / "holdings.json") or {}
    rm = _load_json(STATE_DIR / "risk_management.json") or {}
    ts = _load_json(STATE_DIR / "technical_snapshot.json") or {}
    news = _load_json(STATE_DIR / "portfolio_news.json") or {}
    freshness = _load_json(STATE_DIR / "_freshness.json") or {}
    div_cal = _load_json(STATE_DIR / "dividend_calendar.json") or {}

    holdings = h.get("holdings", [])
    total_value = sum(p.get("market_value", 0) for p in holdings)
    cash = sum(p.get("market_value", 0) for p in holdings if p.get("is_cash"))

    # Enrich holdings with technicals + P&L
    enriched = []
    sector_totals = {}
    for pos in holdings:
        sym = pos.get("symbol", "")
        if not sym or pos.get("is_cash"):
            continue
        tech = ts.get(sym, {}) if isinstance(ts, dict) else {}
        mv = pos.get("market_value", 0)
        cost_basis = pos.get("cost_basis") or pos.get("avg_cost")
        shares = pos.get("shares", 0)
        gain_pct = pos.get("gain_pct")
        gain_dollar = None
        if cost_basis and shares and mv:
            gain_dollar = round(mv - (float(cost_basis) * float(shares)), 2)
            if not gain_pct:
                gain_pct = round((mv / (float(cost_basis) * float(shares)) - 1) * 100, 1) if cost_basis else None

        sector = tech.get("sector") or pos.get("sector", "Other")
        if sector:
            sector_totals[sector] = sector_totals.get(sector, 0) + mv

        rsi = tech.get("rsi")
        rsi_signal = None
        if rsi is not None:
            rsi = float(rsi)
            rsi_signal = "oversold" if rsi < 30 else ("overbought" if rsi > 70 else None)

        enriched.append({
            "symbol": sym,
            "name": pos.get("name", ""),
            "account": pos.get("account", ""),
            "shares": shares,
            "price": pos.get("price", 0),
            "market_value": mv,
            "portfolio_pct": round(mv / total_value * 100, 1) if total_value else 0,
            "gain_pct": gain_pct,
            "gain_dollar": gain_dollar,
            "cost_basis": cost_basis,
            "rsi": rsi,
            "rsi_signal": rsi_signal,
            "sma50_pct": tech.get("sma50_pct"),
            "sma200_pct": tech.get("sma200_pct"),
            "beta": tech.get("beta"),
            "perf_week": tech.get("perf_week"),
            "sector": sector,
        })

    # Sector concentration analysis
    sector_breakdown = []
    for sector, mv in sorted(sector_totals.items(), key=lambda x: -x[1]):
        pct = round(mv / total_value * 100, 1) if total_value else 0
        concentration_flag = "HIGH" if pct > 25 else ("MODERATE" if pct > 15 else None)
        sector_breakdown.append({
            "sector": sector,
            "market_value": round(mv, 2),
            "portfolio_pct": pct,
            "concentration_flag": concentration_flag,
        })

    # Daily delta: compare freshness data
    delta = {}
    if freshness:
        delta["last_refresh"] = freshness.get("completed_at")
        delta["holdings_as_of"] = freshness.get("holdings_as_of")
        delta["pipeline_status"] = freshness.get("status", "unknown")

    # Risk alerts
    risk_positions = rm.get("positions", [])
    no_stop = [p for p in risk_positions if p.get("status") == "NO STOP"]
    triggered = [p for p in risk_positions if p.get("status") == "TRIGGERED"]
    heat = rm.get("portfolio_heat_pct", 0)

    # News digest
    all_news = news.get("all_scored") or news.get("catalysts") or []
    top_news = sorted(all_news, key=lambda x: x.get("quality_score", 0), reverse=True)[:10]

    # LLM health summaries (if available)
    llm_health = _db_query("""
        SELECT symbol, holdings_llm_health, holdings_llm_action, holdings_llm_confidence
        FROM watchlist_items WHERE holdings_llm_health IS NOT NULL
        ORDER BY holdings_llm_confidence DESC NULLS LAST
    """) or []

    # Stopped out watch
    recovery_items = _db_query("""
        SELECT symbol, analyst_verdict, analyst_confidence, exit_type,
               explicit_stop_out, relisted_without_stop_out
        FROM stopped_out_watch WHERE is_active = true
    """) or []

    return {
        "portfolio_summary": {
            "total_value": total_value,
            "cash": cash,
            "cash_pct": round(cash / total_value * 100, 1) if total_value else 0,
            "position_count": len(enriched),
            "portfolio_heat_pct": heat,
            "no_stop_count": len(no_stop),
            "triggered_count": len(triggered),
        },
        "holdings": enriched,
        "risk_alerts": {
            "no_stop": [{"symbol": p.get("symbol"), "market_value": p.get("market_value")} for p in no_stop[:10]],
            "triggered": [{"symbol": p.get("symbol"), "stop_price": p.get("stop_price")} for p in triggered],
        },
        "top_news": [{"symbol": n.get("portfolio_symbol", ""), "title": n.get("title", ""),
                       "source": n.get("source", ""), "score": n.get("quality_score", 0)} for n in top_news],
        "llm_health": [{k: _json_clean(v) for k, v in r.items()} for r in llm_health],
        "recovery_watch": [{k: _json_clean(v) for k, v in r.items()} for r in recovery_items],
        "sector_breakdown": sector_breakdown,
        "concentration_alerts": [s for s in sector_breakdown if s.get("concentration_flag")],
        "delta": delta,
        "dividends": {
            "total_annual_income": div_cal.get("total_annual", 0),
            "monthly_average": div_cal.get("monthly_average", 0),
            "ex_div_alerts": div_cal.get("ex_div_alerts", []),
            "current_month_payers": _get_current_month_dividends(div_cal),
            "top_payers": [{"symbol": p.get("symbol"), "annual": p.get("annual_income"),
                            "yield_pct": p.get("yield_pct"), "frequency": p.get("frequency"),
                            "safety": p.get("safety")}
                           for p in (div_cal.get("payers") or [])[:10]],
        },
        "freshness": freshness,
    }


def _get_current_month_dividends(div_cal):
    """Get dividend payers for the current month."""
    from datetime import datetime
    current_month = datetime.now().month
    monthly = div_cal.get("monthly_summary", [])
    for m in monthly:
        if m.get("month") == current_month:
            return {
                "month_name": m.get("month_name", ""),
                "total": m.get("total", 0),
                "symbols": m.get("symbols", []),
                "count": m.get("count", 0),
            }
    return {"month_name": "", "total": 0, "symbols": [], "count": 0}


# ── Reports hub endpoint (was missing) ────────────────────────────────────

def _reports_hub():
    """GET /api/v2/reports — Reports hub with weekly/monthly data + docx catalog."""
    import glob as _glob
    import os as _os

    # Weekly report data
    agent_activity = _db_query("""
        SELECT agent, COUNT(*) as analyses, AVG(confidence)::numeric(3,2) as avg_conf
        FROM watchlist_agent_results WHERE created_at > NOW() - INTERVAL '7 days'
        GROUP BY agent ORDER BY analyses DESC
    """) or []

    proposals = _db_query("""
        SELECT status, COUNT(*) as cnt FROM paper_trade_proposals
        WHERE created_at > NOW() - INTERVAL '7 days'
        GROUP BY status ORDER BY cnt DESC
    """) or []

    # Pipeline activity
    pipeline_runs = _db_query("""
        SELECT pipeline_key, COUNT(*) as runs,
               MAX(started_at) as last_run,
               COUNT(*) FILTER (WHERE status = 'completed') as successes,
               COUNT(*) FILTER (WHERE status = 'failed') as failures
        FROM pipeline_runs WHERE started_at > NOW() - INTERVAL '7 days'
        GROUP BY pipeline_key ORDER BY runs DESC LIMIT 15
    """) or []

    # Learning stats
    learning = _db_query("""
        SELECT domain, COUNT(*) as hypotheses,
               COUNT(*) FILTER (WHERE status = 'proposed') as pending
        FROM learning_hypotheses WHERE created_at > NOW() - INTERVAL '30 days'
        GROUP BY domain
    """) or []

    # Incubator stats
    incubator = _db_query("""
        SELECT status, COUNT(*) as cnt FROM incubator_universe GROUP BY status
    """) or []

    # Social ingestion
    social = _db_query("""
        SELECT platform, COUNT(*) as posts
        FROM social_posts WHERE ingested_at > NOW() - INTERVAL '7 days'
        GROUP BY platform
    """) or []

    # ── Week-over-week comparison ──
    prior_week_agents = _db_query("""
        SELECT agent, COUNT(*) as analyses, AVG(confidence)::numeric(3,2) as avg_conf
        FROM watchlist_agent_results
        WHERE created_at > NOW() - INTERVAL '14 days' AND created_at <= NOW() - INTERVAL '7 days'
        GROUP BY agent ORDER BY analyses DESC
    """) or []

    prior_week_proposals = _db_query("""
        SELECT status, COUNT(*) as cnt FROM paper_trade_proposals
        WHERE created_at > NOW() - INTERVAL '14 days' AND created_at <= NOW() - INTERVAL '7 days'
        GROUP BY status
    """) or []

    # Win rates
    win_rate_data = _db_query("""
        SELECT COUNT(*) as total,
               COUNT(*) FILTER (WHERE pnl > 0) as wins,
               COUNT(*) FILTER (WHERE pnl <= 0) as losses,
               AVG(r_multiple)::numeric(4,2) as avg_r,
               SUM(pnl)::numeric(10,2) as total_pnl
        FROM paper_trades WHERE status = 'closed'
    """, fetch="one") or {}

    # Agent accuracy from calibration
    agent_accuracy = _db_query("""
        SELECT agent_name, accuracy_pct, correct_count, wrong_count, trending
        FROM agent_calibration WHERE window_days = 90 AND strategy_type IS NULL
        ORDER BY agent_name
    """) or []

    # Compute trend arrows (this week vs prior)
    agent_trends = {}
    current_map = {a.get("agent"): int(a.get("analyses", 0)) for a in agent_activity}
    prior_map = {a.get("agent"): int(a.get("analyses", 0)) for a in prior_week_agents}
    for agent in set(list(current_map.keys()) + list(prior_map.keys())):
        curr = current_map.get(agent, 0)
        prev = prior_map.get(agent, 0)
        if curr > prev * 1.1:
            agent_trends[agent] = "up"
        elif curr < prev * 0.9:
            agent_trends[agent] = "down"
        else:
            agent_trends[agent] = "stable"

    # DOCX catalog
    docx_files = []
    archive_root = str(PROJECT_ROOT / "archive" / "weekly")
    for f in sorted(_glob.glob(f"{archive_root}/**/*.docx", recursive=True), reverse=True)[:20]:
        docx_files.append({
            "filename": _os.path.basename(f),
            "path": f.replace(str(PROJECT_ROOT), ""),
            "size_kb": round(_os.path.getsize(f) / 1024, 1),
            "modified": datetime.fromtimestamp(_os.path.getmtime(f)).isoformat(),
        })

    # Weekly Word report status
    latest_weekly_docx = docx_files[0] if docx_files else None
    weekly_docx_age_days = None
    if latest_weekly_docx:
        try:
            from datetime import datetime as _dt
            mod = _dt.fromisoformat(latest_weekly_docx["modified"])
            weekly_docx_age_days = (datetime.now() - mod).days
        except Exception:
            pass

    return {
        "period": "weekly",
        "generated_at": datetime.now().isoformat(),
        "agent_activity": [{k: _json_clean(v) for k, v in r.items()} for r in agent_activity],
        "agent_trends": agent_trends,
        "agent_accuracy": [{k: _json_clean(v) for k, v in r.items()} for r in agent_accuracy],
        "proposal_summary": [{k: _json_clean(v) for k, v in r.items()} for r in proposals],
        "prior_week_proposals": [{k: _json_clean(v) for k, v in r.items()} for r in prior_week_proposals],
        "win_rate": {k: _json_clean(v) for k, v in win_rate_data.items()} if win_rate_data else {},
        "pipeline_runs": [{k: _json_clean(v) for k, v in r.items()} for r in pipeline_runs],
        "learning_stats": [{k: _json_clean(v) for k, v in r.items()} for r in learning],
        "incubator_stats": [{k: _json_clean(v) for k, v in r.items()} for r in incubator],
        "social_ingestion": [{k: _json_clean(v) for k, v in r.items()} for r in social],
        "docx_catalog": docx_files,
        "weekly_docx_status": {
            "latest": latest_weekly_docx,
            "age_days": weekly_docx_age_days,
            "is_stale": (weekly_docx_age_days or 99) > 7,
            "note": "Weekly Word report should be generated every Sunday" if (weekly_docx_age_days or 99) > 7 else "Weekly Word report is current",
        },
        "market_intelligence": _market_intelligence_summary(),
    }


# ── Morning Command: unified daily starting point ─────────────────────────

def _morning_command():
    """GET /api/v2/command — Single-page daily intelligence briefing.

    Synthesizes: portfolio health, overnight changes, dividends due,
    proposals needing action, recovery items, top news, social sentiment,
    market context, pipeline status. This is the page you open first.
    """
    h = _load_json(STATE_DIR / "holdings.json") or {}
    rm = _load_json(STATE_DIR / "risk_management.json") or {}
    freshness = _load_json(STATE_DIR / "_freshness.json") or {}
    div_cal = _load_json(STATE_DIR / "dividend_calendar.json") or {}
    news_data = _load_json(STATE_DIR / "portfolio_news.json") or {}

    # ── Portfolio snapshot ──
    holdings = h.get("holdings", [])
    total = sum(p.get("market_value", 0) for p in holdings)
    cash = sum(p.get("market_value", 0) for p in holdings if p.get("is_cash"))
    heat = rm.get("portfolio_heat_pct", 0)
    no_stop = sum(1 for p in rm.get("positions", []) if p.get("status") == "NO STOP")
    triggered = sum(1 for p in rm.get("positions", []) if p.get("status") == "TRIGGERED")

    # ── Top movers today (from holdings with perf data) ──
    ts = _load_json(STATE_DIR / "technical_snapshot.json") or {}
    movers = []
    for pos in holdings:
        sym = pos.get("symbol", "")
        if not sym or pos.get("is_cash"):
            continue
        tech = ts.get(sym, {}) if isinstance(ts, dict) else {}
        perf = tech.get("perf_week")
        if perf is not None:
            movers.append({"symbol": sym, "perf_week": perf, "price": pos.get("price", 0),
                           "market_value": pos.get("market_value", 0)})
    movers.sort(key=lambda x: abs(x.get("perf_week", 0)), reverse=True)
    top_gainers = [m for m in movers if m.get("perf_week", 0) > 0][:5]
    top_losers = [m for m in movers if m.get("perf_week", 0) < 0][:5]

    # ── Dividends this month ──
    from datetime import datetime as _ddt
    current_month = _ddt.now().month
    monthly = div_cal.get("monthly_summary", [])
    this_month_div = next((m for m in monthly if m.get("month") == current_month), {})

    # ── Proposals needing action ──
    pending_proposals = _db_query("""
        SELECT id, symbol, strategy_id, status, created_at::date as created
        FROM paper_trade_proposals
        WHERE status = 'PENDING'
        ORDER BY created_at ASC LIMIT 10
    """) or []

    # ── Recovery watch ──
    recovery = _db_query("""
        SELECT symbol, analyst_verdict, analyst_confidence, exit_type, patience_score
        FROM stopped_out_watch WHERE is_active = true
        ORDER BY analyst_confidence DESC NULLS LAST
    """) or []

    # ── Top news (portfolio-relevant) ──
    top_news = _db_query("""
        SELECT DISTINCT ON (symbol) symbol, title, source, relevance_score, sentiment, created_at
        FROM news_articles
        WHERE created_at > NOW() - INTERVAL '24 hours' AND symbol IS NOT NULL AND symbol != ''
        ORDER BY symbol, relevance_score DESC NULLS LAST
        LIMIT 10
    """) or []

    # ── Social sentiment highlights ──
    social_highlights = _db_query("""
        SELECT DISTINCT ON (symbol) symbol, mention_count, bullish_count, bearish_count,
               sentiment_score, theme_tags
        FROM social_sentiment_history
        WHERE observed_at > NOW() - INTERVAL '48 hours'
        ORDER BY symbol, mention_count DESC NULLS LAST
        LIMIT 10
    """) or []

    # ── CIO actions pending (deduped) ──
    cio_pending = _db_query("""
        SELECT DISTINCT ON (symbol) symbol, action, priority, rationale
        FROM cio_decisions
        WHERE priority IN ('critical', 'high')
        ORDER BY symbol, created_at DESC
    """) or []

    # ── Pipeline status ──
    pipeline_ok = True
    pipeline_note = "All systems operational"
    try:
        runs = _db_query("""
            SELECT COUNT(*) FILTER (WHERE status='failed') as failed,
                   COUNT(*) as total
            FROM pipeline_runs WHERE started_at > NOW() - INTERVAL '12 hours'
        """, fetch="one") or {}
        if runs.get("failed", 0) > 0:
            pipeline_ok = False
            pipeline_note = f"{runs['failed']}/{runs['total']} pipeline runs failed in last 12h"
    except Exception:
        pass

    # ── Screener status ──
    screener_status = _db_query("""
        SELECT status, symbols_scanned, finished_at
        FROM screener_run_health WHERE run_date = CURRENT_DATE
        ORDER BY finished_at DESC LIMIT 1
    """, fetch="one") or {}

    # ── Action items (prioritized) ──
    actions = []
    if triggered > 0:
        actions.append({"priority": "urgent", "action": f"{triggered} stop(s) triggered — review immediately"})
    if heat > 5:
        actions.append({"priority": "high", "action": f"Portfolio heat {heat:.1f}% — above 5% threshold"})
    if no_stop > 5:
        actions.append({"priority": "high", "action": f"{no_stop} positions without stops — set stops"})
    if pending_proposals:
        actions.append({"priority": "medium", "action": f"{len(pending_proposals)} proposals pending review"})
    cio_critical = [c for c in cio_pending if c.get("priority") == "critical"]
    if cio_critical:
        syms = ", ".join(c["symbol"] for c in cio_critical[:3])
        actions.append({"priority": "medium", "action": f"CIO critical: {syms}"})
    reentry = [r for r in recovery if r.get("analyst_verdict") == "reentry_candidate"]
    if reentry:
        syms = ", ".join(r["symbol"] for r in reentry[:3])
        actions.append({"priority": "low", "action": f"Re-entry candidates: {syms}"})

    # ── LLM intelligence from cache ──
    llm_cache = {}
    for section in ("portfolio_risk", "morning_synthesis", "prospect_narratives"):
        row = _db_query(
            "SELECT content, generated_at FROM llm_intelligence_cache WHERE section = %s",
            (section,), fetch="one"
        )
        if row:
            llm_cache[section] = {"content": row.get("content", ""), "generated_at": str(row.get("generated_at", ""))}

    return {
        "generated_at": datetime.now().isoformat(),
        "llm_intelligence": llm_cache,
        "portfolio": {
            "total_value": total,
            "cash": cash,
            "cash_pct": round(cash / total * 100, 1) if total else 0,
            "positions": len([p for p in holdings if not p.get("is_cash") and p.get("market_value", 0) > 50]),
            "heat_pct": heat,
            "no_stop_count": no_stop,
            "triggered_count": triggered,
        },
        "actions": actions,
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "dividends": {
            "month": this_month_div.get("month_name", ""),
            "total": this_month_div.get("total", 0),
            "symbols": this_month_div.get("symbols", []),
            "annual_income": div_cal.get("total_annual", 0),
        },
        "pending_proposals": [{k: _json_clean(v) for k, v in r.items()} for r in pending_proposals],
        "recovery_watch": [{k: _json_clean(v) for k, v in r.items()} for r in recovery],
        "top_news": [{k: _json_clean(v) for k, v in r.items()} for r in top_news],
        "social_highlights": [{k: _json_clean(v) for k, v in r.items()} for r in social_highlights],
        "cio_pending": [{k: _json_clean(v) for k, v in r.items()} for r in cio_pending],
        "screener": {
            "status": screener_status.get("status"),
            "symbols_scanned": screener_status.get("symbols_scanned"),
        },
        "pipeline": {"ok": pipeline_ok, "note": pipeline_note},
        "freshness": {
            "last_refresh": freshness.get("completed_at"),
            "status": freshness.get("status", "unknown"),
        },
    }


# ── Intelligence enrichment for portfolio holdings ────────────────────────

def _holdings_intelligence():
    """GET /api/v2/portfolio/intelligence-feed — per-holding news, catalysts, social."""
    # Recent news per portfolio symbol
    news_by_symbol = {}
    news_rows = _db_query("""
        SELECT symbol, title, source, sentiment, relevance_score, created_at
        FROM news_articles
        WHERE created_at > NOW() - INTERVAL '3 days'
          AND symbol IS NOT NULL AND symbol != ''
        ORDER BY created_at DESC LIMIT 200
    """) or []
    for r in news_rows:
        sym = r.get("symbol", "")
        if sym not in news_by_symbol:
            news_by_symbol[sym] = []
        if len(news_by_symbol[sym]) < 3:
            news_by_symbol[sym].append({
                "title": r.get("title", ""),
                "source": r.get("source", ""),
                "sentiment": r.get("sentiment"),
                "relevance": _json_clean(r.get("relevance_score")),
                "date": str(r.get("created_at", ""))[:10],
            })

    # Social sentiment per symbol
    social_by_symbol = {}
    social_rows = _db_query("""
        SELECT DISTINCT ON (symbol) symbol, mention_count, bullish_count, bearish_count,
               sentiment_score, theme_tags
        FROM social_sentiment_history
        WHERE observed_at > NOW() - INTERVAL '7 days'
        ORDER BY symbol, observed_at DESC
    """) or []
    for r in social_rows:
        social_by_symbol[r["symbol"]] = {
            "mentions": r.get("mention_count", 0),
            "bullish": r.get("bullish_count", 0),
            "bearish": r.get("bearish_count", 0),
            "score": _json_clean(r.get("sentiment_score")),
            "themes": r.get("theme_tags"),
        }

    return {
        "news": news_by_symbol,
        "social": social_by_symbol,
        "coverage": {
            "news_symbols": len(news_by_symbol),
            "social_symbols": len(social_by_symbol),
            "total_articles_3d": len(news_rows),
        },
    }


# ── Market intelligence summary for reports ───────────────────────────────

def _market_intelligence_summary():
    """GET /api/v2/market-intelligence — aggregated market/sector sentiment."""
    # News sentiment distribution
    sentiment_dist = _db_query("""
        SELECT sentiment, COUNT(*) as cnt
        FROM news_articles
        WHERE created_at > NOW() - INTERVAL '7 days' AND sentiment IS NOT NULL
        GROUP BY sentiment ORDER BY cnt DESC
    """) or []

    # Top mentioned symbols in news
    top_symbols = _db_query("""
        SELECT symbol, COUNT(*) as mentions, AVG(relevance_score)::numeric(3,2) as avg_relevance
        FROM news_articles
        WHERE created_at > NOW() - INTERVAL '7 days' AND symbol IS NOT NULL AND symbol != ''
        GROUP BY symbol ORDER BY mentions DESC LIMIT 15
    """) or []

    # News by source
    by_source = _db_query("""
        SELECT source, COUNT(*) as cnt
        FROM news_articles WHERE created_at > NOW() - INTERVAL '7 days'
        GROUP BY source ORDER BY cnt DESC LIMIT 10
    """) or []

    # Social volume trends
    social_trend = _db_query("""
        SELECT observed_at::date as day, SUM(mention_count) as total_mentions,
               AVG(sentiment_score)::numeric(3,2) as avg_sentiment
        FROM social_sentiment_history
        WHERE observed_at > NOW() - INTERVAL '7 days'
        GROUP BY observed_at::date ORDER BY day
    """) or []

    # Top SEC filings
    sec_filings = _db_query("""
        SELECT symbol, filer_name, transaction_type, total_value, filing_date
        FROM sec_form4
        WHERE filing_date > NOW() - INTERVAL '7 days'
        ORDER BY total_value DESC NULLS LAST LIMIT 10
    """) or []

    return {
        "period": "7 days",
        "news_sentiment": [{k: _json_clean(v) for k, v in r.items()} for r in sentiment_dist],
        "top_mentioned_symbols": [{k: _json_clean(v) for k, v in r.items()} for r in top_symbols],
        "news_by_source": [{k: _json_clean(v) for k, v in r.items()} for r in by_source],
        "social_trend": [{k: _json_clean(v) for k, v in r.items()} for r in social_trend],
        "sec_insider_activity": [{k: _json_clean(v) for k, v in r.items()} for r in sec_filings],
        "total_articles": sum(r.get("cnt", 0) for r in by_source),
    }


# ── Live Trading Gate Validation ──────────────────────────────────────────

def _live_trading_gate():
    """GET /api/v2/live-trading-gate — Progress toward live trading authorization.

    Requirements: 55% win rate, 1.3 profit factor, 6-month paper validation,
    30+ closed trades minimum sample size.
    """
    REQUIRED_WIN_RATE = 0.55
    REQUIRED_PROFIT_FACTOR = 1.3
    REQUIRED_MONTHS = 6
    REQUIRED_SAMPLE = 30

    # Paper trade stats
    stats = _db_query("""
        SELECT COUNT(*) as total,
               COUNT(*) FILTER (WHERE status='closed') as closed,
               COUNT(*) FILTER (WHERE status='closed' AND pnl > 0) as wins,
               COUNT(*) FILTER (WHERE status='closed' AND pnl <= 0) as losses,
               COALESCE(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 0) as gp,
               COALESCE(SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END), 0) as gl,
               MIN(created_at) as first_trade,
               MAX(close_date) as last_close
        FROM paper_trades
    """, fetch="one") or {}

    closed = stats.get("closed", 0) or 0
    wins = stats.get("wins", 0) or 0
    losses = stats.get("losses", 0) or 0
    gp = float(stats.get("gp", 0) or 0)
    gl = float(stats.get("gl", 0) or 0)
    win_rate = round(wins / max(closed, 1), 3)
    profit_factor = round(gp / max(gl, 0.01), 3)

    # Time in paper mode
    first_trade = stats.get("first_trade")
    months_active = 0
    if first_trade:
        try:
            from datetime import datetime as _dt
            ft = _dt.fromisoformat(str(first_trade).replace("+00:00", "+00:00"))
            months_active = round((datetime.now(timezone.utc) - ft.astimezone(timezone.utc)).days / 30, 1)
        except Exception:
            pass

    # Gate checks
    gates = [
        {
            "gate": "win_rate",
            "label": f"Win Rate >= {REQUIRED_WIN_RATE*100:.0f}%",
            "required": REQUIRED_WIN_RATE,
            "current": win_rate,
            "passed": win_rate >= REQUIRED_WIN_RATE and closed >= REQUIRED_SAMPLE,
            "detail": f"{win_rate*100:.1f}% ({wins}W / {losses}L)",
        },
        {
            "gate": "profit_factor",
            "label": f"Profit Factor >= {REQUIRED_PROFIT_FACTOR}",
            "required": REQUIRED_PROFIT_FACTOR,
            "current": profit_factor,
            "passed": profit_factor >= REQUIRED_PROFIT_FACTOR and closed >= REQUIRED_SAMPLE,
            "detail": f"{profit_factor:.2f} (${gp:,.0f} gross profit / ${gl:,.0f} gross loss)",
        },
        {
            "gate": "sample_size",
            "label": f"Minimum {REQUIRED_SAMPLE} Closed Trades",
            "required": REQUIRED_SAMPLE,
            "current": closed,
            "passed": closed >= REQUIRED_SAMPLE,
            "detail": f"{closed} closed ({stats.get('total', 0)} total)",
        },
        {
            "gate": "time_in_paper",
            "label": f"Minimum {REQUIRED_MONTHS} Months Paper Trading",
            "required": REQUIRED_MONTHS,
            "current": months_active,
            "passed": months_active >= REQUIRED_MONTHS,
            "detail": f"{months_active} months" + (f" (started {str(first_trade)[:10]})" if first_trade else ""),
        },
    ]

    all_passed = all(g["passed"] for g in gates)

    # Projections
    daily_rate = closed / max(months_active * 30, 1) if months_active else 0
    trades_needed = max(0, REQUIRED_SAMPLE - closed)
    days_to_sample = round(trades_needed / max(daily_rate, 0.1))
    months_remaining = max(0, REQUIRED_MONTHS - months_active)

    return {
        "status": "AUTHORIZED" if all_passed else "PAPER_ONLY",
        "all_gates_passed": all_passed,
        "gates": gates,
        "summary": {
            "closed_trades": closed,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "months_active": months_active,
            "gross_profit": gp,
            "gross_loss": gl,
        },
        "projections": {
            "daily_trade_rate": round(daily_rate, 2),
            "trades_to_sample_gate": trades_needed,
            "est_days_to_sample": days_to_sample,
            "months_to_time_gate": round(months_remaining, 1),
        },
        "ha_risks": [
            {"risk": "Single server deployment", "impact": "Total system outage if server fails", "mitigation": "7-day rolling pg_dump backups, documented restore guide"},
            {"risk": "No API authentication", "impact": "Unauthorized access if network exposed", "mitigation": "Auth layer added (API_AUTH_TOKEN in .env), internal-only network"},
            {"risk": "Single Ollama instance", "impact": "LLM enrichment stops if GPU fails", "mitigation": "Cloud fallback chain (xAI → Anthropic → OpenAI)"},
            {"risk": "Anthropic API credits depleted", "impact": "Rebalance advisor, cloud fallback unavailable", "mitigation": "Local LLM covers most use cases, alert fires on depletion"},
            {"risk": "Finviz cookie expiry", "impact": "Screener returns 0 results", "mitigation": "Dual auth (cookie + API token), health check alerts"},
        ],
        "performance_budget": {
            "api_response_p95_ms": 500,
            "pipeline_completion_window": "07:00 - 08:00 ET (morning cascade)",
            "llm_enrichment_budget": "120s total (5 sections)",
            "screener_full_run": "10:00 AM + 4:00 PM weekdays",
            "overnight_batch": "8:00 PM - 10:00 PM",
        },
    }


# ── Feedback loop dashboard ───────────────────────────────────────────────

def _feedback_dashboard():
    """GET /api/v2/feedback-dashboard — Feedback loop closure metrics."""
    # Proposal outcome chain
    chain_stats = _db_query("""
        SELECT chain_status, COUNT(*) as cnt
        FROM proposal_outcome_chain GROUP BY chain_status
    """) or []

    # Alert effectiveness
    alert_eff = _db_query("""
        SELECT notification_type,
               COUNT(*) as total,
               COUNT(*) FILTER (WHERE action_taken = true) as acted_on,
               AVG(effectiveness_score)::numeric(3,2) as avg_score
        FROM alert_effectiveness
        WHERE alert_date > CURRENT_DATE - 30
        GROUP BY notification_type ORDER BY total DESC
    """) or []

    # Agent sample tracking
    agent_samples = _db_query("""
        SELECT DISTINCT ON (agent_name)
               agent_name, resolved, correct, wrong, sample_tier,
               accuracy_pct, days_to_next_tier, snapshot_date
        FROM agent_sample_tracking
        ORDER BY agent_name, snapshot_date DESC
    """) or []

    # Strategy snapshots (latest)
    strat_snaps = _db_query("""
        SELECT strategy_id, trades_closed, wins, losses, win_rate,
               profit_factor, recommendation, snapshot_date
        FROM strategy_performance_snapshots
        WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM strategy_performance_snapshots)
        ORDER BY trades_closed DESC
    """) or []

    # Recovery outcomes
    recovery_outcomes = _db_query("""
        SELECT symbol, final_verdict, patience_correct, days_monitored, reentry_pnl
        FROM recovery_outcome_log ORDER BY resolved_at DESC LIMIT 10
    """) or []

    # CIO response rate
    cio_responses = _db_query("""
        SELECT response, COUNT(*) as cnt
        FROM cio_decision_responses GROUP BY response
    """) or []

    return {
        "proposal_chain": [{k: _json_clean(v) for k, v in r.items()} for r in chain_stats],
        "alert_effectiveness": [{k: _json_clean(v) for k, v in r.items()} for r in alert_eff],
        "agent_samples": [{k: _json_clean(v) for k, v in r.items()} for r in agent_samples],
        "strategy_snapshots": [{k: _json_clean(v) for k, v in r.items()} for r in strat_snaps],
        "recovery_outcomes": [{k: _json_clean(v) for k, v in r.items()} for r in recovery_outcomes],
        "cio_response_rate": [{k: _json_clean(v) for k, v in r.items()} for r in cio_responses],
    }


# ── Global alerts: persistent banner data ─────────────────────────────────

def _global_alerts():
    """GET /api/v2/global-alerts — Critical conditions for persistent banner.

    Returns alerts sorted by severity. Frontend displays as a banner
    across all pages until conditions resolve.
    """
    rm = _load_json(STATE_DIR / "risk_management.json") or {}
    freshness = _load_json(STATE_DIR / "_freshness.json") or {}

    alerts = []
    heat = rm.get("portfolio_heat_pct", 0)
    no_stop = sum(1 for p in rm.get("positions", []) if p.get("status") == "NO STOP")
    triggered = [p.get("symbol", "?") for p in rm.get("positions", []) if p.get("status") == "TRIGGERED"]

    if triggered:
        alerts.append({
            "severity": "critical",
            "message": f"{len(triggered)} stop(s) triggered: {', '.join(triggered[:5])}",
            "action": "Review at /v2/recovery",
        })
    if heat > 5:
        alerts.append({
            "severity": "warning",
            "message": f"Portfolio heat {heat:.1f}% — above 5% threshold",
            "action": "Reduce exposure or add stops",
        })
    if no_stop > 5:
        alerts.append({
            "severity": "warning",
            "message": f"{no_stop} positions without stop losses",
            "action": "Set stops at /v2/portfolio",
        })

    # Data freshness
    completed = freshness.get("completed_at", "")
    if completed:
        try:
            from datetime import datetime as _dt
            age_h = (datetime.now() - _dt.fromisoformat(completed)).total_seconds() / 3600
            if age_h > 6:
                alerts.append({
                    "severity": "info",
                    "message": f"Data is {age_h:.0f}h old",
                    "action": "Pipeline may need attention",
                })
        except Exception:
            pass

    # Stale rebalance
    try:
        yo = _load_json(STATE_DIR / "yaml_advisor_output.json") or {}
        gen = yo.get("generated_at", "")
        if gen:
            from datetime import datetime as _dt2
            days = (datetime.now() - _dt2.fromisoformat(str(gen).replace("Z", "+00:00")).replace(tzinfo=None)).days
            if days > 14:
                alerts.append({
                    "severity": "info",
                    "message": f"Rebalance data is {days} days old",
                    "action": "Refresh requires API credits",
                })
    except Exception:
        pass

    return {
        "alerts": alerts,
        "count": len(alerts),
        "has_critical": any(a["severity"] == "critical" for a in alerts),
        "freshness": {
            "last_refresh": freshness.get("completed_at"),
            "status": freshness.get("status", "unknown"),
        },
    }


# ── Deep Overnight LLM Queue endpoints ─────────────────────────────────────

def _queue_summary():
    from datetime import datetime, timedelta
    rows = _db_query("SELECT status, count(*) as cnt FROM deep_overnight_llm_queue GROUP BY status") or []
    by_status = {r["status"]: r["cnt"] for r in rows}
    tier_rows = _db_query("SELECT priority_tier, count(*) as cnt FROM deep_overnight_llm_queue WHERE status='pending' GROUP BY priority_tier") or []
    tier_map = {r["priority_tier"]: r["cnt"] for r in tier_rows}
    done_today = (_db_query("SELECT count(*) as cnt FROM deep_overnight_llm_queue WHERE status='done' AND completed_at > NOW() - INTERVAL '24 hours'", fetch="one") or {}).get("cnt", 0)
    pending = by_status.get("pending", 0)
    cap = 100
    now = datetime.now()
    window_start = now.replace(hour=23, minute=0, second=0, microsecond=0)
    if now.hour >= 23:
        window_start += timedelta(days=1)
    next_hrs = max(0, (window_start - now).total_seconds() / 3600) if now.hour >= 3 else 0
    will_run = min(pending, cap)
    return {
        "pending": pending, "done_today": done_today, "failed": by_status.get("failed", 0),
        "running": by_status.get("running", 0), "cap_tonight": cap,
        "window_start": "23:00", "window_end": "03:00",
        "next_window_in_hours": round(next_hrs, 1),
        "estimated_completion_nights": round(pending / cap, 1) if cap else 0,
        "by_status": [{"status": s, "count": c} for s, c in by_status.items()],
        "job_budget": {
            "cap": cap, "pending_p0": tier_map.get("P0", 0), "pending_p1": tier_map.get("P1", 0),
            "pending_p2": tier_map.get("P2", 0), "pending_p3": tier_map.get("P3", 0),
            "pending_p4": tier_map.get("P4", 0),
            "will_run_tonight": will_run, "wont_run_tonight": max(0, pending - cap),
        },
    }


def _queue_pending():
    rows = _db_query("""
        SELECT id, job_type, symbol, priority_tier, priority_score, reason_codes,
               queued_at, attempt_count, source_table, source_id,
               EXTRACT(EPOCH FROM (NOW() - queued_at))/3600 as age_hours
        FROM deep_overnight_llm_queue WHERE status = 'pending'
        ORDER BY priority_score DESC, queued_at ASC LIMIT 300
    """) or []
    cap = 100
    jobs = []
    for i, r in enumerate(rows):
        d = {k: _json_clean(v) for k, v in r.items()}
        d["will_run_tonight"] = i < cap
        d["age_hours"] = round(float(d.get("age_hours") or 0), 1)
        jobs.append(d)
    return {"jobs": jobs, "total": len(jobs)}


def _queue_completed():
    rows = _db_query("""
        SELECT q.id, q.job_type, q.symbol, q.priority_tier, q.priority_score,
               q.completed_at, q.last_gemma_runtime_sec as duration_seconds, q.last_error,
               r.summary, r.curation_verdict, r.curation_weight,
               r.risk_narrative, r.reentry_verdict, r.cc_verdict
        FROM deep_overnight_llm_queue q
        LEFT JOIN deep_overnight_llm_results r ON r.queue_id = q.id
        WHERE q.status = 'done' AND q.completed_at > NOW() - INTERVAL '24 hours'
        ORDER BY q.completed_at DESC LIMIT 200
    """) or []
    jobs = [{**{k: _json_clean(v) for k, v in r.items()}, "had_error": bool(r.get("last_error"))} for r in rows]
    durs = [float(r.get("duration_seconds") or 0) for r in rows if r.get("duration_seconds")]
    return {
        "jobs": jobs, "total": len(jobs),
        "stats": {
            "total_ran": len(jobs),
            "avg_duration": round(sum(durs) / len(durs), 1) if durs else 0,
            "fastest": round(min(durs), 1) if durs else 0,
            "slowest": round(max(durs), 1) if durs else 0,
            "error_count": sum(1 for r in rows if r.get("last_error")),
        },
    }


def _queue_failed():
    rows = _db_query("""
        SELECT id, job_type, symbol, priority_tier, priority_score,
               attempt_count, last_error, started_at, completed_at, queued_at
        FROM deep_overnight_llm_queue
        WHERE status IN ('failed', 'error') OR (attempt_count > 1 AND status = 'pending')
        ORDER BY queued_at DESC LIMIT 100
    """) or []
    return {"jobs": [{k: _json_clean(v) for k, v in r.items()} for r in rows], "total": len(rows)}


def _ops_cron_health():
    rows = _db_query("""
        SELECT ps.script_name as name, COALESCE(ps.display_name, ps.script_name) as display_name,
               ps.expected_hour, ps.expected_min, ps.run_days as schedule, ps.critical
        FROM pipeline_schedule ps WHERE ps.active = true ORDER BY ps.expected_hour, ps.expected_min
    """) or []
    crons = []
    for r in rows:
        d = {k: _json_clean(v) for k, v in r.items()}
        # Schedule info + expected time display
        eh = d.get('expected_hour', 0)
        em = d.get('expected_min', 0)
        d['expected_time'] = f"{eh:02d}:{em:02d}"
        d['status'] = 'critical' if d.get('critical') else 'scheduled'
        d['runs_today'] = None  # individual run tracking not yet instrumented
        crons.append(d)
    return {"crons": crons}


def _ops_llm_audit():
    import json as _json
    audit_path = PROJECT_ROOT / "logs" / "llm_routing_audit.jsonl"
    if not audit_path.exists():
        return {"entries": [], "total": 0, "note": "llm_routing_audit.jsonl not found"}
    entries = []
    try:
        lines = audit_path.read_text().strip().split("\n")
        for line in lines[-100:]:
            try:
                e = _json.loads(line)
                entries.append({
                    "timestamp": e.get("timestamp", ""), "caller": e.get("caller", ""),
                    "process_type": e.get("process_type", ""),
                    "model": e.get("model", e.get("model_used", "")),
                    "latency_ms": e.get("latency_ms", e.get("elapsed_ms", 0)),
                    "status": e.get("status", "ok"),
                    "fallback_triggered": e.get("fallback_triggered", False),
                    "tokens": e.get("tokens", e.get("eval_count", 0)),
                })
            except Exception:
                continue
    except Exception:
        pass
    entries.reverse()
    return {"entries": entries, "total": len(entries)}


def _queue_calibration():
    rows = _db_query("""
        SELECT job_type, total_graded, correct, partial, wrong, pending,
               accuracy_pct, tracking_since
        FROM gemma3_accuracy_by_job_type
    """) or []
    if not rows:
        return {"accuracy": [], "note": "Calibration data accumulates as trades close. Check back after first paper trade closes."}
    return {
        "accuracy": [{k: _json_clean(v) for k, v in r.items()} for r in rows],
        "total_events": sum(r.get("total_graded", 0) for r in rows),
    }


def _journal_integrity_warnings():
    """Check paper_trades data integrity. Returns list of warning strings."""
    warnings = []
    try:
        r1 = _db_query("SELECT COUNT(*) as cnt FROM paper_trades WHERE lifecycle_state='open' AND filled_at IS NULL AND broker_status NOT IN ('filled')", fetch="one")
        if r1 and r1.get('cnt', 0) > 0:
            warnings.append(f"{r1['cnt']} open trade(s) never confirmed filled")
        r2 = _db_query("SELECT COUNT(*) as cnt FROM paper_trades WHERE lifecycle_state='closed' AND outcome_verdict IS NULL AND pnl IS NOT NULL", fetch="one")
        if r2 and r2.get('cnt', 0) > 0:
            warnings.append(f"{r2['cnt']} closed trade(s) missing outcome verdict")
        r3 = _db_query("SELECT symbol, COUNT(*) as cnt FROM paper_trades WHERE lifecycle_state='open' GROUP BY symbol HAVING COUNT(*)>1") or []
        for r in r3:
            warnings.append(f"{r['symbol']} has {r['cnt']} open records — possible duplicate")
    except Exception:
        pass
    return warnings


def _strategy_intelligence():
    """GET /api/v2/strategy-intelligence — health dashboard for all 20 strategies."""
    import yaml, glob
    strategies = []
    yaml_dir = PROJECT_ROOT / "config" / "strategies"
    for f in sorted(glob.glob(str(yaml_dir / "*.yaml"))):
        if 'schema' in f or 'shared' in f or 'recommendation' in f:
            continue
        try:
            with open(f) as fh:
                y = yaml.safe_load(fh) or {}
            sid = y.get('strategy_id', '')
            if not sid:
                continue
            # Get governance data
            gov = _db_query("SELECT governance_state, paper_trades, closed_trades, win_rate, profit_factor, expectancy_r, avg_r FROM paper_performance_governance WHERE strategy_id=%s ORDER BY created_at DESC LIMIT 1", [sid], fetch="one") or {}
            # Get proposal/trade counts
            prop_count = (_db_query("SELECT count(*) as n FROM paper_trade_proposals WHERE strategy_id=%s AND status='PENDING'", [sid], fetch="one") or {}).get('n', 0)
            trade_count = gov.get('closed_trades') or 0
            strategies.append({
                'strategy_id': sid,
                'display_name': y.get('display_name', sid.replace('_', ' ').title()),
                'governance_state': gov.get('governance_state', 'UNVALIDATED'),
                'trade_count': trade_count,
                'win_rate': float(gov['win_rate']) if gov.get('win_rate') else None,
                'profit_factor': float(gov['profit_factor']) if gov.get('profit_factor') else None,
                'avg_r': float(gov['avg_r']) if gov.get('avg_r') else None,
                'expectancy': float(gov['expectancy_r']) if gov.get('expectancy_r') else None,
                'trades_to_validation': max(0, 30 - (trade_count or 0)),
                'active_proposals': prop_count,
                'yaml_version': y.get('version', '?'),
                'has_entry_criteria': len(y.get('entry_criteria', [])) >= 4,
                'has_auto_disqualifiers': len(y.get('auto_disqualifiers', [])) >= 3,
                'has_agent_responsibilities': bool(y.get('agent_responsibilities')),
                'has_vix_rules': bool(y.get('vix_rules')),
                'has_technical_indicators': bool(y.get('technical_indicators_required')),
                'co_enables': y.get('co_enables', []),
                'performance_verdict': 'PERFORMING' if gov.get('profit_factor') and float(gov['profit_factor']) >= 1.3 else 'UNDERPERFORMING' if gov.get('profit_factor') and float(gov['profit_factor']) < 0.8 else 'ACCUMULATING' if trade_count else 'NO_DATA',
            })
        except Exception:
            continue

    unvalidated = sum(1 for s in strategies if s['governance_state'] == 'UNVALIDATED')
    with_proposals = sum(1 for s in strategies if s['active_proposals'] > 0)
    return {
        'strategies': strategies,
        'summary': {
            'total_strategies': len(strategies),
            'unvalidated': unvalidated,
            'with_proposals': with_proposals,
            'without_proposals': len(strategies) - with_proposals,
            'total_closed_trades': sum(s['trade_count'] or 0 for s in strategies),
        },
    }


# ── Route dispatch ─────────────────────────────────────────────────────────

ROUTES = {
    "/api/v2/overview": overview,
    "/api/v2/portfolio/holdings": portfolio_holdings,
    "/api/v2/portfolio/performance": portfolio_performance,
    "/api/v2/watchlist": watchlist_combined,
    "/api/v2/notifications/recent": notifications_recent,
    "/api/v2/ops/audit": lambda: _ops_audit(),
    "/api/v2/aegis/findings": lambda: _aegis_findings(),
    "/api/v2/aegis/nightly-deltas": lambda: _aegis_nightly_deltas(),
    "/api/v2/aegis/social-sentiment": lambda: _aegis_social_sentiment(),
    "/api/v2/aegis/transcript-intel": lambda: _aegis_transcript_intel(),
    "/api/v2/aegis/discovery": lambda: _aegis_discovery(),
    "/api/v2/aegis/briefs": lambda: _aegis_briefs(),
    "/api/v2/aegis/covered-calls": lambda: _aegis_covered_calls(),
    "/api/v2/aegis/rotation-alternatives": lambda: _aegis_rotations(),
    "/api/v2/aegis/steph-escalations": lambda: _aegis_steph_escalations(),
    "/api/v2/aegis/steph-review-queue": lambda: _aegis_steph_review_queue(),
    "/api/v2/aegis/chat-context": lambda: _aegis_chat_context(),
    "/api/v2/aegis/improvements": lambda: _aegis_improvements(),
    "/api/v2/aegis/evidence": lambda: _aegis_evidence(),
    "/api/v2/john/decisions": lambda: _john_decisions(),
    "/api/v2/watchlist/summary": _wl_summary,
    "/api/v2/watchlist/jobs": _wl_jobs,
    "/api/v2/watchlist/results": _wl_results,
    "/api/v2/watchlist/debug": _wl_debug,
    "/api/v2/alerts/debug": _alerts_debug,
    "/api/v2/signals/fused": lambda: {"signals": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT * FROM fused_signals ORDER BY created_at DESC LIMIT 50") or [])]},
    "/api/v2/agent-performance": lambda: {"history": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT * FROM agent_performance_history ORDER BY created_at DESC LIMIT 50") or [])]},
    "/api/v2/llm/health": lambda: _llm_health(),
    "/api/v2/system-health": lambda: _system_health_dashboard(),
    "/api/v2/cost-dashboard": lambda: _cost_dashboard(),
    "/api/v2/llm-spend": lambda: _llm_spend(),
    "/api/v2/youtube-audit": lambda: _youtube_audit(),
    "/api/v2/transcript-audit": lambda: _transcript_audit(),
    "/api/v2/portfolio-intelligence": lambda: _portfolio_intelligence(),
    "/api/v2/rewrite-note/status": lambda: _rewrite_status(),
    "/api/v2/iris/status": lambda: _iris_status(),
    "/api/v2/iris/hygiene-status": lambda: _iris_hygiene_status(),
    "/api/v2/iris/library-status": lambda: _iris_library_status(),
    "/api/v2/intelligence-entities": lambda: _intelligence_entities(),
    "/api/v2/agent-calibration": lambda: _agent_calibration(),
    "/api/v2/pipeline-health": lambda: _pipeline_health(),
    "/api/v2/pipeline-run-health": lambda: _pipeline_run_health(),
    "/api/v2/auto-proposal-diagnostics": lambda: _auto_proposal_diagnostics(),
    "/api/v2/iris/stale-symbols": lambda: _iris_stale_symbols(),
    "/api/v2/iris/content-gaps": lambda: _iris_content_gaps(),
    "/api/v2/iris/duplicates": lambda: _iris_duplicates(),
    "/api/v2/iris/failures": lambda: _iris_failures(),
    "/api/v2/iris/integrity": lambda: _iris_integrity(),
    "/api/v2/proposals-with-pnl": lambda: _proposals_with_pnl(),
    "/api/v2/alex-hygiene/history": lambda: {"runs": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT id, decision_type, tier, question, agreement_score, elapsed_seconds, bypass_event, ran_at, LEFT(synthesis,500) as synthesis_preview FROM alex_hygiene_log ORDER BY ran_at DESC LIMIT 10") or [])]},
    "/api/v2/agent-pipeline": lambda: _agent_pipeline(),
    "/api/v2/intelligence-whiteboard": lambda: _intelligence_whiteboard(),
    "/api/v2/tax-situation": lambda: _tax_situation(),
    "/api/v2/trust-transfers": lambda: {"transfers": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT id, event_date, amount, description, trust_type, five_year_lookback_start, protected_amount, trust_notes, created_at FROM tax_events WHERE event_type='trust_transfer' ORDER BY event_date DESC") or [])]},
    "/api/v2/sec/form4": lambda: {"filings": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT id, symbol, filer_name, filer_relation, transaction_type, shares, price, total_value, filing_date, sec_url, quality_score, strategy_tags, agent_tags, created_at FROM sec_form4 ORDER BY filing_date DESC LIMIT 50") or [])]},
    "/api/v2/proposals": lambda: {"proposals": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT id, symbol, action, strategy_type, reason, account_name, shares_to_sell, target_symbol, confidence, status, ssdi_impact, income_impact, irmaa_risk, review_date, created_at FROM watchlist_proposals ORDER BY CASE status WHEN 'proposed' THEN 1 WHEN 'approved' THEN 2 ELSE 3 END, created_at DESC LIMIT 30") or [])]},
    "/api/v2/proposals/feedback": lambda: {"feedback": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT id, proposal_id, symbol, action, strategy_type, account_name, decision, reviewer, reason, ssdi_impact, irmaa_risk, confidence_at_decision, confidence_adjustment, created_at FROM agent_feedback_log ORDER BY created_at DESC LIMIT 30") or [])], "stats": (_db_query("SELECT decision, count(*) as cnt FROM agent_feedback_log GROUP BY decision") or [])},
    "/api/v2/proposals/history": lambda: {"daily": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT d::date as date, COALESCE(SUM(CASE WHEN wp.status='approved' THEN 1 ELSE 0 END),0) as approved, COALESCE(SUM(CASE WHEN wp.status='rejected' THEN 1 ELSE 0 END),0) as rejected, COALESCE(SUM(CASE WHEN wp.status='proposed' THEN 1 ELSE 0 END),0) as proposed FROM generate_series(NOW()-INTERVAL '30 days', NOW(), '1 day') d LEFT JOIN watchlist_proposals wp ON wp.reviewed_at::date = d::date OR (wp.status='proposed' AND wp.created_at::date = d::date) GROUP BY d::date ORDER BY d::date") or [])]},
    "/api/v2/macro-context": lambda: {"context": __import__('importlib').import_module('external_market_data_ingest').get_macro_context()},
    "/api/v2/qualified-intelligence": lambda: {"items": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT id, source_type, symbol, title, quality_score, retirement_relevance, strategy_focus, discovered_at FROM qualified_intelligence ORDER BY quality_score DESC, discovered_at DESC LIMIT 30") or [])]},
    "/api/v2/discovery-log": lambda: {"entries": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT id, discovery_type, title, summary, symbols_mentioned, intel_count, created_at FROM agent_discovery_log ORDER BY created_at DESC LIMIT 10") or [])]},
    "/api/v2/trade-instructions": lambda: {"instructions": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT id, proposal_id, symbol, action, account_name, shares, target_symbol, estimated_tax_impact, ssdi_note, irmaa_note, execution_type, status, instruction_text, created_at, executed_at FROM trade_instructions ORDER BY CASE status WHEN 'pending' THEN 1 WHEN 'executed' THEN 2 ELSE 3 END, created_at DESC LIMIT 20") or [])]},
    "/api/v2/agent-health": lambda: _agent_health(),
    "/api/v2/agent-detail": lambda: _agent_detail(),
    "/api/v2/search-sources": lambda: _search_sources_status(),
    "/api/v2/autonomy-progress": lambda: _autonomy_progress(),
    "/api/v2/sec/form4/symbol": lambda: {"error": "Use /api/v2/sec/form4?symbol=V"},
    "/api/v2/research-topics": lambda: {"topics": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT * FROM user_research_topics WHERE status='active' ORDER BY priority DESC, updated_at DESC") or [])]},
    "/api/v2/finviz-screeners": lambda: {"screeners": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT * FROM finviz_screeners WHERE active=TRUE ORDER BY screener_id") or [])]},
    "/api/v2/intelligence-sources": lambda: {"sources": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT screener_id, display_name, strategy_type, finviz_url, description, keywords, sources, added_by, schedule, active, last_run, results_count, created_at, updated_at FROM finviz_screeners ORDER BY strategy_type, screener_id") or [])]},
    "/api/v2/youtube/transcripts": lambda: _youtube_transcripts(),
    "/api/v2/youtube/channels": lambda: {"channels": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT * FROM youtube_channels WHERE active=TRUE ORDER BY channel_name") or [])]},
    "/api/v2/news/articles": lambda: _news_articles_list(),
    "/api/v2/rag/status": lambda: _rag_status(),
    "/api/v2/intelligence/library": lambda: _intelligence_library(),
    "/api/v2/youtube/channel-lookup": lambda: _youtube_channel_lookup(),
    "/api/v2/social/posts": lambda: {"posts": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT id, platform, post_id, username, display_name, text, post_date, url, followers, verified, likes, retweets, replies, quality_score, relevance_score, validation_status, matched_keywords, sentiment, sentiment_score, added_by, ingested_at, strategy_tags, agent_tags FROM social_posts ORDER BY quality_score DESC, ingested_at DESC LIMIT 100") or [])]},
    "/api/v2/social/status": lambda: _social_api_status(),
    "/api/v2/cio-decisions": lambda: _cio_decisions_enriched(),
    "/api/v2/cio-dashboard": lambda: _cio_dashboard(),
    "/api/v2/cio": lambda: _cio_unified(),
    "/api/v2/recovery": lambda: _recovery_dashboard(),
    "/api/v2/portfolio-monitor": lambda: _portfolio_monitor(),
    "/api/v2/reports": lambda: _reports_hub(),
    "/api/v2/command": lambda: _morning_command(),
    "/api/v2/global-alerts": lambda: _global_alerts(),
    "/api/v2/feedback-dashboard": lambda: _feedback_dashboard(),
    "/api/v2/live-trading-gate": lambda: _live_trading_gate(),
    "/api/v2/portfolio/intelligence-feed": lambda: _holdings_intelligence(),
    "/api/v2/market-intelligence": lambda: _market_intelligence_summary(),
    "/api/v2/strategy-rotations": lambda: {"rotations": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT * FROM strategy_rotation_recommendations ORDER BY created_at DESC LIMIT 20") or [])]},
    "/api/v2/rebalance-plans": lambda: {"plans": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT * FROM rebalance_plans ORDER BY generated_at DESC LIMIT 10") or [])]},
    "/api/v2/rebalance-plans/latest": lambda: _rebalance_latest(),
    "/api/v2/marl/simulations": lambda: {"simulations": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT * FROM marl_simulation_runs ORDER BY started_at DESC LIMIT 10") or [])]},
    "/api/v2/marl/shadow-diagnostics": lambda: _marl_diagnostics(),
    "/api/v2/portfolio-signal-qa": lambda: {"clusters": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT * FROM signal_clusters ORDER BY created_at DESC LIMIT 20") or [])], "latest_events": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT * FROM portfolio_intelligence_events WHERE event_type IN ('signal_cluster','portfolio_qa','fused_signal') ORDER BY created_at DESC LIMIT 20") or [])]},
    "/api/v2/portfolio-level-qa/latest": lambda: {"qa": {k: _json_clean(v) for k, v in r.items()} if (r := _db_query("SELECT * FROM portfolio_level_qa_history ORDER BY evaluated_at DESC LIMIT 1", fetch="one")) else None},
    "/api/v2/intelligence-events": lambda: {"events": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT * FROM portfolio_intelligence_events ORDER BY created_at DESC LIMIT 50") or [])]},
    "/api/v2/classifications": lambda: {"count": len(_db_query("SELECT * FROM ticker_strategy_classifications WHERE active=TRUE") or []), "classifications": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT symbol, strategy_type, asset_type, classification_source, confidence, review_required FROM ticker_strategy_classifications WHERE active=TRUE ORDER BY strategy_type, symbol") or [])]},
    "/api/v2/classifications/suggestions": lambda: {"suggestions": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT * FROM agent_classification_suggestions ORDER BY created_at DESC LIMIT 50") or [])]},
    "/api/v2/strategy-rules": lambda: _strategy_rules_list(),
    "/api/v2/income-dashboard": lambda: _income_dashboard(),
    "/api/v2/tasks": lambda: _tasks_unified(),
    "/api/v2/tasks/pending": lambda: _tasks_pending(),
    "/api/v2/tasks/history": lambda: _tasks_history(),
    "/api/v2/aegis/outcomes": lambda: _aegis_outcomes(),
    "/api/v2/ops/last-import": lambda: _last_import(),
    "/api/v2/orchestration": lambda: _orchestration(),
    "/api/v2/approvals/pending": approvals_pending,
    "/api/v2/approvals/history": approvals_history,
    "/api/v2/approvals/states": approvals_all_states,
    "/api/v2/stopped-out-watch": stopped_out_watch_list,
    "/api/v2/stop-confirmations": lambda: _stop_confirmations_list(),
    "/api/v2/ops/summary": ops_summary,
    "/api/v2/trade-ai": trade_ai,
    "/api/v2/trade-ai/critique": _tradeai_critique_status,
    "/api/v2/trade-ai/history": _tradeai_history,
    "/api/v2/forecast": lambda: _forecast(),
    "/api/v2/dividends": dividends,
    "/api/v2/retirement": retirement,
    "/api/v2/ai-analyst": ai_analyst,
    "/api/v2/ai-reports": lambda: {"reports": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT id, report_type, title, content, provider, cost, generated_at FROM ai_reports ORDER BY generated_at DESC LIMIT 20") or [])]},
    "/api/v2/alex/recent": lambda: _alex_recent(),
    "/api/v2/alex/roth-history": lambda: {"analyses": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT id, payload, created_at FROM portfolio_intelligence_events WHERE event_type='roth_conversion_analysis' ORDER BY created_at DESC LIMIT 5") or [])]},
    "/api/v2/agents/summary": lambda: _agents_summary(),
    "/api/v2/system/metrics-history": lambda: {"metrics": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT * FROM daily_system_metrics ORDER BY metric_date DESC LIMIT 30") or [])]},
    "/api/v2/agents/performance-history": lambda: {"history": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT * FROM agent_performance_history ORDER BY created_at DESC LIMIT 20") or [])]},
    "/api/v2/attribution": attribution,
    "/api/v2/journal": journal,
    "/api/v2/journal/unannotated": _journal_unannotated,
    "/api/v2/journal/previously-traded": _journal_previously_traded,
    "/api/v2/journal/backtest-summary": _journal_backtest_summary,
    "/api/v2/journal/backtest-analytics": _journal_backtest_analytics,
    "/api/v2/journal/analytics": journal_analytics,
    "/api/v2/journal/report": _journal_report,
    "/api/v2/journal/agent-coaching": _journal_agent_coaching,
    "/api/v2/risk": risk,
    "/api/v2/tax-lots": tax_lots,
    "/api/v2/correlation": correlation,
    "/api/v2/rebalance": rebalance,
    "/api/v2/scalp/live": lambda: _scalp_live_poll(),
    "/api/v2/strategy-desk": lambda: _strategy_desk(),
    "/api/v2/open-trade-monitor": lambda: _open_trade_monitor_api(),
    "/api/v2/paper-trade-analysis": lambda: _paper_trade_analysis_api(),
    "/api/v2/agent-curation-events": lambda: _agent_curation_events_api(),
    "/api/v2/local-llm-status": lambda: _local_llm_status_api(),
    "/api/v2/strategy-registry": lambda: _strategy_registry_api(),
    "/api/v2/system-controls": lambda: _system_controls_api(),
    "/api/v2/incubator": lambda: _incubator_api(),
    "/api/v2/incubator-events": lambda: _incubator_events_api(),
    "/api/v2/incubator-health": lambda: _incubator_health_api(),
    "/api/v2/proposal-quality-review": lambda: _proposal_quality_review_api(),
    "/api/v2/queue/summary": lambda: _queue_summary(),
    "/api/v2/queue/pending": lambda: _queue_pending(),
    "/api/v2/queue/completed": lambda: _queue_completed(),
    "/api/v2/queue/failed": lambda: _queue_failed(),
    "/api/v2/ops/cron-health": lambda: _ops_cron_health(),
    "/api/v2/ops/llm-audit": lambda: _ops_llm_audit(),
    "/api/v2/queue/calibration": lambda: _queue_calibration(),
    "/api/v2/strategy-intelligence": lambda: _strategy_intelligence(),
}


def handle(path: str, method: str = "GET", body: dict = None, query: dict = None):
    """Dispatch a v2 API path. Returns (status, dict) or None if not a v2 route."""
    # Strip query string from path if present
    base_path = path.split("?")[0] if "?" in path else path

    # POST routes
    if method == "POST":
        if base_path == "/api/v2/journal/agent-coaching/run":
            try:
                import subprocess as _sp
                _sp.Popen(
                    [str(PROJECT_ROOT / ".venv/bin/python"), str(PROJECT_ROOT / "scripts/journal_agent_coach.py")],
                    cwd=str(PROJECT_ROOT), stdout=open(str(PROJECT_ROOT / "logs/agent_coach.log"), "w"),
                    stderr=_sp.STDOUT
                )
                return 200, {"ok": True, "data": {"status": "started"}}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/journal/review":
            try:
                return journal_review_write(body or {})
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/journal/bulk-suggest":
            try:
                return 200, {"ok": True, "data": _journal_bulk_suggest()}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/journal/reminder":
            try:
                return 200, {"ok": True, "data": _journal_reminder()}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/alex-hygiene/classify":
            try:
                from alex_hygiene import classify_decision, check_cadence
                dt = body.get("decision_type", "")
                q = body.get("question", "")
                ctx = body.get("context", {})
                cl = classify_decision(dt, q, ctx)
                cd = check_cadence(dt)
                return 200, {"ok": True, "data": {"classification": cl, "cadence": {
                    "allowed": cd["allowed"], "reason": cd["reason"],
                    "days_until_allowed": cd.get("days_until_allowed", 0)}}}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/alex-hygiene/run":
            try:
                from alex_hygiene import run_tier3_hygiene, check_cadence
                dt = body.get("decision_type", "quarterly_strategy_review")
                q = body.get("question", "")
                ctx = body.get("context", {})
                bypass = body.get("bypass_event")
                if not q:
                    return 400, {"ok": False, "error": "question required"}
                if not body.get("force"):
                    cd = check_cadence(dt, bypass)
                    if not cd["allowed"]:
                        return 429, {"ok": False, "blocked": True, "reason": cd["reason"],
                                     "days_until_allowed": cd.get("days_until_allowed", 0)}
                r = run_tier3_hygiene(q, body.get("alex_opinion", ""), ctx, dt, bypass)
                return 200, {"ok": True, "data": {k: _json_clean(v) if not isinstance(v, dict) else v for k, v in r.items()}}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/iris/ask":
            try:
                q = (body or {}).get("question", "").strip()
                if not q:
                    return 400, {"ok": False, "error": "question required"}
                from iris_taxonomy_agent import ask_iris
                answer = ask_iris(q)
                return 200, {"ok": True, "data": {"answer": answer, "question": q}}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/iris/approve":
            try:
                pid = (body or {}).get("proposal_id")
                if not pid:
                    return 400, {"ok": False, "error": "proposal_id required"}
                _db_write("UPDATE iris_taxonomy_proposals SET status='approved', reviewed_by='dashboard', reviewed_at=NOW() WHERE id=%s AND status='pending'", (pid,))
                from iris_taxonomy_agent import apply_proposal
                r = apply_proposal(int(pid))
                return 200, {"ok": True, "data": r}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/admin/rag-backfill":
            try:
                import subprocess, threading
                def _run():
                    subprocess.run([str(PROJECT_ROOT / ".venv/bin/python"),
                                    str(PROJECT_ROOT / "scripts/rag_indexer.py"), "--backfill", "--source", "all"],
                                   capture_output=True, cwd=str(PROJECT_ROOT), timeout=7200)
                threading.Thread(target=_run, daemon=True).start()
                return 200, {"ok": True, "message": "RAG backfill started in background"}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/admin/backfill-news-strategy":
            try:
                from _news_strategy_classifier import classify_and_update_all
                updated = classify_and_update_all()
                # Also fix defense_thesis in qualified_intelligence
                _db_write("UPDATE qualified_intelligence SET strategy_focus='investment_general' WHERE strategy_focus='defense_thesis'")
                _db_write("UPDATE news_articles SET strategy_type='investment_general' WHERE strategy_type='defense_thesis'")
                return 200, {"ok": True, "updated": updated}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/admin/fix-channel-name-mismatches":
            try:
                fixes = [
                    ("Joe F. Schmitz Jr. CFP\u00ae CKA\u00ae", "Joe F. Schmitz Jr. CFP"),
                    ("ppcian", "PPC Ian"),
                    ("Felix & Friends (Goat Academy)", "Felix and Friends"),
                    ("Trader Talks: Schwab Coaching Webcasts", "Trader Talks Schwab"),
                    ("Etienne Crete - Desire To TRADE", "Desire To TRADE"),
                    ("Value Investing with Sven Carlin, Ph.D.", "Sven Carlin"),
                ]
                total = 0
                for old, new in fixes:
                    r = _db_write("UPDATE youtube_transcripts SET channel_name = %s WHERE channel_name = %s", (new, old))
                    if r:
                        cnt = _db_query(f"SELECT count(*) as n FROM youtube_transcripts WHERE channel_name = %s", (new,), fetch="one")
                        total += (cnt or {}).get("n", 0)
                return 200, {"ok": True, "rows_updated": total, "fixes_applied": len(fixes)}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/admin/flag-orphan-transcripts":
            try:
                orphans = _db_query("""
                    SELECT DISTINCT yt.channel_name FROM youtube_transcripts yt
                    LEFT JOIN youtube_channels yc ON yc.channel_name = yt.channel_name
                    WHERE yc.channel_name IS NULL AND COALESCE(yt.validation_status,'') != 'orphan'
                """) or []
                ch_names = [r["channel_name"] for r in orphans]
                if ch_names:
                    _db_write("""
                        UPDATE youtube_transcripts yt SET validation_status = 'orphan'
                        WHERE NOT EXISTS (SELECT 1 FROM youtube_channels yc WHERE yc.channel_name = yt.channel_name)
                          AND COALESCE(yt.validation_status,'') != 'orphan'
                    """)
                cnt = _db_query("SELECT count(*) as n FROM youtube_transcripts WHERE validation_status='orphan'", fetch="one")
                return 200, {"ok": True, "rows_flagged": (cnt or {}).get("n", 0), "channels": ch_names}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/iris/hygiene-flag":
            try:
                b = body or {}
                ch_name = b.get("channel_name", "").strip()
                reason = b.get("reason", "").strip()
                if not ch_name or not reason:
                    return 400, {"ok": False, "error": "channel_name and reason required"}
                # Get channel numeric id
                ch = _db_query("SELECT id FROM youtube_channels WHERE channel_name=%s LIMIT 1", (ch_name,), fetch="one")
                ch_id = ch["id"] if ch else 0
                _db_write("""INSERT INTO iris_hygiene_pending
                    (content_type, content_id, content_title, proposed_action, reason, evidence,
                     confidence, status, expires_at)
                    VALUES ('youtube_channel', %s, %s, 'review', %s, %s, 0.5, 'pending_john',
                            NOW() + INTERVAL '30 days')""",
                    (ch_id, ch_name, reason,
                     json.dumps({"category": b.get("category", ""), "avg_quality": b.get("avg_quality", 0),
                                 "threshold": b.get("threshold", 0), "flagged_by": "user_manual"})))
                return 200, {"ok": True, "message": f"Channel '{ch_name}' flagged for Iris review",
                             "next_review": "Sunday 6 AM hygiene run"}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/iris/hygiene-approve":
            try:
                pid = (body or {}).get("pending_id")
                if not pid:
                    return 400, {"ok": False, "error": "pending_id required"}
                from iris_taxonomy_agent import handle_iris_hygiene_command
                msg = handle_iris_hygiene_command("approve", str(pid))
                return 200, {"ok": True, "data": {"message": msg}}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/iris/hygiene-reject":
            try:
                pid = (body or {}).get("pending_id")
                if not pid:
                    return 400, {"ok": False, "error": "pending_id required"}
                from iris_taxonomy_agent import handle_iris_hygiene_command
                msg = handle_iris_hygiene_command("reject", str(pid))
                return 200, {"ok": True, "data": {"message": msg}}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/iris/hygiene-defer":
            try:
                pid = (body or {}).get("pending_id")
                if not pid:
                    return 400, {"ok": False, "error": "pending_id required"}
                from iris_taxonomy_agent import handle_iris_hygiene_command
                msg = handle_iris_hygiene_command("defer", str(pid))
                return 200, {"ok": True, "data": {"message": msg}}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/iris/reject":
            try:
                pid = (body or {}).get("proposal_id")
                if not pid:
                    return 400, {"ok": False, "error": "proposal_id required"}
                _db_write("UPDATE iris_taxonomy_proposals SET status='rejected', reviewed_by='dashboard', reviewed_at=NOW() WHERE id=%s AND status='pending'", (pid,))
                return 200, {"ok": True, "data": {"proposal_id": pid, "status": "rejected"}}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/approvals/decision":
            try:
                return approval_decide(body or {})
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/stopped-out-watch/escalate":
            try:
                return stopped_out_watch_escalate(body or {})
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/aegis/improvements/propose":
            try:
                b = body or {}
                if not b.get("title") or not b.get("proposed_change"):
                    return 400, {"ok": False, "error": "title and proposed_change required"}
                _db_write(
                    """INSERT INTO aegis_improvement_proposals (category, title, description, proposed_change, reasoning, confidence, provenance)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (b.get("category", "general"), b["title"], b.get("description", ""),
                     b["proposed_change"], b.get("reasoning", ""), b.get("confidence", 0.5),
                     json.dumps({"agent": "aegis", "source": "aegis:chat"}))
                )
                return 200, {"ok": True, "action": "proposed"}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/aegis/outcomes/evaluate":
            try:
                b = body or {}
                outcome_id = b.get("id")
                if not outcome_id:
                    return 400, {"ok": False, "error": "id required"}
                label = b.get("label", "")
                valid_labels = ("helpful","partially_helpful","too_early","too_late","noise","incorrect","unresolved","user_overrode","market_invalidated")
                if label not in valid_labels:
                    return 400, {"ok": False, "error": f"label must be: {', '.join(valid_labels)}"}
                _db_write(
                    """UPDATE aegis_outcome_tracking SET
                          status='evaluated', outcome_label=%s, outcome_score=%s,
                          timeliness=%s, usefulness=%s, reasoning=%s,
                          who_evaluated=%s, evaluated_at=NOW()
                       WHERE id=%s""",
                    (label, b.get("score"), b.get("timeliness", "n/a"), b.get("usefulness", "n/a"),
                     b.get("reasoning", ""), b.get("evaluator", "john"), outcome_id)
                )
                return 200, {"ok": True, "action": "evaluated", "id": outcome_id}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        # POST /api/v2/tasks/<id>/resolve|defer|reject
        import re as _re
        _task_action_m = _re.match(r"/api/v2/tasks/(\d+)/(resolve|defer|reject)$", base_path)
        if _task_action_m:
            try:
                tid = int(_task_action_m.group(1))
                action = _task_action_m.group(2)
                note = (body or {}).get("note", "").strip()
                status_map = {"resolve": "decided_action", "defer": "deferred", "reject": "rejected"}
                new_status = status_map[action]
                # Update john_decision_queue
                _db_write("UPDATE john_decision_queue SET status=%s, decided_at=NOW(), john_decision=%s, john_reasoning=%s, closure_note=%s WHERE id=%s",
                          (new_status, action, note, f"{action}: {note}" if note else action, tid))
                # Also try action_queue (may not exist for all tasks)
                try:
                    _db_write("UPDATE action_queue SET status=%s, reviewed_at=NOW(), reviewed_by='john' WHERE id=%s AND status='pending'",
                              (new_status if action != "resolve" else "approved", tid))
                except Exception:
                    pass
                # Log decision
                try:
                    _db_write("INSERT INTO john_decision_history (decision_id, old_status, new_status, decision, reasoning) VALUES (%s,'pending_john',%s,%s,%s)",
                              (tid, new_status, action, note))
                except Exception:
                    pass
                return 200, {"ok": True, "id": tid, "status": new_status}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/tasks/deduplicate":
            try:
                deduped = 0
                dupes = _db_query("""
                    SELECT symbol, category, array_agg(id ORDER BY id DESC) as ids
                    FROM john_decision_queue WHERE status='pending_john'
                    GROUP BY symbol, category HAVING count(*) > 1""") or []
                for d in dupes:
                    ids = d["ids"]
                    keep_id = ids[0]  # most recent
                    old_ids = ids[1:]
                    for oid in old_ids:
                        _db_write("UPDATE john_decision_queue SET status='closed', decided_at=NOW(), closure_note='Superseded by newer task' WHERE id=%s", (oid,))
                        deduped += 1
                # Also dedup action_queue STOP_REVIEW entries (ONLY pending rows)
                aq_dupes = _db_query("""
                    SELECT action, array_agg(id ORDER BY id DESC) as ids
                    FROM action_queue WHERE status='pending' AND action='STOP_REVIEW'
                    GROUP BY action HAVING count(*) > 1""") or []
                for d in aq_dupes:
                    ids = d["ids"]
                    for oid in ids[1:]:
                        _db_write("UPDATE action_queue SET status='resolved', reviewed_at=NOW(), reviewed_by='auto_dedup' WHERE id=%s AND status='pending'", (oid,))
                        deduped += 1
                return 200, {"ok": True, "resolved_count": deduped}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/john/decide":
            try:
                return _john_decide(body or {})
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/watchlist/submit":
            try:
                return _wl_submit(body or {})
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        # POST /api/v2/watchlist/<SYMBOL>/requeue — re-queue analysis for LLM failures
        if base_path.startswith("/api/v2/watchlist/") and base_path.endswith("/requeue"):
            sym = base_path[len("/api/v2/watchlist/"):-len("/requeue")].strip("/").upper()
            if sym:
                try:
                    queued = 0
                    for agent in ['maria_research', 'steph_allocation', 'risk_agent']:
                        _db_query(
                            """INSERT INTO watchlist_agent_jobs
                                (symbol, requested_agent, task_type, priority, status, submitted_from)
                               VALUES (%s, %s, 'requeue_llm_error', 'high', 'pending', 'watchlist_requeue')
                               ON CONFLICT DO NOTHING""",
                            (sym, agent), fetch="none"
                        )
                        queued += 1
                    return 200, {"ok": True, "symbol": sym, "queued": queued}
                except Exception as e:
                    return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/rewrite-note":
            try:
                text = (body or {}).get("text", "").strip()
                if not text or len(text) < 5:
                    return 400, {"ok": False, "error": "text too short"}
                page_type = (body or {}).get("page_type", "approval")
                PROMPTS = {"approval": "Rewrite this investment decision rationale clearly. Under 50 words.",
                           "watchlist": "Rewrite this watchlist note concisely. Under 40 words.",
                           "research": "Expand this into a research question. Under 60 words.",
                           "retirement": "Expand this retirement question. Under 60 words."}
                prompt_text = PROMPTS.get(page_type, PROMPTS["approval"])
                provider = "local"
                # Try local LLM first
                rewritten = ""
                try:
                    from local_llm import generate
                    rewritten = (generate(f"{prompt_text}\n\nOriginal: {text}\n\nRewritten (concise, clear):", timeout=30, fast=True) or "").strip()
                except Exception:
                    pass
                # Fallback to Claude Haiku if local failed
                if not rewritten:
                    try:
                        import anthropic
                        _ak = ""
                        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
                            if line.startswith("ANTHROPIC_API_KEY="): _ak = line.split("=", 1)[1].strip()
                        client = anthropic.Anthropic(api_key=_ak)
                        msg = client.messages.create(model="claude-haiku-4-5", max_tokens=150,
                            messages=[{"role": "user", "content": f"{prompt_text}\n\nOriginal: {text}\n\nRewritten:"}])
                        rewritten = msg.content[0].text.strip()
                        provider = "claude-haiku"
                    except Exception as e2:
                        return 200, {"ok": False, "error": f"Both local LLM and Claude failed: {e2}"}
                return 200, {"ok": True, "rewritten": rewritten, "provider": provider}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/retirement/refresh":
            try:
                import subprocess, threading
                def _run():
                    subprocess.run([str(PROJECT_ROOT / ".venv/bin/python"),
                                    str(PROJECT_ROOT / "scripts/alex_retirement_advisor.py"),
                                    "--weekly-health", "--telegram"], capture_output=True,
                                   cwd=str(PROJECT_ROOT))
                threading.Thread(target=_run, daemon=True).start()
                return 200, {"ok": True, "message": "Retirement refresh started (~60s)"}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/ai-ask":
            try:
                return ai_ask(body or {})
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/aegis/steph-resolve":
            try:
                return _steph_resolve(body or {})
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/aegis/improvements/approve":
            try:
                b = body or {}
                proposal_id = b.get("id")
                approver = b.get("approver", "john")
                if not proposal_id:
                    return 400, {"ok": False, "error": "id required"}
                _db_write(
                    "UPDATE aegis_improvement_proposals SET status=%s, approved_by=%s, approved_at=NOW() WHERE id=%s",
                    (f"{approver}_approved", approver, proposal_id)
                )
                return 200, {"ok": True, "action": "approved", "id": proposal_id}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/intelligence-sources":
            try:
                b = body or {}
                sid = b.get("screener_id", "").strip()
                if not sid:
                    return 400, {"ok": False, "error": "screener_id required"}
                # Upsert
                _db_write(
                    """INSERT INTO finviz_screeners (screener_id, display_name, strategy_type, finviz_url, description, keywords, sources, added_by, schedule, active, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                       ON CONFLICT (screener_id) DO UPDATE SET
                         display_name=EXCLUDED.display_name, strategy_type=EXCLUDED.strategy_type,
                         finviz_url=EXCLUDED.finviz_url, description=EXCLUDED.description,
                         keywords=EXCLUDED.keywords, sources=EXCLUDED.sources,
                         added_by=EXCLUDED.added_by, schedule=EXCLUDED.schedule,
                         active=EXCLUDED.active, updated_at=NOW()""",
                    (sid, b.get("display_name", sid), b.get("strategy_type", ""),
                     b.get("finviz_url", ""), b.get("description", ""),
                     b.get("keywords", ""), json.dumps(b.get("sources", [])),
                     b.get("added_by", "user"), b.get("schedule", "daily"),
                     b.get("active", True))
                )
                return 200, {"ok": True, "action": "upserted", "screener_id": sid}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/youtube/ingest-all":
            try:
                import subprocess
                log_path = str(PROJECT_ROOT / "logs" / "youtube_ingest_manual.log")
                subprocess.Popen(
                    [str(PROJECT_ROOT / ".venv/bin/python"),
                     str(PROJECT_ROOT / "scripts/youtube_transcript_ingest.py"), "--all-channels"],
                    cwd=str(PROJECT_ROOT),
                    stdout=open(log_path, "a"), stderr=subprocess.STDOUT
                )
                ch_count = _db_query("SELECT count(*) as n FROM youtube_channels WHERE active=true", fetch="one")
                n = (ch_count or {}).get("n", 0)
                return 200, {"ok": True, "message": f"Ingest queued for {n} channels", "log": log_path}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/youtube/ingest":
            try:
                b = body or {}
                url = b.get("url", "").strip()
                if not url:
                    return 400, {"ok": False, "error": "url required"}
                import re as _re
                # Detect channel URLs vs video URLs
                ch_match = _re.match(r'https?://(?:www\.)?youtube\.com/(?:channel/|@|c/|user/)([^/?&]+)', url)
                if ch_match:
                    ch_id = ch_match.group(1)
                    # Look up channel in DB
                    ch = _db_query("SELECT channel_name, channel_id FROM youtube_channels WHERE channel_id=%s OR channel_url LIKE %s OR channel_name ILIKE %s LIMIT 1",
                                   (ch_id, f"%{ch_id}%", f"%{ch_id}%"), fetch="one")
                    if not ch:
                        return 400, {"ok": False, "error": f"Channel '{ch_id}' not tracked. Add it first with the + Channel button."}
                    # Trigger ingest for this channel
                    import subprocess, threading
                    def _ingest():
                        subprocess.run([str(PROJECT_ROOT / ".venv/bin/python"),
                                        str(PROJECT_ROOT / "scripts/youtube_transcript_ingest.py"),
                                        "--channel", ch["channel_name"]], capture_output=True, timeout=120,
                                       cwd=str(PROJECT_ROOT))
                    threading.Thread(target=_ingest, daemon=True).start()
                    return 200, {"ok": True, "channel": ch["channel_name"], "channel_id": ch["channel_id"], "queued": True,
                                 "message": f"Ingesting latest videos from {ch['channel_name']}..."}
                # Video URL — existing logic
                import sys as _sys
                _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
                from youtube_transcript_ingest import ingest_video
                result = ingest_video(url, added_by=b.get("added_by", "user"))
                if result.get("error"):
                    return 400, {"ok": False, "error": result["error"]}
                return 200, {"ok": True, **result}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/youtube/channels/add" or base_path == "/api/v2/youtube/add-channel":
            try:
                b = body or {}
                name = b.get("channel_name", "").strip()
                if not name:
                    return 400, {"ok": False, "error": "channel_name required"}
                cid = b.get("channel_id", "").strip() or name.lower().replace(" ", "_").replace("-", "_")
                category = b.get("category", "investment_general")
                priority = b.get("priority", "medium")
                agent_tags = b.get("agent_tags", ["maria", "steph"])
                threshold = int(b.get("auto_promote_threshold", b.get("promote_threshold", 70)))
                _db_write(
                    """INSERT INTO youtube_channels
                       (channel_id, channel_name, channel_url, category, priority,
                        agent_tags, auto_promote_threshold, strategy_focus, active, added_by)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true, %s)
                       ON CONFLICT (channel_id) DO UPDATE SET
                         channel_name=EXCLUDED.channel_name, channel_url=EXCLUDED.channel_url,
                         category=EXCLUDED.category, priority=EXCLUDED.priority,
                         agent_tags=EXCLUDED.agent_tags, auto_promote_threshold=EXCLUDED.auto_promote_threshold""",
                    (cid, name, b.get("channel_url", ""), category, priority,
                     agent_tags, threshold, b.get("strategy_focus", category),
                     b.get("added_by", "user"))
                )
                return 200, {"ok": True, "action": "upserted", "channel_id": cid, "channel_name": name}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/social/ingest":
            try:
                b = body or {}
                text = b.get("text", "").strip()
                if not text:
                    return 400, {"ok": False, "error": "text required"}
                import sys as _sys, hashlib
                _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
                from social_monitor import store_post
                post_id = b.get("post_id") or hashlib.sha256(f"{text}:{b.get('username','')}".encode()).hexdigest()[:16]
                result = store_post(
                    platform=b.get("platform", "x"), post_id=post_id,
                    text=text, username=b.get("username", ""),
                    display_name=b.get("display_name", ""),
                    url=b.get("url", ""), followers=b.get("followers", 0),
                    verified=b.get("verified", False),
                    likes=b.get("likes", 0), retweets=b.get("retweets", 0),
                    replies=b.get("replies", 0), added_by=b.get("added_by", "user"),
                )
                return 200, {"ok": True, **result}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/trust-transfers":
            try:
                b = body or {}
                amount = b.get("amount", 0)
                if not amount:
                    return 400, {"ok": False, "error": "amount required"}
                event_date = b.get("event_date", __import__("datetime").datetime.now().strftime("%Y-%m-%d"))
                trust_type = b.get("trust_type", "MAPT")
                lookback_start = b.get("five_year_lookback_start", event_date)
                _db_write(
                    """INSERT INTO tax_events (event_date, event_type, amount, description, tax_year,
                        trust_type, five_year_lookback_start, protected_amount, trust_notes)
                       VALUES (%s, 'trust_transfer', %s, %s, %s, %s, %s, %s, %s)""",
                    (event_date, amount, b.get("description", f"{trust_type} transfer ${amount:,.0f}"),
                     int(event_date[:4]), trust_type, lookback_start, amount,
                     b.get("notes", ""))
                )
                return 200, {"ok": True, "action": "trust_transfer_recorded", "amount": amount, "trust_type": trust_type}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/proposals/decide":
            try:
                b = body or {}
                pid = b.get("id")
                decision = b.get("decision", "")  # approved / rejected
                if not pid or decision not in ("approved", "rejected"):
                    return 400, {"ok": False, "error": "id and decision (approved/rejected) required"}
                reviewer = b.get("reviewer", "john")
                reason = b.get("reason", "")
                _db_write("UPDATE watchlist_proposals SET status=%s, reviewed_by=%s, reviewed_at=NOW() WHERE id=%s",
                          (decision, reviewer, pid))
                # Record in feedback log for learning loop
                prop = _db_query("SELECT symbol, action, strategy_type, account_name, confidence, ssdi_impact, irmaa_risk FROM watchlist_proposals WHERE id=%s", (pid,))
                if prop:
                    p = prop[0]
                    conf_adj = 0.05 if decision == "approved" else -0.05
                    _db_write("""INSERT INTO agent_feedback_log
                        (proposal_id, symbol, action, strategy_type, account_name, decision, reviewer, reason,
                         ssdi_impact, irmaa_risk, confidence_at_decision, confidence_adjustment)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (pid, p.get("symbol"), p.get("action"), p.get("strategy_type"),
                         p.get("account_name"), decision, reviewer, reason,
                         p.get("ssdi_impact"), p.get("irmaa_risk"), p.get("confidence"), conf_adj))
                # Generate trade instruction on approval
                if decision == "approved" and prop:
                    p = prop[0]
                    full = _db_query("SELECT symbol, account_name, shares_to_sell, target_symbol, ssdi_impact, irmaa_risk, confidence, reason FROM watchlist_proposals WHERE id=%s", (pid,))
                    if full:
                        fp = full[0]
                        shares = float(fp.get("shares_to_sell") or 0)
                        ssdi = fp.get("ssdi_impact", "none")
                        irmaa = fp.get("irmaa_risk", False)
                        ssdi_note = "No SSDI impact" if ssdi == "none" else f"SSDI impact: {ssdi}"
                        irmaa_note = "IRMAA risk: YES — review with CPA" if irmaa else "No IRMAA risk"
                        est_tax = shares * 300 * 0.22 if ssdi != "none" else 0  # rough estimate
                        instr = (f"SELL {shares:.0f} shares of {fp.get('symbol')} in {fp.get('account_name', '?')}. "
                                 f"Target: {fp.get('target_symbol', 'cash')}. "
                                 f"{ssdi_note}. {irmaa_note}. "
                                 f"Reason: {(fp.get('reason') or '')[:200]}")
                        _db_write("""INSERT INTO trade_instructions
                            (proposal_id, symbol, action, account_name, shares, target_symbol,
                             estimated_tax_impact, ssdi_note, irmaa_note, execution_type, status, instruction_text)
                            VALUES (%s,%s,'sell',%s,%s,%s,%s,%s,%s,'manual','pending',%s)""",
                            (pid, fp.get("symbol"), fp.get("account_name"), shares,
                             fp.get("target_symbol", "cash"), est_tax, ssdi_note, irmaa_note, instr))
                return 200, {"ok": True, "action": decision, "id": pid}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/intelligence-sources/delete":
            try:
                b = body or {}
                sid = b.get("screener_id", "").strip()
                if not sid:
                    return 400, {"ok": False, "error": "screener_id required"}
                _db_write("UPDATE finviz_screeners SET active=FALSE, updated_at=NOW() WHERE screener_id=%s", (sid,))
                return 200, {"ok": True, "action": "deactivated", "screener_id": sid}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/stop-confirmations/respond":
            try:
                return stop_confirmation_respond(body or {})
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if base_path == "/api/v2/stopped-out-watch/verdict":
            try:
                return stopped_out_watch_update_verdict(body or {})
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        # Escalate symbol to Alex from watchlist panel
        if base_path.startswith("/api/v2/watchlist/") and base_path.endswith("/escalate-alex"):
            sym = base_path.replace("/api/v2/watchlist/", "").replace("/escalate-alex", "").strip("/").upper()
            if not sym:
                return 400, {"ok": False, "error": "symbol required"}
            try:
                b = body or {}
                import uuid as _uuid
                _db_write("""INSERT INTO watchlist_agent_jobs
                    (id, symbol, requested_agent, request_type, priority, status,
                     submitted_from, payload, created_at)
                    VALUES (%s, %s, 'alex', 'user_escalation', 1, 'queued',
                            'watchlist_panel', %s, NOW())""",
                    (str(_uuid.uuid4()), sym, json.dumps({
                        "reason": b.get("reason", "user_interest"),
                        "note": b.get("note", ""),
                        "source": "watchlist_panel"
                    })))
                try:
                    import sys as _sys2
                    _sys2.path.insert(0, str(PROJECT_ROOT / "scripts"))
                    from telegram_alert import send_telegram
                    send_telegram(f"\u2b50 *{sym}* escalated to Alex from watchlist\nReason: {b.get('note', 'User flagged as interesting')}")
                except Exception:
                    pass
                return 200, {"ok": True, "symbol": sym, "queued": True}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        # Trigger manual debate for a symbol
        if base_path == "/api/v2/debates/trigger":
            try:
                b = body or {}
                sym = (b.get("symbol") or "").upper()
                if not sym:
                    return 400, {"ok": False, "error": "symbol required"}
                _db_write("""INSERT INTO agent_debate_log
                    (symbol, trigger_source, status, created_at)
                    VALUES (%s, 'manual_watchlist', 'pending', NOW())""",
                    (sym,))
                return 200, {"ok": True, "symbol": sym, "status": "pending"}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/trade-ai/run":
            try:
                import subprocess as _sp
                _sp.Popen(
                    [str(PROJECT_ROOT / ".venv/bin/python"), str(PROJECT_ROOT / "scripts/continuous_runner.py"), "--test"],
                    cwd=str(PROJECT_ROOT), stdout=open(str(PROJECT_ROOT / "logs/tradeai_manual.log"), "w"),
                    stderr=_sp.STDOUT
                )
                return 200, {"ok": True, "data": {"status": "started", "mode": "live_cycle"}}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/trade-ai/critique/run":
            try:
                import subprocess as _sp
                _sp.Popen(
                    [str(PROJECT_ROOT / ".venv/bin/python"), str(PROJECT_ROOT / "scripts/trade_ai_orchestrator.py"),
                     "--run-label", "0900", "--date", __import__('datetime').datetime.now().strftime("%Y-%m-%d"),
                     "--skip-market-check", "--no-alerts"],
                    cwd=str(PROJECT_ROOT), stdout=open(str(PROJECT_ROOT / "logs/critic_manual.log"), "w"),
                    stderr=_sp.STDOUT
                )
                return 200, {"ok": True, "data": {"status": "started", "mode": "full_pipeline_with_critic"}}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if base_path == "/api/v2/indicators/batch":
            try:
                return _indicator_batch_handler(body or {})
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        # from-signal proposal creation
        if base_path == "/api/v2/paper-proposals/from-signal":
            try:
                body = body or {}
                signal_id = int(body.get('signal_id', 0))
                if not signal_id:
                    return 400, {"ok": False, "error": "signal_id required"}
                # Duplicate check
                dup = _db_query("""
                    SELECT id, status FROM paper_trade_proposals
                    WHERE source_signal_id = %s
                    AND status IN ('PENDING','APPROVED','MODIFIED','BROKER_SUBMITTED')
                    ORDER BY created_at DESC LIMIT 1
                """, [signal_id], fetch="one")
                if dup:
                    return 400, {"ok": False, "error": "Proposal already exists for this signal",
                                 "proposal_id": dup.get('id'), "status": dup.get('status')}
                sig = _db_query("SELECT * FROM strategy_signals WHERE id = %s", [signal_id], fetch="one")
                if not sig:
                    return 404, {"ok": False, "error": f"Signal {signal_id} not found"}
                symbol = sig.get('symbol')
                strategy_id = sig.get('strategy_id') or 'UNKNOWN'
                entry  = float(sig.get('entry_high') or sig.get('price') or 0)
                stop   = float(sig.get('stop_loss') or 0)
                target = float(sig.get('target_1') or 0)
                shares = int(sig.get('shares') or 0)
                if entry <= 0 or stop <= 0 or shares <= 0:
                    return 400, {"ok": False, "error": f"{symbol} missing trade plan (entry={entry:.2f} stop={stop:.2f} shares={shares})"}
                import sys as _sys
                _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
                from paper_trade_logger import create_manual_proposal
                result = create_manual_proposal(
                    symbol=symbol, shares=shares, entry=entry,
                    stop=stop, target=target, account='ALPACA_PAPER')
                pid = result.get('proposal_id')
                if result.get('success') and pid:
                    # Backfill strategy attribution
                    try:
                        from session13_db import get_conn as _get_s13_conn
                        _attr_conn = _get_s13_conn()
                        _attr_cur = _attr_conn.cursor()
                        _attr_cur.execute("""
                            UPDATE paper_trade_proposals
                            SET strategy_id = COALESCE(NULLIF(%s, ''), strategy_id),
                                setup_type = COALESCE(%s, setup_type),
                                source_signal_id = %s,
                                signal_grade = COALESCE(%s, signal_grade),
                                signal_score = COALESCE(%s::numeric, signal_score),
                                rvol = COALESCE(%s::numeric, rvol),
                                float_m = COALESCE(%s::numeric, float_m),
                                gap_pct = COALESCE(%s::numeric, gap_pct),
                                catalyst = COALESCE(%s, catalyst),
                                catalyst_verified = COALESCE(%s, catalyst_verified),
                                intel_readiness = COALESCE(%s::integer, intel_readiness)
                            WHERE id = %s
                        """, [strategy_id, sig.get('setup_type'), signal_id,
                              sig.get('signal_grade'), sig.get('signal_score'),
                              sig.get('rvol'), sig.get('float_m'), sig.get('gap_pct'),
                              sig.get('catalyst'), sig.get('catalyst_verified'),
                              sig.get('intel_readiness'), pid])
                        _attr_conn.commit()
                        _attr_conn.close()
                    except Exception as _attr_e:
                        print(f"  [from-signal] Attribution backfill failed: {_attr_e}")
                return (200 if result.get('success') else 400), {
                    "ok": result.get('success', False),
                    "proposal_id": pid,
                    "symbol": symbol,
                    "strategy_id": strategy_id,
                    "message": result.get('message', '')[:300],
                }
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        # Fall through to routes defined after POST block (paper-proposals/approve, etc.)

    # GET: journal review read (with query param)
    if base_path == "/api/v2/journal/review":
        trade_key = (query or {}).get("trade_key", "")
        if not trade_key:
            return 400, {"ok": False, "error": "trade_key query param required"}
        try:
            return 200, {"ok": True, "data": journal_review_read(trade_key)}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # GET: journal review by encoded key (path param)
    if base_path.startswith("/api/v2/journal/review/"):
        key_encoded = base_path[len("/api/v2/journal/review/"):].strip("/")
        if key_encoded:
            try:
                return 200, {"ok": True, "data": _journal_review_get(key_encoded)}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    # GET: entry signals for a trade (what intelligence existed at entry time)
    if base_path.startswith("/api/v2/journal/entry-signals/"):
        key_encoded = base_path[len("/api/v2/journal/entry-signals/"):].strip("/")
        if key_encoded:
            trade_key = key_encoded.replace("__", ":")
            try:
                parts = trade_key.split(":")
                sym = parts[0] if parts else ""
                entry_date = parts[2] if len(parts) > 2 else ""
                news = _db_query("""
                    SELECT title, published_at, sentiment, source
                    FROM news_articles WHERE symbol = %s AND created_at::date BETWEEN %s::date - 7 AND %s::date
                    ORDER BY created_at DESC LIMIT 10
                """, (sym, entry_date, entry_date)) or []
                agents = _db_query("""
                    SELECT agent, recommendation, confidence, summary, created_at
                    FROM watchlist_agent_results WHERE symbol = %s AND created_at::date <= %s::date
                    ORDER BY created_at DESC LIMIT 5
                """, (sym, entry_date)) or []
                return 200, {"ok": True, "data": {
                    "symbol": sym, "entry_date": entry_date,
                    "news_before_entry": [{k: (str(v) if hasattr(v, 'isoformat') else v) for k, v in n.items()} for n in news],
                    "agent_analyses": [{k: (str(v) if hasattr(v, 'isoformat') else float(v) if isinstance(v, Decimal) else v) for k, v in a.items()} for a in agents],
                    "signal_count": len(news) + len(agents),
                }}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    # GET: backtest for a specific trade
    if base_path.startswith("/api/v2/journal/backtest/"):
        key_encoded = base_path[len("/api/v2/journal/backtest/"):].strip("/")
        if key_encoded:
            trade_key = key_encoded.replace("__", ":")
            try:
                row = _db_query("SELECT * FROM trade_backtest_results WHERE trade_key = %s", (trade_key,), fetch="one")
                if not row:
                    return 404, {"ok": False, "error": "No backtest data"}
                return 200, {"ok": True, "data": {k: (float(v) if isinstance(v, Decimal) else str(v) if hasattr(v, 'isoformat') else v) for k, v in row.items()}}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    # Pass query params to lookup functions that need them
    _journal_report._query = query or {}
    if query:
        _youtube_channel_lookup._url = (query.get("url") or [""])[0] if isinstance(query.get("url"), list) else query.get("url", "")
        _youtube_transcripts._query = query
        _news_articles_list._query = query
        _intelligence_library._query = query
        _agent_pipeline._query = query

    # ── Queue management POST routes ──────────────────────────────────
    if method == "POST" and base_path == "/api/v2/queue/boost":
        try:
            job_id = (body or {}).get("job_id")
            boost = int((body or {}).get("boost_amount", 50))
            if not job_id:
                return 400, {"ok": False, "error": "job_id required"}
            result = _db_write("UPDATE deep_overnight_llm_queue SET priority_score = priority_score + %s, updated_at = NOW() WHERE id = %s AND status = 'pending' RETURNING id, priority_score", (boost, job_id))
            if result:
                return 200, {"ok": True, "data": {"new_score": result["priority_score"]}}
            return 404, {"ok": False, "error": "Job not found or not pending"}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/queue/cancel":
        try:
            job_id = (body or {}).get("job_id")
            if not job_id:
                return 400, {"ok": False, "error": "job_id required"}
            result = _db_write("UPDATE deep_overnight_llm_queue SET status = 'cancelled', updated_at = NOW() WHERE id = %s AND status = 'pending' RETURNING id", (job_id,))
            if result:
                return 200, {"ok": True, "data": {"cancelled": True}}
            return 404, {"ok": False, "error": "Job not found or not pending"}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/queue/retry":
        try:
            job_id = (body or {}).get("job_id")
            if not job_id:
                return 400, {"ok": False, "error": "job_id required"}
            result = _db_write("UPDATE deep_overnight_llm_queue SET status = 'pending', attempt_count = 0, last_error = NULL, updated_at = NOW() WHERE id = %s AND status IN ('failed', 'error') RETURNING id", (job_id,))
            if result:
                return 200, {"ok": True, "data": {"retried": True}}
            return 404, {"ok": False, "error": "Job not found or not in failed state"}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # Static routes
    handler = ROUTES.get(base_path)
    if handler:
        try:
            return 200, {"ok": True, "data": handler()}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # Per-symbol CIO decisions
    # Task detail (john_decision_queue items with P&L)
    if base_path.startswith("/api/v2/task-detail/"):
        tid_str = base_path[len("/api/v2/task-detail/"):].strip("/")
        if tid_str.isdigit():
            try:
                return 200, {"ok": True, "data": _task_detail(int(tid_str))}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    # Watchlist symbol context
    if base_path.startswith("/api/v2/watchlist/context/"):
        sym = base_path[len("/api/v2/watchlist/context/"):].strip("/").upper()
        if sym:
            try:
                return 200, {"ok": True, "data": _watchlist_context(sym)}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    # Proposal detail
    if base_path.startswith("/api/v2/proposal-detail/"):
        pid_str = base_path[len("/api/v2/proposal-detail/"):].strip("/")
        if pid_str.isdigit():
            try:
                return 200, {"ok": True, "data": _proposal_detail(int(pid_str))}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    if base_path.startswith("/api/v2/cio-decisions/"):
        symbol = base_path[len("/api/v2/cio-decisions/"):].strip("/").upper()
        if symbol:
            try:
                rows = _db_query("SELECT * FROM cio_decisions WHERE symbol=%s ORDER BY created_at DESC LIMIT 10", (symbol,)) or []
                return 200, {"ok": True, "data": {"symbol": symbol, "decisions": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    # Per-symbol signals, catalysts, news, outcomes
    for prefix, table, cols in [
        ("/api/v2/signals/fused/", "fused_signals", "*"),
        ("/api/v2/catalysts/", "catalyst_events", "*"),
        ("/api/v2/news/", "news_articles", "id, title, source, relevance_score, sentiment, published_at, created_at"),
        ("/api/v2/decision-outcomes/", "decision_outcomes", "*"),
    ]:
        if base_path.startswith(prefix):
            sym = base_path[len(prefix):].strip("/").upper()
            if sym:
                try:
                    rows = _db_query(f"SELECT {cols} FROM {table} WHERE symbol=%s ORDER BY created_at DESC LIMIT 20", (sym,)) or []
                    return 200, {"ok": True, "data": {"symbol": sym, "rows": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}}
                except Exception as e:
                    return 500, {"ok": False, "error": str(e)}

    # Per-symbol classification
    if base_path.startswith("/api/v2/classifications/") and not base_path.endswith("/suggestions"):
        symbol = base_path[len("/api/v2/classifications/"):].strip("/").upper()
        if symbol:
            try:
                row = _db_query("SELECT * FROM ticker_strategy_classifications WHERE symbol=%s", (symbol,), fetch="one")
                hist = _db_query("SELECT * FROM ticker_classification_history WHERE symbol=%s ORDER BY changed_at DESC LIMIT 10", (symbol,)) or []
                return 200, {"ok": True, "data": {
                    "classification": {k: _json_clean(v) for k, v in row.items()} if row else None,
                    "history": [{k: _json_clean(v) for k, v in r.items()} for r in hist],
                }}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    # Strategy rules per symbol
    if base_path.startswith("/api/v2/strategy-rules/"):
        symbol = base_path[len("/api/v2/strategy-rules/"):].strip("/").upper()
        if symbol:
            try:
                row = _db_query("SELECT * FROM strategy_rule_evaluations WHERE symbol=%s", (symbol,), fetch="one")
                reg = _db_query("SELECT * FROM strategy_registry WHERE strategy_type=(SELECT strategy_type FROM strategy_rule_evaluations WHERE symbol=%s)", (symbol,), fetch="one")
                return 200, {"ok": True, "data": {
                    "evaluation": {k: _json_clean(v) for k, v in row.items()} if row else None,
                    "config": {k: _json_clean(v) for k, v in reg.items()} if reg else None,
                }}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    # Alert events with query params
    if base_path == "/api/v2/alerts":
        try:
            return 200, {"ok": True, "data": _alerts(query or {})}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # Symbol timeline
    if base_path.startswith("/api/v2/symbol/") and base_path.endswith("/timeline"):
        symbol = base_path[len("/api/v2/symbol/"):].replace("/timeline", "").strip("/").upper()
        if not symbol:
            return 400, {"ok": False, "error": "symbol required"}
        try:
            return 200, {"ok": True, "data": _symbol_timeline(symbol)}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # Watchlist items with query params (source-level detail)
    if base_path == "/api/v2/watchlist/items":
        try:
            return 200, {"ok": True, "data": _wl_items(query or {})}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # Watchlist symbols — deduplicated (one row per symbol, default view)
    if base_path == "/api/v2/watchlist/symbols":
        try:
            return 200, {"ok": True, "data": _wl_symbols(query or {})}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # Dynamic: /api/v2/watchlist/research-card/{symbol}
    if base_path.startswith("/api/v2/watchlist/research-card/"):
        symbol = base_path[len("/api/v2/watchlist/research-card/"):].strip("/").upper()
        if not symbol:
            return 400, {"ok": False, "error": "symbol required"}
        try:
            return 200, {"ok": True, "data": _wl_research_card(symbol)}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # Dynamic: /api/v2/research/ticker/{symbol}
    if base_path.startswith("/api/v2/research/ticker/"):
        symbol = base_path[len("/api/v2/research/ticker/"):].strip("/").upper()
        if not symbol:
            return 400, {"ok": False, "error": "symbol required"}
        try:
            return 200, {"ok": True, "data": research_ticker(symbol)}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # /api/v2/reports/catalog delegates to existing handler
    if base_path == "/api/v2/reports/catalog":
        return None  # let existing handler take it

    if base_path == "/api/v2/weekly-report":
        try:
            # Last 7 days: agent results, proposals acted on, debates, feedback
            agent_activity = _db_query("""
                SELECT agent, COUNT(*) as analyses, AVG(confidence)::numeric(3,2) as avg_conf
                FROM watchlist_agent_results WHERE created_at > NOW() - INTERVAL '7 days'
                GROUP BY agent ORDER BY analyses DESC""") or []
            proposals_acted = _db_query("""
                SELECT id, symbol, action, status, reviewed_at
                FROM watchlist_proposals WHERE reviewed_at > NOW() - INTERVAL '7 days'
                ORDER BY reviewed_at DESC LIMIT 20""") or []
            debates = _db_query("""
                SELECT symbol, consensus_recommendation, consensus_score, trigger_source, created_at
                FROM agent_debate_log WHERE created_at > NOW() - INTERVAL '7 days'
                ORDER BY created_at DESC""") or []
            feedback = _db_query("""
                SELECT symbol, decision, reviewer, created_at
                FROM agent_feedback_log WHERE created_at > NOW() - INTERVAL '7 days'
                ORDER BY created_at DESC LIMIT 20""") or []
            social = _db_query("""
                SELECT platform, COUNT(*) as posts FROM social_posts
                WHERE ingested_at > NOW() - INTERVAL '7 days' GROUP BY platform""") or []
            tasks_resolved = _db_query("""
                SELECT symbol, john_decision, decided_at
                FROM john_decision_queue WHERE decided_at > NOW() - INTERVAL '7 days'
                ORDER BY decided_at DESC LIMIT 10""") or []
            return 200, {"ok": True, "data": {
                "period": "weekly",
                "generated_at": datetime.now().isoformat(),
                "agent_activity": [{k: _json_clean(v) for k, v in r.items()} for r in agent_activity],
                "proposals_acted": [{k: _json_clean(v) for k, v in r.items()} for r in proposals_acted],
                "debates": [{k: _json_clean(v) for k, v in r.items()} for r in debates],
                "feedback_entries": [{k: _json_clean(v) for k, v in r.items()} for r in feedback],
                "social_ingested": [{k: _json_clean(v) for k, v in r.items()} for r in social],
                "tasks_resolved": [{k: _json_clean(v) for k, v in r.items()} for r in tasks_resolved],
            }}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/monthly-report":
        try:
            agent_activity = _db_query("""
                SELECT agent, COUNT(*) as analyses, AVG(confidence)::numeric(3,2) as avg_conf
                FROM watchlist_agent_results WHERE created_at > NOW() - INTERVAL '30 days'
                GROUP BY agent ORDER BY analyses DESC""") or []
            proposals_summary = _db_query("""
                SELECT status, COUNT(*) as cnt FROM watchlist_proposals
                WHERE created_at > NOW() - INTERVAL '30 days' OR reviewed_at > NOW() - INTERVAL '30 days'
                GROUP BY status""") or []
            debates = _db_query("""
                SELECT symbol, consensus_recommendation, consensus_score, created_at
                FROM agent_debate_log WHERE created_at > NOW() - INTERVAL '30 days'
                ORDER BY created_at DESC""") or []
            feedback_summary = _db_query("""
                SELECT decision, COUNT(*) as cnt FROM agent_feedback_log
                WHERE created_at > NOW() - INTERVAL '30 days' GROUP BY decision""") or []
            social_summary = _db_query("""
                SELECT platform, COUNT(*) as posts FROM social_posts
                WHERE ingested_at > NOW() - INTERVAL '30 days' GROUP BY platform""") or []
            tasks_summary = _db_query("""
                SELECT status, COUNT(*) as cnt FROM john_decision_queue
                WHERE decided_at > NOW() - INTERVAL '30 days' OR (status='pending_john')
                GROUP BY status""") or []
            return 200, {"ok": True, "data": {
                "period": "monthly",
                "generated_at": datetime.now().isoformat(),
                "agent_activity": [{k: _json_clean(v) for k, v in r.items()} for r in agent_activity],
                "proposals_summary": [{k: _json_clean(v) for k, v in r.items()} for r in proposals_summary],
                "debates": [{k: _json_clean(v) for k, v in r.items()} for r in debates],
                "feedback_summary": [{k: _json_clean(v) for k, v in r.items()} for r in feedback_summary],
                "social_summary": [{k: _json_clean(v) for k, v in r.items()} for r in social_summary],
                "tasks_summary": [{k: _json_clean(v) for k, v in r.items()} for r in tasks_summary],
            }}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Autonomy Enhancement Endpoints (v7.7) ────────────────────────────

    # Outcome lessons — what agents have learned from past decisions
    if base_path == "/api/v2/outcome-lessons":
        try:
            lessons = _db_query("""
                SELECT changed_by, rule_key, config, updated_at
                FROM agent_intelligence_rules
                WHERE rule_type = 'outcome_lessons'
                ORDER BY updated_at DESC LIMIT 20""") or []
            return 200, {"ok": True, "data": {
                "lessons": [{k: _json_clean(v) for k, v in r.items()} for r in lessons],
                "count": len(lessons),
            }}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # Scalp stats — 30-day hit rate for the scalp pipeline
    if base_path == "/api/v2/scalp-stats":
        try:
            summary = _db_query("""
                SELECT count(*) as total,
                       count(*) FILTER (WHERE outcome_status LIKE 'profit%%') as wins,
                       count(*) FILTER (WHERE outcome_status LIKE 'loss%%') as losses,
                       count(*) FILTER (WHERE outcome_status = 'flat') as flat,
                       round(avg(pct_move_24h)::numeric, 2) as avg_move
                FROM scalp_decision_outcomes
                WHERE scored_at > NOW() - INTERVAL '30 days'""") or [{}]
            by_grade = _db_query("""
                SELECT grade, count(*) as cnt,
                       round(avg(pct_move_24h)::numeric, 2) as avg_move
                FROM scalp_decision_outcomes
                WHERE scored_at > NOW() - INTERVAL '30 days'
                GROUP BY grade ORDER BY grade""") or []
            return 200, {"ok": True, "data": {
                "summary": {k: _json_clean(v) for k, v in summary[0].items()} if summary else {},
                "by_grade": [{k: _json_clean(v) for k, v in r.items()} for r in by_grade],
            }}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # Active debates — unresolved agent disagreements
    if base_path == "/api/v2/debates/active":
        try:
            debates = _db_query("""
                SELECT symbol, consensus_recommendation, consensus_score,
                       trigger_source, created_at
                FROM agent_debate_log
                ORDER BY created_at DESC LIMIT 20""") or []
            return 200, {"ok": True, "data": {
                "debates": [{k: _json_clean(v) for k, v in r.items()} for r in debates],
                "count": len(debates),
            }}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # RAG context for a symbol — shows what agents see
    if base_path.startswith("/api/v2/rag/context/"):
        symbol = base_path[len("/api/v2/rag/context/"):].strip("/").upper()
        if not symbol:
            return 400, {"ok": False, "error": "symbol required"}
        try:
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from rag_retrieval import get_rag_context
            rag_items = get_rag_context(symbol, limit=7)
            return 200, {"ok": True, "data": {
                "symbol": symbol,
                "rag_items": [{k: _json_clean(v) for k, v in r.items()} for r in rag_items] if rag_items else [],
                "count": len(rag_items) if rag_items else 0,
            }}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Prospects ──────────────────────────────────────────────────────────
    if base_path == "/api/v2/prospects":
        if method == "GET":
            try:
                return _prospects_handler(query or {})
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/prospects/add-to-watchlist":
        if method == "POST":
            try:
                return _prospects_add_to_watchlist(body or {})
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    # ── Indicator Engine GET routes ───────────────────────────────────────
    if base_path == "/api/v2/indicators/confluence":
        try:
            return _indicator_confluence_handler(query or {})
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/indicators/history":
        try:
            return _indicator_history_handler(query or {})
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/indicators/levels":
        try:
            return _indicator_levels_handler(query or {})
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Session 11: Prop Desk Governance endpoints ────────────────────────

    if base_path == "/api/v2/risk-gate-log":
        try:
            sym_filter = (query or {}).get("symbol", [""])[0] if isinstance((query or {}).get("symbol"), list) else (query or {}).get("symbol", "")
            where = "WHERE symbol = %s" if sym_filter else ""
            params = [sym_filter] if sym_filter else []
            rows = _db_query(f"""
                SELECT id, symbol, strategy_id, mode, action_context,
                       result, approved, reason_codes, reason_text, created_at
                FROM risk_gate_results
                {where}
                ORDER BY created_at DESC LIMIT 100""", params) or []
            summary_rows = _db_query("""
                SELECT result, COUNT(*) as cnt FROM risk_gate_results
                WHERE created_at > NOW() - INTERVAL '24 hours'
                GROUP BY result""") or []
            summary = {r["result"]: r["cnt"] for r in summary_rows}
            return 200, {"ok": True,
                "summary": {
                    "approved": summary.get("APPROVED", 0),
                    "rejected": summary.get("REJECTED", 0),
                    "paper_only": summary.get("PAPER_ONLY", 0),
                    "risk_gate_error": summary.get("RISK_GATE_ERROR", 0),
                    "total": sum(summary.values()),
                },
                "decisions": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/paper-trades":
        try:
            rows = _db_query("""
                SELECT id, signal_id, strategy_id, symbol, account,
                       entry_price, entry_time, shares, dollar_size,
                       stop_loss, target_1, target_2, dollar_risk,
                       exit_price, exit_time, pnl, pnl_pct,
                       outcome_verdict, status, created_at
                FROM paper_trades
                ORDER BY created_at DESC LIMIT 100""") or []
            return 200, {"ok": True,
                "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows],
                "count": len(rows)}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/paper-trades/open":
        try:
            rows = _db_query("""
                SELECT id, strategy_id, symbol, account, entry_price, entry_time,
                       shares, dollar_size, stop_loss, target_1, dollar_risk,
                       current_price, unrealized_pnl, opened_via, created_at
                FROM paper_trades
                WHERE status = 'open'
                ORDER BY created_at DESC""") or []
            return 200, {"ok": True,
                "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows],
                "count": len(rows)}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path in ("/api/v2/automated-journal-analytics", "/api/v2/paper-analytics"):
        try:
            # Exclude phantom/orphan/never-filled/bogus trades from analytics
            _real_trade_filter = """
                AND COALESCE(exit_reason, '') NOT LIKE 'phantom%%'
                AND COALESCE(exit_reason, '') NOT LIKE 'order_never_filled%%'
                AND COALESCE(exit_reason, '') NOT LIKE 'bogus%%'
                AND COALESCE(close_reason, '') NOT LIKE 'phantom%%'
                AND COALESCE(close_reason, '') NOT LIKE 'Orphan%%'
                AND (pnl IS NULL OR pnl != 0)
            """
            # Overall stats
            overall = _db_query(f"""
                SELECT
                    COUNT(*) FILTER (WHERE status='closed' {_real_trade_filter}) as total_trades,
                    COUNT(*) FILTER (WHERE status='open') as open_trades,
                    COUNT(*) FILTER (WHERE status='closed' AND pnl > 0 {_real_trade_filter}) as wins,
                    COUNT(*) FILTER (WHERE status='closed' AND pnl < 0 {_real_trade_filter}) as losses,
                    ROUND(SUM(pnl) FILTER (WHERE status='closed' AND pnl > 0 {_real_trade_filter})::numeric, 2) as gross_profit,
                    ROUND(ABS(SUM(pnl) FILTER (WHERE status='closed' AND pnl < 0 {_real_trade_filter}))::numeric, 2) as gross_loss,
                    ROUND(SUM(pnl) FILTER (WHERE status='closed' {_real_trade_filter})::numeric, 2) as total_realized_pnl,
                    ROUND(SUM(unrealized_pnl) FILTER (WHERE status='open')::numeric, 2) as total_unrealized_pnl,
                    ROUND(AVG(pnl) FILTER (WHERE status='closed' AND pnl > 0 {_real_trade_filter})::numeric, 2) as avg_winner,
                    ROUND(AVG(ABS(pnl)) FILTER (WHERE status='closed' AND pnl < 0 {_real_trade_filter})::numeric, 2) as avg_loser,
                    ROUND(AVG(r_multiple) FILTER (WHERE status='closed' AND pnl != 0 {_real_trade_filter})::numeric, 2) as avg_r
                FROM paper_trades
            """, fetch="one") or {}
            tc = overall.get('total_trades') or 0
            w = overall.get('wins') or 0
            gp = float(overall.get('gross_profit') or 0)
            gl = float(overall.get('gross_loss') or 0)
            overall['win_rate'] = round(w / tc, 3) if tc > 0 else None
            overall['profit_factor'] = round(gp / gl, 2) if gl > 0 else None
            wr = overall['win_rate']
            aw = float(overall.get('avg_winner') or 0)
            al = float(overall.get('avg_loser') or 0)
            overall['expectancy'] = round((wr * aw) - ((1 - wr) * al), 2) if wr is not None else None

            # By strategy — exclude phantom/orphan/never-filled
            by_strategy = _db_query(f"""
                SELECT strategy_id,
                    COUNT(*) FILTER (WHERE status='closed' {_real_trade_filter}) as trades,
                    COUNT(*) FILTER (WHERE status='closed' AND pnl > 0 {_real_trade_filter}) as wins,
                    ROUND(SUM(pnl) FILTER (WHERE status='closed' {_real_trade_filter})::numeric, 2) as pnl
                FROM paper_trades GROUP BY strategy_id
                HAVING COUNT(*) FILTER (WHERE status='closed' {_real_trade_filter}) > 0
                    OR COUNT(*) FILTER (WHERE status='open') > 0
            """) or []

            # Validation gates per strategy
            validation = {}
            strat_rows = _db_query("""
                SELECT strategy_id, min_win_rate, target_win_rate
                FROM strategy_registry
                WHERE status = 'TESTING'
            """) or []
            for sr in strat_rows:
                sid = sr['strategy_id']
                bs = next((s for s in by_strategy if s.get('strategy_id') == sid), {})
                done = bs.get('trades') or 0
                bw = bs.get('wins') or 0
                bwr = round(bw / done, 3) if done > 0 else None
                validation[sid] = {
                    'trades_needed': 30, 'trades_done': done,
                    'win_rate_needed': float(sr.get('min_win_rate') or 0.50),
                    'win_rate_current': bwr,
                    'gate_passed': done >= 30 and bwr is not None and bwr >= float(sr.get('min_win_rate') or 0.50),
                }

            # Recent closed — exclude phantoms
            recent = _db_query(f"""
                SELECT id, symbol, strategy_id, account, entry_price, exit_price,
                       pnl, pnl_pct, outcome_verdict, exit_reason, closed_at
                FROM paper_trades WHERE status='closed'
                    {_real_trade_filter}
                ORDER BY closed_at DESC LIMIT 20
            """) or []

            return 200, {"ok": True,
                "overall": {k: _json_clean(v) for k, v in overall.items()},
                "by_strategy": [{k: _json_clean(v) for k, v in r.items()} for r in by_strategy],
                "validation_gates": validation,
                "recent_closed": [{k: _json_clean(v) for k, v in r.items()} for r in recent],
            }
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Session 14: Paper Command Center endpoints ──

    if base_path == "/api/v2/paper-status":
        try:
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from alpaca_paper_adapter import AlpacaPaperAdapter
            adapter = AlpacaPaperAdapter()
            alpaca_status = adapter.get_alpaca_paper_status()

            pt_stats = _db_query("""
                SELECT
                    COUNT(*) FILTER (WHERE status='open') as open_trades,
                    COUNT(*) FILTER (WHERE created_at::date = CURRENT_DATE AND status='open') as today_opened,
                    COUNT(*) FILTER (WHERE closed_at::date = CURRENT_DATE) as today_closed,
                    COALESCE(SUM(pnl) FILTER (WHERE closed_at::date = CURRENT_DATE), 0) as today_realized,
                    COALESCE(SUM(COALESCE(unrealized_pnl, pnl)) FILTER (WHERE status='open'), 0) as today_unrealized
                FROM paper_trades
            """, fetch="one") or {}

            pending = _db_query("SELECT COUNT(*) as cnt FROM paper_trade_proposals WHERE status='PENDING' AND expires_at > NOW()", fetch="one") or {}
            halts = _db_query("SELECT key, value FROM system_controls WHERE key LIKE 'halt%'") or []

            return 200, {"ok": True,
                "alpaca": alpaca_status,
                "paper_trading": {k: _json_clean(v) for k, v in pt_stats.items()},
                "pending_proposals": pending.get('cnt', 0),
                "risk": {r['key']: r['value'] for r in halts},
            }
        except Exception as e:
            return 200, {"ok": True, "alpaca": {"connected": False, "last_error": str(e)},
                         "paper_trading": {}, "risk": {}}

    if base_path == "/api/v2/paper-proposals":
        try:
            return _paper_proposals_enriched()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/approve":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            if not pid:
                return 400, {"ok": False, "error": "proposal_id required"}
            confirmed = body.get('confirmed', False)
            approval_mode = body.get('approval_mode', 'approve_ready')

            # Check decision state before approving
            rp = _db_query("""
                SELECT packet_status, research_score, confidence_score
                FROM proposal_research_packets WHERE proposal_id = %s
                ORDER BY updated_at DESC LIMIT 1
            """, [int(pid)], fetch="one")

            if rp:
                ds = rp.get('packet_status', '')
                blocked_states = ('BLOCKED_BY_RISK_GATE', 'RESEARCH_INCOMPLETE', 'AI_REVIEW_MISSING', 'DATA_STALE', 'REJECT_RECOMMENDED')
                if ds in blocked_states and not confirmed:
                    return 400, {"ok": False, "error": f"Cannot approve: {ds}. Run research first or use confirmation.", "decision_state": ds}
                cautious_states = ('CAUTIOUS_PAPER_TEST', 'BACKTEST_INSUFFICIENT')
                if ds in cautious_states and not confirmed:
                    return 400, {"ok": False, "error": f"Requires confirmation: {ds}", "decision_state": ds, "needs_confirmation": True}
                if ds in cautious_states:
                    approval_mode = 'cautious_confirmed' if ds == 'CAUTIOUS_PAPER_TEST' else 'first_sample_learning_confirmed'

            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from paper_trade_logger import approve_proposal
            result = approve_proposal(int(pid),
                override_shares=body.get('shares'),
                override_entry=body.get('entry'),
                override_stop=body.get('stop'),
                override_target=body.get('target'))

            # Store research packet metadata on the paper trade
            if result.get('success') and result.get('paper_trade_id') and rp:
                try:
                    votes = _db_query("""
                        SELECT json_object_agg(agent_name, json_build_object('vote', vote, 'confidence', confidence))
                        FROM proposal_agent_reviews WHERE proposal_id = %s
                    """, [int(pid)], fetch="one")
                    _db_query("""
                        UPDATE paper_trades SET
                            research_packet_id = (SELECT id FROM proposal_research_packets WHERE proposal_id = %s LIMIT 1),
                            decision_state = %s,
                            confidence_score = %s,
                            agent_votes = %s,
                            backtest_quality = (SELECT backtest_quality FROM proposal_backtest_snapshots WHERE proposal_id = %s LIMIT 1),
                            approval_mode = %s
                        WHERE id = %s
                    """, [int(pid), ds if rp else None,
                          rp.get('confidence_score') if rp else None,
                          json.dumps(votes.get('json_object_agg') if votes else None),
                          int(pid), approval_mode, result['paper_trade_id']])
                except Exception:
                    pass

            # Get updated status
            new_status = None
            try:
                _ns = _db_query("SELECT status FROM paper_trade_proposals WHERE id=%s", [int(pid)], fetch="one")
                new_status = _ns.get('status') if _ns else None
            except Exception:
                pass

            # ── INSTANT EXECUTION: attempt Alpaca paper submission immediately ──
            alpaca_result = None
            if result.get('success') and result.get('paper_trade_id'):
                try:
                    from proposal_paper_submitter import submit_paper
                    from session13_db import get_conn as _get_sub_conn
                    _sub_conn = _get_sub_conn()
                    if _sub_conn:
                        alpaca_result = submit_paper(_sub_conn, int(pid), dry_run=False)
                        _sub_conn.close()
                        if alpaca_result and alpaca_result.get('status') == 'submitted':
                            print(f"  [instant-exec] {body.get('proposal_id')}: Alpaca paper order submitted")
                except Exception as _alpaca_err:
                    alpaca_result = {"status": "failed", "error": str(_alpaca_err)}
                    print(f"  [instant-exec] Alpaca submit failed: {_alpaca_err}")

            return 200 if result.get('success') else 400, {
                "ok": result.get('success', False),
                "proposal_id": int(pid),
                "old_status": "PENDING",
                "new_status": new_status or "APPROVED",
                "message": result.get('message', 'Approved for paper test' if result.get('success') else 'Approval failed'),
                "paper_trade_id": result.get('paper_trade_id'),
                "blockers": result.get('blockers', []),
                "alpaca_submission": alpaca_result,
                "data": result,
            }
        except Exception as e:
            return 500, {"ok": False, "error": str(e), "message": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/reject":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            if not pid:
                return 400, {"ok": False, "error": "proposal_id required"}
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from paper_trade_logger import reject_proposal
            result = reject_proposal(int(pid), body.get('reason', 'dashboard'))
            return 200 if result.get('success') else 400, {"ok": result.get('success', False), "data": result}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Session 17v3: Research packet endpoints ──

    if base_path == "/api/v2/paper-proposals/research-packet":
        try:
            q = query or {}
            pid = q.get('proposal_id', [None])[0] if isinstance(q.get('proposal_id'), list) else q.get('proposal_id')
            # Also try parsing from path query string
            if not pid and '?' in path:
                from urllib.parse import parse_qs
                qs = parse_qs(path.split('?', 1)[1])
                pid = qs.get('proposal_id', [None])[0]
            if not pid:
                return 400, {"ok": False, "error": "proposal_id required"}
            rp = _db_query("""
                SELECT * FROM proposal_research_packets
                WHERE proposal_id = %s ORDER BY updated_at DESC LIMIT 1
            """, [int(pid)], fetch="one")
            if not rp:
                return 404, {"ok": False, "error": f"No research packet for proposal {pid}"}
            packet = rp.get('packet') or {}
            return 200, {"ok": True, "packet": {k: _json_clean(v) for k, v in packet.items()} if isinstance(packet, dict) else packet}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/run-research":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            if not pid:
                return 400, {"ok": False, "error": "proposal_id required"}
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from proposal_research_packet_builder import build_research_packet
            from session13_db import get_conn
            conn = get_conn()
            try:
                packet = build_research_packet(conn, int(pid), refresh=body.get('refresh', True))
                return 200, {"ok": True, "packet": {
                    "decision_state": packet.get('final_summary', {}).get('decision_state'),
                    "research_score": packet.get('final_summary', {}).get('research_score'),
                    "confidence_score": packet.get('final_summary', {}).get('confidence_score'),
                    "missing_data_count": packet.get('final_summary', {}).get('missing_data_count'),
                }}
            finally:
                conn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/run-agent-review":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            if not pid:
                return 400, {"ok": False, "error": "proposal_id required"}
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from proposal_agent_review import review_proposal
            from session13_db import get_conn
            conn = get_conn()
            try:
                result = review_proposal(conn, int(pid))
                return 200, {"ok": True, "data": {
                    "agent_review_status": result.get('agent_review_status'),
                    "agent_votes": result.get('agent_votes'),
                }}
            finally:
                conn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/run-backtest":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            if not pid:
                return 400, {"ok": False, "error": "proposal_id required"}
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from proposal_backtest_engine import backtest_proposal
            from session13_db import get_conn
            conn = get_conn()
            try:
                result = backtest_proposal(conn, int(pid))
                return 200, {"ok": True, "data": {
                    "backtest_quality": result.get('backtest_quality'),
                    "sample_size": result.get('sample_size'),
                    "win_rate": result.get('win_rate'),
                    "similar_setup_summary": result.get('similar_setup_summary'),
                }}
            finally:
                conn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/refresh-data":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            if not pid:
                return 400, {"ok": False, "error": "proposal_id required"}
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from proposal_technical_snapshot import generate_snapshot
            from proposal_backtest_engine import backtest_proposal
            from session13_db import get_conn
            conn = get_conn()
            try:
                tech = generate_snapshot(conn, proposal_id=int(pid))
                bt = backtest_proposal(conn, int(pid))
                return 200, {"ok": True, "data": {
                    "technical_refreshed": bool(tech),
                    "backtest_refreshed": bool(bt),
                }}
            finally:
                conn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # Session 23C: Additional institutional packet endpoints
    if method == "POST" and base_path == "/api/v2/paper-proposals/run-indicators":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            if not pid:
                return 400, {"ok": False, "error": "proposal_id required"}
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from proposal_technical_snapshot import generate_snapshot
            from session13_db import get_conn
            conn = get_conn()
            try:
                snap = generate_snapshot(conn, proposal_id=int(pid))
                return 200, {"ok": True, "data": {
                    "rsi": snap.get('rsi'),
                    "atr": snap.get('atr'),
                    "vwap_state": snap.get('vwap_state'),
                    "technical_vote": snap.get('technical_vote'),
                }}
            finally:
                conn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/run-ai-review":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            if not pid:
                return 400, {"ok": False, "error": "proposal_id required"}
            import subprocess as _sp
            _sp.Popen(
                [str(PROJECT_ROOT / ".venv/bin/python"),
                 str(PROJECT_ROOT / "scripts/proposal_intelligence_analyzer.py"),
                 "--proposal-id", str(pid), "--apply"],
                cwd=str(PROJECT_ROOT),
                stdout=open(str(PROJECT_ROOT / "logs/ai_review.log"), "a"),
                stderr=_sp.STDOUT
            )
            return 200, {"ok": True, "message": f"AI review started for proposal #{pid}"}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/check-execution-readiness":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            if not pid:
                return 400, {"ok": False, "error": "proposal_id required"}
            import subprocess as _sp
            result = _sp.run(
                [str(PROJECT_ROOT / ".venv/bin/python"),
                 str(PROJECT_ROOT / "scripts/proposal_execution_readiness.py"),
                 "--proposal-id", str(pid), "--apply"],
                capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT)
            )
            try:
                data = json.loads(result.stdout) if result.stdout else {}
            except Exception:
                data = {"raw": result.stdout[-500:] if result.stdout else ""}
            return 200, {"ok": True, "data": data}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/submit-alpaca-paper":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            confirmed = body.get('confirmed', False)
            if not pid:
                return 400, {"ok": False, "error": "proposal_id required"}
            if not confirmed:
                return 400, {"ok": False, "error": "Must confirm paper submission (confirmed=true)"}
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from proposal_paper_submitter import submit_paper
            from session13_db import get_conn
            conn = get_conn()
            try:
                result = submit_paper(conn, int(pid), dry_run=False)
                return 200, {"ok": True, "data": result}
            finally:
                conn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Session 23D: Technical level and bracket endpoints ────────────────

    if method == "POST" and base_path == "/api/v2/paper-proposals/run-fib":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            symbol = body.get('symbol')
            if not pid and not symbol:
                return 400, {"ok": False, "error": "proposal_id or symbol required"}
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from fib_swing_engine import process_symbol
            from session13_db import get_conn
            conn = get_conn()
            try:
                if pid and not symbol:
                    row = _db_query("SELECT symbol FROM paper_trade_proposals WHERE id=%s", [int(pid)], fetch="one")
                    symbol = row.get("symbol") if row else None
                result = process_symbol(conn, symbol, days=60, apply=True) if symbol else {"error": "no symbol"}
                return 200, {"ok": True, "data": result}
            finally:
                conn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/run-opening-range":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            symbol = body.get('symbol')
            if not pid and not symbol:
                return 400, {"ok": False, "error": "proposal_id or symbol required"}
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from opening_range_engine import process_symbol
            from session13_db import get_conn
            conn = get_conn()
            try:
                if pid and not symbol:
                    row = _db_query("SELECT symbol FROM paper_trade_proposals WHERE id=%s", [int(pid)], fetch="one")
                    symbol = row.get("symbol") if row else None
                result = process_symbol(conn, symbol, apply=True) if symbol else {"error": "no symbol"}
                return 200, {"ok": True, "data": result}
            finally:
                conn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/run-technical-snapshot":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            if not pid:
                return 400, {"ok": False, "error": "proposal_id required"}
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from proposal_technical_snapshot import generate_snapshot
            from session13_db import get_conn
            conn = get_conn()
            try:
                result = generate_snapshot(conn, proposal_id=int(pid))
                return 200, {"ok": True, "data": result}
            finally:
                conn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/dry-run-alpaca-bracket":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            if not pid:
                return 400, {"ok": False, "error": "proposal_id required"}
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from proposal_paper_submitter import dry_run_bracket
            from session13_db import get_conn
            conn = get_conn()
            try:
                result = dry_run_bracket(conn, int(pid))
                return 200, {"ok": True, "data": result}
            finally:
                conn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/submit-alpaca-paper-bracket":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            confirmed = body.get('confirmed', False)
            if not pid:
                return 400, {"ok": False, "error": "proposal_id required"}
            if not confirmed:
                return 400, {"ok": False, "error": "Must confirm bracket submission (confirmed=true)"}
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from proposal_paper_submitter import submit_paper_bracket
            from session13_db import get_conn
            conn = get_conn()
            try:
                result = submit_paper_bracket(conn, int(pid),
                                              allow_after_hours=body.get('allow_after_hours', False))
                return 200, {"ok": True, "data": result}
            finally:
                conn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "GET" and base_path == "/api/v2/paper-proposals/technical-diagnostics":
        try:
            diags = _db_query("""
                SELECT pts.proposal_id, pts.symbol,
                       pts.ema_8, pts.ema_21, pts.ema_50, pts.ema_200,
                       pts.ema_alignment, pts.technical_grade,
                       pts.fib_context, pts.nearest_fib_level, pts.nearest_fib_distance_pct,
                       pts.opening_range_high, pts.opening_range_low,
                       pts.opening_range_status, pts.premarket_status,
                       pts.ohlcv_data_status,
                       per.readiness_state, per.bracket_order_supported,
                       per.alpaca_account_mode, per.market_hours,
                       per.paper_submit_test_result
                FROM proposal_technical_snapshots pts
                LEFT JOIN proposal_execution_readiness per
                    ON per.proposal_id = pts.proposal_id
                    AND per.id = (SELECT MAX(id) FROM proposal_execution_readiness WHERE proposal_id = pts.proposal_id)
                WHERE pts.id IN (
                    SELECT MAX(id) FROM proposal_technical_snapshots GROUP BY proposal_id
                )
                ORDER BY pts.computed_at DESC
            """) or []
            return 200, {"ok": True, "diagnostics": [
                {k: _json_clean(v) for k, v in d.items()} for d in diags
            ]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Session 24B: Strategy config + multi-setup endpoints ──────────────

    if method == "GET" and base_path == "/api/v2/strategy-configs":
        try:
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from strategy_config_loader import load_all_strategy_configs
            configs = load_all_strategy_configs()
            # Derive expiry display for TESTING strategies
            _EXPIRY_DISPLAY = {
                'gap_and_go': '8h (intraday)', 'momentum_scalp': '8h (intraday)',
                'swing_breakout': '120h (5d swing)', 'earnings_catalyst': '120h (5d swing)',
                'swing_trade': '168h (7d)',
            }
            result = {}
            for sid, c in sorted(configs.items()):
                risk = c.get("risk") or {}
                status = c.get("status")
                # Derive risk display for TESTING strategies with NULL risk_pct_portfolio
                risk_display = risk.get("risk_pct_portfolio")
                if risk_display is None and status == "TESTING":
                    risk_display = "Paper only"
                # Derive expiry display
                expiry_display = c.get("lifecycle", {}).get("expiry_hours") if c.get("lifecycle") else None
                if expiry_display is None:
                    expiry_display = _EXPIRY_DISPLAY.get(sid, '168h (7d)' if status == 'TESTING' else None)
                result[sid] = {
                    "strategy_id": sid,
                    "display_name": c.get("display_name"),
                    "version": c.get("version"),
                    "status": status,
                    "timeframe": c.get("timeframe"),
                    "timeframe_class": c.get("timeframe_class"),
                    "purpose": c.get("purpose"),
                    "eligible_accounts": c.get("eligible_accounts"),
                    "config_hash": c.get("_config_hash"),
                    "risk": risk,
                    "risk_display": risk_display,
                    "expiry_display": expiry_display,
                    "lifecycle": c.get("lifecycle"),
                    "co_enables": c.get("co_enables"),
                }
            return 200, {"ok": True, "strategies": result, "count": len(result)}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "GET" and base_path.startswith("/api/v2/strategy-configs/"):
        try:
            sid = base_path.split("/")[-1]
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from strategy_config_loader import load_strategy_config, get_strategy_prompt_context
            config = load_strategy_config(sid)
            ctx = get_strategy_prompt_context(sid)
            return 200, {"ok": True, "config": {k: v for k, v in config.items() if not k.startswith("_")},
                         "config_hash": config.get("_config_hash"), "prompt_context": ctx}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "GET" and base_path == "/api/v2/strategy-setup-matches":
        try:
            rows = _db_query("""
                SELECT id, symbol, proposal_id, strategy_id, match_score,
                       match_status, criteria_met, criteria_failed, disqualifiers_hit,
                       is_primary, priority_rank, reason, created_at
                FROM strategy_setup_matches
                ORDER BY created_at DESC LIMIT 100
            """) or []
            return 200, {"ok": True, "matches": [
                {k: _json_clean(v) for k, v in r.items()} for r in rows
            ]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/strategy-configs/validate":
        try:
            import subprocess as _sp
            r = _sp.run([str(PROJECT_ROOT / ".venv/bin/python"),
                         str(PROJECT_ROOT / "scripts/strategy_config_loader.py"), "--validate"],
                        capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
            return 200, {"ok": r.returncode == 0, "output": r.stdout[-2000:]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/strategy-configs/sync-db":
        try:
            import subprocess as _sp
            r = _sp.run([str(PROJECT_ROOT / ".venv/bin/python"),
                         str(PROJECT_ROOT / "scripts/strategy_config_loader.py"), "--sync-db"],
                        capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
            return 200, {"ok": r.returncode == 0, "output": r.stdout[-1000:]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Session 24A: Lifecycle + governance endpoints ─────────────────────

    if method == "GET" and base_path.startswith("/api/v2/paper-proposals/live-price/"):
        try:
            sym = base_path.split("/")[-1].upper()
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from market_quote_provider import get_best_quote
            from proposal_lifecycle import evaluate_lifecycle_status, get_timeframe_class
            from session13_db import get_conn
            conn = get_conn()
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, strategy_id, proposed_entry, created_at, expires_at,
                           max_expires_at, expiry_extended_count
                    FROM paper_trade_proposals WHERE symbol=%s AND status='PENDING'
                    ORDER BY created_at DESC LIMIT 1
                """, [sym])
                row = cur.fetchone()
                if not row:
                    return 404, {"ok": False, "error": f"No pending proposal for {sym}"}
                pid, strat, entry, created, exp, max_exp, ext_count = row
                q = get_best_quote(sym)
                cp = q.get("last_price") or (q.get("bid") if q.get("bid") else None)
                lc = evaluate_lifecycle_status(strat, cp, float(entry or 0), created, exp, max_exp, q)
                # news count
                cur.execute("SELECT COUNT(*) FROM news_articles WHERE symbol=%s AND published_at > NOW()-INTERVAL '24 hours'", [sym])
                nc = cur.fetchone()[0]
                cur.close()
                return 200, {"ok": True, "symbol": sym, "strategy_id": strat,
                    "current_price": cp, "entry_price": float(entry or 0),
                    "drift_pct": lc.get("price_drift_pct"),
                    "lifecycle_status": lc.get("lifecycle_status"),
                    "entry_zone_status": lc.get("entry_zone_status"),
                    "message": lc.get("message"),
                    "quote_provider": q.get("provider"),
                    "quote_is_delayed": q.get("is_delayed"),
                    "quote_execution_eligible": q.get("is_execution_eligible"),
                    "news_count": nc,
                    "expires_at": _json_clean(exp), "max_expires_at": _json_clean(max_exp),
                    "expiry_extended_count": ext_count or 0,
                    "timeframe_class": get_timeframe_class(strat)}
            finally:
                conn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/monitor":
        try:
            body = body or {}
            import subprocess as _sp
            args = [str(PROJECT_ROOT / ".venv/bin/python"),
                    str(PROJECT_ROOT / "scripts/proposal_monitor.py"),
                    "--pending", "--apply"]
            if body.get("include_intraday"):
                args.append("--include-intraday")
            r = _sp.run(args, capture_output=True, text=True, timeout=120, cwd=str(PROJECT_ROOT))
            return 200, {"ok": True, "output": r.stdout[-2000:] if r.stdout else "", "returncode": r.returncode}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "GET" and base_path == "/api/v2/paper-proposals/lifecycle-events":
        try:
            events = _db_query("""
                SELECT id, proposal_id, symbol, strategy_id, event_type,
                       lifecycle_status, current_price, entry_price, price_drift_pct,
                       quote_provider, news_count, expiry_before, expiry_after,
                       message, created_at
                FROM proposal_lifecycle_events
                ORDER BY created_at DESC LIMIT 100
            """) or []
            return 200, {"ok": True, "events": [
                {k: _json_clean(v) for k, v in e.items()} for e in events
            ]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "GET" and base_path == "/api/v2/execution-quality":
        try:
            rows = _db_query("""
                SELECT * FROM paper_execution_quality ORDER BY created_at DESC LIMIT 50
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "GET" and base_path == "/api/v2/broker-reconciliation":
        try:
            runs = _db_query("SELECT * FROM broker_reconciliation_runs ORDER BY started_at DESC LIMIT 10") or []
            items = _db_query("SELECT * FROM broker_reconciliation_items ORDER BY created_at DESC LIMIT 50") or []
            return 200, {"ok": True, "runs": [{k: _json_clean(v) for k, v in r.items()} for r in runs],
                         "items": [{k: _json_clean(v) for k, v in i.items()} for i in items]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "GET" and base_path == "/api/v2/paper-performance-governance":
        try:
            rows = _db_query("SELECT * FROM paper_performance_governance ORDER BY created_at DESC LIMIT 20") or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-reconciliation/run":
        try:
            import subprocess as _sp
            r = _sp.run([str(PROJECT_ROOT / ".venv/bin/python"),
                         str(PROJECT_ROOT / "scripts/alpaca_paper_reconciler.py"), "--apply"],
                        capture_output=True, text=True, timeout=60, cwd=str(PROJECT_ROOT))
            return 200, {"ok": True, "output": r.stdout[-1000:], "returncode": r.returncode}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/execution-quality/run":
        try:
            import subprocess as _sp
            r = _sp.run([str(PROJECT_ROOT / ".venv/bin/python"),
                         str(PROJECT_ROOT / "scripts/paper_execution_quality_analyzer.py"),
                         "--recent", "--apply"],
                        capture_output=True, text=True, timeout=60, cwd=str(PROJECT_ROOT))
            return 200, {"ok": True, "output": r.stdout[-1000:], "returncode": r.returncode}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/enrich-all":
        try:
            import subprocess as _sp
            import threading as _thr
            import time as _time

            # Status file for async tracking
            _status_file = PROJECT_ROOT / "logs" / "enrich_all_status.json"

            def _run_pipeline():
                steps = [
                    ("tech_snapshot", "proposal_technical_snapshot.py", ["--pending", "--apply"], 60),
                    ("queue_reviews", "queue_proposal_agent_reviews.py", ["--apply"], 30),
                    ("agent_jobs", "process_watchlist_agent_jobs.py", ["--limit", "20"], 600),
                    ("llm_analysis", "proposal_intelligence_analyzer.py", ["--pending", "--apply"], 600),
                    ("backtest", "proposal_backtest_engine.py", ["--pending", "--apply"], 60),
                    ("quality", "proposal_quality_reviewer.py", ["--apply"], 30),
                    ("readiness", "proposal_execution_readiness.py", ["--pending", "--apply"], 120),
                    ("monitor", "proposal_monitor.py", ["--pending", "--include-intraday", "--apply"], 120),
                ]
                results = {}
                for key, script, args, timeout in steps:
                    results[key] = "running"
                    try:
                        _status_file.write_text(json.dumps({"state": "running", "current_step": key, "steps": results}))
                    except Exception:
                        pass
                    try:
                        r = _sp.run(
                            [str(PROJECT_ROOT / ".venv/bin/python"),
                             str(PROJECT_ROOT / "scripts" / script)] + args,
                            capture_output=True, text=True, timeout=timeout, cwd=str(PROJECT_ROOT))
                        results[key] = "ok" if r.returncode == 0 else f"exit:{r.returncode}"
                    except Exception as e:
                        results[key] = f"error: {str(e)[:60]}"
                all_ok = all(v == "ok" for v in results.values())
                try:
                    _status_file.write_text(json.dumps({
                        "state": "done" if all_ok else "done_with_issues",
                        "all_passed": all_ok, "steps": results,
                        "finished_at": _time.strftime("%H:%M:%S")}))
                except Exception:
                    pass

            # Launch in background thread
            t = _thr.Thread(target=_run_pipeline, daemon=True)
            t.start()
            return 200, {"ok": True, "state": "started",
                         "message": "Enrichment pipeline started in background. Poll /api/v2/paper-proposals/enrich-status for progress."}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "GET" and base_path == "/api/v2/paper-proposals/enrich-status":
        try:
            _status_file = PROJECT_ROOT / "logs" / "enrich_all_status.json"
            if _status_file.exists():
                return 200, {"ok": True, **json.loads(_status_file.read_text())}
            return 200, {"ok": True, "state": "idle", "message": "No enrichment running"}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/refresh-packet":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            if not pid:
                return 400, {"ok": False, "error": "proposal_id required"}
            import subprocess as _sp
            results = {}
            for script, key in [
                ("proposal_technical_snapshot.py", "technical"),
                ("proposal_strategy_fit.py", "strategy_fit"),
                ("proposal_backtest_engine.py", "backtest"),
                ("proposal_catalyst_quality.py", "catalyst"),
                ("proposal_execution_readiness.py", "execution"),
            ]:
                try:
                    r = _sp.run(
                        [str(PROJECT_ROOT / ".venv/bin/python"),
                         str(PROJECT_ROOT / "scripts" / script),
                         "--proposal-id", str(pid), "--apply"],
                        capture_output=True, text=True, timeout=60, cwd=str(PROJECT_ROOT)
                    )
                    results[key] = "ok" if r.returncode == 0 else "failed"
                except Exception as e:
                    results[key] = f"error: {e}"
            return 200, {"ok": True, "proposal_id": pid,
                         "packet_ready": all(v == "ok" for v in results.values()),
                         "results": results,
                         "message": "Institutional packet refreshed"}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "GET" and base_path == "/api/v2/paper-proposals/events":
        try:
            events = _db_query("""
                SELECT id, proposal_id, paper_trade_id, symbol, event_type,
                       event_source, payload, created_at
                FROM proposal_event_log
                ORDER BY created_at DESC LIMIT 50
            """) or []
            return 200, {"ok": True, "events": [
                {k: _json_clean(v) for k, v in e.items()} for e in events
            ]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # Session 26: Packet health
    if method == "GET" and base_path == "/api/v2/paper-proposals/packet-health":
        try:
            rows = _db_query("""
                SELECT action_state, packet_state, packet_completion_pct,
                       llm_review_status, agent_review_status, entry_zone_status,
                       latest_execution_readiness
                FROM paper_trade_proposals
                WHERE status = 'PENDING'
            """) or []
            from collections import Counter
            states = Counter(r.get('action_state') or 'UNKNOWN' for r in rows)
            llm_pending = sum(1 for r in rows if (r.get('llm_review_status') or 'NOT_REQUESTED') not in ('COMPLETE',))
            agents_pending = sum(1 for r in rows if (r.get('agent_review_status') or 'NOT_REQUESTED') not in ('COMPLETE', 'complete'))
            exec_pending = sum(1 for r in rows if not r.get('latest_execution_readiness'))
            avg_pct = round(sum(float(r.get('packet_completion_pct') or 0) for r in rows) / max(len(rows), 1), 1)
            return 200, {"ok": True, "summary": {
                "pending": len(rows),
                "paper_ready": states.get('PAPER_READY', 0),
                "blocked": states.get('BLOCKED', 0),
                "missing_data": states.get('MISSING_DATA', 0),
                "needs_review": states.get('NEEDS_REVIEW', 0),
                "caution": states.get('CAUTION', 0),
                "learning_mode": states.get('LEARNING_MODE', 0),
                "avg_completion_pct": avg_pct,
                "llm_pending": llm_pending,
                "agents_pending": agents_pending,
                "execution_pending": exec_pending,
            }}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # Session 26: Enrich proposals
    if method == "POST" and base_path == "/api/v2/paper-proposals/enrich":
        try:
            import subprocess as _sp
            pid_arg = []
            body = {}
            try:
                body = json.loads(environ.get('wsgi.input', b'').read() if hasattr(environ.get('wsgi.input', b''), 'read') else b'{}')
            except Exception:
                pass
            if body.get('proposal_id'):
                pid_arg = ['--proposal-id', str(body['proposal_id'])]
            r = _sp.run(
                [str(PROJECT_ROOT / ".venv/bin/python3"),
                 str(PROJECT_ROOT / "scripts/proposal_enrichment_loop.py"), "--run", "--limit", "10"] + pid_arg,
                capture_output=True, text=True, timeout=120, cwd=str(PROJECT_ROOT))
            return 200, {"ok": r.returncode == 0,
                         "stdout": r.stdout[-2000:],
                         "stderr": r.stderr[-500:] if r.returncode != 0 else ""}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # Session 26: Queue LLM reviews
    if method == "POST" and base_path == "/api/v2/paper-proposals/queue-llm-review":
        try:
            import subprocess as _sp
            r = _sp.run(
                [str(PROJECT_ROOT / ".venv/bin/python3"),
                 str(PROJECT_ROOT / "scripts/proposal_enrichment_loop.py"), "--run", "--queue-llm-only", "--limit", "20"],
                capture_output=True, text=True, timeout=60, cwd=str(PROJECT_ROOT))
            return 200, {"ok": r.returncode == 0,
                         "stdout": r.stdout[-2000:],
                         "stderr": r.stderr[-500:] if r.returncode != 0 else ""}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # Session 26: Run LLM review
    if method == "POST" and base_path == "/api/v2/paper-proposals/run-llm-review":
        try:
            import subprocess as _sp
            r = _sp.run(
                [str(PROJECT_ROOT / ".venv/bin/python3"),
                 str(PROJECT_ROOT / "scripts/proposal_llm_review_worker.py"), "--run", "--limit", "2"],
                capture_output=True, text=True, timeout=600, cwd=str(PROJECT_ROOT))
            return 200, {"ok": r.returncode == 0,
                         "stdout": r.stdout[-2000:],
                         "stderr": r.stderr[-500:] if r.returncode != 0 else ""}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # Session 26: Enrichment events
    if method == "GET" and base_path == "/api/v2/paper-proposals/enrichment-events":
        try:
            events = _db_query("""
                SELECT id, proposal_id, symbol, event_type, stage, status, message, created_at
                FROM proposal_enrichment_events
                ORDER BY created_at DESC LIMIT 50
            """) or []
            return 200, {"ok": True, "events": [{k: _json_clean(v) for k, v in e.items()} for e in events]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # Session 25: Promote from incubator
    if method == "POST" and base_path == "/api/v2/paper-proposals/promote-from-incubator":
        try:
            import subprocess as _sp
            r = _sp.run(
                [str(PROJECT_ROOT / ".venv/bin/python3"),
                 str(PROJECT_ROOT / "scripts/incubator_proposal_promoter.py"), "--run", "--limit", "15"],
                capture_output=True, text=True, timeout=60, cwd=str(PROJECT_ROOT))
            promoted = [l for l in r.stdout.splitlines() if l.startswith("PROMOTED:")]
            return 200, {"ok": r.returncode == 0,
                         "promoted": promoted,
                         "promoted_count": len(promoted),
                         "stdout": r.stdout[-2000:],
                         "stderr": r.stderr[-500:] if r.returncode != 0 else ""}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # Session 25: Pipeline health master
    if method == "GET" and base_path == "/api/v2/pipeline-health-master":
        try:
            from datetime import datetime as _dt, timezone as _tz
            STAGE_REGISTRY = {
                'data_collection': [
                    ('finviz_screener_runner', 'Finviz Screener', 6),
                    ('social_ingest', 'Social Ingest', 24),
                    ('news_ingestion', 'News Ingestion', 6),
                    ('fred_data_ingest', 'FRED Data', 24),
                    ('sec_data_ingest', 'SEC Data', 24),
                ],
                'enrichment': [
                    ('finviz_enrichment', 'Finviz Enrichment', 6),
                    ('catalyst_enrichment', 'Catalyst Enrichment', 6),
                    ('symbol_enrichment', 'Symbol Enrichment', 12),
                    ('rag_indexer', 'RAG Indexer', 8),
                ],
                'scoring': [
                    ('trade_ai_orchestrator', 'Orchestrator', 3),
                    ('indicator_engine', 'Indicators', 24),
                    ('premarket_watcher', 'Premarket', 1),
                    ('agent_router', 'Agent Router', 24),
                ],
                'intelligence': [
                    ('process_watchlist_agent_jobs', 'Agent Jobs', 0.25),
                    ('agent_watchlist_engine', 'Watchlist Engine', 24),
                    ('cio_decision_engine', 'CIO Engine', 24),
                    ('pipeline_watchdog', 'Watchdog', 0.083),
                ],
                'proposals': [
                    ('weekly_incubator_builder', 'Incubator Builder', 168),
                    ('daily_incubator_refresh', 'Incubator Refresh', 24),
                    ('incubator_rolloff_engine', 'Rolloff Engine', 24),
                    ('incubator_proposal_promoter', 'Proposal Promoter', 12),
                    ('proposal_enrichment_loop', 'Enrichment Loop', 0.083),
                    ('proposal_lifecycle', 'Lifecycle', 0.5),
                ],
                'execution': [
                    ('risk_gate', 'Risk Gate', 0),
                    ('alpaca_paper', 'Alpaca Paper', 0),
                    ('broker_reconciliation', 'Broker Recon', 24),
                    ('execution_quality', 'Exec Quality', 24),
                ],
                'overnight': [
                    ('overnight_batch', 'Overnight Batch', 24),
                    ('agent_outcome_scorer', 'Outcome Scorer', 24),
                    ('strategy_weekly_review', 'Weekly Review', 168),
                    ('overnight_batch_embeddings', 'Embeddings', 24),
                ],
            }
            GROUP_LABELS = {
                'data_collection': ('Data Collection', '6-7 AM M-F'),
                'enrichment': ('Enrichment', '7-8 AM M-F'),
                'scoring': ('Scoring', '8-9 AM M-F'),
                'intelligence': ('Intelligence', 'Continuous'),
                'proposals': ('Proposal Pipeline', 'The bridge'),
                'execution': ('Execution', 'Market hours'),
                'overnight': ('Overnight', '8 PM - 6 AM'),
            }
            now = _dt.now(tz=_tz.utc)
            groups = []
            total_stages = 0
            healthy = 0
            warnings = 0
            critical = 0
            for group_id, stages in STAGE_REGISTRY.items():
                label, desc = GROUP_LABELS[group_id]
                stage_list = []
                for script_name, display, cadence_h in stages:
                    total_stages += 1
                    row = _db_query("""
                        SELECT status, started_at, completed_at, rows_processed, duration_sec, error_message
                        FROM pipeline_runs WHERE script_name=%s ORDER BY started_at DESC LIMIT 1
                    """, [script_name], fetch="one")
                    last_run_at = None
                    last_status = None
                    rows_processed = 0
                    duration_sec = None
                    error_msg = None
                    minutes_ago = None
                    if row:
                        last_run_at = _json_clean(row.get('started_at'))
                        last_status = row.get('status')
                        rows_processed = row.get('rows_processed') or 0
                        duration_sec = _json_clean(row.get('duration_sec'))
                        error_msg = row.get('error_message')
                        if row.get('started_at'):
                            td = now - row['started_at']
                            minutes_ago = int(td.total_seconds() / 60)
                    # Derive color
                    if last_status == 'running':
                        color = 'blue'
                    elif last_status == 'failed':
                        color = 'red'
                        critical += 1
                    elif last_run_at is None:
                        color = 'gray'
                    elif cadence_h == 0:
                        color = 'green' if last_status == 'success' else 'red'
                        if color == 'green':
                            healthy += 1
                        else:
                            critical += 1
                    else:
                        hours_since = (minutes_ago or 99999) / 60
                        if hours_since > cadence_h * 2:
                            color = 'red'
                            critical += 1
                        elif hours_since > cadence_h * 1.5:
                            color = 'amber'
                            warnings += 1
                        else:
                            color = 'green'
                            healthy += 1
                    stage_list.append({
                        'id': script_name,
                        'label': display,
                        'status_color': color,
                        'last_run_at': last_run_at,
                        'last_status': last_status,
                        'rows_processed': rows_processed,
                        'duration_sec': duration_sec,
                        'error_message': error_msg,
                        'cadence_h': cadence_h,
                        'minutes_ago': minutes_ago,
                    })
                groups.append({
                    'id': group_id,
                    'label': label,
                    'description': desc,
                    'stages': stage_list,
                })
            return 200, {
                "ok": True,
                "summary": {
                    "healthy": healthy,
                    "warnings": warnings,
                    "critical": critical,
                    "total_stages": total_stages,
                    "last_full_cycle": now.strftime("%I:%M %p"),
                },
                "groups": groups,
            }
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.startswith("/api/v2/journal/trade-detail/"):
        def _deep_clean(obj):
            if isinstance(obj, Decimal): return float(obj)
            if hasattr(obj, 'isoformat'): return obj.isoformat()
            if isinstance(obj, dict): return {k: _deep_clean(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)): return [_deep_clean(i) for i in obj]
            if isinstance(obj, bytes): return obj.decode('utf-8', errors='replace')
            return obj
        try:
            _td_id = int(base_path.rsplit("/", 1)[-1])
            _td = _db_query("SELECT * FROM paper_trades WHERE id = %s", [_td_id], fetch="one")
            if not _td:
                return 404, {"ok": False, "error": "Trade not found"}
            _td_key = f"paper-{_td['symbol']}-{_td_id}"
            _td_review = _db_query("SELECT * FROM journal_trade_reviews WHERE trade_key = %s", [_td_key], fetch="one")
            _td_thesis = _db_query("SELECT * FROM trade_thesis_outcomes WHERE paper_trade_id = %s", [_td_id], fetch="one")
            _td_events = _db_query("SELECT agent_name, event_type, event_summary, payload, created_at FROM agent_curation_events WHERE paper_trade_id = %s ORDER BY created_at", [_td_id]) or []
            _td_analysis = _db_query("SELECT model_used, summary, worked_reasons, failed_reasons, lessons, suggested_rule_changes, confidence, created_at FROM paper_trade_analysis WHERE paper_trade_id = %s ORDER BY created_at DESC LIMIT 1", [_td_id], fetch="one")
            _td_risk = _db_query("SELECT action_type, old_value, new_value, trigger_price, trigger_reason, created_at FROM paper_trade_risk_actions WHERE paper_trade_id = %s ORDER BY created_at", [_td_id]) or []
            _td_alerts = _db_query("SELECT alert_type, severity, title, message, created_at FROM open_trade_alerts WHERE paper_trade_id = %s ORDER BY created_at", [_td_id]) or []
            _td_proposal = None
            if _td.get('proposal_id'):
                _td_proposal = _db_query("SELECT id, symbol, strategy_id, proposed_entry, proposed_stop, proposed_target1, proposed_shares, signal_score, signal_grade, catalyst, catalyst_verified, execution_eligibility_status, execution_eligibility_reason, live_price_at_execution, created_at FROM paper_trade_proposals WHERE id = %s", [_td.get('proposal_id')], fetch="one")
            # Timing classification
            _td_tod = _td_dow = None
            _td_et = _td.get('entry_time')
            if _td_et:
                try:
                    import zoneinfo as _zi
                    _et_obj = _td_et if hasattr(_td_et, 'hour') else __import__('datetime').datetime.fromisoformat(str(_td_et))
                    _et_loc = _et_obj.astimezone(_zi.ZoneInfo("America/New_York"))
                    _h = _et_loc.hour
                    _td_tod = "pre_market" if _h < 9 else "open" if _h < 10 else "midday" if _h < 14 else "close" if _h < 16 else "after_hours"
                    _td_dow = _et_loc.strftime("%A")
                except Exception: pass
            _td_hold = _td.get('hold_time_min')
            if not _td_hold and _td_et and _td.get('closed_at'):
                try:
                    _td_hold = int((_td['closed_at'] - _td_et).total_seconds() / 60) if hasattr(_td_et, 'timestamp') else None
                except Exception: pass
            _entry_p = float(_td.get('entry_price') or 0)
            _stop_p = float(_td.get('stop_loss') or 0)
            _tgt_p = float(_td.get('target_1') or 0)
            _plan_e = float(_td.get('planned_entry') or _entry_p)
            _slip = round(_entry_p - _plan_e, 4) if _plan_e else None
            _itype = "scalp" if (_td_hold or 999) < 60 else "day" if (_td_hold or 999) < 480 else "swing"
            return 200, _deep_clean({"ok": True,
                "trade": dict(_td),
                "classification": {"direction": "long", "strategy": _td.get('strategy_id'), "setup": _td.get('setup_type') or _td.get('strategy_id'), "intended_type": _itype, "time_of_day": _td_tod, "day_of_week": _td_dow, "market_regime": _td.get('market_regime')},
                "timing": {"entry_time": _td_et, "exit_time": _td.get('closed_at'), "hold_minutes": _td_hold},
                "technicals_at_entry": {"vix": _td.get('vix_at_entry'), "rvol": _td.get('rvol_at_entry'), "score": _td.get('score_at_entry'), "signal_grade": _td.get('signal_grade'), "catalyst": _td.get('catalyst_at_entry'), "catalyst_verified": _td.get('catalyst_verified'), "float_m": _td.get('float_m_at_entry'), "intel_readiness": _td.get('intel_readiness')},
                "risk_execution": {"planned_entry": _plan_e, "actual_entry": _entry_p, "slippage": _slip, "stop": _stop_p, "target": _tgt_p, "exit_price": float(_td.get('exit_price') or 0), "pnl": float(_td.get('pnl') or 0), "r_multiple": _td.get('r_multiple'), "mae": _td.get('max_adverse_excursion'), "mfe": _td.get('max_favorable_excursion'), "exit_reason": _td.get('exit_reason'), "outcome_verdict": _td.get('outcome_verdict'), "risk_params_at_fill": _td.get('risk_params_at_fill')},
                "narrative": {
                    "journal_review": dict(_td_review) if _td_review else None,
                    "thesis_outcome": dict(_td_thesis) if _td_thesis else None,
                    "llm_analysis": dict(_td_analysis) if _td_analysis else None,
                },
                "agent_critiques": [dict(e) for e in _td_events],
                "multi_tier_reviews": [dict(r) for r in (_db_query("SELECT tier, model_used, review_text, agent_commentaries, created_at FROM paper_trade_multi_reviews WHERE paper_trade_id = %s ORDER BY created_at", [_td_id]) or [])],
                "risk_actions": [dict(a) for a in _td_risk],
                "alerts": [dict(a) for a in _td_alerts],
                "proposal": dict(_td_proposal) if _td_proposal else None,
            })
        except Exception as e:
            import traceback; traceback.print_exc()
            return 500, {"ok": False, "error": str(e)}

    if base_path in ("/api/v2/automated-journal", "/api/v2/paper-journal"):
        try:
            trades = _db_query("""
                SELECT id, symbol, strategy_id, setup_type, signal_grade, score_at_entry,
                       account, opened_via, automation_source, broker_order_id, broker_status,
                       broker, client_order_id, take_profit_price, stop_loss_price,
                       entry_price, exit_price, current_price, shares, stop_loss, target_1,
                       dollar_risk, pnl, unrealized_pnl, r_multiple, pnl_pct,
                       status, outcome_verdict, exit_reason, catalyst_at_entry, catalyst_verified,
                       risk_gate_result, entry_time, exit_time, created_at, closed_at, proposal_id,
                       post_trade_analyzed, iris_curated, aegis_summarized, submitted_at, filled_at
                FROM paper_trades
                ORDER BY created_at DESC LIMIT 200
            """) or []
            # Filter: only show broker-confirmed open trades
            open_t = [t for t in trades if t.get('status') in ('open',) and (t.get('filled_at') or t.get('broker_status') == 'filled')]
            closed_t = [t for t in trades if t.get('status') == 'closed'
                        and not (t.get('close_reason') or '').startswith('phantom')
                        and not (t.get('close_reason') or '').startswith('Orphan')
                        and not (t.get('exit_reason') or '').startswith('phantom')
                        and not (t.get('exit_reason') or '').startswith('order_never_filled')]
            # Win rate: only count real trades (non-zero PnL)
            real_closed = [t for t in closed_t if (t.get('pnl') or 0) != 0]
            wins = sum(1 for t in real_closed if (t.get('pnl') or 0) > 0)
            losses = sum(1 for t in real_closed if (t.get('pnl') or 0) < 0)
            total_pnl = sum(float(t.get('pnl') or 0) for t in closed_t)
            wr = round(wins / len(real_closed), 3) if real_closed else None
            return 200, {"ok": True,
                "stats": {"closed": len(closed_t), "open": len(open_t), "wins": wins, "losses": losses,
                          "win_rate": wr, "total_pnl": round(total_pnl, 2),
                          "real_trade_count": len(real_closed)},
                "trades": [{k: _json_clean(v) for k, v in t.items()} for t in trades],
                "open_trades": [{k: _json_clean(v) for k, v in t.items()} for t in open_t],
                "closed_trades": [{k: _json_clean(v) for k, v in t.items()} for t in closed_t],
            }
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/automated-trade-journal":
        try:
            _acct = ((query or {}).get("account", ["ALPACA_PAPER"])[0]
                     if isinstance((query or {}).get("account"), list)
                     else (query or {}).get("account", "ALPACA_PAPER"))
            trades = _db_query("""
                SELECT id, symbol, strategy_id, account, entry_price, exit_price,
                       current_price, shares, stop_loss, target_1, target_2, dollar_risk, dollar_size,
                       pnl, unrealized_pnl, r_multiple, pnl_pct,
                       status, outcome_verdict, exit_reason,
                       market_regime, vix_at_entry,
                       catalyst_at_entry, catalyst_verified, intel_readiness,
                       score_at_entry, rvol_at_entry, float_m_at_entry,
                       risk_gate_result, risk_gate_reason_codes,
                       max_favorable_excursion, max_adverse_excursion,
                       planned_entry, entry_slippage, planned_stop, stop_slippage,
                       opened_via, closed_via, logged_by, notes,
                       broker_order_id, broker_status, order_type, broker, client_order_id,
                       bracket_order, take_profit_price, stop_loss_price,
                       submitted_at, filled_at, close_requested_at, close_reason, close_order_id,
                       hold_time_min, proposal_id,
                       post_trade_analyzed, iris_curated, aegis_summarized,
                       entry_time, closed_at, created_at, updated_at
                FROM paper_trades
                WHERE account = %s AND status IN ('open', 'closed')
                  AND NOT (status = 'open' AND filled_at IS NULL
                           AND broker_status NOT IN ('filled')
                           AND close_reason IS NULL)
                ORDER BY CASE WHEN status='open' THEN 0 ELSE 1 END, created_at DESC
                LIMIT 100
            """, [_acct]) or []
            # Fetch full lifecycle events per trade
            _trade_ids = [t['id'] for t in trades if t.get('id')]
            events_by_trade = {}
            if _trade_ids:
                _events = _db_query("""
                    SELECT paper_trade_id, agent_name, event_type, event_summary,
                           payload, created_at
                    FROM agent_curation_events
                    WHERE paper_trade_id = ANY(%s)
                    ORDER BY created_at ASC
                """, [_trade_ids]) or []
                for ev in _events:
                    tid = ev['paper_trade_id']
                    events_by_trade.setdefault(tid, []).append(
                        {k: _json_clean(v) for k, v in ev.items()})
            # Fetch alerts per trade
            alerts_by_trade = {}
            if _trade_ids:
                _alerts = _db_query("""
                    SELECT paper_trade_id, alert_type, severity, title, message,
                           data, created_at
                    FROM open_trade_alerts
                    WHERE paper_trade_id = ANY(%s)
                    ORDER BY created_at ASC
                """, [_trade_ids]) or []
                for al in _alerts:
                    tid = al['paper_trade_id']
                    alerts_by_trade.setdefault(tid, []).append(
                        {k: _json_clean(v) for k, v in al.items()})
            # Fetch journal reviews
            reviews_by_symbol = {}
            _syms = list({t['symbol'] for t in trades if t.get('symbol')})
            if _syms:
                _reviews = _db_query("""
                    SELECT trade_key, symbol, setup_family, setup_name, timeframe,
                           direction, entry_type, exit_type, market_regime, catalyst_type,
                           planned_r, realized_r, followed_plan, well_executed,
                           execution_quality_score, sizing_quality_score, risk_management_score,
                           confidence_before, stress_level,
                           mistake_tags, strength_tags,
                           lesson_learned, review_notes, coach_notes,
                           entry_signals, exit_signals, setup_types,
                           payload, closed_date
                    FROM journal_trade_reviews
                    WHERE symbol = ANY(%s)
                    ORDER BY closed_date DESC
                """, [_syms]) or []
                for rv in _reviews:
                    reviews_by_symbol.setdefault(rv['symbol'], []).append(
                        {k: _json_clean(v) for k, v in rv.items()})
            # Fetch Alpaca real-time data for open trades
            _alpaca_live = {}
            try:
                import os, requests as _req
                _akey = os.getenv('ALPACA_API_KEY', '')
                _asec = os.getenv('ALPACA_SECRET_KEY', '')
                if _akey and os.getenv('ENABLE_ALPACA_PAPER', 'false').lower() == 'true':
                    _hdrs = {'APCA-API-KEY-ID': _akey, 'APCA-API-SECRET-KEY': _asec}
                    _pos_resp = _req.get('https://paper-api.alpaca.markets/v2/positions', headers=_hdrs, timeout=5)
                    if _pos_resp.status_code == 200:
                        for _p in _pos_resp.json():
                            _alpaca_live[_p['symbol']] = {
                                'alpaca_qty': int(float(_p.get('qty', 0))),
                                'alpaca_avg_entry': float(_p.get('avg_entry_price', 0)),
                                'alpaca_current_price': float(_p.get('current_price', 0)),
                                'alpaca_market_value': float(_p.get('market_value', 0)),
                                'alpaca_cost_basis': float(_p.get('cost_basis', 0)),
                                'alpaca_unrealized_pl': float(_p.get('unrealized_pl', 0)),
                                'alpaca_unrealized_plpc': float(_p.get('unrealized_plpc', 0)),
                                'alpaca_intraday_pl': float(_p.get('unrealized_intraday_pl', 0)),
                                'alpaca_intraday_plpc': float(_p.get('unrealized_intraday_plpc', 0)),
                                'alpaca_lastday_price': float(_p.get('lastday_price', 0)),
                                'alpaca_change_today': float(_p.get('change_today', 0)),
                                'alpaca_side': _p.get('side', 'long'),
                            }
                    _ord_resp = _req.get('https://paper-api.alpaca.markets/v2/orders?status=open', headers=_hdrs, timeout=5)
                    if _ord_resp.status_code == 200:
                        for _o in _ord_resp.json():
                            _sym = _o['symbol']
                            if _sym not in _alpaca_live:
                                _alpaca_live[_sym] = {}
                            _alpaca_live[_sym].setdefault('alpaca_orders', []).append({
                                'order_id': _o['id'], 'type': _o.get('type'),
                                'side': _o.get('side'), 'stop_price': _o.get('stop_price'),
                                'limit_price': _o.get('limit_price'),
                                'status': _o.get('status'), 'qty': _o.get('qty'),
                            })
            except Exception:
                pass
            # Build enriched response
            enriched = []
            for t in trades:
                td = {k: _json_clean(v) for k, v in t.items()}
                td['execution_log'] = events_by_trade.get(t['id'], [])
                td['alerts'] = alerts_by_trade.get(t['id'], [])
                td['journal_reviews'] = reviews_by_symbol.get(t['symbol'], [])
                # Merge Alpaca real-time
                if t['symbol'] in _alpaca_live and t.get('status') == 'open':
                    td['alpaca'] = _alpaca_live[t['symbol']]
                enriched.append(td)
            _open = [t for t in enriched if t.get('status') == 'open']
            _closed = [t for t in enriched if t.get('status') == 'closed']
            # Analytics — only count real trades (non-zero PnL) for win rate
            _real_closed = [t for t in _closed if (t.get('pnl') or 0) != 0]
            _wins = sum(1 for t in _real_closed if (t.get('pnl') or 0) > 0)
            _losses = sum(1 for t in _real_closed if (t.get('pnl') or 0) < 0)
            _total_pnl = round(sum(float(t.get('pnl') or 0) for t in _closed), 2)
            _unrealized = round(sum(float(t.get('unrealized_pnl') or 0) for t in _open), 2)
            _avg_r = round(sum(float(t.get('r_multiple') or 0) for t in _real_closed) / max(len(_real_closed), 1), 2)
            _by_strategy = {}
            for t in _closed:
                s = t.get('strategy_id', 'unknown')
                _by_strategy.setdefault(s, {'count': 0, 'pnl': 0, 'wins': 0})
                _by_strategy[s]['count'] += 1
                _by_strategy[s]['pnl'] += float(t.get('pnl') or 0)
                if (t.get('pnl') or 0) > 0:
                    _by_strategy[s]['wins'] += 1
            return 200, {"ok": True, "account": _acct,
                "trades": enriched, "open": _open, "closed": _closed,
                "summary": {
                    "open_count": len(_open), "closed_count": len(_closed),
                    "total_pnl": _total_pnl, "unrealized_pnl": _unrealized,
                    "wins": _wins, "losses": _losses,
                    "win_rate": round(_wins / max(len(_real_closed), 1) * 100, 1),
                    "real_trade_count": len(_real_closed),
                    "avg_r": _avg_r,
                    "by_strategy": [{**v, 'strategy': k, 'win_rate': round(v['wins']/max(v['count'],1)*100,1)}
                                    for k, v in _by_strategy.items()],
                },
                "alpaca_connected": bool(_alpaca_live),
                "integrity_warnings": _journal_integrity_warnings(),
            }
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/automated-journal-analytics":
        try:
            _acct = ((query or {}).get("account", ["ALPACA_PAPER"])[0]
                     if isinstance((query or {}).get("account"), list)
                     else (query or {}).get("account", "ALPACA_PAPER"))
            # Daily P&L for calendar heatmap + equity curve
            _daily = _db_query("""
                SELECT closed_at::date as trade_date,
                       COUNT(*) as trades,
                       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
                       ROUND(SUM(pnl)::numeric, 2) as daily_pnl,
                       ROUND(AVG(pnl)::numeric, 2) as avg_pnl,
                       ROUND(AVG(r_multiple)::numeric, 2) as avg_r
                FROM paper_trades
                WHERE account = %s AND status = 'closed' AND closed_at IS NOT NULL
                GROUP BY closed_at::date
                ORDER BY closed_at::date
            """, [_acct]) or []
            # Monthly summary
            _monthly = _db_query("""
                SELECT TO_CHAR(closed_at, 'YYYY-MM') as month,
                       COUNT(*) as trades,
                       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
                       ROUND(SUM(pnl)::numeric, 2) as total_pnl,
                       ROUND(AVG(pnl)::numeric, 2) as avg_pnl,
                       ROUND(AVG(r_multiple)::numeric, 2) as avg_r,
                       ROUND(MAX(pnl)::numeric, 2) as best_trade,
                       ROUND(MIN(pnl)::numeric, 2) as worst_trade
                FROM paper_trades
                WHERE account = %s AND status = 'closed' AND closed_at IS NOT NULL
                GROUP BY TO_CHAR(closed_at, 'YYYY-MM')
                ORDER BY month
            """, [_acct]) or []
            # Weekly summary
            _weekly = _db_query("""
                SELECT TO_CHAR(date_trunc('week', closed_at), 'YYYY-MM-DD') as week_start,
                       COUNT(*) as trades,
                       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                       ROUND(SUM(pnl)::numeric, 2) as total_pnl,
                       ROUND(AVG(r_multiple)::numeric, 2) as avg_r
                FROM paper_trades
                WHERE account = %s AND status = 'closed' AND closed_at IS NOT NULL
                GROUP BY date_trunc('week', closed_at)
                ORDER BY week_start
            """, [_acct]) or []
            # Build equity curve (cumulative P&L)
            _cumulative = 0
            _equity_curve = []
            for d in _daily:
                _cumulative += float(d.get('daily_pnl') or 0)
                _equity_curve.append({
                    'date': str(d['trade_date']),
                    'daily_pnl': float(d.get('daily_pnl') or 0),
                    'cumulative_pnl': round(_cumulative, 2),
                    'trades': d.get('trades', 0),
                    'wins': d.get('wins', 0),
                    'losses': d.get('losses', 0),
                })
            # Unrealized equity (open positions)
            _open_pnl = _db_query("""
                SELECT ROUND(SUM(unrealized_pnl)::numeric, 2) as total
                FROM paper_trades WHERE account = %s AND status = 'open'
            """, [_acct], fetch="one") or {}
            return 200, {"ok": True, "account": _acct,
                "daily": [{k: _json_clean(v) for k, v in d.items()} for d in _daily],
                "equity_curve": _equity_curve,
                "monthly": [{k: _json_clean(v) for k, v in m.items()} for m in _monthly],
                "weekly": [{k: _json_clean(v) for k, v in w.items()} for w in _weekly],
                "current_equity": round(_cumulative + float(_open_pnl.get('total') or 0), 2),
                "realized_total": round(_cumulative, 2),
                "unrealized_total": float(_open_pnl.get('total') or 0),
            }
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/paper-automation-performance":
        try:
            by_source = _db_query("""
                SELECT COALESCE(opened_via, 'unknown') as source,
                    COUNT(*) FILTER (WHERE status='closed') as closed,
                    COUNT(*) FILTER (WHERE status='closed' AND pnl > 0) as wins,
                    ROUND(SUM(pnl) FILTER (WHERE status='closed')::numeric, 2) as pnl
                FROM paper_trades GROUP BY opened_via
            """) or []
            overall = _db_query("""
                SELECT COUNT(*) FILTER (WHERE status='closed') as closed_trades,
                    COUNT(*) FILTER (WHERE status='closed' AND pnl > 0) as wins,
                    ROUND(SUM(pnl) FILTER (WHERE status='closed')::numeric, 2) as total_pnl
                FROM paper_trades
            """, fetch="one") or {}
            tc = overall.get('closed_trades') or 0
            w = overall.get('wins') or 0
            overall['win_rate'] = round(w / tc, 3) if tc > 0 else None
            return 200, {"ok": True,
                "overall": {k: _json_clean(v) for k, v in overall.items()},
                "by_opened_via": [{k: _json_clean(v) for k, v in r.items()} for r in by_source],
            }
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/strategy-cards":
        try:
            sym_filter = (query or {}).get("symbol", [""])[0] if isinstance((query or {}).get("symbol"), list) else (query or {}).get("symbol", "")
            where = "WHERE symbol = %s" if sym_filter else ""
            params = [sym_filter] if sym_filter else []
            rows = _db_query(f"""
                SELECT id, symbol, strategy_id, setup_type, grade, score,
                       confidence, recommendation, recommendation_reason,
                       risk_gate_result, risk_gate_reason_codes,
                       required_evidence_present, missing_evidence,
                       disqualifiers, agent_votes, account_fit,
                       final_action, explanation, created_at
                FROM strategy_cards
                {where}
                ORDER BY created_at DESC LIMIT 100""", params) or []
            return 200, {"ok": True,
                "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows],
                "count": len(rows)}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/strategy-signals":
        try:
            rows = _db_query("""
                SELECT id, strategy_id, symbol, signal_type, signal_grade,
                       signal_score, price, rvol, float_m, gap_pct,
                       catalyst, catalyst_verified, status, fired_at
                FROM strategy_signals
                WHERE fired_at > NOW() - INTERVAL '48 hours'
                ORDER BY signal_score DESC NULLS LAST
                LIMIT 100""") or []
            by_strategy = _db_query("""
                SELECT strategy_id, COUNT(*) as count,
                       COUNT(CASE WHEN signal_grade='A+' THEN 1 END) as aplus
                FROM strategy_signals
                WHERE fired_at > NOW() - INTERVAL '48 hours'
                GROUP BY strategy_id""") or []
            return 200, {"ok": True,
                "signals": [{k: _json_clean(v) for k, v in r.items()} for r in rows],
                "by_strategy": {r["strategy_id"]: {"count": r["count"], "aplus": r["aplus"]} for r in by_strategy},
                "total": len(rows)}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # POST: system-controls update
    if method == "POST" and base_path == "/api/v2/system-controls":
        try:
            body = body or {}
            key = body.get("key", "")
            value = body.get("value", "")
            updated_by = body.get("updated_by", "api")
            allowed_keys = {
                'halt_all_trading', 'halt_live_only',
                'halt_momentum_scalp_strategy', 'halt_gap_and_go_strategy',
                'halt_swing_breakout_strategy', 'halt_sector_rotation_strategy',
                'halt_earnings_catalyst_strategy', 'halt_income_add_strategy',
            }
            if key not in allowed_keys:
                return 400, {"ok": False, "error": f"Invalid key: {key}. Allowed: {sorted(allowed_keys)}"}
            if value not in ('true', 'false'):
                return 400, {"ok": False, "error": "Value must be 'true' or 'false'"}
            from db_adapter import _execute as _db_exec
            _db_exec("""
                UPDATE system_controls SET value = %s, updated_at = NOW(), updated_by = %s
                WHERE key = %s
            """, [value, updated_by, key])
            _db_exec("""
                INSERT INTO audit_log (event_type, decision, reason_text, actor)
                VALUES (%s, %s, %s, %s)
            """, ['halt' if value == 'true' else 'resume', key, f'{key} set to {value}', updated_by])
            return 200, {"ok": True, "data": {"key": key, "value": value, "updated_by": updated_by}}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Session 27: Paper outcomes, governance run, dashboard summary ────

    if method == "GET" and base_path == "/api/v2/paper-outcomes":
        try:
            rows = _db_query("""
                SELECT * FROM trade_thesis_outcomes ORDER BY created_at DESC LIMIT 50
            """) or []
            open_count = _db_query("""
                SELECT COUNT(*) as cnt FROM paper_trades
                WHERE status NOT IN ('closed', 'cancelled', 'filled')
            """, fetch="one") or {}
            closed_count = _db_query("""
                SELECT COUNT(*) as cnt FROM paper_trades
                WHERE status IN ('closed', 'filled')
            """, fetch="one") or {}
            return 200, {"ok": True,
                "outcomes": [{k: _json_clean(v) for k, v in r.items()} for r in rows],
                "open_paper_trades": open_count.get('cnt', 0),
                "closed_paper_trades": closed_count.get('cnt', 0)}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-outcomes/run":
        try:
            import subprocess as _sp
            r = _sp.run([str(PROJECT_ROOT / ".venv/bin/python"),
                         str(PROJECT_ROOT / "scripts/post_trade_thesis_reviewer.py"), "--apply"],
                        capture_output=True, text=True, timeout=60, cwd=str(PROJECT_ROOT))
            return 200, {"ok": True, "output": r.stdout[-2000:], "returncode": r.returncode}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-performance-governance/run":
        try:
            import subprocess as _sp
            r = _sp.run([str(PROJECT_ROOT / ".venv/bin/python"),
                         str(PROJECT_ROOT / "scripts/paper_performance_governance.py"), "--apply"],
                        capture_output=True, text=True, timeout=60, cwd=str(PROJECT_ROOT))
            return 200, {"ok": True, "output": r.stdout[-2000:], "returncode": r.returncode}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "GET" and base_path == "/api/v2/paper-dashboard-summary":
        try:
            open_pt = _db_query("SELECT COUNT(*) as cnt FROM paper_trades WHERE status NOT IN ('closed','cancelled','filled')", fetch="one") or {}
            closed_pt = _db_query("SELECT COUNT(*) as cnt FROM paper_trades WHERE status IN ('closed','filled')", fetch="one") or {}
            eq_rows = _db_query("SELECT COUNT(*) as cnt FROM paper_execution_quality", fetch="one") or {}
            recon_issues = _db_query("SELECT COUNT(*) as cnt FROM broker_reconciliation_items WHERE severity IN ('WARN','ERROR','CRITICAL')", fetch="one") or {}
            outcome_rows = _db_query("SELECT COUNT(*) as cnt FROM trade_thesis_outcomes", fetch="one") or {}
            strats_learning = _db_query("SELECT COUNT(DISTINCT strategy_id) as cnt FROM paper_trade_proposals WHERE status='PENDING'", fetch="one") or {}
            last_recon = _db_query("SELECT MAX(created_at) as ts FROM broker_reconciliation_runs", fetch="one") or {}
            last_tca = _db_query("SELECT MAX(created_at) as ts FROM paper_execution_quality", fetch="one") or {}
            return 200, {"ok": True, "summary": {
                "open_paper_trades": open_pt.get('cnt', 0),
                "closed_paper_trades": closed_pt.get('cnt', 0),
                "execution_quality_rows": eq_rows.get('cnt', 0),
                "reconciliation_issues": recon_issues.get('cnt', 0),
                "outcome_reviews": outcome_rows.get('cnt', 0),
                "strategies_in_learning_mode": strats_learning.get('cnt', 0),
                "live_eligible_strategies": 0,
                "last_reconciliation": _json_clean(last_recon.get('ts')),
                "last_tca_run": _json_clean(last_tca.get('ts')),
            }}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Session 28: Paper execution workflow endpoints ──────────────────

    if method == "GET" and base_path == "/api/v2/paper-submit-candidates":
        try:
            import subprocess as _sp
            r = _sp.run([str(PROJECT_ROOT / ".venv/bin/python"),
                         str(PROJECT_ROOT / "scripts/paper_submit_readiness.py"),
                         "--best-candidates", "--limit", "5"],
                        capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT))
            try:
                data = json.loads(r.stdout) if r.stdout else {}
            except Exception:
                data = {"raw": r.stdout[-500:] if r.stdout else ""}
            return 200, {"ok": True, "data": data}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/check-submit-readiness":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            if not pid:
                return 400, {"ok": False, "error": "proposal_id required"}
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from paper_submit_readiness import check_readiness, get_db as _get_readiness_db
            conn = _get_readiness_db()
            try:
                result = check_readiness(conn, int(pid))
                return 200, {"ok": True, "data": result}
            finally:
                conn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/dry-run-submit":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            if not pid:
                return 400, {"ok": False, "error": "proposal_id required"}
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from proposal_paper_submitter import dry_run_bracket
            from session13_db import get_conn
            conn = get_conn()
            try:
                result = dry_run_bracket(conn, int(pid))
                return 200, {"ok": True, "data": result}
            finally:
                conn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-proposals/submit-paper":
        try:
            body = body or {}
            pid = body.get('proposal_id')
            if not pid:
                return 400, {"ok": False, "error": "proposal_id required"}
            # Safety: verify ALPACA_MODE=paper
            import os as _os
            if _os.getenv("ALPACA_MODE", "paper").lower() != "paper":
                return 400, {"ok": False, "error": "BLOCKED: ALPACA_MODE is not paper"}
            # Verify proposal exists and is PENDING
            row = _db_query("SELECT status FROM paper_trade_proposals WHERE id=%s",
                            [int(pid)], fetch="one")
            if not row:
                return 404, {"ok": False, "error": f"Proposal {pid} not found"}
            if row.get("status") != "PENDING":
                return 400, {"ok": False, "error": f"Proposal {pid} is {row['status']}, not PENDING"}
            # Run via subprocess for isolation
            import subprocess as _sp
            r = _sp.run([str(PROJECT_ROOT / ".venv/bin/python3"),
                         str(PROJECT_ROOT / "scripts/proposal_paper_submitter.py"),
                         "--proposal-id", str(pid), "--submit-paper-bracket",
                         "--allow-after-hours-paper"],
                        capture_output=True, text=True, timeout=60, cwd=str(PROJECT_ROOT))
            try:
                data = json.loads(r.stdout) if r.stdout else {}
            except Exception:
                data = {"raw": r.stdout[-1000:] if r.stdout else "", "stderr": r.stderr[-500:] if r.stderr else ""}
            return 200, {"ok": True, "data": data, "returncode": r.returncode}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "GET" and base_path == "/api/v2/paper-execution-events":
        try:
            rows = _db_query("""
                SELECT id, paper_trade_id, symbol, event_type, event_source,
                       payload, created_at
                FROM paper_execution_events
                ORDER BY created_at DESC LIMIT 100
            """) or []
            return 200, {"ok": True, "events": [
                {k: _json_clean(v) for k, v in r.items()} for r in rows
            ]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-trades/monitor":
        try:
            import subprocess as _sp
            r = _sp.run([str(PROJECT_ROOT / ".venv/bin/python"),
                         str(PROJECT_ROOT / "scripts/paper_trade_monitor.py"), "--apply"],
                        capture_output=True, text=True, timeout=60, cwd=str(PROJECT_ROOT))
            try:
                data = json.loads(r.stdout) if r.stdout else {}
            except Exception:
                data = {"raw": r.stdout[-1000:] if r.stdout else ""}
            return 200, {"ok": True, "data": data, "returncode": r.returncode}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if method == "POST" and base_path == "/api/v2/paper-trades/close":
        try:
            body = body or {}
            ptid = body.get('paper_trade_id')
            reason = body.get('reason', 'manual_close_via_ui')
            if not ptid:
                return 400, {"ok": False, "error": "paper_trade_id required"}
            import os as _os
            if _os.getenv("ALPACA_MODE", "paper").lower() != "paper":
                return 400, {"ok": False, "error": "BLOCKED: ALPACA_MODE is not paper"}
            import subprocess as _sp
            r = _sp.run([str(PROJECT_ROOT / ".venv/bin/python"),
                         str(PROJECT_ROOT / "scripts/paper_trade_closer.py"),
                         "--paper-trade-id", str(ptid),
                         "--close-paper", "--reason", reason],
                        capture_output=True, text=True, timeout=120, cwd=str(PROJECT_ROOT))
            try:
                data = json.loads(r.stdout) if r.stdout else {}
            except Exception:
                data = {"raw": r.stdout[-1000:] if r.stdout else ""}
            return 200, {"ok": True, "data": data, "returncode": r.returncode}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ══════════════════════════════════════════════════════════════════
    # TOPIC MONITOR — CRUD + research trigger + transcript review
    # ══════════════════════════════════════════════════════════════════

    if base_path == "/api/v2/topics":
        if method == "GET":
            try:
                rows = _db_query("""
                    SELECT t.*,
                        (SELECT COUNT(*) FROM news_articles
                         WHERE strategy_type = t.topic_id
                         AND created_at > NOW() - INTERVAL '1 day' * t.max_age_days) as article_count,
                        (SELECT COUNT(*) FROM youtube_transcripts
                         WHERE added_by = 'topic_ingestion'
                         AND ingested_at > NOW() - INTERVAL '1 day' * t.max_age_days
                         AND (strategy_tags::text LIKE '%%' || t.topic_id || '%%'
                              OR title ILIKE '%%' || REPLACE(t.topic_id, '_', ' ') || '%%')) as transcript_count,
                        (SELECT COUNT(*) FROM blocked_content
                         WHERE topic_id = t.topic_id) as blocked_count
                    FROM topic_monitor t
                    ORDER BY t.priority, t.topic_id
                """) or []
                return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

        if method == "POST":
            try:
                topic_id = (body or {}).get("topic_id", "").strip().lower().replace(" ", "_")
                if not topic_id:
                    return 400, {"ok": False, "error": "topic_id required"}
                display = (body or {}).get("display_name", topic_id.replace("_", " ").title())
                search_q = (body or {}).get("search_queries", [])
                video_q = (body or {}).get("video_queries", [])
                priority = int((body or {}).get("priority", 5))
                agent_owner = (body or {}).get("agent_owner", "Alex")
                agent_tags = (body or {}).get("agent_tags", [agent_owner])
                strategy_tags = (body or {}).get("strategy_tags", [])
                personal_ctx = (body or {}).get("personal_context", "")
                saved_urls = (body or {}).get("saved_search_urls", [])

                _db_write("""
                    INSERT INTO topic_monitor
                        (topic_id, display_name, search_queries, video_queries,
                         priority, agent_owner, agent_tags, strategy_tags,
                         personal_context, saved_search_urls)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (topic_id) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        search_queries = EXCLUDED.search_queries,
                        video_queries = EXCLUDED.video_queries,
                        priority = EXCLUDED.priority,
                        agent_owner = EXCLUDED.agent_owner,
                        agent_tags = EXCLUDED.agent_tags,
                        strategy_tags = EXCLUDED.strategy_tags,
                        personal_context = EXCLUDED.personal_context,
                        saved_search_urls = EXCLUDED.saved_search_urls,
                        updated_at = NOW()
                """, (topic_id, display, json.dumps(search_q), json.dumps(video_q),
                      priority, agent_owner, json.dumps(agent_tags), json.dumps(strategy_tags),
                      personal_ctx, json.dumps(saved_urls)))
                return 200, {"ok": True, "topic_id": topic_id}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/topics/add-url":
        if method == "POST":
            try:
                topic_id = (body or {}).get("topic_id")
                url = (body or {}).get("url", "").strip()
                if not topic_id or not url:
                    return 400, {"ok": False, "error": "topic_id and url required"}
                _db_write("""
                    UPDATE topic_monitor
                    SET saved_search_urls = saved_search_urls || %s::jsonb,
                        updated_at = NOW()
                    WHERE topic_id = %s
                """, (json.dumps([url]), topic_id))
                return 200, {"ok": True, "topic_id": topic_id, "url": url}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/topics/run":
        if method == "POST":
            try:
                topic_id = (body or {}).get("topic_id")
                curate = (body or {}).get("curate", False)
                import subprocess
                cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "topic_ingestion.py")]
                if topic_id:
                    cmd.extend(["--topic", topic_id])
                if curate:
                    cmd.append("--curate")
                r = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     cwd=str(PROJECT_ROOT), text=True)
                return 200, {"ok": True, "message": f"Topic ingestion started (pid {r.pid})",
                             "topic_id": topic_id or "all"}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/topics/transcripts":
        if method == "GET":
            try:
                topic_id = (query or {}).get("topic_id", "")
                status_filter = (query or {}).get("rag_status", "")
                sql = """
                    SELECT yt.id, yt.video_id, yt.title, yt.channel_name,
                           yt.url, yt.quality_score, yt.relevance_score,
                           yt.rag_status, yt.rag_reason, yt.validation_status,
                           yt.added_by, yt.ingested_at,
                           LEFT(yt.summary, 300) as summary,
                           LEFT(yt.transcript_text, 500) as preview,
                           yt.strategy_tags, yt.agent_tags
                    FROM youtube_transcripts yt
                    WHERE yt.added_by = 'topic_ingestion'
                """
                params = []
                if topic_id:
                    sql += " AND (yt.strategy_tags::text LIKE %s OR yt.title ILIKE %s)"
                    params.extend([f'%{topic_id}%', f'%{topic_id.replace("_", " ")}%'])
                if status_filter:
                    sql += " AND yt.rag_status = %s"
                    params.append(status_filter)
                sql += " ORDER BY yt.ingested_at DESC LIMIT 200"
                rows = _db_query(sql, params) or []
                return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/topics/transcripts/review":
        if method == "POST":
            try:
                transcript_id = (body or {}).get("id")
                video_id = (body or {}).get("video_id")
                rag_status = (body or {}).get("rag_status")
                rag_reason = (body or {}).get("rag_reason", "")
                if not rag_status or rag_status not in ("approved", "low_quality", "blocked", "pending"):
                    return 400, {"ok": False, "error": "rag_status must be approved/low_quality/blocked/pending"}
                if transcript_id:
                    _db_write("UPDATE youtube_transcripts SET rag_status=%s, rag_reason=%s WHERE id=%s",
                              (rag_status, rag_reason, transcript_id))
                elif video_id:
                    _db_write("UPDATE youtube_transcripts SET rag_status=%s, rag_reason=%s WHERE video_id=%s",
                              (rag_status, rag_reason, video_id))
                else:
                    return 400, {"ok": False, "error": "id or video_id required"}
                if rag_status == "blocked" and video_id:
                    _db_write("""
                        INSERT INTO blocked_content (content_type, content_id, title, reason, blocked_by)
                        VALUES ('youtube', %s, '', %s, 'operator')
                        ON CONFLICT (content_type, content_id) DO NOTHING
                    """, (video_id, rag_reason or "Operator blocked"))
                return 200, {"ok": True}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/topics/articles":
        if method == "GET":
            try:
                topic_id = (query or {}).get("topic_id", "")
                sql = """
                    SELECT id, symbol as topic_id, title, summary, source,
                           source_url, relevance_score, rag_status, rag_reason,
                           strategy_tags, agent_tags, created_at
                    FROM news_articles WHERE source LIKE 'topic_%%'
                """
                params = []
                if topic_id:
                    sql += " AND strategy_type = %s"
                    params.append(topic_id)
                sql += " ORDER BY created_at DESC LIMIT 200"
                rows = _db_query(sql, params) or []
                return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/topics/blocked":
        if method == "GET":
            try:
                rows = _db_query("SELECT * FROM blocked_content ORDER BY created_at DESC LIMIT 200") or []
                return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        if method == "DELETE":
            try:
                bc_id = (body or {}).get("id")
                if bc_id:
                    _db_write("DELETE FROM blocked_content WHERE id=%s", (bc_id,))
                return 200, {"ok": True}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/topics/gap-fills":
        if method == "GET":
            try:
                rows = _db_query("""
                    SELECT topic_id, source, query_used, results_found,
                           articles_saved, transcripts_saved, llm_normalized,
                           search_time_ms, created_at
                    FROM iris_library_gap_fills ORDER BY created_at DESC LIMIT 100
                """) or []
                return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/topics/delete":
        if method == "POST":
            try:
                topic_id = (body or {}).get("topic_id")
                if not topic_id:
                    return 400, {"ok": False, "error": "topic_id required"}
                _db_write("UPDATE topic_monitor SET enabled=false, updated_at=NOW() WHERE topic_id=%s", (topic_id,))
                return 200, {"ok": True, "topic_id": topic_id}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    # Entity links: what tickers/topics/sectors are linked to topic content
    if base_path == "/api/v2/topics/entities":
        if method == "GET":
            try:
                entity_type = (query or {}).get("type", "")
                entity_value = (query or {}).get("value", "")
                topic_id = (query or {}).get("topic_id", "")
                sql = """
                    SELECT cel.entity_type, cel.entity_value,
                           COUNT(*) as link_count,
                           MAX(na.created_at) as latest
                    FROM content_entity_links cel
                    JOIN news_articles na ON cel.content_type='news_article' AND cel.content_id=na.id
                    WHERE 1=1
                """
                params = []
                if entity_type:
                    sql += " AND cel.entity_type = %s"
                    params.append(entity_type)
                if entity_value:
                    sql += " AND cel.entity_value = %s"
                    params.append(entity_value)
                if topic_id:
                    sql += " AND na.strategy_type = %s"
                    params.append(topic_id)
                sql += " GROUP BY cel.entity_type, cel.entity_value ORDER BY link_count DESC LIMIT 100"
                rows = _db_query(sql, params) or []
                return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    # Ticker intelligence: get all topic content linked to a specific ticker
    if base_path.startswith("/api/v2/topics/by-ticker/"):
        ticker = base_path.split("/")[-1].upper()
        if method == "GET":
            try:
                rows = _db_query("""
                    SELECT na.id, na.title, na.summary, na.source, na.strategy_type as topic,
                           na.relevance_score, na.rag_status, na.created_at,
                           cel.entity_type, cel.confidence
                    FROM content_entity_links cel
                    JOIN news_articles na ON cel.content_type='news_article' AND cel.content_id=na.id
                    WHERE cel.entity_value = %s
                    ORDER BY na.created_at DESC LIMIT 50
                """, (ticker,)) or []
                return 200, {"ok": True, "ticker": ticker,
                             "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    # Topic curation feedback: learning loop history
    if base_path == "/api/v2/topics/curation-feedback":
        if method == "GET":
            try:
                rows = _db_query("""
                    SELECT topic_id, run_date, articles_reviewed, approved_count,
                           blocked_count, tickers_extracted, suggested_queries,
                           quality_summary
                    FROM topic_curation_feedback ORDER BY run_date DESC LIMIT 50
                """) or []
                return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    # Run curator manually from UI
    if base_path == "/api/v2/topics/curate":
        if method == "POST":
            try:
                topic_id = (body or {}).get("topic_id")
                import subprocess
                cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "topic_curator.py"),
                       "--improve-queries"]
                if topic_id:
                    cmd.extend(["--topic", topic_id])
                r = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     cwd=str(PROJECT_ROOT), text=True)
                return 200, {"ok": True, "message": f"Curator started (pid {r.pid})"}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    # ── Pipeline Controller endpoints ─────────────────────────────────────
    if base_path == "/api/v2/pipeline-controller/status":
        try:
            run = _db_query("SELECT run_id, pipeline_key, status, run_label, trigger_source, started_at, finished_at, duration_seconds, summary FROM pipeline_runs ORDER BY created_at DESC LIMIT 1", fetch="one")
            if not run:
                return 200, {"ok": True, "data": None, "message": "No runs yet"}
            return 200, {"ok": True, "data": {k: _json_clean(v) for k, v in run.items()}}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/pipeline-controller/runs":
        try:
            limit = int((query or {}).get("limit", 20))
            rows = _db_query("SELECT run_id, pipeline_key, status, run_label, started_at, finished_at, duration_seconds, summary FROM pipeline_runs ORDER BY created_at DESC LIMIT %s", (limit,)) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.startswith("/api/v2/pipeline-controller/runs/") and base_path.endswith("/stages"):
        run_id = base_path.split("/")[-2]
        try:
            rows = _db_query("""
                SELECT stage_key, status, attempt, duration_seconds, exit_code,
                       error_type, error_message, sla_status, stdout_tail, dependency_blockers,
                       started_at, finished_at
                FROM pipeline_stage_runs WHERE run_id=%s
                ORDER BY created_at
            """, (run_id,)) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.startswith("/api/v2/pipeline-controller/runs/") and not base_path.endswith("/stages"):
        run_id = base_path.split("/")[-1]
        try:
            run = _db_query("SELECT * FROM pipeline_runs WHERE run_id=%s", (run_id,), fetch="one")
            if not run:
                return 404, {"ok": False, "error": "Run not found"}
            return 200, {"ok": True, "data": {k: _json_clean(v) for k, v in run.items()}}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/pipeline-controller/stages":
        try:
            rows = _db_query("""
                SELECT stage_key, group_key, name, command, timeout_seconds,
                       sla_seconds, can_degrade, active, sort_order
                FROM pipeline_stages WHERE pipeline_key='daily' AND active=true
                ORDER BY sort_order
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/pipeline-controller/failures":
        try:
            rows = _db_query("""
                SELECT psr.run_id, psr.stage_key, psr.status, psr.error_message,
                       psr.exit_code, psr.duration_seconds, psr.sla_status,
                       psr.stdout_tail, psr.attempt, psr.started_at
                FROM pipeline_stage_runs psr
                WHERE psr.status IN ('failed', 'degraded')
                ORDER BY psr.created_at DESC LIMIT 50
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── POST: Retry failed stages for a run ─────────────────────────────
    if base_path.startswith("/api/v2/pipeline-controller/runs/") and base_path.endswith("/retry-failed") and method == "POST":
        try:
            parts = base_path.split("/")
            run_id = parts[5]  # /api/v2/pipeline-controller/runs/<run_id>/retry-failed
            # Check run exists
            run = _db_query("SELECT run_id, status FROM pipeline_runs WHERE run_id=%s", (run_id,), fetch="one")
            if not run:
                return 404, {"ok": False, "error": f"Run {run_id} not found"}
            # Find failed stages
            failed = _db_query("""
                SELECT stage_key, status, error_message, attempt
                FROM pipeline_stage_runs
                WHERE run_id=%s AND status IN ('failed', 'degraded')
                ORDER BY created_at
            """, (run_id,)) or []
            if not failed:
                return 200, {"ok": True, "message": "No failed stages to retry", "retried": []}
            # Mark failed stages as pending for retry (does not auto-execute)
            retried = []
            for f in failed:
                _db_write("""
                    UPDATE pipeline_stage_runs SET status='pending', updated_at=now()
                    WHERE run_id=%s AND stage_key=%s AND status IN ('failed', 'degraded')
                """, (run_id, f['stage_key']))
                retried.append(f['stage_key'])
            return 200, {"ok": True, "message": f"Marked {len(retried)} stage(s) for retry", "retried": retried,
                         "note": "Run pipeline_controller.py --resume to execute retries"}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Discovery Source Health endpoints ──────────────────────────────────
    if base_path == "/api/v2/discovery-source-health":
        try:
            rows = _db_query("""
                SELECT source_key, status, last_success_at, last_failure_at,
                       last_row_count, failure_count, last_error, degraded, updated_at
                FROM data_source_health ORDER BY source_key
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/candidate-discovery/recent":
        try:
            limit = int((query or {}).get("limit", 50))
            rows = _db_query("""
                SELECT event_id, source_key, symbol, source_confidence,
                       normalized_payload, degraded, reason, created_at
                FROM candidate_discovery_events
                ORDER BY created_at DESC LIMIT %s
            """, (limit,)) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Paper Validation Status endpoint ──────────────────────────────────
    if base_path == "/api/v2/paper-validation-status":
        try:
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from live_trading_gate import evaluate
            result = evaluate()
            return 200, {"ok": True, "data": {k: _json_clean(v) if not isinstance(v, (dict, list, bool)) else v for k, v in result.items()}}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── System Facts endpoint ─────────────────────────────────────────────
    if base_path == "/api/v2/system-facts":
        try:
            facts_path = PROJECT_ROOT / "data" / "system_facts.json"
            if facts_path.exists():
                facts = json.loads(facts_path.read_text())
                return 200, {"ok": True, "data": facts}
            return 200, {"ok": True, "data": None, "message": "No facts generated yet"}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/system-fact-drift":
        try:
            drift_path = PROJECT_ROOT / "data" / "system_fact_drift.json"
            if drift_path.exists():
                drift = json.loads(drift_path.read_text())
                return 200, {"ok": True, "data": drift}
            return 200, {"ok": True, "data": []}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Session 27: Paper Order Modification Proposals ───────────────────
    if base_path == "/api/v2/paper-order-modifications":
        try:
            status_filter = (query or {}).get("status", "proposed")
            rows = _db_query("""
                SELECT proposal_id, paper_trade_id, symbol, action,
                       current_stop, proposed_stop, current_limit, proposed_limit,
                       reason, confidence, status, admin_decision, approved_by,
                       approved_at, executed_at, error_message, expires_at, created_at
                FROM paper_order_modification_proposals
                WHERE status = %s OR %s = 'all'
                ORDER BY created_at DESC LIMIT 50
            """, (status_filter, status_filter)) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.startswith("/api/v2/paper-order-modifications/") and not base_path.endswith("/approve") and not base_path.endswith("/reject") and not base_path.endswith("/execute"):
        try:
            pid = base_path.split("/")[-1]
            row = _db_query("SELECT * FROM paper_order_modification_proposals WHERE proposal_id=%s",
                            (pid,), fetch="one")
            if not row:
                return 404, {"ok": False, "error": "Proposal not found"}
            return 200, {"ok": True, "data": {k: _json_clean(v) for k, v in row.items()}}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.startswith("/api/v2/paper-order-modifications/") and base_path.endswith("/approve") and method == "POST":
        try:
            pid = base_path.split("/")[-2]
            reason = (body or {}).get("reason", "approved_via_api")
            approved_by = (body or {}).get("approved_by", "admin")
            _db_write("""UPDATE paper_order_modification_proposals
                         SET status='approved', admin_decision='approve', admin_reason=%s,
                             approved_by=%s, approved_at=now(), updated_at=now()
                         WHERE proposal_id=%s AND status='proposed'""",
                      (reason, approved_by, pid))
            return 200, {"ok": True, "message": f"Proposal {pid} approved"}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.startswith("/api/v2/paper-order-modifications/") and base_path.endswith("/reject") and method == "POST":
        try:
            pid = base_path.split("/")[-2]
            reason = (body or {}).get("reason", "rejected_via_api")
            _db_write("""UPDATE paper_order_modification_proposals
                         SET status='rejected', admin_decision='reject', admin_reason=%s,
                             rejected_at=now(), updated_at=now()
                         WHERE proposal_id=%s AND status='proposed'""",
                      (reason, pid))
            return 200, {"ok": True, "message": f"Proposal {pid} rejected"}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.startswith("/api/v2/paper-order-modifications/") and base_path.endswith("/execute") and method == "POST":
        try:
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from open_trade_manager import execute_approved
            pid = base_path.split("/")[-2]
            from session13_db import get_conn as _s27_conn
            econn = _s27_conn()
            try:
                result = execute_approved(econn, pid)
                return 200, {"ok": result.get("status") == "executed", "data": result}
            finally:
                econn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Session 27: Paper Outcome Analytics ────────────────────────────────
    if base_path == "/api/v2/paper-outcome-analytics":
        try:
            rows = _db_query("""
                SELECT paper_trade_id, symbol, strategy_id, pnl, pnl_pct, r_multiple,
                       entry_price, exit_price, stop_price, target_price,
                       exit_reason, tca_grade, outcome_verdict, hold_minutes,
                       stop_adjusted_count, limit_adjusted_count, opened_at, closed_at
                FROM paper_trade_outcome_analytics ORDER BY closed_at DESC NULLS LAST LIMIT 50
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/paper-tca":
        try:
            rows = _db_query("""
                SELECT paper_trade_id, symbol, event_type, expected_price, actual_price,
                       slippage_abs, slippage_bps, quality_grade, created_at
                FROM paper_execution_quality_events ORDER BY created_at DESC LIMIT 50
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/paper-broker-reconciliation":
        try:
            rows = _db_query("""
                SELECT run_id, status, alpaca_mode, db_open_trades, broker_open_positions,
                       broker_open_orders, matched_positions, unmatched_db_trades,
                       unmatched_broker_positions, unmatched_orders, started_at, finished_at
                FROM paper_broker_reconciliation_runs ORDER BY created_at DESC LIMIT 20
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/open-trade-intelligence":
        try:
            rows = _db_query("""
                SELECT DISTINCT ON (paper_trade_id) paper_trade_id, symbol,
                       current_price, entry_price, stop_price, limit_price,
                       unrealized_pnl, unrealized_pnl_pct, r_multiple,
                       distance_to_stop_pct, distance_to_target_pct,
                       rsi, atr, volume_ratio, trend_state,
                       news_risk_score, intelligence_summary, snapshot_time
                FROM open_trade_intelligence_snapshots
                ORDER BY paper_trade_id, snapshot_time DESC
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Session 27B: Execution Revalidation endpoints ─────────────────
    if base_path == "/api/v2/paper-execution-rechecks":
        try:
            rows = _db_query("""
                SELECT recheck_id, paper_trade_proposal_id, symbol, trigger_type,
                       status, execution_readiness_score, material_change_detected,
                       material_change_reasons, price_drift_pct, market_session,
                       requires_reapproval, reason, created_at
                FROM paper_trade_execution_rechecks ORDER BY created_at DESC LIMIT 50
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.startswith("/api/v2/paper-execution-rechecks/") and not base_path.endswith("/run") and not base_path.endswith("/approve-updated-plan") and not base_path.endswith("/reject-updated-plan") and not base_path.endswith("/execute-ready"):
        try:
            rid = base_path.split("/")[-1]
            row = _db_query("SELECT * FROM paper_trade_execution_rechecks WHERE recheck_id=%s",
                            (rid,), fetch="one")
            if not row:
                return 404, {"ok": False, "error": "Recheck not found"}
            return 200, {"ok": True, "data": {k: _json_clean(v) for k, v in row.items()}}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/paper-execution-rechecks/run" and method == "POST":
        try:
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from paper_execution_revalidator import revalidate, get_pending_proposals, save_recheck
            from session13_db import get_conn as _rck_conn
            pid = (body or {}).get("proposal_id")
            rconn = _rck_conn()
            try:
                proposals = get_pending_proposals(rconn, proposal_id=pid)
                results = []
                for p in proposals:
                    r = revalidate(rconn, p)
                    save_recheck(rconn, r)
                    results.append({k: v for k, v in r.items() if k != "events"})
                return 200, {"ok": True, "data": results}
            finally:
                rconn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.endswith("/approve-updated-plan") and method == "POST" and "/paper-execution-rechecks/" in base_path:
        try:
            rid = base_path.split("/")[-2]
            reason = (body or {}).get("reason", "approved_via_api")
            _db_write("""UPDATE paper_trade_execution_rechecks
                         SET admin_approval_status='approved', requires_reapproval=false, updated_at=now()
                         WHERE recheck_id=%s""", (rid,))
            rec = _db_query("SELECT paper_trade_proposal_id FROM paper_trade_execution_rechecks WHERE recheck_id=%s", (rid,), fetch="one")
            if rec:
                _db_write("""UPDATE paper_trade_proposals
                             SET material_change_pending_approval=false, execution_recheck_required=true,
                                 execution_recheck_reason=%s
                             WHERE id=%s""", (reason, rec["paper_trade_proposal_id"]))
            return 200, {"ok": True, "message": f"Approved updated plan for {rid}. Run recheck again before execution."}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.endswith("/reject-updated-plan") and method == "POST" and "/paper-execution-rechecks/" in base_path:
        try:
            rid = base_path.split("/")[-2]
            reason = (body or {}).get("reason", "rejected_via_api")
            _db_write("""UPDATE paper_trade_execution_rechecks
                         SET admin_approval_status='rejected', updated_at=now()
                         WHERE recheck_id=%s""", (rid,))
            rec = _db_query("SELECT paper_trade_proposal_id FROM paper_trade_execution_rechecks WHERE recheck_id=%s", (rid,), fetch="one")
            if rec:
                _db_write("""UPDATE paper_trade_proposals SET status='REJECTED',
                             material_change_pending_approval=false, execution_recheck_reason=%s
                             WHERE id=%s""", (reason, rec["paper_trade_proposal_id"]))
            return 200, {"ok": True, "message": f"Rejected updated plan for {rid}"}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.endswith("/execute-ready") and method == "POST" and "/paper-execution-rechecks/" in base_path:
        try:
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from market_session import is_market_open, current_market_session
            from paper_execution_revalidator import check_safety
            import os

            safe, errs = check_safety()
            if not safe:
                return 403, {"ok": False, "error": f"Safety blocked: {errs}"}
            if os.getenv("ALPACA_MODE", "paper").lower() != "paper":
                return 403, {"ok": False, "error": "ALPACA_MODE not paper"}
            if not is_market_open():
                return 403, {"ok": False, "error": f"Market not open (session={current_market_session()})"}

            rid = base_path.split("/")[-2]
            rec = _db_query("SELECT * FROM paper_trade_execution_rechecks WHERE recheck_id=%s", (rid,), fetch="one")
            if not rec:
                return 404, {"ok": False, "error": "Recheck not found"}
            if rec["status"] != "valid_original":
                return 403, {"ok": False, "error": f"Recheck status is '{rec['status']}', not valid_original"}
            if rec.get("requires_reapproval"):
                return 403, {"ok": False, "error": "Material change requires reapproval first"}

            pid = rec["paper_trade_proposal_id"]
            # Check proposal not already submitted or has material change pending
            prop = _db_query("SELECT material_change_pending_approval FROM paper_trade_proposals WHERE id=%s", (pid,), fetch="one")
            if prop and prop.get("material_change_pending_approval"):
                return 403, {"ok": False, "error": "Material change pending approval"}

            return 200, {"ok": True, "message": f"Recheck {rid} is valid_original. Use submit-paper endpoint to execute.",
                         "proposal_id": pid, "recheck_id": rid, "readiness_score": _json_clean(rec.get("execution_readiness_score"))}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/market-session":
        try:
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from market_session import get_status as _ms_status
            return 200, {"ok": True, "data": _ms_status()}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Session 28: Learning Governance endpoints ─────────────────────────
    if base_path == "/api/v2/learning/status":
        try:
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from learning_governance import get_learning_status, _get_conn as _lg_conn
            conn = _lg_conn()
            try:
                return 200, {"ok": True, "data": get_learning_status(conn)}
            finally:
                conn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/learning/hypotheses":
        try:
            rows = _db_query("""
                SELECT hypothesis_id, title, domain, hypothesis_type, status,
                       sample_size, confidence, risk_level, generated_by, created_at
                FROM learning_hypotheses ORDER BY created_at DESC LIMIT 50
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.startswith("/api/v2/learning/hypotheses/") and base_path.count("/") == 4:
        try:
            hid = base_path.split("/")[-1]
            row = _db_query("SELECT * FROM learning_hypotheses WHERE hypothesis_id=%s", (hid,), fetch="one")
            if not row:
                return 404, {"ok": False, "error": "Hypothesis not found"}
            return 200, {"ok": True, "data": {k: _json_clean(v) for k, v in row.items()}}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/learning/experiments":
        try:
            rows = _db_query("""
                SELECT experiment_id, hypothesis_id, name, domain, experiment_type,
                       status, actual_sample_size, min_sample_size, conclusion, created_at
                FROM learning_experiments ORDER BY created_at DESC LIMIT 50
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.startswith("/api/v2/learning/experiments/") and base_path.count("/") == 4:
        try:
            xid = base_path.split("/")[-1]
            row = _db_query("SELECT * FROM learning_experiments WHERE experiment_id=%s", (xid,), fetch="one")
            if not row:
                return 404, {"ok": False, "error": "Experiment not found"}
            return 200, {"ok": True, "data": {k: _json_clean(v) for k, v in row.items()}}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/learning/recommendations":
        try:
            rows = _db_query("""
                SELECT recommendation_id, hypothesis_id, domain, recommendation_type,
                       title, summary, sample_size, confidence, risk_level, status, created_at
                FROM learning_recommendations ORDER BY created_at DESC LIMIT 50
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.startswith("/api/v2/learning/recommendations/") and base_path.count("/") == 4:
        try:
            rid = base_path.split("/")[-1]
            row = _db_query("SELECT * FROM learning_recommendations WHERE recommendation_id=%s", (rid,), fetch="one")
            if not row:
                return 404, {"ok": False, "error": "Recommendation not found"}
            return 200, {"ok": True, "data": {k: _json_clean(v) for k, v in row.items()}}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/learning/config-proposals":
        try:
            rows = _db_query("""
                SELECT proposal_id, recommendation_id, domain, target_key, change_type,
                       reason, risk_assessment, status, approved_by, created_at
                FROM config_change_proposals ORDER BY created_at DESC LIMIT 50
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.startswith("/api/v2/learning/config-proposals/") and not any(
            base_path.endswith(x) for x in ("/approve-shadow", "/reject", "/approve-implementation", "/rollback")):
        try:
            pid = base_path.split("/")[-1]
            row = _db_query("SELECT * FROM config_change_proposals WHERE proposal_id=%s", (pid,), fetch="one")
            if not row:
                return 404, {"ok": False, "error": "Proposal not found"}
            safe = {k: _json_clean(v) for k, v in row.items()}
            return 200, {"ok": True, "data": safe}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.endswith("/approve-shadow") and method == "POST" and "/learning/config-proposals/" in base_path:
        try:
            pid = base_path.split("/")[-2]
            who = (body or {}).get("approved_by", "api_admin")
            _db_write("UPDATE config_change_proposals SET status='shadow_only', approved_by=%s, approved_at=now(), updated_at=now() WHERE proposal_id=%s AND status='proposed'", (who, pid))
            return 200, {"ok": True, "message": f"Proposal {pid} approved for shadow only"}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.endswith("/reject") and method == "POST" and "/learning/config-proposals/" in base_path:
        try:
            pid = base_path.split("/")[-2]
            reason = (body or {}).get("reason", "rejected_via_api")
            _db_write("UPDATE config_change_proposals SET status='rejected', rejected_at=now(), rejection_reason=%s, updated_at=now() WHERE proposal_id=%s", (reason, pid))
            return 200, {"ok": True, "message": f"Proposal {pid} rejected"}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.endswith("/approve-implementation") and method == "POST" and "/learning/config-proposals/" in base_path:
        try:
            pid = base_path.split("/")[-2]
            who = (body or {}).get("approved_by", "api_admin")
            _db_write("UPDATE config_change_proposals SET status='approved', approved_by=%s, approved_at=now(), updated_at=now() WHERE proposal_id=%s AND status IN ('proposed','shadow_only')", (who, pid))
            return 200, {"ok": True, "message": f"Proposal {pid} approved for implementation (manual apply required)"}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.endswith("/rollback") and method == "POST" and "/learning/config-proposals/" in base_path:
        try:
            pid = base_path.split("/")[-2]
            reason = (body or {}).get("reason", "rollback_via_api")
            _db_write("UPDATE config_change_proposals SET status='rolled_back', updated_at=now() WHERE proposal_id=%s", (pid,))
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from learning_governance import record_rollback_event, _get_conn as _lg_conn2
            conn2 = _lg_conn2()
            try:
                record_rollback_event(conn2, pid, "unknown", "unknown", reason)
            finally:
                conn2.close()
            return 200, {"ok": True, "message": f"Rollback recorded for {pid}"}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Session 29: Agent Calibration endpoints ───────────────────────────
    if base_path == "/api/v2/agent-calibration/status":
        try:
            status = {}
            for tbl, label in [("agent_recommendation_registry", "recommendations"),
                               ("agent_recommendation_outcome_links", "outcome_links"),
                               ("agent_calibration_events", "calibration_events"),
                               ("agent_calibration_windows", "calibration_windows"),
                               ("agent_weight_shadow_proposals", "weight_proposals"),
                               ("agent_disagreement_outcomes", "disagreements")]:
                r = _db_query(f"SELECT COUNT(*) as c FROM {tbl}", fetch="one")
                status[f"{label}_total"] = r["c"] if r else 0
            agents = _db_query("SELECT DISTINCT agent_name FROM agent_recommendation_registry ORDER BY agent_name") or []
            status["agents"] = [a["agent_name"] for a in agents]
            return 200, {"ok": True, "data": status}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/agent-calibration/agents":
        try:
            rows = _db_query("""
                SELECT agent_name, COUNT(*) as total,
                       COUNT(DISTINCT symbol) as symbols
                FROM agent_recommendation_registry GROUP BY agent_name ORDER BY total DESC
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.startswith("/api/v2/agent-calibration/agents/") and base_path.count("/") == 5:
        try:
            agent = base_path.split("/")[-1]
            windows = _db_query("""
                SELECT * FROM agent_calibration_windows WHERE agent_name=%s
                ORDER BY created_at DESC LIMIT 10
            """, (agent,)) or []
            recs = _db_query("""
                SELECT recommendation_id, symbol, recommendation_type, confidence,
                       recommendation_time FROM agent_recommendation_registry
                WHERE agent_name=%s ORDER BY recommendation_time DESC LIMIT 20
            """, (agent,)) or []
            return 200, {"ok": True, "data": {
                "agent_name": agent,
                "windows": [{k: _json_clean(v) for k, v in w.items()} for w in windows],
                "recent_recommendations": [{k: _json_clean(v) for k, v in r.items()} for r in recs]
            }}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/agent-calibration/events":
        try:
            rows = _db_query("""
                SELECT calibration_event_id, agent_name, symbol, predicted_action,
                       predicted_confidence, actual_outcome, outcome_score,
                       calibration_error, explanation, created_at
                FROM agent_calibration_events ORDER BY created_at DESC LIMIT 50
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/agent-calibration/windows":
        try:
            rows = _db_query("""
                SELECT window_id, agent_name, domain, recommendations, resolved,
                       correct, incorrect, accuracy, avg_confidence, calibration_error,
                       overconfidence_score, underconfidence_score, low_sample_size,
                       sample_size_status, recommendation, created_at
                FROM agent_calibration_windows ORDER BY created_at DESC LIMIT 50
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/agent-calibration/recommendations":
        try:
            rows = _db_query("""
                SELECT recommendation_id, title, domain, recommendation_type, status,
                       sample_size, confidence, risk_level, created_at
                FROM learning_recommendations WHERE domain='agent_calibration'
                ORDER BY created_at DESC LIMIT 50
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/agent-calibration/weight-proposals":
        try:
            rows = _db_query("""
                SELECT shadow_proposal_id, agent_name, domain, strategy_id,
                       current_weight, proposed_weight, weight_delta, reason,
                       sample_size, confidence, risk_level, status, created_at
                FROM agent_weight_shadow_proposals ORDER BY created_at DESC LIMIT 50
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/agent-calibration/disagreements":
        try:
            rows = _db_query("""
                SELECT disagreement_id, symbol, agents_involved, disagreement_type,
                       winning_view, losing_view, outcome_summary, resolved, created_at
                FROM agent_disagreement_outcomes ORDER BY created_at DESC LIMIT 50
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Session 30: Weekly Learning Digest + Thesis Review ────────────────
    if base_path == "/api/v2/weekly-learning-digest":
        try:
            rows = _db_query("""
                SELECT digest_id, period_start, period_end, status, holdings_value,
                       paper_trades_closed, win_rate, low_sample_size, generated_at
                FROM weekly_learning_digests ORDER BY created_at DESC LIMIT 20
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/weekly-learning-digest/latest":
        try:
            row = _db_query("""
                SELECT digest_id, period_start, period_end, status, holdings_value,
                       paper_trades_closed, win_rate, profit_factor, low_sample_size,
                       top_lessons, agent_summary, source_summary, strategy_summary,
                       thesis_summary, recommendations, human_review_items, digest_markdown
                FROM weekly_learning_digests ORDER BY created_at DESC LIMIT 1
            """, fetch="one")
            if not row:
                return 200, {"ok": True, "data": None, "message": "No digests generated yet"}
            return 200, {"ok": True, "data": {k: _json_clean(v) for k, v in row.items()}}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.startswith("/api/v2/weekly-learning-digest/") and not base_path.endswith("/latest") and not base_path.endswith("/items") and not base_path.endswith("/generate") and not base_path.endswith("/send-telegram"):
        try:
            did = base_path.split("/")[-1]
            row = _db_query("SELECT * FROM weekly_learning_digests WHERE digest_id=%s", (did,), fetch="one")
            if not row:
                return 404, {"ok": False, "error": "Digest not found"}
            return 200, {"ok": True, "data": {k: _json_clean(v) for k, v in row.items()}}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/trade-thesis-reviews":
        try:
            rows = _db_query("""
                SELECT review_id, paper_trade_id, symbol, strategy_id, trade_status,
                       review_type, thesis_validity, thesis_score, execution_score,
                       risk_management_score, outcome_score, lesson_summary,
                       mistake_tags, strength_tags, low_sample_size, created_at
                FROM trade_thesis_reviews ORDER BY created_at DESC LIMIT 50
            """) or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path.startswith("/api/v2/trade-thesis-reviews/") and not base_path.endswith("/run"):
        try:
            rid = base_path.split("/")[-1]
            row = _db_query("SELECT * FROM trade_thesis_reviews WHERE review_id=%s", (rid,), fetch="one")
            if not row:
                return 404, {"ok": False, "error": "Review not found"}
            return 200, {"ok": True, "data": {k: _json_clean(v) for k, v in row.items()}}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Session 31: Backtesting + Champion/Challenger ─────────────────────
    if base_path == "/api/v2/backtesting/status":
        try:
            status = {}
            for tbl, lbl in [("backtest_datasets","datasets"), ("strategy_backtest_runs","runs"),
                             ("strategy_backtest_trades","trades"), ("challenger_definitions","challengers"),
                             ("champion_challenger_results","comparisons")]:
                r = _db_query(f"SELECT COUNT(*) as c FROM {tbl}", fetch="one")
                status[f"{lbl}_total"] = r["c"] if r else 0
            return 200, {"ok": True, "data": status}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/backtesting/datasets":
        try:
            rows = _db_query("SELECT dataset_id, name, source_type, rows_count, start_date, end_date, created_at FROM backtest_datasets ORDER BY created_at DESC LIMIT 20") or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/backtesting/runs":
        try:
            rows = _db_query("SELECT run_id, strategy_id, run_type, status, start_date, end_date, duration_seconds, created_at FROM strategy_backtest_runs ORDER BY created_at DESC LIMIT 20") or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/backtesting/results":
        try:
            rows = _db_query("SELECT result_id, run_id, strategy_id, simulated_trades, wins, losses, win_rate, profit_factor, expectancy_r, sample_size_status, created_at FROM strategy_backtest_results ORDER BY created_at DESC LIMIT 20") or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/backtesting/trades":
        try:
            rows = _db_query("SELECT simulated_trade_id, run_id, strategy_id, symbol, entry_price, exit_price, pnl, r_multiple, exit_reason FROM strategy_backtest_trades ORDER BY created_at DESC LIMIT 50") or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/champion-challenger":
        try:
            rows = _db_query("SELECT challenger_id, name, domain, strategy_id, challenger_type, status, created_at FROM challenger_definitions ORDER BY created_at DESC LIMIT 20") or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Session 32: Unified Self-Improvement Command Center ───────────────
    if base_path in ("/api/v2/self-improvement/status", "/api/v2/self-improvement/summary"):
        try:
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from self_improvement_summary import collect_status, _get_conn as _si_conn
            conn = _si_conn()
            try:
                return 200, {"ok": True, "data": collect_status(conn)}
            finally:
                conn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/self-improvement/snapshot/latest":
        try:
            row = _db_query("SELECT * FROM self_improvement_snapshots ORDER BY created_at DESC LIMIT 1", fetch="one")
            if not row:
                return 200, {"ok": True, "data": None, "message": "No snapshots yet"}
            return 200, {"ok": True, "data": {k: _json_clean(v) for k, v in row.items()}}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/self-improvement/snapshots":
        try:
            rows = _db_query("SELECT snapshot_id, generated_at, status FROM self_improvement_snapshots ORDER BY created_at DESC LIMIT 20") or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/self-improvement/review-queue":
        try:
            rows = _db_query("SELECT review_item_id, source_domain, title, severity, review_type, status, requires_action, linked_dashboard_route, created_at FROM operator_review_queue WHERE status='open' ORDER BY CASE severity WHEN 'urgent' THEN 0 WHEN 'warning' THEN 1 WHEN 'important' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END, created_at DESC LIMIT 50") or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/self-improvement/component-health":
        try:
            rows = _db_query("SELECT component_key, component_name, status, last_checked_at, health_score, summary FROM self_improvement_component_health ORDER BY component_key") or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/self-improvement/warnings":
        try:
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from self_improvement_summary import collect_status, _get_conn as _si_conn2
            conn = _si_conn2()
            try:
                s = collect_status(conn)
                return 200, {"ok": True, "data": s.get("warnings", [])}
            finally:
                conn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/self-improvement/operator-actions":
        try:
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from self_improvement_summary import collect_status, _get_conn as _si_conn3
            conn = _si_conn3()
            try:
                s = collect_status(conn)
                return 200, {"ok": True, "data": s.get("recommended_actions", [])}
            finally:
                conn.close()
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Session 33: Risk Regime + Strategy Rotation ───────────────────────
    if base_path in ("/api/v2/risk-regime/status", "/api/v2/risk-regime/latest"):
        try:
            row = _db_query("SELECT snapshot_id, regime_label, confidence, stale_data, volatility_state, trend_state, breadth_state, summary, generated_at FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 1", fetch="one")
            if not row:
                return 200, {"ok": True, "data": None, "message": "No regime snapshots yet"}
            return 200, {"ok": True, "data": {k: _json_clean(v) for k, v in row.items()}}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/risk-regime/indicators":
        try:
            rows = _db_query("SELECT indicator_id, indicator_key, indicator_group, value, value_text, signal, source_key, created_at FROM market_regime_indicators ORDER BY created_at DESC LIMIT 30") or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/risk-regime/history":
        try:
            rows = _db_query("SELECT snapshot_id, regime_label, confidence, stale_data, generated_at FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 20") or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/strategy-rotation/signals":
        try:
            rows = _db_query("SELECT signal_id, strategy_id, strategy_name, signal, signal_strength, confidence, reason, recommended_action, status, created_at FROM strategy_rotation_signals ORDER BY created_at DESC LIMIT 30") or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/strategy-rotation/profiles":
        try:
            rows = _db_query("SELECT strategy_id, strategy_name, favored_regimes, disfavored_regimes, volatility_preference, trend_preference, time_horizon FROM strategy_regime_profiles WHERE active=true ORDER BY strategy_id") or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/strategy-rotation/alignments":
        try:
            rows = _db_query("SELECT alignment_id, symbol, strategy_id, alignment_type, alignment_score, alignment_label, regime_label, reason, created_at FROM regime_trade_alignment ORDER BY created_at DESC LIMIT 30") or []
            return 200, {"ok": True, "data": [{k: _json_clean(v) for k, v in r.items()} for r in rows]}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Plan vs Performance ──────────────────────────────────────────────
    if base_path == "/api/v2/plan-vs-performance":
        try:
            # 1. All paper trades with plan vs actual data
            trades_sql = """
                SELECT
                    pt.id as trade_id, pt.symbol, pt.strategy_id, pt.status,
                    pt.planned_entry, pt.planned_stop, pt.stop_loss, pt.target_1, pt.target_2,
                    pt.entry_price, pt.exit_price, pt.exit_reason,
                    pt.pnl, pt.pnl_pct, pt.dollar_risk,
                    pt.vix_at_entry, pt.market_regime as regime_at_entry,
                    pt.score_at_entry, pt.rvol_at_entry, pt.catalyst_at_entry,
                    pt.max_favorable_excursion, pt.max_adverse_excursion,
                    pt.created_at as entry_time, pt.closed_at as exit_time,
                    -- thesis outcomes
                    tto.expected_entry, tto.expected_stop, tto.expected_target, tto.expected_r,
                    tto.actual_entry, tto.actual_exit, tto.actual_r,
                    tto.thesis_result, tto.invalidation_hit, tto.thesis_followed,
                    -- outcome analytics
                    ptoa.planned_r, ptoa.realized_r, ptoa.followed_plan,
                    ptoa.hold_minutes, ptoa.tca_grade, ptoa.outcome_verdict,
                    ptoa.stop_adjusted_count, ptoa.limit_adjusted_count,
                    -- execution quality
                    peq.slippage_pct, peq.slippage_dollars, peq.fill_quality,
                    peq.time_to_fill_seconds,
                    -- proposal chain
                    poc.chain_status, poc.outcome_fed_back
                FROM paper_trades pt
                LEFT JOIN trade_thesis_outcomes tto ON pt.id = tto.paper_trade_id
                LEFT JOIN paper_trade_outcome_analytics ptoa ON pt.id = ptoa.paper_trade_id
                LEFT JOIN paper_execution_quality peq ON pt.id = peq.paper_trade_id
                LEFT JOIN proposal_outcome_chain poc ON tto.proposal_id = poc.proposal_id
                WHERE pt.status IN ('open', 'closed', 'filled')
                  AND NOT (pt.status = 'closed' AND pt.exit_reason = 'never_submitted_to_broker')
                ORDER BY pt.created_at DESC
                LIMIT 100
            """
            trades = _db_query(trades_sql) or []

            # 2. Current market regime
            regime_now = _db_query(
                "SELECT regime_label, confidence, volatility_state, trend_state, breadth_state, liquidity_state, risk_appetite_state, summary, generated_at FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 1",
                fetch="one"
            )

            # 3. Strategy regime profiles (which strategies favor current conditions)
            profiles = _db_query(
                "SELECT strategy_id, strategy_name, favored_regimes, disfavored_regimes, volatility_preference, trend_preference, time_horizon FROM strategy_regime_profiles WHERE active=true ORDER BY strategy_id"
            ) or []

            # 4. Recent rotation signals (market changes affecting plan)
            rotation = _db_query(
                "SELECT strategy_id, strategy_name, signal, signal_strength, confidence, reason, recommended_action, created_at FROM strategy_rotation_signals ORDER BY created_at DESC LIMIT 20"
            ) or []

            # 5. Strategy performance snapshots (weekly auto-assessments)
            perf_snaps = _db_query(
                "SELECT strategy_id, snapshot_date, trades_closed, wins, losses, win_rate, profit_factor, avg_r, total_pnl, assessment, recommendation FROM strategy_performance_snapshots ORDER BY snapshot_date DESC, strategy_id LIMIT 50"
            ) or []

            # 6. Regime history (trend over time)
            regime_history = _db_query(
                "SELECT regime_label, confidence, volatility_state, trend_state, generated_at FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 10"
            ) or []

            # Compute summary stats
            # Filter out "closed" trades that never actually executed (no exit_price, never submitted)
            real_closed = [t for t in trades if t.get("status") == "closed"
                           and t.get("exit_reason") != "never_submitted_to_broker"
                           and (t.get("exit_price") is not None or t.get("pnl") is not None)]
            closed = real_closed
            open_trades = [t for t in trades if t.get("status") in ("open", "filled")]
            realized_pnl = sum(float(t.get("pnl") or 0) for t in closed)
            unrealized_pnl = sum(float(t.get("pnl") or t.get("unrealized_pnl") or 0) for t in open_trades)
            total_pnl = realized_pnl + unrealized_pnl
            winners = [t for t in closed if (float(t.get("pnl") or 0)) > 0]
            losers = [t for t in closed if (float(t.get("pnl") or 0)) < 0]
            win_rate = (len(winners) / len(closed) * 100) if closed else 0
            plan_followed = [t for t in closed if t.get("followed_plan") or t.get("thesis_followed")]
            plan_rate = (len(plan_followed) / len(closed) * 100) if closed else 0
            avg_r_planned = 0
            avg_r_actual = 0
            r_count = 0
            for t in closed:
                pr = t.get("planned_r") or t.get("expected_r")
                ar = t.get("realized_r") or t.get("actual_r")
                if pr is not None and ar is not None:
                    avg_r_planned += float(pr)
                    avg_r_actual += float(ar)
                    r_count += 1
            if r_count:
                avg_r_planned /= r_count
                avg_r_actual /= r_count

            # Check regime alignment for current open trades
            current_regime = regime_now.get("regime_label") if regime_now else None
            regime_alerts = []
            if current_regime and profiles:
                profile_map = {p["strategy_id"]: p for p in profiles}
                for t in open_trades:
                    sid = t.get("strategy_id")
                    prof = profile_map.get(sid)
                    if not prof:
                        continue
                    disfavored = prof.get("disfavored_regimes") or []
                    if isinstance(disfavored, str):
                        import json as _json
                        try: disfavored = _json.loads(disfavored)
                        except: disfavored = []
                    if current_regime in disfavored:
                        regime_alerts.append({
                            "symbol": t.get("symbol"),
                            "strategy_id": sid,
                            "regime_at_entry": t.get("regime_at_entry"),
                            "regime_now": current_regime,
                            "alert": f"Current regime '{current_regime}' is DISFAVORED for strategy {sid}",
                        })

            return 200, {"ok": True,
                "summary": {
                    "total_trades": len(open_trades) + len(closed),
                    "open_trades": len(open_trades),
                    "closed_trades": len(closed),
                    "realized_pnl": round(realized_pnl, 2),
                    "unrealized_pnl": round(unrealized_pnl, 2),
                    "total_pnl": round(total_pnl, 2),
                    "win_rate": round(win_rate, 1),
                    "plan_adherence_rate": round(plan_rate, 1),
                    "avg_r_planned": round(avg_r_planned, 2),
                    "avg_r_actual": round(avg_r_actual, 2),
                },
                "trades": [{k: _json_clean(v) for k, v in t.items()} for t in trades],
                "regime_now": {k: _json_clean(v) for k, v in regime_now.items()} if regime_now else None,
                "regime_history": [{k: _json_clean(v) for k, v in r.items()} for r in regime_history],
                "regime_alerts": regime_alerts,
                "strategy_profiles": [{k: _json_clean(v) for k, v in p.items()} for p in profiles],
                "rotation_signals": [{k: _json_clean(v) for k, v in r.items()} for r in rotation],
                "strategy_snapshots": [{k: _json_clean(v) for k, v in s.items()} for s in perf_snaps],
            }
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── LLM Fleet v4.1 — GPU Status (read-only, short timeout) ──────────
    if base_path == "/api/v2/gpu-status":
        try:
            import urllib.request as _ur
            import json as _json
            result = {
                "ok": True,
                "ollama_alive": False,
                "resident_models": [],
                "vram_used_gb": 0,
                "vram_free_gb": 16.0,
                "vram_total_gb": 16.0,
                "active_hours": False,
                "deployment_phase": __import__("os").environ.get("LLM_DEPLOYMENT_PHASE", ""),
            }
            # Short timeout — must not block the API
            try:
                ps_resp = _ur.urlopen("http://localhost:11434/api/ps", timeout=3)
                ps_data = _json.loads(ps_resp.read())
                result["ollama_alive"] = True
                models = []
                total_vram = 0
                for m in ps_data.get("models", []):
                    size_gb = round(m.get("size", 0) / 1024 / 1024 / 1024, 2)
                    total_vram += size_gb
                    models.append({"name": m["name"], "vram_gb": size_gb})
                result["resident_models"] = models
                result["vram_used_gb"] = round(total_vram, 2)
                result["vram_free_gb"] = round(16.0 - total_vram, 2)
            except Exception:
                result["ollama_alive"] = False

            # Active hours check (inline, no import needed)
            try:
                import zoneinfo as _zi
                _now = __import__("datetime").datetime.now(_zi.ZoneInfo("America/New_York"))
                if _now.weekday() < 5:
                    _mo = _now.replace(hour=9, minute=30, second=0)
                    _mc = _now.replace(hour=16, minute=0, second=0)
                    result["active_hours"] = _mo <= _now <= _mc
            except Exception:
                pass

            # Process type model map
            try:
                from local_llm_config import get_model_for_process_type, STANDARD, BATCH_OVERNIGHT, EMBEDDING
                result["process_models"] = {
                    "STANDARD": get_model_for_process_type(STANDARD),
                    "BATCH_OVERNIGHT": get_model_for_process_type(BATCH_OVERNIGHT),
                    "EMBEDDING": get_model_for_process_type(EMBEDDING),
                }
            except Exception:
                pass

            # Last OOM event
            _oom_log = PROJECT_ROOT / "logs" / "gpu_oom.log"
            try:
                if _oom_log.exists():
                    for line in reversed(_oom_log.read_text().strip().splitlines()[-5:]):
                        try:
                            entry = _json.loads(line)
                            if entry.get("oom_detected"):
                                result["last_oom_event"] = entry.get("checked_at")
                                break
                        except Exception:
                            pass
            except Exception:
                pass

            # Last warmup
            _warmup_log = PROJECT_ROOT / "logs" / "gpu_warmup.log"
            try:
                if _warmup_log.exists():
                    for line in reversed(_warmup_log.read_text().strip().splitlines()[-5:]):
                        try:
                            entry = _json.loads(line)
                            result["last_warmup"] = entry.get("ts")
                            result["last_warmup_ms"] = entry.get("elapsed_ms")
                            result["last_warmup_model"] = entry.get("model")
                            result["last_warmup_success"] = entry.get("success")
                            break
                        except Exception:
                            pass
            except Exception:
                pass

            return 200, result
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # ── Overnight Intelligence Dashboard v2 ─────────────────────────────────
    # ── Alerts Dashboard ──────────────────────────────────────────────────
    if base_path == "/api/v2/alerts-dashboard":
        if method == "GET":
            try:
                # Volume stats (last 24h)
                vol = _db_query("""
                    SELECT
                      COUNT(*) FILTER (WHERE action_taken = 'sent_telegram') as sent,
                      COUNT(*) FILTER (WHERE action_taken = 'suppressed_dedup') as suppressed,
                      COUNT(*) FILTER (WHERE action_taken LIKE 'queued_%%') as queued,
                      COUNT(*) FILTER (WHERE action_taken = 'dashboard_only') as dashboard_only,
                      COUNT(*) as total
                    FROM alert_dispatch_log
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                """, fetch="one") or {}

                # By tier
                by_tier = _db_query("""
                    SELECT tier, action_taken, COUNT(*) as count
                    FROM alert_dispatch_log
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                    GROUP BY tier, action_taken ORDER BY tier, count DESC
                """) or []

                # Suppressed
                suppressed = _db_query("""
                    SELECT alert_type, symbol, COUNT(*) as suppressed_count,
                           MAX(created_at) as last_attempt
                    FROM alert_dispatch_log
                    WHERE action_taken IN ('suppressed_dedup', 'dashboard_only')
                      AND created_at > NOW() - INTERVAL '24 hours'
                    GROUP BY alert_type, symbol ORDER BY suppressed_count DESC LIMIT 20
                """) or []

                # Digest pending
                digest_pending = _db_query("""
                    SELECT digest_slot, COUNT(*) as queued
                    FROM digest_queue WHERE sent = FALSE
                    GROUP BY digest_slot
                """) or []

                # Recent urgent
                urgent = _db_query("""
                    SELECT alert_type, symbol, message, created_at, action_taken
                    FROM alert_dispatch_log
                    WHERE tier = 'URGENT' AND created_at > NOW() - INTERVAL '24 hours'
                    ORDER BY created_at DESC LIMIT 20
                """) or []

                data = {
                    'volume_stats': {k: _json_clean(v) for k, v in (vol or {}).items()},
                    'by_tier': [{k: _json_clean(v) for k, v in r.items()} for r in by_tier],
                    'suppressed': [{k: _json_clean(v) for k, v in r.items()} for r in suppressed],
                    'digest_pending': [{k: _json_clean(v) for k, v in r.items()} for r in digest_pending],
                    'urgent_recent': [{k: _json_clean(v) for k, v in r.items()} for r in urgent],
                }
                return 200, {"ok": True, "data": data}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/overnight-dashboard":
        if method == "GET":
            try:
                return _overnight_dashboard()
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/overnight-grade":
        if method == "POST":
            try:
                b = body or {}
                result_id = b.get("result_id")
                grade = b.get("grade", "")
                if not result_id or grade not in ("CORRECT", "HALLUCINATION", "PARTIAL", "PENDING"):
                    return 400, {"ok": False, "error": "result_id and valid grade required"}
                _db_write("""UPDATE overnight_actionable_outcomes
                             SET calibration_grade=%s, graded_by='dashboard', graded_at=NOW()
                             WHERE result_id=%s""", (grade, result_id))
                return 200, {"ok": True, "graded": result_id}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    if base_path == "/api/v2/overnight-retry" or (base_path.startswith("/api/v2/overnight-retry/") and method == "POST"):
        if method == "POST":
            try:
                # Extract queue_id from URL or body
                qid = None
                if "/" in base_path and base_path.count("/") > 3:
                    qid = base_path.split("/")[-1]
                if not qid:
                    qid = (body or {}).get("queue_id")
                if not qid:
                    return 400, {"ok": False, "error": "queue_id required"}
                _db_write("""UPDATE deep_overnight_llm_queue
                             SET status='pending', attempt_count=0, last_error=NULL
                             WHERE id=%s AND status='failed'""", (int(qid),))
                return 200, {"ok": True, "requeued": int(qid)}
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}

    return None


# ── Gemma3 output parser ──────────────────────────────────────────────────

def _parse_trade_review(fj):
    """Parse closed_trade_review findings_json into normalized fields.
    Handles both snake_case and Title Case formats from gemma3."""
    if not fj or not isinstance(fj, dict):
        return {}
    # Normalize: some results use 'analysis' sub-key, others are flat
    analysis = fj.get("analysis", {})
    flat = {k.lower().replace(" ", "_").replace("/", "_"): v for k, v in fj.items()}
    a = {k.lower().replace(" ", "_").replace("/", "_"): v for k, v in analysis.items()} if analysis else {}
    merged = {**flat, **a}

    details = fj.get("trade_details", {})
    hist = fj.get("historical_performance", {})

    return {
        "grade": merged.get("grade") or None,
        "outcome": merged.get("outcome_assessment", ""),
        "lesson": merged.get("lessons_learned", merged.get("key_lesson", "")),
        "risk_mgmt": merged.get("risk_management", ""),
        "entry_exit": merged.get("entry_exit_quality", merged.get("entry_exit_quality", "")),
        "pattern": merged.get("pattern_match", ""),
        "pnl": details.get("pnl_dollars") if details else None,
        "pnl_pct": details.get("pnl_percent") if details else None,
        "hold_days": details.get("hold_days") if details else None,
        "stop_used": details.get("stop_used") if details else None,
        "entry_price": details.get("entry_price") if details else None,
        "exit_price": details.get("exit_price") if details else None,
        "total_trades": hist.get("trades") if hist else None,
        "win_count": hist.get("wins") if hist else None,
    }


def _parse_strategy_classification(fj, symbol):
    """Parse strategy_classification findings_json into normalized fields.
    Handles variable top-level key structures from gemma3."""
    if not fj or not isinstance(fj, dict):
        return {}
    # Find the review object — try nested first, then flat top-level
    review = None
    # Check nested structures: deep_review, strategy_review, or symbol-named key
    for k, v in fj.items():
        if isinstance(v, dict) and any(sk for sk in v if "CLASSIFICATION" in sk.upper() or "EVIDENCE" in sk.upper() or "RECOMMENDATION" in sk.upper()):
            review = v
            break
    if not review:
        review = fj.get("deep_review", fj.get("strategy_review"))
    # If no nested key, the top-level may be the review itself
    if not review or not isinstance(review, dict):
        if any("CLASSIFICATION" in k.upper() or "RECOMMENDATION" in k.upper() for k in fj):
            review = fj
        else:
            return {}

    # Normalize keys — strip leading numbers like "1. " or "4. "
    import re as _re
    norm = {}
    for k, v in review.items():
        kl = _re.sub(r'^\d+[\.\)]\s*', '', k).lower().strip()
        if "classification" in kl and "assessment" in kl:
            norm["classification"] = v
        elif "evidence" in kl:
            norm["evidence"] = v
        elif "recommendation" in kl:
            norm["recommendation"] = v
        elif "thesis" in kl:
            norm["thesis_intact"] = v
        elif "risk" in kl and "flag" in kl:
            norm["risks"] = v
        elif "alternative" in kl:
            norm["alternatives"] = v
        elif "current" in kl and "strategy" in kl:
            norm["current_strategy"] = v

    return norm


def _parse_growth_scan(fj):
    """Parse growth_strategy_scan findings_json — extract individual candidates from batch."""
    if not fj or not isinstance(fj, dict):
        return []
    # Try direct candidates array
    candidates = fj.get("candidates", [])
    if candidates and isinstance(candidates, list):
        return candidates
    # Try raw_response with embedded JSON (often wrapped in ```json fences)
    raw = fj.get("raw_response", "")
    if raw and isinstance(raw, str):
        # Strip markdown code fences
        clean = raw.replace("```json", "").replace("```", "").strip()
        try:
            parsed = json.loads(clean)
            return parsed.get("candidates", [])
        except json.JSONDecodeError:
            # Truncated JSON — extract individual candidate objects
            import re as _re
            items = []
            for m in _re.finditer(r'\{\s*"symbol"\s*:\s*"([^"]+)"[^}]*?"strategy"\s*:\s*"([^"]*)"[^}]*?"fit_score"\s*:\s*(\d+)', clean):
                items.append({"symbol": m.group(1), "strategy": m.group(2), "fit_score": int(m.group(3)), "thesis": ""})
            # Try extracting thesis too
            for m in _re.finditer(r'\{\s*"symbol"\s*:\s*"([^"]+)".*?"thesis"\s*:\s*"([^"]*)"', clean):
                for item in items:
                    if item["symbol"] == m.group(1):
                        item["thesis"] = m.group(2)
            return items
    return []


def _overnight_dashboard():
    """Single-shot overnight intelligence report v2 — with parsed gemma3 outputs."""
    from datetime import datetime as _dt

    # 1. Window summary
    window = _db_query("""
        SELECT MIN(started_at) as window_start,
               MAX(completed_at) as window_end,
               COUNT(*) FILTER (WHERE status='done') as done_count,
               COUNT(*) FILTER (WHERE status='failed') as failed_count,
               COUNT(*) FILTER (WHERE status='running') as running_count,
               COUNT(*) FILTER (WHERE status='pending') as pending_count,
               ROUND(AVG(EXTRACT(EPOCH FROM (completed_at - started_at)))
                     FILTER (WHERE status='done')) as avg_sec
        FROM deep_overnight_llm_queue
        WHERE updated_at > NOW() - INTERVAL '24 hours'
          AND started_at IS NOT NULL
    """, fetch="one") or {}

    # 2. Job breakdown by type
    by_job_type = _db_query("""
        SELECT q.job_type,
               COUNT(*) FILTER (WHERE q.status='done') as done,
               COUNT(*) FILTER (WHERE q.status='failed') as failed,
               COUNT(*) FILTER (WHERE q.status='pending') as pending,
               ROUND(AVG(EXTRACT(EPOCH FROM (q.completed_at - q.started_at)))
                     FILTER (WHERE q.status='done')) as avg_sec,
               ROUND(AVG(LENGTH(r.summary)) FILTER (WHERE q.status='done')) as avg_chars
        FROM deep_overnight_llm_queue q
        LEFT JOIN deep_overnight_llm_results r ON r.queue_id = q.id
        WHERE q.updated_at > NOW() - INTERVAL '24 hours'
        GROUP BY q.job_type
        ORDER BY done DESC
    """) or []

    # 3. Risk synthesis (morning brief seed)
    risk_synth = _db_query("""
        SELECT generated_at, narrative, top_risks,
               portfolio_value, heat_pct,
               LENGTH(narrative) as narrative_chars
        FROM risk_synthesis_results
        WHERE generated_at > NOW() - INTERVAL '24 hours'
        ORDER BY generated_at DESC LIMIT 1
    """, fetch="one") or {}

    # 4. Recovery watch verdicts — detect template fallback
    recovery_raw = _db_query("""
        SELECT q.id as queue_id, r.id as result_id,
               q.symbol, r.summary,
               r.reentry_verdict as verdict,
               r.findings_json->>'recommended_action' as reentry_signal,
               r.findings_json->>'confidence' as confidence,
               r.findings_json->>'key_factor' as key_factor,
               r.created_at
        FROM deep_overnight_llm_queue q
        JOIN deep_overnight_llm_results r ON r.queue_id = q.id
        WHERE q.job_type = 'recovery_watch_review'
          AND r.created_at > NOW() - INTERVAL '24 hours'
        ORDER BY r.created_at DESC LIMIT 20
    """) or []
    # Detect template fallback: all identical verdicts + signals + confidence
    recovery_verdicts = []
    verdict_set = set()
    for rv in recovery_raw:
        d = {k: _json_clean(v) for k, v in rv.items()}
        sig = f"{d.get('verdict')}|{d.get('reentry_signal')}|{d.get('confidence')}"
        verdict_set.add(sig)
        recovery_verdicts.append(d)
    template_fallback = len(verdict_set) == 1 and len(recovery_verdicts) > 2

    # 5. Closed trade reviews — parsed from findings_json
    trade_raw = _db_query("""
        SELECT q.id as queue_id, r.id as result_id,
               q.symbol, q.trade_id,
               r.findings_json,
               r.summary,
               r.created_at
        FROM deep_overnight_llm_queue q
        JOIN deep_overnight_llm_results r ON r.queue_id = q.id
        WHERE q.job_type = 'closed_trade_review'
          AND r.created_at > NOW() - INTERVAL '24 hours'
        ORDER BY r.created_at DESC LIMIT 30
    """) or []
    trade_reviews = []
    for tr in trade_raw:
        parsed = _parse_trade_review(tr.get("findings_json"))
        trade_reviews.append({
            "queue_id": tr.get("queue_id"),
            "result_id": tr.get("result_id"),
            "symbol": tr.get("symbol"),
            "trade_id": tr.get("trade_id"),
            "grade": parsed.get("grade"),
            "outcome": parsed.get("outcome", ""),
            "lesson": parsed.get("lesson", ""),
            "risk_mgmt": parsed.get("risk_mgmt", ""),
            "pnl": _json_clean(parsed.get("pnl")),
            "pnl_pct": _json_clean(parsed.get("pnl_pct")),
            "hold_days": parsed.get("hold_days"),
            "stop_used": parsed.get("stop_used"),
            "created_at": _json_clean(tr.get("created_at")),
        })

    # 6. Strategy classifications — parsed
    strat_raw = _db_query("""
        SELECT q.id as queue_id, r.id as result_id,
               q.symbol, r.findings_json, r.created_at
        FROM deep_overnight_llm_queue q
        JOIN deep_overnight_llm_results r ON r.queue_id = q.id
        WHERE q.job_type = 'strategy_classification'
          AND r.created_at > NOW() - INTERVAL '24 hours'
        ORDER BY r.created_at DESC LIMIT 30
    """) or []
    strategy_class = []
    for sc in strat_raw:
        parsed = _parse_strategy_classification(sc.get("findings_json"), sc.get("symbol"))
        strategy_class.append({
            "symbol": sc.get("symbol"),
            "classification": parsed.get("classification", ""),
            "recommendation": parsed.get("recommendation", ""),
            "thesis_intact": parsed.get("thesis_intact", ""),
            "evidence": parsed.get("evidence", ""),
            "current_strategy": parsed.get("current_strategy", ""),
            "risks": parsed.get("risks", ""),
            "created_at": _json_clean(sc.get("created_at")),
        })

    # 7. RAG content curation — with per-ticker breakdown
    rag_curation = _db_query("""
        SELECT q.symbol,
               r.curation_verdict as verdict,
               r.curation_weight as quality_score,
               r.summary,
               r.created_at
        FROM deep_overnight_llm_queue q
        JOIN deep_overnight_llm_results r ON r.queue_id = q.id
        WHERE q.job_type = 'rag_content_curation'
          AND r.created_at > NOW() - INTERVAL '24 hours'
        ORDER BY r.created_at DESC LIMIT 25
    """) or []
    # Build per-ticker RAG breakdown
    rag_by_ticker = {}
    for r in rag_curation:
        sym = r.get("symbol") or "unknown"
        v = (r.get("verdict") or "").upper()
        if sym not in rag_by_ticker:
            rag_by_ticker[sym] = {"approved": 0, "rejected": 0, "flagged": 0}
        if "APPROVE" in v:
            rag_by_ticker[sym]["approved"] += 1
        elif "REJECT" in v:
            rag_by_ticker[sym]["rejected"] += 1
        else:
            rag_by_ticker[sym]["flagged"] += 1

    # 8. Covered call scoring
    covered_calls = _db_query("""
        SELECT q.symbol, r.summary,
               r.cc_verdict as verdict,
               r.cc_strike_target as strike,
               r.cc_yield_estimate as yield_est,
               r.created_at
        FROM deep_overnight_llm_queue q
        JOIN deep_overnight_llm_results r ON r.queue_id = q.id
        WHERE q.job_type = 'covered_call_scoring'
          AND r.created_at > NOW() - INTERVAL '24 hours'
        ORDER BY r.cc_yield_estimate DESC NULLS LAST LIMIT 15
    """) or []

    # 9. Strategy opportunity / growth scan — parse individual candidates
    opp_raw = _db_query("""
        SELECT q.symbol, r.summary,
               r.findings_json,
               r.recommendations_json,
               q.job_type,
               r.created_at
        FROM deep_overnight_llm_queue q
        JOIN deep_overnight_llm_results r ON r.queue_id = q.id
        WHERE q.job_type IN ('growth_strategy_scan', 'rebalance_analysis')
          AND r.created_at > NOW() - INTERVAL '24 hours'
        ORDER BY r.created_at DESC LIMIT 15
    """) or []
    opportunity_scan = []
    for opp in opp_raw:
        candidates = _parse_growth_scan(opp.get("findings_json"))
        if candidates:
            for c in candidates:
                opportunity_scan.append({
                    "symbol": c.get("symbol", opp.get("symbol")),
                    "strategy": c.get("strategy", ""),
                    "score": c.get("fit_score"),
                    "thesis": c.get("thesis", ""),
                    "timeframe": c.get("timeframe", ""),
                    "created_at": _json_clean(opp.get("created_at")),
                })
        else:
            opportunity_scan.append({
                "symbol": opp.get("symbol"),
                "strategy": "",
                "score": None,
                "thesis": "",
                "created_at": _json_clean(opp.get("created_at")),
            })

    # 10. Failed jobs
    failed_jobs = _db_query("""
        SELECT id, job_type, symbol, attempt_count,
               last_error, started_at
        FROM deep_overnight_llm_queue
        WHERE status = 'failed'
          AND updated_at > NOW() - INTERVAL '24 hours'
        ORDER BY updated_at DESC LIMIT 20
    """) or []

    # 11. gemma3 calibration (7-day rolling)
    calibration = _db_query("""
        SELECT job_type,
               COUNT(*) as total_events,
               COUNT(*) FILTER (WHERE grade='CORRECT') as correct,
               COUNT(*) FILTER (WHERE grade='HALLUCINATION') as hallucinated,
               COUNT(*) FILTER (WHERE grade='PARTIAL') as partial,
               COUNT(*) FILTER (WHERE grade='PENDING') as pending_grade
        FROM gemma3_calibration_events
        WHERE created_at > NOW() - INTERVAL '7 days'
        GROUP BY job_type
        ORDER BY total_events DESC
    """) or []

    # 12. New proposals generated overnight
    new_proposals = _db_query("""
        SELECT symbol, strategy_id, signal_score as score, signal_grade as grade,
               proposed_entry as entry_price, status, created_at
        FROM paper_trade_proposals
        WHERE created_at > NOW() - INTERVAL '24 hours'
        ORDER BY signal_score DESC NULLS LAST LIMIT 15
    """) or []

    # 13. Duplicate detection
    duplicates = _db_query("""
        SELECT q.symbol, q.job_type, COUNT(*) as cnt
        FROM deep_overnight_llm_queue q
        JOIN deep_overnight_llm_results r ON r.queue_id = q.id
        WHERE r.created_at > NOW() - INTERVAL '24 hours'
        GROUP BY q.symbol, q.job_type
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC LIMIT 20
    """) or []

    # 14. Data quality alerts
    data_quality = []
    if template_fallback:
        data_quality.append({
            "severity": "high",
            "section": "recovery_watch",
            "message": f"All {len(recovery_verdicts)} recovery verdicts are identical — likely template fallback, not real analysis",
        })
    # Check for reviews with no parsed grades
    no_grade = sum(1 for tr in trade_reviews if not tr.get("grade") and not tr.get("outcome"))
    if no_grade > 0:
        data_quality.append({
            "severity": "medium",
            "section": "trade_reviews",
            "message": f"{no_grade} of {len(trade_reviews)} trade reviews have no parsed grade or outcome",
        })
    # Duplicate alert
    high_dupes = [d for d in duplicates if (d.get("cnt") or 0) > 3]
    if high_dupes:
        syms = ", ".join(f"{d['symbol']}({d['cnt']}x)" for d in high_dupes[:5])
        data_quality.append({
            "severity": "medium",
            "section": "duplicates",
            "message": f"High duplicate counts: {syms}",
        })
    # Check for failed jobs
    if failed_jobs:
        data_quality.append({
            "severity": "high" if len(failed_jobs) > 3 else "low",
            "section": "failed_jobs",
            "message": f"{len(failed_jobs)} job(s) failed",
        })

    # 15. Actionable summary — signals the operator should act on
    actionable = []
    # Recovery re-entry signals (only if not template fallback)
    if not template_fallback:
        for rv in recovery_verdicts:
            sig = (rv.get("reentry_signal") or "").upper()
            if sig in ("RE_ENTER", "BUY", "REENTER"):
                actionable.append({"type": "recovery_reentry", "symbol": rv["symbol"], "detail": sig})
    # New proposals with high grades
    for p in new_proposals:
        pg = (p.get("grade") or "").upper()
        if pg in ("A", "A+", "A-"):
            actionable.append({"type": "new_proposal", "symbol": p["symbol"], "detail": f"Grade {pg}, score {p.get('score')}"})
    # Trade lessons with stop failures
    for tr in trade_reviews:
        if tr.get("stop_used") is False:
            actionable.append({"type": "no_stop_alert", "symbol": tr["symbol"], "detail": "No stop used"})

    data = {
        'generated_at': _dt.now().isoformat(),
        'version': 2,
        'window': {k: _json_clean(v) for k, v in (window or {}).items()},
        'by_job_type': [{k: _json_clean(v) for k, v in r.items()} for r in by_job_type],
        'risk_synthesis': {k: _json_clean(v) for k, v in (risk_synth or {}).items()},
        'recovery_verdicts': recovery_verdicts,
        'recovery_template_fallback': template_fallback,
        'trade_reviews': trade_reviews,
        'strategy_classifications': strategy_class,
        'rag_curation': [{k: _json_clean(v) for k, v in r.items()} for r in rag_curation],
        'rag_by_ticker': rag_by_ticker,
        'covered_calls': [{k: _json_clean(v) for k, v in r.items()} for r in covered_calls],
        'opportunity_scan': opportunity_scan,
        'failed_jobs': [{k: _json_clean(v) for k, v in r.items()} for r in failed_jobs],
        'gemma3_calibration': [{k: _json_clean(v) for k, v in r.items()} for r in calibration],
        'new_proposals': [{k: _json_clean(v) for k, v in r.items()} for r in new_proposals],
        'duplicates': [{k: _json_clean(v) for k, v in r.items()} for r in duplicates],
        'data_quality': data_quality,
        'actionable_signals': actionable,
    }

    # 16. Data gap intelligence
    try:
        gap_summary = _db_query("""
            SELECT gap_type, severity, status, COUNT(*) as count,
                   array_agg(DISTINCT symbol ORDER BY symbol)
                       FILTER (WHERE symbol IS NOT NULL) as symbols
            FROM data_gap_registry
            WHERE detected_at > NOW() - INTERVAL '7 days'
            GROUP BY gap_type, severity, status
            ORDER BY
              CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
              count DESC
        """) or []
        gap_stats = _db_query("""
            SELECT
              COUNT(*) FILTER (WHERE status='open') as open_gaps,
              COUNT(*) FILTER (WHERE status='enriching') as enriching,
              COUNT(*) FILTER (WHERE status='resolved'
                                AND resolved_at > NOW() - INTERVAL '24 hours') as resolved_today,
              COUNT(*) FILTER (WHERE status='abandoned') as abandoned
            FROM data_gap_registry
        """, fetch="one") or {}
        data['gap_summary'] = [{k: _json_clean(v) for k, v in r.items()} for r in gap_summary]
        data['gap_stats'] = {k: _json_clean(v) for k, v in (gap_stats or {}).items()}
    except Exception:
        data['gap_summary'] = []
        data['gap_stats'] = {}

    return 200, {"ok": True, "data": data}
