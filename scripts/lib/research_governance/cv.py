"""Research governance — purged/embargoed CV, walk-forward, and CPCV (PR-R1).

López de Prado sampling discipline: financial observations are not i.i.d.
Label intervals (holding periods) leak information across a naive train/test
split. Three distinct procedures are provided:

  * purged_walk_forward       — chronological; training is only BEFORE test.
  * purged_kfold              — training exists BOTH before and after test.
  * combinatorial_purged_splits — all purged/embargoed train/test split
    combinations over the chosen test-group subsets. (CPCV PATH construction —
    i.e. chaining splits into full backtest/P&L paths — is DEFERRED to a later
    PR; this function only generates the purged splits, not the paths.)

Purging removes training samples whose label interval overlaps a test sample's
label. An EMBARGO removes only POST-test training samples whose label begins
within the embargo window after the test period's end.

The test set is treated as a UNION of contiguous test blocks. Embargo is applied
AFTER EACH test block, not just after the globally-last test index. This is the
correct geometry for CPCV partitions with non-contiguous test groups (e.g. test
groups {0, 2}: a training group sitting between them must still be embargoed
relative to block 0 even though it precedes the final test block 2).

Pre-test (earlier) training samples are NEVER embargoed — embargo is a
future-direction leakage control, not a blanket window.

Embargo contract: `embargo` is a value addable to a label end (an integer number
of index steps for integer labels, or a timedelta for datetime labels). `0`
(integer) or `timedelta(0)` disables the embargo.

Pure stdlib. Deterministic.
"""
from __future__ import annotations

import itertools
from typing import List, Sequence, Tuple

Interval = Tuple[object, object]


def _overlaps(a: Interval, b: Interval) -> bool:
    """True if intervals overlap (inclusive). Works for ints and comparable dates."""
    return not (a[1] < b[0] or b[1] < a[0])


def _validate(n_samples: int, labels: Sequence[Interval],
              test_indices: Sequence[int]) -> None:
    if len(labels) != n_samples:
        raise ValueError("labels length must equal n_samples")
    if not test_indices:
        raise ValueError("test set must be non-empty")
    for i in test_indices:
        if i < 0 or i >= n_samples:
            raise ValueError(f"test index {i} out of range")
    for (s, e) in labels:
        if s > e:
            raise ValueError(f"invalid interval {s!r} > {e!r}")


def _contiguous_blocks(test_indices: Sequence[int]) -> List[List[int]]:
    """Split a sorted set of test indices into contiguous runs (test blocks)."""
    ordered = sorted(set(test_indices))
    blocks: List[List[int]] = []
    current: List[int] = []
    for i in ordered:
        if current and i != current[-1] + 1:
            blocks.append(current)
            current = []
        current.append(i)
    if current:
        blocks.append(current)
    return blocks


def _excluded_indices(labels: Sequence[Interval], test_indices: Sequence[int],
                      embargo: object = 0) -> set:
    """Indices EXCLUDED from training: test itself + purged overlaps + per-block embargo.

    The test set is treated as a union of contiguous blocks. A training sample is
    embargoed if it lies chronologically AFTER any test block AND its label begins
    within that block's end + embargo. Pre-test samples are only removed for label
    overlap, never for embargo.
    """
    excluded: set = set(test_indices)
    test_labels = {i: labels[i] for i in test_indices}
    blocks = _contiguous_blocks(test_indices)

    for i, lab in enumerate(labels):
        if i in excluded:
            continue
        # Purging: label overlaps any test label.
        if any(_overlaps(lab, test_labels[t]) for t in test_indices):
            excluded.add(i)
            continue
        # Embargo: after ANY test block within the embargo window.
        if embargo != 0:
            for block in blocks:
                block_max = max(block)
                block_end = max(labels[j][1] for j in block)
                buffer_end = block_end + embargo  # type: ignore[operator]
                if i > block_max and lab[0] < buffer_end:
                    excluded.add(i)
                    break
    return excluded


def purge_train_indices(n_samples: int, labels: Sequence[Interval],
                        test_indices: Sequence[int], embargo: object = 0) -> list[int]:
    """Return training indices KEPT after purging + embargo (excludes test set)."""
    _validate(n_samples, labels, test_indices)
    excl = _excluded_indices(labels, test_indices, embargo)
    return [i for i in range(n_samples) if i not in excl]


def purged_walk_forward(n_samples: int, labels: Sequence[Interval],
                        n_splits: int, embargo: object = 0) -> list[dict]:
    """Chronological purged walk-forward. Training = earlier indices only.

    Each contiguous group in turn is the test set; training is everything
    chronologically before it, purged for label overlap. Embargo does not remove
    earlier (pre-test) samples.
    """
    if n_splits < 2:
        raise ValueError("n_splits must be >= 2")
    group_size = n_samples // n_splits
    folds: list[dict] = []
    for k in range(n_splits):
        start = k * group_size
        end = n_samples if k == n_splits - 1 else (k + 1) * group_size
        test = list(range(start, end))
        _validate(n_samples, labels, test)
        excl = _excluded_indices(labels, test, embargo)
        train = [i for i in range(0, start) if i not in excl]
        folds.append({"train": train, "test": test, "fold": k})
    return folds


def purged_kfold(n_samples: int, labels: Sequence[Interval],
                 n_splits: int, embargo: object = 0) -> list[dict]:
    """Purged K-fold. Training exists both before and after the test fold.

    Purges label overlap on both sides; embargos only the POST-test region.
    """
    if n_splits < 2:
        raise ValueError("n_splits must be >= 2")
    group_size = n_samples // n_splits
    folds: list[dict] = []
    for k in range(n_splits):
        start = k * group_size
        end = n_samples if k == n_splits - 1 else (k + 1) * group_size
        test = list(range(start, end))
        _validate(n_samples, labels, test)
        excl = _excluded_indices(labels, test, embargo)
        train = [i for i in range(n_samples) if i not in excl]
        folds.append({"train": train, "test": test, "fold": k})
    return folds


def _group_combinations(n_groups: int, n_test_groups: int) -> list[list[int]]:
    if n_test_groups >= n_groups or n_test_groups < 1:
        raise ValueError("require 1 <= n_test_groups < n_groups")
    return [list(c) for c in itertools.combinations(range(n_groups), n_test_groups)]


def combinatorial_purged_splits(n_samples: int, labels: Sequence[Interval],
                                n_groups: int, n_test_groups: int,
                                embargo: object = 0) -> list[dict]:
    """Combinatorially-symmetric purged train/test SPLITS (CPCV step 1).

    Partitions the index axis into n_groups contiguous groups; for every
    combination of n_test_groups test groups, training is all other groups with
    label-overlap purging and per-block embargo applied. Returns one {train, test}
    partition per combination (C(n_groups, n_test_groups) total).

    The test set is a UNION of (possibly non-contiguous) test groups; embargo is
    applied after EACH test block, so a training group sandwiched between two test
    groups is embargoed relative to the earlier one.

    NOTE: this generates the purged SPLITS only. CPCV PATH construction (chaining
    the splits into full backtest/P&L paths/scenarios) is DEFERRED to a later PR.
    """
    if n_samples < n_groups:
        raise ValueError("n_samples must be >= n_groups (no empty groups)")
    if len(labels) != n_samples:
        raise ValueError("labels length must equal n_samples")
    if n_groups < 2:
        raise ValueError("n_groups must be >= 2")
    if n_test_groups <= 0:
        raise ValueError("n_test_groups must be >= 1")
    if n_test_groups >= n_groups:
        raise ValueError("require 1 <= n_test_groups < n_groups")

    group_size = n_samples // n_groups
    partitions: list[dict] = []
    for combo in _group_combinations(n_groups, n_test_groups):
        test: list[int] = []
        for g in combo:
            start = g * group_size
            end = n_samples if g == n_groups - 1 else (g + 1) * group_size
            test.extend(range(start, end))
        _validate(n_samples, labels, test)
        excl = _excluded_indices(labels, test, embargo)
        train = [i for i in range(n_samples) if i not in excl]
        partitions.append({"train": train, "test": test})
    return partitions


def combinatorial_purged_cv(n_samples: int, labels: Sequence[Interval],
                            n_groups: int, n_test_groups: int,
                            embargo: object = 0) -> list[dict]:
    """Legacy alias for `combinatorial_purged_splits` (split generation only)."""
    return combinatorial_purged_splits(n_samples, labels, n_groups, n_test_groups, embargo)
