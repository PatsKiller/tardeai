"""SHADOW fleet provider — operator-owned model/retrieval/job-source backends.

Imported by :mod:`agent_runtime_dispatch_boot` via the operator-configured
``AGENT_RUNTIME_PROVIDER_MODULE`` env var.  This module is the operator-owned
bridge between the driver-free ``agent_runtime`` package and the real
model/retrieval providers.

Currently returns no-op stubs for all agents — the operator has not yet wired
real DeepSeek/Ollama model providers or retrieval backends.  The stubs let the
agent_runtime timer exit cleanly (0 jobs, status=0) instead of crashing with
ModuleNotFoundError.

To wire a real backend:
  1. Implement ``build_providers(agent_id)`` returning per-agent model + retrieval
  2. Implement ``job_source(agent_id, limit)`` returning queued JobRequests
  3. The BoundedDispatcher + MvlRuntime handle budgets, circuit breakers,
     authority deny-lists, and kill switches automatically.
"""
from __future__ import annotations

from agent_runtime.providers import build_providers, job_source

__all__ = ["build_providers", "job_source"]
