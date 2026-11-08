"""The score, the band, and the hysteresis (§2.3, §2.7).

``S = 100 · Σ w'_k·C_k / Σ w'_k`` over measured categories only — an UNKNOWN category leaves both the numerator and
the denominator, so it can never be read as a zero. The band is then held or moved by the same hysteresis the MRE
uses, capped by the MRE tier and by the FOMC window, because the outlook is a view and the MRE is the guard.
"""

from __future__ import annotations

import gzip
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from .categories import CategoryResult
from .regime import Regime

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BASE_RATES = PROJECT_ROOT / "scripts" / "lib" / "market_risk" / "base_rates_table.json.gz"


@dataclass
class ScoreResult:
    score: float | None
    score_before_caps: float | None
    band: str | None
    band_naive: str | None
    measured: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    subscore_by_key: dict[str, float] = field(default_factory=dict)
    adjustments: list[str] = field(default_factory=list)
    fomc_window: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def band_of(score: float, policy: dict[str, Any]) -> str:
    b = policy["bands"]
    if score >= float(b["risk_on_min"]):
        return "RISK_ON"
    if score > float(b["neutral_min"]):
        return "NEUTRAL"
    if score > float(b["defensive_min"]):
        return "DEFENSIVE"
    return "RISK_OFF"


_ORDER = {"RISK_OFF": 0, "DEFENSIVE": 1, "NEUTRAL": 2, "RISK_ON": 3}


def _idx(band: str) -> int:
    return _ORDER.get(str(band).replace("-", "_"), 2)


def _from_idx(i: int) -> str:
    for name, idx in _ORDER.items():
        if idx == i:
            return name
    return "NEUTRAL"


def score_categories(categories: Sequence[CategoryResult], policy: dict[str, Any]) -> tuple[float | None, list[str], dict[str, float]]:
    measured = [c for c in categories if c.measured]
    if not measured:
        return None, [], {}
    num = sum(c.weight_effective * float(c.subscore) for c in measured)
    den = sum(c.weight_effective for c in measured)
    if den <= 0:
        return None, [c.key for c in measured], {}
    s = 100.0 * num / den
    return max(-100.0, min(100.0, s)), [c.key for c in measured], {c.key: c.weight_effective for c in measured}


def compute(
    categories: Sequence[CategoryResult],
    policy: dict[str, Any],
    regime: Regime | None = None,
    *,
    prior: dict[str, Any] | None = None,
    history: Sequence[dict[str, Any]] = (),
    fomc_window: bool = False,
) -> ScoreResult:
    s, measured, weights = score_categories(categories, policy)
    res = ScoreResult(
        score=s,
        score_before_caps=s,
        band=None,
        band_naive=None if s is None else band_of(s, policy),
        measured=measured,
        unknown=[c.key for c in categories if not c.measured],
        weights=weights,
        subscore_by_key={c.key: round(float(c.subscore), 4) for c in categories if c.measured},
        fomc_window=fomc_window,
    )
    if s is None:
        res.adjustments.append("no category measured: the engine states UNKNOWN rather than a zero score")
        return res
    band = resolve_band(s, policy, prior=prior, history=history, regime=regime, fomc_window=fomc_window, notes=res.adjustments)
    res.band = band
    return res


def resolve_band(
    score: float,
    policy: dict[str, Any],
    *,
    prior: dict[str, Any] | None,
    history: Sequence[dict[str, Any]] = (),
    regime: Regime | None = None,
    fomc_window: bool = False,
    notes: list[str] | None = None,
) -> str:
    notes = notes if notes is not None else []
    hyst = policy["hysteresis"]
    naive = band_of(score, policy)
    prior_band = str((prior or {}).get("band") or "") or None
    prior_score = _f((prior or {}).get("score"))

    band = naive
    if prior_band and prior_band != naive:
        jump = prior_score is not None and abs(score - prior_score) >= float(hyst["jump_threshold"])
        same_twice = prior_score is not None and band_of(prior_score, policy) == naive
        if jump:
            notes.append(f"band {prior_band}->{naive} on |dS| {abs(score - prior_score):.1f} >= {hyst['jump_threshold']}")
        elif same_twice:
            notes.append(f"band {prior_band}->{naive}: two consecutive evaluations in the new band")
        else:
            band = prior_band
            notes.append(
                f"S {score:+.1f} points at {naive} but holds {prior_band}: "
                f"hysteresis needs a second evaluation or |dS| >= {hyst['jump_threshold']}"
            )

    # from DEFENSIVE/RISK_OFF the stance rises at most one band inside one weekly cycle
    if prior_band and band != prior_band and _idx(band) > _idx(prior_band) and prior_band in ("DEFENSIVE", "RISK_OFF"):
        capped = _from_idx(min(_idx(band), _idx(prior_band) + 1))
        if capped != band:
            notes.append(f"rise capped one band per weekly cycle: {band} -> {capped}")
        band = capped
        if _rose_recently(history, float(hyst.get("window_hours", 168.0)), notes):
            band = prior_band
            notes.append("a rise already happened inside the weekly cycle; holding the prior band")

    # the MRE tier caps the stance (§2.7)
    if regime is not None and regime.mre_tier:
        cap = policy["mre_caps"].get(str(regime.mre_tier).upper())
        if cap and _idx(band) > _idx(cap):
            notes.append(f"MRE {regime.mre_tier} caps the stance at {cap}: {band} -> {cap}")
            band = cap
    if regime is not None and regime.red_shock:
        notes.append("MRE red_shock forces RISK_OFF")
        band = "RISK_OFF"

    if fomc_window and band == "RISK_ON" and prior_band != "RISK_ON":
        notes.append("FOMC window blocks a new RISK_ON: held at NEUTRAL")
        band = "NEUTRAL"
    return band


def _rose_recently(history: Sequence[dict[str, Any]], window_hours: float, notes: list[str]) -> bool:
    """True when a band rise is already recorded inside the window (records are newest-first)."""
    prev = None
    for rec in reversed(list(history)):
        band = (rec or {}).get("band")
        at = _dt((rec or {}).get("as_of"))
        if prev is not None and band and prev[0] and _idx(band) > _idx(prev[0]) and prev[1] and at:
            from datetime import timezone

            if (prev[1] - at).total_seconds() / 3600.0 <= window_hours:
                notes.append(f"last rise {prev[0]}->{band} at {prev[1].isoformat()} is inside {window_hours:.0f} h")
                return True
        prev = (band, at)
    return False


# ── scenarios (§4.6 scenarios block) ---------------------------------------------------------------------------
def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def base_rate_bear(vix_value: float | None, path: Path = BASE_RATES) -> float | None:
    """P(SPY 5-session return < 0 | this VIX bucket) from the frozen base-rate table. Never a live feed."""
    if vix_value is None or not path.is_file():
        return None
    bucket = _vix_bucket(vix_value)
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            body = json.load(fh)
    except (OSError, ValueError):
        return None
    n = down = 0
    for row in body.get("rows") or []:
        if str((row.get("f") or {}).get("vix_b") or "") != bucket:
            continue
        ret = ((row.get("o") or {}).get("SPY") or {}).get("5")
        if ret is None:
            continue
        n += 1
        if float(ret) < 0:
            down += 1
    return (down / n) if n >= 30 else None


def _vix_bucket(v: float) -> str:
    edges = [15, 20, 25, 30, 35, 40]
    for i, e in enumerate(edges):
        if v < e:
            lo = edges[i - 1] if i else None
            return f"{lo}-{e}" if lo is not None else f"<{e}"
    return "40+"


def scenarios(
    score: float, vix_value: float | None, weekly_atr_pct: dict[str, float], policy: dict[str, Any]
) -> dict[str, Any]:
    """Probabilities from S (matched 50/50 with the historical base rate) and +-1/+2 weekly-ATR ranges."""
    p_bear = _sigmoid((-score - 15.0) / 20.0)
    prior = base_rate_bear(vix_value)
    blend_note = "logistic only (no base rate for this VIX bucket)"
    if prior is not None:
        p_bear = 0.5 * p_bear + 0.5 * prior
        blend_note = f"logistic blended 50/50 with the historical base rate {prior:.2f} for this VIX bucket"
    p_bull = _sigmoid((score - 15.0) / 20.0)
    if p_bear + p_bull > 0.95:
        scale = 0.95 / (p_bear + p_bull)
        p_bear, p_bull = p_bear * scale, p_bull * scale
    p_base = max(0.0, 1.0 - p_bear - p_bull)
    ranges = {}
    for key, atr in weekly_atr_pct.items():
        ranges[key] = {"low_1atr": -atr, "high_1atr": atr, "low_2atr": -2.0 * atr, "high_2atr": 2.0 * atr}
    return {
        "base": {"prob": round(p_base, 3), "spx_range": ranges.get("SPX"), "ndx_range": ranges.get("NDX"),
                 "rut_range": ranges.get("RUT"), "triggers": ["S stays inside -10..+25", "no HIGH release surprises"]},
        "bull": {"prob": round(p_bull, 3), "spx_range": ranges.get("SPX"), "ndx_range": ranges.get("NDX"),
                 "rut_range": ranges.get("RUT"), "triggers": ["breadth and credit repair together", "VIX back below 20"]},
        "bear": {"prob": round(p_bear, 3), "spx_range": ranges.get("SPX"), "ndx_range": ranges.get("NDX"),
                 "rut_range": ranges.get("RUT"), "triggers": ["key support breaks on rising volume", "HY OAS widens"]},
        "method": f"P(bear)=sigma((-S-15)/20); {blend_note}; ranges are +-1/+-2 weekly ATR from the Friday close",
    }


def weekly_atr_pct(bars_by_symbol: dict[str, list[dict[str, Any]]], proxy: dict[str, str], sessions: int = 20) -> dict[str, float]:
    """Each index's weekly ATR as a percent: the proxy's 20-session daily ATR scaled by sqrt(5)."""
    out: dict[str, float] = {}
    for index, etf in proxy.items():
        bars = list(bars_by_symbol.get(etf) or [])
        if len(bars) < sessions + 1:
            continue
        trs = []
        for i in range(len(bars) - sessions, len(bars)):
            high, low, prev = _f(bars[i].get("high")), _f(bars[i].get("low")), _f(bars[i - 1].get("close"))
            if high is None or low is None or prev is None:
                break
            trs.append(max(high - low, abs(high - prev), abs(low - prev)))
        close = _f(bars[-1].get("close"))
        if close and trs:
            out[index] = round((sum(trs) / len(trs)) / close * 100.0 * math.sqrt(5), 3)
    return out


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    from datetime import timezone

    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


__all__ = [
    "ScoreResult",
    "band_of",
    "compute",
    "resolve_band",
    "scenarios",
    "weekly_atr_pct",
    "base_rate_bear",
]
