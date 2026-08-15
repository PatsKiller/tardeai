"""R6 append-only governance store.

JSONL hash-chain wrapping (not replacing) R1 TrialRegistry + R4 DecisionUseLedger.

Each committed line is:

    {seq, event_type, payload, prev_hash, record_digest, signature, issuer_id, as_of, authority}

``record_digest`` is ``_stable_hash({seq, event_type, payload, prev_hash})``.
``signature`` is ``ReceiptAuthority.sign`` of that same digest payload.

Fail-closed: rewrite / truncate / last-digest mismatch refuses further appends.
There is no delete / truncate / clear / rewrite API.

READ_ONLY_ADVISORY. No Telegram, no broker, no network, no production DB.
"""
from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from .decision_use_audit import DecisionUseLedger, DecisionUseRecord
from .models import _stable_hash
from .receipts import AUTHORITY as DEFAULT_RECEIPT_AUTHORITY
from .receipts import ReceiptAuthority
from .trial_registry import TrialRegistry

AUTHORITY = "READ_ONLY_ADVISORY"
GENESIS = "0" * 64

EVENT_FAMILY_FREEZE = "family_freeze"
EVENT_TRIAL_RECORD = "trial_record"
EVENT_OOS_WINDOW = "oos_window"
EVENT_DECISION_USE = "decision_use"

SUPPORTED_EVENT_TYPES = frozenset({
    EVENT_FAMILY_FREEZE,
    EVENT_TRIAL_RECORD,
    EVENT_OOS_WINDOW,
    EVENT_DECISION_USE,
})

PathLike = Union[str, os.PathLike]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(obj: Any) -> Any:
    """Round-trip through JSON so hashed payload == re-read payload."""
    return json.loads(json.dumps(obj, default=str))


def _digest_payload(seq: int, event_type: str, payload: dict, prev_hash: str) -> dict:
    return {
        "seq": seq,
        "event_type": event_type,
        "payload": payload,
        "prev_hash": prev_hash,
    }


def _record_digest(seq: int, event_type: str, payload: dict, prev_hash: str) -> str:
    return _stable_hash(_digest_payload(seq, event_type, payload, prev_hash))


def decision_use_event_payload(rec: DecisionUseRecord) -> dict:
    """DecisionUseRecord.payload() plus signature/digest (R6 event body)."""
    body = rec.payload()
    body["signature"] = rec.signature
    body["record_digest"] = rec.record_digest
    return body


def _decision_use_from_payload(payload: dict) -> DecisionUseRecord:
    return DecisionUseRecord(
        decision_id=str(payload["decision_id"]),
        query=dict(payload.get("query") or {}),
        fact_ids=tuple(payload.get("fact_ids") or ()),
        grades=tuple(payload.get("grades") or ()),
        influence_class=str(payload.get("influence_class") or ""),
        influence_cap_pct=float(payload.get("influence_cap_pct") or 0.0),
        forbidden_actions=tuple(payload.get("forbidden_actions") or ()),
        as_of=str(payload.get("as_of") or ""),
        authority=str(payload.get("authority") or AUTHORITY),
        issuer_id=payload.get("issuer_id"),
        signature=payload.get("signature"),
        record_digest=payload.get("record_digest"),
    )


def _iter_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at line {lineno}: {exc}") from exc
            if not isinstance(rec, dict):
                raise ValueError(f"JSONL line {lineno} is not an object")
            out.append(rec)
    return out


def _last_record(path: Path) -> Optional[dict]:
    rows = _iter_jsonl(path)
    return rows[-1] if rows else None


def _require_keys(payload: dict, keys: tuple[str, ...], event_type: str) -> None:
    missing = [k for k in keys if k not in payload or payload[k] in (None, "")]
    if missing:
        raise ValueError(f"{event_type} payload missing {missing}")


def _validate_event_payload(event_type: str, payload: dict) -> None:
    if event_type == EVENT_FAMILY_FREEZE:
        _require_keys(payload, ("family_id", "hypothesis_id", "protocol_hash", "planned_trials"),
                      event_type)
        if not payload["planned_trials"]:
            raise ValueError("family_freeze planned_trials must be non-empty")
    elif event_type == EVENT_TRIAL_RECORD:
        _require_keys(payload, ("family_id", "trial_id", "config_hash"), event_type)
        if payload.get("result_payload") is None and payload.get("result_hash") is None:
            raise ValueError("trial_record requires result_payload or result_hash")
    elif event_type == EVENT_OOS_WINDOW:
        _require_keys(payload, ("family_id", "oos_window_id", "oos_generation"), event_type)
    elif event_type == EVENT_DECISION_USE:
        _require_keys(payload, ("decision_id",), event_type)
    else:
        raise ValueError(f"unsupported event_type: {event_type!r}")


class AppendOnlyStore:
    """Hash-chained JSONL store. Append-only; no rewrite surface."""

    def __init__(self, path: PathLike, *, authority: Optional[ReceiptAuthority] = None) -> None:
        self.path = Path(path)
        self.authority = authority or DEFAULT_RECEIPT_AUTHORITY
        self._size = 0
        self._last_digest = GENESIS
        self._last_seq = 0
        self._load_tip()

    def _load_tip(self) -> None:
        if not self.path.is_file():
            self._size = 0
            self._last_digest = GENESIS
            self._last_seq = 0
            return
        self._size = self.path.stat().st_size
        last = _last_record(self.path)
        if last is None:
            self._last_digest = GENESIS
            self._last_seq = 0
            return
        self._last_digest = str(last.get("record_digest") or GENESIS)
        self._last_seq = int(last.get("seq") or 0)

    def _assert_file_intact(self, *, current_size: int, last: Optional[dict]) -> None:
        """Refuse append after external truncate / rewrite."""
        had_content = self._last_seq > 0 or self._size > 0
        if not had_content:
            return
        if current_size < self._size:
            raise ValueError("append refused: store file truncated")
        if current_size != self._size:
            raise ValueError("append refused: store file rewritten (size changed)")
        if last is None or last.get("record_digest") != self._last_digest:
            raise ValueError("append refused: last digest mismatch (file rewritten)")

    def append(self, event_type: str, payload: dict) -> dict:
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("event_type is required")
        if event_type not in SUPPORTED_EVENT_TYPES:
            raise ValueError(f"unsupported event_type: {event_type!r}")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")

        safe_payload = _json_safe(payload)
        if not isinstance(safe_payload, dict):
            raise ValueError("payload must be a JSON object")
        _validate_event_payload(event_type, safe_payload)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        # a+ creates the file if needed and lets us inspect then append.
        with self.path.open("a+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                fh.seek(0, os.SEEK_END)
                current_size = fh.tell()
                fh.seek(0)
                last = None
                for raw in fh:
                    line = raw.strip()
                    if line:
                        last = json.loads(line)
                self._assert_file_intact(current_size=current_size, last=last)
                ok, reason = self.verify_chain()
                if not ok:
                    raise ValueError(f"append refused: chain invalid ({reason})")

                seq = self._last_seq + 1
                prev_hash = self._last_digest
                digest = _record_digest(seq, event_type, safe_payload, prev_hash)
                signed_body = _digest_payload(seq, event_type, safe_payload, prev_hash)
                issuer_id = self.authority.issuer_id
                signature = self.authority.sign(signed_body)
                as_of = _now_iso()
                record = {
                    "seq": seq,
                    "event_type": event_type,
                    "payload": safe_payload,
                    "prev_hash": prev_hash,
                    "record_digest": digest,
                    "signature": signature,
                    "issuer_id": issuer_id,
                    "as_of": as_of,
                    "authority": AUTHORITY,
                }
                fh.seek(0, os.SEEK_END)
                fh.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
                self._size = fh.tell()
                self._last_digest = digest
                self._last_seq = seq
                return record
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def events(self) -> list[dict]:
        try:
            return _iter_jsonl(self.path)
        except ValueError:
            # Surface parse failures via verify_chain; events() is a raw read.
            raise

    def verify_chain(self) -> tuple[bool, str]:
        try:
            rows = _iter_jsonl(self.path)
        except ValueError as exc:
            return False, str(exc)

        expected_prev = GENESIS
        expected_seq = 1
        for idx, rec in enumerate(rows):
            sig = rec.get("signature")
            if not sig or not isinstance(sig, str):
                return False, f"missing signature at seq={rec.get('seq')}"
            try:
                seq = int(rec["seq"])
            except (KeyError, TypeError, ValueError):
                return False, f"invalid seq at index {idx}"
            if seq != expected_seq:
                return False, f"seq gap: expected {expected_seq} got {seq}"
            event_type = rec.get("event_type")
            payload = rec.get("payload")
            prev_hash = rec.get("prev_hash")
            if not isinstance(event_type, str) or not isinstance(payload, dict):
                return False, f"malformed event at seq={seq}"
            if prev_hash != expected_prev:
                return False, f"prev_hash mismatch at seq={seq}"
            digest = rec.get("record_digest")
            computed = _record_digest(seq, event_type, payload, prev_hash)
            if digest != computed:
                return False, f"record_digest mismatch at seq={seq}"
            signed_body = _digest_payload(seq, event_type, payload, prev_hash)
            if not self.authority.verify(signed_body, sig, rec.get("issuer_id")):
                return False, f"invalid signature at seq={seq}"
            if rec.get("authority") != AUTHORITY:
                return False, f"authority drifted at seq={seq}"
            if event_type == EVENT_DECISION_USE:
                inner = _decision_use_from_payload(payload)
                if not inner.signature:
                    return False, f"decision_use missing inner signature at seq={seq}"
                if not inner.verify():
                    return False, f"decision_use inner signature invalid at seq={seq}"
            expected_prev = digest
            expected_seq += 1
        if not rows:
            return True, "empty"
        return True, f"verified:{len(rows)}"

    def replay_trial_registry(self) -> TrialRegistry:
        ok, reason = self.verify_chain()
        if not ok:
            raise ValueError(f"cannot replay broken chain: {reason}")
        reg = TrialRegistry()
        for rec in _iter_jsonl(self.path):
            et = rec["event_type"]
            p = rec["payload"]
            if et == EVENT_FAMILY_FREEZE:
                reg.freeze_family(
                    p["family_id"],
                    p["hypothesis_id"],
                    p["protocol_hash"],
                    p["planned_trials"],
                    family_definition_hash=p.get("family_definition_hash"),
                    confirmatory=bool(p.get("confirmatory", False)),
                )
            elif et == EVENT_TRIAL_RECORD:
                kwargs: dict[str, Any] = {"config_hash": p["config_hash"]}
                for key in (
                    "result_hash",
                    "result_payload",
                    "result_artifact_ref",
                    "result_artifact_size",
                    "hash_algorithm",
                    "code_sha",
                    "dataset_hash",
                    "started_at",
                    "completed_at",
                    "terminal_status",
                    "terminal_reason",
                    "failure_stage",
                ):
                    if key in p and p[key] is not None:
                        kwargs[key] = p[key]
                reg.record_trial(p["family_id"], p["trial_id"], **kwargs)
            elif et == EVENT_OOS_WINDOW:
                reg.register_oos_window(
                    p["family_id"],
                    p["oos_window_id"],
                    p["oos_generation"],
                    segment_start=p.get("segment_start"),
                    segment_end=p.get("segment_end"),
                    dataset_id=p.get("dataset_id"),
                    dataset_hash=p.get("dataset_hash"),
                )
        return reg

    def replay_decision_ledger(self) -> DecisionUseLedger:
        ok, reason = self.verify_chain()
        if not ok:
            raise ValueError(f"cannot replay broken chain: {reason}")
        ledger = DecisionUseLedger()
        for rec in _iter_jsonl(self.path):
            if rec["event_type"] != EVENT_DECISION_USE:
                continue
            row = _decision_use_from_payload(rec["payload"])
            if not row.signature or not row.verify():
                raise ValueError(
                    f"decision_use record {row.decision_id!r} failed signature verify")
            # Reconstruct the authentic record; do not re-issue via ledger.record().
            ledger._rows.append(row)
        return ledger
