"""recovery_validator.py — the ONE rule for "does this run prove the lane covered / recovered?" (pure; no I/O).

Architect review of main 26fd0518 (2026-10-16), finding 1. Before this module, three components each had their own
idea of recovery evidence, and they disagreed:

* ``n8n_self_heal.verified_done`` / ``lock_skip_cover`` compared the ledger row's ``mode`` column, which is the
  REQUESTED mode. The executor's stage clamp (scripts/lib/lane_stage_clamp.py, applied in
  scripts/n8n_run_executor.py ``receipt["mode"] = clamp["effective_mode"]``) can run a live request as ``dry_run``
  while the row still says ``live``. Reviewer's reproduction: a live-requested, dry-executed run was accepted as the
  cover of a live lock skip.
* ``n8n_self_heal.output_recovered`` accepted the lane's output signal judged FRESH by heartbeat_watch (a shared file
  mtime / JSON timestamp), and ``verified_done`` accepted an advancing output-signal mtime for a live run. A newer
  shared file proves that SOMETHING wrote it, not that this lane's live run produced its contracted output.
* scripts/self_heal_fixer.py ``advance`` moved ``fix_deployed -> output_recovered`` on a newer mtime / JSON key.

The rule (``validate``), used by every component (n8n_self_heal.verified_done / lock_skip_cover / output_recovered,
scripts/n8n_failure_diagnosis.py verify_recovery, and the fixer through ``output_recovered(lane, since, contract)``):

1. The mode that counts is the EFFECTIVE mode from the run's receipt: ``stage_clamp.effective_mode`` when the
   executor clamped, else the receipt's ``mode`` (the executor overwrites it with the effective mode). The ledger
   row's ``mode`` column is the request only. No receipt, or a receipt whose two mode fields disagree, or a receipt
   claiming ``live`` for a ``dry_run`` request (a clamp never upgrades) = mode UNKNOWN = never evidence.
2. A run requested live but executed dry never covers or recovers a live requirement (reason
   ``requested_live_executed_dry``).
3. The run finished ``RUN_DONE`` exit 0, was not a lock / off-peak skip, and carries no failing output verdict.
4. A LIVE requirement needs the lane's full output contract: the receipt's ``output_verdict.verdict`` is
   ``produced`` or ``empty_allowed`` (scripts/lib/n8n_output_verdict.py, enforced by the executor for lanes whose
   allowlist entry declares ``output_receipt: "v2"``). ``declared_not_enforced`` / ``no_rule`` / an advancing mtime /
   a fresh JSON timestamp are NOT evidence. A lane that does not emit a v2 receipt therefore never auto-recovers
   live: it stays open for the model path / a human (fail closed, by design).
5. When the requirement names a semantic slot ``(lane, mode, slot)``, the run must be in that slot (its slot_key,
   run_id or parent_run_id); when it names a lane, the run must be that lane's; when it names ``since``, the run
   must have finished after it.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0: nothing here sizes, orders, stops, sends or touches a broker.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

SCHEMA = "RecoveryVerdict@v1"
MODES = frozenset({"dry_run", "live"})
#: scripts/lib/n8n_output_verdict.py verdicts that mean "the lane's contracted output was produced".
OUTPUT_MET = frozenset({"produced", "empty_allowed"})
#: verdicts that mean the run did NOT do its work (the executor fails the run on these when enforced).
OUTPUT_FAILED = frozenset({"empty_violation", "unverifiable"})
SKIP_REASONS = ("offpeak_skip", "lock_skipped", "flock_held", "safe_flock: skipped", "safe_flock_pid_running")
#: A semantic slot key: ``<ns>:<lane>:<mode>:<slot>[:aN]`` (d:/e:/g: dispatcher keys, p: process-step keys).
SEMANTIC_KEY_RE = re.compile(r"^([degp]):([a-z0-9][a-z0-9._-]{1,63}):(dry_run|live):([0-9]{8}T[0-9]{4})(?::a[0-9]+)?$")


def _ts(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, datetime):
        d = value
    else:
        try:
            d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()


def receipt_of(run: Mapping[str, Any]) -> dict[str, Any]:
    rec = run.get("receipt")
    if isinstance(rec, dict):
        return rec
    try:
        rec = json.loads(run.get("receipt_json") or "") or {}
    except (TypeError, ValueError):
        rec = {}
    return rec if isinstance(rec, dict) else {}


def effective_mode(run: Mapping[str, Any]) -> Optional[str]:
    """The mode the run EXECUTED in, from its receipt (rule 1); None = unknown = never evidence."""
    rec = receipt_of(run)
    clamp = rec.get("stage_clamp")
    seen = set()
    if isinstance(clamp, Mapping) and clamp.get("effective_mode") is not None:
        seen.add(clamp.get("effective_mode"))
    if rec.get("mode") is not None:
        seen.add(rec.get("mode"))
    if len(seen) != 1:
        return None
    mode = seen.pop()
    if mode not in MODES:
        return None
    requested = run.get("mode") or rec.get("requested_mode")
    if requested == "dry_run" and mode == "live":
        return None          # a clamp never upgrades: an inconsistent receipt is not evidence
    return mode


def semantic_slot(run: Mapping[str, Any]) -> Optional[tuple[str, str, str]]:
    """(lane, mode, slot) of a run from its slot_key, run_id or (slot-bound retry) parent_run_id; None = unknown."""
    for k in ("slot_key", "run_id", "parent_run_id"):
        m = SEMANTIC_KEY_RE.match(str(run.get(k) or ""))
        if m:
            return m.group(2), m.group(3), m.group(4)
    return None


def output_verdict(run: Mapping[str, Any]) -> Optional[str]:
    ov = receipt_of(run).get("output_verdict")
    return str(ov.get("verdict")) if isinstance(ov, Mapping) and ov.get("verdict") else None


def _lane_of(run: Mapping[str, Any]) -> Optional[str]:
    if run.get("lane_id"):
        return str(run["lane_id"])
    if receipt_of(run).get("lane_id"):
        return str(receipt_of(run)["lane_id"])
    s = semantic_slot(run)
    return s[0] if s else None


def validate(run: Optional[Mapping[str, Any]], *, mode: Optional[str], lane: Optional[str] = None,
             slot: Optional[tuple[str, str, str]] = None, since: Optional[float] = None,
             exclude_run: Optional[str] = None) -> tuple[bool, str]:
    """(ok, reason): does ``run`` prove the lane did its REQUIRED work in ``mode`` (rules 1-5)? ``mode`` is the mode
    the failure / skip / breach happened in (``live`` for an output breach). ``slot`` = (lane, mode, slot) of the
    semantic slot the evidence must belong to; its mode element is ignored (the effective mode is checked). Pure."""
    if not run:
        return False, "no_run"
    if mode not in MODES:
        return False, "required_mode_unknown"
    if exclude_run is not None and run.get("run_id") == exclude_run:
        return False, "same_run"
    if lane is not None:
        rl = _lane_of(run)
        if rl is None or rl != lane:
            return False, f"other_lane:{rl or 'unknown'}"
    if since is not None:
        fin = _ts(run.get("finished_at")) or _ts(receipt_of(run).get("finished_at"))
        if fin is None or fin <= since:
            return False, "not_after_since"
    if slot is not None:
        rs = semantic_slot(run)
        if rs is None:
            return False, "slot_unknown"
        if rs[0] != slot[0] or rs[2] != slot[2]:
            return False, "other_slot"
    if run.get("state") != "RUN_DONE":
        return False, f"state:{run.get('state')}"
    rec = receipt_of(run)
    ec = run.get("exit_code")
    if ec is None:
        ec = rec.get("exit_code")
    if ec not in (None, 0, "0"):
        return False, f"exit:{ec}"
    if rec.get("lock_skipped") or any(s in str(rec.get("reason") or "").lower() for s in SKIP_REASONS):
        return False, "skip_not_work"
    eff = effective_mode(run)
    if eff is None:
        return False, "effective_mode_unknown"
    if eff != mode:
        requested = run.get("mode") or rec.get("requested_mode")
        if mode == "live" and requested == "live" and eff == "dry_run":
            return False, "requested_live_executed_dry"
        return False, f"mode_mismatch:{eff}_is_not_{mode}"
    ov = output_verdict(run)
    if ov in OUTPUT_FAILED:
        return False, f"output_verdict:{ov}"
    if mode == "live" and ov not in OUTPUT_MET:
        return False, f"output_contract_unproven:{ov or 'none'}"
    return True, "ok"


def output_recovered(lane: str, since: Optional[float], contract: Optional[Mapping[str, Any]] = None, *,
                     runs: Iterable[Mapping[str, Any]], exclude_run: Optional[str] = None
                     ) -> Optional[dict[str, Any]]:
    """The first run in ``runs`` that proves ``lane`` recovered after ``since`` by ``validate``, as evidence; None
    when none does. ``contract`` (optional): {"mode": the required mode (default ``live``), "slot": [lane, mode, slot]
    or None}. The fixer calls this as ``output_recovered(lane, since, contract, runs=<the lane's ledger rows>)``; a
    file mtime or JSON timestamp is never an input."""
    c = dict(contract or {})
    mode = c.get("mode") or "live"
    slot = tuple(c["slot"]) if c.get("slot") else None
    since_ts = _ts(since)
    for r in runs:
        ok, _why = validate(r, mode=mode, lane=lane, slot=slot, since=since_ts, exclude_run=exclude_run)
        if ok:
            return {"schema": SCHEMA, "basis": "verified_run_effective_mode", "evidence": [f"run:{r.get('run_id')}"],
                    "mode": mode, "effective_mode": effective_mode(r), "output_verdict": output_verdict(r),
                    "slot": list(slot) if slot else None}
    return None
