"""Market risk reads the position store and writes memory only through the sanctioned doors (review of #2412).

* ``book_precision.current_book`` and ``market_risk_rotation`` read holdings through ``lib/portfolio_positions``
  (``load_store`` / ``store_path``), never a hand-built holdings path (tests/test_portfolio_price_truth_20261005.py
  ratchet), and the book stays fail-closed: a missing store raises instead of reporting an empty book.
* ``cio_memory_fanout`` admits episodic memory through ``intelligence_client.admit_memory`` (Ring 1,
  scripts/check_memory_chokepoint.py), and the façade refuses a record that names a behaviour field
  (MBI_BEHAVIOR = 0) before admission runs. Hermetic: tmp_path roots only.
"""
from __future__ import annotations

import json

import pytest

from scripts.lib import intelligence_client as ic
from scripts.lib import portfolio_positions as pp
from scripts.lib.market_risk import book_precision as bp

POLICY = {"positions": {"materiality": {"min_shares": 1, "min_market_value": 1, "min_book_weight": 0}}}


def _doc() -> dict:
    return {
        "data_as_of": "2026-10-30T20:00:00Z",
        "holdings": [{"symbol": "ZZTECH", "account": "a1", "shares": 10, "market_value": 1000.0, "price": 100.0,
                      "current_price": 500.0}],
    }


def test_current_book_reads_through_portfolio_positions(tmp_path, monkeypatch):
    store = pp.store_path(tmp_path)
    store.parent.mkdir(parents=True)
    store.write_text(json.dumps(_doc()))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    seen = []
    real = pp.load_store
    monkeypatch.setattr(pp, "load_store", lambda path=None: seen.append(path) or real(path))
    book = bp.current_book(POLICY)
    assert seen and str(seen[0]) == str(store)
    assert book["source"] == str(store)
    assert [m["symbol"] for m in book["material"]] == ["ZZTECH"]
    assert book["material"][0]["mark"] == 100.0  # reconciled price, never current_price


def test_current_book_fails_closed_on_missing_store(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        bp.current_book(POLICY)


def test_rotation_reads_holdings_and_exits_through_portfolio_positions(tmp_path, monkeypatch):
    import scripts.market_risk_rotation as rot

    store = pp.store_path(tmp_path)
    store.parent.mkdir(parents=True)
    doc = _doc()
    doc["closed_today"] = {"a1": [{"symbol": "ZZEX", "shares": 0}]}
    store.write_text(json.dumps(doc))
    seen = []
    real = pp.load_store
    monkeypatch.setattr(pp, "load_store", lambda path=None: seen.append(str(path)) or real(path))
    assert rot._store_path(tmp_path) == store  # noqa: SLF001
    rows = rot.load_holdings(rot._store_path(tmp_path))  # noqa: SLF001
    assert rows == [{"symbol": "ZZTECH", "sector": None, "market_value": 1000.0}]
    exits = rot._exits(tmp_path, {})  # noqa: SLF001
    assert [e["symbol"] for e in exits] == ["ZZEX"]
    assert seen == [str(store), str(store)]
    assert rot._exits(tmp_path / "empty", {}) == []  # noqa: SLF001 — a missing store is no exits, not a crash


def test_admit_memory_refuses_behaviour_fields_before_admission(tmp_path, monkeypatch):
    calls = []
    real = ic._lib  # noqa: SLF001
    monkeypatch.setattr(ic, "_lib", lambda name: calls.append(name) or real(name))
    with pytest.raises(ic.BehaviorWriteRefused):
        ic.admit_memory({"content": "x", "shares": 10}, root=tmp_path, admitted_by="test")
    assert not {"agent_durable_memory", "agent_memory_admission"} & set(calls)  # refused before admission ran
    assert not (tmp_path / "data").exists()


def test_fanout_admits_aif_memory_through_the_facade(tmp_path, monkeypatch):
    from scripts.lib.market_risk import cio_memory_fanout as F

    got = []
    monkeypatch.setattr(ic, "admit_memory", lambda record, **kw: got.append((record, kw)) or {"accepted": True})
    plan = {"target": "aif_memory", "trigger_id": "t1",
            "record": {"memory_type": "EPISODIC", "subject": "market regime episode",
                       "content": "Market risk tier changed from GREEN to YELLOW as of 2026-10-30.",
                       "source_refs": ["snap.json#2026-10-30"]}}
    receipts = F.apply_memory([plan], root=tmp_path)
    assert receipts == [{"trigger_id": "t1", "target": "aif_memory", "accepted": True, "reason": None,
                         "memory_id": None}]
    assert got and got[0][1] == {"root": tmp_path, "admitted_by": F.PRODUCER}
