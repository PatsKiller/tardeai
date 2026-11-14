"""S2 broker — the stop read receipt and the planned facet (PR-003 / PR-017, cc-deepseek-2).

A NO STOP row is a negative observation; these tests pin that it can only be read as one when the
receipt says a broker read happened, and that a planned level never borrows an observed clock.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.broker_stop_read import planned_facet, stops_read  # noqa: E402


def _section(**over):
    s = {
        "last_broker_read_at": "2026-11-14T14:58:10Z",
        "last_broker_read_label": "14:58 ET",
        "as_of": "2026-11-14T14:58:10Z",
        "age_hours": 0.4,
        "stale": False,
        "stale_after_hours": 0.5,
        "partial_observation_as_of": None,
        "gap": None,
        "active_count": 2,
        "pending_count": 0,
        "unprotected_count": 1,
        "awaiting_fill_count": 0,
    }
    s.update(over)
    return s


def test_a_fresh_broker_read_is_a_receipt_a_page_can_cite():
    """READ + the label: a NO STOP row beside this block is a successful negative read."""
    block = stops_read(_section())
    assert block["status"] == "READ"
    assert block["last_broker_read_at"] == "2026-11-14T14:58:10Z"
    assert block["last_broker_read_label"] == "14:58 ET"
    assert block["counts"] == {"active_count": 2, "pending_count": 0, "unprotected_count": 1,
                               "awaiting_fill_count": 0}


def test_a_stale_read_keeps_its_age_and_its_reason():
    """STALE carries the clock that produced it and the section's own gap, unrewritten."""
    gap = {"reason": "Stop data is 30 h old — counts from the last broker stop read on 13 Nov 09:00 ET."}
    block = stops_read(_section(stale=True, age_hours=30.0, gap=gap))
    assert block["status"] == "STALE"
    assert block["age_hours"] == 30.0
    assert block["gap"] == gap  # the producer's words, not a re-worded copy


def test_a_partial_refresh_is_named_and_never_dated_as_complete():
    """PARTIAL: as_of stays None; the last complete observation is published under its own key."""
    block = stops_read(_section(last_broker_read_at=None, as_of=None, age_hours=None, stale=True,
                                partial_observation_as_of="2026-11-13T20:00:00Z"))
    assert block["status"] == "PARTIAL"
    assert block["as_of"] is None
    assert block["last_broker_read_at"] is None
    assert block["partial_observation_as_of"] == "2026-11-13T20:00:00Z"
    assert block["gap"]["reason"]


def test_no_read_is_unknown_and_a_no_stop_row_proves_nothing():
    """An empty/absent section is UNKNOWN with a named reason — never READ, never zero counts."""
    for section in ({}, None, "not a mapping"):
        block = stops_read(section)
        assert block["status"] == "UNKNOWN", section
        assert block["last_broker_read_at"] is None
        assert block["gap"]["reason"].startswith("no complete broker stop read"), section
        assert block["counts"]["active_count"] is None  # None is kept: an unreadable store is not zero


def test_an_unreadable_stop_store_keeps_none_counts():
    """The section's None counts survive the lift; the block never invents 0 stops."""
    block = stops_read(_section(active_count=None, unprotected_count=None))
    assert block["counts"]["active_count"] is None
    assert block["counts"]["unprotected_count"] is None


def test_the_block_is_a_copy_and_the_section_is_untouched():
    """The receipt is deep-copied: a page editing the block cannot rewrite the CIO document's section."""
    gap = {"reason": "Stop data is 30 h old."}
    section = _section(stale=True, gap=gap)
    block = stops_read(section)
    block["gap"]["reason"] = "rewritten"     # nested: only a deep copy protects the source
    block["counts"]["active_count"] = 99     # a fresh dict: the section's count is not aliased
    assert section["gap"] == {"reason": "Stop data is 30 h old."}
    assert section["active_count"] == 2


def test_a_missing_window_is_not_invented():
    """No declared window in the section ⇒ None here; the block does not assume 0.5 h."""
    section = _section()
    section.pop("stale_after_hours")
    assert stops_read(section)["stale_after_hours"] is None


def test_a_planned_level_is_its_own_fact_never_an_observed_one():
    """PR-017: {level, source, as_of} beside the evidence state, dated when it was SET."""
    facet = planned_facet(180.0, as_of="2026-11-12")
    assert facet == {"level": 180.0, "source": "stops.json", "as_of": "2026-11-12"}
    assert planned_facet(12.5, source="operator_note", as_of="2026-11-14T09:00:00Z")["source"] == "operator_note"
    assert planned_facet(None, as_of="2026-11-12") is None  # no level is no fact, not a zero
