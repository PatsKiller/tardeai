#!/usr/bin/env python3
"""shadow_decision_service.py — the canonical multidimensional decision, in shadow.

STAGE A. Generates and persists the full decision packet alongside the legacy
one-word verdict. Changes NO production surface: not the Command Center card,
not proposal eligibility, not routing, not any execution path.

WHAT IT WIRES TOGETHER
----------------------
    event_normalizer   canonical 7-state event, headline-parsed  (Stage A item 1)
    position_truth     live ownership as ground truth            (Stage A item 2)
    decision_packet    six dimensions, validation, retired labels
    trade_blueprints   deterministic construction + payoff arithmetic
    blind_review       per-dimension agreement, anchored disclosure
    watchlist_entry_plans   legacy equity plan, as the SWING component only

EVERY FAMILY IS ALWAYS PRESENT
------------------------------
LONG_TERM, SWING, BEARISH, OPTIONS and NO_TRADE each return exactly one of
ELIGIBLE / CONDITIONAL / REJECTED / NOT_APPLICABLE / DATA_UNAVAILABLE. A family
is never omitted, and a non-ELIGIBLE family always carries reasons. Silence is
the failure mode this whole programme exists to remove — "we did not look"
rendered as "there is nothing there".

OPTIONS AND THE CHAIN
---------------------
The options family attempts the governed Schwab chain path
(schwab_transport.get_option_chain) exactly once per evaluation. On failure it
returns DATA_UNAVAILABLE recording provider, attempted operation, timestamp and
the exact failure reason. It NEVER substitutes an estimated price — a payoff
computed from a Black-Scholes guess looks calculated and is not, and
`bs_estimate_only` already blocks downstream, so a card built on one would be
refused later anyway.

READBACK
    .venv/bin/python scripts/shadow_decision_service.py --symbol BETA --readback
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import decision_packet as dp          # noqa: E402
import event_normalizer as ev         # noqa: E402
import position_truth as pt           # noqa: E402
import trade_blueprints as tb         # noqa: E402

PACKET_VERSION = "1.1.0-shadow"

# Fundamental fields lifted from the Finviz enrichment cache into the blind facts
# packet, so the models can form a THESIS from evidence instead of declining with
# INSUFFICIENT_EVIDENCE off technicals alone (42/62 did on the first batch).
#
# The exclusions matter as much as the inclusions:
#   recom, recom_score, analyst_rating  — analyst VERDICTS; feeding these anchors
#                                          the blind pass (the whole defect).
#   trend, rsi_status                   — pre-chewed signal labels, mild anchors.
#   volatility_w_pct                    — known misparsed (do-not-use, per memory).
FUNDAMENTAL_KEYS = (
    "company", "country",
    "pe", "forward_pe", "peg", "pb", "ps", "pfcf",
    "eps_ttm", "eps_next_y", "eps_next_5y", "eps_past_5y", "eps_qoq",
    "sales_past_5y", "sales_qoq",
    "gross_margin_pct", "oper_margin_pct", "profit_margin_pct",
    "roe_pct", "roa_pct", "roic_pct",
    "lt_debt_equity", "total_debt_equity", "current_ratio", "quick_ratio",
    "div_yield_pct", "beta", "inst_own_pct", "insider_own_pct",
    "short_float_pct", "short_ratio", "shares_outstanding_m",
    "week52_high_pct", "week52_low_pct",
)
_ENRICHMENT_CACHE = None
_ENRICHMENT_MTIME = None

ELIGIBLE, CONDITIONAL, REJECTED = "ELIGIBLE", "CONDITIONAL", "REJECTED"
NOT_APPLICABLE, DATA_UNAVAILABLE = "NOT_APPLICABLE", "DATA_UNAVAILABLE"

REQUIRED_FAMILIES = ("LONG_TERM", "SWING", "BEARISH", "OPTIONS", "NO_TRADE")


def _sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
                              capture_output=True, text=True, timeout=10).stdout.strip()[:12]
    except Exception:
        return ""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── facts ─────────────────────────────────────────────────────────────────────

def _fundamentals_for(symbol: str) -> dict:
    """Clean fundamentals for a symbol from the Finviz enrichment cache.

    Whitelisted keys only — analyst verdicts (recom/analyst_rating) and the
    known-misparsed volatility_w_pct never enter. market_cap is normalised to
    an unambiguous millions field (the cache's 'market_cap_b' is actually in
    millions, e.g. 67674.87 for a ~$68B name)."""
    global _ENRICHMENT_CACHE, _ENRICHMENT_MTIME
    # Reload when the cache file changes (a long-running server would otherwise
    # hold the first snapshot forever). Critically, NEVER lock in an empty parse:
    # if the very first read lands on a missing/mid-rewrite file we serve {} for
    # now but leave the mtime unset so the next call retries — otherwise every
    # current-input snapshot would carry zero fundamentals and falsely flag every
    # packet FUNDAMENTALS_CHANGED.
    path = PROJECT_ROOT / "data" / "portfolios" / "state" / "ticker_enrichment_cache.json"
    try:
        mtime = path.stat().st_mtime if path.exists() else None
    except OSError:
        mtime = None
    if _ENRICHMENT_CACHE is None or mtime != _ENRICHMENT_MTIME:
        try:
            data = json.loads(path.read_text()) if path.exists() else {}
        except Exception:
            data = None
        if data:
            _ENRICHMENT_CACHE = data
            _ENRICHMENT_MTIME = mtime
        elif _ENRICHMENT_CACHE is None:
            _ENRICHMENT_CACHE = {}   # first load failed; retry next call (mtime stays unset)
    e = _ENRICHMENT_CACHE.get(symbol.upper()) or _ENRICHMENT_CACHE.get(symbol) or {}
    if not isinstance(e, dict):
        return {}
    out = {k: e[k] for k in FUNDAMENTAL_KEYS if e.get(k) is not None}
    mc = e.get("market_cap_b")
    if mc is not None:
        out["market_cap_usd_millions"] = mc     # cache mislabels millions as "_b"
    if e.get("cached_at"):
        out["fundamentals_as_of"] = e["cached_at"]
    return out


def gather_facts(symbol: str, conn) -> dict:
    """Everything deterministic, before any model is asked."""
    sym = symbol.upper()
    cur = conn.cursor()
    facts: dict = {"symbol": sym}

    # watchlist_items has no `sector` column (sector lives on symbol_profiles);
    # asserting one raised UndefinedColumn on the first live run.
    cur.execute("""SELECT price, change_pct, rsi, rvol, float_m, hermes_composite_score,
                          hermes_rank, last_enriched_at, scope_tier
                   FROM watchlist_items WHERE upper(symbol)=%s
                   ORDER BY last_enriched_at DESC NULLS LAST LIMIT 1""", (sym,))
    r = cur.fetchone()
    if r:
        facts.update(enriched_price=float(r[0]) if r[0] is not None else None,
                     change_pct=float(r[1]) if r[1] is not None else None,
                     rsi=float(r[2]) if r[2] is not None else None,
                     rvol=float(r[3]) if r[3] is not None else None,
                     float_m=float(r[4]) if r[4] is not None else None,
                     hermes_score=float(r[5]) if r[5] is not None else None,
                     hermes_rank=r[6], enriched_at=str(r[7] or ""),
                     scope_tier=r[8])
    cur.execute("SELECT sector, industry, instrument_type, quote_type FROM symbol_profiles WHERE upper(symbol)=%s", (sym,))
    r2 = cur.fetchone()
    (facts["sector"], facts["industry"], facts["instrument_type"], facts["quote_type"]) = (
        (r2[0], r2[1], r2[2], r2[3]) if r2 else (None, None, None, None))

    # Fundamentals from the Finviz enrichment cache — the evidence the models
    # need for a thesis. Anchor/verdict keys are excluded by the whitelist.
    fund = _fundamentals_for(sym)
    facts["fundamentals"] = fund
    # A genuine short_float lets the bearish family's squeeze check use real data
    # instead of the UNKNOWN default.
    if fund.get("short_float_pct") is not None:
        facts["short_float_pct"] = fund["short_float_pct"]

    cur.execute("""SELECT price, fetched_at FROM market_quotes WHERE symbol=%s
                   ORDER BY fetched_at DESC LIMIT 1""", (sym,))
    r = cur.fetchone()
    facts["live_price"] = float(r[0]) if r and r[0] is not None else None
    facts["live_price_as_of"] = str(r[1]) if r else None

    # ATR and swing levels need TRUE RANGE, which needs highs and lows.
    # ticker_prices stores close_price ONLY — no high, no low. Computing a
    # close-to-close dispersion and calling it "ATR" would be the same class of
    # mislabelling as the model-authored R:R this session already removed: a
    # number that looks like true range and is not. So reuse the planner's real
    # OHLC path (yfinance, with an Alpaca fallback) and leave atr None if it
    # cannot be obtained, which downgrades the affected families to
    # DATA_UNAVAILABLE with a stated reason rather than inventing levels.
    facts["atr"] = None
    facts["support"], facts["resistance"] = [], []
    facts["technicals_source"] = None
    try:
        import watchlist_entry_planner as wep
        bars = wep._bars(sym, 90)
        if bars and len(bars) >= 50:
            t = wep._tech(bars)
            facts["atr"] = round(float(t["atr"]), 4)
            facts["rsi"] = facts.get("rsi") or t.get("rsi")
            facts["support"] = sorted({round(float(t["swing_low"]), 2)})
            facts["resistance"] = sorted({round(float(t["swing_high"]), 2)})
            facts["sma50"] = round(float(t["sma50"]), 4)
            facts["technicals_source"] = "ohlc_bars"
            facts["bars_used"] = len(bars)
    except Exception as exc:
        facts["technicals_error"] = f"{type(exc).__name__}: {str(exc)[:140]}"

    cur.execute("""SELECT headline, published_at, catalyst_type, confidence
                   FROM catalyst_events WHERE upper(symbol)=%s
                     AND published_at > now() - interval '30 days'
                   ORDER BY published_at DESC LIMIT 12""", (sym,))
    facts["catalysts"] = [{"headline": h, "published_at": str(p), "type": t,
                           "confidence": float(c) if c is not None else None}
                          for h, p, t, c in cur.fetchall()]
    return facts


def assess_data_quality(facts: dict, event: ev.EventState) -> dict:
    """Freshness is a first-class dimension. The BETA card reasoned from a packet
    2.9 days old while quoting a live price and said nothing about it."""
    problems, state = [], "FRESH"
    live, enriched = facts.get("live_price"), facts.get("enriched_price")
    drift = None
    if live and enriched:
        drift = abs(live - enriched) / live * 100
        if drift > 1.0:
            problems.append(f"enrichment price {enriched} differs from live {live} by {drift:.1f} pct")
            state = "PARTIAL"
    if not facts.get("atr"):
        problems.append("no ATR — levels and stops cannot be computed")
        state = "INSUFFICIENT"
    if not facts.get("support"):
        problems.append("no support levels — invalidation would be arbitrary")
        state = "INSUFFICIENT" if state != "INSUFFICIENT" else state
    if event.state in (ev.PROVIDER_DOWN,):
        problems.append(f"event provider down: {event.reason}")
        state = "PROVIDER_DOWN"
    elif event.state == ev.CONFLICTED:
        problems.append(f"event sources disagree: {event.reason}")
        state = "CONFLICTED"

    # ── PER-DIMENSION freshness (Part D) ──────────────────────────────────────
    # The packet must NOT read DATA FRESH just because price is fresh while
    # fundamentals are stale. Classify each dimension, keep them visible, and
    # derive the overall state deterministically as the worst of them.
    price_dim = ("STALE" if (drift is not None and drift > 3.0)
                 else "PARTIAL" if (drift is not None and drift > 1.0) else "FRESH")
    tech_dim = "FRESH" if facts.get("atr") else "STALE"
    try:
        import fundamentals_freshness as ff
        fq = ff.classify(facts.get("fundamentals") or {},
                         instrument_type=facts.get("instrument_type"),
                         quote_type=facts.get("quote_type"),
                         fetched_at=(facts.get("fundamentals") or {}).get("fundamentals_as_of"))
    except Exception:
        fq = {"state": "UNAVAILABLE", "missing_critical_fields": []}
    fund_dim = fq.get("state")
    event_dim = ("FRESH" if event.state in (ev.SCHEDULED, ev.NONE_CONFIRMED)
                 else "CONFLICTED" if event.state == ev.CONFLICTED
                 else "STALE" if event.state == ev.STALE else "UNKNOWN")
    dims = {"price": price_dim, "technicals": tech_dim,
            "fundamentals": fund_dim, "event": event_dim}

    # A stale/partial FUNDAMENTAL set drags the overall state down (but a long-term
    # thesis on it stays VISIBLE — the action policy is what refuses READY).
    if fund_dim in ("STALE",):
        problems.append(f"fundamentals stale ({fq.get('cache_age_days')}d) — thesis rests on old data")
        state = "STALE" if state == "FRESH" else state
    elif fund_dim in ("PARTIAL",):
        problems.append(f"fundamentals partial — missing {fq.get('missing_critical_fields')}")
        state = "PARTIAL" if state == "FRESH" else state
    elif fund_dim == "UNAVAILABLE":
        problems.append("no fundamentals for an operating company")
        state = "PARTIAL" if state == "FRESH" else state

    return {"state": state, "fields": problems, "price_drift_pct": drift,
            "dimensions": dims, "fundamentals_provenance": fq,
            "actionable": state in ("FRESH", "PARTIAL")}


# ── families ──────────────────────────────────────────────────────────────────

def build_long_term(facts, event, ownership, thesis_state, timing) -> dict:
    if not facts.get("atr") or not facts.get("support"):
        return {"family": "LONG_TERM", "state": DATA_UNAVAILABLE,
                "structures": [], "rejection_reasons": [
                    "insufficient price history to compute ATR or support — a staged "
                    "plan without levels would be prose, not a plan"]}
    # Thesis gate first — a constructible ladder is not an ownership recommendation
    # when the long-term thesis is unattractive or unproven.
    thesis_decision = dp.thesis_to_long_term_decision(thesis_state)
    try:
        bp = tb.staged_shares(
            symbol=facts["symbol"],
            current_price=facts.get("live_price") or facts.get("enriched_price") or 0,
            atr=facts["atr"], support=facts["support"], resistance=facts["resistance"],
            thesis_state=thesis_state, timing=timing,
            account_equity=float(os.getenv("SHADOW_ACCOUNT_EQUITY", "1252958")),
            earnings_date=event.date.isoformat() if event.date else None)
        # Mechanical default from timing; reconcile_plan_families applies thesis.
        mech_state = CONDITIONAL if timing in ("EXTENDED", "WAIT_FOR_PULLBACK",
                                               "BREAKOUT_CONFIRMATION") else ELIGIBLE
        if thesis_decision in (REJECTED, DATA_UNAVAILABLE):
            bp["state"] = thesis_decision
            bp["rejection_reasons"] = [
                f"thesis {thesis_state} → decision_state {thesis_decision} "
                f"(mechanics constructible but ownership not recommended)"]
            state = thesis_decision
        else:
            state = CONDITIONAL if thesis_decision == CONDITIONAL else mech_state
            bp["state"] = state
        return {"family": "LONG_TERM", "state": state, "structures": [bp],
                "rejection_reasons": list(bp.get("rejection_reasons") or [])}
    except tb.BlueprintRejected as exc:
        return {"family": "LONG_TERM", "state": REJECTED, "structures": [],
                "rejection_reasons": list(exc.reasons)}


# ── V6 swing-entry governance (pure, fixture-testable) ───────────────────────
CHASE_TOLERANCE_PCT = 1.5      # marginally-above-zone tolerance
CHASE_TOLERANCE_ATR = 0.5
BREAKOUT_MAX_PCT = 8.0         # a trigger farther than min(8%, 2 ATR) is NEVER
BREAKOUT_MAX_ATR = 2.0         # an actionable candidate — watch scenario only
BREAKOUT_TEST_WINDOW_BARS = 20
BREAKOUT_TEST_TOL_ATR = 1.0
BREAKOUT_BASE_RANGE_ATR = 2.5


def assess_swing_entry(*, price, zone_low, zone_high, stop, atr,
                       technical_state=None) -> dict:
    """THE rule: a missed plan becomes NO CURRENT TRADE. It never mutates into a
    different strategy to keep the card populated (the FATN defect: $4.75 price
    was rendered as a $6.76 'entry' because a stale pullback plan auto-converted
    to breakout mode at any resistance above price)."""
    out = {"entry_state": "UNRESOLVED", "family_state": "CONDITIONAL",
           "action_state": "WAIT_FOR_PULLBACK", "mechanics_current": True,
           "trigger": None, "reasons": [], "summary": None, "watch_scenarios": []}
    if price is None or zone_low is None or zone_high is None:
        out["reasons"] = ["missing current price or entry zone — cannot assess entry state"]
        return out
    if stop is not None and price < stop:
        out.update(entry_state="INVALIDATED", family_state="REJECTED",
                   mechanics_current=False,
                   reasons=[f"price {price:.2f} is below the plan invalidation {stop:.2f}"],
                   summary="INVALIDATED — the plan's stop level was breached; no current entry")
        return out
    if zone_low <= price <= zone_high:
        mc = (((technical_state or {}).get("timeframes") or {}).get("daily") or {}) \
            .get("momentum_context") or {}
        if mc.get("state") == "OVERSOLD_CONTINUING_DOWN":
            out.update(entry_state="WAIT_PULLBACK",
                       trigger=f"price holds the {zone_low:.2f}-{zone_high:.2f} zone with stabilizing momentum",
                       reasons=["price is in the entry zone but momentum is still deteriorating — wait for stabilization"])
        else:
            out.update(entry_state="READY_PULLBACK", family_state="ELIGIBLE",
                       action_state="READY",
                       trigger=f"price holds the {zone_low:.2f}-{zone_high:.2f} entry zone")
        return out
    if price > zone_high:
        dist_abs = price - zone_high
        dist_pct = 100.0 * dist_abs / price
        dist_atr = (dist_abs / atr) if atr else None
        within_chase = (dist_pct <= CHASE_TOLERANCE_PCT
                        or (dist_atr is not None and dist_atr <= CHASE_TOLERANCE_ATR))
        if within_chase:
            out.update(entry_state="WAIT_PULLBACK",
                       trigger=f"pullback into the {zone_low:.2f}-{zone_high:.2f} zone",
                       reasons=[f"price {price:.2f} is marginally above the zone "
                                f"({dist_pct:.1f}%{f' / {dist_atr:.1f} ATR' if dist_atr is not None else ''}) "
                                f"— inside chase tolerance; original mechanics shown as reference"])
            return out
        out.update(entry_state="MISSED_ENTRY", family_state="REJECTED",
                   mechanics_current=False,
                   reasons=[f"entry missed: price {price:.2f} is {dist_pct:.1f}%"
                            f"{f' / {dist_atr:.1f} ATR' if dist_atr is not None else ''} above the "
                            f"{zone_low:.2f}-{zone_high:.2f} zone — no current entry, do not chase"],
                   summary=(f"MISSED ENTRY — price {price:.2f} is above the "
                            f"{zone_low:.2f}-{zone_high:.2f} zone. No current entry. Do not chase."),
                   watch_scenarios=[{"kind": "PULLBACK_REENTRY",
                                     "zone": [zone_low, zone_high], "actionable": False,
                                     "note": "next valid condition: pullback and stabilization near the original zone"}])
        return out
    out.update(entry_state="WAIT_PULLBACK",
               trigger=f"reclaim and hold the {zone_low:.2f}-{zone_high:.2f} zone",
               reasons=[f"price {price:.2f} is below the entry zone — wait for reclaim"])
    return out


def assess_breakout_blueprint(*, symbol, price, atr, resistance, conn=None,
                              technical_state=None) -> dict:
    """A breakout is a SEPARATE blueprint, built independently from current
    closed-bar structure — never a re-labeling of stale pullback mechanics.
    Eligibility: trigger within min(8%, 2 ATR) of price, resistance tested
    within the recent closed-bar window, a consolidation base beneath it, and
    non-thin volume. Anything farther/looser is a non-actionable watch level."""
    if not (price and resistance and resistance > price):
        return {}
    dist_abs = resistance - price
    dist_pct = 100.0 * dist_abs / price
    dist_atr = (dist_abs / atr) if atr else None
    scenario = {"kind": "BREAKOUT_WATCH_LEVEL", "level": round(resistance, 2),
                "distance_pct": round(dist_pct, 1),
                "distance_atr": round(dist_atr, 2) if dist_atr is not None else None,
                "actionable": False}
    if dist_pct > BREAKOUT_MAX_PCT or (dist_atr is not None and dist_atr > BREAKOUT_MAX_ATR):
        scenario["note"] = (f"distant resistance ({dist_pct:.1f}% away) — FUTURE SCENARIO only, "
                            f"never current mechanics")
        return {"watch_scenario": scenario}
    if not atr or conn is None:
        scenario["note"] = "breakout candidacy unassessable (missing ATR or bars)"
        return {"watch_scenario": scenario}
    # closed-bar structure checks
    try:
        cur = conn.cursor()
        cur.execute("""SELECT high, low, close FROM market_ohlcv_bars
                       WHERE upper(symbol)=%s AND timeframe='daily'
                         AND bar_time < now() - interval '16 hours'
                       ORDER BY bar_time DESC LIMIT %s""",
                    (symbol.upper(), BREAKOUT_TEST_WINDOW_BARS))
        bars = cur.fetchall()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        bars = []
    if len(bars) < 10:
        scenario["note"] = "insufficient closed daily bars to validate a breakout base"
        return {"watch_scenario": scenario}
    tested = any(float(h) >= resistance - BREAKOUT_TEST_TOL_ATR * atr for h, _, _ in bars)
    closes = [float(c) for _, _, c in bars[:10]]
    base_ok = (max(closes) - min(closes)) <= BREAKOUT_BASE_RANGE_ATR * atr
    vroc = ((((technical_state or {}).get("timeframes") or {}).get("daily") or {})
            .get("indicators") or {}).get("volume_roc") or {}
    vol_ratio = (vroc.get("details") or {}).get("volume_ratio")
    vol_ok = vol_ratio is None or vol_ratio >= 0.8
    failed = [w for ok, w in ((tested, "resistance not tested in the recent window"),
                              (base_ok, "no consolidation base beneath the trigger"),
                              (vol_ok, f"volume too thin (RVOL {vol_ratio})")) if not ok]
    if failed:
        scenario["note"] = "breakout candidacy failed: " + "; ".join(failed)
        return {"watch_scenario": scenario}
    new_stop = round(resistance - 1.2 * atr, 2)
    risk = resistance - new_stop
    last_close = float(bars[0][2])
    confirmed = last_close > resistance
    bp = {"structure": "BREAKOUT_SWING", "entry_mode": "BREAKOUT",
          "entry_state": "READY_BREAKOUT" if confirmed else "WAIT_BREAKOUT",
          "state": ELIGIBLE if confirmed else CONDITIONAL,
          "action_state": "READY" if confirmed else "WAIT_FOR_BREAKOUT",
          "mechanics_current": True,
          "entry_zone": [round(resistance, 2), round(resistance + 0.25 * atr, 2)],
          "limit_price": round(resistance, 2), "stop_price": new_stop,
          "targets": [round(resistance + 2 * risk, 2)],
          "risk_per_share": round(risk, 4), "risk_reward": 2.0,
          "risk_reward_source": "DETERMINISTIC_BREAKOUT_BLUEPRINT",
          "trigger": f"closed daily bar above {resistance:.2f}",
          "invalidation": f"close below {new_stop:.2f}",
          "independent_of_pullback_plan": True}
    return {"blueprint": bp}


def build_swing(facts, conn) -> dict:
    """The legacy equity plan, demoted to ONE COMPONENT of the decision rather
    than being the whole product."""
    cur = conn.cursor()
    cur.execute("""SELECT setup_type, entry_zone_low, entry_zone_high, limit_price,
                          stop_price, target_price, risk_reward, urgency, confidence,
                          proposal_tag, plan, created_at, model_used
                   FROM watchlist_entry_plans WHERE upper(symbol)=%s
                   ORDER BY created_at DESC LIMIT 1""", (facts["symbol"],))
    r = cur.fetchone()
    if not r:
        return {"family": "SWING", "state": DATA_UNAVAILABLE, "structures": [],
                "rejection_reasons": ["no entry plan exists for this symbol"]}
    (setup, zlo, zhi, lim, stop, tgt, rr, urg, conf, tag, plan, created, model) = r
    plan = plan if isinstance(plan, dict) else (json.loads(plan) if plan else {})
    mech = {
        "structure": "TACTICAL_SWING", "setup_type": setup,
        "entry_zone": [float(zlo) if zlo else None, float(zhi) if zhi else None],
        "limit_price": float(lim) if lim else None,
        "stop_price": float(stop) if stop else None,
        "targets": [float(tgt)] if tgt else [],
        "risk_per_share": round(float(lim) - float(stop), 4) if lim and stop else None,
        "risk_reward": float(rr) if rr is not None else None,
        "risk_reward_source": "DETERMINISTIC",
        "model_claimed_risk_reward": plan.get("risk_reward_model_claimed"),
        "urgency": str(urg or "").upper(),
        "urgency_source": plan.get("urgency_source"),
        "invalidation": (plan.get("invalidation")
                         or f"close below {stop}" if stop else ""),
        "exit_ladder": (plan.get("exit_ladder") or {}).get("steps", []),
        "proposal_tag": tag, "plan_created_at": str(created), "model_used": model,
    }
    # V6 SAFETY FIX (2026-07-22 afternoon): a MISSED plan becomes NO CURRENT
    # TRADE — it never mutates into a different strategy to keep the card
    # populated. The earlier "correction" auto-converted a stale pullback plan
    # into breakout mechanics at any resistance above price (FATN: $4.75 price
    # rendered a $6.76 "entry") — removed. Breakouts are SEPARATE blueprints
    # built by assess_breakout_blueprint() under strict eligibility; distant
    # levels appear only as non-actionable watch_scenarios.
    price = facts.get("live_price") or facts.get("enriched_price")
    atr = facts.get("atr")
    res_list = facts.get("resistance") or []
    resistance = min(res_list) if res_list else None
    zlo_f = float(zlo) if zlo else None
    zhi_f = float(zhi) if zhi else None
    stop_f = float(stop) if stop else None
    assess = assess_swing_entry(price=price, zone_low=zlo_f, zone_high=zhi_f,
                                stop=stop_f, atr=atr,
                                technical_state=facts.get("technical_state"))
    entry_state = assess["entry_state"]
    state = {"ELIGIBLE": ELIGIBLE, "CONDITIONAL": CONDITIONAL,
             "REJECTED": REJECTED}[assess["family_state"]]
    reasons = assess["reasons"]
    mech["entry_mode"] = "PULLBACK"
    mech["entry_state"] = entry_state
    mech["legacy_plan_urgency"] = str(urg or "").upper()  # audit only, never authority
    mech["state"] = state
    mech["action_state"] = assess["action_state"]
    mech["mechanics_current"] = assess["mechanics_current"]
    mech["trigger"] = assess.get("trigger")
    if not assess["mechanics_current"]:
        # ORIGINAL SETUP — MISSED / NOT CURRENT: prior mechanics move to
        # previous_plan; the current-mechanics surface stays EMPTY.
        mech["previous_plan"] = {
            "entry_zone": mech.get("entry_zone"), "limit_price": mech.get("limit_price"),
            "stop_price": mech.get("stop_price"), "targets": mech.get("targets"),
            "risk_reward": mech.get("risk_reward"), "invalidation": mech.get("invalidation"),
            "plan_created_at": mech.get("plan_created_at"), "label": "MISSED / NOT CURRENT",
        }
        for _k in ("entry_zone", "limit_price", "stop_price", "targets",
                   "risk_per_share", "risk_reward"):
            mech[_k] = None if _k != "targets" and _k != "entry_zone" else []
        mech["invalidation"] = ""
        mech["summary"] = assess.get("summary", "MISSED ENTRY — no current mechanics")
        mech["cta"] = "SET PULLBACK ALERT"
    structures = [mech]
    watch_scenarios = list(assess.get("watch_scenarios") or [])
    # independent BREAKOUT blueprint — never derived from the pullback plan
    bo = assess_breakout_blueprint(symbol=facts["symbol"], price=price, atr=atr,
                                   resistance=resistance, conn=conn,
                                   technical_state=facts.get("technical_state"))
    if bo.get("blueprint"):
        structures.append(bo["blueprint"])
        if bo["blueprint"]["state"] == ELIGIBLE and state != ELIGIBLE:
            state = ELIGIBLE
        elif bo["blueprint"]["state"] == CONDITIONAL and state == REJECTED:
            state = CONDITIONAL
    if bo.get("watch_scenario"):
        watch_scenarios.append(bo["watch_scenario"])
    return {"family": "SWING", "state": state, "structures": structures,
            "watch_scenarios": watch_scenarios,
            "rejection_reasons": reasons}


def build_bearish(facts, event, ownership) -> dict:
    price = facts.get("live_price") or facts.get("enriched_price")
    if not price or not facts.get("atr") or not facts.get("resistance"):
        return {"family": "BEARISH", "state": DATA_UNAVAILABLE, "structures": [],
                "rejection_reasons": ["insufficient levels to define a short entry or buy-stop"]}
    out = tb.short_stock(
        symbol=facts["symbol"], current_price=price, atr=facts["atr"],
        support=facts["support"], resistance=facts["resistance"],
        borrow_state=os.getenv("SHADOW_BORROW_STATE", "UNKNOWN"),
        short_float_pct=float(facts.get("short_float_pct") or 0.0),
        rsi=facts.get("rsi"),
        earnings_date=event.date.isoformat() if event.date else None,
        dte_intent=int(os.getenv("SHADOW_SHORT_DTE_INTENT", "10")),
        held_long=ownership.held)
    state = REJECTED if out.get("state") == "REJECTED" else CONDITIONAL
    return {"family": "BEARISH", "state": state, "structures": [out],
            "rejection_reasons": out.get("rejection_reasons", [])}


def build_options(facts, event, ownership) -> dict:
    """Attempt the governed chain exactly once. Record the exact reason on
    failure — never a substitute price, never silence."""
    sym = facts["symbol"]
    attempt = {"provider": "schwab_transport.get_option_chain", "symbol": sym,
               "attempted_at": _now().isoformat(), "operation": "get_option_chain"}
    try:
        import schwab_transport
        chain = schwab_transport.get_option_chain(sym)
        attempt["status"] = (chain or {}).get("status")
    except Exception as exc:
        attempt.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:200]}")
        return {"family": "OPTIONS", "state": DATA_UNAVAILABLE, "structures": [],
                "chain_attempt": attempt,
                "rejection_reasons": [
                    f"live chain unavailable ({attempt['error']}); option mechanics "
                    f"are not constructible and estimated prices are refused"]}

    if not chain or chain.get("status") != "ok":
        return {"family": "OPTIONS", "state": DATA_UNAVAILABLE, "structures": [],
                "chain_attempt": attempt,
                "rejection_reasons": [
                    f"chain returned status={attempt.get('status')!r}; no contracts to "
                    f"price. Estimated option prices are not an acceptable substitute"]}

    # Event state must be settled before any contract is offered.
    if event.blocks_action:
        return {"family": "OPTIONS", "state": DATA_UNAVAILABLE, "structures": [],
                "chain_attempt": attempt,
                "rejection_reasons": [
                    f"event state {event.state} ({event.reason or 'no detail'}) — option "
                    f"structures cannot be evaluated against an unsettled event date"]}

    # Real chain shape: {expirations: [{exp, dte, strikes: [{strike, side, bid, ask,
    # delta, iv, oi, volume}]}]}. Reading a Schwab-native callExpDateMap key here
    # returned 0 contracts on the first live run — the transport already
    # normalises, so the raw shape is not what arrives.
    exps = chain.get("expirations") or []
    underlying = float(chain.get("underlying_price") or facts.get("live_price") or 0)
    attempt["expirations_seen"] = len(exps)
    attempt["contracts_seen"] = sum(len(e.get("strikes") or []) for e in exps)
    attempt["underlying_price"] = underlying

    def _q(rec):
        return tb.Quote(
            occ_symbol=f"{sym}{str(rec.get('exp','')).replace('-','')[2:]}"
                       f"{'C' if rec.get('side')=='call' else 'P'}"
                       f"{int(round(float(rec.get('strike',0))*1000)):08d}",
            strike=float(rec.get("strike") or 0), bid=float(rec.get("bid") or 0),
            ask=float(rec.get("ask") or 0), delta=rec.get("delta"), iv=rec.get("iv"),
            open_interest=int(rec.get("oi") or 0), volume=int(rec.get("volume") or 0),
            expiration=str(rec.get("exp") or ""), source="chain")

    structures, reasons = [], []
    if not ownership.held:
        structures.append(tb.puts_are_not_a_bullish_entry(sym))
        reasons.append("COVERED_CALL and COLLAR NOT_APPLICABLE — 0 shares held")

    # Nearest expiration with usable records drives the comparison.
    target = next((e for e in exps if (e.get("strikes") or [])), None)
    if not target:
        return {"family": "OPTIONS", "state": DATA_UNAVAILABLE, "structures": structures,
                "chain_attempt": attempt,
                "rejection_reasons": reasons + ["chain returned expirations with no strike records"]}

    exp_date = str(target.get("exp") or "")
    inside = event.inside_contract(exp_date)
    attempt["expiration_evaluated"] = exp_date
    attempt["earnings_inside_contract"] = inside
    calls = sorted([s for s in target["strikes"] if s.get("side") == "call"],
                   key=lambda s: float(s.get("strike") or 0))
    puts = sorted([s for s in target["strikes"] if s.get("side") == "put"],
                  key=lambda s: float(s.get("strike") or 0))

    # LONG_CALL — expected to be refused when earnings sit inside the contract.
    otm_calls = [c for c in calls if float(c.get("strike") or 0) > underlying]
    if otm_calls:
        try:
            structures.append(tb.long_option(
                kind="call", opt=_q(otm_calls[0]), contracts=1, underlying_price=underlying,
                trigger=f"reclaim resistance {min(facts.get('resistance') or [underlying])}",
                invalidation=f"close below {min(facts.get('support') or [0])}",
                earnings_date=event.date.isoformat() if event.date else None,
                directional_setup_confirmed=False))
        except tb.BlueprintRejected as exc:
            structures.append({"structure": "LONG_CALL", "state": REJECTED,
                               "occ_symbol": _q(otm_calls[0]).occ_symbol,
                               "expiration": exp_date,
                               "rejection_reasons": list(exc.reasons)})

    # CALL_DEBIT_SPREAD — defined risk, partially offsets elevated IV.
    if len(otm_calls) >= 2:
        try:
            structures.append(tb.call_debit_spread(
                long_leg=_q(otm_calls[0]), short_leg=_q(otm_calls[1]), contracts=1,
                underlying_price=underlying,
                trigger=f"daily close above {min(facts.get('resistance') or [underlying])} then retest",
                invalidation=f"close below {min(facts.get('support') or [0])}",
                earnings_date=event.date.isoformat() if event.date else None))
        except tb.BlueprintRejected as exc:
            structures.append({"structure": "CALL_DEBIT_SPREAD", "state": REJECTED,
                               "expiration": exp_date,
                               "long_leg": _q(otm_calls[0]).occ_symbol,
                               "short_leg": _q(otm_calls[1]).occ_symbol,
                               "rejection_reasons": list(exc.reasons)})

    # CASH_SECURED_PUT — the bullish put strategy, i.e. acquisition at a discount.
    otm_puts = [p for p in puts if float(p.get("strike") or 0) < underlying]
    if otm_puts:
        best = otm_puts[-1]
        try:
            structures.append(tb.cash_secured_put(
                symbol=sym, put=_q(best), contracts=1, current_price=underlying,
                available_cash=float(os.getenv("SHADOW_AVAILABLE_CASH", "179420")),
                assignment_intent=os.getenv("SHADOW_ASSIGNMENT_INTENT", "UNKNOWN"),
                earnings_date=event.date.isoformat() if event.date else None))
        except tb.BlueprintRejected as exc:
            structures.append({"structure": "CASH_SECURED_PUT", "state": REJECTED,
                               "occ_symbol": _q(best).occ_symbol, "expiration": exp_date,
                               "strike": float(best.get("strike") or 0),
                               "rejection_reasons": list(exc.reasons)})

    # If nothing is eligible or conditional yet, the family cannot legitimately be
    # CONDITIONAL just because structures were REJECTED. But when earnings falls
    # inside the contract and every concrete structure is rejected/NA, the honest
    # actionable answer is an EXPLICIT conditional: re-evaluate after the print,
    # when a post-earnings chain and reset IV can be priced. That is a real
    # CONDITIONAL child, so the roll-up is legitimately CONDITIONAL — not a bare
    # verdict masquerading as conditional.
    have_live = any(s.get("state") in (ELIGIBLE, CONDITIONAL) for s in structures)
    if not have_live and inside and any(s.get("state") == REJECTED for s in structures):
        structures.append({
            "structure": "POST_EARNINGS_REEVALUATION", "state": CONDITIONAL,
            "condition": f"every current structure is rejected AND earnings {event.date} "
                         f"falls inside expiration {exp_date}",
            "event": f"earnings {event.date}",
            "reevaluate_after": event.date.isoformat() if event.date else None,
            "data_required": "post-earnings option chain (reset IV) and a confirmed "
                             "directional setup",
            "why_preferred": "the rejected structures all carry an unpriced earnings event; "
                             "waiting for the post-print chain is preferable to entering "
                             "into the binary now",
            "rejection_reasons": [],
        })

    state = dp.rollup_family_state(structures)
    if inside:
        reasons.append(f"earnings {event.date} falls inside expiration {exp_date} — "
                       f"every structure on this expiry carries the event")
    return {"family": "OPTIONS", "state": state, "structures": structures,
            "chain_attempt": attempt, "rejection_reasons": reasons}


# ── the packet ────────────────────────────────────────────────────────────────

def evaluate(symbol: str, conn=None, *, origin="on_demand", requested_by="operator",
             run_models: bool = True, on_stage=None) -> dict:
    """Build one shadow packet. `on_stage(name)` is invoked as each phase begins
    so the on-demand job runner can report progress the operator polls; it is a
    no-op when not supplied (the CLI/batch path)."""
    def _stage(name):
        if on_stage:
            try:
                on_stage(name)
            except TimeoutError:
                # An SLA breach MUST abort the evaluation. A first version
                # swallowed every exception here "so progress reporting never
                # fails the eval" — which also swallowed the timeout, so a run
                # with a 1s SLA still ran to COMPLETE. Progress-write failures
                # stay swallowed below; the deadline does not.
                raise
            except Exception:
                pass          # a failed progress write must never fail the eval

    sym = str(symbol).upper()
    if conn is None:
        from db_adapter import _get_conn
        conn = _get_conn()

    _stage("facts")
    facts = gather_facts(sym, conn)
    _stage("events")
    event = ev.resolve_from_db(sym, conn)

    holdings_path = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
    holdings = json.loads(holdings_path.read_text()) if holdings_path.exists() else {}
    ownership = pt.ownership_from_holdings(sym, holdings)

    dq = assess_data_quality(facts, event)

    # Legacy label is carried for comparison ONLY and explicitly demoted.
    cur = conn.cursor()
    cur.execute("""SELECT recommendation, confidence, updated_at
                   FROM watchlist_final_synthesis WHERE upper(symbol)=%s""", (sym,))
    r = cur.fetchone()
    legacy = {"recommendation": r[0] if r else None,
              "confidence": float(r[1]) if r and r[1] is not None else None,
              "generated_at": str(r[2]) if r else None,
              "note": "LEGACY SUMMARY — NOT THE DECISION SOURCE OF TRUTH"}

    # ── BLIND MODEL PASS (Stage B) ────────────────────────────────────────────
    # The models see the facts and NO verdict from anyone — not the legacy
    # IGNORE, not each other. run_blind_pass re-checks blindness immediately
    # before each call. A lane that fails is not a lane; one completed lane is
    # SINGLE_LANE, never a consensus. Disabled (env or --no-models) falls back to
    # the deterministic placeholders rather than fabricating agreement.
    model_review = {"mode": "UNAVAILABLE", "lanes_requested": [], "lanes_completed": [],
                    "agreement_by_dimension": {}, "minority_views": [],
                    "unresolved": ["blind pass not run"], "reconciled": None}
    reconciled = None
    if run_models and os.getenv("SHADOW_DISABLE_MODELS", "").lower() not in ("1", "true", "yes"):
        _stage("blind_review")
        try:
            import blind_review as br
            import blind_review_runner as brr
            blind_facts = br.build_facts_packet(
                symbol=sym,
                price={"current": facts.get("live_price"),
                       "enriched": facts.get("enriched_price"),
                       "as_of": facts.get("live_price_as_of"),
                       "change_pct": facts.get("change_pct")},
                technicals={"rsi": facts.get("rsi"), "atr": facts.get("atr"),
                            "support": facts.get("support"), "resistance": facts.get("resistance"),
                            "sma50": facts.get("sma50"), "rvol": facts.get("rvol"),
                            "float_m": facts.get("float_m"),
                            "hermes_rank": facts.get("hermes_rank")},
                fundamentals={"sector": facts.get("sector"), "industry": facts.get("industry"),
                              **(facts.get("fundamentals") or {})},
                # Strip our internal per-catalyst `confidence` — it is data
                # provenance (how sure we are the catalyst is real), but the
                # blindness guard rightly refuses any key named "confidence"
                # because a VERDICT confidence would anchor. The model gets the
                # headline, type and date as evidence, which is all it should see.
                catalysts=[{k: v for k, v in (c or {}).items() if k != "confidence"}
                           for c in (facts.get("catalysts") or [])],
                events={"earnings_state": event.state,
                        "earnings_date": event.date.isoformat() if event.date else None},
                ownership=ownership.to_dict(),
                options_summary=None,
                data_quality=dq)
            mr = brr.run_blind_pass(blind_facts)
            mr.pop("_completed_outputs", None)   # not persisted raw
            reconciled = mr.get("reconciled")
            model_review = mr
        except Exception as exc:
            model_review["unresolved"] = [f"blind pass error: {type(exc).__name__}: {str(exc)[:160]}"]

    # The blind pass runs 30-120s per lane. An idle DB connection gets killed
    # server-side during that window ("SSL connection has been closed
    # unexpectedly") — the same hazard the planner's _live() guards. Rebuild the
    # connection before any further DB read (build_swing, persist) rather than
    # letting the next execute() raise.
    try:
        conn.cursor().execute("SELECT 1")
    except Exception:
        from db_adapter import _get_conn, close_thread_conn
        try:
            close_thread_conn()
        except Exception:
            pass
        conn = _get_conn()

    # Dimensions. Deterministic FALLBACK from facts; overridden by the reconciled
    # model view when the blind pass produced one. Eligibility stays deterministic
    # either way — the model only supplies thesis/direction/timing, never a
    # family state or a payoff number.
    rsi = facts.get("rsi") or 50.0
    chg = facts.get("change_pct") or 0.0
    price = facts.get("live_price") or facts.get("enriched_price") or 0
    res = min(facts.get("resistance") or [price * 1.05])
    extended = bool(price and res and price >= res * 0.98) or chg >= 5.0
    timing = "EXTENDED" if extended else "RANGE_BOUND" if 40 <= rsi <= 60 else "NO_VALID_SETUP"
    # V5: the deterministic thesis ENGINE (factor-based, instrument-aware, raw
    # whitelisted evidence only) replaces the old bare INSUFFICIENT_EVIDENCE
    # fallback — LOCAL_QUANT packets get a real explainable thesis. Always
    # computed and stored for audit; a reconciled model view still overrides
    # the headline thesis_state when the blind pass ran.
    try:
        import deterministic_thesis as dth
        det_thesis = dth.evaluate(facts, facts.get("instrument_type"))
    except Exception as _dte:
        det_thesis = {"engine": "deterministic_thesis", "error": str(_dte)[:120],
                      "thesis_state": "INSUFFICIENT_EVIDENCE"}
    thesis_state = det_thesis.get("thesis_state") or "INSUFFICIENT_EVIDENCE"
    if reconciled:
        thesis_state = reconciled.get("thesis_state") or thesis_state
        if reconciled.get("tactical_timing") not in (None, "", "NO_VALID_SETUP"):
            timing = reconciled["tactical_timing"]

    # V5 Section 17.12: canonical multi-timeframe technical snapshot in every
    # packet (daily+weekly; deterministic, LLM-free; bars cached in
    # market_ohlcv_bars so batch rebuilds don't refetch). Fail-soft: a technical
    # outage never blocks the packet — it shows as UNAVAILABLE, not silence.
    _stage("technicals_mtf")
    try:
        import technical_intelligence as ti
        import watch_decision_refresh as _wdrp
        # Timeframe selection follows refresh-policy priority (V6 item 5): active
        # tactical names (P0/P1) get intraday context; the rest get the
        # long-term set. Never claimed unless bars actually exist (per-TF meta).
        _prio_tf = _wdrp.classify_priority(sym, conn)
        _tfs = (("15m", "1h", "daily", "weekly") if _prio_tf in ("P0", "P1")
                else ("daily", "weekly", "monthly"))
        technical_state = ti.analyze_technicals(sym, _tfs, conn)
        facts["technical_state"] = technical_state  # family builders may consume
    except Exception as _te:
        technical_state = {"schema_version": "unavailable", "overall_freshness": "FAILED",
                          "overall_direction": "UNRESOLVED", "error": str(_te)[:160]}

    # V6 item 6/7: technical evidence REFINES deterministic tactical timing when
    # the snapshot is CURRENT and no model reconciliation overrode it. Guards:
    # stale/failed technicals never contribute; EVENT_BLOCKED and every
    # eligibility/risk gate live downstream and are untouched — technicals can
    # move timing between WAIT/EXTENDED/etc. states but never grant READY
    # (action policy does not read technical_state; test-enforced).
    if (not reconciled) and technical_state.get("overall_freshness") in ("CURRENT", "PARTIAL"):
        _daily = (technical_state.get("timeframes") or {}).get("daily") or {}
        if (_daily.get("meta") or {}).get("freshness_state") == "CURRENT":
            _mc = (_daily.get("momentum_context") or {}).get("state", "")
            _pp = technical_state.get("primary_pattern") or {}
            _vol_sig = ((_daily.get("indicators") or {}).get("volume_roc") or {}).get("signal")
            _conf_state = str((_daily.get("confluence") or {}).get("state", ""))
            if _pp.get("direction") == "BULLISH" and _pp.get("state") == "AWAITING_CONFIRMATION":
                timing = "WAIT_FOR_BREAKOUT"
            elif _pp.get("direction") == "BULLISH" and _pp.get("state") == "CONFIRMED" \
                    and _vol_sig == "BULLISH" and timing != "EXTENDED":
                timing = "BREAKOUT_CONFIRMATION"
            elif _mc == "OVERBOUGHT_STRONG_TREND" or _mc == "OVERBOUGHT_EXHAUSTING":
                timing = "EXTENDED"
            elif _mc == "OVERSOLD_RECOVERY":
                timing = "REVERSAL_WATCH"
            elif _mc == "OVERSOLD_CONTINUING_DOWN":
                timing = "NO_VALID_SETUP"
            elif _conf_state == "MIXED" and timing == "NO_VALID_SETUP":
                timing = "RANGE_BOUND"

    _stage("long_term")
    lt = build_long_term(facts, event, ownership, thesis_state, timing)
    _stage("swing")
    sw = build_swing(facts, conn)
    _stage("bearish")
    be = build_bearish(facts, event, ownership)
    _stage("options")
    op = build_options(facts, event, ownership)

    packet = {
        "packet_version": PACKET_VERSION, "symbol": sym,
        "instrument_type": "STOCK",
        "deterministic_thesis": det_thesis,
        "technical_state": technical_state,
        "evaluated_at": _now().isoformat(),
        "facts_as_of": facts.get("live_price_as_of") or facts.get("enriched_at"),
        "price_used": facts.get("live_price") or facts.get("enriched_price"),
        "current_price": facts.get("live_price"),
        "price_drift_pct": dq.get("price_drift_pct"),
        "source_commit_sha": _sha(),
        # Fundamentals recency, carried so packet invalidation can tell when a
        # thesis rests on newer/older fundamentals than the packet was built on.
        "fundamentals_as_of": (facts.get("fundamentals") or {}).get("fundamentals_as_of"),
        "ownership": ownership.to_dict(),
        "horizons": {
            "tactical": {
                "direction": (reconciled or {}).get("direction", {}).get("tactical", "UNRESOLVED"),
                "timing": timing,
                "confidence": (reconciled or {}).get("thesis_confidence", 0.0),
                "thesis": ("reconciled from blind model pass" if reconciled
                           else "deterministic fallback — no model lane completed"),
                "trigger": f"reclaim/hold vs resistance {res}",
                "invalidation": f"close below {min(facts.get('support') or [0])}"},
            "swing": {
                "direction": (reconciled or {}).get("direction", {}).get("swing", "UNRESOLVED"),
                "timing": timing,
                "confidence": (reconciled or {}).get("timing_agreement", 0.0),
                "thesis": ("reconciled from blind model pass" if reconciled
                           else "deterministic fallback"),
                "trigger": f"break and retest of {res}",
                "invalidation": f"close below {min(facts.get('support') or [0])}"},
            "long_term": {
                "thesis_state": thesis_state,
                "direction": (reconciled or {}).get("direction", {}).get("long_term", "UNRESOLVED"),
                "confidence": (reconciled or {}).get("thesis_confidence", 0.0),
                "thesis": ("reconciled from blind model pass" if reconciled
                           else "no model lane completed — thesis unresolved"),
                "invalidation": "thesis review pending",
                "what_changes_view": []},
        },
        "event_state": {"impact": ("CAUTION" if event.state == ev.SCHEDULED
                                   else "UNKNOWN" if event.blocks_action else "CLEAR"),
                        "earnings": event.to_dict()},
        "data_quality": dq,
        "model_review": model_review,
        "plan_families": {"long_term": lt, "swing": sw, "bearish": be, "options": op,
                          "no_trade": {"family": "NO_TRADE", "available": True,
                                       "preferred": False, "dominant": False,
                                       "state": "NOT_APPLICABLE",
                                       "rationale": "placeholder — reconcile_plan_families fills"}},
        "no_trade_is_valid": True,
        "legacy_summary": legacy,
        "preferred_action": {"structure": "NO_TRADE",
                             "why": "Stage A is shadow-only; no preferred action is "
                                    "published from this path"},
    }
    # Semantic integration layer: three-axis family states, thesis/event/options/
    # no-trade invariants. Must run BEFORE validate so invariants are held at persist.
    packet = dp.reconcile_plan_families(packet)
    # Persist the CURRENT-INPUT snapshot the packet was built on, so a later run
    # can tell whether the packet still matches source truth (not just whether it
    # is young). One canonical builder — the same one the batch and action policy
    # use — so the comparison is apples-to-apples.
    try:
        import packet_invalidation as _inv
        packet["input_snapshot"] = _inv.build_current_input_snapshot(
            sym, conn, source_commit_sha=packet.get("source_commit_sha") or "")
        packet["input_hash"] = packet["input_snapshot"]["input_hash"]
        packet["action_policy_version"] = _inv.POLICY_VERSION
    except Exception as _ie:
        packet["input_snapshot"] = None
        packet["input_hash"] = None

    # ── MANDATORY DETERMINISTIC TICKET GATE (cannot be disabled) ─────────────
    # Runs AFTER construction, BEFORE the ticket can become current/actionable.
    # A hard failure strips current mechanics into audit (validation_rejected),
    # forces the family to REJECTED, and can never be overridden by any model.
    _stage("ticket_validation")
    import strategy_ticket_validator as stv
    _tickets_validated = []
    for _famname, _famobj in (("SWING", sw), ("BEARISH", be), ("LONG_TERM", lt)):
        for _st in (_famobj or {}).get("structures") or []:
            if not isinstance(_st, dict) or not _st.get("mechanics_current", True):
                continue
            if not any(_st.get(k) is not None for k in ("limit_price", "stop_price")):
                continue
            _vres = stv.validate_ticket(sym, _famname, _st, facts,
                                        technical_snapshot=technical_state,
                                        event_state=getattr(event, "state", None),
                                        ownership=ownership)
            _st["ticket_validation"] = _vres
            _tickets_validated.append({"family": _famname,
                                       "structure": _st.get("structure"),
                                       "state": _vres["state"],
                                       "ticket_hash": _vres["ticket_hash"],
                                       "hard_failures": _vres["hard_failures"]})
            if _vres["state"] == "FAIL":
                _st["validation_rejected"] = {
                    "mechanics": {k: _st.get(k) for k in
                                  ("entry_zone", "limit_price", "stop_price",
                                   "targets", "risk_reward")},
                    "hard_failures": _vres["hard_failures"]}
                for _k in ("limit_price", "stop_price", "risk_per_share", "risk_reward"):
                    _st[_k] = None
                _st["targets"], _st["entry_zone"] = [], []
                _st["mechanics_current"] = False
                _st["state"] = REJECTED
                _st["action_state"] = "WAIT_FOR_PULLBACK"
                _famobj["state"] = REJECTED if _famobj.get("state") == ELIGIBLE else _famobj.get("state")
                _famobj.setdefault("rejection_reasons", []).extend(
                    [f"ticket validator: {h}" for h in _vres["hard_failures"][:2]])

    # V6 item 6 — hard separation: current_actionable_plan / watch_scenarios /
    # previous_plan. watch_scenarios NEVER feed proposal mechanics (they carry
    # no limit/stop/target); a MISSED plan leaves current_actionable_plan None.
    _sw_structs = (sw or {}).get("structures") or []
    packet["current_actionable_plan"] = next(
        (s for s in _sw_structs if s.get("mechanics_current")
         and s.get("state") in (ELIGIBLE, CONDITIONAL)), None)
    packet["watch_scenarios"] = (sw or {}).get("watch_scenarios") or []
    packet["previous_plan"] = next(
        (s.get("previous_plan") for s in _sw_structs if s.get("previous_plan")), None)

    # ── TICKET REVIEW LAYER (critics + reconciliation) ───────────────────────
    # Local critic runs inline ONLY when an actionable ticket exists (most
    # packets have none → zero model cost). OAuth critics run on demand /
    # per proposal policy via the API. Deterministic FAIL is never overridable.
    _stage("ticket_review")
    _cap = packet.get("current_actionable_plan")
    _tv = (_cap or {}).get("ticket_validation") or (
        _tickets_validated[0] if _tickets_validated else {"state": "PASS"})
    _reviews = {}
    # The local critic is LOCAL oversight, not a thesis lane — it runs whenever
    # an actionable ticket exists, in every tier (including LOCAL_QUANT).
    if _cap and str(_tv.get("state")) != "FAIL" and not os.getenv("SHADOW_DISABLE_TICKET_CRITIC"):
        try:
            import strategy_ticket_review as strv
            _reviews["local"] = strv.run_local_critic(sym, _cap, facts,
                                                      (_cap or {}).get("ticket_validation") or {})
        except Exception as _re:
            _reviews["local"] = {"review_type": "LOCAL_CRITIC",
                                 "verdict": "UNAVAILABLE", "error": str(_re)[:120]}
    try:
        import strategy_ticket_reconciler as strec
        _reconciled = strec.reconcile((_cap or {}).get("ticket_validation") or {"state": "PASS"},
                                      _reviews)
    except Exception as _rce:
        _reconciled = {"state": "REVIEW_UNAVAILABLE", "proposal_allowed": False,
                       "error": str(_rce)[:120]}
    packet["ticket_review"] = {"tickets_validated": _tickets_validated,
                               "reviews": _reviews, "reconciled": _reconciled}

    # ── V6 canonical contracts (2026-07-22): the card reads these EXACT fields —
    # freshness is generated server-side from the refresh policy, never in React.
    packet["current_input_snapshot"] = packet.get("input_snapshot")  # canonical alias
    _now_iso = _now().isoformat()
    _mr_mode = str((packet.get("model_review") or {}).get("mode") or "UNAVAILABLE")
    # analysis_tier is EXPLICIT: LOCAL_QUANT is a real deterministic analysis, not
    # an unavailable one. UNAVAILABLE stays reserved for actual failures.
    if _mr_mode in ("BLIND", "SINGLE_LANE"):
        packet["analysis_tier"] = "STANDARD_BLIND"
    elif _mr_mode == "PREMIUM":
        packet["analysis_tier"] = "PREMIUM_REVIEW"
    else:
        packet["analysis_tier"] = "LOCAL_QUANT"
    try:
        import watch_decision_refresh as _wdr
        import packet_invalidation as _pinv
        _ttl_h = _pinv.effective_ttl_hours()
        _prio = _wdr.classify_priority(sym, conn)
        _pol = _wdr.load_policy()
        _cad_min = ((_pol.get("tiers") or {}).get(_prio) or {}).get("full_local_packet_max_minutes")
        from datetime import timedelta as _td
        _built = _now()
        _snap_ts = []
        for _sec in (packet.get("input_snapshot") or {}).values():
            if isinstance(_sec, dict):
                _snap_ts += [str(v) for k, v in _sec.items()
                             if v and (k.endswith("_as_of") or k in ("as_of", "fetched_at"))]
        packet["freshness"] = {
            "overall_state": "CURRENT",
            "last_input_refresh_at": max(_snap_ts) if _snap_ts else _now_iso,
            "last_strategy_build_at": _now_iso,
            "last_local_quant_at": _now_iso,
            "last_standard_blind_at": _now_iso if packet["analysis_tier"] == "STANDARD_BLIND" else None,
            "last_premium_review_at": None,
            "valid_until": (_built + _td(hours=_ttl_h)).isoformat(),
            "next_refresh_due_at": (_built + _td(minutes=int(_cad_min))).isoformat()
            if _cad_min else (_built + _td(hours=_ttl_h)).isoformat(),
            "invalidated_at": None,
            "invalidation_reasons": [],
            "policy_version": _wdr.policy_version(),
            "priority_tier": _prio,
        }
    except Exception as _fe:
        packet["freshness"] = {"overall_state": "CURRENT",
                               "last_strategy_build_at": _now_iso,
                               "error": str(_fe)[:120]}

    packet["headline"] = dp.compose_headline(packet)
    packet["validation_errors"] = dp.validate(packet)
    return packet


# ── persistence ───────────────────────────────────────────────────────────────

def persist(packet: dict, conn=None, *, origin="on_demand", requested_by="operator",
            run_id: int = None) -> int:
    """Persist a packet + its blueprints. When called from the job worker the
    run already exists — pass its run_id so the packet links to THAT run instead
    of minting an orphan. A first version always INSERTed a new decision_run, so
    every on-demand run produced two rows: the worker's (with stages) and this
    stageless duplicate the packet then pointed at. The CLI/batch path (no
    existing run) still gets a fresh COMPLETE run created here."""
    if conn is None:
        from db_adapter import _get_conn
        conn = _get_conn()

    # ATOMICITY GUARD (Part E): a broken packet must never supersede a good one.
    # Refuse to persist unless every required family is present and the packet has
    # no fatal validation errors. On refusal the caller keeps the prior live packet
    # (stale but valid) rather than being left with nothing.
    fam = packet.get("plan_families") or {}
    _required = ("long_term", "swing", "bearish", "options", "no_trade")
    _missing = [f for f in _required if not (fam.get(f) or {}).get("state")]
    if _missing:
        raise ValueError(f"refusing to persist {packet.get('symbol')}: missing families {_missing}")
    if packet.get("validation_errors"):
        raise ValueError(f"refusing to persist {packet.get('symbol')}: "
                         f"{len(packet['validation_errors'])} validation error(s): "
                         f"{packet['validation_errors'][:2]}")

    cur = conn.cursor()
    if run_id is None:
        cur.execute("""INSERT INTO decision_runs (origin, requested_by, started_at,
                         completed_at, state, symbols_requested, symbols_completed,
                         source_commit_sha)
                       VALUES (%s,%s,now(),now(),'COMPLETE',1,1,%s) RETURNING run_id""",
                    (origin, requested_by, packet.get("source_commit_sha")))
        run_id = cur.fetchone()[0]

    fam = packet["plan_families"]
    cur.execute("""INSERT INTO decision_packets
                    (run_id, symbol, packet_version, facts_as_of, price_used,
                     current_price, price_drift_pct, instrument_type, thesis_state,
                     swing_timing, tactical_timing, event_state, data_quality, actionable,
                     family_long_term, family_swing, family_bearish, family_options,
                     no_trade_valid, model_review_mode, lanes_requested, lanes_completed,
                     packet, source_commit_sha)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                   RETURNING packet_id""",
                (run_id, packet["symbol"], packet["packet_version"],
                 packet.get("facts_as_of") or None, packet.get("price_used"),
                 packet.get("current_price"), packet.get("price_drift_pct"),
                 packet.get("instrument_type"),
                 packet["horizons"]["long_term"]["thesis_state"],
                 packet["horizons"]["swing"]["timing"],
                 packet["horizons"]["tactical"]["timing"],
                 packet["event_state"]["earnings"]["state"],
                 packet["data_quality"]["state"],
                 bool(packet["data_quality"].get("actionable")),
                 fam["long_term"]["state"], fam["swing"]["state"],
                 fam["bearish"]["state"], fam["options"]["state"],
                 packet["no_trade_is_valid"], packet["model_review"]["mode"],
                 len(packet["model_review"]["lanes_requested"]),
                 len(packet["model_review"]["lanes_completed"]),
                 json.dumps(packet, default=str), packet.get("source_commit_sha")))
    packet_id = cur.fetchone()[0]

    # Supersede any prior live packet — append-only, never updated in place.
    cur.execute("""UPDATE decision_packets SET superseded_by=%s, superseded_at=now()
                   WHERE upper(symbol)=%s AND packet_id <> %s AND superseded_by IS NULL""",
                (packet_id, packet["symbol"], packet_id))

    for key, family in fam.items():
        for s in (family.get("structures") or [{"structure": family.get("family"),
                                                "state": family.get("state")}]):
            cur.execute("""INSERT INTO decision_blueprints
                            (packet_id, symbol, family, structure, state, mechanics,
                             rejection_reasons, quote_source, event_state, eligibility)
                           VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s)""",
                        (packet_id, packet["symbol"], family.get("family", key.upper()),
                         s.get("structure") or key.upper(),
                         s.get("state") or family.get("state"),
                         json.dumps(s, default=str),
                         json.dumps(s.get("rejection_reasons")
                                    or family.get("rejection_reasons") or [], default=str),
                         (family.get("chain_attempt") or {}).get("provider"),
                         packet["event_state"]["earnings"]["state"],
                         family.get("state")))
    # Single transaction: the new packet, its supersession of the old, and all
    # blueprints commit together or not at all — so a mid-write failure leaves the
    # prior packet live and unsuperseded rather than the symbol with nothing.
    try:
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return packet_id


def readback(symbol: str, conn=None) -> dict:
    if conn is None:
        from db_adapter import _get_conn
        conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""SELECT packet_id, generated_at, packet FROM decision_packets
                   WHERE upper(symbol)=%s AND superseded_by IS NULL
                   ORDER BY generated_at DESC LIMIT 1""", (symbol.upper(),))
    r = cur.fetchone()
    if not r:
        return {"ok": False, "error": f"no live shadow packet for {symbol.upper()}"}
    pkt = r[2] if isinstance(r[2], dict) else json.loads(r[2])
    # Root egress gate: every read path materializes three-axis semantics so
    # stored pre-axis packets cannot contradict thesis/event/options/no-trade.
    pkt = dp.materialize_packet(pkt)
    cur.execute("""SELECT family, structure, state, rejection_reasons
                   FROM decision_blueprints WHERE packet_id=%s ORDER BY family""", (r[0],))
    return {"ok": True, "packet_id": r[0], "generated_at": str(r[1]), "packet": pkt,
            "blueprints": [{"family": a, "structure": b, "state": c,
                            "rejection_reasons": d} for a, b, c, d in cur.fetchall()]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Shadow multidimensional decision service (Stage A)")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--readback", action="store_true", help="read the persisted packet only")
    ap.add_argument("--no-models", action="store_true",
                    help="skip the blind model pass (deterministic dimensions only)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.readback:
        out = readback(args.symbol)
    else:
        pkt = evaluate(args.symbol, run_models=not args.no_models)
        pid = persist(pkt)
        out = readback(args.symbol)
        out["persisted_packet_id"] = pid

    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0

    if not out.get("ok"):
        print(out.get("error"))
        return 1
    p = out["packet"]
    print(f"SHADOW PACKET {out['packet_id']} · {p['symbol']} · {out['generated_at']}")
    print(f"  headline      : {p.get('headline')}")
    print(f"  price used    : {p.get('price_used')}  (drift {p.get('price_drift_pct')})")
    e = p["event_state"]["earnings"]
    print(f"  EVENT         : {e['state']} {e.get('date') or ''} · {e.get('source')}")
    print(f"  DATA QUALITY  : {p['data_quality']['state']}")
    mr = p['model_review']
    print(f"  MODEL REVIEW  : {mr['mode']} "
          f"({len(mr.get('lanes_completed') or [])} of {len(mr.get('lanes_requested') or [])} lanes: "
          f"{', '.join(mr.get('lanes_completed') or []) or 'none'})")
    if mr.get("agreement_by_dimension"):
        print("    agreement   : " + " · ".join(
            f"{d}={v}" for d, v in mr["agreement_by_dimension"].items()))
    for _mv in (mr.get("minority_views") or [])[:4]:
        print(f"    minority    : {_mv['dimension']}={_mv['view']} ({', '.join(_mv['lanes'])})")
    if mr.get("reconciled"):
        _rc = mr["reconciled"]
        print(f"    reconciled  : thesis={_rc.get('thesis_state')} "
              f"timing={_rc.get('tactical_timing')} instrument={_rc.get('preferred_instrument')}")
    print(f"  OWNERSHIP     : held={p['ownership']['held']} shares={p['ownership']['shares']}")
    print("  FAMILIES:")
    for f in REQUIRED_FAMILIES:
        key = f.lower()
        fam = p["plan_families"].get(key, {})
        print(f"    {f:11s} {fam.get('state'):18s}", end="")
        rr = fam.get("rejection_reasons") or []
        print(f" {rr[0][:70] if rr else ''}")
    print(f"  legacy label  : {p['legacy_summary']['recommendation']} "
          f"({p['legacy_summary']['note']})")
    if p.get("validation_errors"):
        print(f"  VALIDATION    : {len(p['validation_errors'])} issue(s)")
        for v in p["validation_errors"][:5]:
            print(f"     - {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
