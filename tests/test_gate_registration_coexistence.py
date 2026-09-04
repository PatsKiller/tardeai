#!/usr/bin/env python3
"""Two campaigns must be able to register CI gates without erasing each other.

`scripts/check_test_coverage.py` fails CI on any new test file not named by a
gate in `run_cio_hardening_ci.py::GATES`. That makes the GATES list a shared
write target for every concurrent campaign, and the obvious failure mode is a
merge that keeps one campaign's tuples and silently drops another's — CI stays
green, and the dropped campaign's suites simply never run again.

This module proves coexistence three ways, strongest last:

1. **Structural** — GATES is a flat list of `(name, [paths])` with unique names,
   so appends compose by construction. Always runs.
2. **Fixture merge** — the two campaigns' verbatim appends are replayed onto the
   common ancestor and the result is parsed. Always runs, no git required.
3. **Real 3-way merge** — `git merge-tree` merges this branch with the unmerged
   `cc-whole-site-residual-v1` branch in memory and the merged file is parsed.
   Runs whenever that commit is reachable.

The fixtures exist so (2) keeps working after the residual branch is merged and
deleted; (3) exists because a fixture proves what I recorded, not what git does.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GATE_FILE = REPO / "scripts" / "run_cio_hardening_ci.py"
FIXTURES = REPO / "fixtures" / "gate_registration"

#: Merge-base both campaigns branched from.
MERGE_BASE = "abbe880e6817c963d8473767c1df674a13996527"
#: cc-whole-site-residual-v1-20260903 final SHA (BLOCKED, unmerged).
RESIDUAL_SHA = "49a7be707bdf8f5fbbdf8cd65ea40e2761a964f2"

#: The nine gates the residual campaign registers.
RESIDUAL_GATES = (
    "state_root_convergence",
    "whole_site_surface_truth",
    "effective_truth",
    "state_root_disposition",
    "protection_truth",
    "route_error_containment",
    "ci_fixture_immutability",
    "operator_control_isolated_db",
    "useapi_authorization_contract",
)
#: The gate this campaign registers.
RESEARCH_GATE = "brave_research_router"

RESEARCH_SUITES = (
    "tests/test_brave_research_router.py",
    "tests/test_brave_no_bypass.py",
    "tests/test_brave_research_provenance.py",
    "tests/test_brave_research_lanes.py",
    "tests/test_gate_registration_coexistence.py",
    "tests/test_brave_effectiveness_route.py",
    "tests/test_social_integrity.py",
    "tests/test_research_e2e_trace.py",
)


# ── helpers ─────────────────────────────────────────────────────────────────


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=180, check=False)


def gate_names(source: str) -> list[str]:
    """Parse GATES out of module source. Returns names in list order.

    Parsed with `ast`, not a regex: a regex over the raw file also matches gate
    names quoted inside the explanatory comments both campaigns wrote, which
    would make a dropped tuple look present.
    """
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(getattr(t, "id", None) == "GATES" for t in node.targets):
            continue
        names: list[str] = []
        for elt in node.value.elts:  # type: ignore[attr-defined]
            assert isinstance(elt, ast.Tuple), "GATES entry is not a tuple"
            first = elt.elts[0]
            assert isinstance(first, ast.Constant) and isinstance(first.value, str), (
                "GATES entry does not start with a string name"
            )
            names.append(first.value)
        return names
    raise AssertionError("no GATES assignment found")


def gate_map(source: str) -> dict[str, list[str]]:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "GATES" for t in node.targets):
            out: dict[str, list[str]] = {}
            for elt in node.value.elts:  # type: ignore[attr-defined]
                name = elt.elts[0].value
                paths = [p.value for p in elt.elts[1].elts]
                out[name] = paths
            return out
    raise AssertionError("no GATES assignment found")


# ── 1. Structural: appends compose by construction ──────────────────────────


def test_gates_is_a_flat_list_of_named_tuples():
    names = gate_names(GATE_FILE.read_text(encoding="utf-8"))
    assert len(names) > 10
    assert len(names) == len(set(names)), f"duplicate gate names make one registration shadow another: {names}"


def test_this_campaigns_registration_is_a_pure_append_at_the_end():
    """Appending at the END keeps the hunk far from other campaigns' appends.

    The residual campaign appends at ~line 620; this one at the list tail. Two
    pure appends 30+ lines apart merge without a conflict.
    """
    names = gate_names(GATE_FILE.read_text(encoding="utf-8"))
    assert RESEARCH_GATE in names, "the research gate registration is missing"
    assert names[-1] == RESEARCH_GATE, (
        f"research registration is no longer last (found {names[-1]!r}); it was "
        f"placed at the tail deliberately to stay clear of other campaigns"
    )


def test_the_registration_names_every_suite_it_claims():
    gates = gate_map(GATE_FILE.read_text(encoding="utf-8"))
    assert sorted(gates[RESEARCH_GATE]) == sorted(RESEARCH_SUITES)
    for rel in RESEARCH_SUITES:
        assert (REPO / rel).is_file(), f"{rel} is registered but does not exist"


# ── 2. Fixture merge: replay both verbatim appends onto the ancestor ────────


def _ancestor_source() -> str:
    r = _git("show", f"{MERGE_BASE}:scripts/run_cio_hardening_ci.py")
    if r.returncode != 0:
        pytest.skip(f"merge-base {MERGE_BASE[:9]} not present in this clone")
    return r.stdout


def _append_before_close(source: str, block: str) -> str:
    """Insert a GATES block immediately before the list's closing bracket."""
    lines = source.splitlines(keepends=True)
    start = next(i for i, ln in enumerate(lines) if ln.startswith("GATES = ["))
    close = next(i for i in range(start, len(lines)) if lines[i].startswith("]"))
    return "".join(lines[:close]) + block + "".join(lines[close:])


def test_both_verbatim_appends_replay_onto_the_ancestor_and_coexist():
    residual = (FIXTURES / "residual_gates_append.py.txt").read_text(encoding="utf-8")
    research = (FIXTURES / "research_gates_append.py.txt").read_text(encoding="utf-8")

    combined = _append_before_close(_append_before_close(_ancestor_source(), residual), research)
    names = gate_names(combined)  # parses => the combination is valid Python

    for g in RESIDUAL_GATES:
        assert g in names, f"residual campaign gate {g!r} was lost in the combination"
    assert RESEARCH_GATE in names, "research gate was lost in the combination"
    assert len(names) == len(set(names)), "combination produced a duplicate gate name"


def test_the_combination_is_additive_not_replacing():
    """The arithmetic that catches a silent drop: base + 9 + 1, exactly."""
    base = gate_names(_ancestor_source())
    residual = (FIXTURES / "residual_gates_append.py.txt").read_text(encoding="utf-8")
    research = (FIXTURES / "research_gates_append.py.txt").read_text(encoding="utf-8")

    only_residual = gate_names(_append_before_close(_ancestor_source(), residual))
    only_research = gate_names(_append_before_close(_ancestor_source(), research))
    both = gate_names(_append_before_close(_append_before_close(_ancestor_source(), residual), research))

    assert len(only_residual) == len(base) + len(RESIDUAL_GATES)
    assert len(only_research) == len(base) + 1
    assert len(both) == len(base) + len(RESIDUAL_GATES) + 1, (
        f"combined list has {len(both)} gates; expected {len(base)} + "
        f"{len(RESIDUAL_GATES)} + 1 — one campaign's tuples were dropped"
    )
    # Order is preserved: the ancestor's gates keep their positions.
    assert both[: len(base)] == base


def test_the_residual_fixture_is_the_residual_campaigns_actual_append():
    """Guard against the fixture drifting from what that branch really contains."""
    r = _git("cat-file", "-e", RESIDUAL_SHA)
    if r.returncode != 0:
        pytest.skip(f"residual commit {RESIDUAL_SHA[:9]} not reachable in this clone")
    diff = _git("diff", MERGE_BASE, RESIDUAL_SHA, "--", "scripts/run_cio_hardening_ci.py")
    added = "".join(ln[1:] + "\n" for ln in diff.stdout.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    fixture = (FIXTURES / "residual_gates_append.py.txt").read_text(encoding="utf-8")
    assert added == fixture, (
        "fixtures/gate_registration/residual_gates_append.py.txt no longer matches "
        "the residual campaign's actual append — regenerate it"
    )


# ── 3. Real 3-way merge, in memory, no worktree ─────────────────────────────


def _merge_tree_oid() -> str | None:
    """git merge-tree --write-tree HEAD <residual>. None when unavailable."""
    if _git("cat-file", "-e", RESIDUAL_SHA).returncode != 0:
        return None
    r = _git("merge-tree", "--write-tree", "HEAD", RESIDUAL_SHA)
    if r.returncode not in (0, 1):  # 1 == merged with conflicts
        return None
    oid = r.stdout.splitlines()[0].strip() if r.stdout.strip() else ""
    return oid or None


def test_a_real_three_way_merge_keeps_both_registrations():
    oid = _merge_tree_oid()
    if oid is None:
        pytest.skip(
            f"residual commit {RESIDUAL_SHA[:9]} not reachable; fixture-replay tests above still cover the property"
        )

    r = _git("show", f"{oid}:scripts/run_cio_hardening_ci.py")
    assert r.returncode == 0, f"merged tree has no gate file: {r.stderr[-300:]}"
    merged = r.stdout
    assert "<<<<<<<" not in merged, "the GATES file conflicted on a real merge"

    names = gate_names(merged)
    missing_residual = [g for g in RESIDUAL_GATES if g not in names]
    assert not missing_residual, f"a real merge dropped the residual campaign's gates: {missing_residual}"
    assert RESEARCH_GATE in names, "a real merge dropped the research gate"
    assert len(names) == len(set(names))


def test_no_gate_tuple_from_main_is_altered_by_this_branch():
    """The durable form of "preserved verbatim".

    The original assertion compared the merged file against the residual
    campaign's 93-line diff at `49a7be70`. That held while `49a7be70` was that
    campaign's final SHA — but it kept working after `49a7be70`, reorganised
    its own GATES entries, and merged a different final state. The frozen block
    is therefore not contiguous even on `origin/main`, and asserting it would
    fail for a reason that has nothing to do with this lane.

    What must be true is narrower and permanent: **every gate tuple present on
    `origin/main` appears in this branch with identical paths.** That catches a
    dropped tuple, a reordered path list, and a silently edited registration,
    without freezing another campaign's history.
    """
    main_src = _git("show", "origin/main:scripts/run_cio_hardening_ci.py")
    if main_src.returncode != 0:
        pytest.skip("origin/main not available in this clone")

    theirs = gate_map(main_src.stdout)
    mine = gate_map(GATE_FILE.read_text(encoding="utf-8"))

    missing = sorted(set(theirs) - set(mine))
    assert not missing, f"this branch dropped gates that exist on main: {missing}"

    altered = {name: (paths, mine[name]) for name, paths in theirs.items() if mine[name] != paths}
    assert not altered, f"this branch altered the suite list of gates it does not own: {sorted(altered)}"

    added = sorted(set(mine) - set(theirs))
    assert added == [RESEARCH_GATE], f"this branch adds gates beyond its own registration: {added}"


def test_the_residual_campaigns_gates_are_all_present():
    """Named explicitly, so a future merge that loses one is named too."""
    mine = gate_names(GATE_FILE.read_text(encoding="utf-8"))
    missing = [g for g in RESIDUAL_GATES if g not in mine]
    assert not missing, f"residual campaign gates absent from this branch: {missing}"


def test_the_research_fixture_matches_the_working_tree():
    """Drift guard, symmetric to the residual one.

    The fixture is what the coexistence proof replays, so a fixture that has
    drifted from the real registration proves coexistence of something that is
    no longer in the file.
    """
    diff = _git("diff", "origin/main", "--", "scripts/run_cio_hardening_ci.py")
    if diff.returncode != 0:
        pytest.skip("origin/main not available in this clone")
    added = "".join(ln[1:] + "\n" for ln in diff.stdout.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    fixture = (FIXTURES / "research_gates_append.py.txt").read_text(encoding="utf-8")
    assert added == fixture, (
        "fixtures/gate_registration/research_gates_append.py.txt no longer "
        "matches this campaign's actual append to GATES — regenerate it"
    )


def test_the_merged_gate_file_still_imports():
    """A merge that keeps both tuples but breaks the module helps nobody."""
    oid = _merge_tree_oid()
    if oid is None:
        pytest.skip(f"residual commit {RESIDUAL_SHA[:9]} not reachable")
    merged = _git("show", f"{oid}:scripts/run_cio_hardening_ci.py").stdout
    ast.parse(merged)  # raises SyntaxError if the merge broke it


def test_neither_campaign_registers_a_suite_the_other_owns():
    """Overlapping registration would let one gate mask the other's failure.

    Scoped to the suites the two campaigns *add*. The ancestor already contains
    two duplicates of its own — `tests/test_cio_brain_frontend.py` and
    `tests/test_cio_brain_snapshot.py` each appear in both
    `r11_operator_value_tier0` and `r13_institutional` — which neither campaign
    introduced and neither should be blamed for. Asserting a global
    uniqueness property here would fail on inherited debt and say nothing about
    coexistence.
    """
    ancestor = gate_map(_ancestor_source())
    residual = (FIXTURES / "residual_gates_append.py.txt").read_text(encoding="utf-8")
    research = (FIXTURES / "research_gates_append.py.txt").read_text(encoding="utf-8")

    res_only = gate_map(_append_before_close(_ancestor_source(), residual))
    rsc_only = gate_map(_append_before_close(_ancestor_source(), research))

    ancestor_paths = {p for paths in ancestor.values() for p in paths}
    residual_new = {p for g, paths in res_only.items() if g in RESIDUAL_GATES for p in paths}
    research_new = set(rsc_only[RESEARCH_GATE])

    overlap = residual_new & research_new
    assert not overlap, f"both campaigns register the same suites: {sorted(overlap)}"

    for label, added in (("residual", residual_new), ("research", research_new)):
        clash = added & ancestor_paths
        assert not clash, (
            f"the {label} campaign re-registers suites the ancestor already "
            f"owns, which would run them twice and mask ownership: {sorted(clash)}"
        )


def test_inherited_duplicate_registration_is_recorded_not_hidden():
    """The ancestor's own duplicate is pinned so it cannot grow unnoticed."""
    ancestor = gate_map(_ancestor_source())
    seen: dict[str, str] = {}
    dupes: list[tuple[str, str, str]] = []
    for gate, paths in ancestor.items():
        for p in paths:
            if p in seen and seen[p] != gate:
                dupes.append((p, seen[p], gate))
            seen[p] = gate
    assert dupes == [
        ("tests/test_cio_brain_frontend.py", "r11_operator_value_tier0", "r13_institutional"),
        ("tests/test_cio_brain_snapshot.py", "r11_operator_value_tier0", "r13_institutional"),
    ], f"inherited duplicate-registration debt changed: {dupes}"
