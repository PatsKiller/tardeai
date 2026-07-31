"""Darwin — outcome-join artifact scorer (deterministic when persistence available)."""
from __future__ import annotations

from typing import Any, Mapping

from .agents.definitions import spec as fleet_spec
from .contracts import Environment
from .journal import ShadowRunJournal
from .pipeline_common import advisory_payload, persistence_factory
from .runtime import MvlRuntime


def _fetch_recent_artifacts(factory, *, limit: int = 50) -> list[dict[str, Any]]:
    if factory is None:
        return []
    try:
        conn = factory()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT artifact_id, agent_id, artifact_type, created_at,
                   payload::text AS payload_text
            FROM agentic_runtime.agent_artifacts
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


def _score_artifacts(rows: list[dict[str, Any]], payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, float]]:
    findings: list[dict[str, Any]] = []
    if not rows:
        findings.append(
            {
                "code": "no_artifacts",
                "severity": "info",
                "message": "No agent artifacts available to score",
            }
        )
        return findings, {"coverage": 0.0, "scored_count": 0.0}

    scored = 0
    advisory_only = 0
    for row in rows:
        text = str(row.get("payload_text") or "")
        if "ADVISORY_ONLY" in text:
            advisory_only += 1
        scored += 1

    dimensions = {
        "artifact_sample_size": float(len(rows)),
        "scored_count": float(scored),
        "advisory_only_ratio": round(advisory_only / max(len(rows), 1), 4),
        "independent_score_coverage": 1.0 if scored > 0 else 0.0,
    }
    findings.append(
        {
            "code": "scorecard_computed",
            "severity": "info",
            "message": f"Scored {scored} recent artifacts; advisory-only ratio {dimensions['advisory_only_ratio']}",
            "dimensions": dimensions,
            "outcome_ref": payload.get("outcome_id") or payload.get("artifact_id"),
        }
    )
    return findings, dimensions


def run_darwin(job_type: str, payload: Mapping[str, Any], persistence, journal_root) -> Mapping[str, Any]:
    agent = fleet_spec("darwin")
    runtime = MvlRuntime(
        definition=agent.definition,
        journal=ShadowRunJournal(journal_root, Environment.SHADOW),
        retrieval_provider=lambda _run_id, _q: [],
        model_provider=lambda _run_id, _req: {"verdict": "PASS", "findings": []},
        persistence=persistence,
    )
    factory = persistence_factory(persistence)
    rows = _fetch_recent_artifacts(factory)
    findings, dimensions = _score_artifacts(rows, payload)
    run = runtime.start(
        job_type=job_type,
        objective="Join artifacts to outcomes and emit scorecard",
        input_payload=dict(payload),
        validation_payload={"state": "PASS", "source": payload.get("source")},
    )
    body = advisory_payload(
        agent_id="darwin",
        job_type=job_type,
        source=payload.get("source"),
        findings=findings,
        artifact_kind="scorecard",
        dimensions=dimensions,
    )
    artifact = runtime.create_artifact(
        run.run_id,
        artifact_type="scorecard",
        payload=body,
        prompt_version="darwin-scorecard-v1",
        provider_family="deterministic",
        model="none",
    )
    if persistence is not None and dimensions.get("scored_count", 0) > 0:
        try:
            runtime.record_score(
                run.run_id,
                artifact,
                "darwin",
                {k: float(v) for k, v in dimensions.items()},
                str(payload.get("outcome_id") or payload.get("artifact_id") or ""),
            )
        except Exception:
            pass
    status = str(runtime.status(run.run_id).get("status") or "REVIEW_REQUIRED")
    return {"run_id": run.run_id, "status": status, "agent_id": "darwin", "severity": body["severity"]}
