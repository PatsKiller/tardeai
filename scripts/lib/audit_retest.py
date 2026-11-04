"""Retest runner core (SPEC_SITE_AUDIT_AUTOREMEDIATE_LOOP_20261104 §2.5).

The rule that keeps the loop honest: a PR may never claim "fixed" — only a retest closes an item. This module decides the
four outcomes and nothing else; the capture and the check itself are injected, so the decision is testable without a
browser, a database or a live release.

SERVING is decided from the RUNNING PROCESS (`/proc/<pid>/cwd`), never from the CURRENT symlink: the pointer can lead the
process for an unbounded time (cc3's row-4 finding, 2026-11-04).
"""
from __future__ import annotations

from typing import Callable, Iterable, Mapping, Optional

#: The four results the loop distinguishes. There is deliberately no "fixed".
RETEST_PASS = "retest_pass"
RETEST_FAIL = "retest_fail"
FIXED_NOT_SERVING = "fixed_but_not_serving"
REGRESSED = "regressed"
DEFERRED_SESSION = "retest_deferred_session"


def serving_release(pid_cwd: str) -> Optional[str]:
    """The release basename the process on :7777 is actually running from, or None when its cwd cannot be read."""
    if not pid_cwd or not pid_cwd.strip():
        return None
    return pid_cwd.rstrip("/").rsplit("/", 1)[-1] or None


def is_serving(fix_commit: str, *, is_ancestor: Callable[[str], bool]) -> bool:
    """True when the merge that carried the fix is in the tree the running process uses.

    ``is_ancestor(commit)`` is injected (`git merge-base --is-ancestor <commit> HEAD` run IN THE SERVING RELEASE), so the
    rule is testable without a repository and cannot accidentally read the canonical checkout.
    """
    if not fix_commit:
        return False
    return bool(is_ancestor(fix_commit))


def decide(*, item_status: str, fix_commit: str | None, is_ancestor: Callable[[str], bool],
           session_required: str | None, session_now: str | None,
           check_expected: bool | None) -> str:
    """The outcome for one retest. ``check_expected`` is None when the check was not run (not serving / wrong session)."""
    if item_status == "closed":
        # a previously-closed item is re-checked by the 14-day scan
        if check_expected is False:
            return REGRESSED
        return RETEST_PASS if check_expected else DEFERRED_SESSION
    if not fix_commit or not is_serving(fix_commit, is_ancestor=is_ancestor):
        return FIXED_NOT_SERVING
    if session_required and session_now != session_required:
        return DEFERRED_SESSION
    if check_expected is None:
        return DEFERRED_SESSION
    return RETEST_PASS if check_expected else RETEST_FAIL


def transition(item: Mapping, outcome: str, *, now: str, evidence: Mapping) -> dict:
    """The state change an outcome implies (§2.6). Never writes the word "fixed"."""
    out = dict(item)
    sev = str(item.get("severity") or "P2")
    out.setdefault("history", [])
    if isinstance(out["history"], list):
        out["history"] = list(out["history"]) + [{"at": now, "outcome": outcome, "evidence": dict(evidence)}]
    if outcome == RETEST_PASS:
        out["status"] = "closed"
    elif outcome == RETEST_FAIL:
        out["status"] = "reopened"
        out["severity"] = _bump(sev)
        out["escalate"] = int(item.get("failed_retests") or 0) + 1 >= 2
        out["failed_retests"] = int(item.get("failed_retests") or 0) + 1
    elif outcome == REGRESSED:
        out["status"] = "reopened"
        out["severity"] = "P1"
        out["regressed"] = True
    # FIXED_NOT_SERVING / DEFERRED_SESSION leave the item where it was
    return out


def _bump(sev: str) -> str:
    order = ["P3", "P2", "P1", "P0"]
    return order[min(len(order) - 1, order.index(sev) + 1)] if sev in order else sev
