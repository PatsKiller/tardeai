#!/usr/bin/env python3
"""PR metadata gate for changes with a shared operational blast radius.

Use the BASE list plus immutable minimums: deleting a path from the PR's own
config cannot launder that change. Reads local git/event metadata only.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
import re
import subprocess

MINIMUM = ["scripts/safe_flock.sh", "scripts/*cron*.sh", "scripts/*wrapper*.sh",
           "scripts/run_*.sh", "scripts/pipelines/*.sh",
           "scripts/*deploy*.sh", "scripts/*release*.py", "scripts/lib/release*.py",
           "crontab*.txt", "**/crontab*.txt", "**/*cron*template*",
           "config/shared_infra_paths.json", "scripts/check_shared_infra_pr.py",
           "config/release_wrapper_preflight.json", "config/cron_outage_watchdog.json",
           ".github/workflows/shared-infra-review.yml"]


def assess(paths: list[str], title: str, body: str, patterns: list[str]) -> dict:
    shared = sorted(path for path in paths if any(fnmatch.fnmatchcase(path, pattern) for pattern in MINIMUM + patterns))
    errors = []
    if shared and not title.startswith("[shared-infra] "):
        errors.append("PR title must start '[shared-infra] '")
    if shared and not re.search(r"(?im)^real-layout proof\s*:\s*\S.{10,}$", body):
        errors.append("PR body must name the command/artifact in a Real-layout proof: line")
    return {"ok": not errors, "shared_infra": bool(shared), "paths": shared, "errors": errors,
            "batch_rule": "operator reviews separately; coordinator excludes from mixed batches"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--event-file", required=True, type=Path)
    args = parser.parse_args()
    def git(*parts):
        return subprocess.run(["git", *parts], check=True, capture_output=True, text=True).stdout
    event = json.loads(args.event_file.read_text())
    pr = event.get("pull_request") or {}
    # Never load the candidate list as the sole authority for its own change.
    try:
        cfg = json.loads(git("show", f"{args.base}:config/shared_infra_paths.json"))
        patterns = cfg["paths"]
        if not isinstance(patterns, list) or not all(isinstance(x, str) for x in patterns):
            raise ValueError("base path list malformed")
    except subprocess.CalledProcessError:
        patterns = []  # First introduction still has the immutable minimum set.
    paths = git("diff", "--name-only", f"{args.base}...{args.head}").splitlines()
    result = assess(paths, str(pr.get("title") or ""), str(pr.get("body") or ""), patterns)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
