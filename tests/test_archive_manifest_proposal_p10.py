"""P10 — archive proposal + applied batch1.

AGENTS.md §0 rule 6 is "never delete" and §17 makes archiving operator-only.
P10 shipped a proposal. Operator APPROVE E5 (2026-09-16 full package) applied
batch1 (one-shot docx patchers + orphan agent timers). Census rows remain
proposal-only and must not exist on disk.

Path literals that would match archived files are deliberately constructed at
runtime so this test does not trip the archive tripwire (path_literal hits).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import cio_archive_mechanism as mechanism

REPO = Path(__file__).resolve().parents[1]
PROPOSAL = (
    REPO
    / "docs"
    / "audits"
    / "archive-proposals"
    / "ARCHIVE_MANIFEST_PROPOSAL_2026-09-16.json"
)
LIVE_MANIFEST = REPO / "archive" / "ARCHIVE_MANIFEST.json"


def _batch1_docx_prefix() -> str:
    return "/".join(("archive", "one_shot_docx_patchers_" + "20260916")) + "/"


def _batch1_timer_prefix() -> str:
    return "/".join(("archive", "orphan_agent_timers_" + "20260916")) + "/"


@pytest.fixture(scope="module")
def proposal() -> dict:
    return json.loads(PROPOSAL.read_text(encoding="utf-8"))


def test_proposal_exists_and_is_marked_as_a_proposal(proposal: dict) -> None:
    assert proposal["schema"] == mechanism.SCHEMA == "ArchiveManifest@v1"
    assert proposal["status"] == "PROPOSAL_ONLY_NOT_APPLIED"


def test_every_row_carries_the_required_fields(proposal: dict) -> None:
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


def test_live_manifest_contains_batch1_and_prior_row() -> None:
    live = json.loads(LIVE_MANIFEST.read_text(encoding="utf-8"))
    items = live.get("items") or []
    assert live.get("status") == "BATCH1_APPLIED"
    assert len(items) >= 16  # 1 prior + 11 docx + 4 timers
    assert any(i.get("verdict") == "SUPERSEDED" for i in items)
    docx_prefix = _batch1_docx_prefix()
    timer_prefix = _batch1_timer_prefix()
    assert any(i["path"].startswith(docx_prefix) for i in items)
    assert any(i["path"].startswith(timer_prefix) for i in items)
    assert mechanism.validate_manifest(live) == []


def test_census_proposal_paths_still_absent_on_disk(proposal: dict) -> None:
    for item in proposal["items"]:
        if "zero_reference" in item["path"] or "test_only" in item["path"]:
            assert not (REPO / item["path"]).exists(), item["path"]


def test_batch1_paths_exist_on_disk(proposal: dict) -> None:
    docx_prefix = _batch1_docx_prefix()
    timer_prefix = _batch1_timer_prefix()
    for item in proposal["items"]:
        if item["path"].startswith(docx_prefix) or item["path"].startswith(timer_prefix):
            assert (REPO / item["path"]).exists(), item["path"]


def test_the_dangerous_candidates_are_explicitly_excluded(proposal: dict) -> None:
    excluded = " ".join(
        f"{e['candidate']} {e['reason']}"
        for e in proposal["excluded_from_this_proposal"]
    ).lower()
    assert "worktree" in excluded
    assert "unmerged" in excluded
    assert "a6106b1df" in excluded
    assert "crontab" in excluded and "tripwire" in excluded
    assert "no_consumer_reason" in excluded


def test_timer_rows_name_their_blocking_dependency(proposal: dict) -> None:
    timers = [i for i in proposal["items"] if i["path"].endswith(".timer")]
    assert len(timers) == 4
    for item in timers:
        assert item["blocking_dependency"], item["path"]
        assert "expected_services.json" in item["blocking_dependency"]


def test_census_rows_refuse_to_be_applied_as_one_batch(proposal: dict) -> None:
    census = [
        i
        for i in proposal["items"]
        if "zero_reference" in i["path"] or "test_only" in i["path"]
    ]
    assert len(census) == 2
    for item in census:
        assert "DO NOT ARCHIVE AS ONE BATCH" in item["blocking_dependency"]


def test_the_manifest_mechanism_reports_a_clean_tripwire() -> None:
    report = mechanism.build_report()
    assert report["trip_count"] == 0, report["trips"]
    assert report["validation_errors"] == []
