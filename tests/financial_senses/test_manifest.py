"""Provider manifest completeness tests.

The manifest (`scripts/lib/financial_senses/manifest.py`) is the future gateway
registration contract. Every first-class provider and its read-only capabilities
must be present, so a new provider or capability cannot drift out of the
registration contract without a failing test.
"""
from __future__ import annotations

from financial_senses.manifest import TOOLS, provider_names, tool_names

from financial_senses.sec_provider import SecEdgarProvider
from financial_senses.macro_provider import FredAlfredProvider
from financial_senses.identity import OpenFigiProvider
from financial_senses.stress_engine import PortfolioStressProvider
from financial_senses.factor_exposure import FactorOverlapProvider
from financial_senses.evidence_graph import ClaimEvidenceProvider
from financial_senses.critic import IndependentCriticProvider

# The intended, registerable first-class providers in this branch. A provider
# in this list that is NOT meant to be gateway-registerable should be removed
# here AND explicitly documented as an exclusion (with a test) instead.
ALL_REGISTERABLE_PROVIDERS = [
    SecEdgarProvider(),
    FredAlfredProvider(api_key=None),
    OpenFigiProvider(),
    PortfolioStressProvider(),
    FactorOverlapProvider(),
    ClaimEvidenceProvider(),
    IndependentCriticProvider(),
]


def test_manifest_covers_every_provider_and_capability():
    for p in ALL_REGISTERABLE_PROVIDERS:
        assert p.name in TOOLS, f"provider {p.name!r} missing from manifest"
        registered = set(tool_names(p.name))
        for c in p.capabilities():
            assert c.name in registered, (
                f"capability {c.name!r} of provider {p.name!r} missing from manifest"
            )


def test_manifest_provider_names_match_registered_set():
    registered = set(provider_names())
    expected = {p.name for p in ALL_REGISTERABLE_PROVIDERS}
    assert registered == expected, (
        f"manifest providers {sorted(registered)} != intended {sorted(expected)}"
    )


def test_manifest_tools_are_read_only():
    for provider, entry in TOOLS.items():
        for t in entry["tools"]:
            assert t["mutability"] == "READ_ONLY", (
                f"{provider}.{t['name']} is not READ_ONLY"
            )
