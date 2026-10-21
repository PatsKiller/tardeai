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

  python3 scripts/hermes_watchlist_scorer.py [--once] [--limit N] [--dry-run]

2026-10-21 hardening: per-item isolation (one bad symbol/card is logged + counted as skipped_errors, never
aborts the run; all items failing exits 1), NaN/Inf numerics are "missing" in every factor, a P2 notification
intent when >20% of items error or nothing lands (deduped: once per condition), LaneRunReceipt@v2 receipt
data/runtime/hermes-watchlist-scorer_last.json on a real run, and a write-free --dry-run (n8n shadow lane).
2026-10-21 (PR #1899, n8n shadow lane): the alert is a QUEUED host comms intent, never a send (no telegram_alert
import), and the DB connection is a plain psycopg2 connect, not db_adapter (whose closure reaches broker modules).
"""
from __future__ import annotations
try:  # cc_auth (2026-10-14): service token for loopback Command Center (:7777) calls
    from lib.cc_client import cc_urlopen as _cc_urlopen
except ImportError:  # pragma: no cover - scripts/ not on sys.path
    import sys as _cc_sys
    from pathlib import Path as _CcPath
    _cc_sys.path.insert(0, str(next(p for p in _CcPath(__file__).resolve().parents if p.name == "scripts")))
    from lib.cc_client import cc_urlopen as _cc_urlopen

import argparse, json, math, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# G2: scripts-only + lib — never also put scripts/lib or root on path
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import os
from lib.watchlist_priority import (
    WATCHLIST_TOP_N, daily_priority_sql_params, holdings_list, is_off_hours_et, scoring_top_n,
    sql_scoring_priority_exists,
    sql_daily_priority_exists,
)
from lib.reverse_factor_reliability import REVERSE_FACTORS, calibrated_reverse_weight  # pure; not two_way_curation (db_adapter reach)
PILLS = PROJECT_ROOT / "data" / "runtime" / "pro_analyst_pills_latest.json"
WEIGHTS_FILE = PROJECT_ROOT / "config" / "hermes_score_weights.yaml"
SCALP_WEIGHTS_FILE = PROJECT_ROOT / "config" / "hermes_score_weights_scalp.yaml"
SECTOR_ETF = {"Technology": "XLK", "Financials": "XLF", "Energy": "XLE", "Healthcare": "XLV",
              "Consumer Cyclical": "XLY", "Industrials": "XLI", "Consumer Defensive": "XLP",
              "Utilities": "XLU", "Real Estate": "XLRE", "Basic Materials": "XLB",
              "Communication Services": "XLC"}


#: The DB names this lane reads (db_adapter.DB_ENV_NAMES minus its trace flag).
DB_ENV_NAMES = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")


def _conn():
    """A plain psycopg2 connection with db_adapter's parameters and its three per-connection safety nets.

    Not ``db_adapter._get_conn`` (2026-10-21, PR #1899): db_adapter's import closure reaches holdings_guard ->
    schwab_position_sync -> schwab_transport (broker_module / order_placement), and an n8n-dispatched lane must not
    (tests/test_lane_transitive_capabilities_20261015.py; AGENTS.md §23.14). Credentials: the process env, else
    lib.env_bootstrap.load_env (tmpfs render, then the checkout .env) limited to DB_ENV_NAMES — never a broker name."""
    if not os.getenv("DB_PASSWORD"):
        from lib.env_bootstrap import load_env
        load_env(names=DB_ENV_NAMES)
    import psycopg2
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
        connect_timeout=10,
        application_name="hermes_watchlist_scorer",
    )
    conn.autocommit = False
    with conn.cursor() as c:  # docs/runbooks/DB_HANG_PREVENTION.md (same values as db_adapter)
        c.execute("SET idle_in_transaction_session_timeout = '120s'")
        c.execute("SET lock_timeout = '3s'")
        c.execute("SET statement_timeout = '180s'")
    conn.commit()
    return conn


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


def _finite(v):
    """float(v) when it is a real finite number, else None.

    numeric columns can hold 'NaN' (watchlist_strategy_cards BHVN 2026-10-21): psycopg2 returns
    Decimal('NaN'), which is truthy and makes `px <= stop` raise decimal.InvalidOperation — one bad
    card aborted every scorer run from 2026-10-19 07:45 ET (hermes_score_history went silent).
    Every factor reads its numerics through this, so NaN/Inf is "missing", never a score (a NaN RSI used
    to clamp to 100)."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, ArithmeticError):
        return None
    return f if math.isfinite(f) else None


def _pills_map():
    try:
        return {p["symbol"].upper(): p for p in json.loads(PILLS.read_text()).get("pills", [])}
    except Exception:
        return {}


def _sector_momentum(conn):
    """sector → (momentum_str, score0-100). Leading sectors score high."""
    cur = conn.cursor()
    cur.execute("SELECT day_change_pct FROM market_quotes WHERE symbol='SPY' ORDER BY fetched_at DESC LIMIT 1")
    r = cur.fetchone(); spy = (_finite(r[0]) if r else None) or 0.0
    out = {}
    for sec, etf in SECTOR_ETF.items():
        cur.execute("SELECT day_change_pct FROM market_quotes WHERE symbol=%s ORDER BY fetched_at DESC LIMIT 1", (etf,))
        rr = cur.fetchone()
        etf_chg = _finite(rr[0]) if rr else None
        if etf_chg is None:
            out[sec] = ("unknown", None); continue
        rel = etf_chg - spy
        mom = "leading" if rel > 0.15 else "lagging" if rel < -0.15 else "neutral"
        out[sec] = (mom, _clamp(55 + rel * 25))
    return out


# ── per-factor scorers → (score0-100 or None, detail string) ──────────────────────
def _f_technical(wi, ie):
    rsi = _finite(wi.get("rsi")); trend = wi.get("trend")
    rvol = _finite((ie or {}).get("rvol")); conf = _finite((ie or {}).get("confluence_score"))
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
    sc = _finite(wi.get("score"))
    if sc is None:
        return None, None
    s = _clamp(float(sc) + (12 if wi.get("watch_score_kind") == "strategy_qualified" else 0))
    kind = "strategy-qualified" if wi.get("watch_score_kind") == "strategy_qualified" else "technical posture"
    return s, f"{kind}, base {float(sc):.0f}"


def _f_analyst(pill):
    if not pill or not pill.get("has_professional_coverage"):
        return None, None
    rm = _finite(pill.get("recommendation_mean")); up = _finite(pill.get("upside_to_mean_target_pct"))
    div = pill.get("divergence")
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
    ss = _finite(ie.get("social_score")); sd = ie.get("social_sentiment")
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
    px = _finite(wi.get("price")); tgt = _finite(wi.get("target_price")); stop = _finite(wi.get("stop_loss"))
    if not (px and tgt and stop) or px <= stop:
        return None, None
    rr = (float(tgt) - float(px)) / (float(px) - float(stop)) if (float(px) - float(stop)) > 0 else None
    if rr is None or rr <= 0:
        return None, None
    return _clamp(rr * 33), f"R:R {rr:.1f}:1"


def _f_hermes_research(wi):
    """Reverse-edge factor: Hermes research intelligence folded back onto the name.
    Absent (not yet written) → factor DROPPED, never a fabricated neutral."""
    s = _finite(wi.get("hermes_research_score"))
    if s is None:
        return None, None
    return _clamp(float(s)), f"hermes research {float(s):.0f}"


def _f_options_edge(wi):
    """Reverse-edge factor: options paper-outcome edge folded onto the UNDERLYING symbol.
    Absent (no closed options outcomes yet) → factor DROPPED, never a fabricated neutral."""
    s = _finite(wi.get("options_edge_score"))
    if s is None:
        return None, None
    return _clamp(float(s)), f"options edge {float(s):.0f}"


def _f_thesis_outcome(wi):
    """Reverse-edge factor: realized thesis outcome on the watchlist name.

    win/thesis_win True → reward; loss/False → penalty; scratch/null → drop factor
    (never fabricate neutral). Bounded 0-100 scores for the composite scorer.
    """
    ro = (wi.get("realized_outcome") or "").strip().lower()
    tw = wi.get("thesis_win")
    if tw is True or ro == "win":
        return 78.0, "thesis win"
    if tw is False or ro == "loss":
        return 22.0, "thesis loss"
    if ro == "scratch":
        return 50.0, "thesis scratch"
    return None, None


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
        "thesis_outcome": _f_thesis_outcome(wi),
    }
    present = {k: (v[0], v[1]) for k, v in factors.items() if v[0] is not None}
    if not present:
        return None, {}

    # Phase 5: reliability-gate reverse factors — below n_min the weight is damped
    # toward zero so an uncalibrated reverse signal never outranks a calibrated one.
    eff = dict(weights)
    gates = {}
    for f in REVERSE_FACTORS:
        if f not in present:
            continue
        base = float(weights.get(f, 0.0) or 0.0)
        if base <= 0:
            continue
        g = calibrated_reverse_weight(base, f, wi.get(f"{f}_n"))
        eff[f] = g["effective_weight"]
        gates[f] = g

    # A reverse factor damped to zero weight contributes nothing to the blend
    # (and is not counted toward coverage). Fall back to the raw factor set only
    # if every factor got damped out, so a scored name never returns empty.
    blend = {k: v for k, v in present.items() if eff.get(k, 0.0) > 0} or present

    wsum = sum(eff.get(k, 0.0) for k in blend) or 1.0
    raw = sum(eff.get(k, 0.0) * v[0] for k, v in blend.items()) / wsum
    # Coverage-confidence: the spec rewards the strongest COMBINATION across dimensions, so penalize
    # names scored on only 1-2 factors (a 2-dim high-RVOL pop shouldn't outrank a broad 6-dim setup).
    coverage = len(blend) / len(factors)
    confidence = round(0.4 + 0.6 * coverage, 2)            # 1 factor → ~0.49, all 10 → 1.0
    composite = raw * (0.55 + 0.45 * coverage)
    components = {k: {"score": round(v[0], 1), "weight": round(eff.get(k, 0.0) / wsum, 3), "detail": v[1]}
                 for k, v in present.items()}
    components["_coverage"] = round(coverage, 2)
    components["_confidence"] = confidence
    components["_raw_score"] = round(raw, 1)
    if gates:
        components["_reverse_reliability"] = {
            f: {"reliability": g["reliability"], "n": g["n"], "n_min": g["n_min"],
                "evidence_class": g["evidence_class"], "trusted": g["trusted"]}
            for f, g in gates.items()
        }
    return round(_clamp(composite), 1), components


def _vix(conn):
    """VIX from the local trade-ai snapshot API (same value the header shows); DB fallback."""
    try:
        import urllib.request, json as _j, os as _os
        base = _os.getenv("LOCAL_API_BASE", "http://127.0.0.1:7777")
        with _cc_urlopen(f"{base}/api/v2/trade-ai", timeout=6) as r:
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
                     wi.realized_outcome, wi.thesis_win,
                     sc.target_price, sc.stop_loss,
                     wi.hermes_research_score, wi.options_edge_score,
                     wi.thesis_outcome_n, wi.options_edge_n, wi.hermes_research_n,
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
                     wi.realized_outcome, wi.thesis_win,
                     sc.target_price, sc.stop_loss,
                     wi.hermes_research_score, wi.options_edge_score,
                     wi.thesis_outcome_n, wi.options_edge_n, wi.hermes_research_n,
                     ie.social_score, ie.social_sentiment, ie.rvol, ie.confluence_score,
                     ie.catalyst, ie.catalyst_verified, ie.sector
                   FROM candidates c
                   JOIN watchlist_items wi ON wi.symbol = c.symbol AND wi.status IN ('active','researched')
                   LEFT JOIN intelligence_entities ie ON ie.display_name = wi.symbol
                   LEFT JOIN watchlist_strategy_cards sc ON sc.symbol = wi.symbol
                   ORDER BY c.tier, c.best_rank ASC NULLS LAST""",
                (dp[0], dp[1], dp[2], dp[3], *dp, WATCHLIST_TOP_N, cap, cap))


LANE_ID = "hermes-watchlist-scorer"
#: Loud-failure threshold (2026-10-21): the NaN-card outage aborted every run for ~2 days and nothing paged.
ERROR_RATIO_ALERT = 0.20
#: One alert per condition per 12h. A dispatched lane may not send (AGENTS.md §23.3 "No sends from n8n";
#: tests/test_agents_policy_7_0_0_advisory_market_data.py), so the alert is a HOST COMMS INTENT queued in the
#: coordination ledger (config/host_comms_intent_routes.json research/hermes_watchlist_scorer_failure, DIGEST -> P2);
#: the host comms-intent consumer turns it into an incident and the incident notifier sends it. Dedupe is two-layer:
#: the store folds an identical (domain, kind, subject) inside its window, and ALERT_STATE_PATH holds the last
#: queue time per condition so one condition is queued at most once per ALERT_DEDUPE_MINUTES.
ALERT_DEDUPE_MINUTES = 720
ALERT_PRODUCER = "hermes_watchlist_scorer"
ALERT_DOMAIN = "research"
ALERT_KIND = "hermes_watchlist_scorer_failure"
ALERT_STATE_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_watchlist_scorer_alert_state.json"
ALERT_OUTAGE_SUBJECT = "Hermes watchlist scorer OUTAGE: no scores written"
ALERT_DEGRADED_SUBJECT = "Hermes watchlist scorer DEGRADED: >20% of names failed"
ALERT_OUTAGE = ("Hermes watchlist scorer OUTAGE: a run wrote no scores because every name failed with an "
                "error. Watchlist ranks are going stale. Check logs/hermes_scorer.log for '[hermes-scorer] error'.")
ALERT_DEGRADED = ("Hermes watchlist scorer DEGRADED: more than 20% of names failed to score in a run; the rest "
                  "were written. Check logs/hermes_scorer.log for '[hermes-scorer] error'.")

_WI_KEYS = ("symbol", "rsi", "trend", "score", "watch_score_kind", "price",
            "target_price", "stop_loss", "hermes_research_score", "options_edge_score",
            "realized_outcome", "thesis_win",
            "thesis_outcome_n", "options_edge_n", "hermes_research_n")
_IE_KEYS = ("social_score", "social_sentiment", "rvol", "confluence_score", "catalyst", "catalyst_verified", "sector")


def _dumps(obj):
    """Components JSON for a jsonb column: non-finite floats become null (a bare NaN token aborts the txn)."""
    from lib.json_finite import dumps
    return dumps(obj, default=str)


def _score_row(r, pills, secmap, weights, regime, vix):
    wi = {k: r.get(k) for k in _WI_KEYS}
    ie = {k: r.get(k) for k in _IE_KEYS}
    comp, components = score_symbol(wi, ie, pills.get(str(r["symbol"]).upper()), secmap, weights)
    if comp is not None:
        components = {**components, "_regime": regime, "_vix": vix}
    return comp, components


def _record_error(errors, sym, stage, exc):
    """Per-item isolation: one bad symbol/card is logged + counted, never aborts the run."""
    import traceback
    reason = f"{stage}:{type(exc).__name__}"
    errors["reasons"][reason] = errors["reasons"].get(reason, 0) + 1
    errors["symbols"].append(str(sym))
    frames = traceback.extract_tb(exc.__traceback__)
    where = " <- ".join(f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in reversed(frames[-3:]))
    print(f"[hermes-scorer] error {stage} {sym}: {type(exc).__name__}: {str(exc)[:200]} @ {where}", flush=True)


def failure_condition(summary):
    """'outage' | 'degraded' | None for one run's summary.

    outage   : items were attempted, at least one errored, and NOTHING landed (every name failed).
    degraded : more than ERROR_RATIO_ALERT of the attempted items errored (some still landed).
    A name with no usable factor is "unscored", not an error — it never pages."""
    items = int(summary.get("items") or 0)
    errored = int(summary.get("errored") or 0)
    if items <= 0 or errored <= 0:
        return None
    if int(summary.get("landed") or 0) == 0:
        return "outage"
    if errored / items > ERROR_RATIO_ALERT:
        return "degraded"
    return None


def _ledger_path(environ=None):
    """Same resolution as scripts/n8n_coordination_gateway.default_ledger_path (not imported: its closure reaches
    broker modules; tests/test_hermes_scorer_n8n_shadow_20261021.py pins the two equal)."""
    source = os.environ if environ is None else environ
    explicit = source.get("TRADEAI_N8N_COORDINATION_LEDGER")
    if explicit:
        return Path(explicit)
    root = source.get("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(root) / "data" / "governance" / "n8n_coordination_ledger.sqlite"


class _LedgerConn:
    """The two attributes CommsIntentStore uses (``_conn``, ``lock``) on a plain sqlite connection to an EXISTING
    ledger — the scripts/disk_usage_monitor.py / check_registry_runtime_truth.py pattern, because
    lib/host_comms_intents.queue_intent's closure (via scripts/n8n_coordination_gateway.py) reaches broker modules."""

    read_only = False

    def __init__(self, path):
        import sqlite3
        import threading
        self.lock = threading.RLock()  # CommsIntentStore re-enters it (accept -> _receipt -> get)
        self._conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self._conn.row_factory = sqlite3.Row

    def close(self):
        self._conn.close()


def _queue_host_intent(*, subject, summary, execution_id, ledger_path=None, now=None):
    """Queue ONE host comms intent (never a send). Raises ValueError(<reason>): producer_refused, intent_unrouted,
    intent_rate_limited, intent_routes_unreadable, ledger_absent (a lane never creates the ledger),
    intent_store_unavailable. Same rows, dedupe and hourly cap as lib/host_comms_intents.queue_intent."""
    import sqlite3
    import time
    from lib.n8n_fabric_store import (SUBJECT_MAX, SUMMARY_MAX, CommsIntentStore, FabricStoreError,
                                      load_host_intent_routes, load_intent_routes, merged_intent_routes)
    try:
        hosts = load_host_intent_routes()
        routes = merged_intent_routes(load_intent_routes(), hosts)
    except FabricStoreError as exc:
        raise ValueError(getattr(exc, "reason", "intent_routes_unreadable")) from exc
    route = hosts["routes"].get((ALERT_DOMAIN, ALERT_KIND))
    if route is None:
        raise ValueError("intent_unrouted")
    if route.get("producer") != ALERT_PRODUCER:
        raise ValueError("producer_refused")
    path = Path(ledger_path) if ledger_path is not None else _ledger_path()
    if not path.exists():
        raise ValueError("ledger_absent")

    def clean(text, limit):
        flat = " ".join("".join(" " if ord(ch) < 32 or ord(ch) == 127 else ch for ch in str(text or "")).split())
        return flat if len(flat) <= limit else flat[: max(0, limit - 1)] + "…"

    request = {"domain": ALERT_DOMAIN, "kind": ALERT_KIND, "subject": clean(subject, SUBJECT_MAX),
               "summary": clean(summary, SUMMARY_MAX), "workflow_id": f"host.{ALERT_PRODUCER}",
               "execution_id": str(execution_id)[:40], "node": LANE_ID}
    try:
        ledger = _LedgerConn(path)
    except (sqlite3.Error, OSError) as exc:
        raise ValueError("intent_store_unavailable") from exc
    try:
        store = CommsIntentStore(ledger, routes=routes)
        return dict(store.accept(request, caller_id=f"host:{ALERT_PRODUCER}",
                                 now=time.time() if now is None else now))
    except FabricStoreError as exc:
        raise ValueError(getattr(exc, "reason", "intent_store_unavailable")) from exc
    except sqlite3.Error as exc:
        raise ValueError("intent_store_unavailable") from exc
    finally:
        ledger.close()


def _execution_id():
    import re as _re
    raw = os.environ.get("TRADEAI_RUN_ID") or f"manual-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}"
    return (_re.sub(r"[^A-Za-z0-9_-]", "-", raw)[-40:].strip("-_")) or "host"


def emit_failure_alert(summary, *, queue=None, state_path=None, now=None):
    """Queue one host comms intent per failure condition, at most once per ALERT_DEDUPE_MINUTES (never a send).

    Fixed subject/body per condition (counts and symbols go to the log). A queued or store-folded intent stamps
    the cooldown; a refused one leaves it alone so the next run tries again. Never raises: an alert failure must
    never mask the run's own result. Returns the condition ('outage' | 'degraded') or None."""
    cond = failure_condition(summary)
    if cond is None:
        return None
    subject, body = (ALERT_OUTAGE_SUBJECT, ALERT_OUTAGE) if cond == "outage" else (ALERT_DEGRADED_SUBJECT,
                                                                                    ALERT_DEGRADED)
    queue = queue or _queue_host_intent
    path = Path(state_path) if state_path is not None else ALERT_STATE_PATH
    ts = (now or datetime.now(timezone.utc)).timestamp()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    last = (state.get("last_queued") or {}).get(cond)
    if isinstance(last, (int, float)) and ts - last < ALERT_DEDUPE_MINUTES * 60:
        print(f"[hermes-scorer] failure alert {cond} deduped (queued {int((ts - last) // 60)} min ago)", flush=True)
        return cond
    try:
        receipt = queue(subject=subject, summary=body, execution_id=_execution_id())
    except Exception as exc:  # an alert failure must never mask the run's own result
        print(f"[hermes-scorer] failure alert not queued: {type(exc).__name__}: {exc}", flush=True)
        return cond
    try:
        state.setdefault("last_queued", {})[cond] = ts
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        print(f"[hermes-scorer] alert dedupe state not written: {type(exc).__name__}", flush=True)
    print(f"[hermes-scorer] failure alert {cond} queued: {(receipt or {}).get('intent_id')}", flush=True)
    return cond


def _empty_summary(**kw):
    out = {"items": 0, "scored": 0, "unscored": 0, "written": 0, "skipped_unchanged": 0, "landed": 0,
           "errored": 0, "skipped_errors": {}, "error_symbols": [], "top": [], "dry_run": False}
    out.update(kw)
    return out


def run(limit=None, *, dry_run=False):
    """Score the universe. Returns the run summary (items attempted, scored, landed, errored + reasons).

    ``dry_run``: the DB session is READ ONLY at the server, every score is computed and NOTHING is written,
    committed or sent; the summary carries ``would_alert``. That makes the dry run the lane's health probe."""
    conn = _conn()
    if dry_run:
        from lib.lane_last_receipt import enforce_readonly
        enforce_readonly(conn)
    cur = conn.cursor()
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
        if dry_run:
            conn.rollback()
        return _empty_summary(dry_run=dry_run, empty_reason="nothing_due")

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
    errors = {"reasons": {}, "symbols": []}
    scored, unscored = [], 0
    for r in rows:
        try:
            comp, components = _score_row(r, pills, secmap, weights, _regime, vix)
        except Exception as exc:  # per-item isolation (2026-10-21): one bad card never aborts the run
            _record_error(errors, r.get("symbol"), "score", exc)
            continue
        if comp is not None:
            scored.append((r["symbol"], comp, components, _finite(r.get("price"))))
        else:
            unscored += 1
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
    if tier_mode:
        mode = "tiers[%s]+events(%d)%s" % (",".join(tiers) or "-", len(event_syms),
                                           "-frozen-ranks" if off_hours else "")
    elif use_capped_fetch:
        mode = "capped-top%d%s" % (limit or WATCHLIST_TOP_N, "-frozen-ranks" if off_hours else "")
    else:
        mode = "full"

    if dry_run:
        conn.rollback()
        summary = _empty_summary(
            dry_run=True, mode=mode, items=len(rows), scored=len(scored), unscored=unscored,
            landed=len(scored), errored=len(errors["symbols"]), skipped_errors=dict(errors["reasons"]),
            error_symbols=errors["symbols"][:20], top=[(s, round(c, 1)) for s, c, *_ in scored[:10]])
        summary["would_alert"] = failure_condition(summary)
        print(f"[hermes-scorer] DRY-RUN {mode}: {summary['items']} items, {summary['scored']} scored, "
              f"{summary['unscored']} unscored, {summary['errored']} errored {summary['skipped_errors']} "
              f"— nothing written, nothing sent (would_alert={summary['would_alert']})", flush=True)
        return summary

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
    skipped = written = 0
    for rank, (sym, comp, components, px) in enumerate(scored, 1):
        # Per-symbol SAVEPOINT: a failed write rolls back only this symbol, not the whole transaction.
        cur.execute("SAVEPOINT hermes_sym")
        try:
            outcome = _write_symbol(cur, sym, rank, comp, components, px, last_hist.get(sym),
                                    off_hours=off_hours, hb_cutoff=hb_cutoff)
            cur.execute("RELEASE SAVEPOINT hermes_sym")
        except Exception as exc:
            cur.execute("ROLLBACK TO SAVEPOINT hermes_sym")
            _record_error(errors, sym, "write", exc)
            continue
        if outcome == "unchanged":
            skipped += 1
        else:
            written += 1
    if tier_mode and event_syms:
        # drain everything we attempted — an unscoreable symbol must not wedge its queue slot
        cur.execute("""UPDATE hermes_score_event_queue SET processed_at=NOW()
                       WHERE processed_at IS NULL AND UPPER(symbol) = ANY(%s)""",
                    ([s.upper() for s in event_syms],))
    conn.commit()
    errored = len(errors["symbols"])
    print(f"[hermes-scorer] {mode}: scored {len(scored)} watchlist names, "
          f"{skipped} unchanged (history-skip), {errored} errored {dict(errors['reasons'])} of {len(rows)} items "
          f"(top: " + ", ".join(f"{s}={round(c,1)}" for s, c, *_ in scored[:5]) + ")", flush=True)
    return _empty_summary(
        mode=mode, items=len(rows), scored=len(scored), unscored=unscored, written=written,
        skipped_unchanged=skipped, landed=written + skipped, errored=errored,
        skipped_errors=dict(errors["reasons"]), error_symbols=errors["symbols"][:20],
        top=[(s, round(c, 1)) for s, c, *_ in scored[:10]])


def _write_symbol(cur, sym, rank, comp, components, px, prev, *, off_hours, hb_cutoff):
    """Persist one symbol's score. Returns 'unchanged' (live row refreshed only) or 'written'."""
    if prev is not None and prev[0] is not None and abs(float(prev[0]) - comp) < 0.05 \
            and (off_hours or prev[1] == rank):
        prev_at = prev[2]
        cutoff = hb_cutoff if (prev_at is not None and prev_at.tzinfo) else hb_cutoff.replace(tzinfo=None)
        if prev_at is not None and prev_at >= cutoff:
            # unchanged and recent → refresh the live row only, no history append
            cur.execute("""UPDATE watchlist_items SET hermes_scored_at=NOW(), updated_at=NOW()
                           WHERE symbol=%s AND status IN ('active','researched')""", (sym,))
            return "unchanged"
    body = _dumps(components)
    if off_hours:
        # Off-hours: refresh composite only — frozen global ranks prevent tail rank-jump spam.
        cur.execute("""UPDATE watchlist_items SET hermes_composite_score=%s,
                         hermes_score_components=%s::jsonb, hermes_scored_at=NOW(), updated_at=NOW()
                       WHERE symbol=%s AND status IN ('active','researched')""",
                    (comp, body, sym))
        cur.execute("""INSERT INTO hermes_score_history (symbol, composite_score, rank, components, price)
                       SELECT %s, %s, hermes_rank, %s::jsonb, %s FROM watchlist_items
                       WHERE symbol=%s AND status IN ('active','researched') LIMIT 1""",
                    (sym, comp, body, px, sym))
    else:
        cur.execute("""UPDATE watchlist_items SET hermes_composite_score=%s, hermes_rank=%s,
                         hermes_score_components=%s::jsonb, hermes_scored_at=NOW(), updated_at=NOW()
                       WHERE symbol=%s AND status IN ('active','researched')""",
                    (comp, rank, body, sym))
        cur.execute("""INSERT INTO hermes_score_history (symbol, composite_score, rank, components, price)
                       VALUES (%s, %s, %s, %s::jsonb, %s)""",
                    (sym, comp, rank, body, px))
    return "written"


def all_failed(summary):
    """Every attempted item errored and nothing landed: a real outage -> non-zero exit."""
    return int(summary.get("items") or 0) > 0 and int(summary.get("errored") or 0) > 0 \
        and int(summary.get("landed") or 0) == 0


def _receipt_fields(summary):
    keys = ("mode", "items", "scored", "unscored", "written", "skipped_unchanged", "errored", "skipped_errors")
    return {k: summary[k] for k in keys if k in summary}


def _empty_reason(summary):
    """Why a clean run produced nothing: off-hours tick with nothing due, or names with no usable factor."""
    if summary.get("empty_reason"):
        return summary["empty_reason"]
    if int(summary.get("landed") or 0) == 0 and not int(summary.get("errored") or 0):
        return "no_new_input"
    return None


def _pipeline_run():
    try:
        from pipeline_registry import PipelineRun
        return PipelineRun("hermes_watchlist_scorer")
    except Exception:  # pragma: no cover - registry unavailable: the run itself still proceeds
        import contextlib

        class _NoRun(contextlib.AbstractContextManager):
            def rows(self, n):
                pass

            def __exit__(self, *exc):
                return False
        return _NoRun()


def main(argv=None):
    # G2: after imports settle — refuse dual lib.X / scripts.lib.X identity
    from lib import assert_single_import_identity
    assert_single_import_identity()
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true",
                    help="compute every score on a READ ONLY session; write no rows, no receipt, send nothing")
    a = ap.parse_args(argv)
    if a.dry_run:
        from lib.lane_last_receipt import dry_run_report
        summary = run(limit=a.limit, dry_run=True)
        dry_run_report(LANE_ID, _receipt_fields(summary) | {"would_alert": summary.get("would_alert")},
                       would_write=["watchlist_items.hermes_*", "hermes_score_history",
                                    "hermes_score_event_queue.processed_at", "pipeline_runs"])
        return 1 if all_failed(summary) else 0

    from lib.lane_last_receipt import now_iso, write_lane_receipt
    started_at = now_iso()
    with _pipeline_run() as prun:
        try:
            summary = run(limit=a.limit)
        except Exception as exc:
            write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started_at,
                               script="hermes_watchlist_scorer.py", error=f"{type(exc).__name__}: {exc}",
                               output={"produced_count": 0, "attempted_count": 0,
                                       "skipped_reasons": {"dependency_unavailable": 1}})
            raise
        if summary.get("items"):
            prun.rows(int(summary.get("landed") or 0))
        emit_failure_alert(summary)
        rc = 1 if all_failed(summary) else 0
        write_lane_receipt(LANE_ID, ok=rc == 0, exit_code=rc, started_at=started_at,
                           script="hermes_watchlist_scorer.py", summary=_receipt_fields(summary),
                           error=(f"all {summary['items']} items errored: {summary['skipped_errors']}" if rc else None),
                           output={"produced_count": int(summary.get("landed") or 0),
                                   "attempted_count": int(summary.get("items") or 0),
                                   "skipped_reasons": summary.get("skipped_errors") or {},
                                   "empty_reason": _empty_reason(summary)})
        if rc:
            # SystemExit(str) exits 1 and PipelineRun records the run failed with this reason.
            raise SystemExit(f"[hermes-scorer] all {summary['items']} items errored: {summary['skipped_errors']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
