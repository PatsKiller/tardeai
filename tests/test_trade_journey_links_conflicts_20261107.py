"""TradeJourney origin attribution + conflict detection — the two mapping defects of 2026-11-07.

ANCHOR: LQ-20261107-234. The /v3/journal page showed 46 journeys with an unknown origin and 100 conflicts.
Two separate mapping errors were behind the numbers:

1. **Origin.** ``db_adapter._execute`` catches every SQL error and returns ``None``; ``_q`` folded that to
   ``[]``, so the links read looked like a clean, empty answer. ``trade_recommendation_links`` and
   ``recommendation_registry`` do not exist on this host (the learning-loop PR1 migration is not applied),
   yet every row said "no recommendation … was recorded before this entry" and the freshness chip said
   ``links: linked``. A store that does not exist must say so.

2. **Conflicts.** ``conflicts_for`` compared a *closed round trip* (one lot) against the CIO book's
   ``position_status`` and the re-entry desk's ``CURRENTLY HELD``, both of which are per **symbol**. A
   partial stop leaves a fraction behind, so the symbol really is still owned; 91 of the 100 conflicts were
   that join artifact. The guard only ran when a holdings row was absent, and ``holding`` is set for open
   trades only — so it never ran for the closed trades it was written for.

Fakes only: no database, no network, no broker, no production state (AGENTS.md §24.6). Every symbol,
account and value here is synthetic.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.data_broker import trade_journey as tj  # noqa: E402


# ── fakes ───────────────────────────────────────────────────────────────────


def _db(*, links, links_probe, raise_links=False):
    """A stand-in for ``db_adapter._execute``: rows for reads we do not care about, a chosen answer for links."""
    def q(sql, params=None, fetch="all"):
        s = " ".join(str(sql).split())
        if "to_regclass" in s:
            return links_probe
        if "trade_recommendation_links" in s:
            if raise_links:
                raise RuntimeError("connection reset")
            return links
        return []
    return q


@pytest.fixture()
def hermetic(monkeypatch):
    """gather() reads the CIO store and the desk snapshot from disk; replace both, and nothing else."""
    class _Store:
        def read_projection(self):
            return {"as_of": None, "items": {}}

    monkeypatch.setattr("lib.cio_opportunity_store.CIOOpportunityStore", _Store)
    monkeypatch.setattr(tj, "load_opportunity_history", lambda syms, event_path=None: {})
    monkeypatch.setattr(tj, "load_desk_snapshot", lambda path=None: ({}, None))
    return monkeypatch


HOLDINGS = {"as_of": "2026-11-07T15:00:00-05:00", "holdings": []}


def _closed(symbol="AAAA", round_trip_key="rt-x1"):
    return {"trade_id": f"closed:acct_demo:{symbol}", "symbol": symbol, "account": "acct_demo",
            "round_trip_key": round_trip_key, "status": "closed", "fill_qty": 10.0,
            "entry_at": "2026-11-01T14:30:00+00:00", "exit_at": "2026-11-05T19:00:00+00:00",
            "entry_ref": 10.0, "exit_ref": 11.0, "pl_amount": 10.0, "pl_pct": 10.0,
            "entry_source": "fixture", "exit_source": "fixture", "entry_detail": "FIFO"}


def _gather(db, hermetic):
    return tj.gather(db, days=30, holdings_document=HOLDINGS)


# ── 1. a read that did not happen is a gap, never an empty result ───────────


def test_q_records_a_gap_when_the_driver_returns_no_result_set():
    gaps = []
    assert tj._q(lambda sql, params=None: None, "SELECT 1", gaps=gaps, what="some_store") == []
    assert [g["input"] for g in gaps] == ["some_store"]
    assert "no result set" in gaps[0]["why"]


def test_q_passes_rows_through_without_a_gap():
    gaps = []
    assert tj._q(lambda sql, params=None: [{"a": 1}], "SELECT 1", gaps=gaps, what="some_store") == [{"a": 1}]
    assert gaps == []


# ── 2. origin: a store that does not exist says so ──────────────────────────


def test_missing_link_table_is_unavailable_and_names_the_migration(hermetic):
    trades, inputs = _gather(_db(links=None, links_probe=[{"t": None}]), hermetic)
    assert trades == []
    assert inputs["link_status"] == "unavailable"
    gap = next(g for g in inputs["gaps"] if g["input"] == "trade_recommendation_links")
    assert "does not exist" in gap["why"] and "learning_loop_pr1" in gap["why"]
    assert "trade_recommendation_links" not in inputs["reads"]

    payload = tj.build_trade_journeys([_closed()], inputs=inputs)
    origin = payload["journeys"][0]["origin"]
    assert origin["kind"] == "unknown"
    assert origin["link_status"] == "unavailable"
    assert "tables are not available" in origin["label"]


def test_a_failed_link_read_is_named_as_a_failure_not_as_a_migration(hermetic):
    _, inputs = _gather(_db(links=None, links_probe=[{"t": "trade_recommendation_links"}], raise_links=True),
                        hermetic)
    assert inputs["link_status"] == "unavailable"
    gap = next(g for g in inputs["gaps"] if g["input"] == "trade_recommendation_links")
    assert gap["why"].startswith("read failed:") and "RuntimeError" in gap["why"]


def test_an_existing_empty_link_table_still_reads_ok(hermetic):
    _, inputs = _gather(_db(links=[], links_probe=[{"t": "trade_recommendation_links"}]), hermetic)
    assert inputs["link_status"] == "ok"
    assert not [g for g in inputs["gaps"] if g["input"] == "trade_recommendation_links"]
    assert "trade_recommendation_links" in inputs["reads"]


# ── 3. conflicts: a closed lot is not the symbol ────────────────────────────

OWNED = {"stance": "HOLD", "position_status": "owned", "as_of": "2026-11-06T21:30:18+00:00"}
DESK = {"symbol": "AAAA", "intel": {"state": "CURRENTLY HELD", "action": "hold"}}
HOLDING = {"fill_qty": 10.0, "as_of": "2026-11-07T15:00:00-05:00", "mark_at": "2026-11-07T20:00:02+00:00"}


def _conflicts(*, closed=True, exit_cause=None, holding=None, held_symbols, symbol="AAAA"):
    return tj.conflicts_for(closed=closed, exit_cause=exit_cause or {"kind": "manual", "label": "closed manually"},
                            holding=holding, opp_now=OWNED, desk_row=DESK, desk_at="2026-11-07T20:08:05+00:00",
                            exit_at="2026-11-05T19:00:00+00:00", symbol=symbol, held_symbols=held_symbols)


def test_a_closed_lot_in_a_symbol_still_held_is_not_a_conflict():
    assert _conflicts(held_symbols={"AAAA"}) == []


def test_a_closed_lot_flat_everywhere_is_a_real_conflict_with_both_stores():
    fields = [c["field"] for c in _conflicts(held_symbols=set())]
    assert fields == ["position_status", "reentry_state"]


def test_an_unread_holdings_snapshot_hides_nothing():
    fields = [c["field"] for c in _conflicts(held_symbols=None)]
    assert fields == ["position_status", "reentry_state"]


def test_an_unconfirmed_stop_fill_is_a_conflict_even_while_the_symbol_is_held():
    cause = {"kind": "stop_likely_filled", "label": "stop likely filled (unconfirmed)", "level_ref": 9.5}
    fields = [c["field"] for c in _conflicts(closed=False, exit_cause=cause, holding=HOLDING, held_symbols={"AAAA"})]
    assert fields == ["position", "reentry_state"]


def test_build_trade_journeys_wires_the_held_symbol_set_through():
    base = {"link_status": "unavailable", "opp_now": {"AAAA": OWNED}, "desk_rows": {"AAAA": DESK},
            "desk_at": "2026-11-07T20:08:05+00:00"}
    held = tj.build_trade_journeys([_closed()], inputs={**base, "held_symbols": ["AAAA"]})
    assert held["counts"]["conflicts"] == 0
    flat = tj.build_trade_journeys([_closed()], inputs={**base, "held_symbols": []})
    assert flat["counts"]["conflicts"] == 2
    unknown = tj.build_trade_journeys([_closed()], inputs=base)
    assert unknown["counts"]["conflicts"] == 2
