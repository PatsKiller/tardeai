"""Canonical Transferson universe: membership ≠ graph-profile count, ≠ 120/126."""
from __future__ import annotations

from scripts.lib.transferson_universe import (
    build_universe,
    get_membership_lineage,
    get_related_by_catalyst,
    get_related_by_industry,
    get_related_by_sector,
    get_symbol,
    research_tier_index,
    universe_diff,
)


def _sources(**over):
    base = {
        "holdings": ["SCHD", "NOC"],
        "cusips": ["12507E201"],
        "reentry": [
            {"symbol": "OLD", "intel": {"state": "WAIT"}},
            {"symbol": "NEAR1", "intel": {"state": "NEAR ENTRY"}},
            {"symbol": "HELDX", "intel": {"state": "CURRENTLY HELD"}, "held": True},
        ],
        "proposals_active": ["PROP1"],
        "proposals_recent": ["OLDPROP"],
        "watch_directives": ["WATCH1"],
        "hermes_ranks": {"WATCH1": 3, "COLD1": 900},
        "incubator": ["INC1"],
        "symbol_profiles": [
            {"symbol": "COLD1", "sector": "Technology", "industry": "Software"},
            {"symbol": "SCHD", "sector": "Financials", "industry": "Asset Management"},
            {"symbol": "NOC", "sector": "Industrials", "industry": "Aerospace"},
        ],
        "graph_profiles": [
            {"symbol": "SCHD", "ticker_guid": "tg-schd", "sector": "Financials", "industry": "Asset Management", "catalyst_guids": ["cat-1"]},
            {"symbol": "GRAPHONLY", "ticker_guid": "tg-g"},
        ],
        "trs": [{"symbol": "SCHD", "security_guid": "sec-schd", "ticker_guid": "tg-schd"}],
        "scope_s3": ["WATCH1"],
        "top_rank_n": 200,
    }
    base.update(over)
    return base


def test_no_hardcoded_universe_counts_in_module() -> None:
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "scripts/lib/transferson_universe.py").read_text()
    assert "120" not in text
    assert "126" not in text
    assert "3061" not in text


def test_canonical_count_is_unique_union() -> None:
    m = build_universe(sources=_sources())
    symbols = [r["symbol"] for r in m["securities"]]
    assert len(symbols) == len(set(symbols))
    assert m["canonical_universe_count"] == len(symbols)
    assert sum(m["tier_counts"].values()) == m["canonical_universe_count"]


def test_overlapping_reasons_do_not_double_count() -> None:
    m = build_universe(sources=_sources())
    schd = get_symbol(m, "SCHD")
    assert schd["currently_held"] is True
    assert "CURRENTLY_HELD" in schd["membership_reasons"]
    assert "GRAPH_PROFILE" in schd["membership_reasons"]
    assert m["securities"].count(schd) == 1 or symbols_once(m, "SCHD")


def symbols_once(m, sym) -> bool:
    return sum(1 for r in m["securities"] if r["symbol"] == sym) == 1


def test_every_holding_in_universe() -> None:
    m = build_universe(sources=_sources())
    assert get_symbol(m, "SCHD")
    assert get_symbol(m, "NOC")
    assert get_symbol(m, "SCHD")["current_research_tier"] == "T0-HOLD"


def test_active_proposal_in_universe() -> None:
    m = build_universe(sources=_sources())
    assert get_symbol(m, "PROP1")["current_research_tier"] == "T0-PROP"
    assert get_symbol(m, "PROP1")["active_proposal"] is True


def test_reentry_wait_stays_in_universe_without_t1() -> None:
    m = build_universe(sources=_sources())
    old = get_symbol(m, "OLD")
    assert old is not None
    assert old["sold_history_present"] is True
    assert old["current_research_tier"] != "T1-WATCH"
    assert "REENTRY_HISTORY" in old["membership_reasons"]
    near = get_symbol(m, "NEAR1")
    assert near["current_research_tier"] == "T1-WATCH"


def test_ready_near_promotes_t1() -> None:
    m = build_universe(sources=_sources())
    assert get_symbol(m, "NEAR1")["current_research_tier"] == "T1-WATCH"


def test_scope_governor_demotes_watch_not_hold() -> None:
    m = build_universe(sources=_sources())
    # WATCH1 is directive T1 but S3 → T3 unless READY/NEAR
    assert get_symbol(m, "WATCH1")["current_research_tier"] == "T3-COLD"
    assert get_symbol(m, "SCHD")["current_research_tier"] == "T0-HOLD"


def test_watch_qualify_disqualify() -> None:
    a = build_universe(sources=_sources())
    b = build_universe(sources=_sources(watch_directives=[], scope_s3=[]))
    diff = universe_diff(a, b)
    # WATCH1 remains (Hermes rank) — not a remove
    assert "WATCH1" not in diff["removed"]
    assert any(x["symbol"] == "WATCH1" and x["event"] == "TIER_CHANGED" for x in diff["tier_changed"]) or get_symbol(b, "WATCH1")


def test_graph_profile_is_coverage_not_universe() -> None:
    m = build_universe(sources=_sources())
    assert m["graph_profiled_count"] == 2
    assert m["canonical_universe_count"] > m["graph_profiled_count"]
    assert "graph-profiled /" in m["graph_coverage"]
    assert str(m["canonical_universe_count"]) in m["graph_coverage"]


def test_historical_120_cohort_is_not_the_universe() -> None:
    graph_only = [{"symbol": f"G{i:03d}", "ticker_guid": f"tg{i}"} for i in range(120)]
    m = build_universe(sources=_sources(graph_profiles=graph_only, holdings=["SCHD"], symbol_profiles=[]))
    assert m["graph_profiled_count"] == 120
    assert m["canonical_universe_count"] > 120
    idx = research_tier_index(m)
    assert "SCHD" in idx
    assert idx["SCHD"]["tier"] == "T0-HOLD"
    assert "OLD" not in idx  # WAIT is universe-only, not scheduler T1/T3 by membership alone


def test_cusip_unresolved_not_scheduler_ticker() -> None:
    m = build_universe(sources=_sources())
    assert get_symbol(m, "12507E201")
    assert get_symbol(m, "12507E201")["unresolved_identity"]
    idx = research_tier_index(m)
    assert "12507E201" not in idx


def test_never_mint_security_guid_from_ticker() -> None:
    m = build_universe(sources=_sources())
    graphonly = get_symbol(m, "GRAPHONLY")
    assert graphonly.get("security_guid") in {None, ""}
    schd = get_symbol(m, "SCHD")
    assert schd["security_guid"] == "sec-schd"


def test_industry_and_sector_reverse_not_supply_chain() -> None:
    m = build_universe(sources=_sources(
        holdings=["SCHD", "PFLT"],
        symbol_profiles=[
            {"symbol": "SCHD", "sector": "Financials", "industry": "Asset Management"},
            {"symbol": "PFLT", "sector": "Financials", "industry": "Asset Management"},
        ],
        graph_profiles=[],
    ))
    ind = get_related_by_industry(m, "SCHD")
    sec = get_related_by_sector(m, "SCHD")
    assert "PFLT" in ind["related_symbols"]
    assert "PFLT" in sec["related_symbols"]
    assert ind["not_supply_chain"] is True
    assert sec["not_supply_chain"] is True


def test_catalyst_reverse_traversal() -> None:
    m = build_universe(sources=_sources(
        holdings=["A", "B"],
        graph_profiles=[
            {"symbol": "A", "catalyst_guids": ["cat-z"]},
            {"symbol": "B", "catalyst_guids": ["cat-z"]},
        ],
        symbol_profiles=[],
    ))
    by_sym = get_related_by_catalyst(m, "A")
    by_cat = get_related_by_catalyst(m, "cat-z")
    assert "B" in by_sym["related_symbols"]
    assert set(by_cat["related_symbols"]) >= {"A", "B"}


def test_tier_change_is_not_add_remove() -> None:
    a = build_universe(sources=_sources(holdings=["SCHD"]))
    b = build_universe(sources=_sources(holdings=[]))  # sold SCHD; remains via graph profile
    diff = universe_diff(a, b)
    assert "SCHD" not in diff["added"]
    assert "SCHD" not in diff["removed"]
    assert any(x["symbol"] == "SCHD" and x["event"] == "TIER_CHANGED" for x in diff["tier_changed"])


def test_membership_lineage_and_scheduler_index() -> None:
    m = build_universe(sources=_sources())
    lin = get_membership_lineage(m, "SCHD")
    assert "CURRENTLY_HELD" in lin["membership_reasons"]
    idx = research_tier_index(m)
    assert set(idx) <= {r["symbol"] for r in m["securities"]}
    assert sum(1 for v in idx.values() if v["tier"] == "T0-HOLD") == 2


def test_no_126_hardcoded_as_universe() -> None:
    m = build_universe(sources=_sources())
    assert m["canonical_universe_count"] != 126
    assert "126" not in str(m["graph_coverage"])
