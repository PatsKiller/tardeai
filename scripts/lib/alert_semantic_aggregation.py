"""Aggregate raw alert events into semantic generations.

Do not delete underlying events. Operator messages are counted by meaning.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0


def semantic_key(event: dict[str, Any]) -> str:
    kind = str(event.get("alert_type") or event.get("type") or "event").lower()
    if kind in {"hermes_rank_surge", "hermes_score_move"}:
        return f"hermes_rank:{event.get('symbol') or '*'}"
    payload = {
        "type": kind,
        "symbol": event.get("symbol"),
        "state": event.get("state") or event.get("to_state") or event.get("status"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def aggregate(events: list[dict[str, Any]]) -> dict[str, Any]:
    gens: dict[str, dict[str, Any]] = {}
    for ev in events:
        key = semantic_key(ev)
        slot = gens.setdefault(key, {"key": key, "n": 0, "sample": ev})
        slot["n"] += 1
    operator_messages = []
    for slot in gens.values():
        n = slot["n"]
        sample = slot["sample"]
        kind = str(sample.get("alert_type") or sample.get("type") or "event")
        if kind in {"hermes_rank_surge", "hermes_score_move"} and n > 1:
            operator_messages.append({
                "key": slot["key"],
                "text": (
                    f"Hermes rank movement for {sample.get('symbol') or 'multiple names'} "
                    f"({n} raw events aggregated). Not a CIO decision."
                ),
                "channel": "RESEARCH_INTELLIGENCE" if n < 20 else "OPS_HEALTH",
            })
        else:
            operator_messages.append({
                "key": slot["key"],
                "text": str(sample.get("raw_text") or sample.get("text") or kind),
                "channel": "OPS_HEALTH" if kind.startswith("health") else "RESEARCH_INTELLIGENCE",
            })
    return {
        "schema": "AlertSemanticAggregation@v1",
        "raw_events": len(events),
        "semantic_generations": len(gens),
        "operator_messages": len(operator_messages),
        "messages": operator_messages[:50],
        "deleted": 0,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }
