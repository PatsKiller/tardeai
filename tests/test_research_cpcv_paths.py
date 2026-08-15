"""R5 CPCV path construction — covering partitions, P&L, family challenge."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.research_governance import acceptance  # noqa: E402
from scripts.lib.research_governance.cpcv_paths import (  # noqa: E402
    AUTHORITY,
    build_cpcv_paths,
    challenge_path_family,
    covering_path_partitions,
    path_pnl,
)
from scripts.lib.research_governance.cv import combinatorial_purged_splits  # noqa: E402


def _labels(n: int):
    return [(i, i) for i in range(n)]


def test_covering_partitions_4_groups_2_test():
    parts = covering_path_partitions(4, 2)
    assert parts
    assert parts == [
        ((0, 1), (2, 3)),
        ((0, 2), (1, 3)),
        ((0, 3), (1, 2)),
    ]
    for part in parts:
        groups = [g for combo in part for g in combo]
        assert sorted(groups) == [0, 1, 2, 3]
        assert len(groups) == 4
        assert all(len(combo) == 2 for combo in part)
        assert all(tuple(combo) == tuple(sorted(combo)) for combo in part)


def test_covering_partitions_not_divisible_fail_closed():
    with pytest.raises(ValueError):
        covering_path_partitions(5, 2)
    with pytest.raises(ValueError):
        covering_path_partitions(4, 0)
    with pytest.raises(ValueError):
        covering_path_partitions(7, 3)


def test_build_paths_4x2_each_group_tested_once():
    n_samples = 12
    out = build_cpcv_paths(n_samples, _labels(n_samples), n_groups=4, n_test_groups=2)
    assert out["status"] == "OK"
    assert out["authority"] == AUTHORITY
    assert out["winner_only"] is False
    assert out["whole_family"] is True
    assert out["n_splits"] == 6  # C(4, 2)
    assert out["n_paths"] == 3
    assert len(out["paths"]) == 3

    splits = combinatorial_purged_splits(
        n_samples, _labels(n_samples), n_groups=4, n_test_groups=2
    )
    for path in out["paths"]:
        groups = [g for combo in path["test_group_sets"] for g in combo]
        assert sorted(groups) == [0, 1, 2, 3]
        assert len(groups) == 4
        assert path["test_indices"] == list(range(n_samples))
        assert len(path["split_refs"]) == 2
        for ref in path["split_refs"]:
            split = splits[ref]
            assert set(split["train"]).isdisjoint(set(split["test"]))


def test_build_paths_5x2_fail_closed_unavailable():
    out = build_cpcv_paths(10, _labels(10), n_groups=5, n_test_groups=2)
    assert out["status"] == "UNAVAILABLE"
    assert out["paths"] == []
    assert out["n_paths"] == 0
    assert out["winner_only"] is False
    assert out["whole_family"] is True
    assert out["authority"] == AUTHORITY
    assert "reason" in out


def test_remainder_tail_included_exactly_once():
    # 13 samples / 4 groups: last group is [9, 10, 11, 12].
    n_samples = 13
    out = build_cpcv_paths(n_samples, _labels(n_samples), n_groups=4, n_test_groups=2)
    assert out["status"] == "OK"
    for path in out["paths"]:
        idx = path["test_indices"]
        assert idx.count(12) == 1
        assert sorted(idx) == list(range(n_samples))
        assert len(idx) == n_samples


def test_path_pnl_matches_independent_recompute():
    n_samples = 12
    returns = [0.01 * (i + 1) for i in range(n_samples)]
    out = build_cpcv_paths(n_samples, _labels(n_samples), n_groups=4, n_test_groups=2)
    assert out["status"] == "OK"
    for path in out["paths"]:
        expected = [returns[i] for i in path["test_indices"]]
        pnl = path_pnl(returns, path)
        assert pnl["status"] == "OK"
        assert pnl["values"] == expected
        assert pnl["n"] == len(expected)
        assert pnl["sum"] == pytest.approx(sum(expected))
        assert pnl["mean"] == pytest.approx(sum(expected) / len(expected))


def test_path_pnl_empty_unavailable():
    pnl = path_pnl([0.1, 0.2], {"test_indices": []})
    assert pnl["status"] == "UNAVAILABLE"
    assert pnl["n"] == 0


def test_family_challenge_winner_only_false():
    n_samples = 12
    returns = [0.02, -0.01, 0.03, 0.00, 0.01, -0.02, 0.04, 0.01, -0.01, 0.02, 0.00, 0.03]
    out = build_cpcv_paths(n_samples, _labels(n_samples), n_groups=4, n_test_groups=2)
    ch = challenge_path_family(returns, out["paths"], seed=7, n_resamples=100)
    assert ch["winner_only"] is False
    assert ch["whole_family"] is True
    assert ch["authority"] == AUTHORITY
    assert ch["n_rules"] == out["n_paths"]
    assert ch["status"] in {"OK", "UNAVAILABLE"}
    if ch["status"] == "OK":
        assert ch["n_rules"] >= 2
        assert ch["pvalue"] is not None


def test_authority_read_only_advisory():
    assert AUTHORITY == "READ_ONLY_ADVISORY"
    out = build_cpcv_paths(12, _labels(12), n_groups=4, n_test_groups=2)
    assert out["authority"] == "READ_ONLY_ADVISORY"
    ch = challenge_path_family([0.01] * 12, out["paths"])
    assert ch["authority"] == "READ_ONLY_ADVISORY"


def test_r5_cpcv_acceptance_profile_includes_r5a1():
    rep = acceptance.run_acceptance("R5_cpcv")
    assert "R5A-1" in acceptance.PHASE_PROFILES["R5_cpcv"]["required_runtime"]
    assert "R5A-1" in rep["required_runtime_pass"], rep
    assert "R6A-1" in rep["not_in_scope"]
    assert "R7A-1" in rep["not_in_scope"]
    assert "R8A-1" in rep["not_in_scope"]
    # RGA-1..16 still pass on this branch; R5A-1 is the only new required check.
    for gid in acceptance.RGA_IDS:
        assert gid in rep["required_runtime_pass"], (gid, rep)
    assert rep["overall"] == "PASS", rep


def test_covering_partitions_are_deterministic():
    a = covering_path_partitions(6, 3)
    b = covering_path_partitions(6, 3)
    assert a == b
    # 6! / (3!^2 * 2!) = 10
    assert len(a) == 10
    assert a == sorted(a)
    for part in a:
        groups = [g for combo in part for g in combo]
        assert sorted(groups) == list(range(6))
        assert math.comb(6, 3)  # sanity: splits exist independently
