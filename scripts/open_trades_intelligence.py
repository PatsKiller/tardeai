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

# Fallback sector for common holdings the sector table lacks (read-only display aid only).
_SECTOR_FALLBACK = {"AGNC": "Real Estate", "NWG": "Financial", "NUVL": "Healthcare", "TMHC": "Consumer Cyclical",
                    "AGM": "Financial", "RKLB": "Industrials", "IRDM": "Technology", "V": "Financial"}

# Authoritative ETF/fund sector. Finviz reports EVERY ETF as sector "Financial" (industry
# "Exchange Traded Fund"), which mislabels industrials/materials/bond/income funds. This map takes
# PRECEDENCE over the (Finviz-sourced) sector table: sector SPDRs → their real GICS sector; broad/
# bond/income funds → an honest asset-class label (no single sector → no vs-sector benchmark).
_ETF_SECTOR = {
    "XLK": "Technology", "XLF": "Financial", "XLV": "Healthcare", "XLE": "Energy",
    "XLI": "Industrials", "XLB": "Materials", "XLU": "Utilities", "XLP": "Consumer Defensive",
    "XLY": "Consumer Cyclical", "XLRE": "Real Estate", "XLC": "Communication Services",
    "BND": "Fixed Income", "AGG": "Fixed Income", "TLT": "Fixed Income", "BNDX": "Fixed Income", "LQD": "Fixed Income",
    "JEPI": "Income / Covered Call", "JEPQ": "Income / Covered Call",
    "SCHD": "Dividend Equity", "DGRO": "Dividend Equity", "VYM": "Dividend Equity", "SCHG": "Growth Equity",
    "SPY": "Broad Equity", "VOO": "Broad Equity", "VTI": "Broad Equity", "QQQ": "Broad Equity", "IWM": "Broad Equity",
    "ARKG": "Healthcare", "ARKK": "Innovation", "ARKQ": "Innovation", "ARKW": "Innovation", "ARKF": "Innovation",
}

_STRATEGY_PURPOSE_CACHE = None


def _strategy_purposes():
    """Load each strategy's `purpose:` from config/strategies/*.yaml — the 'why this strategy' rationale."""
    global _STRATEGY_PURPOSE_CACHE
    if _STRATEGY_PURPOSE_CACHE is not None:
        return _STRATEGY_PURPOSE_CACHE
    out = {}
    d = os.path.join(PROJ, "config", "strategies")
    try:
        for fn in os.listdir(d):
            if not fn.endswith(".yaml"):
                continue
            name = fn[:-5]
            for line in open(os.path.join(d, fn), encoding="utf-8"):
                if line.startswith("purpose:"):
                    out[name] = line.split("purpose:", 1)[1].strip().strip('"').strip("'")
                    break
    except Exception:
        pass
    _STRATEGY_PURPOSE_CACHE = out
    return out


def _derive_decision(*, upnl_pct, protected, stop, tp_missing, big_gain_unprot, below, stop_near, rsi,
                     stale_tech, basis_reliable, cost_basis_source, basis_kind, market_value, strategy,
                     trend_label, sec_label, vs_sec5, latest_news_age_h, last_hermes_at, on_watchlist,
                     directive, is_fund, family="position", mutual_fund=False, broker_protected=False):
    """Derive the read-only operator-decision fields. Pure function of already-computed signals — no writes,
    no source-of-truth changes. Action language is review/consider only, never execute."""
    high_value = (market_value or 0) >= 50000
    risk_flags, opp_flags = [], []
    # risk
    if big_gain_unprot:
        risk_flags.append("large_gain_unprotected")
    if not protected and not stop:
        risk_flags.append("no_protection")
    if not basis_reliable:
        risk_flags.append("basis_unknown")
    if stale_tech:
        risk_flags.append("data_stale")
    if below:
        risk_flags.append("below_entry")
    if rsi is not None and rsi > 75:
        risk_flags.append("overbought")
    if stop_near:
        risk_flags.append("stop_near")
    # opportunity
    if upnl_pct is not None and upnl_pct > 8 and not stop_near:
        opp_flags.append("trailing_candidate")
    if (vs_sec5 or 0) > 1:
        opp_flags.append("outperforming_sector")
    if trend_label and "bull" in str(trend_label).lower():
        opp_flags.append("bullish_trend")
    # freshness
    data_freshness = "stale" if stale_tech else "fresh"
    if latest_news_age_h is None:
        news_freshness = "none"
    elif latest_news_age_h <= 24:
        news_freshness = "fresh"
    elif latest_news_age_h <= 48:
        news_freshness = "aging"
    else:
        news_freshness = "stale"
    # broker_protected covers TRAILING stops, which protect without a fixed `stop` level (it's dynamic).
    protection_state = "protected" if (broker_protected or (protected and stop)) else ("partial" if stop else "unprotected")
    basis_quality = ("broker" if cost_basis_source in ("broker", "schwab", "alpaca", "broker_api") else
                     "tax_grade" if cost_basis_source in ("csv", "tax", "documented", "csv_lot") else
                     "owner_provided" if cost_basis_source in ("owner", "owner_provided", "manual") else
                     "entry" if basis_kind == "entry" else
                     # 2026-06-12: reconstruction is NEVER badged "verified" again — the SCHG/SCHD
                     # audit showed reconstructed basis can be wildly wrong while wearing the badge
                     "reconstructed" if cost_basis_source == "reconstructed_from_amounts" else
                     "verified" if basis_reliable else "unknown")
    watchlist_state = "directive" if directive else ("watchlist" if on_watchlist else "none")
    # decision (most important text) — priority-ordered
    if not basis_reliable and high_value:
        decision, reason, pr = "Cost basis uncertain", "High-value position with unverified cost basis — resolve before any tax/exit decision.", "high"
        nxt = "Resolve cost basis (CSV/broker reconciliation)"
    elif mutual_fund and ((upnl_pct or 0) > 10 or big_gain_unprot):
        # Fund with no exchange stop (mutual fund or 401k/proxy code): a stop CANNOT be placed (transacts at
        # NAV / inside the plan). A large gain is still worth protecting — via a tax-aware trim / rebalance.
        decision, reason, pr = ("Large gain — review trim (fund)",
            f"+{round(upnl_pct or 0)}% in a fund with no exchange stop available — protect the gain with a "
            "tax-aware trim / rebalance, not a stop order.", "high")
        nxt = "Review trim / rebalance (no stop on a fund)"
    elif big_gain_unprot or (not protected and not stop and (upnl_pct or 0) > 10):
        decision, reason, pr = "Needs protection review", f"+{round(upnl_pct or 0)}% gain with no active protection{', bullish trend' if 'bullish_trend' in opp_flags else ''}{', trailing candidate' if 'trailing_candidate' in opp_flags else ''}.", "high"
        nxt = "Review protection / trailing-stop placement"
    elif stale_tech and high_value:
        decision, reason, pr = "Data stale — refresh first", "Technicals are stale on a high-value position — refresh intelligence before judging.", "high"
        nxt = "Refresh intelligence, then re-review"
    elif below and (upnl_pct or 0) < -5:
        decision, reason, pr = "Needs exit review", f"Down {round(upnl_pct or 0)}% and below entry — review thesis vs exit.", "medium"
        nxt = "Review exit vs thesis"
    elif family == "income" or (strategy and ("income" in str(strategy) or "dividend" in str(strategy))):
        # Income-family holding (dividend/bond ETF): held for yield, not momentum. A hard protective stop
        # is OPTIONAL by design — income holdings are held through noise to keep the distribution. Frame as
        # an income role, not as a missing stop.
        decision, reason, pr = ("Income role — held for yield",
            "Held for income/distributions, not price momentum. A protective stop is OPTIONAL here (income "
            "holdings ride through noise to keep the yield) — monitor distributions + total return instead.", "low")
        nxt = "Income role — monitor distributions (stop optional)"
    elif "no_protection" in risk_flags:
        if mutual_fund:
            # Un-stoppable fund (mutual fund or 401k/proxy code), no large gain: don't tell the operator to
            # place a stop that can't exist.
            decision, reason, pr = ("Fund — no exchange stop",
                "Fund / plan holding: a protective stop order can't be placed (transacts at NAV / inside "
                "the plan). Manage via sell / rebalance and monitor total return — a stop does not apply.", "low")
            nxt = "Monitor NAV / total return — no stop applies"
        else:
            # Stop-eligible (stock or ETF), unprotected, low-urgency. NO protective stop in place. Do NOT say
            # "No action" — that reads as "no stop needed". State the gap; mark it optional/low. Advisory-neutral.
            decision, reason, pr = ("Unprotected — no stop in place",
                "No protective stop is set. A stop is worth placing to cap downside — low urgency at this "
                "size/gain, but this is NOT 'no stop needed'. See the advised level below if present.", "low")
            nxt = "Consider placing a protective stop (optional)"
    elif trend_label and "bull" in str(trend_label).lower() and not risk_flags:
        decision, reason, pr = "Hold thesis intact", "Thesis intact: trend supportive, protective stop in place, no data flags.", "low"
        nxt = "No action needed — protected & monitored"
    else:
        # Reached only when a stop IS in place (protected/partial) and nothing else flags — genuinely nothing to do.
        decision, reason, pr = "No action — monitored", "Protective stop in place and within normal parameters — nothing to do.", "low"
        nxt = "No action needed — protected & monitored"
    # priority escalation by value
    if pr == "high" and high_value:
        pr = "critical"
    actions = []
    if "Needs protection" in decision:
        actions.append("Review protection")
    if "exit" in decision.lower():
        actions.append("Review exit thesis")
    if "basis" in decision.lower():
        actions.append("Reconcile cost basis")
    if "stale" in decision.lower():
        actions.append("Refresh intelligence")
    actions += ["Open replay", "Open journal", "Open news"]
    return {
        "operator_priority": pr, "operator_decision": decision, "decision_reason": reason,
        "risk_flags": risk_flags, "opportunity_flags": opp_flags,
        "data_freshness": data_freshness, "news_freshness": news_freshness,
        "protection_state": protection_state, "basis_quality": basis_quality,
        "watchlist_state": watchlist_state, "directive_state": ("active" if directive else "none"),
        "last_hermes_review_at": last_hermes_at, "latest_news_age_hours": latest_news_age_h,
        "primary_next_review": nxt, "recommended_manual_actions": actions[:6],
        "strategy_rationale": (_strategy_purposes().get(str(strategy), None)),
    }


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
        # UPPER(account): paper_trades carries mixed-case account keys ('ALPACA_PAPER' vs 'alpaca_paper'
        # on older rows) — without normalization they surface as two phantom accounts in the UI filters
        # (operator caught this 2026-06-12 via the account badges).
        cur.execute("""SELECT UPPER(account) account, symbol, sum(shares) sh,
                              sum(entry_price*shares)/NULLIF(sum(shares),0) avg_entry,
                              min(stop_loss) stop, max(target_1) tgt, min(strategy_id) strat, min(entry_time) ent
                       FROM paper_trades WHERE lower(status)='open' GROUP BY UPPER(account), symbol""")
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


_BSTOP_CACHE = {"ts": 0.0, "map": {}, "key": None, "fetched_at": None}
_ASTOP_CACHE = {"ts": 0.0, "map": {}, "fetched_at": None}
_BSTOP_TERMINAL = {"canceled", "cancelled", "filled", "rejected", "expired", "replaced", "working_rejected"}


def _alpaca_protective_stops():
    """Stage 2c — read Alpaca's LIVE working SELL stop/trailing-stop orders for the PAPER account (source of
    truth for paper protection — the bracket/ratchet stops the paper pipeline places). Keyed by
    (_norm_acct('alpaca_paper'), symbol), same shape as _broker_protective_stops so callers can merge the
    two transparently. Cached 60s; fail-open (empty on any read error so Open Trades never blocks)."""
    import time
    if time.time() - _ASTOP_CACHE["ts"] < 60 and _ASTOP_CACHE["map"]:
        return _ASTOP_CACHE["map"]
    out = {}
    try:
        import alpaca_paper_reconciler as apr
        env = apr.get_env()
        acct_norm = _norm_acct("alpaca_paper")
        for o in (apr.get_alpaca_orders(env, status="open") or []):
            if str(o.get("side", "")).lower() != "sell":
                continue
            otype = str(o.get("type", "") or o.get("order_type", "")).upper()
            if "STOP" not in otype and "TRAILING" not in otype:
                continue
            if str(o.get("status", "")).lower() in _BSTOP_TERMINAL:
                continue
            sym = str(o.get("symbol", "")).upper()
            if not sym:
                continue
            _sp = o.get("stop_price")
            try:
                sp = float(_sp) if _sp not in (None, "", 0, "0", "0.0") else None
            except Exception:
                sp = None
            _to = o.get("trail_price") or o.get("trail_percent")
            try:
                trail_offset = float(_to) if _to not in (None, "") else None
            except Exception:
                trail_offset = None
            out[(acct_norm, sym)] = {
                "order_id": str(o.get("id") or ""), "stop_price": sp,
                "trail_offset": trail_offset, "trail_link": ("trail" if trail_offset else None),
                "order_type": otype.replace(" ", "_"), "status": str(o.get("status", "")).lower(),
                "qty": o.get("qty"), "account": "alpaca_paper", "source": "broker"}
    except Exception:
        return out
    import datetime as _dt
    _fetched = _dt.datetime.now(_dt.timezone.utc).isoformat()
    for _v in out.values():
        _v["fetched_at"] = _fetched
    _ASTOP_CACHE.update(ts=time.time(), map=out, fetched_at=_fetched)
    return out


def _broker_protective_stops(accounts):
    """Stage 2c FULL STOP MONITORING — read the broker's LIVE working/pending SELL stop orders (source of
    truth) for the given real accounts and key them by (norm_account, symbol). Captures stops placed via the
    Command Center AND any placed manually in thinkorswim. Cached 60s; fail-open (empty on any read error so
    the Open Trades page never blocks on a slow broker call). Returns {(acct, sym): {order_id, stop_price,
    order_type, status, qty, account}}."""
    import time
    _ckey = tuple(sorted({(a or "").lower() for a in (accounts or [])}))
    if time.time() - _BSTOP_CACHE["ts"] < 60 and _BSTOP_CACHE.get("key") == _ckey and _BSTOP_CACHE["map"]:
        return _BSTOP_CACHE["map"]
    import datetime as _dt
    out = {}
    # Alpaca paper account uses its own trading API (not Schwab) — pull its live SELL stops too so paper
    # positions count as broker-protected on the same canonical footing. Only when a paper acct is requested.
    if any("alpaca" in (a or "").lower() for a in (accounts or [])):
        try:
            out.update(_alpaca_protective_stops())
        except Exception:
            pass
    try:
        import schwab_transport as st
    except Exception:
        _fetched = _dt.datetime.now(_dt.timezone.utc).isoformat()
        _BSTOP_CACHE.update(ts=time.time(), map=out, key=_ckey, fetched_at=_fetched)
        return out
    for acct in accounts:
        try:
            raw = st.get_orders_raw(acct)   # RAW so we capture trailing fields (offset/link), not just a fixed price
            if not isinstance(raw, list):
                continue  # dict ⇒ NOT_PROVEN/degraded/error — skip this account, keep others
            for o in (raw or []):
                leg = (o.get("orderLegCollection") or [{}])[0]
                if str(leg.get("instruction", "")).upper() not in ("SELL", "SELL_SHORT"):
                    continue
                otype = str(o.get("orderType", "")).upper()
                if "STOP" not in otype and "TRAILING" not in otype:
                    continue
                if str(o.get("status", "")).lower() in _BSTOP_TERMINAL:
                    continue
                sym = str((leg.get("instrument") or {}).get("symbol", "")).upper()
                if not sym:
                    continue
                _sp = o.get("stopPrice")
                try:
                    sp = float(_sp) if _sp not in (None, "", 0, "0", "0.0") else None  # fixed stop level (None for trailing — it's dynamic)
                except Exception:
                    sp = None
                _to = o.get("stopPriceOffset")
                try:
                    trail_offset = float(_to) if _to not in (None, "") else None
                except Exception:
                    trail_offset = None
                # A live SELL stop/trailing order IS protection regardless of whether it carries a fixed price.
                out[(_norm_acct(acct), sym)] = {
                    "order_id": str(o.get("orderId") or ""), "stop_price": sp,
                    "trail_offset": trail_offset, "trail_link": o.get("stopPriceLinkType"),
                    "order_type": otype.replace(" ", "_"), "status": str(o.get("status", "")).lower(),
                    "qty": leg.get("quantity"), "account": acct, "source": "broker"}
        except Exception:
            continue
    _fetched = _dt.datetime.now(_dt.timezone.utc).isoformat()
    for _v in out.values():
        _v["fetched_at"] = _fetched
    _BSTOP_CACHE.update(ts=time.time(), map=out, key=_ckey, fetched_at=_fetched)
    return out


def broker_stops_fetched_at() -> str | None:
    """ISO timestamp of the last Schwab/Alpaca protective-stop API read (60s cache)."""
    return _BSTOP_CACHE.get("fetched_at") or _ASTOP_CACHE.get("fetched_at")


def build_intelligence():
    base, excluded, excl_counts = _load_base_positions()
    held_set = {(_norm_acct(p["account"]), p["symbol"]) for p in base}
    syms = sorted({p["symbol"] for p in base if p["symbol"]})
    # watchlist + directive membership (read-only) for the decision enrichment
    # ── Card enrichment maps (2026-06-11): surface what the system already knows ─────────────────────────
    _pills_by_sym, _l2_by_sym, _hermes_rank, _enrich_by_sym = {}, {}, {}, {}
    try:
        import json as _j
        _pd = _j.loads(open(os.path.join(PROJ, "data", "runtime", "pro_analyst_pills_latest.json")).read_text() if False else open(os.path.join(PROJ, "data", "runtime", "pro_analyst_pills_latest.json")).read())
        for _pl in (_pd.get("pills") or (_pd if isinstance(_pd, list) else [])):
            _pills_by_sym[(_pl.get("symbol") or "").upper()] = _pl
    except Exception:
        pass
    try:
        _c2 = _conn(); _cur2 = _c2.cursor()
        _cur2.execute("""SELECT DISTINCT ON (symbol) symbol, imbalance, bid_depth, ask_depth, captured_at
                         FROM schwab_stream_book ORDER BY symbol, captured_at DESC""")
        _l2_by_sym = {r[0]: {"symbol": r[0], "imbalance": r[1], "bid_depth": r[2], "ask_depth": r[3],
                             "captured_at": r[4]} for r in _cur2.fetchall()}
        _cur2.execute("""SELECT DISTINCT ON (symbol) symbol, hermes_rank, hermes_composite_score
                         FROM watchlist_items WHERE hermes_rank IS NOT NULL ORDER BY symbol, hermes_rank""")
        _hermes_rank = {r[0]: {"symbol": r[0], "hermes_rank": r[1], "hermes_composite_score": r[2]}
                        for r in _cur2.fetchall()}
        _c2.close()
    except Exception:
        pass
    try:
        import json as _j
        _ec = _j.loads(open(os.path.join(PROJ, "data", "state", "ticker_enrichment_cache.json")).read())
        _enrich_by_sym = {k.upper(): v for k, v in (_ec.get("tickers") or _ec or {}).items() if isinstance(v, dict)}
    except Exception:
        pass

    def _card_enrichment(sym, cur_px=None):
        out = {}
        pl = _pills_by_sym.get(sym)
        if pl:
            # Recompute upside vs the LIVE price — the stored upside_to_mean_target_pct is frozen at
            # analyst-fetch time and goes stale fast on a moving name (e.g. SPCX +11% intraday).
            _tm = pl.get("target_mean_price")
            try:
                _upside = ((float(_tm) - cur_px) / cur_px * 100) if (_tm and cur_px) else pl.get("upside_to_mean_target_pct")
            except (TypeError, ValueError, ZeroDivisionError):
                _upside = pl.get("upside_to_mean_target_pct")
            out["analyst"] = {
                "rating": pl.get("recommendation_key"), "rating_mean": pl.get("recommendation_mean"),
                "opinions": pl.get("number_of_analyst_opinions"),
                "target_mean": pl.get("target_mean_price"), "target_high": pl.get("target_high_price"),
                "target_low": pl.get("target_low_price"),
                "target_upside_pct": round(_upside, 1) if _upside is not None else None,
                "source": pl.get("analyst_rating_source"),
                "latest_event": pl.get("latest_event_headline"),
            }
        l2 = _l2_by_sym.get(sym)
        if l2:
            out["l2_pressure"] = {"imbalance": float(l2["imbalance"]) if l2.get("imbalance") is not None else None,
                                  "bid_depth": float(l2.get("bid_depth") or 0), "ask_depth": float(l2.get("ask_depth") or 0),
                                  "at": str(l2.get("captured_at"))[11:19]}
        hr = _hermes_rank.get(sym)
        if hr:
            out["hermes_rank"] = hr.get("hermes_rank")
            out["hermes_composite"] = float(hr["hermes_composite_score"]) if hr.get("hermes_composite_score") is not None else None
        en = _enrich_by_sym.get(sym) or {}
        if en.get("earnings_date"):
            out["earnings_date"] = en.get("earnings_date")
        if en.get("short_float_pct") is not None:
            out["short_float_pct"] = en.get("short_float_pct")
        return out

    wl_set, dir_set = set(), set()
    try:
        for r in (_db_query("SELECT DISTINCT symbol FROM watchlist_items WHERE status IN ('active','researched') AND symbol = ANY(%s)", (syms,)) or []):
            wl_set.add(r["symbol"])
        for r in (_db_query("SELECT DISTINCT UPPER(spec->>'symbol') sym FROM watch_directives WHERE status='active' AND spec ? 'symbol'", None) or []):
            if r.get("sym"):
                dir_set.add(r["sym"])
    except Exception:
        pass
    # proxy-mapped fund codes (FID-CONTRA-F etc.) now carry proxy-computed technicals in
    # ticker_snapshot_daily (technicals_gap_backfill, 2026-06-12) — include them in the lookup
    try:
        from holding_proxies import HOLDING_PROXY_MAP as _PXM
    except Exception:
        _PXM = {}
    tickers = [s for s in syms if _is_ticker(s) or s in _PXM]

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
        # FULL STOP MONITORING: pull the broker's live working/pending stops once (cached) for every account
        # with a live trading API in view — Schwab (ToS/API stops) AND Alpaca paper (bracket/ratchet stops) —
        # so a placed protective stop (ours or a manual ToS one) shows as PROTECTED on the same footing.
        _bstop_accts = sorted({p["account"] for p in base
                               if str(p.get("account", "")).startswith("schwab")
                               or "alpaca" in str(p.get("account", "")).lower()})
        bmap = _broker_protective_stops(_bstop_accts) if _bstop_accts else {}
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
            # FULL STOP MONITORING overlay: a LIVE broker stop is the source of truth — it sets the real stop
            # price and marks the position PROTECTED regardless of below-entry (a placed stop IS protection).
            _bstop = bmap.get((_norm_acct(p["account"]), sym))
            broker_protected = bool(_bstop)   # ANY live SELL stop/trailing order = protected (trailing has no fixed price)
            broker_stop_payload = None
            if broker_protected:
                if _bstop.get("stop_price") is not None:
                    stop = float(_bstop["stop_price"])   # fixed stop → real level; trailing → dynamic, leave advised/None
                # COVERAGE CHECK: a standalone GTC stop does NOT auto-resize when the position is trimmed.
                # Compare the stop's share count to shares held now: oversized (stop qty > held → on trigger
                # it could short the difference in a margin acct / reject in cash) or partial (only some
                # shares protected). Surfaced so the card can warn + offer resize. (operator Q 2026-06-15)
                _held = None
                try:
                    _held = float(p.get("shares") or 0)
                except Exception:
                    _held = None
                try:
                    _sq = float(_bstop.get("qty") or 0)
                except Exception:
                    _sq = 0.0
                coverage = "full"
                if _held and _sq:
                    if _sq > _held + 1e-6:
                        coverage = "oversized"
                    elif _sq < _held - 1e-6:
                        coverage = "partial"
                broker_stop_payload = {**_bstop, "held_qty": _held, "coverage": coverage}
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
            # 2026-06-12 basis-audit fix: reconstruction REMOVED from trusted (SCHD showed a +$111K
            # phantom gain wearing "verified"); broker_api + csv_lot added (sync_basis_from_broker
            # hierarchy: csv tax lot > Schwab averagePrice > nothing).
            TRUSTED = {"operator_provided", "operator_provided_carry_forward",
                       "fidelity_positions_pdf", "broker_api", "csv_lot"}
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
            sec = _ETF_SECTOR.get(sym) or sector.get(sym) or _SECTOR_FALLBACK.get(sym)
            etf = SECTOR_ETF.get(sec) if sec else None
            et = (tech.get(etf) or {}) if etf else {}
            sym5 = float(t["perf_week_pct"]) if t.get("perf_week_pct") is not None else None
            sec5 = float(et["perf_week_pct"]) if et.get("perf_week_pct") is not None else None
            spy5 = float(spy["perf_week_pct"]) if spy.get("perf_week_pct") is not None else None
            vs_sec5 = (sym5 - sec5) if (sym5 is not None and sec5 is not None) else None
            vs_spy5 = (sym5 - spy5) if (sym5 is not None and spy5 is not None) else None
            # No vs-sector benchmark (asset-class ETF, or no sector ETF perf) → don't fake an "in-line" call.
            sec_label = ("unavailable" if sec is None else
                         "no sector benchmark" if vs_sec5 is None else
                         "outperforming sector" if vs_sec5 > 1 else
                         "lagging sector" if vs_sec5 < -1 else "in-line")
            below = bool(cur_px is not None and ent is not None and cur_px < ent)
            # Worthless / likely-delisted equity: a real ticker (not a fund) that has collapsed to ~zero.
            # Its cached technicals (RSI/SMA) are meaningless noise — don't present them as live signals.
            worthless = bool(_is_ticker(sym) and not p.get("is_fund") and cur_px is not None
                             and cur_px < 0.05 and upnl_pct is not None and upnl_pct < -90)
            if worthless:
                stale_tech = True
                rsi = sma50 = sma200 = None
            stop_near = bool(cur_px is not None and stop is not None and stop and abs(cur_px - stop) / cur_px < 0.02)
            tp_missing = tgt is None or tgt == 0
            # a live broker stop (incl. a trailing one) IS protection → not "large gain UNPROTECTED"
            big_gain_unprot = bool(upnl_pct is not None and upnl_pct > 10 and tp_missing and not broker_protected)
            pr = {"protected": broker_protected or bool(stop and not below), "tp_missing": tp_missing, "stop_near": stop_near,
                  "below_entry": below, "trailing_candidate": bool(upnl_pct is not None and upnl_pct > 8 and not stop_near),
                  "top_recommendation": (prot.get(sym) or {}).get("act"), "option_count": (prot.get(sym) or {}).get("n", 0)}
            warns = []
            if worthless:
                warns.append("delisted/worthless — verify & write off")
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
            # newest-news age (hours) for freshness
            _news_age_h = None
            for _n in ((news.get(sym) or []) + herm.get(sym, {}).get("items", [])):
                _ts = _n.get("published_at") or _n.get("created_at")
                if _ts:
                    try:
                        import datetime as _d
                        _pt = _d.datetime.fromisoformat(str(_ts).replace("Z", "+00:00"))
                        if _pt.tzinfo is None:
                            _pt = _pt.replace(tzinfo=_d.timezone.utc)
                        _age = (_d.datetime.now(_d.timezone.utc) - _pt).total_seconds() / 3600
                        _news_age_h = _age if _news_age_h is None else min(_news_age_h, _age)
                    except Exception:
                        pass
            _mv = p.get("market_value") or (cur_px * sh if cur_px else None)
            try:
                from holding_family import classify_family, is_unstoppable_fund
                _fam, _ = classify_family(sym)
                _is_mf = is_unstoppable_fund(sym)   # mutual fund OR 401k/proxy fund code → no exchange stop
            except Exception:
                _fam, _is_mf = "position", False
            _decision = _derive_decision(
                upnl_pct=upnl_pct, protected=pr["protected"], stop=stop, tp_missing=tp_missing,
                big_gain_unprot=big_gain_unprot, below=below, stop_near=stop_near, rsi=rsi,
                stale_tech=stale_tech, basis_reliable=basis_reliable, cost_basis_source=p.get("cost_basis_source"),
                basis_kind=("entry" if p.get("src") == "paper_trades" else "avg_cost"), market_value=_mv,
                strategy=(p.get("strategy") or lot.get("strat") or pl.get("strat")),
                trend_label=_trend_label(sma50, sma200), sec_label=sec_label, vs_sec5=vs_sec5,
                latest_news_age_h=(round(_news_age_h, 1) if _news_age_h is not None else None),
                last_hermes_at=herm.get(sym, {}).get("research_at"),
                on_watchlist=(sym in wl_set), directive=(sym in dir_set), is_fund=p.get("is_fund", False),
                family=_fam, mutual_fund=_is_mf, broker_protected=broker_protected)
            positions.append({
                **_decision,
                **_card_enrichment(sym, cur_px),
                "trade_id": None, "symbol": sym, "company_name": p.get("company_name"),
                "account": p["account"], "broker": p["broker"], "environment": p["environment"],
                "worthless": worthless,
                "strategy": p.get("strategy") or lot.get("strat") or pl.get("strat"), "shares": sh, "is_fund": p.get("is_fund", False),
                "holding_family": _fam, "is_mutual_fund": _is_mf, "is_unstoppable_fund": _is_mf, "stop_eligible": (not _is_mf),
                "entry_price": ent, "avg_cost": p.get("avg_cost"), "cost_basis": p.get("cost_basis"),
                "basis_kind": ("entry" if p.get("src") == "paper_trades" else "avg_cost"),
                "basis_reliable": basis_reliable, "basis_warning": basis_warning,
                "cost_basis_source": p.get("cost_basis_source"),
                "current_price": cur_px, "market_value": p.get("market_value") or (cur_px * sh if cur_px else None),
                "stop_price": stop, "target_price": tgt, "unrealized_pnl": upnl, "unrealized_pnl_pct": upnl_pct,
                "broker_stop": broker_stop_payload,
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
            "broker_stops_fetched_at": broker_stops_fetched_at(),
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
