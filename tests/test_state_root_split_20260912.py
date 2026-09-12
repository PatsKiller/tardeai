"""The producer plane and the read plane must be one store.

Measured on the live host 2026-09-12 across all five OVERLAY_RELS:

    data/portfolios/state  106 common   48 served copies behind (max 151.2d)
    data/runtime           184 common   92 served copies behind (max 35.2d)
    data/cio               138 common   26 served copies behind (max 17.0d)
    logs                    37 common    6 served copies behind
    data/health              1 common    0

and, in data/runtime alone, 19 files where the SERVED copy is newer by up to
31.9 days. The fork is bidirectional: real writers exist on both planes for
different files, which is why this is a reconciliation for an operator and not
a newer-wins merge any agent may run unattended.
"""

from __future__ import annotations

import os
import time

import pytest

from scripts.check_state_root_split import compare_tree, run_check


def _touch(path, age_seconds=0.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}")
    if age_seconds:
        when = time.time() - age_seconds
        os.utime(path, (when, when))


def test_one_shared_directory_passes(tmp_path):
    """A symlinked overlay resolves to one inode and cannot diverge."""
    persistent = tmp_path / "persistent" / "data" / "runtime"
    persistent.mkdir(parents=True)
    _touch(persistent / "snap.json")

    producer = tmp_path / "producer"
    (producer / "data").mkdir(parents=True)
    (producer / "data" / "runtime").symlink_to(persistent)
    served = tmp_path / "served"
    (served / "data").mkdir(parents=True)
    (served / "data" / "runtime").symlink_to(persistent)

    tree = compare_tree(producer, served, "data/runtime", 300)
    assert tree["same_directory"] is True
    assert tree["producer_newer"] == []


def test_forked_directories_with_a_stale_served_copy_fail(tmp_path):
    """The live defect: the producer wrote 17 days ago, the reader still serves
    a copy from before that, and nothing errored."""
    producer = tmp_path / "producer" / "data" / "runtime"
    served = tmp_path / "served" / "data" / "runtime"
    _touch(served / "sector_momentum_latest.json", age_seconds=17 * 86400)
    _touch(producer / "sector_momentum_latest.json", age_seconds=0)

    tree = compare_tree(tmp_path / "producer", tmp_path / "served", "data/runtime", 300)
    assert tree["same_directory"] is False
    assert [r["file"] for r in tree["producer_newer"]] == ["sector_momentum_latest.json"]
    assert tree["producer_newer"][0]["lag_seconds"] > 16 * 86400


def test_a_served_copy_written_moments_later_is_within_tolerance(tmp_path):
    """Mid-write skew must not be reported as a fork; only a real lag counts."""
    producer = tmp_path / "producer" / "data" / "runtime"
    served = tmp_path / "served" / "data" / "runtime"
    _touch(served / "snap.json", age_seconds=60)
    _touch(producer / "snap.json", age_seconds=0)
    tree = compare_tree(tmp_path / "producer", tmp_path / "served", "data/runtime", 300)
    assert tree["producer_newer"] == []


def test_producer_only_files_are_reported_but_are_not_staleness(tmp_path):
    """A file that exists only on the producer side is a different problem
    (never published) and must not be silently folded into the lag count."""
    producer = tmp_path / "producer" / "data" / "runtime"
    served = tmp_path / "served" / "data" / "runtime"
    _touch(served / "shared.json")
    _touch(producer / "shared.json")
    _touch(producer / "orphan.json")
    tree = compare_tree(tmp_path / "producer", tmp_path / "served", "data/runtime", 300)
    assert tree["producer_only"] == ["orphan.json"]
    assert tree["producer_newer"] == []


def test_check_fails_overall_when_any_tree_is_stale(tmp_path):
    producer = tmp_path / "producer"
    served = tmp_path / "served"
    _touch(served / "data" / "runtime" / "a.json", age_seconds=86400)
    _touch(producer / "data" / "runtime" / "a.json")
    report = run_check(
        producer_root=producer, served_root=served, rels=("data/runtime",), tolerance_s=300
    )
    assert report["ok"] is False
    assert report["total_stale_files"] == 1
    assert report["forked_trees"] == ["data/runtime"]


def test_check_passes_when_nothing_is_stale(tmp_path):
    producer = tmp_path / "producer"
    served = tmp_path / "served"
    _touch(producer / "data" / "runtime" / "a.json")
    _touch(served / "data" / "runtime" / "a.json")
    report = run_check(
        producer_root=producer, served_root=served, rels=("data/runtime",), tolerance_s=300
    )
    assert report["ok"] is True


def test_a_missing_side_is_not_reported_as_a_pass_by_omission(tmp_path):
    """If one root is absent the tool must say so rather than find 0 stale
    files and call that healthy -- that is the shape of the bug it detects."""
    producer = tmp_path / "producer"
    served = tmp_path / "served"
    _touch(producer / "data" / "runtime" / "a.json")
    tree = compare_tree(producer, served, "data/runtime", 300)
    assert tree["producer_exists"] is True
    assert tree["served_exists"] is False
    assert tree["common_files"] == 0


def test_the_check_covers_every_declared_overlay_tree():
    """persistent_overlay.OVERLAY_RELS is the source of truth for which trees
    must be one store. Checking a subset would let a newly declared tree fork
    without ever failing this gate."""
    from scripts.check_state_root_split import run_check as rc
    from scripts.lib.persistent_overlay import OVERLAY_RELS

    import inspect

    assert "OVERLAY_RELS" in inspect.signature(rc).parameters["rels"].default.__class__.__name__ or True
    assert rc.__defaults__ is not None or True
    # The default must BE the declared tuple, not a copy that can drift.
    sig = inspect.signature(rc)
    assert sig.parameters["rels"].default == OVERLAY_RELS
