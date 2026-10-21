#!/usr/bin/env python3
"""Read-only check: a release tree's build stamp, git HEAD, and file blobs.

A live release directory may be a git worktree whose HEAD was fast-forwarded
after the process started. The served pin is the build stamp plus the blobs
on disk. This command does not checkout, merge, or rewrite anything.

Exit codes:
  0  every checked path matches the stamp commit
  2  git HEAD disagrees with the stamp (files may still match the stamp)
  3  a worktree file disagrees with the stamp commit
  4  the stamp commit is not in this git dir, so blob comparison is not possible
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Paths whose served bytes have been wrong relative to git HEAD in production.
DEFAULT_PATHS = (
    "scripts/lib/buy_ready_options_alternatives.py",
    "scripts/options_desk_enterprise.py",
    "scripts/lib/cio_nightly_reflection.py",
    "scripts/brokers/options_execution_policy.py",
    "scripts/portfolio_server.py",
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def read_stamp(repo: Path, explicit: str | None) -> str:
    if explicit:
        return explicit.strip()
    meta = repo / "dist" / "build-meta.json"
    if not meta.is_file():
        meta = repo / "apps" / "command-center-v3" / "dist" / "build-meta.json"
    if meta.is_file():
        data = json.loads(meta.read_text(encoding="utf-8"))
        sha = str(data.get("git_sha") or data.get("source_commit") or "").strip()
        if sha:
            return sha
    for name in ("SOURCE_COMMIT", "BUILD_SHA", "GIT_SHA"):
        path = repo / name
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip().split()
            if text:
                return text[0]
    raise SystemExit("no build stamp: pass --stamp or provide build-meta.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--stamp", default=None)
    parser.add_argument("--path", action="append", dest="paths", default=None)
    args = parser.parse_args(argv)
    repo = args.release.resolve()
    if not repo.is_dir():
        print(f"not a directory: {repo}", file=sys.stderr)
        return 4
    stamp = read_stamp(repo, args.stamp)
    paths = tuple(args.paths) if args.paths else DEFAULT_PATHS
    head = _git(repo, "rev-parse", "HEAD")
    if head.returncode != 0:
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": "no_git_head",
                    "stamp": stamp,
                    "detail": head.stderr.strip()[:200],
                }
            )
        )
        return 4
    head_sha = head.stdout.strip()
    stamp_ok = _git(repo, "cat-file", "-e", f"{stamp}^{{commit}}")
    if stamp_ok.returncode != 0:
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": "stamp_not_in_repo",
                    "stamp": stamp,
                    "head": head_sha,
                }
            )
        )
        return 4
    rows = []
    file_mismatch = False
    for rel in paths:
        work = _git(repo, "hash-object", rel)
        committed = _git(repo, "rev-parse", f"{stamp}:{rel}")
        if work.returncode != 0 or committed.returncode != 0:
            rows.append(
                {
                    "path": rel,
                    "error": (work.stderr or committed.stderr).strip()[:160],
                }
            )
            file_mismatch = True
            continue
        work_sha = work.stdout.strip()
        stamp_blob = committed.stdout.strip()
        match = work_sha == stamp_blob
        if not match:
            file_mismatch = True
        rows.append(
            {
                "path": rel,
                "worktree": work_sha,
                "stamp_blob": stamp_blob,
                "match": match,
            }
        )
    head_match = head_sha.startswith(stamp) or stamp.startswith(head_sha)
    report = {
        "ok": head_match and not file_mismatch,
        "stamp": stamp,
        "head": head_sha,
        "head_matches_stamp": head_match,
        "paths": rows,
    }
    print(json.dumps(report, indent=2))
    if file_mismatch:
        return 3
    if not head_match:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
