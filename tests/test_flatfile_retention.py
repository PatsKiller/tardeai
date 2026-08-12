"""Flat-file retention scope tests.

Verifies policy-driven keep-newest and max-age TTL behavior, dry-run default
(no deletion), and apply-mode deletion. No DB required.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from scripts.lib.hermes_librarian import flatfiles


@pytest.fixture
def artifact_dir(tmp_path):
    """Create a fake generated-artifacts dir with N files of varying age."""
    d = tmp_path / "dryruns"
    d.mkdir()
    return d


def _make_files(d: Path, names: list[str], ages_days: list[float]):
    now = time.time()
    for name, age in zip(names, ages_days):
        p = d / name
        p.write_text("x" * 100)
        os.utime(p, (now - age * 86400, now - age * 86400))


class TestKeepNewest:
    def test_dry_run_does_not_delete(self, artifact_dir, monkeypatch):
        _make_files(artifact_dir, ["a", "b", "c", "d", "e"], [0, 0, 0, 0, 0])
        # patch ROOT to tmp so relative policy path resolves via _prune directly
        result = flatfiles._prune_keep_newest(artifact_dir, keep=2, apply=False)
        assert len(result) == 3  # 5 files, keep 2 → remove 3
        # nothing actually deleted
        remaining = sorted(p.name for p in artifact_dir.iterdir())
        assert remaining == ["a", "b", "c", "d", "e"]

    def test_apply_deletes_oldest(self, artifact_dir):
        _make_files(artifact_dir, ["a", "b", "c", "d", "e"], [5, 4, 3, 2, 1])
        result = flatfiles._prune_keep_newest(artifact_dir, keep=2, apply=True)
        assert len(result) == 3
        remaining = sorted(p.name for p in artifact_dir.iterdir())
        # newest by mtime = smallest age = "e"(1d) and "d"(2d)
        assert remaining == ["d", "e"]


class TestMaxAge:
    def test_dry_run_lists_but_keeps(self, artifact_dir):
        _make_files(artifact_dir, ["old.json", "new.json"], [30, 1])
        result = flatfiles._prune_age(artifact_dir, "*.json", 14, apply=False)
        assert len(result) == 1
        assert result[0]["path"].endswith("old.json")
        assert sorted(p.name for p in artifact_dir.iterdir()) == ["new.json", "old.json"]

    def test_apply_deletes_old(self, artifact_dir):
        _make_files(artifact_dir, ["old.json", "new.json"], [30, 1])
        result = flatfiles._prune_age(artifact_dir, "*.json", 14, apply=True)
        assert len(result) == 1
        assert sorted(p.name for p in artifact_dir.iterdir()) == ["new.json"]


class TestPolicyDriven:
    def test_missing_policy_returns_empty(self, monkeypatch):
        monkeypatch.setattr(flatfiles, "POLICY_PATH", Path("/nonexistent/policy.yaml"))
        result = flatfiles.apply_flatfile_retention(dry_run=True)
        assert result["removed_count"] == 0
        assert result["targets"] == []

    def test_bytes_reported(self, artifact_dir):
        _make_files(artifact_dir, ["a", "b", "c"], [0, 0, 0])
        result = flatfiles._prune_keep_newest(artifact_dir, keep=1, apply=False)
        assert result[0]["bytes"] > 0
