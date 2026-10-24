"""Pinned, provider-free W7 projection and ownership regressions."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from scripts.lib.w7_pages import page_payload, project_pages, validate_payload
import pytest

NOW = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def inputs():
    guid = "00000000-0000-4000-8000-000000000001"
    accounts = [{"account_id": "fixture_ira", "account_label": "Fixture IRA", "total_usd": 20000,
                 "status": "LIVE", "as_of": NOW.isoformat()},
                {"account_id": "fixture_manual", "account_label": "Fixture manual account", "total_usd": 8000,
                 "status": "STALE", "as_of": "2026-10-20T20:00:00+00:00"}]
    holdings = [{"symbol": "SYNF", "account_id": "fixture_ira", "market_value": 12000, "is_fund": True},
                {"symbol": "ALFA", "account_id": "fixture_ira", "market_value": 6000, "asset_type": "equity"},
                {"symbol": "MISS", "account_id": "fixture_manual", "market_value": 4000, "is_fund": True},
                {"symbol": "CASH", "account_id": "fixture_ira", "market_value": 2000, "is_cash": True},
                {"symbol": "CASH", "account_id": "fixture_manual", "market_value": 4000, "is_cash": True}]
    company = {"symbol": "ALFA", "security_guid": guid, "company_facts": {"security_guid": guid,
               "sector": {"value": "Technology", "source": "fixture-C1"},
               "industry": {"value": "Software", "source": "fixture-C1"}}}
    truth = {"portfolio": {"total_usd": 28000, "cash_usd": 6000, "accounts": accounts, "holdings": holdings,
                            "as_of": NOW.isoformat(), "source": "fixture-CIO", "stale": False, "gap": None},
             "positions": {"rows": [], "source": "fixture-CIO", "as_of": NOW.isoformat()},
             "stops": {"active_count": 1, "pending_count": 1, "filled_count": 0, "unprotected_count": 2},
             "regime": {"label": "Fixture regime", "vix": 23.4, "as_of": NOW.isoformat()},
             "approvals": {"total": 4}, "cio_status": {"evaluations": []},
             "capital": {"cash_usd": 6000, "reserved_usd": 1000, "earmarked_usd": 2000, "investable_usd": 3000,
                         "policy_max_pct": 9, "alert_level_pct": 14},
             "do_now": {"items": [{"id": str(i), "title": "CIO-ranked fixture action " + str(i)} for i in range(9)]},
             "companies": {"by_guid": {guid: company}}}
    look = {"fund_cache": {"SYNF": {"ALFA": 0.5, "BETA": 0.25}}, "fund_symbols": {"SYNF", "MISS"},
            "proxies": {}, "theme_members": {"Fixture theme": {"ALFA"}}, "theme_targets": {"Fixture theme": 50},
            "snapshot": {"portfolio_total": 999999, "grok_narrative": "I cannot provide investment advice", "grok_status": "ok"}}
    return truth, look


def test_current_cio_basis_and_partial_fund_coverage_are_dollar_exact():
    truth, look = inputs()
    result = project_pages(truth, **look)["lookthrough"]
    assert result["portfolio_total_usd"] == 28000  # never snapshot's 999999
    assert result["looked_through_usd"] == 15000
    assert result["fund_value_usd"] == 16000
    assert result["fund_covered_usd"] == 9000
    assert result["fund_coverage_pct"] == 56.25
    assert result["portfolio_coverage_pct"] == 53.57
    assert result["funds_without_holdings"][0]["value_usd"] == 4000
    assert result["gaps"][0]["value_usd"] == 3000
    assert result["unclassified_industry_usd"] == 3000
    assert result["top_underlying"][0]["value_usd"] == 12000
    assert {x["source"] for x in result["top_underlying"][0]["sources"]} == {"Direct holding", "Published fund holdings"}


def test_account_filters_have_their_own_denominator_and_no_global_fallback():
    truth, look = inputs()
    data = project_pages(truth, **look)["lookthrough"]
    ira = data["by_account"]["fixture_ira"]
    assert ira["portfolio_total_usd"] == 20000
    assert ira["portfolio_coverage_pct"] == 75
    manual = data["by_account"]["fixture_manual"]
    assert manual["looked_through_usd"] == 0  # measured holdings contain only unresolved fund + cash
    assert manual["funds_without_holdings"][0]["value_usd"] == 4000
    assert manual["account_gaps"][0]["value_usd"] == 8000
    assert manual["account_gaps"][0]["label"] == "Fixture manual account"
    assert "unknown" not in data["by_account"]


def test_company_classification_requires_bound_guid_and_source():
    truth, look = inputs()
    c = next(iter(truth["companies"]["by_guid"].values()))
    c["company_facts"]["security_guid"] = "wrong-guid"
    result = project_pages(truth, **look)["lookthrough"]
    assert result["unclassified_industry_usd"] == 15000
    assert [r["name"] for r in result["industries"]] == ["Unclassified"]


def test_bad_cache_never_turns_a_fund_into_a_direct_equity():
    truth, look = inputs()
    look["fund_cache"]["SYNF"] = {"ALFA": 0.8, "BETA": 0.9}
    data = project_pages(truth, **look)["lookthrough"]
    assert data["looked_through_usd"] == 6000
    assert {r["symbol"] for r in data["top_underlying"]} == {"ALFA"}
    assert {r["symbol"] for r in data["funds_without_holdings"]} == {"SYNF", "MISS"}


def test_model_refusal_is_a_gap_not_an_advisory():
    truth, look = inputs()
    narrative = project_pages(truth, **look)["lookthrough"]["narrative"]
    assert narrative["text"] is None
    assert narrative["reason"] == "The model declined to provide a narrative"


def test_shared_facts_are_forwarded_unchanged_and_cio_ranking_is_preserved():
    truth, look = inputs()
    truth["conflicts"] = {"findings": [{"kind": "AGREEMENT", "rule": "U5", "key": "fixture-finding"}], "gap": None}
    before = deepcopy(truth)
    data = project_pages(truth, **look)
    for key in ("stops", "regime", "approvals", "capital", "cio_status"):
        assert data[key] == truth[key]
    assert data["portfolio"] == {k: v for k, v in truth["portfolio"].items() if k not in ("holdings", "stored_totals")}
    assert data["positions"] == truth["positions"]
    assert data["conflicts"] == truth["conflicts"]
    assert [a["id"] for a in data["do_now"]["items"]] == [str(i) for i in range(7)]
    assert truth == before


def test_endpoint_is_read_only_and_calls_one_cio_resolver(tmp_path):
    truth, look = inputs()
    (tmp_path / "data").mkdir()
    artifact = tmp_path / "data" / "fixture.json"
    artifact.write_text(json.dumps({"sentinel": 17}))
    original = artifact.read_bytes()
    calls = []
    def resolver(**kw):
        calls.append(kw)
        return truth
    result = page_payload(tmp_path, resolver=resolver, now=NOW, lookthrough_inputs=look)
    assert len(calls) == 1
    assert calls[0]["root"] == tmp_path and calls[0]["now"] == NOW
    assert result["approvals"]["total"] == 4
    assert artifact.read_bytes() == original
    assert sorted(p.name for p in tmp_path.rglob("*")) == ["data", "fixture.json"]


def test_unavailable_canonical_basis_is_never_rendered_as_a_zero(tmp_path):
    def resolver(**kw):
        raise OSError("fixture unmounted")
    result = page_payload(tmp_path, resolver=resolver, now=NOW, lookthrough_inputs={})
    assert result["portfolio"]["gap"]
    assert result["lookthrough"]["portfolio_total_usd"] is None
    assert result["lookthrough"]["looked_through_usd"] is None


def test_display_contract_refuses_invalid_measurements_and_requires_account_names():
    truth, look = inputs()
    data = project_pages(truth, **look)
    assert validate_payload(data) is data
    data["portfolio"]["total_usd"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        validate_payload(data)
    data["portfolio"]["total_usd"] = 28000
    data["positions"]["rows"] = [{"symbol": "ALFA", "account_id": "fixture_ira"}]
    with pytest.raises(ValueError, match="account display name"):
        validate_payload(data)


def test_ownership_removes_w7_duplicate_panels_and_links_to_the_single_home():
    pages = ROOT / "apps/command-center-v3/src/pages"
    home = (pages / "HomeHub.tsx").read_text()
    cio = (pages / "CioHub.tsx").read_text()
    portfolio = (pages / "PortfolioHub.tsx").read_text()
    assert "HomeClassic" not in home and "HomeDoNow" not in home
    assert "<CioObservabilityPanel" not in cio and "<CioScorecardStrip" not in cio
    assert "<CapitalPlanSection" not in cio
    assert "<AllocationPanel" not in portfolio
    assert "<W7Allocation" in portfolio and "<W7Lookthrough" in portfolio
    ownership = (ROOT / "docs/ops/CONTENT_OWNERSHIP.md").read_text()
    for route in ("/portfolio?tab=Look-through", "/watch?tab=sectors", "/strategy", "/rec-intel", "/reports", "/defense"):
        assert route in ownership
