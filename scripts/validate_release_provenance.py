#!/usr/bin/env python3
"""Deterministic fail-closed release-provenance validator.

Verifies that an immutable exact-main release stamps ONE authoritative
40-character source commit across every provenance artifact:

  SOURCE_COMMIT
  BUILD_SHA
  GIT_SHA
  BUILD_STAMP.json                          (build_sha / source_sha / git_sha)
  apps/command-center-v3/build-meta.json     (git_sha / source_sha / source_commit)
  apps/command-center-v3/dist/build-meta.json (same)

Any missing, malformed, or disagreeing artifact fails closed (exit 1).

This closes the stale-clone hole: a re-stamped release must never inherit an
older SOURCE_COMMIT while BUILD_SHA advances. The validator is deterministic
and side-effect free, so it is safe to run in tests and release gates.

Usage:
  python3 scripts/validate_release_provenance.py <release_dir> [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def validate(root: Path) -> tuple[bool, list[str]]:
    errors: list[str] = []

    def check(label: str, value: object, canonical: str | None) -> str | None:
        if value is None or str(value).strip() == "":
            errors.append(f"{label}: missing")
            return None
        v = str(value).strip()
        if not SHA_RE.match(v):
            errors.append(f"{label}: malformed SHA {v[:20]!r}")
            return None
        if canonical is not None and v != canonical:
            errors.append(f"{label}: {v} != canonical {canonical}")
        return v

    src_commit = check("SOURCE_COMMIT", _read_text(root / "SOURCE_COMMIT"), None)
    build_sha = check("BUILD_SHA", _read_text(root / "BUILD_SHA"), None)
    git_sha = check("GIT_SHA", _read_text(root / "GIT_SHA"), None)

    # SOURCE_COMMIT is authoritative; fall back to BUILD_SHA/GIT_SHA if it is
    # missing so remaining checks still report a precise diff.
    canonical = src_commit or build_sha or git_sha

    if canonical is not None:
        # Cross-check the root files (already format-validated above).
        if build_sha is not None and build_sha != canonical:
            errors.append(f"BUILD_SHA: {build_sha} != canonical {canonical}")
        if git_sha is not None and git_sha != canonical:
            errors.append(f"GIT_SHA: {git_sha} != canonical {canonical}")

        stamp = _read_json(root / "BUILD_STAMP.json")
        if stamp is None:
            errors.append("BUILD_STAMP.json: missing or invalid JSON")
        else:
            for k in ("build_sha", "source_sha", "git_sha"):
                check(f"BUILD_STAMP.json.{k}", stamp.get(k), canonical)

        for rel in (
            "apps/command-center-v3/build-meta.json",
            "apps/command-center-v3/dist/build-meta.json",
        ):
            meta = _read_json(root / rel)
            if meta is None:
                errors.append(f"{rel}: missing or invalid JSON")
                continue
            for k in ("git_sha", "source_sha", "source_commit"):
                check(f"{rel}.{k}", meta.get(k), canonical)

    return (len(errors) == 0, errors)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("release_dir")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.release_dir)
    if not root.is_dir():
        print(f"FAIL: not a directory: {root}", file=sys.stderr)
        return 1

    ok, errors = validate(root)
    if args.json:
        print(json.dumps({"ok": ok, "errors": errors}, indent=2))
    else:
        if ok:
            print("Release provenance: PASS")
        else:
            print("Release provenance: FAIL")
            for e in errors:
                print(f"  [FAIL] {e}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
