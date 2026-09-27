#!/usr/bin/env python3
"""Served-release receipt for the options order gates (operator work order 2026-09-27).

Runs the desk-side options gate test files AS THEY EXIST IN A RELEASE TREE (default the
served CURRENT release), records per-test pass/fail against that tree's GIT_SHA and
BUILD_STAMP.json, and names the gate tests that are NOT yet in the release -- so the
receipt says what the served code proves, not what the dev tree proves.

Hermetic by construction: pytest only, PYTHONDONTWRITEBYTECODE=1 -p no:cacheprovider, no
network, no DB, no brokers.* import. The matrix test's doc export is deselected so the run
writes nothing into the release tree.

    .venv/bin/python scripts/options_gate_proof.py
    .venv/bin/python scripts/options_gate_proof.py --release-root ~/trade-ai-releases/portfolio-server/CURRENT

Writes data/audit/options_gate_proof/<utc>-<sha7>.json and prints a summary.
"""
from __future__ import annotations

# Receipt script run by the operator or a CI step; nothing imports it (dark-contract guard).
NO_CONSUMER_REASON = "operator/CI-invoked served-release receipt (scripts/options_gate_proof.py); emits OptionsGateProof@v1 to data/audit, no importer by design"

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RELEASE = Path(os.path.expanduser("~/trade-ai-releases/portfolio-server/CURRENT"))
AUDIT_DIR = PROJECT_ROOT / "data" / "audit" / "options_gate_proof"

# The desk-side gate proofs, in the order the work order lists them. Each is a test FILE
# path relative to the release root; ``deselect`` names test ids that write to the tree.
GATE_TESTS = [
    {"file": "tests/test_options_order_gates_20260927.py",
     "proves": "preflight_desk_gate refuses before any broker call; submit-mode fails closed on unknown inputs"},
    {"file": "tests/test_options_hard_risk_blocks.py",
     "proves": "hard risk block codes (earnings, bs_estimate, quote_stale, advisory empty)"},
    {"file": "tests/test_options_hard_risk_blocks_matrix.py",
     "proves": "stable block-code matrix incl. *_unknown fail-closed codes",
     "deselect": ["tests/test_options_hard_risk_blocks_matrix.py::test_export_matrix_doc"]},
    {"file": "tests/test_options_action_gating.py", "proves": "action gating on options cards"},
    {"file": "tests/test_options_validate_20260926.py", "proves": "fresh VALIDATED result required for approval"},
    {"file": "tests/test_options_thesis_20260926.py", "proves": "thesis bar and CIO decision blocks"},
    {"file": "tests/test_options_thesis_lifecycle_20260926.py", "proves": "lifecycle stages incl. ARCHIVED_ABANDONED"},
    {"file": "tests/test_options_credit_spread_rr_floor_20260925.py", "proves": "credit spread R:R floor"},
    {"file": "tests/test_options_wave_b_20260927.py", "proves": "per-leg liquidity, combined exposure"},
    {"file": "tests/test_options_economics_20260927.py", "proves": "honest economics"},
    {"file": "tests/test_options_fill_truth_20260927.py", "proves": "executable credit, leg quote timestamps"},
]

_SUMMARY_RE = re.compile(r"(?:(\d+) passed)?(?:, )?(?:(\d+) failed)?(?:, )?(?:(\d+) error)?", re.I)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _counts(tail: str) -> dict:
    out = {"passed": 0, "failed": 0, "errors": 0, "deselected": 0}
    for line in tail.splitlines()[::-1]:
        if " passed" in line or " failed" in line or " error" in line or "no tests ran" in line:
            for key, pat in (("passed", r"(\d+) passed"), ("failed", r"(\d+) failed"),
                             ("errors", r"(\d+) error"), ("deselected", r"(\d+) deselected")):
                m = re.search(pat, line)
                if m:
                    out[key] = int(m.group(1))
            break
    return out


def run(release_root: Path, python: str, timeout: int = 600) -> dict:
    root = release_root.resolve()
    git_sha = _read(root / "GIT_SHA")
    stamp_raw = _read(root / "BUILD_STAMP.json")
    try:
        stamp = json.loads(stamp_raw) if stamp_raw else None
    except ValueError:
        stamp = {"_invalid": stamp_raw[:200] if stamp_raw else None}
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", TRADE_AI_CI="1")
    results = []
    for spec in GATE_TESTS:
        rel = spec["file"]
        entry = {"file": rel, "proves": spec["proves"]}
        if not (root / rel).is_file():
            entry.update({"status": "not_in_release", "note": "test file is not in this release tree"})
            results.append(entry)
            continue
        cmd = [python, "-m", "pytest", "-q", "-p", "no:cacheprovider", rel]
        for d in spec.get("deselect") or []:
            cmd += ["--deselect", d]
        try:
            proc = subprocess.run(cmd, cwd=str(root), env=env, capture_output=True, text=True, timeout=timeout)
            tail = "\n".join((proc.stdout or "").strip().splitlines()[-3:])
            counts = _counts(proc.stdout or "")
            entry.update({"status": "pass" if proc.returncode == 0 else "fail", "returncode": proc.returncode,
                          **counts, "tail": tail})
            if proc.returncode != 0:
                entry["stderr_tail"] = "\n".join((proc.stderr or "").strip().splitlines()[-5:])
        except subprocess.TimeoutExpired:
            entry.update({"status": "timeout", "returncode": None})
        results.append(entry)
    ran = [r for r in results if r["status"] in ("pass", "fail", "timeout")]
    receipt = {
        "schema": "OptionsGateProof@v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "release_root": str(root),
        "release_root_as_given": str(release_root),
        "git_sha": git_sha,
        "build_stamp": stamp,
        "python": python,
        "pytest_args": "-q -p no:cacheprovider (PYTHONDONTWRITEBYTECODE=1)",
        "tests": results,
        "summary": {
            "files_in_release": len(ran),
            "files_not_in_release": len([r for r in results if r["status"] == "not_in_release"]),
            "files_passed": len([r for r in ran if r["status"] == "pass"]),
            "files_failed": len([r for r in ran if r["status"] != "pass"]),
            "tests_passed": sum(r.get("passed", 0) for r in ran),
            "tests_failed": sum(r.get("failed", 0) + r.get("errors", 0) for r in ran),
        },
        "authority": "READ_ONLY_EVIDENCE",
    }
    return receipt


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--release-root", default=str(DEFAULT_RELEASE))
    ap.add_argument("--out-dir", default=str(AUDIT_DIR))
    ap.add_argument("--python", default=sys.executable, help="interpreter used to run pytest (default: this one)")
    ap.add_argument("--no-write", action="store_true", help="print only; do not write the receipt")
    args = ap.parse_args(argv)
    root = Path(os.path.expanduser(args.release_root))
    if not root.is_dir():
        print(f"release root not found: {root}", file=sys.stderr)
        return 2
    receipt = run(root, args.python)
    sha7 = (receipt.get("git_sha") or "nosha")[:7]
    out_path = None
    if not args.no_write:
        out_dir = Path(os.path.expanduser(args.out_dir))
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = out_dir / f"{ts}-{sha7}.json"
        out_path.write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
    s = receipt["summary"]
    print(f"options gate proof  release={receipt['release_root']}  sha={receipt.get('git_sha')}")
    stamp = receipt.get("build_stamp") or {}
    if isinstance(stamp, dict) and stamp.get("stamped_at"):
        print(f"  build stamp: {stamp.get('label')} stamped_at={stamp.get('stamped_at')} branch={stamp.get('branch')}")
    for r in receipt["tests"]:
        if r["status"] == "not_in_release":
            print(f"  [NOT IN RELEASE] {r['file']}")
        else:
            print(f"  [{r['status'].upper():4}] {r['file']}  passed={r.get('passed', 0)} failed={r.get('failed', 0)}"
                  f"{' deselected=' + str(r['deselected']) if r.get('deselected') else ''}")
    print(f"  files: {s['files_passed']}/{s['files_in_release']} passed, {s['files_not_in_release']} not in release; "
          f"tests: {s['tests_passed']} passed, {s['tests_failed']} failed")
    if out_path:
        print(f"  receipt: {out_path}")
    return 0 if s["files_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
