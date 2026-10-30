"""Deploy console P2 — the operator write path behind ``POST /api/v2/ops/in-flight/action``.

Four operator actions, each behind the Command Center operator session (tailnet identity) + same-origin
CSRF, reusing EXISTING authority — nothing new is granted (DSN-20261029-deploy-console P2):

* ``approve``       — add the ``operator-merge`` label, bound to the submitted head SHA, so Mergify queues
                      the PR. This is the SAME host side-effect the Telegram tap already performs
                      (``scripts/lib/pr_merge_telegram.py`` ``add_operator_merge_label``; the digest's
                      ``settle_approve_all``). The head is re-read first; a moved head / closed PR refuses.
* ``hold``          — remove the ``operator-merge`` label (``pr_merge_telegram.remove_operator_merge_label``).
                      No other label is written.
* ``refresh_hints`` — re-run the self-contained duration-hints refresh the CI runner exposes
                      (``scripts/run_cio_hardening_ci.py --write-duration-hints``) and record its result.
                      The shard-duration-hints refresh from a green ci-gate ``cio-shard-timings`` artifact
                      remains the runbook procedure (docs/ops/SHARD_HINTS_REFRESH_RUNBOOK.md): local wall
                      seconds would fabricate CI-measured values (AGENTS.md §5).
* ``push``          — write a ``git-push`` guard grant into the Cursor approval ledger (the same effect as
                      ``bin/guard grant git-push``) bound to branch + head SHA + reason, then fast-forward
                      push the already-green local branch. Force-push / reset / history rewrite stays
                      refused: the push is a plain ``git push origin <sha>:refs/heads/<branch>`` (no
                      ``--force``), and the tracked pre-push hook (``.githooks/pre-push``) re-checks scope and
                      refuses any non-fast-forward.

AUTHORITY: the caller (``scripts/api_v2.py``) supplies ``actor`` from the AUTHENTICATED ``cc_auth`` principal
(``tailnet:<login>``) and the CSRF verdict (``cc_auth.command_csrf_check``); this module refuses without both.
``MBI_BEHAVIOR = 0``: no broker, no order, no size, no stop, no credential. Every action appends one durable
``DeployConsoleAction@v1`` receipt (append-only JSONL, fsynced — the same pattern as the digest's
``PrMergeDigestApproval@v1`` approvals and ``deploy_stop``'s audit trail).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

SCHEMA = "DeployConsoleAction@v1"
ROUTE = "/api/v2/ops/in-flight/action"
AUTHORITY = "OPERATOR_SESSION (tailnet identity + same-origin CSRF; reuses cc_auth)"
MERGE_LABEL = "operator-merge"
GUARD_TIER = "git-push"
GRANT_TTL_S = 300  # 5 minutes: enough for the immediate fast-forward push, no standing window
GRANT_USES = 1     # one button press = one bound operation
DEFAULT_REPO = os.environ.get("TRADEAI_GITHUB_REPO", "PatsKiller/tardeai")
ACTIONS = ("approve", "hold", "refresh_hints", "push")
REASON_MIN = 4
REASON_MAX = 500


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


# ── pure logic (hermetic; no I/O) ────────────────────────────────────────────────────────────────


def label_intent(action: str) -> Optional[tuple[str, str]]:
    """The label side-effect an action maps to: approve → ("add", label); hold → ("remove", label)."""
    return {"approve": ("add", MERGE_LABEL), "hold": ("remove", MERGE_LABEL)}.get(action)


def push_reason(*, branch: str, head_sha: str, reason: str = "", override: bool = False) -> str:
    """The guard git-push grant reason, built so ``guard_push_auth.grant_scope_covers`` passes.

    It names the branch AND a 7+-hex prefix of the head SHA (both, not one), so the tracked pre-push
    hook's scope check is satisfied. The literal word ``override`` is appended only when asked, and it is
    the only thing that lifts the per-branch push budget (``tradeai_push_budget.grant_overrides_budget``).
    """
    parts = [f"deploy-console push branch={str(branch).strip()} head={str(head_sha).strip()[:12]}"]
    if str(reason or "").strip():
        parts.append(str(reason).strip()[:400])
    text = " ".join(parts)
    if override:
        text += " override"
    return text


def push_command(branch: str, head_sha: str) -> list[str]:
    """The fast-forward-only push argv. Never ``--force``/``--force-with-lease``/``--mirror``/reset."""
    return ["git", "push", "origin", f"{str(head_sha).strip()}:refs/heads/{str(branch).strip()}"]


def force_refusal(body: dict[str, Any] | None) -> Optional[str]:
    """A reason to refuse, when the body asks to rewrite history (force-push / reset), else None."""
    b = body if isinstance(body, dict) else {}
    for key, bad in (("force", True), ("force_push", True), ("force_with_lease", True),
                     ("rewrite_history", True), ("reset", True)):
        if b.get(key) is True or str(b.get(key) or "").strip().lower() in ("1", "true", "yes"):
            return f"field {key!r} refused: a deploy-console push is fast-forward only"
    if any(tok in str(b.get("reason") or "").lower() for tok in ("--force", "force-push", "force push")):
        return "reason asks to force-push; a deploy-console push is fast-forward only"
    return None


def guard_reason_covers(reason: str, *, branch: str, head_sha: str) -> bool:
    """True when the reason names the branch or head SHA (delegates to guard_push_auth; pure)."""
    try:
        from scripts.lib import guard_push_auth as _gpa
    except ImportError:  # pragma: no cover - flat lib.* layout
        from lib import guard_push_auth as _gpa  # type: ignore[no-redef]
    covers, _why = _gpa.grant_scope_covers(reason, branch=branch, head_sha=head_sha)
    return covers


# ── subprocess effects (stubbed in tests) ─────────────────────────────────────────────────────────


def _gh_pr_view(pr_number: int, *, repo: str = DEFAULT_REPO) -> dict[str, Any]:
    """Read-only ``gh pr view`` of one PR's open state + head (the same read the digest settle makes)."""
    proc = subprocess.run(
        ["gh", "pr", "view", str(int(pr_number)), "--repo", repo, "--json",
         "number,state,headRefOid,isDraft,labels"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        raise RuntimeError(f"gh pr view failed: {(proc.stderr or proc.stdout or '').strip()[:200]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh pr view returned non-JSON: {exc}") from exc


def _add_label(pr_number: int, *, repo: str = DEFAULT_REPO) -> dict[str, Any]:
    try:
        from scripts.lib import pr_merge_telegram as pmt
    except ImportError:  # pragma: no cover
        from lib import pr_merge_telegram as pmt  # type: ignore[no-redef]
    return pmt.add_operator_merge_label(pr_number, repo=repo)


def _remove_label(pr_number: int, *, repo: str = DEFAULT_REPO) -> dict[str, Any]:
    try:
        from scripts.lib import pr_merge_telegram as pmt
    except ImportError:  # pragma: no cover
        from lib import pr_merge_telegram as pmt  # type: ignore[no-redef]
    return pmt.remove_operator_merge_label(pr_number, repo=repo)


def _comment(pr_number: int, body: str, *, repo: str = DEFAULT_REPO) -> dict[str, Any]:
    try:
        from scripts.lib import pr_merge_telegram as pmt
    except ImportError:  # pragma: no cover
        from lib import pr_merge_telegram as pmt  # type: ignore[no-redef]
    return pmt.comment_on_pr(pr_number, body, repo=repo)


def _import_guard_ledger():
    hooks = Path(__file__).resolve().parents[2] / ".cursor" / "hooks"
    if str(hooks) not in sys.path:
        sys.path.insert(0, str(hooks))
    import guard_ledger as gl  # noqa: WPS433

    return gl


def _write_guard_grant(*, branch: str, head_sha: str, reason: str, adir: Optional[Path] = None) -> dict[str, Any]:
    """Write a single-use ``git-push`` grant into the guard ledger (the ``bin/guard grant git-push`` effect)."""
    gl = _import_guard_ledger()
    now = int(time.time())
    return gl.ledger_create_grant_row(
        GUARD_TIER,
        expires=now + GRANT_TTL_S,
        uses=GRANT_USES,
        reason=reason,
        adir=Path(adir) if adir is not None else None,
    )


def _git_push(branch: str, head_sha: str, *, repo_root: Path) -> dict[str, Any]:
    """Fast-forward-only push of ``head_sha`` to ``refs/heads/<branch>``. No force flag, ever."""
    argv = ["git", "-C", str(repo_root), "push", "origin", f"{head_sha}:refs/heads/{branch}"]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
    return {
        "ok": proc.returncode == 0,
        "rc": proc.returncode,
        "argv": argv,
        "stdout": (proc.stdout or "")[-500:],
        "stderr": (proc.stderr or "")[-500:],
        "fast_forward_only": True,
    }


def _refresh_hints(repo_root: Path) -> dict[str, Any]:
    """Re-run the self-contained duration-hints refresh (run_cio_hardening_ci.py --write-duration-hints)."""
    argv = [sys.executable, "scripts/run_cio_hardening_ci.py", "--write-duration-hints"]
    proc = subprocess.run(argv, cwd=str(repo_root), capture_output=True, text=True, timeout=900, check=False)
    tail = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
    return {
        "ok": proc.returncode == 0,
        "rc": proc.returncode,
        "argv": argv,
        "tail": "\n".join(tail[-20:]),
        "note": "fast-profile duration hints (ci_test_duration_hints.json); the shard-hints refresh from a "
                "green ci-gate artifact stays the runbook procedure (docs/ops/SHARD_HINTS_REFRESH_RUNBOOK.md)",
    }


# ── receipts (append-only JSONL, fsynced — the digest-approval / deploy-stop pattern) ─────────────


def _runtime_dir() -> Path:
    try:
        from scripts.lib import lane_last_receipt as _llr
    except ImportError:  # pragma: no cover
        from lib import lane_last_receipt as _llr  # type: ignore[no-redef]
    return Path(_llr.runtime_dir())


def receipts_dir() -> Path:
    return _runtime_dir() / "deploy_console"


def _append_receipt(row: dict[str, Any]) -> Path:
    d = receipts_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / "actions.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return path


# ── dispatch (operator authority first, then the action) ─────────────────────────────────────────


def _refuse(actor: str, action: str, http: int, code: str, message: str, base: dict[str, Any]) -> tuple[int, dict]:
    row = {**base, "ok": False, "outcome": "REFUSED", "refusal": code, "error": message}
    try:
        _append_receipt(row)
    except OSError as exc:  # the refusal stands even if the receipt dir is unwritable
        row["receipt_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    return http, row


def perform(
    body: dict[str, Any] | None,
    *,
    actor: str,
    csrf_ok: bool,
    csrf_reason: str = "",
    repo: str = DEFAULT_REPO,
    repo_root: Optional[Path] = None,
    pr_view: Callable[..., dict[str, Any]] = _gh_pr_view,
    add_label: Callable[..., dict[str, Any]] = _add_label,
    remove_label: Callable[..., dict[str, Any]] = _remove_label,
    comment: Callable[..., dict[str, Any]] = _comment,
    write_grant: Callable[..., dict[str, Any]] = _write_guard_grant,
    git_push: Callable[..., dict[str, Any]] = _git_push,
    refresh: Callable[..., dict[str, Any]] = _refresh_hints,
    now: Optional[datetime] = None,
    adir: Optional[Path] = None,
) -> tuple[int, dict]:
    """One operator action. Returns (http_status, body). Authority is checked before anything runs."""
    b = body if isinstance(body, dict) else {}
    action = str(b.get("action") or "").strip()
    requested_at = _iso(now)
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    base: dict[str, Any] = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "at": requested_at,
        "action": action,
        "actor": actor or "",
    }

    # Order: identity, then CSRF, then the action's own preconditions.
    if not (actor or "").startswith("tailnet:"):
        return _refuse(actor, action, 403, "NO_OPERATOR_IDENTITY",
                       "operator action needs an authenticated tailnet identity; a service token or an "
                       "unauthenticated/report-only request is not one", base)
    if not csrf_ok:
        return _refuse(actor, action, 403, "CSRF", csrf_reason or "csrf: same-origin proof required", base)

    if action not in ACTIONS:
        return _refuse(actor, action, 400, "UNKNOWN_ACTION",
                       f"action must be one of {', '.join(ACTIONS)}", base)

    # --- approve / hold (label write; the Telegram-tap authority, re-used) ---
    if action in ("approve", "hold"):
        pr_number = b.get("pr_number")
        head_sha = str(b.get("head_sha") or "")
        try:
            pr_number = int(pr_number)
        except (TypeError, ValueError):
            return _refuse(actor, action, 400, "PR_NUMBER_REQUIRED", "pr_number must be an int", base)
        if not head_sha:
            return _refuse(actor, action, 400, "HEAD_SHA_REQUIRED", "head_sha is required", base)
        try:
            view = pr_view(pr_number, repo=repo)
        except RuntimeError as exc:
            return _refuse(actor, action, 502, "PR_VIEW_FAILED", str(exc)[:200], base)
        if str(view.get("state") or "").upper() != "OPEN":
            return _refuse(actor, action, 409, "NOT_OPEN",
                           f"PR #{pr_number} is not open (state={view.get('state')})", {**base, "pr_number": pr_number})
        now_head = str(view.get("headRefOid") or "")
        if now_head and str(head_sha) != now_head:
            return _refuse(actor, action, 409, "HEAD_CHANGED",
                           f"head moved from {str(head_sha)[:9]} to {now_head[:9]}; re-read the board",
                           {**base, "pr_number": pr_number, "head_sha": str(head_sha)[:9]})
        verb, _label = label_intent(action)
        if action == "approve":
            res = add_label(pr_number, repo=repo)
        else:
            res = remove_label(pr_number, repo=repo)
        if not res.get("ok"):
            return _refuse(actor, action, 502, "LABEL_WRITE_FAILED",
                           f"gh label {verb} failed (rc={res.get('rc')})", {**base, "pr_number": pr_number})
        if action == "approve":
            comment(pr_number,
                    f"operator-merge: set from the deploy console (bound head `{str(head_sha)[:9]}`). "
                    f"Mergify may queue when CI is green in an ET window; if the head moves the host "
                    f"removes the label and the PR returns to the next digest.", repo=repo)
        result = {
            **base,
            "ok": True,
            "outcome": "LABEL_ADDED" if action == "approve" else "LABEL_REMOVED",
            "pr_number": pr_number,
            "head_sha": str(head_sha)[:9],
            "label": MERGE_LABEL,
        }
        _append_receipt(result)
        return 200, result

    # --- refresh_hints ---
    if action == "refresh_hints":
        out = refresh(root)
        result = {**base, "ok": bool(out.get("ok")), "outcome": "HINTS_REFRESHED" if out.get("ok") else "HINTS_REFRESH_FAILED",
                  "rc": out.get("rc"), "tail": out.get("tail"), "note": out.get("note")}
        _append_receipt(result)
        return (200 if out.get("ok") else 502), result

    # --- push ---
    refused = force_refusal(b)
    if refused:
        return _refuse(actor, action, 400, "FORCE_PUSH_REFUSED", refused, base)
    branch = str(b.get("branch") or "").strip()
    head_sha = str(b.get("head_sha") or "").strip()
    if not branch or branch == "HEAD":
        return _refuse(actor, action, 400, "BRANCH_REQUIRED", "branch is required", base)
    if not head_sha:
        return _refuse(actor, action, 400, "HEAD_SHA_REQUIRED", "head_sha is required", base)
    reason = str(b.get("reason") or "").strip()
    if reason and len(reason) < REASON_MIN:
        return _refuse(actor, action, 400, "REASON_TOO_SHORT",
                       f"reason, when given, must be at least {REASON_MIN} chars", base)
    override = bool(b.get("override"))
    grant_reason = push_reason(branch=branch, head_sha=head_sha, reason=reason[:REASON_MAX], override=override)
    if not guard_reason_covers(grant_reason, branch=branch, head_sha=head_sha):
        # Cannot happen with push_reason (branch and head are both named), but keep the check as the control.
        return _refuse(actor, action, 500, "GRANT_UNSCOPED", "grant reason does not name branch/head", base)
    try:
        grant = write_grant(branch=branch, head_sha=head_sha, reason=grant_reason, adir=adir)
    except Exception as exc:  # noqa: BLE001 - the ledger error is the evidence
        return _refuse(actor, action, 502, "GRANT_WRITE_FAILED", f"{type(exc).__name__}: {str(exc)[:200]}", base)
    push_out = git_push(branch, head_sha, repo_root=root)
    result = {
        **base,
        "ok": bool(push_out.get("ok")),
        "outcome": "PUSHED" if push_out.get("ok") else "PUSH_FAILED",
        "branch": branch,
        "head_sha": head_sha[:9],
        "grant_id": str(grant.get("grant_id") or "")[:12],
        "reason": grant_reason,
        "override": override,
        "push": {k: v for k, v in push_out.items() if k in ("rc", "stdout", "stderr", "fast_forward_only")},
    }
    _append_receipt(result)
    return (200 if push_out.get("ok") else 502), result


__all__ = [
    "SCHEMA", "ROUTE", "AUTHORITY", "MERGE_LABEL", "ACTIONS", "label_intent", "push_reason",
    "push_command", "force_refusal", "guard_reason_covers", "perform", "receipts_dir", "DEFAULT_REPO",
]
