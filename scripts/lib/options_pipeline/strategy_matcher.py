"""strategy_matcher.py — per-symbol multi-strategy matcher (operator spec Part C).

For ONE symbol, evaluates every strategy the options registry knows about and
reports an honest per-strategy verdict:

    run_matchers(symbol, context, strategies="enabled") →
        {"symbol", "context", "strategy_results": {strategy_id:
            {"status": pass|watch|fail|not_applicable, "reason", "proposals"}},
         "cross_strategy_summary": {...}}

Thesis rules (the matcher owns direction; generators own contract math):
  • atm_call requires a BULLISH context — watchlist buy/strong_buy, or held with
    a positive thesis. Otherwise: fail "bullish thesis missing".
  • atm_put requires a BEARISH context — watchlist sell/avoid/deteriorating,
    an explicit bearish thesis, or a hedge-of-held flag. Otherwise: fail
    "bearish thesis missing".
  • deep_itm_call delegates to the existing deep_itm_generator (its conviction
    floor + chain gates decide pass/watch/fail).
  • earnings_put_debit_spread (EARNINGS-SPREADS Stage 2, spec Part E):
    not_applicable when there is no earnings date / the event window is closed
    ("no earnings in window"); fail when the bearish/hedge thesis is missing or
    event_confidence sits below the registry gate; otherwise the earnings
    vertical generator runs → pass/watch (watch when every proposal carries
    disclosed flags only — iv_rich / historical_move_below_breakeven).
  • earnings_put_credit_spread stays not_applicable — BLOCKED_INITIAL in the
    registry (paper_enabled false, loader-enforced) until the debit lane has
    observed paper history.
  • covered_call / cash_secured_put / protective_put / credit_spread return
    not_applicable with honest reasons (requires held shares / requires existing
    exposure / scanner_mode arrives in a later stage) — NO generation.

Status semantics:
  pass    — gates passed; at least one proposal carries no watch-class flag
  watch   — gates passed but every proposal carries disclosed-flag-only issues
            (e.g. earnings flagged, IV-rich pay-up warning)
  fail    — thesis missing, chain unavailable, or no candidate survived gates
  not_applicable — the strategy structurally does not apply here (honest reason)

PURE LIBRARY (test-enforced): no queue writes (Stage 2's scanner owns writing),
no broker / submit / order / 2FA imports. Context resolution reads are the same
read-only sources the scanner's conviction resolution uses (watchlist research
card + CIO synthesis verdicts, holdings.json) and degrade honestly to None.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .atm_long_premium_generator import generate_atm_proposals
from .deep_itm_generator import generate_deep_itm_proposals
from .earnings_vertical_generator import generate_put_debit_spreads
from .universe import load_strategy_registry

STATUS_PASS = "pass"
STATUS_WATCH = "watch"
STATUS_FAIL = "fail"
STATUS_NOT_APPLICABLE = "not_applicable"
ALL_STATUSES = (STATUS_PASS, STATUS_WATCH, STATUS_FAIL, STATUS_NOT_APPLICABLE)

BULLISH_VERDICTS = frozenset({"buy", "strong_buy"})
BEARISH_VERDICTS = frozenset({"sell", "strong_sell", "avoid", "deteriorating",
                              "reduce"})

# Disclosed-flag-only issues that demote pass → watch (spec Part C). Data-quality
# disclosures (delta proxy, earnings unknown) do NOT demote — they are visible on
# the card but are not risk events.
WATCH_FLAGS = frozenset({
    "earnings_before_expiry_flagged",           # atm lane, earnings_policy=flag
    "earnings_before_expiry_operator_flagged",  # deep-ITM lane equivalent
    "iv_rich_pay_up_warning",                   # IV-rank rich disclosure
    "iv_rich",                                  # earnings lane: event premium rich
    "historical_move_below_breakeven",          # earnings lane: hist < required BE move
})

# Matchers with no generation path yet — honest not_applicable reasons.
_NOT_APPLICABLE_REASONS: Dict[str, Callable[[dict], str]] = {
    "covered_call": lambda ctx: (
        "held shares present — covered-call generation arrives in a later "
        "scanner_mode stage (income overlay not wired)"
        if _f(ctx.get("held_shares")) >= 100 else
        "requires 100 held shares of the underlying (income overlay); "
        "generation arrives in a later scanner_mode stage"),
    "cash_secured_put": lambda ctx: (
        "cash-secured put generation not wired — scanner_mode arrives in a "
        "later stage (cash collateral must be modeled per contract)"),
    "protective_put": lambda ctx: (
        "hedge generation arrives in a later scanner_mode stage"
        if _f(ctx.get("held_shares")) > 0 else
        "requires existing long exposure (held shares) to hedge; generation "
        "arrives in a later scanner_mode stage"),
    "credit_spread": lambda ctx: (
        "multi-leg credit spreads are RESEARCH_ONLY in the registry — no paper "
        "generation is modeled"),
    "earnings_put_credit_spread": lambda ctx: (
        "blocked initially (BLOCKED_INITIAL) — paper_enabled false in registry "
        "until the debit lane observes paper history (short-premium event "
        "risk: gap-through-strike, assignment)"),
}


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if x != x else x  # NaN guard


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── context resolution (same read-only sources as the scanner) ───────────────

def _normalize_verdict(raw: Any) -> Optional[str]:
    """Full-spectrum verdict normalization (the scanner's normalizer only keeps
    buy-side; the matcher needs bearish verdicts too)."""
    if not raw:
        return None
    r = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {"strongbuy": "strong_buy", "strongsell": "strong_sell"}
    return aliases.get(r, r) or None


def _fetch_watchlist_verdict(symbol: str) -> Optional[str]:
    """Watchlist verdict for one symbol — research card first, CIO synthesis
    fallback (the same sources the scanner's conviction resolution reads).
    Read-only; any failure returns None (honest unknown)."""
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return None
        row = _execute(
            """SELECT rc.latest_recommendation AS card_rec,
                      fs.recommendation AS synth_rec
               FROM watchlist_items wi
               LEFT JOIN watchlist_research_cards rc ON rc.symbol = wi.symbol
               LEFT JOIN watchlist_final_synthesis fs ON UPPER(fs.symbol) = UPPER(wi.symbol)
               WHERE wi.symbol = %s AND wi.status <> 'removed'""",
            ((symbol or "").upper(),), fetch="one")
        if not row:
            return None
        d = dict(row)
        return _normalize_verdict(d.get("card_rec")) or _normalize_verdict(d.get("synth_rec"))
    except Exception:
        return None


def _held_shares(symbol: str) -> Optional[float]:
    """Held shares from holdings.json (universe resolver reuse); None on outage."""
    try:
        from .universe import _load_holdings_symbols
        held = _load_holdings_symbols()
        return held.get((symbol or "").upper())
    except Exception:
        return None


def resolve_context(symbol: str, context: Optional[dict] = None) -> dict:
    """Fill missing context keys from read-only sources. Caller-supplied keys
    always win; unavailable sources leave honest Nones (never guessed)."""
    ctx = dict(context or {})
    sym = (symbol or "").strip().upper()
    ctx.setdefault("symbol", sym)
    if "verdict" not in ctx:
        ctx["verdict"] = _fetch_watchlist_verdict(sym)
    else:
        ctx["verdict"] = _normalize_verdict(ctx.get("verdict"))
    if "held_shares" not in ctx:
        ctx["held_shares"] = _held_shares(sym)
    ctx.setdefault("thesis_direction", None)   # explicit 'bullish' | 'bearish'
    ctx.setdefault("hedge_of_held", False)
    return ctx


# ── thesis evaluation ────────────────────────────────────────────────────────

def thesis_of(ctx: dict) -> dict:
    """{"bullish": bool, "bearish": bool, "bullish_source", "bearish_source"}."""
    verdict = _normalize_verdict(ctx.get("verdict"))
    held = _f(ctx.get("held_shares")) > 0
    explicit = str(ctx.get("thesis_direction") or "").strip().lower() or None

    bullish_source = None
    if verdict in BULLISH_VERDICTS:
        bullish_source = f"watchlist_{verdict}"
    elif held and (explicit == "bullish" or ctx.get("positive_thesis") is True):
        bullish_source = "held_with_positive_thesis"

    bearish_source = None
    if verdict in BEARISH_VERDICTS:
        bearish_source = f"watchlist_{verdict}"
    elif explicit == "bearish":
        bearish_source = "explicit_bearish_thesis"
    elif ctx.get("hedge_of_held") and held:
        bearish_source = "hedge_of_held"

    return {"bullish": bullish_source is not None,
            "bearish": bearish_source is not None,
            "bullish_source": bullish_source,
            "bearish_source": bearish_source,
            "verdict": verdict,
            "held_shares": ctx.get("held_shares"),
            "explicit_thesis": explicit}


def _bullish_conviction(ctx: dict, thesis: dict) -> tuple[float, str]:
    verdict = thesis.get("verdict")
    held = _f(ctx.get("held_shares")) > 0
    if "conviction" in ctx and ctx["conviction"] is not None:
        return _f(ctx["conviction"]), str(ctx.get("conviction_source")
                                          or thesis.get("bullish_source") or "caller")
    if verdict == "strong_buy":
        conv = 0.90 if held else 0.85
    elif verdict == "buy":
        conv = 0.75 if held else 0.70
    elif thesis.get("bullish_source") == "held_with_positive_thesis":
        conv = 0.60
    else:
        conv = 0.0
    return conv, (thesis.get("bullish_source") or "none")


def _bearish_conviction(ctx: dict, thesis: dict) -> tuple[float, str]:
    verdict = thesis.get("verdict")
    if "conviction" in ctx and ctx["conviction"] is not None:
        return _f(ctx["conviction"]), str(ctx.get("conviction_source")
                                          or thesis.get("bearish_source") or "caller")
    if verdict == "strong_sell":
        conv = 0.80
    elif verdict in BEARISH_VERDICTS:
        conv = 0.70
    elif thesis.get("bearish_source") == "explicit_bearish_thesis":
        conv = 0.65
    elif thesis.get("bearish_source") == "hedge_of_held":
        conv = 0.60
    else:
        conv = 0.0
    return conv, (thesis.get("bearish_source") or "none")


# ── per-strategy result interpretation ───────────────────────────────────────

def _rank(proposals: List[dict]) -> List[dict]:
    """Rank within a strategy by (IV-modified) edge score, best first."""
    return sorted(proposals or [], key=lambda p: -_f(p.get("edge_score")))


def _pass_or_watch(proposals: List[dict]) -> tuple[str, str]:
    """pass when any proposal is free of watch-class flags; watch when every
    proposal carries at least one disclosed watch flag."""
    flagged = []
    for p in proposals:
        flags = set((p.get("meta") or {}).get("gate_flags") or [])
        flagged.append(sorted(flags & WATCH_FLAGS))
    if any(not fl for fl in flagged):
        return STATUS_PASS, f"{len(proposals)} proposal(s) passed gates"
    disclosed = sorted({f for fl in flagged for f in fl})
    return STATUS_WATCH, ("gates pass with disclosed flags only: "
                          + ", ".join(disclosed))


def _result(status: str, reason: str, proposals: Optional[List[dict]] = None,
            **extra: Any) -> dict:
    out = {"status": status, "reason": reason, "proposals": _rank(proposals or [])}
    out.update(extra)
    return out


def _match_atm(symbol: str, side: str, ctx: dict, thesis: dict,
               atm_fn: Callable[..., dict], **gen_kwargs: Any) -> dict:
    if side == "call":
        if not thesis["bullish"]:
            return _result(STATUS_FAIL, "bullish thesis missing "
                           "(needs watchlist buy/strong_buy or held with a "
                           "positive thesis)")
        conviction, source = _bullish_conviction(ctx, thesis)
    else:
        if not thesis["bearish"]:
            return _result(STATUS_FAIL, "bearish thesis missing "
                           "(needs watchlist sell/avoid/deteriorating, an "
                           "explicit bearish thesis, or a hedge-of-held flag)")
        conviction, source = _bearish_conviction(ctx, thesis)

    thesis_ctx = {
        "conviction": conviction,
        "conviction_source": source,
        "verdict": thesis.get("verdict"),
        "held_shares": ctx.get("held_shares"),
        "hedge_of_held": bool(ctx.get("hedge_of_held")),
    }
    gen = atm_fn(symbol, side, None, thesis_ctx, **gen_kwargs)
    if not gen.get("available"):
        return _result(STATUS_FAIL,
                       f"chain unavailable: {gen.get('reason') or 'unknown'}",
                       generator=gen)
    proposals = gen.get("proposals") or []
    if not proposals:
        notes = "; ".join(
            f"{b.get('target_dte')}d: {b.get('reason')}"
            for b in (gen.get("buckets") or []) if not b.get("available"))
        return _result(STATUS_FAIL,
                       "no candidates passed gates"
                       + (f" ({notes})" if notes else ""),
                       generator=gen)
    status, reason = _pass_or_watch(proposals)
    return _result(status, reason, proposals, generator_buckets=gen.get("buckets"))


def _match_deep_itm(symbol: str, ctx: dict, thesis: dict,
                    deep_itm_fn: Callable[..., dict],
                    analysis_fn: Optional[Callable[..., dict]]) -> dict:
    conviction, source = _bullish_conviction(ctx, thesis)
    underlying = {
        "symbol": symbol,
        "conviction": conviction,
        "conviction_source": source,
        "verdict": thesis.get("verdict"),
        "held_shares": ctx.get("held_shares"),
    }
    kwargs = {"analysis_fn": analysis_fn} if analysis_fn is not None else {}
    gen = deep_itm_fn([underlying], None, **kwargs)
    proposals = gen.get("proposals") or []
    per = (gen.get("per_underlying") or [{}])[0]
    if proposals:
        status, reason = _pass_or_watch(proposals)
        return _result(status, reason, proposals, per_underlying=per)
    st = per.get("status")
    if st == "skipped":
        return _result(STATUS_FAIL, per.get("reason")
                       or "conviction below the deep-ITM floor",
                       per_underlying=per)
    if st == "degraded":
        return _result(STATUS_FAIL,
                       f"chain unavailable: {per.get('reason') or 'unknown'}",
                       per_underlying=per)
    notes = "; ".join(per.get("notes") or [])
    return _result(STATUS_FAIL, "no candidates passed gates"
                   + (f" ({notes})" if notes else ""), per_underlying=per)


def _event_summary(ev: dict) -> dict:
    """Compact event context for matcher results (full JSON rides proposals)."""
    ev = ev or {}
    im = ev.get("implied_move_pct") or {}
    return {"earnings_date": (ev.get("earnings_date") or {}).get("date"),
            "days_to_earnings": ev.get("days_to_earnings"),
            "in_window": (ev.get("event_window") or {}).get("in_window"),
            "implied_move_pct": im.get("pct") if im.get("available") else None,
            "event_confidence": ev.get("event_confidence"),
            "event_thesis": ev.get("event_thesis"),
            "risk_flags": list(ev.get("risk_flags") or [])}


def _match_earnings_debit(symbol: str, ctx: dict, thesis: dict, reg_row: dict,
                          *, snapshot: Optional[dict],
                          chain_fn: Optional[Callable[..., dict]],
                          earnings_date: Optional[str],
                          event_json: Optional[dict],
                          gen_fn: Callable[..., dict]) -> dict:
    """earnings_put_debit_spread lane (EARNINGS-SPREADS Stage 2, spec Part E).

    Order of verdicts: window (not_applicable) → thesis (fail) → confidence
    (fail) → generate (pass / watch / fail). The event context comes from
    earnings_event_model.build_event_json unless injected.
    """
    sel = dict((reg_row or {}).get("selection") or {})
    snap = snapshot
    if snap is None and chain_fn is not None:
        try:
            snap = chain_fn(symbol)
        except Exception as e:
            snap = {"available": False, "reason": str(e)[:120]}
    ev = event_json
    if ev is None:
        from .earnings_event_model import build_event_json
        try:
            ev = build_event_json(symbol, chain_snapshot=snap, config=sel,
                                  context=ctx, earnings_date=earnings_date)
        except Exception as e:
            return _result(STATUS_FAIL,
                           f"event context error: {str(e)[:140]}")

    window = ev.get("event_window") or {}
    if not (ev.get("earnings_date") or {}).get("date") \
            or not window.get("in_window"):
        days = ev.get("days_to_earnings")
        detail = (f"days_to_earnings={days}" if days is not None
                  else (ev.get("earnings_date") or {}).get("reason")
                  or "no earnings date")
        return _result(STATUS_NOT_APPLICABLE,
                       f"no earnings in window ({detail}; window "
                       f"−{window.get('days_after')}.."
                       f"{window.get('days_before')}d)",
                       event=_event_summary(ev))
    if not thesis["bearish"]:
        return _result(STATUS_FAIL,
                       "bearish/hedge thesis missing (needs watchlist "
                       "sell/avoid/deteriorating, an explicit bearish thesis, "
                       "or a hedge-of-held flag)",
                       event=_event_summary(ev))
    min_conf = _f(sel.get("min_event_confidence"), 0.65)
    conf = _f(ev.get("event_confidence"))
    if conf < min_conf:
        return _result(STATUS_FAIL,
                       f"event_confidence {conf:.2f} below gate "
                       f"{min_conf:.2f} (min_event_confidence)",
                       event=_event_summary(ev))

    conviction, source = _bearish_conviction(ctx, thesis)
    thesis_ctx = {
        "conviction": conviction,
        "conviction_source": source,
        "verdict": thesis.get("verdict"),
        "held_shares": ctx.get("held_shares"),
        "hedge_of_held": bool(ctx.get("hedge_of_held")),
        "thesis_direction": ctx.get("thesis_direction"),
    }
    gen = gen_fn(symbol, ev, None, thesis_ctx, snapshot=snap,
                 chain_fn=chain_fn)
    if not gen.get("available"):
        reason = gen.get("reason") or "unknown"
        if gen.get("degraded"):
            reason = f"chain unavailable: {reason}"
        return _result(STATUS_FAIL, reason, generator_gate=gen.get("gate"),
                       event=_event_summary(ev))
    proposals = gen.get("proposals") or []
    if not proposals:
        notes = "; ".join(gen.get("reject_notes") or [])
        return _result(STATUS_FAIL,
                       "no candidates passed gates"
                       + (f" ({notes})" if notes else ""),
                       event=_event_summary(ev))
    status, reason = _pass_or_watch(proposals)
    return _result(status, reason, proposals, event=_event_summary(ev))


# ── main API (operator spec Part C) ──────────────────────────────────────────

def run_matchers(
    symbol: str,
    context: Optional[dict] = None,
    strategies: Any = "enabled",
    *,
    registry: Optional[dict] = None,
    deep_itm_fn: Optional[Callable[..., dict]] = None,
    deep_itm_analysis_fn: Optional[Callable[..., dict]] = None,
    atm_fn: Optional[Callable[..., dict]] = None,
    snapshot: Optional[dict] = None,
    chain_fn: Optional[Callable[..., dict]] = None,
    earnings_date: Optional[str] = None,
    iv_context: Optional[dict] = None,
    event_json: Optional[dict] = None,
    earnings_fn: Optional[Callable[..., dict]] = None,
) -> dict:
    """Evaluate every requested strategy for one symbol.

    strategies: "enabled"/"all" → every strategy in the options registry
    (each reports honestly, including not_applicable); or an explicit list of
    strategy ids. An invalid registry raises (fail-closed — including
    LivePolicyViolation when any row claims live permission).

    Injectables (tests / weekend sanity): snapshot/chain_fn/earnings_date/
    iv_context flow into the ATM generator; snapshot/chain_fn/earnings_date/
    event_json/earnings_fn into the earnings-vertical lane; deep_itm_analysis_fn
    into the deep-ITM generator; registry/deep_itm_fn/atm_fn override wholesale.

    PURE: writes nothing — Stage 2's scanner owns queue writes.
    """
    sym = (symbol or "").strip().upper()
    reg = registry if registry is not None else load_strategy_registry()
    known = dict(reg.get("strategies") or {})
    if isinstance(strategies, str):
        wanted = list(known)          # "enabled"/"all": every registry strategy
    else:
        wanted = [str(s) for s in (strategies or [])]

    ctx = resolve_context(sym, context)
    thesis = thesis_of(ctx)
    deep_fn = deep_itm_fn or generate_deep_itm_proposals
    atm = atm_fn or generate_atm_proposals
    atm_kwargs: Dict[str, Any] = {}
    if snapshot is not None:
        atm_kwargs["snapshot"] = snapshot
    if chain_fn is not None:
        atm_kwargs["chain_fn"] = chain_fn
    if earnings_date is not None:
        atm_kwargs["earnings_date"] = earnings_date
    if iv_context is not None:
        atm_kwargs["iv_context"] = iv_context

    results: Dict[str, dict] = {}
    for sid in wanted:
        row = known.get(sid)
        if row is None:
            results[sid] = _result(STATUS_NOT_APPLICABLE,
                                   "unknown strategy — not in "
                                   "options_strategy_registry")
            continue
        if not row.get("paper_enabled"):
            reason = _NOT_APPLICABLE_REASONS.get(sid, lambda c: "")(ctx) or (
                f"paper_enabled false in registry (status "
                f"{row.get('status')}) — no paper generation")
            results[sid] = _result(STATUS_NOT_APPLICABLE, reason)
            continue
        if sid == "deep_itm_call":
            results[sid] = _match_deep_itm(sym, ctx, thesis, deep_fn,
                                           deep_itm_analysis_fn)
        elif sid == "atm_call":
            results[sid] = _match_atm(sym, "call", ctx, thesis, atm, **atm_kwargs)
        elif sid == "atm_put":
            results[sid] = _match_atm(sym, "put", ctx, thesis, atm, **atm_kwargs)
        elif sid == "earnings_put_debit_spread":
            results[sid] = _match_earnings_debit(
                sym, ctx, thesis, row,
                snapshot=snapshot, chain_fn=chain_fn,
                earnings_date=earnings_date, event_json=event_json,
                gen_fn=earnings_fn or generate_put_debit_spreads)
        elif sid == "earnings_put_credit_spread":
            # Even if the registry were flipped scannable, the credit matcher
            # lane arrives only after the debit lane observes paper history.
            results[sid] = _result(
                STATUS_NOT_APPLICABLE,
                "blocked initially (BLOCKED_INITIAL) — the credit matcher "
                "lane arrives after the debit lane observes paper history")
        elif sid in _NOT_APPLICABLE_REASONS:
            results[sid] = _result(STATUS_NOT_APPLICABLE,
                                   _NOT_APPLICABLE_REASONS[sid](ctx))
        else:
            results[sid] = _result(STATUS_NOT_APPLICABLE,
                                   "no matcher implemented for this strategy")

    return {
        "symbol": sym,
        "generated_at": _now_iso(),
        "context": {
            "verdict": thesis.get("verdict"),
            "held_shares": ctx.get("held_shares"),
            "thesis_direction": ctx.get("thesis_direction"),
            "hedge_of_held": bool(ctx.get("hedge_of_held")),
            "bullish": thesis["bullish"],
            "bearish": thesis["bearish"],
            "bullish_source": thesis.get("bullish_source"),
            "bearish_source": thesis.get("bearish_source"),
        },
        "strategy_results": results,
        "cross_strategy_summary": cross_strategy_summary(sym, results, thesis),
    }


def cross_strategy_summary(symbol: str, results: Dict[str, dict],
                           thesis: dict) -> dict:
    """Roll-up across strategies: status buckets, proposal totals, best proposal."""
    buckets: Dict[str, List[str]] = {s: [] for s in ALL_STATUSES}
    total_proposals = 0
    best: Optional[dict] = None
    for sid, res in results.items():
        buckets.setdefault(res.get("status") or STATUS_FAIL, []).append(sid)
        for p in res.get("proposals") or []:
            total_proposals += 1
            if best is None or _f(p.get("edge_score")) > _f(best.get("edge_score")):
                best = {"strategy": sid, "id": p.get("id"),
                        "symbol": p.get("symbol"),
                        "strike": p.get("strike"), "expiration": p.get("expiration"),
                        "edge_score": p.get("edge_score"),
                        "status": res.get("status")}
    for s in buckets:
        buckets[s].sort()
    return {
        "symbol": symbol,
        "considered": len(results),
        "counts": {s: len(buckets[s]) for s in ALL_STATUSES},
        "pass": buckets[STATUS_PASS],
        "watch": buckets[STATUS_WATCH],
        "fail": buckets[STATUS_FAIL],
        "not_applicable": buckets[STATUS_NOT_APPLICABLE],
        "total_proposals": total_proposals,
        "best_proposal": best,
        "thesis": {"bullish": thesis["bullish"], "bearish": thesis["bearish"],
                   "verdict": thesis.get("verdict"),
                   "bullish_source": thesis.get("bullish_source"),
                   "bearish_source": thesis.get("bearish_source")},
    }
