"""Validate the proposed Ask owner hook in memory; never edit the held files."""
from pathlib import Path
import types

from scripts.lib.cio_ask_contract import EntityRef
from scripts.lib.cio_conflicts import ask_context_rows
from tests.test_conflict_ledger import NOW, SUBJECT, KEY, conflict, ledger


def proposed_memory():
    path = Path(__file__).parents[1] / "config/proposals/conflict_ledger/ask_memory_owner_proposal.py.txt"
    module = types.ModuleType("_proposed_ask_memory_fixture")
    exec(compile(path.read_text(), "<proposed-Ask-owner-hook>", "exec"), module.__dict__)
    return module


def entity():
    return EntityRef(kind="security", name="Fixture security", symbol="SYM", security_guid="guid", resolution="CONFIRMED")


def test_proposed_owner_hook_reads_current_guid_conflicts_without_writes(tmp_path, monkeypatch):
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    before = st.path.read_bytes()
    from scripts.lib.cross_asset import security_research_spine as spine
    monkeypatch.setattr(spine, "load_latest", lambda *a, **k: {})
    memory = proposed_memory().SpineAskMemory(spine_path=tmp_path / "spine.jsonl",
                                            conflict_reader=lambda guid: ask_context_rows(tmp_path, guid))
    rows = memory.recall(entity=entity(), limit=4)
    assert len(rows) == 1 and rows[0]["kind"] == "conflict.current"
    assert rows[0]["current_conflicts"][0]["key"] == KEY
    assert "CIO WATCH vs desk ADD" in rows[0]["summary"]
    assert st.path.read_bytes() == before and not (tmp_path / "spine.jsonl").exists()


def test_missing_ledger_surfaces_named_gap_and_reader_failure_is_not_clear(tmp_path, monkeypatch):
    from scripts.lib.cross_asset import security_research_spine as spine
    monkeypatch.setattr(spine, "load_latest", lambda *a, **k: {})
    module = proposed_memory()
    memory = module.SpineAskMemory(spine_path=tmp_path / "spine.jsonl",
                                  conflict_reader=lambda guid: ask_context_rows(tmp_path, guid))
    assert memory.recall(entity=entity())[0]["gap"]
    memory.conflict_reader = lambda guid: (_ for _ in ()).throw(RuntimeError("fixture unavailable"))
    assert "unavailable" in memory.recall(entity=entity())[0]["summary"]


def test_unconfigured_legacy_memory_and_private_entities_do_not_call_conflict_reader(tmp_path, monkeypatch):
    from scripts.lib.cross_asset import security_research_spine as spine
    monkeypatch.setattr(spine, "load_latest", lambda *a, **k: {})
    module = proposed_memory()
    assert module.SpineAskMemory(spine_path=tmp_path / "spine.jsonl").recall(entity=entity()) == []
    memory = module.SpineAskMemory(conflict_reader=lambda _: (_ for _ in ()).throw(AssertionError("private entity")))
    private = EntityRef(kind="private", name="Private fixture", entity_guid="private-fixture")
    assert memory.recall(entity=private) == []


def test_ask_rows_carry_the_conflict_age_without_inventing_one(tmp_path):
    """Ask memory is where an answer would cite "waiting since"; the rows had no clock before."""
    from datetime import timedelta

    from scripts.lib.cio_conflicts import ask_context_rows

    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict(kind="NEEDS_OPERATOR", never_auto=True)], at=NOW - timedelta(hours=30),
                 apply=True)
    row = ask_context_rows(tmp_path, SUBJECT.id, now=NOW)[0]["current_conflicts"][0]
    assert row["age_hours"] == 30.0
    assert row["opened_at"].endswith("Z")
    # A subject with no open conflict yields no rows at all — "nothing waiting", not "unknown age".
    assert ask_context_rows(tmp_path, "guid-with-no-conflicts", now=NOW) == []


def test_ask_rows_tolerate_an_unreadable_updated_at(monkeypatch, tmp_path):
    """An unreadable clock is absent, never a TypeError and never a fabricated value."""
    from scripts.lib import cio_conflicts

    def record(**over):
        base = {"key": "k", "state": "OPEN", "kind": "CONFLICT", "summary": "s", "sides": [],
                "clears_when": "the delta clears", "owner": "cio", "next_run": None, "decision": None,
                "updated_at": "2026-11-02T00:00:00Z", "revision": 1, "opened_at": "2026-11-01T00:00:00Z"}
        base.update(over)
        return base

    records = [record(updated_at=None, revision=None),
               record(key="b", updated_at="2026-11-02T00:00:00Z", revision=4)]
    monkeypatch.setattr(cio_conflicts, "context_for",
                        lambda root, guid: {"gap": None, "open_conflicts": records})
    row = cio_conflicts.ask_context_rows(tmp_path, "guid")[0]
    assert row["at"] == "2026-11-02T00:00:00Z"
    assert row["ref"] == "conflicts:guid:4"

    records = [record(updated_at=None, revision=None)]
    row = cio_conflicts.ask_context_rows(tmp_path, "guid")[0]
    assert row["at"] is None
    assert row["ref"] == "conflicts:guid:unknown"
