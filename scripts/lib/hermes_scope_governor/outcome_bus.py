"""Scope Governor consumption of outcome_bus.json feedback."""
from __future__ import annotations

from typing import Any

from lib.hermes_outcome_bus.bus import governor_feedback_index, load_outcome_bus


def apply_bus_to_edge_scores(
    edge_scores: dict[str, float],
    edge_details: dict[str, dict],
    cfg: dict[str, Any],
) -> tuple[dict[str, float], dict[str, dict]]:
    """Overlay explicit bus feedback onto edge scores (advisory reinforcement)."""
    bus = load_outcome_bus()
    feedback = governor_feedback_index(bus)
    if not feedback:
        return edge_scores, edge_details

    scfg = cfg.get("scoring") or {}
    gates = scfg.get("outcome_gates") or {}
    demote_penalty = float(gates.get("demote_score_penalty", 20))
    promote_boost = float(gates.get("promote_score_boost", 8))

    updated_scores = dict(edge_scores)
    updated_details = {k: dict(v) for k, v in edge_details.items()}

    for sym, item in feedback.items():
        action = str(item.get("action") or "")
        es = updated_scores.get(sym)
        if es is None:
            continue
        detail = updated_details.setdefault(sym, {})
        reasons = list(detail.get("reasons") or [])
        if action == "demote_pressure":
            pen = item.get("edge_penalty")
            delta = float(pen) if pen is not None else -demote_penalty
            updated_scores[sym] = max(0.0, es + delta)
            reasons.append(f"bus:{action}")
        elif action == "promote_eligible":
            boost = item.get("edge_boost")
            delta = float(boost) if boost is not None else promote_boost
            updated_scores[sym] = min(100.0, es + delta)
            reasons.append(f"bus:{action}")
        elif action == "pause":
            updated_scores[sym] = min(es, 15.0)
            reasons.append("bus:pause")
        detail["reasons"] = reasons
        detail["bus_feedback"] = item

    return updated_scores, updated_details


def bus_tier_override(sym: str, desired: str, cur_tier: str | None, cfg: dict[str, Any]) -> tuple[str, str] | None:
    """Force tier changes from bus pause/demote when graft gates pass. Returns (tier, reason) or None."""
    if cur_tier == "S0":
        return None  # capital exposed — never bus-demoted

    bus = load_outcome_bus()
    item = governor_feedback_index(bus).get(sym.upper())
    if not item:
        return None

    action = str(item.get("action") or "")
    min_n = int((cfg.get("scoring") or {}).get("outcome_gates", {}).get("min_graded_samples", 3))
    evidence = item.get("evidence") or {}
    graded = int(evidence.get("n") or evidence.get("graded_n") or 0)
    if graded < min_n:
        return None

    if action == "pause" and desired in ("S0", "S1", "S2"):
        return "S3", f"bus_pause({item.get('reason', '')})"
    if action == "demote_pressure" and desired == "S1" and cur_tier in ("S1", "S2"):
        return "S2" if cur_tier == "S1" else "S3", f"bus_demote_pressure({item.get('reason', '')})"
    return None