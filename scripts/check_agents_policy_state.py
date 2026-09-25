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

Usage:  python3 scripts/check_agents_policy_state.py [--path AGENTS.md]
                 [--on-main | --on-branch]
Default ref detection: GITHUB_REF == refs/heads/main => on-main, else branch.
Exit 0 = ok, 1 = violations (printed). Reads one file; writes nothing.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--path", default="AGENTS.md")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--on-main", action="store_true")
    g.add_argument("--on-branch", action="store_true")
    args = ap.parse_args(argv)
    on_main = args.on_main or (not args.on_branch and os.environ.get("GITHUB_REF") == "refs/heads/main")
    text = Path(args.path).read_text(encoding="utf-8")
    errors = check(text, on_main=on_main)
    where = "main" if on_main else "branch"
    if errors:
        print(f"AGENTS policy state FAILED ({where}):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(
        f"AGENTS policy state ok ({where}): {control_block(text).get('Policy-Version')} "
        f"{control_block(text).get('Status')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
