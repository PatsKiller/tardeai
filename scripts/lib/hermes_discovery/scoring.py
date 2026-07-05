"""discovery_score — weighted composite score for discovery candidates.

Components (each 0..1) weighted by the module-level WEIGHTS dict, minus
penalties. Signals that don't exist yet are STUBBED at 0.5 neutral with an
explicit note in parts, so the score_json is honest about what's real.

Feedback-driven adjustments (feedback.py) shift the source_quality /
trend_momentum component values (bounded ±0.3 per key) — the weights
themselves stay fixed so the score stays comparable over time.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

SCORING_VERSION = "discovery-score-v1"

# Positive component weights (sum 1.0). Keep keys in sync with _component_*.
WEIGHTS: dict[str, float] = {
    "novelty": 0.15,
    "source_quality": 0.15,
    "cross_source_confirmation": 0.15,
    "ticker_validation": 0.10,
    "trend_momentum": 0.15,
    "outcome_bus_alignment": 0.15,
    "operator_history_lift": 0.15,
}

# Penalty magnitudes (each subtracted from the weighted sum when triggered).
PENALTIES: dict[str, float] = {
    "duplicate": 0.15,     # candidate sits in a duplicate cluster
    "noise": 0.10,         # noise-ish risk flags (spam / low-signal source)
    "stale": 0.15,         # max stale penalty, scaled by age vs ttl_days
    "risk": 0.05,          # per risk flag, capped at 0.20
}

_NEUTRAL_NOTE = "stubbed neutral (no signal provider yet)"
_NOISE_FLAGS = {"noise", "spam", "low_signal", "clickbait", "promotional"}


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _risk_flag_list(candidate: dict[str, Any]) -> list[str]:
    flags = candidate.get("risk_flags") or []
    if isinstance(flags, dict):
        flags = list(flags.keys())
    return [str(f).lower() for f in flags if f]


def _component_novelty(candidate: dict[str, Any], signals: dict[str, Any]) -> tuple[float, str]:
    if "novelty" in signals:
        return _clamp01(signals["novelty"]), "provided signal"
    seen = max(1, int(candidate.get("seen_count") or 1))
    # First sighting = 1.0, decays as the same story keeps reappearing.
    return _clamp01(1.0 / math.sqrt(seen)), f"decay from seen_count={seen}"


def _component_source_quality(candidate: dict[str, Any], signals: dict[str, Any],
                              adjustments: dict[str, Any]) -> tuple[float, str]:
    base, note = 0.5, _NEUTRAL_NOTE
    if "source_quality" in signals:
        base, note = _clamp01(signals["source_quality"]), "provided signal"
    domain = (candidate.get("source_domain") or "").lower()
    delta = float((adjustments.get("source_deltas") or {}).get(domain, 0.0))
    if delta:
        note = f"{note}; feedback delta {delta:+.3f} for {domain}"
    return _clamp01(base + delta), note


def _component_cross_source(candidate: dict[str, Any], signals: dict[str, Any]) -> tuple[float, str]:
    if "cross_source_confirmation" in signals:
        return _clamp01(signals["cross_source_confirmation"]), "provided signal"
    evidence = candidate.get("evidence_json") or candidate.get("evidence") or []
    if not isinstance(evidence, list) or not evidence:
        return 0.5, _NEUTRAL_NOTE
    domains = set()
    for item in evidence:
        if isinstance(item, dict):
            d = (item.get("source_domain") or item.get("domain") or "").lower().strip()
            if d:
                domains.add(d)
    if not domains:
        return 0.5, "evidence carries no source domains — neutral"
    # 1 domain = 0.25, 2 = 0.5, 3 = 0.75, 4+ = 1.0
    return _clamp01(len(domains) * 0.25), f"{len(domains)} distinct evidence domain(s)"


def _component_ticker_validation(candidate: dict[str, Any], signals: dict[str, Any]) -> tuple[float, str]:
    if "ticker_validation" in signals:
        return _clamp01(signals["ticker_validation"]), "provided signal"
    meta = candidate.get("meta_json") or candidate.get("meta") or {}
    ratio = meta.get("ticker_validation_ratio") if isinstance(meta, dict) else None
    if ratio is not None:
        return _clamp01(float(ratio)), "validated-symbol ratio from meta"
    return 0.5, _NEUTRAL_NOTE


def _component_trend_momentum(candidate: dict[str, Any], signals: dict[str, Any],
                              adjustments: dict[str, Any]) -> tuple[float, str]:
    base, note = 0.5, _NEUTRAL_NOTE
    if "trend_momentum" in signals:
        base, note = _clamp01(signals["trend_momentum"]), "provided signal"
    key = (candidate.get("normalized_key") or "").lower()
    delta = float((adjustments.get("trend_deltas") or {}).get(key, 0.0))
    if delta:
        note = f"{note}; feedback delta {delta:+.3f}"
    return _clamp01(base + delta), note


def _component_outcome_bus(candidate: dict[str, Any], signals: dict[str, Any]) -> tuple[float, str]:
    if "outcome_bus_alignment" in signals:
        return _clamp01(signals["outcome_bus_alignment"]), "provided signal"
    return 0.5, _NEUTRAL_NOTE


def _component_operator_history(candidate: dict[str, Any], signals: dict[str, Any]) -> tuple[float, str]:
    if "operator_history_lift" in signals:
        return _clamp01(signals["operator_history_lift"]), "provided signal"
    return 0.5, _NEUTRAL_NOTE


def _penalties(candidate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    flags = _risk_flag_list(candidate)

    if candidate.get("duplicate_cluster_id"):
        out["duplicate"] = {"value": PENALTIES["duplicate"],
                            "note": f"member of cluster {candidate['duplicate_cluster_id']}"}
    noise_hits = sorted(set(flags) & _NOISE_FLAGS)
    if noise_hits:
        out["noise"] = {"value": PENALTIES["noise"], "note": f"noise flags: {','.join(noise_hits)}"}

    last_seen = _parse_ts(candidate.get("last_seen_at"))
    ttl_days = max(1, int(candidate.get("ttl_days") or 30))
    if last_seen is not None:
        age_days = (datetime.now(timezone.utc) - last_seen).total_seconds() / 86400.0
        if age_days > ttl_days:
            frac = min(1.0, (age_days - ttl_days) / ttl_days)
            out["stale"] = {"value": round(PENALTIES["stale"] * frac, 6),
                            "note": f"age {age_days:.1f}d past ttl {ttl_days}d"}

    risk_only = [f for f in flags if f not in _NOISE_FLAGS]
    if risk_only:
        out["risk"] = {"value": min(0.20, PENALTIES["risk"] * len(risk_only)),
                       "note": f"{len(risk_only)} risk flag(s): {','.join(sorted(risk_only)[:5])}"}
    return out


def discovery_score(candidate: dict[str, Any],
                    signals: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compute the composite discovery score for a candidate row/dict.

    Returns {"total": float 0..1, "parts": {...}} — parts is ALWAYS persisted
    to score_json by inbox.py so every score is explainable after the fact.
    `signals` lets future providers inject real component values (0..1);
    anything missing falls back to candidate-derived heuristics or a 0.5 stub.
    """
    signals = signals or {}
    try:
        from .feedback import load_weight_adjustments
        adjustments = load_weight_adjustments()
    except Exception:
        adjustments = {}

    computed: dict[str, tuple[float, str]] = {
        "novelty": _component_novelty(candidate, signals),
        "source_quality": _component_source_quality(candidate, signals, adjustments),
        "cross_source_confirmation": _component_cross_source(candidate, signals),
        "ticker_validation": _component_ticker_validation(candidate, signals),
        "trend_momentum": _component_trend_momentum(candidate, signals, adjustments),
        "outcome_bus_alignment": _component_outcome_bus(candidate, signals),
        "operator_history_lift": _component_operator_history(candidate, signals),
    }

    parts: dict[str, Any] = {"version": SCORING_VERSION, "components": {}, "penalties": {}}
    weighted_sum = 0.0
    for name, weight in WEIGHTS.items():
        value, note = computed[name]
        weighted = round(value * weight, 6)
        weighted_sum += weighted
        parts["components"][name] = {"value": round(value, 6), "weight": weight,
                                     "weighted": weighted, "note": note}

    penalty_sum = 0.0
    for name, info in _penalties(candidate).items():
        parts["penalties"][name] = info
        penalty_sum += float(info["value"])

    raw_total = weighted_sum - penalty_sum
    total = round(_clamp01(raw_total), 6)
    parts["weighted_sum"] = round(weighted_sum, 6)
    parts["penalty_sum"] = round(penalty_sum, 6)
    parts["raw_total"] = round(raw_total, 6)
    return {"total": total, "parts": parts}
