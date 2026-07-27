#!/usr/bin/env python3
"""M3-S5.5 — bounded, provider-neutral concurrent acquisition.

Fan out per-provider fetch tasks under STRICT bounds (never one-thread-per-symbol): a global
concurrency cap AND per-provider caps, explicit deadlines, bounded retries with jitter (NEVER on an
auth/entitlement rejection), independent per-provider circuit breakers, and DETERMINISTIC result
ordering (results align to input-task order regardless of completion order). No network here — tasks
are opaque callables; providers own their own batching/rate limits.
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional


# ── typed failures: auth/entitlement are NEVER retried ──
class AuthError(Exception): ...
class EntitlementError(Exception): ...
class TransientError(Exception): ...


@dataclass
class ConcurrencyLimits:
    global_max: int = 8
    per_provider_max: dict = field(default_factory=lambda: {
        "alpaca": 4, "yahoo": 2, "schwab": 2, "moomoo": 1})   # moomoo: single gateway owner
    task_timeout_s: float = 10.0
    max_retries: int = 2
    retry_base_s: float = 0.20
    retry_jitter_s: float = 0.10
    breaker_threshold: int = 3        # consecutive failures → open
    breaker_cooldown_s: float = 30.0

    def provider_cap(self, provider: str) -> int:
        return int(self.per_provider_max.get(provider, 2))


@dataclass
class Task:
    provider: str
    key: str                          # label for ordering/provenance (e.g. "AAPL:bar")
    fn: Callable[[], Awaitable]        # async callable → Observation, or raises Auth/Entitlement/Transient


@dataclass
class ProviderCounters:
    success: int = 0
    failure: int = 0
    retry: int = 0
    timeout: int = 0
    throttled: int = 0                 # not retried (auth/entitlement)
    breaker_skipped: int = 0
    latency_ms_total: float = 0.0


@dataclass
class _Breaker:
    consecutive: int = 0
    open_until: float = -1.0           # monotonic seconds; open while now < open_until


class BoundedRunner:
    """Runs Tasks under global + per-provider semaphores with retry/breaker. `clock` returns
    monotonic seconds (injectable for tests); `rng` supplies jitter (injectable/seedable)."""

    def __init__(self, limits: ConcurrencyLimits, clock: Optional[Callable[[], float]] = None,
                 rng: Optional[random.Random] = None, sleeper: Optional[Callable[[float], Awaitable]] = None):
        self.limits = limits
        self._clock = clock or (lambda: asyncio.get_event_loop().time())
        self._rng = rng or random.Random(1729)      # seeded default → reproducible jitter
        self._sleep = sleeper or asyncio.sleep
        self.counters: dict[str, ProviderCounters] = {}
        self._breakers: dict[str, _Breaker] = {}
        self._live = 0
        self._max_live = 0
        self._live_by_provider: dict[str, int] = {}
        self._max_live_by_provider: dict[str, int] = {}

    def _c(self, p: str) -> ProviderCounters:
        return self.counters.setdefault(p, ProviderCounters())

    def _b(self, p: str) -> _Breaker:
        return self._breakers.setdefault(p, _Breaker())

    def _enter(self, p: str):
        self._live += 1
        self._max_live = max(self._max_live, self._live)
        self._live_by_provider[p] = self._live_by_provider.get(p, 0) + 1
        self._max_live_by_provider[p] = max(self._max_live_by_provider.get(p, 0), self._live_by_provider[p])

    def _exit(self, p: str):
        self._live -= 1
        self._live_by_provider[p] -= 1

    async def _run_one(self, task: Task, gsem: asyncio.Semaphore, psems: dict[str, asyncio.Semaphore]):
        p = task.provider
        br = self._b(p)
        # circuit breaker: skip while open
        if br.open_until >= 0 and self._clock() < br.open_until:
            self._c(p).breaker_skipped += 1
            return None
        async with gsem:
            async with psems[p]:
                self._enter(p)
                t0 = self._clock()
                try:
                    for attempt in range(self.limits.max_retries + 1):
                        try:
                            obs = await asyncio.wait_for(task.fn(), timeout=self.limits.task_timeout_s)
                            self._c(p).success += 1
                            br.consecutive = 0
                            self._c(p).latency_ms_total += (self._clock() - t0) * 1000.0
                            return obs
                        except (AuthError, EntitlementError):
                            self._c(p).throttled += 1          # NEVER retried
                            self._trip(br, p)
                            return None
                        except asyncio.TimeoutError:
                            self._c(p).timeout += 1
                            last = TransientError("timeout")
                        except TransientError as e:
                            last = e
                        except Exception as e:                 # unknown → treat as transient once
                            last = TransientError(str(e))
                        # retryable path
                        if attempt < self.limits.max_retries:
                            self._c(p).retry += 1
                            delay = self.limits.retry_base_s * (2 ** attempt) + self._rng.uniform(0, self.limits.retry_jitter_s)
                            await self._sleep(delay)
                        else:
                            self._c(p).failure += 1
                            self._trip(br, p)
                            return None
                finally:
                    self._exit(p)

    def _trip(self, br: _Breaker, p: str):
        br.consecutive += 1
        if br.consecutive >= self.limits.breaker_threshold:
            br.open_until = self._clock() + self.limits.breaker_cooldown_s

    async def run(self, tasks: list[Task]) -> list:
        """Run all tasks; return results aligned to `tasks` order (Observation | None)."""
        gsem = asyncio.Semaphore(self.limits.global_max)
        psems = {p: asyncio.Semaphore(self.limits.provider_cap(p))
                 for p in {t.provider for t in tasks}}
        coros = [self._run_one(t, gsem, psems) for t in tasks]
        # gather preserves input order in its result list → deterministic ordering
        return await asyncio.gather(*coros)

    @property
    def max_concurrency(self) -> int:
        return self._max_live

    def max_concurrency_for(self, provider: str) -> int:
        return self._max_live_by_provider.get(provider, 0)


def run_bounded(tasks: list[Task], limits: ConcurrencyLimits, **kw) -> tuple[list, BoundedRunner]:
    """Sync entrypoint: returns (results_aligned_to_tasks, runner_with_counters)."""
    runner = BoundedRunner(limits, **kw)
    results = asyncio.run(runner.run(tasks))
    return results, runner
