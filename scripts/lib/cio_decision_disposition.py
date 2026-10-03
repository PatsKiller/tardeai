"""Durable operator decision disposition records.

operator_disposition was MISSING: decision_dispositions.jsonl was read-only advisory
with no producer persisting operator decisions. This module wires a producer so the
lineage projection can derive LIVE evidence.

A disposition record captures when an operator manually reviews a decision and records
their judgment, rationale, and disposition (APPROVED, REJECTED, HOLD_FOR_REVIEW, etc).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from scripts.lib.canonical_store_registry import production_state_root

SCHEMA = "OperatorDisposition@v1"
NO_CONSUMER_REASON = (
    "producer built (PR #1394, flight recorder steps 19-20) but NOT wired: no "
    "production code calls DispositionRecorder yet -- only "
    "tests/test_operator_disposition_lineage_20261003.py. Nothing writes "
    "decision_dispositions.jsonl until an operator-review path (desk approve/"
    "reject handler) is wired to record()."
)
AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

DISPOSITION_PATH = Path("data") / "cio" / "decision_dispositions.jsonl"


def default_disposition_path() -> Path:
    """Disposition JSONL under production_state_root."""
    return production_state_root() / DISPOSITION_PATH


def _now() -> str:
    """ISO timestamp in UTC."""
    return datetime.now(timezone.utc).isoformat()


def _digest(*parts: Any) -> str:
    """Short content hash for semantic_key."""
    text = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _optional_str(value: Any) -> str:
    """Convert to string or empty if falsy."""
    return str(value).strip() if value is not None and str(value).strip() else ""


class DispositionRecorder:
    """Record operator decisions on CIO judgments."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or default_disposition_path())

    def record(
        self,
        decision_id: str,
        disposition: str,
        rationale: str | None = None,
        disposed_by: str | None = None,
        disposed_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Record an operator's disposition on a decision.

        Args:
            decision_id: The CIO decision being judged
            disposition: APPROVED, REJECTED, HOLD_FOR_REVIEW, NEEDS_REFINEMENT, etc
            rationale: Why the operator made this disposition
            disposed_by: Operator ID or name
            disposed_at: ISO timestamp (defaults to now)
            metadata: Optional extra context (evidence_refs, tags, etc)

        Returns:
            True if written, False if duplicate (semantic key exists)
        """
        did = _optional_str(decision_id)
        if not did:
            return False

        disp = _optional_str(disposition)
        if not disp:
            return False

        record = {
            "schema": SCHEMA,
            "authority": AUTHORITY,
            "memory_behavior_influence": MBI,
            "recorded_at": _now(),
            "decision_id": did,
            "disposition": disp,
            "rationale": _optional_str(rationale) or None,
            "disposed_by": _optional_str(disposed_by) or None,
            "disposed_at": _optional_str(disposed_at) or _now(),
        }

        if metadata and isinstance(metadata, dict):
            for k, v in metadata.items():
                if _optional_str(k) and v is not None:
                    record[k] = v

        # Semantic key prevents duplicate disposition records
        semantic_parts = (did, disp, _optional_str(rationale))
        semantic_key = _digest(semantic_parts)

        # Check for existing record with same semantic_key
        if self._key_exists(semantic_key):
            return False

        record["semantic_key"] = semantic_key

        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return True
        except Exception:
            return False

    def _key_exists(self, semantic_key: str) -> bool:
        """Check if a record with this semantic_key already exists."""
        if not self.path.exists():
            return False
        try:
            with self.path.open(encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                        if row.get("semantic_key") == semantic_key:
                            return True
                    except (ValueError, TypeError):
                        continue
        except Exception:
            pass
        return False

    def latest_for_decision(self, decision_id: str) -> dict[str, Any] | None:
        """Get the most recent disposition for a decision."""
        did = _optional_str(decision_id)
        if not did or not self.path.exists():
            return None

        latest = None
        try:
            with self.path.open(encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                        if row.get("decision_id") == did:
                            latest = row
                    except (ValueError, TypeError):
                        continue
        except Exception:
            pass
        return latest


def record_disposition(
    decision_id: str,
    disposition: str,
    rationale: str | None = None,
    disposed_by: str | None = None,
    disposed_at: str | None = None,
    *,
    path: Path | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Module-level function to record an operator disposition."""
    recorder = DispositionRecorder(path)
    return recorder.record(
        decision_id=decision_id,
        disposition=disposition,
        rationale=rationale,
        disposed_by=disposed_by,
        disposed_at=disposed_at,
        metadata=metadata,
    )
