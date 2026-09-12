"""A lane must be able to prove it RAN, not only that it produced.

CL-46, a defect in this campaign's own earlier work. `config/lane_registry.json`
declares `material-change-detector-stage1` with

    {"kind": "db_max", "table": "material_changes", "column": "created_at"}

and the commit that added it argued this "keys on the table it exists to write".
That is right about the failure it was chosen to catch — the lane sitting at 178
rows while cron ran it 30 more times — and wrong about a failure it creates.

`persist()` uses ON CONFLICT (change_guid) DO NOTHING. A run that correctly
finds only already-recorded changes writes nothing, so max(created_at) does not
move. Measured 2026-09-12T02:45Z: newest row 00:30Z, four correct runs in
between, lane reporting SLOW on its way to SILENT.

The heartbeat advances on every successful run regardless of what was written,
and carries the write_disposition so "nothing was new" stays distinguishable
from "stopped" — which a max() over rows the producer correctly declined to
write can never do.
"""

from __future__ import annotations

import json

import pytest

from scripts.material_change_detector import (
    build_health_record,
    health_path,
)


def test_the_heartbeat_advances_even_when_nothing_was_written():
    """The whole point: a fully deduped run is a successful run."""
    rec = build_health_record(
        universe=517, changes_found=25,
        write={"attempted": 25, "written": 0, "already_present": 25,
               "disposition": "ALL_ALREADY_PRESENT"},
        source_sha="71f4e7a71", now="2026-09-12T02:30:00Z")
    assert rec["as_of"] == "2026-09-12T02:30:00Z"
    assert rec["last_success_at"] == "2026-09-12T02:30:00Z"
    assert rec["outcome"] == "ALL_ALREADY_PRESENT"
    assert rec["written"] == 0
    assert rec["already_present"] == 25


def test_an_unexplained_zero_is_not_a_success():
    """Rows attempted, none landed, dedup does not account for it."""
    rec = build_health_record(
        universe=517, changes_found=25,
        write={"attempted": 25, "written": 0, "already_present": 0,
               "disposition": "WROTE_NOTHING_UNEXPLAINED"},
        source_sha="71f4e7a71", now="2026-09-12T02:30:00Z")
    assert rec["outcome"] == "WROTE_NOTHING_UNEXPLAINED"
    assert rec["last_success_at"] is None, (
        "an unexplained zero must not stamp last_success_at, or the heartbeat "
        "becomes the same lie the old health predicate told"
    )


def test_the_record_carries_the_identity_an_auditor_needs():
    rec = build_health_record(
        universe=517, changes_found=0,
        write={"attempted": 0, "written": 0, "already_present": 0,
               "disposition": "NOTHING_DETECTED"},
        source_sha="71f4e7a71440dba95b0910b43a86ca9f685a68f5",
        now="2026-09-12T03:00:00Z")
    assert rec["schema"] == "MaterialChangeDetectorHealth@v1"
    assert rec["source_sha"] == "71f4e7a71440dba95b0910b43a86ca9f685a68f5"
    assert rec["universe"] == 517
    assert rec["authority"] == "READ_ONLY_ADVISORY"
    assert rec["financial_action"] is False


def test_the_path_is_outside_both_trees():
    """It must NOT live under $PROJ/data/runtime. The detector runs from the
    canonical tree, and that directory is on the producer side of the
    state-root split this campaign documented — the served plane would never
    see it, so a lane keyed on it would read SILENT forever."""
    p = str(health_path())
    assert "trade-ai-v12-rebuild" not in p, (
        f"health path {p} is inside the canonical tree; the served plane "
        "cannot see it"
    )
    assert "/portfolio-server/" not in p, (
        f"health path {p} is inside a release; it would not survive a promote"
    )
    assert p.endswith(".json")


def test_the_path_is_env_overridable():
    import os
    from scripts.material_change_detector import health_path as hp
    assert str(hp({"TRADEAI_MATERIAL_CHANGE_HEALTH_PATH": "/tmp/x.json"})) == "/tmp/x.json"


def test_nothing_detected_is_still_a_successful_run():
    """An empty market is not a broken detector."""
    rec = build_health_record(
        universe=517, changes_found=0,
        write={"attempted": 0, "written": 0, "already_present": 0,
               "disposition": "NOTHING_DETECTED"},
        source_sha="abc", now="2026-09-12T03:00:00Z")
    assert rec["last_success_at"] == "2026-09-12T03:00:00Z"
