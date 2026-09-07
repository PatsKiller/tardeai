#!/usr/bin/env python3
"""persistent_agent_wake.py — WakeRecord@v2 producer (CampaignInterfaces@v1).

Deployable entrypoint for unattended wakes. Does NOT install or activate a
production schedule. Integration wires `run_scheduled_wake` later.

Ordering invariant (fail-closed):
  CLAIMED -> load durable subject memory -> load prior comms/operator turns
  -> decide -> optional commitment -> receipts -> ACTED/SETTLED
A wake that acts before loading memory is a bug.

Idempotency:
  WakeId = uuid5(ns_wake, agent_id + wake_reason + schedule_slot_utc + subject_guid)
Same slot re-run collides; zero new rows for wake/commitment/receipt.

Authority: READ_ONLY_ADVISORY. Never sizes, orders, stops, or writes broker state.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from scripts.lib.persistent_wake_interfaces import (
    COMMITMENT_SCHEMA,
    EFFECT_KINDS,
    INTERFACE_VERSION,
    RECEIPT_SCHEMA,
    SOURCE_KINDS,
    WAKE_LIFECYCLE,
    WAKE_SCHEMA,
    envelope,
    mint_commitment_id,
    mint_receipt_id,
    mint_view_id,
    mint_wake_id,
)
from scripts.lib.persistent_wake_schedule import ScheduleContract, evaluate_health
from scripts.lib.persistent_wake_store import JsonlStore

AUTHORITY = "READ_ONLY_ADVISORY"
FEATURE_FLAG = "PERSISTENT_WAKE_ENABLED"  # default OFF
KNOWN_AGENTS = frozenset({"cio", "hermes", "advisory", "darwin", "maria"})
TERMINAL_WAKE = frozenset({
    "SETTLED", "ABANDONED", "STALE", "MEMORY_UNAVAILABLE", "MEMORY_MALFORMED",
})
MEMORY_STALE_HOURS = float(os.getenv("WAKE_MEMORY_STALE_HOURS", "168"))


class WakeRejected(RuntimeError):
    """Fail-closed refusal — recorded as a failure lifecycle state when possible."""


class CommsHistoryPort(Protocol):
    """Lane B interface (§8). Lane A never writes comms tables."""

    def prior_comm_events(self, subject_guid: str, *, limit: int = 20) -> list[dict]:
        ...

    def prior_operator_turns(self, subject_guid: str, *, limit: int = 20) -> list[dict]:
        ...


@dataclass
class MemoryFact:
    fact_id: str
    subject_guid: str
    content: Any
    as_of: datetime
    relevant: bool = True


@dataclass
class MemorySnapshot:
    snapshot_id: str
    subject_guid: str
    facts: list[MemoryFact]
    loaded_at: datetime
    empty: bool = False
    malformed: bool = False
    stale: bool = False
    error: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _content_hash(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _normalize_claim(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def feature_enabled(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(FEATURE_FLAG, "")).strip().lower() in {"1", "true", "yes", "on"}


def source_sha() -> str:
    return (
        os.environ.get("TRADEAI_SOURCE_SHA")
        or os.environ.get("BUILD_SHA")
        or os.environ.get("SOURCE_COMMIT")
        or "unknown"
    )


# ── Memory loading ──────────────────────────────────────────────────────────

class MemoryLoader:
    """Loads durable subject memory before any decision.

    `backend` may be a callable(subject_guid) -> list[dict] or a path to JSONL.
    """

    def __init__(self, backend: Any = None, *, stale_hours: float = MEMORY_STALE_HOURS):
        self.backend = backend
        self.stale_hours = stale_hours

    def load(self, subject_guid: str, *, now: datetime | None = None) -> MemorySnapshot:
        now = now or _now()
        snap_id = mint_receipt_id("memory", "snapshot", subject_guid, "wake_load")
        try:
            rows = self._fetch(subject_guid)
        except Exception as exc:  # malformed / unreadable
            return MemorySnapshot(
                snapshot_id=snap_id, subject_guid=subject_guid, facts=[],
                loaded_at=now, malformed=True, error=f"{type(exc).__name__}: {exc}",
            )
        facts: list[MemoryFact] = []
        newest: datetime | None = None
        for row in rows:
            if not isinstance(row, dict):
                return MemorySnapshot(
                    snapshot_id=snap_id, subject_guid=subject_guid, facts=[],
                    loaded_at=now, malformed=True, error="non-object memory row",
                )
            fid = str(row.get("fact_id") or row.get("id") or "")
            if not fid:
                return MemorySnapshot(
                    snapshot_id=snap_id, subject_guid=subject_guid, facts=[],
                    loaded_at=now, malformed=True, error="memory row missing fact_id",
                )
            as_of_raw = row.get("as_of") or row.get("produced_at")
            try:
                if isinstance(as_of_raw, datetime):
                    as_of = as_of_raw if as_of_raw.tzinfo else as_of_raw.replace(tzinfo=timezone.utc)
                else:
                    as_of = datetime.fromisoformat(str(as_of_raw).replace("Z", "+00:00"))
            except Exception:
                return MemorySnapshot(
                    snapshot_id=snap_id, subject_guid=subject_guid, facts=[],
                    loaded_at=now, malformed=True, error=f"bad as_of on {fid}",
                )
            relevant = bool(row.get("relevant", True))
            # Exclude irrelevant history
            if row.get("subject_guid") and str(row.get("subject_guid")) != str(subject_guid):
                relevant = False
            facts.append(MemoryFact(
                fact_id=fid, subject_guid=subject_guid,
                content=row.get("content", row), as_of=as_of, relevant=relevant,
            ))
            if newest is None or as_of > newest:
                newest = as_of
        relevant_facts = [f for f in facts if f.relevant]
        stale = False
        if newest is not None and (now - newest) > timedelta(hours=self.stale_hours):
            stale = True
        return MemorySnapshot(
            snapshot_id=snap_id, subject_guid=subject_guid,
            facts=relevant_facts, loaded_at=now,
            empty=(len(relevant_facts) == 0), stale=stale,
        )

    def _fetch(self, subject_guid: str) -> list[dict]:
        if self.backend is None:
            return []
        if callable(self.backend):
            return list(self.backend(subject_guid) or [])
        path = Path(self.backend)
        if not path.exists():
            return []
        text = path.read_text()
        # Allow deliberate malformed fixture: prefix "MALFORMED:"
        if text.startswith("MALFORMED:"):
            raise ValueError(text[len("MALFORMED:"):].strip() or "malformed memory")
        rows = []
        for line in text.splitlines():
            if not line.strip():
                continue
            rows.append(json.loads(line))
        return [r for r in rows if str(r.get("subject_guid", subject_guid)) == str(subject_guid)]


@dataclass
class NullCommsHistory:
    """Default port when Lane B interface is unavailable in isolated tests."""

    events: list[dict] = field(default_factory=list)
    turns: list[dict] = field(default_factory=list)

    def prior_comm_events(self, subject_guid: str, *, limit: int = 20) -> list[dict]:
        out = [e for e in self.events if str(e.get("subject_guid")) == str(subject_guid)]
        return out[:limit]

    def prior_operator_turns(self, subject_guid: str, *, limit: int = 20) -> list[dict]:
        out = [e for e in self.turns if str(e.get("subject_guid")) == str(subject_guid)]
        return out[:limit]


# ── Wake engine ─────────────────────────────────────────────────────────────

@dataclass
class WakeEngine:
    store: JsonlStore
    memory_loader: MemoryLoader
    comms: CommsHistoryPort
    source_sha: str = field(default_factory=source_sha)
    agent_version: str = "lane-a@v2"

    def run(
        self,
        *,
        agent_id: str,
        subject_guid: str,
        wake_reason: str,
        schedule_slot_utc: str,
        correlation_id: str | None = None,
        now: datetime | None = None,
        decide: Callable[[dict], dict] | None = None,
        env: dict | None = None,
        crash_after: str | None = None,
    ) -> dict:
        """Execute one wake. Idempotent on (agent, reason, slot, subject).

        `crash_after` is a test hook: 'reserved' simulates crash after CLAIMED
        reservation and before completion.
        """
        now = now or _now()
        if not feature_enabled(env):
            return {
                "ok": False,
                "skipped": True,
                "reason": "feature_flag_off",
                "feature_flag": FEATURE_FLAG,
            }
        if agent_id not in KNOWN_AGENTS:
            raise WakeRejected(f"unknown agent {agent_id!r}")
        if not subject_guid:
            raise WakeRejected("subject_guid required")

        wake_id = mint_wake_id(agent_id, wake_reason, schedule_slot_utc, subject_guid)
        corr = correlation_id or wake_id

        existing = self.store.get("wakes", "wake_id", wake_id)
        if existing and existing.get("lifecycle_state") in TERMINAL_WAKE:
            return {
                "ok": True,
                "replay_suppressed": True,
                "wake": existing,
                "inserted": False,
            }

        # Reserve / claim
        wake = {
            "wake_id": wake_id,
            "agent_id": agent_id,
            "wake_reason": wake_reason,
            "schedule_slot_utc": schedule_slot_utc,
            "subject_guid": subject_guid,
            "memory_snapshot_id": None,
            "memory_fact_ids": [],
            "prior_comm_event_ids": [],
            "prior_operator_turn_ids": [],
            "research_object_ids": [],
            "commitments_created": [],
            "receipts_emitted": [],
            "authority": AUTHORITY,
            "interface_version": INTERFACE_VERSION,
            **envelope(
                schema_version=WAKE_SCHEMA,
                source_sha=self.source_sha,
                produced_at=_iso(now),
                correlation_id=corr,
                idempotency_key=wake_id,
                lifecycle_state="CLAIMED",
                provenance={
                    "producer": "test" if (env or {}).get("PROVENANCE_PRODUCER") == "test"
                    or os.environ.get("PROVENANCE_PRODUCER") == "test"
                    else "persistent_agent_wake",
                    "inputs": [],
                    "policy_decisions": ["feature_flag_on"],
                    "llm": None,
                    "trigger": "schedule_slot",
                },
            ),
        }
        inserted, wake = self.store.append_unique("wakes", "wake_id", wake)
        if not inserted and wake.get("lifecycle_state") in TERMINAL_WAKE:
            return {"ok": True, "replay_suppressed": True, "wake": wake, "inserted": False}

        if crash_after == "reserved":
            raise RuntimeError("simulated_crash_after_reservation")

        # 1) Load memory BEFORE any decision
        snap = self.memory_loader.load(subject_guid, now=now)
        wake["memory_snapshot_id"] = snap.snapshot_id
        wake["memory_fact_ids"] = [f.fact_id for f in snap.facts]
        wake["lifecycle_state"] = "LOADED"
        wake["provenance"]["inputs"] = list(wake["provenance"].get("inputs") or []) + [
            {"kind": "memory_snapshot", "id": snap.snapshot_id}
        ]

        if snap.malformed:
            wake["lifecycle_state"] = "MEMORY_MALFORMED"
            wake["provenance"]["policy_decisions"].append("refuse_malformed_memory")
            self.store.upsert_by_key("wakes", "wake_id", wake, preserve_terminal=True,
                                     terminal_states=TERMINAL_WAKE)
            return {"ok": False, "wake": wake, "state": "MEMORY_MALFORMED", "inserted": inserted}

        if snap.stale:
            wake["lifecycle_state"] = "STALE"
            wake["provenance"]["policy_decisions"].append("refuse_stale_memory")
            self.store.upsert_by_key("wakes", "wake_id", wake, preserve_terminal=True,
                                     terminal_states=TERMINAL_WAKE)
            return {"ok": False, "wake": wake, "state": "STALE", "inserted": inserted}

        # Empty memory is LOADED-with-empty — not a crash, not a silent act.
        memory_empty = snap.empty

        # 2) Load prior communications / operator turns via Lane B port
        comm_events = self.comms.prior_comm_events(subject_guid)
        op_turns = self.comms.prior_operator_turns(subject_guid)
        # Exclude irrelevant history (wrong subject already filtered by port)
        wake["prior_comm_event_ids"] = [str(e.get("event_id") or e.get("id")) for e in comm_events]
        wake["prior_operator_turn_ids"] = [str(t.get("turn_id") or t.get("id")) for t in op_turns]
        wake["provenance"]["inputs"].extend(
            [{"kind": "comm_event", "id": i} for i in wake["prior_comm_event_ids"]]
            + [{"kind": "operator_turn", "id": i} for i in wake["prior_operator_turn_ids"]]
        )
        self.store.upsert_by_key("wakes", "wake_id", wake)

        context = {
            "wake_id": wake_id,
            "agent_id": agent_id,
            "subject_guid": subject_guid,
            "memory_facts": [
                {"fact_id": f.fact_id, "content": f.content, "as_of": _iso(f.as_of)}
                for f in snap.facts
            ],
            "comm_events": comm_events,
            "operator_turns": op_turns,
            "memory_empty": memory_empty,
        }

        # 3) Decide (deterministic by default)
        decide = decide or default_decide
        decision = decide(context)
        if memory_empty and decision.get("act") and not decision.get("allow_empty_memory"):
            # Explicit no-act on empty memory unless decide opts in
            decision = {
                "act": False,
                "effect_kind": "none",
                "commitment": None,
                "view": None,
                "reason": "no_relevant_memory",
            }

        receipts: list[dict] = []
        commitments: list[dict] = []
        view_rec = None

        # 4) Emit consumption receipts for what influenced the output
        influence_ids: list[str] = []
        for fact in snap.facts:
            rec = self._emit_receipt(
                agent_id=agent_id, source_kind="memory_fact", source_id=fact.fact_id,
                wake_id=wake_id, subject_guid=subject_guid, purpose="wake_memory_load",
                effect_kind="none", effect_ref=None, now=now, corr=corr,
                influence_source_ids=[],
            )
            receipts.append(rec)
            influence_ids.append(rec["receipt_id"])
        for ev in comm_events:
            sid = str(ev.get("event_id") or ev.get("id"))
            rec = self._emit_receipt(
                agent_id=agent_id, source_kind="comm_event", source_id=sid,
                wake_id=wake_id, subject_guid=subject_guid, purpose="wake_comm_load",
                effect_kind="none", effect_ref=None, now=now, corr=corr,
                influence_source_ids=[],
            )
            receipts.append(rec)
            influence_ids.append(rec["receipt_id"])
        for turn in op_turns:
            sid = str(turn.get("turn_id") or turn.get("id"))
            rec = self._emit_receipt(
                agent_id=agent_id, source_kind="operator_turn", source_id=sid,
                wake_id=wake_id, subject_guid=subject_guid, purpose="wake_operator_load",
                effect_kind="none", effect_ref=None, now=now, corr=corr,
                influence_source_ids=[],
            )
            receipts.append(rec)
            influence_ids.append(rec["receipt_id"])

        effect_kind = decision.get("effect_kind", "none")
        if effect_kind not in EFFECT_KINDS:
            raise WakeRejected(f"illegal effect_kind {effect_kind!r}")

        # 5) Organic commitment from genuine decision only
        if decision.get("act") and decision.get("commitment"):
            c = decision["commitment"]
            kind = c.get("commitment_kind") or c.get("claim_type") or "OBSERVATION"
            claim = _normalize_claim(c.get("claim") or c.get("normalized_claim") or "")
            if not claim:
                raise WakeRejected("commitment requires normalized claim")
            cid = mint_commitment_id(wake_id, subject_guid, kind, claim)
            crec = {
                "commitment_id": cid,
                "wake_id": wake_id,
                "subject_guid": subject_guid,
                "agent_id": agent_id,
                "commitment_kind": kind,
                "normalized_claim": claim,
                "claim": c.get("claim") or claim,
                "authority": AUTHORITY,
                **envelope(
                    schema_version=COMMITMENT_SCHEMA,
                    source_sha=self.source_sha,
                    produced_at=_iso(now),
                    correlation_id=corr,
                    idempotency_key=cid,
                    lifecycle_state="OPEN",
                    parent_id=wake_id,
                    parent_kind="wake",
                    provenance={
                        "producer": wake["provenance"]["producer"],
                        "inputs": [{"kind": "wake", "id": wake_id}],
                        "policy_decisions": ["organic_from_wake_decision"],
                        "llm": None,
                        "influence_source_ids": list(wake["memory_fact_ids"]),
                    },
                ),
            }
            c_ins, crec = self.store.append_unique("commitments", "commitment_id", crec)
            commitments.append(crec)
            wake["commitments_created"] = [crec["commitment_id"]]
            # Effect receipt tied to commitment
            erec = self._emit_receipt(
                agent_id=agent_id,
                source_kind=(decision.get("primary_source_kind") or "memory_fact"),
                source_id=(decision.get("primary_source_id")
                           or (wake["memory_fact_ids"][0] if wake["memory_fact_ids"] else "none")),
                wake_id=wake_id, subject_guid=subject_guid, purpose="wake_decision",
                effect_kind="changed_commitment" if c_ins or effect_kind == "changed_commitment" else effect_kind,
                effect_ref=cid, now=now, corr=corr,
                influence_source_ids=list(wake["memory_fact_ids"]) + list(wake["prior_comm_event_ids"]),
            )
            receipts.append(erec)
        elif decision.get("act") and decision.get("view"):
            v = decision["view"]
            vid = mint_view_id(agent_id, subject_guid, wake_id)
            view_rec = {
                "view_id": vid,
                "wake_id": wake_id,
                "agent_id": agent_id,
                "subject_guid": subject_guid,
                "stance": v.get("stance", "UNKNOWN"),
                "summary": v.get("summary", ""),
                "authority": AUTHORITY,
                **envelope(
                    schema_version="AgentView@v2",
                    source_sha=self.source_sha,
                    produced_at=_iso(now),
                    correlation_id=corr,
                    idempotency_key=vid,
                    lifecycle_state="OPEN",
                    parent_id=wake_id,
                    parent_kind="wake",
                    provenance={
                        "producer": wake["provenance"]["producer"],
                        "inputs": [{"kind": "wake", "id": wake_id}],
                        "policy_decisions": [],
                        "llm": None,
                        "influence_source_ids": list(wake["memory_fact_ids"]),
                    },
                ),
            }
            self.store.append_unique("views", "view_id", view_rec)
            erec = self._emit_receipt(
                agent_id=agent_id,
                source_kind=decision.get("primary_source_kind") or "memory_fact",
                source_id=decision.get("primary_source_id")
                or (wake["memory_fact_ids"][0] if wake["memory_fact_ids"] else "none"),
                wake_id=wake_id, subject_guid=subject_guid, purpose="wake_decision",
                effect_kind="changed_view", effect_ref=vid, now=now, corr=corr,
                influence_source_ids=list(wake["memory_fact_ids"]),
            )
            receipts.append(erec)
        else:
            # Honest none-effect decision receipt (still not maturity evidence)
            if wake["memory_fact_ids"] or wake["prior_comm_event_ids"] or wake["prior_operator_turn_ids"]:
                primary_kind = "memory_fact" if wake["memory_fact_ids"] else (
                    "comm_event" if wake["prior_comm_event_ids"] else "operator_turn"
                )
                primary_id = (
                    wake["memory_fact_ids"][0] if wake["memory_fact_ids"]
                    else (wake["prior_comm_event_ids"][0] if wake["prior_comm_event_ids"]
                          else wake["prior_operator_turn_ids"][0])
                )
                erec = self._emit_receipt(
                    agent_id=agent_id, source_kind=primary_kind, source_id=primary_id,
                    wake_id=wake_id, subject_guid=subject_guid, purpose="wake_decision",
                    effect_kind="none", effect_ref=None, now=now, corr=corr,
                    influence_source_ids=list(wake["memory_fact_ids"]),
                )
                receipts.append(erec)

        wake["receipts_emitted"] = [r["receipt_id"] for r in receipts]
        wake["lifecycle_state"] = "ACTED" if decision.get("act") else (
            "LOADED" if memory_empty else "ACTED"
        )
        if decision.get("act"):
            wake["lifecycle_state"] = "SETTLED"
        elif memory_empty:
            wake["lifecycle_state"] = "LOADED"
            wake["provenance"]["policy_decisions"].append("no_relevant_memory")
        else:
            wake["lifecycle_state"] = "SETTLED"

        wake["decision_summary"] = {
            "act": bool(decision.get("act")),
            "effect_kind": effect_kind,
            "reason": decision.get("reason"),
            "output_fingerprint": _content_hash({
                "commitment": decision.get("commitment"),
                "view": decision.get("view"),
                "memory_fact_ids": wake["memory_fact_ids"],
            }),
        }
        self.store.upsert_by_key(
            "wakes", "wake_id", wake, preserve_terminal=True, terminal_states=TERMINAL_WAKE,
        )
        return {
            "ok": True,
            "inserted": inserted,
            "wake": wake,
            "receipts": receipts,
            "commitments": commitments,
            "view": view_rec,
            "memory_empty": memory_empty,
        }

    def _emit_receipt(
        self, *, agent_id: str, source_kind: str, source_id: str, wake_id: str,
        subject_guid: str, purpose: str, effect_kind: str, effect_ref: str | None,
        now: datetime, corr: str, influence_source_ids: list[str],
    ) -> dict:
        if source_kind not in SOURCE_KINDS:
            raise WakeRejected(f"illegal source_kind {source_kind!r}")
        if effect_kind not in EFFECT_KINDS:
            raise WakeRejected(f"illegal effect_kind {effect_kind!r}")
        rid = mint_receipt_id(agent_id, source_kind, source_id, purpose)
        rec = {
            "receipt_id": rid,
            "agent_id": agent_id,
            "agent_version": self.agent_version,
            "source_kind": source_kind,
            "source_id": source_id,
            "wake_id": wake_id,
            "thread_id": None,
            "subject_guid": subject_guid,
            "purpose": purpose,
            "policy_decision": "consume",
            "retrieved_at": _iso(now),
            "acknowledged_at": _iso(now),
            "effect_kind": effect_kind,
            "effect_ref": effect_ref,
            "derived_artifact_ids": [effect_ref] if effect_ref else [],
            "influence_declaration": (
                f"wake {wake_id} consumed {source_kind}:{source_id}"
            ),
            "influence_source_ids": list(influence_source_ids),
            "authority": AUTHORITY,
            **envelope(
                schema_version=RECEIPT_SCHEMA,
                source_sha=self.source_sha,
                produced_at=_iso(now),
                correlation_id=corr,
                idempotency_key=rid,
                lifecycle_state="SETTLED",
                parent_id=wake_id,
                parent_kind="wake",
                provenance={
                    "producer": (
                        "test" if os.environ.get("PROVENANCE_PRODUCER") == "test"
                        else "persistent_agent_wake"
                    ),
                    "inputs": [{"kind": source_kind, "id": source_id}],
                    "policy_decisions": [],
                    "llm": None,
                },
            ),
        }
        _, rec = self.store.append_unique("receipts", "receipt_id", rec)
        return rec


def default_decide(context: dict) -> dict:
    """Deterministic decision: if relevant memory exists, mint an observational commitment."""
    facts = context.get("memory_facts") or []
    if not facts:
        return {"act": False, "effect_kind": "none", "reason": "no_relevant_memory"}
    # Fingerprint memory into claim so changed memory => changed commitment/output
    digest = _content_hash([f.get("content") for f in facts])[:16]
    claim = f"memory_digest:{digest} remains salient"
    return {
        "act": True,
        "effect_kind": "changed_commitment",
        "commitment": {
            "commitment_kind": "MEMORY_SALIENCE",
            "claim": claim,
            "normalized_claim": _normalize_claim(claim),
        },
        "primary_source_kind": "memory_fact",
        "primary_source_id": facts[0]["fact_id"],
        "reason": "organic_from_memory",
    }


def run_scheduled_wake(
    *,
    agent_id: str,
    subject_guid: str,
    wake_reason: str = "scheduled_persistent_review",
    state_root: str | Path,
    memory_backend: Any = None,
    comms: CommsHistoryPort | None = None,
    when: datetime | None = None,
    contract: ScheduleContract | None = None,
    env: dict | None = None,
    decide: Callable[[dict], dict] | None = None,
    crash_after: str | None = None,
) -> dict:
    """Stable entrypoint for a future schedule. Does not install the schedule."""
    when = when or _now()
    contract = contract or ScheduleContract(agent_id=agent_id, wake_reason=wake_reason)
    slot = contract.slot_for(when)
    engine = WakeEngine(
        store=JsonlStore(state_root),
        memory_loader=MemoryLoader(memory_backend),
        comms=comms or NullCommsHistory(),
    )
    return engine.run(
        agent_id=agent_id,
        subject_guid=subject_guid,
        wake_reason=wake_reason,
        schedule_slot_utc=slot,
        now=when,
        decide=decide,
        env=env,
        crash_after=crash_after,
    )


def recover_incomplete_wakes(store: JsonlStore) -> list[dict]:
    """Restart recovery: abandon non-terminal incomplete wakes; do not duplicate."""
    abandoned = []
    for wake in store.iter("wakes"):
        state = wake.get("lifecycle_state")
        if state in {"CLAIMED", "LOADED", "ACTED"} and state not in TERMINAL_WAKE:
            # If ACTED with commitments already created, promote to SETTLED;
            # if only CLAIMED/LOADED, mark ABANDONED — no commitment allowed.
            if state == "ACTED" and wake.get("commitments_created"):
                wake["lifecycle_state"] = "SETTLED"
            elif state in {"CLAIMED", "LOADED"}:
                wake["lifecycle_state"] = "ABANDONED"
                wake.setdefault("provenance", {}).setdefault("policy_decisions", []).append(
                    "restart_recovery_abandon"
                )
            else:
                wake["lifecycle_state"] = "SETTLED"
            store.upsert_by_key(
                "wakes", "wake_id", wake, preserve_terminal=True, terminal_states=TERMINAL_WAKE,
            )
            abandoned.append(wake)
    return abandoned


__all__ = [
    "AUTHORITY",
    "FEATURE_FLAG",
    "WakeEngine",
    "WakeRejected",
    "MemoryLoader",
    "MemorySnapshot",
    "NullCommsHistory",
    "feature_enabled",
    "run_scheduled_wake",
    "recover_incomplete_wakes",
    "default_decide",
    "ScheduleContract",
    "evaluate_health",
]
