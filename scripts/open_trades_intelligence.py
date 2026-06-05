#!/usr/bin/env python3
"""open_trades_intelligence.py — aggregate READ-ONLY intelligence for v3 Open Trades.

One normalized object per open position across ALL accounts (from `trades`), enriched with:
technicals (ticker_snapshot_daily + indicator_confluence_cache), news (news_articles + Hermes
research/alerts/findings), sector-relative perf (best-effort), and protection state. Batched (no N+1).
NO writes anywhere; Hermes data is read-only. Missing data degrades gracefully (buckets like
'missing'/'unavailable'), never crashes.
"""
import os
from datetime import datetime, timezone

SECTOR_ETF = {"Technology": "XLK", "Financial": "XLF", "Financials": "XLF", "Healthcare": "XLV",
              "Health Care": "XLV", "Industrials": "XLI", "Consumer Discretionary": "XLY",
              "Consumer Cyclical": "XLY", "Consumer Staples": "XLP", "Consumer Defensive": "XLP",
              "Energy": "XLE", "Utilities": "XLU", "Real Estate": "XLRE", "Materials": "XLB",
              "Basic Materials": "XLB", "Communication Services": "XLC"}


def _conn():
    import psycopg2
    import psycopg2.extras
    c = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                         user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])
    return c


def _age_hours(dt):
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - dt).total_seconds() / 3600.0, 1)


def _broker_norm(b):
    b = (b or "").lower()
    for k in ("alpaca", "schwab", "fidelity", "tos", "tradier"):
        if k in b:
            return k
    return b or "—"


def _nan_clean(o):
    import math
    from decimal import Decimal
    if isinstance(o, Decimal):
        f = float(o)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: _nan_clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_nan_clean(v) for v in o]
    return o


def _hold(ed):
    if not ed:
        return None
    d = ed.date() if hasattr(ed, "date") else ed
    try:
        return f"{(datetime.now(timezone.utc).date() - d).days}d"
    except Exception:
        return None


def _is_ticker(sym):
    return bool(sym) and sym.isalpha() and 1 <= len(sym) <= 5


def _rsi_bucket(rsi):
    if rsi is None:
        return "missing"
    if rsi < 30:
        return "oversold"
    if rsi > 70:
        return "overbought"
    return "neutral"


def _trend_label(sma50_pct, sma200_pct, adx):
    if sma50_pct is None and sma200_pct is None:
        return "unknown"
    above50 = (sma50_pct or 0) > 0
    above200 = (sma200_pct or 0) > 0
    if above50 and above200:
        return "bullish"
    if not above50 and not above200:
        return "bearish"
    return "neutral"


def build_intelligence():
    c = _conn()
    import psycopg2.extras
    cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""SELECT trade_id, symbol, broker, account, strategy_id, entry_price, stop_loss,
                       target_price, shares, r_multiple, entry_date, status
                       FROM trades WHERE lower(status)='open' ORDER BY account, symbol""")
        rows = cur.fetchall()
        syms = sorted({r["symbol"] for r in rows if r["symbol"]})
        tickers = [s for s in syms if _is_ticker(s)]

        # ── batch enrichment (no N+1) ──
        price = {}
        if syms:
            cur.execute("""SELECT DISTINCT ON (symbol) symbol, close_price, price_date
                           FROM price_cache WHERE symbol = ANY(%s) ORDER BY symbol, price_date DESC""", (syms,))
            price = {r["symbol"]: r for r in cur.fetchall()}
        quote = {}
        if syms:
            cur.execute("""SELECT DISTINCT ON (symbol) symbol, price, prev_close, day_change_pct, volume, avg_volume, fetched_at
                           FROM market_quotes WHERE symbol = ANY(%s) ORDER BY symbol, fetched_at DESC""", (syms,))
            quote = {r["symbol"]: r for r in cur.fetchall()}
        tech = {}
        etf_syms = list(set(SECTOR_ETF.values())) + ["SPY"]
        if tickers or etf_syms:
            cur.execute("""SELECT DISTINCT ON (symbol) symbol, rsi, beta, sma20_pct, sma50_pct, sma200_pct,
                           perf_week_pct, perf_month_pct, week52_high_pct, snapshot_date
                           FROM ticker_snapshot_daily WHERE symbol = ANY(%s) ORDER BY symbol, snapshot_date DESC""",
                        (tickers + etf_syms,))
            tech = {r["symbol"]: r for r in cur.fetchall()}
        conf = {}
        if tickers:
            cur.execute("""SELECT DISTINCT ON (symbol) symbol, atr, adx_regime, key_levels, confluence_tier, computed_at
                           FROM indicator_confluence_cache WHERE symbol = ANY(%s) ORDER BY symbol, computed_at DESC""", (tickers,))
            conf = {r["symbol"]: r for r in cur.fetchall()}
        sector = {}
        try:
            cur.execute("SELECT DISTINCT ON (symbol) symbol, sector FROM aegis_symbol_snapshot_nightly "
                        "WHERE symbol = ANY(%s) AND sector IS NOT NULL ORDER BY symbol, snapshot_date DESC NULLS LAST", (tickers,))
            sector = {r["symbol"]: r["sector"] for r in cur.fetchall()}
        except Exception:
            c.rollback()
        missing_sec = [s for s in tickers if s not in sector]
        if missing_sec:
            for tbl, datecol in (("intelligence_entities", None), ("hermes_v_ticker_context", None), ("strategy_signals", None)):
                if not missing_sec:
                    break
                try:
                    cur.execute(f"SELECT DISTINCT ON (symbol) symbol, sector FROM {tbl} WHERE symbol = ANY(%s) AND sector IS NOT NULL ORDER BY symbol", (missing_sec,))
                    for r in cur.fetchall():
                        sector[r["symbol"]] = r["sector"]
                    missing_sec = [s for s in missing_sec if s not in sector]
                except Exception:
                    c.rollback()
        # news (TradeAI)
        news = {s: [] for s in syms}
        if tickers:
            cur.execute("""SELECT symbol, title, source, source_url, published_at, sentiment, relevance_score
                           FROM news_articles WHERE symbol = ANY(%s) AND coalesce(is_duplicate,false)=false
                           ORDER BY published_at DESC NULLS LAST LIMIT 600""", (tickers,))
            for r in cur.fetchall():
                if len(news.get(r["symbol"], [])) < 4:
                    news.setdefault(r["symbol"], []).append({
                        "title": r["title"], "url": r["source_url"], "source": (r["source"] or "tradeai"),
                        "published_at": r["published_at"].isoformat() if r["published_at"] else None,
                        "age_hours": _age_hours(r["published_at"]), "sentiment": r["sentiment"], "severity": "info",
                        "why_it_matters": None})
        # Hermes research + alerts + findings
        herm = {s: {"items": [], "research_at": None, "finding_count_24h": 0, "alert_count_24h": 0,
                    "top_finding": None, "disagreement": False} for s in syms}
        if tickers:
            cur.execute("""SELECT symbol, summary, thesis, thesis_type, confidence_score, source_urls_json, created_at
                           FROM hermes_research_intelligence WHERE symbol = ANY(%s) ORDER BY created_at DESC LIMIT 400""", (tickers,))
            for r in cur.fetchall():
                h = herm[r["symbol"]]
                if h["research_at"] is None:
                    h["research_at"] = r["created_at"].isoformat() if r["created_at"] else None
                if (_age_hours(r["created_at"]) or 999) <= 24:
                    h["finding_count_24h"] += 1
                if (r["thesis_type"] or "").lower() in ("bear", "bearish", "contrarian", "disagree"):
                    h["disagreement"] = True
                if len(h["items"]) < 3:
                    url = None
                    try:
                        import json as _j
                        u = r["source_urls_json"]
                        if u:
                            uu = _j.loads(u) if isinstance(u, str) else u
                            url = uu[0] if isinstance(uu, list) and uu else (uu.get("url") if isinstance(uu, dict) else None)
                    except Exception:
                        url = None
                    h["items"].append({"title": (r["summary"] or r["thesis"] or "Hermes research")[:140], "url": url,
                                       "source": "hermes", "published_at": r["created_at"].isoformat() if r["created_at"] else None,
                                       "age_hours": _age_hours(r["created_at"]),
                                       "sentiment": r["thesis_type"], "severity": "info",
                                       "why_it_matters": (r["thesis"] or "")[:140] or None})
            cur.execute("""SELECT symbol, title, severity, alert_type, created_at FROM hermes_alerts
                           WHERE symbol = ANY(%s) AND lower(coalesce(status,'open')) NOT IN ('dismissed','resolved')
                           ORDER BY created_at DESC LIMIT 300""", (tickers,))
            for r in cur.fetchall():
                h = herm[r["symbol"]]
                if (_age_hours(r["created_at"]) or 999) <= 24:
                    h["alert_count_24h"] += 1
                if len(h["items"]) < 4:
                    sev = (r["severity"] or "info").lower()
                    h["items"].append({"title": r["title"] or "Hermes alert", "url": None, "source": "hermes_alert",
                                       "published_at": r["created_at"].isoformat() if r["created_at"] else None,
                                       "age_hours": _age_hours(r["created_at"]), "sentiment": None,
                                       "severity": "high" if sev in ("critical", "high", "urgent") else sev,
                                       "why_it_matters": r["alert_type"]})
            cur.execute("""SELECT symbol, description, severity, finding_type FROM hermes_validation_findings
                           WHERE symbol = ANY(%s) AND lower(coalesce(status,'open')) NOT IN ('resolved','dismissed')
                           ORDER BY created_at DESC LIMIT 200""", (tickers,))
            for r in cur.fetchall():
                h = herm.get(r["symbol"])
                if h and h["top_finding"] is None:
                    h["top_finding"] = {"finding_type": r["finding_type"], "severity": r["severity"],
                                        "description": (r["description"] or "")[:160]}

        # protection proposals (read-only) keyed by symbol
        prot = {s: {"protected": True, "tp_missing": False, "stop_near": False, "below_entry": False,
                    "trailing_candidate": False, "top_recommendation": None, "option_count": 0} for s in syms}
        try:
            cur.execute("""SELECT symbol, count(*) n, max(recommended_action) act FROM protection_adjustment_proposals
                           WHERE symbol = ANY(%s) AND lower(coalesce(status,'pending')) IN ('pending','open','proposed')
                           GROUP BY symbol""", (syms,))
            for r in cur.fetchall():
                if r["symbol"] in prot:
                    prot[r["symbol"]]["option_count"] = r["n"]
                    prot[r["symbol"]]["top_recommendation"] = r["act"]
        except Exception:
            c.rollback()

        # ── assemble positions ──
        positions = []
        spy = tech.get("SPY") or {}
        for r in rows:
            sym = r["symbol"]
            ent = float(r["entry_price"]) if r["entry_price"] is not None else None
            stop = float(r["stop_loss"]) if r["stop_loss"] is not None else None
            tgt = float(r["target_price"]) if r["target_price"] is not None else None
            sh = float(r["shares"]) if r["shares"] is not None else 0
            pr = price.get(sym) or {}
            q = quote.get(sym) or {}
            cur_px = float(q["price"]) if q.get("price") is not None else (float(pr["close_price"]) if pr.get("close_price") is not None else None)
            today_move = float(q["day_change_pct"]) if q.get("day_change_pct") is not None else None
            rvol = (float(q["volume"]) / float(q["avg_volume"])) if (q.get("volume") and q.get("avg_volume")) else None
            px_at = q.get("fetched_at") or pr.get("price_date")
            upnl = (cur_px - ent) * sh if (cur_px is not None and ent is not None) else None
            upnl_pct = ((cur_px - ent) / ent * 100) if (cur_px and ent) else None
            rmult = float(r["r_multiple"]) if r["r_multiple"] is not None else (
                ((cur_px - ent) / (ent - stop)) if (cur_px and ent and stop and ent != stop) else None)
            t = tech.get(sym) or {}
            cf = conf.get(sym) or {}
            rsi = float(t["rsi"]) if t.get("rsi") is not None else None
            sma50 = float(t["sma50_pct"]) if t.get("sma50_pct") is not None else None
            sma200 = float(t["sma200_pct"]) if t.get("sma200_pct") is not None else None
            stale_tech = not t and not cf
            # sector relative
            sec = sector.get(sym)
            etf = SECTOR_ETF.get(sec) if sec else None
            et = tech.get(etf) or {} if etf else {}
            sym5 = float(t["perf_week_pct"]) if t.get("perf_week_pct") is not None else None
            sec5 = float(et["perf_week_pct"]) if et.get("perf_week_pct") is not None else None
            spy5 = float(spy["perf_week_pct"]) if spy.get("perf_week_pct") is not None else None
            vs_sec5 = (sym5 - sec5) if (sym5 is not None and sec5 is not None) else None
            vs_spy5 = (sym5 - spy5) if (sym5 is not None and spy5 is not None) else None
            sec_label = "unavailable" if sec is None else (
                "outperforming sector" if (vs_sec5 or 0) > 1 else "lagging sector" if (vs_sec5 or 0) < -1 else "in-line")
            # protection state
            p = prot.get(sym, {})
            below = bool(cur_px is not None and ent is not None and cur_px < ent)
            stop_near = bool(cur_px is not None and stop is not None and stop and abs(cur_px - stop) / cur_px < 0.02)
            tp_missing = tgt is None or tgt == 0
            big_gain_unprot = bool(upnl_pct is not None and upnl_pct > 10 and tp_missing)
            p.update({"tp_missing": tp_missing, "stop_near": stop_near, "below_entry": below,
                      "trailing_candidate": bool(upnl_pct is not None and upnl_pct > 8 and not stop_near),
                      "protected": bool(stop and not below)})
            # action state
            warns = []
            if tp_missing:
                warns.append("TP missing")
            if stop_near:
                warns.append("stop near")
            if below:
                warns.append("below entry")
            if big_gain_unprot:
                warns.append("large gain unprotected")
            if (herm[sym]["alert_count_24h"] if sym in herm else 0) > 0:
                warns.append("Hermes alert 24h")
            if rsi is not None and rsi > 70:
                warns.append("overbought")
            level = "alert" if (stop_near or below or big_gain_unprot) else ("watch" if warns else "ok")
            label = warns[0] if warns else "Hold working"
            news_list = (news.get(sym) or []) + (herm[sym]["items"] if sym in herm else [])
            positions.append({
                "trade_id": r["trade_id"], "symbol": sym, "company_name": None,
                "account": r["account"], "broker": _broker_norm(r["broker"]),
                "environment": "paper" if (r["account"] or "").endswith("paper") else "live",
                "strategy": r["strategy_id"], "shares": sh, "entry_price": ent, "current_price": cur_px,
                "stop_price": stop, "target_price": tgt, "unrealized_pnl": upnl, "unrealized_pnl_pct": upnl_pct,
                "today_move_pct": today_move, "r_multiple": rmult, "hold_duration": _hold(r.get("entry_date")),
                "price_updated_at": px_at.isoformat() if hasattr(px_at, "isoformat") else None,
                "is_ticker": _is_ticker(sym),
                "technical": {"rsi": rsi, "rsi_bucket": _rsi_bucket(rsi), "rsi_direction": None,
                              "sma20_pct": (float(t["sma20_pct"]) if t.get("sma20_pct") is not None else None),
                              "sma50_pct": sma50, "sma200_pct": sma200,
                              "atr_pct": None, "rvol": (round(rvol, 2) if rvol else None),
                              "trend_label": _trend_label(sma50, sma200, cf.get("adx_regime")),
                              "adx_regime": cf.get("adx_regime"), "confluence_tier": cf.get("confluence_tier"),
                              "stale": stale_tech},
                "sector_relative": {"sector": sec, "sector_etf": etf, "symbol_perf_5d": sym5, "symbol_perf_1m":
                                    (float(t["perf_month_pct"]) if t.get("perf_month_pct") is not None else None),
                                    "sector_perf_5d": sec5, "spy_perf_5d": spy5, "vs_sector_5d": vs_sec5,
                                    "vs_spy_5d": vs_spy5, "label": sec_label},
                "news": news_list[:5],
                "hermes": {"latest_research_at": herm[sym]["research_at"] if sym in herm else None,
                           "finding_count_24h": herm[sym]["finding_count_24h"] if sym in herm else 0,
                           "alert_count_24h": herm[sym]["alert_count_24h"] if sym in herm else 0,
                           "top_finding": herm[sym]["top_finding"] if sym in herm else None,
                           "disagreement": herm[sym]["disagreement"] if sym in herm else False},
                "protection": p,
                "action_state": {"level": level, "label": label, "warnings": warns},
            })

        # ── summary + filter metadata ──
        def cnt(key, val):
            return sum(1 for p in positions if p.get(key) == val)
        total_pnl = sum(p["unrealized_pnl"] for p in positions if p["unrealized_pnl"] is not None)
        by_acct, by_broker = {}, {}
        for p in positions:
            by_acct[p["account"]] = by_acct.get(p["account"], 0) + 1
            by_broker[p["broker"]] = by_broker.get(p["broker"], 0) + 1
        last_hermes = max([p["hermes"]["latest_research_at"] for p in positions if p["hermes"]["latest_research_at"]] or [None])
        last_tech = max([t["snapshot_date"].isoformat() for t in tech.values() if t.get("snapshot_date")] or [None])
        last_price = max([p["price_updated_at"] for p in positions if p["price_updated_at"]] or [None])
        summary = {
            "total_positions": len(positions), "visible_positions": len(positions),
            "total_unrealized_pnl": total_pnl, "last_price_update": last_price,
            "last_hermes_update": last_hermes, "last_technical_update": last_tech,
            "by_account": by_acct, "by_broker": by_broker,
            "risk_counts": {"near_stop": sum(1 for p in positions if p["protection"]["stop_near"]),
                            "tp_missing": sum(1 for p in positions if p["protection"]["tp_missing"]),
                            "below_entry": sum(1 for p in positions if p["protection"]["below_entry"]),
                            "negative_news": sum(1 for p in positions if any((n.get("severity") == "high") for n in p["news"])),
                            "hermes_findings": sum(1 for p in positions if p["hermes"]["top_finding"] or p["hermes"]["alert_count_24h"]),
                            "large_gain_unprotected": sum(1 for p in positions if "large gain unprotected" in p["action_state"]["warnings"])},
        }
        filters = {
            "accounts": sorted(by_acct.keys()), "brokers": sorted(by_broker.keys()),
            "environments": sorted({p["environment"] for p in positions}),
            "strategies": sorted({p["strategy"] for p in positions if p["strategy"]}),
            "sectors": sorted({p["sector_relative"]["sector"] for p in positions if p["sector_relative"]["sector"]}),
            "technical_buckets": ["oversold", "neutral", "overbought", "missing"],
            "protection_states": ["protected", "tp_missing", "stop_near", "below_entry", "trailing_candidate", "large_gain_unprotected"],
        }
        return _nan_clean({"summary": summary, "filters": filters, "positions": positions})
    finally:
        c.close()


if __name__ == "__main__":
    import json
    print(json.dumps(build_intelligence(), default=str)[:2000])
