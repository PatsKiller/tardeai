"""Pure SEC event selection; no watcher, sender, provider, database or live state."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("premarket_dedupe_under_test", ROOT / "scripts/lib/premarket_dedupe.py")
assert SPEC is not None and SPEC.loader is not None
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)

DAY = "2026-10-18"
FIRST_ID = "8-K:0000000001-26-000001"
SECOND_ID = "8-K:0000000001-26-000002"


def filing(event_id=FIRST_ID):
    return {"type": "8-K", "title": "Same filing headline", "event_id": event_id}


def item(filings, symbol="EXAMPLE", surge_count=None):
    return {"symbol": symbol, "filings": filings, "surge_count": surge_count}


def empty_state():
    return {"day": DAY, "symbols": {}}


def test_repeated_event_id_within_one_item_is_selected_once():
    first = filing()
    material, state = D.select_material([item([first, copy.deepcopy(first)])], empty_state())

    assert material == [item([first])], "one SEC event must not repeat inside the first message"
    assert state["symbols"]["EXAMPLE"]["events"] == [FIRST_ID]


def test_distinct_event_ids_with_same_headline_are_both_selected():
    filings = [filing(FIRST_ID), filing(SECOND_ID)]
    material, state = D.select_material([item(filings)], empty_state())

    assert material == [item(filings)]
    assert state["symbols"]["EXAMPLE"]["events"] == [FIRST_ID, SECOND_ID]


def test_existing_cross_poll_dedupe_still_suppresses_the_same_event():
    state = empty_state()
    messages = []
    for _ in range(12):
        material, state = D.select_material([item([filing()])], state)
        messages.extend(material)

    assert messages == [item([filing()])]


def test_same_id_in_two_items_of_one_symbol_is_already_covered():
    material, _ = D.select_material([item([filing()]), item([filing()])], empty_state())
    assert material == [item([filing()])]


def test_same_id_on_distinct_symbols_is_not_collapsed():
    material, _ = D.select_material([item([filing()], "EXAMPLE"), item([filing()], "OTHER")], empty_state())
    assert material == [item([filing()], "EXAMPLE"), item([filing()], "OTHER")]


@pytest.mark.parametrize("event_id", [None, "", False, 0])
def test_missing_event_identity_is_not_invented_or_deduplicated(event_id):
    filings = [filing(event_id), filing(event_id)]
    material, state = D.select_material([item(filings)], empty_state())
    assert material == [item(filings)]
    assert state["symbols"]["EXAMPLE"]["events"] == []
    assert D.select_material([item(filings)], state)[0] == [item(filings)]


def test_absent_event_id_is_not_replaced_by_the_headline():
    filings = [{"type": "8-K", "title": "Same filing headline"}] * 2
    material, state = D.select_material([item(filings)], empty_state())
    assert material == [item(filings)]
    assert state["symbols"]["EXAMPLE"]["events"] == []


def test_selection_does_not_mutate_input_items_or_prior_state():
    items = [item([filing(), filing()])]
    state = {"day": DAY, "symbols": {"EXAMPLE": {"events": ["prior"], "surge_count": 20}}}
    before_items, before_state = copy.deepcopy(items), copy.deepcopy(state)

    D.select_material(items, state)

    assert items == before_items and state == before_state


def test_existing_surge_materiality_is_unchanged():
    _, state = D.select_material([item([], surge_count=20)], empty_state())
    assert D.select_material([item([], surge_count=35)], state)[0] == []
    assert D.select_material([item([], surge_count=40)], state)[0] == [item([], surge_count=40)]
