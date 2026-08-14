"""Research governance — PR scope guard (PR-R1).

Turns collision avoidance into an enforceable invariant. Given a base SHA (from
`RESEARCH_GOVERNANCE_BUILD_BASELINE.md`), inspect `git diff --name-only
BASE_SHA...HEAD`. R1 permits ONLY an explicit allowlist. Any off-limits file in
the denylist, or any file not in the allowlist, fails the guard.

Usage:
    python scripts/lib/research_governance/pr_scope_guard.py

    # or run the pure evaluation in-process:
    pr_scope_guard.evaluate([...changed files...])

Exit code 0 on PASS, 1 on FAIL.
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Sequence

# Explicit R1 allowlist. Nothing outside this set may change in R1.
ALLOWLIST_PATTERNS: List[str] = [
    "scripts/lib/research_governance/*",
    "scripts/lib/research_governance/**",
    "tests/test_research_governance*",
    ".github/workflows/research-governance-ci.yml",
    "config/cio_research_source_catalog.json",
    "docs/investment-office/RESEARCH_GOVERNANCE*",
    "docs/investment-office/BOOK_KNOWLEDGE_INVENTORY.md",
    "scripts/run_research_governance_acceptance.py",
]

# Off-limits shared CIO / retrieval / release files. Deferred to R4.
DENYLIST_PATTERNS: List[str] = [
    "scripts/lib/cio_acceptance_v4.py",
    "scripts/lib/cio_capital_plan.py",
    "scripts/lib/cio_strategy_knowledge.py",
    "scripts/lib/cio_seasonality_engine.py",
    "scripts/lib/cio_command_center.py",
    "scripts/lib/cio_financial_truth_gate.py",
    "scripts/lib/cio_freshness_materiality_gate.py",
    "scripts/run_cio_acceptance.py",
    "scripts/lib/advisory/kb_lessons.py",
    "scripts/agent_runtime/knowledge.py",
    "scripts/lib/hermes_research_backend.py",
    "scripts/rag_retrieval.py",
    "apps/command-center-v3/*",
    "apps/command-center-v3/**",
    "RELEASE_MANIFEST*",
    "deploy/*",
    "scripts/deploy_*.sh",
]


def is_denied(path: str, deny_patterns: Sequence[str] = DENYLIST_PATTERNS) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in deny_patterns)


def is_allowed(path: str, allow_patterns: Sequence[str] = ALLOWLIST_PATTERNS) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in allow_patterns)


def evaluate(changed_files: Iterable[str]) -> dict:
    """Pure evaluation. Returns PASS/FAIL with the offending files."""
    denied: list[str] = []
    unexpected: list[str] = []
    for f in changed_files:
        if is_denied(f):
            denied.append(f)
        elif not is_allowed(f):
            unexpected.append(f)

    state = "PASS" if (not denied and not unexpected) else "FAIL"
    return {
        "state": state,
        "denied": denied,
        "unexpected": unexpected,
        "changed_count": len(list(changed_files)),
    }


def _base_sha_from_baseline(repo_root: Path) -> str:
    baseline = repo_root / "docs" / "investment-office" / "RESEARCH_GOVERNANCE_BUILD_BASELINE.md"
    text = baseline.read_text(encoding="utf-8")
    m = re.search(r"base_sha:\s*`([0-9a-f]{40})`", text)
    if not m:
        raise RuntimeError("base_sha not found in RESEARCH_GOVERNANCE_BUILD_BASELINE.md")
    return m.group(1)


def _resolve_effective_base(repo_root: Path, frozen_base: str) -> str:
    """Choose the diff base that isolates THIS branch's changes.

    `origin/main` may have moved under the parallel CIO remediation agent. A
    three-dot diff against live `origin/main` therefore isolates only this
    branch's own commits (the merge-base logic excludes main's new files),
    whereas diffing against the frozen BASE_SHA would, in a PR merge-commit
    context, also pick up main's post-fork commits. Fall back to the frozen base
    when `origin/main` is not available (e.g. a local pre-push check).
    """
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "origin/main"],
        cwd=str(repo_root), capture_output=True, text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    return frozen_base


def main(argv: Sequence[str] = ()) -> int:
    repo_root = Path(__file__).resolve().parents[3]
    frozen_base = _base_sha_from_baseline(repo_root)
    base = _resolve_effective_base(repo_root, frozen_base)
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=str(repo_root), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(f"git diff failed: {proc.stderr}", file=sys.stderr)
        return 1
    changed = [l for l in proc.stdout.splitlines() if l.strip()]
    result = evaluate(changed)
    print(f"frozen_base_sha={frozen_base}")
    print(f"effective_base={base}")
    print(f"changed_files={len(changed)}")
    print(f"denied={result['denied']}")
    print(f"unexpected={result['unexpected']}")
    print(f"scope_guard={result['state']}")
    return 0 if result["state"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
