"""The PII gate's merge-up trap: main's own lines are not "added" by a merge (FQ-154b).

The pre-commit gate diffs the index against the branch's first parent, so every file a merge-up brings in from main
reads as added — and the PII lines main already publishes fail the scan. Baseline may only shrink, so a far-behind
branch had no sanctioned way to merge (cc-deepseek proved it on #2182, 356 behind; cc-deepseek-2 measured 32 of the
40 oldest PRs in that class).

The rule pinned here:

1. in a merge commit, a finding whose line is BYTE-IDENTICAL at the same path and line in `origin/main` does not
   count — a merge-up cannot introduce exposure main already publishes;
2. a finding on a line that differs from main at that path still counts, in full;
3. an ordinary (non-merge) commit is judged exactly as before;
4. if `origin/main` cannot be resolved during a merge, the scan REFUSES (exit 2), never skips.

Hermetic: temporary git repositories, no network.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_no_pii as C  # noqa: E402

#: A line the scanner reports as a private IP. It is main's own line, so a merge-up of it must not count.
MAIN_PII_LINE = "server = " + "10." + "4.3.17" + "  # internal audit collector"
#: A second, DIFFERENT PII line, planted by the branch: this one must still be refused.
PLANTED_PII_LINE = "backup_host = " + "10." + "9.9.9" + "  # branch-only"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, check=check, capture_output=True, text=True)


def _commit(repo: Path, msg: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


def _repos(tmp_path: Path) -> tuple[Path, Path, Path]:
    """(upstream, work) where work branched before the file main added, plus a clone to serve as origin/main."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    _git(upstream, "config", "user.email", "synthetic@example.com")
    _git(upstream, "config", "user.name", "synthetic")
    (upstream / "README.md").write_text("synthetic\n", encoding="utf-8")
    _commit(upstream, "seed")

    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(upstream), str(work))
    _git(work, "config", "user.email", "synthetic@example.com")
    _git(work, "config", "user.name", "synthetic")

    # main gains a file whose line is PII; the branch is made BEFORE this, i.e. far behind.
    (upstream / "config" / "collector.md").parent.mkdir()
    (upstream / "config" / "collector.md").write_text(f"# collector\n\n{MAIN_PII_LINE}\n", encoding="utf-8")
    _commit(upstream, "main adds an internal collector note")

    _git(work, "checkout", "-q", "-b", "feature")
    (work / "feature.md").write_text("branch work\n", encoding="utf-8")
    _commit(work, "branch work")
    return upstream, work, tmp_path


def _merge_up(work: Path) -> subprocess.CompletedProcess:
    """Stage the merge WITHOUT committing: the pre-commit hook runs in exactly this state (MERGE_HEAD present)."""
    return _git(work, "merge", "--no-commit", "--no-ff", "--no-edit", "origin/main", check=False)


def _scan_staged(work: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_no_pii.py"), "--repo", str(work), "--staged"],
        capture_output=True, text=True, timeout=120,
    )


def test_a_merge_up_of_mains_own_line_is_not_added(tmp_path):
    upstream, work, _ = _repos(tmp_path)
    _git(work, "fetch", "-q", "origin")
    assert _merge_up(work).returncode == 0, "the synthetic merge-up itself failed"
    assert C.in_merge(work), "the fixture must leave a merge in progress (MERGE_HEAD)"
    proc = _scan_staged(work)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "byte-identical in origin/main" in proc.stdout, proc.stdout


def test_a_line_the_branch_adds_in_the_same_file_still_counts(tmp_path):
    upstream, work, _ = _repos(tmp_path)
    _git(work, "fetch", "-q", "origin")
    assert _merge_up(work).returncode == 0
    doc = work / "config" / "collector.md"
    doc.write_text(doc.read_text(encoding="utf-8") + f"{PLANTED_PII_LINE}\n", encoding="utf-8")
    _git(work, "add", "-A")
    proc = _scan_staged(work)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "private_ip" in proc.stdout
    # The merge-up lines are exempt, the planted one is not: both statements must be true at once.
    assert "byte-identical in origin/main" in proc.stdout


def test_an_ordinary_commit_is_judged_exactly_as_before(tmp_path):
    upstream, work, _ = _repos(tmp_path)
    _git(work, "fetch", "-q", "origin")
    doc = work / "feature.md"
    doc.write_text(doc.read_text(encoding="utf-8") + f"{PLANTED_PII_LINE}\n", encoding="utf-8")
    _git(work, "add", "-A")
    proc = _scan_staged(work)
    assert proc.returncode == 1, "a non-merge commit must be judged exactly as today"
    assert "private_ip" in proc.stdout
    assert "byte-identical" not in proc.stdout


def test_an_unresolvable_merge_target_refuses(tmp_path):
    upstream, work, _ = _repos(tmp_path)
    _git(work, "fetch", "-q", "origin")
    assert _merge_up(work).returncode == 0
    _git(work, "update-ref", "-d", "refs/remotes/origin/main")
    proc = _scan_staged(work)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "cannot be resolved" in proc.stderr and "refusing" in proc.stderr.lower()


def test_the_gate_is_registered():
    from scripts.lib import ci_gates

    records = {r["name"]: r for r in ci_gates.load_records(ROOT)}
    assert "check_no_pii_mergeup_20261105" in records
    assert "tests/test_check_no_pii_mergeup_20261105.py" in records["check_no_pii_mergeup_20261105"]["files"]
