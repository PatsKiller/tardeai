"""Append-only conflict lifecycle. Explicit root and apply; no implicit live writer.

ConflictRecord is rebuilt from ConflictEvent rows. Corrupt/truncated history fails
closed rather than dropping evidence. Retention is archival, never deletion here.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re

EVENT_SCHEMA = "ConflictEvent@v1"
RECORD_SCHEMA = "ConflictRecord@v1"
DECISION_SCHEMA = "ConflictDecision@v1"
ACTIVE = {"OPEN", "UNDER_REVIEW", "DECIDED", "REOPENED"}
TERMINAL = {"CLEARED", "SUPERSEDED"}
KINDS = {"CONFLICT", "GATE", "NEEDS_OPERATOR", "DATA_ERROR"}
EVENT_STATES = {"opened": "OPEN", "finding_changed": None, "review_queued": "UNDER_REVIEW",
                "review_completed": "DECIDED", "decided": "DECIDED", "cleared": "CLEARED",
                "superseded": "SUPERSEDED", "reopened": "REOPENED"}


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _iso(at):
    if not isinstance(at, datetime) or at.tzinfo is None:
        raise ValueError("explicit timezone-aware event clock required")
    return at.isoformat()


def lineage(key):
    return re.sub(r":[UR]\d+[a-z]*:", ":source:", key)


class ConflictLedger:
    def __init__(self, root, *, memory_writer=None, pg_writer=None, pg_enabled=False):
        self.root = Path(root)
        self.path = self.root / "data/conflicts/conflict_events.jsonl"
        self.memory_writer = memory_writer
        self.pg_writer = pg_writer
        self.pg_enabled = pg_enabled
        if pg_enabled and not pg_writer:
            raise ValueError("gated PG dual write requires an explicit writer")

    @contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def events(self):
        if not self.path.exists():
            return []
        out = []
        with self.path.open() as handle:
            for number, line in enumerate(handle, 1):
                try:
                    event = json.loads(line)
                    if event["schema"] != EVENT_SCHEMA or event["event"] not in EVENT_STATES:
                        raise ValueError("unknown schema or event")
                    if event["sequence"] != len(out) + 1:
                        raise ValueError("noncontiguous sequence")
                except (KeyError, ValueError, TypeError) as exc:
                    raise ValueError(f"invalid conflict ledger row {number}") from exc
                out.append(event)
        return out

    def records(self):
        records = {}
        for event in self.events():
            key = event["key"]
            prior = records.get(key, {})
            finding = event.get("finding") or prior.get("finding") or {}
            state = EVENT_STATES[event["event"]] or prior.get("state", "OPEN")
            records[key] = {**deepcopy(finding), "schema": RECORD_SCHEMA, "key": key,
                            "subject": event.get("subject") or prior["subject"], "state": state,
                            "finding": deepcopy(finding), "opened_at": prior.get("opened_at", event["at"]),
                            "updated_at": event["at"], "revision": event["sequence"],
                            "decision": event.get("decision") or prior.get("decision"),
                            "history": [*prior.get("history", []), deepcopy(event)]}
        return records

    def _append(self, event, *, events):
        event = {"schema": EVENT_SCHEMA, **event, "sequence": len(events) + 1}
        event["event_id"] = "conflict-" + hashlib.sha256(_json(event).encode()).hexdigest()
        # CIO and PG sinks are recoverable outboxes keyed by immutable event_id.
        event["memory_required"] = event["subject"]["kind"] == "security"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        events.append(event)
        return event

    def drain(self):
        """Idempotent sinks must acknowledge each event_id; never one write per poll."""
        receipt_path = self.path.with_name("conflict_delivery_receipts.jsonl")
        delivered = set()
        if receipt_path.exists():
            for line in receipt_path.read_text().splitlines():
                row = json.loads(line)
                delivered.add((row["event_id"], row["sink"]))
        for event in self.events():
            sinks = []
            if event.get("memory_required"):
                sinks.append(("cio_memory", self.memory_writer))
            if self.pg_enabled:
                sinks.append(("pg", self.pg_writer))
            for sink, writer in sinks:
                if (event["event_id"], sink) in delivered:
                    continue
                if not writer or writer(event) is not True:
                    raise RuntimeError(f"conflict {sink} pending")
                with receipt_path.open("a", encoding="utf-8") as handle:
                    handle.write(_json({"event_id": event["event_id"], "sink": sink}) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                delivered.add((event["event_id"], sink))

    def reconcile(self, subject, findings, *, at, observed_sources=(), apply=False):
        """Complete observations may clear only their own prior finding.

        Missing producers never clear. U0 safety/protection/policy never clear
        automatically, even if their current source disappears or agrees.
        """
        subject = deepcopy(subject.__dict__ if hasattr(subject, "__dict__") else subject)
        findings = [f.as_dict() if hasattr(f, "as_dict") else deepcopy(f) for f in findings]
        at = _iso(at)

        def plan():
            records = self.records()
            pending = []
            current_lineages = {lineage(f["key"]): f for f in findings}
            for finding in findings:
                old = records.get(finding["key"])
                if finding["kind"] not in KINDS:
                    continue
                event = "reopened" if old and old["state"] in TERMINAL else "opened" if not old else None
                if old and old["state"] in ACTIVE and _json(old["finding"]) != _json(finding):
                    event = "finding_changed"
                if event:
                    pending.append({"event": event, "key": finding["key"], "subject": subject,
                                    "at": at, "finding": finding})
            for old in records.values():
                if old["subject"]["kind"] != subject["kind"] or old["subject"]["id"] != subject["id"]:
                    continue
                if old["state"] not in ACTIVE or old.get("rule") in {"U0", "T0", "T1", "R12", "R16"} or old.get("never_auto"):
                    continue
                new = current_lineages.get(lineage(old["key"]))
                # U1 does not mean a disagreement has been resolved.
                clear = new and new["kind"] in {"AGREEMENT", "SUPERSEDED"} and new.get("rule") != "R15"
                gate_passed = old.get("rule") in {"U6", "R3"} and not new and not any(
                    f["kind"] == "DATA_ERROR" for f in findings) and any(
                    side["source"] in observed_sources for side in old.get("sides", [])[:1])
                nway_agreed = old.get("rule") == "R11" and not any(f["kind"] in KINDS for f in findings) and any(
                    f["kind"] == "AGREEMENT" and f["rule"] != "R15" for f in findings) and all(
                    side["source"] in observed_sources for side in old.get("sides", []))
                if clear or gate_passed or nway_agreed:
                    pending.append({"event": "superseded" if new and new["kind"] == "SUPERSEDED" else "cleared",
                                    "key": old["key"], "subject": subject, "at": at,
                                    "evidence": deepcopy(new) if new else {"gate_observed": list(observed_sources)}})
            return pending
        if not apply:
            return plan()
        with self.locked():
            pending = plan()
            events = self.events()
            result = [self._append(event, events=events) for event in pending]
            self.drain()
            return result

    def transition(self, key, event, *, at, expected_revision=None, decision=None, review_request_id=None, apply=False):
        if event not in {"review_queued", "decided", "review_completed"}:
            raise ValueError("transition not admitted")
        def plan():
            record = self.records().get(key)
            if not record:
                raise KeyError(key)
            if record["state"] not in ACTIVE:
                raise ValueError("terminal conflict requires re-evaluation before transition")
            if expected_revision is not None and expected_revision != record["revision"]:
                raise ValueError("stale conflict revision")
            if event == "review_queued" and not review_request_id:
                raise ValueError("actual review request receipt required before queued")
            if event in {"decided", "review_completed"}:
                if not decision or decision.get("schema") != DECISION_SCHEMA:
                    raise ValueError("durable typed decision required")
                if not decision.get("reason") or not decision.get("evidence_refs"):
                    raise ValueError("decision reason and evidence required")
                try:
                    expires = datetime.fromisoformat(str(decision["expires_at"]).replace("Z", "+00:00"))
                    if not expires.tzinfo or expires <= at:
                        raise ValueError("expired or naive decision")
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError("future timezone-aware decision expiry required") from exc
                if record.get("tier", 4) <= 1:
                    raise ValueError("hard safety and facts require source repair, never a chosen side")
                if decision.get("actor_kind") == "cio" and (record["subject"]["kind"] != "security" or
                        record.get("kind") != "CONFLICT" or record.get("rule") not in {"U2", "U3", "U7", "R11"}):
                    raise ValueError("CIO may decide only stance owner reviews")
                if decision.get("actor_kind") not in {"cio", "operator"}:
                    raise ValueError("unknown decision actor")
                if record["subject"]["kind"] in {"metric", "job"}:
                    raise ValueError("numeric/schedule defects require source repair, never a chosen number")
            return {"event": event, "key": key, "subject": record["subject"], "at": _iso(at),
                    "finding": record["finding"],
                    **({"decision": deepcopy(decision)} if decision else {}),
                    **({"request_id": review_request_id} if review_request_id else {})}
        if not apply:
            return plan()
        with self.locked():
            result = self._append(plan(), events=self.events())
            self.drain()
            return result


def list_records(root, *, subject_kind=None, subject_id=None, state=None, kind=None, limit=100, offset=0,
                 include_history=False):
    rows = list(ConflictLedger(root).records().values())
    rows = [r for r in rows if (not subject_kind or r["subject"]["kind"] == subject_kind)
            and (not subject_id or r["subject"]["id"] == subject_id)
            and (not state or r["state"] == state) and (not kind or r.get("kind") == kind)]
    rows.sort(key=lambda r: (r["updated_at"], r["key"]), reverse=True)
    selected = rows[offset:offset + min(max(limit, 1), 200)]
    if not include_history:
        selected = [{k: v for k, v in row.items() if k not in {"history", "finding"}} for row in selected]
    return {"schema": "ConflictCollection@v1", "records": selected,
            "total": len(rows), "offset": offset}


def postgres_sink(connection_factory):
    """Explicit dependency only; caller must opt in with pg_enabled after migration."""
    def write(event):
        connection = connection_factory()
        try:
            cursor = connection.cursor()
            cursor.execute("""INSERT INTO conflict_events
                (event_id,sequence,conflict_key,subject_kind,subject_id,event_kind,at,payload)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT(event_id) DO NOTHING""",
                (event["event_id"], event["sequence"], event["key"], event["subject"]["kind"], event["subject"]["id"],
                 event["event"], event["at"], _json(event)))
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            return False
        finally:
            connection.close()
    return write


def decision_inputs(root, subject, *, now):
    """Only durable, unexpired owner decisions become T4 inputs; never T0/T1."""
    from .adapters import timestamp
    from .engine import Input
    output = []
    for record in ConflictLedger(root).records().values():
        if record["subject"]["kind"] != subject.kind or record["subject"]["id"] != subject.id:
            continue
        decision = record.get("decision") or {}
        expires = timestamp(decision.get("expires_at"))
        at = timestamp(decision.get("at"))
        if record.get("tier", 4) <= 1 or not expires or expires <= now or not at or at > now:
            continue
        output.append(Input("operator decision" if decision["actor_kind"] == "operator" else "CIO decision",
            decision["chosen_side"], at, role="judgment", subject_id=subject.id,
            metadata={"recorded_by": decision["actor_kind"], "reason": decision["reason"], "expires_at": expires,
                      "evidence_refs": decision["evidence_refs"], "conflict_key": record["key"]}))
    return output
