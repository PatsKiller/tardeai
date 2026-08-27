"""Read-only completion metrics for the CIO workflow lineage.

`is_complete_to_checkpoint` has existed since the lineage landed, but nothing
ever measured it. On 2026-08-27 it was False for 94/94 workflows and no surface
reported that, because "the pipeline is running" and "the pipeline completes"
were never distinguished: the stores were fresh, the logs were clean, and the
loop had simply never closed.

The measured cause was identity fragmentation, not a stage failure. Two arcs
write lineage under two different identifier systems and never join:

    A  research + specialist + checkpoint   workflow_id = "wf_" + digest(...)
    B  cio + notification                   workflow_id = the CIO run UUID

`is_complete_to_checkpoint` needs checkpoint COMPLETED *and* a settled
notification stage on one envelope. Arc A has the first, arc B has the second,
and with `event_id`/`context_id` unpopulated there is no key to join them on --
so the predicate is not merely false, it is structurally unsatisfiable.

AUTHORITY: READ_ONLY_ADVISORY. Pure analysis over the lineage projection. This
module never writes lineage, never mints identity, and never repairs a workflow.
Diagnosing a fork is not authority to merge one -- which arc owns identity is an
architecture decision, not a cleanup this code may make on its own.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from scripts.lib.cio_lineage import iter_lineage_records
from scripts.lib.cio_workflow_envelope import (
    STAGE_COMPLETED,
    STAGE_NOT_YET_CREATED,
    is_complete_to_checkpoint,
)

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "LineageCompletionReport@v1"

STAGE_KEYS = ("research", "specialist", "cio", "notification", "checkpoint")

# The two arcs observed in production. A workflow matching one and not the other
# can never satisfy is_complete_to_checkpoint.
ARC_RESEARCH = "research_checkpoint"
ARC_CIO = "cio_notification"


def latest_envelopes(path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """Latest envelope per workflow_id.

    The lineage is append-only, so a workflow appears once per stage transition.
    Counting raw rows overstates the population and mixes a workflow's early
    snapshots with its final state -- fold to the newest row per workflow first.
    """
    latest: dict[str, tuple[str, dict[str, Any]]] = {}
    for row in iter_lineage_records(path):
        if not isinstance(row, dict) or "complete_to_checkpoint" not in row:
            continue
        wid = row.get("workflow_id")
        if not wid:
            continue
        stamp = str(row.get("updated_at") or row.get("created_at") or "")
        if wid not in latest or stamp >= latest[wid][0]:
            latest[wid] = (stamp, row)
    return {wid: row for wid, (_, row) in latest.items()}


def _stage_status(envelope: dict[str, Any]) -> dict[str, str]:
    ss = envelope.get("stage_status")
    return dict(ss) if isinstance(ss, dict) else {}


def classify_arc(envelope: dict[str, Any]) -> str | None:
    """Which half of the split pipeline this workflow belongs to, if either."""
    ss = _stage_status(envelope)
    if ss.get("checkpoint") == STAGE_COMPLETED:
        return ARC_RESEARCH
    if ss.get("notification") == STAGE_COMPLETED:
        return ARC_CIO
    return None


def completion_report(path: Path | str | None = None) -> dict[str, Any]:
    """Completion metrics over the lineage. Never raises on a malformed row."""
    envelopes = latest_envelopes(path)
    total = len(envelopes)

    complete = 0
    arcs: Counter[str] = Counter()
    stalled_at: Counter[str] = Counter()
    with_checkpoint_id = 0

    for env in envelopes.values():
        if is_complete_to_checkpoint(env):
            complete += 1
        arc = classify_arc(env)
        if arc:
            arcs[arc] += 1
        if env.get("checkpoint_id"):
            with_checkpoint_id += 1
        ss = _stage_status(env)
        first_open = next(
            (k for k in STAGE_KEYS if ss.get(k) in (None, STAGE_NOT_YET_CREATED)),
            None,
        )
        stalled_at[first_open or "none"] += 1

    forked = arcs[ARC_RESEARCH] > 0 and arcs[ARC_CIO] > 0 and complete == 0

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "workflows": total,
        "complete_to_checkpoint": complete,
        "completion_rate": round(complete / total, 4) if total else None,
        "with_checkpoint_id": with_checkpoint_id,
        "arcs": dict(arcs),
        "stalled_at": dict(stalled_at),
        # Both arcs present, neither completing: the halves are being recorded
        # under different workflow ids and no envelope can ever satisfy the
        # predicate. This is the signature of identity fragmentation, and it is
        # a different fault from "a stage is failing".
        "identity_fork_suspected": forked,
    }


def findings(report: dict[str, Any] | None = None, *, path: Path | str | None = None,
             min_workflows: int = 10) -> list[dict[str, Any]]:
    """Health-agent-shaped findings. Empty when there is nothing to say.

    Deliberately silent below `min_workflows`: a quiet window legitimately has
    no completions, and an alert that fires every night is one nobody reads.
    """
    rep = report if report is not None else completion_report(path)
    out: list[dict[str, Any]] = []
    total = rep.get("workflows") or 0
    if total < min_workflows:
        return out

    if rep.get("identity_fork_suspected"):
        out.append({
            "check": "cio_lineage_identity_fork",
            "severity": "critical",
            "message": (
                f"Lineage split across two arcs with 0/{total} workflows complete: "
                f"{rep.get('arcs')}. The research and CIO halves are recorded under "
                "different workflow ids, so no envelope can reach a checkpoint with a "
                "settled notification. Needs an identity decision, not a retry."
            ),
            "detail": rep,
        })
    elif rep.get("complete_to_checkpoint") == 0:
        out.append({
            "check": "cio_lineage_no_completions",
            "severity": "warning",
            "message": (
                f"0/{total} workflows reached complete_to_checkpoint; "
                f"first open stage: {rep.get('stalled_at')}."
            ),
            "detail": rep,
        })
    return out
