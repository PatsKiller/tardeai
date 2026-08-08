"""
CIO Operator Profile — Deterministic versioned operator profile store.

Event-sourced authoritative store for operator profile, investment policy statement,
financial goals, account constraints, and related domains. Uses the same pattern as
all Phase -1 modules: append-only JSONL with file lock, fsync, and hash chain.

Event store path: data/cio/operator_profile.jsonl

Authority: Only OPERATOR_CONFIRMED facts can support material financial advice.
UNVERIFIED, SUPERSEDED, EXPIRED, or CONFLICTED facts must be flagged.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ═══════════════════════════════════════════════════════════════════════════════
# Canonical constants
# ═══════════════════════════════════════════════════════════════════════════════

VALID_EVENT_TYPES = frozenset({
    "PROFILE_CREATED",
    "PROFILE_UPDATED",
    "PROFILE_CONFIRMED",
    "PROFILE_SUPERSEDED",
    "PROFILE_DEPRECATED",
    "OPERATOR_PROFILE_GENESIS",
})

FIELD_STATUSES = frozenset({
    "UNVERIFIED",
    "OPERATOR_CONFIRMED",
    "SUPERSEDED",
    "EXPIRED",
    "CONFLICTED",
})

SUPPORTED_DOMAINS = frozenset({
    "operator_profile",
    "investment_policy_statement",
    "goals",
    "account_constraints",
    "cash_liquidity_needs",
    "risk_constraints",
    "tax_constraints",
    "retirement_constraints",
    "income_needs",
    "time_horizon",
    "communication_preferences",
})

GENESIS_PREV_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

ALLOWED_ACTOR_TYPES = frozenset({"agent", "operator", "system"})

# ═══════════════════════════════════════════════════════════════════════════════
# Deterministic serialization and hashing
# ═══════════════════════════════════════════════════════════════════════════════


def canonicalize_payload(payload: dict[str, Any]) -> str:
    """Deterministic JSON serialization: sorted keys, compact, no trailing whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_payload_hash(payload: dict[str, Any]) -> str:
    """SHA-256 hash of the canonicalized payload."""
    return hashlib.sha256(canonicalize_payload(payload).encode("utf-8")).hexdigest()


def compute_event_hash(
    event_id: str,
    event_type: str,
    occurred_at: str,
    prev_event_hash: str,
    payload_hash: str,
) -> str:
    """SHA-256 hash that chains events together."""
    raw = f"{event_id}|{event_type}|{occurred_at}|{prev_event_hash}|{payload_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_event(
    event_type: str,
    payload: dict[str, Any],
    prev_event_hash: str,
    *,
    actor: str = "system",
    actor_type: str = "system",
) -> dict[str, Any]:
    """Build a complete event record with hash chain."""
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Invalid event type: {event_type}")
    if actor_type not in ALLOWED_ACTOR_TYPES:
        raise ValueError(f"Invalid actor type: {actor_type}")

    event_id = str(uuid.uuid4())
    occurred_at = datetime.now(timezone.utc).isoformat()
    payload_hash = compute_payload_hash(payload)
    event_hash = compute_event_hash(event_id, event_type, occurred_at, prev_event_hash, payload_hash)

    return {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "prev_event_hash": prev_event_hash,
        "payload_hash": payload_hash,
        "event_hash": event_hash,
        "actor": actor,
        "actor_type": actor_type,
        "payload": payload,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Field value helper
# ═══════════════════════════════════════════════════════════════════════════════


def profile_field(
    value: Any,
    source: str,
    *,
    confirmed_by_operator: bool = False,
    confirmed_at: Optional[str] = None,
    version: int = 1,
    superseded_by_version: Optional[int] = None,
) -> dict[str, Any]:
    """Build a versioned, source-tracked profile field."""
    status = "OPERATOR_CONFIRMED" if confirmed_by_operator else "UNVERIFIED"
    if superseded_by_version is not None:
        status = "SUPERSEDED"

    return {
        "value": value,
        "source": source,
        "status": status,
        "confirmed_by_operator": confirmed_by_operator,
        "confirmed_at": confirmed_at,
        "version": version,
        "superseded_by_version": superseded_by_version,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Operator Profile Store
# ═══════════════════════════════════════════════════════════════════════════════


class OperatorProfile:
    """Deterministic versioned operator profile store (event-sourced)."""

    def __init__(self, store_path: str = "data/cio/operator_profile.jsonl"):
        self.store_path = Path(store_path)
        self.lock_path = Path(str(store_path) + ".lock")
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def _last_event_hash(self) -> str:
        """Read the hash of the last event in the store."""
        if not self.store_path.exists():
            return GENESIS_PREV_HASH
        with open(self.store_path, "r") as f:
            last_line = None
            for line in f:
                stripped = line.strip()
                if stripped:
                    last_line = stripped
            if last_line is None:
                return GENESIS_PREV_HASH
            return json.loads(last_line)["event_hash"]

    def _acquire_lock(self) -> int:
        """Acquire exclusive file lock. Returns lock file descriptor."""
        fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def _release_lock(self, fd: int):
        """Release file lock and close descriptor."""
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    def _append_event(self, event: dict[str, Any]):
        """Append a single event to the store with fsync."""
        line = json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n"
        with open(self.store_path, "a") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def _genesis(self):
        """Write genesis event if store is empty."""
        if self.store_path.exists():
            return
        prev_hash = GENESIS_PREV_HASH
        event = build_event(
            "OPERATOR_PROFILE_GENESIS",
            {"message": "Operator profile event store initialized"},
            prev_hash,
        )
        self._append_event(event)

    def initialize(self):
        """Initialize the store with genesis if needed."""
        fd = self._acquire_lock()
        try:
            self._genesis()
        finally:
            self._release_lock(fd)

    def create_field(
        self,
        domain: str,
        field_name: str,
        value: Any,
        source: str,
        *,
        actor: str = "system",
        actor_type: str = "system",
        confirmed_by_operator: bool = False,
    ) -> dict[str, Any]:
        """Create a new profile field."""
        if domain not in SUPPORTED_DOMAINS:
            raise ValueError(f"Unsupported domain: {domain}. Supported: {sorted(SUPPORTED_DOMAINS)}")

        confirmed_at = datetime.now(timezone.utc).isoformat() if confirmed_by_operator else None
        field = profile_field(
            value=value,
            source=source,
            confirmed_by_operator=confirmed_by_operator,
            confirmed_at=confirmed_at,
            version=1,
        )

        payload = {
            "domain": domain,
            "field_name": field_name,
            "field": field,
        }

        fd = self._acquire_lock()
        try:
            prev_hash = self._last_event_hash()
            event = build_event("PROFILE_CREATED", payload, prev_hash, actor=actor, actor_type=actor_type)
            self._append_event(event)
            return event
        finally:
            self._release_lock(fd)

    def update_field(
        self,
        domain: str,
        field_name: str,
        value: Any,
        source: str,
        *,
        actor: str = "system",
        actor_type: str = "system",
        confirmed_by_operator: bool = False,
    ) -> dict[str, Any]:
        """Update an existing profile field, superseding the previous version."""
        if domain not in SUPPORTED_DOMAINS:
            raise ValueError(f"Unsupported domain: {domain}. Supported: {sorted(SUPPORTED_DOMAINS)}")

        current = self.get_field(domain, field_name)
        if current is None:
            return self.create_field(
                domain, field_name, value, source,
                actor=actor, actor_type=actor_type,
                confirmed_by_operator=confirmed_by_operator,
            )

        new_version = current.get("version", 1) + 1
        confirmed_at = datetime.now(timezone.utc).isoformat() if confirmed_by_operator else None
        field = profile_field(
            value=value,
            source=source,
            confirmed_by_operator=confirmed_by_operator,
            confirmed_at=confirmed_at,
            version=new_version,
        )

        payload = {
            "domain": domain,
            "field_name": field_name,
            "field": field,
        }

        fd = self._acquire_lock()
        try:
            prev_hash = self._last_event_hash()
            event = build_event("PROFILE_UPDATED", payload, prev_hash, actor=actor, actor_type=actor_type)
            self._append_event(event)
            return event
        finally:
            self._release_lock(fd)

    def confirm_field(
        self,
        domain: str,
        field_name: str,
        *,
        actor: str = "operator",
        actor_type: str = "operator",
    ) -> dict[str, Any]:
        """Mark a field as operator-confirmed."""
        current = self.get_field(domain, field_name)
        if current is None:
            raise ValueError(f"Field {domain}.{field_name} not found")

        confirmed_at = datetime.now(timezone.utc).isoformat()
        field = profile_field(
            value=current["value"],
            source=current["source"],
            confirmed_by_operator=True,
            confirmed_at=confirmed_at,
            version=current.get("version", 1),
        )

        payload = {
            "domain": domain,
            "field_name": field_name,
            "field": field,
        }

        fd = self._acquire_lock()
        try:
            prev_hash = self._last_event_hash()
            event = build_event("PROFILE_CONFIRMED", payload, prev_hash, actor=actor, actor_type=actor_type)
            self._append_event(event)
            return event
        finally:
            self._release_lock(fd)

    def deprecate_field(
        self,
        domain: str,
        field_name: str,
        *,
        actor: str = "system",
        actor_type: str = "system",
        reason: str = "",
    ) -> dict[str, Any]:
        """Mark a field as deprecated/expired."""
        current = self.get_field(domain, field_name)
        if current is None:
            raise ValueError(f"Field {domain}.{field_name} not found")

        field = dict(current)
        field["status"] = "EXPIRED"

        payload = {
            "domain": domain,
            "field_name": field_name,
            "field": field,
            "reason": reason,
        }

        fd = self._acquire_lock()
        try:
            prev_hash = self._last_event_hash()
            event = build_event("PROFILE_DEPRECATED", payload, prev_hash, actor=actor, actor_type=actor_type)
            self._append_event(event)
            return event
        finally:
            self._release_lock(fd)

    def get_field(self, domain: str, field_name: str) -> Optional[dict[str, Any]]:
        """Get the latest version of a field (projection from event log)."""
        latest = None
        if not self.store_path.exists():
            return None
        with open(self.store_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                payload = event.get("payload", {})
                if payload.get("domain") == domain and payload.get("field_name") == field_name:
                    latest = payload.get("field")
        return latest

    def get_domain(self, domain: str) -> dict[str, Any]:
        """Get all current fields for a domain."""
        fields = {}
        if not self.store_path.exists():
            return fields
        with open(self.store_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                payload = event.get("payload", {})
                if payload.get("domain") == domain:
                    fname = payload.get("field_name")
                    field = payload.get("field")
                    if fname and field:
                        fields[fname] = field
        return fields

    def get_confirmed_fields(self, domain: str) -> dict[str, Any]:
        """Get only OPERATOR_CONFIRMED fields for a domain."""
        all_fields = self.get_domain(domain)
        return {k: v for k, v in all_fields.items() if v.get("status") == "OPERATOR_CONFIRMED"}

    def get_all_profiles(self) -> dict[str, dict[str, Any]]:
        """Get all domains with their current fields."""
        result = {}
        for domain in SUPPORTED_DOMAINS:
            fields = self.get_domain(domain)
            if fields:
                result[domain] = fields
        return result

    def get_all_confirmed(self) -> dict[str, dict[str, Any]]:
        """Get all OPERATOR_CONFIRMED facts across all domains."""
        result = {}
        for domain in SUPPORTED_DOMAINS:
            fields = self.get_confirmed_fields(domain)
            if fields:
                result[domain] = fields
        return result

    def verify_integrity(self) -> tuple[bool, str]:
        """Verify the hash chain integrity of the entire event log."""
        if not self.store_path.exists():
            return True, "No event store exists"

        prev_hash = GENESIS_PREV_HASH
        line_num = 0
        with open(self.store_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                line_num += 1
                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError:
                    return False, f"Line {line_num}: JSON decode error"

                expected_prev = event.get("prev_event_hash")
                if expected_prev != prev_hash:
                    return False, f"Line {line_num}: Chain broken. Expected {prev_hash[:16]}..., got {expected_prev[:16]}..."

                # Recompute event hash
                event_id = event["event_id"]
                event_type = event["event_type"]
                occurred_at = event["occurred_at"]
                payload_hash = event["payload_hash"]
                computed = compute_event_hash(event_id, event_type, occurred_at, expected_prev, payload_hash)
                if computed != event["event_hash"]:
                    return False, f"Line {line_num}: Hash mismatch"

                prev_hash = event["event_hash"]

        return True, f"Chain verified ({line_num} events)"


# ═══════════════════════════════════════════════════════════════════════════════
# Convenience functions
# ═══════════════════════════════════════════════════════════════════════════════

def create_operator_profile(
    store_path: str = "data/cio/operator_profile.jsonl",
    *,
    domain: str,
    field_name: str,
    value: Any,
    source: str,
    actor: str = "system",
    actor_type: str = "system",
    confirmed_by_operator: bool = False,
) -> dict[str, Any]:
    """Convenience: initialize store and create a profile field."""
    p = OperatorProfile(store_path)
    p.initialize()
    return p.create_field(
        domain, field_name, value, source,
        actor=actor, actor_type=actor_type,
        confirmed_by_operator=confirmed_by_operator,
    )


def get_operator_confirmed_facts(
    store_path: str = "data/cio/operator_profile.jsonl",
) -> dict[str, dict[str, Any]]:
    """Convenience: get all OPERATOR_CONFIRMED facts."""
    p = OperatorProfile(store_path)
    return p.get_all_confirmed()
