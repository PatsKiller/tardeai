"""Read-only Moomoo quote-gateway primitives.

The in-memory gateway is transport-agnostic and bounded. Production ownership is not
created here: ActiveTrader currently keeps production runtime disabled until a dedicated
long-lived gateway/IPC service exists. Tests inject ``MockTransport`` to exercise quota,
subscription, freshness, and feature behavior without OpenD.

No order, trade-unlock, credential, database-write, or LLM path exists in this module.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Protocol


class GatewayTransport(Protocol):
    def ping(self) -> bool: ...
    def entitlement_ok(self) -> bool: ...
    def query_subscription(self, is_all_conn: bool = True) -> dict: ...
    def subscribe(self, symbol: str, subtypes: list[str]) -> tuple[bool, str]: ...
    def unsubscribe(self, symbol: str, subtypes: list[str]) -> tuple[bool, str]: ...
    def get_order_book(self, symbol: str, levels: int = 10) -> dict: ...


@dataclass
class BookSnapshot:
    symbol: str
    bids: list
    asks: list
    provider_at: Optional[str]
    received_at: str
    sequence_id: Optional[int] = None

    @property
    def crossed(self) -> bool:
        if not self.bids or not self.asks:
            return False
        try:
            return float(self.bids[0][0]) > float(self.asks[0][0])
        except (TypeError, ValueError, IndexError):
            return False


@dataclass
class TapePrint:
    price: float
    size: float
    side: Optional[str]
    provider_at: Optional[str]
    received_at: str


@dataclass
class QuoteTick:
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float]
    provider_at: Optional[str]
    received_at: str


class QuoteGateway:
    """Bounded read gateway over one explicitly injected transport."""

    def __init__(self, transport: GatewayTransport, *, tape_maxlen: int = 256):
        self._t = transport
        self._lock = threading.RLock()
        self._books: dict[str, BookSnapshot] = {}
        self._tape: dict[str, Deque[TapePrint]] = {}
        self._quotes: dict[str, QuoteTick] = {}
        self._tape_maxlen = int(tape_maxlen)

    def ping(self) -> bool:
        try:
            return bool(self._t.ping())
        except Exception:
            return False

    def entitlement_ok(self) -> bool:
        try:
            return bool(self._t.entitlement_ok())
        except Exception:
            return False

    def query_subscription(self, is_all_conn: bool = True) -> dict:
        try:
            return dict(self._t.query_subscription(is_all_conn=is_all_conn) or {})
        except Exception:
            return {}

    def subscribe(self, symbol: str, subtypes: list[str]) -> tuple[bool, str]:
        try:
            return self._t.subscribe(symbol, list(subtypes))
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def unsubscribe(self, symbol: str, subtypes: list[str]) -> tuple[bool, str]:
        try:
            return self._t.unsubscribe(symbol, list(subtypes))
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def on_book_push(self, snapshot: BookSnapshot) -> None:
        with self._lock:
            self._books[snapshot.symbol.upper()] = snapshot

    def on_tape_push(self, symbol: str, prints: list[TapePrint]) -> None:
        with self._lock:
            buffer = self._tape.setdefault(
                symbol.upper(), deque(maxlen=self._tape_maxlen)
            )
            buffer.extend(prints)

    def on_quote_push(self, symbol: str, tick: QuoteTick) -> None:
        with self._lock:
            self._quotes[symbol.upper()] = tick

    def poll_book(
        self, symbol: str, received_at: str, levels: int = 10
    ) -> Optional[BookSnapshot]:
        try:
            raw = self._t.get_order_book(symbol, levels=levels)
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None
        snapshot = BookSnapshot(
            symbol=symbol.upper(),
            bids=list(raw.get("bids") or []),
            asks=list(raw.get("asks") or []),
            provider_at=raw.get("ts"),
            received_at=received_at,
            sequence_id=raw.get("seq"),
        )
        self.on_book_push(snapshot)
        return snapshot

    def latest_book(self, symbol: str) -> Optional[BookSnapshot]:
        with self._lock:
            return self._books.get(symbol.upper())

    def tape(self, symbol: str) -> list[TapePrint]:
        with self._lock:
            return list(self._tape.get(symbol.upper()) or [])

    def latest_quote(self, symbol: str) -> Optional[QuoteTick]:
        with self._lock:
            return self._quotes.get(symbol.upper())

    def clear_symbol(self, symbol: str) -> None:
        with self._lock:
            self._books.pop(symbol.upper(), None)
            self._tape.pop(symbol.upper(), None)
            self._quotes.pop(symbol.upper(), None)


class MockTransport:
    """Programmable transport with hard simultaneous-quota enforcement."""

    def __init__(
        self,
        *,
        up: bool = True,
        entitled: bool = True,
        total_quota: int = 200,
        other_connection_usage: int = 0,
    ):
        self.up = up
        self.entitled = entitled
        self.total_quota = int(total_quota)
        self.other_connection_usage = int(other_connection_usage)
        self.subs: dict[str, set[str]] = {}
        self.subscribe_calls: list[tuple[str, tuple[str, ...]]] = []
        self.unsubscribe_calls: list[tuple[str, tuple[str, ...]]] = []
        self._books: dict[str, dict] = {}
        self.fail_next_subscribe = False
        self.fail_next_unsubscribe = False
        self.fail_quota_query = False

    def ping(self) -> bool:
        return self.up

    def entitlement_ok(self) -> bool:
        return self.up and self.entitled

    def _own_units(self) -> int:
        return sum(len(subtypes) for subtypes in self.subs.values())

    def query_subscription(self, is_all_conn: bool = True) -> dict:
        if self.fail_quota_query:
            return {}
        used = self._own_units() + (
            self.other_connection_usage if is_all_conn else 0
        )
        return {
            "total_quota": self.total_quota,
            "total_used": used,
            "remain": max(0, self.total_quota - used),
            "own_used": self._own_units(),
            "other_connection_usage": self.other_connection_usage if is_all_conn else 0,
            "subscriptions_by_type": self._by_type(),
        }

    def _by_type(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for subtype_set in self.subs.values():
            for subtype in subtype_set:
                result[subtype] = result.get(subtype, 0) + 1
        return result

    def subscribe(self, symbol: str, subtypes: list[str]) -> tuple[bool, str]:
        if not self.up:
            return False, "opend down"
        if self.fail_next_subscribe:
            self.fail_next_subscribe = False
            return False, "simulated subscribe failure"
        normalized = symbol.upper()
        existing = self.subs.get(normalized, set())
        additions = set(subtypes) - existing
        hard_used = self._own_units() + self.other_connection_usage
        if hard_used + len(additions) > self.total_quota:
            return False, "hard quota exceeded"
        self.subscribe_calls.append((normalized, tuple(subtypes)))
        self.subs.setdefault(normalized, set()).update(subtypes)
        return True, "ok"

    def unsubscribe(self, symbol: str, subtypes: list[str]) -> tuple[bool, str]:
        normalized = symbol.upper()
        self.unsubscribe_calls.append((normalized, tuple(subtypes)))
        if self.fail_next_unsubscribe:
            self.fail_next_unsubscribe = False
            return False, "simulated unsubscribe failure"
        if normalized in self.subs:
            for subtype in subtypes:
                self.subs[normalized].discard(subtype)
            if not self.subs[normalized]:
                del self.subs[normalized]
        return True, "ok"

    def set_book(
        self,
        symbol: str,
        bids: list,
        asks: list,
        ts: str,
        seq: Optional[int] = None,
    ) -> None:
        self._books[symbol.upper()] = {
            "bids": bids,
            "asks": asks,
            "ts": ts,
            "seq": seq,
        }

    def get_order_book(self, symbol: str, levels: int = 10) -> dict:
        return self._books.get(
            symbol.upper(), {"bids": [], "asks": [], "ts": None, "seq": None}
        )


_LOCK = threading.Lock()
_GATEWAY: Optional[QuoteGateway] = None


def get_gateway(transport: Optional[GatewayTransport] = None) -> QuoteGateway:
    """Return the injected process singleton; implicit real construction is forbidden."""
    global _GATEWAY
    with _LOCK:
        if _GATEWAY is None:
            if transport is None:
                raise RuntimeError(
                    "explicit gateway transport required; production owner is a dedicated service"
                )
            _GATEWAY = QuoteGateway(transport)
        elif transport is not None and _GATEWAY._t is not transport:
            raise RuntimeError("gateway already initialized with a different transport")
        return _GATEWAY


def set_gateway_for_test(gateway: Optional[QuoteGateway]) -> None:
    global _GATEWAY
    with _LOCK:
        _GATEWAY = gateway
