from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.agent_runtime.contracts import (
    AgentDefinition,
    BudgetPolicy,
    DeploymentState,
    Environment,
    ReviewVerdict,
    canonical_hash,
)
from scripts.agent_runtime.journal import ShadowRunJournal
from scripts.agent_runtime.knowledge import KnowledgeIndex, KnowledgeRecord
from scripts.agent_runtime.sentinel_pipeline import (
    ReviewDecision,
    ScoreDecision,
    SentinelShadowPipeline,
)


NOW = datetime(2026, 7, 23, 14, 0, tzinfo=timezone.utc)


def definition() -> AgentDefinition:
    return AgentDefinition(
        agent_id="sentinel",
        display_name="Sentinel",
        role="Decision-integrity reflective critic",
        version="pipeline-test-v1",
        owner="architecture-owner",
        allowed_job_types=("watch_ticket_review",),
        allowed_tools=("kb.search", "ticket.read", "validator.read", "artifact.write", "quarantine.stage"),
        denied_tools=("score.write", "config.promote"),
        retrieval_required=True,
        budget=BudgetPolicy(max_model_calls=2, max_tool_calls=12, max_cost_usd=0.0, deadline_seconds=360),
        deployment_state=DeploymentState.SHADOW,
        enabled=True,
    )


def lesson(symbol: str = "SCHG") -> KnowledgeRecord:
    payload = {"symbol": symbol, "content": "Deterministic validation remains sovereign."}
    return KnowledgeRecord(
        record_id=f"{symbol.lower()}-integrity",
        version=1,
        kind="LESSON",
        lifecycle="RATIFIED",
        title=f"{symbol} ticket integrity lesson",
        content="Deterministic validation remains sovereign; a reflective critic cannot repair or release a failed ticket.",
        source_refs=(f"source:{symbol}:integrity",),
        source_hash=canonical_hash(payload),
        valid_from="2026-01-01T00:00:00+00:00",
        symbols=(symbol,),
        tags=("ticket", "integrity", "deterministic"),
    )


def good_watch():
    return {
        "id": "watch-good",
        "symbol": "SCHG",
        "profile_sector": "Large Blend",
        "price": 33.4,
        "rsi": 45.3,
        "trend_state": "neutral",
        "last_enriched_at": "2026-07-23T13:30:00+00:00",
        "decision_packet": {
            "current_actionable_plan": {
                "state": "READY",
                "ticket_validation": {"state": "PASS", "proposal_allowed": True, "hard_failures": []},
                "mechanics": {"entry": 34.1, "stop": 33.6, "target": 35.5, "direction": "LONG"},
            }
        },
    }


def bad_watch():
    raw = good_watch()
    raw["id"] = "watch-bad"
    raw["decision_packet"]["current_actionable_plan"]["ticket_validation"] = {
        "state": "FAIL",
        "proposal_allowed": False,
        "hard_failures": ["STOP_DIRECTION"],
    }
    return raw


def test_deterministic_failure_never_reaches_model(tmp_path: Path) -> None:
    model_calls = []

    def model_provider(run_id, request):
        model_calls.append((run_id, request))
        return {"verdict": "PASS"}

    pipeline = SentinelShadowPipeline(
        definition=definition(),
        journal=ShadowRunJournal(tmp_path / "runs", Environment.SHADOW),
        knowledge=KnowledgeIndex([lesson()]),
        model_provider=model_provider,
    )
    result = pipeline.run(bad_watch(), now=NOW)
    assert result.model_used is False
    assert model_calls == []
    assert result.integrity_report.release_allowed is False
    assert result.runtime_artifact.artifact_type == "watch_ticket_integrity_block"
    assert result.runtime_artifact.payload["decision"] == "BLOCK_OR_QUARANTINE"
    assert result.status == "REVIEW_REQUIRED"
    state = pipeline.runtime.status(result.run_id)
    assert state["model_calls"] == 0
    assert state["retrieval_count"] >= 1


def test_clean_ticket_retrieves_before_one_model_call(tmp_path: Path) -> None:
    model_calls = []

    def model_provider(run_id, request):
        model_calls.append((run_id, request))
        return {"verdict": "CAUTION", "abstain": False, "findings": ["Review pullback context."]}

    pipeline = SentinelShadowPipeline(
        definition=definition(),
        journal=ShadowRunJournal(tmp_path / "runs", Environment.SHADOW),
        knowledge=KnowledgeIndex([lesson()]),
        model_provider=model_provider,
    )
    result = pipeline.run(good_watch(), now=NOW)
    assert result.model_used is True
    assert len(model_calls) == 1
    request = model_calls[0][1]
    assert request["watch_artifact"]["symbol"] == "SCHG"
    assert request["retrieval"][0]["lifecycle"] == "RATIFIED"
    assert request["constraints"]["may_submit_or_authorize"] is False
    assert result.runtime_artifact.artifact_type == "watch_ticket_reflective_critique"
    assert result.status == "REVIEW_REQUIRED"
    state = pipeline.runtime.status(result.run_id)
    assert state["last_event_type"] == "ARTIFACT_CREATED"
    assert state["model_calls"] == 1
    assert state["retrieval_count"] == 1


def test_no_kb_hit_records_insufficient_knowledge_not_fabricated_context(tmp_path: Path) -> None:
    requests = []

    def model_provider(run_id, request):
        requests.append(request)
        return {"verdict": "INSUFFICIENT_EVIDENCE", "abstain": True}

    pipeline = SentinelShadowPipeline(
        definition=definition(),
        journal=ShadowRunJournal(tmp_path / "runs", Environment.SHADOW),
        knowledge=KnowledgeIndex([]),
        model_provider=model_provider,
    )
    result = pipeline.run(good_watch(), now=NOW)
    state = pipeline.runtime.status(result.run_id)
    assert result.retrieval_context.bundle.hits == ()
    assert state["retrieval_refs"] == ["source_notice:no_relevant_knowledge"]
    assert requests[0]["retrieval"] == []
    assert result.runtime_artifact.payload["critique"]["abstain"] is True


def test_independent_review_and_score_complete_the_loop(tmp_path: Path) -> None:
    def model_provider(run_id, request):
        return {"verdict": "PASS", "abstain": False, "findings": []}

    def reviewer(artifact, integrity, retrieval):
        return ReviewDecision(
            reviewer_agent_id="iris",
            verdict=ReviewVerdict.PASS,
            findings=("Provenance and deterministic integrity bindings verified.",),
        )

    def scorer(artifact, integrity, retrieval):
        return ScoreDecision(
            scorer_agent_id="darwin",
            dimensions={"grounding": 1.0, "integrity": 1.0, "utility": 0.5},
            outcome_ref="outcome:pending",
        )

    pipeline = SentinelShadowPipeline(
        definition=definition(),
        journal=ShadowRunJournal(tmp_path / "runs", Environment.SHADOW),
        knowledge=KnowledgeIndex([lesson()]),
        model_provider=model_provider,
        review_provider=reviewer,
        score_provider=scorer,
    )
    result = pipeline.run(good_watch(), now=NOW)
    assert result.status == "COMPLETED"
    assert result.review is not None and result.review.reviewer_agent_id == "iris"
    assert result.score is not None and result.score.scorer_agent_id == "darwin"
    state = pipeline.runtime.status(result.run_id)
    assert state["review"]["verdict"] == "PASS"
    assert state["score"]["dimensions"]["grounding"] == 1.0


def test_self_review_is_rejected_and_run_stays_uncompleted(tmp_path: Path) -> None:
    def reviewer(artifact, integrity, retrieval):
        return ReviewDecision(reviewer_agent_id="sentinel", verdict=ReviewVerdict.PASS, findings=())

    pipeline = SentinelShadowPipeline(
        definition=definition(),
        journal=ShadowRunJournal(tmp_path / "runs", Environment.SHADOW),
        knowledge=KnowledgeIndex([lesson()]),
        model_provider=lambda run_id, request: {"verdict": "PASS"},
        review_provider=reviewer,
    )
    with pytest.raises(ValueError, match="may not review its own"):
        pipeline.run(good_watch(), now=NOW)
