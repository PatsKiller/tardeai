"""Real SHADOW fleet provider — queue-backed intake with fail-closed model paths.

Leases governed trigger rows from ``agentic_runtime.trigger_intake``. No fixture
loading, generic seed, or forced SCHEDULED_SWEEP fallback.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from agent_runtime.agents.definitions import FLEET, spec as fleet_spec
from agent_runtime.agents.dispatcher import JobRequest
from agent_runtime.contracts import Environment
from agent_runtime.journal import ShadowRunJournal
from agent_runtime.knowledge import KnowledgeIndex
from agent_runtime.runtime import MvlRuntime
from agent_runtime.sentinel_pipeline import SentinelShadowPipeline
from agent_runtime.trigger_intake import (
    PostgresTriggerIntakeStore,
    TriggerIntakeStore,
    intake_row_to_job_request,
)

DISPATCH_DSN_ENV = "AGENT_RUNTIME_DISPATCH_DSN"
JOURNAL_ENV = "AGENT_RUNTIME_LAB_JOURNAL_DIR"
OLLAMA_BASE_ENV = "AGENT_RUNTIME_OLLAMA_BASE"
DEFAULT_OLLAMA = "http://127.0.0.1:11434"
MODEL_ENV = "AGENT_RUNTIME_SHADOW_MODEL"
DEFAULT_MODEL = "qwen2.5:3b"
LEASE_OWNER_ENV = "AGENT_RUNTIME_LEASE_OWNER"

_store: TriggerIntakeStore | None = None
_cached_lease_owner: str | None = None


class ProviderUnavailable(RuntimeError):
    """Raised when the approved local model route is unavailable."""


def _journal_dir() -> Path:
    raw = os.environ.get(JOURNAL_ENV, "").strip()
    return Path(raw) if raw else Path("state/agent_runtime/journal")


def _ollama_base() -> str:
    return os.environ.get(OLLAMA_BASE_ENV, DEFAULT_OLLAMA).rstrip("/")


def _model_name() -> str:
    return os.environ.get(MODEL_ENV, DEFAULT_MODEL).strip() or DEFAULT_MODEL


def lease_owner_id() -> str:
    global _cached_lease_owner
    if _cached_lease_owner is None:
        _cached_lease_owner = os.environ.get(LEASE_OWNER_ENV, "").strip() or socket.gethostname()
    return _cached_lease_owner


def _build_store() -> TriggerIntakeStore:
    global _store
    if _store is not None:
        return _store
    dsn = os.environ.get(DISPATCH_DSN_ENV, "").strip()
    if not dsn:
        raise RuntimeError(f"{DISPATCH_DSN_ENV} is required for shadow fleet provider")

    import importlib

    psycopg2 = importlib.import_module("psycopg2")

    def factory() -> Any:
        conn = psycopg2.connect(dsn)
        conn.autocommit = False
        return conn

    _store = PostgresTriggerIntakeStore(factory)
    return _store


def _ollama_available() -> bool:
    try:
        req = urllib.request.Request(f"{_ollama_base()}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _local_model(run_id: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
    if not _ollama_available():
        raise ProviderUnavailable("local model route unavailable")
    prompt = json.dumps({"run_id": run_id, "request": dict(request)}, sort_keys=True)
    payload = json.dumps(
        {
            "model": _model_name(),
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{_ollama_base()}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.load(resp)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderUnavailable(str(exc)) from exc
    response = str(body.get("response") or "").strip()
    if not response:
        raise ProviderUnavailable("local model returned empty response")
    return {
        "verdict": "CAUTION",
        "findings": [response[:2000]],
        "authority": "ADVISORY_ONLY",
        "provider": "ollama",
        "model": _model_name(),
    }


def _retrieval_from_payload(payload: Mapping[str, Any]) -> Callable[[str, str], list[Mapping[str, Any]]]:
    refs = []
    for key in ("packet_id", "artifact_id", "outcome_id", "lesson_id", "incident_id", "ref_id", "symbol"):
        if payload.get(key):
            refs.append({"ref": f"source:{key}:{payload[key]}", "content": json.dumps(payload, sort_keys=True)[:4000]})
    if not refs:
        refs = [{"ref": "source:payload", "content": json.dumps(payload, sort_keys=True)[:4000]}]

    def provider(_run_id: str, _query: str) -> list[Mapping[str, Any]]:
        return refs

    return provider


def _payload_from_job(job: JobRequest) -> Mapping[str, Any]:
    if job.payload is not None:
        return job.payload
    try:
        parsed = json.loads(job.dedup_value)
        if isinstance(parsed, Mapping):
            return parsed
    except json.JSONDecodeError:
        pass
    return {"dedup": job.dedup_value, "agent_id": job.agent_id}


@dataclass
class ShadowFleetProviders:
    agent_id: str
    store: TriggerIntakeStore

    def make_processor(self, persistence) -> Callable[[JobRequest], Mapping[str, Any]]:
        agent_id = self.agent_id
        store = self.store
        journal_root = _journal_dir()
        journal_root.mkdir(parents=True, exist_ok=True)

        def processor(job: JobRequest) -> Mapping[str, Any]:
            payload = _payload_from_job(job)
            if agent_id == "sentinel":
                return _process_sentinel(job, payload, persistence, journal_root)
            return _process_generic(agent_id, job, payload, persistence, journal_root)

        return processor


def _process_sentinel(job: JobRequest, payload: Mapping[str, Any], persistence, journal_root: Path) -> Mapping[str, Any]:
    definition = fleet_spec("sentinel").definition
    watch_payload = payload.get("packet") if isinstance(payload.get("packet"), Mapping) else payload
    if not isinstance(watch_payload, Mapping):
        watch_payload = {
            "id": payload.get("packet_id") or job.intake_id,
            "symbol": payload.get("symbol") or "UNKNOWN",
            "decision_packet": payload.get("packet") or payload,
        }
    pipeline = SentinelShadowPipeline(
        definition=definition,
        journal=ShadowRunJournal(journal_root, Environment.SHADOW),
        knowledge=KnowledgeIndex([]),
        model_provider=_local_model,
        review_provider=None,
        score_provider=None,
        persistence=persistence,
        provider_family="shadow-fleet-provider",
        model=_model_name(),
    )
    result = pipeline.run(watch_payload)
    return {"run_id": result.run_id, "status": result.status, "agent_id": "sentinel", "intake_id": job.intake_id}


def _process_generic(
    agent_id: str,
    job: JobRequest,
    payload: Mapping[str, Any],
    persistence,
    journal_root: Path,
) -> Mapping[str, Any]:
    agent = fleet_spec(agent_id)
    definition = agent.definition
    runtime = MvlRuntime(
        definition=definition,
        journal=ShadowRunJournal(journal_root, Environment.SHADOW),
        retrieval_provider=_retrieval_from_payload(payload),
        model_provider=_local_model,
        persistence=persistence,
    )
    run = runtime.start(
        job_type=job.job_type,
        objective=f"SHADOW bounded job for {agent_id}",
        input_payload=dict(payload),
        validation_payload={"state": "PASS", "source": payload.get("source")},
    )
    if definition.retrieval_required:
        runtime.retrieve(run.run_id, f"{agent_id} evidence query")
    if definition.budget.max_model_calls > 0:
        runtime.reason(
            run.run_id,
            prompt_version="shadow-fleet-v1",
            provider_family="shadow-fleet-provider",
            model=_model_name(),
            request_payload={"task": job.job_type, "agent_id": agent_id, "payload": dict(payload)},
        )
    artifact_type = {
        "darwin": "scorecard",
        "iris": "knowledge_review",
        "reflection": "reflection_case",
    }.get(agent_id, f"{agent_id}_integrity_review")
    runtime.create_artifact(
        run.run_id,
        artifact_type=artifact_type,
        payload={"agent_id": agent_id, "job_type": job.job_type, "source": payload.get("source"), "authority": "ADVISORY_ONLY"},
        prompt_version="shadow-fleet-v1",
        provider_family="shadow-fleet-provider",
        model=_model_name(),
    )
    # MvlRuntime.complete() enforces "cannot complete a run without independent
    # review" — this pipeline never fabricates that review (that would be the
    # exact synthetic-evidence pattern this provider replaces). The artifact
    # is real and durably recorded; independent review (by agent.reviewer_agent_id,
    # e.g. iris/sentinel/darwin per definitions.py) and completion happen as a
    # separate, later governed step, same as the sentinel pipeline's own
    # REVIEW_REQUIRED artifacts.
    status = str(runtime.status(run.run_id).get("status") or "REVIEW_REQUIRED")
    return {"run_id": run.run_id, "status": status, "agent_id": agent_id, "intake_id": job.intake_id}


def build_providers(agent_id: str) -> ShadowFleetProviders:
    if agent_id not in FLEET:
        raise ValueError(f"unknown agent: {agent_id}")
    if not fleet_spec(agent_id).is_operable_now:
        raise ValueError(f"agent not operable in SHADOW: {agent_id}")
    return ShadowFleetProviders(agent_id=agent_id, store=_build_store())


def job_source(agent_id: str, limit: int) -> Sequence[JobRequest]:
    if agent_id not in FLEET:
        raise ValueError(f"unknown agent: {agent_id}")
    store = _build_store()
    store.return_expired_leases()
    rows = store.lease(agent_id, limit=limit, lease_owner=lease_owner_id())
    return [intake_row_to_job_request(row) for row in rows]
