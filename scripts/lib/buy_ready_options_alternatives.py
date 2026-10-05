"""Directional options alternatives for a BUY_READY / ENTRY_NEAR equity plan.

M5 2026-09-24 (operator: "build options"). The V BUY_READY page could never show
an options alternative: the only cached idea was a covered call (wrong class for
an entry), debit verticals were never generated, and LEAPS were capped out by
options_engine.MAX_DTE=60. This module ranks the directional expressions of the
SAME equity plan from a normalized read-only chain:

    long_call            0.60-0.70 delta,   45-120 DTE
    debit_call_vertical  long ~0.60 delta / short near the plan target, 45-120 DTE
    leaps_call           >= 0.75 delta,    270-540 DTE (this path only; the
                         engine's MAX_DTE is untouched)
    cash_secured_put     strike at/below the entry-zone low, 30-60 DTE
                         ("paid to wait"); never on a held name — house rule
                         from options_engine Stage 1E

Every number is PER UNIT (per contract, or per share for the stock row). This
module never sizes, never orders, never picks a quantity (MBI_BEHAVIOR=0). It is
pure: the chain, liquidity gate and earnings check are passed in, so tests make
no broker or network calls. Live callers pass options_desk_enterprise's
liquidity_gate / earnings_blackout_check and a chain from
the Command Center option-chain route (read-only Schwab chain).

Greeks: the normalized chain carries delta only; gamma/theta/vega are
Black-Scholes estimates from the contract IV and are labelled as such.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

SCHEMA = "BuyReadyOptionsAlternatives@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

#: Defaults; override any key with the JSON env var BUY_READY_OPTIONS_CFG.
DEFAULTS: dict[str, Any] = {
    "contract_multiplier": 100,
    "risk_free_rate": 0.04,
    "long_call_delta": [0.60, 0.70],
    "long_call_delta_target": 0.65,
    "long_call_dte": [45, 120],
    "vertical_long_delta_target": 0.60,
    "vertical_dte": [45, 120],
    "leaps_min_delta": 0.75,
    "leaps_delta_target": 0.80,
    "leaps_dte": [270, 540],
    "csp_dte": [30, 60],
    "rr_cap_for_score": 3.0,
    "score_weights": {"reward_risk": 0.40, "pop": 0.30, "liquidity": 0.20, "theta": 0.10},
    "max_spread_pct_for_score": 12.0,
}


def config() -> dict[str, Any]:
    cfg = json.loads(json.dumps(DEFAULTS))
    raw = str(os.environ.get("BUY_READY_OPTIONS_CFG") or "").strip()
    if raw:
        try:
            over = json.loads(raw)
            if isinstance(over, dict):
                cfg.update(over)
        except ValueError:
            pass
    return cfg


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _iv_decimal(iv: Any) -> Optional[float]:
    x = _f(iv)
    if x is None or x <= 0:
        return None
    return x / 100.0 if x > 3 else x


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_greeks(spot: float, strike: float, iv: float, dte: int, right: str, r: float) -> dict[str, Optional[float]]:
    """Black-Scholes greeks PER SHARE. theta per calendar day, vega per 1 vol point."""
    if not (spot and strike and iv and dte) or spot <= 0 or strike <= 0 or iv <= 0 or dte <= 0:
        return {"delta": None, "gamma": None, "theta_per_day": None, "vega_per_vol_pt": None}
    t = dte / 365.0
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * math.sqrt(t))
    d2 = d1 - iv * math.sqrt(t)
    gamma = _norm_pdf(d1) / (spot * iv * math.sqrt(t))
    vega = spot * _norm_pdf(d1) * math.sqrt(t) / 100.0
    if right == "call":
        delta = _norm_cdf(d1)
        theta = (-(spot * _norm_pdf(d1) * iv) / (2 * math.sqrt(t)) - r * strike * math.exp(-r * t) * _norm_cdf(d2)) / 365.0
    else:
        delta = _norm_cdf(d1) - 1.0
        theta = (-(spot * _norm_pdf(d1) * iv) / (2 * math.sqrt(t)) + r * strike * math.exp(-r * t) * _norm_cdf(-d2)) / 365.0
    return {"delta": round(delta, 4), "gamma": round(gamma, 5),
            "theta_per_day": round(theta, 4), "vega_per_vol_pt": round(vega, 4)}


def prob_above(spot: float, level: float, iv: float, dte: int, r: float) -> Optional[float]:
    """Risk-neutral lognormal P(S_T > level) — an ESTIMATE, labelled as such."""
    if not (spot and level and iv and dte) or spot <= 0 or level <= 0 or iv <= 0 or dte <= 0:
        return None
    t = dte / 365.0
    d2 = (math.log(spot / level) + (r - 0.5 * iv * iv) * t) / (iv * math.sqrt(t))
    return round(_norm_cdf(d2), 4)


def _mid(c: dict[str, Any]) -> Optional[float]:
    bid, ask = _f(c.get("bid")), _f(c.get("ask"))
    if bid is not None and ask is not None and ask >= bid and ask > 0:
        return (bid + ask) / 2.0
    last = _f(c.get("last"))
    return last if last and last > 0 else None


def flatten_chain(chain: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalized chain (schwab_transport.normalize_option_chain) -> contract rows."""
    rows: list[dict[str, Any]] = []
    for exp in (chain or {}).get("expirations") or []:
        for c in exp.get("strikes") or []:
            dte = c.get("dte") if c.get("dte") is not None else exp.get("dte")
            strike, dte_i = _f(c.get("strike")), None
            try:
                dte_i = int(dte)
            except (TypeError, ValueError):
                dte_i = None
            if strike is None or dte_i is None:
                continue
            row = dict(c)
            row.update({
                "exp": c.get("exp") or exp.get("exp"),
                "dte": dte_i,
                "strike": strike,
                "right": str(c.get("side") or c.get("right") or "").lower(),
                "mid": _mid(c),
                "iv_dec": _iv_decimal(c.get("iv")),
                "delta": _f(c.get("delta")),
            })
            rows.append(row)
    return rows


def _in(v: Optional[float], lo_hi: Iterable[float]) -> bool:
    lo, hi = list(lo_hi)
    return v is not None and lo <= v <= hi


def _leg(c: dict[str, Any], position: str) -> dict[str, Any]:
    return {"position": position, "right": c["right"], "strike": c["strike"], "exp": c.get("exp"),
            "dte": c["dte"], "delta": c.get("delta"), "bid": _f(c.get("bid")), "ask": _f(c.get("ask")),
            "mid": round(c["mid"], 4) if c.get("mid") else None, "iv": c.get("iv"),
            "oi": c.get("oi"), "volume": c.get("volume")}


def _round(d: dict[str, Any]) -> dict[str, Any]:
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}


class _Ctx:
    def __init__(self, plan: dict[str, Any], cfg: dict[str, Any], liquidity_fn, blackout_fn):
        self.plan = plan
        self.cfg = cfg
        self.mult = float(cfg["contract_multiplier"])
        self.r = float(cfg["risk_free_rate"])
        self.spot = _f(plan.get("price"))
        self.target = _f(plan.get("target"))
        self.plan_stop = _f(plan.get("stop"))
        self.zone_low = _f(plan.get("entry_low"))
        self.symbol = str(plan.get("symbol") or "").upper()
        self.liquidity_fn = liquidity_fn
        self.blackout_fn = blackout_fn

    def liquidity(self, c: dict[str, Any]) -> dict[str, Any]:
        if self.liquidity_fn is None:
            return {"pass": None, "issues": ["liquidity gate not supplied"]}
        try:
            return dict(self.liquidity_fn(c))
        except Exception as exc:  # noqa: BLE001 — a broken gate never blesses a contract
            return {"pass": False, "issues": [f"liquidity gate error {type(exc).__name__}"]}

    def blackout(self, dte: int, strategy: str) -> dict[str, Any]:
        # Reviewer 2026-09-28 (finding 1): no gate is not "no event". A missing or broken earnings
        # check disqualifies the unit at BUILD time, before any alert or review can see it.
        if self.blackout_fn is None:
            return {"in_blackout": True, "trigger": "gate_unavailable", "reason": "earnings check not supplied"}
        try:
            out = dict(self.blackout_fn(self.symbol, dte=dte, strategy=strategy))
        except Exception as exc:  # noqa: BLE001 — fail closed like the enterprise gate
            return {"in_blackout": True, "trigger": "gate_error", "reason": f"earnings check error {type(exc).__name__}"}
        if out.get("in_blackout") is not False:
            out["in_blackout"] = True
            out.setdefault("trigger", "gate_unknown")
            out.setdefault("reason", "earnings check returned no verdict")
        return out


def _long_call_economics(ctx: _Ctx, c: dict[str, Any]) -> dict[str, Any]:
    prem = c["mid"]
    cap = prem * ctx.mult
    be = c["strike"] + prem
    at_target = max(0.0, (ctx.target or 0) - c["strike"]) * ctx.mult
    at_stop = max(0.0, (ctx.plan_stop or 0) - c["strike"]) * ctx.mult
    return _round({
        "capital": cap, "max_loss": cap, "max_gain": None, "breakeven": be,
        "value_at_target_expiry": at_target, "value_at_plan_stop_expiry": at_stop,
        "return_at_target_pct": 100.0 * (at_target - cap) / cap if cap else None,
        "return_at_plan_stop_pct": 100.0 * (at_stop - cap) / cap if cap else None,
        "reward_risk": (at_target - cap) / cap if cap else None,
    })


def _vertical_economics(ctx: _Ctx, lo: dict[str, Any], hi: dict[str, Any]) -> dict[str, Any]:
    debit = lo["mid"] - hi["mid"]
    width = hi["strike"] - lo["strike"]
    cap = debit * ctx.mult
    tgt = ctx.target or 0
    at_target = min(max(tgt - lo["strike"], 0.0), width) * ctx.mult
    at_stop = min(max((ctx.plan_stop or 0) - lo["strike"], 0.0), width) * ctx.mult
    return _round({
        "capital": cap, "max_loss": cap, "max_gain": (width - debit) * ctx.mult,
        "breakeven": lo["strike"] + debit,
        "value_at_target_expiry": at_target, "value_at_plan_stop_expiry": at_stop,
        "return_at_target_pct": 100.0 * (at_target - cap) / cap if cap > 0 else None,
        "return_at_plan_stop_pct": 100.0 * (at_stop - cap) / cap if cap > 0 else None,
        "reward_risk": (at_target - cap) / cap if cap > 0 else None,
    })


def _csp_economics(ctx: _Ctx, c: dict[str, Any]) -> dict[str, Any]:
    prem = c["mid"]
    collateral = c["strike"] * ctx.mult
    max_loss = (c["strike"] - prem) * ctx.mult
    return _round({
        "capital": collateral, "max_loss": max_loss, "max_gain": prem * ctx.mult,
        "breakeven": c["strike"] - prem, "effective_entry_if_assigned": c["strike"] - prem,
        "value_at_target_expiry": prem * ctx.mult,
        "value_at_plan_stop_expiry": (prem - max(0.0, c["strike"] - (ctx.plan_stop or 0))) * ctx.mult,
        "return_at_target_pct": 100.0 * prem * ctx.mult / collateral if collateral else None,
        "return_at_plan_stop_pct": None,
        "reward_risk": (prem * ctx.mult) / max_loss if max_loss > 0 else None,
    })


def _score(ctx: _Ctx, econ: dict[str, Any], pop: Optional[float], liq: dict[str, Any],
           theta_per_day_share: Optional[float]) -> float:
    w = ctx.cfg["score_weights"]
    rr = econ.get("reward_risk") or 0.0
    rr_n = max(0.0, min(float(ctx.cfg["rr_cap_for_score"]), rr)) / float(ctx.cfg["rr_cap_for_score"])
    spread = _f(liq.get("bid_ask_spread_pct"))
    max_sp = float(ctx.cfg["max_spread_pct_for_score"])
    liq_n = max(0.0, 1.0 - (spread / max_sp)) if spread is not None else 0.0
    cap = econ.get("capital") or 0.0
    theta_cost = abs(theta_per_day_share or 0.0) * ctx.mult / cap if cap else 0.0
    theta_n = min(1.0, theta_cost * 100.0)  # % of capital per day, capped
    return round(w["reward_risk"] * rr_n + w["pop"] * (pop or 0.0) + w["liquidity"] * liq_n
                 - w["theta"] * theta_n, 4)


def _neighbours(rows: list[dict[str, Any]], pick: dict[str, Any]) -> list[dict[str, Any]]:
    """±1 strike same expiry and the nearest strike in the adjacent expiries."""
    same_side = [r for r in rows if r["right"] == pick["right"] and r.get("mid")]
    same_exp = sorted({r["strike"] for r in same_side if r["dte"] == pick["dte"]})
    out: list[dict[str, Any]] = []
    if pick["strike"] in same_exp:
        i = same_exp.index(pick["strike"])
        for j in (i - 1, i + 1):
            if 0 <= j < len(same_exp):
                out += [r for r in same_side if r["dte"] == pick["dte"] and r["strike"] == same_exp[j]]
    dtes = sorted({r["dte"] for r in same_side})
    if pick["dte"] in dtes:
        i = dtes.index(pick["dte"])
        for j in (i - 1, i + 1):
            if 0 <= j < len(dtes):
                cands = [r for r in same_side if r["dte"] == dtes[j]]
                if cands:
                    out.append(min(cands, key=lambda r: abs(r["strike"] - pick["strike"])))
    return out


def _describe_neighbour(pick: dict[str, Any], n: dict[str, Any], reason: str) -> dict[str, Any]:
    return {"strike": n["strike"], "exp": n.get("exp"), "dte": n["dte"], "delta": n.get("delta"),
            "mid": round(n["mid"], 4) if n.get("mid") else None, "why_not": reason}


def _pick_single(ctx: _Ctx, rows: list[dict[str, Any]], *, strategy: str, right: str,
                 dte_band: list[int], delta_ok: Callable[[Optional[float]], bool],
                 delta_target: float) -> Optional[dict[str, Any]]:
    cands = [r for r in rows if r["right"] == right and r.get("mid") and _in(r["dte"], dte_band)
             and delta_ok(r.get("delta"))]
    if not cands:
        return None
    return _prefer_liquid(ctx, sorted(cands, key=lambda r: (abs((r.get("delta") or 0) - delta_target), -r["dte"])))


def _prefer_liquid(ctx: _Ctx, ordered: list[dict[str, Any]]) -> dict[str, Any]:
    """First candidate (in preference order) that passes the liquidity gate; else the
    first overall — so a liquid neighbour beats a closer-delta strike with 0 OI or a
    30% spread (live V 2026-09-24), and an all-illiquid band is still reported."""
    if ctx.liquidity_fn is not None:
        for c in ordered:
            if ctx.liquidity(c).get("pass") is True:
                return c
    return ordered[0]


def _finish(ctx: _Ctx, strategy: str, legs: list[dict[str, Any]], econ: dict[str, Any],
            pop: Optional[float], liq: dict[str, Any], earn: dict[str, Any], greeks: dict[str, Any],
            why_strike: str, why_expiry: str, neighbours: list[dict[str, Any]]) -> dict[str, Any]:
    score = _score(ctx, econ, pop, liq, greeks.get("theta_per_day"))
    disq: list[str] = []
    if liq.get("pass") is False:
        disq.append("LIQUIDITY: " + "; ".join(liq.get("issues") or []))
    if earn.get("in_blackout"):
        disq.append("EARNINGS_BLACKOUT" + (f" ({earn.get('reason')})" if earn.get("reason") else ""))
    be = econ.get("breakeven")
    if strategy != "cash_secured_put" and ctx.target is not None and be is not None and be >= ctx.target:
        disq.append(f"BREAKEVEN_AT_OR_ABOVE_TARGET (BE {be:.2f} vs target {ctx.target:.2f})")
    return {
        "strategy": strategy,
        "strategy_gate": earn.get("strategy"),          # what the earnings gate evaluated (canonical id)
        "expiration": (legs[0].get("exp") if legs else None),
        "dte": (legs[0].get("dte") if legs else None),
        "event_date": earn.get("next_earnings") or earn.get("event_date"),
        "gate_version": earn.get("gate_version"),
        "disqualification_reason": "; ".join(disq) or None,
        "legs": legs,
        "per_contract": econ,
        "greeks_per_share": greeks,
        "greeks_source": "delta from chain; gamma/theta/vega Black-Scholes estimate from contract IV",
        "pop_estimate": pop,
        "pop_basis": "risk-neutral lognormal P(price above breakeven at expiry) from contract IV — estimate",
        "liquidity": liq,
        "earnings": earn,
        "score": score,
        "qualified": not disq,
        "disqualified_by": disq,
        "why_this_strike": why_strike,
        "why_this_expiry": why_expiry,
        "neighbours_rejected": neighbours,
    }


def _gate_version_of(blackout_fn) -> Optional[str]:
    if blackout_fn is None:
        return None
    try:
        import options_desk_enterprise as ode  # type: ignore
    except ImportError:
        try:
            from scripts import options_desk_enterprise as ode  # type: ignore
        except ImportError:
            return None
    mod = getattr(blackout_fn, "__module__", "") or ""
    if mod.endswith("options_desk_enterprise") or getattr(blackout_fn, "gate_version", None):
        return getattr(blackout_fn, "gate_version", None) or ode.EARNINGS_GATE_VERSION
    return None


def build_alternatives(
    plan: dict[str, Any],
    chain: Optional[dict[str, Any]],
    *,
    held: bool = False,
    liquidity_fn: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
    blackout_fn: Optional[Callable[..., dict[str, Any]]] = None,
    chain_source: str = "",
    chain_as_of: Optional[str] = None,
    cfg: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Rank directional options expressions of ``plan`` (per-unit only, never sized)."""
    cfg = cfg or config()
    ctx = _Ctx(plan, cfg, liquidity_fn, blackout_fn)
    base: dict[str, Any] = {
        "schema": SCHEMA, "authority": AUTHORITY, "symbol": ctx.symbol,
        "chain_source": chain_source or None, "chain_as_of": chain_as_of,
        "generated_at": now_iso(), "gate_version": None,   # gate_version filled from the first verdict below
        "underlying": ctx.spot, "alternatives": [], "skipped": [],
        "stock_per_share": None, "notes": [],
    }
    if ctx.spot and ctx.plan_stop is not None and ctx.target is not None and ctx.spot > ctx.plan_stop:
        risk = ctx.spot - ctx.plan_stop
        base["stock_per_share"] = _round({
            "capital": ctx.spot, "max_loss_to_plan_stop": risk, "breakeven": ctx.spot,
            "value_at_target": ctx.target - ctx.spot,
            "return_at_target_pct": 100.0 * (ctx.target - ctx.spot) / ctx.spot,
            "return_at_plan_stop_pct": -100.0 * risk / ctx.spot,
            "reward_risk": (ctx.target - ctx.spot) / risk,
        })
    rows = flatten_chain(chain or {})
    if not rows or not ctx.spot:
        base["status"] = "NO_CHAIN"
        base["notes"].append("no usable chain (" + str((chain or {}).get("status") or (chain or {}).get("error")
                                                       or "empty") + ") — no alternatives computed")
        return base

    alts: list[dict[str, Any]] = []

    def greeks_for(c: dict[str, Any]) -> dict[str, Any]:
        g = bs_greeks(ctx.spot, c["strike"], c.get("iv_dec") or 0, c["dte"], c["right"], ctx.r)
        if c.get("delta") is not None:
            g["delta"] = c["delta"]
        return g

    # Long call
    lc = _pick_single(ctx, rows, strategy="long_call", right="call", dte_band=cfg["long_call_dte"],
                      delta_ok=lambda d: _in(d, cfg["long_call_delta"]), delta_target=cfg["long_call_delta_target"])
    if lc:
        econ = _long_call_economics(ctx, lc)
        g = greeks_for(lc)
        pop = prob_above(ctx.spot, econ["breakeven"], lc.get("iv_dec") or 0, lc["dte"], ctx.r)
        nbrs = [_describe_neighbour(lc, n, "delta further from target band centre" if n["dte"] == lc["dte"]
                                    else "expiry further from the preferred horizon")
                for n in _neighbours(rows, lc)]
        alts.append(_finish(
            ctx, "long_call", [_leg(lc, "long")], econ, pop, ctx.liquidity(lc), ctx.blackout(lc["dte"], "long_call"),
            g,
            f"{lc['strike']:.2f} call: delta {lc.get('delta')} is closest to {cfg['long_call_delta_target']} inside "
            f"{cfg['long_call_delta'][0]}–{cfg['long_call_delta'][1]}; breakeven {econ['breakeven']:.2f} vs target "
            f"{ctx.target:.2f}",
            f"{lc.get('exp')} ({lc['dte']} DTE) inside {cfg['long_call_dte'][0]}–{cfg['long_call_dte'][1]} DTE so the "
            "thesis has time to reach target without short-dated decay",
            nbrs))
    else:
        base["skipped"].append({"strategy": "long_call", "reason": "NO_CONTRACT_IN_DELTA_DTE_BAND"})

    # Debit call vertical: long ~0.60 delta, short at/near target, same expiry
    long_leg = _pick_single(ctx, rows, strategy="debit_call_vertical", right="call", dte_band=cfg["vertical_dte"],
                            delta_ok=lambda d: d is not None and 0.0 < d < 1.0,
                            delta_target=cfg["vertical_long_delta_target"])
    if long_leg and ctx.target:
        shorts = [r for r in rows if r["right"] == "call" and r["dte"] == long_leg["dte"] and r.get("mid")
                  and r["strike"] > long_leg["strike"]]
        short = _prefer_liquid(ctx, sorted(shorts, key=lambda r: abs(r["strike"] - ctx.target))) if shorts else None
        if short and long_leg["mid"] > short["mid"]:
            econ = _vertical_economics(ctx, long_leg, short)
            g_l, g_s = greeks_for(long_leg), greeks_for(short)
            g = {k: (round((g_l.get(k) or 0) - (g_s.get(k) or 0), 5)
                     if g_l.get(k) is not None and g_s.get(k) is not None else None) for k in g_l}
            iv_mid = long_leg.get("iv_dec") or short.get("iv_dec") or 0
            pop = prob_above(ctx.spot, econ["breakeven"], iv_mid, long_leg["dte"], ctx.r)
            liq_l, liq_s = ctx.liquidity(long_leg), ctx.liquidity(short)
            liq = {"pass": (liq_l.get("pass") is not False and liq_s.get("pass") is not False),
                   "issues": (liq_l.get("issues") or []) + [f"short leg: {i}" for i in (liq_s.get("issues") or [])],
                   "bid_ask_spread_pct": max(_f(liq_l.get("bid_ask_spread_pct")) or 0,
                                             _f(liq_s.get("bid_ask_spread_pct")) or 0) or None}
            nbrs = [_describe_neighbour(short, n, "short strike further from the plan target")
                    for n in _neighbours(rows, short) if n["dte"] == short["dte"]]
            alts.append(_finish(
                ctx, "debit_call_vertical", [_leg(long_leg, "long"), _leg(short, "short")], econ, pop, liq,
                ctx.blackout(long_leg["dte"], "debit_call_vertical"), g,
                f"long {long_leg['strike']:.2f} (delta {long_leg.get('delta')}, closest to "
                f"{cfg['vertical_long_delta_target']}) / short {short['strike']:.2f} (the liquid strike nearest the plan "
                f"target {ctx.target:.2f}) caps the payoff where the plan expects to exit",
                f"{long_leg.get('exp')} ({long_leg['dte']} DTE) inside {cfg['vertical_dte'][0]}–"
                f"{cfg['vertical_dte'][1]} DTE; the short leg offsets most of the time decay",
                nbrs))
        else:
            base["skipped"].append({"strategy": "debit_call_vertical", "reason": "NO_SHORT_STRIKE_ABOVE_LONG_NEAR_TARGET"})
    else:
        base["skipped"].append({"strategy": "debit_call_vertical", "reason": "NO_LONG_LEG_IN_DTE_BAND"})

    # LEAPS (this path only — options_engine.MAX_DTE is not changed)
    lp = _pick_single(ctx, rows, strategy="leaps_call", right="call", dte_band=cfg["leaps_dte"],
                      delta_ok=lambda d: d is not None and d >= cfg["leaps_min_delta"],
                      delta_target=cfg["leaps_delta_target"])
    if lp:
        econ = _long_call_economics(ctx, lp)
        g = greeks_for(lp)
        pop = prob_above(ctx.spot, econ["breakeven"], lp.get("iv_dec") or 0, lp["dte"], ctx.r)
        nbrs = [_describe_neighbour(lp, n, "delta further from the deep-ITM target" if n["dte"] == lp["dte"]
                                    else "expiry outside or further from the LEAPS horizon")
                for n in _neighbours(rows, lp)]
        alts.append(_finish(
            ctx, "leaps_call", [_leg(lp, "long")], econ, pop, ctx.liquidity(lp), ctx.blackout(lp["dte"], "leaps_call"),
            g,
            f"{lp['strike']:.2f} call: delta {lp.get('delta')} ≥ {cfg['leaps_min_delta']} behaves like stock with a "
            "fixed maximum loss",
            f"{lp.get('exp')} ({lp['dte']} DTE) inside {cfg['leaps_dte'][0]}–{cfg['leaps_dte'][1]} DTE — "
            "low theta per day relative to capital",
            nbrs))
    else:
        base["skipped"].append({"strategy": "leaps_call",
                                "reason": "NO_CONTRACT_IN_LEAPS_BAND (chain may be near-the-money only)"})

    # Cash-secured put below the zone — never on a held name (options_engine Stage 1E house rule)
    if held:
        base["skipped"].append({"strategy": "cash_secured_put",
                                "reason": "HELD_NAME — house rule: no CSP on a name already held (Stage 1E)"})
    elif ctx.zone_low:
        puts = [r for r in rows if r["right"] == "put" and r.get("mid") and _in(r["dte"], cfg["csp_dte"])
                and r["strike"] <= ctx.zone_low]
        if puts:
            cp = max(puts, key=lambda r: (r["strike"], -abs(r["dte"] - sum(cfg["csp_dte"]) / 2)))
            econ = _csp_economics(ctx, cp)
            g = greeks_for(cp)
            pop = prob_above(ctx.spot, econ["breakeven"], cp.get("iv_dec") or 0, cp["dte"], ctx.r)
            nbrs = [_describe_neighbour(cp, n, "strike above the entry zone or further from it") for n in _neighbours(rows, cp)]
            alts.append(_finish(
                ctx, "cash_secured_put", [_leg(cp, "short")], econ, pop, ctx.liquidity(cp),
                ctx.blackout(cp["dte"], "cash_secured_put"), g,
                f"{cp['strike']:.2f} put: highest strike at/below the entry-zone low {ctx.zone_low:.2f}; assignment "
                f"would mean owning at {econ['effective_entry_if_assigned']:.2f}",
                f"{cp.get('exp')} ({cp['dte']} DTE) inside {cfg['csp_dte'][0]}–{cfg['csp_dte'][1]} DTE",
                nbrs))
        else:
            base["skipped"].append({"strategy": "cash_secured_put", "reason": "NO_PUT_AT_OR_BELOW_ZONE_LOW_IN_DTE_BAND"})

    ranked = sorted(alts, key=lambda a: (not a["qualified"], -a["score"]))
    for i, a in enumerate(ranked, 1):
        a["rank"] = i
    base["alternatives"] = ranked
    # gate_version from any verdict, else from the gate module itself (so an empty / NONE block is not
    # mislabelled STALE_PRE_FIX on read — reviewer 2026-09-28 finding 6)
    base["gate_version"] = next((a.get("gate_version") for a in ranked if a.get("gate_version")), None) or _gate_version_of(blackout_fn)
    base["status"] = "OK" if any(a["qualified"] for a in ranked) else ("NONE_QUALIFIED" if ranked else "NONE")
    base["notes"].append("Per-unit economics only (per contract / per share); never a position size.")
    return base


def iv_context(current_iv_pct: Optional[float], history: Optional[list[float]], *,
               proxy_rank: Optional[float] = None, min_rank_rows: int = 5,
               min_percentile_rows: int = 20) -> dict[str, Any]:
    """IV rank (true when history suffices, else labelled proxy) + IV percentile."""
    vals = [v for v in (history or []) if v is not None and v > 0]
    cur = _f(current_iv_pct)
    out: dict[str, Any] = {"current_iv_pct": cur, "history_rows": len(vals),
                           "iv_rank": None, "iv_rank_source": "unavailable", "iv_percentile": None}
    if cur is not None and len(vals) >= min_rank_rows:
        lo, hi = min(vals), max(vals)
        out["iv_rank"] = 50.0 if hi <= lo else round(100.0 * (cur - lo) / (hi - lo), 1)
        out["iv_rank_source"] = "history"
    elif proxy_rank is not None:
        out["iv_rank"] = _f(proxy_rank)
        out["iv_rank_source"] = "proxy"
    if cur is not None and len(vals) >= min_percentile_rows:
        out["iv_percentile"] = round(100.0 * sum(1 for v in vals if v <= cur) / len(vals), 1)
    return out


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _iv_history(symbol: str) -> list[float]:
    """options_iv_history (365d) — read-only; [] when the store is unavailable."""
    try:
        from db_adapter import USE_DB, _execute  # type: ignore
    except ImportError:
        return []
    try:
        if not USE_DB:
            return []
        rows = _execute(
            "SELECT iv_pct FROM options_iv_history WHERE symbol=%s AND captured_at > NOW() - INTERVAL '365 days'",
            (symbol.upper(),), fetch="all") or []
        return [v for v in (_f(r.get("iv_pct")) for r in rows) if v and v > 0]
    except Exception:  # noqa: BLE001
        return []


def _atm_iv_pct(chain: dict[str, Any], spot: Optional[float]) -> Optional[float]:
    rows = [r for r in flatten_chain(chain) if r["right"] == "call" and r.get("iv_dec") and 20 <= r["dte"] <= 60]
    if not rows or not spot:
        return None
    best = min(rows, key=lambda r: abs(r["strike"] - spot))
    return round(best["iv_dec"] * 100.0, 2)


CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "runtime" / "buy_ready_options"


def live_alternatives(plan: dict[str, Any], *, held: bool, proxy_iv_rank: Optional[float] = None,
                      cache_dir: Optional[Path] = None, chain_fetcher=None) -> dict[str, Any]:
    """Read-only chain fetch → ranked alternatives → cached JSON. Never raises.

    Chain: Command Center /api/v2/schwab/option-chain (READ-ONLY; no order surface), wide
    strike window so deep-ITM LEAPS strikes are present. Gates: the enterprise
    liquidity gate and earnings blackout (fail-closed on an unknown calendar).
    """
    sym = str(plan.get("symbol") or "").upper()
    if str(os.environ.get("CIO_ENTRY_OPTIONS_CHAIN") or "on").strip().lower() in ("0", "off", "false", "no"):
        return {"schema": SCHEMA, "symbol": sym, "status": "DISABLED", "alternatives": [], "skipped": [],
                "notes": ["CIO_ENTRY_OPTIONS_CHAIN=off"]}
    strike_count = int(os.environ.get("CIO_ENTRY_OPTIONS_STRIKE_COUNT") or 40)
    # Through the Command Center (operator rule 2026-10-05: alerts never fetch their own data);
    # the CC route is the same read-only Schwab chain, normalized.
    try:
        try:
            from lib.alert_quotes import cc_option_chain  # type: ignore
        except ImportError:
            from scripts.lib.alert_quotes import cc_option_chain  # type: ignore
        chain = (chain_fetcher or cc_option_chain)(sym, strike_count) or {}
    except Exception as exc:  # noqa: BLE001
        chain = {"status": "error", "error": f"Command Center chain unavailable: {type(exc).__name__}: {str(exc)[:100]}"}
    try:
        try:
            import options_desk_enterprise as ode  # type: ignore
        except ImportError:
            from scripts import options_desk_enterprise as ode  # type: ignore
        liq, bo = ode.liquidity_gate, ode.earnings_blackout_check
    except Exception:  # noqa: BLE001
        liq, bo = None, None
    out = build_alternatives(plan, chain, held=held, liquidity_fn=liq, blackout_fn=bo,
                             chain_source="command_center:/api/v2/schwab/option-chain (read-only)", chain_as_of=now_iso())
    out["iv_context"] = iv_context(_atm_iv_pct(chain, _f(plan.get("price"))), _iv_history(sym),
                                   proxy_rank=proxy_iv_rank)
    try:
        d = cache_dir or CACHE_DIR
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{sym}.json").write_text(json.dumps(out, default=str, indent=1), encoding="utf-8")
    except OSError:
        pass
    return out


def load_cached(symbol: str, cache_dir: Optional[Path] = None) -> Optional[dict[str, Any]]:
    try:
        return json.loads(((cache_dir or CACHE_DIR) / f"{symbol.upper()}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


STALE_PRE_FIX = "STALE_PRE_FIX"


def _parse_iso(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        ts = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def staleness(alts: Optional[dict[str, Any]], *, now: Optional[datetime] = None,
              current_gate_version: Optional[str] = None, max_age_s: Optional[float] = None) -> Optional[dict[str, Any]]:
    """Why a STORED alternatives block may no longer be trusted, or None when it is current.

    LP-DEF-02 (live-proof 2026-09-28): the AXTI packet written at 14:20:23Z on release a328a8817 still
    showed ``debit_call_vertical qualified=True`` after the earnings gate was fixed, and every reader
    returned the file verbatim. A stored block is stale when its gate_version is missing (computed before
    the gate stamped verdicts) or differs from the running gate, when generated_at / chain_as_of are
    missing or unparseable (age unknown -> fail closed), or when the chain is older than ``max_age_s``.
    """
    if not isinstance(alts, dict) or not alts or not alts.get("alternatives"):
        return None   # nothing was qualified, so nothing can be stale-qualified
    if current_gate_version is None or max_age_s is None:
        try:
            import options_desk_enterprise as ode  # type: ignore
        except ImportError:
            from scripts import options_desk_enterprise as ode  # type: ignore
        current_gate_version = current_gate_version or ode.EARNINGS_GATE_VERSION
        max_age_s = max_age_s if max_age_s is not None else float(ode.load_desk_config().get("buy_ready_block_max_age_s") or 0)
    gv = alts.get("gate_version")
    gen = alts.get("generated_at") or alts.get("chain_as_of")
    base = {"gate_version_cached": gv, "gate_version_current": current_gate_version,
            "generated_at": alts.get("generated_at"), "chain_as_of": alts.get("chain_as_of")}
    if not gv:
        return {"code": STALE_PRE_FIX, "reason": "no gate_version on the stored verdicts (computed before the 2026-09-28 earnings-gate fix)", **base}
    if gv != current_gate_version:
        return {"code": STALE_PRE_FIX, "reason": f"stored gate_version {gv} != running {current_gate_version}", **base}
    ts = _parse_iso(gen)
    if ts is None:
        return {"code": "STALE_UNKNOWN_AGE", "reason": "generated_at / chain_as_of missing or unparseable — age unknown, fail closed", **base}
    if not max_age_s or float(max_age_s) <= 0:
        return {"code": "STALE_UNKNOWN_AGE", "reason": "no positive buy_ready_block_max_age_s configured — fail closed", **base}
    age = ((now or datetime.now(timezone.utc)) - ts).total_seconds()
    if age < 0 or age > float(max_age_s):
        return {"code": "STALE_CHAIN", "reason": f"stored block is {age:.0f}s old > {float(max_age_s):.0f}s", "age_s": round(age), **base}
    return None


def packet_view(packet: Optional[dict[str, Any]], *, now: Optional[datetime] = None, **kw) -> dict[str, Any]:
    """The READ-SIDE view of a saved BUY_READY packet: never the file verbatim.

    Returns a COPY with ``status`` OK or the stale code; a stale ``options_alternatives`` block has every
    unit forced to ``qualified: False`` with the stale reason prepended to ``disqualified_by`` and
    ``superseded: True`` set, while the original verdicts are kept under ``original`` (the packet on
    disk is immutable incident evidence and is never rewritten). ``as_of`` / ``generated_at`` /
    ``gate_version`` are surfaced at the top so a card can show them (LP-DEF-02).
    """
    if not isinstance(packet, dict):
        return {"status": "NO_PACKET", "packet": None}
    view = json.loads(json.dumps(packet, default=str))
    alts = view.get("options_alternatives")
    stale = staleness(alts, now=now, **kw) if isinstance(alts, dict) else None
    if stale is not None:
        original = {"status": alts.get("status"), "qualified": [a.get("strategy") for a in alts.get("alternatives") or [] if a.get("qualified")]}
        for a in alts.get("alternatives") or []:
            a["qualified"] = False
            a["disqualified_by"] = [f"{stale['code']} ({stale['reason']})"] + list(a.get("disqualified_by") or [])
            a["disqualification_reason"] = "; ".join(a["disqualified_by"])
        alts["status"] = stale["code"]
        alts["superseded"] = True
        alts["stale"] = stale
        alts["original"] = original
    return {
        "status": stale["code"] if stale else "OK",
        "saved_at": view.get("saved_at"),
        "generated_at": (alts or {}).get("generated_at") if isinstance(alts, dict) else None,
        "as_of": (alts or {}).get("chain_as_of") if isinstance(alts, dict) else None,
        "gate_version": (alts or {}).get("gate_version") if isinstance(alts, dict) else None,
        "stale": stale,
        "packet": view,
    }


__all__ = ["SCHEMA", "build_alternatives", "bs_greeks", "config", "flatten_chain", "iv_context",
           "live_alternatives", "load_cached", "prob_above"]
