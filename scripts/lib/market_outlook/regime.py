"""Regime conditioning (§2.4): the VIX band, the MRE tier, and the category weight multipliers they imply.

The regime never re-scores anything. It changes *how much* each measured category counts, so that in stress the
survival categories (volatility, breadth, credit) dominate while rotation and trend matter less — and it caps the
stance (§2.7), because the MRE is the guard and the outlook is the view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from . import sessions_shim


@dataclass
class Regime:
    vix_band: str | None = None
    vix_value: float | None = None
    vix_source: str | None = None
    mre_tier: str | None = None
    mre_score: float | None = None
    mre_as_of: str | None = None
    episode_id: str | None = None
    red_shock: bool = False
    stress: bool = False
    calm: bool = False
    multipliers: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "vix_band": self.vix_band,
            "vix_value": self.vix_value,
            "vix_source": self.vix_source,
            "mre_tier": self.mre_tier,
            "mre_score": self.mre_score,
            "mre_as_of": self.mre_as_of,
            "episode_id": self.episode_id,
            "red_shock": self.red_shock,
            "stress": self.stress,
            "calm": self.calm,
            "multipliers": dict(self.multipliers),
            "notes": list(self.notes),
        }


def vix_band_of(value: float | None, policy: dict[str, Any]) -> str | None:
    if value is None:
        return None
    for band in policy["regimes"]["vix_bands"]:
        ceiling = band.get("max")
        if ceiling is None or value < float(ceiling):
            return str(band["name"])
    return None


def _clean_vix(bundle: Any, policy: dict[str, Any]) -> tuple[float | None, str | None, str]:
    """VIX from a clean feed only: FRED VIXCLS first, the regime table only when its feed is not banned."""
    banned = {str(b).lower() for b in policy["sources"]["banned_feeds"]}
    rows = list((bundle.fred or {}).get("VIXCLS") or [])
    if rows:
        return float(rows[-1]["value"]), "fred:VIXCLS", ""
    row = (bundle.regime or {}).get("vix_close")
    if row and str(row.get("feed") or "").lower() not in banned:
        return float(row["value"]), str(row.get("feed")), ""
    if row:
        return None, None, f"VIX from {row.get('feed')!r} refused (banned feed) and FRED VIXCLS is empty"
    return None, None, "no VIX on a clean feed"


def _red_shock(mre: dict[str, Any]) -> bool:
    if mre.get("red_shock") is True:
        return True
    hyst = mre.get("hysteresis") or {}
    if isinstance(hyst, dict) and hyst.get("red_shock") is True:
        return True
    episode = mre.get("episode") if isinstance(mre.get("episode"), dict) else {}
    return bool(episode.get("shock")) and str(mre.get("tier")) == "RED"


def resolve(bundle: Any, policy: dict[str, Any], now: datetime, category_keys: tuple[str, ...]) -> Regime:
    reg = policy["regimes"]
    vix, vix_source, vix_note = _clean_vix(bundle, policy)
    band = vix_band_of(vix, policy)
    out = Regime(vix_band=band, vix_value=None if vix is None else round(vix, 4), vix_source=vix_source)
    if vix_note:
        out.notes.append(vix_note)

    mre = bundle.mre or {}
    out.mre_as_of = mre.get("as_of")
    out.mre_score = _f(mre.get("score"))
    tier = mre.get("tier")
    if tier and out.mre_as_of:
        hours = sessions_shim.market_hours_between(_dt(out.mre_as_of), now, reopen=_reopen(policy))
        if hours > float(reg.get("mre_max_age_hours", 36)):
            out.notes.append(f"MRE snapshot {hours:.1f} market hours old — stale, no tier cap applied")
            tier = None
    out.mre_tier = str(tier) if tier else None
    out.episode_id = mre.get("episode_id")
    out.red_shock = _red_shock(mre)
    if out.red_shock:
        out.notes.append("MRE red_shock: RISK-OFF is forced")

    stress_tiers = {str(t).upper() for t in reg.get("stress_weight_tiers") or []}
    calm_tiers = {str(t).upper() for t in reg.get("calm_mre_tiers") or []}
    tier_u = out.mre_tier.upper() if out.mre_tier else None
    out.stress = band in ("HIGH", "EXTREME") or (tier_u is not None and tier_u in stress_tiers)
    out.calm = (band == "LOW") and (tier_u is not None and tier_u in calm_tiers)

    mult = {k: 1.0 for k in category_keys}
    applied: list[str] = []
    if out.stress:
        for key, value in (reg["multipliers"].get("stress") or {}).items():
            if key in mult:
                mult[key] *= float(value)
                applied.append(f"{key}x{value}")
    elif out.calm:
        for key, value in (reg["multipliers"].get("calm") or {}).items():
            if key in mult:
                mult[key] *= float(value)
                applied.append(f"{key}x{value}")
    if out.episode_id:
        for key, value in (reg["multipliers"].get("episode_open") or {}).items():
            if key in mult:
                mult[key] *= float(value)
                applied.append(f"{key}x{value} (open episode)")
    out.multipliers = mult
    if applied:
        out.notes.append(("stress" if out.stress else "calm" if out.calm else "base") + " weights: " + ", ".join(applied))
    return out


def _reopen(policy: dict[str, Any]):
    raw = str((policy.get("freshness") or {}).get("reopen_et") or "")
    try:
        h, m = raw.split(":")
        from datetime import time as _t

        return _t(int(h), int(m))
    except (ValueError, AttributeError):
        return None


def _dt(value: Any) -> datetime:
    from datetime import timezone

    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


__all__ = ["Regime", "resolve", "vix_band_of"]
