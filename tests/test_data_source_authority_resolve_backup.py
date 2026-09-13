"""resolve_backup(domain): the registry's same-question chain, minus retired.

AGENTS.md §7A rule 5 — a backup answers the SAME question. A Finviz performance
column is not an analyst rating; a chain that would hand one over must raise,
not return. Rule 4 — a retired provider has zero call sites; a chain that
consults this helper never sees one.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import data_source_authority as dsa  # noqa: E402
from scripts.lib import retired_providers as rp  # noqa: E402


def _reg(domains: list[dict], providers: dict) -> dict:
    return {"schema": "DataSourceAuthority@v1", "domains": domains, "providers": providers}


# ── the live registry ────────────────────────────────────────────────────────


def test_web_search_backup_is_searxng_then_tavily():
    assert dsa.resolve_backup("web_search") == ["searxng", "tavily"]


def test_catalyst_news_backup_is_yahoo_then_the_search_chain():
    assert dsa.resolve_backup("catalyst_news") == ["yahoo", "brave", "searxng"]


def test_web_search_spill_reasons():
    assert dsa.spill_on("web_search") == frozenset({"DAILY_EXHAUSTED", "MONTHLY_EXHAUSTED", "HTTP_429"})


def test_no_live_domain_chain_contains_a_retired_provider():
    reg = dsa.registry()
    for d in reg["domains"]:
        for p in dsa.resolve_backup(d["domain"]):
            assert not rp.is_retired(p), (d["domain"], p)


def test_unknown_domain_raises():
    with pytest.raises(dsa.UnknownDomain):
        dsa.resolve_backup("no_such_domain")


# ── retired providers are dropped ────────────────────────────────────────────


def test_a_retired_provider_in_a_backup_list_is_dropped():
    reg = _reg(
        [{"domain": "web_search", "backup": ["polygon", "searxng", "tavily"]}],
        {"polygon": {"status": "retired", "supplies": ["web_search"]},
         "searxng": {"status": "active", "supplies": ["web_search"]},
         "tavily": {"status": "configured_unused", "supplies": ["web_search"]}},
    )
    assert dsa.resolve_backup("web_search", registry=reg) == ["searxng", "tavily"]


def test_a_provider_retired_in_the_live_registry_is_dropped_even_if_the_chain_forgets_to_say_so():
    """The injected registry does not mark fmp retired; scripts/lib/retired_providers does."""
    assert rp.is_retired("fmp")
    reg = _reg([{"domain": "dividends", "backup": ["fmp", "yfinance"]}],
               {"yfinance": {"status": "active", "supplies": ["dividends"]}})
    assert dsa.resolve_backup("dividends", registry=reg) == ["yfinance"]


def test_negative_control_an_active_provider_is_kept():
    reg = _reg([{"domain": "web_search", "backup": ["searxng"]}],
               {"searxng": {"status": "active", "supplies": ["web_search"]}})
    assert dsa.resolve_backup("web_search", registry=reg) == ["searxng"]


# ── same question, or refuse ─────────────────────────────────────────────────

_ANALYST = {"domain": "analyst_opinion", "answers": ["analyst_targets"], "backup": ["finviz"]}
_PROVIDERS = {
    "finviz": {"status": "active", "supplies": ["screeners", "sector_perf", "news"]},
    "yahoo": {"status": "active", "supplies": ["analyst_targets", "vix", "news_feed"]},
}


def test_a_cross_domain_substitution_raises():
    """Finviz supplies performance/screeners; it does not answer 'analyst_opinion'."""
    reg = _reg([_ANALYST], _PROVIDERS)
    with pytest.raises(dsa.CrossDomainSubstitution, match="cross-domain"):
        dsa.resolve_backup("analyst_opinion", registry=reg)


def test_positive_control_a_same_question_backup_resolves():
    reg = _reg([dict(_ANALYST, backup=["yahoo"])], _PROVIDERS)
    assert dsa.resolve_backup("analyst_opinion", registry=reg) == ["yahoo"]


def test_a_retired_cross_domain_provider_is_dropped_before_it_can_raise():
    reg = _reg([_ANALYST], dict(_PROVIDERS, finviz={"status": "retired", "supplies": ["screeners"]}))
    assert dsa.resolve_backup("analyst_opinion", registry=reg) == []


def test_a_domain_without_answers_takes_the_registry_declaration_as_the_decision():
    """Until the registry declares `answers` for a domain there is nothing to
    compare against; the declared list stands (the gate polices the registry)."""
    reg = _reg([{"domain": "analyst_opinion", "backup": ["finviz"]}], _PROVIDERS)
    assert dsa.resolve_backup("analyst_opinion", registry=reg) == ["finviz"]


def test_with_the_proposed_phase5_patch_the_live_chains_still_resolve():
    """docs/implementation/sot/phase5_registry_patch.json adds `answers`; applying it
    to a copy of the live registry must not break web_search or catalyst_news."""
    patch = json.loads((ROOT / "docs" / "implementation" / "sot" / "phase5_registry_patch.json").read_text())
    reg = json.loads(json.dumps(dsa.registry()))
    by_name = {d["domain"]: d for d in reg["domains"]}
    for op in patch["ops"]:
        if op["op"] == "set_domain_field":
            by_name[op["domain"]][op["field"]] = op["value"]
        elif op["op"] == "set_provider_field":
            reg["providers"][op["provider"]][op["field"]] = op["value"]
    assert dsa.resolve_backup("web_search", registry=reg) == ["searxng", "tavily"]
    assert dsa.resolve_backup("catalyst_news", registry=reg) == ["yahoo", "brave", "searxng"]
    assert dsa.resolve_backup("analyst_opinion", registry=reg) == ["yfinance_on_demand"]


# ── budgets ──────────────────────────────────────────────────────────────────


def test_provider_budget_reads_only_declared_keys():
    assert dsa.provider_budget("brave") == {"daily": 120, "monthly": 1500}
    assert dsa.provider_budget("searxng") == {"daily": 10000}
    assert dsa.provider_budget("not_a_provider") == {}
    reg = _reg([], {"x": {"budget": {"daily": "12", "monthly": "abc"}}})
    assert dsa.provider_budget("x", registry=reg) == {"daily": 12}
