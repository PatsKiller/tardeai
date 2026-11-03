#!/usr/bin/env python3
"""home_approvals_adapters.py — read-only fact checks for the Home v008 action types.

Each adapter answers one question at click time: *is what this request promised still true?* Nothing here decides,
executes, merges, grants, stops, installs or restores anything. Execution stays behind the approved executor seam in
``home_approvals.py`` and its own reviewed wiring; this module is the part that can safely run on every render and every
click.

Every adapter takes an injected ``run`` callable so the checks are testable without a network, a DB or a live process:

    run(argv: list[str]) -> tuple[int, str, str]      # exit code, stdout, stderr

The defaults use ``subprocess`` with a timeout and no shell. A check that cannot be performed returns
``(False, plain-English reason)`` — fail-closed, never a silent pass.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Optional

from lib import home_approvals as ha

Runner = Callable[[list[str]], tuple[int, str, str]]


def _run_cli(argv: list[str], *, timeout_s: float = 30.0) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s, shell=False,  # noqa: S603
                              check=False)  # fixed argv built here (gh + numeric/JSON args), no shell, no user text
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", f"{argv[0]} is not installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"{argv[0]} did not answer within {timeout_s:.0f}s"


def _gh_pr_head(run: Runner, pr: int) -> tuple[Optional[dict[str, Any]], str]:
    code, out, err = run(["gh", "pr", "view", str(pr), "--json", "headRefOid,state,number"])
    if code != 0:
        return None, (err or out or "gh could not read the PR").strip()
    try:
        payload = json.loads(out)
    except ValueError:
        return None, "gh returned something that is not JSON"
    return payload, ""


def check_merge_pr(record: Mapping[str, Any], *, run: Runner = _run_cli) -> tuple[bool, str]:
    facts = record.get("facts") or {}
    payload, why = _gh_pr_head(run, int(facts.get("pr", 0)))
    if payload is None:
        return False, f"This changed, or could not be checked: {why}. The lead will re-ask."
    state = str(payload.get("state") or "").upper()
    if state != "OPEN":
        return False, f"PR #{facts.get('pr')} is {state or 'not open'}, so there is nothing to merge. The lead will re-ask."
    if str(payload.get("headRefOid") or "") != str(facts.get("head_sha") or ""):
        return False, "This changed: the PR head moved since the lead asked. The lead will re-ask."
    return True, ""


def check_policy_approval(record: Mapping[str, Any], *, run: Runner = _run_cli) -> tuple[bool, str]:
    ok, plain = check_merge_pr(record, run=run)
    if not ok:
        return ok, plain
    if not str((record.get("facts") or {}).get("policy_version") or "").strip():
        return True, ""  # policy_version is optional; the exact head is the binding fact
    return True, ""


def check_rerun_ci(record: Mapping[str, Any], *, run: Runner = _run_cli,
                   rerun_state: Optional[Path] = None) -> tuple[bool, str]:
    """The run must still be on the approved head, the named jobs must still be failed, and it may be re-run once.

    The operator's standing order is exactly one automatic re-run per failing head per check; a request that would be a
    second re-run is refused here rather than discovered by the lane.
    """
    facts = record.get("facts") or {}
    run_id = str(facts.get("run_id", ""))
    code, out, err = run(["gh", "run", "view", run_id, "--json", "headSha,status,conclusion,jobs"])
    if code != 0:
        return False, f"This changed, or could not be checked: {(err or out).strip()}. The lead will re-ask."
    try:
        payload = json.loads(out)
    except ValueError:
        return False, "gh returned something that is not JSON about the run. The lead will re-ask."
    if str(payload.get("headSha") or "") != str(facts.get("head_sha") or ""):
        return False, "This changed: the run is no longer on the head the lead asked about. The lead will re-ask."
    wanted = [str(job) for job in (facts.get("failed_job_ids") or []) if str(job).strip()]
    if not wanted:
        return False, ("This request does not name the failed jobs it would re-run, so nothing will be re-run. The lead "
                       "will re-ask.")
    if wanted:
        jobs = {str(job.get("databaseId")): job for job in (payload.get("jobs") or []) if isinstance(job, dict)}
        for job_id in wanted:
            job = jobs.get(job_id)
            if job is None:
                return False, f"Job {job_id} is no longer part of run {run_id}. The lead will re-ask."
            if str(job.get("conclusion") or "") != "failure":
                return False, (f"Job {job_id} is {job.get('conclusion') or 'not failed'}, so re-running it is not what "
                               f"the lead approved. The lead will re-ask.")
    if rerun_state is not None:
        state, error = _load_reruns(Path(rerun_state))
        if error:
            return False, (f"The re-run history could not be read ({error}), so the one-re-run rule cannot be proven. "
                           f"The lead will re-ask.")
        already = int(state.get(str(facts.get("head_sha") or ""), 0))
        if already >= 1:
            return False, ("This head has already been re-run once; a second automatic re-run is not allowed. Fix the "
                           "failure instead.")
    return True, ""


def _load_reruns(path: Path) -> tuple[dict[str, int], str]:
    """Read the one-re-run-per-head ledger. A missing file is zero runs; a corrupt one is an error, never zero."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, ""
    except OSError as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    try:
        data = json.loads(text)
        return {str(k): int(v) for k, v in (data or {}).items()}, ""
    except (ValueError, TypeError) as exc:
        return {}, f"corrupt re-run history: {exc}"


def record_rerun(path: Path, head_sha: str) -> None:
    """Count a consumed re-run for a head. Called by the execute adapter after the re-run is issued."""
    path.parent.mkdir(parents=True, exist_ok=True)
    state, _error = _load_reruns(path)
    state[str(head_sha)] = state.get(str(head_sha), 0) + 1
    path.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def check_stop_job(record: Mapping[str, Any], *, proc_root: Path = Path("/proc")) -> tuple[bool, str]:
    """A pid must still be that same process: same pid, same start time, same command hash."""
    facts = record.get("facts") or {}
    pid = str(facts.get("pid", ""))
    stat_path = Path(proc_root) / pid / "stat"
    try:
        stat = stat_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False, f"Process {pid} is no longer running, so there is nothing to stop. The lead will re-ask."
    # /proc/<pid>/stat: the command is in parentheses and may contain spaces; starttime is field 22 overall.
    try:
        tail = stat.rsplit(")", 1)[1].split()
        start_time = tail[19]
    except (IndexError, ValueError):
        return False, f"Process {pid} could not be read safely, so nothing will be stopped."
    if str(start_time) != str(facts.get("start_time_epoch", "")):
        return False, (f"Process {pid} was restarted since the lead asked (its start time changed), so this is no "
                       f"longer the process he approved. The lead will re-ask.")
    cmd_path = Path(proc_root) / pid / "cmdline"
    try:
        cmd = cmd_path.read_bytes()
    except OSError:
        return False, f"The command of process {pid} could not be read, so nothing will be stopped."
    if hashlib.sha256(cmd).hexdigest() != str(facts.get("cmd_sha256", "")):
        return False, (f"Process {pid} is now running a different command than the one shown when the lead asked. "
                       f"The lead will re-ask.")
    return True, ""


def check_install_schedule(record: Mapping[str, Any], *, unit_root: Optional[Path] = None,
                           registry_path: Optional[Path] = None,
                           source_root: Optional[Path] = None) -> tuple[bool, str]:
    """Three facts must still hold: the unit is absent, the schedule is the registry's, and the reviewed text is intact."""
    facts = record.get("facts") or {}
    root = Path(unit_root or os.environ.get("TRADEAI_UNIT_ROOT") or "/etc/systemd/system")
    lane = str(facts.get("lane_id") or "")
    if not lane:
        return False, "This request no longer names a lane. The lead will re-ask."
    unit = root / f"{lane}.service"
    if unit.exists():
        return False, f"{unit.name} already exists, so the schedule the lead approved is not the one that would land."
    wanted_sha = str(facts.get("file_sha256") or "").strip()
    if not wanted_sha:
        return False, "This request does not carry the hash of the unit it would install. The lead will re-ask."

    registry = Path(registry_path or os.environ.get("TRADEAI_LANE_REGISTRY") or "config/lane_registry.json")
    try:
        lanes = json.loads(registry.read_text(encoding="utf-8")).get("lanes") or []
    except (OSError, ValueError, AttributeError):
        return False, ("The lane registry could not be read, so there is no way to prove the schedule is the reviewed "
                       "one. The lead will re-ask.")
    match = next((row for row in lanes if isinstance(row, dict) and str(row.get("lane_id")) == lane), None)
    if match is None:
        return False, f"Lane {lane} is not in the lane registry, so it is not a schedule the lead can approve."
    expression = str((match.get("scheduler") or {}).get("expression") or "")
    if expression != str(facts.get("schedule_expression") or ""):
        return False, (f"Lane {lane}'s registered schedule is “{expression or '(none)'}”, not the one shown on the "
                       f"card. The lead will re-ask.")

    source = facts.get("source_path")
    if not source:
        return False, ("This request does not name the reviewed unit file, so its text cannot be proven unchanged. "
                       "The lead will re-ask.")
    base = Path(os.path.realpath(source_root or os.environ.get("TRADEAI_REPO_ROOT") or "."))
    candidate = Path(os.path.realpath(str(base / str(source))))
    if not candidate.is_relative_to(base):
        return False, ("The reviewed unit file is outside the repository it must live in, so nothing will be "
                       "installed. The lead will re-ask.")
    if candidate.is_symlink() or not candidate.is_file():
        return False, "The reviewed unit file is not a plain file inside the repository, so nothing will be installed."
    try:
        actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
    except OSError:
        return False, "The reviewed unit file could not be read, so nothing will be installed. The lead will re-ask."
    if actual != wanted_sha:
        return False, "The unit text changed since it was reviewed, so it is not the schedule the lead approved."
    return True, ""


def check_restore_store(record: Mapping[str, Any], *, packet_root: Optional[Path] = None) -> tuple[bool, str]:
    facts = record.get("facts") or {}
    wanted = str(facts.get("packet_sha256") or "")
    if not wanted:
        return False, "This request does not carry the restore packet's hash. The lead will re-ask."
    root = Path(packet_root or os.environ.get("TRADEAI_RESTORE_PACKET_ROOT") or ".")
    matches = []
    for path in root.glob("*.packet*"):
        try:
            if hashlib.sha256(path.read_bytes()).hexdigest() == wanted:
                matches.append(path)
        except OSError:
            continue
    if len(matches) != 1:
        return False, ("The restore packet the lead approved is not present exactly once, so nothing will be "
                       "restored. The lead will re-ask.")
    return True, ""


def check_grant(record: Mapping[str, Any], *, grants_root: Optional[Path] = None) -> tuple[bool, str]:
    """A grant request must name a grant that does not already exist, or it would silently re-issue one."""
    facts = record.get("facts") or {}
    grant_id = str(facts.get("grant_id") or "").strip()
    if not grant_id:
        return False, "This request does not name the grant it would issue. The lead will re-ask."
    root = Path(grants_root or os.environ.get("TRADEAI_GRANTS_ROOT") or ".")
    if root.is_dir() and (root / f"{grant_id}.json").exists():
        return False, f"Grant {grant_id} already exists, so approving this would not do what the card says."
    return True, ""


CHECKS: dict[str, Callable[..., tuple[bool, str]]] = {
    "merge_pr": check_merge_pr,
    "rerun_ci": check_rerun_ci,
    "grant": check_grant,
    "stop_job": check_stop_job,
    "install_schedule": check_install_schedule,
    "restore_store": check_restore_store,
    "policy_approval": check_policy_approval,
}


def make_executor(kind: str, *, execute_fn: Optional[Callable[..., dict[str, Any]]] = None, **check_kwargs: Any
                  ) -> ha.CallbackExecutor:
    """Build a CallbackExecutor whose revalidate half is this module's read-only check.

    ``execute_fn`` is left to the caller on purpose: performing a merge, a grant, a stop, an install or a restore needs
    its own reviewed wiring. Without it the adapter is check-only and ``execute`` fails closed, so a click can never
    half-run an action through this path by accident.
    """
    check = CHECKS.get(kind)
    if check is None:
        raise ha.Refused("unknown_action_type", f"“{kind}” has no adapter.")

    def _revalidate(record: Mapping[str, Any]) -> tuple[bool, str]:
        return check(record, **check_kwargs)

    def _execute(record: Mapping[str, Any], actor: str, progress: Any) -> dict[str, Any]:
        if execute_fn is None:
            progress.reached("execute_refused_no_wiring")
            raise ha.Refused("no_executor",
                             "The check passed, but this action has no reviewed wiring yet, so nothing was done.")
        progress.reached("execute_started")
        result = execute_fn(record, actor, progress)
        progress.reached("execute_returned")
        return result

    return ha.CallbackExecutor(_revalidate, _execute)


def register_read_only(kind: str, **check_kwargs: Any) -> None:
    """Register an adapter that can CHECK but never acts. Safe for every type; leaves execute fail-closed."""
    ha.register_executor(kind, make_executor(kind, **check_kwargs))
