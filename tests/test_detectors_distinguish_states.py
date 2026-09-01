"""Two detectors that could not tell two different states apart.

1. `report_docs_inventory.collect_inventory` walked the filesystem, so a gitignored
   __pycache__ under docs/ changed the generated index. CI runs on a clean checkout
   and could never reproduce it: tracked 2274 vs filesystem 2276. That divergence
   reddened a REQUIRED gate on commits that passed locally.

2. `signal_flow_audit` recorded OK when there were zero GO/A+ scans, because
   `go>0 and after==0` is false. "Upstream produced nothing" was indistinguishable
   from "everything worked" -- during the 2026-08 outage it read OK on 08-28, 08-30
   and 08-31 while the Strategy Desk was empty.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


# ── 1 · the docs inventory must see what git sees ────────────────────────────
def _in_git_checkout() -> bool:
    try:
        subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--git-dir"],
                       capture_output=True, check=True, timeout=30)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _in_git_checkout(), reason="requires a git checkout")
def test_candidate_files_ignores_untracked_artifacts(tmp_path):
    import sys
    sys.path.insert(0, str(SCRIPTS))
    import report_docs_inventory as rdi

    docs = ROOT / "docs"
    found = {p.resolve() for p in rdi._candidate_files(docs)}

    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--", "docs"],
        capture_output=True, text=True, check=True, timeout=60,
    ).stdout.split()
    assert tracked, "expected docs/ to be tracked"

    # every returned path is tracked
    tracked_abs = {(ROOT / t).resolve() for t in tracked}
    extra = found - tracked_abs
    assert not extra, f"inventory returned untracked paths: {sorted(map(str, extra))[:5]}"


@pytest.mark.skipif(not _in_git_checkout(), reason="requires a git checkout")
def test_a_planted_gitignored_file_does_not_change_the_inventory():
    """Positive control, through collect_inventory -- the real entry point.

    An earlier version of this test called the _candidate_files helper directly.
    Reverting collect_inventory to root.rglob("*") left the helper intact and
    correct, so the mutation SURVIVED: the test proved the helper worked while the
    generator no longer used it. Exercise what the gate exercises.
    """
    import sys
    sys.path.insert(0, str(SCRIPTS))
    import report_docs_inventory as rdi

    docs = ROOT / "docs"
    before, _ = rdi.collect_inventory(docs)
    before_paths = {e["path"] for e in before}

    junk_dir = docs / "_design" / "__pytest_probe__" / "__pycache__"
    junk_dir.mkdir(parents=True, exist_ok=True)
    junk = junk_dir / "probe.cpython-314.pyc"
    junk.write_bytes(b"x")
    try:
        after, _ = rdi.collect_inventory(docs)
        after_paths = {e["path"] for e in after}
        assert after_paths == before_paths, (
            "a gitignored artifact changed the generated inventory again -- this is "
            "what made tracked 2274 and filesystem 2276 diverge and reddened CI"
        )
    finally:
        junk.unlink(missing_ok=True)
        for d in (junk_dir, junk_dir.parent):
            try:
                d.rmdir()
            except OSError:
                pass


# ── 2 · one vocabulary for the audit status ──────────────────────────────────
def _string_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def test_zero_scan_state_exists_and_is_not_ok():
    """The zero-GO case must have its own state, distinct from OK."""
    consts = _string_constants(SCRIPTS / "strategy_signal_sync.py")
    assert "NO_GO_TODAY" in consts, (
        "strategy_signal_sync no longer emits a distinct zero-input state; "
        "signal_flow_audit is back to reporting OK when nothing was scanned"
    )


def test_both_writers_use_one_name_for_the_zero_scan_state():
    """Both modules write signal_flow_audit. Two names for one state is drift.

    session18_signal_flow_health.py has emitted NO_GO_TODAY since before this fix.
    A second label (NO_INPUT was the tempting one) would put two names for the same
    condition into one column.
    """
    sync = _string_constants(SCRIPTS / "strategy_signal_sync.py")
    health = _string_constants(SCRIPTS / "session18_signal_flow_health.py")
    assert "NO_GO_TODAY" in health, "the health check's own name changed; re-align both"
    assert "NO_INPUT" not in sync, (
        "strategy_signal_sync coined a second name for the zero-scan state; "
        "session18_signal_flow_health already calls it NO_GO_TODAY"
    )
