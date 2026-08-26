"""R5A-1 CPCV path-construction acceptance."""
from __future__ import annotations

from .cpcv_paths import (
    AUTHORITY,
    build_cpcv_paths,
    covering_path_partitions,
)
from .enums import GateState


def _pass(d: str) -> tuple[str, str]:
    return GateState.PASS.value, d


def _fail(d: str) -> tuple[str, str]:
    return GateState.FAIL.value, d


def check_cpcv_paths() -> tuple[str, str]:
    n_samples = 12
    labels = [(i, i) for i in range(n_samples)]
    out = build_cpcv_paths(n_samples, labels, n_groups=4, n_test_groups=2)
    if out.get("authority") != AUTHORITY or AUTHORITY != "READ_ONLY_ADVISORY":
        return _fail(f"authority drifted: {out.get('authority')}")
    if out.get("status") != "OK":
        return _fail(f"covering paths unavailable: {out.get('reason')}")
    if out.get("winner_only") is not False:
        return _fail("winner_only must be False")
    if out.get("whole_family") is not True:
        return _fail("whole_family must be True")
    paths = out.get("paths") or []
    if not paths:
        return _fail("no covering paths")
    if out.get("n_paths") != len(paths):
        return _fail("n_paths does not match paths list")

    universe = list(range(n_samples))
    expected_groups = [0, 1, 2, 3]
    for path in paths:
        idx = list(path.get("test_indices") or [])
        if sorted(idx) != universe or len(idx) != n_samples:
            return _fail("path does not test each sample exactly once")
        groups = [g for combo in path.get("test_group_sets") or [] for g in combo]
        if sorted(groups) != expected_groups or len(groups) != len(expected_groups):
            return _fail("path does not test each group once (double-count or miss)")

    try:
        covering_path_partitions(5, 2)
        return _fail("5 groups / 2 test groups must fail-closed")
    except ValueError:
        pass

    bad = build_cpcv_paths(10, [(i, i) for i in range(10)], n_groups=5, n_test_groups=2)
    if bad.get("status") != "UNAVAILABLE":
        return _fail("non-divisible groups must be UNAVAILABLE, not a guessed path")
    if bad.get("paths"):
        return _fail("guessed paths returned when covering partitions cannot form")
    if bad.get("winner_only") is not False:
        return _fail("fail-closed result must still be whole-family")

    return _pass(
        "covering CPCV paths, no double-count, family not winner-only, "
        "fail-closed when groups are not divisible"
    )


CHECKS = {"R5A-1": check_cpcv_paths}
