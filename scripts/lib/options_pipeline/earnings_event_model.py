"""earnings_event_model.py — earnings event context JSON (EARNINGS-SPREADS Stage 1, spec Part B).

Builds the per-symbol event_json the earnings vertical-spread lanes
(config/options_strategy_registry.yaml: earnings_put_debit_spread /
earnings_put_credit_spread) will consume in Stage 2:

    build_event_json("RTX") → {
        days_to_earnings, earnings_date {date, source},
        nearest_expiration_after_earnings {exp, dte} | degrade,
        implied_move_pct {pct, method atm_straddle_mid|otm_strangle_fallback,
                          expiration, legs} | degrade,
        historical_earnings_moves {avg_abs_move_pct, max_abs_move_pct,
                                   samples, per_event} | degrade,
        iv_context (iv_history.iv_rank reuse) | degrade,
        post_earnings_iv_crush_estimate {estimate_pct, LABELED estimate} | degrade,
        event_thesis bullish|bearish|neutral|unknown (+ source),
        event_confidence 0-1 (+ documented components),
        risk_flags [iv_rich, thin_history, wide_quotes, event_stale, ...],
    }

Data sources (ALL read-only, one SQL statement per call, lazy imports):
  * earnings date — symbol_profiles.next_earnings_date (primary; maintained by
    scripts/earnings_enrich.py), data/portfolios/state/earnings_dates.json
    (fallback snapshot; earnings_date_enrichment.py).
  * historical earnings dates — this deployment stores only ONE past report
    date (symbol_profiles.last_earnings_date; earnings_enrich.py persists the
    single most recent past row). There is NO multi-quarter earnings-dates
    table, so historical moves honestly carry at most samples=1 and always the
    thin_history flag; with no past date at all the block degrades to
    {"available": False, "reason": "no historical earnings dates source ..."}.
    NEVER fabricated.
  * price bars — price_cache daily closes (symbol, price_date, close_price).
    Earnings report timing (BMO/AMC) is not stored, so a past-event move is
    the LARGER of the two close-to-close moves straddling the report date
    (disclosed via method) — an upper-bound-honest approximation.
  * option chain — options_chain.fetch_chain_snapshot (the AST-proven
    read-only Schwab chain path) unless a snapshot is injected.
  * IV rank / crush proxy — strategy_research.iv_history (options_iv_history
    daily ATM-IV series; honest {"available": False} under MIN_HISTORY_DAYS).
  * thesis — the SAME watchlist verdict resolution the strategy matcher uses
    (lib.options_pipeline.strategy_matcher.resolve_context: research card →
    CIO synthesis → holdings.json), mapped onto the event-thesis vocabulary.

event_confidence formula (documented, unit-tested for bounds):

    confidence = clamp01(0.45 * thesis_strength
                         + 0.35 * data_completeness
                         + 0.20 * event_proximity)

    thesis_strength   strong_buy/strong_sell → 1.0; other actionable verdicts
                      (buy, sell, avoid, deteriorating, reduce) → 0.8;
                      explicit caller thesis_direction → 0.7;
                      hold/neutral → 0.5; unknown → 0.0
    data_completeness available_count / 5 over {earnings_date, chain snapshot,
                      implied_move_pct, historical_earnings_moves, iv_context}
    event_proximity   1.0 inside the event window
                      (−window_after ≤ days_to_earnings ≤ window_before);
                      0.6 within 2× window_before; 0.25 farther out;
                      0.0 when the date is unknown or already past the window

HONEST DEGRADATION (HARD RULE): every missing input degrades into event_json
with an explicit {"available": False, "reason": ...} — numbers are never
guessed. ADVISORY/EDUCATIONAL ONLY: this module writes nothing and imports no
broker/submit/order/2FA surface (AST test-enforced by
tests/test_options_earnings_event_model.py).

CLI sanity (from the scripts/ directory, primary .env):
    .venv/bin/python -m lib.options_pipeline.earnings_event_model RTX
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

EDUCATIONAL_BANNER = (
    "EDUCATIONAL_ONLY — earnings event research context. Not investment "
    "advice, not a recommendation, and NOT an order: this module has no "
    "order, submit, or execution surface.")

# ── policy defaults (overridable via the registry row's `selection` block) ───
DEFAULT_CONFIG: Dict[str, Any] = {
    "earnings_window_days_before": 10,
    "earnings_window_days_after": 2,
}

WIDE_QUOTE_SPREAD_PCT = 10.0     # leg spread% above this → wide_quotes flag
IV_RICH_RANK = 70.0              # iv_rank above this → iv_rich flag
THIN_HISTORY_MIN_SAMPLES = 4     # fewer past-event moves than this → thin_history
_PRICE_WINDOW_DAYS = 7           # calendar days of closes pulled around a past event

# Confidence formula weights (documented in the module docstring).
W_THESIS, W_COMPLETENESS, W_PROXIMITY = 0.45, 0.35, 0.20

EARNINGS_SOURCE_DB = "symbol_profiles.next_earnings_date"
EARNINGS_SOURCE_JSON = "data/portfolios/state/earnings_dates.json"
PAST_EARNINGS_SOURCE = "symbol_profiles.last_earnings_date (single most recent report only)"
PRICE_SOURCE = "price_cache daily closes"

STRONG_VERDICTS = frozenset({"strong_buy", "strong_sell"})
NEUTRAL_VERDICTS = frozenset({"hold", "neutral"})


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x  # NaN guard


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _iso_date(v: Any) -> Optional[str]:
    if not v:
        return None
    s = str(v)[:10]
    try:
        date.fromisoformat(s)
    except ValueError:
        return None
    return s


def _today() -> date:
    return datetime.now(timezone.utc).date()


# ── earnings date (read-only; DB primary, state-json fallback) ───────────────

def _db_next_earnings(symbol: str) -> Optional[str]:
    """symbol_profiles.next_earnings_date — one read-only statement; None on any failure."""
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return None
        row = _execute(
            "SELECT next_earnings_date FROM symbol_profiles WHERE upper(symbol) = %s",
            ((symbol or "").upper(),), fetch="one")
        return _iso_date(dict(row).get("next_earnings_date")) if row else None
    except Exception:
        return None


def _json_next_earnings(symbol: str) -> Optional[str]:
    """earnings_dates.json snapshot fallback ({SYM: {earnings_date}}); None on any failure."""
    try:
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent.parent.parent
        raw = json.loads((root / "data" / "portfolios" / "state" /
                          "earnings_dates.json").read_text(encoding="utf-8"))
        entry = raw.get((symbol or "").upper()) or {}
        return _iso_date(entry.get("earnings_date"))
    except Exception:
        return None


def resolve_earnings_date(symbol: str,
                          earnings_date: Optional[str] = None) -> Dict[str, Any]:
    """{date, source} or {date: None, source: None, reason}. Caller value wins."""
    if earnings_date is not None:
        d = _iso_date(earnings_date)
        if d:
            return {"date": d, "source": "caller_supplied"}
        return {"date": None, "source": None,
                "reason": f"caller-supplied earnings date unparsable: {earnings_date!r}"}
    d = _db_next_earnings(symbol)
    if d:
        return {"date": d, "source": EARNINGS_SOURCE_DB}
    d = _json_next_earnings(symbol)
    if d:
        return {"date": d, "source": EARNINGS_SOURCE_JSON}
    return {"date": None, "source": None,
            "reason": "no earnings date in symbol_profiles or earnings_dates.json"}


# ── chain-derived pieces: expiration after event + implied move ──────────────

def nearest_expiration_after(snapshot: Optional[dict],
                             earnings_date: Optional[str]) -> Dict[str, Any]:
    """First listed expiration ON/after the earnings date (the event expiry)."""
    if not earnings_date:
        return {"available": False, "reason": "earnings date unknown"}
    if not isinstance(snapshot, dict) or not snapshot.get("available"):
        return {"available": False,
                "reason": (snapshot or {}).get("reason") or "chain snapshot unavailable"}
    after = [e for e in snapshot.get("expirations") or []
             if _iso_date(e.get("exp")) and str(e["exp"])[:10] >= earnings_date]
    if not after:
        return {"available": False,
                "reason": "no listed expiration on/after the earnings date"}
    best = min(after, key=lambda e: str(e["exp"])[:10])
    return {"available": True, "exp": str(best["exp"])[:10],
            "dte": int(_f(best.get("dte")) or 0)}


def _usable_quote(c: dict) -> bool:
    """A leg quote is usable only with a real two-sided market (bid>0, ask>=bid)."""
    b, a = _f(c.get("bid")), _f(c.get("ask"))
    return bool(b and a and b > 0 and a >= b and c.get("mid"))


def implied_move_from_snapshot(snapshot: Optional[dict],
                               event_exp: Dict[str, Any]) -> Dict[str, Any]:
    """Implied event move: ATM straddle mid ÷ spot (OTM-strangle fallback).

    Uses the event expiration only. Straddle = call+put at the strike nearest
    spot where BOTH legs have usable two-sided quotes. Fallback: nearest OTM
    call above + OTM put below spot (disclosed as a slight underestimate).
    Unusable quotes → honest {"available": False, "reason": ...}.
    """
    if not event_exp.get("available"):
        return {"available": False, "pct": None,
                "reason": f"no event expiration: {event_exp.get('reason')}"}
    if not isinstance(snapshot, dict) or not snapshot.get("available"):
        return {"available": False, "pct": None,
                "reason": (snapshot or {}).get("reason") or "chain snapshot unavailable"}
    spot = _f(snapshot.get("underlying_price"))
    if not spot or spot <= 0:
        return {"available": False, "pct": None,
                "reason": "chain carried no underlying price"}
    exp_row = next((e for e in snapshot.get("expirations") or []
                    if str(e.get("exp") or "")[:10] == event_exp["exp"]), None)
    if exp_row is None:
        return {"available": False, "pct": None,
                "reason": "event expiration row missing from snapshot"}

    calls = {c["strike"]: c for c in exp_row.get("contracts") or []
             if c.get("side") == "call" and _f(c.get("strike"))}
    puts = {c["strike"]: c for c in exp_row.get("contracts") or []
            if c.get("side") == "put" and _f(c.get("strike"))}

    # ATM straddle: shared strike nearest spot with both legs usable.
    shared = sorted(set(calls) & set(puts), key=lambda k: abs(k - spot))
    for strike in shared:
        c, p = calls[strike], puts[strike]
        if _usable_quote(c) and _usable_quote(p):
            pct = round((c["mid"] + p["mid"]) / spot * 100.0, 2)
            return {"available": True, "pct": pct, "method": "atm_straddle_mid",
                    "expiration": event_exp["exp"], "strike": strike,
                    "straddle_mid": round(c["mid"] + p["mid"], 4),
                    "legs": [{"side": "call", "strike": strike, "mid": c["mid"],
                              "spread_pct": c.get("spread_pct")},
                             {"side": "put", "strike": strike, "mid": p["mid"],
                              "spread_pct": p.get("spread_pct")}],
                    "wide_quotes": any((_f(l.get("spread_pct")) or 0) > WIDE_QUOTE_SPREAD_PCT
                                       for l in (c, p))}
    # Strangle fallback: nearest usable OTM call above / OTM put below spot.
    otm_calls = sorted((k for k, c in calls.items() if k >= spot and _usable_quote(c)))
    otm_puts = sorted((k for k, p in puts.items() if k <= spot and _usable_quote(p)),
                      reverse=True)
    if otm_calls and otm_puts:
        c, p = calls[otm_calls[0]], puts[otm_puts[0]]
        pct = round((c["mid"] + p["mid"]) / spot * 100.0, 2)
        return {"available": True, "pct": pct, "method": "otm_strangle_fallback",
                "expiration": event_exp["exp"],
                "note": "no shared ATM strike with usable two-sided quotes; "
                        "OTM strangle slightly understates the implied move",
                "legs": [{"side": "call", "strike": c["strike"], "mid": c["mid"],
                          "spread_pct": c.get("spread_pct")},
                         {"side": "put", "strike": p["strike"], "mid": p["mid"],
                          "spread_pct": p.get("spread_pct")}],
                "wide_quotes": any((_f(l.get("spread_pct")) or 0) > WIDE_QUOTE_SPREAD_PCT
                                   for l in (c, p))}
    return {"available": False, "pct": None,
            "reason": "no usable two-sided quotes for a straddle or strangle "
                      "at the event expiration"}


# ── historical earnings moves (price_cache around past report dates) ─────────

def _db_past_earnings_dates(symbol: str) -> Optional[List[str]]:
    """Past report dates this deployment stores — ONLY last_earnings_date (≤1).

    Returns None when the source is unreachable, [] when reachable but empty.
    """
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return None
        row = _execute(
            "SELECT last_earnings_date FROM symbol_profiles WHERE upper(symbol) = %s",
            ((symbol or "").upper(),), fetch="one")
        if row is None:
            return []
        d = _iso_date(dict(row).get("last_earnings_date"))
        return [d] if d else []
    except Exception:
        return None


def _db_closes_around(symbol: str, event_date: str) -> List[dict]:
    """price_cache closes in [event−7d, event+7d] — one statement; [] on failure."""
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return []
        rows = _execute(
            "SELECT price_date::text AS d, close_price FROM price_cache "
            "WHERE symbol = %s "
            "  AND price_date BETWEEN %s::date - %s AND %s::date + %s "
            "ORDER BY price_date",
            ((symbol or "").upper(), event_date, _PRICE_WINDOW_DAYS,
             event_date, _PRICE_WINDOW_DAYS), fetch="all") or []
        return [dict(r) for r in rows]
    except Exception:
        return []


def move_around_event(closes: List[dict], event_date: str) -> Optional[dict]:
    """Abs % earnings move from daily closes around one report date.

    Report timing (BMO/AMC) is not stored, so the move is the LARGER abs
    close-to-close change of (D−1→D) and (D→D+1) around report date D —
    an upper-bound-honest approximation, disclosed via `method`. None when
    the bars needed are missing (never guessed).
    """
    series: List[tuple] = []
    for r in closes or []:
        d, c = _iso_date(r.get("d")), _f(r.get("close_price"))
        if d and c and c > 0:
            series.append((d, c))
    if not series:
        return None
    before = [x for x in series if x[0] < event_date]
    on_after = [x for x in series if x[0] >= event_date]
    if not before or len(on_after) < 2:
        return None   # need D−1 plus two bars from D onward for both day-moves
    prev = before[-1]
    d0, d1 = on_after[0], on_after[1]
    m1 = abs(d0[1] / prev[1] - 1.0) * 100.0
    m2 = abs(d1[1] / d0[1] - 1.0) * 100.0
    pick = ("close_to_close_into_event", round(m1, 2)) if m1 >= m2 else \
           ("close_to_close_out_of_event", round(m2, 2))
    return {"event_date": event_date, "abs_move_pct": pick[1],
            "window": [prev[0], d1[0]],
            "method": "max abs close-to-close move straddling the report date "
                      "(BMO/AMC timing unknown)",
            "picked_leg": pick[0]}


def historical_earnings_moves(symbol: str, *,
                              past_dates: Optional[List[str]] = None,
                              closes_fn: Any = None) -> Dict[str, Any]:
    """{avg_abs_move_pct, max_abs_move_pct, samples, per_event} or honest degrade.

    This deployment has NO multi-quarter past-earnings-dates source —
    symbol_profiles stores only last_earnings_date — so samples is at most 1
    and thin_history is structural. `past_dates`/`closes_fn` are injectable
    for tests.
    """
    dates = past_dates if past_dates is not None else _db_past_earnings_dates(symbol)
    if dates is None:
        return {"available": False,
                "reason": "no historical earnings dates source (DB unavailable)",
                "source": PAST_EARNINGS_SOURCE}
    dates = [d for d in (_iso_date(x) for x in dates) if d and d <= _today().isoformat()]
    if not dates:
        return {"available": False,
                "reason": "no historical earnings dates source "
                          "(symbol_profiles stores only last_earnings_date, "
                          "absent for this symbol; no multi-quarter table exists)",
                "source": PAST_EARNINGS_SOURCE}
    fetch = closes_fn or _db_closes_around
    per_event: List[dict] = []
    missing: List[str] = []
    for d in sorted(set(dates), reverse=True):
        mv = move_around_event(fetch(symbol, d), d)
        (per_event.append(mv) if mv else missing.append(d))
    if not per_event:
        return {"available": False,
                "reason": f"price_cache carries no usable daily bars around "
                          f"past report date(s) {missing}",
                "source": f"{PAST_EARNINGS_SOURCE} + {PRICE_SOURCE}"}
    moves = [e["abs_move_pct"] for e in per_event]
    return {"available": True,
            "avg_abs_move_pct": round(sum(moves) / len(moves), 2),
            "max_abs_move_pct": round(max(moves), 2),
            "samples": len(per_event),
            "per_event": per_event,
            "dates_without_bars": missing,
            "source": f"{PAST_EARNINGS_SOURCE} + {PRICE_SOURCE}",
            "note": "single most recent report only — this deployment stores "
                    "no multi-quarter earnings-date history (thin_history)"}


# ── IV context + post-event crush estimate ───────────────────────────────────

def _iv_context(symbol: str, snapshot: Optional[dict]) -> Dict[str, Any]:
    """iv_history.iv_rank reuse with the snapshot's ATM IV; honest degrade."""
    try:
        from lib.strategy_research import iv_history
        atm = iv_history.extract_atm_iv(snapshot) if snapshot else None
        return iv_history.iv_rank(symbol, current_iv=(atm or {}).get("atm_iv"))
    except Exception as e:
        return {"available": False, "reason": f"iv context error: {str(e)[:120]}"}


def crush_estimate(current_atm_iv: Optional[float],
                   history: Optional[List[float]],
                   *, min_days: Optional[int] = None) -> Dict[str, Any]:
    """Post-earnings IV-crush ESTIMATE: current ATM IV vs stored-history median.

    Heuristic proxy (labeled, never a measurement): assumes post-event IV
    reverts toward its 52-week median, so
        estimate_pct = max(0, (current − median) / current × 100).
    Requires a current IV and ≥ MIN_HISTORY_DAYS stored days; otherwise an
    honest degrade.
    """
    try:
        from lib.strategy_research.iv_history import MIN_HISTORY_DAYS
    except Exception:
        MIN_HISTORY_DAYS = 20
    need = min_days if min_days is not None else MIN_HISTORY_DAYS
    cur = _f(current_atm_iv)
    if cur is None or cur <= 0:
        return {"available": False, "estimate_pct": None,
                "reason": "no current ATM IV from the chain snapshot"}
    vals = [v for v in (_f(x) for x in history or []) if v is not None and v > 0]
    if len(vals) < need:
        return {"available": False, "estimate_pct": None,
                "reason": f"insufficient iv history for a crush estimate "
                          f"({len(vals)} days stored, {need} required)"}
    svals = sorted(vals)
    n = len(svals)
    median = svals[n // 2] if n % 2 else (svals[n // 2 - 1] + svals[n // 2]) / 2.0
    est = max(0.0, (cur - median) / cur * 100.0)
    return {"available": True,
            "estimate_pct": round(est, 1),
            "current_atm_iv": round(cur, 3),
            "median_iv": round(median, 3),
            "history_days": n,
            "method": "heuristic ESTIMATE — current ATM IV vs 52-week stored "
                      "median as a reversion proxy; NOT a measured event crush",
            "is_estimate": True}


# ── thesis mapping + confidence ──────────────────────────────────────────────

def event_thesis_of(ctx: dict) -> Dict[str, Any]:
    """Map matcher thesis context onto bullish|bearish|neutral|unknown."""
    try:
        from .strategy_matcher import BEARISH_VERDICTS, BULLISH_VERDICTS, thesis_of
    except Exception:  # pragma: no cover — matcher is a sibling module
        BULLISH_VERDICTS = frozenset({"buy", "strong_buy"})
        BEARISH_VERDICTS = frozenset({"sell", "strong_sell", "avoid",
                                      "deteriorating", "reduce"})
        thesis_of = None
    verdict = str(ctx.get("verdict") or "").strip().lower() or None
    th = thesis_of(ctx) if thesis_of else {"bullish": verdict in BULLISH_VERDICTS,
                                           "bearish": verdict in BEARISH_VERDICTS,
                                           "bullish_source": None,
                                           "bearish_source": None,
                                           "verdict": verdict}
    if th["bearish"]:
        thesis, source = "bearish", th.get("bearish_source") or "verdict_bearish"
    elif th["bullish"]:
        thesis, source = "bullish", th.get("bullish_source") or "verdict_bullish"
    elif (th.get("verdict") or verdict) in NEUTRAL_VERDICTS:
        thesis, source = "neutral", f"watchlist_{th.get('verdict') or verdict}"
    else:
        thesis, source = "unknown", None
    return {"thesis": thesis, "source": source, "verdict": th.get("verdict")}


def _thesis_strength(thesis: Dict[str, Any], ctx: dict) -> float:
    verdict = thesis.get("verdict")
    if thesis["thesis"] == "unknown":
        return 0.0
    if verdict in STRONG_VERDICTS:
        return 1.0
    if thesis["thesis"] == "neutral":
        return 0.5
    if verdict:                       # actionable non-strong verdict
        return 0.8
    return 0.7                        # explicit caller thesis_direction / hedge


def _event_proximity(days: Optional[int], before: int, after: int) -> float:
    if days is None:
        return 0.0
    if -after <= days <= before:
        return 1.0
    if days < -after:                 # event already passed beyond the window
        return 0.0
    if days <= 2 * before:
        return 0.6
    return 0.25


def event_confidence(*, thesis: Dict[str, Any], ctx: dict,
                     completeness_flags: List[bool],
                     days_to_earnings: Optional[int],
                     window_before: int, window_after: int) -> Dict[str, Any]:
    """Composite 0-1 confidence (formula in the module docstring)."""
    ts = _thesis_strength(thesis, ctx)
    dc = sum(1 for f in completeness_flags if f) / max(1, len(completeness_flags))
    px = _event_proximity(days_to_earnings, window_before, window_after)
    score = _clamp01(W_THESIS * ts + W_COMPLETENESS * dc + W_PROXIMITY * px)
    return {"score": round(score, 3),
            "components": {"thesis_strength": round(ts, 3),
                           "data_completeness": round(dc, 3),
                           "event_proximity": round(px, 3)},
            "weights": {"thesis_strength": W_THESIS,
                        "data_completeness": W_COMPLETENESS,
                        "event_proximity": W_PROXIMITY},
            "formula": "clamp01(0.45*thesis_strength + 0.35*data_completeness "
                       "+ 0.20*event_proximity)"}


# ── main API ─────────────────────────────────────────────────────────────────

def build_event_json(symbol: str, *,
                     chain_snapshot: Optional[dict] = None,
                     config: Optional[dict] = None,
                     context: Optional[dict] = None,
                     earnings_date: Optional[str] = None,
                     today: Optional[date] = None,
                     past_earnings_dates: Optional[List[str]] = None,
                     closes_fn: Any = None,
                     iv_history_series: Optional[List[float]] = None) -> Dict[str, Any]:
    """Earnings event context for one symbol (spec Part B). EDUCATIONAL_ONLY.

    config: typically the registry row's `selection` block (window days are
    read from it; DEFAULT_CONFIG otherwise). chain_snapshot / context /
    earnings_date / past_earnings_dates / closes_fn / iv_history_series are
    injectable for tests and weekend sanity; live reads are all read-only and
    degrade honestly into the returned JSON.
    """
    sym = (symbol or "").strip().upper()
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    w_before = int(cfg.get("earnings_window_days_before")
                   or DEFAULT_CONFIG["earnings_window_days_before"])
    w_after = int(cfg.get("earnings_window_days_after")
                  or DEFAULT_CONFIG["earnings_window_days_after"])
    now = today or _today()

    # 1. earnings date + distance
    ed = resolve_earnings_date(sym, earnings_date)
    days_to = None
    if ed["date"]:
        days_to = (date.fromisoformat(ed["date"]) - now).days
    in_window = (None if days_to is None
                 else (-w_after <= days_to <= w_before))

    # 2. chain snapshot (injected or live read-only fetch)
    snap = chain_snapshot
    if snap is None:
        try:
            from lib.strategy_research.options_chain import fetch_chain_snapshot
            snap = fetch_chain_snapshot(sym)
        except Exception as e:
            snap = {"available": False,
                    "reason": f"chain adapter import failed: {str(e)[:120]}"}
    chain_ok = bool(isinstance(snap, dict) and snap.get("available"))

    # 3. event expiration + implied move
    event_exp = nearest_expiration_after(snap, ed["date"])
    implied = implied_move_from_snapshot(snap, event_exp)

    # 4. historical earnings moves (honest: at most one stored past date)
    hist = historical_earnings_moves(sym, past_dates=past_earnings_dates,
                                     closes_fn=closes_fn)

    # 5. IV rank context + post-event crush estimate
    atm: Optional[dict] = None
    if iv_history_series is not None:
        try:
            from lib.strategy_research import iv_history
            atm = iv_history.extract_atm_iv(snap) if chain_ok else None
            ivc = iv_history.iv_rank(sym, current_iv=(atm or {}).get("atm_iv"),
                                     history=iv_history_series)
        except Exception as e:
            ivc = {"available": False, "reason": f"iv context error: {str(e)[:120]}"}
        crush = crush_estimate((atm or {}).get("atm_iv") if chain_ok else None,
                               iv_history_series)
    else:
        ivc = _iv_context(sym, snap if chain_ok else None)
        cur_iv = ivc.get("atm_iv") if ivc.get("available") else None
        if cur_iv is None and chain_ok:
            try:
                from lib.strategy_research import iv_history
                cur_iv = (iv_history.extract_atm_iv(snap) or {}).get("atm_iv")
            except Exception:
                cur_iv = None
        series = _read_iv_series(sym)
        crush = crush_estimate(cur_iv, series)

    # 6. thesis (matcher-context reuse; caller context wins)
    ctx = _resolve_context(sym, context)
    thesis = event_thesis_of(ctx)

    # 7. confidence (documented composite)
    completeness = [bool(ed["date"]), chain_ok,
                    bool(implied.get("available")),
                    bool(hist.get("available")),
                    bool(ivc.get("available"))]
    conf = event_confidence(thesis=thesis, ctx=ctx,
                            completeness_flags=completeness,
                            days_to_earnings=days_to,
                            window_before=w_before, window_after=w_after)

    # 8. risk flags
    flags: List[str] = []
    if ivc.get("available") and _f(ivc.get("iv_rank")) is not None \
            and ivc["iv_rank"] > IV_RICH_RANK:
        flags.append("iv_rich")
    if not hist.get("available") or int(hist.get("samples") or 0) < THIN_HISTORY_MIN_SAMPLES:
        flags.append("thin_history")
    if (implied.get("available") and implied.get("wide_quotes")) or (
            chain_ok and not implied.get("available")):
        flags.append("wide_quotes")
    if days_to is None:
        flags.append("no_earnings_date")
    elif days_to < -w_after:
        flags.append("event_stale")
    elif days_to > w_before:
        flags.append("event_far")
    if not event_exp.get("available"):
        flags.append("no_expiration_after_earnings")
    if thesis["thesis"] == "unknown":
        flags.append("thesis_unknown")
    if not chain_ok:
        flags.append("chain_unavailable")

    return {
        "symbol": sym,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of_date": now.isoformat(),
        "days_to_earnings": days_to,
        "earnings_date": ed,
        "event_window": {"days_before": w_before, "days_after": w_after,
                         "in_window": in_window},
        "nearest_expiration_after_earnings": event_exp,
        "implied_move_pct": implied,
        "historical_earnings_moves": hist,
        "iv_context": ivc,
        "post_earnings_iv_crush_estimate": crush,
        "event_thesis": thesis["thesis"],
        "event_thesis_source": thesis["source"],
        "event_confidence": conf["score"],
        "event_confidence_detail": conf,
        "risk_flags": flags,
        "educational_only": True,
        "banner": EDUCATIONAL_BANNER,
    }


def _resolve_context(symbol: str, context: Optional[dict]) -> dict:
    """Matcher resolve_context reuse (read-only watchlist/holdings); degrades
    to caller context (or bare symbol) if the matcher import fails."""
    try:
        from .strategy_matcher import resolve_context
        return resolve_context(symbol, context)
    except Exception:
        ctx = dict(context or {})
        ctx.setdefault("symbol", (symbol or "").upper())
        ctx.setdefault("verdict", None)
        return ctx


def _read_iv_series(symbol: str) -> Optional[List[float]]:
    """Stored daily ATM-IV series (iv_history reader reuse); None when unavailable."""
    try:
        from lib.strategy_research.iv_history import _read_history
        return _read_history(symbol)
    except Exception:
        return None


# ── CLI sanity (read-only) ───────────────────────────────────────────────────

if __name__ == "__main__":  # pragma: no cover
    import argparse
    import sys
    from pathlib import Path

    scripts_dir = Path(__file__).resolve().parent.parent.parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    ap = argparse.ArgumentParser(
        description="Earnings event context JSON (read-only sanity CLI)")
    ap.add_argument("symbol", help="underlying symbol, e.g. RTX")
    ap.add_argument("--earnings-date", default=None,
                    help="override YYYY-MM-DD (skips the DB/json lookup)")
    args = ap.parse_args()
    print(json.dumps(build_event_json(args.symbol,
                                      earnings_date=args.earnings_date),
                     indent=2, default=str))
