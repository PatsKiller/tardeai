#!/usr/bin/env python3
"""Every audited store gets one verdict, and detection is not called resolution.

No network, broker or production path. The taxonomy tests run on synthetic scans;
one live test asserts the shape of the real audit without asserting counts that
change as producers run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.state_root_disposition import (  # noqa: E402
    CONVERGED,
    DISPOSITIONS,
    INTENTIONALLY_SEPARATE,
    MIGRATION_REQUIRED,
    RETIRED,
    disposition_for,
    state_root_disposition,
)


@pytest.fixture
def roots(tmp_path):
    """Real files on disk. A fixture that claims a file exists without creating it
    is classified UNREADABLE — correctly — and proves nothing about forks."""
    p, s = tmp_path / "producer", tmp_path / "served"
    p.mkdir()
    s.mkdir()
    return p, s


def make_store(
    roots,
    name,
    verdict,
    direction,
    p_exists=True,
    s_exists=True,
    skew=3600.0,
    p_body='{"schema": "Thing@v1", "n": 1}',
    s_body='{"schema": "Thing@v1", "n": 2}',
):
    p_root, s_root = roots
    if p_exists:
        (p_root / name).write_text(p_body)
    if s_exists:
        (s_root / name).write_text(s_body)
    return {
        "store": name,
        "verdict": verdict,
        "direction": direction,
        "producer_path": str(p_root / name),
        "served_path": str(s_root / name),
        "producer": {"exists": p_exists, "mtime_utc": "2026-09-03T10:00:00+00:00", "bytes": len(p_body)},
        "served": {"exists": s_exists, "mtime_utc": "2026-09-01T10:00:00+00:00", "bytes": len(s_body)},
        "skew_seconds": skew,
    }


def test_the_taxonomy_is_closed():
    assert set(DISPOSITIONS) == {
        "CONVERGED",
        "INTENTIONALLY_SEPARATE",
        "MIGRATION_REQUIRED",
        "RETIRED",
        "UNREADABLE",
        "UNKNOWN_BLOCKING",
    }


def test_identical_stores_are_converged(roots):
    row = disposition_for(make_store(roots, "a.json", "IDENTICAL", "NEITHER"), cc_src="")
    assert row["disposition"] == CONVERGED
    assert row["blocking"] is False


def test_a_real_fork_requires_migration_and_says_it_cannot_run_here(roots):
    row = disposition_for(make_store(roots, "stops.json", "DIVERGENT", "PRODUCER_AHEAD"), cc_src="stops.json")
    assert row["disposition"] == MIGRATION_REQUIRED
    assert row["executable_by_this_lane"] is False
    assert "AGENTS.md rule 5" in row["why_not_executable"]
    assert len(row["migration_plan"]) >= 5
    assert row["unique_information"]["both_sides_retained"] is True


def test_a_migration_plan_names_a_canonical_target_and_an_owner(roots):
    row = disposition_for(make_store(roots, "x.json", "DIVERGENT", "SERVED_AHEAD"), cc_src="")
    assert row["canonical_target"].endswith("/served/x.json")
    assert row["canonical_rule"]
    assert row["owner"]


def test_a_store_nothing_reads_or_writes_is_retired(roots):
    row = disposition_for(make_store(roots, "ghost.json", "PRODUCER_ONLY", "NEITHER", s_exists=False), cc_src="")
    assert row["disposition"] == RETIRED


def test_a_missing_store_on_both_sides_is_retired(roots):
    row = disposition_for(
        make_store(roots, "gone.json", "ABSENT", "NEITHER", p_exists=False, s_exists=False), cc_src=""
    )
    assert row["disposition"] == RETIRED


def test_cc_criticality_is_derived_from_the_surface_not_asserted(roots):
    fork = make_store(roots, "used.json", "DIVERGENT", "PRODUCER_AHEAD")
    assert disposition_for(fork, cc_src="")["cc_critical"] is False
    assert disposition_for(fork, cc_src='x = "used.json"')["cc_critical"] is True


def test_a_cc_critical_fork_is_blocking_and_a_converged_one_is_not(roots):
    fork = disposition_for(make_store(roots, "used.json", "DIVERGENT", "PRODUCER_AHEAD"), cc_src="used.json")
    ok = disposition_for(make_store(roots, "used2.json", "IDENTICAL", "NEITHER"), cc_src="used2.json")
    assert fork["blocking"] is True
    assert ok["blocking"] is False


def test_readiness_requires_every_cc_critical_store_to_be_settled(roots):
    scan = {
        "producer_root": "/p",
        "served_root": "/s",
        "stores": [
            make_store(roots, "clean.json", "IDENTICAL", "NEITHER"),
            make_store(roots, "forked.json", "DIVERGENT", "PRODUCER_AHEAD"),
        ],
    }
    blocked = state_root_disposition_with(scan, cc_src="forked.json")
    assert blocked["ready"] is False
    assert blocked["blocking_stores"] == ["forked.json"]

    unused = state_root_disposition_with(scan, cc_src="")
    assert unused["ready"] is True, "a fork nothing renders is not a readiness blocker"
    assert unused["disposition_counts"][MIGRATION_REQUIRED] == 1, "it is still an open fork; it is simply not blocking"


def state_root_disposition_with(scan, cc_src):
    """Run the disposition against an explicit surface source, for testability."""
    import lib.state_root_disposition as mod

    original = mod.CC_SURFACE
    tmp = Path(__file__).parent / "_cc_src_probe.txt"
    tmp.write_text(cc_src)
    mod.CC_SURFACE = tmp
    try:
        return mod.state_root_disposition(scan)
    finally:
        mod.CC_SURFACE = original
        tmp.unlink(missing_ok=True)


def test_the_report_never_claims_it_resolved_anything(roots):
    scan = {
        "producer_root": "/p",
        "served_root": "/s",
        "stores": [make_store(roots, "f.json", "DIVERGENT", "PRODUCER_AHEAD")],
    }
    rep = state_root_disposition_with(scan, cc_src="")
    assert rep["auto_remediate"] is False
    assert "RESOLUTION IS NOT" in rep["note"]


def test_the_live_audit_has_a_verdict_for_every_store():
    from lib.state_root_divergence import scan as live_scan

    rep = state_root_disposition(live_scan(with_hashes=False))
    assert rep["audited_store_count"] > 0
    assert sum(rep["disposition_counts"].values()) == rep["audited_store_count"]
    for row in rep["stores"]:
        assert row["disposition"] in DISPOSITIONS
        assert row["evidence"]
    assert rep["cc_critical_count"] >= 1
    assert isinstance(rep["ready"], bool)


def test_the_contract_is_registered_and_fails_closed():
    src = (ROOT / "scripts" / "api_v2.py").read_text(errors="replace")
    assert '"/api/v2/system/state-root-disposition"' in src
    fn = src[src.index("def _state_root_disposition()") :]
    fn = fn[: fn.index("\ndef ")]
    assert "UNAVAILABLE" in fn and "reason" in fn


def test_the_module_never_writes_a_store():
    src = (ROOT / "scripts" / "lib" / "state_root_disposition.py").read_text()
    for banned in ("write_text", "shutil.copy", "shutil.move", "os.replace", "unlink", "rmtree"):
        assert banned not in src, f"a report module must not contain {banned}"
