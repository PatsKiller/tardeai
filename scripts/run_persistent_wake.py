#!/usr/bin/env python3
"""run_persistent_wake.py — cron-callable CLI for PersistentAgentWake@v2.

Thin runner around ``run_scheduled_wake``. Does NOT install or activate any
crontab, systemd unit, or timer (AGENTS.md §17). Activation stays operator-only.

Fail-closed: BOTH env flags must be on, otherwise exit 0 with no side effects:
  PERSISTENT_WAKE_ENABLED
  PERSISTENT_WAKE_SCHEDULE_ENABLED

When ``--subject-guid`` is omitted, subjects come from
``scripts.lib.wake_subject_selector`` (unconsumed research first, then recent
MaterialChange@v1). An empty selection reports
``detail: "selector returned no candidates"`` — distinguishable from a missing
argument.

Idempotent per schedule slot *per subject*. Missed slots are skipped
(catch_up_policy=skip_missed). Exit 0 for ok / disabled / nothing-due; exit 1
for hard errors.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_PROJECT = Path(__file__).resolve().parents[1]
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from scripts.lib.persistent_agent_wake import (  # noqa: E402
    FEATURE_FLAG as WAKE_FLAG,
    feature_enabled as wake_feature_enabled,
    run_scheduled_wake,
)

# SFR-G-003. Imported as a MODULE, not `from ... import deliver_agent_outbound`,
# so static reachability can follow run_persistent_wake -> gateway_settlement ->
# deliver_agent_outbound. An ImportFrom of the leaf would hide the edge from the
# very gate that exists to prove it.
import scripts.lib.gateway_settlement as gateway_settlement  # noqa: E402
from scripts.lib.persistent_wake_schedule import (  # noqa: E402
    FEATURE_FLAG as SCHEDULE_FLAG,
    ScheduleContract,
)
from scripts.lib.persistent_wake_store import JsonlStore  # noqa: E402
from scripts.lib.wake_subject_selector import (  # noqa: E402
    DEFAULT_LIMIT,
    SubjectCandidate,
    load_selection_inputs,
    select_subjects,
)

WAKE_REASON = "scheduled_persistent_review"
DEFAULT_STATE_ENV = "TRADEAI_PERSISTENT_WAKE_STATE_ROOT"
DEFAULT_MEMORY_ENV = "TRADEAI_PERSISTENT_WAKE_MEMORY_PATH"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def schedule_enabled(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return _truthy(e.get(SCHEDULE_FLAG))


def both_flags_on(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return wake_feature_enabled(e) and schedule_enabled(e)


def _emit(line: dict[str, Any]) -> None:
    print(json.dumps(line, sort_keys=True, default=str), flush=True)


#: Release-independent home for persistent-wake evidence. Anything under a
#: release directory is destroyed-by-replacement on the next promote.
SHARED_STATE_ROOT = Path.home() / "trade-ai-state" / "persistent_wake" / "state"

#: Marks a checkout as an immutable deployed release rather than a dev tree.
_RELEASE_MARKER = "trade-ai-releases"


def _is_release_tree(path: Path) -> bool:
    return _RELEASE_MARKER in path.parts


def _default_state_root(env: dict) -> Path:
    """Resolve the durable wake state root.

    Precedence: explicit env var, then a release-independent shared root when
    running from a deployed release, then the project-local path for dev/tests.

    Why the shared root exists. The state used to live at
    ``<release>/data/persistent_wake/state``. ``prepare`` snapshots the current
    release, so every wake that fired between prepare and promote was stranded
    in the retiring release and never appeared in the new one -- the evidence
    silently FORKED on each deploy. Observed 2026-09-09: the 23:00Z wake landed
    in dbdf498b9 (102 rows, latest slot 23:00Z) while the release promoted at
    23:14Z carried only 99 rows, latest slot 19:00Z. Three contiguous organic
    cycles can never accumulate across a promote under that layout, and the loss
    is invisible because both files look healthy in isolation.

    Dev and test trees keep the project-local path so nothing outside a release
    changes behaviour.
    """
    raw = env.get(DEFAULT_STATE_ENV) or ""
    if raw:
        return Path(raw)
    if _is_release_tree(_PROJECT):
        return SHARED_STATE_ROOT
    return _PROJECT / "data" / "persistent_wake" / "state"


def _emitted_receipts(root: Path) -> list[dict]:
    """The agent's OWN consumption receipts from the JSONL state store it writes.

    Closes the selection loop. The file-backed selector feed
    (``TRADEAI_WAKE_RECEIPTS_PATH``) is regenerated from the database and never
    contains receipts this runner just wrote. Observed 2026-09-08 on deployed
    ``54639ff5a``: slots 13:00Z and 14:00Z re-selected the same three sources
    and re-emitted the same UUIDv5 receipt ids while ten other research objects
    were never reached.

    Fail-safe: never raises into the wake path. Missing or unreadable state
    returns ``[]`` (degrades to feed-only — the pre-existing behaviour). Does
    not fabricate receipts.
    """
    try:
        return list(JsonlStore(root).iter("receipts"))
    except Exception:
        return []


def _completed_slots(
    store: JsonlStore, *, agent_id: str, wake_reason: str, subject_guid: str,
) -> set[str]:
    out: set[str] = set()
    for row in store.iter("wakes"):
        if row.get("agent_id") != agent_id:
            continue
        if row.get("wake_reason") != wake_reason:
            continue
        if str(row.get("subject_guid")) != str(subject_guid):
            continue
        if row.get("lifecycle_state") in {
            "SETTLED", "ABANDONED", "STALE", "MEMORY_UNAVAILABLE", "MEMORY_MALFORMED",
        }:
            slot = row.get("schedule_slot_utc")
            if slot:
                out.add(str(slot))
    return out


def _missed_slots(contract: ScheduleContract, when: datetime, completed: set[str], current: str) -> list[str]:
    missed: list[str] = []
    n = max(1, contract.staleness_tolerance_minutes // contract.cadence_minutes)
    for i in range(1, n + 1):
        past = contract.slot_for(when - timedelta(minutes=i * contract.cadence_minutes))
        if past not in completed and past != current:
            missed.append(past)
    return missed


def _process_one_subject(
    *,
    agent_id: str,
    subject_guid: str,
    dry_run: bool,
    env: dict,
    when: datetime,
    state_root: Path,
    memory_backend: Any,
    selection: SubjectCandidate | dict | None = None,
) -> int:
    """Run one subject for the current slot. Return process exit code.

    ``selection`` is the SubjectCandidate that chose this subject (source /
    source_id / observed_at). It is passed into run_scheduled_wake so decide
    can consume the ORIGINAL research / material-change id — not log-only.
    """
    contract = ScheduleContract(agent_id=agent_id, wake_reason=WAKE_REASON)
    slot = contract.slot_for(when)
    base: dict[str, Any] = {
        "script": "run_persistent_wake",
        "agent_id": agent_id,
        "subject_guid": subject_guid,
        "slot": slot,
        "wake_flag": WAKE_FLAG,
        "schedule_flag": SCHEDULE_FLAG,
    }
    if selection is not None:
        if isinstance(selection, SubjectCandidate):
            base["selection_source"] = selection.source
            base["selection_source_id"] = selection.source_id
        elif isinstance(selection, dict):
            if selection.get("source"):
                base["selection_source"] = selection.get("source")
            if selection.get("source_id"):
                base["selection_source_id"] = selection.get("source_id")

    store = JsonlStore(state_root)
    completed = _completed_slots(
        store, agent_id=agent_id, wake_reason=WAKE_REASON, subject_guid=subject_guid,
    )

    if slot in completed:
        _emit({
            **base,
            "outcome": "nothing_due",
            "wake_id": "none",
            "detail": "current slot already complete; missed slots skipped",
            "missed_skipped": _missed_slots(contract, when, completed, slot),
        })
        return 0

    if dry_run:
        _emit({
            **base,
            "outcome": "dry_run",
            "wake_id": "none",
            "detail": "would invoke run_scheduled_wake; no writes",
        })
        return 0

    # SFR-G-003: construct the outbound callable ONLY when the campaign flag is
    # on. Fail-closed at four independent points -- flag off => None; Lane G
    # refuses without an injected transport; its ownership/allowlist gate must
    # return delivery_owner='gateway'; and CANARY/ACTIVE scope is enforced inside
    # build_wake_outbound_handler. Any one of them missing means nothing is sent.
    outbound = None
    if gateway_settlement.wake_gateway_outbound_enabled(env):
        outbound = gateway_settlement.build_wake_outbound_handler(
            env=env,
            transport=gateway_settlement.sanctioned_telegram_transport,
            deliver=True,
        )

    try:
        result = run_scheduled_wake(
            agent_id=agent_id,
            subject_guid=subject_guid,
            wake_reason=WAKE_REASON,
            state_root=state_root,
            memory_backend=memory_backend,
            when=when,
            contract=contract,
            env=env,
            selection=selection,
            outbound=outbound,
        )
    except Exception as exc:
        _emit({
            **base,
            "outcome": "error",
            "wake_id": "none",
            "detail": f"{type(exc).__name__}: {exc}",
        })
        return 1

    if result.get("skipped"):
        _emit({
            **base,
            "outcome": "disabled",
            "wake_id": "none",
            "detail": result.get("reason") or "feature_flag_off",
        })
        return 0

    wake = result.get("wake") or {}
    wake_id = wake.get("wake_id") or "none"
    state = wake.get("lifecycle_state") or result.get("state") or "unknown"

    if result.get("replay_suppressed"):
        outcome = "nothing_due"
        detail = "idempotent collision; slot already settled"
    elif state in {"MEMORY_MALFORMED", "STALE", "MEMORY_UNAVAILABLE"}:
        outcome = "refused"
        detail = f"memory_state={state}"
    elif result.get("memory_empty") and state == "LOADED":
        outcome = "refused"
        detail = "no_relevant_memory"
    elif result.get("ok"):
        outcome = "ok"
        detail = f"lifecycle_state={state}"
    else:
        outcome = "refused"
        detail = f"lifecycle_state={state}"

    _emit({
        **base,
        "outcome": outcome,
        "wake_id": wake_id,
        "detail": detail,
        "missed_skipped": _missed_slots(contract, when, completed, slot),
        "inserted": bool(result.get("inserted")),
    })
    return 0


def run_once(
    *,
    agent_id: str,
    subject_guid: str | None = None,
    dry_run: bool = False,
    env: dict | None = None,
    when: datetime | None = None,
    state_root: Path | str | None = None,
    memory_backend: Any = None,
    limit: int = DEFAULT_LIMIT,
    select_only: bool = False,
    research_objects: list[dict] | None = None,
    receipts: list[dict] | None = None,
    material_changes: list[dict] | None = None,
) -> int:
    """Resolve subject(s) and process the current schedule slot.

    Explicit ``subject_guid`` ⇒ one named subject (unchanged behaviour).
    Omitted ⇒ selector; empty ⇒ ``selector returned no candidates``.
    """
    env = dict(env if env is not None else os.environ)
    when = when or _now()
    contract = ScheduleContract(agent_id=agent_id, wake_reason=WAKE_REASON)
    slot = contract.slot_for(when)

    base = {
        "script": "run_persistent_wake",
        "agent_id": agent_id,
        "subject_guid": subject_guid,
        "slot": slot,
        "wake_flag": WAKE_FLAG,
        "schedule_flag": SCHEDULE_FLAG,
    }

    if not both_flags_on(env):
        _emit({
            **base,
            "outcome": "disabled",
            "wake_id": "none",
            "detail": (
                f"{WAKE_FLAG}={'on' if wake_feature_enabled(env) else 'off'} "
                f"{SCHEDULE_FLAG}={'on' if schedule_enabled(env) else 'off'}; "
                "both must be on"
            ),
        })
        return 0

    root = Path(state_root) if state_root is not None else _default_state_root(env)
    if memory_backend is None:
        mem_path = env.get(DEFAULT_MEMORY_ENV) or ""
        memory_backend = Path(mem_path) if mem_path else None

    # Resolve subjects — keep full SubjectCandidate so source_id reaches decide.
    selection_meta: list[SubjectCandidate] = []
    work: list[tuple[str, SubjectCandidate | None]]
    if subject_guid:
        work = [(subject_guid, None)]
    else:
        inputs = {
            "research_objects": research_objects,
            "receipts": receipts,
            "material_changes": material_changes,
        }
        if inputs["research_objects"] is None and inputs["receipts"] is None and inputs["material_changes"] is None:
            loaded = load_selection_inputs(env)
            inputs = loaded
        # Union feed receipts with receipts this agent already emitted so a
        # subject consumed in an earlier slot is not selected again. Without
        # this the loop never closes — see _emitted_receipts.
        inputs["receipts"] = list(inputs.get("receipts") or []) + _emitted_receipts(root)
        selection_meta = select_subjects(
            agent_id,
            limit=limit,
            now=when,
            research_objects=inputs.get("research_objects") or [],
            receipts=inputs.get("receipts") or [],
            material_changes=inputs.get("material_changes") or [],
        )
        if not selection_meta:
            _emit({
                **base,
                "outcome": "nothing_due",
                "wake_id": "none",
                "detail": "selector returned no candidates",
                "limit": limit,
            })
            return 0
        work = [(c.subject_guid, c) for c in selection_meta]

    if select_only:
        _emit({
            **base,
            "outcome": "select_only",
            "wake_id": "none",
            "detail": "selection only; no writes",
            "candidates": [c.to_dict() for c in selection_meta] if selection_meta else [
                {"subject_guid": subject_guid, "source": "explicit"}
            ],
            "limit": limit,
        })
        return 0

    rc = 0
    for sg, cand in work:
        subject_rc = _process_one_subject(
            agent_id=agent_id,
            subject_guid=sg,
            dry_run=dry_run,
            env=env,
            when=when,
            state_root=root,
            memory_backend=memory_backend,
            selection=cand,
        )
        if subject_rc != 0:
            rc = subject_rc
    return rc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Cron-callable persistent wake runner (schedule-READY; not schedule-ACTIVE)",
    )
    p.add_argument("--agent-id", required=True, help="Agent id (e.g. cio)")
    p.add_argument(
        "--subject-guid",
        default=None,
        help="Explicit subject GUID. If omitted, the subject selector chooses.",
    )
    p.add_argument("--dry-run", action="store_true", help="Report what would run; write nothing")
    p.add_argument(
        "--once",
        action="store_true",
        default=True,
        help="Process current slot and exit (default)",
    )
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                   help=f"Max subjects from selector when --subject-guid omitted (default {DEFAULT_LIMIT})")
    p.add_argument("--select-only", action="store_true",
                   help="Print selector results and exit without writing")
    p.add_argument("--state-root", default=None, help="Disposable/state JSONL root (tests/ops)")
    p.add_argument("--memory-path", default=None, help="Optional memory JSONL path")
    p.add_argument("--when-utc", default=None, help="Override clock ISO-8601 UTC (tests only)")
    args = p.parse_args(argv)

    when = _now()
    if args.when_utc:
        when = datetime.fromisoformat(args.when_utc.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)

    env = dict(os.environ)
    mem = Path(args.memory_path) if args.memory_path else None
    return run_once(
        agent_id=args.agent_id,
        subject_guid=args.subject_guid,
        dry_run=args.dry_run,
        env=env,
        when=when,
        state_root=args.state_root,
        memory_backend=mem,
        limit=args.limit,
        select_only=args.select_only,
    )


if __name__ == "__main__":
    raise SystemExit(main())
