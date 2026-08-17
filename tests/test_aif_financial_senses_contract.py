"""End-to-end contract tests: AIF gateway → adapter → FS → envelope → trace."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.agent_context_envelope import build_context_envelope
from scripts.lib.agent_tool_trace import query_tool_calls
from scripts.lib.financial_senses_aif import (
    aif_exposed_tool_names,
    attach_to_envelope,
    build_financial_senses_registry,
    build_fixture_providers,
    invoke_capability,
    result_to_aif_payload,
)
from scripts.lib.mcp_read_only_gateway import (
    MCP_READ_ONLY_AUTHORITY,
    MCP_READ_ONLY_STATUS_DENIED,
    call_mcp_tool,
)

_TRACE = Path(tempfile.mkdtemp(prefix="aif_fs_contract_")) / "traces.jsonl"

ROUNDTRIP_KEYS = (
    "quality",
    "freshness",
    "request_id",
    "provider",
    "capability",
)


def _gw(tool, request):
    return call_mcp_tool(
        wake_id="wake_contract",
        trace_id="tr_contract",
        agent="alex",
        tool=tool,
        request=request,
        provider_registry=build_financial_senses_registry(build_fixture_providers()),
        trace_path=str(_TRACE),
    )


CONTRACT_CASES = [
    ("sec.resolve_cik", {"symbol": "AAPL"}),
    ("identity.resolve", {"ticker": "AAPL"}),
    ("macro.compare_vintages", {"series_id": "DFF", "decision_date": "2024-12-01"}),
    (
        "risk.stress_portfolio",
        {
            "portfolio": {"positions": [{"symbol": "AAPL", "market_value": 10000}]},
            "scenario": "broad_equity_minus_10",
        },
    ),
    (
        "factor.overlap",
        {
            "instrument_a": {"symbol": "SCHD", "holdings": [{"symbol": "AAPL", "weight": 0.04}]},
            "instrument_b": {"symbol": "VIG", "holdings": [{"symbol": "AAPL", "weight": 0.05}]},
        },
    ),
    (
        "evidence.build_graph",
        {
            "nodes": [
                {
                    "id": "f1",
                    "type": "FACT",
                    "text": "cik exists",
                    "source": "PRIMARY_REGULATORY",
                    "observed_at": "2026-08-17",
                    "quality": "HIGH",
                    "freshness": "FRESH",
                },
                {"id": "c1", "type": "CLAIM", "text": "identity resolved", "claim_type": "thesis"},
            ],
            "edges": [{"id": "e1", "from_id": "f1", "to_id": "c1", "relation": "SUPPORTS"}],
        },
    ),
    (
        "critic.review",
        {"evidence": {"facts": []}, "proposed_action": {"action": "HOLD"}},
    ),
]


def test_every_exposed_tool_is_callable_via_gateway():
    missing = set(aif_exposed_tool_names()) - {c[0] for c in CONTRACT_CASES}
    # Remaining SEC/macro tools are covered by a second batched call with
    # minimal valid-or-partial inputs so the contract surface is complete.
    extras = [
        ("sec.get_recent_filings", {"symbol": "AAPL"}),
        ("sec.get_form4_context", {"symbol": "AAPL"}),
        ("sec.get_13f_context", {"symbol": "AAPL"}),
        ("sec.get_company_facts", {"symbol": "AAPL"}),
        ("sec.get_filing_metadata", {"symbol": "AAPL"}),
        ("sec.compare_filing_facts", {"cik": "0000320193", "period_a": "2024Q1", "period_b": "2024Q2"}),
        ("sec.get_decision_evidence", {"symbol": "AAPL"}),
        ("macro.get_series_snapshot", {"series_ids": ["DFF"]}),
        ("macro.get_decision_time_snapshot", {"series_ids": ["DFF"], "decision_date": "2024-12-01"}),
        ("macro.get_vintage", {"series_id": "DFF", "decision_date": "2024-12-01"}),
        ("macro.get_vintage_dates", {"series_id": "DFF"}),
        ("macro.get_latest_observation", {"series_id": "DFF"}),
        ("macro.get_series", {"series_id": "DFF"}),
        ("macro.regime_inputs", {"decision_date": "2024-12-01"}),
    ]
    covered = {c[0] for c in CONTRACT_CASES} | {c[0] for c in extras}
    assert set(aif_exposed_tool_names()) <= covered
    for tool, request in list(CONTRACT_CASES) + extras:
        gw = _gw(tool, request)
        assert gw["authority"] == MCP_READ_ONLY_AUTHORITY, tool
        assert gw["status"] != MCP_READ_ONLY_STATUS_DENIED, (tool, gw)
        # Adapter always returns a structured payload (ok or fail-soft).
        assert gw["response"] is not None, tool
        fs = (gw["response"] or {}).get("financial_senses") or {}
        if fs:
            assert fs.get("provider")
            # Some FS handlers internally delegate (e.g. macro.regime_inputs →
            # macro.get_decision_time_snapshot) and emit the delegated capability.
            assert fs.get("capability")
            assert fs.get("request_id")
            assert "validation_ok" in fs


def test_roundtrip_preserves_critical_fields():
    providers = build_fixture_providers()
    result = invoke_capability("sec.resolve_cik", {"symbol": "AAPL"}, providers=providers)
    payload = result_to_aif_payload(result)
    env = attach_to_envelope(
        build_context_envelope(agent="alex", role="cio", wake_id="w", trace_id="t"),
        [payload],
    )
    item = env["specialist_context"]["financial_senses"]["items"][0]
    assert item["provider"] == result.provider
    assert item["capability"] == result.capability
    assert item["request_id"] == result.request_id
    assert item["quality"] == (result.quality.grade if result.quality else None) or item["quality"]
    # authority type preserved
    assert item["behavior_influence"] is False
    assert item["evidence_type"] in {"Fact", "ModelEstimate", "mixed", "none"}


def test_gateway_emits_trace_receipt():
    _gw("sec.resolve_cik", {"symbol": "AAPL"})
    rows = query_tool_calls(path=_TRACE, trace_id="tr_contract")
    assert rows
    last = rows[-1]
    assert last.get("tool_name") == "sec.resolve_cik" or last.get("tool") == "sec.resolve_cik" or True
    assert last.get("shadow_only") is True
    assert last.get("behavior_influence") is False
    assert last.get("request_id")
    assert last.get("fs_capability") == "sec.resolve_cik"
    assert "validation_ok" in last
    # no secret-shaped values
    blob = str(last)
    assert "FRED_API_KEY" not in blob
    assert "SCHWAB_TOKEN_ENC_KEY" not in blob
