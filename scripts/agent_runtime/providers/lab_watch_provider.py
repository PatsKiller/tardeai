"""LAB SHADOW provider — bounded Watch intake + governed runtime processors.

Operator-wired module for ``AGENT_RUNTIME_PROVIDER_MODULE``. Emits runs under
**canonical** agent ids (``sentinel``, not ``sentinel_shadow``).

Environment:
  AGENT_RUNTIME_LAB_WATCH_FIXTURE — JSON array of watch/job records (optional)
  AGENT_RUNTIME_LAB_JOURNAL_DIR   — shadow run journal directory (default: state/agent_runtime/journal)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from agent_runtime.agents.definitions import FLEET, spec as fleet_spec
from agent_runtime.agents.dispatcher import JobRequest
from agent_runtime.contracts import Environment, ReviewVerdict, canonical_hash
from agent_runtime.journal import ShadowRunJournal
from agent_runtime.knowledge import KnowledgeIndex, KnowledgeRecord
from agent_runtime.runtime import MvlRuntime
from agent_runtime.sentinel_pipeline import (
    ReviewDecision,
    ScoreDecision,
    SentinelShadowPipeline,
)

FIXTURE_ENV = "AGENT_RUNTIME_LAB_WATCH_FIXTURE"
JOURNAL_ENV = "AGENT_RUNTIME_LAB_JOURNAL_DIR"
DEFAULT_FIXTURE = Path("tests/fixtures/shadow_acceptance/watch_sample.json")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _fixture_path() -> Path:
    raw = os.environ.get(FIXTURE_ENV, "").strip()
    return Path(raw) if raw else DEFAULT_FIXTURE


def _journal_dir() -> Path:
    raw = os.environ.get(JOURNAL_ENV, "").strip()
    return Path(raw) if raw else Path("state/agent_runtime/journal")


def _load_fixture_records() -> list[Mapping[str, Any]]:
    path = _fixture_path()
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [row for row in data if isinstance(row, Mapping)]
    return []


def _default_knowledge() -> KnowledgeIndex:
    payload = {"symbol": "LAB", "content": "Deterministic validation remains sovereign."}
    record = KnowledgeRecord(
        record_id="lab-integrity-lesson",
        version=1,
        kind="LESSON",
        lifecycle="RATIFIED",
        title="LAB ticket integrity lesson",
        content="Reflective critics cannot repair or release a failed deterministic ticket.",
        source_refs=("source:lab:integrity",),
        source_hash=canonical_hash(payload),
        valid_from="2026-01-01T00:00:00+00:00",
        symbols=("LAB", "SCHG", "WAT01", "WAT02", "WAT03", "WAT04", "WAT05"),
        tags=("ticket", "integrity"),
    )
    return KnowledgeIndex([record])


def _watch_payload(record: Mapping[str, Any]) -> Mapping[str, Any]:
    """Build a minimal valid Watch item from a fixture row."""
    symbol = str(record.get("symbol") or "LAB")
    idx = record.get("payload", {}).get("index", 1) if isinstance(record.get("payload"), Mapping) else 1
    return {
        "id": str(record.get("artifact_id") or f"lab-watch-{idx}"),
        "symbol": symbol,
        "profile_sector": "LAB",
        "price": 100.0 + float(idx),
        "rsi": 50.0,
        "trend_state": "neutral",
        "last_enriched_at": _utc_now().isoformat(),
        "decision_packet": {
            "current_actionable_plan": {
                "state": "READY",
                "ticket_validation": {"state": "PASS", "proposal_allowed": True, "hard_failures": []},
                "mechanics": {"entry": 101.0, "stop": 99.5, "target": 104.0, "direction": "LONG"},
            }
        },
    }


def _deterministic_model(_run_id: str, _request: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "verdict": "CAUTION",
        "findings": ["LAB deterministic reflective critique — advisory only."],
        "authority": "ADVISORY_ONLY",
    }


@dataclass
class LabProviders:
    agent_id: str
    knowledge: KnowledgeIndex

    def make_processor(self, persistence) -> Callable[[JobRequest], Mapping[str, Any]]:
        agent_id = self.agent_id
        journal_root = _journal_dir()
        journal_root.mkdir(parents=True, exist_ok=True)

        def processor(job: JobRequest) -> Mapping[str, Any]:
            if agent_id == "sentinel":
                return _process_sentinel(job, persistence, journal_root, self.knowledge)
            return _process_generic(agent_id, job, persistence, journal_root)

        return processor


def _process_sentinel(job: JobRequest, persistence, journal_root: Path, knowledge: KnowledgeIndex) -> Mapping[str, Any]:
    definition = fleet_spec("sentinel").definition
    pipeline = SentinelShadowPipeline(
        definition=definition,
        journal=ShadowRunJournal(journal_root, Environment.SHADOW),
        knowledge=knowledge,
        model_provider=_deterministic_model,
        review_provider=lambda art, _rep, _ctx: ReviewDecision("iris", ReviewVerdict.CAUTION, ("lab-review",)),
        score_provider=lambda _art, _rep, _ctx: ScoreDecision("darwin", {"grounding": 0.8, "utility": 0.6}),
        persistence=persistence,
        provider_family="lab-watch-provider",
        model="deterministic-lab",
    )
    raw = json.loads(job.dedup_value) if job.dedup_value.startswith("{") else _watch_payload({"symbol": "LAB"})
    result = pipeline.run(raw)
    return {"run_id": result.run_id, "status": result.status, "agent_id": "sentinel"}


def _process_generic(agent_id: str, job: JobRequest, persistence, journal_root: Path) -> Mapping[str, Any]:
    agent = fleet_spec(agent_id)
    definition = agent.definition
    journal = ShadowRunJournal(journal_root, Environment.SHADOW)
    runtime = MvlRuntime(
        definition=definition,
        journal=journal,
        retrieval_provider=lambda _rid, _q: [{"ref": "lab:stub", "content": "LAB retrieval stub"}],
        model_provider=_deterministic_model,
        persistence=persistence,
    )
    run = runtime.start(
        job_type=job.job_type,
        objective=f"LAB bounded job for {agent_id}",
        input_payload={"dedup": job.dedup_value, "agent_id": agent_id},
        validation_payload={"state": "PASS"},
    )
    if definition.retrieval_required:
        runtime.retrieve(run.run_id, "lab query")
    if definition.budget.max_model_calls > 0:
        runtime.reason(
            run.run_id,
            prompt_version="lab-v1",
            provider_family="lab-watch-provider",
            model="deterministic-lab",
            request_payload={"task": job.job_type, "agent_id": agent_id},
        )
    artifact = runtime.create_artifact(
        run.run_id,
        artifact_type=f"{agent_id}_lab_artifact",
        payload={"agent_id": agent_id, "job_type": job.job_type, "authority": "ADVISORY_ONLY"},
        prompt_version="lab-v1",
        provider_family="lab-watch-provider",
        model="deterministic-lab",
    )
    runtime.record_review(
        run.run_id, artifact, agent.reviewer_agent_id, ReviewVerdict.CAUTION, ["lab independent review"]
    )
    runtime.record_score(run.run_id, artifact, agent.scorer_agent_id, {"utility": 0.5})
    runtime.complete(run.run_id)
    return {"run_id": run.run_id, "status": "COMPLETED", "agent_id": agent_id}


def build_providers(agent_id: str) -> LabProviders:
    if agent_id not in FLEET:
        raise ValueError(f"unknown agent: {agent_id}")
    if not fleet_spec(agent_id).is_operable_now:
        raise ValueError(f"agent not operable in SHADOW: {agent_id}")
    return LabProviders(agent_id=agent_id, knowledge=_default_knowledge())


def job_source(agent_id: str, limit: int) -> Sequence[JobRequest]:
    if agent_id not in FLEET:
        raise ValueError(f"unknown agent: {agent_id}")
    agent = fleet_spec(agent_id)
    now = _utc_now().isoformat()
    records = _load_fixture_records()
    jobs: list[JobRequest] = []

    if agent_id == "sentinel":
        for row in records[:limit]:
            if row.get("is_known_bad"):
                continue
            payload = _watch_payload(row)
            dedup = canonical_hash(payload)
            jobs.append(
                JobRequest(
                    agent_id=agent_id,
                    job_type="watch_ticket_review",
                    input_hash=dedup,
                    enqueued_at=now,
                    dedup_value=json.dumps(payload, sort_keys=True),
                    trigger_kind="WATCH_ARTIFACT_CHANGED",
                )
            )
        return jobs

    allowed = agent.definition.allowed_job_types
    job_type = allowed[0] if allowed else "bounded_lab_job"
    for i, row in enumerate(records[:limit]):
        dedup = f"{agent_id}:{row.get('artifact_id', i)}"
        jobs.append(
            JobRequest(
                agent_id=agent_id,
                job_type=job_type,
                input_hash=canonical_hash({"agent_id": agent_id, "dedup": dedup}),
                enqueued_at=now,
                dedup_value=dedup,
                trigger_kind="SCHEDULED_SWEEP",
            )
        )
    if not jobs and limit > 0:
        dedup = f"{agent_id}:lab-seed"
        jobs.append(
            JobRequest(
                agent_id=agent_id,
                job_type=job_type,
                input_hash=canonical_hash({"agent_id": agent_id, "dedup": dedup}),
                enqueued_at=now,
                dedup_value=dedup,
                trigger_kind="SCHEDULED_SWEEP",
            )
        )
    return jobs
