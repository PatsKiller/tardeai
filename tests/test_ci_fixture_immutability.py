#!/usr/bin/env python3
"""Validation must never dirty the candidate worktree.

The defect: ``run_harness()`` unconditionally wrote
``fixtures/cc_runtime/route_ledger.json``, so every harness run — including
``pytest tests/test_cc_runtime_harness.py`` — rewrote a TRACKED file and left the
worktree dirty. Worse, it then compared discovery against the ledger it had just
written from that same discovery, so the unaccounted-route control could never
fail. And the pin it wrote came from a hardcoded commit literal, which is how an
unrelated SHA ended up stamped across weeks of harness evidence.

These tests are the regression rail for all three.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cc_runtime_harness.negatives import SYNTHETIC_NOW  # noqa: E402
from scripts.cc_runtime_harness.runner import HarnessConfig, run_harness  # noqa: E402

FIXTURES = ROOT / "fixtures" / "cc_runtime"
LEDGER = FIXTURES / "route_ledger.json"


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_no_hardcoded_commit_sha_anywhere_in_the_harness():
    """A commit literal in a test or control stamps evidence it did not produce."""
    offenders = []
    for p in list((ROOT / "scripts" / "cc_runtime_harness").glob("*.py")) + [
        ROOT / "tests" / "test_cc_runtime_harness.py"
    ]:
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if "cd049cb4eb20add7a24de28b5a5e42eafcc4d673" in line:
                offenders.append(f"{p.relative_to(ROOT)}:{n}")
    assert offenders == [], f"hardcoded commit SHA: {offenders}"


def test_ordinary_run_does_not_touch_the_tracked_fixture_tree(tmp_path):
    """The rail: a full hermetic run leaves every tracked fixture byte-identical."""
    before = _hash_tree(FIXTURES)
    cfg = HarnessConfig(
        mode="hermetic",
        repo_root=ROOT,
        fixture_root=FIXTURES,
        output_dir=tmp_path / "out",
        build_sha="a" * 40,
        # The harness's canonical instant: the timezone-boundary controls are
        # written against it, so passing any other clock fails them for the wrong reason.
        synthetic_now=SYNTHETIC_NOW,
    )
    result = run_harness(cfg)
    after = _hash_tree(FIXTURES)
    assert result.ok, result.failures
    changed = [k for k in before if before[k] != after.get(k)]
    added = [k for k in after if k not in before]
    assert changed == [], f"ordinary CI mutated tracked fixtures: {changed}"
    assert added == [], f"ordinary CI added files to the tracked fixture tree: {added}"


def test_generated_evidence_goes_to_the_output_directory(tmp_path):
    cfg = HarnessConfig(
        mode="hermetic",
        repo_root=ROOT,
        fixture_root=FIXTURES,
        output_dir=tmp_path / "out",
        build_sha="b" * 40,
        # The harness's canonical instant: the timezone-boundary controls are
        # written against it, so passing any other clock fails them for the wrong reason.
        synthetic_now=SYNTHETIC_NOW,
    )
    run_harness(cfg)
    generated = tmp_path / "out" / "route_ledger.generated.json"
    assert generated.is_file(), "the generated ledger must be written as evidence, not discarded"
    obj = json.loads(generated.read_text())
    assert obj["build_sha_pin"] == "b" * 40, "the pin must come from the build under test"


def test_the_committed_ledger_is_the_expectation(tmp_path):
    """Comparing discovery against a ledger just written from that discovery is vacuous."""
    cfg = HarnessConfig(
        mode="hermetic",
        repo_root=ROOT,
        fixture_root=FIXTURES,
        output_dir=tmp_path / "out",
        build_sha="c" * 40,
        # The harness's canonical instant: the timezone-boundary controls are
        # written against it, so passing any other clock fails them for the wrong reason.
        synthetic_now=SYNTHETIC_NOW,
    )
    result = run_harness(cfg)
    assert result.ok, result.failures
    src = (ROOT / "scripts" / "cc_runtime_harness" / "runner.py").read_text()
    assert 'ledger_source = "committed"' in src
    assert "if cfg.regenerate_fixtures:" in src, "regeneration must be an explicit branch"


def test_regeneration_is_a_separately_named_command():
    main = (ROOT / "scripts" / "cc_runtime_harness" / "__main__.py").read_text()
    assert "--regenerate-fixtures" in main
    assert "Never use in CI" in main, "the flag must warn about its own effect"
    runner = (ROOT / "scripts" / "cc_runtime_harness" / "runner.py").read_text()
    assert "regenerate_fixtures: bool = False" in runner, "the safe default must be immutable"


def test_negative_control_detects_a_tracked_file_mutation(tmp_path):
    """The control that proves the rail can fail.

    A copy of the fixture tree is deliberately mutated and the same hash
    comparison must catch it. Without this, a rail that always passes would look
    identical to a rail that works.
    """
    import shutil

    copy_root = tmp_path / "fixtures_copy"
    shutil.copytree(FIXTURES, copy_root)
    before = _hash_tree(copy_root)

    victim = copy_root / "route_ledger.json"
    doc = json.loads(victim.read_text())
    doc["build_sha_pin"] = "d" * 40
    victim.write_text(json.dumps(doc, indent=2) + "\n")

    after = _hash_tree(copy_root)
    changed = [k for k in before if before[k] != after.get(k)]
    assert changed == ["route_ledger.json"], "the mutation detector failed to notice a rewritten tracked fixture"


@pytest.mark.skipif(
    subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=ROOT, capture_output=True).returncode != 0,
    reason="not a git worktree",
)
def test_git_agrees_the_fixture_tree_is_unmodified():
    """Belt and braces: ask git, not just a hash of our own making."""
    out = subprocess.check_output(["git", "status", "--porcelain", "--", "fixtures/cc_runtime"], cwd=ROOT, text=True)
    assert out.strip() == "", f"tracked fixtures are dirty: {out}"
