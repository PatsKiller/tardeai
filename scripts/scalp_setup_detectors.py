#!/usr/bin/env python3
"""Momentum-scalp NAMED SETUP DETECTORS (Layer A) — deterministic, pure, SHADOW.

One detector per canonical setup. Each is a pure function over a context (price-derived facts computed
from 1-minute bars here; external evidence — catalyst, order book, RVOL denominator, market alignment —
passed in) and returns a normalized result:

    {setup_id, state, mandatory_satisfied, mandatory_total, evidence, fail_reasons}

state ∈ SCANNING | ARMED | FIRED | INVALIDATED | EXPIRED | DATA_UNAVAILABLE | OUTSIDE_WINDOW.
FIRED requires ALL mandatory deterministic criteria true on a closed bar / valid book event. A partial
match is ARMED, never FIRED. Required-but-absent data fails CLOSED to DATA_UNAVAILABLE (never inferred).

No I/O, no DB, no network, no order path, no LLM. Reuses the existing trigger FSM (scalp_trigger_engine)
for MICRO PULLBACK and IGNITION BREAKOUT — it does NOT build a second state machine. detect_setups()
runs every enabled detector, applies the session/window gate (scalp_session), retains ALL matches, and
picks the deterministic primary (scalp_setup_registry).
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path
from typing import Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scalp_t0_metrics as t0            # noqa: E402
import scalp_trigger_engine as tfsm      # noqa: E402
import scalp_session as ssess            # noqa: E402
import scalp_setup_registry as sreg      # noqa: E402
import scalp_confirmations as sconf      # noqa: E402  (Layer B overlays)
import scalp_execution_gate as sgate     # noqa: E402  (Layer C universal gate)

_CONF_CFG = None


def _conf_cfg() -> dict:
    global _CONF_CFG
    if _CONF_CFG is None:
        import yaml
        p = Path(__file__).resolve().parent.parent / "config" / "scalp_confirmations.yaml"
        _CONF_CFG = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _CONF_CFG

SCANNING, ARMED, FIRED, INVALIDATED, EXPIRED, DATA_UNAVAILABLE, OUTSIDE_WINDOW = (
    "SCANNING", "ARMED", "FIRED", "INVALIDATED", "EXPIRED", "DATA_UNAVAILABLE", "OUTSIDE_WINDOW")


def normalize_gate_result(execution_gate_result) -> str | None:
    """PURE persistence normalization for the universal execution gate (Defect 1). Maps the detector's
    taxonomy gate result onto the persisted/projected gate_result: PASS->PASS, FAIL->VETO, anything
    missing/unreadable->None (NOT_EVALUATED). NEVER returns PASS unless the detector produced a PASS —
    a DB row must never claim PASS when no successful gate evaluation exists."""
    r = str(execution_gate_result).strip().upper() if execution_gate_result is not None else ""
    if r == "PASS":
        return "PASS"
    if r == "FAIL":
        return "VETO"
    return None

# state precedence when no setup FIRED, for the row's summary setup_state
_STATE_RANK = {FIRED: 6, INVALIDATED: 5, ARMED: 4, DATA_UNAVAILABLE: 3, EXPIRED: 2, OUTSIDE_WINDOW: 1, SCANNING: 0}


def _res(setup_id, state, satisfied, total, evidence=None, fails=None):
    return {"setup_id": setup_id, "state": state, "mandatory_satisfied": int(satisfied),
            "mandatory_total": int(total), "evidence": evidence or {}, "fail_reasons": list(fails or [])}


# ── price-derived helpers (deterministic over bars) ──
def _vwap(bars: Sequence[Mapping]) -> float | None:
    s = tfsm._vwap_series(bars)
    return s[-1] if s else None


def _declining_volume(vols: Sequence[float]) -> bool:
    """Mean of the later half <= mean of the earlier half (deterministic 'declining')."""
    v = [x for x in vols if x is not None]
    if len(v) < 2:
        return False
    mid = len(v) // 2
    early, late = v[:mid] or v[:1], v[mid:]
    return statistics.mean(late) <= statistics.mean(early)


def _trend_from_vwap(bars: Sequence[Mapping], vwap: float | None) -> str | None:
    if vwap is None or len(bars) < 3:
        return None
    closes = [t0._c(b) for b in bars[-5:] if t0._c(b) is not None]
    if len(closes) < 2:
        return None
    if closes[-1] > vwap and closes[-1] >= closes[0]:
        return "up"
    if closes[-1] < vwap and closes[-1] <= closes[0]:
        return "down"
    return None


def opening_range(bars: Sequence[Mapping], cfg: Mapping) -> dict | None:
    """Build the 09:30:00-09:44:59 opening range from REGULAR-session bars ONLY (each bar must carry a
    minute-of-session 'm', added by the logger). Premarket bars (m<0 or absent) are excluded."""
    hi = lo = None
    n = 0
    for b in bars:
        m = b.get("m")
        if m is None or m < 0 or m > 14:     # 0..14 == 09:30..09:44
            continue
        h, l = t0._h(b), t0._l(b)
        if h is not None:
            hi = h if hi is None else max(hi, h)
        if l is not None:
            lo = l if lo is None else min(lo, l)
        n += 1
    if hi is None or lo is None or n == 0:
        return None
    complete = any((b.get("m") is not None and b["m"] >= 14) for b in bars)
    return {"high": hi, "low": lo, "bars": n, "complete": complete}


# ── detectors ──
def detect_ignition_breakout(ctx: Mapping, cfg: Mapping) -> dict:
    """EXISTING engine composite: the trigger FSM fires on the current bar AND the IGN score is above a
    notification lane (not BELOW). Mandatory: (1) TRIGGERED on current bar, (2) IGN lane active."""
    bars = ctx["bars"]
    res = tfsm.run_trigger_engine(bars, cfg)
    cur = len(bars) - 1
    fired = [e for e in tfsm.triggered_fires(res) if e.get("fire_idx") == cur]
    lane = ctx.get("ign_lane")
    ign = ctx.get("ign_score")
    lane_active = lane not in (None, "BELOW")
    sat = int(bool(fired)) + int(lane_active)
    ev = {"trigger": fired[0] if fired else None, "ign_score": ign, "ign_lane": lane}
    if fired and lane_active:
        return _res("SCALP_IGNITION_BREAKOUT_V1", FIRED, sat, 2, ev)
    fails = []
    if not fired:
        fails.append("no_trigger_on_current_bar")
    if not lane_active:
        fails.append("ign_below_lane")
    return _res("SCALP_IGNITION_BREAKOUT_V1", ARMED if sat else SCANNING, sat, 2, ev, fails)


def detect_micro_pullback(ctx: Mapping, cfg: Mapping) -> dict:
    """TradeZella Micro Pullback == the existing impulse/pullback FSM (reused, not duplicated).
    Mandatory: a TRIGGERED fire on the current bar (impulse→declining-vol pullback→reversal-candle
    break, no-chase already enforced inside compute_levels)."""
    bars = ctx["bars"]
    res = tfsm.run_trigger_engine(bars, cfg)
    cur = len(bars) - 1
    fired = [e for e in tfsm.triggered_fires(res) if e.get("fire_idx") == cur]
    # a REJECT with a no-chase reason on the current bar is an explicit refusal, not a fire
    rejects = [e for e in res["events"] if e.get("fire_idx") == cur and e.get("outcome") == "REJECT"]
    if fired:
        ev = {"trigger": fired[0], "fsm_reused": True}
        return _res("SCALP_MICRO_PULLBACK_V1", FIRED, 1, 1, ev)
    fails = [f"reject:{r.get('reason')}" for r in rejects] or ["no_reversal_trigger"]
    state = ARMED if tfsm.ARMED in res.get("trace", []) else SCANNING
    return _res("SCALP_MICRO_PULLBACK_V1", state, 0, 1, {"fsm_reused": True}, fails)


def detect_orb_15(ctx: Mapping, cfg: Mapping) -> dict:
    """15-minute Opening Range Breakout. Mandatory: (1) OR complete, (2) current CLOSED bar closes
    OUTSIDE the OR, (3) breakout-volume confirmation, (4) broader-market alignment (when required)."""
    bars = ctx["bars"]
    orb_cfg = cfg.get("orb", {})
    orr = opening_range(bars, cfg)
    if orr is None or not orr["complete"]:
        return _res("SCALP_ORB_15_BREAKOUT_V1", SCANNING, 0, 4, {"opening_range": orr},
                    ["opening_range_incomplete"])
    cur = bars[-1]
    c, v = t0._c(cur), t0._v(cur)
    up = c is not None and c > orr["high"]
    dn = c is not None and c < orr["low"]
    closed_outside = bool(up or dn)
    # breakout volume: current bar volume >= mult * mean OR-window volume
    or_vols = [t0._v(b) or 0.0 for b in bars if b.get("m") is not None and 0 <= b["m"] <= 14]
    vol_mult = float(orb_cfg.get("breakout_vol_mult", 1.5))
    vol_ok = bool(or_vols and v is not None and v >= vol_mult * statistics.mean(or_vols))
    require_align = bool(orb_cfg.get("require_market_alignment", True))
    aligned = ctx.get("market_aligned")
    align_ok = (aligned is True) if require_align else True
    sat = int(True) + int(closed_outside) + int(vol_ok) + int(align_ok)  # OR-complete counts as 1
    ev = {"opening_range": orr, "close": c, "direction": "up" if up else "down" if dn else None,
          "vol_ok": vol_ok, "market_aligned": aligned}
    fails = []
    if not closed_outside:
        fails.append("close_inside_range")
    if not vol_ok:
        fails.append("insufficient_breakout_volume")
    if require_align and aligned is not True:
        fails.append("market_not_aligned" if aligned is False else "market_alignment_unknown")
    if closed_outside and vol_ok and align_ok:
        return _res("SCALP_ORB_15_BREAKOUT_V1", FIRED, sat, 4, ev)
    return _res("SCALP_ORB_15_BREAKOUT_V1", ARMED if closed_outside else SCANNING, sat, 4, ev, fails)


def detect_vwap_pullback(ctx: Mapping, cfg: Mapping) -> dict:
    """CONTINUATION: price stays on the trend side of VWAP, pulls back toward VWAP on DECLINING volume,
    then resumes. Mandatory: (1) trend established, (2) price on trend side of VWAP, (3) pullback toward
    VWAP on declining volume, (4) resumption bar in the trend direction. Never mean reversion."""
    bars = ctx["bars"]
    if len(bars) < 5:
        return _res("SCALP_VWAP_PULLBACK_V1", SCANNING, 0, 4, {}, ["insufficient_bars"])
    vwap = _vwap(bars)
    trend = ctx.get("trend") or _trend_from_vwap(bars, vwap)
    if vwap is None or trend is None:
        return _res("SCALP_VWAP_PULLBACK_V1", SCANNING, 0, 4, {"vwap": vwap, "trend": trend},
                    ["no_trend_or_vwap"])
    closes = [t0._c(b) for b in bars[-5:]]
    vols = [t0._v(b) for b in bars[-4:-1]]        # pullback window (exclude the resumption bar)
    cur_c, prev_c = t0._c(bars[-1]), t0._c(bars[-2])
    on_trend_side = (trend == "up" and cur_c is not None and cur_c >= vwap) or \
                    (trend == "down" and cur_c is not None and cur_c <= vwap)
    # pullback approached VWAP then resumed
    approached = min((abs(t0._c(b) - vwap) for b in bars[-4:-1] if t0._c(b) is not None), default=None)
    decel = _declining_volume(vols)
    resume = (trend == "up" and cur_c is not None and prev_c is not None and cur_c > prev_c) or \
             (trend == "down" and cur_c is not None and prev_c is not None and cur_c < prev_c)
    sat = int(True) + int(on_trend_side) + int(decel and approached is not None) + int(bool(resume))
    ev = {"vwap": vwap, "trend": trend, "declining_pullback_volume": decel, "resumed": bool(resume)}
    fails = []
    if not on_trend_side:
        fails.append("not_on_trend_side_of_vwap")
    if not decel:
        fails.append("pullback_volume_not_declining")
    if not resume:
        fails.append("no_resumption")
    if on_trend_side and decel and resume and approached is not None:
        return _res("SCALP_VWAP_PULLBACK_V1", FIRED, sat, 4, ev)
    return _res("SCALP_VWAP_PULLBACK_V1", ARMED if on_trend_side else SCANNING, sat, 4, ev, fails)


def detect_vwap_reversion(ctx: Mapping, cfg: Mapping) -> dict:
    """MEAN REVERSION: price materially STRETCHED from VWAP with a reversal toward VWAP. Mandatory:
    (1) VWAP present, (2) |price-VWAP| >= stretch threshold (in ATR units), (3) reversal bar toward VWAP.
    An ordinary small pullback (below the stretch threshold) is NOT reversion."""
    bars = ctx["bars"]
    if len(bars) < 3:
        return _res("SCALP_VWAP_REVERSION_V1", SCANNING, 0, 3, {}, ["insufficient_bars"])
    vwap = _vwap(bars)
    atr = ctx.get("atr_1m") or t0.atr(bars, int(cfg.get("trigger", {}).get("atr_period", 14)))
    if vwap is None or not atr:
        return _res("SCALP_VWAP_REVERSION_V1", SCANNING, 0, 3, {"vwap": vwap, "atr": atr},
                    ["no_vwap_or_atr"])
    stretch_mult = float(cfg.get("vwap_reversion", {}).get("stretch_atr_mult", 2.0))
    prev_c, cur_c = t0._c(bars[-2]), t0._c(bars[-1])
    if prev_c is None or cur_c is None:
        return _res("SCALP_VWAP_REVERSION_V1", SCANNING, 0, 3, {}, ["no_close"])
    dist_prev = (prev_c - vwap) / atr
    stretched = abs(dist_prev) >= stretch_mult
    reverting = (dist_prev > 0 and cur_c < prev_c) or (dist_prev < 0 and cur_c > prev_c)
    sat = int(vwap is not None) + int(stretched) + int(bool(reverting))
    ev = {"vwap": vwap, "atr": atr, "stretch_atr": round(dist_prev, 3), "stretched": stretched,
          "reverting_toward_vwap": bool(reverting)}
    fails = []
    if not stretched:
        fails.append("not_stretched_from_vwap")   # ordinary pullback — not reversion
    if not reverting:
        fails.append("no_reversal_toward_vwap")
    if stretched and reverting:
        return _res("SCALP_VWAP_REVERSION_V1", FIRED, sat, 3, ev)
    return _res("SCALP_VWAP_REVERSION_V1", ARMED if stretched else SCANNING, sat, 3, ev, fails)


def detect_l2_momentum(ctx: Mapping, cfg: Mapping) -> dict:
    """Level-2 Momentum Breakout. REQUIRES entitled, fresh order-book evidence — NEVER inferred from
    OHLCV. When no book → DATA_UNAVAILABLE. Mandatory: catalyst gap, exceptional early volume,
    consolidation, directional stacking, break with bid lifting. Book FLIP → INVALIDATED."""
    book = ctx.get("book")
    if not book:
        return _res("SCALP_L2_MOMENTUM_V1", DATA_UNAVAILABLE, 0, 5,
                    {"required_tier": "T2"}, ["L2_ENTITLEMENT_OR_BOOK_UNAVAILABLE"])
    if book.get("flip"):
        return _res("SCALP_L2_MOMENTUM_V1", INVALIDATED, 0, 5, {"book": book}, ["book_flip"])
    crit = {
        "catalyst_gap": bool(book.get("catalyst_gap")),
        "early_volume": bool(book.get("early_volume")),
        "consolidation": bool(book.get("consolidation")),
        "directional_stacking": book.get("stacking") in ("bid", "offer"),
        "break_with_lift": bool(book.get("break")) and bool(book.get("bid_lifting")),
    }
    sat = sum(1 for v in crit.values() if v)
    fails = [f"missing:{k}" for k, v in crit.items() if not v]
    if sat == 5:
        return _res("SCALP_L2_MOMENTUM_V1", FIRED, sat, 5, {"book": book, "criteria": crit})
    return _res("SCALP_L2_MOMENTUM_V1", ARMED, sat, 5, {"book": book, "criteria": crit}, fails)


def detect_premarket_momentum(ctx: Mapping, cfg: Mapping) -> dict:
    """Premarket momentum (ENGINE_ADAPTATION). REQUIRES premarket-specific inputs (separate premarket
    VWAP + premarket RVOL denominator + premarket structure). Absent premarket RVOL denominator →
    DATA_UNAVAILABLE (fail-closed fallback; regular-session profile is NEVER reused). Mandatory:
    (1) above premarket VWAP, (2) break of premarket structure high, (3) building premarket volume,
    (4) premarket RVOL_tod above threshold."""
    bars = ctx["bars"]
    pv = ctx.get("premarket_vwap")
    prvol = ctx.get("premarket_rvol_tod")
    struct = ctx.get("premarket_structure")
    if prvol is None:                       # separate premarket denominator not built → fail closed
        return _res("SCALP_PREMARKET_MOMENTUM_V1", DATA_UNAVAILABLE, 0, 4,
                    {"premarket_vwap": pv}, ["PREMARKET_RVOL_PROFILE_UNAVAILABLE"])
    if pv is None or not struct:
        return _res("SCALP_PREMARKET_MOMENTUM_V1", SCANNING, 0, 4, {}, ["no_premarket_vwap_or_structure"])
    cur_c = t0._c(bars[-1]) if bars else None
    above_vwap = cur_c is not None and cur_c >= pv
    broke_structure = cur_c is not None and struct.get("high") is not None and cur_c > struct["high"]
    building = bool(ctx.get("premarket_building_volume"))
    rvol_min = float(cfg.get("premarket", {}).get("rvol_min", 2.0))
    rvol_ok = prvol >= rvol_min
    crit = {"above_pm_vwap": above_vwap, "broke_pm_structure": broke_structure,
            "building_volume": building, "pm_rvol": rvol_ok}
    sat = sum(1 for v in crit.values() if v)
    fails = [f"missing:{k}" for k, v in crit.items() if not v]
    ev = {"premarket_vwap": pv, "premarket_rvol_tod": prvol, "criteria": crit}
    if sat == 4:
        return _res("SCALP_PREMARKET_MOMENTUM_V1", FIRED, sat, 4, ev)
    return _res("SCALP_PREMARKET_MOMENTUM_V1", ARMED if above_vwap else SCANNING, sat, 4, ev, fails)


_DETECTORS = {
    "SCALP_IGNITION_BREAKOUT_V1": detect_ignition_breakout,
    "SCALP_MICRO_PULLBACK_V1": detect_micro_pullback,
    "SCALP_ORB_15_BREAKOUT_V1": detect_orb_15,
    "SCALP_VWAP_PULLBACK_V1": detect_vwap_pullback,
    "SCALP_VWAP_REVERSION_V1": detect_vwap_reversion,
    "SCALP_L2_MOMENTUM_V1": detect_l2_momentum,
    "SCALP_PREMARKET_MOMENTUM_V1": detect_premarket_momentum,
}


def detect_setups(ctx: Mapping, cfg: Mapping, now, registry: Mapping | None = None) -> dict:
    """Run every enabled detector, apply the session/window gate to FIRED transitions, retain ALL
    matches, and pick the deterministic primary. `now` is a datetime.time (ET). Returns the taxonomy row
    (the additive event columns). No confirmations here — Layer B fills confirmation_labels."""
    reg = registry if registry is not None else sreg.load_registry()
    by_id = {s["setup_id"]: s for s in reg["setups"]}
    ms = ssess.market_session(now, cfg)

    # Layer B (confirmations) + Layer C (universal execution gate) — computed once; independent of setup.
    cc = _conf_cfg()
    conf = sconf.compute_confirmations(ctx, cfg, cc.get("overlays", {}))
    gate = sgate.evaluate_gate(ctx, cfg, cc.get("gate", {}))

    results = []
    for sid, fn in _DETECTORS.items():
        setup = by_id.get(sid)
        if not setup or not setup.get("enabled") or setup.get("operating_state") == "DISABLED":
            continue
        r = fn(ctx, cfg)
        if r["state"] == FIRED:
            # (1) window/session gate: a pattern can only reach FIRED inside its eligibility window
            ok, reason = ssess.setup_eligible(setup, now, cfg)
            if not ok:
                r = {**r, "state": OUTSIDE_WINDOW, "fail_reasons": [*r["fail_reasons"], reason]}
            # (2) universal execution-quality gate can VETO any fire (FIRED requires the gate PASS)
            elif not gate["passed"]:
                r = {**r, "state": ARMED,
                     "fail_reasons": [*r["fail_reasons"], "EXECUTION_GATE_VETO", *gate["reasons"]]}
        results.append(r)

    fired = [r for r in results if r["state"] == FIRED]
    matched_ids = [r["setup_id"] for r in fired]
    primary_id = sreg.select_primary(fired, reg) if fired else None
    # summary state = best state present
    summary_state = max((r["state"] for r in results), key=lambda s: _STATE_RANK.get(s, 0)) if results else SCANNING

    return {
        "market_session": ms,
        "primary_setup_id": primary_id,
        "primary_setup_label": (by_id[primary_id]["display_label"] if primary_id else None),
        "matched_setup_ids": matched_ids,
        "matched_setup_labels": [by_id[i]["display_label"] for i in matched_ids],
        "setup_state": FIRED if fired else summary_state,
        "setup_version": (by_id[primary_id]["version"] if primary_id else None),
        "confirmation_labels": [*conf["labels"], *gate["labels"]],   # Layer B overlays + Layer C gate labels
        "setup_evidence": {
            **{r["setup_id"]: {"state": r["state"], "evidence": r["evidence"],
                               "mandatory": [r["mandatory_satisfied"], r["mandatory_total"]]}
               for r in results},
            "_confirmations": {"score": conf["confirmation_score"],
                               "pass_count": conf["confirmation_pass_count"],
                               "fail_count": conf["confirmation_fail_count"],
                               "authorizes_fire": conf["authorizes_fire"]},
            "_execution_gate": {"result": gate["result"], "passed": gate["passed"],
                                "reasons": gate["reasons"], "price_control": gate["price_control"],
                                "stop_validation": gate.get("stop_validation")},
        },
        "setup_fail_reasons": {r["setup_id"]: r["fail_reasons"] for r in results if r["fail_reasons"]},
        "execution_gate_result": gate["result"],
        "stop_validation": gate.get("stop_validation"),
        "confirmation_score": conf["confirmation_score"],
        "registry_hash": sreg.registry_hash(reg),
        "multi_setup": len(matched_ids) > 1,
    }


def taxonomy_for_symbol(*, bars, now, cfg, registry=None, ign_lane=None, ign_score=None, atr_1m=None,
                        book=None, market_aligned=None, trend=None, premarket_vwap=None,
                        premarket_rvol_tod=None, premarket_structure=None, premarket_building_volume=None,
                        spread_bps=None, data_age_sec=None, bar_volume=None, price=None,
                        catalyst_weight=None, halted=None, data_tier=None, hypothetical_shares=None,
                        macd_hist_5m=None, entry_ref=None, stop_ref=None, price_increment=None) -> dict:
    """Thin wrapper the shadow logger calls per symbol: assemble the detector context (setup inputs +
    Layer B confirmation inputs + Layer C gate inputs) from what the logger already has, run detect_setups.
    Absent T2 book / premarket profile / market-alignment fail closed inside their detectors; the universal
    gate vetoes on stale/wide-spread/insufficient-volume/etc. Honest for the current T0-only data plane."""
    ctx = {"bars": bars, "ign_lane": ign_lane, "ign_score": ign_score, "atr_1m": atr_1m,
           "book": book, "market_aligned": market_aligned, "trend": trend, "macd_hist_5m": macd_hist_5m,
           "premarket_vwap": premarket_vwap, "premarket_rvol_tod": premarket_rvol_tod,
           "premarket_structure": premarket_structure, "premarket_building_volume": premarket_building_volume,
           "spread_bps": spread_bps, "data_age_sec": data_age_sec, "bar_volume": bar_volume, "price": price,
           "catalyst_weight": catalyst_weight, "halted": halted, "data_tier": data_tier or "T0",
           "hypothetical_shares": hypothetical_shares,
           "entry_ref": entry_ref, "stop_ref": stop_ref, "price_increment": price_increment}
    return detect_setups(ctx, cfg, now, registry)
