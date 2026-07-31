from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping, Sequence

from .base import ShadowAgentSpec

DISPATCHER_CONTRACT = "agent-runtime-bounded-dispatcher-v1"


class JobOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REFUSED_STALE = "REFUSED_STALE"
    REFUSED_DUPLICATE = "REFUSED_DUPLICATE"
    REFUSED_DISABLED = "REFUSED_DISABLED"
    REFUSED_CAPACITY = "REFUSED_CAPACITY"
    REFUSED_WRONG_AGENT = "REFUSED_WRONG_AGENT"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class JobRequest:
    agent_id: str
    job_type: str
    input_hash: str
    enqueued_at: str  # ISO-8601
    dedup_value: str
    trigger_kind: str = ""
    intake_id: str | None = None
    payload: Mapping[str, Any] | None = None

    def enqueued_dt(self) -> datetime:
        value = datetime.fromisoformat(self.enqueued_at)
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class JobResult:
    input_hash: str
    outcome: JobOutcome
    detail: str = ""


@dataclass
class CircuitBreaker:
    """Consecutive-failure breaker. Pure in-memory state; controls nothing but the
    dispatcher's own willingness to accept the next job."""

    threshold: int
    consecutive_failures: int = 0
    _open: bool = field(default=False)

    @property
    def is_open(self) -> bool:
        return self._open

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self._open = False

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.threshold:
            self._open = True

    def reset(self) -> None:
        self.consecutive_failures = 0
        self._open = False


class BoundedDispatcher:
    """Deterministic, NON-agentic bounded-queue runner for ONE agent.

    This class is the queue-side control plane that an external, deterministic
    scheduler (a systemd timer running ``--once``) invokes. It enforces, per
    bounded batch: single-agent scoping, one queue, a concurrency cap, dedup /
    idempotency by ``dedup_value``, stale-input refusal, a consecutive-failure
    circuit breaker, and cooperative cancellation. It NEVER schedules itself,
    opens a database or a socket, spawns a process, or reads a secret — the job
    ``processor`` is injected and owns the governed runtime call.
    """

    def __init__(
        self,
        spec: ShadowAgentSpec,
        processor: Callable[[JobRequest], Mapping[str, Any]],
        *,
        max_concurrency: int = 1,
        clock: Callable[[], datetime] | None = None,
        breaker: CircuitBreaker | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> None:
        spec.validate()
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self.spec = spec
        self.processor = processor
        self.max_concurrency = max_concurrency
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.breaker = breaker or CircuitBreaker(threshold=spec.circuit_breaker_trips_open_after)
        self.should_cancel = should_cancel or (lambda: False)
        self._in_progress = False  # re-entrancy guard (no overlapping batches)

    def process_batch(self, jobs: Sequence[JobRequest]) -> list[JobResult]:
        if self._in_progress:
            raise RuntimeError("dispatcher is already processing a batch (concurrency guard)")
        self._in_progress = True
        try:
            return self._run(jobs)
        finally:
            self._in_progress = False

    def _run(self, jobs: Sequence[JobRequest]) -> list[JobResult]:
        results: list[JobResult] = []
        seen: set[str] = set()
        accepted = 0
        now = self._now()
        for job in jobs:
            if self.should_cancel():
                results.append(JobResult(job.input_hash, JobOutcome.CANCELLED, "operator cancellation observed"))
                continue
            if job.agent_id != self.spec.agent_id:
                results.append(JobResult(job.input_hash, JobOutcome.REFUSED_WRONG_AGENT, "queue is single-agent scoped"))
                continue
            if not self.spec.is_operable_now:
                results.append(JobResult(job.input_hash, JobOutcome.REFUSED_DISABLED, "agent is disabled / not SHADOW-operable"))
                continue
            if self.breaker.is_open:
                results.append(JobResult(job.input_hash, JobOutcome.CIRCUIT_OPEN, "circuit breaker is open"))
                continue
            if job.dedup_value in seen:
                results.append(JobResult(job.input_hash, JobOutcome.REFUSED_DUPLICATE, "duplicate dedup_value in batch"))
                continue
            if self._is_stale(job, now):
                results.append(JobResult(job.input_hash, JobOutcome.REFUSED_STALE, "input older than stale_input_seconds"))
                continue
            if accepted >= self.max_concurrency and self.max_concurrency < len(jobs):
                # Capacity is expressed as the number of jobs a single bounded
                # invocation will admit; the remainder is left on the queue.
                results.append(JobResult(job.input_hash, JobOutcome.REFUSED_CAPACITY, "batch concurrency cap reached"))
                continue
            seen.add(job.dedup_value)
            accepted += 1
            results.append(self._process_one(job))
        return results

    def _process_one(self, job: JobRequest) -> JobResult:
        try:
            self.processor(job)
        except Exception as exc:  # noqa: BLE001 — outcome is recorded, breaker advances
            self.breaker.record_failure()
            return JobResult(job.input_hash, JobOutcome.FAILED, f"{type(exc).__name__}: {exc}")
        self.breaker.record_success()
        return JobResult(job.input_hash, JobOutcome.COMPLETED, "processed")

    def _is_stale(self, job: JobRequest, now: datetime) -> bool:
        elapsed = (now - job.enqueued_dt()).total_seconds()
        return elapsed > self.spec.stale_input_seconds

    def _now(self) -> datetime:
        value = self.clock()
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def batch_summary(results: Sequence[JobResult]) -> dict[str, Any]:
    counts: dict[str, int] = {outcome.value: 0 for outcome in JobOutcome}
    for result in results:
        counts[result.outcome.value] += 1
    return {
        "contract": DISPATCHER_CONTRACT,
        "total": len(results),
        "outcomes": counts,
    }
