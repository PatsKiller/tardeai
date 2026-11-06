from scripts.lib.cio_agent_brief import build_brief, render_telegram
from scripts.lib import cio_agent_brief
from tests.test_conflict_ledger import NOW, SUBJECT, KEY, conflict, decision, ledger
import pytest


@pytest.fixture(autouse=True)
def unrelated_brief_sources(monkeypatch):
    monkeypatch.setattr(cio_agent_brief, "could_not_do", lambda root: {
        "lanes": [], "unstamped_domains": [], "blocked_purposes": []})
    monkeypatch.setattr(cio_agent_brief, "acted_on_memory", lambda root: {})


def test_cio_telegram_brief_uses_recorded_decision_reason_without_claiming_clear(tmp_path):
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    st.transition(KEY, "decided", at=NOW, decision=decision(), apply=True)
    brief = build_brief(root=tmp_path, now=NOW)
    text = render_telegram(brief)
    assert brief["conflicts"]["decided"][0]["state"] == "DECIDED"
    assert "I recorded SYM: WATCH" in text and "evidence reviewed" in text
    assert "resolved SYM" not in text


def test_missing_ledger_is_an_explicit_brief_gap(tmp_path):
    brief = build_brief(root=tmp_path, now=NOW)
    assert brief["conflicts"]["gap"]
    assert "Conflicts* — evaluation unavailable" in render_telegram(brief)


def test_operator_items_are_grouped_in_the_existing_brief(tmp_path):
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict(kind="NEEDS_OPERATOR", never_auto=True)], at=NOW, apply=True)
    brief = build_brief(root=tmp_path, now=NOW)
    assert len(brief["conflicts"]["waiting_on_operator"]) == 1
    assert "1 waiting on you (U7): SYM" in render_telegram(brief)


def test_waiting_items_carry_their_age_so_a_backlog_is_not_a_queue(tmp_path):
    """The brief said "1 waiting on you" for an item a minute old and one nine days old alike."""
    from datetime import timedelta
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict(kind="NEEDS_OPERATOR", never_auto=True)], at=NOW - timedelta(hours=26), apply=True)
    brief = build_brief(root=tmp_path, now=NOW)
    assert brief["conflicts"]["waiting_on_operator"][0]["age_hours"] == 26.0
    text = render_telegram(brief)
    assert "1 waiting on you (U7): SYM · oldest 26h" in text


def test_an_unreadable_open_time_says_unknown_instead_of_inventing_zero():
    from datetime import datetime, timezone
    from scripts.lib.conflicts import cio
    now = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
    rows = cio._waiting_with_age([{"kind": "NEEDS_OPERATOR", "state": "OPEN", "opened_at": None,
                                   "rule": "R12", "subject": {"label": "X"}}], now)
    assert rows[0]["age_hours"] is None
    assert cio.age_text(None) == "age unknown"


@pytest.mark.parametrize("hours,text", [(0.5, "30m"), (0.99, "59m"), (26.0, "26h"), (47.9, "48h"), (72.0, "3d")])
def test_age_text_stays_short_enough_for_a_telegram_line(hours, text):
    from scripts.lib.conflicts.cio import age_text
    assert age_text(hours) == text


def test_five_waiting_items_are_not_reported_as_four(tmp_path):
    """The brief lists four names; it must say so when more are waiting."""
    from tests.test_conflict_ledger import Subject
    st = ledger(tmp_path)
    subjects = [Subject("security", f"guid-{i}", f"S{i}", {"held": False, "identity_confirmed": True})
                for i in range(5)]
    for i, subject in enumerate(subjects):
        st.reconcile(subject, [conflict(kind="NEEDS_OPERATOR", never_auto=True,
                                       key=f"security:guid-{i}:U7:desk")], at=NOW, apply=True)
    text = render_telegram(build_brief(root=tmp_path, now=NOW))
    assert "5 waiting on you (U7)" in text and "+1 more" in text
