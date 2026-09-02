#!/usr/bin/env python3
"""Deterministic changed-file quality floor (SOP Stage 6).

Exit 0 only when all applicable gates pass. Skipped tools → NOT_APPLICABLE
printed, never silent success. Does not mass-format legacy files.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> int:
    print("+", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(ROOT))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--paths", nargs="*", default=[], help="explicit changed paths")
    args = ap.parse_args(argv)
    paths = [Path(p) for p in args.paths]
    if not paths:
        # default: git diff against merge-base with origin/main if available
        try:
            base = subprocess.check_output(
                ["git", "merge-base", "HEAD", "origin/main"], cwd=ROOT, text=True).strip()
            out = subprocess.check_output(
                ["git", "diff", "--name-only", base], cwd=ROOT, text=True)
            paths = [Path(p) for p in out.splitlines() if p.strip()]
        except Exception:  # noqa: BLE001
            print("NOT_APPLICABLE: no paths and merge-base unavailable")
            return 0

    rc = 0
    # diff --check
    if _run(["git", "diff", "--check"] + [str(p) for p in paths if p.exists()]) != 0:
        rc = 1

    py = [p for p in paths if p.suffix == ".py" and p.exists()]
    if py:
        # ruff if present
        ruff = subprocess.call(["ruff", "--version"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if ruff == 0:
            if _run(["ruff", "check", *[str(p) for p in py]]) != 0:
                rc = 1
        else:
            print("NOT_APPLICABLE: ruff not installed")
    else:
        print("NOT_APPLICABLE: no python paths")

    # registry validate when touched
    if any("agent_clients" in str(p) for p in paths):
        from scripts.lib.agent_clients_registry import load_registry, validate_registry
        errs = validate_registry(load_registry())
        if errs:
            print("FAIL registry", errs)
            rc = 1
        else:
            print("PASS agent_clients registry")

    # secret scan positive-control note (real scan uses existing check_no_secrets)
    if (ROOT / "scripts" / "check_no_secrets.py").is_file():
        if _run([sys.executable, "scripts/check_no_secrets.py"]) != 0:
            rc = 1
    else:
        print("NOT_APPLICABLE: check_no_secrets.py missing")

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
