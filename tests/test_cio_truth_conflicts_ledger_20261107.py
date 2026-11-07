"""The CIO truth payload reads its conflict section from the engine ledger (LQ-20261107-237).

Synthetic ledger in tmp_path; it never reads the live state.
"""
from datetime import timedelta

from scripts.lib import cio_truth
from tests.test_conflict_ledger import NOW, SUBJECT, conflict, ledger


def test_ledger_present_gives_findings_with_the_ledger_as_of(tmp_path):
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    section = cio_truth._ledger_conflicts(tmp_path, NOW + timedelta(hours=1))
    assert len(section["findings"]) == 1
    assert section["source"] == "conflict_events.jsonl"
    assert section["as_of"] and section["stale"] is False
    assert not section.get("gap")


def test_an_old_ledger_shows_its_age_as_stale(tmp_path):
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    section = cio_truth._ledger_conflicts(tmp_path, NOW + timedelta(days=5))
    assert section["stale"] is True
    assert len(section["findings"]) == 1


def test_missing_ledger_keeps_an_honest_gap_not_an_empty_all_clear(tmp_path):
    section = cio_truth._ledger_conflicts(tmp_path, NOW)
    assert section["findings"] == []
    assert section["gap"]["reason"] == "conflict ledger not yet produced"


def test_unreadable_ledger_degrades_to_a_named_gap(tmp_path, monkeypatch):
    import scripts.lib.conflicts.api as api
    monkeypatch.setattr(api, "records_section", lambda root=None, **k: (_ for _ in ()).throw(OSError("x")))
    section = cio_truth._ledger_conflicts(tmp_path, NOW)
    assert section["findings"] == []
    assert "OSError" in section["gap"]["reason"]
