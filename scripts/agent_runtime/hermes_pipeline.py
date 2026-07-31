"""Hermes FLEET agent — real hypothesis preregistration via HermesHypothesisGateway."""
from __future__ import annotations

from typing import Any, Mapping

from .agents.definitions import spec as fleet_spec
from .contracts import Environment
from .critic_llm import EgressClass, extract_json_object, generate_for_critic, lanes_enabled
from .hermes import HermesHypothesisGateway
from .journal import ShadowRunJournal
from .pipeline_common import advisory_payload, persistence_factory
from .pipeline_common import load_knowledge_index
from .runtime import MvlRuntime


def _fetch_discovery_candidates(factory, limit: int = 5) -> list[dict[str, Any]]:
    if factory is None:
        return []
    try:
        conn = factory()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT candidate_id, title, summary, status, created_at
            FROM hermes_discovery_candidates
            WHERE status IN ('READY_FOR_REVIEW', 'NEEDS_VALIDATION', 'DISCOVERED')
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        cols = [d[0] for d in cur.description or ()]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return rows
    except Exception:
        return []


def _draft_hypothesis_claim(seed: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    """Return (claim, provider_family, model, success_metric, failure_metric)."""
    title = str(seed.get("title") or "Hermes discovery candidate")
    summary = str(seed.get("summary") or seed.get("title") or "")
    provider_family = "deterministic"
    model = "none"
    success_metric = "artifact_quality_improves"
    failure_metric = "no_measurable_lift"
    claim = summary[:2000] if summary else title

    if lanes_enabled():
        prompt = (
            "Draft a falsifiable research hypothesis from this discovery candidate. "
            "Reply with ONLY JSON: "
            '{"claim":"...", "success_metric":"...", "failure_metric":"..."}\n'
            "Do not include dollar amounts or account identifiers.\n\n"
            f"Title: {title}\nSummary: {summary}\n"
        )
        llm = generate_for_critic(
            agent_id="hermes",
            prompt=prompt,
            egress=EgressClass.TEXT_ONLY,
            severity="info",
            doc_count=2,
            force=True,
        )
        if llm.escalated and llm.text:
            provider_family = llm.provider_family
            model = llm.model
            parsed = extract_json_object(llm.text) or {}
            claim = str(parsed.get("claim") or claim)[:2000]
            success_metric = str(parsed.get("success_metric") or success_metric)[:200]
            failure_metric = str(parsed.get("failure_metric") or failure_metric)[:200]
    return claim, provider_family, model, success_metric, failure_metric


def run_hermes(job_type: str, payload: Mapping[str, Any], persistence, journal_root) -> Mapping[str, Any]:
    agent = fleet_spec("hermes")
    journal = ShadowRunJournal(journal_root, Environment.SHADOW)
    gateway = HermesHypothesisGateway(journal)
    knowledge = load_knowledge_index(persistence)
    kb_hits = len(knowledge.records) if hasattr(knowledge, "records") else 0
    factory = persistence_factory(persistence)
    candidates = _fetch_discovery_candidates(factory)
    runtime = MvlRuntime(
        definition=agent.definition,
        journal=journal,
        retrieval_provider=lambda _run_id, _q: [
            {"ref": f"discovery:{c.get('candidate_id')}", "content": str(c.get("summary") or c.get("title") or "")[:500]}
            for c in candidates[:3]
        ],
        model_provider=lambda _run_id, _req: {"verdict": "ADVISORY", "findings": []},
        persistence=persistence,
    )
    run = runtime.start(
        job_type=job_type,
        objective="Hypothesis discovery and experiment design",
        input_payload=dict(payload),
        validation_payload={"state": "PASS", "source": payload.get("source")},
    )
    runtime.retrieve(run.run_id, "hermes hypothesis discovery")
    findings: list[dict[str, Any]] = []
    hypotheses = []
    provider_family = "hermes-hypothesis-gateway"
    model = "none"
    if job_type == "hypothesis_discovery":
        seed = candidates[0] if candidates else {
            "title": payload.get("title") or "Discovery batch",
            "summary": payload.get("summary") or str(payload),
        }
        claim, claim_provider, claim_model, success_metric, failure_metric = _draft_hypothesis_claim(seed)
        if claim_model != "none" and agent.definition.budget.max_model_calls > 0:
            runtime.reason(
                run.run_id,
                prompt_version="hermes-gateway-v1",
                provider_family=claim_provider,
                model=claim_model,
                request_payload={"task": "hypothesis_draft", "title": seed.get("title")},
                cost_usd=0.0,
            )
            provider_family = claim_provider
            model = claim_model
        hyp = gateway.preregister(
            run_id=run.run_id,
            title=str(seed.get("title") or "Hermes hypothesis"),
            claim=claim,
            frozen_inputs={"payload": dict(payload), "kb_hits": kb_hits, "candidate_id": seed.get("candidate_id")},
            evaluation_plan={"method": "shadow_observation", "window_days": 30},
            success_metrics=(success_metric,),
            failure_metrics=(failure_metric,),
            rollback_plan="Leave hypothesis PREREGISTERED_SHADOW; no config promotion",
        )
        hypotheses.append(hyp.hypothesis_id)
        findings.append(
            {
                "code": "hypothesis_preregistered",
                "severity": "info",
                "message": f"Preregistered hypothesis {hyp.hypothesis_id}",
                "hypothesis_id": hyp.hypothesis_id,
            }
        )
    elif job_type == "experiment_design":
        findings.append(
            {
                "code": "experiment_plan_draft",
                "severity": "info",
                "message": "Draft experiment plan references preregistered hypotheses only",
                "candidate_count": len(candidates),
            }
        )
    else:
        findings.append({"code": "unknown_job", "severity": "info", "message": f"Unhandled job_type {job_type}"})

    artifact_type = "candidate_hypothesis" if job_type == "hypothesis_discovery" else "research_task"
    body = advisory_payload(
        agent_id="hermes",
        job_type=job_type,
        source=payload.get("source"),
        findings=findings,
        artifact_kind=artifact_type,
        kb_hits=kb_hits,
        discovery_candidates=len(candidates),
        hypothesis_ids=hypotheses,
    )
    runtime.create_artifact(
        run.run_id,
        artifact_type=artifact_type,
        payload=body,
        prompt_version="hermes-gateway-v1",
        provider_family=provider_family,
        model=model,
    )
    status = str(runtime.status(run.run_id).get("status") or "REVIEW_REQUIRED")
    return {"run_id": run.run_id, "status": status, "agent_id": "hermes", "severity": body["severity"]}
