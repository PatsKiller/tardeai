"""Check 3 is named for a critique. Only a critique may satisfy it.

On 2026-08-30 a residual_web hop turned it GREEN: the check accepted a bare
`last_artifact_id`, so ANY artifact counted. artifact rw_8893dcc5aad5be6c, lane
residual_web, zero grok lessons — and the board reported "Grok critique attach
OR reject persisted" while the critique lane had never run.

A green obtained by the wrong artifact type is worse than a red, because a red
gets investigated.
"""
import pytest

from scripts.lib.cio_preconditions_board import _critique_evidence, _is_critique_shaped


def _rec(**kw):
    base = {"subject_key": "HELD:SCHD", "lessons": []}
    base.update(kw)
    return base


def test_a_residual_web_attach_does_not_satisfy_it():
    """The exact record that produced the false green."""
    rec = _rec(last_artifact_id="rw_8893dcc5aad5be6c",
               last_outcome="partial", last_lane="residual_web")
    assert _is_critique_shaped(rec) is False
    assert _critique_evidence(rec) is None


def test_a_grok_critique_reject_does_satisfy_it():
    rec = _rec(last_artifact_id="grok_critique_ebb4120ba659",
               last_outcome="rejected", research_blocked=True, last_lane="grok")
    ev = _critique_evidence(rec)
    assert ev and ev["kind"] == "reject"


def test_a_grok_critique_attach_does_satisfy_it():
    rec = _rec(last_artifact_id="grok_critique_abc", last_outcome="valid")
    ev = _critique_evidence(rec)
    assert ev and ev["kind"] == "attach"


def test_a_critique_lesson_alone_is_enough():
    rec = _rec(lessons=[{"lesson_id": "x", "claim": "grok critique rejected it"}],
               last_outcome="valid")
    assert _is_critique_shaped(rec) is True


@pytest.mark.parametrize("marker", ["grok", "critique", "red_team", "devils_advocate"])
def test_every_marker_is_recognised(marker):
    assert _is_critique_shaped(_rec(last_provider=f"{marker}_v1")) is True


def test_a_plain_research_attach_is_still_not_a_critique():
    """Real work, still not what this check is named for."""
    for lane in ("residual_web", "flash", "pro", "corpus_hit"):
        rec = _rec(last_artifact_id="art_123", last_outcome="valid", last_lane=lane)
        assert _critique_evidence(rec) is None, lane


def test_a_blocked_record_without_a_critique_does_not_count():
    """research_blocked can be set by the execution-language guard too."""
    rec = _rec(research_blocked=True, last_outcome="execution_language",
               last_lane="residual_web")
    assert _critique_evidence(rec) is None


def test_the_stale_policy_comment_is_corrected():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "scripts" / "lib"
           / "cio_grok_critique.py").read_text(encoding="utf-8")
    assert "STALE AS OF 2026-08-30" in src
    assert "no research process, today" not in src
