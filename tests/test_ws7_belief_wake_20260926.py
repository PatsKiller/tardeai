"""WS-7 (C-13, 2026-09-26): hourly wakes consume the record they selected.

A due record is not eligible again until its own cadence elapses. Two due
records rotate by last wake, not by sort order. An unconsumed-research
selection loads a subject only from a CONFIRMED registry guid, and stays
NO_SUBJECT otherwise. A missing cadence does not invent an interval.

MBI_BEHAVIOR stays 0. Nothing here changes an order, a size, a stop, or a
gate threshold. agent_gate_measurements.json is not wired.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.cio_instrument_record import (  # noqa: E402
    BEHAVIOR_FIELDS,
    DEFAULT_PATH,
    MBI_BEHAVIOR,
    InstrumentRecordStore,
    new_record,
)
from scripts.lib.identity_registry import (  # noqa: E402
    empty_registry,
    lookup_symbol,
    register,
    save,
)
from scripts.lib.persistent_agent_wake import (  # noqa: E402
    FEATURE_FLAG,
    advance_instrument_record_after_due_wake,
    _load_instrument_record_for_selection,
    run_scheduled_wake,
)
from scripts.lib.wake_subject_selector import (  # noqa: E402
    SubjectCandidate,
    instrument_record_candidates,
    select_subjects,
)
import scripts.run_persistent_wake as wake_runner  # noqa: E402

NOW = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)
PAST = "2026-09-01T00:00:00Z"


def _walk(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            _walk(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, out)
    return out


def _guid_for(sym: str) -> str | None:
    return {"BJDX": "g-bjdx", "NOC": "g-noc", "MCD": "g-mcd"}.get(sym)


def _research(n: int = 4) -> list[dict]:
    return [
        {"subject_guid": f"rg-{i}", "research_object_id": f"ro-{i}",
         "published_at": "2026-09-26T12:00:00Z"}
        for i in range(n)
    ]


def _due(key: str, woken: str | None) -> dict:
    row = {"subject_key": key, "next_eligible_at": PAST}
    if woken is not None:
        row["last_woken_at"] = woken
    return row


def _reserved(records: list[dict]) -> str:
    cands = select_subjects(
        "cio", limit=3, now=NOW,
        research_objects=_research(),
        instrument_records=records,
        guid_for_symbol=_guid_for,
    )
    assert [c.source for c in cands].count("instrument_record_due") == 1
    return cands[2].source_id


def test_memory_behavior_influence_stays_zero_and_gate_file_is_not_wired():
    assert MBI_BEHAVIOR == 0
    for rel in (
        "scripts/lib/persistent_agent_wake.py",
        "scripts/lib/wake_subject_selector.py",
        "scripts/run_persistent_wake.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "agent_gate_measurements" not in text


def test_a_due_record_is_not_eligible_again_until_next_eligible_at(tmp_path: Path):
    root = tmp_path / "book"
    store = InstrumentRecordStore(root / DEFAULT_PATH)
    belief = {"belief_key": "EXIT:BJDX|TRIM|30d", "revision": 1}
    rec = new_record(
        "EXIT", "BJDX", symbols=["BJDX"], next_eligible_at=PAST, cadence="PT2H",
        beliefs=[belief],
    )
    store.upsert(rec)
    out = advance_instrument_record_after_due_wake(
        {"source": "instrument_record_due", "source_id": "EXIT:BJDX"},
        now=NOW, root=root,
    )
    assert out["advanced"] is True
    assert out["reason"] == "cadence_applied"
    assert out["memory_behavior_influence"] == 0
    tip = InstrumentRecordStore(root / DEFAULT_PATH).load("EXIT:BJDX")
    assert tip["next_eligible_at"] == "2026-09-26T20:00:00Z"
    assert tip["memory_behavior_influence"] == 0
    assert tip["beliefs"] == [belief]
    assert not (_walk(tip) & set(BEHAVIOR_FIELDS))
    assert instrument_record_candidates(
        [tip], now=NOW + timedelta(hours=1), guid_for_symbol=_guid_for,
    ) == []
    again = instrument_record_candidates(
        [tip], now=NOW + timedelta(hours=2), guid_for_symbol=_guid_for,
    )
    assert [c.source_id for c in again] == ["EXIT:BJDX"]


def test_two_due_records_rotate_to_the_least_recently_woken():
    """g-bjdx sorts before g-noc. The reserved slot must not follow that."""
    older_noc = _reserved([
        _due("EXIT:BJDX", "2026-09-26T18:00:00Z"),
        _due("HELD:NOC", "2026-09-20T00:00:00Z"),
    ])
    assert older_noc == "HELD:NOC"
    older_bjdx = _reserved([
        _due("EXIT:BJDX", "2026-09-20T00:00:00Z"),
        _due("HELD:NOC", "2026-09-26T18:00:00Z"),
    ])
    assert older_bjdx == "EXIT:BJDX"
    never_woken = _reserved([
        _due("EXIT:BJDX", "2026-09-26T18:00:00Z"),
        _due("HELD:NOC", None),
    ])
    assert never_woken == "HELD:NOC"


def _save_registry(tmp_path: Path, row: dict, name: str) -> str:
    path = tmp_path / name
    doc = register(empty_registry(), row)
    # save() reads TRADEAI_IDENTITY_REGISTRY. The caller sets it.
    save(doc)
    ent = lookup_symbol(doc, row["symbol"])
    assert ent and ent.get("subject_guid")
    assert path.is_file()
    return str(ent["subject_guid"])


def test_confirmed_research_guid_loads_that_subject_and_unconfirmed_stays_no_subject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    book = tmp_path / "book"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(book))
    store = InstrumentRecordStore(book / DEFAULT_PATH)
    belief = {"belief_key": "HELD:NOC|HOLD|30d", "revision": 4}
    store.upsert(new_record("HELD", "NOC", symbols=["NOC"], beliefs=[belief]))

    reg = tmp_path / "confirmed.json"
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(reg))
    confirmed = _save_registry(tmp_path, {
        "symbol": "NOC", "company": "Northrop Grumman",
        "identifiers": {"cusip": "666807102"},
    }, "confirmed.json")
    assert lookup_symbol(
        json.loads(reg.read_text(encoding="utf-8")), "NOC",
    )["identity_status"] == "CONFIRMED"

    def _boom(*_a, **_k):
        raise AssertionError("registry mint is not allowed on the wake path")

    monkeypatch.setattr("scripts.lib.identity_registry.register", _boom)
    monkeypatch.setattr("scripts.lib.identity_registry.ticker_alias_guid", _boom)

    loaded = _load_instrument_record_for_selection(
        {"source": "unconsumed_research", "source_id": "ro-noc",
         "subject_guid": confirmed, "symbol": "ZZZZ"},
        confirmed,
    )
    assert loaded["status"] == "LOADED"
    assert loaded["subject_key"] == "HELD:NOC"
    assert loaded["record"]["beliefs"] == [belief]
    assert loaded["reason"] == "confirmed"

    cand_reg = tmp_path / "candidate.json"
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(cand_reg))
    monkeypatch.setattr("scripts.lib.identity_registry.register", register)
    monkeypatch.setattr(
        "scripts.lib.identity_registry.ticker_alias_guid",
        __import__("scripts.lib.identity_registry", fromlist=["ticker_alias_guid"]).ticker_alias_guid,
    )
    candidate = _save_registry(tmp_path, {
        "symbol": "NOC", "company": "Northrop Grumman",
    }, "candidate.json")
    ent = lookup_symbol(json.loads(cand_reg.read_text(encoding="utf-8")), "NOC")
    assert ent["identity_status"] != "CONFIRMED"
    monkeypatch.setattr("scripts.lib.identity_registry.register", _boom)

    refused = _load_instrument_record_for_selection(
        {"source": "unconsumed_research", "source_id": "ro-noc",
         "subject_guid": candidate, "symbol": "NOC"},
        candidate,
    )
    assert refused["status"] == "NO_SUBJECT"
    assert refused["record"] is None
    assert refused["reason"] == "subject_guid_not_confirmed"
    assert "not CONFIRMED" in refused["detail"]

    missing = _load_instrument_record_for_selection(
        {"source": "unconsumed_research", "source_id": "ro-noc"}, None,
    )
    assert missing["status"] == "NO_SUBJECT"
    assert missing["record"] is None
    assert missing["reason"] == "subject_guid_missing"
    assert "missing" in missing["detail"]


def test_a_wake_with_no_confirmed_guid_says_no_subject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "empty.json"))
    (tmp_path / "empty.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "book"))
    mem = tmp_path / "mem.jsonl"
    mem.write_text("")
    result = run_scheduled_wake(
        agent_id="cio",
        subject_guid="ws7-not-a-registry-guid",
        state_root=tmp_path / "wake",
        memory_backend=str(mem),
        when=NOW,
        env={FEATURE_FLAG: "1", "PROVENANCE_PRODUCER": "test"},
        selection={"source": "unconsumed_research", "source_id": "ro-1"},
    )
    ir = result["wake"]["provenance"]["instrument_record"]
    assert ir["status"] == "NO_SUBJECT"
    assert ir["reason"] == "subject_guid_not_confirmed"
    assert "not CONFIRMED" in ir["detail"]
    assert ir["subject_key"] is None


def test_a_missing_cadence_does_not_invent_an_interval(tmp_path: Path):
    root = tmp_path / "book"
    store = InstrumentRecordStore(root / DEFAULT_PATH)
    store.upsert(new_record("HELD", "NOC", symbols=["NOC"], next_eligible_at=PAST))
    store.upsert(new_record(
        "EXIT", "BJDX", symbols=["BJDX"], next_eligible_at=PAST, cadence="7",
    ))
    missing = advance_instrument_record_after_due_wake(
        {"source": "instrument_record_due", "source_id": "HELD:NOC"},
        now=NOW, root=root,
    )
    bare = advance_instrument_record_after_due_wake(
        {"source": "instrument_record_due", "source_id": "EXIT:BJDX"},
        now=NOW, root=root,
    )
    fresh = InstrumentRecordStore(root / DEFAULT_PATH)
    noc = fresh.load("HELD:NOC")
    bjdx = fresh.load("EXIT:BJDX")
    assert missing["advanced"] is False and missing["reason"] == "cadence_missing"
    assert noc["next_eligible_at"] == PAST
    assert noc["cadence_advance"]["reason"] == "cadence_missing"
    assert noc["last_woken_at"]
    assert bare["advanced"] is False and bare["reason"] == "cadence_unparseable"
    assert bjdx["next_eligible_at"] == PAST
    invented = (NOW + timedelta(days=7)).isoformat()
    assert noc["next_eligible_at"] != invented
    assert bjdx["next_eligible_at"] != invented
    assert noc["memory_behavior_influence"] == 0
    assert not (_walk(noc) & set(BEHAVIOR_FIELDS))
    assert not (_walk(bjdx) & set(BEHAVIOR_FIELDS))


def test_runner_advances_a_handled_due_wake_and_not_a_replay(tmp_path: Path, monkeypatch, capsys):
    calls: list[dict] = []

    def _fake_advance(selection, *, now=None, root=None):
        calls.append({"source_id": selection.source_id, "now": now, "root": root})
        return {"advanced": True, "reason": "cadence_applied", "memory_behavior_influence": 0}

    def _fake_run(**_kwargs):
        return {
            "ok": True, "inserted": True,
            "wake": {"wake_id": "w-1", "lifecycle_state": "SETTLED", "provenance": {}},
        }

    monkeypatch.setattr(wake_runner, "advance_instrument_record_after_due_wake", _fake_advance)
    monkeypatch.setattr(wake_runner, "run_scheduled_wake", _fake_run)
    monkeypatch.setattr(wake_runner, "comms_history", lambda: None)
    sel = SubjectCandidate("g-bjdx", "instrument_record_due", "EXIT:BJDX")
    rc = wake_runner._process_one_subject(
        agent_id="cio", subject_guid="g-bjdx", dry_run=False,
        env={FEATURE_FLAG: "1"}, when=NOW, state_root=tmp_path / "wake",
        memory_backend=None, selection=sel,
    )
    assert rc == 0 and len(calls) == 1 and calls[0]["source_id"] == "EXIT:BJDX"
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["cadence_advance"]["reason"] == "cadence_applied"

    def _replay(**_kwargs):
        return {
            "ok": True, "replay_suppressed": True, "inserted": False,
            "wake": {"wake_id": "w-1", "lifecycle_state": "SETTLED", "provenance": {}},
        }

    monkeypatch.setattr(wake_runner, "run_scheduled_wake", _replay)
    rc = wake_runner._process_one_subject(
        agent_id="cio", subject_guid="g-bjdx", dry_run=False,
        env={FEATURE_FLAG: "1"}, when=NOW, state_root=tmp_path / "wake2",
        memory_backend=None, selection=sel,
    )
    assert rc == 0 and len(calls) == 1
