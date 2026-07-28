#!/usr/bin/env python3
"""Legacy Moomoo/T2 observation helpers.

This module remains a pure normalization and intent helper for the scalp shadow logger.
It must not create a production OpenD context.  A cron process is not the canonical
single-owner gateway and cannot safely own subscriptions that the ActiveTrader server
cannot observe or reconcile.

The future dedicated gateway service may inject a client/book fetcher explicitly.  The
``default_provider`` is deliberately scaffold-only, even when ``live=True`` is passed by
legacy callers.  Read plane only; no order or trade-unlock path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

try:
    from observation import (
        make_observation,
        Observation,
        ObservationType,
        EntitlementState,
        FreshnessState,
        QualityState,
        DataTier,
    )
    import scalp_t2_metrics as t2
except ModuleNotFoundError:
    from .observation import (
        make_observation,
        Observation,
        ObservationType,
        EntitlementState,
        FreshnessState,
        QualityState,
        DataTier,
    )
    import pathlib as _pl
    import sys as _sys

    _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
    import scalp_t2_metrics as t2


@dataclass
class ArmedEntry:
    symbol: str
    armed_at: float
    expires_at: float
    reason: str


class ArmedSubscriptionManager:
    """Local desired-intent budget; it never proves a live OpenD subscription."""

    def __init__(self, max_armed: int = 8, ttl_seconds: float = 120.0):
        self.max_armed = int(max_armed)
        self.ttl_seconds = float(ttl_seconds)
        self._armed: dict[str, ArmedEntry] = {}
        self.rejected_budget = 0

    def prune(self, now: float) -> None:
        for symbol in [s for s, entry in self._armed.items() if entry.expires_at <= now]:
            del self._armed[symbol]

    def arm(self, symbol: str, now: float, reason: str = "near_trigger") -> bool:
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

    def to_state(self, now: float) -> dict:
        self.prune(now)
        return {
            "armed": {
                symbol: {
                    "armed_at": entry.armed_at,
                    "expires_at": entry.expires_at,
                    "reason": entry.reason,
                }
                for symbol, entry in self._armed.items()
            }
        }

    def load_state(self, state: dict) -> None:
        for symbol, data in (state or {}).get("armed", {}).items():
            self._armed[symbol.upper()] = ArmedEntry(
                symbol.upper(),
                float(data["armed_at"]),
                float(data["expires_at"]),
                data.get("reason", "restored"),
            )


class MoomooT2Provider:
    """Injected order-book normalizer; default construction remains scaffold-only."""

    name = "moomoo"

    def __init__(
        self,
        client=None,
        book_fetcher: Optional[Callable[[str], dict]] = None,
        manager: Optional[ArmedSubscriptionManager] = None,
        book_releaser: Optional[Callable[[str], None]] = None,
    ):
        self._client = client
        self._book_fetcher = book_fetcher
        self._book_releaser = book_releaser
        self.manager = manager or ArmedSubscriptionManager()

    def opend_up(self) -> bool:
        try:
            return bool(self._client is not None and self._client.opend_up)
        except Exception:
            return False

    def entitlement(self) -> EntitlementState:
        if self.opend_up() and self._book_fetcher is not None:
            return EntitlementState.AVAILABLE_REALTIME
        return EntitlementState.SCAFFOLD_ONLY

    def arm(self, symbol: str, now: float, reason: str = "near_trigger") -> bool:
        return self.manager.arm(symbol, now, reason)

    def disarm(self, symbol: str) -> None:
        self.manager.disarm(symbol)
        if self._book_releaser is not None:
            try:
                self._book_releaser(symbol)
            except Exception:
                pass

    def fetch_book(self, symbol: str, now: float, now_iso: str) -> Optional[Observation]:
        if not self.manager.is_armed(symbol, now):
            return None
        if not self.opend_up() or self._book_fetcher is None:
            return None
        raw = self._book_fetcher(symbol)
        if not raw:
            return None
        return self.normalize_book(symbol, raw, now_iso)

    @staticmethod
    def normalize_book(symbol: str, raw: dict, now_iso: str, levels: int = 5) -> Observation:
        bids = raw.get("bids") or []
        asks = raw.get("asks") or []
        summary = t2.book_summary(bids, asks, levels)
        payload = {
            "bids": [[float(price), float(size)] for price, size in bids[:levels]],
            "asks": [[float(price), float(size)] for price, size in asks[:levels]],
            **summary,
        }
        return make_observation(
            source_system="moomoo",
            symbol=symbol,
            observation_type=ObservationType.ORDER_BOOK,
            payload=payload,
            provider_at=raw.get("ts"),
            observed_at=raw.get("ts"),
            received_at=now_iso,
            normalized_at=now_iso,
            entitlement_state=EntitlementState.AVAILABLE_REALTIME,
            feed="moomoo_totalview",
            freshness_state=FreshnessState.FRESH,
            quality_state=QualityState.OK,
            data_tier=DataTier.T2,
            sequence_id=raw.get("seq"),
        )


def sync_arm_from_states(
    provider: MoomooT2Provider,
    symbol_to_state: dict,
    now: float,
    arm_states: tuple = ("ARMED",),
) -> dict:
    """Persist desired arm intent only; no default provider performs live I/O."""
    wanted = [symbol.upper() for symbol, state in symbol_to_state.items() if state in arm_states]
    have = set(provider.manager.armed_symbols(now))
    for symbol in sorted(have - set(wanted)):
        provider.disarm(symbol)
    armed: list[str] = []
    skipped: list[str] = []
    for symbol in sorted(set(wanted)):
        (armed if provider.arm(symbol, now, reason="trigger_armed") else skipped).append(symbol)
    return {"armed": armed, "skipped_budget": skipped, "disarmed": sorted(have - set(wanted))}


def default_provider(*, live: bool = False) -> MoomooT2Provider:
    """Return a scaffold-only provider.

    ``live`` is retained for source compatibility but intentionally ignored.  The legacy
    shadow logger must never open a second production OpenD context.  A future dedicated
    gateway client may inject an already-owned client/fetcher explicitly.
    """
    import logging

    if live:
        logging.getLogger(__name__).warning(
            "legacy in-process Moomoo provider disabled; recording arm intent only"
        )
    try:
        try:
            from moomoo.client import MoomooClient
            from moomoo.config import load_stage0_config
        except ModuleNotFoundError:
            from scripts.moomoo.client import MoomooClient
            from scripts.moomoo.config import load_stage0_config

        client = MoomooClient(load_stage0_config())  # StubTransport only; no OpenQuoteContext
    except Exception:
        client = None
    return MoomooT2Provider(client=client, book_fetcher=None, book_releaser=None)
