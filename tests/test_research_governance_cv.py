"""Research governance — purged/embargoed CV dry tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import cv  # noqa: E402


def test_purge_removes_overlapping_labels():
    labels = [(0, 1), (1, 2), (2, 6), (3, 4), (4, 5), (5, 7)]
    kept = cv.purge_train_indices(6, labels, [3, 4, 5], embargo=0)
    assert kept == [0, 1]


def test_purge_keeps_non_overlapping():
    # Labels with a gap before the test block so no boundary overlap occurs.
    labels = [(0, 1), (1, 2), (2, 3), (5, 6), (6, 7), (7, 8)]
    kept = cv.purge_train_indices(6, labels, [3, 4, 5], embargo=0)
    assert kept == [0, 1, 2]


def test_embargo_excludes_buffer():
    # With a large embargo, even non-overlapping earlier samples are excluded.
    labels = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6)]
    kept = cv.purge_train_indices(6, labels, [3, 4, 5], embargo=100)
    assert kept == []


def test_kfold_walkforward_partitions():
    # Spaced labels so adjacent folds never share a boundary bar.
    labels = [(i * 3, i * 3 + 1) for i in range(6)]
    folds = cv.embargoed_purged_kfold(6, labels, n_splits=3, embargo=0)
    assert len(folds) == 3
    # Fold 0 test [0,1], no training.
    assert folds[0]["test"] == [0, 1]
    assert folds[0]["train"] == []
    # Fold 1 test [2,3], training [0,1] (labels don't overlap test labels).
    assert folds[1]["test"] == [2, 3]
    assert folds[1]["train"] == [0, 1]


def test_kfold_requires_splits():
    with pytest.raises(ValueError):
        cv.embargoed_purged_kfold(6, [(0, 1)] * 6, n_splits=1)


def test_cpcv_partitions_count():
    assert len(cv.cpcv_partitions(6, 2)) == 15
    assert len(cv.cpcv_partitions(4, 1)) == 4


def test_cpcv_partitions_invalid():
    with pytest.raises(ValueError):
        cv.cpcv_partitions(4, 4)
    with pytest.raises(ValueError):
        cv.cpcv_partitions(4, 0)
