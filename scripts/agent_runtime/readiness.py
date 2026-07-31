"""Read-only operator readiness surface for the agent-runtime fleet.

Reports wiring gates (env vars, kill switch) and per-agent blockers derived from
the maturity board. Never exposes secrets, DSN values, or mutation authority.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .maturity_observability import maturity_payload
from .read_api import READ_API_CONTRACT

READINESS_CONTRACT = "agent-runtime-readiness-v1"
ENABLE_FILE_ENV = "AGENT_RUNTIME_ENABLED_FILE"
DEFAULT_ENABLE_FILE = "/etc/tradeai/agent_runtime_enabled"
READ_GATE_ENV = "AGENT_RUNTIME_READ_API"
READ_DSN_ENV = "AGENT_RUNTIME_READ_DSN"
DISPATCH_DSN_ENV = "AGENT_RUNTIME_DISPATCH_DSN"
PROVIDER_MODULE_ENV = "AGENT_RUNTIME_PROVIDER_MODULE"
OPERATOR_AUTH_ENV = "AGENT_RUNTIME_OPERATOR_AUTH"
QUEUE_MODULE_ENV = "AGENT_RUNTIME_QUEUE_MODULE"

_TRUTHY = {"1", "true", "yes", "on"}

_WAVE1 = ("sentinel", "darwin", "iris", "reflection", "argus")
_WAVE2 = ("maria", "vega", "risk_agent", "aegis")
_CATALOG_ONLY = ("alex", "atlas", "concierge", "hermes", "pulse", "steph", "tax_agent")
_OBSERVABILITY = ("broker_cloud_oversight", "defense_adjudication")


def _truthy(env: Mapping[str, str], key: str) -> bool:
    return str(env.get(key, "")).strip().lower() in _TRUTHY


def _enable_file(env: Mapping[str, str]) -> Path:
    return Path(str(env.get(ENABLE_FILE_ENV, DEFAULT_ENABLE_FILE)).strip() or DEFAULT_ENABLE_FILE)


def _dispatch_state(env: Mapping[str, str]) -> str:
    if not _truthy(env, OPERATOR_AUTH_ENV):
        return "MISSING_OPERATOR_AUTH"
    if not str(env.get(QUEUE_MODULE_ENV, "")).strip():
        return "MISSING_QUEUE_MODULE"
    if not str(env.get(DISPATCH_DSN_ENV, "")).strip():
        return "MISSING_DSN"
    if not str(env.get(PROVIDER_MODULE_ENV, "")).strip():
        return "MISSING_PROVIDER"
    if not _enable_file(env).exists():
        return "KILL_SWITCH_OFF"
    return "WIRED"


def _read_state(env: Mapping[str, str], *, reader_connected: bool) -> str:
    if not _truthy(env, READ_GATE_ENV):
        return "GATE_OFF"
    if not str(env.get(READ_DSN_ENV, "")).strip():
        return "MISSING_DSN"
    if not reader_connected:
        return "NOT_CONNECTED"
    return "CONNECTED"


def _fleet_summary(agent_rows: list[Mapping[str, Any]]) -> dict[str, int]:
    wave1 = wave2 = catalog_only = observability = runtime_evidence = 0
    for row in agent_rows:
        aid = str(row.get("agent_id") or "")
        if aid in _WAVE1:
            wave1 += 1
        elif aid in _WAVE2:
            wave2 += 1
        elif aid in _CATALOG_ONLY:
            catalog_only += 1
        elif aid in _OBSERVABILITY:
            observability += 1
        if str(row.get("source_class") or "") == "RUNTIME_EVIDENCE":
            runtime_evidence += 1
    return {
        "wave1_agents": wave1,
        "wave2_agents": wave2,
        "catalog_only_agents": catalog_only,
        "observability_agents": observability,
        "runtime_evidence_agents": runtime_evidence,
        "total_agents": len(agent_rows),
    }


def _dispatch_operable(agent_id: str) -> bool:
    """True when the governed fleet registry allows bounded LAB dispatch for this agent."""
    try:
        from agent_runtime.agents.definitions import FLEET

        spec = FLEET.get(agent_id)
        return bool(spec and spec.is_operable_now)
    except Exception:
        return False


def _agent_blocker(row: Mapping[str, Any], *, dispatch_operable: bool) -> dict[str, Any]:
    return {
        "agent_id": row.get("agent_id"),
        "display_name": row.get("display_name"),
        "source_class": row.get("source_class"),
        "next_gate_state": row.get("next_gate_state"),
        "next_gate_id": row.get("next_gate_id"),
        "next_step_hint": row.get("next_step_hint"),
        "promotion_eligibility": row.get("promotion_eligibility"),
        "declared_lifecycle_state": row.get("declared_lifecycle_state"),
        "review_health": row.get("review_health"),
        "sample_size": row.get("sample_size"),
        "required_sample_size": row.get("required_sample_size"),
        "dispatch_operable": dispatch_operable,
    }


def readiness_payload(
    root: Path,
    *,
    env: Mapping[str, str] | None = None,
    reader: Any | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if env is None else env)
    observed_at = observed_at or datetime.now(timezone.utc).isoformat()
    reader_connected = reader is not None
    maturity = maturity_payload(root, reader=reader)
    agent_rows = list(maturity.get("data") or [])

    dispatch = _dispatch_state(env)
    read_api = _read_state(env, reader_connected=reader_connected)

    return {
        "contract": READINESS_CONTRACT,
        "read_api_contract": READ_API_CONTRACT,
        "observed_at": observed_at,
        "read_only": True,
        "authority": {
            "mutation": False,
            "provider_call": False,
            "service_control": False,
            "schedule_change": False,
            "financial_action": False,
        },
        "wiring": {
            "read_api": {
                "state": read_api,
                "gate_enabled": _truthy(env, READ_GATE_ENV),
                "dsn_configured": bool(str(env.get(READ_DSN_ENV, "")).strip()),
            },
            "dispatch": {
                "state": dispatch,
                "operator_auth": _truthy(env, OPERATOR_AUTH_ENV),
                "queue_module_configured": bool(str(env.get(QUEUE_MODULE_ENV, "")).strip()),
                "dispatch_dsn_configured": bool(str(env.get(DISPATCH_DSN_ENV, "")).strip()),
                "provider_module_configured": bool(str(env.get(PROVIDER_MODULE_ENV, "")).strip()),
                "kill_switch_present": _enable_file(env).exists(),
            },
        },
        "fleet_summary": _fleet_summary(agent_rows),
        "agents": [
            _agent_blocker(
                row,
                dispatch_operable=_dispatch_operable(str(row.get("agent_id") or "")),
            )
            for row in agent_rows
        ],
        "runbook_refs": [
            "docs/agent_runtime/SHADOW_ACTIVATION_RUNBOOK.md",
            "docs/agent_runtime/FLEET_STATUS_2026-07-30.md",
            "config/systemd/agent_runtime/README.md",
        ],
        "manual_run_command_template": (
            "AGENT_RUNTIME_OPERATOR_AUTH=1 AGENT_RUNTIME_QUEUE_MODULE=agent_runtime_dispatch_boot "
            ".venv/bin/python scripts/agent_runtime/agents/run_once.py --agent <agent_id> --once"
        ),
    }
