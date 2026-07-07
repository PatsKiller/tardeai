#!/usr/bin/env python3
"""proxy_options_scanner.py — options strategy candidates for a public-market PROXY of a private target.

For the proxy ticker (e.g. ZM as an Anthropic proxy) it pulls the live option chain and ranks three
structures that fit an event-driven, capital-preserving IPO-upside thesis:
  1. DEEP ITM CALLS / LEAPS  — stock replacement; rank by delta, spread, OI, DTE, breakeven, capital efficiency
  2. CALL DEBIT SPREADS       — defined-risk directional; rank by debit, max gain, breakeven, reward/risk, liquidity
  3. CASH-SECURED PUTS        — get paid to own lower; rank by strike discount, premium yield, assignment risk, WTO

Flags earnings-before-expiry and IPO-headline risk. Short-dated OTM calls are flagged SPECULATIVE and
covered calls UPSIDE-CAPPING (handled in the registry/card, not auto-generated here). REVIEW/PAPER ONLY —
every candidate is live_eligible=false; nothing here submits or promotes.

  python3 scripts/proxy_options_scanner.py --target anthropic [--apply] [--dte-min 60] [--strikes 40]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

REGISTRY = PROJECT_ROOT / "config" / "private_company_proxies.yaml"


def _f(v, d=None):
    try:
        return float(v)
    except Exception:
        return d


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _load_registry():
    import yaml
    return yaml.safe_load(REGISTRY.read_text()) or {}


def _ensure_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS proxy_option_candidates (
            id serial PRIMARY KEY,
            slug text NOT NULL,
            proxy_ticker text NOT NULL,
            strategy text NOT NULL,
            speculative boolean DEFAULT false,
            caps_upside boolean DEFAULT false,
            underlying_price numeric,
            legs jsonb,
            metrics jsonb,
            rank_score numeric,
            flags jsonb,
            live_eligible boolean DEFAULT false,   -- INVARIANT: proxy candidates are NEVER live-eligible
            status text DEFAULT 'review_only',
            data_source text,
            scanned_at timestamptz DEFAULT now()
        )""")


def _chain_schwab(proxy, strikes):
    """Live normalized chain via the read-only Schwab transport (source of truth when the Schwab
    session is authed). Never touches an order surface."""
    import schwab_transport as st
    ch = st.get_option_chain(proxy, strike_count=strikes)
    if not isinstance(ch, dict) or ch.get("status") != "ok":
        return None, (ch or {}).get("status") or (ch or {}).get("error", "chain_unavailable"), None
    spot = _f(ch.get("underlying_price"))
    calls, puts = [], []
    for exp in ch.get("expirations", []):
        for s in exp.get("strikes", []):
            row = {"strike": _f(s.get("strike")), "exp": s.get("exp"), "dte": s.get("dte"),
                   "bid": _f(s.get("bid")), "ask": _f(s.get("ask")), "last": _f(s.get("last")),
                   "iv": _f(s.get("iv")), "delta": _f(s.get("delta")), "oi": s.get("oi") or 0}
            row["mid"] = round((row["bid"] + row["ask"]) / 2, 2) if (row["bid"] and row["ask"]) else row["last"]
            (calls if s.get("side") == "call" else puts).append(row)
    return {"calls": calls, "puts": puts}, "schwab", spot


def _chain_alpaca(proxy, dte_min):
    """Fallback chain via Alpaca options market data (works on paper keys; independent of the Schwab
    login session). Merges /v2/options/contracts (strike/exp/type/open_interest) with
    /v1beta1/options/snapshots (live quote + greeks + IV). Read-only market data — no order surface."""
    import os, json as _j, urllib.request as _ur, urllib.parse as _up
    from datetime import date, datetime
    key, sec = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
    if not (key and sec):
        return None, "alpaca_no_keys", None
    hdr = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}

    def _get(url):
        with _ur.urlopen(_ur.Request(url, headers=hdr), timeout=20) as r:
            return _j.loads(r.read())

    # spot from the latest stock trade
    spot = None
    try:
        spot = _f((_get(f"https://data.alpaca.markets/v2/stocks/{proxy}/trades/latest")
                   .get("trade") or {}).get("p"))
    except Exception:
        pass
    # contracts (OI/strike/exp/type), paginated, from ~dte_min out to a LEAPS horizon
    contracts, tok, pages = {}, None, 0
    exp_gte = date.today().isoformat()
    while pages < 12:
        q = {"underlying_symbols": proxy, "status": "active", "limit": "1000", "expiration_date_gte": exp_gte}
        if tok:
            q["page_token"] = tok
        try:
            d = _get("https://paper-api.alpaca.markets/v2/options/contracts?" + _up.urlencode(q))
        except Exception as e:
            if not contracts:
                return None, f"alpaca_contracts_err:{str(e)[:40]}", spot
            break
        for c in d.get("option_contracts") or []:
            contracts[c["symbol"]] = {"strike": _f(c.get("strike_price")), "exp": c.get("expiration_date"),
                                      "type": c.get("type"), "oi": int(c.get("open_interest") or 0),
                                      "close": _f(c.get("close_price"))}
        tok = d.get("next_page_token")
        pages += 1
        if not tok:
            break
    if not contracts:
        return None, "alpaca_no_contracts", spot
    # snapshots (quote + greeks + IV), paginated
    snaps, tok, pages = {}, None, 0
    while pages < 12:
        q = {"feed": "indicative", "limit": "1000"}
        if tok:
            q["page_token"] = tok
        try:
            d = _get(f"https://data.alpaca.markets/v1beta1/options/snapshots/{proxy}?" + _up.urlencode(q))
        except Exception:
            break
        snaps.update(d.get("snapshots") or {})
        tok = d.get("next_page_token")
        pages += 1
        if not tok:
            break
    today = date.today()
    calls, puts = [], []
    for sym, c in contracts.items():
        if not c["strike"] or not c["exp"]:
            continue
        try:
            dte = (datetime.strptime(c["exp"], "%Y-%m-%d").date() - today).days
        except Exception:
            continue
        if dte < dte_min:
            continue
        sn = snaps.get(sym) or {}
        q = sn.get("latestQuote") or {}
        g = sn.get("greeks") or {}
        bid, ask = _f(q.get("bp")), _f(q.get("ap"))
        mid = round((bid + ask) / 2, 2) if (bid and ask) else c["close"]
        row = {"strike": c["strike"], "exp": c["exp"], "dte": dte, "bid": bid, "ask": ask,
               "last": c["close"], "iv": _f(sn.get("impliedVolatility")), "delta": _f(g.get("delta")),
               "oi": c["oi"], "mid": mid}
        (calls if c["type"] == "call" else puts).append(row)
    if not spot:  # last resort: infer from deepest ITM call intrinsic
        return None, "alpaca_no_spot", None
    return {"calls": calls, "puts": puts}, "alpaca", spot


def _chain(proxy, strikes, dte_min):
    """Schwab first (authoritative), Alpaca fallback (independent of the Schwab login session).
    Returns (chain, source, spot) or (None, reason, None)."""
    ch, src, spot = _chain_schwab(proxy, strikes)
    if ch and spot:
        return ch, src, spot
    schwab_reason = src
    ch, src, spot = _chain_alpaca(proxy, dte_min)
    if ch and spot:
        return ch, src, spot
    return None, f"schwab={schwab_reason}; alpaca={src}", None


def _spread_pct(c):
    if not (c.get("bid") and c.get("ask")) or not c["mid"]:
        return None
    return round((c["ask"] - c["bid"]) / c["mid"] * 100, 1)


def _liquid(c):
    """Liquidity floor so illiquid strikes (e.g. OI 1, no live quote) don't rank on a stale close
    price. Keep a contract only if it has a live two-sided quote OR meaningful open interest."""
    has_quote = bool(c.get("bid") and c.get("ask"))
    return has_quote or (c.get("oi") or 0) >= 10


def _rank_deep_itm(calls, spot, dte_min):
    """Deep ITM calls (Δ≥0.75, ITM, DTE≥min) as stock replacement. Composite favors high delta,
    tight spread, high OI, high capital efficiency (little time premium), breakeven near spot."""
    out = []
    for c in calls:
        if not c["mid"] or not c["strike"] or c["strike"] >= spot or not _liquid(c):
            continue
        if (c["dte"] or 0) < dte_min or (c["delta"] or 0) < 0.75:
            continue
        intrinsic = max(0.0, spot - c["strike"])
        extrinsic = max(0.0, c["mid"] - intrinsic)
        cap_eff = round(intrinsic / c["mid"], 3) if c["mid"] else 0        # 1.0 = zero time premium
        leverage = round(spot / c["mid"], 2) if c["mid"] else None         # $ exposure per $ premium
        be = round(c["strike"] + c["mid"], 2)
        be_over_spot = round((be / spot - 1) * 100, 1)
        sp = _spread_pct(c)
        # composite 0-100: delta 30 + cap_eff 30 + liquidity 20 (OI + tight spread) + breakeven 20
        liq = min(20.0, (c["oi"] or 0) / 100.0) * 0.5 + (max(0.0, 10 - (sp or 20)) if sp is not None else 0)
        score = round((c["delta"] or 0) * 30 + cap_eff * 30 + min(20, liq)
                      + max(0.0, 20 - abs(be_over_spot) * 4), 1)
        out.append({"strategy": "deep_itm_call", "legs": [{**c, "side": "call", "action": "BUY"}],
                    "metrics": {"debit": c["mid"], "delta": c["delta"], "breakeven": be,
                                "breakeven_pct_over_spot": be_over_spot, "capital_efficiency": cap_eff,
                                "leverage": leverage, "extrinsic": round(extrinsic, 2),
                                "spread_pct": sp, "oi": c["oi"], "dte": c["dte"]},
                    "rank_score": score, "speculative": False, "caps_upside": False})
    return sorted(out, key=lambda x: -x["rank_score"])[:5]


def _rank_debit_spreads(calls, spot, dte_min):
    """Call debit spreads (buy near-ITM/ATM, sell higher OTM). Rank by reward/risk, debit,
    breakeven, and two-leg liquidity."""
    out = []
    by_exp = {}
    for c in calls:
        if c["mid"] and c["strike"] and _liquid(c):
            by_exp.setdefault(c["exp"], []).append(c)
    for exp, cs in by_exp.items():
        if (cs[0].get("dte") or 0) < dte_min:
            continue
        cs = sorted(cs, key=lambda x: x["strike"])
        longs = [c for c in cs if 0.45 <= (c["delta"] or 0) <= 0.75 and c["strike"] <= spot * 1.03]
        for lo in longs:
            shorts = [c for c in cs if c["strike"] > lo["strike"] and (c["delta"] or 0) >= 0.15]
            for hi in shorts[:6]:
                debit = round(lo["mid"] - hi["mid"], 2)
                width = round(hi["strike"] - lo["strike"], 2)
                if debit <= 0 or width <= 0:
                    continue
                max_gain = round(width - debit, 2)
                be = round(lo["strike"] + debit, 2)
                rr = round(max_gain / debit, 2) if debit else None
                oi = min(lo["oi"] or 0, hi["oi"] or 0)
                sp = max(_spread_pct(lo) or 30, _spread_pct(hi) or 30)
                # composite: reward/risk 45 + liquidity 25 + breakeven proximity 15 + debit sanity 15
                score = round(min(45, (rr or 0) * 15) + min(25, oi / 40.0)
                              + max(0.0, 15 - abs(be / spot - 1) * 100)
                              + max(0.0, 15 - (sp / 4)), 1)
                out.append({"strategy": "call_debit_spread",
                            "legs": [{**lo, "side": "call", "action": "BUY"},
                                     {**hi, "side": "call", "action": "SELL"}],
                            "metrics": {"debit": debit, "width": width, "max_gain": max_gain,
                                        "breakeven": be, "reward_risk": rr, "min_leg_oi": oi,
                                        "max_leg_spread_pct": round(sp, 1), "dte": lo["dte"]},
                            "rank_score": score, "speculative": False, "caps_upside": True})
    return sorted(out, key=lambda x: -x["rank_score"])[:5]


def _rank_csps(puts, spot, dte_min):
    """Cash-secured puts (sell OTM put). Rank by strike discount (cushion), premium yield (annualized),
    assignment risk (put |delta|), and a willingness-to-own composite."""
    out = []
    for p in puts:
        if not p["mid"] or not p["strike"] or p["strike"] >= spot or not _liquid(p):
            continue
        if (p["dte"] or 0) < dte_min:
            continue
        discount = round((spot - p["strike"]) / spot * 100, 1)          # % OTM cushion
        yield_pct = round(p["mid"] / p["strike"] * 100, 2)              # premium on cash secured
        ann_yield = round(yield_pct * 365 / max(1, p["dte"]), 1)
        assign_risk = round(abs(p["delta"] or 0), 2)                    # ≈ P(assignment) proxy
        sp = _spread_pct(p)
        # willingness-to-own: reward discount + yield, penalize assignment risk + wide spread
        wto = round(min(35, discount * 3) + min(35, ann_yield) + (25 * (1 - assign_risk))
                    - (sp / 5 if sp else 0), 1)
        out.append({"strategy": "cash_secured_put", "legs": [{**p, "side": "put", "action": "SELL"}],
                    "metrics": {"premium": p["mid"], "strike_discount_pct": discount,
                                "premium_yield_pct": yield_pct, "annualized_yield_pct": ann_yield,
                                "assignment_risk": assign_risk, "willingness_to_own_score": wto,
                                "spread_pct": sp, "oi": p["oi"], "dte": p["dte"],
                                "cash_secured": round(p["strike"] * 100, 2)},
                    "rank_score": wto, "speculative": False, "caps_upside": False})
    return sorted(out, key=lambda x: -x["rank_score"])[:5]


def _earnings_before(cur, proxy, max_dte):
    try:
        cur.execute("SELECT next_earnings_date FROM symbol_profiles WHERE upper(symbol)=%s", (proxy,))
        r = cur.fetchone()
        if r and r[0]:
            from datetime import date
            days = (r[0] - date.today()).days
            if 0 <= days <= (max_dte or 400):
                return {"date": str(r[0]), "days": days}
    except Exception:
        pass
    return None


def _proxies_to_scan(cur, target_slug, tgt, top_n):
    """The optionable proxies to scan for a target: the top-ranked ACCEPTED discovered proxies whose
    options aren't known-absent (has_options true or unknown). Falls back to the registry primary/first
    ticker when discovery hasn't run yet (back-compat)."""
    try:
        cur.execute("""SELECT proxy_ticker FROM private_company_proxies
                       WHERE slug=%s AND accepted IS NOT false
                             AND (has_options IS NULL OR has_options = true)
                       ORDER BY rank_overall NULLS LAST LIMIT %s""", (target_slug, top_n))
        rows = [r[0] for r in cur.fetchall() if r and r[0]]
        if rows:
            return rows
    except Exception:
        pass
    prox = tgt.get("proxies") or []
    primary = next((p for p in prox if p.get("primary")), (prox[0] if prox else None))
    return [primary["ticker"].upper()] if primary else []


def _scan_one(cur, target_slug, tgt, proxy, dte_min, strikes, apply):
    """Scan + rank one proxy ticker. Returns a per-proxy result dict; degraded when no live chain."""
    chain, status, spot = _chain(proxy, strikes, dte_min)
    if chain is None or not spot:
        return {"proxy": proxy, "ok": False, "degraded": True, "error": f"chain unavailable ({status})"}
    cands = (_rank_deep_itm(chain["calls"], spot, dte_min)
             + _rank_debit_spreads(chain["calls"], spot, dte_min)
             + _rank_csps(chain["puts"], spot, dte_min))
    max_dte = max((c["metrics"].get("dte") or 0) for c in cands) if cands else 0
    earnings = _earnings_before(cur, proxy, max_dte)
    cur.execute("""SELECT ipo_status, expected_ipo_window, catalyst_score FROM private_company_proxies
                   WHERE slug=%s AND proxy_ticker=%s""", (target_slug, proxy))
    rr = cur.fetchone()
    ipo_flag = {"ipo_status": (rr[0] if rr else tgt.get("ipo_status")),
                "expected_window": (rr[1] if rr else tgt.get("expected_ipo_window")),
                "catalyst_score": (rr[2] if rr else None),
                "note": f"Event-driven: {tgt['private_target_name']} IPO headline can move {proxy} sharply "
                        f"in EITHER direction; timing/value are uncertain. UNVALIDATED until paper outcomes exist."}
    flags = {"earnings_before_expiry": earnings, "ipo_headline_risk": ipo_flag}
    if apply:
        cur.execute("DELETE FROM proxy_option_candidates WHERE slug=%s AND proxy_ticker=%s",
                    (target_slug, proxy))
        for c in cands:
            cur.execute("""INSERT INTO proxy_option_candidates
                (slug, proxy_ticker, strategy, speculative, caps_upside, underlying_price,
                 legs, metrics, rank_score, flags, live_eligible, status, data_source, scanned_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, false, 'review_only', %s, now())""",
                (target_slug, proxy, c["strategy"], c["speculative"], c["caps_upside"], spot,
                 json.dumps(c["legs"]), json.dumps(c["metrics"]), c["rank_score"], json.dumps(flags),
                 f"{status}_chain"))
    from collections import Counter
    return {"proxy": proxy, "ok": True, "underlying_price": spot,
            "counts": dict(Counter(c["strategy"] for c in cands)),
            "top": [{"strategy": c["strategy"], "rank_score": c["rank_score"],
                     "strikes": [l["strike"] for l in c["legs"]], "caps_upside": c["caps_upside"]}
                    for c in cands[:6]]}


def scan(target_slug, apply=False, dte_min=60, strikes=40, top_n=4):
    """Scan the top-N optionable public proxies for a private target (not just the operator's ticker).
    A degraded chain for one proxy is skipped, not fatal. REVIEW/PAPER only — live_eligible=false."""
    reg = _load_registry()
    tgt = next((t for t in (reg.get("targets") or []) if t.get("slug") == target_slug), None)
    if not tgt:
        return {"ok": False, "error": f"no target '{target_slug}'"}
    conn = _conn(); cur = conn.cursor()
    _ensure_table(cur)
    proxies = _proxies_to_scan(cur, target_slug, tgt, top_n)
    if not proxies:
        return {"ok": False, "error": "no proxy tickers to scan (run discovery first)"}
    results = [_scan_one(cur, target_slug, tgt, p, dte_min, strikes, apply) for p in proxies]
    if apply:
        conn.commit()
    scanned = [r for r in results if r.get("ok")]
    return {"ok": True, "target": target_slug, "applied": apply, "advisory_only": True,
            "proxies_scanned": [r["proxy"] for r in scanned],
            "proxies_degraded": [r["proxy"] for r in results if not r.get("ok")],
            "results": results}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dte-min", type=int, default=60)
    ap.add_argument("--strikes", type=int, default=40)
    a = ap.parse_args()
    print(json.dumps(scan(a.target, apply=a.apply, dte_min=a.dte_min, strikes=a.strikes),
                     default=str, indent=2))


if __name__ == "__main__":
    main()
