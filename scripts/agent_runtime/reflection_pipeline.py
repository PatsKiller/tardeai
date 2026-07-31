"""Nightly reflection pipeline — writes real CANDIDATE_LESSON rows (not stubs)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from .agents.definitions import spec as fleet_spec
from .contracts import Environment
from .critic_llm import EgressClass, generate_for_critic, lanes_enabled
from .journal import ShadowRunJournal
from .runtime import MvlRuntime


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReflectionPipeline:
    """Bounded nightly reflection: case/exception payload → candidate lesson."""

    def __init__(self, *, persistence: Any, journal_root, model_provider, model: str, provider_family: str) -> None:
        self.definition = fleet_spec("reflection").definition
        self.persistence = persistence
        self.journal_root = journal_root
        self.model_provider = model_provider
        self.model = model
        self.provider_family = provider_family

    def run(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        runtime = MvlRuntime(
            definition=self.definition,
            journal=ShadowRunJournal(self.journal_root, Environment.SHADOW),
            retrieval_provider=lambda _run_id, _q: [{"ref": "reflection:payload", "content": str(dict(payload))[:4000]}],
            model_provider=self.model_provider,
            persistence=self.persistence,
        )
        run = runtime.start(
            job_type="nightly_reflection",
            objective="Nightly reflection batch",
            input_payload=dict(payload),
            validation_payload={"state": "PASS", "source": payload.get("source")},
        )
        provider_family = "deterministic"
        model = "none"
        statement = (
            f"Candidate lesson from nightly reflection over source={payload.get('source')}. "
            "Requires human ratification before retrieval."
        )
        llm_text = ""
        if lanes_enabled() and self.definition.budget.max_model_calls > 0:
            prompt = (
                "Draft one concise candidate lesson (2-4 sentences) from this nightly reflection payload. "
                "Do not include dollar amounts, account numbers, or secrets. "
                "State what was observed and what an operator should verify.\n\n"
                f"Payload: {dict(payload)}"
            )
            llm = generate_for_critic(
                agent_id="reflection",
                prompt=prompt,
                egress=EgressClass.LOCAL_ONLY,
                severity="info",
                force=True,
            )
            if llm.escalated and llm.text.strip():
                llm_text = llm.text.strip()[:2000]
                statement = llm_text
                provider_family = llm.provider_family
                model = llm.model
                runtime.reason(
                    run.run_id,
                    prompt_version="reflection-v1",
                    provider_family=provider_family,
                    model=model,
                    request_payload={"task": "nightly_reflection", "payload": dict(payload)},
                    cost_usd=0.0,
                )
        lesson_id = f"lesson_{uuid.uuid4().hex[:10]}"
        title = f"Reflection candidate {payload.get('nightly_bucket') or _utc_now_iso()[:10]}"
        if self.persistence is not None and hasattr(self.persistence, "record_lesson"):
            self.persistence.record_lesson(
                lesson_id=lesson_id,
                lesson_version=1,
                lifecycle="CANDIDATE",
                title=title,
                statement=statement,
                provenance={
                    "source": payload.get("source"),
                    "nightly_bucket": payload.get("nightly_bucket"),
                    "payload": dict(payload),
                    "llm_used": bool(llm_text),
                },
                created_by="reflection",
                reviewed_by=None,
            )
        runtime.create_artifact(
            run.run_id,
            artifact_type="candidate_lesson",
            payload={
                "lesson_id": lesson_id,
                "lifecycle": "CANDIDATE",
                "authority": "ADVISORY_ONLY",
                "statement_preview": statement[:500],
            },
            prompt_version="reflection-v1",
            provider_family=provider_family,
            model=model,
        )
        status = str(runtime.status(run.run_id).get("status") or "REVIEW_REQUIRED")
        return {"run_id": run.run_id, "status": status, "agent_id": "reflection", "lesson_id": lesson_id}
