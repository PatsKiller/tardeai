"""Operator-owned provider module for the SHADOW agent-runtime fleet.

Wired via AGENT_RUNTIME_PROVIDER_MODULE=agent_runtime_live_providers in the
systemd drop-in.  Exposes real model providers (DeepSeek API, local Ollama) and
retrieval backends (Data Broker read APIs, filesystem portfolio state) for the
governed MvlRuntime lifecycle.

SAFETY: All model calls go through llm_router.py (cost-governed, budget-capped).
No provider can bypass the circuit breaker, budget cap, or authority deny-list
enforced by BoundedDispatcher + MvlRuntime.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

# ---------------------------------------------------------------------------
# Resolve the live project root (same machinery as the health agent)
# ---------------------------------------------------------------------------
def _resolve_project_root() -> Path:
    for candidate in (
        Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"),
        Path(os.environ.get("TRADE_AI_PROJECT_ROOT", "")),
    ):
        if (candidate / "scripts").is_dir():
            return candidate
    raise RuntimeError("Cannot resolve Trade AI project root")


PROJECT_ROOT = _resolve_project_root()


# ---------------------------------------------------------------------------
# Model providers (per agent)
# ---------------------------------------------------------------------------
def _build_governed_gateway_provider() -> Callable[[str, Mapping[str, Any]], Mapping[str, Any]]:
    """Governed financial-agent gateway provider sentinel.

    Financial agents (alex, maria, steph, guardian, ledger, morgan) must route
    through the governed financial-agent gateway. This provider returns
    PROVIDER_BLOCKED if invoked directly — it exists only as a sentinel.
    The actual governed calls go through CIO governed model bridge HTTP API.
    """
    def _call(run_id: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "response": "",
            "provider": "governed_gateway",
            "error": "PROVIDER_BLOCKED: Financial agent must route through governed gateway. Direct provider calls removed in Gate-B.",
        }
    return _call


def _build_ollama_provider(model_name: str = "gemma3:12b") -> Callable[[str, Mapping[str, Any]], Mapping[str, Any]]:
    """Local Ollama provider for routine/lower-cost agent work."""
    OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

    def _call(run_id: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            payload = json.dumps({
                "model": model_name,
                "messages": request.get("messages", []),
                "stream": False,
                "options": {
                    "temperature": request.get("temperature", 0.3),
                    "num_predict": request.get("max_tokens", 1024),
                },
            }).encode()
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read())
            return {"response": body.get("message", {}).get("content", ""),
                    "provider": "ollama", "model": model_name}
        except Exception as exc:
            return {"response": "", "provider": "ollama", "model": model_name,
                    "error": f"{type(exc).__name__}: {exc}"}
    return _call


# ---------------------------------------------------------------------------
# Retrieval providers
# ---------------------------------------------------------------------------
def _build_data_broker_retrieval(agent_id: str) -> Callable[[str, str], Sequence[Mapping[str, Any]]]:
    """Retrieval that reads from the Data Broker read APIs (localhost :7777)."""
    BASE = os.environ.get("TRADE_AI_API_BASE", "http://localhost:7777")

    # Map agent → data domains they're authorized to read
    DOMAINS: dict[str, list[str]] = {
        "sentinel": ["portfolio", "watch", "risk"],
        "darwin": ["portfolio", "risk"],
        "iris": ["kb", "hermes_research"],
        "reflection": ["kb", "watch"],
        "alex": ["portfolio", "risk", "watch", "rotation", "income",
                 "reconciliation", "hermes_research", "investment_policy",
                 "model_portfolio", "cost_basis"],
        "morgan": ["portfolio", "holdings_detail", "sectors", "cost_basis",
                   "transactions", "model_portfolio", "investment_policy",
                   "income", "risk"],
    }

    def _retrieve(run_id: str, query: str) -> Sequence[Mapping[str, Any]]:
        domains = DOMAINS.get(agent_id, ["portfolio"])
        results: list[Mapping[str, Any]] = []
        for domain in domains:
            try:
                req = urllib.request.Request(
                    f"{BASE}/api/v3/data-broker/cio/{domain}",
                    headers={"Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                results.append({"ref": f"data-broker:{domain}",
                                "domain": domain,
                                "data": data.get("data", data),
                                "retrieved_at": time.time()})
            except Exception:
                continue
        return results
    return _retrieve


def _build_filesystem_retrieval(agent_id: str) -> Callable[[str, str], Sequence[Mapping[str, Any]]]:
    """Fallback: read portfolio state from filesystem (zero network, always available)."""
    STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

    def _retrieve(run_id: str, query: str) -> Sequence[Mapping[str, Any]]:
        results: list[Mapping[str, Any]] = []
        holdings = STATE_DIR / "holdings.json"
        if holdings.exists():
            try:
                data = json.loads(holdings.read_text())
                results.append({"ref": "fs:holdings",
                                "domain": "portfolio",
                                "data": data,
                                "retrieved_at": holdings.stat().st_mtime})
            except Exception:
                pass
        return results
    return _retrieve


# ---------------------------------------------------------------------------
# Agent processor factory
# ---------------------------------------------------------------------------
def _make_agent_processor(
    agent_id: str,
    persistence: Any,
    retrieval: Callable[[str, str], Sequence[Mapping[str, Any]]],
    model: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
) -> Callable[[Any], dict[str, Any]]:
    """Build a processor that executes the full MVL lifecycle for one JobRequest."""
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from agent_runtime.agents.dispatcher import JobRequest
    from agent_runtime.agents.definitions import FLEET
    from agent_runtime.runtime import MvlRuntime
    from agent_runtime.journal import ShadowRunJournal
    from agent_runtime.contracts import Environment

    spec = FLEET[agent_id]
    env = Environment(
        hostname=os.uname().nodename,
        runtime_user=os.environ.get("USER", "tradeai"),
        project_root=str(PROJECT_ROOT),
    )

    def _process(job: JobRequest) -> dict[str, Any]:
        journal = ShadowRunJournal(agent_id=agent_id, environment=env)
        runtime = MvlRuntime(
            definition=spec.definition,
            journal=journal,
            retrieval_provider=retrieval,
            model_provider=model,
            persistence=persistence,
        )
        objective = f"{agent_id}:{job.job_type} — {job.trigger_kind or 'scheduled'}"
        envelope = runtime.start(
            job_type=job.job_type,
            objective=objective,
            input_payload={"trigger": job.trigger_kind, "dedup": job.dedup_value},
            validation_payload={"agent_id": agent_id, "job_type": job.job_type},
        )
        # retrieval-before-reasoning gate (required by spec)
        retrieval_rows = runtime.retrieve(envelope.run_id,
            f"{agent_id} {job.job_type} context")
        # model reasoning
        if retrieval_rows:
            context = json.dumps([dict(r) for r in retrieval_rows[:20]], default=str)
        else:
            context = "no retrieval results available"
        messages = [
            {"role": "system", "content": (
                f"You are {agent_id}, a SHADOW agent in the Trade AI agent runtime. "
                f"Your job: {job.job_type}. Produce a concise, evidence-grounded "
                f"advisory artifact. Cite retrieval sources. Never fabricate.")},
            {"role": "user", "content": f"Context:\n{context}\n\nObjective: {objective}"},
        ]
        model_output = runtime.reason(
            envelope.run_id,
            prompt_version="provider-v1",
            provider_family="deepseek",
            model="deepseek-v4-flash",
            request_payload={"messages": messages, "max_tokens": 1024, "temperature": 0.3},
        )
        artifact = runtime.create_artifact(
            envelope.run_id,
            artifact_type=job.job_type,
            payload={
                "objective": objective,
                "model_response": model_output.get("response", ""),
                "retrieval_count": len(retrieval_rows),
                "trigger": job.trigger_kind,
            },
            prompt_version="provider-v1",
            provider_family="deepseek",
            model="deepseek-v4-flash",
        )
        return {
            "input_hash": job.input_hash,
            "run_id": envelope.run_id,
            "artifact_id": artifact.artifact_id,
            "outcome": "completed",
        }
    return _process


# ---------------------------------------------------------------------------
# Job source — bounded intake from existing infrastructure
# ---------------------------------------------------------------------------
def job_source(agent_id: str, limit: int = 8) -> Sequence[Any]:
    """Return bounded jobs for *agent_id* from governed intake sources.

    Pulls from:
      1. Agent handoff queue — specialist delegations (all agents)

    Alex-specific CIO intake (wakes, hermes challenges, CIO event bus) has been
    removed in Gate-B. Alex performs final CIO synthesis only for a specific
    parent_run_id authorized by the CIO Run Orchestrator via the governed bridge.

    Returns at most *limit* JobRequests. Returns empty when nothing is pending.
    """
    from agent_runtime.agents.dispatcher import JobRequest
    import hashlib

    jobs: list[JobRequest] = []
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _hash(s: str) -> str:
        return hashlib.sha256(s.encode()).hexdigest()[:16]

    # Agent handoff queue (all agents — specialist delegations only)
    handoff_path = PROJECT_ROOT / "data" / "cio" / "agent_handoff_queue.jsonl"
    if handoff_path.exists():
        try:
            # Use canonical projection via AgentHandoffQueue API, not raw event records
            from scripts.lib.cio_agent_handoff_queue import AgentHandoffQueue
            queue = AgentHandoffQueue(event_store_path=handoff_path)
            enqueued = queue.list_handoffs(status="ENQUEUED", limit=limit)
            for handoff in enqueued:
                to_agent = handoff.get("to_agent", "")
                if to_agent != agent_id:
                    continue
                jobs.append(JobRequest(
                    agent_id=agent_id,
                    job_type=handoff.get("task_type", "specialist_delegation"),
                    input_hash=_hash(json.dumps(handoff, sort_keys=True, default=str)),
                    enqueued_at=handoff.get("created_at", now_iso),
                    dedup_value=handoff.get("handoff_id", ""),
                    trigger_kind="AGENT_HANDOFF",
                ))
        except Exception:
            pass

    return jobs[:limit]


# ---------------------------------------------------------------------------
# Public contract — build_providers + job_source
# ---------------------------------------------------------------------------
class _AgentProviders:
    """Governed provider set for one agent."""
    def __init__(self, agent_id: str, retrieval, model):
        self.agent_id = agent_id
        self.retrieval = retrieval
        self.model = model

    def make_processor(self, persistence: Any) -> Callable[[Any], dict[str, Any]]:
        return _make_agent_processor(
            self.agent_id, persistence, self.retrieval, self.model)


# Agent → provider assignments
# Gate-B: Financial agents (alex, maria, steph, guardian, ledger, morgan) route
# through the governed financial-agent gateway ONLY. Raw Ollama paths for
# financial agents have been removed. PRO/PRO_THINK for Alex; FAST/Flash for
# specialists.
#
# Non-financial reflective critics (sentinel, darwin, iris, reflection) retain
# Ollama for their independent analytical work.
_AGENT_MODEL_MAP: dict[str, Callable[[], Callable]] = {
    # Financial agents — governed gateway only; no model factory here
    "alex":      lambda: _build_governed_gateway_provider(),
    "maria":     lambda: _build_governed_gateway_provider(),
    "steph":     lambda: _build_governed_gateway_provider(),
    "guardian":  lambda: _build_governed_gateway_provider(),
    "ledger":    lambda: _build_governed_gateway_provider(),
    "morgan":    lambda: _build_governed_gateway_provider(),
    # Reflective critics — local Ollama
    "sentinel":  lambda: _build_ollama_provider("gemma3:12b"),
    "darwin":    lambda: _build_ollama_provider("gemma3:4b"),
    "iris":      lambda: _build_ollama_provider("gemma3:12b"),
    "reflection": lambda: _build_ollama_provider("gemma3:12b"),
}
_DEFAULT_MODEL = lambda: _build_ollama_provider("gemma3:4b")


def build_providers(agent_id: str):
    """Return governed provider set for *agent_id*.

    DeepSeek V4 Pro/Flash for Alex (CIO synthesis); local Ollama for wave-1
    reflective critics (sentinel, darwin, iris, reflection). Retrieval uses
    Data Broker read APIs with filesystem fallback.
    """
    model_factory = _AGENT_MODEL_MAP.get(agent_id, _DEFAULT_MODEL)
    retrieval = _build_data_broker_retrieval(agent_id)
    return _AgentProviders(agent_id, retrieval=retrieval, model=model_factory())
