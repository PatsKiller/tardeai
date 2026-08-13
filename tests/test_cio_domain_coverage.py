"""Dry tests for the institutional evidence-domain coverage matrix."""
from __future__ import annotations

from scripts.lib.cio_domain_coverage import (
    REQUIRED_INSTITUTIONAL_DOMAINS,
    domain_coverage_report,
    undeclared_required_domains,
)
from scripts.lib.cio_domain_registry import CIODomainRegistry


def _registry():
    return CIODomainRegistry.load()


def test_required_domains_cover_constitution():
    # The 20 institutionally-required domains from the Phase 2 constitution.
    assert len(REQUIRED_INSTITUTIONAL_DOMAINS) == 20
    assert "benchmark" in REQUIRED_INSTITUTIONAL_DOMAINS
    assert "cfo_liquidity_constraints" in REQUIRED_INSTITUTIONAL_DOMAINS
    assert "cwo_wealth_goals" in REQUIRED_INSTITUTIONAL_DOMAINS


def test_coverage_report_has_all_required_domains():
    report = domain_coverage_report(_registry())
    assert report["required_domain_count"] == 20
    assert set(report["detail"].keys()) == set(REQUIRED_INSTITUTIONAL_DOMAINS.keys())


def test_coverage_report_counts_sum_to_total():
    report = domain_coverage_report(_registry())
    assert sum(report["counts"].values()) == 20


def test_benchmark_is_undeclared_gap():
    report = domain_coverage_report(_registry())
    assert report["detail"]["benchmark"]["overall_state"] == "NOT_DECLARED"


def test_core_account_state_domains_are_supported():
    report = domain_coverage_report(_registry())
    # cash (cash_buying_power + liquidity) and broker_reconciliation are SUPPORTED.
    assert report["detail"]["cash_investable_reserved"]["overall_state"] == "SUPPORTED"
    assert report["detail"]["broker_reconciliation"]["overall_state"] == "SUPPORTED"


def test_partial_domains_mix_supported_and_unsupported():
    report = domain_coverage_report(_registry())
    # holdings_and_accounts: portfolio/holdings_detail/transactions SUPPORTED,
    # account_constraints UNSUPPORTED.
    assert report["detail"]["holdings_and_accounts"]["overall_state"] == "PARTIAL"


def test_undeclared_reports_benchmark_only():
    undeclared = undeclared_required_domains(_registry())
    assert "benchmark" in undeclared


def test_rotation_is_broken_in_registry():
    reg = _registry()
    assert reg.get("rotation").adapter_state == "BROKEN"
