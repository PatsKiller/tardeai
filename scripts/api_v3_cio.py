"""api_v3_cio.py — /v3/cio Command Center API: CIO dashboard data.

Serves the CIO Data Broker projection, action ledger, delegation status,
and Hermes research — all deterministic, zero model calls, zero provider cost.

Routes:
  GET /api/v3/cio              — Full CIO dashboard (snapshot + actions + delegation)
  GET /api/v3/cio/snapshot      — CIO Data Broker snapshot only
  GET /api/v3/cio/actions       — Open action items from the JSONL ledger
  GET /api/v3/cio/delegation    — Delegation + Hermes challenge status
  GET /api/v3/cio/hermes        — Hermes research intelligence summary
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def _cio_snapshot_data() -> dict[str, Any]:
    """Get the CIO Data Broker snapshot."""
    try:
        from lib.data_broker.cio_portfolio import get_cio_snapshot
        return get_cio_snapshot(max_age_s=30)
    except Exception:
        return {"error": "Data Broker unavailable", "domains": {}, "health": {}}


def _cio_actions_data(limit: int = 20) -> list[dict[str, Any]]:
    """Get CIO actions from the event-sourced JSONL ledger."""
    ledger_path = PROJECT_ROOT / "data" / "cio" / "cio_action_ledger.jsonl"
    events = _read_jsonl(ledger_path)
    actions: dict[str, dict[str, Any]] = {}

    for event in events:
        payload = event.get("payload", {})
        aid = payload.get("cio_action_id")
        if not aid:
            continue
        event_type = event.get("event_type", "")
        if event_type == "CIO_ACTION_CREATED":
            actions[aid] = payload
        elif event_type == "CIO_ACTION_UPDATED":
            if aid in actions:
                actions[aid].update(payload)

    open_actions = [
        a for a in actions.values()
        if a.get("status") in ("OPEN", "ACKNOWLEDGED")
    ]
    return sorted(open_actions, key=lambda a: a.get("created_at", ""), reverse=True)[:limit]


def _delegation_data() -> dict[str, Any]:
    """Get delegation and Hermes challenge status."""
    handoff_path = PROJECT_ROOT / "data" / "cio" / "agent_handoff_queue.jsonl"
    challenge_path = PROJECT_ROOT / "data" / "cio" / "hermes_challenge_queue.jsonl"

    handoffs = _read_jsonl(handoff_path)
    challenges = _read_jsonl(challenge_path)

    # Count by status
    handoff_statuses: dict[str, int] = {}
    for h in handoffs:
        et = h.get("event_type", "")
        if "ENQUEUED" in et:
            handoff_statuses["ENQUEUED"] = handoff_statuses.get("ENQUEUED", 0) + 1
        elif "BLOCKED" in et:
            handoff_statuses["BLOCKED"] = handoff_statuses.get("BLOCKED", 0) + 1
        elif "COMPLETED" in et:
            handoff_statuses["COMPLETED"] = handoff_statuses.get("COMPLETED", 0) + 1

    challenge_statuses: dict[str, int] = {}
    for c in challenges:
        et = c.get("event_type", "")
        if "ENQUEUED" in et:
            challenge_statuses["ENQUEUED"] = challenge_statuses.get("ENQUEUED", 0) + 1
        elif "RESOLVED" in et:
            challenge_statuses["RESOLVED"] = challenge_statuses.get("RESOLVED", 0) + 1

    # Latest events
    latest_handoff = handoffs[-1] if handoffs else None
    latest_challenge = challenges[-1] if challenges else None

    return {
        "handoffs": {
            "statuses": handoff_statuses,
            "total": len([h for h in handoffs if h.get("event_type") != "HANDOFF_QUEUE_GENESIS"]),
            "latest": {
                "event_type": latest_handoff.get("event_type"),
                "stream_id": latest_handoff.get("stream_id"),
                "timestamp": latest_handoff.get("timestamp"),
            } if latest_handoff else None,
        },
        "challenges": {
            "statuses": challenge_statuses,
            "total": len([c for c in challenges if c.get("event_type") != "HERMES_CHALLENGE_GENESIS"]),
            "latest": {
                "event_type": latest_challenge.get("event_type"),
                "stream_id": latest_challenge.get("stream_id"),
                "challenge_type": (latest_challenge.get("payload") or {}).get("challenge_type") if latest_challenge else None,
                "timestamp": latest_challenge.get("timestamp"),
            } if latest_challenge else None,
        },
    }


def get_cio_dashboard() -> dict[str, Any]:
    """Full CIO dashboard payload for /v3/cio."""
    snapshot = _cio_snapshot_data()
    actions = _cio_actions_data(15)
    delegation = _delegation_data()

    return {
        "ok": True,
        "as_of": _now_iso(),
        "snapshot": snapshot,
        "actions": actions,
        "delegation": delegation,
        "model_provider": "deepseek-v4-pro",
        "fallback": "deepseek-v4-flash → free-oauth (grok/chatgpt)",
        "authority": "READ_ONLY_ADVISORY",
    }


def get_cio_snapshot() -> dict[str, Any]:
    return {"ok": True, "as_of": _now_iso(), "snapshot": _cio_snapshot_data()}


def get_cio_actions() -> dict[str, Any]:
    actions = _cio_actions_data(30)
    return {"ok": True, "as_of": _now_iso(), "actions": actions, "count": len(actions)}


def get_cio_delegation() -> dict[str, Any]:
    return {"ok": True, "as_of": _now_iso(), "delegation": _delegation_data()}
