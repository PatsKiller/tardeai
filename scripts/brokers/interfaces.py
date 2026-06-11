"""Broker abstraction interfaces (ADR-B1). Protocols, not ABCs — existing adapters conform structurally."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class BrokerAuthProvider(Protocol):
    def health(self) -> dict: ...


@runtime_checkable
class BrokerAccountService(Protocol):
    def get_account(self, account_key: str) -> dict: ...
    def get_positions(self, account_key: str) -> dict | list: ...


@runtime_checkable
class BrokerMarketDataAdapter(Protocol):
    def get_quote(self, symbol: str) -> dict: ...
    def get_bars(self, symbol: str, start: str, end: str, timeframe: str) -> list: ...


@runtime_checkable
class BrokerOrderTranslator(Protocol):
    """PURE: OrderIntent -> {'orders': [payload...], 'notes': [...], 'unverified': [...]} — no I/O."""
    def translate(self, intent) -> dict: ...


@runtime_checkable
class BrokerOrderAdapter(Protocol):
    def submit(self, intent, translation) -> dict: ...
    def replace(self, intent, broker_order_id: str) -> dict: ...
    def cancel(self, broker_order_id: str) -> dict: ...
    def get_status(self, account_key: str, order_id: str) -> dict: ...


class BrokerError(Exception):
    """Normalized broker error taxonomy root."""


class BrokerRateLimited(BrokerError): ...
class BrokerRejected(BrokerError): ...
class BrokerUnavailable(BrokerError): ...
