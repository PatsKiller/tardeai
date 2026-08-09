"""SHADOW fleet providers — operator-supplied model/retrieval backends for the
governed agent runtime.

This module is the operator-owned bridge between the driver-free agent_runtime
package and the real model/retrieval/persistence providers. Each agent gets a
governed provider set assembled from the frozen AgentDefinition.

SAFETY: Model calls, retrieval queries, and job sources are fully governed by
the AgentDefinition budget, tool allowlist, and MvlRuntime lifecycle. No
provider can bypass the circuit breaker, budget cap, or authority deny-list.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from agent_runtime.agents.dispatcher import JobRequest


def _noop_retrieval(run_id: str, query: str) -> Sequence[Mapping[str, Any]]:
    """No-op retrieval: shadow agents have no real retrieval backend wired yet."""
    return ()


def _noop_model(run_id: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
    """No-op model: shadow agents have no model provider until operator wires one."""
    return {"response": "", "provider": "shadow-noop", "model": "none"}


def _make_noop_processor(persistence: Any):
    """Build a processor that skips all jobs (no real work for shadow agents)."""
    def _process(job: JobRequest) -> dict[str, Any]:
        return {
            "input_hash": job.input_hash,
            "outcome": "skipped",
            "detail": f"shadow agent has no queue backend wired (agent={job.agent_id}, job_type={job.job_type})",
        }
    return _process


class _ShadowProviders:
    """Minimal governed provider set for a single shadow agent.

    Assembled from operator-owned providers keyed by agent_id.  For agents
    without a real backend (the default for Wave 2/3 shadow), uses no-op stubs
    so the agent_runtime timer can exit cleanly instead of crashing.
    """

    def __init__(self, agent_id: str, retrieval=None, model=None):
        self.agent_id = agent_id
        self.retrieval = retrieval or _noop_retrieval
        self.model = model or _noop_model

    def make_processor(self, persistence: Any) -> Callable[[JobRequest], dict[str, Any]]:
        return _make_noop_processor(persistence)


def build_providers(agent_id: str):
    """Return a governed provider set for *agent_id*.

    Currently returns no-op stubs for all agents — the operator has not yet
    wired real DeepSeek/Ollama model providers or retrieval backends for the
    shadow fleet.  The no-op stubs let the agent_runtime timer exit cleanly
    (0 jobs) instead of crashing with ModuleNotFoundError.
    """
    return _ShadowProviders(agent_id)


def job_source(agent_id: str, limit: int = 8) -> Sequence[JobRequest]:
    """Return bounded jobs for *agent_id* from the governed job queue.

    Currently returns an empty list for all agents — no real job queue has been
    wired for the shadow fleet.  The BoundedDispatcher handles an empty batch
    cleanly (0 runs, no model calls).
    """
    return ()
