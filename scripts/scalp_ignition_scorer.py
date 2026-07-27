#!/usr/bin/env python3
"""M3-S3 — IGN ignition scorer (Momentum Scalp Signal Engine, design §3.2/§3.3).

PURE scoring. Six sub-scores each normalized to [0,1], combined by fixed v1-prior weights into an
IGN score 0-100. No I/O, no DB, no network, no alerts, no proposals, no order path. The I/O layer
(scalp_shadow_logger.py) assembles the primitive inputs and writes shadow rows; this module only
computes numbers.

Sub-scores (§3.2):
  v_rvol  volume pace       clamp(log_10(RVOL_tod / ref), 0, 1)            ref=2 → 0, 20× → 1
  v_burst ignition detector clamp(z_vol / div, 0, 1), z=(v_1m-μ)/σ_eff     σ_eff = σ FLOOR-GUARDED
  v_cat   catalyst heat     tier_weight · exp(-age_min / decay)
  v_disp  displacement      clamp((P-VWAP)/(k·ATR_1m·√n_bars), 0, 1)
  v_liq   tradability       clamp(log_10(($·vol_5m)/ref)/div, 0, 1)        $50K → 0, $2.5M → 1
  v_rs    leadership        percentile rank of (ret_sym - ret_SPY) within the day's universe

Composite (§3.3): IGN = 100 · Σ w_i · v_i   (weights are v1 PRIORS; refit once on shadow at M3-S8).

Weights are refit ONCE post-shadow (§12); do NOT hand-tune mid-shadow.
"""
from __future__ import annotations

import math
from typing import Mapping, Sequence

# lanes
LANE_75 = "IGN_75"
LANE_60 = "IGN_60"
LANE_45 = "IGN_45"
LANE_ACCEL = "IGN_ACCEL"
LANE_BELOW = "BELOW"


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


# ─────────────────────────── sub-scores (pure) ───────────────────────────

def v_rvol(rvol_tod: float | None, cfg: Mapping) -> float:
    ref = float(cfg["subscores"]["v_rvol"]["ref_rvol"])
    base = float(cfg["subscores"]["v_rvol"]["log_base"])
    if rvol_tod is None or rvol_tod <= 0 or ref <= 0:
        return 0.0
    ratio = rvol_tod / ref
    if ratio <= 0:
        return 0.0
    return clamp(math.log(ratio, base))


def sigma_effective(mu_20: float | None, sigma_20: float | None, cfg: Mapping) -> float:
    """σ floor guard: a dead 20-bar window (σ≈0) must not blow up the z-score."""
    c = cfg["subscores"]["v_burst"]
    frac = float(c["sigma_floor_frac"])
    eps = float(c["sigma_eps"])
    mu = float(mu_20 or 0.0)
    s = float(sigma_20 or 0.0)
    return max(s, frac * mu, eps)


def v_burst(v_1m: float | None, mu_20: float | None, sigma_20: float | None, cfg: Mapping) -> float:
    if v_1m is None or mu_20 is None:
        return 0.0
    div = float(cfg["subscores"]["v_burst"]["z_divisor"])
    sig = sigma_effective(mu_20, sigma_20, cfg)
    z = (float(v_1m) - float(mu_20)) / sig
    return clamp(z / div)


def v_cat(tier_weight: float | None, age_min: float | None, cfg: Mapping) -> float:
    if tier_weight is None or tier_weight <= 0:
        return 0.0
    decay = float(cfg["subscores"]["v_cat"]["decay_min"])
    age = float(age_min if age_min is not None else 0.0)
    if age < 0:
        age = 0.0
    return clamp(float(tier_weight) * math.exp(-age / decay))


def v_disp(price: float | None, vwap: float | None, atr_1m: float | None, n_bars: int, cfg: Mapping) -> float:
    if price is None or vwap is None or atr_1m is None or atr_1m <= 0 or n_bars <= 0:
        return 0.0
    k = float(cfg["subscores"]["v_disp"]["atr_mult"])
    denom = k * atr_1m * math.sqrt(n_bars)
    if denom <= 0:
        return 0.0
    return clamp((price - vwap) / denom)


def v_liq(price: float | None, vol_5m: float | None, cfg: Mapping) -> float:
    if price is None or vol_5m is None or price <= 0 or vol_5m <= 0:
        return 0.0
    c = cfg["subscores"]["v_liq"]
    ref = float(c["dollar_ref_low"])
    div = float(c["log_divisor"])
    dollar = price * vol_5m
    if dollar <= 0 or ref <= 0 or div <= 0:
        return 0.0
    return clamp(math.log10(dollar / ref) / div)


def percentile_rank(value: float, distribution: Sequence[float]) -> float:
    """Fraction of `distribution` <= value, ∈ [0,1]. 0.0 when the distribution is empty."""
    vals = [d for d in distribution if d is not None]
    if not vals:
        return 0.0
    return sum(1 for d in vals if d <= value) / len(vals)


def v_rs(rs_value: float | None, universe_rs: Sequence[float], cfg: Mapping) -> float:
    if rs_value is None:
        return 0.0
    return percentile_rank(float(rs_value), universe_rs)


# ─────────────────────────── composite + lanes ───────────────────────────

def composite_ign(subscores: Mapping[str, float], cfg: Mapping) -> float:
    w = cfg["weights"]
    return 100.0 * sum(float(w[k]) * float(subscores.get(k, 0.0)) for k in w)


def classify_lane(ign: float, notif: Mapping, prev_ign: float | None = None) -> str:
    """Level lanes from absolute IGN; IGN_ACCEL if the acceleration threshold is crossed
    (fires at ANY absolute level — the leader-catcher, §3.4)."""
    if prev_ign is not None and (ign - prev_ign) >= float(notif["accel_delta"]):
        return LANE_ACCEL
    if ign >= float(notif["proposal_min"]):
        return LANE_75
    if ign >= float(notif["alert_min"]):
        return LANE_60
    if ign >= float(notif["info_min"]):
        return LANE_45
    return LANE_BELOW


# ─────────────────────────── RVOL_tod (§3.1) ───────────────────────────

def rvol_tod(cum_vol: float, profile_median_cum: float | None) -> float | None:
    """Time-of-day RVOL from the per-symbol profile (M3-S1)."""
    if profile_median_cum is None or profile_median_cum <= 0:
        return None
    return cum_vol / profile_median_cum


def rvol_tod_proxy(cum_vol: float, adv_20d: float | None, expected_fraction: float | None) -> float | None:
    """Universe-proxy fallback (§3.1) for symbols without a per-symbol profile:
        RVOL_tod_proxy = CumVol / (ADV_20d · ExpectedFraction(t))."""
    if not adv_20d or adv_20d <= 0 or not expected_fraction or expected_fraction <= 0:
        return None
    denom = adv_20d * expected_fraction
    if denom <= 0:
        return None
    return cum_vol / denom


# ─────────────────────────── top-level score ───────────────────────────

def score(inputs: Mapping, cfg: Mapping, prev_ign: float | None = None) -> dict:
    """Compute all six sub-scores + IGN + lane from an assembled `inputs` mapping. Pure.
    Missing inputs degrade their sub-score to 0 (never raises)."""
    ign_cfg = cfg["ignition"]
    notif = cfg["notifications"]
    subs = {
        "v_rvol": v_rvol(inputs.get("rvol_tod"), ign_cfg),
        "v_burst": v_burst(inputs.get("v_1m"), inputs.get("mu_20"), inputs.get("sigma_20"), ign_cfg),
        "v_cat": v_cat(inputs.get("tier_weight"), inputs.get("age_min"), ign_cfg),
        "v_disp": v_disp(inputs.get("price"), inputs.get("vwap"), inputs.get("atr_1m"),
                         int(inputs.get("n_bars") or 0), ign_cfg),
        "v_liq": v_liq(inputs.get("price"), inputs.get("vol_5m"), ign_cfg),
        "v_rs": v_rs(inputs.get("rs_value"), inputs.get("universe_rs") or [], ign_cfg),
    }
    ign = composite_ign(subs, ign_cfg)
    lane = classify_lane(ign, notif, prev_ign)
    return {"subscores": {k: round(v, 6) for k, v in subs.items()}, "ign": round(ign, 3), "lane": lane}
