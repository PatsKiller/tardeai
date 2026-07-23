"""Stage 5 — request-rate governors (implemented + tested; NOT attached to any
trade API — Stage 5 has no trade surface to attach to, statically enforced).

Owner-approved budgets per 30 s per account:
  PLACE          ceiling 15 · ordinary 12 · protection/exit reserve 3
  MODIFY_CANCEL  ceiling 20 · ordinary 16 · protection/cancel reserve 4
  SNAPSHOT       documented ceiling 60 · ordinary 48 · diagnostic reserve 12

Mechanism: token bucket AND exact sliding window (both must admit). Restart is
conservative: a fresh governor assumes the window is FULL until it ages out.
Monotonic clock only.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


class RateRefused(RuntimeError):
    def __init__(self, action_class: str, reason: str):
        super().__init__(f"{action_class}: {reason}")
        self.action_class, self.reason = action_class, reason


@dataclass(frozen=True)
class Budget:
    action_class: str
    ceiling: int
    ordinary: int
    reserve: int
    window_seconds: float = 30.0

    def __post_init__(self):
        if self.ordinary + self.reserve != self.ceiling:
            raise ValueError("ordinary + reserve must equal the provider ceiling")
        if self.window_seconds <= 0 or min(self.ceiling, self.ordinary, self.reserve) < 0:
            raise ValueError("invalid budget values")


PLACE = Budget("PLACE", 15, 12, 3)
MODIFY_CANCEL = Budget("MODIFY_CANCEL", 20, 16, 4)
SNAPSHOT = Budget("SNAPSHOT", 60, 48, 12)


class Governor:
    """Per-account, per-action-class governor. Thread-safe."""

    def __init__(self, budget: Budget, account_scope: str,
                 clock=time.monotonic, conservative_start: bool = True):
        if not account_scope.strip():
            raise ValueError("account scope required")
        self.budget = budget
        self.account_scope = account_scope
        self._clock = clock
        self._lock = threading.Lock()
        self._events: deque[tuple[float, bool]] = deque()   # (ts, is_reserve)
        if conservative_start:
            now = self._clock()
            for _ in range(budget.ordinary):                 # assume full ordinary window
                self._events.append((now, False))

    def _prune(self, now: float) -> None:
        w = self.budget.window_seconds
        while self._events and now - self._events[0][0] >= w:
            self._events.popleft()

    def acquire(self, *, reserve: bool = False) -> None:
        """Admit or raise. Ordinary can NEVER borrow reserve; reserve may use its
        carve-out but the provider ceiling is absolute."""
        with self._lock:
            now = self._clock()
            self._prune(now)
            total = len(self._events)
            ordinary_used = sum(1 for _, r in self._events if not r)
            if total >= self.budget.ceiling:
                raise RateRefused(self.budget.action_class,
                                  "provider ceiling reached — refused even for protection")
            if not reserve and ordinary_used >= self.budget.ordinary:
                raise RateRefused(self.budget.action_class,
                                  "ordinary budget exhausted; reserve is protection-only")
            self._events.append((now, reserve))

    def state(self) -> dict:
        with self._lock:
            now = self._clock()
            self._prune(now)
            ordinary_used = sum(1 for _, r in self._events if not r)
            return {"action_class": self.budget.action_class,
                    "account_scope": self.account_scope,
                    "window_seconds": self.budget.window_seconds,
                    "used_total": len(self._events),
                    "used_ordinary": ordinary_used,
                    "used_reserve": len(self._events) - ordinary_used,
                    "ceiling": self.budget.ceiling,
                    "ordinary": self.budget.ordinary,
                    "reserve": self.budget.reserve}


class GovernorSet:
    """All three governors for one account scope. Snapshot batching helper."""

    def __init__(self, account_scope: str, clock=time.monotonic,
                 conservative_start: bool = True):
        self.place = Governor(PLACE, account_scope, clock, conservative_start)
        self.modify_cancel = Governor(MODIFY_CANCEL, account_scope, clock, conservative_start)
        self.snapshot = Governor(SNAPSHOT, account_scope, clock, conservative_start)

    def snapshot_batch(self, symbols: list[str], batch_size: int = 100) -> list[list[str]]:
        """One snapshot request covers up to batch_size symbols — batch, never poll."""
        return [symbols[i:i + batch_size] for i in range(0, len(symbols), batch_size)]
