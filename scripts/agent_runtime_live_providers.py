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

# Writer DSN for the governed trigger queue (the queue the producer enqueues into).
DISPATCH_DSN_ENV = "AGENT_RUNTIME_DISPATCH_DSN"

# input_hash -> the run_id the processor actually minted for that job. Kept as the
# settle channel: a missing entry means the job never ran, so the row is left leased
# to expire rather than acked with an invented id. (Since 2026-09-16 the dispatcher
# also returns the processor's own result — JobResult.continuation — so "keep going"
# no longer has to be smuggled through a module global.)
_RUN_IDS: dict[str, str] = {}

# Module-level so a test can redirect them. Both defaulted to PROJECT_ROOT, which is
# resolved to the LIVE tree even under pytest, so every processor test wrote journals
# into the real data/ directory of the running system.
JOURNAL_ROOT = PROJECT_ROOT / "data" / "runtime" / "agent_runtime_journals"
GOAL_LAP_LEDGER_PATH = PROJECT_ROOT / "data" / "cio" / "cio_goal_laps.jsonl"


def _goal_store():
    """The CIO goal store. One seam, so the goal path is testable in isolation."""
    from scripts.lib.cio_goals import CIOGoalStore  # type: ignore

    return CIOGoalStore()


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

    Routes through llm_lane.generate → gate_and_generate, so every call is
    cost-governed (process cap + global daily cap), circuit-breakered, and
    fail-closed (no silent Ollama/Grok/Claude fallback). Replaces the raw Ollama
    path that previously served sentinel/iris/reflection.
    """
    def _call(run_id: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            try:
                from llm_lane import generate
            except ImportError:
                from scripts.llm_lane import generate  # type: ignore
            msgs = request.get("messages") or []
            prompt = "\n\n".join(
                str(m.get("content") or "") for m in msgs if m.get("content")
            ).strip()
            if not prompt:
                return {"response": "", "provider": "deepseek",
                        "model": "deepseek-flash", "error": "empty prompt"}
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
                    "provider": "deepseek", "model": "deepseek-flash"}
        except Exception as exc:
            return {"response": "", "provider": "deepseek",
                    "model": "deepseek-flash",
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
    """Build a SHADOW processor: goal context -> retrieval -> model -> lap artifact.

    Financial agents use the governed-gateway *sentinel* as model (returns
    PROVIDER_BLOCKED if invoked). We still complete the job with a
    retrieval-grounded advisory artifact and never invent numbers.

    The goal is loaded BEFORE the model call. It used to be loaded after it
    (model at :252, goal at :262), so the prompt was built from retrieval rows
    alone and the agent never saw its goal, its predicate, its need ledger or
    its own previous output. Every one of 11,457 laps on one goal was a cold
    start, and the 29,774 thesis events those laps wrote are 100%
    `PROVIDER_BLOCKED` with `retrieval_n=0` — runtime telemetry, not findings.
    """
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from agent_runtime.agents.dispatcher import JobRequest
    from agent_runtime.agents.definitions import FLEET
    from agent_runtime.contracts import Environment, canonical_hash
    import uuid

    spec = FLEET[agent_id]

    def _process(job: JobRequest) -> dict[str, Any]:
        run_id = f"{agent_id}-{uuid.uuid4().hex[:12]}"
        _RUN_IDS[job.input_hash] = run_id
        objective = f"{agent_id}:{job.job_type} — {job.trigger_kind or 'scheduled'}"

        # ── goal context, BEFORE the model call ──────────────────────────────
        goal_touch: dict[str, Any] = {}
        store = None
        goal: dict[str, Any] | None = None
        generation: dict[str, Any] = {}
        goal_block = ""
        goal_id = ""
        try:
            from scripts.lib import goal_generation as gg  # type: ignore

            payload = job.payload if isinstance(job.payload, Mapping) else {}
            goal_id = str(payload.get("goal_id") or "") or gg.goal_id_from_dedup_key(job.dedup_value)
            store = _goal_store()
            ctx = store.get_context_for_agent(agent_id)
            open_goals = ctx.get("open_goals") or []
            goal_touch = {
                "open_goal_count": len(open_goals),
                "goal_ids": [g.get("goal_id") for g in open_goals[:8]],
            }
            if goal_id:
                goal = store.get_goal(goal_id)
            if goal:
                generation = gg.generation_for_goal(goal, laps_path=GOAL_LAP_LEDGER_PATH)
                goal_block = gg.goal_context_block(goal, generation)
                goal_touch["goal_id"] = goal_id
                goal_touch["predicate_version"] = generation["predicate_version"]
                goal_touch["ledger_digest"] = generation["ledger_digest"]
                goal_touch["lap"] = generation["lap"]
                goal_touch["open_needs"] = list(generation["open_needs"])
        except Exception as exc:
            goal_touch["error"] = f"{type(exc).__name__}: {exc}"

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
            system = (
                f"You are {agent_id}, a SHADOW READ_ONLY_ADVISORY agent. "
                f"Job: {job.job_type}. Evidence-grounded notes only. Never invent numbers."
            )
            if goal_block:
                system += (
                    " You are working ONE goal across many laps. Continue the prior lap's work; "
                    "to close a need, write a line beginning 'CLOSED: <need>' and cite the evidence."
                )
                user = f"{goal_block}\n\nContext:\n{context}\n\nObjective: {objective}"
            else:
                user = f"Context:\n{context}\n\nObjective: {objective}"
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            model_output = model(run_id, {"messages": messages, "max_tokens": 512, "temperature": 0.2})
            model_response = str(model_output.get("response") or "")
            if model_output.get("error"):
                model_error = str(model_output["error"])[:300]
        except Exception as exc:
            model_error = f"{type(exc).__name__}: {exc}"

        # ── the lap's artifact, and what it moved ────────────────────────────
        finding = " ".join(model_response.split()) if model_response else ""
        artifact_id = f"art-{run_id}"
        artifact_payload: dict[str, Any] = {}
        payload_hash = ""
        continuation: dict[str, Any] | None = None
        if goal and generation:
            try:
                from scripts.lib import goal_generation as gg  # type: ignore

                open_needs = list(generation.get("open_needs") or [])
                # Parsed from the RAW response: `finding` is whitespace-collapsed
                # for the thesis, and a collapsed string has no lines to scan.
                closed_now = (
                    _declared_closures(model_response, open_needs)
                    if finding and not model_error
                    else []
                )
                lap_refs = [str(r.get("ref")) for r in retrieval_rows if r.get("ref")]
                if finding and not model_error:
                    ref = gg.finding_ref(finding)
                    if ref:
                        lap_refs.append(ref)
                open_after = [n for n in open_needs if n not in closed_now]
                # Content only: no run id, no timestamp, no lap number. Two laps
                # that reach the same conclusion therefore hash the SAME — which
                # is how "this agent is repeating itself" stays visible instead of
                # looking like progress.
                artifact_payload = {
                    "goal_id": goal_id,
                    "predicate_version": generation["predicate_version"],
                    "finding": finding,
                    "closed_needs": closed_now,
                    "open_needs_after": open_after,
                    "evidence_refs": sorted(set(lap_refs)),
                    "retrieval_count": len(retrieval_rows),
                    "model_error": model_error,
                }
                payload_hash = canonical_hash(artifact_payload)
                gg.append_lap(
                    {
                        "goal_id": goal_id,
                        "predicate_version": generation["predicate_version"],
                        "lap": generation["lap"],
                        "run_id": run_id,
                        "agent_id": agent_id,
                        "artifact_id": artifact_id,
                        "payload_hash": payload_hash,
                        "answered_dedup_key": generation["dedup_key"],
                        "finding": finding,
                        "evidence_refs": sorted(set(lap_refs)),
                        "closed_needs": closed_now,
                        "open_needs_after": open_after,
                        "model_error": model_error,
                        "retrieval_count": len(retrieval_rows),
                    },
                    path=GOAL_LAP_LEDGER_PATH,
                )
                # Recomputed AFTER the lap is durable: this is the key the next
                # tick will present. Unchanged when the lap learned nothing, so
                # the enqueue is correctly refused instead of storming.
                next_generation = gg.generation_for_goal(goal, laps_path=GOAL_LAP_LEDGER_PATH)
                continuation = {
                    "goal_id": goal_id,
                    "predicate_version": next_generation["predicate_version"],
                    "lap_completed": generation["lap"],
                    "answered_dedup_key": generation["dedup_key"],
                    "next_dedup_key": next_generation["dedup_key"],
                    "open_needs": list(next_generation["open_needs"]),
                    "closed_needs": list(next_generation["closed_needs"]),
                    "made_progress": next_generation["dedup_key"] != generation["dedup_key"],
                    "artifact_id": artifact_id,
                    "payload_hash": payload_hash,
                }
                goal_touch["artifact_id"] = artifact_id
                goal_touch["payload_hash"] = payload_hash
                goal_touch["made_progress"] = continuation["made_progress"]
            except Exception as exc:
                goal_touch["lap_error"] = f"{type(exc).__name__}: {exc}"

        # ── the goal's own record ────────────────────────────────────────────
        # record_wake carries the run telemetry — that is what the wake event is
        # FOR. update_thesis is only ever given a real finding. Writing
        # "shadow_run=...; retrieval_n=0; model_error=PROVIDER_BLOCKED" into the
        # thesis produced 29,774 events in which the thesis of the goal was a run
        # id, and buried whatever the goal actually believed.
        if store is not None and goal_id and goal:
            try:
                store.record_wake(
                    goal_id,
                    agent_id=agent_id,
                    outcome=(
                        f"shadow_lap:{generation.get('lap')}"
                        f"{'' if not model_error else ':provider_error'}"
                    ),
                )
                goal_touch["updated_goal_id"] = goal_id
                if finding and not model_error:
                    store.update_thesis(goal_id, finding[:500], agent_id=agent_id)
                    goal_touch["thesis_updated"] = True
                else:
                    goal_touch["thesis_updated"] = False
                    goal_touch["thesis_skipped_reason"] = (
                        model_error[:120] if model_error else "no finding produced"
                    )
            except Exception as exc:
                goal_touch["error"] = f"{type(exc).__name__}: {exc}"

        # Persist a minimal journal line for audit (not production path)
        try:
            journal_root = Path(JOURNAL_ROOT) / agent_id
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
        detail = ""
        if continuation and continuation.get("open_needs"):
            # The LAP finished; the GOAL has not. Nine outcomes existed and none
            # could say that, so a lap that had made real progress had to report
            # COMPLETED and the goal looked answered 11,457 times over.
            outcome = "incomplete"
            detail = (
                f"goal {goal_id} lap {continuation['lap_completed']} done; "
                f"{len(continuation['open_needs'])} need(s) open; "
                f"progress={continuation['made_progress']}"
            )

        return {
            "input_hash": job.input_hash,
            "run_id": run_id,
            "artifact_id": artifact_id,
            "payload_hash": payload_hash,
            "outcome": outcome,
            "detail": detail,
            "continuation": continuation,
            "retrieval_count": len(retrieval_rows),
            "model_error": model_error,
            "goal_touch": goal_touch,
            "authority": "READ_ONLY_ADVISORY",
            "definition_id": getattr(spec.definition, "agent_id", agent_id),
        }
    return _process


def _declared_closures(finding: str, open_needs: Sequence[str]) -> list[str]:
    """Needs the lap EXPLICITLY declared closed, matched against the open ledger.

    Deterministic and conservative: a need closes only when the output says so
    on a ``CLOSED:`` line AND that need is currently open. Nothing is inferred
    from tone, length or confidence — an agent cannot close a need by sounding
    finished, and it can never close one that was not declared.
    """
    closed: list[str] = []
    for line in str(finding or "").splitlines() or []:
        stripped = line.strip()
        if not stripped.upper().startswith("CLOSED:"):
            continue
        claim = stripped.split(":", 1)[1].strip().lower()
        for need in open_needs:
            if need.lower() in claim and need not in closed:
                closed.append(need)
    return closed


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
            from scripts.lib import goal_generation as gg  # type: ignore

            store = _goal_store()
            due = store.list_due_or_idle_goals(owner_agent=agent_id, limit=limit - len(jobs))
            for g in due:
                gid = g.get("goal_id", "")
                # The generation token, not a constant `goal:<id>`. The old key was
                # the same string for every lap of a goal for all time, and the
                # intake UNIQUE constraint carries no state column, so the FIRST
                # lap permanently consumed the only slot that goal would ever get:
                # 29,653 duplicate enqueues against 1,759 accepted, one goal worked
                # 11,457 times without a single GOAL_STATUS_CHANGED.
                generation = gg.generation_for_goal(g, laps_path=GOAL_LAP_LEDGER_PATH)
                jobs.append(JobRequest(
                    agent_id=agent_id,
                    job_type="goal_shadow_review",
                    input_hash=_hash(generation["dedup_key"]),
                    enqueued_at=now_iso,
                    dedup_value=generation["dedup_key"],
                    trigger_kind="GOAL_DUE",
                    payload={
                        "goal_id": gid,
                        "predicate_version": generation["predicate_version"],
                        "ledger_digest": generation["ledger_digest"],
                        "lap": generation["lap"],
                        "open_needs": list(generation["open_needs"]),
                    },
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


def _intake_store():
    """The governed trigger queue, or None when no writer DSN is configured."""
    dsn = os.environ.get(DISPATCH_DSN_ENV, "").strip()
    if not dsn:
        return None
    import importlib

    psycopg2 = importlib.import_module("psycopg2")
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from agent_runtime.trigger_intake import PostgresTriggerIntakeStore

    def factory():
        conn = psycopg2.connect(dsn)
        conn.autocommit = False
        return conn

    return PostgresTriggerIntakeStore(factory)


def job_source_with_acks(agent_id: str, limit: int = 8, *, store: Any = None):
    """Lease governed trigger_intake rows and return ``(jobs, ack)``.

    The producer has written this queue since July; nothing ever leased it
    (PostgresTriggerIntakeStore.lease had zero callers), so every row aged past
    stale_input_seconds and each agent sat at max_queue_depth, which stopped the
    producer from enqueueing anything new.

    Rows are converted by trigger_intake.intake_row_to_job_request — the helper that
    has existed all along — so JobRequest carries the row's intake_id, payload and its
    REAL source_timestamp. A runner must never restamp old evidence as ``now`` to walk
    it past the dispatcher's staleness gate: input that is genuinely stale is refused.
    """
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from agent_runtime.trigger_intake import intake_row_to_job_request

    _RUN_IDS.clear()
    if store is None:
        store = _intake_store()
    jobs: list[Any] = []
    leased_hashes: set[str] = set()

    if store is not None:
        try:
            store.return_expired_leases()
        except Exception:
            pass
        try:
            rows = store.lease(
                agent_id, limit=limit, lease_owner=f"runner:{agent_id}:{os.getpid()}")
        except Exception:
            rows = []
        for row in rows:
            job = intake_row_to_job_request(row)
            jobs.append(job)
            leased_hashes.add(job.input_hash)

    if len(jobs) < limit:
        for job in job_source(agent_id, limit - len(jobs)):
            if job.input_hash in leased_hashes:
                continue
            jobs.append(job)

    by_hash = {j.input_hash: j.intake_id for j in jobs if getattr(j, "intake_id", "")}

    def ack(results: Sequence[Any]) -> dict[str, Any]:
        if store is None or not by_hash:
            return {"leased": len(by_hash), "acked": 0}
        counts: dict[str, int] = {}
        for res in results:
            intake_id = by_hash.get(getattr(res, "input_hash", ""))
            if not intake_id:
                continue
            outcome = getattr(getattr(res, "outcome", ""), "value", str(getattr(res, "outcome", "")))
            detail = str(getattr(res, "detail", ""))
            try:
                # INCOMPLETE settles the ROW as COMPLETED: that lap really did
                # finish, and holding the lease open (or failing the row) would
                # either wedge the queue for 900s or advance the breaker against
                # a goal that is making progress. Continuation is a NEW dedup key
                # next tick — never a held lease.
                if outcome in ("COMPLETED", "INCOMPLETE"):
                    run_id = _RUN_IDS.get(res.input_hash)
                    if not run_id:
                        continue  # no real run id: let the lease expire and retry
                    store.ack_completed(intake_id, run_id=run_id)
                elif outcome == "REFUSED_STALE":
                    store.ack_refused_stale(intake_id, detail=detail or "REFUSED_STALE")
                elif outcome in ("FAILED", "CIRCUIT_OPEN"):
                    store.ack_failed(intake_id, detail=f"{outcome}: {detail}"[:300])
                else:
                    continue  # capacity / cancelled / wrong-agent: lease expires, row requeues
            except Exception:
                continue
            counts[outcome] = counts.get(outcome, 0) + 1
        return {"leased": len(by_hash), "acked": sum(counts.values()), "by_outcome": counts}

    return jobs, ack


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
