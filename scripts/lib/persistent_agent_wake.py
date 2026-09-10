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
# Selection provenance → receipt source_kind. `material_change` is accepted on
# the wake path pending SFR promotion into CampaignInterfaces SOURCE_KINDS.
_SELECTION_SOURCE_TO_KIND = {
    "unconsumed_research": "research_object",
    "material_change": "material_change",
}
_WAKE_SOURCE_KINDS = frozenset(SOURCE_KINDS) | frozenset({"material_change"})


def _normalize_selection(selection: Any) -> dict[str, Any] | None:
    """Return `{source, source_id, observed_at}` or None. Never mint a source_id."""
    if selection is None:
        return None
    if hasattr(selection, "source") and hasattr(selection, "source_id"):
        src = getattr(selection, "source", None)
        sid = getattr(selection, "source_id", None)
        observed = getattr(selection, "observed_at", None)
    elif isinstance(selection, dict):
        src = selection.get("source")
        sid = selection.get("source_id")
        observed = selection.get("observed_at")
    else:
        return None
    if not src or not sid:
        return None
    out: dict[str, Any] = {"source": str(src), "source_id": str(sid)}
    if observed is not None:
        out["observed_at"] = str(observed)
    return out


def _selection_primary_kind(selection: dict[str, Any] | None) -> str | None:
    if not selection:
        return None
    return _SELECTION_SOURCE_TO_KIND.get(str(selection.get("source") or ""))
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
class MemoryLoadMetrics:
    """Per-load counters for MemoryLoader schema/adapter outcomes."""

    loaded: int = 0
    rejected: int = 0
    malformed_rows: int = 0
    unmatched: int = 0
    cross_subject_prevented: int = 0


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
    metrics: MemoryLoadMetrics | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_memory_identity(row: dict) -> tuple[str | None, str | None]:
    """Resolve durable identity from fact_id / id / memory_id.

    Returns (identity, error). error is set when missing or conflicting.
    Aliases are accepted only when unambiguous (single value across present keys).
    """
    present: list[str] = []
    for key in ("fact_id", "id", "memory_id"):
        raw = row.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            present.append(text)
    if not present:
        return None, "missing_id"
    unique = set(present)
    if len(unique) > 1:
        return None, "conflicting_ids"
    return next(iter(unique)), None


def _row_subject_disposition(row: dict, subject_guid: str) -> str:
    """Classify row relevance for a wake subject.

    Only an explicit subject_guid can match. A human-readable `subject` title
    is never treated as a GUID, and a missing subject_guid must not default to
    the wake subject (that would load every title-only durable row for every
    wake).
    """
    raw = row.get("subject_guid")
    if raw is None or str(raw).strip() == "":
        return "unmatched"
    if str(raw) == str(subject_guid):
        return "match"
    return "cross"


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
    """Deployed source identity for durable wake stamps (env → CURRENT → git)."""
    from scripts.lib.runtime_identity import resolve_source_sha

    return resolve_source_sha()


# ── Memory loading ──────────────────────────────────────────────────────────

class MemoryLoader:
    """Loads durable subject memory before any decision.

    `backend` may be a callable(subject_guid) -> list[dict] or a path to JSONL.

    Schema adapter (2026-09-10): accept unambiguous fact_id / id / memory_id;
    match subjects only via explicit subject_guid; never default-match title-only
    durable rows onto the wake subject (that would load the entire store).
    Matched rows with missing/conflicting/duplicate ids fail closed for the
    snapshot. Unmatched and cross-subject rows are skipped with metrics.
    """

    def __init__(self, backend: Any = None, *, stale_hours: float = MEMORY_STALE_HOURS):
        self.backend = backend
        self.stale_hours = stale_hours

    def load(self, subject_guid: str, *, now: datetime | None = None) -> MemorySnapshot:
        now = now or _now()
        snap_id = mint_receipt_id("memory", "snapshot", subject_guid, "wake_load")
        metrics = MemoryLoadMetrics()
        try:
            rows = self._fetch(subject_guid)
        except Exception as exc:  # malformed / unreadable
            return MemorySnapshot(
                snapshot_id=snap_id, subject_guid=subject_guid, facts=[],
                loaded_at=now, malformed=True, error=f"{type(exc).__name__}: {exc}",
                metrics=metrics,
            )
        facts: list[MemoryFact] = []
        newest: datetime | None = None
        seen_ids: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                return MemorySnapshot(
                    snapshot_id=snap_id, subject_guid=subject_guid, facts=[],
                    loaded_at=now, malformed=True, error="non-object memory row",
                    metrics=metrics,
                )
            disposition = _row_subject_disposition(row, subject_guid)
            if disposition == "unmatched":
                metrics.unmatched += 1
                continue
            if disposition == "cross":
                metrics.cross_subject_prevented += 1
                continue

            fid, id_err = _resolve_memory_identity(row)
            if id_err or not fid:
                metrics.malformed_rows += 1
                return MemorySnapshot(
                    snapshot_id=snap_id, subject_guid=subject_guid, facts=[],
                    loaded_at=now, malformed=True,
                    error=f"memory row {id_err or 'missing_id'}",
                    metrics=metrics,
                )
            if fid in seen_ids:
                metrics.rejected += 1
                return MemorySnapshot(
                    snapshot_id=snap_id, subject_guid=subject_guid, facts=[],
                    loaded_at=now, malformed=True,
                    error=f"duplicate memory identity {fid}",
                    metrics=metrics,
                )
            seen_ids.add(fid)

            as_of_raw = row.get("as_of") or row.get("produced_at") or row.get("observed_at")
            try:
                if isinstance(as_of_raw, datetime):
                    as_of = as_of_raw if as_of_raw.tzinfo else as_of_raw.replace(tzinfo=timezone.utc)
                else:
                    as_of = datetime.fromisoformat(str(as_of_raw).replace("Z", "+00:00"))
            except Exception:
                metrics.malformed_rows += 1
                return MemorySnapshot(
                    snapshot_id=snap_id, subject_guid=subject_guid, facts=[],
                    loaded_at=now, malformed=True, error=f"bad as_of on {fid}",
                    metrics=metrics,
                )
            if not bool(row.get("relevant", True)):
                metrics.rejected += 1
                continue
            facts.append(MemoryFact(
                fact_id=fid, subject_guid=subject_guid,
                content=row.get("content", row), as_of=as_of, relevant=True,
            ))
            metrics.loaded += 1
            if newest is None or as_of > newest:
                newest = as_of
        stale = False
        if newest is not None and (now - newest) > timedelta(hours=self.stale_hours):
            stale = True
        return MemorySnapshot(
            snapshot_id=snap_id, subject_guid=subject_guid,
            facts=facts, loaded_at=now,
            empty=(len(facts) == 0), stale=stale, metrics=metrics,
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
        # Return the full store. Subject matching is fail-closed in load() via
        # _row_subject_disposition — never default missing subject_guid to the
        # wake subject.
        return rows


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
    # SFR-G-002: optional outbound gateway hand-off, called only after a SETTLED
    # wake with a non-none effect. Default None = no delivery path exists at all.
    # Nothing in this module constructs one; the caller must inject it, and Lane G
    # requires an injected transport on top of that. Two independent opt-ins.
    _outbound: Callable[..., dict] | None = None

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
        selection: Any = None,
    ) -> dict:
        """Execute one wake. Idempotent on (agent, reason, slot, subject).

        `crash_after` is a test hook: 'reserved' simulates crash after CLAIMED
        reservation and before completion.

        `selection` is the SubjectCandidate (or dict) that chose this subject —
        threaded unchanged into context so decide can consume the original
        research_object / material_change id.
        """
        now = now or _now()
        selection_meta = _normalize_selection(selection)
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
        research_ids: list[str] = []
        if selection_meta and _selection_primary_kind(selection_meta) == "research_object":
            research_ids = [selection_meta["source_id"]]
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
            "research_object_ids": list(research_ids),
            "selection": selection_meta,
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
                    "inputs": (
                        [{"kind": _selection_primary_kind(selection_meta) or selection_meta["source"],
                          "id": selection_meta["source_id"]}]
                        if selection_meta else []
                    ),
                    "policy_decisions": ["feature_flag_on"],
                    "llm": None,
                    "trigger": "schedule_slot",
                    "selection": selection_meta,
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
            # Selection provenance reaches decide unchanged (original source_id).
            "selection": selection_meta,
        }

        # 3) Decide (deterministic by default)
        decide = decide or default_decide
        decision = decide(context)
        if memory_empty and decision.get("act") and not decision.get("allow_empty_memory"):
            # Explicit no-act on empty memory unless decide opts in
            # (research / material-change selection sets allow_empty_memory).
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
            # Effect receipt tied to commitment. Preserve decision effect_kind
            # (e.g. changed_question from research selection); only default to
            # changed_commitment when the decision did not name a real effect.
            emit_effect = (
                effect_kind if effect_kind and effect_kind != "none"
                else ("changed_commitment" if c_ins else "none")
            )
            primary_kind = decision.get("primary_source_kind") or (
                "memory_fact" if wake["memory_fact_ids"] else None
            )
            primary_id = decision.get("primary_source_id") or (
                wake["memory_fact_ids"][0] if wake["memory_fact_ids"] else "none"
            )
            influence = list(wake["memory_fact_ids"]) + list(wake["prior_comm_event_ids"])
            if selection_meta and selection_meta.get("source_id"):
                influence = list(dict.fromkeys(influence + [selection_meta["source_id"]]))
            erec = self._emit_receipt(
                agent_id=agent_id,
                source_kind=primary_kind or "memory_fact",
                source_id=primary_id,
                wake_id=wake_id, subject_guid=subject_guid, purpose="wake_decision",
                effect_kind=emit_effect,
                effect_ref=cid, now=now, corr=corr,
                influence_source_ids=influence,
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
        # SFR-G-002 (Lane G): outbound gateway hand-off. FAIL-CLOSED at three
        # independent points -- the flag must be on, a transport must be injected,
        # and Lane G's own ownership/allowlist gate must return delivery_owner
        # 'gateway'. Missing any one of them means NOTHING is sent. This module
        # never imports a transport and never touches the network itself; the
        # interdiction is enforced by there being no default transport to call.
        if decision.get("act") and effect_kind != "none" and self._outbound is not None:
            try:
                wake["outbound"] = self._outbound(wake=wake, receipts=receipts)
            except Exception as exc:  # never let delivery failure corrupt the wake
                wake["outbound"] = {"ok": False,
                                    "error": f"{type(exc).__name__}: {exc}"}

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
        if source_kind not in _WAKE_SOURCE_KINDS:
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
    """Deterministic decision.

    Memory facts present → MEMORY_SALIENCE commitment (unchanged).
    No memory BUT selection provenance is unconsumed_research / material_change
    → act with changed_question, preserving the ORIGINAL selection source_id.
    Neither → refuse no_relevant_memory.
    """
    facts = context.get("memory_facts") or []
    if facts:
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

    selection = context.get("selection")
    if isinstance(selection, dict):
        primary_kind = _selection_primary_kind(selection)
        source_id = selection.get("source_id")
        if primary_kind and source_id:
            # Bounded observational commitment — same shape as MEMORY_SALIENCE.
            # MBI_BEHAVIOR = 0: no sizing/ordering/stops/weights/broker reach.
            claim = f"selection:{selection.get('source')}:{source_id} warrants review"
            return {
                "act": True,
                "allow_empty_memory": True,
                "effect_kind": "changed_question",
                "commitment": {
                    "commitment_kind": "SELECTION_OBSERVATION",
                    "claim": claim,
                    "normalized_claim": _normalize_claim(claim),
                },
                "primary_source_kind": primary_kind,
                "primary_source_id": str(source_id),  # ORIGINAL id, never reminted
                "reason": "organic_from_selection",
            }

    return {"act": False, "effect_kind": "none", "reason": "no_relevant_memory"}


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
    selection: Any = None,
    outbound: Callable[..., dict] | None = None,
) -> dict:
    """Stable entrypoint for a future schedule. Does not install the schedule.

    ``selection`` — SubjectCandidate or ``{source, source_id, observed_at}`` —
    is threaded into context so decide can consume the selecting research /
    material-change id verbatim.
    """
    when = when or _now()
    contract = contract or ScheduleContract(agent_id=agent_id, wake_reason=wake_reason)
    slot = contract.slot_for(when)
    engine = WakeEngine(
        store=JsonlStore(state_root),
        memory_loader=MemoryLoader(memory_backend),
        comms=comms or NullCommsHistory(),
        # SFR-G-003: threaded through rather than reconstructing the engine in the
        # runner, which would duplicate slot/contract resolution. None = no
        # delivery path exists, which stays the default for every caller.
        _outbound=outbound,
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
        selection=selection,
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
    "MemoryLoadMetrics",
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
