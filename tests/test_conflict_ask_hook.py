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
