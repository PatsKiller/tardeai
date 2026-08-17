"""Provider manifest — the registration contract for the future MCP gateway.

This module describes each provider tool in a gateway-neutral way so the Agent
Intelligence Foundation's central MCP gateway can later import/register these
read-only tools. It does NOT implement a gateway, MCP server, or transport.
"""
from __future__ import annotations

from typing import Any

MUTABILITY_READ_ONLY = "READ_ONLY"

# Each tool entry: name, mutability, input/output schemas, source policy,
# timeout, rate limit, and expected trace metadata.
TOOLS: dict[str, dict[str, Any]] = {
    "sec_edgar": {
        "tools": [
            {
                "name": "sec.resolve_cik",
                "mutability": MUTABILITY_READ_ONLY,
                "description": "Resolve a ticker to its SEC CIK using the canonical mapping.",
                "input_schema": {"symbol": "string"},
                "output_schema": {"cik": "string|null"},
                "source_policy": "PRIMARY_REGULATORY",
                "timeout_seconds": 15.0,
                "rate_limit": "10/sec",
            },
            {
                "name": "sec.get_recent_filings",
                "mutability": MUTABILITY_READ_ONLY,
                "description": "Recent EDGAR submissions for a CIK/symbol.",
                "input_schema": {"symbol": "string", "form": "string?", "limit": "int?"},
                "output_schema": {"filings": "array"},
                "source_policy": "PRIMARY_REGULATORY",
            },
            {
                "name": "sec.get_form4_context",
                "mutability": MUTABILITY_READ_ONLY,
                "description": "Recent insider (Form 4) context from the canonical store.",
                "input_schema": {"symbol": "string", "limit": "int?"},
                "output_schema": {"rows": "array"},
                "source_policy": "PRIMARY_REGULATORY",
            },
            {
                "name": "sec.get_13f_context",
                "mutability": MUTABILITY_READ_ONLY,
                "description": "Recent institutional (13F) holdings context.",
                "input_schema": {"symbol": "string", "limit": "int?"},
                "output_schema": {"rows": "array"},
                "source_policy": "PRIMARY_REGULATORY",
            },
            {
                "name": "sec.get_company_facts",
                "mutability": MUTABILITY_READ_ONLY,
                "description": "Company facts / XBRL concepts for a CIK.",
                "input_schema": {"symbol": "string?", "cik": "string?"},
                "output_schema": {"facts": "array"},
                "source_policy": "PRIMARY_REGULATORY",
            },
            {
                "name": "sec.get_filing_metadata",
                "mutability": MUTABILITY_READ_ONLY,
                "description": "Filing metadata for a CIK/symbol.",
                "input_schema": {"symbol": "string?", "cik": "string?"},
                "output_schema": {"filings": "array"},
                "source_policy": "PRIMARY_REGULATORY",
            },
            {
                "name": "sec.compare_filing_facts",
                "mutability": MUTABILITY_READ_ONLY,
                "description": "Deterministic comparison of company facts across two periods.",
                "input_schema": {"cik": "string", "period_a": "string", "period_b": "string"},
                "output_schema": {"changed_facts": "object"},
                "source_policy": "PRIMARY_REGULATORY",
            },
            {
                "name": "sec.get_decision_evidence",
                "mutability": MUTABILITY_READ_ONLY,
                "description": "Assemble provenance-bound SEC evidence for a decision subject.",
                "input_schema": {"symbol": "string"},
                "output_schema": {"evidence": "object"},
                "source_policy": "PRIMARY_REGULATORY",
            },
        ]
    },
    "macro": {
        "tools": [
            {"name": "macro.get_series_snapshot", "mutability": MUTABILITY_READ_ONLY},
            {"name": "macro.get_decision_time_snapshot", "mutability": MUTABILITY_READ_ONLY},
        ]
    },
    "identity": {
        "tools": [
            {"name": "identity.resolve", "mutability": MUTABILITY_READ_ONLY},
        ]
    },
    "stress": {
        "tools": [
            {"name": "risk.stress_portfolio", "mutability": MUTABILITY_READ_ONLY},
        ]
    },
    "evidence": {
        "tools": [
            {"name": "evidence.build_graph", "mutability": MUTABILITY_READ_ONLY},
        ]
    },
}


def provider_names() -> list[str]:
    return list(TOOLS.keys())


def tool_names(provider: str) -> list[str]:
    return [t["name"] for t in TOOLS.get(provider, {}).get("tools", [])]


def render_registration_manifest() -> dict:
    """Render the full provider manifest for the future gateway."""
    return {
        "version": "1.0",
        "providers": TOOLS,
        "authority": "READ_ONLY_ADVISORY",
        "trace_metadata_expected": ["request_id", "provider", "capability", "as_of", "observed_at"],
    }
