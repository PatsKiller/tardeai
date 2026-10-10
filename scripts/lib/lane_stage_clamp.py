"""lane_stage_clamp.py — the executor's stage clamp (AGENTS.md §23.11, §23.12).

§23.11: "The gateway and the executor clamp the mode to the row's stage: a lane in `shadow` runs `dry_run` whatever
was requested." Until 2026-10-10 nothing implemented it: the gateway recorded the requested mode and the executor
passed it through verbatim (found while building the n8n failure diagnoser, REMEDIATION_PLAN §6; operator "Ok"
2026-10-10 ~00:35 ET). This module is the one rule; scripts/n8n_run_executor.py applies it to every claimed row and
scripts/n8n_failure_diagnosis.py reads it before it asks for a live rerun.

Rule (pure, no I/O except ``load_stage_rows``):

* ``scheduler.stage`` comes from the lane's ``config/lane_registry.json`` row.
* stage ``shadow`` -> ``dry_run`` whatever was requested. ``canary`` / ``cutover`` -> the requested mode.
* FAIL CLOSED to ``dry_run`` when the stage is unknown: the registry is unreadable, the lane has no registry row
  (§23.2 "registry row first"), or the row declares a stage that is not one of the three, or the row is a
  dispatcher row (``scheduler.expression == "dispatcher"``, or the workflow id ``tradeai-dispatcher`` written as
  one) with no stage at all.
* A registered row that is not a dispatcher row and declares no stage (a lane-specific workflow, §23.2 per-lane
  ladder, or a cron/systemd lane fired by its own grant) is NOT clamped: stage is a dispatcher-row field
  (§23.2 / §23.11), and its live gate is the relay's live-lane list plus the workflow's activation grant. Clamping
  those would silently turn today's cut-over live lanes (n8n-incident-fanin, n8n-pilot-dispatch,
  n8n-research-intake-consumer, crontab-snapshot-for-health-agent, trade-ai-scalp-live) into dry runs.

A clamp never upgrades: ``dry_run`` requested is ``dry_run`` in every case.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

STAGES = ("shadow", "canary", "cutover")
LIVE_STAGES = frozenset({"canary", "cutover"})
DRY_RUN, LIVE = "dry_run", "live"


def _row_for(lane_id: str, rows: Iterable[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    for r in rows:
        if isinstance(r, Mapping) and r.get("lane_id") == lane_id:
            return r
    return None


def _scheduler(row: Mapping[str, Any]) -> Mapping[str, Any]:
    s = row.get("scheduler")
    return s if isinstance(s, Mapping) else {}


#: ``dispatcher`` is the expression a dispatcher row carries (§23.11). ``tradeai-dispatcher`` is the dispatcher's n8n
#: workflow id, written as an expression by design 02 §12.2; lane_dispatch refuses it, and the clamp treats it as a
#: dispatcher row so a mis-flipped row without a stage fails closed to dry_run instead of passing live through.
DISPATCHER_EXPRESSIONS = frozenset({"dispatcher", "tradeai-dispatcher"})


def is_dispatcher_row(row: Mapping[str, Any]) -> bool:
    s = _scheduler(row)
    return s.get("kind") == "n8n" and s.get("expression") in DISPATCHER_EXPRESSIONS


def lane_stage(lane_id: str, rows: Optional[Iterable[Mapping[str, Any]]]) -> Optional[str]:
    """The row's declared ``scheduler.stage`` when it is one of STAGES, else None."""
    if rows is None:
        return None
    row = _row_for(lane_id, rows)
    stage = _scheduler(row).get("stage") if row is not None else None
    return stage if stage in STAGES else None


def clamp_mode(lane_id: str, requested: str, rows: Optional[Iterable[Mapping[str, Any]]]) -> dict[str, Any]:
    """{requested_mode, effective_mode, stage, clamped, reason}. ``rows`` None = registry unreadable."""
    out: dict[str, Any] = {"requested_mode": requested, "effective_mode": requested, "stage": None,
                           "clamped": False, "reason": None}

    def to_dry(reason: str) -> dict[str, Any]:
        out.update(effective_mode=DRY_RUN, clamped=requested != DRY_RUN, reason=reason)
        return out

    if requested != LIVE:                       # dry_run (or a bad mode, refused by the caller) is never upgraded
        out["reason"] = "not_live"
        return out
    if rows is None:
        return to_dry("registry_unreadable")
    row = _row_for(lane_id, rows)
    if row is None:
        return to_dry("no_registry_row")
    sched = _scheduler(row)
    if "stage" in sched:
        stage = sched.get("stage")
        out["stage"] = stage if isinstance(stage, str) else None
        if stage not in STAGES:
            return to_dry("unknown_stage")
        if stage == "shadow":
            return to_dry("stage_shadow")
        out["reason"] = f"stage_{stage}"
        return out
    if is_dispatcher_row(row):
        return to_dry("dispatcher_row_without_stage")
    out["reason"] = "not_a_dispatcher_row"
    return out


def live_rerun_allowed(lane_id: str, rows: Optional[Iterable[Mapping[str, Any]]]) -> bool:
    """The diagnoser's own bar for a LIVE rerun: the row must be at stage ``cutover`` (operator 2026-10-10)."""
    return lane_stage(lane_id, rows) == "cutover"


def load_stage_rows(path: Path) -> Optional[list[Mapping[str, Any]]]:
    """The registry's lanes, or None when the file is missing, unreadable or not a {lanes: [...]} document."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    lanes = doc.get("lanes") if isinstance(doc, Mapping) else None
    return [r for r in lanes if isinstance(r, Mapping)] if isinstance(lanes, list) else None
