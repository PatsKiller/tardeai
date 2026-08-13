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
import os
from watchlist_priority import (
    WATCHLIST_TOP_N, daily_priority_sql_params, holdings_list, is_off_hours_et, scoring_top_n,
    sql_scoring_priority_exists,
    sql_daily_priority_exists,
)
PILLS = PROJECT_ROOT / "data" / "runtime" / "pro_analyst_pills_latest.json"
WEIGHTS_FILE = PROJECT_ROOT / "config" / "hermes_score_weights.yaml"
SCALP_WEIGHTS_FILE = PROJECT_ROOT / "config" / "hermes_score_weights_scalp.yaml"
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
        profile = (os.getenv("HERMES_WEIGHTS_PROFILE") or "").strip().lower()
        path = SCALP_WEIGHTS_FILE if profile == "scalp" and SCALP_WEIGHTS_FILE.exists() else WEIGHTS_FILE
        w = (yaml.safe_load(path.read_text()) or {}).get("weights", {})
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


def _f_hermes_research(wi):
    """Reverse-edge factor: Hermes research intelligence folded back onto the name.
    Absent (not yet written) → factor DROPPED, never a fabricated neutral."""
    s = wi.get("hermes_research_score")
    if s is None:
        return None, None
    return _clamp(float(s)), f"hermes research {float(s):.0f}"


def _f_options_edge(wi):
    """Reverse-edge factor: options paper-outcome edge folded onto the UNDERLYING symbol.
    Absent (no closed options outcomes yet) → factor DROPPED, never a fabricated neutral."""
    s = wi.get("options_edge_score")
    if s is None:
        return None, None
    return _clamp(float(s)), f"options edge {float(s):.0f}"


def score_symbol(wi, ie, pill, secmap, weights):
    factors = {
        "technical_momentum": _f_technical(wi, ie),
        "setup_quality": _f_setup(wi),
        "analyst": _f_analyst(pill),
        "social_sentiment": _f_social(ie),
        "sector_strength": _f_sector(ie, secmap),
        "news_catalyst": _f_catalyst(ie),
        "risk_reward": _f_rr(wi),
        "hermes_research": _f_hermes_research(wi),
        "options_edge": _f_options_edge(wi),
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
                     wi.hermes_research_score, wi.options_edge_score,
                     ie.social_score, ie.social_sentiment, ie.rvol, ie.confluence_score,
                     ie.catalyst, ie.catalyst_verified, ie.sector
                   FROM watchlist_items wi
                   LEFT JOIN intelligence_entities ie ON ie.display_name = wi.symbol
                   LEFT JOIN watchlist_strategy_cards sc ON sc.symbol = wi.symbol
                   WHERE wi.status IN ('active','researched')"""


def _tier_plan(now_et=None):
    """Which scope tiers this run scores (design §1.2). Events are always drained.
      market hours  : S0 + S1
      pre-market 7h : S0 + S2 (the daily warm-pool pass; no-change skip absorbs the repeats)
      pre-market 8-9: S0
      other off-hrs : S0 once an hour (minute<15), else events only
    """
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    now = now_et or _dt.now(ZoneInfo("America/New_York"))
    wd, mins = now.weekday(), now.hour * 60 + now.minute
    if wd < 5 and 9 * 60 + 30 <= mins < 16 * 60:
        # S0 every tick (15m); S1 every other tick (30m) on the */15 cron
        return ["S0", "S1"] if now.minute % 30 < 15 else ["S0"]
    if wd < 5 and 7 * 60 <= mins < 8 * 60:
        return ["S0", "S2"]
    if wd < 5 and 8 * 60 <= mins < 9 * 60 + 30:
        return ["S0"]
    return ["S0"] if now.minute < 15 else []


def _pending_event_symbols(cur):
    cur.execute("SELECT symbol FROM hermes_score_event_queue WHERE processed_at IS NULL")
    return [r[0] for r in cur.fetchall()]


def _fetch_tier_rows(cur, tiers, event_symbols, limit=None):
    """Tier-aware universe: governed scope tiers for this run + event-lane symbols (any tier)."""
    lim = f" LIMIT {int(limit)}" if limit else ""
    cur.execute(_BASE_SELECT +
                " AND (wi.scope_tier = ANY(%s) OR UPPER(wi.symbol) = ANY(%s))" + lim,
                (tiers or ["_none_"], [s.upper() for s in event_symbols] or ["_NONE_"]))


def _fetch_watchlist_rows(cur, limit=None, off_hours=False):
    """Off-hours: daily-priority (holdings/proposals/buy/start) + Hermes top-N; skip ~3k tail."""
    if not off_hours:
        sql = _BASE_SELECT + (f" LIMIT {int(limit)}" if limit else "")
        cur.execute(sql)
        return
    cap = int(limit or WATCHLIST_TOP_N)
    dp = daily_priority_sql_params(project_root=PROJECT_ROOT)
    daily_sql = sql_scoring_priority_exists("wi.symbol")
    # Tier order: holdings and live proposals ahead of in_directive_watch — 989 directive-flagged
    # names were consuming the whole cap and pushing real-money holdings out of the scoring window.
    # Within a tier, hermes_rank orders who makes the cut (was an arbitrary 0 for all daily rows).
    cur.execute(f"""WITH daily AS (
                     SELECT wi.symbol,
                       MIN(CASE WHEN wi.symbol = ANY(%s) THEN 0
                                WHEN EXISTS (SELECT 1 FROM paper_trade_proposals p
                                             WHERE UPPER(p.symbol)=UPPER(wi.symbol) AND p.status=ANY(%s)) THEN 1
                                WHEN wi.in_directive_watch THEN 2
                                WHEN EXISTS (SELECT 1 FROM watchlist_research_cards rc
                                             WHERE UPPER(rc.symbol)=UPPER(wi.symbol)
                                               AND UPPER(REPLACE(REPLACE(rc.latest_recommendation,' ','_'),'-','_'))=ANY(%s))
                                  OR EXISTS (SELECT 1 FROM watchlist_final_synthesis fs
                                             WHERE UPPER(fs.symbol)=UPPER(wi.symbol)
                                               AND UPPER(REPLACE(REPLACE(fs.recommendation,' ','_'),'-','_'))=ANY(%s)) THEN 3
                                WHEN wi.status = 'active' THEN 4
                                ELSE 5 END) AS tier,
                       MIN(wi.hermes_rank) AS best_rank
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
                     SELECT symbol, tier, best_rank FROM (
                       SELECT symbol, tier, best_rank,
                              ROW_NUMBER() OVER (ORDER BY tier, best_rank ASC NULLS LAST) AS rn
                       FROM (
                         SELECT symbol, tier, best_rank FROM daily
                         UNION ALL
                         SELECT symbol, 10 AS tier, best_rank FROM ranked
                       ) u
                     ) capped WHERE rn <= %s
                   )
                   SELECT wi.symbol, wi.rsi, wi.trend, wi.score, wi.watch_score_kind, wi.price,
                     sc.target_price, sc.stop_loss,
                     wi.hermes_research_score, wi.options_edge_score,
                     ie.social_score, ie.social_sentiment, ie.rvol, ie.confluence_score,
                     ie.catalyst, ie.catalyst_verified, ie.sector
                   FROM candidates c
                   JOIN watchlist_items wi ON wi.symbol = c.symbol AND wi.status IN ('active','researched')
                   LEFT JOIN intelligence_entities ie ON ie.display_name = wi.symbol
                   LEFT JOIN watchlist_strategy_cards sc ON sc.symbol = wi.symbol
                   ORDER BY c.tier, c.best_rank ASC NULLS LAST""",
                (dp[0], dp[1], dp[2], dp[3], *dp, WATCHLIST_TOP_N, cap, cap))


def run(limit=None):
    conn = _conn(); cur = conn.cursor()
    off_hours = is_off_hours_et()

    # Tier mode (Phase 1): when the scope governor has populated scope_tier, the universe is
    # this run's tiers + pending event-lane symbols. Legacy capped fetch remains the fallback
    # for an ungoverned DB (fresh install / governor never applied).
    cur.execute("""SELECT count(*) FROM watchlist_items
                   WHERE scope_tier IS NOT NULL AND status IN ('active','researched')""")
    tier_mode = (cur.fetchone()[0] or 0) > 0
    event_syms = _pending_event_symbols(cur) if tier_mode else []
    tiers = _tier_plan() if tier_mode else []
    if tier_mode and not tiers and not event_syms:
        print("[hermes-scorer] tier-plan: nothing due this tick (off-hours, no pending events)")
        return {"scored": 0, "skipped_unchanged": 0, "top": []}

    pills = _pills_map(); secmap = _sector_momentum(conn); weights = _weights()
    vix = _vix(conn)
    weights, _regime = _regime_weights(weights, vix)
    if tier_mode:
        use_capped_fetch = False
        _fetch_tier_rows(cur, tiers, event_syms, limit=limit)
    else:
        limit = scoring_top_n(limit)
        use_capped_fetch = limit is not None
        _fetch_watchlist_rows(cur, limit=limit, off_hours=use_capped_fetch)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    scored = []
    for r in rows:
        wi = {k: r[k] for k in ("symbol", "rsi", "trend", "score", "watch_score_kind", "price",
                                "target_price", "stop_loss", "hermes_research_score", "options_edge_score")}
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
    # No-change write skip: 98.6% (market hours) to 100% (off-hours) of history INSERTs were
    # byte-identical to the prior run. Skip the INSERT when composite+rank are unchanged, but
    # always write a heartbeat row once per ~20h so per-symbol freshness stays provable.
    last_hist = {}
    try:
        cur.execute("""SELECT DISTINCT ON (symbol) symbol, composite_score, rank, scored_at
                       FROM hermes_score_history WHERE symbol = ANY(%s)
                       ORDER BY symbol, scored_at DESC""", ([s for s, *_ in scored],))
        last_hist = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}
    except Exception:
        conn.rollback()  # skip-optimization is best-effort; never block scoring
    from datetime import timedelta
    hb_cutoff = datetime.now(timezone.utc) - timedelta(hours=20)
    skipped = 0
    for rank, (sym, comp, components, px) in enumerate(scored, 1):
        prev = last_hist.get(sym)
        if prev is not None and prev[0] is not None and abs(float(prev[0]) - comp) < 0.05 \
                and (off_hours or prev[1] == rank):
            prev_at = prev[2]
            cutoff = hb_cutoff if (prev_at is not None and prev_at.tzinfo) else hb_cutoff.replace(tzinfo=None)
            if prev_at is not None and prev_at >= cutoff:
                # unchanged and recent → refresh the live row only, no history append
                cur.execute("""UPDATE watchlist_items SET hermes_scored_at=NOW(), updated_at=NOW()
                               WHERE symbol=%s AND status IN ('active','researched')""", (sym,))
                skipped += 1
                continue
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
    if tier_mode and event_syms:
        # drain everything we attempted — an unscoreable symbol must not wedge its queue slot
        cur.execute("""UPDATE hermes_score_event_queue SET processed_at=NOW()
                       WHERE processed_at IS NULL AND UPPER(symbol) = ANY(%s)""",
                    ([s.upper() for s in event_syms],))
    conn.commit()
    if tier_mode:
        mode = "tiers[%s]+events(%d)%s" % (",".join(tiers) or "-", len(event_syms),
                                           "-frozen-ranks" if off_hours else "")
    elif use_capped_fetch:
        mode = "capped-top%d%s" % (limit or WATCHLIST_TOP_N, "-frozen-ranks" if off_hours else "")
    else:
        mode = "full"
    print(f"[hermes-scorer] {mode}: scored {len(scored)} watchlist names, "
          f"{skipped} unchanged (history-skip) (top: " +
          ", ".join(f"{s}={round(c,1)}" for s, c, *_ in scored[:5]) + ")")
    return {"scored": len(scored), "skipped_unchanged": skipped,
            "top": [(s, round(c, 1)) for s, c, *_ in scored[:10]]}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--once", action="store_true"); ap.add_argument("--limit", type=int)
    a = ap.parse_args(); run(limit=a.limit)


if __name__ == "__main__":
    main()
