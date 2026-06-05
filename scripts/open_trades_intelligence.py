#!/usr/bin/env python3
"""open_trades_intelligence.py — aggregate READ-ONLY intelligence for v3 Open Trades.

SOURCE OF TRUTH = current holdings, NOT `trades.status='open'` (which contains stale/zero-share
phantom lots, e.g. sold-out AXTI). Base universe:
  - real accounts (schwab/fidelity): data/portfolios/state/holdings.json `holdings` (repriced, aggregated)
  - alpaca_paper: paper_trades WHERE status='open' (aggregated by symbol)
`trades` is used ONLY for enrichment (lot count, entry dates, stop/target, strategy) and to surface
stale-but-not-held rows in `excluded_items` — it never creates a position.

One normalized object per CURRENT held position, enriched with technicals + news + Hermes +
sector-relative + protection. No writes anywhere. NaN/Decimal-safe.
"""
import os
import json
from datetime import datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOLDINGS_JSON = os.path.join(PROJ, "data", "portfolios", "state", "holdings.json")

SECTOR_ETF = {"Technology": "XLK", "Financial": "XLF", "Financials": "XLF", "Healthcare": "XLV",
              "Health Care": "XLV", "Industrials": "XLI", "Consumer Discretionary": "XLY",
              "Consumer Cyclical": "XLY", "Consumer Staples": "XLP", "Consumer Defensive": "XLP",
              "Energy": "XLE", "Utilities": "XLU", "Real Estate": "XLRE", "Materials": "XLB",
              "Basic Materials": "XLB", "Communication Services": "XLC"}


def _conn():
    import psycopg2
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                            user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])


def _norm_acct(a):
    """Normalize account keys so holdings (schwab_roth) and trades (schwab_roth_ira) match."""
    return (a or "").lower().replace("_ira", "")


def _broker_norm(b):
    b = (b or "").lower()
    for k in ("alpaca", "schwab", "fidelity", "tos", "tradier"):
        if k in b:
            return k
    return b or "—"


def _is_numeric_cusip(sym):
    """True for security identifiers, not tradeable tickers: all-digit 6-12, or 9-char alphanumeric
    CUSIP (no dash) containing digits. Fund codes with dashes (JPM-LGCG) are NOT cusips."""
    s = str(sym or "").strip()
    if s.isdigit() and 6 <= len(s) <= 12:
        return True
    if len(s) == 9 and s.isalnum() and not s.isalpha() and any(ch.isdigit() for ch in s):
        return True
    return False


def _is_ticker(sym):
    return bool(sym) and sym.isalpha() and 1 <= len(sym) <= 5


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


def _age_hours(dt):
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - dt).total_seconds() / 3600.0, 1)


def _hold(ed):
    if not ed:
        return None
    d = ed.date() if hasattr(ed, "date") else ed
    try:
        return f"{(datetime.now(timezone.utc).date() - d).days}d"
    except Exception:
        return None


def _rsi_bucket(rsi):
    if rsi is None:
        return "missing"
    if rsi < 30:
        return "oversold"
    if rsi > 70:
        return "overbought"
    return "neutral"


def _trend_label(sma50_pct, sma200_pct):
    if sma50_pct is None and sma200_pct is None:
        return "unknown"
    above50 = (sma50_pct or 0) > 0
    above200 = (sma200_pct or 0) > 0
    if above50 and above200:
        return "bullish"
    if not above50 and not above200:
        return "bearish"
    return "neutral"


def _load_base_positions():
    """Returns (base[], excluded_items[], excl_counts) from holdings.json + paper_trades — current
    held positions only. base rows are partial dicts; enrichment is added later."""
    base, excluded, counts = [], [], {"zero_share": 0, "non_ticker": 0, "cash": 0}
    # ── real accounts: holdings.json (canonical, repriced) ──
    try:
        hj = json.load(open(HOLDINGS_JSON))
        for h in hj.get("holdings", []):
            sym = (h.get("symbol") or "").strip()
            acct = h.get("account")
            # paper accounts are sourced from paper_trades (canonical, always-current paper ledger);
            # holdings.json includes them only intermittently → skip here to keep paper consistent.
            if "paper" in (acct or "").lower():
                continue
            sh = float(h.get("shares") or 0)
            mv = float(h.get("market_value") or 0)
            if h.get("is_cash"):
                counts["cash"] += 1
                continue
            if sh <= 0 or mv <= 0:
                counts["zero_share"] += 1
                excluded.append({"account": h.get("account"), "symbol": sym,
                                 "reason": "zero_share_or_zero_value", "source": "holdings.json"})
                continue
            if _is_numeric_cusip(sym):
                counts["non_ticker"] += 1
                excluded.append({"account": h.get("account"), "symbol": sym,
                                 "reason": "non_ticker_security_id", "source": "holdings.json"})
                continue
            cb = h.get("cost_basis")
            base.append({
                "account": acct, "broker": _broker_norm(h.get("broker") or acct),
                "environment": "paper" if "paper" in (acct or "").lower() else "live", "symbol": sym, "company_name": h.get("name"),
                "shares": sh, "current_price": float(h["price"]) if h.get("price") is not None else None,
                "market_value": mv, "cost_basis": float(cb) if cb is not None else None,
                "avg_cost": (float(cb) / sh) if (cb and sh) else None,
                "unrealized_pnl": float(h["gain_loss"]) if h.get("gain_loss") is not None else None,
                "unrealized_pnl_pct": float(h["gain_loss_pct"]) if h.get("gain_loss_pct") is not None else None,
                "today_move_pct": float(h["day_change_pct"]) if h.get("day_change_pct") is not None else None,
                "is_fund": bool(h.get("is_fund")), "price_updated_at": h.get("updated_at") or hj.get("last_repriced"),
                "src": "holdings",
                "cost_basis_source": h.get("cost_basis_source"), "basis_partial_flag": bool(h.get("basis_partial")),
            })
    except Exception as e:
        excluded.append({"account": None, "symbol": None, "reason": f"holdings.json load error: {e}", "source": "holdings.json"})
    # ── alpaca paper: paper_trades open (canonical paper ledger), aggregated by symbol ──
    try:
        c = _conn(); cur = c.cursor()
        cur.execute("""SELECT account, symbol, sum(shares) sh,
                              sum(entry_price*shares)/NULLIF(sum(shares),0) avg_entry,
                              min(stop_loss) stop, max(target_1) tgt, min(strategy_id) strat, min(entry_time) ent
                       FROM paper_trades WHERE lower(status)='open' GROUP BY account, symbol""")
        for acct, sym, sh, avg_entry, stop, tgt, strat, ent in cur.fetchall():
            sh = float(sh or 0)
            if sh <= 0:
                counts["zero_share"] += 1
                continue
            avg = float(avg_entry) if avg_entry else None
            base.append({
                "account": acct, "broker": _broker_norm(acct), "environment": "paper", "symbol": (sym or "").strip(),
                "company_name": None, "shares": sh, "current_price": None, "market_value": None,
                "cost_basis": (avg * sh) if avg else None, "avg_cost": avg, "entry_price": avg,
                "stop_price": float(stop) if stop is not None else None,
                "target_price": float(tgt) if tgt is not None else None, "strategy": strat,
                "entry_date": ent, "unrealized_pnl": None, "unrealized_pnl_pct": None, "today_move_pct": None,
                "is_fund": False, "price_updated_at": None, "src": "paper_trades",
            })
        c.close()
    except Exception as e:
        excluded.append({"account": "alpaca_paper", "symbol": None, "reason": f"paper_trades error: {e}", "source": "paper_trades"})
    return base, excluded, counts


def build_intelligence():
    base, excluded, excl_counts = _load_base_positions()
    held_set = {(_norm_acct(p["account"]), p["symbol"]) for p in base}
    syms = sorted({p["symbol"] for p in base if p["symbol"]})
    tickers = [s for s in syms if _is_ticker(s)]

    c = _conn()
    import psycopg2.extras
    cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # ── STALE detection: trades.status=open (acct,symbol) NOT in current holdings → excluded ──
        cur.execute("""SELECT account, symbol, count(*) n, max(entry_date) last_entry
                       FROM trades WHERE lower(status)='open' GROUP BY account, symbol""")
        stale_count = 0
        for r in cur.fetchall():
            if (_norm_acct(r["account"]), (r["symbol"] or "").strip()) not in held_set:
                stale_count += r["n"]
                if len([e for e in excluded if e["reason"] == "not_in_current_holdings"]) < 60:
                    excluded.append({"account": r["account"], "symbol": r["symbol"],
                                     "reason": "not_in_current_holdings", "stale_trade_count": r["n"],
                                     "source": "trades_status_open"})

        # ── batch enrichment over CURRENT held symbols only ──
        quote, tech, conf, sector = {}, {}, {}, {}
        if syms:
            cur.execute("""SELECT DISTINCT ON (symbol) symbol, price, prev_close, day_change_pct, volume, avg_volume, fetched_at
                           FROM market_quotes WHERE symbol = ANY(%s) ORDER BY symbol, fetched_at DESC""", (syms,))
            quote = {r["symbol"]: r for r in cur.fetchall()}
        etf_syms = list(set(SECTOR_ETF.values())) + ["SPY"]
        if tickers or etf_syms:
            cur.execute("""SELECT DISTINCT ON (symbol) symbol, rsi, sma20_pct, sma50_pct, sma200_pct,
                           perf_week_pct, perf_month_pct, snapshot_date FROM ticker_snapshot_daily
                           WHERE symbol = ANY(%s) ORDER BY symbol, snapshot_date DESC""", (tickers + etf_syms,))
            tech = {r["symbol"]: r for r in cur.fetchall()}
        if tickers:
            cur.execute("""SELECT DISTINCT ON (symbol) symbol, atr, adx_regime, confluence_tier, computed_at
                           FROM indicator_confluence_cache WHERE symbol = ANY(%s) ORDER BY symbol, computed_at DESC""", (tickers,))
            conf = {r["symbol"]: r for r in cur.fetchall()}
            for tbl in ("aegis_symbol_snapshot_nightly", "intelligence_entities", "hermes_v_ticker_context"):
                miss = [s for s in tickers if s not in sector]
                if not miss:
                    break
                try:
                    cur.execute(f"SELECT DISTINCT ON (symbol) symbol, sector FROM {tbl} WHERE symbol = ANY(%s) AND sector IS NOT NULL ORDER BY symbol", (miss,))
                    for r in cur.fetchall():
                        sector[r["symbol"]] = r["sector"]
                except Exception:
                    c.rollback()
        # news
        news = {s: [] for s in syms}
        if tickers:
            cur.execute("""SELECT symbol, title, source, source_url, published_at, sentiment FROM news_articles
                           WHERE symbol = ANY(%s) AND coalesce(is_duplicate,false)=false
                           ORDER BY published_at DESC NULLS LAST LIMIT 600""", (tickers,))
            for r in cur.fetchall():
                if len(news.get(r["symbol"], [])) < 4:
                    news.setdefault(r["symbol"], []).append({"title": r["title"], "url": r["source_url"],
                        "source": r["source"] or "tradeai", "published_at": r["published_at"].isoformat() if r["published_at"] else None,
                        "age_hours": _age_hours(r["published_at"]), "sentiment": r["sentiment"], "severity": "info", "why_it_matters": None})
        # Hermes
        herm = {s: {"items": [], "research_at": None, "finding_count_24h": 0, "alert_count_24h": 0, "top_finding": None, "disagreement": False} for s in syms}
        if tickers:
            cur.execute("""SELECT symbol, summary, thesis, thesis_type, created_at FROM hermes_research_intelligence
                           WHERE symbol = ANY(%s) ORDER BY created_at DESC LIMIT 400""", (tickers,))
            for r in cur.fetchall():
                h = herm[r["symbol"]]
                if h["research_at"] is None:
                    h["research_at"] = r["created_at"].isoformat() if r["created_at"] else None
                if (_age_hours(r["created_at"]) or 999) <= 24:
                    h["finding_count_24h"] += 1
                if (r["thesis_type"] or "").lower() in ("bear", "bearish", "contrarian"):
                    h["disagreement"] = True
                if len(h["items"]) < 3:
                    h["items"].append({"title": (r["summary"] or r["thesis"] or "Hermes research")[:140], "url": None,
                        "source": "hermes", "published_at": r["created_at"].isoformat() if r["created_at"] else None,
                        "age_hours": _age_hours(r["created_at"]), "sentiment": r["thesis_type"], "severity": "info",
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
                        "published_at": r["created_at"].isoformat() if r["created_at"] else None, "age_hours": _age_hours(r["created_at"]),
                        "sentiment": None, "severity": "high" if sev in ("critical", "high", "urgent") else sev, "why_it_matters": r["alert_type"]})
            cur.execute("""SELECT symbol, description, severity, finding_type FROM hermes_validation_findings
                           WHERE symbol = ANY(%s) AND lower(coalesce(status,'open')) NOT IN ('resolved','dismissed')
                           ORDER BY created_at DESC LIMIT 200""", (tickers,))
            for r in cur.fetchall():
                h = herm.get(r["symbol"])
                if h and h["top_finding"] is None:
                    h["top_finding"] = {"finding_type": r["finding_type"], "severity": r["severity"], "description": (r["description"] or "")[:160]}

        # trades enrichment (lot context + stop/target/strategy) for HELD account+symbol only
        lots = {}
        if base:
            cur.execute("""SELECT account, symbol, count(*) lot_count, min(entry_date) first_entry, max(entry_date) last_entry,
                           max(stop_loss) stop, max(target_price) tgt, min(strategy_id) strat, max(r_multiple) rmult
                           FROM trades WHERE lower(status)='open' GROUP BY account, symbol""")
            for r in cur.fetchall():
                lots[(_norm_acct(r["account"]), r["symbol"])] = r
        # paper_trades enrichment (stop/target/strategy/entry for paper positions), keyed by symbol
        paper_lots = {}
        try:
            cur.execute("""SELECT symbol, min(stop_loss) stop, max(target_1) tgt, min(strategy_id) strat,
                           min(entry_time) ent, count(*) lc FROM paper_trades WHERE lower(status)='open' GROUP BY symbol""")
            paper_lots = {r["symbol"]: r for r in cur.fetchall()}
        except Exception:
            c.rollback()

        # protection (read-only)
        prot = {}
        try:
            cur.execute("""SELECT symbol, count(*) n, max(recommended_action) act FROM protection_adjustment_proposals
                           WHERE symbol = ANY(%s) AND lower(coalesce(status,'pending')) IN ('pending','open','proposed') GROUP BY symbol""", (syms,))
            prot = {r["symbol"]: r for r in cur.fetchall()}
        except Exception:
            c.rollback()

        # ── assemble ──
        spy = tech.get("SPY") or {}
        positions = []
        for p in base:
            sym = p["symbol"]
            lot = lots.get((_norm_acct(p["account"]), sym)) or {}
            pl = (paper_lots.get(sym) or {}) if p["environment"] == "paper" else {}
            q = quote.get(sym) or {}
            cur_px = p.get("current_price")
            if cur_px is None and q.get("price") is not None:
                cur_px = float(q["price"])
            ent = p.get("entry_price") or p.get("avg_cost")
            _stop = lot.get("stop") if lot.get("stop") is not None else pl.get("stop")
            _tgt = lot.get("tgt") if lot.get("tgt") is not None else pl.get("tgt")
            stop = p.get("stop_price") if p.get("stop_price") is not None else (float(_stop) if _stop is not None else None)
            tgt = p.get("target_price") if p.get("target_price") is not None else (float(_tgt) if _tgt is not None else None)
            sh = p["shares"]
            # paper P&L (holdings already has it)
            upnl = p.get("unrealized_pnl")
            upnl_pct = p.get("unrealized_pnl_pct")
            if upnl is None and cur_px is not None and ent is not None:
                upnl = (cur_px - ent) * sh
                upnl_pct = ((cur_px - ent) / ent * 100) if ent else None
            # ── basis validation. Prefer the explicit cost_basis_source set by the import repair: a
            #    trusted source (operator_provided, reconstructed_from_amounts, fidelity_positions_pdf)
            #    is honoured as-is even with a large legit gain (e.g. V at $43 → +600%). Only fall back
            #    to the heuristic when there is no source flag (legacy/unrepaired data). ──
            TRUSTED = {"operator_provided", "operator_provided_carry_forward",
                       "reconstructed_from_amounts", "fidelity_positions_pdf"}
            basis_reliable, basis_warning = True, None
            cbasis, avgc = p.get("cost_basis"), p.get("avg_cost")
            cbsrc = p.get("cost_basis_source")
            if p.get("src") != "paper_trades":  # holdings
                if p.get("basis_partial_flag") or cbasis is None or avgc is None:
                    basis_reliable, basis_warning = False, (cbsrc or "no_cost_basis")
                elif cbsrc in TRUSTED:
                    basis_reliable, basis_warning = True, None  # authoritative basis — trust it
                elif (cur_px and avgc < 0.10 * cur_px) or (upnl_pct is not None and (upnl_pct > 400 or upnl_pct < -99)):
                    basis_reliable, basis_warning = False, "basis_unverified"
            if not basis_reliable:
                upnl, upnl_pct = None, None  # do not show P&L derived from unreliable basis
            today = p.get("today_move_pct")
            if today is None and q.get("day_change_pct") is not None:
                today = float(q["day_change_pct"])
            rvol = (float(q["volume"]) / float(q["avg_volume"])) if (q.get("volume") and q.get("avg_volume")) else None
            t = tech.get(sym) or {}
            cf = conf.get(sym) or {}
            rsi = float(t["rsi"]) if t.get("rsi") is not None else None
            sma50 = float(t["sma50_pct"]) if t.get("sma50_pct") is not None else None
            sma200 = float(t["sma200_pct"]) if t.get("sma200_pct") is not None else None
            stale_tech = not t and not cf
            sec = sector.get(sym)
            etf = SECTOR_ETF.get(sec) if sec else None
            et = (tech.get(etf) or {}) if etf else {}
            sym5 = float(t["perf_week_pct"]) if t.get("perf_week_pct") is not None else None
            sec5 = float(et["perf_week_pct"]) if et.get("perf_week_pct") is not None else None
            spy5 = float(spy["perf_week_pct"]) if spy.get("perf_week_pct") is not None else None
            vs_sec5 = (sym5 - sec5) if (sym5 is not None and sec5 is not None) else None
            vs_spy5 = (sym5 - spy5) if (sym5 is not None and spy5 is not None) else None
            sec_label = "unavailable" if sec is None else ("outperforming sector" if (vs_sec5 or 0) > 1 else "lagging sector" if (vs_sec5 or 0) < -1 else "in-line")
            below = bool(cur_px is not None and ent is not None and cur_px < ent)
            stop_near = bool(cur_px is not None and stop is not None and stop and abs(cur_px - stop) / cur_px < 0.02)
            tp_missing = tgt is None or tgt == 0
            big_gain_unprot = bool(upnl_pct is not None and upnl_pct > 10 and tp_missing)
            pr = {"protected": bool(stop and not below), "tp_missing": tp_missing, "stop_near": stop_near,
                  "below_entry": below, "trailing_candidate": bool(upnl_pct is not None and upnl_pct > 8 and not stop_near),
                  "top_recommendation": (prot.get(sym) or {}).get("act"), "option_count": (prot.get(sym) or {}).get("n", 0)}
            warns = []
            if tp_missing and p["src"] != "holdings":
                warns.append("TP missing")
            if stop_near:
                warns.append("stop near")
            if below:
                warns.append("below entry")
            if big_gain_unprot:
                warns.append("large gain unprotected")
            if herm.get(sym, {}).get("alert_count_24h", 0) > 0:
                warns.append("Hermes alert 24h")
            if rsi is not None and rsi > 70:
                warns.append("overbought")
            level = "alert" if (stop_near or big_gain_unprot) else ("watch" if warns else "ok")
            ent_date = p.get("entry_date") or lot.get("first_entry") or pl.get("ent")
            positions.append({
                "trade_id": None, "symbol": sym, "company_name": p.get("company_name"),
                "account": p["account"], "broker": p["broker"], "environment": p["environment"],
                "strategy": p.get("strategy") or lot.get("strat") or pl.get("strat"), "shares": sh, "is_fund": p.get("is_fund", False),
                "entry_price": ent, "avg_cost": p.get("avg_cost"), "cost_basis": p.get("cost_basis"),
                "basis_kind": ("entry" if p.get("src") == "paper_trades" else "avg_cost"),
                "basis_reliable": basis_reliable, "basis_warning": basis_warning,
                "cost_basis_source": p.get("cost_basis_source"),
                "current_price": cur_px, "market_value": p.get("market_value") or (cur_px * sh if cur_px else None),
                "stop_price": stop, "target_price": tgt, "unrealized_pnl": upnl, "unrealized_pnl_pct": upnl_pct,
                "today_move_pct": today, "r_multiple": float(lot["rmult"]) if lot.get("rmult") is not None else None,
                "lot_count": lot.get("lot_count", 1), "hold_duration": _hold(ent_date),
                "price_updated_at": p.get("price_updated_at"),
                "is_ticker": _is_ticker(sym),
                "technical": {"rsi": rsi, "rsi_bucket": _rsi_bucket(rsi), "rsi_direction": None,
                              "sma20_pct": (float(t["sma20_pct"]) if t.get("sma20_pct") is not None else None),
                              "sma50_pct": sma50, "sma200_pct": sma200, "atr_pct": None,
                              "rvol": (round(rvol, 2) if rvol else None),
                              "trend_label": _trend_label(sma50, sma200), "adx_regime": cf.get("adx_regime"),
                              "confluence_tier": cf.get("confluence_tier"), "stale": stale_tech},
                "sector_relative": {"sector": sec, "sector_etf": etf, "symbol_perf_5d": sym5,
                                    "symbol_perf_1m": (float(t["perf_month_pct"]) if t.get("perf_month_pct") is not None else None),
                                    "sector_perf_5d": sec5, "spy_perf_5d": spy5, "vs_sector_5d": vs_sec5, "vs_spy_5d": vs_spy5, "label": sec_label},
                "news": (news.get(sym) or []) + herm.get(sym, {}).get("items", []),
                "hermes": {"latest_research_at": herm.get(sym, {}).get("research_at"), "finding_count_24h": herm.get(sym, {}).get("finding_count_24h", 0),
                           "alert_count_24h": herm.get(sym, {}).get("alert_count_24h", 0), "top_finding": herm.get(sym, {}).get("top_finding"),
                           "disagreement": herm.get(sym, {}).get("disagreement", False)},
                "protection": pr,
                "action_state": {"level": level, "label": (warns[0] if warns else "Hold working"), "warnings": warns},
            })
        positions.sort(key=lambda p: (-(p["market_value"] or 0)))

        total_pnl = sum(p["unrealized_pnl"] for p in positions if p["unrealized_pnl"] is not None)
        by_acct, by_broker = {}, {}
        for p in positions:
            by_acct[p["account"]] = by_acct.get(p["account"], 0) + 1
            by_broker[p["broker"]] = by_broker.get(p["broker"], 0) + 1
        last_hermes = max([p["hermes"]["latest_research_at"] for p in positions if p["hermes"]["latest_research_at"]] or [None])
        last_tech = max([t["snapshot_date"].isoformat() for t in tech.values() if t.get("snapshot_date")] or [None])
        summary = {
            "total_positions": len(positions), "visible_positions": len(positions), "total_unrealized_pnl": total_pnl,
            "source_of_truth": "current_holdings_plus_paper_positions",
            "excluded_stale_trade_rows": stale_count, "excluded_zero_share_rows": excl_counts["zero_share"],
            "excluded_non_ticker_rows": excl_counts["non_ticker"], "excluded_cash_rows": excl_counts["cash"],
            "basis_unverified_count": sum(1 for p in positions if not p["basis_reliable"]),
            "last_price_update": max([p["price_updated_at"] for p in positions if p["price_updated_at"]] or [None]),
            "last_hermes_update": last_hermes, "last_technical_update": last_tech,
            "by_account": by_acct, "by_broker": by_broker,
            "risk_counts": {"near_stop": sum(1 for p in positions if p["protection"]["stop_near"]),
                            "tp_missing": sum(1 for p in positions if p["protection"]["tp_missing"] and p.get("basis_kind") != "avg_cost"),
                            "below_entry": sum(1 for p in positions if p["protection"]["below_entry"]),
                            "negative_news": sum(1 for p in positions if any(n.get("severity") == "high" for n in p["news"])),
                            "hermes_findings": sum(1 for p in positions if p["hermes"]["top_finding"] or p["hermes"]["alert_count_24h"]),
                            "large_gain_unprotected": sum(1 for p in positions if "large gain unprotected" in p["action_state"]["warnings"])},
        }
        filters = {"accounts": sorted(by_acct.keys()), "brokers": sorted(by_broker.keys()),
                   "environments": sorted({p["environment"] for p in positions}),
                   "strategies": sorted({p["strategy"] for p in positions if p["strategy"]}),
                   "sectors": sorted({p["sector_relative"]["sector"] for p in positions if p["sector_relative"]["sector"]}),
                   "technical_buckets": ["oversold", "neutral", "overbought", "missing"],
                   "protection_states": ["protected", "tp_missing", "stop_near", "below_entry", "trailing_candidate"]}
        return _nan_clean({"summary": summary, "filters": filters, "positions": positions, "excluded_items": excluded})
    finally:
        c.close()


if __name__ == "__main__":
    print(json.dumps(build_intelligence(), default=str)[:2000])
