#!/usr/bin/env python3
"""M3 Moomoo/T2 — order-book (L2) capability + CONSERVING arm-on-demand subscription.

Provides normalized Tier-2 order-book observations through the moomoo Stage-0 client boundary
(`scripts/moomoo/client.py`) — NEVER a direct OpenD connection, NEVER an order/unlock path. Two hard
properties:

1. **Conserve.** OpenD's live-subscription budget is scarce (L2 especially). This layer subscribes a
   symbol's book ONLY while it is "armed" — i.e. seconds/minutes from trading. `ArmedSubscriptionManager`
   caps the number of concurrent armed symbols to a hard budget and auto-disarms on TTL. Nothing is
   subscribed continuously; unarmed symbols cost nothing.
2. **Fail-closed.** OpenD is not configured on this host, so `entitlement()` resolves to
   `SCAFFOLD_ONLY` and `fetch_book()` returns None — no T2 capability is manufactured. It only ever
   returns a real book once OpenD is up AND a real L2 fetcher is wired AND the symbol is armed.

NOT wired into the shadow logger (operator: capability + tests only; activate on-demand later).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

try:
    from observation import (make_observation, Observation, ObservationType, EntitlementState,
                             FreshnessState, QualityState, DataTier)
    import scalp_t2_metrics as t2
except ModuleNotFoundError:
    from .observation import (make_observation, Observation, ObservationType, EntitlementState,
                              FreshnessState, QualityState, DataTier)
    import sys as _sys, pathlib as _pl
    _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
    import scalp_t2_metrics as t2


@dataclass
class ArmedEntry:
    symbol: str
    armed_at: float
    expires_at: float
    reason: str


class ArmedSubscriptionManager:
    """CONSERVING on-demand budget. Arm a symbol only when it is SECONDS/MINUTES from trading; only
    armed symbols are ever subscribed at OpenD, up to `max_armed` (the hard OpenD quote budget).
    Auto-disarm on TTL. `now` is monotonic seconds supplied by the caller (deterministic/testable)."""

    def __init__(self, max_armed: int = 8, ttl_seconds: float = 120.0):
        self.max_armed = int(max_armed)
        self.ttl_seconds = float(ttl_seconds)
        self._armed: dict[str, ArmedEntry] = {}
        self.rejected_budget = 0            # count of arm() calls refused for budget (observability)

    def prune(self, now: float) -> None:
        for s in [s for s, e in self._armed.items() if e.expires_at <= now]:
            del self._armed[s]

    def arm(self, symbol: str, now: float, reason: str = "near_trigger") -> bool:
        """Arm (or refresh) a symbol. Returns False WITHOUT evicting when the budget is full — the
        caller must disarm something first (never silently blow the OpenD budget)."""
        symbol = symbol.upper()
        self.prune(now)
        if symbol in self._armed:
            self._armed[symbol].expires_at = now + self.ttl_seconds
            return True
        if len(self._armed) >= self.max_armed:
            self.rejected_budget += 1
            return False
        self._armed[symbol] = ArmedEntry(symbol, now, now + self.ttl_seconds, reason)
        return True

    def disarm(self, symbol: str) -> None:
        self._armed.pop(symbol.upper(), None)

    def is_armed(self, symbol: str, now: float) -> bool:
        self.prune(now)
        return symbol.upper() in self._armed

    def armed_symbols(self, now: float) -> list[str]:
        self.prune(now)
        return sorted(self._armed)

    def budget_used(self, now: float) -> tuple[int, int]:
        self.prune(now)
        return len(self._armed), self.max_armed


class MoomooT2Provider:
    """order-book (L2) provider through the Stage-0 client boundary. Read-only; conserving; fail-closed."""
    name = "moomoo"

    def __init__(self, client=None, book_fetcher: Optional[Callable[[str], dict]] = None,
                 manager: Optional[ArmedSubscriptionManager] = None):
        self._client = client                       # a MoomooClient (opend_up/health/get_quote); order methods never called
        self._book_fetcher = book_fetcher           # callable(symbol)->{bids,asks,ts} when real L2 is wired; else None
        self.manager = manager or ArmedSubscriptionManager()

    def opend_up(self) -> bool:
        try:
            return bool(self._client is not None and self._client.opend_up)
        except Exception:
            return False

    def entitlement(self) -> EntitlementState:
        """Real-time T2 only when OpenD is up AND a real L2 fetcher is wired; otherwise SCAFFOLD_ONLY.
        Never manufactures a T2 capability from scaffolding."""
        if self.opend_up() and self._book_fetcher is not None:
            return EntitlementState.AVAILABLE_REALTIME
        return EntitlementState.SCAFFOLD_ONLY

    # ── conserving arm/disarm (only armed symbols cost OpenD budget) ──
    def arm(self, symbol: str, now: float, reason: str = "near_trigger") -> bool:
        return self.manager.arm(symbol, now, reason)

    def disarm(self, symbol: str) -> None:
        self.manager.disarm(symbol)

    def fetch_book(self, symbol: str, now: float, now_iso: str) -> Optional[Observation]:
        """Return a normalized T2 ORDER_BOOK Observation — ONLY if the symbol is armed AND OpenD is up
        AND a real L2 fetcher is wired. Unarmed / scaffold / down → None (conserve + fail-closed)."""
        if not self.manager.is_armed(symbol, now):
            return None                              # not imminent → do not spend OpenD budget
        if not self.opend_up() or self._book_fetcher is None:
            return None                              # SCAFFOLD_ONLY / OpenD down → fail-closed
        raw = self._book_fetcher(symbol)             # {bids:[(p,s)…], asks:[…], ts}
        if not raw:
            return None
        return self.normalize_book(symbol, raw, now_iso)

    @staticmethod
    def normalize_book(symbol: str, raw: dict, now_iso: str, levels: int = 5) -> Observation:
        bids = raw.get("bids") or []
        asks = raw.get("asks") or []
        summ = t2.book_summary(bids, asks, levels)
        payload = {
            "bids": [[float(p), float(s)] for p, s in bids[:levels]],
            "asks": [[float(p), float(s)] for p, s in asks[:levels]],
            **summ,
        }
        return make_observation(
            source_system="moomoo", symbol=symbol, observation_type=ObservationType.ORDER_BOOK,
            payload=payload, provider_at=raw.get("ts"), observed_at=raw.get("ts"),
            received_at=now_iso, normalized_at=now_iso,
            entitlement_state=EntitlementState.AVAILABLE_REALTIME, feed="moomoo_totalview",
            freshness_state=FreshnessState.FRESH, quality_state=QualityState.OK,
            data_tier=DataTier.T2, sequence_id=raw.get("seq"))


def default_provider() -> MoomooT2Provider:
    """Build the provider over the real Stage-0 MoomooClient (no L2 fetcher wired → SCAFFOLD_ONLY)."""
    try:
        try:
            from moomoo.client import MoomooClient  # scripts on path
        except ModuleNotFoundError:
            from scripts.moomoo.client import MoomooClient
        client = MoomooClient()
    except Exception:
        client = None
    return MoomooT2Provider(client=client, book_fetcher=None)   # no fetcher today → conserving + fail-closed
