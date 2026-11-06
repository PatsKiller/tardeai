#!/usr/bin/env python3
"""Design reference + removal guard for a PR (AGENTS.md §28.13 proposed, design/README.md).

    python3 scripts/check_design_reference.py --base origin/main            # body from $GITHUB_EVENT_PATH
    python3 scripts/check_design_reference.py --base origin/main --body-file body.md
    python3 scripts/check_design_reference.py --body-file b.md --changed-file files.txt --diff-file d.diff   # git-free

A PR that changes UI under apps/command-center-v3/src must cite ``Design: <page>/vNNN`` (APPROVED or IMPLEMENTING)
or ``Design: none``. Every nav item, route, tab or panel the diff removes or hides must be listed in the cited
version's SPEC.md removal list. Exit 0 pass, 1 refused, 2 could not run.

AUTHORITY: READ_ONLY_ADVISORY — reads git, the event payload and design/.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import design_checks as dc  # noqa: E402


def _body(args) -> str | None:
    if args.body_file:
        return Path(args.body_file).read_text(encoding="utf-8")
    event = os.environ.get("GITHUB_EVENT_PATH")
    if event and Path(event).is_file():
        payload = json.loads(Path(event).read_text(encoding="utf-8"))
        pr = payload.get("pull_request")
        if isinstance(pr, dict):
            return pr.get("body") or ""
    return None


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True, timeout=60).stdout


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="origin/main", help="merge base ref for git diff <base>...HEAD")
    ap.add_argument("--body-file")
    ap.add_argument("--changed-file", help="newline-separated changed paths (instead of git)")
    ap.add_argument("--diff-file", help="unified diff (instead of git)")
    args = ap.parse_args(argv)
    try:
        body = _body(args)
        if body is None:
            print("check_design_reference: no PR body (not a pull_request event and no --body-file); nothing to check")
            return 0
        if args.changed_file:
            changed = [x.strip() for x in Path(args.changed_file).read_text(encoding="utf-8").splitlines() if x.strip()]
        else:
            changed = [x for x in _git("diff", "--name-only", f"{args.base}...HEAD").splitlines() if x]
        ui = [f for f in changed if dc.is_ui_file(f)]
        if args.diff_file:
            diff = Path(args.diff_file).read_text(encoding="utf-8")
        else:
            diff = _git("diff", "-U0", f"{args.base}...HEAD", "--", *ui) if ui else ""
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"check_design_reference: could not run: {exc}", file=sys.stderr)
        return 2
    errors, cited = dc.check_reference(body, changed)
    if not errors and ui:
        errors = dc.check_removals(diff, cited)
    for e in errors:
        print("REFUSED: " + e)
    refs = dc.design_refs(body)
    print(f"check_design_reference: {'FAIL' if errors else 'PASS'} — {len(ui)} UI file(s), Design: "
          f"{', '.join(refs) or '(none cited)'}; {len(dc.surface_changes(diff)) if ui else 0} surface removal/hide(s) found")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
