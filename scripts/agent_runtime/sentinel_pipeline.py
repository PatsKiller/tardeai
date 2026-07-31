from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Callable, Mapping

from .contracts import AgentDefinition, Artifact, Review, ReviewVerdict, Score
from .journal import ShadowRunJournal
from .knowledge import KnowledgeIndex, WatchRetrievalContext
from .runtime import ModelProvider, MvlRuntime
from .sentinel import SentinelReport, inspect_ticket
from .watch_artifact import WatchArtifact, adapt_watch_item


@dataclass(frozen=True)
class ReviewDecision:
    reviewer_agent_id: str
    verdict: ReviewVerdict
    findings: tuple[str, ...]


@dataclass(frozen=True)
class ScoreDecision:
    scorer_agent_id: str
    dimensions: Mapping[str, float]
    outcome_ref: str | None = None


@dataclass(frozen=True)
class SentinelPipelineResult:
    run_id: str
    status: str
    watch_artifact: WatchArtifact
    integrity_report: SentinelReport
    retrieval_context: WatchRetrievalContext
    runtime_artifact: Artifact
    review: Review | None
    score: Score | None
    model_used: bool


ReviewProvider = Callable[[Artifact, SentinelReport, WatchRetrievalContext], ReviewDecision]
ScoreProvider = Callable[[Artifact, SentinelReport, WatchRetrievalContext], ScoreDecision]


class SentinelShadowPipeline:
    """One governed Watch -> Sentinel -> retrieval -> artifact loop.

    The pipeline is LAB/SHADOW only. Deterministic failures never reach a model.
    Passing artifacts remain REVIEW_REQUIRED until an independent reviewer is
    provided. No method in this class can submit, authorize or promote a trade.
    """

    def __init__(
        self,
        *,
        definition: AgentDefinition,
        journal: ShadowRunJournal,
        knowledge: KnowledgeIndex,
        model_provider: ModelProvider,
        review_provider: ReviewProvider | None = None,
        score_provider: ScoreProvider | None = None,
        persistence: Any | None = None,
        prompt_version: str = "sentinel-reflective-v1",
        provider_family: str = "injected-shadow-provider",
        model: str = "injected-shadow-model",
    ) -> None:
        if definition.agent_id != "sentinel":
            raise ValueError("SentinelShadowPipeline requires the sentinel agent definition")
        self.definition = definition
        self.journal = journal
        self.knowledge = knowledge
        self.review_provider = review_provider
        self.score_provider = score_provider
        self.prompt_version = prompt_version
        self.provider_family = provider_family
        self.model = model
        self._retrieval_by_run: dict[str, WatchRetrievalContext] = {}
        self.runtime = MvlRuntime(
            definition=definition,
            journal=journal,
            retrieval_provider=self._retrieval_provider,
            model_provider=model_provider,
            persistence=persistence,
        )

    def run(self, raw_watch: Mapping[str, Any], *, now: datetime | None = None) -> SentinelPipelineResult:
        adapted = adapt_watch_item(raw_watch, now=now)
        watch_artifact = adapted.artifact
        integrity = inspect_ticket(watch_artifact.sentinel_ticket(), adapted.source_validation, now=now)
        retrieval = self.knowledge.retrieve_for_watch(watch_artifact, integrity, as_of=now)

        envelope = self.runtime.start(
            job_type="watch_ticket_review",
            objective="Challenge one deterministic Watch artifact without changing its facts, mechanics or authority.",
            input_payload={
                "watch_artifact_hash": watch_artifact.artifact_hash,
                "artifact_key": watch_artifact.artifact_key,
                "symbol": watch_artifact.symbol,
                "source_refs": list(watch_artifact.source_refs),
                "data_gaps": list(watch_artifact.data_gaps),
                "advisory_only": True,
                "financial_authority": "DENIED",
            },
            validation_payload={
                "sentinel_kernel": integrity.kernel_version,
                "integrity_report_hash": integrity.report_hash,
                "verdict": integrity.verdict,
                "release_allowed": integrity.release_allowed,
                "findings": [asdict(finding) for finding in integrity.findings],
            },
        )
        self._retrieval_by_run[envelope.run_id] = retrieval
        self.runtime.retrieve(envelope.run_id, retrieval.query)

        if not integrity.release_allowed:
            payload = {
                "artifact_kind": "sentinel_integrity_block",
                "watch_artifact_hash": watch_artifact.artifact_hash,
                "retrieval_bundle_hash": retrieval.bundle.bundle_hash,
                "integrity_report": asdict(integrity),
                "decision": "BLOCK_OR_QUARANTINE",
                "model_used": False,
                "authority": "ADVISORY_ONLY",
            }
            runtime_artifact = self.runtime.create_artifact(
                envelope.run_id,
                artifact_type="watch_ticket_integrity_block",
                payload=payload,
                prompt_version=integrity.kernel_version,
                provider_family="deterministic",
                model="none",
            )
            model_used = False
        else:
            request = {
                "task": "Critique the validated Watch ticket; preserve deterministic facts and abstain when evidence is insufficient.",
                "watch_artifact": {
                    "artifact_hash": watch_artifact.artifact_hash,
                    "symbol": watch_artifact.symbol,
                    "state": watch_artifact.state,
                    "direction": watch_artifact.direction,
                    "as_of": watch_artifact.as_of,
                    "mechanics": dict(watch_artifact.mechanics),
                    "market_context": dict(watch_artifact.market_context),
                    "strategy_context": dict(watch_artifact.strategy_context),
                    "data_gaps": list(watch_artifact.data_gaps),
                },
                "deterministic_integrity": asdict(integrity),
                "retrieval": [
                    {
                        "ref": hit.retrieval_ref,
                        "kind": hit.kind,
                        "lifecycle": hit.lifecycle,
                        "title": hit.title,
                        "content": hit.content,
                        "source_refs": list(hit.source_refs),
                        "source_hash": hit.source_hash,
                        "counterevidence_refs": list(hit.counterevidence_refs),
                        "contradicts_refs": list(hit.contradicts_refs),
                    }
                    for hit in retrieval.bundle.hits
                ],
                "constraints": {
                    "may_change_ticket": False,
                    "may_override_deterministic_failure": False,
                    "may_submit_or_authorize": False,
                    "valid_abstention": True,
                },
            }
            critique = self.runtime.reason(
                envelope.run_id,
                prompt_version=self.prompt_version,
                provider_family=self.provider_family,
                model=self.model,
                request_payload=request,
            )
            runtime_artifact = self.runtime.create_artifact(
                envelope.run_id,
                artifact_type="watch_ticket_reflective_critique",
                payload={
                    "artifact_kind": "sentinel_reflective_critique",
                    "watch_artifact_hash": watch_artifact.artifact_hash,
                    "retrieval_bundle_hash": retrieval.bundle.bundle_hash,
                    "integrity_report_hash": integrity.report_hash,
                    "critique": dict(critique),
                    "model_used": True,
                    "authority": "ADVISORY_ONLY",
                },
                prompt_version=self.prompt_version,
                provider_family=self.provider_family,
                model=self.model,
            )
            model_used = True

        review: Review | None = None
        score: Score | None = None
        if self.review_provider is not None:
            decision = self.review_provider(runtime_artifact, integrity, retrieval)
            review = self.runtime.record_review(
                envelope.run_id,
                runtime_artifact,
                decision.reviewer_agent_id,
                decision.verdict,
                decision.findings,
            )
            if self.score_provider is not None:
                scoring = self.score_provider(runtime_artifact, integrity, retrieval)
                score = self.runtime.record_score(
                    envelope.run_id,
                    runtime_artifact,
                    scoring.scorer_agent_id,
                    scoring.dimensions,
                    scoring.outcome_ref,
                )
            self.runtime.complete(envelope.run_id)

        state = self.runtime.status(envelope.run_id)
        return SentinelPipelineResult(
            run_id=envelope.run_id,
            status=str(state.get("status") or "UNKNOWN"),
            watch_artifact=watch_artifact,
            integrity_report=integrity,
            retrieval_context=retrieval,
            runtime_artifact=runtime_artifact,
            review=review,
            score=score,
            model_used=model_used,
        )

    def _retrieval_provider(self, run_id: str, query: str):
        context = self._retrieval_by_run.get(run_id)
        if context is None:
            raise KeyError(f"retrieval context not registered for run: {run_id}")
        if context.query != query:
            raise ValueError("retrieval query changed after preregistration")
        if not context.bundle.hits:
            return [
                {
                    "ref": "source_notice:no_relevant_knowledge",
                    "kind": "SOURCE_NOTICE",
                    "lifecycle": "OBSERVED",
                    "title": "No relevant active knowledge found",
                    "content": "The temporal and lifecycle filters returned no relevant records. This is evidence of insufficient knowledge, not permission to infer facts.",
                    "query_hash": context.bundle.query_hash,
                    "bundle_hash": context.bundle.bundle_hash,
                }
            ]
        return [
            {
                "ref": hit.retrieval_ref,
                "kind": hit.kind,
                "lifecycle": hit.lifecycle,
                "title": hit.title,
                "content": hit.content,
                "source_refs": list(hit.source_refs),
                "source_hash": hit.source_hash,
                "counterevidence_refs": list(hit.counterevidence_refs),
                "contradicts_refs": list(hit.contradicts_refs),
                "score": hit.score,
                "reasons": list(hit.reasons),
            }
            for hit in context.bundle.hits
        ]
