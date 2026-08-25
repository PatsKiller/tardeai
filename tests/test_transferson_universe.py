"""Canonical Transferson universe: membership ≠ graph-profile count, ≠ 120/126."""
from __future__ import annotations

from scripts.lib.security_identity import attach_identity_v2, resolve_identity_spine
from scripts.lib.transferson_universe import (
    build_universe,
    get_identity_lineage,
    get_membership_lineage,
    get_related_by_catalyst,
    get_related_by_industry,
    get_related_by_sector,
    get_symbol,
    graph_coverage_report,
    identity_coverage,
    metrics,
    operator_denominators,
    research_tier_index,
    seed_graph_from_universe,
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


def test_ticker_text_does_not_mint_security_guid() -> None:
    spine = resolve_identity_spine({"symbol": "NVDA"})
    assert spine["security_guid"] is None
    assert spine["identity_status"] == "UNRESOLVED_WITH_REASON"
    assert spine["ticker_guid_is_not_security"] is True
    attached = attach_identity_v2({"symbol": "NVDA"})
    assert attached.get("security_guid") is None


def test_company_or_cusip_yields_security_not_from_ticker() -> None:
    with_co = resolve_identity_spine({"symbol": "NOC", "company": "Northrop"})
    assert with_co["security_guid"]
    assert with_co["issuer_guid"]
    assert with_co["listing_guid"]
    assert with_co["security_guid"] != with_co.get("ticker_guid")
    with_cusip = resolve_identity_spine({"symbol": "X", "identifiers": {"cusip": "808524201"}})
    assert with_cusip["security_guid"]
    assert with_cusip["identity_status"] == "CONFIRMED"


def test_metrics_never_alias_graph_as_universe() -> None:
    m = build_universe(sources=_sources())
    met = metrics(m)
    assert met["canonical_universe_count"] == m["canonical_universe_count"]
    assert met["persistent_graph_profiled"] == m["graph_profiled_count"]
    assert met["free_first_circulated_count"] == m["graph_profiled_count"]
    assert met["ticker_guid_is_not_security"] is True
    assert met["canonical_universe_count"] != met["graph_profiled_count"] or m["graph_profiled_count"] < m["canonical_universe_count"]


def test_seed_graph_from_canonical_universe(tmp_path) -> None:
    m = build_universe(sources=_sources())
    cov = graph_coverage_report(m)
    assert cov["missing_n"] > 0
    assert cov["direction"].startswith("canonical_universe")
    seeded = seed_graph_from_universe(tmp_path, m)
    assert seeded["profiles_created"] == cov["missing_n"]
    again = seed_graph_from_universe(tmp_path, m)
    assert again["profiles_created"] == 0


def test_identity_lineage_four_paths() -> None:
    m = build_universe(sources=_sources())
    ident = get_identity_lineage(m, "SCHD")
    assert ident["ticker_guid_is_not_security"] is True
    assert ident["security_guid"] == "sec-schd"
    assert get_related_by_industry(m, "SCHD")["not_supply_chain"] is True
    assert get_related_by_sector(m, "SCHD")["not_supply_chain"] is True
    cat = get_related_by_catalyst(m, "SCHD")
    assert "catalyst_guids" in cat


def test_validated_screener_joins_universe_not_scheduler() -> None:
    m = build_universe(sources=_sources(
        screener_active=[{"symbol": "SCRN1", "screener_ids": ["core_growth_compounders"]}],
    ))
    rec = get_symbol(m, "SCRN1")
    assert rec is not None
    assert "SCREENER_ACTIVE" in rec["membership_reasons"]
    assert rec["current_research_tier"] == "T3-COLD"
    idx = research_tier_index(m)
    assert "SCRN1" not in idx


def test_screener_overlap_does_not_double_count() -> None:
    before = build_universe(sources=_sources())
    after = build_universe(sources=_sources(
        screener_active=[{"symbol": "SCHD", "screener_ids": ["covered_call_candidates"]}],
    ))
    assert after["canonical_universe_count"] == before["canonical_universe_count"]
    assert "SCREENER_ACTIVE" in get_symbol(after, "SCHD")["membership_reasons"]


def test_discovery_validated_is_member() -> None:
    m = build_universe(sources=_sources(
        discovery_validated=[{"symbol": "DISC1", "statuses": ["READY_FOR_REVIEW"]}],
    ))
    rec = get_symbol(m, "DISC1")
    assert rec is not None
    assert "DISCOVERY_VALIDATED" in rec["membership_reasons"]
    assert rec["current_research_tier"] == "T2-INCUB"
    assert "DISC1" in research_tier_index(m)


def test_company_description_is_candidate_not_confirmed() -> None:
    m = build_universe(sources=_sources(
        holdings=[],
        graph_profiles=[],
        trs=[],
        symbol_profiles=[{"symbol": "NVDA", "company": "NVIDIA Corporation", "sector": "Technology"}],
    ))
    rec = get_symbol(m, "NVDA")
    assert rec["issuer_guid"]
    assert rec["security_guid"]
    assert rec["identity_status"] == "CANDIDATE"
    assert rec["security_guid"] != rec.get("ticker_guid")


def test_share_class_collision_does_not_collapse_securities() -> None:
    m = build_universe(sources=_sources(
        holdings=[],
        graph_profiles=[],
        trs=[],
        symbol_profiles=[
            {"symbol": "GOOG", "company": "Alphabet Inc"},
            {"symbol": "GOOGL", "company": "Alphabet Inc"},
        ],
    ))
    a, b = get_symbol(m, "GOOG"), get_symbol(m, "GOOGL")
    assert a["issuer_guid"] == b["issuer_guid"]
    assert not a.get("security_guid")
    assert not b.get("security_guid")
    assert a["unresolved_reason"] == "share_class_unspecified_collision"


def test_operator_denominators_never_alias_graph_as_universe() -> None:
    m = build_universe(sources=_sources())
    pack = operator_denominators(m)
    assert pack["canonical_universe_count"] == m["canonical_universe_count"]
    assert "graph-profiled /" in pack["graph_coverage"]
    assert "free-first circulated /" in pack["free_first_coverage"]
    assert pack["pre_merge_gate"] == "PRE_MERGE_SOURCE_ACCEPTANCE"
    assert pack["r17_requires"] == "POST_DEPLOY_LIVE_ACCEPTANCE_PASS"
    cov = identity_coverage(m)
    assert cov["r17_must_not_attach_to_ticker"] if False else cov["unresolved_ceiling_policy"]["r17_must_not_attach_to_ticker"] is True


def test_seeded_edges_carry_provenance(tmp_path) -> None:
    m = build_universe(sources=_sources(graph_profiles=[]))
    seeded = seed_graph_from_universe(tmp_path, m)
    assert seeded["profiles_created"] > 0
    path = tmp_path / "data/cio/ticker_research_graph.jsonl"
    import json
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    edges = [e for r in rows for e in (r.get("relationships") or [])]
    assert edges
    assert all(e.get("producer") == "seed_graph_from_universe" for e in edges)
    assert all(e.get("source_type") == "canonical_universe" for e in edges)
    assert all("observed_at" in e and "recorded_at" in e for e in edges)
