"""Synthesis / orchestration FLEET critics — alex, atlas, concierge, aegis."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .agents.definitions import spec as fleet_spec
from .contracts import Environment
from .critic_llm import EgressClass, generate_for_critic, lanes_enabled, redact_or_refuse
from .journal import ShadowRunJournal
from .operations import operations_payload
from .pipeline_common import advisory_payload, persistence_factory
from .runtime import MvlRuntime

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _stuck_runs(factory) -> list[dict[str, Any]]:
    if factory is None:
        return []
    try:
        conn = factory()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT run_id, agent_id, status, updated_at
            FROM agentic_runtime.agent_runs
            WHERE status NOT IN ('COMPLETED', 'CANCELLED', 'FAILED')
              AND updated_at < now() - interval '2 hours'
            ORDER BY updated_at ASC
            LIMIT 20
            """
        )
        cols = [d[0] for d in cur.description or ()]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return rows
    except Exception:
        return []


def _aegis_incident_findings(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str, str]:
    incident_id = payload.get("incident_id") or payload.get("ref_id")
    provider_family = "deterministic"
    model = "none"
    if not incident_id:
        return [{"code": "no_incident", "severity": "info", "message": "No incident id in trigger payload"}], provider_family, model

    proposed_actions = [
        "Review incident logs and correlated health_agent finding",
        "Confirm whether allowlisted auto-remediation already ran",
        "Escalate to operator if circuit breaker tripped",
    ]
    if lanes_enabled():
        prompt = (
            "Draft an advisory incident triage narrative for an operator. "
            "Provide 3-5 bullet remediation steps. Do not include secrets or dollar amounts.\n\n"
            f"Incident id: {incident_id}\nPayload: {dict(payload)}"
        )
        llm = generate_for_critic(
            agent_id="aegis",
            prompt=prompt,
            egress=EgressClass.LOCAL_ONLY,
            severity="warning",
            force=True,
        )
        if llm.escalated and llm.text.strip():
            provider_family = llm.provider_family
            model = llm.model
            proposed_actions = [ln.strip("- ").strip() for ln in llm.text.splitlines() if ln.strip()][:8] or proposed_actions

    return [
        {
            "code": "incident_triage",
            "severity": "warning",
            "message": f"Incident {incident_id} requires remediation proposal (advisory draft only)",
            "incident_id": incident_id,
            "proposed_actions": proposed_actions,
        }
    ], provider_family, model


def _alex_synthesis(payload: Mapping[str, Any], factory) -> tuple[list[dict[str, Any]], str, str]:
    tradeoffs = []
    if factory:
        try:
            conn = factory()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT agent_id, payload::text
                FROM agentic_runtime.agent_artifacts
                WHERE created_at > now() - interval '7 days'
                  AND payload::text LIKE '%"severity": "high"%'
                ORDER BY created_at DESC
                LIMIT 5
                """
            )
            for agent_id, text in cur.fetchall():
                tradeoffs.append({"agent_id": agent_id, "snippet": text[:200]})
            cur.close()
            conn.close()
        except Exception:
            pass
    provider_family = "deterministic"
    model = "none"
    if not tradeoffs:
        return [
            {
                "code": "no_open_tradeoffs",
                "severity": "info",
                "message": "No recent high-severity critic findings to synthesize",
                "symbol": payload.get("symbol"),
            }
        ], provider_family, model

    synthesis_message = f"Synthesized {len(tradeoffs)} open high-severity critic findings for operator review"
    if lanes_enabled():
        block = "\n".join(f"- {row['agent_id']}: {row['snippet']}" for row in tradeoffs)
        redacted = redact_or_refuse(block)
        if redacted is not None:
            prompt = (
                "Synthesize these high-severity FLEET critic findings into one CIO-level advisory paragraph. "
                "Highlight conflicts and recommended operator focus. No dollar amounts.\n\n"
                f"{redacted}"
            )
            llm = generate_for_critic(
                agent_id="alex",
                prompt=prompt,
                egress=EgressClass.TEXT_ONLY,
                severity="high",
                doc_count=len(tradeoffs),
                force=True,
            )
            if llm.escalated and llm.text.strip():
                provider_family = llm.provider_family
                model = llm.model
                synthesis_message = llm.text.strip()[:1200]
        else:
            llm = generate_for_critic(
                agent_id="alex",
                prompt=(
                    "Summarize that multiple high-severity FLEET findings need operator review. "
                    "Do not invent portfolio numbers.\n"
                ),
                egress=EgressClass.LOCAL_ONLY,
                severity="high",
                force=True,
            )
            if llm.escalated and llm.text.strip():
                provider_family = llm.provider_family
                model = llm.model
                synthesis_message = llm.text.strip()[:1200]

    return [
        {
            "code": "cio_synthesis",
            "severity": "warning",
            "message": synthesis_message,
            "tradeoffs": tradeoffs,
        }
    ], provider_family, model


def run_synthesis_critic(agent_id: str, job_type: str, payload: Mapping[str, Any], persistence, journal_root) -> Mapping[str, Any]:
    agent = fleet_spec(agent_id)
    factory = persistence_factory(persistence)
    provider_family = "deterministic"
    model = "none"
    if agent_id == "atlas":
        stuck = _stuck_runs(factory)
        findings = (
            [
                {
                    "code": "stuck_runs",
                    "severity": "high",
                    "message": f"{len(stuck)} FLEET runs stuck >2h",
                    "runs": stuck,
                }
            ]
            if stuck
            else [{"code": "workflow_ok", "severity": "info", "message": "No stuck FLEET runs detected"}]
        )
        artifact_type = "workflow_health"
    elif agent_id == "concierge":
        ops = operations_payload(PROJECT_ROOT)
        enabled = sum(1 for row in ops.get("agents") or [] if row.get("enabled"))
        findings = [
            {
                "code": "operator_status",
                "severity": "info",
                "message": f"FLEET operator posture: {enabled} enabled agents; read-only status surface",
                "promotion_framework": ops.get("promotion_framework"),
            }
        ]
        artifact_type = "operator_status"
    elif agent_id == "aegis":
        findings, provider_family, model = _aegis_incident_findings(payload)
        artifact_type = "remediation_proposal"
    elif agent_id == "alex":
        findings, provider_family, model = _alex_synthesis(payload, factory)
        artifact_type = "cio_synthesis"
    else:
        findings = [{"code": "unknown", "severity": "info", "message": "No synthesis handler"}]
        artifact_type = f"{agent_id}_integrity_review"

    runtime = MvlRuntime(
        definition=agent.definition,
        journal=ShadowRunJournal(journal_root, Environment.SHADOW),
        retrieval_provider=lambda _run_id, _q: [],
        model_provider=lambda _run_id, _req: {"verdict": "ADVISORY", "findings": [f["message"] for f in findings]},
        persistence=persistence,
    )
    run = runtime.start(
        job_type=job_type,
        objective=f"Synthesis/orchestration for {agent_id}",
        input_payload=dict(payload),
        validation_payload={"state": "PASS", "source": payload.get("source")},
    )
    if model != "none" and agent.definition.budget.max_model_calls > 0:
        runtime.reason(
            run.run_id,
            prompt_version="synthesis-critic-v1",
            provider_family=provider_family,
            model=model,
            request_payload={"task": job_type, "agent_id": agent_id},
            cost_usd=0.0,
        )
    body = advisory_payload(
        agent_id=agent_id,
        job_type=job_type,
        source=payload.get("source"),
        findings=findings,
        artifact_kind=artifact_type,
    )
    runtime.create_artifact(
        run.run_id,
        artifact_type=artifact_type,
        payload=body,
        prompt_version="synthesis-critic-v1",
        provider_family=provider_family,
        model=model,
    )
    status = str(runtime.status(run.run_id).get("status") or "REVIEW_REQUIRED")
    return {"run_id": run.run_id, "status": status, "agent_id": agent_id, "severity": body["severity"]}
