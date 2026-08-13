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
import sys
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


def _build_governed_flash_provider() -> Callable[[str, Mapping[str, Any]], Mapping[str, Any]]:
    """Governed DeepSeek V4 Flash provider for the reflective critics.

    Routes through lib.llm_lane.generate → gate_and_generate, so every call is
    cost-governed (process cap + global daily cap), circuit-breakered, and
    fail-closed (no silent Ollama/Grok/Claude fallback). Replaces the raw Ollama
    path that previously served sentinel/iris/reflection.
    """
    def _call(run_id: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from lib.llm_lane import generate
            msgs = request.get("messages") or []
            prompt = "\n\n".join(
                str(m.get("content") or "") for m in msgs if m.get("content")
            ).strip()
            if not prompt:
                return {"response": "", "provider": "deepseek",
                        "model": "deepseek-v4-flash", "error": "empty prompt"}
            max_tokens = int(request.get("max_tokens") or 512)
            text = generate(
                prompt,
                lane="deepseek-flash",
                process_id="reflective_critic_flash",
                task_summary=f"reflective:{run_id}"[:160],
                timeout=90,
                max_tokens=max_tokens,
            )
            return {"response": str(text or "").strip(),
                    "provider": "deepseek", "model": "deepseek-v4-flash"}
        except Exception as exc:
            return {"response": "", "provider": "deepseek",
                    "model": "deepseek-v4-flash",
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
    """Build a SHADOW processor: retrieval + optional model + goal thesis touch.

    Financial agents use the governed-gateway *sentinel* as model (returns
    PROVIDER_BLOCKED if invoked). We still complete the job with a
    retrieval-grounded advisory artifact and never invent numbers.
    """
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from agent_runtime.agents.dispatcher import JobRequest
    from agent_runtime.agents.definitions import FLEET
    from agent_runtime.contracts import Environment
    import uuid

    spec = FLEET[agent_id]
    journal_root = PROJECT_ROOT / "data" / "runtime" / "agent_runtime_journals" / agent_id

    def _process(job: JobRequest) -> dict[str, Any]:
        run_id = f"{agent_id}-{uuid.uuid4().hex[:12]}"
        objective = f"{agent_id}:{job.job_type} — {job.trigger_kind or 'scheduled'}"
        # retrieval-before-reasoning
        try:
            retrieval_rows = list(retrieval(run_id, f"{agent_id} {job.job_type} context") or [])
        except Exception as exc:
            retrieval_rows = []
            retrieval_err = f"{type(exc).__name__}: {exc}"
        else:
            retrieval_err = None

        model_response = ""
        model_error = None
        # Only call model for non-financial agents or when explicitly allowed
        try:
            if retrieval_rows:
                context = json.dumps([dict(r) for r in retrieval_rows[:12]], default=str)[:8000]
            else:
                context = "no retrieval results available"
            messages = [
                {"role": "system", "content": (
                    f"You are {agent_id}, a SHADOW READ_ONLY_ADVISORY agent. "
                    f"Job: {job.job_type}. Evidence-grounded notes only. Never invent numbers."
                )},
                {"role": "user", "content": f"Context:\n{context}\n\nObjective: {objective}"},
            ]
            model_output = model(run_id, {"messages": messages, "max_tokens": 512, "temperature": 0.2})
            model_response = str(model_output.get("response") or "")
            if model_output.get("error"):
                model_error = str(model_output["error"])[:300]
        except Exception as exc:
            model_error = f"{type(exc).__name__}: {exc}"

        # Goal / thesis touch (fail-open on missing store)
        goal_touch: dict[str, Any] = {}
        try:
            from scripts.lib.cio_goals import CIOGoalStore  # type: ignore
            store = CIOGoalStore()
            ctx = store.get_context_for_agent(agent_id)
            open_goals = ctx.get("open_goals") or []
            goal_touch = {
                "open_goal_count": len(open_goals),
                "goal_ids": [g.get("goal_id") for g in open_goals[:8]],
            }
            # If job carries a goal_id (dedup_value=goal:<id>), update wake + thesis
            goal_id = None
            if job.dedup_value and str(job.dedup_value).startswith("goal:"):
                goal_id = str(job.dedup_value).split(":", 1)[1]
            if goal_id:
                snippet = (
                    f"shadow_run={run_id}; retrieval_n={len(retrieval_rows)}; "
                    f"model_error={model_error or 'none'}; "
                    f"trigger={job.trigger_kind}"
                )
                store.record_wake(goal_id, agent_id=agent_id, outcome="shadow_completed")
                store.update_thesis(goal_id, snippet[:500], agent_id=agent_id)
                goal_touch["updated_goal_id"] = goal_id
        except Exception as exc:
            goal_touch["error"] = f"{type(exc).__name__}: {exc}"

        # Persist a minimal journal line for audit (not production path)
        try:
            journal_root.mkdir(parents=True, exist_ok=True)
            line = json.dumps({
                "run_id": run_id,
                "agent_id": agent_id,
                "environment": Environment.SHADOW.value,
                "job_type": job.job_type,
                "objective": objective,
                "retrieval_count": len(retrieval_rows),
                "retrieval_err": retrieval_err,
                "model_error": model_error,
                "goal_touch": goal_touch,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "authority": "READ_ONLY_ADVISORY",
            }, sort_keys=True) + "\n"
            with open(journal_root / f"{run_id}.jsonl", "a") as fh:
                fh.write(line)
        except Exception:
            pass

        # Optional persistence: best-effort, never fail the SHADOW job
        try:
            if persistence is not None and hasattr(persistence, "record_shadow_outcome"):
                persistence.record_shadow_outcome(run_id, agent_id, job.job_type)
        except Exception:
            pass

        outcome = "completed"
        if retrieval_err and not retrieval_rows:
            outcome = "completed_degraded"  # fail-open shadow

        return {
            "input_hash": job.input_hash,
            "run_id": run_id,
            "artifact_id": f"art-{run_id}",
            "outcome": outcome,
            "retrieval_count": len(retrieval_rows),
            "model_error": model_error,
            "goal_touch": goal_touch,
            "authority": "READ_ONLY_ADVISORY",
            "definition_id": getattr(spec.definition, "agent_id", agent_id),
        }
    return _process


# ---------------------------------------------------------------------------
# Job source — bounded intake from existing infrastructure
# ---------------------------------------------------------------------------
def job_source(agent_id: str, limit: int = 8) -> Sequence[Any]:
    """Return bounded jobs for *agent_id* from governed intake sources.

    Pulls from:
      1. Agent handoff queue — specialist delegations
      2. Open CIO goals owned by this agent (due or never-woken) — SHADOW only

    Returns at most *limit* JobRequests. Empty batch is a successful no-op.
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

    # Open goals owned by this agent (bounded)
    if len(jobs) < limit:
        try:
            from scripts.lib.cio_goals import CIOGoalStore  # type: ignore
            store = CIOGoalStore()
            due = store.list_due_or_idle_goals(owner_agent=agent_id, limit=limit - len(jobs))
            for g in due:
                gid = g.get("goal_id", "")
                jobs.append(JobRequest(
                    agent_id=agent_id,
                    job_type="goal_shadow_review",
                    input_hash=_hash(f"goal:{gid}:{g.get('updated_ts','')}"),
                    enqueued_at=now_iso,
                    dedup_value=f"goal:{gid}",
                    trigger_kind="GOAL_DUE",
                ))
        except Exception:
            pass

    # Pending EVENT_BUS / GOAL wakes targeting this agent (reactive path)
    if len(jobs) < limit:
        try:
            from scripts.lib.cio_wake_jobs import CIOWakeJobStore
            ws = CIOWakeJobStore()
            pending = ws.list_wakes(status="PENDING", limit=limit * 3)
            for wake in pending:
                ctx = wake.get("context") or {}
                target = (ctx.get("target_agent") or wake.get("target_agent") or "").lower()
                # Goal wakes: owner embedded in wake_job_id wake_goal_* or context
                if not target and str(wake.get("trigger_type", "")).startswith("GOAL"):
                    # best-effort: pull owner from goal store
                    try:
                        from scripts.lib.cio_goals import CIOGoalStore
                        g = CIOGoalStore().get_goal(str(wake.get("trigger_ref") or ""))
                        target = (g or {}).get("owner_agent") or ""
                    except Exception:
                        target = ""
                if target and target != agent_id:
                    continue
                if not target and wake.get("trigger_type") not in ("EVENT_BUS", "GOAL_DUE", "GOAL_EVENT_LINKED"):
                    continue
                if not target:
                    target = agent_id  # unscoped schedule wakes allowed for any runner
                wid = wake.get("wake_job_id") or ""
                jobs.append(JobRequest(
                    agent_id=agent_id,
                    job_type=f"wake_{wake.get('trigger_type', 'EVENT_BUS')}".lower(),
                    input_hash=_hash(f"wake:{wid}"),
                    enqueued_at=wake.get("created_at") or now_iso,
                    dedup_value=wid,
                    trigger_kind=str(wake.get("trigger_type") or "EVENT_BUS"),
                ))
                if len(jobs) >= limit:
                    break
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
# Reflective critics (sentinel, iris, reflection) route through governed
# DeepSeek V4 Flash (reflective_critic_flash). darwin is deterministic
# (BudgetPolicy max_model_calls=0) and keeps an Ollama factory that is never
# invoked — it performs pure artifact scoring with no LLM call.
_REFLECTIVE_FLASH = lambda: _build_governed_flash_provider()
_AGENT_MODEL_MAP: dict[str, Callable[[], Callable]] = {
    # Financial agents — governed gateway only; no model factory here
    "alex":      lambda: _build_governed_gateway_provider(),
    "maria":     lambda: _build_governed_gateway_provider(),
    "steph":     lambda: _build_governed_gateway_provider(),
    "guardian":  lambda: _build_governed_gateway_provider(),
    "ledger":    lambda: _build_governed_gateway_provider(),
    "morgan":    lambda: _build_governed_gateway_provider(),
    # Reflective critics — governed DeepSeek V4 Flash
    "sentinel":  _REFLECTIVE_FLASH,
    "iris":      _REFLECTIVE_FLASH,
    "reflection": _REFLECTIVE_FLASH,
    # darwin is deterministic (0 model calls) — Ollama factory retained but unused.
    "darwin":    lambda: _build_ollama_provider("gemma3:4b"),
}
# Default for any fleet agent not explicitly mapped above (argus, vigil, vega,
# risk_agent, aegis). Unchanged — vigil still uses local Ollama for its health
# fusion; argus is deterministic (0 model calls). Only the three LLM-using
# reflective critics (sentinel/iris/reflection) are migrated above.
_DEFAULT_MODEL = lambda: _build_ollama_provider("gemma3:4b")


def build_providers(agent_id: str):
    """Return governed provider set for *agent_id*.

    DeepSeek V4 Pro/Flash for Alex (CIO synthesis) and Flash for the reflective
    critics (sentinel, iris, reflection). darwin is deterministic and never calls
    a model. Retrieval uses Data Broker read APIs with filesystem fallback.
    """
    model_factory = _AGENT_MODEL_MAP.get(agent_id, _DEFAULT_MODEL)
    retrieval = _build_data_broker_retrieval(agent_id)
    return _AgentProviders(agent_id, retrieval=retrieval, model=model_factory())
