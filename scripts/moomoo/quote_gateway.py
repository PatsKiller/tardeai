"""Single-owner Moomoo/OpenD read-only quote gateway.

EXACTLY ONE process-wide gateway owns EXACTLY ONE OpenQuoteContext. Every consumer
(subscription manager, L2 feature service, ActiveTrader read API, live-mark service) goes
through this gateway — no request handler, logger, test, script, or React component may
open an independent production OpenQuoteContext.

The gateway does NOT construct an OpenQuoteContext itself. The single construction site
stays `scripts/moomoo/client.py:FutuTransport` (which already owns one and closes it at
exit); the real transport composes that. For deterministic tests, inject `MockTransport` —
no live OpenD required. Observations are held in BOUNDED in-memory structures; nothing here
writes per-event books/tape to PostgreSQL.

Read plane only: no order path, no unlock, no trade context.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Mapping, Optional, Protocol


# ── transport surface (real futu adapter or mock both satisfy this) ──────────
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
    bids: list           # [(price, size), ...]
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
    side: Optional[str]   # 'BUY' | 'SELL' | None
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
    """The one OpenD read gateway. Bounded buffers per symbol; PUSH-preferred ingest."""

    def __init__(self, transport: GatewayTransport, *, tape_maxlen: int = 256):
        self._t = transport
        self._lock = threading.RLock()
        self._books: dict[str, BookSnapshot] = {}
        self._tape: dict[str, Deque[TapePrint]] = {}
        self._quotes: dict[str, QuoteTick] = {}
        self._tape_maxlen = int(tape_maxlen)

    # ── health / entitlement / quota (pass-through to the single transport) ──
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

    # ── subscription control (the ONLY place subscribe/unsubscribe is issued) ─
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

    # ── PUSH ingest (preferred): OpenD callbacks feed these bounded buffers ───
    def on_book_push(self, snap: BookSnapshot) -> None:
        with self._lock:
            self._books[snap.symbol.upper()] = snap

    def on_tape_push(self, symbol: str, prints: list[TapePrint]) -> None:
        with self._lock:
            dq = self._tape.setdefault(symbol.upper(), deque(maxlen=self._tape_maxlen))
            dq.extend(prints)

    def on_quote_push(self, symbol: str, tick: QuoteTick) -> None:
        with self._lock:
            self._quotes[symbol.upper()] = tick

    # ── PULL fallback (only for a subscribed symbol; never a per-request remote poll storm) ──
    def poll_book(self, symbol: str, received_at: str, levels: int = 10) -> Optional[BookSnapshot]:
        try:
            raw = self._t.get_order_book(symbol, levels=levels)
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None
        snap = BookSnapshot(
            symbol=symbol.upper(),
            bids=list(raw.get("bids") or []),
            asks=list(raw.get("asks") or []),
            provider_at=raw.get("ts"),
            received_at=received_at,
            sequence_id=raw.get("seq"),
        )
        self.on_book_push(snap)
        return snap

    # ── reads ────────────────────────────────────────────────────────────────
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


# ── deterministic mock transport for tests (no live OpenD) ───────────────────
class MockTransport:
    """Programmable in-memory transport. Records subscribe/unsubscribe, serves quota+books.

    total_quota/total_used model SIMULTANEOUS subscription quota. `subscribe` consumes
    len(subtypes) units and records the call; `unsubscribe` releases them. This lets tests
    prove per-subtype quota accounting and dwell/reconnect behavior deterministically.
    """

    def __init__(self, *, up: bool = True, entitled: bool = True,
                 total_quota: int = 200, other_connection_usage: int = 0):
        self.up = up
        self.entitled = entitled
        self.total_quota = total_quota
        self.other_connection_usage = int(other_connection_usage)
        self.subs: dict[str, set[str]] = {}
        self.subscribe_calls: list[tuple[str, tuple[str, ...]]] = []
        self.unsubscribe_calls: list[tuple[str, tuple[str, ...]]] = []
        self._books: dict[str, dict] = {}
        self.fail_next_subscribe = False

    def ping(self) -> bool:
        return self.up

    def entitlement_ok(self) -> bool:
        return self.up and self.entitled

    def _own_units(self) -> int:
        return sum(len(v) for v in self.subs.values())

    def query_subscription(self, is_all_conn: bool = True) -> dict:
        used = self._own_units() + (self.other_connection_usage if is_all_conn else 0)
        return {
            "total_quota": self.total_quota,
            "total_used": used,
            "remain": self.total_quota - used,
            "own_used": self._own_units(),
            "other_connection_usage": self.other_connection_usage if is_all_conn else 0,
            "subscriptions_by_type": self._by_type(),
        }

    def _by_type(self) -> dict:
        out: dict[str, int] = {}
        for st_set in self.subs.values():
            for st in st_set:
                out[st] = out.get(st, 0) + 1
        return out

    def subscribe(self, symbol: str, subtypes: list[str]) -> tuple[bool, str]:
        if not self.up:
            return False, "opend down"
        if self.fail_next_subscribe:
            self.fail_next_subscribe = False
            return False, "simulated subscribe failure"
        sym = symbol.upper()
        self.subscribe_calls.append((sym, tuple(subtypes)))
        self.subs.setdefault(sym, set()).update(subtypes)
        return True, "ok"

    def unsubscribe(self, symbol: str, subtypes: list[str]) -> tuple[bool, str]:
        sym = symbol.upper()
        self.unsubscribe_calls.append((sym, tuple(subtypes)))
        if sym in self.subs:
            for st in subtypes:
                self.subs[sym].discard(st)
            if not self.subs[sym]:
                del self.subs[sym]
        return True, "ok"

    def set_book(self, symbol: str, bids: list, asks: list, ts: str,
                 seq: Optional[int] = None) -> None:
        self._books[symbol.upper()] = {"bids": bids, "asks": asks, "ts": ts, "seq": seq}

    def get_order_book(self, symbol: str, levels: int = 10) -> dict:
        return self._books.get(symbol.upper(), {"bids": [], "asks": [], "ts": None})


# ── process-wide singleton (single-owner enforcement) ────────────────────────
_LOCK = threading.Lock()
_GATEWAY: Optional[QuoteGateway] = None


def get_gateway(transport: Optional[GatewayTransport] = None) -> QuoteGateway:
    """Return the one process-wide gateway, building it on first use.

    A transport may be supplied on first call (real adapter in production, mock in tests).
    Subsequent calls return the SAME gateway — a second production OpenQuoteContext is never
    created here."""
    global _GATEWAY
    with _LOCK:
        if _GATEWAY is None:
            _GATEWAY = QuoteGateway(transport or _build_default_transport())
        return _GATEWAY


def set_gateway_for_test(gateway: Optional[QuoteGateway]) -> None:
    global _GATEWAY
    with _LOCK:
        _GATEWAY = gateway


def _build_default_transport() -> GatewayTransport:
    """Build the real futu-backed transport (single OpenQuoteContext via client.FutuTransport).

    Not exercised in CI (no live OpenD). Fail-closed: if the SDK/host is unavailable the
    returned transport reports down/unentitled, so the gateway degrades to honest 'not
    connected' rather than fabricating data.
    """
    try:
        from .real_gateway_transport import RealGatewayTransport
    except ImportError:  # pragma: no cover
        from real_gateway_transport import RealGatewayTransport  # type: ignore
    return RealGatewayTransport()
