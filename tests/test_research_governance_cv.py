"""Research governance — purged/embargoed CV semantics tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import cv  # noqa: E402


def _labels(n):
    return [(i * 3, i * 3 + 1) for i in range(n)]


def test_purged_walk_forward_preserves_pre_test_history():
    # A large embargo must NOT erase earlier (pre-test) training samples.
    folds = cv.purged_walk_forward(9, _labels(9), n_splits=3, embargo=100)
    assert folds[1]["train"] == [0, 1, 2]


def test_purged_walk_forward_chronological_only():
    folds = cv.purged_walk_forward(9, _labels(9), n_splits=3, embargo=0)
    assert folds[0]["train"] == []
    assert folds[1]["test"] == [3, 4, 5]
    # No future samples may leak into walk-forward training.
    assert all(i < min(folds[1]["test"]) for i in folds[1]["train"])


def test_purge_removes_label_overlap():
    # Label of index 3 (6,7) overlaps test label (6,7) region if test covers 0..2
    # with overlapping labels. Build explicit overlap.
    labels = [(0, 4), (5, 9), (10, 14), (13, 20), (21, 25)]
    # Test = index 3 (13,20). Index 2 (10,14) overlaps it.
    kept = cv.purge_train_indices(5, labels, [3], embargo=0)
    assert 2 not in kept
    assert 3 not in kept  # test itself excluded


def test_purged_kfold_removes_post_test_embargo_only():
    labels = _labels(9)
    kf = cv.purged_kfold(9, labels, n_splits=3, embargo=3)
    fold0 = kf[0]  # test [0,1,2] -> test_end label = 7, embargo buffer = 10
    # index 3 label starts at 9 (< 10) -> removed; index 4 label starts at 12 -> kept.
    assert 3 not in fold0["train"]
    assert 4 in fold0["train"]


def test_purged_kfold_keeps_pre_test_samples():
    labels = _labels(9)
    kf = cv.purged_kfold(9, labels, n_splits=3, embargo=3)
    fold1 = kf[1]  # test [3,4,5]; pre-test [0,1,2] must remain despite embargo.
    assert 0 in fold1["train"]
    assert 1 in fold1["train"]
    assert 2 in fold1["train"]


def test_combinatorial_purged_cv_full_partitions():
    parts = cv.combinatorial_purged_cv(9, _labels(9), n_groups=3, n_test_groups=1, embargo=0)
    assert len(parts) == 3  # C(3,1)
    for p in parts:
        assert p["test"]
        assert set(p["train"]).isdisjoint(set(p["test"]))


def test_cpcv_with_embargo_removes_post_test_only():
    parts = cv.combinatorial_purged_cv(9, _labels(9), n_groups=3, n_test_groups=1, embargo=3)
    # First partition: test = group 0 (indices 0,1,2).
    p0 = parts[0]
    assert 3 not in p0["train"]  # post-test index inside embargo removed
    assert 4 in p0["train"]      # after embargo remains


def test_cpcv_group_combinations_count():
    assert len(cv._group_combinations(4, 2)) == 6


def test_validation_rejects_bad_labels():
    with pytest.raises(ValueError):
        cv.purged_walk_forward(5, _labels(4), n_splits=2)  # labels length mismatch
    with pytest.raises(ValueError):
        cv.purge_train_indices(5, _labels(5), [99])
    with pytest.raises(ValueError):
        cv.purge_train_indices(5, _labels(5), [])


def test_validation_rejects_invalid_intervals():
    bad = [(0, 1), (5, 4), (2, 3)]
    with pytest.raises(ValueError):
        cv.purge_train_indices(3, bad, [0])
