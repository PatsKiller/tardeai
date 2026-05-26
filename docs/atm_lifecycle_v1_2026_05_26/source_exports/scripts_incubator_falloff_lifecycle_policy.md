# Source Export: scripts/incubator_falloff_lifecycle_policy.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/incubator_falloff_lifecycle_policy.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `f136747bf29e5060e4339ef1f1700d234baacb8e3efa5a189dca7cdeecb23218` |
| **File Size** | 3785 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""incubator_falloff_lifecycle_policy.py — Rules for ticker screener falloff.

Pure functions. No DB writes. No trades. No promotions.
"""
from strategy_watch_horizon_policy import get_default_watch_horizon

MISSING_THRESHOLD_RUNS = 3  # Mark stale after 3 consecutive missing runs
EXPIRE_AFTER_DAYS_WITHOUT_SOURCE = 14  # Expire if no source for 14 days


def classify_source_membership_state(candidate: dict, memberships: list) -> dict:
    """Classify whether a candidate's source screeners still contain it."""
    present = [m for m in memberships if m.get("present_this_run") or m.get("membership_status") == "present"]
    dropped = [m for m in memberships if m.get("membership_status") == "dropped"]
    stale = [m for m in memberships if m.get("membership_status") == "stale"]

    if present:
        return {"state": "active_in_sources", "present_count": len(present), "dropped_count": len(dropped)}
    if dropped and not present:
        return {"state": "dropped_from_all", "present_count": 0, "dropped_count": len(dropped)}
    if stale:
        return {"state": "stale_all_sources", "present_count": 0, "dropped_count": len(dropped)}
    if not memberships:
        return {"state": "no_membership_data", "present_count": 0, "dropped_count": 0}
    return {"state": "unknown", "present_count": len(present), "dropped_count": len(dropped)}


def determine_retention_ttl(candidate: dict, strategy_id: str = None) -> dict:
    """How long to retain a candidate after source goes missing."""
    sid = strategy_id or candidate.get("strategy_id", "")
    horizon = get_default_watch_horizon(sid)
    return {
        "ttl_days": horizon["max_days"],
        "strategy_id": sid,
        "reason": f"{sid} max watch horizon {horizon['max_days']} days",
    }


def classify_falloff_action(candidate: dict, membership_state: dict) -> dict:
    """Determine what should happen to a candidate based on source state."""
    state = membership_state.get("state", "unknown")
    age = int(candidate.get("days_active") or 0)
    sid = candidate.get("strategy_id", "")
    ttl = determine_retention_ttl(candidate, sid)

    if state == "active_in_sources":
        return {"action": "keep_active", "reason": "Still present in source screeners", "human_review_only": True}
    if state == "dropped_from_all":
        if age < ttl["ttl_days"]:
            return {"action": "retain_by_ttl", "reason": f"Dropped but within {ttl['ttl_days']}d TTL ({age}d active)",
                    "ttl_remaining": ttl["ttl_days"] - age, "human_review_only": True}
        return {"action": "expire", "reason": f"Dropped from all sources and TTL expired ({age}d > {ttl['ttl_days']}d)",
                "human_review_only": True}
    if state == "stale_all_sources":
        return {"action": "expire", "reason": "All source screeners stale", "human_review_only": True}
    if state == "no_membership_data":
        return {"action": "retain_no_data", "reason": "No membership data — retain until membership established",
                "human_review_only": True}
    return {"action": "review", "reason": f"Unknown state: {state}", "human_review_only": True}


def build_falloff_audit_event(candidate: dict, action: dict) -> dict:
    """Build an audit event for the falloff decision."""
    return {
        "symbol": candidate.get("symbol"),
        "strategy_id": candidate.get("strategy_id"),
        "action": action["action"],
        "reason": action["reason"],
        "event_type": {
            "keep_active": "present",
            "retain_by_ttl": "retained",
            "expire": "expired",
            "retain_no_data": "retained",
            "review": "review_required",
        }.get(action["action"], "unknown"),
        "human_review_only": True,
    }
```
