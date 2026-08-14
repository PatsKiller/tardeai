"""Research governance — purged/embargoed CV and CPCV (PR-R1).

López de Prado sampling discipline: financial observations are not i.i.d.
Label intervals (holding periods) leak information across a naive train/test
split. Purging removes training samples whose label interval overlaps a test
sample's label; an embargo adds a buffer after the test set before training can
resume. CPCV reuses the CSCV combination logic over purged folds.

Inputs here are label bounds as opaque comparable values (indices or datetimes).
The module is metric-agnostic: the caller supplies `(label_start, label_end)`
pairs and gets train/test index partitions back.

Pure stdlib. Deterministic.
"""
from __future__ import annotations

import itertools
from typing import Callable, Optional, Sequence, Tuple

Interval = Tuple[object, object]
Labeler = Callable[[int], Interval]


def _overlaps(a: Interval, b: Interval) -> bool:
    """True if intervals overlap (inclusive). Works for ints and comparable dates."""
    return not (a[1] < b[0] or b[1] < a[0])


def _min(a: object, b: object) -> object:
    return a if a <= b else b


def _max(a: object, b: object) -> object:
    return a if a >= b else b


def purge_train_indices(
    n_samples: int,
    labels: Sequence[Interval],
    test_indices: Sequence[int],
    embargo: object = 0,
) -> list[int]:
    """Return training indices excluding purged/embargoed leakage.

    A training sample is excluded if its label interval overlaps any test
    sample's label interval (purge), or if it falls inside the embargo buffer
    placed after the test set's end (i.e. its label start < test_end + embargo).
    """
    test_end = None
    test_labels = [labels[i] for i in test_indices]
    for (s, e) in test_labels:
        test_end = e if test_end is None else _max(test_end, e)

    result: list[int] = []
    for i in range(n_samples):
        if i in set(test_indices):
            continue
        lab = labels[i]
        # Purge: label overlaps any test label.
        if any(_overlaps(lab, tl) for tl in test_labels):
            continue
        # Embargo: only when a non-zero buffer is requested; otherwise no buffer.
        if test_end is not None and embargo != 0:
            buffer_end = test_end + embargo  # type: ignore[operator]
            if lab[0] < buffer_end:
                continue
        result.append(i)
    return result


def embargoed_purged_kfold(
    n_samples: int,
    labels: Sequence[Interval],
    n_splits: int,
    embargo: object = 0,
) -> list[dict]:
    """Yield n_splits purged/embargoed walk-forward train/test partitions.

    Splits the index axis into n_splits contiguous chronological groups; each
    group in turn is the test set, and training is everything before it, with
    label-overlap purging and an embargo buffer applied to the train side.
    """
    if n_splits < 2:
        raise ValueError("n_splits must be >= 2")
    if len(labels) != n_samples:
        raise ValueError("labels length must equal n_samples")
    group_size = n_samples // n_splits
    folds: list[dict] = []
    for k in range(n_splits):
        start = k * group_size
        end = n_samples if k == n_splits - 1 else (k + 1) * group_size
        test = list(range(start, end))
        # Train only on chronologically earlier data (walk-forward), then purge
        # training samples whose label interval leaks into the test block.
        earlier = list(range(0, start))
        purged = _purged_indices(labels, test, embargo)
        train = [i for i in earlier if i not in purged]
        folds.append({"train": train, "test": test, "fold": k})
    return folds


def _purged_indices(
    labels: Sequence[Interval],
    test_indices: Sequence[int],
    embargo: object,
) -> set[int]:
    """Indices purged against this test block (overlap + embargo)."""
    test_labels = [labels[i] for i in test_indices]
    test_end = None
    for (_s, e) in test_labels:
        test_end = e if test_end is None else _max(test_end, e)

    purged: set[int] = set()
    for i, lab in enumerate(labels):
        if i in set(test_indices):
            purged.add(i)
            continue
        if any(_overlaps(lab, tl) for tl in test_labels):
            purged.add(i)
            continue
        if test_end is not None and embargo != 0:
            buffer_end = test_end + embargo  # type: ignore[operator]
            if lab[0] < buffer_end:
                purged.add(i)
    return purged


def cpcv_partitions(n_groups: int, n_test_groups: int) -> list[list[int]]:
    """Combinatorially-symmetric CV: all test-group combinations.

    With n_groups groups, hold out n_test_groups; every combination of test
    groups appears, and the complement is the training group set. Matches the
    CSCV machinery in pbo.py.
    """
    if n_test_groups >= n_groups or n_test_groups < 1:
        raise ValueError("require 1 <= n_test_groups < n_groups")
    return [list(c) for c in itertools.combinations(range(n_groups), n_test_groups)]
