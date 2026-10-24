"""Approved Watch sort/filter: pure saved rows, pinned clock; no DB, providers, or source writes."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlencode

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.data_broker import watch_position_facts as pf

NOW = datetime(2026, 10, 24, 14, tzinfo=timezone.utc)


def row(symbol, score, *, stance="WATCH", lane="forming", starred=False, cat=False, blocked=False, position="never_held"):
    return {"symbol": symbol, "security_guid": "fixture-" + symbol, "conviction": score, "stance": stance,
            "lane": lane, "starred": starred, "position_state": position,
            "conflicts": [{"kind": "trade_ai_block", "summary": "Stored disagreement"}] if blocked else [],
            "next_action": {"kind": "resolve_conflict" if blocked else "none"},
            "company_facts": {"catalyst": {"status": "CURRENT" if cat else "MISSING", "headline": "Fixture publication" if cat else None}}}


def ranked(rows, sort):
    return [r["symbol"] for r in sorted(rows, key=lambda r: (*pf.sort_key(sort, r, r.get("conviction")), r["symbol"]))]


@pytest.mark.parametrize("sort", ["conviction_desc", "conviction_asc"])
def test_no_score_last_even_when_starred_and_known_zero_is_not_missing(sort):
    rows = [row("MISSING", None, starred=True), row("BOOL", True), row("NAN", float("nan")),
            row("INF", float("inf")), row("ZERO", 0), row("KNOWN", "70", starred=True)]
    result = ranked(rows, sort)
    assert result[:2] == ["KNOWN", "ZERO"]
    assert set(result[2:]) == {"MISSING", "BOOL", "NAN", "INF"}
    assert pf.passes(rows[4], {"conv": "lt60"}, now=NOW)
    assert not pf.passes(rows[0], {"conv": "lt60"}, now=NOW)


def test_starred_priority_then_score_direction_then_stance_severity_then_symbol():
    rows = [row("Z", 80, starred=True, stance="EXIT"), row("A", 80, starred=True, stance="EXIT"),
            row("H", 80, starred=True, stance="HOLD"), row("L", 50, starred=True), row("U", 99)]
    assert ranked(rows, "conviction_desc") == ["A", "Z", "H", "L", "U"]
    assert ranked(rows, "conviction_asc") == ["L", "A", "Z", "H", "U"]


def test_setup_order_and_ties_use_existing_lane_without_mutation():
    rows = [row("NO", 99, lane=""), row("OLD", None, lane="expired"), row("HELD", 60, lane="manage"),
            row("F", 80, lane="forming"), row("R", 40, lane="reentry"), row("READY", 90, lane="actionable")]
    before = deepcopy(rows)
    assert ranked(rows, "setup") == ["READY", "R", "F", "HELD", "OLD", "NO"]
    assert rows == before


def test_all_filter_groups_combine_and_but_stance_and_setup_choices_are_multiselect():
    yes = row("YES", 80, stance="RE_ENTER", lane="reentry", cat=True, blocked=True, position="formerly_held")
    query = {"conv": "70", "stance": "RE-ENTER,WATCH", "stage": "reentry,forming,blocked,has_catalyst", "position": "formerly_held"}
    assert pf.passes(yes, query, now=NOW)
    for patch in [{"conviction": 60}, {"stance": "EXIT"}, {"lane": "manage"}, {"conflicts": [], "next_action": {"kind": "none"}},
                  {"position_state": "held"}, {"company_facts": {"catalyst": {"status": "STALE", "headline": "old"}}}]:
        assert not pf.passes({**yes, **patch}, query, now=NOW), patch


def test_catalyst_filter_requires_current_cio_facts_not_raw_overlay_or_stale_headline():
    r = row("AAA", 80, cat=False)
    r.update(catalyst="Unrelated raw overlay", news=[{"title": "Raw"}])
    assert pf.passes(r, {"stage": "no_catalyst"}, now=NOW)
    assert not pf.passes(r, {"stage": "has_catalyst"}, now=NOW)
    assert pf.passes(r, {"stage": "has_catalyst,no_catalyst"}, now=NOW)


def test_disjunctive_facets_keep_other_filters_and_other_stage_subgroups():
    rows = [row("R", 80, lane="reentry", cat=True, blocked=True), row("F", 60, lane="forming", cat=True, blocked=True),
            row("UNBLOCKED", 90, lane="reentry", cat=True), row("NOCAT", 90, lane="forming", blocked=True)]
    f = pf.facet_counts(rows, now=NOW, filters={"conv": "70", "stage": "reentry,blocked,has_catalyst"})
    assert f["conv"]["70"] == 1 and f["conv"]["60"] == 1
    assert f["stage"]["forming"] == 0 and f["stage"]["reentry"] == 1
    assert f["stage"]["has_catalyst"] == 1 and f["stage"]["no_catalyst"] == 0
    assert f["stance"]["WATCH"] == 1


def test_url_roundtrip_keeps_all_requested_filters_and_sort():
    query = {"conv": "70", "stance": "RE-ENTER,WATCH", "stage": "reentry,blocked,has_catalyst", "position": "formerly_held", "sort": "conviction_desc"}
    parsed = {k: v[0] for k, v in parse_qs(urlencode(query)).items()}
    assert pf.active_filters(parsed) == {k: v for k, v in query.items() if k != "sort"}
    assert parsed["sort"] in pf.SORTS
    assert pf.active_filters({"conv": "any"}) == {}


def test_curation_filters_enriched_cio_rows_and_preserves_security_facts():
    from lib.data_broker import watch_curation as wc
    rows = [row("A", 80, cat=True, starred=True), row("B", 90, cat=False), row("C", None)]
    by = {r["symbol"]: r for r in rows}; before = deepcopy(by)
    g = {"operator": {k: {} for k in by}, "opps": {}, "row_for": lambda s: deepcopy(by[s]), "now": NOW, "payload": {}}
    out = wc.build_curation(g, filters={"conv": "70", "stage": "has_catalyst", "sort": "conviction_desc"}, now=NOW)["my_watchlist"]
    assert [r["symbol"] for r in out["rows"]] == ["A"]
    assert out["unfiltered_count"] == 3 and out["count"] == 1 and out["position_facets"]["stage"]["no_catalyst"] == 1
    assert out["rows"][0]["security_guid"] == "fixture-A" and by == before


def test_sort_only_prospects_preserves_capped_population_and_overflow():
    from lib.data_broker.watch_prospects import filter_payload
    payload = {"lanes": [{"id": "forming", "count": 3, "cap": 2, "items": [row("A", 60), row("B", 80)], "overflow": ["C"]}],
               "counts": {"forming": 3, "total": 3}}
    before = deepcopy(payload)
    out = filter_payload(payload, {"sort": "conviction_desc"}, now=NOW)
    assert [r["symbol"] for r in out["lanes"][0]["items"]] == ["B", "A"]
    assert out["lanes"][0]["count"] == 3 and out["lanes"][0]["overflow"] == ["C"]
    assert out["counts"] == payload["counts"] and payload == before
    filtered = filter_payload(payload, {"conv": "70", "sort": "conviction_desc"}, now=NOW)
    assert [r["symbol"] for r in filtered["lanes"][0]["items"]] == ["B"]
    assert filtered["lanes"][0]["overflow"] == ["C"] and filtered["unevaluated_overflow"] == 1
    assert filtered["filter_scope"] == "shown_lane_rows"
