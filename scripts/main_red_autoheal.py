#!/usr/bin/env python3
"""Main-red self-heal — a PROPOSED host lane (plan item 4, 2026-11-02).

What it does, once per scheduled run:

1. Reads the newest ``origin/main`` run of every *required* workflow (GitHub Actions).
2. If the run on the current tip is red, re-runs its failed jobs ONCE
   (``gh run rerun <id> --failed``) — but only for the failure classes the config
   allows.
3. A green re-run records the failure as a suspected flake (the plan's case C: one
   flaky test blocked the deploy poller until a human re-ran it).
4. A run that stays red escalates exactly once: one P1 Telegram page and one durable
   Claude Code fixer request (``fixer_requests/<run id>.json``) carrying the failing
   test ids and the run URL.

AGENTS.md wins over the plan. §24.5 forbids a scheduled job from writing to a remote,
and §28.14 limits the monitor's rerun to an *infrastructure* flake, "never a test
failure". The shipped config therefore re-runs infrastructure failures only; a failed
log that names test ids escalates on the first cycle instead of being re-run. Opening
a flaky-test issue is off by default for the same reason. Every remote write is behind
a config gate whose default honours those rules; turning one on is an operator
decision, not an agent's.

Idempotent per (run id, attempt): the durable state file is the only thing that decides
whether a run has already been re-run, paged or handed to a fixer. ``--dry-run`` is the
default; ``--apply`` is needed to act.

PROPOSED — NOT INSTALLED. There is no timer, cron line or n8n workflow for this lane.
Installing one is operator-only (AGENTS.md §17). Activation was approved by the operator
in-session 2026-11-01, conditional on the PR merging with every check green, an
independent ``MERGE`` review, and a quoted dry-run receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

CONFIG_SCHEMA = "MainRedAutohealConfig@v1"
STATE_SCHEMA = "MainRedAutohealState@v1"
RECEIPT_SCHEMA = "MainRedAutohealReceipt@v1"
FIXER_REQUEST_SCHEMA = "MainRedAutohealFixerRequest@v1"

#: Every action a decision may name. Nothing outside this set can be returned (tested exhaustively).
ACTION_NOOP = "noop"
ACTION_RERUN = "rerun"
ACTION_FLAKE_RECORDED = "flake_recorded"
ACTION_PAGE_AND_DISPATCH = "page_and_dispatch"
DECISIONS = frozenset({ACTION_NOOP, ACTION_RERUN, ACTION_FLAKE_RECORDED, ACTION_PAGE_AND_DISPATCH})

#: Conclusion values that mean "this run is red".
FAILED_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})
#: Events a main-branch run may carry. A pull_request run is never this lane's business.
MAIN_EVENTS = frozenset({"push", "workflow_dispatch", "schedule"})
#: A run that failed without a test id and without an infra marker.
CLASS_INFRASTRUCTURE = "infrastructure"
CLASS_TEST_FAILURE = "test_failure"
CLASS_UNKNOWN = "unknown"

#: Real `gh run view --log-failed` lines are "job<TAB>step<TAB><timestamp> FAILED tests/x.py::test".
#: The earlier patterns anchored on ^FAILED, so a live log matched nothing and no test id was found.
_TEST_ID_PATTERNS = (
    re.compile(r"\bFAILED\s+(\S+::\S+)"),
    re.compile(r"\b(\S+\.py::\S+)\s+FAILED\b"),
    re.compile(r"\bERROR\s+(\S+::\S+)"),
)
#: Any of these in a failed log means pytest ran and a test failed, whatever infra markers also appear.
PYTEST_FAILURE_SIGNATURES = (
    "short test summary info",
    "assertionerror",
    "error during collection",
    "exit after collection",
    "no tests ran",
)


# --------------------------------------------------------------------------- helpers
def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def extract_test_ids(log_text: str) -> list[str]:
    """Pytest node ids named as failures in a job log, in first-seen order, deduped."""
    seen: list[str] = []
    for line in (log_text or "").splitlines():
        for pattern in _TEST_ID_PATTERNS:
            match = pattern.search(line.strip())
            if match:
                test_id = match.group(1)
                if test_id not in seen:
                    seen.append(test_id)
                break
    return seen


def classify_failure(conclusion: str, log_text: str, infra_markers: list[str]) -> tuple[str, list[str]]:
    """Return (failure_class, failing_test_ids).

    A test id wins over every other signal: a test failure is never re-run under the
    shipped config (§28.14), so mis-classifying one as infrastructure would hide it.
    """
    test_ids = extract_test_ids(log_text)
    lowered = (log_text or "").lower()
    if test_ids:
        return CLASS_TEST_FAILURE, test_ids
    if any(sig in lowered for sig in PYTEST_FAILURE_SIGNATURES):
        # A 502/503 line or a step timeout inside a pytest step does not make a test failure infra.
        return CLASS_TEST_FAILURE, []
    if conclusion in {"startup_failure", "timed_out"}:
        return CLASS_INFRASTRUCTURE, []
    if any(marker.lower() in lowered for marker in infra_markers):
        return CLASS_INFRASTRUCTURE, []
    return CLASS_UNKNOWN, []


def newest_main_runs(runs: list[Mapping[str, Any]], required_workflows: list[str]) -> tuple[Optional[str], dict[str, Mapping[str, Any]]]:
    """The tip SHA and each required workflow's newest main run.

    ``tip`` is the head SHA of the newest main-branch run overall (any workflow), so a
    red run left behind by an older commit is never re-run after main moved on.
    """
    relevant = [r for r in runs if r.get("event") in MAIN_EVENTS and r.get("headSha")]
    if not relevant:
        return None, {}
    relevant.sort(key=lambda r: str(r.get("createdAt") or ""), reverse=True)
    tip = next((r["headSha"] for r in relevant if r.get("event") == "push"), relevant[0]["headSha"])
    newest: dict[str, Mapping[str, Any]] = {}
    for run in relevant:  # already newest-first
        workflow = str(run.get("workflowName") or "")
        if workflow in required_workflows and workflow not in newest:
            newest[workflow] = run
    return str(tip), newest


def _load_json(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text())
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, doc: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    tmp.replace(path)


def _append_jsonl(path: Path, doc: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, sort_keys=True) + "\n")


# --------------------------------------------------------------------------- cycle
def run_cycle(
    config: Mapping[str, Any],
    *,
    state_dir: Path,
    gh: Callable[[list[str]], tuple[int, str]],
    dry_run: bool = True,
    telegram: Optional[Callable[..., Any]] = None,
    issue_writer: Optional[Callable[..., str]] = None,
    now: Optional[str] = None,
) -> dict:
    """One scheduled cycle. Every side effect is injected or gated; returns the receipt."""
    started_at = now or _utcnow()
    repo = str(config["repo"])
    required = list(config.get("required_workflows") or [])
    state_path = state_dir / "state.json"
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA, "started_at": started_at, "dry_run": bool(dry_run),
        "repo": repo, "actions": [], "skipped": [],
    }
    state = _load_json(state_path)
    if state.get("schema") != STATE_SCHEMA:
        state = {"schema": STATE_SCHEMA, "runs": {}}
    runs_state: dict[str, dict] = state.setdefault("runs", {})
    # Operator standing order 2026-11-03: ONE re-run per failing HEAD per check group, so red is never
    # retried into green. The ledger is keyed (head SHA, check group) and survives run-id changes: a
    # second workflow in the same page group on the same head does not get its own retry.
    rerun_ledger: dict[str, dict] = state.setdefault("rerun_ledger", {})

    rc, out = gh(["run", "list", "--repo", repo, "--branch", str(config.get("branch", "main")),
                  "--limit", str(int(config["run_list_limit"])),
                  "--json", "databaseId,headSha,status,conclusion,workflowName,url,createdAt,event"])
    if rc != 0:
        receipt["error"] = f"gh run list rc={rc}: {(out or '')[:300]}"
        return _finish(receipt, state, state_dir, dry_run)
    try:
        runs = json.loads(out or "[]")
    except ValueError:
        receipt["error"] = "gh run list returned non-JSON"
        return _finish(receipt, state, state_dir, dry_run)

    tip, newest = newest_main_runs(runs, required)
    receipt["tip"] = (tip or "")[:12]
    if tip is None or not newest:
        receipt["skipped"].append({"reason": "no_required_main_run_red"})
        return _finish(receipt, state, state_dir, dry_run)

    infra_markers = list(config.get("infra_log_markers") or [])
    for workflow, run in sorted(newest.items()):
        run_id = str(run.get("databaseId"))
        run_key = f"{run_id}:{_run_attempt(config, gh, run_id, run)}"
        if str(run.get("headSha")) != tip:
            receipt["skipped"].append({"run_id": run_id, "workflow": workflow, "reason": "stale_commit"})
            continue
        if run.get("status") != "completed":
            receipt["skipped"].append({"run_id": run_id, "workflow": workflow, "reason": "not_completed"})
            continue
        if run.get("conclusion") not in FAILED_CONCLUSIONS:
            rec = runs_state.get(run_key) or {}
            if not (int(rec.get("attempts") or 0) > 0):
                # A re-run that turned green is a NEW attempt (id:2), so its own record has no
                # attempts: the flake belongs to the attempt that actually re-ran the run.
                rec = next((r for k, r in runs_state.items()
                            if k.startswith(f"{run_id}:") and int(r.get("attempts") or 0) > 0), {})
            if int(rec.get("attempts") or 0) > 0 and not rec.get("flake_recorded") and not rec.get("escalated"):
                # The re-run turned the run green: THIS is the flake receipt (it used to be skipped
                # as "green" before the flake was ever recorded).
                rec["flake_recorded"] = True
                rec["last_action"] = ACTION_FLAKE_RECORDED
                rec["updated_at"] = started_at
                fixer_path = None
                failing: list[str] = []
                if not dry_run and bool(config.get("fixer", {}).get("enabled", True)):
                    # ONE re-run passed -> FLAKY; open the deterministic fix task with the named test ids.
                    flog = _failed_log(config, gh, run_id)
                    failure_class, failing = classify_failure("failure", flog, infra_markers)
                    fixer_path, failing = _fix_request(
                        config, {"failure_class": failure_class, "failing_test_ids": failing},
                        run, run_id, workflow, state_dir, started_at,
                        why="suspected flake: the re-run passed; make the failing test deterministic",
                        log_tail=_log_tail(config, flog), run_key=run_key)
                    rec["fixer_request"] = str(fixer_path)
                receipt["actions"].append({"run_id": run_id, "workflow": workflow,
                                           "action": ACTION_FLAKE_RECORDED, "suspected_flake": True,
                                           "failing_test_ids": list(failing),
                                           "fixer_request": str(fixer_path) if fixer_path else None,
                                           "note": "the re-run passed; recorded as a suspected flake and a fix task was opened"})
            else:
                receipt["skipped"].append({"run_id": run_id, "workflow": workflow, "reason": "green"})
            continue
        prior_attempts = sum(1 for k in runs_state if k.startswith(f"{run_id}:")) - (1 if run_key in runs_state else 0)
        group = (config.get("page_groups") or {}).get(workflow) or workflow
        head_key = f"{tip}:{group}"
        action = _handle_red_run(
            config=config, run=run, run_id=run_id, workflow=workflow,
            record=runs_state.setdefault(run_key, {"attempts": 0, "escalated": False,
                                                   "flake_recorded": False, "head_sha": tip,
                                                   "run_id": run_id}),
            gh=gh, state_dir=state_dir, dry_run=dry_run, telegram=telegram,
            issue_writer=issue_writer, infra_markers=infra_markers, now=started_at,
            run_key=run_key, run_prior_attempts=max(prior_attempts, 0),
            head_key=head_key, rerun_ledger=rerun_ledger,
        )
        receipt["actions"].append(action)

    _prune(runs_state, int(config.get("state_keep_runs", 50)))
    return _finish(receipt, state, state_dir, dry_run)


def decide(*, attempts: int, max_reruns: int, escalated: bool, flake_recorded: bool,
           prior_rerun_outcome: Optional[str], failure_class: str, rerun_allowed: bool) -> str:
    """The ONE pure decision for a red run. Returns exactly one of ``DECISIONS``.

    ``prior_rerun_outcome`` is ``None`` (this run was never re-run), ``"success"``, ``"failure"`` or
    ``"in_progress"``. The caller owns every side effect; this function owns the choice, so an
    exhaustive test can prove no other action is reachable.
    """
    if flake_recorded or escalated:
        return ACTION_NOOP
    if int(attempts) > 0:
        if prior_rerun_outcome == "success":
            return ACTION_FLAKE_RECORDED
        if prior_rerun_outcome == "failure":
            return ACTION_PAGE_AND_DISPATCH
        return ACTION_NOOP
    if int(attempts) >= int(max_reruns):
        return ACTION_PAGE_AND_DISPATCH
    if rerun_allowed:
        return ACTION_RERUN
    return ACTION_PAGE_AND_DISPATCH


def _handle_red_run(*, config, run, run_id, workflow, record, gh, state_dir, dry_run,
                    telegram, issue_writer, infra_markers, now, run_key="", run_prior_attempts=0,
                    head_key="", rerun_ledger=None) -> dict:
    base = {"run_id": run_id, "workflow": workflow, "head_sha": str(run.get("headSha")),
            "run_url": run.get("url")}
    record["head_sha"] = str(run.get("headSha"))
    record["updated_at"] = now
    attempts = int(record.get("attempts") or 0)

    # Read what a prior re-run produced, then classify. Both are reads; the choice stays in decide().
    prior_outcome: Optional[str] = None
    view_conclusion: Optional[str] = None
    if attempts > 0 and not record.get("flake_recorded") and not record.get("escalated"):
        rc, out = gh(["run", "view", run_id, "--repo", str(config["repo"]), "--json", "status,conclusion,url"])
        view = {}
        if rc == 0:
            try:
                view = json.loads(out or "{}")
            except ValueError:
                view = {}
        view_conclusion = view.get("conclusion")
        if view.get("status") == "completed" and view_conclusion == "success":
            prior_outcome = "success"
        elif view.get("status") == "completed" and view_conclusion in FAILED_CONCLUSIONS:
            prior_outcome = "failure"
        else:
            prior_outcome = "in_progress"

    log = _failed_log(config, gh, run_id)
    failure_class, test_ids = classify_failure(
        str(view_conclusion or run.get("conclusion")), log, infra_markers)
    base.update({"failure_class": failure_class, "failing_test_ids": test_ids})
    ledger = rerun_ledger if rerun_ledger is not None else {}
    head_rerun = bool(head_key) and head_key in ledger
    # Only the ORIGINAL attempt of a held head/check waits. Once the rerun attempt itself is red
    # (attempt >= 2) this is the 'fail again = REAL' case: it must page and get the fix task, never
    # another rerun. The attempt number is the last run_key component.
    try:
        attempt_no = int(str(run_key).rsplit(":", 1)[-1]) if ":" in str(run_key) else 1
    except ValueError:
        attempt_no = 1
    if (head_rerun and attempt_no <= 1 and attempts == 0
            and not record.get("escalated") and not record.get("flake_recorded")):
        # This head/check already got its one re-run (possibly from the other workflow in the group).
        # Hold, do not page: the re-run's outcome is the decision.
        return {**base, "action": ACTION_NOOP,
                "reason": "one re-run already requested for this head/check"}
    rerun_allowed = (bool((config.get("rerun_classes") or {}).get(failure_class))
                     and run_prior_attempts == 0 and not head_rerun)

    decision = decide(attempts=attempts, max_reruns=int(config["max_reruns"]),
                      escalated=bool(record.get("escalated")),
                      flake_recorded=bool(record.get("flake_recorded")),
                      prior_rerun_outcome=prior_outcome, failure_class=failure_class,
                      rerun_allowed=rerun_allowed)

    if decision == ACTION_NOOP:
        return {**base, "action": ACTION_NOOP,
                "reason": "already handled" if record.get("escalated") or record.get("flake_recorded")
                else "re-run still in progress"}
    if decision == ACTION_FLAKE_RECORDED:
        record["flake_recorded"] = True
        record["last_action"] = ACTION_FLAKE_RECORDED
        fixer_path = None
        if not dry_run and bool(config.get("fixer", {}).get("enabled", True)):
            # Operator standing order 2026-11-03: a passing re-run is FLAKY and must OPEN A FIX TASK so the
            # test becomes deterministic. The task is this durable request; the fixer stops at a local fix.
            fixer_path, test_ids = _fix_request(
                config, base, run, run_id, workflow, state_dir, now,
                why="suspected flake: the re-run passed; make the failing test deterministic",
                log_tail=_log_tail(config, log), run_key=run_key)
            record["fixer_request"] = str(fixer_path)
        if bool(config.get("flaky_issue", {}).get("enabled")) and issue_writer is not None and test_ids:
            try:
                base["flaky_issue_url"] = issue_writer(
                    title=f"Flaky test on main: {test_ids[0]}", body=f"run {run.get('url')} cleared on re-run",
                    label=str(config["flaky_issue"].get("label") or "flaky-test"))
            except Exception as exc:  # noqa: BLE001
                base["issue_error"] = f"{type(exc).__name__}: {exc}"
        return {**base, "action": ACTION_FLAKE_RECORDED, "suspected_flake": True,
                "failing_test_ids": list(test_ids or []),
                "fixer_request": str(fixer_path) if fixer_path else None,
                "note": "the re-run passed; recorded as a suspected flake and a fix task was opened"}
    if decision == ACTION_RERUN:
        if dry_run:
            return {**base, "action": "would_" + ACTION_RERUN}
        rc, out = gh(["run", "rerun", run_id, "--repo", str(config["repo"]), "--failed"])
        # Count the attempt even when the call fails: otherwise a broken rerun would be retried on
        # every cycle, forever.
        record["attempts"] = attempts + 1
        record["last_action"] = ACTION_RERUN
        if rc == 0 and head_key:
            ledger[head_key] = {"run_id": run_id, "at": now}
        if rc != 0:
            return {**base, "action": "rerun_failed", "attempt": record["attempts"],
                    "error": (out or "")[:300]}
        return {**base, "action": ACTION_RERUN, "attempt": record["attempts"]}

    why = ("re-run failed again" if prior_outcome == "failure"
           else f"max_reruns={config['max_reruns']} reached" if attempts >= int(config["max_reruns"])
           else f"failure class '{failure_class}' is not re-runnable")
    if dry_run:
        return {**base, "action": "would_" + ACTION_PAGE_AND_DISPATCH, "reason": why}
    return _escalate(config, base, record, run, run_id, workflow, gh, state_dir, dry_run,
                     telegram, issue_writer, infra_markers, now, why=why, log_tail=_log_tail(config, log),
                     run_key=run_key)


def _page_allowed(state_dir: Path, key: str, now: str, hours: float) -> bool:
    """Has the cooldown passed since this (commit, check) last paged? Config-driven, fail open on junk."""
    last = _load_json(state_dir / "pages.json").get(key)
    if not last:
        return True
    try:
        seen = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        cur = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
        return (cur - seen).total_seconds() >= float(hours) * 3600.0
    except ValueError:
        return True


def _mark_page(state_dir: Path, key: str, now: str, hours: float = 6.0) -> None:
    pages = _load_json(state_dir / "pages.json")
    pages[key] = now
    try:
        cur = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
        keep = {}
        for k, ts in pages.items():
            seen = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if (cur - seen).total_seconds() <= float(hours) * 3600.0:
                keep[k] = ts
        pages = keep
    except ValueError:
        pass
    _write_json(state_dir / "pages.json", pages)


def _run_attempt(config, gh, run_id: str, run: Mapping[str, Any]) -> int:
    """The run attempt number.

    `gh run list` has no `attempt` field, and this host's gh 2.46.0 also rejects
    `gh run view --json attempt` ("Unknown JSON field"), which left every run on attempt 1 — so a
    manual re-run that failed a different test was never seen as a new attempt. The REST field
    ``run_attempt`` works on the host.
    """
    if run.get("attempt") is not None:
        return int(run["attempt"])
    rc, out = gh(["api", f"repos/{config['repo']}/actions/runs/{run_id}", "--jq", ".run_attempt"])
    if rc == 0:
        try:
            return int(str(out).strip() or 1)
        except (ValueError, TypeError):
            pass
    return 1


def _failed_log(config, gh, run_id: str) -> str:
    """The run's ENTIRE failed-job log. Classification must see all of it: on a real 35.9k log the
    FAILED line sat at offset 4486, so a 20k tail classified it 'unknown', and an infra marker in
    another job's tail could then re-run a test failure. The tail is taken separately, for the request."""
    rc, out = gh(["run", "view", run_id, "--repo", str(config["repo"]), "--log-failed"])
    if rc != 0:
        return ""
    return out or ""


def _log_tail(config, log: str) -> str:
    return (log or "")[-int(config["log_tail_chars"]):]


def fixer_incident_document(*, run: Mapping[str, Any], run_id: str, workflow: str, failing: list[str],
                            failure_class: str, log_tail: str, now: str) -> dict:
    """A dry-run-consumable incident for ``scripts/self_heal_fixer.py --cycle --incident <file>``.

    The fixer's ``--incident`` intake reads ``code_defect`` (the N8nCodeDefect@v1 contract it already
    consumes), ``receipt`` (a RunReceipt@v2-shaped evidence record) and ``registry_row``. Everything
    here is derived from the GitHub run; nothing is invented beyond naming the run's own fields.
    """
    basis = "|".join(failing) if failing else f"{workflow}:{run.get('conclusion')}"
    signature = "sig-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
    failed_run_id = f"gh:{run_id}"
    return {
        "at": now,
        "code_defect": {
            "schema": "N8nCodeDefect@v1",
            "kind": "code_defect",
            "consumer": "claude_code_iterative_fix",
            "consumer_status": "pending_consumer",
            "defect_id": f"cd-main-red-{run_id}-ep1",
            "episode": 1,
            "lane": workflow,
            "signature": signature,
            "failure_class": "code_error",
            "failure_kind": f"ci_main_red:{workflow}",
            "route": "fix_pr_release",
            "next": "fix branch -> PR -> every check green -> merge (AGENTS.md deploy protocol)",
            "evidence": {
                "failed_run_id": failed_run_id,
                "incident_key": f"gh:{workflow}:{run_id}",
                "event_type": "RUN_FAILED",
                "siem_id": None,
                "receipt": f"github:{run.get('url')}",
                "coordination_ledger": None,
                "diagnoses_store": None,
                "evidence_pack": None,
            },
        },
        "receipt": {
            "schema": "RunReceipt@v2",
            "run_id": failed_run_id,
            "lane_id": workflow,
            "state": "RUN_FAILED",
            "mode": "live",
            "scheduler": "github_actions",
            "attempt": 1,
            "attempts": 1,
            "exit_code": None,
            "argv": [],
            "reason": f"run_conclusion_{run.get('conclusion')}",
            "stderr_tail": log_tail,
            "output_signal": None,
            "output_verdict": {"verdict": "not_evaluated", "why": "red_main_run"},
            "started_at": None,
            "finished_at": None,
        },
        "registry_row": {
            "lane_id": workflow,
            "owner": "platform",
            "state": "ACTIVE",
            "scheduler": {"kind": "github_actions", "workflow": workflow},
            "output_signal": {"kind": "none"},
        },
        "main_red_autoheal": {
            "schema": FIXER_REQUEST_SCHEMA,
            "created_at": now,
            "repo": None,
            "run_id": run_id,
            "run_url": run.get("url"),
            "workflow": workflow,
            "head_sha": run.get("headSha"),
            "conclusion": run.get("conclusion"),
            "failure_class": failure_class,
            "failing_test_ids": list(failing),
            "note": "Consumed by scripts/self_heal_fixer.py --cycle --incident <this file>. The fixer "
                    "opens ONE fix PR through the merge gate (scripts/lib/pr_all_checks_green.py); the "
                    "scheduled lane never pushes, opens a PR or merges (AGENTS.md 24.5, 28.14).",
        },
    }


def _fix_request(config, base, run, run_id, workflow, state_dir, now, *, why, log_tail="", run_key=""):
    """Write the durable LOCAL fix task (N8nCodeDefect@v1) the self-heal fixer consumes.

    Operator standing order 2026-11-03: a re-run that passes leaves a FLAKY test, and 'OPEN A FIX TASK so it
    becomes deterministic'. The fix task is this request file, not a GitHub issue (a scheduled remote write is
    §24.5); the fixer still stops at a local fix branch until it is armed. Returns (path, failing test ids).
    """
    failing = list(base.get("failing_test_ids") or [])
    request = fixer_incident_document(
        run=run, run_id=run_id, workflow=workflow, failing=failing,
        failure_class=str(base.get("failure_class") or ""), log_tail=log_tail, now=now)
    request["main_red_autoheal"]["repo"] = str(config["repo"])
    request["main_red_autoheal"]["why"] = why
    run_key = run_key or run_id
    request_path = state_dir / str(config["fixer"].get("requests_rel") or "fixer_requests") / \
        f"{run_key.replace(':', '-')}.json"
    _write_json(request_path, request)
    if bool(config.get("fixer", {}).get("enabled", True)):
        _append_jsonl(state_dir / "fixer_requests.jsonl", request)
    return request_path, failing


def _escalate(config, base, record, run, run_id, workflow, gh, state_dir, dry_run,
              telegram, issue_writer, infra_markers, now, *, why, log_tail="", run_key="") -> dict:
    failing = list(base.get("failing_test_ids") or [])
    if dry_run:
        return {**base, "action": "would_escalate", "reason": why, "failing_test_ids": failing}
    request_path, failing = _fix_request(config, base, run, run_id, workflow, state_dir, now,
                                         why=why, log_tail=log_tail, run_key=run_key)

    text = (
        f"[{config['page'].get('severity', 'P1')}] main is red: {workflow} on "
        f"{str(run.get('headSha'))[:12]} — {why}.\n"
        f"Failing tests: {', '.join(failing) if failing else 'none named in the failed log'}\n"
        f"Run: {run.get('url')}\nFixer request: {request_path}"
    )
    record["escalated"] = True
    record["last_action"] = ACTION_PAGE_AND_DISPATCH
    record["fixer_request"] = str(request_path)
    group = (config.get("page_groups") or {}).get(workflow) or workflow
    page_key = f"{run.get('headSha')}:{group}"
    cooldown_h = float((config.get("page") or {}).get("page_cooldown_hours", 6))
    if (bool(config.get("page", {}).get("enabled", True)) and telegram is not None
            and _page_allowed(state_dir, page_key, now, cooldown_h)):
        try:
            telegram(text, priority=str(config["page"].get("severity", "P1")))
            _mark_page(state_dir, page_key, now, cooldown_h)
        except Exception as exc:  # noqa: BLE001 - a page failure must not lose the request
            base["page_error"] = f"{type(exc).__name__}: {exc}"
    elif telegram is not None:
        base["page_suppressed"] = f"cooldown {cooldown_h:g}h for {page_key}"
    if bool(config.get("flaky_issue", {}).get("enabled")) and issue_writer is not None and failing:
        try:
            base["flaky_issue_url"] = issue_writer(
                title=f"Flaky test on main: {failing[0]}",
                body=text, label=str(config["flaky_issue"].get("label") or "flaky-test"))
        except Exception as exc:  # noqa: BLE001
            base["issue_error"] = f"{type(exc).__name__}: {exc}"
    return {**base, "action": ACTION_PAGE_AND_DISPATCH, "reason": why, "failing_test_ids": failing,
            "fixer_request": str(request_path)}


def _prune(runs_state: dict, keep: int) -> None:
    if len(runs_state) <= max(keep, 1):
        return
    ordered = sorted(runs_state.items(), key=lambda kv: str(kv[1].get("updated_at") or ""), reverse=True)
    for run_id, _ in ordered[max(keep, 1):]:
        runs_state.pop(run_id, None)


def _finish(receipt: dict, state: dict, state_dir: Path, dry_run: bool) -> dict:
    receipt["finished_at"] = _utcnow()
    if dry_run:
        receipt["wrote_state"] = False
        return receipt
    stamp = str(receipt["started_at"]).replace(":", "").replace("-", "")
    _write_json(state_dir / "receipts" / f"{stamp}.json", receipt)
    _write_json(state_dir / "last.json", receipt)
    _write_json(state_dir / "state.json", state)
    _append_jsonl(state_dir / "runs.jsonl", receipt)
    receipt["wrote_state"] = True
    return receipt


# --------------------------------------------------------------------------- host main
def _gh_runner(argv: list[str]) -> tuple[int, str]:
    proc = subprocess.run(["gh", *argv], capture_output=True, text=True, timeout=120)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def default_config_path() -> Path:
    """``config/main_red_autoheal.json`` beside this script's package root.

    ``parents[1]`` is the repo root for ``scripts/main_red_autoheal.py``; a test drives this exact
    function so a wrong parent count fails a test, not only the first scheduled run.
    """
    return Path(__file__).resolve().parents[1] / "config" / "main_red_autoheal.json"


def default_state_dir() -> Path:
    root = os.environ.get("TRADEAI_STATE_ROOT")
    return Path(root) / "data" / "runtime" / "main_red_autoheal" if root else \
        Path(__file__).resolve().parents[1] / "data" / "runtime" / "main_red_autoheal"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--config", default=str(default_config_path()))
    parser.add_argument("--state-dir", default=None)
    parser.add_argument("--apply", action="store_true", help="act; without it the cycle is a dry run")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    config = json.loads(Path(args.config).read_text())
    if config.get("schema") != CONFIG_SCHEMA:
        print(f"refusing: config schema {config.get('schema')!r} != {CONFIG_SCHEMA}", file=sys.stderr)
        return 2
    telegram = None
    if args.apply:
        try:
            from telegram_alert import send_telegram  # type: ignore
        except Exception:  # pragma: no cover - import path differs under scripts/
            from scripts.telegram_alert import send_telegram  # type: ignore
        telegram = lambda text, priority="P1": send_telegram(text, priority=priority)  # noqa: E731
    receipt = run_cycle(config, state_dir=Path(args.state_dir) if args.state_dir else default_state_dir(),
                        gh=_gh_runner, dry_run=not args.apply, telegram=telegram)
    print(json.dumps(receipt, indent=1, sort_keys=True) if args.json else
          f"main-red-autoheal: {len(receipt['actions'])} action(s), "
          f"{len(receipt['skipped'])} skipped, dry_run={receipt['dry_run']}")
    return 0 if not receipt.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
