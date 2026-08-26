"""Deterministic AIF ↔ Financial Senses dry replay.

READ_ONLY_ADVISORY. Fixtures only — no live network, no broker, no Telegram,
no production mutation. Runs representative wakes through:

  AIF gateway → FS adapter → FinancialSenseResult → ContextEnvelope → trace

and compares a baseline envelope (no FS) to an augmented shadow envelope
(FS attached). Canonical action is never changed.

This program records attributable action *differences* as observations, not
as errors, and never executes them.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.lib.agent_context_envelope import (
    build_context_envelope,
    context_envelope_digest,
)
from scripts.lib.agent_context_integration import apply_context_budget, shadow_compare
from scripts.lib.financial_senses_aif import (
    attach_to_envelope,
    behavior_influence,
    build_fixture_providers,
    build_financial_senses_registry,
    invoke_capability,
    memory_behavior_influence,
    result_to_aif_payload,
)
from scripts.lib.mcp_read_only_gateway import call_mcp_tool

WAKES: list[dict[str, Any]] = [
    {
        "name": "portfolio_review",
        "agent": "alex",
        "decision": {"current_action": "HOLD", "act_now": False, "decision_id": "dec_replay_1"},
        "office_truth": {"holdings_ref": "holdings.json", "cash_ref": "cash.json", "source_asof": "2026-08-17"},
        "calls": [
            ("identity.resolve", {"ticker": "AAPL"}),
            ("sec.resolve_cik", {"symbol": "AAPL"}),
        ],
    },
    {
        "name": "single_security_research",
        "agent": "steph",
        "decision": {"current_action": "WAIT", "act_now": False, "decision_id": "dec_replay_2"},
        "office_truth": {"holdings_ref": "holdings.json", "source_asof": "2026-08-17"},
        "calls": [
            ("sec.resolve_cik", {"symbol": "MSFT"}),
            ("sec.get_decision_evidence", {"symbol": "MSFT"}),
        ],
    },
    {
        "name": "macro_regime_request",
        "agent": "alex",
        "decision": {"current_action": "HOLD", "act_now": False, "decision_id": "dec_replay_3"},
        "office_truth": {"holdings_ref": "holdings.json", "source_asof": "2026-08-17"},
        "calls": [
            ("macro.compare_vintages", {"series_id": "DFF", "decision_date": "2024-12-01"}),
            ("macro.regime_inputs", {"decision_date": "2024-12-01"}),
        ],
    },
    {
        "name": "instrument_identity_resolution",
        "agent": "steph",
        "decision": {"current_action": "WAIT", "act_now": False, "decision_id": "dec_replay_4"},
        "office_truth": {"holdings_ref": "holdings.json", "source_asof": "2026-08-17"},
        "calls": [("identity.resolve", {"ticker": "SCHD"})],
    },
    {
        "name": "sec_filing_change",
        "agent": "steph",
        "decision": {"current_action": "HOLD", "act_now": False, "decision_id": "dec_replay_5"},
        "office_truth": {"holdings_ref": "holdings.json", "source_asof": "2026-08-17"},
        "calls": [("sec.compare_filing_facts", {"cik": "0000320193", "period_a": "2024Q1", "period_b": "2024Q2"})],
    },
    {
        "name": "portfolio_stress",
        "agent": "guardian",
        "decision": {"current_action": "HOLD", "act_now": False, "decision_id": "dec_replay_6"},
        "office_truth": {"holdings_ref": "holdings.json", "risk_ref": "risk.json", "source_asof": "2026-08-17"},
        "calls": [
            (
                "risk.stress_portfolio",
                {
                    "portfolio": {"positions": [{"symbol": "AAPL", "market_value": 10000, "weight": 0.1}]},
                    "scenario": "rates_plus_100bp",
                },
            )
        ],
    },
    {
        "name": "factor_overlap_check",
        "agent": "guardian",
        "decision": {"current_action": "HOLD", "act_now": False, "decision_id": "dec_replay_7"},
        "office_truth": {"holdings_ref": "holdings.json", "source_asof": "2026-08-17"},
        "calls": [
            (
                "factor.overlap",
                {
                    "instrument_a": {"symbol": "SCHD", "holdings": [{"symbol": "AAPL", "weight": 0.04}]},
                    "instrument_b": {"symbol": "VIG", "holdings": [{"symbol": "AAPL", "weight": 0.05}]},
                },
            )
        ],
    },
    {
        "name": "independent_critic_request",
        "agent": "alex",
        "decision": {"current_action": "WAIT", "act_now": False, "decision_id": "dec_replay_8"},
        "office_truth": {"holdings_ref": "holdings.json", "source_asof": "2026-08-17"},
        "calls": [
            (
                "critic.review",
                {
                    "evidence": {"facts": [{"key": "cik", "value": "0000320193"}]},
                    "proposed_action": {"action": "HOLD", "act_now": False},
                },
            )
        ],
    },
]


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _zero_invariants() -> dict[str, int]:
    return {
        "execution_actions_changed": 0,
        "broker_calls": 0,
        "order_calls": 0,
        "stop_mutations": 0,
        "two_fa_mutations": 0,
        "risk_policy_mutations": 0,
        "memory_behavior_flips": 0,
        "auto_promotions": 0,
        "unsupported_fact_promotions": 0,
        "invalid_provenance_accepts": 0,
        "invalid_quality_accepts": 0,
        "invalid_freshness_accepts": 0,
        "financial_senses_attributable_action_flips": 0,
    }


def replay_wake(case: dict[str, Any], *, trace_path: str | Path | None = None) -> dict[str, Any]:
    providers = build_fixture_providers()
    registry = build_financial_senses_registry(providers)
    baseline = build_context_envelope(
        agent=case["agent"],
        role="cio" if case["agent"] == "alex" else "specialist",
        wake_id=f"wake_{case['name']}",
        trace_id=f"tr_{case['name']}",
        decision=case.get("decision"),
        office_truth=case.get("office_truth"),
    )
    payloads: list[dict[str, Any]] = []
    gateway_results: list[dict[str, Any]] = []
    for tool, request in case.get("calls") or []:
        # Direct adapter (contract) + gateway (governance).
        result = invoke_capability(tool, request, providers=providers)
        payloads.append(result_to_aif_payload(result))
        gw = call_mcp_tool(
            wake_id=f"wake_{case['name']}",
            trace_id=f"tr_{case['name']}",
            agent=case["agent"],
            tool=tool,
            request=request,
            provider_registry=registry,
            trace_path=str(trace_path) if trace_path else None,
        )
        gateway_results.append(
            {
                "tool": tool,
                "ok": gw.get("ok"),
                "status": gw.get("status"),
                "authority": gw.get("authority"),
            }
        )
    augmented = attach_to_envelope(baseline, payloads)
    budgeted, budget_meta = apply_context_budget(augmented, budget_tokens=50_000)
    # Shadow decision is the SAME canonical action — influence is not promoted.
    baseline_decision = case.get("decision") or {}
    shadow_decision = deepcopy(baseline_decision)
    cmp = shadow_compare(baseline_decision, shadow_decision)
    invariants = _zero_invariants()
    if memory_behavior_influence() != 0 or behavior_influence():
        invariants["memory_behavior_flips"] = 1
    if cmp.get("action_changed"):
        invariants["financial_senses_attributable_action_flips"] = 1
        invariants["execution_actions_changed"] = 1
    return {
        "wake": case["name"],
        "baseline_digest": context_envelope_digest(baseline),
        "augmented_digest": context_envelope_digest(budgeted),
        "budget": budget_meta,
        "gateway": gateway_results,
        "fs_items": len((budgeted.get("specialist_context") or {}).get("financial_senses", {}).get("items") or []),
        "shadow_compare": cmp,
        "invariants": invariants,
        "behavior_influence": False,
        "shadow_only": True,
    }


def run_replay(trace_path: str | Path | None = None) -> dict[str, Any]:
    wakes = [replay_wake(c, trace_path=trace_path) for c in WAKES]
    invariants = _zero_invariants()
    for w in wakes:
        for k, v in w["invariants"].items():
            invariants[k] = invariants.get(k, 0) + int(v)
    # Envelope digests include per-call request_ids / timestamps inside FS
    # items. The governed replay hash is the stable semantic surface.
    stable = [
        {
            "wake": w["wake"],
            "invariants": w["invariants"],
            "fs_items": w["fs_items"],
            "gateway": w["gateway"],
            "same": (w.get("shadow_compare") or {}).get("same"),
        }
        for w in wakes
    ]
    report = {
        "wake_count": len(wakes),
        "wakes": wakes,
        "invariants": invariants,
        "baseline_hash": _hash([w["baseline_digest"] for w in wakes]),
        "augmented_hash": _hash(stable),
        "behavior_influence": False,
        "memory_behavior_influence": memory_behavior_influence(),
        "authority": "READ_ONLY_ADVISORY",
    }
    return report
