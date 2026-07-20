#!/usr/bin/env python3
"""watchlist_entry_planner.py — actionable ENTRY PLANS for watchlist items (operator req 2026-06-12).

For every watch-grade symbol (active watchlist + operator directives), goes beyond analysis to a
concrete plan: entry thesis · entry zone (typed: pullback/breakout/support-bounce/reversal) · limit
price with realistic fill odds · pullback definition + invalidation · stop + target + R:R · urgency
· layered exit ladder (T1 +1R de-risk / T2 plan target / T3 Street-mean runner with trail — same
deterministic math as command-center-v3 lib/exitLadder.ts) + in-trade monitoring rules.

ADVISORY ONLY — never submits orders, never modifies proposal state, never触execution. The proposal
section is a RECOMMENDATION tag (WAIT / READY / NEEDS_CONFIRMATION) for the operator's queue.

Alerting: urgency near_entry/ready, or price already inside the entry zone, sends a Telegram alert
(ticker, zone, limit, reason, urgency). One alert per symbol per day (dedup on alerted_at).

  python3 scripts/watchlist_entry_planner.py [--lane local|grok] [--symbols CIFR,DLR] [--limit 25]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import os
os.environ.setdefault("LOCAL_LLM_NUM_PREDICT", "700")   # strict-JSON plans need more than the 300 default

PROMPT_VERSION = "entry_planner_v1"

# ── CURATED PROMPT — same discipline as protection_advisor_v1: role → hard rules → labeled
# inputs → exact output contract. Identical across lanes so plans are comparable.
PROMPT_V1 = """You are a disciplined swing-trade entry planner. Produce an ACTIONABLE ENTRY PLAN for
a stock we are watching but do NOT yet own. You never place orders — the operator decides.

HARD RULES
- The entry ZONE must be technically anchored (pullback to SMA/support, breakout over resistance,
  support bounce, or reversal) — never "buy here" at any price.
- limit_price sits INSIDE the zone at a level with REALISTIC fill probability (no optimistic fills
  at the extreme of the zone).
- pullback_definition must be objective (e.g. "3-5% drop from 20d high into the rising 20d SMA").
- invalidation must state when the setup is DEAD (level or condition).
- stop is structural (below the zone's anchor, ATR-buffered), target honest vs analyst mean and
  recent range. risk_reward = (target-limit)/(limit-stop), one decimal.
- urgency: "ready" = price in/at zone now; "near_entry" = within ~1 ATR of the zone; else "watch".
- proposal_tag: READY only when urgency=ready AND confidence>=0.7; NEEDS_CONFIRMATION when a
  specific catalyst/level must confirm first; else WAIT.
- STRICT JSON only. Numbers as numbers.

CANDIDATE
symbol: {symbol} · price: ${price:.2f} · RSI14: {rsi} · ATR14: ${atr:.2f} ({atr_pct:.1f}%)
20d swing high: ${swing_high:.2f} · 20d swing low: ${swing_low:.2f} · 50d SMA: ${sma50:.2f} ({sma50_dist:+.1f}%)
hermes composite: {hermes} (rank #{rank}) · trend: {trend}
ANALYSTS: mean target {tgt_mean} · range {tgt_low}-{tgt_high} · rating {rec_key} · n={n_analysts}

OUTPUT (strict JSON):
{{"entry_thesis": "<max 50 words — why actionable now/soon + the trigger>",
  "setup_type": "pullback"|"breakout"|"support_bounce"|"reversal",
  "entry_zone_low": <number>, "entry_zone_high": <number>, "limit_price": <number>,
  "pullback_definition": "<objective qualifying condition>",
  "invalidation": "<level/condition that kills the setup>",
  "stop_price": <number>, "target_price": <number>, "risk_reward": <number>,
  "urgency": "watch"|"near_entry"|"ready", "confidence": <0.0-1.0>,
  "proposal": {{"tag": "WAIT"|"READY"|"NEEDS_CONFIRMATION",
               "suggested_entry": <number>, "sizing_rationale": "<max 25 words>"}}}}"""


def _alpaca_creds():
    """ALPACA_API_KEY / ALPACA_SECRET_KEY from env, falling back to the repo .env."""
    import os
    k, s = os.getenv("ALPACA_API_KEY", ""), os.getenv("ALPACA_SECRET_KEY", "")
    if k and s:
        return k, s
    try:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("ALPACA_API_KEY=") and not k:
                k = line.split("=", 1)[1].strip()
            elif line.startswith("ALPACA_SECRET_KEY=") and not s:
                s = line.split("=", 1)[1].strip()
    except Exception:
        pass
    return k, s


def _bars_alpaca(symbol, days=70):
    """Daily OHLC from the Alpaca data API (IEX feed — works on paper keys, NOT rate-limited like
    yfinance). Fallback bars source so entry plans keep generating when Yahoo is throttled."""
    import requests
    from datetime import datetime, timedelta, timezone
    k, s = _alpaca_creds()
    if not (k and s):
        return None
    start = (datetime.now(timezone.utc) - timedelta(days=max(days, 70) * 2 + 20)).date().isoformat()
    try:
        r = requests.get(
            f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
            params={"timeframe": "1Day", "start": start, "limit": 500, "adjustment": "raw", "feed": "iex"},
            headers={"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s}, timeout=15)
        if r.status_code != 200:
            return None
        bars = [{"high": float(b["h"]), "low": float(b["l"]), "close": float(b["c"])}
                for b in (r.json().get("bars") or [])]
        return bars[-days:] if len(bars) >= 50 else None
    except Exception:
        return None


def _bars(symbol, days=70):
    """yfinance first; on rate-limit/empty, fall back to Alpaca (IEX). Either returns the last `days`
    of {high,low,close} (≥50 bars) or None."""
    try:
        import yfinance as yf
        h = yf.Ticker(symbol).history(period="1y")
        bars = [{"high": float(hi), "low": float(lo), "close": float(c)}
                for hi, lo, c in zip(h["High"], h["Low"], h["Close"])]
        if len(bars) >= 50:
            return bars[-days:]
    except Exception:
        pass
    return _bars_alpaca(symbol, days)


def _tech(bars):
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    gains = losses = 0.0
    for i in range(-14, 0):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0); losses += max(-d, 0)
    rsi = round(100 - 100 / (1 + gains / losses), 1) if losses else 100.0
    trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
           for i in range(-14, 0)]
    return {"price": closes[-1], "rsi": rsi, "atr": sum(trs) / 14,
            "swing_high": max(highs[-20:]), "swing_low": min(lows[-20:]),
            "sma50": sum(closes[-50:]) / 50}


def _analyst(cur, symbol):
    cur.execute("""SELECT target_mean_price, target_low_price, target_high_price, recommendation_key,
                          number_of_analyst_opinions FROM yahoo_analyst_targets_history
                   WHERE symbol=%s ORDER BY created_at DESC LIMIT 1""", (symbol,))
    r = cur.fetchone()
    if not r:
        return {"tgt_mean": "n/a", "tgt_low": "n/a", "tgt_high": "n/a", "rec_key": "n/a",
                "n_analysts": 0, "tgt_mean_num": None}
    return {"tgt_mean": f"${float(r[0]):.2f}" if r[0] else "n/a",
            "tgt_low": f"${float(r[1]):.2f}" if r[1] else "n/a",
            "tgt_high": f"${float(r[2]):.2f}" if r[2] else "n/a",
            "rec_key": r[3] or "n/a", "n_analysts": int(r[4] or 0),
            "tgt_mean_num": float(r[0]) if r[0] else None}   # numeric mean for the exit ladder


MONITOR_RULES = ("+1R -> stop to breakeven; T1 filled -> trail 1R or prior-day low; "
                 "close below stop = exit, never average down; "
                 "no +0.5R within 5 sessions -> time-stop review")


def _exit_ladder(entry, stop, plan_target, street_target):
    """Deterministic layered scale-out — SAME math as command-center-v3 lib/exitLadder.ts so the
    engine, the Watchlist cards and the Manual ToS desk never disagree. The LLM's single target is
    the floor, not the whole exit: T1 banks +1R and de-risks, T2 is the plan target, T3 keeps a
    runner toward the Street mean with a trailing stop. Advisory only."""
    try:
        entry, stop = float(entry), float(stop)
    except (TypeError, ValueError):
        return None
    if entry <= 0 or stop <= 0 or entry <= stop:
        return None
    r = entry - stop
    plan_t = float(plan_target) if plan_target else None
    street = float(street_target) if street_target else None
    t1 = entry + r
    plan_above_t1 = bool(plan_t and plan_t > t1 + 0.01)
    t2 = plan_t if plan_above_t1 else entry + 2 * r
    steps = [
        {"px": round(t1, 2), "label": "T1 (+1R)", "action": "sell 1/3, move stop to breakeven"},
        {"px": round(t2, 2), "label": "T2 (plan target)" if plan_above_t1 else "T2 (+2R)",
         "action": "sell 1/3, trail stop to T1"},
    ]
    if street and street > t2 * 1.03:
        steps.append({"px": round(street, 2), "label": "T3 (Street mean)",
                      "action": "runner, trail 1R or prior-day low"})
    else:
        steps.append({"px": round(t2 + r, 2), "label": "T3 (runner)",
                      "action": "runner, trail 1R or prior-day low"})
    return {"r_per_share": round(r, 2), "steps": steps, "monitoring": MONITOR_RULES}


def _parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        p = json.loads(m.group(0)) if m else None
        return p if p and "entry_zone_low" in p else None
    except Exception:
        return None


# Thresholds for the Priority-2 "evidence of interest" signals (2026-07-20). Env-configurable
# rather than literal: these are policy, they will need tuning as the watchlist grows, and the
# standing rule is that no threshold is hardcoded. Defaults chosen from measured 2026-07-20
# watchlist distribution — a 5% move WITH >=2x relative volume, which distinguishes "something
# happened" from "this is a small cap on a normal day" (the bare 5% test admitted 523 names,
# 434 of them volume-confirmed).
INTEREST_MOVE_PCT = float(os.getenv("PLANNER_INTEREST_MOVE_PCT", "5.0"))
INTEREST_MOVE_RVOL = float(os.getenv("PLANNER_INTEREST_MOVE_RVOL", "2.0"))
INTEREST_CATALYST_DAYS = int(os.getenv("PLANNER_INTEREST_CATALYST_DAYS", "3"))
INTEREST_CATALYST_CONF = float(os.getenv("PLANNER_INTEREST_CATALYST_CONF", "0.7"))


def _weekly_drain_clause(sym_ref: str) -> str:
    """SQL predicate: TRUE when `sym_ref` needs (re)planning under the WEEKLY-with-catalyst-override
    cadence (operator 2026-07-01: "doesn't need daily grok — once weekly unless technicals drastically
    change or catalyst"). A name is held (predicate FALSE) only while it has a plan < 7 days old AND no
    non-'other' catalyst_event newer than that plan. A newer catalyst — news_momentum/short_squeeze for
    big technical moves, earnings/M&A/analyst/etc. for fundamentals — flips it back to TRUE (re-plan now).
    Unplanned names are always TRUE. `sym_ref` is the outer query's symbol column (e.g. wi.symbol).
    Operator-STARRED symbols (operator_starred_symbols) refresh on a FASTER 1-day cadence instead of 7
    (2026-07-01: "starred should update more frequently") — the catalyst override still applies to both."""
    return f"""NOT EXISTS (
                    SELECT 1 FROM watchlist_entry_plans ep
                    WHERE ep.symbol = {sym_ref}
                      AND ep.created_at > now() - (CASE WHEN EXISTS (
                              SELECT 1 FROM operator_starred_symbols s WHERE upper(s.symbol) = upper({sym_ref}))
                            THEN interval '1 day' ELSE interval '7 days' END)
                      AND NOT EXISTS (SELECT 1 FROM catalyst_events ce
                                      WHERE upper(ce.symbol) = upper({sym_ref})
                                        AND ce.catalyst_type <> 'other'
                                        AND COALESCE(ce.published_at, ce.created_at) > ep.created_at))"""


def _candidates(cur, limit, symbols=None, scope="watchlist", buy_rated_cap=20):
    if scope == "proposals":
        # operator 2026-06-12: "same should be done for strategy proposals" — validate each PENDING
        # proposal's entry against live structure (zone realism, urgency, WAIT/READY tag)
        cur.execute("""SELECT DISTINCT ON (symbol) symbol, NULL::numeric AS hermes_composite_score,
                         NULL::int AS hermes_rank, NULL::text AS trend,
                         id AS proposal_id, proposed_entry, proposed_stop, proposed_target1, strategy_id
                       FROM paper_trade_proposals
                       -- live pre-execution statuses (2026-06-12: actual pipeline uses
                       -- APPROVED_FOR_PAPER_TEST; bare 'APPROVED' never occurs — planner found 0)
                       WHERE status IN ('PENDING','APPROVED','APPROVED_FOR_PAPER_TEST')
                         AND symbol ~ '^[A-Z]{1,5}$'
                       ORDER BY symbol, created_at DESC""")
        # this branch fell off the function end (returned None) since 2026-06-12 — every
        # --scope proposals cron run crashed at run()'s for-loop before validating anything
        return [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
    else:
        # ON-DEMAND (operator 2026-06-18): an explicit --symbols request plans those exact watchlist
        # names REGARDLESS of status (researched/active/directive) — "I want to buy FATN/HPE, give me
        # an entry". Bypasses the active-only base + the buy-rated rotation cap below.
        if symbols:
            want = tuple(s.upper() for s in symbols)
            cur.execute("""SELECT DISTINCT ON (symbol) symbol, hermes_composite_score, hermes_rank, trend,
                             NULL::int AS proposal_id, NULL::numeric AS proposed_entry,
                             NULL::numeric AS proposed_stop, NULL::numeric AS proposed_target1, NULL::text AS strategy_id
                           FROM watchlist_items
                           WHERE upper(symbol) IN %s AND status <> 'removed'
                           ORDER BY symbol, hermes_composite_score DESC NULLS LAST""", (want,))
            return [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        # PRIORITY 1: directive-watch + active names. WEEKLY re-plan cadence with a catalyst override
        # (operator 2026-07-01: "doesn't need daily grok — once weekly unless technicals drastically change
        # or catalyst"). A name is HELD (skipped) only while it has a plan < 7 days old AND no NEW catalyst
        # since that plan; a non-'other' catalyst_event newer than the plan (news_momentum/short_squeeze
        # capture big technical moves, earnings/M&A/analyst/etc. capture fundamentals) forces an earlier
        # re-plan. Unplanned names always plan. This also drains the list by rank instead of re-planning the
        # same top ~`limit` every run (which starved low-ranked directive names like MRLN #76).
        cur.execute(f"""SELECT DISTINCT ON (symbol) symbol, hermes_composite_score, hermes_rank, trend,
                         NULL::int AS proposal_id, NULL::numeric AS proposed_entry,
                         NULL::numeric AS proposed_stop, NULL::numeric AS proposed_target1, NULL::text AS strategy_id,
                         EXISTS (SELECT 1 FROM operator_starred_symbols s
                                 WHERE upper(s.symbol) = upper(watchlist_items.symbol)) AS _starred
                       FROM watchlist_items
                       WHERE symbol ~ '^[A-Z]{{1,5}}$' AND status <> 'removed'
                         AND (in_directive_watch=true OR status='active'
                              OR EXISTS (SELECT 1 FROM operator_starred_symbols s
                                         WHERE upper(s.symbol) = upper(watchlist_items.symbol)))
                         AND {_weekly_drain_clause('watchlist_items.symbol')}
                       ORDER BY symbol, hermes_composite_score DESC NULLS LAST""")
        rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        if symbols:
            want = {s.upper() for s in symbols}
            rows = [r for r in rows if r["symbol"] in want]
        # starred names first: their 1-day cadence is meaningless if the rank sort leaves them
        # below the per-run `limit` cut (MRLN #71 sat at eligible-index ~114 and never re-planned)
        rows.sort(key=lambda r: (not r.get("_starred"), r["hermes_rank"] is None, r["hermes_rank"] or 1e9))
        rows = rows[:limit]
        # PRIORITY 2 — EVIDENCE OF INTEREST (was: CONVICTION COMPLETENESS).
        #
        # This lane used to select ONLY buy-side-rated names, which made the recommendation label a
        # ROUTING decision rather than a summary: a symbol labelled IGNORE/AVOID/HOLD could never
        # receive an entry plan, the card then displayed "no entry plan", and that absence read as
        # further evidence against the symbol. The label produced the gap and the gap corroborated the
        # label. Measured 2026-07-20: 96% plan coverage for BUY/ADD/ADD_ON_PULLBACK against 30-33% for
        # AVOID/IGNORE/HOLD and 2% for RESEARCH_MORE — a step, not a slope. 3,526 watchlist symbols are
        # reachable ONLY through this lane (Priority 1 requires directive/active/starred), so for those
        # the verdict was the sole determinant of whether any entry analysis ever ran.
        #
        # The deeper problem is that the two questions are unrelated. "Do we like this company?" and
        # "where would one enter it?" are different questions, and gating the second on the first means
        # the system can never answer "good company, bad entry today" — it simply goes quiet instead.
        # An entry plan is also what REFUTES a bad label: levels, invalidation and R:R are how an
        # operator sees the verdict is wrong.
        #
        # So the label is now ONE signal among five rather than the gate. A name qualifies on buy-side
        # conviction (unchanged), OR on evidence that someone should look regardless of the verdict:
        # operator star, a move >= 5%, a fresh high-confidence catalyst, or S1 scope promotion. The
        # buy_rated_cap still bounds per-run cost, so this widens WHO is reachable without widening how
        # much is spent per run. (operator 2026-07-20: "remove the label gate from the entry planner")
        #
        # Original intent preserved (operator 2026-07-01: "no info should be missing on strong buy, buy,
        # or wait") — buy-side names still qualify and still sort first. ANY status: this includes
        # directive/active buy
        # names too (previously excluded, which starved directive buy names below Priority 1's rank cap,
        # e.g. MRLN). Deduped against Priority 1 (`have`) so nothing is planned twice. NOT planned in the
        # WEEKLY re-plan cadence with catalyst override (see _weekly_drain_clause) → the cron DRAINS the
        # qualifying set resumably (buy_rated_cap = per-run batch size, cron sets 400). Skipped only under a
        # --symbols filter. run() routes every one of these through the OAuth lane (they're _buy_rated).
        if buy_rated_cap > 0 and not symbols:
            have = {r["symbol"] for r in rows}
            cur.execute(f"""SELECT * FROM (
                             SELECT DISTINCT ON (wi.symbol) wi.symbol, wi.hermes_composite_score,
                               wi.hermes_rank, wi.trend, NULL::int AS proposal_id,
                               NULL::numeric AS proposed_entry, NULL::numeric AS proposed_stop,
                               NULL::numeric AS proposed_target1, NULL::text AS strategy_id,
                               (COALESCE(wi.in_directive_watch,false) OR wi.status='active') AS _displayed,
                               -- Ranked ABOVE _displayed below: an operator star or a same-session
                               -- material move/catalyst is the most time-sensitive reason to plan, and
                               -- sorting these by hermes score alone buries them. BETA sat at hermes
                               -- rank 525 with six catalysts and a +7.6 pct day and was never
                               -- reached. (No literal percent sign in this comment: psycopg2 reads
                               -- it as a parameter placeholder and the execute raises IndexError.)
                               (EXISTS (SELECT 1 FROM operator_starred_symbols s
                                        WHERE UPPER(s.symbol) = UPPER(wi.symbol))
                                OR (ABS(COALESCE(wi.change_pct, 0)) >= {INTEREST_MOVE_PCT}
                                    AND COALESCE(wi.rvol, 0) >= {INTEREST_MOVE_RVOL})) AS _interest
                             FROM watchlist_items wi
                             WHERE wi.symbol ~ '^[A-Z]{{1,5}}$' AND wi.status <> 'removed'
                               AND (
                                 -- SIGNAL 1 — buy-side conviction (research card / CIO / analyst).
                                 EXISTS (SELECT 1 FROM watchlist_research_cards rc WHERE rc.symbol = wi.symbol
                                         AND UPPER(rc.latest_recommendation) IN ('BUY','STRONG_BUY','ADD','ADD_ON_PULLBACK'))
                                 OR EXISTS (SELECT 1 FROM watchlist_final_synthesis fs WHERE UPPER(fs.symbol) = UPPER(wi.symbol)
                                            AND UPPER(fs.recommendation) IN ('BUY','STRONG_BUY','ADD','ADD_ON_PULLBACK'))
                                 -- analyst rating too (2026-07-01): the card's top "strong buy"/"buy" is the
                                 -- analyst recommendation_key, distinct from research/CIO — names like NTST
                                 -- (analyst strong buy, no research/CIO buy) were slipping through blank.
                                 OR (SELECT LOWER(yat.recommendation_key) FROM yahoo_analyst_targets_history yat
                                     WHERE yat.symbol = wi.symbol ORDER BY yat.created_at DESC LIMIT 1)
                                     IN ('strong_buy','buy')
                                 -- SIGNAL 2 — OPERATOR INTEREST. A star is a direct instruction to
                                 -- analyse, and it must not be overruled by a verdict.
                                 OR EXISTS (SELECT 1 FROM operator_starred_symbols s
                                            WHERE UPPER(s.symbol) = UPPER(wi.symbol))
                                 -- SIGNAL 3 — MATERIAL MOVE, volume-confirmed. A move this size on
                                 -- elevated volume means the packet the verdict was formed from no
                                 -- longer describes the tape. RVOL is required so this reads
                                 -- "something happened" rather than "this is a small cap".
                                 OR (ABS(COALESCE(wi.change_pct, 0)) >= {INTEREST_MOVE_PCT}
                                     AND COALESCE(wi.rvol, 0) >= {INTEREST_MOVE_RVOL})
                                 -- SIGNAL 4 — FRESH CATALYST. Same reasoning on the fundamental side.
                                 OR EXISTS (SELECT 1 FROM catalyst_events ce
                                            WHERE UPPER(ce.symbol) = UPPER(wi.symbol)
                                              AND ce.catalyst_type <> 'other'
                                              AND ce.published_at > now() - interval '{INTEREST_CATALYST_DAYS} days'
                                              AND COALESCE(ce.confidence, 0) >= {INTEREST_CATALYST_CONF})
                                 -- SIGNAL 5 — SCOPE PROMOTION. The governor already decided this name
                                 -- warrants attention; planning is what "attention" should mean.
                                 OR UPPER(COALESCE(wi.scope_tier, '')) = 'S1'
                               )
                               AND {_weekly_drain_clause('wi.symbol')}
                             ORDER BY wi.symbol, wi.hermes_composite_score DESC NULLS LAST
                           ) t
                           -- displayed conviction (directive/active + top-rank — what the operator actually
                           -- sees) fills the cap FIRST, so a low-hermes directive name (e.g. NTST rank ~918)
                           -- is never crowded out by a deep researched name.
                           ORDER BY _interest DESC, _displayed DESC,
                                    hermes_composite_score DESC NULLS LAST LIMIT %s""",
                        (buy_rated_cap,))
            for r in cur.fetchall():
                d = dict(zip([dd[0] for dd in cur.description], r))
                if d["symbol"] not in have:
                    d["_buy_rated"] = True
                    rows.append(d)
        return rows


def _live(conn, cur):
    """Ping the DB connection and reconnect if the server dropped it. Each candidate stalls
    30-120s in yfinance/Ollama/OAuth calls, and the idle connection gets killed mid-drain
    ("SSL connection has been closed unexpectedly" — 2026-07-02/03 runs died after planning
    2/13 of ~300, starving every card downstream). psycopg2 can't see a server-side kill in
    conn.closed, so probe with SELECT 1 and rebuild through db_adapter on failure."""
    try:
        cur.execute("SELECT 1"); cur.fetchone()
        return conn, cur
    except Exception:
        from db_adapter import _get_conn, close_thread_conn
        try:
            close_thread_conn()
        except Exception:
            pass
        conn = _get_conn()
        return conn, conn.cursor()


def run(lane="local", symbols=None, limit=25, alert=True, scope="watchlist", buy_rated_cap=20):
    import llm_lane
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    base_lane = lane if llm_lane.available(lane) else "local"
    # STANDING BEHAVIOR (operator 2026-07-01): buy/strong-conviction names get the OAuth review lane
    # (Grok) instead of the weak local model — "need oauth review not local". Only kicks in when running
    # in the default local mode (an explicit --lane grok already routes everything through OAuth); the
    # low-conviction tail stays local to conserve the OAuth lane. Falls back to local if OAuth is down.
    oauth_lane = "grok" if llm_lane.available("grok") else None
    upgrade_conviction = base_lane == "local" and oauth_lane is not None
    buy_strong_syms = set()
    if upgrade_conviction:
        cur.execute("""SELECT DISTINCT upper(symbol) FROM (
                         SELECT symbol FROM watchlist_research_cards
                           WHERE upper(latest_recommendation) IN ('BUY','STRONG_BUY','ADD','ADD_ON_PULLBACK')
                         UNION
                         SELECT symbol FROM watchlist_final_synthesis
                           WHERE upper(recommendation) IN ('BUY','STRONG_BUY','ADD','ADD_ON_PULLBACK')
                         UNION
                         SELECT symbol FROM (
                           SELECT DISTINCT ON (symbol) symbol, lower(recommendation_key) rk
                           FROM yahoo_analyst_targets_history ORDER BY symbol, created_at DESC
                         ) a WHERE rk IN ('strong_buy','buy')
                       ) x""")
        buy_strong_syms = {r[0] for r in cur.fetchall()}
    done = failed = alerts = oauth_used = 0
    for c in _candidates(cur, limit, symbols, scope, buy_rated_cap):
        sym = c["symbol"]
        # per-symbol lane: buy/strong (P2 tags _buy_rated; P1/on-demand resolved via the set) → OAuth
        eff_lane = oauth_lane if (upgrade_conviction and (c.get("_buy_rated") or sym.upper() in buy_strong_syms)) else base_lane
        bars = _bars(sym)
        if not bars:
            failed += 1; continue
        t = _tech(bars)
        conn, cur = _live(conn, cur)   # _bars can stall long enough for the server to drop us
        an = _analyst(cur, sym)
        prompt = PROMPT_V1.format(symbol=sym, hermes=c.get("hermes_composite_score"),
                                  rank=c.get("hermes_rank"), trend=c.get("trend"),
                                  atr_pct=t["atr"] / t["price"] * 100,
                                  sma50_dist=(t["price"] - t["sma50"]) / t["sma50"] * 100,
                                  **{k: t[k] for k in ("price", "rsi", "atr", "swing_high", "swing_low", "sma50")},
                                  **{k: v for k, v in an.items() if k != "tgt_mean_num"})
        if scope == "proposals" and c.get("proposal_id"):
            prompt += (f"\nEXISTING PROPOSAL #{c['proposal_id']} (strategy {c.get('strategy_id')}): "
                       f"entry ${c.get('proposed_entry')} stop ${c.get('proposed_stop')} "
                       f"target ${c.get('proposed_target1')}. VALIDATE this entry against live structure: "
                       "your zone/limit may agree or amend it — say which in entry_thesis. The proposal "
                       "stays untouched; this is advisory.")
        try:
            out = llm_lane.generate(prompt, lane=eff_lane, timeout=120)
        except Exception as e:
            # completeness > lane (operator 2026-07-01: "no info should be missing on buy/strong/wait"):
            # if the OAuth lane errors/rate-limits, fall back to local so the card is never left blank.
            if eff_lane != base_lane:
                try:
                    out = llm_lane.generate(prompt, lane=base_lane, timeout=120)
                    eff_lane = base_lane
                except Exception as e2:
                    print(f"  {sym}: lane error {str(e2)[:60]}"); failed += 1; continue
            else:
                print(f"  {sym}: lane error {str(e)[:60]}"); failed += 1; continue
        p = _parse(out)
        if not p:
            print(f"  {sym}: unparseable"); failed += 1; continue
        model = "grok-3-mini" if eff_lane == "grok" else getattr(__import__("local_llm"), "model_used", None) or "local"
        if eff_lane == "grok":
            oauth_used += 1
        # ── DETERMINISTIC R:R AND URGENCY (2026-07-20) ──────────────────────────
        # Both were taken from the model. Neither survived checking.
        #
        # BETA's first plan stored risk_reward=1.5 against limit 17.75 / stop 16.94 /
        # target 20.00, where the arithmetic gives 2.78 — and 1.00 to the T1 rung. The
        # stored number was not derivable from any level in its own plan. The prompt
        # asks for (target-limit)/(limit-stop); nothing verified it, so the answer was
        # whatever the model felt like. The same plan claimed urgency=near_entry with
        # spot at 19.805 and the entry zone topping out at 18.20 — 8.1% away — because
        # the only server-side adjustment was an UPGRADE (watch -> ready when price is
        # inside the zone) and no path could ever downgrade an overstated one.
        #
        # near_entry is one of the two urgency values that unlock PROPOSE_ENTRY, so an
        # overstated urgency is not cosmetic — it is a button that should not be lit.
        #
        # These are arithmetic over levels the model already chose, so the model has no
        # business authoring them. It picks the levels; the levels imply the rest.
        _lim, _stop, _tgt = p.get("limit_price"), p.get("stop_price"), p.get("target_price")
        _model_rr = p.get("risk_reward")
        if _lim and _stop and _tgt and float(_lim) > float(_stop):
            _risk = float(_lim) - float(_stop)
            p["risk_reward"] = round((float(_tgt) - float(_lim)) / _risk, 1)
            # Keep the model's claim when it differs, so the drift is auditable rather
            # than silently overwritten.
            if _model_rr is not None and abs(float(_model_rr) - p["risk_reward"]) >= 0.1:
                p["risk_reward_model_claimed"] = _model_rr
                p["risk_reward_source"] = "recomputed_from_levels"
        else:
            # Levels that cannot produce an R:R must not carry one.
            p["risk_reward"] = None
            if _model_rr is not None:
                p["risk_reward_model_claimed"] = _model_rr
                p["risk_reward_source"] = "rejected_unverifiable_levels"

        # Urgency from distance to the zone, in ATR — the same rule the prompt states
        # ("ready" = in zone, "near_entry" = within ~1 ATR) but enforced rather than
        # requested. Distance is measured to the NEAR edge of the zone.
        _zlo, _zhi, _atr = p.get("entry_zone_low"), p.get("entry_zone_high"), t.get("atr")
        _model_urg = p.get("urgency", "watch")
        if _zlo and _zhi and _atr and float(_atr) > 0:
            _px = float(t["price"])
            if float(_zlo) <= _px <= float(_zhi):
                urg = "ready"
            else:
                _dist = (float(_zlo) - _px) if _px < float(_zlo) else (_px - float(_zhi))
                urg = "near_entry" if _dist <= float(_atr) else "watch"
            if urg != _model_urg:
                p["urgency_model_claimed"] = _model_urg
                p["urgency_source"] = "recomputed_from_atr_distance"
                p["urgency_distance_atr"] = round(
                    0.0 if urg == "ready"
                    else ((float(_zlo) - _px) if _px < float(_zlo) else (_px - float(_zhi))) / float(_atr), 2)
        else:
            # No ATR means the distance rule cannot run. Fail to the value that does
            # NOT unlock PROPOSE_ENTRY rather than trusting the model's.
            urg = "ready" if (_zlo and _zhi and float(_zlo) <= float(t["price"]) <= float(_zhi)) else "watch"
            if urg != _model_urg:
                p["urgency_model_claimed"] = _model_urg
                p["urgency_source"] = "no_atr_failed_closed"
        p["urgency"] = urg
        prop = p.get("proposal") or {}
        # The tag's own rule (line 49) makes it a FUNCTION of urgency and confidence,
        # so a recomputed urgency must not leave a stale READY behind it. Enforced in
        # one direction only: a model tag may be demoted by the arithmetic, never
        # promoted by it — READY is a claim the model has to make for itself.
        if str(prop.get("tag") or "").upper() == "READY" \
                and not (urg == "ready" and float(p.get("confidence") or 0) >= 0.7):
            prop["tag_model_claimed"] = prop.get("tag")
            prop["tag"] = "NEEDS_CONFIRMATION"
            prop["tag_source"] = "demoted_urgency_or_confidence"
            p["proposal"] = prop
        p["scope"] = scope
        if c.get("proposal_id"):
            p["proposal_id"] = c["proposal_id"]
        # layered exit plan (operator 2026-06-12): deterministic ladder from the LLM's entry/stop/target
        # + Street mean — stored in the plan JSON so proposals, cards and alerts all carry it
        p["exit_ladder"] = _exit_ladder(p.get("limit_price"), p.get("stop_price"),
                                        p.get("target_price"), an.get("tgt_mean_num"))
        conn, cur = _live(conn, cur)   # LLM call above runs 30-120s — reconnect if dropped
        cur.execute("""INSERT INTO watchlist_entry_plans
                         (symbol, plan, setup_type, entry_zone_low, entry_zone_high, limit_price,
                          stop_price, target_price, risk_reward, urgency, confidence, proposal_tag,
                          price_at_plan, model_used, prompt_version)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (sym, json.dumps(p), p.get("setup_type"), p.get("entry_zone_low"),
                     p.get("entry_zone_high"), p.get("limit_price"), p.get("stop_price"),
                     p.get("target_price"), p.get("risk_reward"), urg, p.get("confidence"),
                     prop.get("tag"), t["price"], model, PROMPT_VERSION))
        plan_id = cur.fetchone()[0]
        conn.commit()
        print(f"  {sym}: {p.get('setup_type')} zone {p.get('entry_zone_low')}-{p.get('entry_zone_high')} "
              f"limit {p.get('limit_price')} R:R {p.get('risk_reward')} · {urg} · {prop.get('tag')}")
        done += 1
        # pre-promotion buy-rated names are NOT active watches — plan them, but don't Telegram-alert
        # (operator no-noise rule); they alert once you promote them to an active watch/directive.
        if alert and urg in ("near_entry", "ready") and not c.get("_buy_rated"):
            cur.execute("""SELECT 1 FROM watchlist_entry_plans WHERE symbol=%s AND alerted_at > now()-interval '20 hours'""", (sym,))
            if not cur.fetchone():
                if _alert(sym, p, urg, t["price"]):
                    cur.execute("UPDATE watchlist_entry_plans SET alerted_at=now() WHERE id=%s", (plan_id,))
                    conn.commit(); alerts += 1
    print(json.dumps({"lane": base_lane, "oauth_upgraded": upgrade_conviction, "planned": done,
                      "via_oauth": oauth_used, "failed": failed, "alerts": alerts,
                      "note": "ADVISORY ONLY — no orders, no proposal-state changes, no execution"}))


def _alert(sym, p, urg, price) -> bool:
    import os
    tok = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not tok:
        try:
            for l in (PROJECT_ROOT / ".env").read_text().splitlines():
                if l.startswith("TELEGRAM_BOT_TOKEN="):
                    tok = l.split("=", 1)[1].strip()
        except Exception:
            pass
    try:
        from tg_chat_ids import chat_ids
        chat = (chat_ids() or [None])[0]
    except Exception:
        chat = None
    if not (tok and chat):
        return False
    icon = "🟢 READY" if urg == "ready" else "🟡 NEAR-ENTRY"
    prop = p.get("proposal") or {}
    lad = p.get("exit_ladder")
    ladder_txt = ""
    if lad and lad.get("steps"):
        ladder_txt = (f"exit ladder (R ${lad.get('r_per_share')}/sh):\n"
                      + "\n".join(f"  {s['label']} ${s['px']} — {s['action']}" for s in lad["steps"])
                      + "\n")
    text = (f"{icon} *ENTRY ALERT — {sym}* (advisory)\n"
            f"setup: {p.get('setup_type')} · now ${price:.2f}\n"
            f"zone: ${p.get('entry_zone_low')}–${p.get('entry_zone_high')} · limit ${p.get('limit_price')}\n"
            f"stop ${p.get('stop_price')} · target ${p.get('target_price')} · R:R {p.get('risk_reward')}\n"
            f"{ladder_txt}"
            f"why: {str(p.get('entry_thesis',''))[:180]}\n"
            f"invalidation: {str(p.get('invalidation',''))[:120]}\n"
            f"proposal advice: *{prop.get('tag','WAIT')}* — {str(prop.get('sizing_rationale',''))[:100]}\n"
            f"_advisory only — nothing queued, nothing executed_")
    try:
        import requests
        requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      json={"chat_id": chat, "text": text, "parse_mode": "Markdown"}, timeout=10)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", default="local", choices=["local", "grok"])
    ap.add_argument("--symbols")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--scope", default="watchlist", choices=["watchlist", "proposals"])
    ap.add_argument("--buy-rated-cap", type=int, default=20,
                    help="also plan up to N strongest BUY-rated researched names (0=off)")
    ap.add_argument("--no-alert", action="store_true")
    a = ap.parse_args()
    run(lane=a.lane, symbols=a.symbols.split(",") if a.symbols else None,
        limit=a.limit, alert=not a.no_alert, scope=a.scope, buy_rated_cap=a.buy_rated_cap)
