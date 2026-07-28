"""Server-side setup-fire performance — computed from immutable fire facts + live marks.

Pure reducers, no I/O, no DB writes, no order path. React never computes this from stale
fields; the read API calls these and ships the result. Two hard rules:

  * fire_price is IMMUTABLE — a 09:45 fire always shows fired_at 09:45 / fire_price X.
  * the current mark updates INDEPENDENTLY; change / MFE / MAE / current-R recompute from
    the running path, never from the entry reference.

Finalized T+1 outcomes are the record of record: when a fire carries a resolved outcome we
pass it through as OUTCOME_RESOLVED and never overwrite it with an ephemeral UI mark.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional


# ── fire lifecycle display states (section H) ────────────────────────────────
FIRED_FRESH = "FIRED_FRESH"
ACTIVE_OBSERVATION = "ACTIVE_OBSERVATION"
STOP_TOUCHED = "STOP_TOUCHED"
TARGET_TOUCHED = "TARGET_TOUCHED"
EXPIRED = "EXPIRED"
OUTCOME_PENDING = "OUTCOME_PENDING"
OUTCOME_RESOLVED = "OUTCOME_RESOLVED"
DATA_STALE = "DATA_STALE"

# only these appear in the MAIN active queue; everything else → TODAY'S FIRE HISTORY
ACTIVE_LIFECYCLE = frozenset({FIRED_FRESH, ACTIVE_OBSERVATION, STOP_TOUCHED, TARGET_TOUCHED})


@dataclass(frozen=True)
class FirePerfConfig:
    fresh_fire_seconds: float = 60.0
    active_observation_minutes: float = 30.0
    mark_stale_after_ms: float = 6000.0


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _f(v) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def compute_fire_performance(
    fire: dict[str, Any],
    *,
    current_bid: Optional[float],
    current_ask: Optional[float],
    current_last: Optional[float],
    mark_source: Optional[str],
    mark_at_iso: Optional[str],
    now_iso: str,
    cfg: FirePerfConfig,
    prior_high: Optional[float] = None,
    prior_low: Optional[float] = None,
    l2_state_now: Optional[str] = None,
    finalized_outcome: Optional[str] = None,
) -> dict[str, Any]:
    """Reduce one fire + one current mark into the full performance projection.

    `prior_high`/`prior_low` carry the running MFE/MAE extremes across polls (the caller
    persists them in a bounded in-memory map). fire_price/fired_at pass through untouched."""
    now = _parse_iso(now_iso)
    fired = _parse_iso(fire.get("fired_at"))
    fire_price = _f(fire.get("fire_price"))
    stop_ref = _f(fire.get("stop_ref"))
    target_ref = _f(fire.get("target_ref"))
    mark_at = _parse_iso(mark_at_iso)

    # current mark: prefer last, else mid of bid/ask
    last = current_last
    if last is None and current_bid is not None and current_ask is not None:
        last = (current_bid + current_ask) / 2.0

    # running extremes (MFE/MAE path) — seed from prior, update with this mark
    high = prior_high
    low = prior_low
    if last is not None:
        high = last if high is None else max(high, last)
        low = last if low is None else min(low, last)

    risk_per_share = None
    if fire_price is not None and stop_ref is not None:
        risk_per_share = fire_price - stop_ref     # long convention (>0 expected)

    change_from_fire = None
    change_from_fire_pct = None
    current_r = None
    if fire_price is not None and last is not None:
        change_from_fire = last - fire_price
        change_from_fire_pct = (change_from_fire / fire_price * 100.0) if fire_price else None
        if risk_per_share and risk_per_share > 0:
            current_r = change_from_fire / risk_per_share

    mfe = None if (fire_price is None or high is None) else high - fire_price
    mae = None if (fire_price is None or low is None) else low - fire_price

    hit_stop = bool(stop_ref is not None and low is not None and low <= stop_ref)
    one_r_price = (fire_price + risk_per_share) if (fire_price is not None and risk_per_share) else None
    target_price = target_ref if target_ref is not None else one_r_price
    hit_target = bool(target_price is not None and high is not None and high >= target_price)
    hit_1r = bool(one_r_price is not None and high is not None and high >= one_r_price)

    mark_age_ms = None
    if mark_at is not None and now is not None:
        mark_age_ms = max(0.0, (now - mark_at).total_seconds() * 1000.0)
    mark_is_stale = (mark_age_ms is not None and mark_age_ms > cfg.mark_stale_after_ms) or last is None

    age_seconds = None if (fired is None or now is None) else max(0.0, (now - fired).total_seconds())

    # ── lifecycle state (finalized outcome wins; never overwritten by UI marks) ──
    if finalized_outcome:
        outcome_state = OUTCOME_RESOLVED
        lifecycle = OUTCOME_RESOLVED
    elif mark_is_stale:
        outcome_state = OUTCOME_PENDING
        lifecycle = DATA_STALE
    elif hit_stop:
        outcome_state = OUTCOME_PENDING
        lifecycle = STOP_TOUCHED
    elif hit_target:
        outcome_state = OUTCOME_PENDING
        lifecycle = TARGET_TOUCHED
    elif age_seconds is not None and age_seconds <= cfg.fresh_fire_seconds:
        outcome_state = OUTCOME_PENDING
        lifecycle = FIRED_FRESH
    elif age_seconds is not None and age_seconds <= cfg.active_observation_minutes * 60.0:
        outcome_state = OUTCOME_PENDING
        lifecycle = ACTIVE_OBSERVATION
    else:
        outcome_state = OUTCOME_PENDING
        lifecycle = EXPIRED

    return {
        "fire_id": fire.get("fire_id") or fire.get("id"),
        "symbol": fire.get("symbol"),
        "primary_setup_id": fire.get("primary_setup_id"),
        "primary_setup_label": fire.get("primary_setup_label"),
        "lane": fire.get("lane"),
        "setup_state": fire.get("setup_state"),
        "gate_decision": fire.get("gate_decision"),
        "fired_at": fire.get("fired_at"),
        "fire_price": fire_price,               # IMMUTABLE
        "stop_ref": stop_ref,
        "target_ref": target_price,
        "current_bid": current_bid,
        "current_ask": current_ask,
        "current_last": last,
        "mark_source": mark_source,
        "mark_at": mark_at_iso,
        "mark_age_ms": mark_age_ms,
        "change_from_fire": change_from_fire,
        "change_from_fire_pct": change_from_fire_pct,
        "high_since_fire": high,
        "low_since_fire": low,
        "mfe_since_fire": mfe,
        "mae_since_fire": mae,
        "current_r_multiple": current_r,
        "risk_per_share": risk_per_share,
        "hit_stop": hit_stop,
        "hit_1r": hit_1r,
        "hit_target": hit_target,
        "outcome_state": outcome_state,
        "lifecycle_state": lifecycle,
        "in_active_queue": lifecycle in ACTIVE_LIFECYCLE,
        "age_seconds": age_seconds,
        "l2_state_at_fire": fire.get("l2_state_at_fire"),
        "l2_state_now": l2_state_now,
        "mark_stale": mark_is_stale,
    }


class FirePerfTracker:
    """Bounded in-memory running-extreme store keyed by fire_id (MFE/MAE across polls).

    Not a DB — a small dict the read API keeps for the session. Cleared for expired fires.
    """

    def __init__(self, cfg: Optional[FirePerfConfig] = None, max_fires: int = 512):
        self.cfg = cfg or FirePerfConfig()
        self._extremes: dict[str, tuple[Optional[float], Optional[float]]] = {}
        self._max = int(max_fires)

    def update(self, fire: dict[str, Any], *, current_bid=None, current_ask=None,
               current_last=None, mark_source=None, mark_at_iso=None, now_iso: str,
               l2_state_now=None, finalized_outcome=None) -> dict[str, Any]:
        fid = str(fire.get("fire_id") or fire.get("id") or fire.get("symbol"))
        ph, pl = self._extremes.get(fid, (None, None))
        result = compute_fire_performance(
            fire, current_bid=current_bid, current_ask=current_ask, current_last=current_last,
            mark_source=mark_source, mark_at_iso=mark_at_iso, now_iso=now_iso, cfg=self.cfg,
            prior_high=ph, prior_low=pl, l2_state_now=l2_state_now,
            finalized_outcome=finalized_outcome)
        self._extremes[fid] = (result["high_since_fire"], result["low_since_fire"])
        if len(self._extremes) > self._max:            # bound memory
            for k in list(self._extremes)[: len(self._extremes) - self._max]:
                self._extremes.pop(k, None)
        return result
