"""The brief that tells a working system from a silent one.

The system completed hundreds of workflows, admitted hundreds of memories and
wrote hundreds of lesson candidates, and the operator saw none of it. Silence and
a stopped system looked identical from the outside.

Two rules this suite defends, both learned from the first live render:

  * timestamp churn is not a change. The first render reported "98 field(s)
    moved" when nearly all were `cc_narrative.as_of` rewrites. Filtered, the true
    number was 9.
  * window and lifetime counts are never conflated. The first render printed
    "0 written" beside all-time totals, which reads as 336 lessons written today.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "scripts", ROOT / "scripts" / "lib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib import cio_agent_brief as ab  # noqa: E402

NOW = datetime.now(timezone.utc)
SINCE = NOW - timedelta(hours=24)


def _rec(subject, ts, **fields):
    r = {"subject_key": subject, "updated_ts": ts.isoformat()}
    r.update(fields)
    return r


# ── the noise rule ─────────────────────────────────────────────────────────

def test_a_timestamp_only_move_is_not_reported_as_a_change():
    a = _rec("HELD:X", NOW - timedelta(hours=2),
             cc_narrative={"what": "same sentence", "as_of": "2026-08-30T02:23:59"})
    b = _rec("HELD:X", NOW - timedelta(hours=1),
             cc_narrative={"what": "same sentence", "as_of": "2026-08-30T02:33:18"})
    assert ab.changed_because([a, b], SINCE)["changed"] == 0


def test_a_real_narrative_change_is_reported():
    a = _rec("HELD:X", NOW - timedelta(hours=2),
             cc_narrative={"what": "before", "as_of": "t1"})
    b = _rec("HELD:X", NOW - timedelta(hours=1),
             cc_narrative={"what": "after", "as_of": "t2"})
    out = ab.changed_because([a, b], SINCE)
    assert out["changed"] == 1
    assert out["changes"][0]["before"] == "before"
    assert out["changes"][0]["after"] == "after"


def test_the_before_after_is_readable_not_a_dict_dump():
    """A whole cc_narrative on a phone is noise; `what` is what a person reads."""
    a = _rec("HELD:X", NOW - timedelta(hours=2), cc_narrative={"what": "A", "risks": [1, 2, 3]})
    b = _rec("HELD:X", NOW - timedelta(hours=1), cc_narrative={"what": "B", "risks": [1, 2, 3]})
    c = ab.changed_because([a, b], SINCE)["changes"][0]
    assert c["before"] == "A" and c["after"] == "B"


# ── the "nothing changed" rule ─────────────────────────────────────────────

def test_nothing_changed_is_stated_not_omitted():
    """The most valuable sentence in the brief."""
    brief = {
        "as_of": NOW.isoformat(), "window_hours": 24,
        "looked_at": {"requests_raised": 0, "self_raised": 0, "operator_forced": 0,
                      "by_situation": {}},
        "came_back": {"completed": 0, "critique_verdicts": {}},
        "changed_because": {"changed": 0, "changes": []},
        "learned": {"written_in_window": 0, "window_research_derived": 0,
                    "window_outcome_derived": 0, "total": 0,
                    "total_research_derived": 0, "total_outcome_derived": 0},
        "could_not_do": {"lanes": [], "unstamped_domains": [], "blocked_purposes": []},
    }
    text = ab.render_telegram(brief)
    assert "nothing changed" in text.lower()


# ── the provenance rule ────────────────────────────────────────────────────

def test_research_and_outcome_lessons_are_never_blurred():
    lessons = [
        {"hermes_result_id": "r1"},
        {"hermes_result_id": "r2"},
        {"supporting_outcome_ids": ["o1"]},
    ]
    out = ab.learned(lessons, SINCE)
    assert out["total_research_derived"] == 2
    assert out["total_outcome_derived"] == 1


def test_window_and_lifetime_counts_are_separate_keys():
    lessons = [{"hermes_result_id": "r1"}]  # no created_ts -> outside window
    out = ab.learned(lessons, SINCE)
    assert out["written_in_window"] == 0
    assert out["total"] == 1
    assert "written" not in out, "the ambiguous single 'written' key must not return"


def test_no_outcome_derived_lesson_is_called_out(monkeypatch):
    brief = {
        "as_of": NOW.isoformat(), "window_hours": 24,
        "looked_at": {"requests_raised": 1, "self_raised": 1, "operator_forced": 0,
                      "by_situation": {"S1": 1}},
        "came_back": {"completed": 1, "critique_verdicts": {"VALID": 1}},
        "changed_because": {"changed": 0, "changes": []},
        "learned": {"written_in_window": 0, "window_research_derived": 0,
                    "window_outcome_derived": 0, "total": 337,
                    "total_research_derived": 336, "total_outcome_derived": 0},
        "could_not_do": {"lanes": [], "unstamped_domains": [], "blocked_purposes": []},
    }
    text = ab.render_telegram(brief)
    assert "not about money" in text


# ── the register rule ──────────────────────────────────────────────────────

def test_the_brief_labels_its_own_provenance_and_claims_no_judgment():
    brief = ab.build_brief.__doc__ or ""
    src = (ROOT / "scripts/lib/cio_agent_brief.py").read_text(encoding="utf-8")
    i = src.index("def render_telegram")
    block = src[i:]
    assert "class D" in block and "class T" in block
    assert "No judgment was exercised" in block


def test_it_declares_itself_reporting_only():
    src = (ROOT / "scripts/lib/cio_agent_brief.py").read_text(encoding="utf-8")
    assert "REPORTING ONLY" in src
    assert '"memory_behavior_influence": 0' in src
    assert '"financial_action": False' in src


# ── M5: what memory changed about what the agent DID ──────────────────────

def _brief_root(tmp_path, consult=None):
    import json as _j
    d = tmp_path / "data" / "cio"
    d.mkdir(parents=True, exist_ok=True)
    if consult is not None:
        (d / "wake_record_consult.json").write_text(_j.dumps(consult), encoding="utf-8")
    return tmp_path


def test_a_missing_consult_artifact_is_a_fault_not_a_quiet_day(tmp_path):
    """Silence must never be indistinguishable from 'nothing to report'."""
    from scripts.lib.cio_agent_brief import acted_on_memory
    got = acted_on_memory(_brief_root(tmp_path))
    assert got["state"] == "NOT_RUNNING"
    assert "not consulting" in got["note"] or "not running" in got["note"].lower()


def test_the_brief_says_a_missing_consult_is_a_fault(tmp_path):
    from scripts.lib.cio_agent_brief import render_telegram
    brief = {"as_of": "2026-08-30T12:00:00Z", "window_hours": 24,
             "looked_at": {"requests_raised": 0, "self_raised": 0,
                           "operator_forced": 0, "by_situation": {}},
             "came_back": {"completed": 0, "critique_verdicts": {}},
             "changed_because": {"changed": 0, "changes": []},
             "learned": {"written_in_window": 0, "total": 0,
                         "total_research_derived": 0, "total_outcome_derived": 0},
             "acted_on_memory": {"state": "NOT_RUNNING", "note": "absent"},
             "could_not_do": {"lanes": [], "unstamped_domains": [],
                              "blocked_purposes": []}}
    out = render_telegram(brief)
    assert "not consulting the record" in out
    assert "fault, not a quiet day" in out


def test_the_brief_reads_the_scheduled_artifact_rather_than_recomputing(tmp_path):
    """Recomputing would report what the record WOULD have changed, which is a
    different claim from what it DID change on a schedule."""
    from scripts.lib.cio_agent_brief import acted_on_memory
    got = acted_on_memory(_brief_root(tmp_path, consult={
        "as_of": "2026-08-30T23:15:00+00:00", "unattended": True,
        "wakes_considered": 1515, "subject_resolved": 1,
        "decisions_changed_by_record": 1, "skipped_cadence_not_due": 1,
        "no_subject": 1514,
        "changed": [{"subject_key": "HELD:SCHD", "without_record": "proceed",
                     "with_record": "skip/cadence_not_due", "reason": "deferred"}]}))
    assert got["state"] == "RUNNING"
    assert got["unattended"] is True
    assert got["decisions_changed_by_record"] == 1
    assert got["changed"][0]["subject_key"] == "HELD:SCHD"


def test_zero_changes_is_reported_as_read_and_nothing_applied(tmp_path):
    """'Nothing changed today' is a valid brief — but it must be distinguishable
    from the lane not running at all."""
    from scripts.lib.cio_agent_brief import render_telegram
    brief = {"as_of": "2026-08-30T12:00:00Z", "window_hours": 24,
             "looked_at": {"requests_raised": 0, "self_raised": 0,
                           "operator_forced": 0, "by_situation": {}},
             "came_back": {"completed": 0, "critique_verdicts": {}},
             "changed_because": {"changed": 0, "changes": []},
             "learned": {"written_in_window": 0, "total": 0,
                         "total_research_derived": 0, "total_outcome_derived": 0},
             "acted_on_memory": {"state": "RUNNING", "wakes_considered": 12,
                                 "subject_resolved": 0,
                                 "decisions_changed_by_record": 0, "changed": []},
             "could_not_do": {"lanes": [], "unstamped_domains": [],
                              "blocked_purposes": []}}
    out = render_telegram(brief)
    assert "the record changed nothing today" in out
    assert "fault" not in out.split("*Acted on memory*")[1].split("*Learned*")[0]
