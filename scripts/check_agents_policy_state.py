#!/usr/bin/env python3
"""Post-merge policy-state check for AGENTS.md.

Why (governance truth repair, 2026-09-25): AGENTS.md 1.2.7 merged on
2026-09-24 as a PATCH that "rides APPROVE_AGENTS_POLICY_1_2_0" and is ACTIVE on
merge, yet the header still said ``Status: PROPOSED / Effective-Date: PENDING``
on main, and the version history carried two 1.2.6 rows and six 1.2.0 rows.
tests/test_agents_policy_v1.py checks the header's internal consistency; it
cannot know whether the text is on a branch or already merged. This check can.

Rules
-----
1. One row per version in the version-history table (one version, one
   activation event).
2. The current version's row status agrees with the header status
   (ACTIVE header ⇔ row begins with ACTIVE; PROPOSED header ⇔ row begins with
   PROPOSED).
3. On ``main`` (post-merge) a ``PROPOSED`` header is allowed ONLY when the
   current row names a separate operator ratification that has not happened
   (approval cell contains ``PENDING`` and an ``APPROVE_`` token, and does not
   say it rides an earlier ratification). A version that "rides" a prior
   approval is ACTIVE on merge and must say so.
4. On a branch (pre-merge) ``PROPOSED`` is always allowed; ``ACTIVE`` is
   allowed only for a version that is already on main or rides a prior
   ratification.
5. (25.0.0) Every change to AGENTS.md bumps the version: when the text differs
   from the base revision, ``Policy-Version`` and ``Last-Reviewed`` must both
   differ from the base and the new version must have a history row. Why: PR
   #2208 (2026-10-26) rewrote §25.10 and §28.12 with no bump and no token, and
   nothing failed (review 2026-10-27 H2). The base is ``--base REF`` or, in a
   pull_request CI run, the merge-base of HEAD and ``origin/$GITHUB_BASE_REF``.
6. (policy freshness, operator 2026-10-28) A PR is not built under an old policy: when the base branch's tip carries
   a higher ``Policy-Version`` than the PR head, the PR fails with ``STALE_POLICY`` unless the PR itself changes the
   version (head differs from the merge-base), which rule 5 then governs. The base tip is ``--base REF`` or
   ``origin/$GITHUB_BASE_REF``; with neither (push to main, local run) the rule is skipped and says so.
   Version parsing is shared with every other gate: ``scripts/lib/policy_freshness.py``.

Usage:  python3 scripts/check_agents_policy_state.py [--path AGENTS.md]
                 [--on-main | --on-branch] [--base REF]
Default ref detection: GITHUB_REF == refs/heads/main => on-main, else branch.
Exit 0 = ok, 1 = violations (printed). Reads one file; writes nothing.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import policy_freshness as PF  # noqa: E402

ROW_RE = re.compile(r"^\|\s*(\d+\.\d+\.\d+)\s*\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)\|(.*)$")
RIDES_RE = re.compile(r"\brides?\b", re.IGNORECASE)


def control_block(text: str) -> dict[str, str]:
    m = re.search(r"```\n(Policy-Version:.*?)```", text, re.DOTALL)
    out: dict[str, str] = {}
    for line in (m.group(1) if m else "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def version_rows(text: str) -> list[dict[str, str]]:
    rows = []
    for line in text.splitlines():
        m = ROW_RE.match(line)
        if m:
            rows.append(
                {
                    "version": m.group(1),
                    "date": m.group(2).strip(),
                    "status": m.group(3).strip(),
                    "cls": m.group(4).strip(),
                    "rest": m.group(5),
                }
            )
    return rows


def check(text: str, *, on_main: bool) -> list[str]:
    errors: list[str] = []
    cb = control_block(text)
    version = cb.get("Policy-Version")
    status = cb.get("Status")
    if not version or not status:
        return ["control block missing Policy-Version or Status"]
    rows = version_rows(text)
    seen: dict[str, int] = {}
    for r in rows:
        seen[r["version"]] = seen.get(r["version"], 0) + 1
    for v, n in sorted(seen.items()):
        if n > 1:
            errors.append(f"version {v} has {n} history rows; one version = one activation event")
    current = [r for r in rows if r["version"] == version]
    if not current:
        errors.append(f"no version-history row for current Policy-Version {version}")
        return errors
    row = current[0]
    row_status = row["status"].upper()
    if status == "ACTIVE" and not row_status.startswith("ACTIVE"):
        errors.append(f"header says ACTIVE but the {version} row says {row['status']!r}")
    if status == "PROPOSED" and not row_status.startswith("PROPOSED"):
        errors.append(f"header says PROPOSED but the {version} row says {row['status']!r}")
    approval = row["rest"]
    rides_prior = bool(RIDES_RE.search(approval)) or bool(RIDES_RE.search(row["status"]))
    awaits_new_token = ("PENDING" in approval) and ("APPROVE_" in approval) and not rides_prior
    if on_main and status == "PROPOSED" and not awaits_new_token:
        errors.append(
            f"{version} is PROPOSED on main but its row names no separate pending operator "
            "ratification (it rides a prior approval, so it became ACTIVE on merge) — set "
            "Status: ACTIVE and the merge timestamp as Effective-Date"
        )
    if status == "ACTIVE" and cb.get("Effective-Date", "PENDING") == "PENDING":
        errors.append("ACTIVE policy with Effective-Date PENDING")
    return errors


def check_bump(text: str, base_text: str | None) -> list[str]:
    """Rule 5: a changed AGENTS.md carries a new Policy-Version, a new Last-Reviewed and that version's row."""
    if base_text is None or base_text == text:
        return []
    errors: list[str] = []
    cb, old = control_block(text), control_block(base_text)
    version, old_version = cb.get("Policy-Version"), old.get("Policy-Version")
    if not version or version == old_version:
        errors.append(
            f"AGENTS.md changed but Policy-Version is still {old_version}; every change bumps the version "
            "(document version policy)"
        )
    if cb.get("Last-Reviewed") == old.get("Last-Reviewed"):
        errors.append("AGENTS.md changed but Last-Reviewed did not")
    if version and not any(r["version"] == version for r in version_rows(text)):
        errors.append(f"AGENTS.md changed but has no version-history row for {version}")
    return errors


def check_not_behind(head_text: str, base_tip_text: str | None, merge_base_text: str | None) -> list[str]:
    """Rule 6: the PR head's Policy-Version is not behind the base branch tip's, unless the PR changes the version."""
    if base_tip_text is None:
        return []
    head_v = PF.parse_policy_version(head_text)
    tip_v = PF.parse_policy_version(base_tip_text)
    mb_v = PF.parse_policy_version(merge_base_text) if merge_base_text is not None else None
    if merge_base_text is not None and head_v != mb_v:
        return []  # the PR bumps (or otherwise changes) the version itself: rule 5 governs it
    if PF.version_behind(head_v, tip_v):
        return [
            f"STALE_POLICY: this PR's AGENTS.md is {head_v}, the base branch has {tip_v}; rebase onto fresh "
            "origin/main, re-read AGENTS.md §0, and push again (the PR was built under an older policy)"
        ]
    return []


def base_tip_text_for(base: str | None, rel_path: str) -> tuple[str | None, str]:
    """The AGENTS.md text at the base branch TIP (not the merge-base): what main says now."""
    if not base:
        ref = os.environ.get("GITHUB_BASE_REF")
        if not ref:
            return None, "no base"
        base = f"origin/{ref}"
    text = _git("show", f"{base}:{rel_path}")
    return (text, base) if text is not None else (None, f"base {base} unreadable")


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def base_text_for(base: str | None, rel_path: str) -> tuple[str | None, str]:
    """The AGENTS.md text at the base revision, or None when no base applies (push to main, local run)."""
    if not base:
        ref = os.environ.get("GITHUB_BASE_REF")
        if not ref:
            return None, "no base"
        base = f"origin/{ref}"
    mb = _git("merge-base", "HEAD", base)
    rev = mb.strip() if mb else base
    text = _git("show", f"{rev}:{rel_path}")
    if text is None:
        return None, f"base {base} unreadable"
    return text, rev[:12]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--path", default="AGENTS.md")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--on-main", action="store_true")
    g.add_argument("--on-branch", action="store_true")
    ap.add_argument(
        "--base",
        default=None,
        help="git ref to compare against (rule 5); default merge-base with "
        "origin/$GITHUB_BASE_REF in a pull_request run, else no comparison",
    )
    args = ap.parse_args(argv)
    on_main = args.on_main or (not args.on_branch and os.environ.get("GITHUB_REF") == "refs/heads/main")
    text = Path(args.path).read_text(encoding="utf-8")
    errors = check(text, on_main=on_main)
    base_text, base_label = base_text_for(args.base, args.path)
    errors += check_bump(text, base_text)
    tip_text, tip_label = base_tip_text_for(args.base, args.path)
    errors += check_not_behind(text, tip_text, base_text)
    where = "main" if on_main else "branch"
    if errors:
        print(f"AGENTS policy state FAILED ({where}):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(
        f"AGENTS policy state ok ({where}): {control_block(text).get('Policy-Version')} "
        f"{control_block(text).get('Status')} (version bump vs {base_label}: ok; "
        + (
            f"not behind {tip_label} ({PF.parse_policy_version(tip_text)}): ok)"
            if tip_text is not None
            else f"freshness vs base tip: skipped, {tip_label})"
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
