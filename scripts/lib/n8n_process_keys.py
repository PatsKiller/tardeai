"""Server-side validation of ``p:`` (process-step) run keys (n8n fabric, 2026-10-15; AGENTS.md §23.23).

A fabric process workflow (``config/n8n_fabric_processes.json``, rendered by ``scripts/n8n_workflow_templates.py
build-fabric``) asks Run Lane to run each step with the idempotency key ``p:<lane>:<mode>:<slot>[:aN]``. Until this
module the gateway accepted that key as a free-form caller key and the executor refused every LIVE ``p:`` run
(``effect:effect_slot_unknown``, fail closed) because nothing on the host had checked the slot. §23.23 puts
idempotency keys on the host ("server-minted or manifest-validated, never free-form"); this is the manifest
validation:

* the key is well formed and names the request's own lane and mode (``MALFORMED_KEY`` / ``KEY_MISMATCH``);
* the lane is a step of a registered process and that step is not BLOCKED (``NOT_A_PROCESS_STEP`` /
  ``STEP_BLOCKED``);
* a ``live`` key is accepted only when the process spec's ``mode`` is ``live`` (``MODE_NOT_LIVE``): while the spec
  says ``dry_run`` nothing in n8n is entitled to ask for a live step;
* the slot is not in the future and not older than ``WINDOW_S`` (the process execution timeout plus a margin), in
  ``America/New_York`` (``SLOT_IN_FUTURE`` / ``SLOT_EXPIRED``), so a forged or replayed old slot is refused;
* the slot is the step's STAGE slot (today's date + the stage's cron minute, the same string the cron stage runner's
  effect-key claim uses: ``pipeline_manifest.effect_slot``) = ``scheduled``; any other minute is a ``manual`` slot.
  A manual slot is accepted for ``dry_run``; for ``live`` only when the process spec sets
  ``live_manual_slots: true`` (an operator flag, false at merge), because a manual live slot's effect key differs
  from the cron runner's and the two could each claim their own key (``MANUAL_LIVE_REFUSED``); an optional
  ``live_manual_slots_until`` (ISO-8601 with offset) bounds that flag, refusing at or after it (``MANUAL_LIVE_EXPIRED``);
* the attempt suffix ``:aN`` is at most the step's Run Lane budget (``ATTEMPT_OVER_BUDGET``).

The gateway stores the base key (no attempt suffix) as the run row's ``slot_key``; the executor's effect gate
claims ``fx:<process>:<slot>:<ver>`` for a ``p:`` row only when that ``slot_key`` is present (the server validated
it). Pure apart from ``load_sources`` (two JSON reads). Never writes, never spawns, never sends.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
PROCESS_SPEC_REL = Path("config") / "n8n_fabric_processes.json"
PROCESS_SPEC_SCHEMA = "N8nFabricProcesses@v1"
PREFIX = "p:"
KEY_RE = re.compile(r"^p:([a-z0-9][a-z0-9._-]{1,63}):(dry_run|live):([0-9]{8}T[0-9]{4})(?::a([2-9]))?$")
SLOT_TZ = "America/New_York"
#: n8n's execution timeout for a process (scripts/n8n_workflow_templates.py PROCESS_EXECUTION_TIMEOUT_S = 3600) plus
#: queueing margin: the last step of a manual all-stages run is requested at most this long after its slot.
WINDOW_S = 3600 + 300
#: A request may arrive this far before its slot minute (clock skew between n8n and the host).
FUTURE_SKEW_S = 120
#: Run Lane's own ceiling (scripts/n8n_workflow_templates.py RUN_LANE_MAX_ATTEMPTS); a spec cannot raise it.
RUN_LANE_MAX_ATTEMPTS = 3
STATES = (
    "OK",
    "MALFORMED_KEY",
    "KEY_MISMATCH",
    "NOT_A_PROCESS_STEP",
    "STEP_BLOCKED",
    "MODE_NOT_LIVE",
    "SLOT_IN_FUTURE",
    "SLOT_EXPIRED",
    "MANUAL_LIVE_REFUSED",
    "MANUAL_LIVE_EXPIRED",
    "ATTEMPT_OVER_BUDGET",
    "PROCESS_SPEC_UNREADABLE",
)


class ProcessKeyError(ValueError):
    pass


@dataclass(frozen=True)
class ProcessKeyCheck:
    ok: bool
    state: str
    slot_key: Optional[str] = None
    attempt: int = 1
    process_id: Optional[str] = None
    step_id: Optional[str] = None
    stage: Optional[str] = None
    slot: Optional[str] = None
    slot_kind: Optional[str] = None  # "scheduled" | "manual"


def is_process_key(key: Any) -> bool:
    """Case-insensitive, so ``P:`` cannot pass as a free-form caller key."""
    return isinstance(key, str) and key[:2].lower() == PREFIX


def parse_process_key(key: Any) -> Optional[tuple[str, str, str, int]]:
    """(lane_id, mode, slot, attempt) of a well-formed lower-case ``p:`` key, else None."""
    m = KEY_RE.fullmatch(key) if isinstance(key, str) else None
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3), int(m.group(4) or 1)


def base_key(lane_id: str, mode: str, slot: str) -> str:
    return f"{PREFIX}{lane_id}:{mode}:{slot}"


def load_sources(root: Path | None = None) -> dict[str, Any]:
    """{"processes": <spec processes>, "manifests": {process_id: manifest}} re-read from disk (a reviewed spec change
    applies without a restart). Raises ProcessKeyError on an unreadable or malformed file: the caller fails closed."""
    base = root or ROOT
    try:
        doc = json.loads((base / PROCESS_SPEC_REL).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProcessKeyError("process_spec_unreadable") from exc
    if (
        not isinstance(doc, dict)
        or doc.get("schema") != PROCESS_SPEC_SCHEMA
        or not isinstance(doc.get("processes"), dict)
    ):
        raise ProcessKeyError("process_spec_unreadable")
    manifests: dict[str, Any] = {}
    for pid, spec in doc["processes"].items():
        rel = spec.get("manifest") if isinstance(spec, dict) else None
        if not isinstance(rel, str) or rel.startswith("/") or ".." in rel:
            raise ProcessKeyError("process_spec_unreadable")
        try:
            manifests[pid] = json.loads((base / rel).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProcessKeyError("process_spec_unreadable") from exc
    return {"processes": doc["processes"], "manifests": manifests}


def _stage_slot_hhmm(manifest: Mapping[str, Any], stage: str) -> str:
    try:
        from scripts.pipelines.pipeline_manifest import stage_slot_hhmm
    except ImportError:  # pragma: no cover - run with scripts/ on sys.path
        from pipelines.pipeline_manifest import stage_slot_hhmm  # type: ignore[no-redef]
    return stage_slot_hhmm(dict(manifest), stage)


def find_step(sources: Mapping[str, Any], lane_id: str) -> Optional[dict[str, Any]]:
    """The process step whose lane is ``lane_id``: {process_id, step_id, stage, spec, step, manifest} or None."""
    for pid, spec in (sources.get("processes") or {}).items():
        for sid, step in (spec.get("steps") or {}).items():
            if isinstance(step, dict) and step.get("lane_id") == lane_id:
                manifest = (sources.get("manifests") or {}).get(pid) or {}
                stage = next(
                    (
                        st_name
                        for st_name, s in (manifest.get("stages") or {}).items()
                        if any(str(x.get("id")) == sid for x in s.get("steps") or [])
                    ),
                    None,
                )
                return {
                    "process_id": pid,
                    "step_id": sid,
                    "stage": stage,
                    "spec": spec,
                    "step": step,
                    "manifest": manifest,
                }
    return None


def _now_utc(now: datetime | float) -> datetime:
    if isinstance(now, datetime):
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return now.astimezone(timezone.utc)
    return datetime.fromtimestamp(float(now), timezone.utc)


def _manual_live_window_open(spec: Mapping[str, Any], now: datetime | float) -> bool:
    """2026-10-16 (hermes-learning cutover, one-day manual-slots PR): ``live_manual_slots_until`` bounds the operator
    flag. Absent = the flag alone decides (unchanged). Present = an ISO-8601 time WITH an offset; at or after it, or
    unparseable / naive, a manual live slot is refused (fail closed), so a one-day flag cannot outlive its day."""
    until = spec.get("live_manual_slots_until")
    if until is None:
        return True
    try:
        end = datetime.fromisoformat(str(until))
    except ValueError:
        return False
    if end.tzinfo is None or end.utcoffset() is None:
        return False
    return _now_utc(now) < end.astimezone(timezone.utc)


def check_process_key(
    key: Any,
    lane_id: str,
    mode: str,
    *,
    sources: Mapping[str, Any] | None,
    now: datetime | float,
    tz: str = SLOT_TZ,
) -> ProcessKeyCheck:
    """Validate one ``p:`` key for a run request of (lane_id, mode). ``sources`` is ``load_sources()``; None means
    the spec was unreadable (PROCESS_SPEC_UNREADABLE, fail closed)."""
    parsed = parse_process_key(key)
    if parsed is None:
        return ProcessKeyCheck(False, "MALFORMED_KEY")
    k_lane, k_mode, slot, attempt = parsed
    if k_lane != lane_id or k_mode != mode:
        return ProcessKeyCheck(False, "KEY_MISMATCH")
    if sources is None:
        return ProcessKeyCheck(False, "PROCESS_SPEC_UNREADABLE")
    found = find_step(sources, lane_id)
    if found is None or found["stage"] is None:
        return ProcessKeyCheck(False, "NOT_A_PROCESS_STEP")
    ctx = {"process_id": found["process_id"], "step_id": found["step_id"], "stage": found["stage"], "slot": slot}
    if found["step"].get("blocked"):
        return ProcessKeyCheck(False, "STEP_BLOCKED", **ctx)
    spec = found["spec"]
    if mode == "live" and spec.get("mode") != "live":
        return ProcessKeyCheck(False, "MODE_NOT_LIVE", **ctx)
    budget = int(found["step"].get("max_attempts") or spec.get("default_max_attempts") or 1)
    if attempt > max(1, min(RUN_LANE_MAX_ATTEMPTS, budget)):
        return ProcessKeyCheck(False, "ATTEMPT_OVER_BUDGET", attempt=attempt, **ctx)
    try:
        slot_local = datetime.strptime(slot, "%Y%m%dT%H%M").replace(tzinfo=ZoneInfo(tz))
    except ValueError:
        return ProcessKeyCheck(False, "MALFORMED_KEY")
    age = (_now_utc(now) - slot_local.astimezone(timezone.utc)).total_seconds()
    if age < -FUTURE_SKEW_S:
        return ProcessKeyCheck(False, "SLOT_IN_FUTURE", attempt=attempt, **ctx)
    if age > WINDOW_S:
        return ProcessKeyCheck(False, "SLOT_EXPIRED", attempt=attempt, **ctx)
    try:
        stage_hhmm = _stage_slot_hhmm(found["manifest"], found["stage"])
    except ValueError:
        return ProcessKeyCheck(False, "PROCESS_SPEC_UNREADABLE", **ctx)
    kind = "scheduled" if slot[-4:] == stage_hhmm else "manual"
    if kind == "manual" and mode == "live":
        if spec.get("live_manual_slots") is not True:
            return ProcessKeyCheck(False, "MANUAL_LIVE_REFUSED", attempt=attempt, slot_kind=kind, **ctx)
        if not _manual_live_window_open(spec, now):
            return ProcessKeyCheck(False, "MANUAL_LIVE_EXPIRED", attempt=attempt, slot_kind=kind, **ctx)
    return ProcessKeyCheck(True, "OK", slot_key=base_key(lane_id, mode, slot), attempt=attempt, slot_kind=kind, **ctx)
