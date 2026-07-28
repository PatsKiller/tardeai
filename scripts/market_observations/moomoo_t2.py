#!/usr/bin/env python3
"""M3 Moomoo/T2 — order-book (L2) capability + CONSERVING arm-on-demand subscription.

Provides normalized Tier-2 order-book observations through the moomoo Stage-0 client boundary
(`scripts/moomoo/client.py`) — NEVER a direct OpenD connection, NEVER an order/unlock path. Two hard
properties:

1. **Conserve.** OpenD's live-subscription budget is scarce (L2 especially). This layer subscribes a
   symbol's book ONLY while it is "armed" — i.e. seconds/minutes from trading. `ArmedSubscriptionManager`
   caps the number of concurrent armed symbols to a hard budget and auto-disarms on TTL. Nothing is
   subscribed continuously; unarmed symbols cost nothing.
2. **Fail-closed.** Until OpenD is up AND a real L2 fetcher is wired, `entitlement()` resolves to
   `SCAFFOLD_ONLY` and `fetch_book()` returns None — no T2 capability is manufactured. It only ever
   returns a real book once OpenD is up AND a real L2 fetcher is wired AND the symbol is armed.
   (The authoritative single-owner lifecycle now lives in `scripts/moomoo/quote_gateway.py` +
   `subscription_manager.py` + `l2_feature_service.py`; this module remains the conserving
   arm-on-demand capability the shadow logger uses. The consumer path is NOT claimed live until an
   integration probe against a logged-in OpenD proves book+tape+quota round-trip.)
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

    # ── cross-invocation persistence (real conserving: survive the per-cron process boundary) ──
    def to_state(self, now: float) -> dict:
        self.prune(now)
        return {"armed": {s: {"armed_at": e.armed_at, "expires_at": e.expires_at, "reason": e.reason}
                          for s, e in self._armed.items()}}

    def load_state(self, state: dict) -> None:
        for s, d in (state or {}).get("armed", {}).items():
            self._armed[s.upper()] = ArmedEntry(s.upper(), float(d["armed_at"]),
                                                float(d["expires_at"]), d.get("reason", "restored"))


class MoomooT2Provider:
    """order-book (L2) provider through the Stage-0 client boundary. Read-only; conserving; fail-closed."""
    name = "moomoo"

    def __init__(self, client=None, book_fetcher: Optional[Callable[[str], dict]] = None,
                 manager: Optional[ArmedSubscriptionManager] = None,
                 book_releaser: Optional[Callable[[str], None]] = None):
        self._client = client                       # a MoomooClient (opend_up/health/get_quote); order methods never called
        self._book_fetcher = book_fetcher           # callable(symbol)->{bids,asks,ts} when real L2 is wired; else None
        self._book_releaser = book_releaser         # callable(symbol) -> drop the live L2 subscription
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
        # Actually release the OpenD subscription. Dropping it from the manager alone
        # would free the budget slot in our bookkeeping while the real subscription
        # stayed open at OpenD — the opposite of conserving.
        if self._book_releaser is not None:
            try:
                self._book_releaser(symbol)
            except Exception:
                pass

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


def sync_arm_from_states(provider: "MoomooT2Provider", symbol_to_state: dict, now: float,
                         arm_states: tuple = ("ARMED",)) -> dict:
    """Wire the trigger FSM to the L2 budget: ARM every symbol currently in an arm-state (ARMED =
    seconds/minutes from a fire) and DISARM everything else. Conserving — respects the hard budget
    (arms in stable order until full; the rest are reported as skipped, never force-subscribed)."""
    want = [s.upper() for s, st in symbol_to_state.items() if st in arm_states]
    have = set(provider.manager.armed_symbols(now))
    for s in sorted(have - set(want)):
        provider.disarm(s)                       # no longer imminent → free the budget
    armed, skipped = [], []
    for s in sorted(set(want)):
        (armed if provider.arm(s, now, reason="trigger_armed") else skipped).append(s)
    return {"armed": armed, "skipped_budget": skipped, "disarmed": sorted(have - set(want))}


def default_provider(*, live: bool = True) -> MoomooT2Provider:
    """Build the provider over the real Stage-0 MoomooClient.

    live=True wires a real futu transport + L2 book fetcher, so entitlement resolves
    to AVAILABLE_REALTIME once OpenD is logged in. live=False keeps the stub (CI).

    Previously this called `MoomooClient()` with no arguments — but `config` is
    required, so it raised TypeError, the bare `except` swallowed it, and the
    provider was built with client=None. opend_up() was therefore False no matter
    what OpenD was doing, pinning entitlement to SCAFFOLD_ONLY permanently. The
    exception is now narrowed and logged rather than silently discarded.
    """
    import logging
    log = logging.getLogger(__name__)

    client = None
    fetcher = None
    releaser = None
    try:
        try:
            from moomoo.client import MoomooClient, FutuTransport
            from moomoo.config import load_stage0_config
        except ModuleNotFoundError:
            from scripts.moomoo.client import MoomooClient, FutuTransport
            from scripts.moomoo.config import load_stage0_config

        cfg = load_stage0_config()          # falls back to the shipped example config
        if live:
            transport = FutuTransport(cfg.host, cfg.port,
                                      timeout=cfg.connect_timeout_seconds or 4.0)
            client = MoomooClient(cfg, transport=transport)
            # Bind the fetcher to the same transport so subscribe/unsubscribe and the
            # book read share one OpenD context (and one subscription budget).
            fetcher = transport.get_order_book
            releaser = transport.unsubscribe_book
        else:
            client = MoomooClient(cfg)      # StubTransport → SCAFFOLD_ONLY
    except Exception as e:                  # never let provider construction break a scan
        log.warning("moomoo provider unavailable (%s: %s) — SCAFFOLD_ONLY",
                    type(e).__name__, str(e)[:160])
        client, fetcher, releaser = None, None, None

    return MoomooT2Provider(client=client, book_fetcher=fetcher, book_releaser=releaser)
