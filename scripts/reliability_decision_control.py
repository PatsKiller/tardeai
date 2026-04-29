#!/usr/bin/env python3
"""
Reliability-driven decision control.

Turns DB reliability context into behavior:
- allow
- force_review
- require_manual_approval
- block_write
- block_all_high_impact
"""

from typing import Dict, Any


CRITICAL_FILES = {
    "steph": ["holdings.json", "risk_management.json", "asset_intelligence.json"],
    "risk_agent": ["holdings.json", "risk_management.json", "stops.json", "technical_snapshot.json"],
    "maria": ["holdings.json", "portfolio_news.json", "analyst_data.json", "asset_intelligence.json"],
    "tax_agent": ["holdings.json", "risk_management.json"],
    "orchestrator": ["holdings.json", "risk_management.json"],
}


def apply_reliability_controls(route: Dict[str, Any]) -> Dict[str, Any]:
    rel = route.get("reliability") or {}
    agent = route.get("to_agent", "orchestrator")
    score = float(rel.get("reliability_score", 1.0) or 1.0)

    missing = set(rel.get("missing") or [])
    bad = set(rel.get("bad") or [])
    weak = set(rel.get("weak") or [])
    critical = set(CRITICAL_FILES.get(agent, []))

    critical_bad = sorted((missing | bad) & critical)
    action_type = route.get("action_type", "read_only")
    high_impact = bool(route.get("high_impact"))

    controls = {
        "mode": "allow",
        "reliability_score": score,
        "critical_bad": critical_bad,
        "forced_reviewers": [],
        "blocked": False,
        "requires_manual_approval": False,
        "reasons": [],
    }

    if critical_bad:
        controls["mode"] = "block_write"
        controls["blocked"] = action_type in {"pending_write", "write"}
        controls["requires_manual_approval"] = True
        controls["reasons"].append(
            "Critical dependency unreliable: " + ", ".join(critical_bad)
        )

    elif score < 0.65:
        controls["mode"] = "block_all_high_impact"
        controls["blocked"] = high_impact or action_type in {"pending_write", "write"}
        controls["requires_manual_approval"] = True
        controls["reasons"].append(f"Reliability score too low: {score}")

    elif score < 0.80:
        controls["mode"] = "require_manual_approval"
        controls["requires_manual_approval"] = True
        controls["reasons"].append(f"Reliability score below approval threshold: {score}")

    elif score < 0.90 or weak:
        controls["mode"] = "force_review"
        controls["requires_manual_approval"] = action_type in {"pending_write", "write"}
        controls["reasons"].append("Reliability history is limited or mildly degraded.")

    if agent == "steph" and (score < 0.90 or critical_bad):
        controls["forced_reviewers"].extend(["risk_agent", "tax_agent"])
    if agent == "risk_agent" and (score < 0.90 or critical_bad):
        controls["forced_reviewers"].append("maria")
    if agent == "maria" and (score < 0.90 or critical_bad):
        controls["forced_reviewers"].append("steph")

    controls["forced_reviewers"] = sorted(set(controls["forced_reviewers"]))

    route["reliability_controls"] = controls

    if controls["forced_reviewers"]:
        existing = set(route.get("reviewers") or [])
        route["reviewers"] = sorted(existing | set(controls["forced_reviewers"]))
        route["status"] = "routed_multi_review"

    if controls["requires_manual_approval"]:
        route.setdefault("pending_actions", []).append({
            "type": "reliability_manual_approval_required",
            "message": "Reliability controls require manual approval before execution.",
            "reasons": controls["reasons"],
        })

    if controls["blocked"]:
        route["status"] = "blocked_by_reliability"
        route.setdefault("pending_actions", []).append({
            "type": "reliability_block",
            "message": "Write/high-impact action blocked until reliability recovers.",
            "reasons": controls["reasons"],
        })

    if controls["mode"] != "allow":
        route["short_telegram"] = (
            route.get("short_telegram", "")
            + f" Reliability control: {controls['mode']}."
        )
        route["full_dashboard"] = (
            route.get("full_dashboard", "")
            + "\n\nReliability Control: "
            + controls["mode"]
            + " — "
            + "; ".join(controls["reasons"])
        )

    return route
