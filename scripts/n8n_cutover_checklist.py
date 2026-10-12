#!/usr/bin/env python3
"""n8n_cutover_checklist.py — the operator's per-lane / per-tranche cutover checklist, from receipts.

Renders the shadow → canary → cutover → rollback ladder of the 2026-10-08 plan
(streamed-humming-wolf, "Rollback triggers" and "Verification") as Markdown checkboxes and
ticks each box only when evidence for it exists on disk. Every input is optional; a missing
file is an unticked box with the path named, never an error.

Evidence read (all under the state root, default `TRADEAI_STATE_ROOT` or the repo):

    data/runtime/n8n_runs/*.json                RunReceipt@v1 (executor) — dry_run / live per lane
    data/runtime/n8n_cutover/*.json             CutoverReceipt@v1 (cutover tool) — cutover / rollback
    config/lane_registry.json                   scheduler.kind == "n8n" after the flip
    data/runtime/n8n_lane_readiness_last.json   readiness verdict per lane
    data/runtime/n8n_migration_board_last.json  board row per lane (phase, rollback_ready)
    docs/implementation/n8n-parallel/workflows/generated/INDEX.json   workflow files exist

    python3 scripts/n8n_cutover_checklist.py --lane n8n-lab-watchdog
    python3 scripts/n8n_cutover_checklist.py --tranche N1 --write

`--write` stores `data/runtime/n8n_cutover_checklist_<lane|tranche>.md` under the state root.

Acceptance additionally requires ``--expected-sha <full integrated SHA>`` and a read-only
``--acceptance-evidence packet.json`` collected after the relevant fixes. The packet contains
``tested_sha``, ``deployed_sha``, ``fixes_deployed_at``, ``observed_at`` and ``lanes`` keyed by lane ID.
Each lane's ``runs`` observations contain ``run_id``, ``evidence_class`` (NATURAL_SHADOW,
NATURAL_CANARY, MANUAL_CANARY or NATURAL_POST_CUTOVER), ``legacy_lock``, ``legacy_authoritative``,
the exported ``ledger_run`` and a correlated ``n8n_execution`` (execution_id, workflow_id, run_id,
trigger_kind schedule/manual, started_at, finished_at). ``effect_proof_ref`` names a relative JSON
observation artifact under data/runtime containing lane_id, run_id, code_sha, observed_at,
business_effect_count, duplicate_effect_count, output_matches_contract and consumer_correct.
These are collected observations, never populated from a lock or exit code. Missing correlation,
reviewed contract fields or current release identity is NOT_MEASURED. This renderer grants no authority.

AUTHORITY: READ_ONLY_ADVISORY. Reads receipts; writes only the rendered checklist with --write.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from n8n_workflow_templates import LANES, TRANCHES  # noqa: E402
from lib.cron_schedule import last_fire_at_or_before  # noqa: E402
from lib.n8n_due import parse_key  # noqa: E402
from lib.n8n_health_contracts import unknown_fields, validate_contract  # noqa: E402

SCHEMA = "N8nCutoverChecklist@v1"
NO_CONSUMER_REASON = (
    "Operator-run renderer; the Markdown it writes is read by the operator before each cron-write "
    "grant. No lane or job imports it (plan 2026-10-08, workstream H)."
)

RUNS_DIR = Path("data/runtime/n8n_runs")
CUTOVER_DIR = Path("data/runtime/n8n_cutover")
READINESS_FILE = Path("data/runtime/n8n_lane_readiness_last.json")
BOARD_FILE = Path("data/runtime/n8n_migration_board_last.json")
REGISTRY_FILE = Path("config/lane_registry.json")
WORKFLOW_INDEX = Path("docs/implementation/n8n-parallel/workflows/generated/INDEX.json")
CONTRACTS_FILE = Path("config/n8n_health_contracts.json")
OUT_DIR = Path("data/runtime")

# ---------------------------------------------------------------------------
# tolerant readers
# ---------------------------------------------------------------------------
def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _iter_json_files(directory: Path):
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.json")):
        obj = _load_json(path)
        if isinstance(obj, dict):
            yield path, obj
        elif isinstance(obj, list):
            for row in obj:
                if isinstance(row, dict):
                    yield path, row


def _run_ok(receipt: dict) -> bool:
    state = str(receipt.get("state") or receipt.get("status") or "").upper()
    exit_code = receipt.get("exit_code", receipt.get("exit"))
    return (state == "RUN_DONE" and type(exit_code) is int and exit_code == 0
            and not receipt.get("lock_skipped") and not receipt.get("timed_out")
            and receipt.get("verdict", "ok") == "ok")


def run_receipts(state_root: Path, lane_id: str) -> dict[str, list[dict]]:
    """{mode: [receipt, ...]} for the lane; modes seen in the files, not assumed."""
    out: dict[str, list[dict]] = {}
    for path, obj in _iter_json_files(state_root / RUNS_DIR):
        if obj.get("lane_id") != lane_id:
            continue
        mode = str(obj.get("mode") or "unknown")
        row = dict(obj)
        row["_file"] = path.name
        out.setdefault(mode, []).append(row)
    return out


def cutover_receipts(state_root: Path, lane_id: str) -> list[dict]:
    rows = []
    for path, obj in _iter_json_files(state_root / CUTOVER_DIR):
        if obj.get("lane_id") != lane_id:
            continue
        row = dict(obj)
        row["_file"] = path.name
        rows.append(row)
    return rows


def _is_dry(receipt: dict) -> bool:
    if "dry_run" in receipt:
        return bool(receipt["dry_run"])
    if "apply" in receipt:
        return not bool(receipt["apply"])
    return str(receipt.get("mode", "")).lower() in {"dry_run", "dry-run"}


def _timestamp(value) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None
    except ValueError:
        return None


def _positive_number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _proof_file(state_root: Path, ref):
    """Only a declared relative observation artifact; never traverse to a credential or another root."""
    if not isinstance(ref, str) or not ref or Path(ref).is_absolute():
        return None
    path = state_root / ref
    if ".." in Path(ref).parts or not path.resolve().is_relative_to(state_root.resolve()):
        return None
    # Observation proofs belong under runtime; arbitrary files are not acceptance evidence.
    if not Path(ref).is_relative_to(OUT_DIR) or path.suffix != ".json":
        return None
    obj = _load_json(path)
    return obj if isinstance(obj, dict) else None


def acceptance_context(repo_root: Path, lane_id: str, packet, expected_sha, now: datetime) -> tuple[dict, list[str]]:
    """No release identity, review or freshness is inferred from a successful historical run."""
    errors = []
    packet = packet if isinstance(packet, dict) else {}
    doc = _load_json(repo_root / CONTRACTS_FILE)
    contracts = doc.get("contracts", []) if isinstance(doc, dict) else []
    contracts = contracts if isinstance(contracts, list) else []
    contract = next((c for c in contracts if isinstance(c, dict) and c.get("id") == lane_id), {})
    try:
        reviewed = (bool(contract) and contract.get("status") == "REVIEWED"
                    and not validate_contract(contract) and not unknown_fields(contract))
    except (AttributeError, TypeError, ValueError):
        reviewed = False
    if not reviewed:
        errors.append("NOT_MEASURED: reviewed contract with no UNKNOWN fields required")
    baseline = contract.get("baseline") or {}
    baseline = baseline if isinstance(baseline, dict) else {}
    freshness = baseline.get("freshness_degraded_after_h")
    timeout = baseline.get("timeout_s")
    if not _positive_number(freshness) or not _positive_number(timeout):
        errors.append("NOT_MEASURED: reviewed freshness_degraded_after_h and timeout_s required")
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        errors.append("NOT_MEASURED: exact --expected-sha required")
    elif packet.get("tested_sha") != expected_sha or packet.get("deployed_sha") != expected_sha:
        errors.append("DRIFT: tested/deployed SHA differs from expected integrated head")
    fixed = _timestamp(packet.get("fixes_deployed_at"))
    observed = _timestamp(packet.get("observed_at"))
    if fixed is None or observed is None or not fixed <= observed <= now:
        errors.append("NOT_MEASURED: ordered, timezone-aware fixes_deployed_at/observed_at required")
    elif _positive_number(freshness) and (now - observed).total_seconds() > freshness * 3600:
        errors.append("STALE: acceptance observation exceeds reviewed freshness")
    return {"sha": expected_sha, "fixed": fixed, "observed": observed, "freshness": freshness,
            "timeout": timeout, "contract": contract}, errors


def _current_receipt(row: dict, ctx: dict, now: datetime, time_key="finished_at") -> bool:
    finished = _timestamp(row.get(time_key))
    return (row.get("code_sha") == ctx["sha"] and finished is not None
            and ctx["fixed"] <= finished <= ctx["observed"] <= now
            and (now - finished).total_seconds() <= ctx["freshness"] * 3600)


def _correlate(state_root: Path, lane: dict, receipt: dict, observation: dict, ctx: dict, now: datetime) -> str | None:
    """Join a host receipt, ledger row, n8n trigger observation and independent effect inspection."""
    if not _run_ok(receipt) or not _current_receipt(receipt, ctx, now):
        return "receipt failed, stale, pre-fix or wrong SHA"
    if not isinstance(receipt.get("run_id"), str) or not receipt["run_id"]:
        return "NOT_MEASURED: run identity required"
    started, finished = _timestamp(receipt.get("started_at")), _timestamp(receipt.get("finished_at"))
    duration = receipt.get("duration_s")
    if (started is None or finished is None or not ctx["fixed"] <= started <= finished
            or (finished - started).total_seconds() > ctx["timeout"]
            or type(duration) not in (int, float) or not math.isfinite(duration) or not 0 <= duration <= ctx["timeout"]):
        return "receipt timing/timeout not proven"
    ledger = observation.get("ledger_run") or {}
    execution = observation.get("n8n_execution") or {}
    if not isinstance(ledger, dict) or not isinstance(execution, dict):
        return "NOT_MEASURED: ledger/n8n correlation required"
    for key in ("run_id", "lane_id", "mode", "state", "exit_code"):
        if ledger.get(key) != receipt.get(key):
            return f"DRIFT: ledger/receipt {key} mismatch"
    requested = _timestamp(ledger.get("requested_at"))
    ledger_started, ledger_finished = _timestamp(ledger.get("started_at")), _timestamp(ledger.get("finished_at"))
    if (requested is None or ledger_started is None or ledger_finished is None
            or not ctx["fixed"] <= requested <= ledger_started <= started <= finished <= ledger_finished <= ctx["observed"]
            or ledger.get("caller_id") != "n8n-relay"):
        return "NOT_MEASURED: n8n-relay request timing required"
    if (execution.get("run_id") != receipt.get("run_id")
            or not isinstance(execution.get("execution_id"), str) or not execution["execution_id"]
            or not ctx["contract"].get("workflow_id")
            or execution.get("workflow_id") != ctx["contract"].get("workflow_id")):
        return "NOT_MEASURED: matching n8n execution/workflow/run required"
    n_started, n_finished = _timestamp(execution.get("started_at")), _timestamp(execution.get("finished_at"))
    # A request workflow can finish before the host worker; do not infer business completion from its status.
    if n_started is None or n_finished is None or not ctx["fixed"] <= n_started <= requested <= n_finished <= ctx["observed"]:
        return "NOT_MEASURED: n8n trigger/request correlation required"
    klass = observation.get("evidence_class")
    natural = klass in {"NATURAL_SHADOW", "NATURAL_CANARY", "NATURAL_POST_CUTOVER"}
    if execution.get("trigger_kind") != ("schedule" if natural else "manual"):
        return "DRIFT: manual/event fire cannot substitute for a natural schedule"
    if natural:
        slot_key = ledger.get("slot_key")
        key = parse_key(slot_key) if isinstance(slot_key, str) else None
        if (key is None or key[0] != "d" or key[1:3] != (lane["lane_id"], receipt["mode"])
                or key[4] != 1 or ledger.get("slot_key") != receipt.get("slot_key")):
            return "NOT_MEASURED: distinct first-attempt natural schedule slot required"
        row = _lane_row(_load_json(state_root / REGISTRY_FILE), lane["lane_id"]) or {}
        dispatch = row.get("dispatch") or {}
        if not isinstance(dispatch, dict):
            return "NOT_MEASURED: schedule declaration malformed"
        try:
            tz = dispatch.get("tz") or "America/New_York"
            local = requested.astimezone(ZoneInfo(tz))
            schedules = dispatch.get("cron") or lane["cron"]
            schedules = [schedules] if isinstance(schedules, str) else schedules
            fires = [last_fire_at_or_before(expr, requested, tz=tz) for expr in schedules]
        except (ValueError, TypeError, KeyError):
            return "NOT_MEASURED: valid schedule/timezone required"
        if key[3] != local.strftime("%Y%m%dT%H%M"):
            return "DRIFT: request is outside its natural slot"
        if not any(fire is not None and fire.at == local.replace(second=0, microsecond=0) for fire in fires):
            return "DRIFT: slot is outside the declared schedule"
    lock = receipt.get("lock") or {}
    legacy_lock = observation.get("legacy_lock")
    if not isinstance(lock, dict) or not isinstance(legacy_lock, str) or not legacy_lock:
        return "NOT_MEASURED: legacy lock identity required"
    if receipt["mode"] == "dry_run":
        if (observation.get("legacy_authoritative") is not True or lock.get("scope") != "dryrun"
                or lock.get("path") != legacy_lock + ".dryrun"):
            return "DRIFT: shadow must preserve legacy authority and use a disjoint dryrun lock"
        if ("output_signal_mtime_before" not in receipt or "output_signal_mtime_after" not in receipt
                or receipt["output_signal_mtime_before"] != receipt["output_signal_mtime_after"]):
            return "DRIFT: shadow output signal changed or was not observed"
    elif lock.get("scope") != "live" or lock.get("path") != legacy_lock:
        return "DRIFT: live canary must use the legacy lock"
    elif klass in {"NATURAL_CANARY", "MANUAL_CANARY"} and observation.get("legacy_authoritative") is not True:
        return "NOT_MEASURED: legacy authority during canary required"
    proof = _proof_file(state_root, observation.get("effect_proof_ref"))
    if (not proof or proof.get("run_id") != receipt["run_id"] or proof.get("lane_id") != lane["lane_id"]
            or not _current_receipt(proof, ctx, now, "observed_at")
            or _timestamp(proof.get("observed_at")) < finished):
        return "NOT_MEASURED: current per-run business-effect inspection required; a lock is insufficient"
    count = proof.get("business_effect_count")
    duplicates = proof.get("duplicate_effect_count")
    if (type(count) is not int or count < 0 or type(duplicates) is not int or duplicates != 0
            or (receipt["mode"] == "dry_run" and count != 0)
            or proof.get("output_matches_contract") is not True or proof.get("consumer_correct") is not True):
        return "DRIFT: business effects, duplicate effects, output or consumer check failed"
    return None


def accepted_runs(state_root: Path, lane: dict, runs: dict, packet, ctx: dict, errors: list[str], now: datetime):
    accepted = {k: [] for k in ("NATURAL_SHADOW", "NATURAL_CANARY", "MANUAL_CANARY", "NATURAL_POST_CUTOVER")}
    rejected = {k: [] for k in accepted}
    if errors:
        return accepted, rejected
    by_id: dict[str, list[dict]] = {}
    for rows in runs.values():
        for row in rows:
            by_id.setdefault(str(row.get("run_id") or ""), []).append(row)
    evidence = _lane_row(packet, lane["lane_id"]) or {}
    observations = evidence.get("runs") or []
    executions: dict[str, str] = {}
    accepted_ids: dict[str, str] = {}
    for observation in observations if isinstance(observations, list) else []:
        if (not isinstance(observation, dict) or not isinstance(observation.get("evidence_class"), str)
                or observation["evidence_class"] not in accepted):
            continue
        klass = observation["evidence_class"]
        receipts = by_id.get(str(observation.get("run_id") or ""), [])
        canonical = [{k: v for k, v in row.items() if k != "_file"} for row in receipts]
        reason = "NOT_MEASURED: matching host receipt required"
        if receipts and all(row == canonical[0] for row in canonical):
            row = receipts[0]
            expected_mode = "dry_run" if klass == "NATURAL_SHADOW" else "live"
            reason = "DRIFT: evidence class/mode mismatch" if row.get("mode") != expected_mode else _correlate(
                state_root, lane, row, observation, ctx, now)
            if reason is None:
                execution_id = observation["n8n_execution"]["execution_id"]
                previous = executions.setdefault(execution_id, row["run_id"])
                if previous != row["run_id"]:
                    reason = "DRIFT: one n8n execution cannot prove two fires of the same lane"
                elif row["run_id"] in accepted_ids and accepted_ids[row["run_id"]] != klass:
                    reason = "DRIFT: conflicting evidence classes for one run"
                elif row["run_id"] not in accepted_ids:
                    accepted_ids[row["run_id"]] = klass
                    accepted[klass].append(row)
        elif receipts:
            reason = "DRIFT: conflicting copies of one receipt"
        if reason:
            rejected[klass].append(reason)
    return accepted, rejected


def _action(receipt: dict) -> str:
    return str(receipt.get("action") or receipt.get("operation") or receipt.get("kind") or "").lower()


def registry_kind(state_root: Path, lane_id: str) -> str | None:
    obj = _load_json(state_root / REGISTRY_FILE)
    rows = obj.get("lanes") if isinstance(obj, dict) else obj
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and row.get("lane_id") == lane_id:
            sched = row.get("scheduler") or {}
            return str(sched.get("kind")) if isinstance(sched, dict) else None
    return None


def _lane_row(obj, lane_id: str) -> dict | None:
    """Find a per-lane row in a verdict/board file of unknown exact shape."""
    if not isinstance(obj, dict):
        return None
    for key in ("lanes", "rows", "verdicts", "board"):
        rows = obj.get(key)
        if isinstance(rows, dict) and isinstance(rows.get(lane_id), dict):
            return rows[lane_id]
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get("lane_id") == lane_id:
                    return row
    if isinstance(obj.get(lane_id), dict):
        return obj[lane_id]
    return None


def readiness_verdict(state_root: Path, lane_id: str) -> str | None:
    row = _lane_row(_load_json(state_root / READINESS_FILE), lane_id)
    if not row:
        return None
    return str(row.get("verdict") or row.get("readiness") or row.get("status") or "") or None


def board_row(state_root: Path, lane_id: str) -> dict | None:
    return _lane_row(_load_json(state_root / BOARD_FILE), lane_id)


def workflow_files_present(repo_root: Path, lane_id: str) -> tuple[bool, str]:
    idx = _load_json(repo_root / WORKFLOW_INDEX)
    if not isinstance(idx, dict):
        return False, f"{WORKFLOW_INDEX} absent"
    for row in idx.get("lanes") or []:
        if row.get("lane_id") == lane_id:
            base = (repo_root / WORKFLOW_INDEX).parent
            both = (base / row["shadow_file"]).exists() and (base / row["live_file"]).exists()
            return both, f"{row['shadow_file']} + {row['live_file']}"
    return False, "lane not in INDEX.json"


# ---------------------------------------------------------------------------
# checklist
# ---------------------------------------------------------------------------
def lane_items(state_root: Path, repo_root: Path, lane: dict, *, acceptance=None,
               expected_sha: str | None = None, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    lane_id = lane["lane_id"]
    runs = run_receipts(state_root, lane_id)
    ctx, errors = acceptance_context(repo_root, lane_id, acceptance, expected_sha, now)
    accepted, rejected = accepted_runs(state_root, lane, runs, acceptance, ctx, errors, now)
    dry = accepted["NATURAL_SHADOW"]
    slots = {r.get("slot_key") for r in dry}
    canary = accepted["NATURAL_CANARY"] + accepted["MANUAL_CANARY"]
    natural = accepted["NATURAL_POST_CUTOVER"]
    # A failed current live run cannot be concealed by selecting one successful canary.
    failed_live = [r for r in runs.get("live", []) if not errors and _current_receipt(r, ctx, now) and not _run_ok(r)]
    failed_dry = [r for r in runs.get("dry_run", []) if not errors and _current_receipt(r, ctx, now) and not _run_ok(r)]
    cuts = [r for r in cutover_receipts(state_root, lane_id) if not errors
            and _current_receipt(r, ctx, now, "at") and r.get("problems") == []]
    cut_dry = [r for r in cuts if _action(r) == "cutover" and _is_dry(r) and r.get("applied") is False]
    cut_apply = [r for r in cuts if _action(r) == "cutover" and not _is_dry(r) and r.get("applied") is True]
    rb_dry = [r for r in cuts if _action(r) == "rollback" and _is_dry(r) and r.get("applied") is False]
    rb_apply = [r for r in cuts if _action(r) == "rollback" and not _is_dry(r) and r.get("applied") is True]
    kind = registry_kind(state_root, lane_id)
    verdict = readiness_verdict(state_root, lane_id)
    board = board_row(state_root, lane_id)
    wf_ok, wf_detail = workflow_files_present(repo_root, lane_id)
    phase = str((board or {}).get("phase") or "").upper()
    rollback_ready = bool((board or {}).get("rollback_ready")) if board else False

    def ev(rows: list[dict]) -> str:
        return ", ".join(sorted({r["_file"] for r in rows})[:3]) if rows else "none"

    def detail(classes: tuple[str, ...], rows: list[dict]) -> str:
        reasons = errors + [s for klass in classes for s in rejected[klass]]
        count = len({r["run_id"] for r in rows})
        return (f"{count} correlated run(s): {ev(rows)}; " + "; ".join(sorted(set(reasons)))) if reasons else (
            f"{count} correlated run(s): {ev(rows)}" if rows else "NOT_MEASURED: correlated observations absent")

    return [
        {
            "step": "workflows",
            "label": "Workflow JSON present (shadow + live); source review is a separate requirement",
            "done": wf_ok,
            "evidence": wf_detail,
        },
        {
            "step": "registry_row",
            "label": "Lane registry row exists (kind cron/systemd before the flip)",
            "done": kind is not None,
            "evidence": f"scheduler.kind={kind}" if kind else f"no row in {REGISTRY_FILE}",
        },
        {
            "step": "shadow",
            "label": "Shadow: two natural fires after fixes, exact SHA, correlated n8n/ledger/host proof, zero business effects",
            "done": len(slots) >= 2 and not rejected["NATURAL_SHADOW"] and not errors and not failed_dry,
            "evidence": f"{len(slots)} distinct natural slot(s); " + detail(("NATURAL_SHADOW",), dry)
                        + f"; failed current shadow={len(failed_dry)}",
        },
        {
            "step": "canary",
            "label": "Canary: correlated live fire, legacy lock, outputs/consumers checked and no duplicate business effects",
            "done": bool(canary) and not failed_live and not errors
                    and not rejected["NATURAL_CANARY"] and not rejected["MANUAL_CANARY"],
            "evidence": detail(("NATURAL_CANARY", "MANUAL_CANARY"), canary)
                        + f"; MANUAL_CANARY={len(accepted['MANUAL_CANARY'])}; failed current live={len(failed_live)}",
        },
        {
            "step": "readiness",
            "label": "Recorded readiness verdict READY (release acceptance remains separate)",
            "done": (verdict or "").upper() in {"READY", "GO", "GREEN", "PASS"},
            "evidence": f"verdict={verdict}" if verdict else f"{READINESS_FILE} absent or no row",
        },
        {
            "step": "cutover_dry",
            "label": "Cutover dry-run receipt (_cutover.py --lane <id>, default dry-run)",
            "done": bool(cut_dry),
            "evidence": ev(cut_dry) if cut_dry else f"none in {CUTOVER_DIR}",
        },
        {
            "step": "cutover_apply",
            "label": "Recorded cutover applied at current SHA (operator grant and scheduler verification remain required)",
            "done": bool(cut_apply),
            "evidence": ev(cut_apply) if cut_apply else f"none in {CUTOVER_DIR}",
        },
        {
            "step": "registry_n8n",
            "label": "Registry row scheduler.kind=n8n (live scheduler drift check remains required)",
            "done": kind == "n8n",
            "evidence": f"scheduler.kind={kind}",
        },
        {
            "step": "rollback_dry",
            "label": "Rollback proven in dry-run (_cutover.py rollback --lane <id>)",
            "done": bool(rb_dry),
            "evidence": ev(rb_dry) if rb_dry else f"none in {CUTOVER_DIR}",
        },
        {
            "step": "rollback_real",
            "label": "Rollback executed for real once (first lane of each tranche) and re-cut",
            "done": bool(rb_apply),
            "evidence": ev(rb_apply) if rb_apply else "none (required for the first lane of the tranche only)",
        },
        {
            "step": "board",
            "label": "Recorded migration board phase CUTOVER, rollback_ready true (production acceptance remains separate)",
            "done": phase in {"CUTOVER", "DONE", "LIVE"} and rollback_ready,
            "evidence": f"phase={phase or '-'} rollback_ready={rollback_ready}"
            if board
            else f"{BOARD_FILE} absent or no row",
        },
        {
            "step": "natural_fire",
            "label": "Post-cutover natural fire: correlated schedule, current SHA, fresh output/consumer and duplicate checks",
            "done": bool(natural) and kind == "n8n" and not errors
                    and not rejected["NATURAL_POST_CUTOVER"] and not failed_live
                    and all(any(_timestamp(c["at"]) <= _timestamp(r["started_at"]) for c in cut_apply) for r in natural),
            "evidence": detail(("NATURAL_POST_CUTOVER",), natural),
        },
    ]


def render(state_root: Path, repo_root: Path, lanes: list[dict], title: str, *, acceptance=None,
           expected_sha: str | None = None, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    lines = [
        f"# n8n cutover checklist — {title}",
        "",
        f"Rendered {now.isoformat()} by `scripts/n8n_cutover_checklist.py` from receipts under `{state_root}`.",
        "A ticked box is backed by a file named on the line; an unticked box names what is missing.",
        "Ticks are evidence, not approval: the cron-write grant and the activation clicks stay with the operator.",
        "NOT_MEASURED is not zero. A checklist count is not production readiness or cutover approval.",
        "",
    ]
    totals = [0, 0]
    for lane in lanes:
        items = lane_items(state_root, repo_root, lane, acceptance=acceptance, expected_sha=expected_sha, now=now)
        done = sum(1 for i in items if i["done"])
        totals[0] += done
        totals[1] += len(items)
        lines.append(f"## {lane['lane_id']}  ({lane['tranche']}, {done}/{len(items)})")
        lines.append("")
        lines.append(f"- schedule: `{' | '.join(lane['cron'])}` — {lane['fidelity']} — {lane['source']}")
        if lane.get("note"):
            lines.append(f"- note: {lane['note']}")
        lines.append("")
        for item in items:
            box = "x" if item["done"] else " "
            lines.append(f"- [{box}] {item['label']}  \n      evidence: {item['evidence']}")
        lines.append("")
    lines.append(f"**Total: {totals[0]}/{totals[1]} boxes ticked across {len(lanes)} lane(s).**")
    lines.append("")
    lines.append(
        "Rollback triggers (plan 2026-10-08): RUN_FAILED where the last 3 cron runs succeeded; output_signal "
        "older than 2x cadence after cutover; CRON_PRESENT_WHILE_SCHEDULER_N8N; relay bearer failures; "
        "n8n healthz down > 10 min; any REFUSED run row. Rollback = `_cutover.py rollback --lane <id> --apply` "
        "+ deactivate the workflow; target < 5 min."
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--lane", help="one lane id from the generator table")
    g.add_argument("--tranche", choices=TRANCHES)
    ap.add_argument("--state-root", default=os.environ.get("TRADEAI_STATE_ROOT") or str(ROOT))
    ap.add_argument("--repo-root", default=str(ROOT))
    ap.add_argument("--expected-sha", help="full integrated head SHA required for acceptance ticks")
    ap.add_argument("--acceptance-evidence", type=Path, help="read-only correlated observations JSON packet")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    if a.lane:
        lanes = [lane for lane in LANES if lane["lane_id"] == a.lane]
        if not lanes:
            print(f"unknown lane {a.lane!r}; known: {[lane['lane_id'] for lane in LANES]}", file=sys.stderr)
            return 2
        title, slug = a.lane, a.lane
    else:
        lanes = [lane for lane in LANES if lane["tranche"] == a.tranche]
        title, slug = f"tranche {a.tranche}", a.tranche
    acceptance = (_load_json(a.acceptance_evidence) if a.acceptance_evidence
                  and a.acceptance_evidence.suffix == ".json" else None)
    text = render(Path(a.state_root), Path(a.repo_root), lanes, title,
                  acceptance=acceptance, expected_sha=a.expected_sha)
    if a.write:
        out = Path(a.state_root) / OUT_DIR / f"n8n_cutover_checklist_{slug}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(json.dumps({"schema": SCHEMA, "wrote": str(out), "lanes": len(lanes)}))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
