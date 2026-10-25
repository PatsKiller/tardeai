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
