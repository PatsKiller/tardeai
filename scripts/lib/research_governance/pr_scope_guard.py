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
    "docs/investment-office/R1_FORMULA_AND_REFERENCE_AUDIT.md",
    "docs/investment-office/R2_*",
    "docs/investment-office/R3_*",
    "docs/investment-office/R4_*",
    "docs/investment-office/R5_*",
    "docs/investment-office/R6_*",
    "docs/investment-office/R7_*",
    "docs/investment-office/R8_*",
    "scripts/run_research_governance_acceptance.py",
    "scripts/lib/research_governance/mechanics/*",
    "scripts/lib/research_governance/mechanics/**",
    "tests/test_research_mechanics*",
    "tests/test_research_almanac*",
    "tests/test_research_r3*",
    "tests/test_research_r4*",
    "tests/test_research_cpcv*",
    "tests/test_research_durable*",
    "tests/test_research_policy*",
    "tests/test_research_behavioral*",
    "tests/test_research_empirical*",
    "tests/test_research_r5*",
    "tests/test_research_r6*",
    "tests/test_research_r7*",
    "tests/test_research_r8*",
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
    """Pure evaluation. Returns PASS/FAIL with the offending files.

    The iterable is normalized to a list ONCE at entry so generators are
    consumed a single time and the reported count is correct.
    """
    files: list[str] = list(changed_files)
    denied: list[str] = []
    unexpected: list[str] = []
    for f in files:
        if is_denied(f):
            denied.append(f)
        elif not is_allowed(f):
            unexpected.append(f)

    state = "PASS" if (not denied and not unexpected) else "FAIL"
    return {
        "state": state,
        "denied": denied,
        "unexpected": unexpected,
        "changed_count": len(files),
    }


def _base_sha_from_baseline(repo_root: Path) -> str:
    baseline = repo_root / "docs" / "investment-office" / "RESEARCH_GOVERNANCE_BUILD_BASELINE.md"
    text = baseline.read_text(encoding="utf-8")
    m = re.search(r"base_sha:\s*`([0-9a-f]{40})`", text)
    if not m:
        raise RuntimeError("base_sha not found in RESEARCH_GOVERNANCE_BUILD_BASELINE.md")
    return m.group(1)


def _resolve_effective_base(repo_root: Path, frozen_base: str, *,
                            require_remote: bool = True) -> str:
    """Resolve the diff base (P2-1/P2-2).

    For CI / merge acceptance (``require_remote=True``), a freshly-resolved remote
    ``origin/main`` SHA is MANDATORY. If remote truth cannot be resolved or parsed,
    this RAISES so the guard FAILS CLOSED rather than silently diffing against a
    local ref or a frozen baseline.

    An explicit local/offline developer mode (``require_remote=False``) may fall
    back to the local merge-base and then the frozen baseline, but offline mode is
    NEVER merge acceptance.
    """
    remote_main_sha = _fresh_remote_main_sha(repo_root)
    if remote_main_sha:
        return remote_main_sha
    if require_remote:
        raise RuntimeError(
            "fresh remote-main truth is mandatory for merge acceptance; could not "
            "resolve origin/main via git ls-remote")
    # Explicit local/offline developer mode only.
    proc = subprocess.run(
        ["git", "merge-base", "HEAD", "origin/main"],
        cwd=str(repo_root), capture_output=True, text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    return frozen_base


def _fresh_remote_main_sha(repo_root: Path) -> str | None:
    """Return the freshly-fetched remote `main` SHA, or None if unresolvable."""
    proc = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=str(repo_root), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "refs/heads/main":
            sha = parts[0]
            if re.fullmatch(r"[0-9a-f]{40}", sha):
                return sha
    return None


def main(argv: Sequence[str] = ()) -> int:
    repo_root = Path(__file__).resolve().parents[3]
    frozen_base = _base_sha_from_baseline(repo_root)
    offline = "--offline" in argv
    # Resolve remote truth ONCE (P2-1: do not call ls-remote a second time just to
    # print status). require_remote=True means the guard fails closed if remote
    # truth is unavailable (merge acceptance); --offline is explicit dev mode only.
    base = _resolve_effective_base(repo_root, frozen_base, require_remote=not offline)
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
    print(f"base_truth={'offline' if offline else 'remote'}")
    print(f"changed_files={len(changed)}")
    print(f"denied={result['denied']}")
    print(f"unexpected={result['unexpected']}")
    print(f"scope_guard={result['state']}")
    return 0 if result["state"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
