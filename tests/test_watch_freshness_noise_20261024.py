"""C2 stored-reference selection only: no DB, providers, host state, or new fact store."""
from copy import deepcopy
from datetime import datetime, timezone
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.data_broker import watch_market_facts as mf

NOW = datetime(2026, 10, 24, 14, tzinfo=timezone.utc)


def facts(master, strategy=None, closed=None, price=10):
    raw = {"master": {"AAA": master}, "strategy": {"AAA": strategy or {}}, "closed": {"AAA": closed or {}},
           "quotes": {"AAA": {"price": price, "as_of": "2026-10-23T19:45:00Z", "source": "data_broker.latest_quote:schwab", "provider": "schwab"}},
           "read_status": {k: "ok" for k in ("master", "strategy", "closed", "quotes")}}
    return raw, mf.view(raw, "AAA", now=NOW)


def test_broken_primary_uses_nearest_existing_resistance_not_first_compatible():
    raw, view = facts({"resistance": 8}, {"resistance": 15, "created_at": NOW},
                      {"resistance": 11, "as_of": "2026-10-23", "state": "BELOW"})
    before = deepcopy(raw)
    r = view["resistance"]
    assert (r["value"], r["source"], r["as_of"]) == (11, "ui_prefs:" + mf.RESISTANCE_KEY, "2026-10-23")
    assert r["broken_reference"] == {"value": 8.0, "source": "watchlist_symbol_master", "source_label": "Watch symbol master", "as_of": None, "relation": "BELOW_PRICE"}
    assert r["fallback_status"] == "nearest_compatible_reference" and r["source_state"] == "BELOW"
    assert "below the shown price" in r["reason"] and r["freshness"] == "UNKNOWN"
    assert mf.view(raw, "AAA", now=NOW) == view and raw == before and view["provider_calls"] == 0


def test_valid_primary_keeps_precedence_even_with_nearer_fallback():
    _, view = facts({"support": 7, "resistance": 15}, {"support": 9, "resistance": 12}, {"resistance": 11})
    for kind, expected in (("support", 7), ("resistance", 15)):
        assert view[kind]["value"] == expected and view[kind]["source"] == "watchlist_symbol_master"
        assert view[kind]["broken_reference"] is None and view[kind]["fallback_status"] is None


@pytest.mark.parametrize("kind,primary,strategy,status", [("support", 12, 11, "none_below_price"), ("resistance", 8, 9, "none_above_price")])
def test_all_crossed_sources_report_missing_fallback_without_inventing_level(kind, primary, strategy, status):
    _, view = facts({kind: primary}, {kind: strategy}, {"resistance": 9})
    level = view[kind]
    assert level["value"] is None and level["source"] is None and level["freshness"] == "MISSING"
    assert level["broken_reference"]["value"] == primary and level["fallback_status"] == status


def test_missing_price_keeps_original_reference_and_unknown_relation():
    _, view = facts({"support": 12, "resistance": 8}, {"support": 9, "resistance": 11}, price=None)
    assert view["price"]["value"] is None
    for kind, value in (("support", 12), ("resistance", 8)):
        assert view[kind]["value"] == value and view[kind]["compatibility"] == "UNKNOWN"
        assert view[kind]["broken_reference"] is None and "relation is unknown" in view[kind]["reason"]


def test_closed_unavailable_and_targets_stops_are_never_fallback_levels():
    _, view = facts({"resistance": 8}, {"target_price": 20, "stop_loss": 9}, {"resistance": 11, "state": "UNAVAILABLE"})
    assert view["resistance"]["value"] is None and view["resistance"]["fallback_status"] == "none_above_price"


def test_price_truth_source_time_and_staleness_are_not_upgraded_by_presentation_metadata():
    _, view = facts({"support": 9})
    p = view["price"]
    assert p["as_of"] == "2026-10-23T19:45:00Z" and p["stale"] is True and p["freshness"] == "STALE"
    assert p["source"] == "data_broker.latest_quote:schwab" and p["value"] == 10
