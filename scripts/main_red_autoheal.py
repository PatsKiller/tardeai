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

_TEST_ID_PATTERNS = (
    re.compile(r"^FAILED\s+(\S+::\S+)"),
    re.compile(r"^(\S+\.py::\S+)\s+FAILED"),
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
    if test_ids:
        return CLASS_TEST_FAILURE, test_ids
    if conclusion in {"startup_failure", "timed_out"}:
        return CLASS_INFRASTRUCTURE, []
    lowered = (log_text or "").lower()
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
        if str(run.get("headSha")) != tip:
            receipt["skipped"].append({"run_id": run_id, "workflow": workflow, "reason": "stale_commit"})
            continue
        if run.get("status") != "completed":
            receipt["skipped"].append({"run_id": run_id, "workflow": workflow, "reason": "not_completed"})
            continue
        if run.get("conclusion") not in FAILED_CONCLUSIONS:
            receipt["skipped"].append({"run_id": run_id, "workflow": workflow, "reason": "green"})
            continue
        action = _handle_red_run(
            config=config, run=run, run_id=run_id, workflow=workflow,
            record=runs_state.setdefault(run_id, {"attempts": 0, "escalated": False,
                                                  "flake_recorded": False, "head_sha": tip}),
            gh=gh, state_dir=state_dir, dry_run=dry_run, telegram=telegram,
            issue_writer=issue_writer, infra_markers=infra_markers, now=started_at,
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
                    telegram, issue_writer, infra_markers, now) -> dict:
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
    rerun_allowed = bool((config.get("rerun_classes") or {}).get(failure_class))

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
        if bool(config.get("flaky_issue", {}).get("enabled")) and issue_writer is not None and test_ids:
            try:
                base["flaky_issue_url"] = issue_writer(
                    title=f"Flaky test on main: {test_ids[0]}", body=f"run {run.get('url')} cleared on re-run",
                    label=str(config["flaky_issue"].get("label") or "flaky-test"))
            except Exception as exc:  # noqa: BLE001
                base["issue_error"] = f"{type(exc).__name__}: {exc}"
        return {**base, "action": ACTION_FLAKE_RECORDED, "suspected_flake": True,
                "note": "the re-run passed; recorded as a suspected flake"}
    if decision == ACTION_RERUN:
        if dry_run:
            return {**base, "action": "would_" + ACTION_RERUN}
        rc, out = gh(["run", "rerun", run_id, "--failed"])
        if rc != 0:
            return {**base, "action": "rerun_failed", "error": (out or "")[:300]}
        record["attempts"] = attempts + 1
        record["last_action"] = ACTION_RERUN
        return {**base, "action": ACTION_RERUN, "attempt": record["attempts"]}

    why = ("re-run failed again" if prior_outcome == "failure"
           else f"max_reruns={config['max_reruns']} reached" if attempts >= int(config["max_reruns"])
           else f"failure class '{failure_class}' is not re-runnable")
    if dry_run:
        return {**base, "action": "would_" + ACTION_PAGE_AND_DISPATCH, "reason": why}
    return _escalate(config, base, record, run, run_id, workflow, gh, state_dir, dry_run,
                     telegram, issue_writer, infra_markers, now, why=why)


def _failed_log(config, gh, run_id: str) -> str:
    """The tail of a run's failed job log; classification only ever reads the tail."""
    rc, out = gh(["run", "view", run_id, "--repo", str(config["repo"]), "--log-failed"])
    return (out or "")[-int(config["log_tail_chars"]):] if rc == 0 else ""


def _escalate(config, base, record, run, run_id, workflow, gh, state_dir, dry_run,
              telegram, issue_writer, infra_markers, now, *, why) -> dict:
    failing = list(base.get("failing_test_ids") or [])
    request = {
        "schema": FIXER_REQUEST_SCHEMA, "created_at": now, "repo": str(config["repo"]),
        "run_id": run_id, "run_url": run.get("url"), "workflow": workflow,
        "head_sha": run.get("headSha"), "conclusion": run.get("conclusion"),
        "failure_class": base.get("failure_class"), "failing_test_ids": failing,
        "reason": why,
        "note": "A Claude Code fixer opens ONE fix PR from this request; it follows the "
                "merge gate (scripts/lib/pr_all_checks_green.py). The scheduled lane never "
                "pushes, opens a PR or merges (AGENTS.md 24.5, 28.14).",
    }
    request_path = state_dir / str(config["fixer"].get("requests_rel") or "fixer_requests") / f"{run_id}.json"
    if dry_run:
        return {**base, "action": "would_escalate", "reason": why, "failing_test_ids": failing}

    text = (
        f"[{config['page'].get('severity', 'P1')}] main is red: {workflow} on "
        f"{str(run.get('headSha'))[:12]} — {why}.\n"
        f"Failing tests: {', '.join(failing) if failing else 'none named in the failed log'}\n"
        f"Run: {run.get('url')}\nFixer request: {request_path}"
    )
    record["escalated"] = True
    record["last_action"] = ACTION_PAGE_AND_DISPATCH
    record["fixer_request"] = str(request_path)
    _write_json(request_path, request)
    if bool(config.get("fixer", {}).get("enabled", True)):
        _append_jsonl(state_dir / "fixer_requests.jsonl", request)
    if bool(config.get("page", {}).get("enabled", True)) and telegram is not None:
        try:
            telegram(text, priority=str(config["page"].get("severity", "P1")))
        except Exception as exc:  # noqa: BLE001 - a page failure must not lose the request
            base["page_error"] = f"{type(exc).__name__}: {exc}"
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
