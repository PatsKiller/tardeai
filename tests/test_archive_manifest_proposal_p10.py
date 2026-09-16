"""P10 — the archive batch is a PROPOSAL, and nothing has been archived.

AGENTS.md §0 rule 6 is "never delete" and §17 makes deleting anything
operator-only. So the P10 clean-up produces a manifest proposal and stops. These
tests pin both halves: the proposal is well-formed against the existing
mechanism's schema, and no file has actually moved.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import cio_archive_mechanism as mechanism

REPO = Path(__file__).resolve().parents[1]
PROPOSAL = (REPO / "docs" / "audits" / "archive-proposals"
            / "ARCHIVE_MANIFEST_PROPOSAL_2026-09-16.json")
LIVE_MANIFEST = REPO / "archive" / "ARCHIVE_MANIFEST.json"


@pytest.fixture(scope="module")
def proposal() -> dict:
    return json.loads(PROPOSAL.read_text(encoding="utf-8"))


def test_proposal_exists_and_is_marked_as_a_proposal(proposal: dict) -> None:
    assert proposal["schema"] == mechanism.SCHEMA == "ArchiveManifest@v1"
    assert proposal["status"] == "PROPOSAL_ONLY_NOT_APPLIED"


def test_every_row_carries_the_required_fields(proposal: dict) -> None:
    """The mechanism's own required-field list, not a re-typed copy."""
    for item in proposal["items"]:
        for field in mechanism.REQUIRED_ITEM_FIELDS:
            assert item.get(field), f"{item.get('path')} missing {field}"


def test_every_verdict_is_one_the_mechanism_accepts(proposal: dict) -> None:
    for item in proposal["items"]:
        assert item["verdict"] in mechanism.ALLOWED_VERDICTS, item["verdict"]


def test_every_row_has_a_restore_command_and_a_review_date(proposal: dict) -> None:
    for item in proposal["items"]:
        assert item["restore_command"].strip()
        assert item["review_by"] > item["date"], (
            f"{item['path']}: review_by must be after the archive date"
        )


def test_nothing_has_actually_been_archived(proposal: dict) -> None:
    """The live manifest gained no rows from this proposal.

    Deliberately does NOT spell the one archived path out as a literal: the
    mechanism's tripwire treats a path literal as a live READ of an archived
    file, and an earlier draft of this very test tripped it. That is the
    tripwire working, so the test is written around it rather than added to the
    allowlist -- an allowlist entry here would blunt the check for everyone.
    """
    live = json.loads(LIVE_MANIFEST.read_text(encoding="utf-8"))
    items = live.get("items") or []
    assert len(items) == 1, (
        f"P10 must not add rows to the live manifest; found {len(items)}"
    )
    assert items[0]["verdict"] == "SUPERSEDED"
    proposed = {i["path"] for i in proposal["items"]}
    assert not (proposed & {i["path"] for i in items}), (
        "a proposed row has been applied to the live manifest"
    )


def test_no_proposed_path_exists_on_disk(proposal: dict) -> None:
    """A proposal that had already moved files would not be a proposal."""
    for item in proposal["items"]:
        assert not (REPO / item["path"]).exists(), (
            f"{item['path']} exists on disk — this batch must not be applied"
        )


def test_the_dangerous_candidates_are_explicitly_excluded(proposal: dict) -> None:
    """Worktrees, masked cron lines, and self-declared dormancy are off-limits."""
    excluded = " ".join(
        f"{e['candidate']} {e['reason']}" for e in proposal["excluded_from_this_proposal"]
    ).lower()
    assert "worktree" in excluded
    assert "unmerged" in excluded
    assert "a6106b1df" in excluded, "the unrescued commit must be named"
    assert "crontab" in excluded and "tripwire" in excluded
    assert "no_consumer_reason" in excluded


def test_timer_rows_name_their_blocking_dependency(proposal: dict) -> None:
    """Archiving a timer that five other files still declare creates an alarm.

    config/expected_services.json declares these timers expected-present and
    check_expected_services.py --alert fires MISSING against it, so a timer
    archived alone converts a silent no-op into a live alarm.
    """
    timers = [i for i in proposal["items"] if i["path"].endswith(".timer")]
    assert len(timers) == 4, "all four orphan timers must be proposed"
    for item in timers:
        assert item["blocking_dependency"], item["path"]
        assert "expected_services.json" in item["blocking_dependency"]


def test_census_rows_refuse_to_be_applied_as_one_batch(proposal: dict) -> None:
    """158 zero-ref and 76 test-only scripts are a census, not an approved list."""
    census = [i for i in proposal["items"]
              if "zero_reference" in i["path"] or "test_only" in i["path"]]
    assert len(census) == 2
    for item in census:
        assert "DO NOT ARCHIVE AS ONE BATCH" in item["blocking_dependency"]


def test_the_manifest_mechanism_still_reports_a_clean_tripwire() -> None:
    """Nothing in the repo reads an archived path."""
    report = mechanism.build_report()
    assert report["trip_count"] == 0, report["trips"]
    assert report["validation_errors"] == []
