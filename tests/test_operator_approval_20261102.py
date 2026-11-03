"""Only a GitHub comment URL by the operator authorises a grant-free push.

The guard rejected a free-text reference at push time ("it must be the URL of a GitHub comment by
the operator on the canonical repository"), so a claim must carry that form and say so early.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import operator_approval as OA  # noqa: E402

GOOD = "https://github.com/PatsKiller/tardeai/pull/2470#issuecomment-1234567890"


def test_a_canonical_comment_url_is_accepted():
    assert OA.validate(GOOD) == GOOD


def test_an_issue_url_on_the_canonical_repo_is_accepted():
    ref = "https://github.com/PatsKiller/tardeai/issues/42#issuecomment-7"
    assert OA.validate(ref) == ref


def test_a_free_text_reference_is_refused_with_the_fix():
    with pytest.raises(ValueError) as exc:
        OA.validate("operator in-session 2026-11-01, plan X, quote: 'do it'")
    text = str(exc.value)
    assert "not a GitHub comment URL" in text
    assert "approve-push" in text  # the exact command the operator runs


def test_a_comment_url_on_another_repository_is_refused():
    with pytest.raises(ValueError, match="must be a comment on PatsKiller/tardeai"):
        OA.validate("https://github.com/someone/other/pull/1#issuecomment-1")


def test_a_pull_url_without_a_comment_id_is_refused():
    with pytest.raises(ValueError, match="not a GitHub comment URL"):
        OA.validate("https://github.com/PatsKiller/tardeai/pull/2470")


def test_an_empty_ref_is_refused():
    with pytest.raises(ValueError, match="approval ref is required"):
        OA.validate("   ")


def test_the_line_format_the_guard_reads():
    assert OA.approval_line(GOOD) == f"Operator-approval: {GOOD}"


def test_merging_keeps_the_existing_note():
    assert OA.merge_into_note("built item 5", GOOD) == f"Operator-approval: {GOOD}\nbuilt item 5"
    assert OA.merge_into_note(None, None) is None
