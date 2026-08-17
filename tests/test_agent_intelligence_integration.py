"""Phase 10 — End-to-end integration chain (deterministic, no network).

Walks the full READ_ONLY_ADVISORY chain with fixed fixtures and asserts that
authority stays READ_ONLY_ADVISORY and no write capability ever appears:

  canonical truth -> ContextEnvelope -> validate -> specialist sub-envelope ->
  MCP read call -> trace -> memory retrieval -> context budget -> operator
  feedback -> memory candidate -> decision -> notification suppression ->
  follow-up -> case -> outcome -> reflection -> memory proposal.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.agent_context_envelope import (  # noqa: E402
    AUTHORITY_READ_ONLY_ADVISORY,
    RETRIEVAL_OK,
    get_context_for_agent,
    validate_context_envelope,
)
from scripts.lib.agent_context_integration import (  # noqa: E402
    apply_context_budget,
    build_specialist_sub_envelope,
)
from scripts.lib.agent_followup import (  # noqa: E402
    build_durable_next_review,
    validate_durable_next_review,
)
from scripts.lib.agent_learning_linkage import (  # noqa: E402
    FEEDBACK_CLASS,
    build_lineage,
    classify_feedback_vs_outcome,
    is_measured_outcome,
    lineage_digest,
    propose_memory_write,
)
from scripts.lib.agent_memory_governance import (  # noqa: E402
    MEMORY_TYPE_OPERATOR_EXPLICIT_PREFERENCE,
    STATUS_ACTIVE,
    build_memory_record,
    retrieve_for_context,
)
from scripts.lib.agent_memory_provider import LocalTestMemoryProvider  # noqa: E402
from scripts.lib.agent_notification_intelligence import (  # noqa: E402
    dedupe_identity,
    evaluate_notification,
)
from scripts.lib.agent_run_trace import build_trace, validate_trace  # noqa: E402
from scripts.lib.cio_decision_semantics import (  # noqa: E402
    canonical_act_now,
    decision_content_digest,
    make_decision_id,
)
from scripts.lib.mcp_provider_adapters import build_local_provider_registry  # noqa: E402
from scripts.lib.mcp_read_only_gateway import (  # noqa: E402
    MCP_READ_ONLY_STATUS_OK,
    call_mcp_tool,
)

_TRACE_DIR = Path(tempfile.mkdtemp(prefix="agent_intel_integration_"))

_FORBIDDEN_CAPABILITIES = {
    "broker", "order", "trade", "write", "stop", "2fa", "risk_policy",
    "place", "cancel", "submit", "mutate",
}


class _HealthyMemory:
    """Duck-typed provider matching the get_context_for_agent contract."""

    name = "TestMemory"

    def health(self):
        return True

    def search(self, query=None, symbols=None, plan_id=None):
        return {
            "records": [{"memory_id": "m1", "content": "operator prefers SCHD as income anchor"}],
            "conflicts": [],
        }


def _assert_read_only_authority(governance) -> None:
    assert isinstance(governance, dict)
    assert governance.get("authority") == AUTHORITY_READ_ONLY_ADVISORY
    permitted = governance.get("permitted_capabilities") or []
    for cap in permitted:
        lowered = str(cap).lower()
        for forbidden in _FORBIDDEN_CAPABILITIES:
            assert forbidden not in lowered, f"forbidden capability {forbidden!r} permitted"


def test_end_to_end_chain_preserves_read_only_authority(tmp_path):
    # ── fixed, deterministic fixtures ──
    office_truth = {
        "holdings_ref": "holdings:real",
        "cash_ref": "cash:real",
        "portfolio_ref": "portfolio:real",
        "source_asof": "2026-08-16T00:00:00Z",
    }
    decision_id = make_decision_id("SCHD", "WAIT", 0.0, "concentration")
    decision = {"decision_id": decision_id, "current_action": "WAIT", "act_now": False}
    wake = {"wake_id": "wake_e2e"}

    # 1. canonical truth -> ContextEnvelope
    env = get_context_for_agent(
        agent="alex",
        wake=wake,
        decision=decision,
        office_truth=office_truth,
        memory_provider=_HealthyMemory(),
        symbols=["SCHD"],
    )
    assert env["office_truth"]["cash_ref"] == "cash:real"
    assert env["episodic_memory"]["retrieval_status"] == RETRIEVAL_OK
    _assert_read_only_authority(env["governance"])

    # 2. validate
    ok, errs = validate_context_envelope(env)
    assert ok, errs

    # 3. specialist sub-envelope (scoped, trace-linked)
    sub = build_specialist_sub_envelope(env, "guardian", "is risk acceptable?")
    assert sub["parent_wake_id"] == "wake_e2e"
    _assert_read_only_authority(sub["governance"])

    # 4. MCP read call (allowed read-only tool)
    registry = build_local_provider_registry()
    mcp = call_mcp_tool(
        wake_id="wake_e2e",
        trace_id=env["trace_id"],
        agent="alex",
        tool="portfolio.get_cash_snapshot",
        provider="portfolio",
        request={"account_id": "acct_1"},
        provider_registry=registry,
        trace_path=str(tmp_path / "tool.jsonl"),
    )
    assert mcp["ok"] is True
    assert mcp["status"] == MCP_READ_ONLY_STATUS_OK
    assert mcp["authority"] == AUTHORITY_READ_ONLY_ADVISORY

    # 5. trace (build + validate)
    trace = build_trace(
        trace_id=env["trace_id"],
        wake_id="wake_e2e",
        agent="alex",
        role="cio_synthesis",
        context_digest=env["provenance"]["context_digest"],
    )
    ok_trace, errs_trace = validate_trace(trace)
    assert ok_trace, errs_trace

    # 6. memory retrieval
    memory = LocalTestMemoryProvider()
    rec = build_memory_record(
        memory_type=MEMORY_TYPE_OPERATOR_EXPLICIT_PREFERENCE,
        subject="income anchor",
        content="operator prefers SCHD as income anchor",
        source_event_ids=["evt_1"],
        status=STATUS_ACTIVE,
    )
    memory.add_candidate(rec)
    mem = retrieve_for_context(memory, query="SCHD", symbols=["SCHD"])
    assert mem["retrieval_status"] == RETRIEVAL_OK
    assert rec["memory_id"] in [r["memory_id"] for r in mem["supporting"]]

    # 7. context budget (canonical truth is never dropped)
    budgeted, meta = apply_context_budget(env, budget_tokens=0)
    assert meta["canonical_truth_preserved"] is True
    assert meta["authority"] == AUTHORITY_READ_ONLY_ADVISORY
    assert budgeted["office_truth"]["holdings_ref"] == "holdings:real"
    _assert_read_only_authority(budgeted["governance"])

    # 8. operator feedback (FEEDBACK, never an investment outcome)
    feedback = {"disposition": "REJECT", "note": "concentration too high"}
    assert classify_feedback_vs_outcome(feedback["disposition"]) == FEEDBACK_CLASS

    # 9. memory candidate from feedback (candidate only, no write)
    candidate = propose_memory_write(
        {"feedback": feedback},
        memory_type="lesson",
        content="operator rejected concentration-heavy proposal",
        source_event_ids=["evt_1"],
        wake_id="wake_e2e",
        trace_id=env["trace_id"],
        decision_id=decision_id,
        case_id="case_1",
    )
    assert candidate["status"] == "CANDIDATE"
    assert candidate["provenance"]["write_attempted"] is False
    assert candidate["authority"] == AUTHORITY_READ_ONLY_ADVISORY

    # 10. decision
    effective, _blocking = canonical_act_now(env["decision"])
    assert effective is False
    assert decision_content_digest("SCHD", "WAIT", 0.0, extra="evidence")

    # 11. notification suppression (non-material WAIT)
    notif = evaluate_notification(decision=decision)
    assert notif["send"] is False
    assert notif["suppressed_reason"] == "non_material"
    assert notif["follow_up_required"] is True

    # 12. follow-up (durable next-review binding)
    follow_up = build_durable_next_review("WAIT", kind="TIME", due_at="2026-08-20T00:00:00Z")
    ok_nr, reason_nr = validate_durable_next_review(follow_up)
    assert ok_nr, reason_nr

    # 13. case
    case = {"case_id": "case_1", "decision_id": decision_id, "status": "open"}

    # 14. outcome (only an explicit measured investment outcome counts)
    outcome = {"disposition": "MEASURED_INVESTMENT_OUTCOME", "measured": True, "matured": True}
    assert is_measured_outcome(outcome) is True

    # 15. reflection -> memory proposal (candidate only, no write)
    reflection = {"finding": "concentration rejected; wait for diversification"}
    proposal = propose_memory_write(
        reflection,
        memory_type="case_summary",
        content="SCHD concentration rejected; revisit after diversification",
        source_event_ids=["evt_1"],
        wake_id="wake_e2e",
        trace_id=env["trace_id"],
        decision_id=decision_id,
        case_id=case["case_id"],
    )
    assert proposal["status"] == "CANDIDATE"
    assert proposal["provenance"]["write_attempted"] is False
    assert proposal["authority"] == AUTHORITY_READ_ONLY_ADVISORY

    # lineage binding ties every hop together
    lineage = build_lineage(
        wake_id="wake_e2e",
        trace_id=env["trace_id"],
        decision_id=decision_id,
        case_id=case["case_id"],
        operator_feedback=feedback,
        follow_up=follow_up,
        measured_outcome=outcome,
        reflection=reflection,
        lesson_candidate=proposal["memory_id"],
    )
    assert lineage["wake_id"] == "wake_e2e"
    assert lineage_digest(lineage).startswith("lin_")


def test_prior_reject_suppresses_unchanged_recommendation():
    decision = {
        "decision_id": "dec_1",
        "current_action": "TRIM",
        "act_now": False,
        "decision_input_digest": "in_1",
        "decision_evidence_digest": "ev_1",
    }
    previous = {
        "notification_id": "n_1",
        "decision_id": "dec_1",
        "evidence_digest": "ev_1",
        "disposition": "REJECT",
        "dedupe_key": dedupe_identity(decision),
    }
    result = evaluate_notification(decision=decision, previous=previous, operator_disposition="REJECT")
    assert result["send"] is False
    assert result["suppressed_reason"] == "prior_operator_reject_unchanged"
    assert result["reopen"] is False


def test_no_write_capability_appears_across_chain(tmp_path):
    office_truth = {"holdings_ref": "holdings:real", "source_asof": "2026-08-16T00:00:00Z"}
    env = get_context_for_agent(
        agent="alex",
        wake={"wake_id": "wake_ro"},
        decision={"decision_id": "dec_ro", "current_action": "WAIT", "act_now": False},
        office_truth=office_truth,
        memory_provider=_HealthyMemory(),
    )
    sub = build_specialist_sub_envelope(env, "guardian", "q?")
    budgeted, _ = apply_context_budget(env, 0)

    mcp = call_mcp_tool(
        wake_id="wake_ro",
        trace_id=env["trace_id"],
        agent="alex",
        tool="portfolio.get_verified_snapshot",
        provider="portfolio",
        request={"account_id": "acct_1"},
        provider_registry=build_local_provider_registry(),
        trace_path=str(tmp_path / "tool.jsonl"),
    )

    for obj in (env, sub, budgeted):
        _assert_read_only_authority(obj["governance"])
    assert mcp["authority"] == AUTHORITY_READ_ONLY_ADVISORY
    assert mcp["ok"] is True
    assert mcp["status"] == MCP_READ_ONLY_STATUS_OK
    # the gateway only ever resolves a read-only, allowlisted tool
    assert mcp["tool"] == "portfolio.get_verified_snapshot"
