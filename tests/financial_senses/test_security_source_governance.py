"""Security and source-governance tests.

No provider exposes arbitrary URL fetch, shell, filesystem write, SQL write, or
broker/order/stop authority. Source classes are enforced and MODEL_INFERENCE
can never be promoted to FACT.
"""
from __future__ import annotations

import pytest

from financial_senses.source_governance import (
    SOURCE_MEMORY_CONTEXT,
    SOURCE_MODEL_INFERENCE,
    SOURCE_PRIMARY_GOVERNMENT,
    SOURCE_PRIMARY_REGULATORY,
    SOURCE_SECONDARY_RESEARCH,
    assert_no_inference_as_fact,
    best_source,
    can_back_fact,
    grade_for_source,
    validate_source_type,
)
from financial_senses.sec_provider import SecEdgarProvider
from financial_senses.macro_provider import FredAlfredProvider
from financial_senses.identity import OpenFigiProvider
from financial_senses.stress_engine import PortfolioStressProvider
from financial_senses.evidence_graph import ClaimEvidenceProvider
from financial_senses.critic import IndependentCriticProvider


ALL_PROVIDERS = [
    SecEdgarProvider(configured=False),
    FredAlfredProvider(api_key=None),
    OpenFigiProvider(),
    PortfolioStressProvider(),
    ClaimEvidenceProvider(),
    IndependentCriticProvider(),
]

FORBIDDEN_METHODS = [
    "write",
    "execute",
    "exec_sql",
    "shell",
    "system",
    "send_telegram",
    "place_order",
    "cancel_order",
    "set_stop",
    "mutate",
    "delete",
]


def test_validate_source_type():
    assert validate_source_type(SOURCE_PRIMARY_REGULATORY) is None
    assert validate_source_type("NOT_REAL") is not None
    assert validate_source_type(None) is not None


def test_model_inference_cannot_back_fact():
    assert not can_back_fact(SOURCE_MODEL_INFERENCE)
    assert not can_back_fact(SOURCE_MEMORY_CONTEXT)
    assert can_back_fact(SOURCE_PRIMARY_REGULATORY)
    assert assert_no_inference_as_fact(SOURCE_MODEL_INFERENCE) is not None


def test_grade_for_source():
    assert grade_for_source(SOURCE_PRIMARY_REGULATORY) == "HIGH"
    assert grade_for_source(SOURCE_SECONDARY_RESEARCH) == "LOW"
    assert grade_for_source(SOURCE_MODEL_INFERENCE) == "UNKNOWN"


def test_best_source_orders_by_claim_type():
    best = best_source(
        [SOURCE_MODEL_INFERENCE, SOURCE_PRIMARY_REGULATORY, SOURCE_MEMORY_CONTEXT],
        "company_filing_fact",
    )
    assert best == SOURCE_PRIMARY_REGULATORY


def test_all_capabilities_are_read_only():
    for p in ALL_PROVIDERS:
        for c in p.capabilities():
            assert c.mutability == "READ_ONLY", f"{p.name}.{c.name} is not READ_ONLY"


def test_no_provider_exposes_forbidden_surface():
    for p in ALL_PROVIDERS:
        for m in FORBIDDEN_METHODS:
            assert not hasattr(p, m), f"{p.name} exposes forbidden method {m}()"


def test_no_arbitrary_url_fetch_capability():
    for p in ALL_PROVIDERS:
        for c in p.capabilities():
            assert "url" not in c.name.lower()
            assert c.input_schema.get("url") is None


def test_provider_query_is_not_a_write_path():
    # Querying a read-only provider must never mutate the provider's own state.
    p = SecEdgarProvider(
        conn_factory=lambda: None,
        cik_resolver=lambda s: "0000320193",
        fetcher=lambda url: {"filings": {"recent": {}}},
    )
    before = p.capabilities()
    p.query("sec.resolve_cik", {"symbol": "AAPL"})
    assert p.capabilities() == before
