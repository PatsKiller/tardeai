#!/usr/bin/env python3
"""hermes_watchlist_scorer.py — H-1/H-2: Hermes composite watchlist score + ranking + intel card.

Combines existing intelligence into ONE tunable weighted score per watchlist name and ranks them
highest-first. Reuses (no new data invented):
  technical_momentum ← watchlist_items (rsi/trend, from the sweep) + intelligence_entities (rvol/confluence)
  setup_quality      ← watchlist_items.score + watch_score_kind (Bucket-2/3 classifier qualification)
  analyst            ← data/runtime/pro_analyst_pills_latest.json (consensus, target upside, divergence)
  social_sentiment   ← intelligence_entities (social_score, social_sentiment)
  sector_strength    ← sector ETF vs SPY (market_quotes), via the symbol's intelligence_entities.sector
  news_catalyst      ← intelligence_entities (catalyst, catalyst_verified, catalyst_updated)
  risk_reward        ← watchlist_items target/stop

Each factor normalized 0-100; weights from config/hermes_score_weights.yaml; missing factors are
DROPPED and the remaining weights re-normalized (never a fabricated neutral). Stores composite +
hermes_rank + hermes_score_components (the per-factor breakdown = the H-2 intel card). Advisory only.

  python3 scripts/hermes_watchlist_scorer.py [--once] [--limit N]
"""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
from watchlist_priority import (
    WATCHLIST_TOP_N, daily_priority_sql_params, holdings_list, is_off_hours_et, off_hours_top_n,
    sql_daily_priority_exists,
)
PILLS = PROJECT_ROOT / "data" / "runtime" / "pro_analyst_pills_latest.json"
WEIGHTS_FILE = PROJECT_ROOT / "config" / "hermes_score_weights.yaml"
SECTOR_ETF = {"Technology": "XLK", "Financials": "XLF", "Energy": "XLE", "Healthcare": "XLV",
              "Consumer Cyclical": "XLY", "Industrials": "XLI", "Consumer Defensive": "XLP",
              "Utilities": "XLU", "Real Estate": "XLRE", "Basic Materials": "XLB",
              "Communication Services": "XLC"}


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _weights():
    try:
        import yaml
        w = (yaml.safe_load(WEIGHTS_FILE.read_text()) or {}).get("weights", {})
        return {k: float(v) for k, v in w.items()} if w else {}
    except Exception:
        return {"technical_momentum": .2, "setup_quality": .18, "analyst": .16,
                "social_sentiment": .12, "sector_strength": .12, "news_catalyst": .12, "risk_reward": .1}


def _clamp(x):
    return max(0.0, min(100.0, float(x)))


def _pills_map():
    try:
        return {p["symbol"].upper(): p for p in json.loads(PILLS.read_text()).get("pills", [])}
    except Exception:
        return {}


def _sector_momentum(conn):
    """sector → (momentum_str, score0-100). Leading sectors score high."""
    cur = conn.cursor()
    cur.execute("SELECT day_change_pct FROM market_quotes WHERE symbol='SPY' ORDER BY fetched_at DESC LIMIT 1")
    r = cur.fetchone(); spy = float(r[0]) if r and r[0] is not None else 0.0
    out = {}
    for sec, etf in SECTOR_ETF.items():
        cur.execute("SELECT day_change_pct FROM market_quotes WHERE symbol=%s ORDER BY fetched_at DESC LIMIT 1", (etf,))
        rr = cur.fetchone()
        if not rr or rr[0] is None:
            out[sec] = ("unknown", None); continue
        rel = float(rr[0]) - spy
        mom = "leading" if rel > 0.15 else "lagging" if rel < -0.15 else "neutral"
        out[sec] = (mom, _clamp(55 + rel * 25))
    return out


# ── per-factor scorers → (score0-100 or None, detail string) ──────────────────────
def _f_technical(wi, ie):
    rsi = wi.get("rsi"); trend = wi.get("trend"); rvol = (ie or {}).get("rvol"); conf = (ie or {}).get("confluence_score")
    if rsi is None and trend is None and rvol is None:
        return None, None
    parts, det = [], []
    if rsi is not None:
        r = float(rsi); s = 100 - abs(55 - r) * 2.2  # sweet spot ~55, penalize extremes
        parts.append(_clamp(s)); det.append(f"RSI {r:.0f}")
    if trend:
        parts.append({"bullish": 82, "neutral": 50, "bearish": 22, "unknown": 45}.get(trend, 45)); det.append(trend)
    if rvol is not None:
        parts.append(_clamp(40 + float(rvol) * 12)); det.append(f"RVOL {float(rvol):.1f}")
    if conf is not None:
        parts.append(_clamp(float(conf))); det.append(f"confluence {float(conf):.0f}")
    return (sum(parts) / len(parts) if parts else None), ", ".join(det)


def _f_setup(wi):
    sc = wi.get("score")
    if sc is None:
        return None, None
    s = _clamp(float(sc) + (12 if wi.get("watch_score_kind") == "strategy_qualified" else 0))
    kind = "strategy-qualified" if wi.get("watch_score_kind") == "strategy_qualified" else "technical posture"
    return s, f"{kind}, base {float(sc):.0f}"


def _f_analyst(pill):
    if not pill or not pill.get("has_professional_coverage"):
        return None, None
    rm = pill.get("recommendation_mean"); up = pill.get("upside_to_mean_target_pct"); div = pill.get("divergence")
    parts, det = [], []
    if rm is not None:
        parts.append(_clamp((5 - float(rm)) / 4 * 100)); det.append(f"{pill.get('recommendation_key', '')} ({float(rm):.2f})")
    if up is not None:
        parts.append(_clamp(50 + float(up) * 1.2)); det.append(f"{float(up):+.0f}% to target")
    if div == "aligned":
        parts.append(70); det.append("aligned w/ internal")
    elif div == "divergent":
        parts.append(30); det.append("divergent vs internal")
    return (sum(parts) / len(parts) if parts else None), ", ".join(det)


def _f_social(ie):
    if not ie:
        return None, None
    ss = ie.get("social_score"); sd = ie.get("social_sentiment")
    if ss is None and not sd:
        return None, None
    parts, det = [], []
    if ss is not None:
        parts.append(_clamp(float(ss))); det.append(f"score {float(ss):.0f}")
    if sd:
        parts.append({"bullish": 80, "positive": 75, "neutral": 50, "mixed": 45, "bearish": 20, "negative": 25}.get(str(sd).lower(), 50)); det.append(str(sd))
    return (sum(parts) / len(parts) if parts else None), ", ".join(det)


def _f_sector(ie, secmap):
    sec = (ie or {}).get("sector")
    if not sec or sec not in secmap:
        return None, None
    mom, s = secmap[sec]
    return s, f"{sec}: {mom}"


def _f_catalyst(ie):
    if not ie or not ie.get("catalyst"):
        return None, None
    s = 70 + (15 if ie.get("catalyst_verified") else 0)
    return _clamp(s), ("verified catalyst" if ie.get("catalyst_verified") else "catalyst") + f": {str(ie['catalyst'])[:50]}"


def _f_rr(wi):
    px = wi.get("price"); tgt = wi.get("target_price"); stop = wi.get("stop_loss")
    if not (px and tgt and stop) or px <= stop:
        return None, None
    rr = (float(tgt) - float(px)) / (float(px) - float(stop)) if (float(px) - float(stop)) > 0 else None
    if rr is None or rr <= 0:
        return None, None
    return _clamp(rr * 33), f"R:R {rr:.1f}:1"


def score_symbol(wi, ie, pill, secmap, weights):
    factors = {
        "technical_momentum": _f_technical(wi, ie),
        "setup_quality": _f_setup(wi),
        "analyst": _f_analyst(pill),
        "social_sentiment": _f_social(ie),
        "sector_strength": _f_sector(ie, secmap),
        "news_catalyst": _f_catalyst(ie),
        "risk_reward": _f_rr(wi),
    }
    present = {k: (v[0], v[1]) for k, v in factors.items() if v[0] is not None}
    if not present:
        return None, {}
    wsum = sum(weights.get(k, 0) for k in present) or 1.0
    raw = sum(weights.get(k, 0) * v[0] for k, v in present.items()) / wsum
    # Coverage-confidence: the spec rewards the strongest COMBINATION across dimensions, so penalize
    # names scored on only 1-2 factors (a 2-dim high-RVOL pop shouldn't outrank a broad 6-dim setup).
    coverage = len(present) / len(factors)
    confidence = round(0.4 + 0.6 * coverage, 2)            # 1 factor → ~0.49, all 7 → 1.0
    composite = raw * (0.55 + 0.45 * coverage)
    components = {k: {"score": round(v[0], 1), "weight": round(weights.get(k, 0) / wsum, 3), "detail": v[1]}
                 for k, v in present.items()}
    components["_coverage"] = round(coverage, 2)
    components["_confidence"] = confidence
    components["_raw_score"] = round(raw, 1)
    return round(_clamp(composite), 1), components


def _vix(conn):
    """VIX from the local trade-ai snapshot API (same value the header shows); DB fallback."""
    try:
        import urllib.request, json as _j, os as _os
        base = _os.getenv("LOCAL_API_BASE", "http://127.0.0.1:7777")
        with urllib.request.urlopen(f"{base}/api/v2/trade-ai", timeout=6) as r:
            d = _j.load(r); d = d.get("data", d)
            v = d.get("vix")
            if v is not None:
                return float(v)
    except Exception:
        pass
    try:
        cur = conn.cursor()
        cur.execute("SELECT price FROM market_quotes WHERE symbol IN ('^VIX','VIX') ORDER BY fetched_at DESC LIMIT 1")
        r = cur.fetchone()
        return float(r[0]) if r and r[0] else None
    except Exception:
        return None


def _regime_weights(weights, vix):
    """VIX-conditioned weights (2026-06-11): in fear regimes (VIX>25) lean into sector strength / risk-reward
    and dampen social/catalyst chase; in complacency (<15) modest inverse. Bounded ±25%, renormalized."""
    if vix is None:
        return weights, "no_vix"
    w = dict(weights)
    if vix > 25:
        for k, m in (("sector_strength", 1.25), ("risk_reward", 1.25), ("social_sentiment", 0.75), ("news_catalyst", 0.85)):
            if k in w:
                w[k] = w[k] * m
        regime = "risk_off"
    elif vix < 15:
        for k, m in (("technical_momentum", 1.15), ("news_catalyst", 1.1), ("sector_strength", 0.9)):
            if k in w:
                w[k] = w[k] * m
        regime = "risk_on"
    else:
        return weights, "neutral"
    tot = sum(w.values()) or 1.0
    return {k: v / tot for k, v in w.items()}, regime


_BASE_SELECT = """SELECT wi.symbol, wi.rsi, wi.trend, wi.score, wi.watch_score_kind, wi.price,
                     sc.target_price, sc.stop_loss,
                     ie.social_score, ie.social_sentiment, ie.rvol, ie.confluence_score,
                     ie.catalyst, ie.catalyst_verified, ie.sector
                   FROM watchlist_items wi
                   LEFT JOIN intelligence_entities ie ON ie.display_name = wi.symbol
                   LEFT JOIN watchlist_strategy_cards sc ON sc.symbol = wi.symbol
                   WHERE wi.status IN ('active','researched')"""


def _fetch_watchlist_rows(cur, limit=None, off_hours=False):
    """Off-hours: daily-priority (holdings/proposals/buy/start) + Hermes top-N; skip ~3k tail."""
    if not off_hours:
        sql = _BASE_SELECT + (f" LIMIT {int(limit)}" if limit else "")
        cur.execute(sql)
        return
    cap = int(limit or WATCHLIST_TOP_N)
    dp = daily_priority_sql_params(project_root=PROJECT_ROOT)
    daily_sql = sql_daily_priority_exists("wi.symbol")
    cur.execute(f"""WITH daily AS (
                     SELECT DISTINCT wi.symbol,
                       MIN(CASE WHEN wi.in_directive_watch THEN 0
                                WHEN wi.symbol = ANY(%s) THEN 1
                                WHEN EXISTS (SELECT 1 FROM paper_trade_proposals p
                                             WHERE UPPER(p.symbol)=UPPER(wi.symbol) AND p.status=ANY(%s)) THEN 2
                                WHEN EXISTS (SELECT 1 FROM watchlist_research_cards rc
                                             WHERE UPPER(rc.symbol)=UPPER(wi.symbol)
                                               AND UPPER(REPLACE(REPLACE(rc.latest_recommendation,' ','_'),'-','_'))=ANY(%s))
                                  OR EXISTS (SELECT 1 FROM watchlist_final_synthesis fs
                                             WHERE UPPER(fs.symbol)=UPPER(wi.symbol)
                                               AND UPPER(REPLACE(REPLACE(fs.recommendation,' ','_'),'-','_'))=ANY(%s)) THEN 3
                                WHEN wi.status = 'active' THEN 4
                                ELSE 5 END) AS tier
                     FROM watchlist_items wi
                     WHERE wi.status IN ('active','researched') AND {daily_sql}
                     GROUP BY wi.symbol
                   ),
                   ranked AS (
                     SELECT wi.symbol, MIN(wi.hermes_rank) AS best_rank
                     FROM watchlist_items wi
                     WHERE wi.status IN ('active','researched')
                       AND wi.hermes_rank IS NOT NULL AND wi.hermes_rank <= %s
                       AND UPPER(wi.symbol) NOT IN (SELECT UPPER(symbol) FROM daily)
                     GROUP BY wi.symbol
                     ORDER BY best_rank ASC NULLS LAST
                     LIMIT GREATEST(%s - (SELECT COUNT(*) FROM daily), 0)
                   ),
                   candidates AS (
                     SELECT symbol, tier, 0 AS best_rank FROM daily
                     UNION ALL
                     SELECT symbol, 10 AS tier, best_rank FROM ranked
                   )
                   SELECT wi.symbol, wi.rsi, wi.trend, wi.score, wi.watch_score_kind, wi.price,
                     sc.target_price, sc.stop_loss,
                     ie.social_score, ie.social_sentiment, ie.rvol, ie.confluence_score,
                     ie.catalyst, ie.catalyst_verified, ie.sector
                   FROM candidates c
                   JOIN watchlist_items wi ON wi.symbol = c.symbol AND wi.status IN ('active','researched')
                   LEFT JOIN intelligence_entities ie ON ie.display_name = wi.symbol
                   LEFT JOIN watchlist_strategy_cards sc ON sc.symbol = wi.symbol
                   ORDER BY c.tier, c.best_rank ASC NULLS LAST""",
                (dp[0], dp[1], dp[2], dp[3], *dp, WATCHLIST_TOP_N, cap))


def run(limit=None):
    conn = _conn(); cur = conn.cursor()
    pills = _pills_map(); secmap = _sector_momentum(conn); weights = _weights()
    vix = _vix(conn)
    weights, _regime = _regime_weights(weights, vix)
    off_hours = is_off_hours_et()
    limit = off_hours_top_n(limit)
    _fetch_watchlist_rows(cur, limit=limit, off_hours=off_hours)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    scored = []
    for r in rows:
        wi = {k: r[k] for k in ("symbol", "rsi", "trend", "score", "watch_score_kind", "price", "target_price", "stop_loss")}
        ie = {k: r[k] for k in ("social_score", "social_sentiment", "rvol", "confluence_score", "catalyst", "catalyst_verified", "sector")}
        comp, components = score_symbol(wi, ie, pills.get(str(r["symbol"]).upper()), secmap, weights)
        if comp is not None:
            components = {**components, "_regime": _regime, "_vix": vix}
        if comp is not None:
            scored.append((r["symbol"], comp, components, r.get("price")))
    scored.sort(key=lambda x: -x[1])
    # dedup by symbol (watchlist_items can hold multiple rows per symbol) — clean 1-per-symbol ranks
    _seen, _dedup = set(), []
    for s, c, comp, px in scored:
        if s in _seen:
            continue
        _seen.add(s); _dedup.append((s, c, comp, px))
    scored = _dedup
    # Sector-diversity soft cap (2026-06-11): within the top 20, a sector above 25% (5 slots) takes a
    # compounding composite penalty so one hot sector can't monopolize the rank. Re-sorted after penalty.
    sec_of = {}
    for r in rows:
        if r.get("sector"):
            sec_of.setdefault(r["symbol"], r["sector"])
    counts, penalized = {}, []
    for s_, c_, comp_, px_ in scored:
        sec = sec_of.get(s_) or "unknown"
        n = counts.get(sec, 0)
        if n >= 5 and sec != "unknown":
            c_ = c_ * (0.92 ** (n - 4))      # 8% compounding penalty per slot beyond 5
            comp_ = {**comp_, "_sector_diversity_penalty": round(1 - 0.92 ** (n - 4), 3)}
        counts[sec] = n + 1
        penalized.append((s_, c_, comp_, px_))
    penalized.sort(key=lambda x: -x[1])
    scored = penalized
    for rank, (sym, comp, components, px) in enumerate(scored, 1):
        if off_hours:
            # Off-hours: refresh composite only — frozen global ranks prevent tail rank-jump spam.
            cur.execute("""UPDATE watchlist_items SET hermes_composite_score=%s,
                             hermes_score_components=%s::jsonb, hermes_scored_at=NOW(), updated_at=NOW()
                           WHERE symbol=%s AND status IN ('active','researched')""",
                        (comp, json.dumps(components), sym))
            cur.execute("""INSERT INTO hermes_score_history (symbol, composite_score, rank, components, price)
                           SELECT %s, %s, hermes_rank, %s::jsonb, %s FROM watchlist_items
                           WHERE symbol=%s AND status IN ('active','researched') LIMIT 1""",
                        (sym, comp, json.dumps(components), px, sym))
        else:
            cur.execute("""UPDATE watchlist_items SET hermes_composite_score=%s, hermes_rank=%s,
                             hermes_score_components=%s::jsonb, hermes_scored_at=NOW(), updated_at=NOW()
                           WHERE symbol=%s AND status IN ('active','researched')""",
                        (comp, rank, json.dumps(components), sym))
            cur.execute("""INSERT INTO hermes_score_history (symbol, composite_score, rank, components, price)
                           VALUES (%s, %s, %s, %s::jsonb, %s)""",
                        (sym, comp, rank, json.dumps(components), px))
    conn.commit()
    mode = "off-hours-top%d" % (limit or WATCHLIST_TOP_N) if off_hours else "full"
    print(f"[hermes-scorer] {mode}: scored {len(scored)} watchlist names (top: " +
          ", ".join(f"{s}={round(c,1)}" for s, c, *_ in scored[:5]) + ")")
    return {"scored": len(scored), "top": [(s, round(c, 1)) for s, c, *_ in scored[:10]]}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--once", action="store_true"); ap.add_argument("--limit", type=int)
    a = ap.parse_args(); run(limit=a.limit)


if __name__ == "__main__":
    main()
