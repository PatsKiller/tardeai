#!/usr/bin/env python3
"""Verify none/proposed/ratified stages in unique isolated exports; never delete or publish."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from common import HERE, apply_proposed, export_base, metadata, ratify_text, run, verify_digests


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, default=Path.home() / "trade-ai-v12-rebuild/trade-ai-v12-rebuild")
    ap.add_argument("--stage", choices=("none", "proposed", "ratified", "all"), default="all")
    a = ap.parse_args()
    verify_digests()
    scratch = Path.home() / ".cache/rtc/codex-wp15-20261023"
    scratch.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix="verification-", dir=scratch))
    stages = ("none", "proposed", "ratified") if a.stage == "all" else (a.stage,)
    results = []
    py = os.environ.get("PY", str(a.repo / ".venv/bin/python"))
    for stage in stages:
        dest = evidence / stage
        dest.mkdir()
        export_base(a.repo, dest)
        run("git", "init", "-q", cwd=dest)
        run("git", "add", "-A", cwd=dest)
        run(
            "git",
            "-c",
            "user.name=WP15 fixture",
            "-c",
            "user.email=fixture@local",
            "commit",
            "-qm",
            "isolated base",
            cwd=dest,
        )
        if stage != "none":
            apply_proposed(dest)
        if stage == "ratified":
            path = dest / "AGENTS.md"
            path.write_text(
                ratify_text(
                    path.read_text(), pr="99999", sha="a" * 40, comment_id="1", comment_at="2026-10-24T02:00:00Z"
                )
            )
        run("git", "add", "-A", cwd=dest)
        env = dict(os.environ, PY=py, TRADE_AI_CI="1", TMPDIR=str(scratch))
        log = evidence / (stage + ".log")
        with log.open("w") as stream:
            proc = subprocess.run(
                ["bash", str(HERE / "checks202.sh")], cwd=dest, env=env, stdout=stream, stderr=subprocess.STDOUT
            )
        result = {
            "stage": stage,
            "returncode": proc.returncode,
            "log": str(log),
            "fixture": str(dest),
            "live_effects": False,
        }
        results.append(result)
        print(json.dumps(result), flush=True)
    receipt = {
        "schema": "AgentsPolicyPackageVerification@v1",
        "version": "20.2.0",
        "base_sha": metadata()["base_sha"],
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "fixture_approval": "SYNTHETIC; NOT AN OPERATOR RATIFICATION",
        "results": results,
        "passed": all(x["returncode"] == 0 for x in results),
    }
    (evidence / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("receipt", evidence / "receipt.json")
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
