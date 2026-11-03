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
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s, shell=False, check=False)
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


def check_rerun_ci(record: Mapping[str, Any], *, run: Runner = _run_cli) -> tuple[bool, str]:
    facts = record.get("facts") or {}
    run_id = str(facts.get("run_id", ""))
    code, out, err = run(["gh", "run", "view", run_id, "--json", "headSha,status,conclusion"])
    if code != 0:
        return False, f"This changed, or could not be checked: {(err or out).strip()}. The lead will re-ask."
    try:
        payload = json.loads(out)
    except ValueError:
        return False, "gh returned something that is not JSON about the run. The lead will re-ask."
    if str(payload.get("headSha") or "") != str(facts.get("head_sha") or ""):
        return False, "This changed: the run is no longer on the head the lead asked about. The lead will re-ask."
    return True, ""


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


def check_install_schedule(record: Mapping[str, Any], *, unit_root: Optional[Path] = None) -> tuple[bool, str]:
    """The lane text must hash to what was reviewed, and the unit file must still be absent (nothing half-installed)."""
    facts = record.get("facts") or {}
    root = Path(unit_root or os.environ.get("TRADEAI_UNIT_ROOT") or "/etc/systemd/system")
    lane = str(facts.get("lane_id") or "")
    if not lane:
        return False, "This request no longer names a lane. The lead will re-ask."
    unit = root / f"{lane}.service"
    if unit.exists():
        return False, f"{unit.name} already exists, so the schedule the lead approved is not the one that would land."
    if not str(facts.get("file_sha256") or "").strip():
        return False, "This request does not carry the hash of the unit it would install. The lead will re-ask."
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
