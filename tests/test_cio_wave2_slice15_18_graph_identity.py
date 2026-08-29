"""Wave 2 slices 15 / 16 / 17 / 18 — graph context and identity honesty.

15  1-hop same-sector held neighbours, cap 5, class D, from the existing
    holdings sector resolution. No new store, no invented edge.
16  graph_impact attaches to S6 names only.
17  a failed registry read is LOOKUP_FAILED, not UNRESOLVED.
18  a bare ticker is never used as a security GUID.

READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

import pytest

from scripts.lib import cio_subject_guid as sg
from scripts.lib.cio_graph_impact import (
    NEIGHBOR_CAP,
    build_graph_impact_for_s6,
    build_sector_index,
    graph_impact_for,
    s6_symbols,
)

HOLDINGS = {
    "holdings": [
        {"symbol": "SCHD", "market_value": 365694.75},
        {"symbol": "XLI", "market_value": 36268.37},
        {"symbol": "SPCX", "market_value": 27292.00},
        {"symbol": "BAH", "market_value": 673.83},
        {"symbol": "BND", "market_value": 55.91},
        {"symbol": "SCHG", "market_value": 8.09},        # dust
        {"symbol": "CASH", "is_cash": True, "market_value": 585917.80},
    ],
    "resolved_sector_contributors": {
        "Industrials": [
            {"symbol": "XLI", "value": 35868.30},
            {"symbol": "SPCX", "value": 27590.00},
            {"symbol": "BAH", "value": 664.47},
            {"symbol": "SCHD", "value": 20875.63},
            {"symbol": "SCHG", "value": 2.00},           # dust must not be a neighbour
        ],
        "Financial Services": [
            {"symbol": "SCHD", "value": 100000.00},
            {"symbol": "XLI", "value": 500.00},
        ],
        "Fixed Income": [{"symbol": "BND", "value": 55.91}],
    },
}

S6 = "S6_CONCENTRATION_OR_DISPOSITION"
PLANS = [
    {"situation_type": S6, "symbols": ["SCHD"], "status": "draft"},
    {"situation_type": S6, "symbols": ["BND"], "status": "draft"},
    {"situation_type": S6, "symbols": ["SCHG"], "status": "draft"},   # dust
    {"situation_type": S6, "symbols": ["QCOM"], "status": "draft"},   # not held
    {"situation_type": "S1_POSITION_LIFECYCLE", "symbols": ["XLI"], "status": "draft"},
]


# ── 15 ───────────────────────────────────────────────────────────────────────

def test_neighbours_are_same_sector_held_names_ranked_deterministically():
    idx = build_sector_index(HOLDINGS, eligible={"SCHD", "XLI", "SPCX", "BAH", "BND"})
    g = graph_impact_for("SCHD", index=idx)
    assert g["hop"] == 1
    assert g["class"] == "D"
    assert g["edge"] == "same_sector_held"
    assert g["quality"] == "OK"
    names = [n["symbol"] for n in g["neighbors"]]
    # XLI shares two sectors with SCHD, so it outranks the one-sector names.
    assert names[0] == "XLI"
    assert set(names) == {"XLI", "SPCX", "BAH"}
    assert g["neighbors"][0]["shared_sector_n"] == 2


def test_ranking_is_stable_across_calls():
    idx = build_sector_index(HOLDINGS, eligible={"SCHD", "XLI", "SPCX", "BAH"})
    first = [n["symbol"] for n in graph_impact_for("SCHD", index=idx)["neighbors"]]
    second = [n["symbol"] for n in graph_impact_for("SCHD", index=idx)["neighbors"]]
    assert first == second


def test_cap_is_enforced_and_truncation_is_declared():
    contributors = {"Industrials": [{"symbol": f"Q{chr(65 + i)}", "value": 100.0 - i}
                                    for i in range(12)] + [{"symbol": "SCHD", "value": 5.0}]}
    holdings = {"resolved_sector_contributors": contributors}
    eligible = {f"Q{chr(65 + i)}" for i in range(12)} | {"SCHD"}
    g = graph_impact_for("SCHD", holdings=holdings, eligible=eligible)
    assert g["neighbor_n"] == NEIGHBOR_CAP == 5
    assert g["neighbor_total"] == 12
    assert g["truncated"] is True


def test_dust_is_never_a_neighbour():
    g = build_graph_impact_for_s6(plans=PLANS, holdings=HOLDINGS)
    for item in g["items"].values():
        assert "SCHG" not in [n["symbol"] for n in item["neighbors"]]


def test_lone_sector_yields_an_honest_empty_not_a_guess():
    g = build_graph_impact_for_s6(plans=PLANS, holdings=HOLDINGS)
    bnd = g["items"]["BND"]
    assert bnd["quality"] == "OK"
    assert bnd["sectors"] == ["Fixed Income"]
    assert bnd["neighbors"] == []
    assert bnd["neighbor_n"] == 0


def test_missing_sector_map_is_data_unavailable_not_empty_success():
    g = graph_impact_for("SCHD", holdings={"holdings": []})
    assert g["available"] is False
    assert g["quality"] == "DATA_UNAVAILABLE"
    assert g["neighbors"] == []


def test_symbol_absent_from_sector_map_is_labelled():
    g = graph_impact_for("ZZZX", holdings=HOLDINGS, eligible={"ZZZX", "SCHD"})
    assert g["quality"] == "NO_SECTOR_FOR_SYMBOL"
    assert g["neighbors"] == []


# ── 16 ───────────────────────────────────────────────────────────────────────

def test_scope_is_s6_only():
    assert s6_symbols(PLANS) == ["BND", "QCOM", "SCHD", "SCHG"]
    g = build_graph_impact_for_s6(plans=PLANS, holdings=HOLDINGS)
    assert g["scope"] == "S6_CONCENTRATION_OR_DISPOSITION names only"
    # XLI carries only an S1 plan, so it gets no graph_impact
    assert "XLI" not in g["items"]
    assert set(g["items"]) == {"SCHD", "BND"}


def test_s6_names_that_are_not_held_non_dust_are_skipped_with_a_reason():
    g = build_graph_impact_for_s6(plans=PLANS, holdings=HOLDINGS)
    by = {s["symbol"]: s["reason"] for s in g["skipped"]}
    assert by["SCHG"] == "dust_residual"
    assert by["QCOM"] == "not_held_non_dust"
    assert g["attached_n"] == 2


def test_graph_impact_is_context_never_action():
    g = build_graph_impact_for_s6(plans=PLANS, holdings=HOLDINGS)
    assert g["class"] == "D"
    assert g["financial_action"] is False
    assert g["memory_behavior_influence"] == 0
    assert g["authority"] == "READ_ONLY_ADVISORY"


# ── 17 ───────────────────────────────────────────────────────────────────────

REGISTRY = {"entities": {"g1": {"subject_guid": "g1", "identity_status": "CONFIRMED",
                                "entity_type": "SECURITY"}},
            "by_symbol": {"SCHD": "g1"}}


def test_registry_answer_no_entity_is_unresolved():
    hit = sg.lookup_subject("ZZZX", root=None)
    assert hit["identity_status"] == sg.UNRESOLVED
    assert hit["identity_lookup"] == sg.UNRESOLVED
    assert hit["identity_lookup_failed"] is False
    assert hit["subject_guid"] is None


def test_registry_read_failure_is_lookup_failed_not_unresolved(monkeypatch):
    def _boom(root=None):
        raise OSError("registry unreadable")

    monkeypatch.setattr("scripts.lib.identity_registry.load_cached", _boom)
    hit = sg.lookup_subject("SCHD")
    assert hit["identity_lookup"] == sg.LOOKUP_FAILED
    assert hit["identity_lookup_failed"] is True
    assert hit["identity_lookup_reason"] == "OSError"
    # the old contract still holds: it never claims a guid it does not have
    assert hit["subject_guid"] is None
    assert hit["identity_status"] == sg.UNRESOLVED


def test_cash_is_not_applicable_rather_than_unresolved():
    hit = sg.lookup_subject("CASH")
    assert hit["identity_lookup"] == sg.NOT_APPLICABLE
    assert hit["identity_lookup_failed"] is False
    assert hit["subject_guid"] is None


def test_stamp_row_keeps_the_strongest_explanation(monkeypatch):
    calls = {"n": 0}

    def _mixed(symbol, *, root=None):
        calls["n"] += 1
        if symbol == "CASH":
            return sg._empty("CASH", sg.NOT_APPLICABLE, "cash_or_non_entity_symbol")
        return sg._empty(symbol, sg.LOOKUP_FAILED, "OSError")

    monkeypatch.setattr(sg, "lookup_subject", _mixed)
    row = sg.stamp_row({"symbols": ["CASH", "SCHD"]})
    # A read failure outranks "nothing to look up" — the row must not read clean.
    assert row["identity_lookup"] == sg.LOOKUP_FAILED
    assert row["identity_lookup_failed"] is True
    assert row["subject_guid"] is None


def test_stamp_row_resolved_path(monkeypatch):
    monkeypatch.setattr(sg, "lookup_subject", lambda s, root=None: {
        "subject_guid": "g1", "entity_type": "SECURITY", "identity_status": "CONFIRMED",
        "identity_lookup": sg.RESOLVED, "identity_lookup_failed": False,
        "identity_lookup_reason": None,
    })
    row = sg.stamp_row({"symbol": "SCHD"})
    assert row["subject_guid"] == "g1"
    assert row["identity_lookup"] == sg.RESOLVED
    assert row["identity_lookup_failed"] is False


# ── 18 ───────────────────────────────────────────────────────────────────────

def test_a_bare_ticker_is_never_used_as_a_security_guid():
    from scripts.lib.identity_registry import register, ticker_alias_guid

    doc = {"entities": {}, "by_symbol": {}}
    register(doc, {"symbol": "ZZZX"})
    guids = list(doc["entities"])
    assert guids, "a ticker-only row should still get a durable alias key"
    for guid in guids:
        assert guid != "ZZZX"
        assert guid == ticker_alias_guid("ZZZX")
        ent = doc["entities"][guid]
        # the ticker is recorded as an alias, never promoted to the security id
        assert ent.get("security_guid") in (None, guid) or ent["security_guid"] != "ZZZX"
        assert "ZZZX" in (ent.get("aliases") or [])


def test_ticker_alias_guid_is_a_uuid_not_the_symbol():
    from scripts.lib.identity_registry import ticker_alias_guid

    guid = ticker_alias_guid("SCHD")
    assert guid and guid != "SCHD"
    assert len(guid) == 36 and guid.count("-") == 4


@pytest.mark.parametrize("sym", ["SCHD", "12507E201", "V"])
def test_registered_entity_key_is_never_the_symbol_text(sym):
    from scripts.lib.identity_registry import register

    doc = {"entities": {}, "by_symbol": {}}
    register(doc, {"symbol": sym})
    assert sym not in doc["entities"]
    assert doc["by_symbol"].get(sym.upper()) != sym.upper()


def test_home_carries_graph_impact_and_says_so_when_not_computed():
    from scripts.lib.cio_command_center import build_office_home

    bare = build_office_home(operator_product={})
    assert bare["graph_impact"]["available"] is False
    assert bare["graph_impact"]["reason"] == "not_computed_by_this_caller"

    supplied = build_office_home(
        operator_product={},
        graph_impact=build_graph_impact_for_s6(plans=PLANS, holdings=HOLDINGS),
    )
    g = supplied["graph_impact"]
    assert g["attached_n"] == 2
    assert set(g["items"]) == {"SCHD", "BND"}
    assert supplied["telegram_sent"] is False
