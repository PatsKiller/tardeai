"""LQ-20261107-2129 — a request path reads the memoised InstrumentRecord store, not a fresh one.

Live finding 2026-11-11: portfolio-server was killed by its watchdog at memory.high (12:14 and 22:10 ET).
``cio_command_center.resolve_record_store()`` returned a new ``InstrumentRecordStore()`` on every call, so each
/api/v3/cio/home build (about every 2 min on the stale-serve refresh) re-parsed the whole append-only store
(2.26 GB, 256k lines) and added 300-400 MB of RSS. ``_store_for_root()`` (LQ-1634) already holds one object
per path that catches up from the append tail; the request paths did not use it.

Fail-before: two home builds give two stores and ``_full_parses`` 2; two ask turns re-parse likewise.
Pass-after: one store, one full parse; an append is absorbed from the tail; a replaced, truncated or
rewritten file is still re-read (freshness is not traded away). Synthetic rows in tmp dirs only; no DB, no
network, the real store is never opened.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import canonical_store_registry as registry  # noqa: E402
from scripts.lib import cio_command_center as c  # noqa: E402
from scripts.lib import cio_instrument_record as ir  # noqa: E402
from scripts.lib.cio_ask_contract import EntityRef  # noqa: E402
from scripts.lib.cio_ask_tracking import CioRecordBackend  # noqa: E402
from tests.test_cio_cc_record_narrative_slice_c import _plan, _queue, _sectors  # noqa: E402

FIXED = datetime(2026, 8, 28, 20, 0, 0, tzinfo=timezone.utc)


def _row(key: str, **extra) -> dict:
    return {"subject_key": key, "schema": ir.SCHEMA, "authority": ir.AUTHORITY, **extra}


def _write(path: Path, rows: list[dict], mode: str = "w") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode, encoding="utf-8") as fh:
        fh.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


@pytest.fixture()
def store_file(tmp_path, monkeypatch):
    """A synthetic canonical store that the registry resolves to; a clean per-test memo."""
    path = tmp_path / "data" / "cio" / "cio_instrument_records.jsonl"
    _write(path, [_row("HELD:AAA"), _row("WATCH:BBB"), _row("SECTOR:Technology")])
    monkeypatch.setattr(ir, "_STORES", {})
    monkeypatch.setattr(registry, "resolve_store", lambda store_id, *a, **k: {"ok": True, "path": str(path)})
    return path


def _home():
    return c.build_office_home(
        capital_plan=_plan(), sector_opportunities=_sectors(), opportunity_queue=_queue(),
        operator_product={}, now=FIXED,
    )


def _keys(store) -> set:
    return {r["subject_key"] for r in store.all()}


def _stores() -> list:
    return list(ir._STORES.values())


def test_two_home_builds_parse_the_store_once(store_file):
    _home()
    _home()
    stores = _stores()
    assert len(stores) == 1, "one memoised store for the one canonical file"
    assert stores[0]._full_parses == 1, f"re-parsed the whole store: {stores[0]._full_parses} full parses"


def test_resolve_record_store_returns_the_same_object(store_file):
    assert c.resolve_record_store() is c.resolve_record_store()


def test_an_explicit_store_is_still_honoured(store_file, tmp_path):
    mine = ir.InstrumentRecordStore(tmp_path / "other.jsonl")
    assert c.resolve_record_store(mine) is mine


def test_an_append_between_home_builds_is_seen_without_a_full_reparse(store_file):
    store = c.resolve_record_store()
    assert "WATCH:NEW" not in _keys(store)
    _write(store_file, [_row("WATCH:NEW")], mode="a")
    again = c.resolve_record_store()
    assert again is store and "WATCH:NEW" in _keys(again)
    assert store._full_parses == 1 and store._tail_lines_parsed == 1


def test_a_truncated_or_replaced_file_is_re_read(store_file):
    store = c.resolve_record_store()
    assert "HELD:AAA" in _keys(store)
    _write(store_file, [_row("HELD:ZZZ")])  # shorter and rewritten
    fresh = _keys(c.resolve_record_store())
    assert "HELD:ZZZ" in fresh and "HELD:AAA" not in fresh
    swap = store_file.with_name("swap.jsonl")
    _write(swap, [_row("HELD:REPLACED"), _row("HELD:AAA"), _row("WATCH:BBB"), _row("X:1")])
    os.replace(swap, store_file)  # a new inode at the same path
    assert "HELD:REPLACED" in _keys(c.resolve_record_store())


def test_an_ask_turn_shares_the_store_with_the_home_page(store_file, monkeypatch):
    backend = CioRecordBackend()  # no explicit path: the canonical file under TRADEAI_ROOT
    monkeypatch.setenv("TRADEAI_ROOT", str(store_file.parents[2]))
    home_store = c.resolve_record_store()
    home_store.all()
    entity = EntityRef(name="AAA Corp", symbol="AAA")
    for n in range(2):
        backend.note_question(entity, question=f"question {n}", ask_id=f"a{n}", thread_id="t", channel="web")
    assert _stores() == [home_store], "the ask turn used a different object for the same file"
    assert home_store._full_parses == 1, f"{home_store._full_parses} full parses for two ask turns plus a home read"
    assert home_store.load("SECURITY:AAA")["next_research_question"].startswith("Operator asked: question 1")


def test_an_explicit_ask_path_keeps_its_own_store(tmp_path, store_file):
    other = tmp_path / "ask_only.jsonl"
    _write(other, [])
    backend = CioRecordBackend(path=other)
    backend.note_question(EntityRef(name="CCC", symbol="CCC"), question="q", ask_id="a", thread_id="t", channel="web")
    assert "SECURITY:CCC" in _keys(ir.InstrumentRecordStore(other))
    assert "SECURITY:CCC" not in _keys(ir.InstrumentRecordStore(store_file))


# ---- LQ-20261107-2154: the shared store must not defeat the ask turn's compare-and-swap ----------------

def test_a_concurrent_refresh_between_read_and_write_cannot_hide_an_external_append(store_file, monkeypatch):
    """Between the turn's read and its upsert an external lane appends a newer tip and another request in this
    process refreshes the shared store (the home build). On the shared store that refresh advanced
    ``_observed_hashes`` to the new tip, so the check passed and the lane's record was overwritten silently.
    The turn must instead be told the tip changed (StaleInstrumentRecordWrite), as it was with a store per turn."""
    import threading

    _write(store_file, [_row("SECURITY:AAA", next_research_question="old")], mode="a")
    monkeypatch.setenv("TRADEAI_ROOT", str(store_file.parents[2]))
    home_store = c.resolve_record_store()
    home_store.all()
    real_apply = ir.apply_cognition
    refresher = {}

    def apply_with_race(rec, **kw):
        _write(store_file, [_row("SECURITY:AAA", next_research_question="external lane wrote this")], mode="a")
        t = threading.Thread(target=home_store.all, daemon=True)  # the concurrent home refresh
        t.start()
        t.join(timeout=0.5)  # blocks while the turn holds the store; completes at once if it does not
        refresher["t"] = t
        return real_apply(rec, **kw)

    monkeypatch.setattr(ir, "apply_cognition", apply_with_race)
    backend = CioRecordBackend()
    with pytest.raises(ir.StaleInstrumentRecordWrite):
        backend.note_question(EntityRef(name="AAA Corp", symbol="AAA"), question="q", ask_id="a1", thread_id="t", channel="web")
    refresher["t"].join(timeout=5)
    assert not refresher["t"].is_alive()
    tip = [json.loads(l) for l in store_file.read_text().splitlines() if '"SECURITY:AAA"' in l][-1]
    assert tip["next_research_question"] == "external lane wrote this", "the external record was overwritten"


def test_a_serial_ask_turn_still_writes(store_file, monkeypatch):
    """The lock must not turn a normal turn into a failure."""
    monkeypatch.setenv("TRADEAI_ROOT", str(store_file.parents[2]))
    out = CioRecordBackend().note_question(EntityRef(name="AAA Corp", symbol="AAA"), question="q1", ask_id="a1", thread_id="t", channel="web")
    assert out["action"] == "created"
    out = CioRecordBackend().note_question(EntityRef(name="AAA Corp", symbol="AAA"), question="q2", ask_id="a2", thread_id="t", channel="web")
    assert out["action"] == "updated"
