"""CLI: python -m scripts.cc_runtime_harness ..."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .negatives import SYNTHETIC_NOW
from .runner import HarnessConfig, run_harness


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    # scripts/cc_runtime_harness/__main__.py → repo root
    return here.parents[2]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="CC runtime validation harness")
    p.add_argument("--mode", choices=["hermetic", "candidate-preview"], default="hermetic")
    p.add_argument("--fixture-root", type=Path, default=None)
    p.add_argument("--output-dir", type=Path, default=None)
    p.add_argument("--repo-root", type=Path, default=None)
    p.add_argument("--build-sha", default=None)
    p.add_argument("--preview-base-url", default=None, help="Or set CC_RUNTIME_PREVIEW_BASE_URL (never production)")
    p.add_argument("--expected-build-sha", default=None)
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--regenerate-fixtures",
        action="store_true",
        help="DELIBERATE fixture regeneration: rewrites the tracked route ledger. "
        "Never use in CI — ordinary runs treat committed fixtures as immutable.",
    )
    args = p.parse_args(argv)

    root = (args.repo_root or _repo_root()).resolve()
    fixture_root = (args.fixture_root or (root / "fixtures" / "cc_runtime")).resolve()
    output_dir = (args.output_dir or (root / "evidence" / "cc_runtime" / "last_run")).resolve()
    build_sha = args.build_sha or os.environ.get("CC_RUNTIME_BUILD_SHA")
    if not build_sha:
        import subprocess

        build_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(root), text=True).strip()

    preview = args.preview_base_url or os.environ.get("CC_RUNTIME_PREVIEW_BASE_URL")
    if args.mode == "candidate-preview" and not preview:
        print("candidate-preview requires --preview-base-url or CC_RUNTIME_PREVIEW_BASE_URL", file=sys.stderr)
        return 2

    cfg = HarnessConfig(
        mode=args.mode,
        repo_root=root,
        fixture_root=fixture_root,
        output_dir=output_dir,
        build_sha=build_sha,
        synthetic_now=SYNTHETIC_NOW,
        preview_base_url=preview,
        expected_build_sha=args.expected_build_sha or build_sha,
        regenerate_fixtures=bool(args.regenerate_fixtures),
    )
    result = run_harness(cfg)
    payload = {
        "ok": result.ok,
        "mode": result.mode,
        "counts": result.counts,
        "failures": result.failures,
        "artifact_hashes": result.artifact_hashes,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"cc_runtime_harness: {'PASS' if result.ok else 'FAIL'} mode={result.mode}")
        print(json.dumps(result.counts, indent=2))
        if result.failures:
            print("failures:")
            for f in result.failures:
                print(" -", f)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
