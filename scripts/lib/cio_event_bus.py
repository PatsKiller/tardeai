"""CIO Event Bus — Append-only event stream for material portfolio/system changes.

Agents subscribe to events instead of polling cron timers.  The bus is the
single source of truth for "something happened that an agent should react to."
Deterministic, hash-chained, no model calls.

Event types cover the full CIO surface:
  portfolio.material_change  — >1% value move
  risk.heat_increased        — heat crossed threshold
  risk.stop_triggered        — protective stop fired
  allocation.drift           — drift > rebalancing threshold
  action.stale               — OPEN action > 7 days
  action.operator_silence    — High-priority action not acknowledged in 24h
  hermes.contradiction_found — Hermes found conflicting research
  hermes.research_promoted   — New research promoted to knowledge base
  watch.new_signal           — New watch directive fired
  reconciliation.drift       — Broker sync discrepancy
  market.regime_change       — VIX regime / sector rotation shift
  behavioral.flag_raised     — Disposition effect or other bias detected
  cost_basis.material_change — Cost basis data changed materially

Usage:
  from scripts.lib.cio_event_bus import CIOEventBus, CIOEvent
  bus = CIOEventBus()
  bus.emit("portfolio.material_change", {"pct": 1.5, "direction": "up"})
  events = bus.poll(since="2026-08-09T00:00:00Z", event_types=["portfolio.*"])
"""
from __future__ import annotations

import fcntl
import fnmatch
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

# -- Paths --
DEFAULT_BUS_PATH = "data/cio/cio_events.jsonl"

# -- Canonical event types --
VALID_EVENT_TYPES = frozenset({
    "portfolio.material_change",
    "risk.heat_increased",
    "risk.stop_triggered",
    "allocation.drift",
    "action.stale",
    "action.operator_silence",
    "hermes.contradiction_found",
    "hermes.research_promoted",
    "watch.new_signal",
    "reconciliation.drift",
    "market.regime_change",
    "behavioral.flag_raised",
    "cost_basis.material_change",
    "system.heartbeat_ok",
    "system.domain_stale",
})

# Events that should wake Alex
ALEX_EVENTS = frozenset({
    "portfolio.material_change",
    "risk.heat_increased",
    "allocation.drift",
    "action.stale",
    "action.operator_silence",
    "hermes.contradiction_found",
    "hermes.research_promoted",
    "watch.new_signal",
    "reconciliation.drift",
    "market.regime_change",
    "behavioral.flag_raised",
    "system.domain_stale",
})

# Events that should wake Steph
STEPH_EVENTS = frozenset({
    "portfolio.material_change",
    "allocation.drift",
    "market.regime_change",
})

# Events that should wake Hermes
HERMES_EVENTS = frozenset({
    "hermes.contradiction_found",
    "hermes.research_promoted",
    "watch.new_signal",
    "market.regime_change",
})

# Agent routing table
AGENT_EVENT_ROUTING: dict[str, frozenset[str]] = {
    "alex": ALEX_EVENTS,
    "steph": STEPH_EVENTS,
    "hermes": HERMES_EVENTS,
}

# Priority mapping for wake job creation
EVENT_PRIORITY: dict[str, str] = {
    "portfolio.material_change": "HIGH",
    "risk.heat_increased": "HIGH",
    "risk.stop_triggered": "HIGH",
    "allocation.drift": "MEDIUM",
    "action.stale": "MEDIUM",
    "action.operator_silence": "HIGH",
    "hermes.contradiction_found": "HIGH",
    "hermes.research_promoted": "MEDIUM",
    "watch.new_signal": "MEDIUM",
    "reconciliation.drift": "MEDIUM",
    "market.regime_change": "HIGH",
    "behavioral.flag_raised": "HIGH",
    "cost_basis.material_change": "LOW",
    "system.heartbeat_ok": "LOW",
    "system.domain_stale": "HIGH",
}


@dataclass
class CIOEvent:
    """One event on the bus."""
    event_id: str
    event_type: str
    timestamp: str
    payload: dict[str, Any]
    source: str           # "cio_heartbeat", "sentinel", "hermes", "operator"
    priority: str = "MEDIUM"
    acknowledged: bool = False
    acknowledged_at: str = ""
    acknowledged_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "source": self.source,
            "priority": self.priority,
            "acknowledged": self.acknowledged,
            "acknowledged_at": self.acknowledged_at,
            "acknowledged_by": self.acknowledged_by,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CIOEvent":
        return cls(
            event_id=d.get("event_id", ""),
            event_type=d.get("event_type", ""),
            timestamp=d.get("timestamp", ""),
            payload=d.get("payload", {}),
            source=d.get("source", ""),
            priority=d.get("priority", "MEDIUM"),
            acknowledged=d.get("acknowledged", False),
            acknowledged_at=d.get("acknowledged_at", ""),
            acknowledged_by=d.get("acknowledged_by", ""),
        )


class CIOEventBus:
    """Append-only, hash-chained event bus.

    Subscribers poll for events matching patterns (e.g. "portfolio.*").
    The bus is the source of truth for material changes — agents react to
    events instead of polling cron timers.
    """

    def __init__(self, bus_path: str = DEFAULT_BUS_PATH):
        self.bus_path = Path(bus_path)
        self.lock_path = Path(str(bus_path) + ".lock")
        self.bus_path.parent.mkdir(parents=True, exist_ok=True)
        self._genesis()

    def _genesis(self):
        if not self.bus_path.exists():
            self._append({
                "event_type": "CIO_EVENT_BUS_GENESIS",
                "event_id": "genesis-0000000000000000",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {"contract": "cio-event-bus-v1"},
                "source": "system",
                "priority": "INFO",
                "acknowledged": True,
                "acknowledged_at": datetime.now(timezone.utc).isoformat(),
                "acknowledged_by": "system",
                "prev_hash": "0" * 64,
                "event_hash": "",
            })

    def _last_hash(self) -> str:
        if not self.bus_path.exists():
            return "0" * 64
        try:
            with open(self.bus_path) as f:
                last = None
                for line in f:
                    if line.strip():
                        last = line.strip()
                if last:
                    return json.loads(last).get("event_hash", "0" * 64)
        except Exception:
            pass
        return "0" * 64

    def _append(self, entry: dict[str, Any]) -> None:
        prev_hash = self._last_hash()
        entry["prev_hash"] = prev_hash
        entry["event_hash"] = hashlib.sha256(
            json.dumps(entry, sort_keys=True, default=str).encode()
        ).hexdigest()
        with open(self.bus_path, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(json.dumps(entry, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
            fcntl.flock(f, fcntl.LOCK_UN)

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        source: str = "cio_heartbeat",
        priority: str | None = None,
    ) -> CIOEvent:
        """Emit an event onto the bus. Returns the created event."""
        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(
                f"Unknown event type: {event_type}. "
                f"Valid: {sorted(VALID_EVENT_TYPES)}"
            )
        evt = CIOEvent(
            event_id=f"evt-{uuid.uuid4().hex[:12]}",
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=payload,
            source=source,
            priority=priority or EVENT_PRIORITY.get(event_type, "MEDIUM"),
        )
        self._append(evt.to_dict())
        return evt

    def acknowledge(self, event_id: str, by: str = "alex") -> bool:
        """Mark an event as acknowledged. Returns True if found."""
        if not self.bus_path.exists():
            return False
        lines = self.bus_path.read_text().strip().splitlines()
        found = False
        updated: list[str] = []
        for line in lines:
            entry = json.loads(line)
            if entry.get("event_id") == event_id and not entry.get("acknowledged"):
                entry["acknowledged"] = True
                entry["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
                entry["acknowledged_by"] = by
                found = True
            updated.append(json.dumps(entry, default=str))
        if found:
            self.bus_path.write_text("\n".join(updated) + "\n")
        return found

    def poll(
        self,
        since: str | None = None,
        event_types: Sequence[str] | None = None,
        unacknowledged_only: bool = False,
        limit: int = 50,
    ) -> list[CIOEvent]:
        """Poll for events matching filters. Most recent first."""
        if not self.bus_path.exists():
            return []
        events: list[CIOEvent] = []
        for line in self.bus_path.read_text().strip().splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("event_type") == "CIO_EVENT_BUS_GENESIS":
                continue

            evt = CIOEvent.from_dict(entry)
            if since and evt.timestamp < since:
                continue
            if event_types:
                if not any(fnmatch.fnmatch(evt.event_type, pat) for pat in event_types):
                    continue
            if unacknowledged_only and evt.acknowledged:
                continue
            events.append(evt)

        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]

    def unacknowledged_count(self) -> int:
        """Count unacknowledged events."""
        return len(self.poll(unacknowledged_only=True, limit=1000))

    def route_to_agents(self, event_type: str) -> list[str]:
        """Return agent IDs that should be woken for this event type."""
        agents: list[str] = []
        for agent_id, subscribed in AGENT_EVENT_ROUTING.items():
            if any(fnmatch.fnmatch(event_type, pat) for pat in subscribed):
                agents.append(agent_id)
        return agents

    def drain_unacknowledged(self, limit: int = 20) -> list[CIOEvent]:
        """Return unacknowledged events and mark them acknowledged.

        Call this from the heartbeat or wake worker to process pending events
        and prevent duplicate wake jobs.
        """
        events = self.poll(unacknowledged_only=True, limit=limit)
        for evt in events:
            self.acknowledge(evt.event_id, by="cio_heartbeat")
        return events
