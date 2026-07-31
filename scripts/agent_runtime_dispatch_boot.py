"""Governed dispatch backend for the SHADOW agent-runtime fleet (out-of-package).

`run_once.py` is prepare-only and imports the module named by
`AGENT_RUNTIME_QUEUE_MODULE`; this is that module. It assembles the governed
pipeline and runs ONE bounded batch for a single agent:

    job source  ->  BoundedDispatcher (single-agent, bounded, circuit-broken,
                    dedup, stale-refusal, kill-switch cancel)
                ->  processor  ->  MvlRuntime (advisory-only lifecycle)
                ->  PostgresPersistence (append-only agentic_runtime, LAB writer)

SAFETY POSTURE (why this is safe to run in LAB):
  * NON-AGENTIC — it cannot schedule itself (a deterministic external timer is the
    only caller), cannot extend a budget (budgets come from the frozen
    AgentDefinition and are enforced inside MvlRuntime), and cannot change any
    permission or config. There is no broker/order/2FA/execution/promotion call
    anywhere in the path (MvlRuntime + governed_output reject forbidden verbs).
  * DRIVER-ISOLATED — psycopg2 is imported ONLY in this out-of-package module
    (mirroring agent_runtime_read_boot.py); the `scripts/agent_runtime` package
    stays driver-free.
  * FAIL-CLOSED / NO FABRICATION — it refuses (does no work) unless the operator
    supplies a real write DSN (shadow_rw role) AND a provider module
    (`AGENT_RUNTIME_PROVIDER_MODULE`) exposing real model/retrieval providers and
    a bounded job source. It never ships a canned provider, so it cannot inflate
    the maturity board with hollow evidence.
  * KILL-SWITCHABLE — `should_cancel` observes the operator opt-in file
    (`/etc/tradeai/agent_runtime_enabled`); once it is gone, every remaining job
    in the batch is CANCELLED.

This module performs writes only to the LAB `agentic_runtime` schema through the
identity-verified PostgresPersistence (which rejects any non-shadow/lab writer).
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

# In-package (driver-free) governed pieces.
import sys
_PKG = Path(__file__).resolve().parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from agent_runtime.agents.dispatcher import BoundedDispatcher, JobOutcome, JobRequest, JobResult, batch_summary  # noqa: E402
from agent_runtime.agents.definitions import FLEET  # noqa: E402

DISPATCH_DSN_ENV = "AGENT_RUNTIME_DISPATCH_DSN"      # LAB shadow_rw writer DSN
PROVIDER_MODULE_ENV = "AGENT_RUNTIME_PROVIDER_MODULE"  # operator-supplied providers + job source
ENABLE_FILE_ENV = "AGENT_RUNTIME_ENABLED_FILE"
DEFAULT_ENABLE_FILE = "/etc/tradeai/agent_runtime_enabled"


class DispatchConfigError(RuntimeError):
    """Raised when the backend is asked to run without the operator wiring."""


def _enable_file() -> Path:
    return Path(os.environ.get(ENABLE_FILE_ENV) or DEFAULT_ENABLE_FILE)


def make_should_cancel() -> Callable[[], bool]:
    """Kill switch: cancel the moment the operator opt-in file is absent."""
    enable = _enable_file()
    return lambda: not enable.exists()


def _connection_factory(dsn: str) -> Callable[[], Any]:
    """Zero-arg factory returning a fresh autocommit-off connection. This is the
    ONLY driver import in the pipeline; PostgresPersistence verifies the role is a
    shadow/lab runtime writer before its first write."""
    import psycopg2  # driver import isolated to this out-of-package boot module

    def factory() -> Any:
        conn = psycopg2.connect(dsn)
        conn.autocommit = False
        return conn

    return factory


def build_persistence(dsn: str):
    """PostgresPersistence bound to the LAB writer DSN (identity-verified)."""
    from agent_runtime.persistence import PostgresPersistence

    return PostgresPersistence(_connection_factory(dsn))


def build_dispatcher(
    agent_id: str,
    *,
    processor: Callable[[JobRequest], Mapping[str, Any]],
    should_cancel: Callable[[], bool] | None = None,
    max_batch: int = 8,
) -> BoundedDispatcher:
    """Assemble the single-agent bounded dispatcher (pure; unit-testable)."""
    if agent_id not in FLEET:
        raise DispatchConfigError(f"unknown agent: {agent_id}")
    spec = FLEET[agent_id]
    return BoundedDispatcher(
        spec,
        processor,
        max_concurrency=max(1, int(max_batch)),
        should_cancel=should_cancel or make_should_cancel(),
    )


def _load_provider_module():
    name = os.environ.get(PROVIDER_MODULE_ENV)
    if not name:
        raise DispatchConfigError(
            f"no {PROVIDER_MODULE_ENV} configured. The dispatch backend ships no "
            "canned provider (it must never fabricate evidence); wire a module that "
            "exposes build_providers(agent_id) and job_source(agent_id, limit)."
        )
    return importlib.import_module(name)


def run_bounded_batch(agent_id: str, max_batch: int = 8) -> dict[str, Any]:
    """Entry point invoked by run_once.py. Fail-closed on missing operator wiring.

    The provider module (operator-supplied) must expose:
      * build_providers(agent_id) -> object with .retrieval, .model, .make_processor(persistence)
      * job_source(agent_id, limit) -> Sequence[JobRequest]
    so the real model/retrieval logic and the bounded job intake are owned and
    reviewed by the operator, not hard-wired here.
    """
    dsn = os.environ.get(DISPATCH_DSN_ENV)
    if not dsn:
        raise DispatchConfigError(
            f"no {DISPATCH_DSN_ENV} configured (LAB shadow_rw writer DSN required)."
        )
    provider_mod = _load_provider_module()
    persistence = build_persistence(dsn)
    providers = provider_mod.build_providers(agent_id)
    store = getattr(providers, "store", None)
    processor = providers.make_processor(persistence)
    jobs: Sequence[JobRequest] = list(provider_mod.job_source(agent_id, max_batch))

    run_ids: dict[str, str] = {}

    def _tracking_processor(job: JobRequest) -> Mapping[str, Any]:
        result = processor(job)
        run_id = str(result.get("run_id") or "")
        if run_id:
            run_ids[job.input_hash] = run_id
        return result

    dispatcher = build_dispatcher(agent_id, processor=_tracking_processor, max_batch=max_batch)
    results = dispatcher.process_batch(jobs)
    summary = batch_summary(results)
    summary["intake_acks"] = _ack_intake_outcomes(store, jobs, results, run_ids)
    summary["leased_run_ids"] = [run_ids[h] for h in run_ids]
    return summary


def _ack_intake_outcomes(
    store: Any,
    jobs: Sequence[JobRequest],
    results: list[JobResult],
    run_ids: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Ack leased trigger-intake rows when the provider uses the governed queue."""
    if store is None:
        return []
    by_hash = {job.input_hash: job for job in jobs}
    acks: list[dict[str, Any]] = []
    for result in results:
        job = by_hash.get(result.input_hash)
        if job is None or not job.intake_id:
            continue
        detail = {"intake_id": job.intake_id, "outcome": result.outcome.value}
        try:
            if result.outcome == JobOutcome.COMPLETED:
                run_id = run_ids.get(result.input_hash, "")
                store.ack_completed(job.intake_id, run_id=run_id)
                detail["state"] = "COMPLETED"
                detail["run_id"] = run_id
            elif result.outcome == JobOutcome.REFUSED_STALE:
                store.ack_refused_stale(job.intake_id, detail=result.detail)
                detail["state"] = "REFUSED_STALE"
            else:
                store.ack_failed(job.intake_id, detail=result.detail or result.outcome.value)
                detail["state"] = "FAILED"
        except Exception as exc:
            detail["state"] = "ACK_ERROR"
            detail["error"] = str(exc)
        acks.append(detail)
    return acks
