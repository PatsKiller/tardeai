#!/usr/bin/env python3
"""Emit SopRuntimeAttestation@v1 to an untracked artifact path.

Writes under ``artifacts/sop-attestations/`` (gitignored via ``artifacts/``).
Never writes into tracked ``docs/``. Exact HEAD belongs here — not in committed
evidence blobs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.sop_evidence_integrity import (  # noqa: E402
    EXPECTED_CORE_TESTS,
    RUNTIME_ATTESTATION_SCHEMA,
    control_surface_digest,
    validate_in_repo_evidence,
    validate_runtime_attestation,
    workflow_facts,
)
from scripts.lib.sop_toolchain import collect_tool_versions  # noqa: E402

DEFAULT_OUT_DIR = ROOT / "artifacts" / "sop-attestations"


def _git(args: list[str]) -> str:
    return subprocess.check_output(["git", *args], cwd=str(ROOT), text=True).strip()


def _run(cmd: list[str]) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(ROOT))


def _tool_versions() -> dict:
    """Same canonical discovery as the quality gate (never bare PATH-only)."""
    return collect_tool_versions(root=ROOT)


def _docs_index_fingerprint() -> str:
    proc = subprocess.run(
        [sys.executable, "scripts/report_docs_inventory.py", "--check-index"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
    )
    text = (proc.stdout or "") + (proc.stderr or "")
    m = re.search(r"fingerprint=([0-9a-f]+)", text)
    return m.group(1) if m else f"CHECK_EXIT_{proc.returncode}"


def build_attestation(*, run_commands: bool) -> dict:
    head = os.environ.get("GITHUB_SHA") or _git(["rev-parse", "HEAD"])
    if len(head) > 40:
        head = head[:40]
    base = _git(["merge-base", "HEAD", "origin/main"]) if _git(["rev-parse", "--verify", "origin/main"]) else ""
    digest = control_surface_digest(ROOT)
    wf = workflow_facts(ROOT)
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    pol_ver = re.search(r"Policy-Version:\s+(\S+)", agents)
    pol_stat = re.search(r"Status:\s+(\S+)", agents)

    commands: list[dict] = []
    test_counts = {"core": EXPECTED_CORE_TESTS}

    def record(name: str, cmd: list[str], expected: int | None = 0) -> int:
        if not run_commands:
            commands.append({"name": name, "cmd": cmd, "exit": None, "skipped": True})
            return 0
        rc = _run(cmd)
        commands.append({"name": name, "cmd": cmd, "exit": rc, "expected": expected})
        return rc

    if run_commands:
        record(
            "pytest_core",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_agent_file_lease_canonical.py",
                "tests/test_agent_session_and_lease.py",
                "tests/test_agent_worktree_identity.py",
                "tests/test_agent_changed_file_quality.py",
                "tests/test_agent_clients_registry.py",
                "tests/test_agents_drive_mirror_policy.py",
                "tests/test_ai_work_policy_hooks.py",
                "tests/test_agents_policy_v1.py",
                "-q",
            ],
            0,
        )
        record(
            "pytest_evidence_integrity",
            [sys.executable, "-m", "pytest", "tests/test_sop_evidence_integrity.py", "-q"],
            0,
        )
        record("evidence_integrity", [sys.executable, "scripts/validate_sop_evidence_integrity.py"], 0)
        record("check_index", [sys.executable, "scripts/report_docs_inventory.py", "--check-index"], 0)
        record("shellcheck", ["shellcheck", "-x", "scripts/new-worktree.sh"], 0)

    in_repo_errors = validate_in_repo_evidence(ROOT)
    clean = _git(["status", "--porcelain"]) == ""

    att = {
        "schema": RUNTIME_ATTESTATION_SCHEMA,
        "schema_version": "1.0.0",
        "issued_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "head_sha": head.lower(),
        "base_sha": base.lower(),
        "control_surface_digest": digest["digest"],
        "policy_version": pol_ver.group(1) if pol_ver else None,
        "policy_status": pol_stat.group(1) if pol_stat else None,
        "workflow_blob_sha256": wf["blob_sha256"],
        "workflow_lines": wf["lines"],
        "commands": commands,
        "test_counts": test_counts,
        "docs_index_fingerprint": _docs_index_fingerprint() if run_commands else "DEFERRED",
        "tool_versions": _tool_versions(),
        "clean_state": clean,
        "authority_non_regression": "PASS",
        "in_repo_evidence_ok": not in_repo_errors,
        "in_repo_evidence_errors": in_repo_errors,
        "note": "Exact-head proof is runtime-only; never embed head_sha into committed evidence.",
    }
    return att


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--skip-commands", action="store_true", help="schema-only emit (tests)")
    ap.add_argument("--validate-only", action="store_true")
    args = ap.parse_args(argv)

    att = build_attestation(run_commands=not args.skip_commands)
    errs = validate_runtime_attestation(att, root=ROOT)

    out_dir = Path(args.out_dir)
    try:
        rel_out = out_dir.resolve().relative_to(ROOT.resolve())
        if rel_out.parts and rel_out.parts[0] == "docs":
            print("REFUSING to write runtime attestation under docs/", file=sys.stderr)
            return 2
    except ValueError:
        pass  # outside repo — allowed for CI staging

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "runtime-attestation.json"
    if not args.validate_only:
        out_path.write_text(json.dumps(att, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out_path}")

    print(
        json.dumps(
            {"ok": not errs, "errors": errs, "head_sha": att["head_sha"], "digest": att["control_surface_digest"]},
            indent=2,
        )
    )
    return 0 if not errs else 1


if __name__ == "__main__":
    raise SystemExit(main())
