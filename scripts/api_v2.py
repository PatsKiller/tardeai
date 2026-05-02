"""api_v2.py — Normalized API for Command Center v2.

All endpoints return stable, frontend-friendly JSON shapes.
Read-only aggregation + journal review write layer.
"""
import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


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
        # If no local data at all, try Yahoo (for watchlist-only symbols)
        yq = {}
        if not company and not e and not t and not hp:
            yq = _fetch_yahoo_quote(sym)
        return {
            "company": company or yq.get("company", ""),
            "sector": e.get("sector") or t.get("sector") or hp.get("sector", ""),
            "rsi": e.get("rsi") or t.get("rsi") or yq.get("rsi"),
            "perf_week_pct": e.get("perf_week_pct") or t.get("perf_week_pct") or t.get("perf_week"),
            "beta": t.get("beta") or hp.get("beta"),
            "market_cap_b": e.get("market_cap_b"),
            "current_price": yq.get("price") if yq else None,
            "pct_from_52wk_high": yq.get("pct_from_52wk_high") if yq else None,
            "data_source": "yahoo" if yq.get("company") else ("enrichment_cache" if e else "technical_snapshot" if t else "holdings" if hp else "metadata_only"),
        }

    items = []
    for sym, meta in wl_json.items():
        enriched = _enrich(sym)
        items.append({"symbol": sym, "source": "user", "status": "active",
                       "company": enriched["company"], "sector": enriched["sector"],
                       "rsi": enriched["rsi"], "perf_week_pct": enriched["perf_week_pct"],
                       "beta": enriched["beta"], "market_cap_b": enriched["market_cap_b"],
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
                "aegis-overnight", "aegis-surveillance"}
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
    _triggered = len([p for p in _risk.get("positions", []) if p.get("triggered")])
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

    # 6. Summary line
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
               ORDER BY close_date DESC, symbol
               LIMIT 500""",
            fetch="all"
        )
        if rows:
            trades = [{k: (float(v) if isinstance(v, __import__('decimal').Decimal) else v)
                       for k, v in r.items()} for r in rows]
    except Exception:
        pass

    # Fallback to JSON if DB empty
    if not trades:
        j = _load_json(STATE_DIR / "trade_journal.json") or {}
        trades = j.get("closed_trades", [])
        trades = [{
            "symbol": t.get("symbol", ""), "account": t.get("account", ""),
            "open_date": t.get("open_date", ""), "close_date": t.get("close_date", ""),
            "trade_type": t.get("trade_type", ""), "shares": t.get("shares", 0),
            "buy_price": t.get("buy_price", 0), "sell_price": t.get("sell_price", 0),
            "cost_basis": t.get("cost_basis", 0), "proceeds": t.get("proceeds", 0),
            "pnl": t.get("pnl", 0), "pnl_pct": t.get("pnl_pct", 0),
            "hold_days": t.get("hold_days", 0),
        } for t in trades[:500]]

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
                       for p in positions if p.get("triggered") or p.get("status") == "danger"][:4],
            "warning": [{"symbol": p.get("symbol",""), "max_loss": p.get("max_loss",0), "distance_pct": p.get("distance_pct",0), "account": p.get("account","")}
                        for p in positions if p.get("status") == "warning"][:4],
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
    accounts = r.get("accounts") or {}
    key_dates = r.get("key_dates") or {}
    loan = r.get("loan") or {}
    gw = r.get("golden_window") or {}
    tl = r.get("timeline") or []
    return {
        "as_of": r.get("as_of", ""),
        "current_age": r.get("current_age", 0),
        "key_dates": key_dates,
        "accounts": {
            "total": accounts.get("portfolio_total") or accounts.get("total") or 0,
            "roth": accounts.get("roth") or accounts.get("roth_balance") or 0,
            "traditional": accounts.get("traditional") or accounts.get("traditional_ira") or accounts.get("pre_tax") or 0,
            "taxable": accounts.get("taxable") or 0,
        },
        "loan": {
            "balance": loan.get("balance", 0),
            "deadline": loan.get("deadline", key_dates.get("loan_deadline", "")),
            "days_remaining": loan.get("days_remaining", key_dates.get("days_to_loan_deadline", 0)),
            "monthly_to_payoff": loan.get("monthly_to_payoff", 0),
        },
        "timeline": tl,
        "golden_window": {
            "start_age": gw.get("start_age") or key_dates.get("golden_window_start", ""),
            "end_age": gw.get("end_age") or key_dates.get("golden_window_end", ""),
            "years_available": gw.get("years_available") or key_dates.get("years_to_golden", 0),
            "optimal_annual_conversion": gw.get("optimal_annual_conversion") or gw.get("sweet_spot_annual") or 0,
            "projected_roth_at_start": gw.get("projected_roth_at_start") or accounts.get("roth") or 0,
            "narrative": gw.get("narrative") or "",
        },
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
        payload = json.dumps({"model": "qwen3:1.7b", "stream": False, "prompt": f"/no_think\n{prompt}",
                              "options": {"temperature": 0.2, "num_predict": 500}}).encode()
        req = urllib.request.Request("http://127.0.0.1:11434/api/generate",
                                     data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = json.loads(resp.read()).get("response", "").strip()
            return 200, {"ok": True, "answer": raw, "model": "qwen3:1.7b", "question": question}
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
    return {
        "agents": [{k: _json_clean(v) for k, v in r.items()} for r in agent_counts],
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
    macro = ""
    try:
        from external_market_data_ingest import get_macro_context
        macro = (get_macro_context() or "")[:500]
    except Exception:
        pass

    # Detect real conflicts (opposing directions, both >40% confidence)
    conflict_info = _detect_real_conflict(agents)

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
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            import json as _j
            models = [m["name"] for m in _j.loads(r.read()).get("models", [])]
            local_up = any("qwen3" in m for m in models)
    except Exception:
        pass
    return {"local_llm": local_up, "fallback": "claude-haiku-4-5"}


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
    """
    # 1. Active + recent agent jobs (last 24h)
    jobs = _db_query(
        """SELECT id, symbol, requested_agent, request_type, status,
                  priority, submitted_from, created_at, started_at, completed_at,
                  payload::text as payload_text
           FROM watchlist_agent_jobs
           WHERE created_at > NOW() - INTERVAL '24 hours'
           ORDER BY created_at DESC LIMIT 200"""
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
           ORDER BY created_at DESC LIMIT 50"""
    ) or []

    # 4. Event queue (Level 3)
    events = _db_query(
        """SELECT id, event_type, symbol, priority, status,
                  agents_to_notify, trigger_data::text as trigger_text,
                  created_at, processed_at
           FROM agent_event_queue
           ORDER BY created_at DESC LIMIT 50"""
    ) or []

    # 5. Pending proposals
    proposals = _db_query(
        """SELECT symbol, action, strategy_type, confidence, status,
                  created_at
           FROM watchlist_proposals
           WHERE status = 'proposed'
           ORDER BY created_at DESC LIMIT 30"""
    ) or []

    # 6. Recent debates
    debates = _db_query(
        """SELECT symbol, consensus_recommendation, consensus_score,
                  participants, created_at, provider
           FROM agent_debate_log
           WHERE created_at > NOW() - INTERVAL '24 hours'
           ORDER BY created_at DESC LIMIT 20"""
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
    if src == "portfolio":
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
            computed.append({"symbol": "", "action": "INCOME REVIEW", "rationale": f'Portfolio yield {_rann/_rtotal*100:.2f}% — below 1% target.', "severity": "low"})
        recommendations = computed

    return {
        "generated_at": yo.get("generated_at", ""),
        "status": yo.get("status", ""),
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
    }


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

    # Parse watchlist CSV for the latest run
    tickers = []
    csv_pattern = latest.get("_path", "").replace("run_summary.json", "").rstrip("/")
    if csv_pattern:
        csvs = sorted(glob.glob(csv_pattern + "/trade_ai_*_watchlist.csv"))
        if csvs:
            try:
                rows = list(csv.DictReader(io.StringIO(Path(csvs[-1]).read_text())))
                for r in rows:
                    tickers.append({
                        "symbol": r.get("Symbol", ""),
                        "score": int(r.get("Score", 0) or 0),
                        "grade": r.get("Grade", ""),
                        "decision": r.get("Decision", ""),
                        "rvol": float(r.get("RVOL", 0) or 0),
                        "price": float(r.get("Price", 0) or 0),
                        "change_pct": r.get("Change%", ""),
                        "gap_pct": r.get("Gap%", ""),
                        "float_m": r.get("Float_M", ""),
                        "catalyst": r.get("Catalyst", ""),
                    })
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

    go_count = latest.get("go_count", 0)
    wait_count = latest.get("wait_count", 0)

    return {
        "run_date": latest.get("date", ""),
        "run_label": latest.get("run_label", ""),
        "vix": latest.get("vix"),
        "breadth": latest.get("breadth", ""),
        "go_count": go_count,
        "wait_count": wait_count,
        "avoid_count": latest.get("ticker_count", 0) - go_count - wait_count,
        "ticker_count": latest.get("ticker_count", 0),
        "top_ticker": latest.get("top_ticker", ""),
        "top_score": latest.get("top_score", 0),
        "delta_events": latest.get("delta_events", 0),
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
    "/api/v2/iris/stale-symbols": lambda: _iris_stale_symbols(),
    "/api/v2/iris/content-gaps": lambda: _iris_content_gaps(),
    "/api/v2/iris/duplicates": lambda: _iris_duplicates(),
    "/api/v2/proposals-with-pnl": lambda: _proposals_with_pnl(),
    "/api/v2/alex-hygiene/history": lambda: {"runs": [{k: _json_clean(v) for k, v in r.items()} for r in (_db_query("SELECT id, decision_type, tier, question, agreement_score, elapsed_seconds, bypass_event, ran_at, LEFT(synthesis,500) as synthesis_preview FROM alex_hygiene_log ORDER BY ran_at DESC LIMIT 10") or [])]},
    "/api/v2/agent-pipeline": lambda: _agent_pipeline(),
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
    "/api/v2/journal/analytics": journal_analytics,
    "/api/v2/risk": risk,
    "/api/v2/tax-lots": tax_lots,
    "/api/v2/correlation": correlation,
    "/api/v2/rebalance": rebalance,
}


def handle(path: str, method: str = "GET", body: dict = None, query: dict = None):
    """Dispatch a v2 API path. Returns (status, dict) or None if not a v2 route."""
    # Strip query string from path if present
    base_path = path.split("?")[0] if "?" in path else path

    # POST routes
    if method == "POST":
        if base_path == "/api/v2/journal/review":
            try:
                return journal_review_write(body or {})
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
        return None

    # GET: journal review read (with query param)
    if base_path == "/api/v2/journal/review":
        trade_key = (query or {}).get("trade_key", "")
        if not trade_key:
            return 400, {"ok": False, "error": "trade_key query param required"}
        try:
            return 200, {"ok": True, "data": journal_review_read(trade_key)}
        except Exception as e:
            return 500, {"ok": False, "error": str(e)}

    # Pass query params to lookup functions that need them
    if query:
        _youtube_channel_lookup._url = (query.get("url") or [""])[0] if isinstance(query.get("url"), list) else query.get("url", "")
        _youtube_transcripts._query = query
        _news_articles_list._query = query
        _intelligence_library._query = query

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

    return None
