"""Fleet Iris — lesson review with provenance/contradiction checks."""
from __future__ import annotations

import re
from typing import Any, Mapping

from .agents.definitions import spec as fleet_spec
from .contracts import Environment
from .critic_llm import (
    classify_lesson_verdict,
    finding_from_lesson_verdict,
    lanes_enabled,
)
from .journal import ShadowRunJournal
from .pipeline_common import advisory_payload, persistence_factory
from .runtime import MvlRuntime


def _fetch_lessons(factory, lesson_id: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if factory is None:
        return [], []
    try:
        conn = factory()
        cur = conn.cursor()
        if lesson_id:
            cur.execute(
                """
                SELECT lesson_id, lifecycle, title, statement, created_at
                FROM agentic_runtime.kb_lessons
                WHERE lesson_id = %s
                """,
                (lesson_id,),
            )
        else:
            cur.execute(
                """
                SELECT lesson_id, lifecycle, title, statement, created_at
                FROM agentic_runtime.kb_lessons
                WHERE lifecycle = 'CANDIDATE'
                ORDER BY created_at DESC
                LIMIT 5
                """
            )
        cols = [d[0] for d in cur.description or ()]
        candidates = [dict(zip(cols, row)) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT lesson_id, title, statement
            FROM agentic_runtime.kb_lessons
            WHERE lifecycle = 'RATIFIED'
            ORDER BY created_at DESC
            LIMIT 50
            """
        )
        cols = [d[0] for d in cur.description or ()]
        ratified = [dict(zip(cols, row)) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return candidates, ratified
    except Exception:
        return [], []


def _normalize_statement(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _exact_duplicate(stmt: str, ratified: list[dict[str, Any]]) -> str | None:
    norm = _normalize_statement(stmt)
    if not norm:
        return None
    for row in ratified:
        other = _normalize_statement(str(row.get("statement") or ""))
        if not other:
            continue
        if norm == other or norm in other or other in norm:
            return str(row.get("lesson_id") or "")
    return None


def _review_lessons(candidates: list[dict[str, Any]], ratified: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str, str]:
    findings: list[dict[str, Any]] = []
    provider_family = "deterministic"
    model = "none"
    if not candidates:
        return [{"code": "no_candidates", "severity": "info", "message": "No CANDIDATE lessons to review"}], provider_family, model

    for cand in candidates:
        lid = str(cand.get("lesson_id") or "")
        stmt = str(cand.get("statement") or "")
        if len(stmt.strip()) < 20:
            findings.append(
                {
                    "code": "provenance_thin",
                    "severity": "warning",
                    "message": f"Lesson {lid} has thin statement — dispute recommended",
                    "lesson_id": lid,
                    "verdict": "dispute",
                }
            )
            continue

        dup_ref = _exact_duplicate(stmt, ratified)
        if dup_ref:
            findings.append(
                {
                    "code": "duplicate_lesson",
                    "severity": "warning",
                    "message": f"Lesson {lid} duplicates ratified lesson {dup_ref}",
                    "lesson_id": lid,
                    "verdict": "duplicate",
                    "related": [dup_ref],
                }
            )
            continue

        if lanes_enabled():
            verdict, llm = classify_lesson_verdict(
                candidate_id=lid,
                candidate_statement=stmt,
                ratified=ratified,
                agent_id="iris",
            )
            if llm.escalated:
                provider_family = llm.provider_family
                model = llm.model
            parsed_ref = None
            if llm.text:
                from .critic_llm import extract_json_object

                body = extract_json_object(llm.text) or {}
                parsed_ref = body.get("ref")
            findings.append(
                finding_from_lesson_verdict(lesson_id=lid, verdict=verdict, ref=str(parsed_ref) if parsed_ref else None)
            )
        else:
            findings.append(
                {
                    "code": "classification_deferred",
                    "severity": "info",
                    "message": f"Lesson {lid} pending model classification (AGENT_RUNTIME_CRITIC_LANES off)",
                    "lesson_id": lid,
                    "verdict": "caution",
                }
            )
    return findings, provider_family, model


def run_iris_critic(job_type: str, payload: Mapping[str, Any], persistence, journal_root) -> Mapping[str, Any]:
    agent = fleet_spec("iris")
    factory = persistence_factory(persistence)
    lesson_id = str(payload.get("lesson_id") or "") or None
    candidates, ratified = _fetch_lessons(factory, lesson_id)
    findings, provider_family, model = _review_lessons(candidates, ratified)
    runtime = MvlRuntime(
        definition=agent.definition,
        journal=ShadowRunJournal(journal_root, Environment.SHADOW),
        retrieval_provider=lambda _run_id, _q: [{"ref": f"lesson:{lesson_id or 'batch'}", "content": str(len(candidates))}],
        model_provider=lambda _run_id, _req: {"verdict": "ADVISORY", "findings": [f["message"] for f in findings]},
        persistence=persistence,
    )
    run = runtime.start(
        job_type=job_type,
        objective="Lesson lifecycle review",
        input_payload=dict(payload),
        validation_payload={"state": "PASS", "source": payload.get("source")},
    )
    if agent.definition.retrieval_required:
        runtime.retrieve(run.run_id, "lesson review")
    if model != "none" and agent.definition.budget.max_model_calls > 0:
        runtime.reason(
            run.run_id,
            prompt_version="iris-lesson-v1",
            provider_family=provider_family,
            model=model,
            request_payload={"task": "lesson_classification", "candidate_count": len(candidates)},
            cost_usd=0.0,
        )
    body = advisory_payload(
        agent_id="iris",
        job_type=job_type,
        source=payload.get("source"),
        findings=findings,
        artifact_kind="knowledge_review",
        candidate_count=len(candidates),
        ratified_sample=len(ratified),
    )
    runtime.create_artifact(
        run.run_id,
        artifact_type="knowledge_review",
        payload=body,
        prompt_version="iris-lesson-v1",
        provider_family=provider_family,
        model=model,
    )
    status = str(runtime.status(run.run_id).get("status") or "REVIEW_REQUIRED")
    return {"run_id": run.run_id, "status": status, "agent_id": "iris", "severity": body["severity"]}
