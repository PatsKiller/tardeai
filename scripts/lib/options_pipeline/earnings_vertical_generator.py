"""earnings_vertical_generator.py — earnings vertical-spread paper proposal
generators (EARNINGS-SPREADS Stage 2, operator spec Parts C + D).

Two lanes over ONE event-expiration chain read:

  generate_put_debit_spreads(underlying, event_json, config, thesis_ctx)
      Bearish defined-risk event vertical (registry earnings_put_debit_spread,
      family earnings_vertical_debit, TESTING_PAPER). Generates ONLY when the
      event window is open (in_window per the registry's 10-before/2-after),
      the thesis is bearish_or_hedge, and event_confidence clears
      min_event_confidence — otherwise an honest {"available": False, gate}.
      Long put ATM/slightly ITM (|delta| 0.45-0.60, NTM proxy disclosed when
      the chain carries no greeks); short put below the expected-move boundary
      (spot × (1 − implied_move_pct/100)) plus width-table candidates
      (<$50: 2.5 · $50-150: 5 · $150-400: 10 · >$400: 20, adjacent width also
      tried). Package math from leg mids: debit = long mid − short mid,
      max_loss = debit×100, max_gain = (width − debit)×100,
      breakeven = long_strike − debit, reward_to_risk = max_gain / max_loss.

  generate_put_credit_spreads(underlying, event_json, config, thesis_ctx)
      Post-event IV-crush short-premium vertical (earnings_put_credit_spread,
      family earnings_vertical_credit) — STRUCTURALLY complete but BLOCKED:
      the registry row is BLOCKED_INITIAL (paper_enabled=false, loader-
      enforced), the matcher/scanner never call this function, and a direct
      call refuses unless allow_blocked=True is passed EXPLICITLY (tests /
      operator inspection only). Even force-generated rows carry the
      earnings_vertical_credit family that lib.options_pipeline.alpaca_paper.
      assert_spread_allowed refuses UNCONDITIONALLY, plus mandatory
      assignment-risk / gap-risk / short-leg-lifecycle disclosures in meta.

REJECT gates (named, machine-readable, per the registry selection block):
package slippage Σ(leg ask−bid)/package-mid > max_spread_package_slippage_pct;
either leg OI < min_open_interest_each_leg or volume < min_volume_each_leg;
debit > max_debit_pct_of_underlying × spot; max_loss > max_loss_usd_paper;
credit lane additionally credit_pct_of_width < min_credit_pct_of_width.
DISCLOSED flags (demote pass → watch in the matcher, never reject):
iv_rich (from event_json.risk_flags), historical_move_below_breakeven
(historical avg abs move < the down-move the breakeven requires).

SAFETY INVARIANTS (test-enforced by tests/test_options_earnings_vertical_
generator.py): every row carries educational_paper_model / paper_only /
requires_manual_review / execution_mode='manual_review_only' /
auto_eligible=False / enterprise.live_eligible=False (desk fail-closed);
1 spread max (spreads=1, contracts=1); no broker submit / order / 2FA import —
chain reads use the AST-proven read-only options_chain adapter. This module
writes NOTHING — queue writes belong to the scanner via the fail-closed
deep_itm_generator.submit_to_desk_queue upsert.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

# Shared conventions — REUSED, never re-implemented (same package, no broker surface).
from .deep_itm_generator import PAPER_MODEL_BLOCK, _f

STRATEGY_DEBIT = "earnings_put_debit_spread"
STRATEGY_CREDIT = "earnings_put_credit_spread"
FAMILY_DEBIT = "earnings_vertical_debit"
FAMILY_CREDIT = "earnings_vertical_credit"
FAMILY_BY_STRATEGY = {STRATEGY_DEBIT: FAMILY_DEBIT, STRATEGY_CREDIT: FAMILY_CREDIT}

RECOMMENDED_ACTION = {
    STRATEGY_DEBIT: "Review Earnings Put Debit Spread (paper model)",
    STRATEGY_CREDIT: "Review Earnings Put Credit Spread (paper model)",
}
EXECUTION_NOTE_TEMPLATE = (
    "PAPER MODEL — educational earnings-vertical analysis ({label}). Manual "
    "review only; no auto-execution, no live order path. Outcomes feed the "
    "{strategy} validation gate (30 paper outcomes, PF>1.3, WR>55%) before "
    "any live consideration."
)
BLOCKED_REASON = (
    "earnings_put_credit_spread is BLOCKED_INITIAL (registry, loader-enforced "
    "paper_enabled=false) — short-premium event risk (gap-through-strike, "
    "assignment) stays unscannable until the debit lane observes paper "
    "history; direct generation requires an explicit allow_blocked=True"
)

# Disclosed flags (matcher WATCH_FLAGS members — demote pass → watch, never reject)
FLAG_IV_RICH = "iv_rich"
FLAG_HIST_BELOW_BE = "historical_move_below_breakeven"

# MANDATORY credit-lane disclosures (spec Part D) — embedded in every credit row.
CREDIT_DISCLOSURES = {
    "assignment_risk": (
        "ASSIGNMENT RISK — the short put can be assigned at ANY time it is "
        "in the money (American exercise), most likely after the earnings gap "
        "or near expiration/ex-dividend. Assignment delivers 100 long shares "
        "per spread at the short strike; the long put caps the loss but does "
        "NOT prevent assignment."),
    "gap_risk": (
        "GAP RISK — earnings gaps can jump straight through the short strike "
        "overnight with no chance to adjust; the full width-minus-credit max "
        "loss can be realized at the open. Defined risk ≠ small risk."),
    "short_leg_lifecycle": (
        "SHORT-LEG LIFECYCLE — a short option requires active management to "
        "expiration: monitor for early assignment, close or roll before the "
        "final week when ITM, and never let an ITM short leg ride into "
        "expiration (auto-exercise nets a stock position)."),
}

# Width table by underlying price (spec Part C): <50: 2.5 · 50-150: 5 ·
# 150-400: 10 · >400: 20. The adjacent ladder width is also tried.
WIDTH_LADDER: Tuple[float, ...] = (2.5, 5.0, 10.0, 20.0)

DEFAULT_SELECTION: Dict[str, Dict[str, Any]] = {
    STRATEGY_DEBIT: {
        "dte_buckets": [7, 14, 21, 30, 45],
        "earnings_window_days_before": 10,
        "earnings_window_days_after": 2,
        "min_event_confidence": 0.65,
        "required_thesis": "bearish_or_hedge",
        "max_spread_package_slippage_pct": 8.0,
        "min_open_interest_each_leg": 250,
        "min_volume_each_leg": 10,
        "max_debit_pct_of_underlying": 6.0,
        "max_loss_usd_paper": 1000.0,
        "long_delta_range": [0.45, 0.60],   # |delta| window for the long leg
        "atm_proxy_band_pct": 0.05,         # NTM proxy band when no greeks
        "max_proposals_per_run": 5,
        "max_contracts_paper": 1,
    },
    STRATEGY_CREDIT: {
        "dte_buckets": [7, 14, 21, 30, 45],
        "earnings_window_days_before": 10,
        "earnings_window_days_after": 2,
        "min_event_confidence": 0.65,
        "required_thesis": "bullish_or_neutral",
        "min_credit_pct_of_width": 20.0,
        "assignment_risk_required": True,
        "max_spread_package_slippage_pct": 8.0,
        "min_open_interest_each_leg": 250,
        "min_volume_each_leg": 10,
        "max_loss_usd_paper": 1000.0,
        "atm_proxy_band_pct": 0.05,
        "max_proposals_per_run": 5,
        "max_contracts_paper": 1,
    },
}

BEARISH_VERDICTS = frozenset({"sell", "strong_sell", "avoid", "deteriorating",
                              "reduce"})
BULLISH_VERDICTS = frozenset({"buy", "strong_buy"})
NEUTRAL_VERDICTS = frozenset({"hold", "neutral"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


# ── config (registry row is the gate source of record) ───────────────────────

def load_pipeline_config(strategy: str) -> dict:
    """Registry-backed pipeline config for one earnings-vertical strategy.

    The registry row's selection block, liquidity gates, and paper caps overlay
    the defaults above. A LivePolicyViolation is NEVER swallowed (fail-closed);
    other registry outages keep the defaults. paper_only + manual_review_only
    are structural — this lane has no other mode.
    """
    if strategy not in FAMILY_BY_STRATEGY:
        raise ValueError(f"unknown earnings-vertical strategy {strategy!r} "
                         f"(known: {sorted(FAMILY_BY_STRATEGY)})")
    policy = dict(DEFAULT_SELECTION[strategy])
    cfg: Dict[str, Any] = {"strategy_id": strategy,
                           "family": FAMILY_BY_STRATEGY[strategy]}
    from .universe import LivePolicyViolation, load_strategy_registry
    try:
        row = (load_strategy_registry().get("strategies") or {}).get(strategy) or {}
        policy.update({k: v for k, v in (row.get("selection") or {}).items()
                       if v is not None})
        gates = row.get("liquidity_gates") or {}
        if gates.get("min_oi") is not None:
            policy.setdefault("min_open_interest_each_leg", int(gates["min_oi"]))
        if gates.get("min_volume") is not None:
            policy.setdefault("min_volume_each_leg", int(gates["min_volume"]))
        if row.get("max_contracts_paper") is not None:
            policy["max_contracts_paper"] = int(row["max_contracts_paper"])
        cfg["status"] = row.get("status")
        cfg["display_name"] = row.get("display_name")
        cfg["paper_enabled"] = bool(row.get("paper_enabled"))
        cfg["alpaca_paper_enabled"] = bool(row.get("alpaca_paper_enabled"))
    except LivePolicyViolation:
        raise  # the live-policy wall is NEVER swallowed (fail-closed)
    except Exception:
        cfg.setdefault("status", "TESTING_PAPER" if strategy == STRATEGY_DEBIT
                       else "BLOCKED_INITIAL")
        cfg.setdefault("paper_enabled", strategy == STRATEGY_DEBIT)
        cfg.setdefault("alpaca_paper_enabled", False)
    cfg["selection_policy"] = policy
    cfg["paper_only"] = True
    cfg["execution_mode"] = "manual_review_only"
    return cfg


# ── width table ───────────────────────────────────────────────────────────────

def width_for_price(spot: float) -> float:
    """Primary vertical width by underlying price (spec table)."""
    s = _f(spot)
    if s < 50:
        return 2.5
    if s <= 150:
        return 5.0
    if s <= 400:
        return 10.0
    return 20.0


def candidate_widths(spot: float) -> List[float]:
    """Primary width + the adjacent ladder width (next larger; largest rung
    falls back to the next smaller)."""
    primary = width_for_price(spot)
    i = WIDTH_LADDER.index(primary)
    adjacent = WIDTH_LADDER[i + 1] if i + 1 < len(WIDTH_LADDER) else WIDTH_LADDER[i - 1]
    return [primary, adjacent]


# ── thesis + event gates (generator-side wall; the matcher lanes first) ───────

def _thesis_ok(strategy: str, thesis_ctx: dict) -> bool:
    """bearish_or_hedge for the debit lane; bullish_or_neutral for credit."""
    ctx = thesis_ctx or {}
    verdict = str(ctx.get("verdict") or "").strip().lower()
    direction = str(ctx.get("thesis_direction") or "").strip().lower()
    src = str(ctx.get("conviction_source") or "")
    if strategy == STRATEGY_DEBIT:
        return (verdict in BEARISH_VERDICTS
                or direction == "bearish"
                or (bool(ctx.get("hedge_of_held")) and _f(ctx.get("held_shares")) > 0)
                or src in ("explicit_bearish_thesis", "hedge_of_held")
                or (src.startswith("watchlist_")
                    and src[len("watchlist_"):] in BEARISH_VERDICTS))
    return (verdict in BULLISH_VERDICTS or verdict in NEUTRAL_VERDICTS
            or direction == "bullish"
            or (src.startswith("watchlist_")
                and src[len("watchlist_"):] in BULLISH_VERDICTS))


def _event_gate(strategy: str, event_json: dict, policy: dict,
                thesis_ctx: dict) -> Optional[Dict[str, str]]:
    """None when generation may proceed; else {gate, reason} (honest refusal)."""
    ev = event_json or {}
    window = ev.get("event_window") or {}
    if not (ev.get("earnings_date") or {}).get("date") or not window.get("in_window"):
        days = ev.get("days_to_earnings")
        detail = (f"days_to_earnings={days}" if days is not None
                  else (ev.get("earnings_date") or {}).get("reason") or "no earnings date")
        return {"gate": "event_window",
                "reason": f"no earnings in window ({detail}; window "
                          f"−{window.get('days_after')}..{window.get('days_before')}d)"}
    if not _thesis_ok(strategy, thesis_ctx):
        need = ("bearish/hedge thesis missing" if strategy == STRATEGY_DEBIT
                else "bullish/neutral thesis missing")
        return {"gate": "thesis", "reason": need}
    min_conf = _f(policy.get("min_event_confidence"), 0.65)
    conf = _f(ev.get("event_confidence"))
    if conf < min_conf:
        return {"gate": "event_confidence",
                "reason": f"event_confidence {conf:.2f} below gate {min_conf:.2f}"}
    return None


# ── chain helpers ─────────────────────────────────────────────────────────────

def _usable(c: dict) -> bool:
    b, a = _f(c.get("bid")), _f(c.get("ask"))
    return bool(b > 0 and a >= b and c.get("mid") is not None)


def _event_exp_row(snapshot: dict, exp: str) -> Optional[dict]:
    for e in (snapshot or {}).get("expirations") or []:
        if str(e.get("exp") or "")[:10] == str(exp)[:10]:
            return e
    return None


def _puts_of(exp_row: dict) -> List[dict]:
    return [c for c in (exp_row.get("contracts") or [])
            if c.get("side") == "put" and _f(c.get("strike")) > 0 and _usable(c)]


def _select_long_put(puts: List[dict], spot: float, policy: dict) -> Dict[str, Any]:
    """Long put ATM/slightly ITM: |delta| in long_delta_range; NTM proxy
    (±atm_proxy_band_pct of spot, ITM-side preferred) when no usable greeks."""
    lo, hi = sorted(abs(float(x)) for x in (policy.get("long_delta_range")
                                            or [0.45, 0.60]))
    with_delta = [c for c in puts if c.get("delta") is not None]
    if with_delta:
        in_band = [c for c in with_delta if lo <= abs(_f(c.get("delta"))) <= hi]
        if not in_band:
            return {"mode": "delta", "leg": None,
                    "reason": f"no puts with |delta| in [{lo}, {hi}]"}
        mode, pool = "delta", in_band
    else:
        band = _f(policy.get("atm_proxy_band_pct"), 0.05)
        pool = [c for c in puts if abs(_f(c.get("strike")) - spot) / spot <= band]
        if not pool:
            return {"mode": "atm_proxy", "leg": None,
                    "reason": f"no puts within ±{band:.0%} of spot (NTM proxy band)"}
        mode = "atm_proxy"
    # nearest the money; ties prefer the slightly-ITM side (strike ≥ spot)
    best = sorted(pool, key=lambda c: (abs(_f(c.get("strike")) - spot),
                                       0 if _f(c.get("strike")) >= spot else 1))[0]
    return {"mode": mode, "leg": best}


def _short_put_candidates(puts: List[dict], spot: float, long_strike: float,
                          event_json: dict) -> List[dict]:
    """Short-strike candidates below the long leg: expected-move boundary
    (highest strike ≤ spot × (1 − implied_move_pct/100)) plus width-table
    targets snapped to listed strikes. Deduped, methods disclosed."""
    below = sorted((c for c in puts if _f(c.get("strike")) < long_strike),
                   key=lambda c: -_f(c.get("strike")))
    out: List[dict] = []
    seen: set = set()

    im = (event_json or {}).get("implied_move_pct") or {}
    if im.get("available") and _f(im.get("pct")) > 0:
        boundary = round(spot * (1.0 - _f(im["pct"]) / 100.0), 4)
        at_or_below = [c for c in below if _f(c.get("strike")) <= boundary]
        if at_or_below:
            c = at_or_below[0]           # highest strike at/below the boundary
            seen.add(_f(c.get("strike")))
            out.append({"leg": c, "method": "expected_move_boundary",
                        "boundary": boundary})
    for width in candidate_widths(spot):
        target = long_strike - width
        snapped = min(below, default=None,
                      key=lambda c: abs(_f(c.get("strike")) - target))
        if snapped is None:
            continue
        k = _f(snapped.get("strike"))
        if k in seen:
            continue
        seen.add(k)
        out.append({"leg": snapped, "method": f"width_table_{width:g}",
                    "target": target})
    return out


# ── gates over one packaged spread ───────────────────────────────────────────

def evaluate_spread_gates(strategy: str, pkg: dict, spot: float, policy: dict,
                          event_json: dict) -> Dict[str, Any]:
    """{"pass", "rejects", "flags"} for one packaged vertical (honest names)."""
    rejects: List[str] = []
    flags: List[str] = []
    net = _f(pkg.get("net"))            # debit (debit lane) / credit (credit lane)
    width = _f(pkg.get("width"))

    if net <= 0:
        rejects.append("non_positive_debit" if strategy == STRATEGY_DEBIT
                       else "non_positive_credit")
    if width <= 0:
        rejects.append("non_positive_width")
    if strategy == STRATEGY_DEBIT and 0 < width <= net:
        rejects.append("debit_ge_width_no_profit_possible")
    if strategy == STRATEGY_CREDIT and 0 < width <= net:
        rejects.append("credit_ge_width_data_error")

    # Package slippage: Σ(leg ask−bid) vs the package mid
    slip_abs = sum(max(0.0, _f(l.get("ask")) - _f(l.get("bid")))
                   for l in (pkg["long"], pkg["short"]))
    cap = _f(policy.get("max_spread_package_slippage_pct"), 8.0)
    if net > 0:
        slip_pct = round(slip_abs / net * 100.0, 2)
        pkg["package_slippage_pct"] = slip_pct
        if slip_pct > cap:
            rejects.append(f"package_slippage_{slip_pct:.1f}pct_gt_{cap:g}")

    # Per-leg OI / volume floors
    min_oi = int(_f(policy.get("min_open_interest_each_leg"), 250))
    min_vol = int(_f(policy.get("min_volume_each_leg"), 10))
    for name, leg in (("long", pkg["long"]), ("short", pkg["short"])):
        oi, vol = int(_f(leg.get("oi"))), int(_f(leg.get("volume")))
        if oi < min_oi:
            rejects.append(f"{name}_leg_oi_{oi}_lt_{min_oi}")
        if vol < min_vol:
            rejects.append(f"{name}_leg_volume_{vol}_lt_{min_vol}")

    if strategy == STRATEGY_DEBIT:
        dcap = _f(policy.get("max_debit_pct_of_underlying"), 6.0)
        if spot > 0 and net > 0:
            dpct = round(net / spot * 100.0, 2)
            pkg["debit_pct_of_underlying"] = dpct
            if dpct > dcap:
                rejects.append(f"debit_{dpct:.1f}pct_of_underlying_gt_{dcap:g}")
    else:
        ccap = _f(policy.get("min_credit_pct_of_width"), 20.0)
        if width > 0:
            cpct = round(net / width * 100.0, 2)
            pkg["credit_pct_of_width"] = cpct
            if cpct < ccap:
                rejects.append(f"credit_{cpct:.1f}pct_of_width_lt_{ccap:g}")

    ml_cap = _f(policy.get("max_loss_usd_paper"), 1000.0)
    max_loss = _f(pkg.get("max_loss"))
    if max_loss > ml_cap:
        rejects.append(f"max_loss_{max_loss:.0f}_gt_max_loss_usd_paper_{ml_cap:.0f}")

    # Disclosed flags (never reject)
    if FLAG_IV_RICH in ((event_json or {}).get("risk_flags") or []):
        flags.append(FLAG_IV_RICH)
    hist = (event_json or {}).get("historical_earnings_moves") or {}
    req = pkg.get("required_move_to_breakeven_pct")
    if (strategy == STRATEGY_DEBIT and hist.get("available")
            and req is not None and _f(hist.get("avg_abs_move_pct")) < _f(req)):
        flags.append(FLAG_HIST_BELOW_BE)

    return {"pass": not rejects, "rejects": rejects, "flags": flags}


# ── scoring + ids ─────────────────────────────────────────────────────────────

def score_spread(pkg: dict, event_confidence: float) -> float:
    """Edge = mean(R:R fit, leg liquidity) × event_confidence (0-100).

    R:R fit saturates at 3:1 (100 points); liquidity is the mean leg
    liquidity_score. Missing pieces lower the score — never invented.
    """
    rr = max(0.0, min(_f(pkg.get("reward_to_risk")), 3.0)) / 3.0 * 100.0
    liq = (_f(pkg["long"].get("liquidity_score"))
           + _f(pkg["short"].get("liquidity_score"))) / 2.0
    return round((rr + liq) / 2.0 * _clamp01(_f(event_confidence)), 1)


def _k(strike: Any) -> str:
    return f"{_f(strike):g}".replace(".", "p")


def spread_proposal_id(strategy: str, sym: str, long_strike: Any,
                       short_strike: Any, exp: str) -> str:
    """opt_<strategy>_SYM_paper_model_<longK>x<shortK>_<exp> (deterministic)."""
    return (f"opt_{strategy}_{(sym or '').upper()}_paper_model_"
            f"{_k(long_strike)}x{_k(short_strike)}_"
            f"{str(exp or '')[:10].replace('-', '')}")


# ── proposal row (desk-queue shape — ATM/deep-ITM conventions) ───────────────

def _leg_disclosure(leg: dict, side: str) -> dict:
    """meta.strategy_json.legs entry: {side, type, strike, exp, mid, oi,
    volume, spread_pct} (spec Part C)."""
    return {"side": side, "type": "put", "strike": _f(leg.get("strike")),
            "exp": str(leg.get("exp") or "")[:10], "mid": leg.get("mid"),
            "oi": leg.get("oi"), "volume": leg.get("volume"),
            "spread_pct": leg.get("spread_pct")}


def _leg_order_shape(sym: str, exp: str, leg: dict, side: str) -> dict:
    """Top-level legs[] entry in the shape the guarded Alpaca spread lane
    parses (underlying/expiration/strike/option_type/side/ratio_qty)."""
    return {"underlying": sym, "expiration": str(exp)[:10],
            "strike": _f(leg.get("strike")), "option_type": "put",
            "side": side, "ratio_qty": 1}


def _build_spread_row(strategy: str, sym: str, spot: float, exp: str, dte: Any,
                      pkg: dict, gate: dict, event_json: dict,
                      thesis_ctx: dict, cfg: dict) -> dict:
    family = FAMILY_BY_STRATEGY[strategy]
    is_debit = strategy == STRATEGY_DEBIT
    long_leg, short_leg = pkg["long"], pkg["short"]
    net = _f(pkg["net"])
    edge = score_spread(pkg, _f((event_json or {}).get("event_confidence")))
    ivc = (event_json or {}).get("iv_context") or {}
    im = (event_json or {}).get("implied_move_pct") or {}
    hist = (event_json or {}).get("historical_earnings_moves") or {}
    flags = list(gate.get("flags") or [])

    try:
        import options_desk_enterprise as ent
        tier = ent.desk_tier(edge)
    except Exception:
        tier = "A" if edge >= 72 else ("B" if edge >= 62 else "C")

    label = ("earnings put DEBIT spread" if is_debit
             else "earnings put CREDIT spread")
    reasoning_bits = [
        f"{label}: long ${_f(long_leg.get('strike')):g}P / "
        f"short ${_f(short_leg.get('strike')):g}P {str(exp)[:10]} "
        f"(width ${_f(pkg['width']):g})",
        (f"net debit ${net:.2f} (${_f(pkg['max_loss']):,.0f} max loss) · "
         f"max gain ${_f(pkg['max_gain']):,.0f} · R:R {pkg['reward_to_risk']}"
         if is_debit else
         f"net credit ${net:.2f} ({pkg.get('credit_pct_of_width')}% of width) · "
         f"max loss ${_f(pkg['max_loss']):,.0f} · max gain ${_f(pkg['max_gain']):,.0f}"),
        f"breakeven ${_f(pkg['breakeven']):.2f} "
        f"({_f(pkg['breakeven_move_pct']):+.1f}%)",
        (f"implied event move {im.get('pct')}%" if im.get("available")
         else "implied event move unavailable"),
        (f"historical avg |move| {hist.get('avg_abs_move_pct')}% "
         f"({hist.get('samples')} sample(s))" if hist.get("available")
         else "no historical earnings-move data"),
        f"event confidence {(event_json or {}).get('event_confidence')} · "
        f"thesis: {thesis_ctx.get('conviction_source') or 'unknown'}",
    ]
    if flags:
        reasoning_bits.append("flags: " + ", ".join(flags))
    if not is_debit:
        reasoning_bits.append("SHORT PREMIUM — assignment + gap risk disclosed "
                              "in meta.disclosures (BLOCKED_INITIAL lane)")
    reasoning_bits.append("PAPER MODEL — manual review only, never auto-executed")

    earnings_date = ((event_json or {}).get("earnings_date") or {}).get("date")
    row = {
        "id": spread_proposal_id(strategy, sym, long_leg.get("strike"),
                                 short_leg.get("strike"), exp),
        "strategy": strategy,
        "strategy_family": family,
        "symbol": sym,
        "underlying": sym,
        "account": "",
        "account_display": "Paper Model (educational)",
        "broker": "paper_model",
        "side": "BUY" if is_debit else "SELL",       # net premium direction
        "option_type": "put",
        "structure": "vertical_spread",
        "strike": _f(long_leg.get("strike")),        # primary (long) leg strike
        "long_strike": _f(long_leg.get("strike")),
        "short_strike": _f(short_leg.get("strike")),
        "width": pkg["width"],
        "expiration": str(exp)[:10],
        "dte": dte,
        "contracts": 1,
        "spreads": 1,                                # ONE spread max (alpaca lane cap)
        "premium": round(net, 4),                    # net package mid (per share)
        "premium_total": round(net * 100.0, 2),
        **({"net_debit": round(net, 4)} if is_debit
           else {"net_credit": round(net, 4)}),
        "legs": [_leg_order_shape(sym, exp, long_leg, "buy"),
                 _leg_order_shape(sym, exp, short_leg, "sell")],
        "underlying_price": round(spot, 2),
        "pop_pct": None,
        "max_profit": pkg["max_gain"],
        "max_loss": pkg["max_loss"],
        "breakeven": pkg["breakeven"],
        "breakeven_move_pct": pkg["breakeven_move_pct"],
        "risk_reward": pkg["reward_to_risk"],
        "reward_to_risk": pkg["reward_to_risk"],
        "expected_value": None,
        "edge_score": edge,
        "iv_rank": (round(_f(ivc.get("iv_rank")), 1)
                    if ivc.get("available") and ivc.get("iv_rank") is not None
                    else None),
        "iv_context": ivc,
        "delta": long_leg.get("delta"),
        "oi": min(int(_f(long_leg.get("oi"))), int(_f(short_leg.get("oi")))),
        "volume": min(int(_f(long_leg.get("volume"))),
                      int(_f(short_leg.get("volume")))),
        "spread_pct": max(_f(long_leg.get("spread_pct")),
                          _f(short_leg.get("spread_pct"))),
        "liquidity_score": round((_f(long_leg.get("liquidity_score"))
                                  + _f(short_leg.get("liquidity_score"))) / 2.0, 1),
        "severity": "info",
        "recommended_action": RECOMMENDED_ACTION[strategy],
        "action_buttons": [
            {"action": "review_chain", "label": "View Chain"},
            {"action": "hold", "label": "Pass"},
        ],
        "reasoning": " · ".join(reasoning_bits),
        "quality_pass": True,
        "data_source": "schwab_chain",
        # ── paper/educational lane flags (HARD SAFETY — test-enforced) ──
        "educational_paper_model": True,
        "requires_manual_review": True,
        "paper_only": True,
        "execution_mode": "manual_review_only",
        "execution_label": "Paper model · manual review only",
        "auto_eligible": False,
        "execution_note": EXECUTION_NOTE_TEMPLATE.format(label=label,
                                                         strategy=strategy),
        "desk_tier": tier,
        "enterprise": {
            "tier": tier,
            "live_eligible": False,      # desk fail-closed: approve+submit refuse
            "blocks": [PAPER_MODEL_BLOCK],
            "earnings": {
                # the EVENT is the trade — earnings before expiry by design
                "in_blackout": True,
                "next_earnings": earnings_date,
                "event_lane": True,
            },
            "liquidity": {
                "pass": True,
                "oi": min(int(_f(long_leg.get("oi"))),
                          int(_f(short_leg.get("oi")))),
                "volume": min(int(_f(long_leg.get("volume"))),
                              int(_f(short_leg.get("volume")))),
                "bid_ask_spread_pct": max(_f(long_leg.get("spread_pct")),
                                          _f(short_leg.get("spread_pct"))),
                "mid": round(net, 4),
                "issues": [],
            },
            "vol_analytics": None,
            "approval_required": True,
            "paper_model": True,
        },
        "meta": {
            "strategy_json": {
                "strategy_id": strategy,
                "family": family,
                "direction": "bearish" if is_debit else "bullish_or_neutral",
                "display_name": cfg.get("display_name") or strategy,
                "legs": [_leg_disclosure(dict(long_leg, exp=exp), "buy"),
                         _leg_disclosure(dict(short_leg, exp=exp), "sell")],
                "selection_policy": dict(cfg.get("selection_policy") or {}),
            },
            "event_json": event_json,
            "gate_flags": flags,
            "short_strike_method": pkg.get("short_method"),
            "selection_mode": pkg.get("selection_mode"),
            "underlying_intel": {
                "conviction": _f(thesis_ctx.get("conviction")),
                "conviction_source": thesis_ctx.get("conviction_source"),
                "watchlist_verdict": thesis_ctx.get("verdict"),
                "held_shares": thesis_ctx.get("held_shares"),
                "hedge_of_held": bool(thesis_ctx.get("hedge_of_held")),
                "thesis_direction": "bearish" if is_debit else "bullish_or_neutral",
            },
            "analysis": {
                "strategy": strategy,
                "underlying_price": spot,
                ("debit" if is_debit else "credit"): round(net, 4),
                "max_loss": pkg["max_loss"],
                "max_gain": pkg["max_gain"],
                "breakeven": pkg["breakeven"],
                "breakeven_move_pct": pkg["breakeven_move_pct"],
                "required_move_to_breakeven_pct":
                    pkg.get("required_move_to_breakeven_pct"),
                "reward_to_risk": pkg["reward_to_risk"],
                "width": pkg["width"],
                "package_slippage_pct": pkg.get("package_slippage_pct"),
                **({"debit_pct_of_underlying": pkg.get("debit_pct_of_underlying")}
                   if is_debit else
                   {"credit_pct_of_width": pkg.get("credit_pct_of_width")}),
                "implied_move_pct": im.get("pct") if im.get("available") else None,
                "historical_avg_abs_move_pct":
                    hist.get("avg_abs_move_pct") if hist.get("available") else None,
                "implied_vs_historical": (
                    f"implied {im.get('pct')}% vs historical avg "
                    f"{hist.get('avg_abs_move_pct')}%"
                    if im.get("available") and hist.get("available")
                    else "incomplete — one or both move estimates unavailable"),
                "event_confidence": (event_json or {}).get("event_confidence"),
                "generated_at": _now_iso(),
            },
        },
        "generated_at": _now_iso(),
    }
    if not is_debit:
        # MANDATORY short-premium disclosures (registry assignment_risk_required)
        row["meta"]["disclosures"] = dict(CREDIT_DISCLOSURES)
        row["blocked_initial"] = True
    return row


# ── packaging math ────────────────────────────────────────────────────────────

def _package(strategy: str, spot: float, long_leg: dict, short_leg: dict,
             method: str, mode: str) -> dict:
    """Vertical package math from leg mids (spec Part C).

    Debit lane (long = higher strike): net = long mid − short mid;
    max_loss = net×100; max_gain = (width − net)×100; breakeven = long − net.
    Credit lane (short = higher strike): net = short mid − long mid;
    max_gain = net×100; max_loss = (width − net)×100; breakeven = short − net.
    """
    lk, sk = _f(long_leg.get("strike")), _f(short_leg.get("strike"))
    lm, sm = _f(long_leg.get("mid")), _f(short_leg.get("mid"))
    if strategy == STRATEGY_DEBIT:
        net = round(lm - sm, 4)
        width = round(lk - sk, 4)
        max_loss = round(net * 100.0, 2)
        max_gain = round((width - net) * 100.0, 2)
        breakeven = round(lk - net, 4)
    else:
        net = round(sm - lm, 4)
        width = round(sk - lk, 4)
        max_gain = round(net * 100.0, 2)
        max_loss = round((width - net) * 100.0, 2)
        breakeven = round(sk - net, 4)
    be_move = round((breakeven / spot - 1.0) * 100.0, 2) if spot else None
    rr = round(max_gain / max_loss, 2) if max_loss > 0 else None
    return {"long": long_leg, "short": short_leg, "net": net, "width": width,
            "max_loss": max_loss, "max_gain": max_gain, "breakeven": breakeven,
            "breakeven_move_pct": be_move,
            # down-move the debit breakeven requires (positive %, disclosure)
            "required_move_to_breakeven_pct": (round(-be_move, 2)
                                               if be_move is not None
                                               and strategy == STRATEGY_DEBIT
                                               else None),
            "reward_to_risk": rr, "short_method": method,
            "selection_mode": mode}


# ── main generators (spec Parts C + D) ───────────────────────────────────────

def _generate(strategy: str, underlying: Any, event_json: Optional[dict],
              config: Optional[dict], thesis_ctx: Optional[dict],
              snapshot: Optional[dict], chain_fn: Optional[Callable[..., dict]]
              ) -> dict:
    if isinstance(underlying, dict):
        sym = (underlying.get("symbol") or "").strip().upper()
        merged_ctx = dict(underlying)
    else:
        sym = str(underlying or "").strip().upper()
        merged_ctx = {}
    merged_ctx.update(thesis_ctx or {})

    cfg = config or load_pipeline_config(strategy)
    policy = dict(DEFAULT_SELECTION[strategy])
    policy.update(cfg.get("selection_policy") or {})
    cfg = dict(cfg, selection_policy=policy)

    base = {"strategy": strategy, "symbol": sym,
            "family": FAMILY_BY_STRATEGY[strategy], "generated_at": _now_iso(),
            "count": 0, "proposals": [], "reject_notes": []}
    if not sym:
        return {**base, "available": False, "reason": "no symbol given"}

    # Chain snapshot (shared with the event model when the caller built one)
    snap = snapshot
    if snap is None:
        if chain_fn is None:
            from lib.strategy_research.options_chain import fetch_chain_snapshot as chain_fn  # noqa: F811
        try:
            snap = chain_fn(sym)
        except Exception as e:
            snap = {"available": False,
                    "reason": f"chain adapter error: {str(e)[:120]}"}

    # Event context (caller-built preferred; live build degrades honestly)
    ev = event_json
    if ev is None:
        from .earnings_event_model import build_event_json
        ev = build_event_json(sym, chain_snapshot=snap, config=policy,
                              context=merged_ctx)

    # Generator-side event wall (the matcher lanes these first — defense in depth)
    gate = _event_gate(strategy, ev, policy, merged_ctx)
    if gate is not None:
        return {**base, "available": False, "event_json": ev, **gate}

    if not (snap or {}).get("available"):
        return {**base, "available": False, "degraded": True, "event_json": ev,
                "reason": (snap or {}).get("reason") or "chain unavailable"}
    spot = _f(snap.get("underlying_price"))
    if spot <= 0:
        return {**base, "available": False, "degraded": True, "event_json": ev,
                "reason": "chain carried no underlying price — refusing to "
                          "compute strikes from fabricated data"}

    event_exp = ev.get("nearest_expiration_after_earnings") or {}
    if not event_exp.get("available"):
        return {**base, "available": False, "event_json": ev,
                "gate": "event_expiration",
                "reason": f"no expiration after earnings: "
                          f"{event_exp.get('reason') or 'unknown'}"}
    exp = event_exp["exp"]
    exp_row = _event_exp_row(snap, exp)
    if exp_row is None:
        return {**base, "available": False, "degraded": True, "event_json": ev,
                "reason": f"event expiration {exp} missing from the chain snapshot"}
    dte = exp_row.get("dte", event_exp.get("dte"))
    puts = _puts_of(exp_row)
    if not puts:
        return {**base, "available": False, "event_json": ev,
                "reason": "no puts with usable two-sided quotes at the event "
                          "expiration"}

    reject_notes: List[str] = []
    proposals: List[dict] = []

    if strategy == STRATEGY_DEBIT:
        sel = _select_long_put(puts, spot, policy)
        if sel.get("leg") is None:
            return {**base, "available": True, "event_json": ev,
                    "reject_notes": [sel.get("reason") or "no long-leg candidate"]}
        long_leg = dict(sel["leg"], exp=exp)
        for cand in _short_put_candidates(puts, spot,
                                          _f(long_leg.get("strike")), ev):
            short_leg = dict(cand["leg"], exp=exp)
            pkg = _package(strategy, spot, long_leg, short_leg,
                           cand["method"], sel["mode"])
            g = evaluate_spread_gates(strategy, pkg, spot, policy, ev)
            key = f"${_f(long_leg.get('strike')):g}x${_f(short_leg.get('strike')):g}"
            if g["pass"]:
                proposals.append(_build_spread_row(
                    strategy, sym, spot, exp, dte, pkg, g, ev, merged_ctx, cfg))
            else:
                reject_notes.append(f"{key} [{cand['method']}]: "
                                    + ",".join(g["rejects"]))
        if not proposals and not reject_notes:
            reject_notes.append("no short-strike candidate below the long leg")
    else:
        # Credit: short put below the expected-move boundary (or width table
        # fallback when the implied move is unavailable), long put lower.
        shorts = _short_put_candidates(puts, spot, spot + 0.01, ev)
        if not shorts:
            reject_notes.append("no short-strike candidate below spot")
        for s_cand in shorts[:1]:        # one short anchor; widths vary the long
            short_leg = dict(s_cand["leg"], exp=exp)
            sk = _f(short_leg.get("strike"))
            lower = sorted((c for c in puts if _f(c.get("strike")) < sk),
                           key=lambda c: -_f(c.get("strike")))
            seen: set = set()
            for width in candidate_widths(spot):
                target = sk - width
                snapped = min(lower, default=None,
                              key=lambda c: abs(_f(c.get("strike")) - target))
                if snapped is None:
                    reject_notes.append(f"no long strike near ${target:g} "
                                        f"below short ${sk:g}")
                    continue
                lk = _f(snapped.get("strike"))
                if lk in seen:
                    continue
                seen.add(lk)
                long_leg = dict(snapped, exp=exp)
                pkg = _package(strategy, spot, long_leg, short_leg,
                               s_cand["method"], "credit")
                g = evaluate_spread_gates(strategy, pkg, spot, policy, ev)
                key = f"${sk:g}x${lk:g}"
                if g["pass"]:
                    proposals.append(_build_spread_row(
                        strategy, sym, spot, exp, dte, pkg, g, ev,
                        merged_ctx, cfg))
                else:
                    reject_notes.append(f"{key} [width {width:g}]: "
                                        + ",".join(g["rejects"]))

    proposals.sort(key=lambda p: -_f(p.get("edge_score")))
    proposals = proposals[: max(1, int(policy.get("max_proposals_per_run") or 5))]
    return {**base, "available": True, "underlying_price": spot,
            "event_expiration": exp, "event_json": ev,
            "count": len(proposals), "proposals": proposals,
            "reject_notes": reject_notes[:8]}


def generate_put_debit_spreads(
    underlying: Any,
    event_json: Optional[dict] = None,
    config: Optional[dict] = None,
    thesis_ctx: Optional[dict] = None,
    *,
    snapshot: Optional[dict] = None,
    chain_fn: Optional[Callable[..., dict]] = None,
) -> dict:
    """Earnings put DEBIT spread paper proposals for ONE underlying (Part C).

    Generates ONLY when the event window is open AND the thesis is
    bearish_or_hedge AND event_confidence ≥ min_event_confidence; otherwise
    an honest {"available": False, "gate", "reason"}. event_json defaults to a
    live earnings_event_model.build_event_json; snapshot/chain_fn are
    injectable for tests. Writes NOTHING.
    """
    return _generate(STRATEGY_DEBIT, underlying, event_json, config,
                     thesis_ctx, snapshot, chain_fn)


def generate_put_credit_spreads(
    underlying: Any,
    event_json: Optional[dict] = None,
    config: Optional[dict] = None,
    thesis_ctx: Optional[dict] = None,
    *,
    snapshot: Optional[dict] = None,
    chain_fn: Optional[Callable[..., dict]] = None,
    allow_blocked: bool = False,
) -> dict:
    """Earnings put CREDIT spread model (Part D) — BLOCKED_INITIAL.

    The registry row is BLOCKED_INITIAL, so the matcher/scanner never call
    this; a direct call REFUSES unless allow_blocked=True is passed explicitly
    (tests / operator inspection). Force-generated rows still carry the
    earnings_vertical_credit family (the Alpaca spread lane refuses credit
    families unconditionally) and the mandatory assignment/gap/short-leg
    disclosures in meta.disclosures.
    """
    if not allow_blocked:
        return {"strategy": STRATEGY_CREDIT, "family": FAMILY_CREDIT,
                "symbol": (underlying.get("symbol") if isinstance(underlying, dict)
                           else str(underlying or "")).strip().upper(),
                "available": False, "blocked": True, "gate": "blocked_initial",
                "reason": BLOCKED_REASON, "count": 0, "proposals": [],
                "generated_at": _now_iso()}
    out = _generate(STRATEGY_CREDIT, underlying, event_json, config,
                    thesis_ctx, snapshot, chain_fn)
    out["blocked_initial"] = True
    out["blocked_note"] = BLOCKED_REASON
    return out


if __name__ == "__main__":
    # Smoke: config load only (generation is driven by the matcher/scanner)
    print(json.dumps({
        "debit_config_loaded": bool(load_pipeline_config(STRATEGY_DEBIT)),
        "credit_config_loaded": bool(load_pipeline_config(STRATEGY_CREDIT)),
        "families": FAMILY_BY_STRATEGY,
        "width_table": {"40": width_for_price(40), "100": width_for_price(100),
                        "300": width_for_price(300), "500": width_for_price(500)},
    }, indent=2))
