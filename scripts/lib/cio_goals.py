"""CIO Goal + Thesis store — durable JSONL beside action/wake ledgers.

READ_ONLY_ADVISORY. No broker/order/risk/secret authority.

Storage (append-only event log + rebuildable projection):
  data/cio/cio_goals.jsonl          — immutable events
  data/cio/cio_goals_projection.json — rebuildable snapshot

Statuses: open | blocked | achieved | cancelled | superseded
Owners: alex | morgan | steph | hermes (and other roster ids allowed)

P2/P7 (2026-09-16) — a goal now stops for a stated reason, with proof:
  * `GOAL_PREDICATE_SET` carries the predicate whose satisfaction IS "done".
    Identity is (goal_id, predicate_version, predicate_hash); no new id scheme.
  * `close_goal` REQUIRES non-empty evidence; `achieved` also requires a
    non-vacuous falsifier and binds an `outcome_checkpoints` re-check.
  * `terminate_goal` names one of five outcomes: sufficient | no_new_evidence |
    budget_exhausted | bounded_ignorance | ask_operator.
  * `due_ts` earlier than `created_ts` is refused -- the live defect that made
    three goals due before they existed, and so due on every tick forever.
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

DEFAULT_GOALS_PATH = Path("data/cio/cio_goals.jsonl")
DEFAULT_PROJECTION_PATH = Path("data/cio/cio_goals_projection.json")
DEFAULT_EVENT_CURSOR_PATH = Path("data/cio/cio_goal_event_cursors.json")

VALID_STATUSES = frozenset({"open", "blocked", "achieved", "cancelled", "superseded"})
OPENISH = frozenset({"open", "blocked"})
VALID_OWNERS = frozenset({
    "alex", "morgan", "steph", "hermes", "maria", "guardian", "ledger",
    "sentinel", "darwin", "iris", "reflection",
})

VALID_EVENT_TYPES = frozenset({
    "GOAL_CREATED",
    "GOAL_UPDATED",
    "GOAL_STATUS_CHANGED",
    "GOAL_THESIS_UPDATED",
    "GOAL_WAKE_RECORDED",
    "GOAL_LINKED",
    # P2 (2026-09-16). Safe in both directions by construction:
    #   * `_append_event` REJECTS an event type it does not know, so a typo can
    #     never reach the log.
    #   * `_apply_event` SILENTLY IGNORES an event type it does not know, so a
    #     reader running older code replays a log containing this event and
    #     degrades to "this goal has no predicate" instead of crashing.
    # The pair is what makes a new event type additive rather than a migration.
    "GOAL_PREDICATE_SET",
})

# ── P2: the goal predicate ───────────────────────────────────────────────────
# A goal closes because a predicate over evidence is satisfied, not because a
# step ran. Identity is (goal_id, predicate_version, predicate_hash) -- it
# REUSES goal_id and mints no sixth id scheme (the operator's GUID-first rule).

PREDICATE_SCHEMA = "GoalPredicate@v1"

VERDICT_SATISFIED = "SATISFIED"
VERDICT_UNSATISFIED = "UNSATISFIED"
VERDICT_UNEVALUABLE = "UNEVALUABLE"

#: Evaluators this code can actually run. An evaluator outside this set is
#: UNEVALUABLE -- never `satisfied`. A predicate may still be STORED with an
#: unknown evaluator: that is what lets newer code write a predicate older code
#: can read without either lying or dying.
KNOWN_EVALUATORS = frozenset({"all_terms_true@v1"})

# ── P7: termination ──────────────────────────────────────────────────────────
#: The five ways a goal may stop. Anything else is not a termination and will
#: not close a goal.
TERMINATION_OUTCOMES = (
    "sufficient",          # predicate satisfied AND the validator is calibrated
    "no_new_evidence",     # two laps, identical ledger digest
    "budget_exhausted",    # the per-goal budget is spent
    "bounded_ignorance",   # every open need is UNOBTAINABLE -- states what is NOT knowable
    "ask_operator",        # escalate to a human
)

#: Only `sufficient` may claim achievement. The other four stop the work
#: without claiming the question was answered -- that distinction is the whole
#: point of naming them.
TERMINATION_STATUS = {
    "sufficient": "achieved",
    "no_new_evidence": "blocked",
    "budget_exhausted": "blocked",
    "bounded_ignorance": "blocked",
    "ask_operator": "blocked",
}

#: Horizon for the re-check bound to an `achieved` goal. `resolve_due_checkpoints`
#: -- the one outcome loop that already works and refuses to fabricate -- is what
#: picks it up when it comes due.
DEFAULT_CHECKPOINT_HORIZON = "5_sessions"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: Any) -> Optional[datetime]:
    """Parse an ISO timestamp to an aware datetime, or None if it is not one."""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _reject_inverted_due(due_ts: Any, created_ts: Any) -> None:
    """Refuse a goal that is born overdue.

    Measured 2026-09-16: all three live goals carry a `due_ts` **10 minutes
    before** their `created_ts`. A goal that is due before it exists is due on
    every tick forever, which is how 34,347 wakes were served against three
    goals that never closed. Equality is allowed -- "due the moment it is
    created" is coherent; going backwards is not.

    An unparseable `due_ts` raises rather than being ignored: silently dropping
    it is how the inversion survived 36 days without anything noticing.
    """
    if due_ts is None or str(due_ts).strip() == "":
        return
    due = _parse_ts(due_ts)
    if due is None:
        raise ValueError(f"due_ts is not an ISO timestamp: {due_ts!r}")
    created = _parse_ts(created_ts)
    if created is None:
        raise ValueError(f"created_ts is not an ISO timestamp: {created_ts!r}")
    if due < created:
        raise ValueError(
            f"due_ts {due.isoformat()} precedes created_ts {created.isoformat()}: "
            "a goal cannot be born overdue"
        )


def predicate_hash(evaluator: str, terms: Any) -> str:
    """sha256 over the predicate's MEANING (evaluator + terms), nothing else.

    Timestamps and versions are deliberately excluded so that re-stating the
    same predicate produces the same hash, and a changed predicate cannot keep
    the old one's identity.
    """
    blob = json.dumps(
        {"evaluator": str(evaluator), "terms": terms},
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def predicate_identity(goal_id: str, predicate_version: int, phash: str) -> str:
    """(goal_id, predicate_version, predicate_hash) rendered as one string.

    No new ID namespace: the goal's own id is the root of this identity.
    """
    if not goal_id:
        raise ValueError("predicate_identity requires a goal_id")
    return f"{goal_id}:v{int(predicate_version)}:{phash[:16]}"


def evaluate_predicate(predicate: Optional[dict[str, Any]], facts: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate a stored predicate against supplied facts.

    Fail-closed in every direction that could manufacture a victory:
      * no predicate at all            -> UNEVALUABLE
      * an evaluator this code does not implement -> UNEVALUABLE
      * a predicate with no terms      -> UNEVALUABLE (an empty conjunction is
        vacuously true in logic, and that is exactly how a goal would close
        having proven nothing)
      * a term with no supplied fact   -> UNEVALUABLE
    A term that is supplied and false is decisive, so it returns UNSATISFIED.
    The ONE path to SATISFIED is: known evaluator, at least one term, every
    term supplied, every term true.
    """
    out: dict[str, Any] = {
        "schema": "GoalPredicateVerdict@v1",
        "verdict": VERDICT_UNEVALUABLE,
        "reason": "",
        "evaluator": "",
        "predicate_identity": None,
        "terms": {},
    }
    if not isinstance(predicate, dict) or not predicate:
        out["reason"] = "no_predicate"
        return out
    evaluator = str(predicate.get("evaluator") or "")
    out["evaluator"] = evaluator
    out["predicate_identity"] = predicate.get("predicate_identity")
    if evaluator not in KNOWN_EVALUATORS:
        out["reason"] = f"unknown_evaluator:{evaluator or '(none)'}"
        return out
    terms = predicate.get("terms") or []
    if not isinstance(terms, (list, tuple)) or not terms:
        out["reason"] = "no_terms"
        return out

    supplied = facts if isinstance(facts, dict) else {}
    missing: list[str] = []
    false_terms: list[str] = []
    for term in terms:
        name = str(term)
        if name not in supplied:
            missing.append(name)
            out["terms"][name] = None
            continue
        value = bool(supplied[name])
        out["terms"][name] = value
        if not value:
            false_terms.append(name)
    if false_terms:
        out["verdict"] = VERDICT_UNSATISFIED
        out["reason"] = "false_terms:" + ",".join(sorted(false_terms))
        return out
    if missing:
        out["reason"] = "missing_facts:" + ",".join(sorted(missing))
        return out
    out["verdict"] = VERDICT_SATISFIED
    out["reason"] = "all_terms_true"
    return out


def _clean_evidence(evidence: Any) -> list[str]:
    """Evidence refs for a close. Refuses anything that proves nothing.

    `close_goal` previously defaulted to status="achieved" and required no
    evidence at all, so victory was declarable without proof. This is the
    function that makes that impossible.
    """
    if isinstance(evidence, (str, bytes)):
        raise ValueError("evidence must be a list of refs, not a bare string")
    if not isinstance(evidence, (list, tuple)):
        raise ValueError(f"evidence must be a list of refs, got {type(evidence).__name__}")
    refs = [str(e).strip() for e in evidence if str(e).strip()]
    if not refs:
        raise ValueError("evidence is empty: a goal may not be closed without proof")
    return refs


def _goal_id() -> str:
    return f"goal_{uuid.uuid4().hex[:12]}"


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


def _register_goal_on_spine(goal_id: str, linked_symbols: list[str]) -> list[str]:
    """Register `goal_id` on the subject spine, under source_table `cio_goals`.

    `goal_id` does not change: "goal_<12 hex>" is not a UUID, so the spine gives
    it the same `row_guid_for(table, pk)` uuid5 the other non-guid narrative
    surfaces get, and the goal_id itself travels in `source_id`. This is the
    join that lets a gap or a question say which goal it belongs to -- the one
    thing `cio_goals`, the only genuinely goal-keyed store here, could not do.

    A goal with no `linked_symbols` registers nothing and that is honest: the
    three live goals carry none, so there is no subject to be about yet.

    Fail-safe: the event is already on disk when this runs; an unwritten link
    never costs a goal.
    """
    if not linked_symbols:
        return []
    try:
        from scripts.lib.cio_identity_spine import register_symbol_on_spine

        return [lg for lg in (
            register_symbol_on_spine("cio_goals", goal_id, sym)
            for sym in linked_symbols
        ) if lg]
    except Exception:  # noqa: BLE001 -- a goal is never lost to a link
        return []


class CIOGoalStore:
    """Durable goal + thesis store with rebuildable projection."""

    def __init__(
        self,
        event_path: Path | str = DEFAULT_GOALS_PATH,
        projection_path: Path | str = DEFAULT_PROJECTION_PATH,
        cursor_path: Path | str = DEFAULT_EVENT_CURSOR_PATH,
    ):
        self.event_path = Path(event_path)
        self.projection_path = Path(projection_path)
        self.cursor_path = Path(cursor_path)
        self.event_path.parent.mkdir(parents=True, exist_ok=True)
        self._goals: dict[str, dict[str, Any]] = {}
        self._load_or_rebuild()

    # ── Persistence ──────────────────────────────────────────────────────

    def _load_or_rebuild(self) -> None:
        if self.projection_path.exists():
            try:
                data = json.loads(self.projection_path.read_text())
                goals = data.get("goals") or {}
                if isinstance(goals, dict):
                    self._goals = goals
                    return
            except Exception:
                pass
        self.rebuild_projection()

    def rebuild_projection(self) -> dict[str, Any]:
        goals: dict[str, dict[str, Any]] = {}
        if self.event_path.exists():
            with open(self.event_path, "r") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self._apply_event(goals, ev)
        self._goals = goals
        self._write_projection()
        return {"goal_count": len(goals)}

    def _write_projection(self) -> None:
        payload = {
            "updated_ts": _now(),
            "goal_count": len(self._goals),
            "goals": self._goals,
        }
        tmp = self.projection_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        os.replace(tmp, self.projection_path)

    def _append_event(self, event_type: str, goal_id: str, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(f"invalid event_type: {event_type}")
        envelope = {
            "event_id": f"{int(time.time() * 1_000_000):020d}-{uuid.uuid4().hex[:8]}",
            "event_type": event_type,
            "goal_id": goal_id,
            "occurred_at": _now(),
            "actor_id": actor_id,
            "actor_type": "system" if actor_id.startswith("cio_") or actor_id.endswith("_worker") else "agent",
            "authority": "READ_ONLY_ADVISORY",
            "payload": payload,
        }
        lock = _lock_path(self.event_path)
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, "a") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                with open(self.event_path, "a") as fh:
                    fh.write(json.dumps(envelope, sort_keys=True) + "\n")
                    fh.flush()
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        self._apply_event(self._goals, envelope)
        self._write_projection()
        return envelope

    def _apply_event(self, goals: dict[str, dict[str, Any]], ev: dict[str, Any]) -> None:
        et = ev.get("event_type")
        gid = ev.get("goal_id")
        if not gid:
            return
        p = ev.get("payload") or {}
        if et == "GOAL_CREATED":
            goals[gid] = dict(p)
            goals[gid]["goal_id"] = gid
            return
        g = goals.get(gid)
        if g is None:
            # orphan update — ignore fail-closed for projection
            return
        if et == "GOAL_UPDATED":
            for k, v in p.items():
                if k in ("goal_id", "created_ts"):
                    continue
                g[k] = v
            g["updated_ts"] = p.get("updated_ts") or ev.get("occurred_at") or _now()
        elif et == "GOAL_STATUS_CHANGED":
            g["status"] = p.get("status", g.get("status"))
            g["updated_ts"] = p.get("updated_ts") or ev.get("occurred_at") or _now()
            if p.get("reason"):
                g["status_reason"] = p["reason"]
        elif et == "GOAL_THESIS_UPDATED":
            g["thesis_summary"] = p.get("thesis_summary", g.get("thesis_summary", ""))
            g["updated_ts"] = p.get("updated_ts") or ev.get("occurred_at") or _now()
            hist = list(g.get("thesis_history") or [])
            hist.append({
                "ts": g["updated_ts"],
                "thesis_summary": g["thesis_summary"],
                "agent_id": p.get("agent_id"),
            })
            g["thesis_history"] = hist[-20:]
        elif et == "GOAL_WAKE_RECORDED":
            g["last_wake_ts"] = p.get("last_wake_ts") or ev.get("occurred_at")
            g["wake_count"] = int(g.get("wake_count") or 0) + 1
            g["last_outcome"] = p.get("outcome", g.get("last_outcome"))
            g["updated_ts"] = g["last_wake_ts"]
        elif et == "GOAL_LINKED":
            for field in ("linked_event_types", "linked_symbols", "linked_action_ids"):
                if field in p and isinstance(p[field], list):
                    existing = list(g.get(field) or [])
                    for item in p[field]:
                        if item not in existing:
                            existing.append(item)
                    g[field] = existing
            g["updated_ts"] = p.get("updated_ts") or ev.get("occurred_at") or _now()
        elif et == "GOAL_PREDICATE_SET":
            # ONE new projection field. The event carries the whole predicate,
            # so replaying the log rebuilds it exactly.
            g["predicate"] = {
                "schema": p.get("schema") or PREDICATE_SCHEMA,
                "predicate_version": p.get("predicate_version"),
                "predicate_hash": p.get("predicate_hash"),
                "predicate_identity": p.get("predicate_identity"),
                "evaluator": p.get("evaluator"),
                "terms": list(p.get("terms") or []),
                "set_ts": p.get("set_ts") or ev.get("occurred_at"),
            }
            g["updated_ts"] = p.get("set_ts") or ev.get("occurred_at") or _now()
        # NO `else` and NO raise, deliberately. An event type this code does not
        # know is skipped in silence so that a reader on older code can replay a
        # log written by newer code. Adding a raise here would turn every future
        # event type into a crash for every deployed older reader.

    # ── Public API ───────────────────────────────────────────────────────

    def create_goal(
        self,
        *,
        owner_agent: str,
        title: str,
        description: str = "",
        priority: str = "NORMAL",
        success_criteria: str = "",
        linked_event_types: Optional[list[str]] = None,
        linked_symbols: Optional[list[str]] = None,
        linked_action_ids: Optional[list[str]] = None,
        thesis_summary: str = "",
        due_ts: Optional[str] = None,
        actor_id: str = "cio_goals",
        goal_id: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner_agent.strip().lower()
        if owner not in VALID_OWNERS:
            raise ValueError(f"invalid owner_agent: {owner_agent}")
        if not title or not title.strip():
            raise ValueError("title required")
        gid = goal_id or _goal_id()
        ts = _now()
        _reject_inverted_due(due_ts, ts)
        payload = {
            "goal_id": gid,
            "owner_agent": owner,
            "title": title.strip(),
            "description": description or "",
            "status": "open",
            "priority": (priority or "NORMAL").upper(),
            "created_ts": ts,
            "updated_ts": ts,
            "due_ts": due_ts,
            "success_criteria": success_criteria or "",
            "linked_event_types": list(linked_event_types or []),
            "linked_symbols": [s.upper() for s in (linked_symbols or [])],
            "linked_action_ids": list(linked_action_ids or []),
            "thesis_summary": thesis_summary or "",
            "last_wake_ts": None,
            "wake_count": 0,
            "last_outcome": None,
            "thesis_history": [],
        }
        self._append_event("GOAL_CREATED", gid, payload, actor_id=actor_id)
        _register_goal_on_spine(gid, payload["linked_symbols"])
        return dict(self._goals[gid])

    def update_goal(
        self,
        goal_id: str,
        *,
        actor_id: str = "cio_goals",
        **fields: Any,
    ) -> dict[str, Any]:
        if goal_id not in self._goals:
            raise KeyError(f"unknown goal_id: {goal_id}")
        allowed = {
            "title", "description", "priority", "success_criteria", "due_ts",
            "linked_event_types", "linked_symbols", "linked_action_ids", "owner_agent",
        }
        patch = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "owner_agent" in patch:
            patch["owner_agent"] = str(patch["owner_agent"]).strip().lower()
            if patch["owner_agent"] not in VALID_OWNERS:
                raise ValueError(f"invalid owner_agent: {patch['owner_agent']}")
        if "linked_symbols" in patch and isinstance(patch["linked_symbols"], list):
            patch["linked_symbols"] = [str(s).upper() for s in patch["linked_symbols"]]
        if "due_ts" in patch:
            # Compared against the goal's OWN created_ts, not against now: moving
            # a due date into the recent past is legitimate ("this is due now"),
            # while moving it before the goal existed is the live defect.
            _reject_inverted_due(patch["due_ts"], self._goals[goal_id].get("created_ts"))
        patch["updated_ts"] = _now()
        self._append_event("GOAL_UPDATED", goal_id, patch, actor_id=actor_id)
        return dict(self._goals[goal_id])

    # ── P2: predicate ────────────────────────────────────────────────────

    def set_predicate(
        self,
        goal_id: str,
        *,
        evaluator: str,
        terms: list[str],
        actor_id: str = "cio_goals",
    ) -> dict[str, Any]:
        """Attach the predicate whose satisfaction is what "done" means.

        The evaluator is NOT validated against `KNOWN_EVALUATORS` here, on
        purpose: storing a predicate this code cannot run is safe (it reads
        UNEVALUABLE), while refusing to store it would make the store unable to
        carry a predicate written by a newer deployment.
        """
        if goal_id not in self._goals:
            raise KeyError(f"unknown goal_id: {goal_id}")
        ev_name = str(evaluator or "").strip()
        if not ev_name:
            raise ValueError("predicate requires an evaluator")
        if isinstance(terms, (str, bytes)):
            raise ValueError("terms must be a list, not a bare string")
        if not isinstance(terms, (list, tuple)):
            raise ValueError(f"terms must be a list, got {type(terms).__name__}")
        clean_terms = [str(t).strip() for t in terms if str(t).strip()]

        prior = (self._goals[goal_id].get("predicate") or {}).get("predicate_version") or 0
        version = int(prior) + 1
        phash = predicate_hash(ev_name, clean_terms)
        payload = {
            "schema": PREDICATE_SCHEMA,
            "predicate_version": version,
            "predicate_hash": phash,
            "predicate_identity": predicate_identity(goal_id, version, phash),
            "evaluator": ev_name,
            "terms": clean_terms,
            "set_ts": _now(),
        }
        self._append_event("GOAL_PREDICATE_SET", goal_id, payload, actor_id=actor_id)
        return dict(self._goals[goal_id])

    def evaluate_goal(self, goal_id: str, facts: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Verdict for this goal's predicate against supplied facts."""
        if goal_id not in self._goals:
            raise KeyError(f"unknown goal_id: {goal_id}")
        verdict = evaluate_predicate(self._goals[goal_id].get("predicate"), facts)
        verdict["goal_id"] = goal_id
        return verdict

    # ── P7: termination ──────────────────────────────────────────────────

    def _bind_goal_checkpoint(
        self,
        goal_id: str,
        *,
        root: Any,
        horizon: str,
        evidence: list[str],
        falsifier: str,
        termination: str,
    ) -> dict[str, Any]:
        """Bind a re-check for an achieved goal into `outcome_checkpoints`.

        Deliberately reuses the existing OutcomeCheckpoint@v1 store and the
        hourly `resolve_due_checkpoints` loop -- the one outcome loop that works
        and that refuses to invent a result when the data is missing. The
        checkpoint_id derives from the goal_id, so no new id is minted.

        Fails LOUDLY. An achieved goal with no bound re-check is a claim nobody
        will ever test, which is the condition this phase exists to end.
        """
        from scripts.lib.cio_institutional_learning import (
            CHECKPOINT_PATH,
            _jsonl,
            persist_checkpoint,
            schedule_outcome_checkpoint,
        )
        from scripts.lib.r17_checkpoint_binding import due_at_for

        if root is None:
            from scripts.lib.canonical_store_registry import production_state_root
            root = production_state_root()
        root_p = Path(root)
        existing = [str(r.get("checkpoint_id")) for r in _jsonl(root_p / CHECKPOINT_PATH)]
        ck = schedule_outcome_checkpoint(
            goal_id, horizon, existing, plan_id=None, plan_binding="cio_goal",
        )
        due_at = due_at_for(horizon, now=datetime.now(timezone.utc))
        if not due_at:
            raise ValueError(f"no due_at for horizon {horizon!r}: the re-check would never come due")
        ck.update({
            "due_at": due_at,
            "entity_type": "CIO_GOAL",
            "subject_id": goal_id,
            "subject_guid": None,
            "goal_id": goal_id,
            "termination": termination,
            "falsifier": falsifier,
            "evidence": list(evidence),
            "original_decision_state": {
                "as_of": _now(),
                "goal_id": goal_id,
                "title": (self._goals.get(goal_id) or {}).get("title"),
                "termination": termination,
            },
            "observational_only": True,
            "trading": False,
            "auto_registered": True,
            "created_at": _now(),
        })
        result = persist_checkpoint(root_p, ck)
        if result.get("rejected"):
            raise RuntimeError(f"checkpoint refused: {result.get('rejected')} — {result.get('reason')}")
        return ck

    def close_goal(
        self,
        goal_id: str,
        *,
        evidence: list[str],
        status: str = "achieved",
        reason: str = "",
        falsifier: Optional[str] = None,
        termination: Optional[str] = None,
        checkpoint_root: Any = None,
        checkpoint_horizon: str = DEFAULT_CHECKPOINT_HORIZON,
        actor_id: str = "cio_goals",
    ) -> dict[str, Any]:
        """Close a goal. `evidence` is REQUIRED and may not be empty.

        Before 2026-09-16 this defaulted to status="achieved" and took no
        evidence at all: any caller could declare victory with one line and no
        proof. It also had no caller anywhere, so nothing had ever closed a
        goal -- `GOAL_STATUS_CHANGED` stood at 0 across 34,704 wakes.

        An `achieved` close additionally requires a NON-VACUOUS falsifier and
        binds a checkpoint, so the claim is both refutable in principle and
        actually scheduled to be re-checked.
        """
        if goal_id not in self._goals:
            raise KeyError(f"unknown goal_id: {goal_id}")
        status = status.lower()
        if status not in VALID_STATUSES - {"open"}:
            raise ValueError(f"close status must be terminal-ish, got {status}")
        refs = _clean_evidence(evidence)
        if termination is not None and termination not in TERMINATION_OUTCOMES:
            raise ValueError(f"unknown termination outcome: {termination!r}")

        checked_falsifier = None
        checkpoint_id = None
        if status == "achieved":
            from scripts.lib.cortex_shadow_pipeline import refuse_vacuous_falsifier
            # Raises on empty AND on the repo's declared vacuous strings --
            # 343 live commitments carry exactly such a placeholder.
            checked_falsifier = refuse_vacuous_falsifier(falsifier)
            ck = self._bind_goal_checkpoint(
                goal_id,
                root=checkpoint_root,
                horizon=checkpoint_horizon,
                evidence=refs,
                falsifier=checked_falsifier,
                termination=termination or "sufficient",
            )
            checkpoint_id = ck.get("checkpoint_id")

        self._append_event(
            "GOAL_STATUS_CHANGED",
            goal_id,
            {
                "status": status,
                "reason": reason,
                "evidence": refs,
                "termination": termination,
                "falsifier": checked_falsifier,
                "checkpoint_id": checkpoint_id,
                "updated_ts": _now(),
            },
            actor_id=actor_id,
        )
        return dict(self._goals[goal_id])

    def terminate_goal(
        self,
        goal_id: str,
        *,
        outcome: str,
        evidence: list[str],
        reason: str = "",
        falsifier: Optional[str] = None,
        predicate_satisfied: Optional[bool] = None,
        validator_calibrated: Optional[bool] = None,
        checkpoint_root: Any = None,
        checkpoint_horizon: str = DEFAULT_CHECKPOINT_HORIZON,
        actor_id: str = "cio_goals",
    ) -> dict[str, Any]:
        """Stop a goal for one of the five named reasons.

        `sufficient` is the only outcome that may claim achievement, and it
        requires BOTH that the predicate was satisfied AND that the validator
        which said so is calibrated. A validator that has never disagreed is
        not evidence, so an uncalibrated one cannot produce a victory here.
        """
        if outcome not in TERMINATION_OUTCOMES:
            raise ValueError(
                f"unknown termination outcome: {outcome!r}; expected one of {list(TERMINATION_OUTCOMES)}"
            )
        if outcome == "sufficient":
            if predicate_satisfied is not True:
                raise ValueError("sufficient requires predicate_satisfied=True")
            if validator_calibrated is not True:
                raise ValueError("sufficient requires validator_calibrated=True")
        return self.close_goal(
            goal_id,
            evidence=evidence,
            status=TERMINATION_STATUS[outcome],
            reason=reason or outcome,
            falsifier=falsifier,
            termination=outcome,
            checkpoint_root=checkpoint_root,
            checkpoint_horizon=checkpoint_horizon,
            actor_id=actor_id,
        )

    def set_status(
        self,
        goal_id: str,
        status: str,
        *,
        reason: str = "",
        actor_id: str = "cio_goals",
    ) -> dict[str, Any]:
        if goal_id not in self._goals:
            raise KeyError(f"unknown goal_id: {goal_id}")
        status = status.lower()
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")
        self._append_event(
            "GOAL_STATUS_CHANGED",
            goal_id,
            {"status": status, "reason": reason, "updated_ts": _now()},
            actor_id=actor_id,
        )
        return dict(self._goals[goal_id])

    def update_thesis(
        self,
        goal_id: str,
        thesis_summary: str,
        *,
        agent_id: str = "",
        actor_id: str = "cio_goals",
    ) -> dict[str, Any]:
        if goal_id not in self._goals:
            raise KeyError(f"unknown goal_id: {goal_id}")
        self._append_event(
            "GOAL_THESIS_UPDATED",
            goal_id,
            {
                "thesis_summary": thesis_summary,
                "agent_id": agent_id,
                "updated_ts": _now(),
            },
            actor_id=actor_id or agent_id or "cio_goals",
        )
        return dict(self._goals[goal_id])

    def record_wake(
        self,
        goal_id: str,
        *,
        agent_id: str = "",
        outcome: str = "",
        actor_id: str = "cio_wake_dispatcher",
    ) -> dict[str, Any]:
        if goal_id not in self._goals:
            raise KeyError(f"unknown goal_id: {goal_id}")
        self._append_event(
            "GOAL_WAKE_RECORDED",
            goal_id,
            {
                "last_wake_ts": _now(),
                "outcome": outcome,
                "agent_id": agent_id,
            },
            actor_id=actor_id,
        )
        return dict(self._goals[goal_id])

    def list_open_goals(
        self,
        *,
        owner_agent: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows = [
            dict(g) for g in self._goals.values()
            if g.get("status") in OPENISH
        ]
        if owner_agent:
            owner = owner_agent.strip().lower()
            rows = [g for g in rows if g.get("owner_agent") == owner]
        rows.sort(key=lambda g: (g.get("priority") != "HIGH", g.get("due_ts") or "9999", g.get("created_ts") or ""))
        return rows[:limit]

    def get_goal(self, goal_id: str) -> Optional[dict[str, Any]]:
        g = self._goals.get(goal_id)
        return dict(g) if g else None

    def list_due_or_idle_goals(
        self,
        *,
        owner_agent: Optional[str] = None,
        limit: int = 10,
        idle_hours: float = 24.0,
    ) -> list[dict[str, Any]]:
        """Goals that are due (due_ts <= now) OR never woken OR idle past idle_hours."""
        now = datetime.now(timezone.utc)
        out: list[dict[str, Any]] = []
        for g in self.list_open_goals(owner_agent=owner_agent, limit=200):
            due = g.get("due_ts")
            last_wake = g.get("last_wake_ts")
            reason = None
            if due:
                try:
                    due_dt = datetime.fromisoformat(str(due).replace("Z", "+00:00"))
                    if due_dt.tzinfo is None:
                        due_dt = due_dt.replace(tzinfo=timezone.utc)
                    if due_dt <= now:
                        reason = "due"
                except Exception:
                    pass
            if reason is None and not last_wake:
                reason = "never_woken"
            if reason is None and last_wake:
                try:
                    lw = datetime.fromisoformat(str(last_wake).replace("Z", "+00:00"))
                    if lw.tzinfo is None:
                        lw = lw.replace(tzinfo=timezone.utc)
                    age_h = (now - lw).total_seconds() / 3600.0
                    if age_h >= idle_hours:
                        reason = "idle"
                except Exception:
                    pass
            if reason:
                row = dict(g)
                row["_wake_reason"] = reason
                out.append(row)
            if len(out) >= limit:
                break
        return out

    def goals_for_event_types(self, event_types: list[str], *, limit: int = 20) -> list[dict[str, Any]]:
        et_set = {e.upper() for e in event_types}
        out = []
        for g in self.list_open_goals(limit=200):
            linked = {str(x).upper() for x in (g.get("linked_event_types") or [])}
            if linked & et_set:
                out.append(dict(g))
            if len(out) >= limit:
                break
        return out

    def get_context_for_agent(self, agent_id: str, *, limit_goals: int = 10, limit_events: int = 20) -> dict[str, Any]:
        """Assemble agent context: open goals + thesis + recent goal events + open actions."""
        agent = agent_id.strip().lower()
        open_goals = self.list_open_goals(owner_agent=agent, limit=limit_goals)
        thesis_snippets = [
            {
                "goal_id": g.get("goal_id"),
                "title": g.get("title"),
                "thesis_summary": g.get("thesis_summary") or "",
                "status": g.get("status"),
            }
            for g in open_goals
            if g.get("thesis_summary")
        ]

        # Recent goal events for this owner
        recent_events: list[dict[str, Any]] = []
        if self.event_path.exists():
            try:
                lines = self.event_path.read_text().splitlines()
                for line in reversed(lines[-500:]):
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    gid = ev.get("goal_id")
                    g = self._goals.get(gid or "")
                    if g and g.get("owner_agent") == agent:
                        recent_events.append(ev)
                    if len(recent_events) >= limit_events:
                        break
                recent_events.reverse()
            except Exception:
                pass

        open_actions: list[dict[str, Any]] = []
        try:
            from scripts.lib.cio_action_ledger import CIOActionLedger
            ledger = CIOActionLedger()
            # best-effort list open actions
            if hasattr(ledger, "list_actions"):
                open_actions = ledger.list_actions(status="OPEN", limit=15)  # type: ignore
            elif hasattr(ledger, "project_open_actions"):
                open_actions = ledger.project_open_actions(limit=15)  # type: ignore
        except Exception:
            open_actions = []

        # Recent material events from CIO event bus (fail-open if missing)
        bus_events: list[dict[str, Any]] = []
        try:
            from scripts.lib.cio_event_bus import CIOEventBus, AGENT_EVENT_ROUTING
            bus = CIOEventBus()
            types = list(AGENT_EVENT_ROUTING.get(agent, frozenset()))
            polled = bus.poll(consumer=f"context:{agent}", event_types=types or None, limit=limit_events)
            for ev in polled:
                if hasattr(ev, "__dict__"):
                    bus_events.append({
                        "event_id": getattr(ev, "event_id", None),
                        "event_type": getattr(ev, "event_type", None),
                        "payload": getattr(ev, "payload", None),
                        "occurred_at": getattr(ev, "occurred_at", None),
                    })
                elif isinstance(ev, dict):
                    bus_events.append(ev)
            # Do NOT advance cursor here — context reads are non-destructive
        except Exception:
            bus_events = []

        # P3: versioned desk thesis (distinct from per-goal thesis_snippets)
        desk_thesis = None
        try:
            from scripts.lib.cio_theses import safe_context_block
            desk_thesis = safe_context_block("desk")
        except Exception:
            try:
                from lib.cio_theses import safe_context_block  # type: ignore
                desk_thesis = safe_context_block("desk")
            except Exception:
                desk_thesis = None

        return {
            "agent_id": agent,
            "as_of": _now(),
            "authority": "READ_ONLY_ADVISORY",
            "open_goals": open_goals,
            "thesis_snippets": thesis_snippets,
            "desk_thesis": desk_thesis,
            "recent_goal_events": recent_events,
            "recent_bus_events": bus_events[:limit_events],
            "open_actions": open_actions[:15],
        }

    # ── Event-bus cursor helpers (per-consumer) ──────────────────────────

    def load_cursor(self, consumer_id: str) -> str:
        if not self.cursor_path.exists():
            return ""
        try:
            data = json.loads(self.cursor_path.read_text())
            return str((data.get("cursors") or {}).get(consumer_id) or "")
        except Exception:
            return ""

    def save_cursor(self, consumer_id: str, event_id: str) -> None:
        data: dict[str, Any] = {"cursors": {}}
        if self.cursor_path.exists():
            try:
                data = json.loads(self.cursor_path.read_text())
            except Exception:
                data = {"cursors": {}}
        data.setdefault("cursors", {})[consumer_id] = event_id
        data["updated_ts"] = _now()
        tmp = self.cursor_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        os.replace(tmp, self.cursor_path)

    def dedup_key(self, agent_id: str, goal_id: str, window_bucket: str) -> str:
        raw = f"{agent_id}:{goal_id}:{window_bucket}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
