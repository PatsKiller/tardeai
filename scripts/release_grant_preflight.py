#!/usr/bin/env python3
"""Release-grant preflight for cio_phase2_exact_main_deploy.sh (prepare/promote).

Exit 0 when a release-write grant is bound to THIS release (PR/SHA/campaign);
exit 2 when refused. ``TRADEAI_RELEASE_GRANT_BINDING=warn`` prints the refusal
and exits 0 (visible degradation, transition only). Prints one JSON line.
No credential is read or printed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.release_grant_binding import ReleaseAction, decide_from_disk  # noqa: E402


GUARD_LEDGER = ROOT / ".cursor" / "hooks" / "guard_ledger.py"


def consume_release_grant(*, tier: str = "release-write", runner=None) -> dict:
    """Decrement one use of the active grant through the guard's own ledger CLI.

    Fail-soft: a missing ledger CLI or a consume error is REPORTED in the
    preflight JSON, never allowed to block a release the binding already
    approved (the binding is the control; consumption is the accounting).
    Disable with TRADEAI_GUARD_CONSUME=0.
    """
    if os.environ.get("TRADEAI_GUARD_CONSUME", "1") == "0":
        return {"ok": False, "skipped": "disabled"}
    if not GUARD_LEDGER.is_file():
        return {"ok": False, "skipped": "guard_ledger.py absent"}
    import subprocess
    run = runner or subprocess.run
    try:
        proc = run([sys.executable, str(GUARD_LEDGER), "consume", "--tier", tier],
                   capture_output=True, text=True, timeout=20)
        last = [ln for ln in (proc.stdout or "").splitlines() if ln.strip().startswith("{")]
        body = json.loads(last[-1]) if last else {}
        return {"ok": proc.returncode == 0, "rc": proc.returncode, "tier": tier, **({"ledger": body} if body else {})}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


# Always-on post-merge workflows. PR runs do not execute the same test profile.
REQUIRED_PUSH_WORKFLOWS = frozenset({
    ".github/workflows/cio-production-hardening-ci.yml",
    ".github/workflows/agent-governance.yml",
})

# Push workflows that report on main but do NOT gate a promote. The sharded full suite
# (ci-gate) gained a push/main trigger on 2026-10-09 so main has a full-suite signal (n8n
# maturity ci_signal; due diligence C "Missing"). Its rollout is still advisory: branch
# protection and promote stay on the required contexts until the operator switches them.
# Listed, not silently ignored: the report names what it set aside.
ADVISORY_PUSH_WORKFLOWS = frozenset({
    ".github/workflows/cio-full-suite-sharded.yml",
})


def evaluate_push_checks(sha: str, runs: list[dict]) -> dict:
    """Fail closed on exact-commit push/main evidence, including reruns in flight."""
    import re
    from datetime import datetime, timezone

    errors = []
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        errors.append("candidate_sha_must_be_full")
    latest = {}
    for run in runs:
        if run.get("head_sha") != sha or run.get("event") != "push" or run.get("head_branch") != "main":
            continue
        path = str(run.get("path") or "").split("@", 1)[0]
        if not path or not run.get("workflow_id") or not run.get("id"):
            errors.append("workflow_identity_missing")
            continue
        # A later run/attempt supersedes an old success. Never select by conclusion.
        order = (int(run.get("run_number") or 0), int(run["id"]), int(run.get("run_attempt") or 1))
        if path not in latest or order > latest[path][0]:
            latest[path] = (order, run)
    for path in sorted(REQUIRED_PUSH_WORKFLOWS - latest.keys()):
        errors.append("missing:" + path)
    checks = []
    advisory = sorted(p for p in latest if p in ADVISORY_PUSH_WORKFLOWS and p not in REQUIRED_PUSH_WORKFLOWS)
    for path in advisory:
        latest.pop(path)
    for path, (_, run) in sorted(latest.items()):
        check = {k: run.get(k) for k in (
            "id", "workflow_id", "name", "head_sha", "event", "head_branch",
            "status", "conclusion", "run_attempt", "html_url", "updated_at",
        )}
        check["path"] = path
        checks.append(check)
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            errors.append("not_successful:" + path)
    return {"ok": not errors, "candidate_sha": sha, "checks": checks, "errors": errors,
            "required_workflows": sorted(REQUIRED_PUSH_WORKFLOWS),
            "advisory_not_gating": advisory,
            "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}


def collect_push_checks(sha: str, *, runner=None) -> dict:
    """Read GitHub via gh; network/API errors are unavailable, never a pass."""
    import re
    import subprocess

    run = runner or subprocess.run
    try:
        remote = run(["git", "-C", str(ROOT), "remote", "get-url", "origin"],
                     capture_output=True, text=True, timeout=20, check=True).stdout.strip()
        match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?", remote)
        if not match:
            raise ValueError("unsupported_repository")
        repository = match.group(1)
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            return evaluate_push_checks(sha, [])
        endpoint = f"repos/{repository}/actions/runs?head_sha={sha}&event=push&branch=main&per_page=100"
        response = run(["gh", "api", "--paginate", endpoint],
                       capture_output=True, text=True, timeout=60, check=True)
        # gh 2.46 (the deployment host) emits consecutive JSON documents for
        # --paginate and does not support --slurp. Decode every page ourselves;
        # malformed or trailing output remains unavailable, never partial success.
        decoder = json.JSONDecoder()
        remaining = response.stdout.strip()
        pages = []
        while remaining:
            page, end = decoder.raw_decode(remaining)
            if not isinstance(page, dict) or not isinstance(page.get("workflow_runs"), list):
                raise ValueError("invalid_workflow_response")
            pages.append(page)
            remaining = remaining[end:].lstrip()
        if not pages:
            raise ValueError("invalid_workflow_response")
        evidence = evaluate_push_checks(sha, [r for p in pages for r in p["workflow_runs"]])
        evidence["repository"] = repository
        return evidence
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError) as exc:
        evidence = evaluate_push_checks(sha, [])
        # Do not copy CLI stderr, which can contain host credential diagnostics.
        evidence["errors"].append("checks_unavailable:" + type(exc).__name__)
        evidence["ok"] = False
        return evidence


def collect_ci_evidence(sha: str, *, env=None, attest=None, push=None) -> dict:
    """Promote CI evidence: tree-attested PR evidence when flagged on and proven, else push/main.

    TRADEAI_TREE_ATTESTED_PROMOTE=1 (default off) tries scripts/lib/tree_attested_promote.py
    first; any unproven condition falls back to the exact-SHA push/main rule unchanged, and the
    fallback reasons are recorded in the receipt.
    """
    from scripts.lib import tree_attested_promote as tap

    push = push or collect_push_checks
    if not tap.flag_enabled(env):
        return push(sha)
    attested = (attest or (lambda s: tap.collect(s, root=ROOT)))(sha)
    if attested.get("ok"):
        return attested
    evidence = push(sha)
    evidence["tree_attested_fallback"] = {"reasons": attested.get("reasons") or [],
                                          "pr": attested.get("pr"), "head_sha": attested.get("head_sha")}
    return evidence


def _write_json(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


BACKSTOP_RECEIPT = Path.home() / ".local" / "state" / "cio-phase2-exact-main" / "tree_attested_backstop.json"


def backstop_check(sha: str, receipt: Path, *, push=None) -> int:
    """Async backstop for a tree-attested release: 0 green, 2 pending/unavailable, 3 RED (alarm)."""
    from scripts.lib import tree_attested_promote as tap

    evidence = (push or collect_push_checks)(sha)
    status, rc = tap.backstop_status(evidence)
    body = {"schema": "TreeAttestedBackstop@v1", "candidate_sha": sha, "status": status,
            "exit_code": rc, "push_evidence": evidence}
    _write_json(receipt, body)
    print(json.dumps({"candidate_sha": sha, "status": status, "exit_code": rc}, sort_keys=True))
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ci-only", action="store_true", help="read exact-SHA post-merge checks; no grant consumed")
    ap.add_argument("--ci-receipt", type=Path, default=None)
    ap.add_argument("--action", default="verify", choices=("prepare", "promote", "rollback", "verify"))
    ap.add_argument("--sha", required=True)
    ap.add_argument("--pr", type=int, default=None)
    ap.add_argument("--campaign", default=os.environ.get("TRADEAI_RELEASE_CAMPAIGN") or None)
    ap.add_argument("--backstop-check", action="store_true",
                    help="read the push/main run of a tree-attested release; exit 3 when it is red")
    ap.add_argument("--backstop-receipt", type=Path, default=BACKSTOP_RECEIPT)
    args = ap.parse_args()
    if args.backstop_check:
        return backstop_check(args.sha, args.backstop_receipt)
    if args.ci_only:
        evidence = collect_ci_evidence(args.sha)
        if args.ci_receipt:
            args.ci_receipt.parent.mkdir(parents=True, exist_ok=True)
            tmp = args.ci_receipt.with_suffix(".tmp")
            tmp.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            tmp.replace(args.ci_receipt)
        print(json.dumps(evidence, sort_keys=True))
        return 0 if evidence["ok"] else 2
    mode = (os.environ.get("TRADEAI_RELEASE_GRANT_BINDING") or "enforce").lower()
    v = decide_from_disk(ReleaseAction(action=args.action, target_sha=args.sha, pr_number=args.pr, campaign=args.campaign))
    out = {**v.to_dict(), "mode": mode, "action": args.action, "sha": args.sha, "pr": args.pr}
    if v.allowed and args.action in ("prepare", "promote", "rollback"):
        # C-10 (2026-09-26): the deploy path never consumed a grant use, so the
        # ledger under-counted every Claude Code promote (both P1 grants showed
        # unconsumed uses after being exercised). One use per release action.
        out["consumed"] = consume_release_grant()
    print(json.dumps(out, sort_keys=True))
    if v.allowed:
        return 0
    if mode == "warn":
        print("RELEASE GRANT BINDING: REFUSED (warn mode — continuing): " + v.reason, file=sys.stderr)
        return 0
    print("RELEASE GRANT BINDING: REFUSED — " + v.reason, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
