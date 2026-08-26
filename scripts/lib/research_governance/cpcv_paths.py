"""Research governance — CPCV path construction (R5 / AFML Ch. 12 step 2).

R1 (`cv.combinatorial_purged_splits`) emits purged/embargoed train/test SPLITS
only. This module is the deferred second step: chain those splits into covering
backtest PATHS.

A covering path is an unordered partition of the group axis into subsets of
size `n_test_groups`. Each block is one R1 split. Concatenating that split's
test indices in chronological order tests every sample exactly once on the
path (including the last group's remainder tail). The family of paths is
reported whole — never a winner-only path.

Fail-closed:
  * `covering_path_partitions` raises ValueError when
    `n_groups % n_test_groups != 0` (cannot tile the group axis).
  * `build_cpcv_paths` returns status UNAVAILABLE with an empty `paths` list
    rather than guessing a non-covering assignment.

Authority: READ_ONLY_ADVISORY. Pure stdlib. Deterministic.
"""
from __future__ import annotations

import itertools
from typing import Any, Sequence

from .bootstrap_reality_check import calendar_family_reality_check
from .cv import combinatorial_purged_splits

AUTHORITY = "READ_ONLY_ADVISORY"


def _unavailable(
    reason: str,
    *,
    n_splits: int = 0,
) -> dict[str, Any]:
    return {
        "authority": AUTHORITY,
        "status": "UNAVAILABLE",
        "n_splits": int(n_splits),
        "n_paths": 0,
        "winner_only": False,
        "whole_family": True,
        "paths": [],
        "reason": reason,
    }


def _group_bounds(n_samples: int, n_groups: int) -> list[tuple[int, int, int]]:
    """(group_id, start, end) using the same grouping as combinatorial_purged_splits.

    `group_size = n_samples // n_groups`; the last group takes the remainder.
    """
    group_size = n_samples // n_groups
    bounds: list[tuple[int, int, int]] = []
    for g in range(n_groups):
        start = g * group_size
        end = n_samples if g == n_groups - 1 else (g + 1) * group_size
        bounds.append((g, start, end))
    return bounds


def _groups_from_test_indices(
    test_indices: Sequence[int],
    n_samples: int,
    n_groups: int,
) -> frozenset[int]:
    """Recover test-group ids from a split's sample index ranges."""
    test_set = set(test_indices)
    found: list[int] = []
    for g, start, end in _group_bounds(n_samples, n_groups):
        group_idx = set(range(start, end))
        if group_idx and group_idx <= test_set:
            found.append(g)
        elif group_idx & test_set:
            # Partial group membership is not a valid CPCV split.
            raise ValueError(
                f"test indices only partially cover group {g} "
                f"(range [{start}, {end}))"
            )
    return frozenset(found)


def covering_path_partitions(
    n_groups: int,
    n_test_groups: int,
) -> list[tuple[tuple[int, ...], ...]]:
    """Unordered partitions of {0..n_groups-1} into subsets of size n_test_groups.

    Fail-closed (ValueError) if n_groups % n_test_groups != 0.
    Each inner tuple is a sorted test-group combo. The outer list is
    deterministic (sorted).
    """
    if not isinstance(n_groups, int) or not isinstance(n_test_groups, int):
        raise ValueError("n_groups and n_test_groups must be integers")
    if n_groups < 1:
        raise ValueError("n_groups must be >= 1")
    if n_test_groups < 1:
        raise ValueError("n_test_groups must be >= 1")
    if n_groups % n_test_groups != 0:
        raise ValueError(
            "n_groups must be divisible by n_test_groups to form covering paths "
            f"(got n_groups={n_groups}, n_test_groups={n_test_groups})"
        )

    items = tuple(range(n_groups))
    block_size = n_test_groups

    def _partitions(remaining: tuple[int, ...]) -> list[tuple[tuple[int, ...], ...]]:
        if not remaining:
            return [()]
        first = remaining[0]
        rest = remaining[1:]
        out: list[tuple[tuple[int, ...], ...]] = []
        for partners in itertools.combinations(rest, block_size - 1):
            block = tuple(sorted((first,) + partners))
            partner_set = set(partners)
            leftover = tuple(x for x in rest if x not in partner_set)
            for tail in _partitions(leftover):
                out.append((block,) + tail)
        return out

    raw = _partitions(items)
    partitions = [tuple(sorted(part)) for part in raw]
    partitions.sort()
    return partitions


def build_cpcv_paths(
    n_samples: int,
    labels: Sequence[tuple[object, object]],
    n_groups: int,
    n_test_groups: int,
    embargo: object = 0,
) -> dict[str, Any]:
    """Chain combinatorial purged splits into covering CPCV paths.

    1. Call combinatorial_purged_splits for the same arguments.
    2. Index splits by frozenset(test groups) recovered from sample ranges.
    3. For each covering partition, chain the corresponding splits.
    4. For each path, concatenate test indices in chronological order so that
       every sample 0..n_samples-1 appears in the path's test union exactly
       once (remainder tail of the last group included once). No train index
       of a split may appear in that split's test.
    5. Return the whole family (winner_only=False).

    Fail-closed UNAVAILABLE (empty paths) when covering partitions cannot be
    formed — never a guessed assignment.
    """
    try:
        splits = combinatorial_purged_splits(
            n_samples, labels, n_groups, n_test_groups, embargo
        )
    except (TypeError, ValueError) as exc:
        return _unavailable(f"splits unavailable: {exc}")

    try:
        partitions = covering_path_partitions(n_groups, n_test_groups)
    except ValueError as exc:
        return _unavailable(
            f"covering partitions cannot be formed: {exc}",
            n_splits=len(splits),
        )

    if not partitions:
        return _unavailable(
            "covering partitions cannot be formed",
            n_splits=len(splits),
        )

    try:
        by_groups: dict[frozenset[int], int] = {}
        for i, split in enumerate(splits):
            key = _groups_from_test_indices(split["test"], n_samples, n_groups)
            if key in by_groups:
                return _unavailable(
                    f"duplicate split for test groups {sorted(key)}",
                    n_splits=len(splits),
                )
            by_groups[key] = i
    except ValueError as exc:
        return _unavailable(f"cannot index splits by test groups: {exc}",
                            n_splits=len(splits))

    universe = set(range(n_samples))
    paths: list[dict[str, Any]] = []
    for p_i, part in enumerate(partitions):
        split_refs: list[int] = []
        test_acc: list[int] = []
        for combo in part:
            key = frozenset(combo)
            if key not in by_groups:
                return _unavailable(
                    f"missing split for test groups {combo}",
                    n_splits=len(splits),
                )
            ref = by_groups[key]
            split = splits[ref]
            train_set = set(split["train"])
            test_set = set(split["test"])
            if train_set & test_set:
                return _unavailable(
                    f"train/test overlap in split {ref}",
                    n_splits=len(splits),
                )
            split_refs.append(ref)
            test_acc.extend(split["test"])
        test_indices = sorted(test_acc)
        if len(test_indices) != len(set(test_indices)):
            return _unavailable(
                "sample tested more than once on path",
                n_splits=len(splits),
            )
        if set(test_indices) != universe:
            return _unavailable(
                "path does not cover every sample exactly once",
                n_splits=len(splits),
            )
        paths.append({
            "path_id": f"path-{p_i:04d}",
            "test_group_sets": [tuple(combo) for combo in part],
            "test_indices": test_indices,
            "split_refs": split_refs,
        })

    return {
        "authority": AUTHORITY,
        "status": "OK",
        "n_splits": len(splits),
        "n_paths": len(paths),
        "winner_only": False,
        "whole_family": True,
        "paths": paths,
    }


def path_pnl(returns: Sequence[float], path: dict) -> dict[str, Any]:
    """Chronological concat of returns[i] for i in path['test_indices'].

    Return {n, mean, sum, values}. Empty → UNAVAILABLE.
    """
    if not isinstance(path, dict):
        return {
            "status": "UNAVAILABLE",
            "reason": "path must be a dict",
            "n": 0,
            "mean": None,
            "sum": None,
            "values": [],
        }
    indices = path.get("test_indices") or []
    if not indices:
        return {
            "status": "UNAVAILABLE",
            "reason": "empty path",
            "n": 0,
            "mean": None,
            "sum": None,
            "values": [],
        }
    values: list[float] = []
    n_returns = len(returns)
    for i in indices:
        try:
            ii = int(i)
        except (TypeError, ValueError):
            return {
                "status": "UNAVAILABLE",
                "reason": f"non-integer path index {i!r}",
                "n": 0,
                "mean": None,
                "sum": None,
                "values": [],
            }
        if ii < 0 or ii >= n_returns:
            return {
                "status": "UNAVAILABLE",
                "reason": f"returns missing for path index {ii}",
                "n": 0,
                "mean": None,
                "sum": None,
                "values": [],
            }
        try:
            values.append(float(returns[ii]))
        except (TypeError, ValueError):
            return {
                "status": "UNAVAILABLE",
                "reason": f"non-numeric return at index {ii}",
                "n": 0,
                "mean": None,
                "sum": None,
                "values": [],
            }
    n = len(values)
    total = sum(values)
    return {
        "status": "OK",
        "n": n,
        "mean": total / n,
        "sum": total,
        "values": values,
    }


def challenge_path_family(
    returns: Sequence[float],
    paths: Sequence[dict] | dict,
    *,
    seed: int = 7,
    n_resamples: int = 100,
) -> dict[str, Any]:
    """Reality-check the FAMILY of path P&L series. Never winner-only."""
    if isinstance(paths, dict):
        path_list = list(paths.get("paths") or [])
    else:
        path_list = list(paths)

    base = {
        "authority": AUTHORITY,
        "winner_only": False,
        "whole_family": True,
        "n_rules": len(path_list),
    }
    if len(path_list) < 1:
        return {
            **base,
            "status": "UNAVAILABLE",
            "reason": "empty path family",
        }

    series: list[list[float]] = []
    for path in path_list:
        pnl = path_pnl(returns, path)
        if pnl.get("status") != "OK":
            return {
                **base,
                "status": "UNAVAILABLE",
                "reason": pnl.get("reason") or "path pnl unavailable",
            }
        series.append(list(pnl["values"]))

    rc = calendar_family_reality_check(
        "cpcv_path_family",
        series,
        n_bootstrap=n_resamples,
        seed=seed,
        family_definition_hash="r5-cpcv-path-family",
        trial_family_id="r5-cpcv-paths",
        confirmatory=False,
    )
    return {
        "authority": AUTHORITY,
        "status": rc.get("status") or "OK",
        "reason": rc.get("reason"),
        "n_rules": rc.get("n_rules") or len(series),
        "n_observations": rc.get("n_observations"),
        "pvalue": rc.get("bootstrap_pvalue"),
        "statistic": rc.get("observed_statistic"),
        "whole_family": True,
        "winner_only": False,
        "raw": rc,
    }
