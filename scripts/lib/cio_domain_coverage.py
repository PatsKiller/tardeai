"""Institutional evidence-domain coverage matrix.

Maps the 20 institutionally-required evidence domains (Phase 2 constitution) to
the canonical CIO domain capability registry (`config/cio_domain_capability_registry.json`)
and reports, per required domain, which registry domains back it and whether each
backing adapter is SUPPORTED / UNSUPPORTED / BROKEN.

This is the machine-readable companion to
docs/investment-office/EVIDENCE_AND_PROVENANCE.md. It is provider-call-free and
read-only: it only reads the static registry JSON and reports declared state; it
does not claim any domain is *actually* fresh at runtime (freshness is a
collection-time property, reported by CIOFinancialSnapshot / EvidenceRef).

Purpose: give Alex (CIO) a deterministic answer to "which facts can I stand
behind, and which are currently unsourced?" before synthesis.
"""
from __future__ import annotations

from typing import Any

from scripts.lib.cio_domain_registry import CIODomainRegistry

# Required institutional evidence domains (Phase 2). Each maps to one or more
# registry domain_ids. These are the 20 "at minimum" domains from the
# Investment Office constitution.
REQUIRED_INSTITUTIONAL_DOMAINS: dict[str, list[str]] = {
    "holdings_and_accounts": ["portfolio", "holdings_detail", "account_constraints", "transactions"],
    "cash_investable_reserved": ["cash_buying_power", "liquidity"],
    "tax_lots_cost_basis": ["tax_lots", "cost_basis"],
    "broker_reconciliation": ["broker_reconciliation"],
    "portfolio_performance": ["performance"],
    "benchmark": [],  # NOT declared in the registry — explicit gap
    "risk_concentration_protection": ["risk", "defense_stops_protection"],
    "watch_intelligence": ["watch_intelligence"],
    "defense": ["defense_stops_protection"],
    "rotation_sectors_industries": ["rotation", "sectors", "market_regime", "industry_context"],
    "reentry": ["reentry"],
    "analyst_actions": ["analyst_actions"],
    "fundamentals_valuation": ["fundamentals"],
    "technicals_price_action": ["technicals"],
    "catalysts_earnings_events": ["catalysts"],
    "hermes_research": ["hermes_research"],
    "income_dividends": ["income"],
    "model_portfolio_policy": ["model_portfolio", "investment_policy"],
    "cfo_liquidity_constraints": ["liquidity", "cash_buying_power"],
    "cwo_wealth_goals": ["goals", "retirement", "operator_profile"],
}


def _state_for(registry: CIODomainRegistry, domain_id: str) -> str:
    if not registry.has(domain_id):
        return "NOT_DECLARED"
    return registry.get(domain_id).adapter_state


def domain_coverage_report(
    registry: CIODomainRegistry | None = None,
) -> dict[str, Any]:
    """Produce the required-domain coverage matrix from the registry.

    Each required domain resolves to an overall state:
      SUPPORTED     — every backing registry domain has adapter_state SUPPORTED
      PARTIAL       — some SUPPORTED, some UNSUPPORTED backing domains
      BROKEN        — at least one backing domain is BROKEN (produces wrong data)
      UNSUPPORTED   — backing domains exist but none are SUPPORTED or BROKEN
      NOT_DECLARED  — no backing registry domain exists at all

    Returns a report with per-domain detail + roll-up counts.
    """
    if registry is None:
        registry = CIODomainRegistry.load()

    detail: dict[str, Any] = {}
    counts = {
        "SUPPORTED": 0,
        "PARTIAL": 0,
        "BROKEN": 0,
        "UNSUPPORTED": 0,
        "NOT_DECLARED": 0,
    }

    for required, backing_ids in REQUIRED_INSTITUTIONAL_DOMAINS.items():
        rows = []
        states: list[str] = []
        for d in backing_ids:
            st = _state_for(registry, d)
            states.append(st)
            rows.append({
                "domain_id": d,
                "adapter_state": st,
                "canonical_source": registry.get(d).canonical_source if registry.has(d) else None,
            })

        if not backing_ids:
            overall = "NOT_DECLARED"
        elif "BROKEN" in states:
            overall = "BROKEN"
        elif all(s == "SUPPORTED" for s in states):
            overall = "SUPPORTED"
        elif any(s == "SUPPORTED" for s in states):
            overall = "PARTIAL"
        else:
            overall = "UNSUPPORTED"  # all UNSUPPORTED

        counts[overall] = counts.get(overall, 0) + 1
        detail[required] = {
            "overall_state": overall,
            "backing_domains": rows,
        }

    total = len(REQUIRED_INSTITUTIONAL_DOMAINS)
    return {
        "schema": "institutional-evidence-domains-v1",
        "registry_version": registry.registry_version,
        "required_domain_count": total,
        "counts": counts,
        "coverage_pct": round(counts["SUPPORTED"] / total * 100, 1),
        "detail": detail,
    }


def undeclared_required_domains(registry: CIODomainRegistry | None = None) -> list[str]:
    """Return the required domains with no registry backing (hard gaps)."""
    report = domain_coverage_report(registry)
    return [
        name for name, d in report["detail"].items()
        if d["overall_state"] == "NOT_DECLARED"
    ]
