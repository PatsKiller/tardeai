"""Read-only operations posture for the agent-runtime fleet.

Surfaces designed schedule metadata, last dispatch timestamps from the read
plane, and optional timer probe results. Never exposes secrets or mutation
authority.
"""
from __future__ import annotations

import os
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from .readiness import (
    DEFAULT_ENABLE_FILE,
    ENABLE_FILE_ENV,
    OPERATOR_AUTH_ENV,
    _truthy,
)

OPERATIONS_CONTRACT = "agent-runtime-operations-v1"
TIMER_PROBE_ENV = "AGENT_RUNTIME_TIMER_PROBE"
HEALTH_STATE_ENV = "AGENT_RUNTIME_HEALTH_STATE_FILE"
DEFAULT_HEALTH_STATE_FILE = "~/.local/state/tradeai/agent-runtime-health.json"
MANUAL_RUN_TEMPLATE = (
    "AGENT_RUNTIME_OPERATOR_AUTH=1 AGENT_RUNTIME_QUEUE_MODULE=agent_runtime_dispatch_boot "
    "AGENT_RUNTIME_PROVIDER_MODULE=agent_runtime.providers.shadow_fleet_provider "
    ".venv/bin/python -m scripts.agent_runtime.agents.run_once --agent <agent_id> --once"
)
SCHEDULE_MANIFEST = "config/agent_runtime_schedules.json"
DISPATCH_DSN_ENV = "AGENT_RUNTIME_DISPATCH_DSN"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manual_command(agent_id: str) -> str:
    return MANUAL_RUN_TEMPLATE.replace("<agent_id>", agent_id)


def _schedule_metadata(spec: Any, manifest_row: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Describe schedule contract from manifest when installed."""
    kinds = [trigger.kind.value for trigger in spec.triggers]
    configured_calendar = None
    if manifest_row:
        configured_calendar = manifest_row.get("on_calendar") or (
            f"*/{manifest_row.get('drain_minutes')} drain"
            if manifest_row.get("drain_minutes")
            else None
        )
    if "NIGHTLY_BATCH" in kinds:
        mode = "NIGHTLY_DESIGNED"
        description = "Nightly bounded batch after close."
    elif "SCHEDULED_SWEEP" in kinds:
        mode = "EVENT_AND_SWEEP_DESIGNED" if len(kinds) > 1 else "SWEEP_DESIGNED"
        description = "Trigger-driven with optional bounded sweep."
    else:
        mode = "EVENT_DRIVEN"
        description = "Runs when upstream governed triggers enqueue work."
    if configured_calendar:
        description = f"{description} Configured calendar: {configured_calendar}."
    return {
        "schedule_mode": mode,
        "designed_schedule": description,
        "configured_calendar": configured_calendar,
    }


def _load_schedule_manifest(root: Path) -> dict[str, Any]:
    path = root / SCHEDULE_MANIFEST
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _queue_posture(env: Mapping[str, str]) -> dict[str, Any]:
    dsn = str(env.get(DISPATCH_DSN_ENV, "")).strip()
    if not dsn:
        return {"available": False, "per_agent": {}, "producer_last_at": None}
    try:
        import importlib

        psycopg2 = importlib.import_module("psycopg2")

        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            """
            SELECT agent_id,
                   count(*) FILTER (WHERE state = 'QUEUED') AS queued,
                   count(*) FILTER (WHERE state = 'LEASED') AS leased,
                   min(source_timestamp) FILTER (WHERE state = 'QUEUED') AS oldest,
                   max(enqueued_at) AS last_trigger_at,
                   (SELECT trigger_kind FROM agentic_runtime.trigger_intake ti2
                    WHERE ti2.agent_id = ti.agent_id
                    ORDER BY enqueued_at DESC LIMIT 1) AS last_trigger_kind
            FROM agentic_runtime.trigger_intake ti
            GROUP BY agent_id
            """
        )
        per_agent = {}
        for row in cur.fetchall():
            per_agent[str(row[0])] = {
                "queue_depth": int(row[1] or 0) + int(row[2] or 0),
                "queued": int(row[1] or 0),
                "leased": int(row[2] or 0),
                "oldest_queued_source_at": row[3].isoformat() if row[3] else None,
                "last_trigger_at": row[4].isoformat() if row[4] else None,
                "last_trigger_kind": row[5],
            }
        cur.close()
        conn.close()
        return {"available": True, "per_agent": per_agent, "producer_last_at": None}
    except Exception:
        return {"available": False, "per_agent": {}, "producer_last_at": None}


def _source_posture(env: Mapping[str, str]) -> list[dict[str, Any]]:
    try:
        from .trigger_sources import probe_all_sources

        return [
            {
                "source_id": probe.source_id,
                "state": probe.state.value,
                "detail": probe.detail,
                "last_observed_at": probe.last_observed_at,
            }
            for probe in probe_all_sources()
        ]
    except Exception:
        return []


def _health_monitor_state(env: Mapping[str, str]) -> dict[str, Any]:
    path = Path(
        str(env.get(HEALTH_STATE_ENV, DEFAULT_HEALTH_STATE_FILE)).strip()
        or DEFAULT_HEALTH_STATE_FILE
    ).expanduser()
    if not path.is_file():
        return {
            "state": "NOT_INSTALLED",
            "last_checked_at": None,
            "detail": "No agent-runtime health monitor observation is installed.",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        observed = str(payload.get("observed_at") or "")
        age_seconds = None
        if observed:
            parsed = datetime.fromisoformat(observed.replace("Z", "+00:00"))
            age_seconds = max(0, int((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()))
        state = str(payload.get("state") or "UNKNOWN")
        if age_seconds is None or age_seconds > 900:
            state = "STALE"
        return {
            "state": state,
            "last_checked_at": observed or None,
            "age_seconds": age_seconds,
            "detail": str(payload.get("detail") or ""),
        }
    except Exception:
        return {
            "state": "INVALID",
            "last_checked_at": None,
            "detail": "Health monitor state could not be parsed.",
        }


def _last_dispatch(reader: Any, agent_id: str) -> tuple[str | None, str | None, str | None]:
    if reader is None:
        return None, None, None
    try:
        result = reader.list_runs(limit=1, offset=0, agent_id=agent_id, status=None)
        if isinstance(result, dict):
            rows = result.get("data")
        else:
            rows = result
        if not rows:
            return None, None, None
        row = rows[0]
        started = row.get("started_at")
        status = row.get("status")
        run_id = row.get("run_id")
        return (
            str(started) if started else None,
            str(status) if status else None,
            str(run_id) if run_id else None,
        )
    except Exception:
        return None, None, None


def _probe_timers() -> dict[str, dict[str, str | None]]:
    """Best-effort probe of canonical system timers, then legacy user timers."""
    out: dict[str, dict[str, str | None]] = {}
    for scope in ([], ["--user"]):
        try:
            proc = subprocess.run(
                ["systemctl", *scope, "show", "tradeai-agent-runtime@*.timer",
                 "--property=Id,LoadState,ActiveState,LastTriggerUSec,NextElapseUSecRealtime",
                 "--no-pager"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            current: dict[str, str] = {}
            for line in [*proc.stdout.splitlines(), ""]:
                if line.strip():
                    key, _, value = line.partition("=")
                    current[key] = value
                    continue
                unit = current.get("Id", "")
                match = re.match(r"tradeai-agent-runtime@([^.]+)\.timer", unit)
                if match and current.get("LoadState") == "loaded":
                    out[match.group(1)] = {
                        "timer_state": "ACTIVE" if current.get("ActiveState") == "active" else "INACTIVE",
                        "next_timer_at": current.get("NextElapseUSecRealtime") or None,
                        "last_timer_run_at": current.get("LastTriggerUSec") or None,
                        "timer_scope": "USER" if scope else "SYSTEM",
                    }
                current = {}
        except Exception:
            continue
    return out


def _agent_entry(
    spec: Any,
    *,
    reader: Any,
    timer_rows: dict[str, dict[str, str | None]],
    timer_probe_enabled: bool,
    manifest_row: Mapping[str, Any] | None,
    queue_row: Mapping[str, Any] | None,
    source_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    agent_id = spec.agent_id
    trigger = spec.triggers[0] if spec.triggers else None
    last_at, last_outcome, last_run_id = _last_dispatch(reader, agent_id)
    timer = timer_rows.get(agent_id, {})
    timer_state = timer.get("timer_state")
    if not timer_probe_enabled:
        timer_state = "OPERATOR_CHECK_REQUIRED"
    elif not timer_state:
        timer_state = "NOT_INSTALLED"
    schedule = _schedule_metadata(spec, manifest_row)
    queue_depth = int((queue_row or {}).get("queue_depth") or 0)
    oldest_age = (queue_row or {}).get("oldest_queued_source_at")
    event_queue_state = "NOT_VERIFIED"
    if queue_row is not None:
        event_queue_state = "READY" if queue_depth >= 0 else "NOT_VERIFIED"
    mode = (manifest_row or {}).get("mode") or ""
    if mode in {"SWEEP", "NIGHTLY", "WEEKDAY_SWEEP"}:
        sweep_id = (manifest_row or {}).get("source") or f"sweep:{agent_id}"
        source_ready = any(
            row.get("source_id") == sweep_id and row.get("state") == "READY"
            for row in source_rows
        )
    else:
        source_ready = any(
            row.get("state") == "READY" and not str(row.get("source_id") or "").startswith("sweep:")
            for row in source_rows
        )
    source_state = "READY" if source_ready else "BLOCKED_SOURCE"
    execution = (
        "SCHEDULED_AUTONOMOUS_SHADOW"
        if spec.is_operable_now and timer_state == "ACTIVE" and source_ready
        else "MANUAL_DISPATCH_ONLY"
        if spec.is_operable_now
        else "NOT_OPERABLE"
    )
    return {
        "agent_id": agent_id,
        "display_name": spec.definition.display_name,
        "role": spec.definition.role,
        "summary": spec.summary,
        "enabled": bool(spec.definition.enabled),
        "lifecycle": spec.definition.deployment_state.value,
        "trigger_kind": trigger.kind.value if trigger else None,
        "trigger_description": trigger.description if trigger else None,
        "triggers": [
            {"kind": item.kind.value, "description": item.description}
            for item in spec.triggers
        ],
        "interacts_with": list(spec.definition.allowed_tools),
        "allowed_outputs": [item.value for item in spec.allowed_output_kinds],
        "reviewer_agent_id": spec.reviewer_agent_id,
        "scorer_agent_id": spec.scorer_agent_id,
        "autonomy": {
            "execution": execution,
            "capability": "BOUNDED_AUTONOMOUS_SHADOW" if spec.is_operable_now else "NOT_OPERABLE",
            "event_queue_state": event_queue_state,
            "per_run_operator_approval_required": False,
            "human_review_scope": "Maturity/promotion and advisory output acceptance; not each bounded run.",
            "self_scheduling_permitted": False,
            "financial_authority": "NONE",
        },
        "source_state": source_state,
        "queue_depth": queue_depth,
        "oldest_queued_source_at": oldest_age,
        "last_trigger_at": (queue_row or {}).get("last_trigger_at"),
        "last_trigger_kind": (queue_row or {}).get("last_trigger_kind"),
        **schedule,
        "timer_unit": f"tradeai-agent-runtime@{agent_id}.timer",
        "timer_state": timer_state,
        "timer_scope": timer.get("timer_scope"),
        "last_timer_run_at": timer.get("last_timer_run_at"),
        "next_timer_at": timer.get("next_timer_at"),
        "last_dispatch_at": last_at,
        "last_dispatch_outcome": last_outcome,
        "last_run_id": last_run_id,
        "manual_run_command": _manual_command(agent_id),
        "timer_probe_hint": (
            None
            if timer_probe_enabled
            else "Set AGENT_RUNTIME_TIMER_PROBE=1 on the server to probe user timers."
        ),
    }


def _catalog_only_entries(root: Path, fleet_ids: set[str]) -> list[dict[str, Any]]:
    """Expose non-runtime catalog rows so the UI can explain why they cannot run."""
    path = root / "config" / "agent_maturity_catalog.json"
    try:
        catalog = json.loads(path.read_text(encoding="utf-8")).get("agents") or {}
    except Exception:
        catalog = {}
    catalog = dict(catalog)
    catalog.setdefault("broker_cloud_oversight", {
        "display_name": "Broker Cloud Oversight",
        "objective": "Read-visible per-proposal cloud second-opinion provenance; invoked from broker proposal review, not the governed Agent Runtime.",
        "allowed_tools": ["llm_feedback_observations.read", "broker_proposal.read"],
        "artifact_schema": "broker_cloud_oversight_observation",
        "deployment_state": "DESIGNED",
        "review_policy": "Operator chooses provider/review from the broker proposal workflow.",
    })
    catalog.setdefault("defense_adjudication", {
        "display_name": "Defense Adjudication",
        "objective": "Read-visible deterministic defense adjudication evidence; its write-capable workflow is deliberately outside Agent Runtime dispatch.",
        "allowed_tools": ["defense_adjudication.read", "promote_criteria.read"],
        "artifact_schema": "defense_adjudication_v9",
        "deployment_state": "DESIGNED",
        "review_policy": "Deterministic defense workflow controls apply; no Agent Runtime dispatch.",
    })
    entries: list[dict[str, Any]] = []
    for agent_id, row in sorted(catalog.items()):
        if agent_id in fleet_ids:
            continue
        entries.append({
            "agent_id": agent_id,
            "display_name": row.get("display_name") or agent_id.replace("_", " ").title(),
            "role": row.get("objective") or "Read-visible observability definition",
            "summary": row.get("objective") or "Catalog-only definition; no governed runtime spec is installed.",
            "enabled": False,
            "lifecycle": row.get("deployment_state") or "DESIGNED",
            "trigger_kind": None,
            "trigger_description": None,
            "triggers": [],
            "interacts_with": list(row.get("allowed_tools") or []),
            "allowed_outputs": [row.get("artifact_schema")] if row.get("artifact_schema") else [],
            "reviewer_agent_id": None,
            "scorer_agent_id": None,
            "autonomy": {
                "execution": "OBSERVABILITY_ONLY",
                "capability": "NOT_AN_AGENT_RUNTIME_TARGET",
                "event_queue_state": "NOT_APPLICABLE",
                "per_run_operator_approval_required": None,
                "human_review_scope": row.get("review_policy") or "No runtime is installed.",
                "self_scheduling_permitted": False,
                "financial_authority": "NONE",
            },
            "schedule_mode": "NOT_RUNNABLE",
            "designed_schedule": "No governed runtime spec or timer exists.",
            "configured_calendar": None,
            "timer_unit": None,
            "timer_state": "NOT_APPLICABLE",
            "timer_scope": None,
            "last_timer_run_at": None,
            "next_timer_at": None,
            "last_dispatch_at": None,
            "last_dispatch_outcome": None,
            "last_run_id": None,
            "manual_run_command": None,
            "timer_probe_hint": None,
        })
    return entries


def operations_payload(
    root: Path,
    *,
    env: Mapping[str, str] | None = None,
    reader: Any = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    env = os.environ if env is None else env
    from agent_runtime.agents.definitions import FLEET

    manifest = _load_schedule_manifest(root)
    manifest_agents = manifest.get("agents") or {}
    queue_posture = _queue_posture(env)
    sources = _source_posture(env)
    timer_probe_enabled = _truthy(env, TIMER_PROBE_ENV) and _truthy(env, OPERATOR_AUTH_ENV)
    timer_rows = _probe_timers() if timer_probe_enabled else {}
    agents = []
    for aid, spec in sorted(FLEET.items()):
        if agent_id and aid != agent_id:
            continue
        agents.append(
            _agent_entry(
                spec,
                reader=reader,
                timer_rows=timer_rows,
                timer_probe_enabled=timer_probe_enabled,
                manifest_row=manifest_agents.get(aid),
                queue_row=queue_posture.get("per_agent", {}).get(aid),
                source_rows=sources,
            )
        )
    if not agent_id or agent_id not in FLEET:
        extras = _catalog_only_entries(root, set(FLEET))
        agents.extend(row for row in extras if not agent_id or row["agent_id"] == agent_id)
    return {
        "contract": OPERATIONS_CONTRACT,
        "observed_at": _now_iso(),
        "read_only": True,
        "timer_probe_enabled": timer_probe_enabled,
        "health_monitor": _health_monitor_state(env),
        "sources": sources,
        "queue_posture": queue_posture,
        "schedule_manifest": manifest.get("contract"),
        "authority": {
            "mutation": False,
            "provider_call": False,
            "service_control": False,
            "schedule_change": False,
            "financial_action": False,
        },
        "agents": agents,
    }
