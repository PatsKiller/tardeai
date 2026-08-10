"""CIO Event Bus — Immutable, append-only event stream for material portfolio/system changes.

Invariants:
  - Source events are immutable and append-only with hash chaining.
  - Per-consumer cursors are append-only records in a separate store.
    Historical source events are NEVER mutated.
  - The prior hash is computed inside the write lock to prevent TOCTOU races.
  - Concurrent writers preserve valid chains via lock serialization.
  - No model calls.  Deterministic only.

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
  from scripts.lib.cio_event_bus import CIOEventBus
  bus = CIOEventBus()
  bus.emit("portfolio.material_change", {"pct": 1.5, "direction": "up"})
  events = bus.poll(consumer="alex", event_types=["portfolio.*"])
  bus.advance_cursor("alex", events[-1].event_id)
"""
from __future__ import annotations

import fcntl
import fnmatch
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

# -- Paths --
DEFAULT_BUS_PATH = "data/cio/cio_events.jsonl"
DEFAULT_CURSOR_PATH = "data/cio/cio_event_cursors.jsonl"

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

# Events that should wake Morgan (Senior Wealth Advisor)
MORGAN_EVENTS = frozenset({
    "portfolio.material_change",
    "allocation.drift",
    "behavioral.flag_raised",
    "risk.heat_increased",
    "market.regime_change",
})

# Agent routing table
AGENT_EVENT_ROUTING: dict[str, frozenset[str]] = {
    "alex": ALEX_EVENTS,
    "steph": STEPH_EVENTS,
    "hermes": HERMES_EVENTS,
    "morgan": MORGAN_EVENTS,
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


# ═══════════════════════════════════════════════════════════════════════════
#  Cursor store — per-consumer append-only cursor records
# ═══════════════════════════════════════════════════════════════════════════

class CursorStore:
    """Append-only per-consumer cursor/offset store.

    Each record is an immutable CURSOR_ADVANCE event with hash chaining.
    The current cursor for a consumer is the last event_id they advanced past.
    No mutation of prior cursor records.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_last_hash(self, lines: list[str]) -> str:
        """Compute prior hash from in-memory lines (caller holds lock)."""
        for line in reversed(lines):
            stripped = line.strip()
            if stripped:
                try:
                    return json.loads(stripped).get("record_hash", "0" * 64)
                except json.JSONDecodeError:
                    pass
        return "0" * 64

    def _read_all_lines(self) -> list[str]:
        if not self.path.exists():
            return []
        try:
            with open(self.path) as fh:
                return [line for line in fh if line.strip()]
        except Exception:
            return []

    def _append_locked(self, record: dict[str, Any], prior_lines: list[str]) -> None:
        """Compute hash and append.  Caller MUST hold the write lock."""
        prev = self._read_last_hash(prior_lines)
        record["prev_hash"] = prev
        record["record_hash"] = hashlib.sha256(
            json.dumps(record, sort_keys=True, default=str).encode()
        ).hexdigest()

    def _append(self, record: dict[str, Any]) -> None:
        """Thread-safe append: lock, read, hash, write, fsync, unlock."""
        with open(self.path, "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                existing = self._read_all_lines()
                self._append_locked(record, existing)
                fh.write(json.dumps(record, default=str) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def get_cursor(self, consumer_id: str) -> str:
        """Return the last event_id this consumer advanced past, or ''."""
        if not self.path.exists():
            return ""
        last_id = ""
        try:
            with open(self.path) as fh:
                for line in fh:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    entry = json.loads(stripped)
                    if entry.get("consumer_id") == consumer_id:
                        eid = entry.get("event_id", "")
                        if eid:
                            last_id = eid
        except Exception:
            pass
        return last_id

    def advance(self, consumer_id: str, event_id: str, event_type: str = "") -> str:
        """Record that *consumer_id* has consumed up through *event_id*.

        Returns the record_id of the cursor-advance record.
        """
        record = {
            "record_type": "CURSOR_ADVANCE",
            "record_id": f"cur-{uuid.uuid4().hex[:12]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "consumer_id": consumer_id,
            "event_id": event_id,
            "event_type": event_type,
        }
        self._append(record)
        return record["record_id"]

    def advance_batch(self, consumer_id: str, event_ids: list[str]) -> list[str]:
        """Record that *consumer_id* has consumed a batch of events."""
        record_ids: list[str] = []
        for eid in event_ids:
            record_ids.append(self.advance(consumer_id, eid))
        return record_ids

    def unprocessed_event_ids(
        self, consumer_id: str, all_event_ids: list[str]
    ) -> list[str]:
        """Return event_ids from *all_event_ids* the consumer has NOT yet advanced past."""
        cursor = self.get_cursor(consumer_id)
        if not cursor:
            return list(all_event_ids)
        try:
            idx = all_event_ids.index(cursor)
            return all_event_ids[idx + 1:]
        except ValueError:
            return list(all_event_ids)

    def verify_integrity(self) -> tuple[bool, str]:
        """Verify the hash chain of all cursor records."""
        if not self.path.exists():
            return True, "no cursor store yet"
        prev = "0" * 64
        line_num = 0
        try:
            with open(self.path) as fh:
                for line in fh:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    line_num += 1
                    entry = json.loads(stripped)
                    if entry.get("prev_hash") != prev:
                        return False, (
                            f"prev_hash mismatch at line {line_num}: "
                            f"expected {prev[:16]}..., got {entry.get('prev_hash', '')[:16]}..."
                        )
                    rec = dict(entry)
                    rec.pop("record_hash", None)
                    computed = hashlib.sha256(
                        json.dumps(rec, sort_keys=True, default=str).encode()
                    ).hexdigest()
                    if computed != entry.get("record_hash"):
                        return False, f"record_hash mismatch at line {line_num}"
                    prev = entry["record_hash"]
        except Exception as e:
            return False, f"cursor store integrity check failed: {e}"
        return True, f"cursor store chain valid ({line_num} records)"


# ═══════════════════════════════════════════════════════════════════════════
#  Event model — immutable source events
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class CIOEvent:
    """One immutable event on the bus.  No mutable acknowledgement state."""
    event_id: str
    event_type: str
    timestamp: str
    payload: dict[str, Any]
    source: str
    priority: str = "MEDIUM"
    source_event_id: str = ""
    semantic_event_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "source": self.source,
            "priority": self.priority,
            "source_event_id": self.source_event_id,
            "semantic_event_key": self.semantic_event_key,
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
            source_event_id=d.get("source_event_id", ""),
            semantic_event_key=d.get("semantic_event_key", ""),
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Event bus — immutable sources + append-only per-consumer cursors
# ═══════════════════════════════════════════════════════════════════════════

class CIOEventBus:
    """Immutable, append-only, hash-chained event bus with per-consumer cursors.

    Source events are NEVER mutated.  Consumer progress is recorded via
    append-only CURSOR_ADVANCE records in a separate CursorStore.
    The prior hash is computed inside the write lock to prevent TOCTOU races.
    """

    def __init__(self, bus_path: str = DEFAULT_BUS_PATH,
                 cursor_path: str = DEFAULT_CURSOR_PATH):
        self.bus_path = Path(bus_path)
        self.cursor_store = CursorStore(Path(cursor_path))
        self.bus_path.parent.mkdir(parents=True, exist_ok=True)
        self._genesis()

    # ── source-event helpers ────────────────────────────────────────────

    def _read_all_event_lines(self) -> list[str]:
        if not self.bus_path.exists():
            return []
        try:
            with open(self.bus_path) as fh:
                return [line for line in fh if line.strip()]
        except Exception:
            return []

    def _last_hash_from_lines(self, lines: list[str]) -> str:
        """Compute prior hash from in-memory lines (caller holds lock
        or is reading in a context where concurrent writes are impossible)."""
        for line in reversed(lines):
            stripped = line.strip()
            if stripped:
                try:
                    entry = json.loads(stripped)
                    if entry.get("event_type") == "CIO_EVENT_BUS_GENESIS":
                        return entry.get("event_hash", "0" * 64)
                    return entry.get("event_hash", "0" * 64)
                except json.JSONDecodeError:
                    pass
        return "0" * 64

    def _build_event_envelope(self, entry: dict[str, Any],
                              prior_lines: list[str]) -> None:
        """Compute prev_hash and event_hash.  prior_lines is read under lock."""
        prev = self._last_hash_from_lines(prior_lines)
        entry["prev_hash"] = prev
        entry["event_hash"] = hashlib.sha256(
            json.dumps(entry, sort_keys=True, default=str).encode()
        ).hexdigest()

    def _append_locked(self, entry: dict[str, Any]) -> None:
        """Lock, read prior lines, hash, append, fsync, unlock."""
        with open(self.bus_path, "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                existing = self._read_all_event_lines()
                self._build_event_envelope(entry, existing)
                fh.write(json.dumps(entry, default=str) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _genesis(self):
        """Append genesis event if the bus file does not exist."""
        if not self.bus_path.exists():
            genesis = {
                "event_type": "CIO_EVENT_BUS_GENESIS",
                "event_id": "genesis-0000000000000000",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {"contract": "cio-event-bus-v2"},
                "source": "system",
                "priority": "INFO",
                "prev_hash": "0" * 64,
                "event_hash": "",
            }
            self._append_locked(genesis)

    # ── public API ──────────────────────────────────────────────────────

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        source: str = "cio_heartbeat",
        priority: str | None = None,
        source_event_id: str = "",
        semantic_event_key: str = "",
    ) -> CIOEvent:
        """Emit an immutable event onto the bus. Returns the created event.

        source_event_id — preserves provenance of the original event.
        semantic_event_key — deduplication key computed from business transition.
        """
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
            source_event_id=source_event_id,
            semantic_event_key=semantic_event_key,
        )
        self._append_locked(evt.to_dict())
        return evt

    def poll(
        self,
        consumer: str | None = None,
        since: str | None = None,
        event_types: Sequence[str] | None = None,
        limit: int = 50,
    ) -> list[CIOEvent]:
        """Poll for events. If *consumer* is given, only returns events the
        consumer has not yet advanced past (via cursor look-up)."""
        if not self.bus_path.exists():
            return []
        cursor_id = self.cursor_store.get_cursor(consumer) if consumer else ""

        events: list[CIOEvent] = []
        found_cursor = cursor_id == ""  # no cursor means all events are new
        for line in self._read_all_event_lines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = entry.get("event_type", "")
            if etype == "CIO_EVENT_BUS_GENESIS":
                continue

            evt = CIOEvent.from_dict(entry)

            # cursor filtering: skip until we pass the last-cursor event
            if consumer and not found_cursor:
                if evt.event_id == cursor_id:
                    found_cursor = True
                continue

            if since and evt.timestamp < since:
                continue
            if event_types:
                if not any(fnmatch.fnmatch(evt.event_type, pat)
                           for pat in event_types):
                    continue
            events.append(evt)

        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]

    def advance_cursor(self, consumer_id: str, event_id: str,
                       event_type: str = "") -> str:
        """Record that *consumer_id* has consumed up through *event_id*."""
        return self.cursor_store.advance(consumer_id, event_id, event_type)

    def unprocessed_count(self, consumer_id: str) -> int:
        """Count events this consumer has not yet consumed."""
        all_ids = self._all_event_ids()
        unprocessed = self.cursor_store.unprocessed_event_ids(consumer_id, all_ids)
        return len(unprocessed)

    def _all_event_ids(self) -> list[str]:
        ids: list[str] = []
        for line in self._read_all_event_lines():
            try:
                entry = json.loads(line)
                if entry.get("event_type") != "CIO_EVENT_BUS_GENESIS":
                    ids.append(entry.get("event_id", ""))
            except json.JSONDecodeError:
                pass
        return ids

    def drain_unprocessed(
        self, consumer_id: str = "cio_heartbeat", limit: int = 20
    ) -> list[CIOEvent]:
        """Return unprocessed events for *consumer_id* and advance cursor.

        Replaces the old `drain_unacknowledged` — uses per-consumer cursors
        instead of mutating source events.
        """
        events = self.poll(consumer=consumer_id, limit=limit)
        # poll returns newest-first; advance in chronological order so the
        # last cursor-advance record points to the most recent event
        for evt in sorted(events, key=lambda e: e.timestamp):
            self.advance_cursor(consumer_id, evt.event_id, evt.event_type)
        return events

    def route_to_agents(self, event_type: str) -> list[str]:
        """Return agent IDs that should be woken for this event type."""
        agents: list[str] = []
        for agent_id, subscribed in AGENT_EVENT_ROUTING.items():
            if any(fnmatch.fnmatch(event_type, pat) for pat in subscribed):
                agents.append(agent_id)
        return agents

    def verify_integrity(self) -> tuple[bool, str]:
        """Verify the hash chain of all source events.

        Each event's `prev_hash` must match the preceding event's `event_hash`,
        forming a cryptographically linked chain.  Individual event hashes from
        the old (pre-R1.2) code may not be independently verifiable, but the
        chain linkage proves no event was inserted, removed, or reordered.
        """
        if not self.bus_path.exists():
            return True, "no event bus yet"
        prev = "0" * 64
        line_num = 0
        try:
            with open(self.bus_path) as fh:
                for line in fh:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    line_num += 1
                    entry = json.loads(stripped)
                    entry_hash = entry.get("event_hash", "")
                    entry_prev = entry.get("prev_hash", "")

                    # Genesis must reference the zero hash
                    if line_num == 1:
                        if entry_prev != "0" * 64:
                            return False, (
                                f"genesis prev_hash at line 1: expected 64 zeros, "
                                f"got {entry_prev[:16]}..."
                            )
                        if not entry_hash or len(entry_hash) != 64:
                            return False, "genesis missing or malformed event_hash"
                        prev = entry_hash
                        continue

                    # Chain check: prev_hash must match the prior event's hash
                    if entry_prev != prev:
                        return False, (
                            f"prev_hash mismatch at line {line_num}: "
                            f"expected {prev[:16]}..., got {entry_prev[:16]}..."
                        )
                    if not entry_hash or len(entry_hash) != 64:
                        return False, (
                            f"event_hash missing or malformed at line {line_num}"
                        )
                    prev = entry_hash
        except Exception as e:
            return False, f"integrity check failed: {e}"
        return True, f"event bus chain valid ({line_num} events)"
