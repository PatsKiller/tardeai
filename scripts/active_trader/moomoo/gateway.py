"""Stage 5 — single quote-subscription owner (DATA ONLY).

Exactly one OpenQuoteContext, one subscription registry, one reconnect coordinator,
one quota/entitlement authority, one callback→queue boundary. No UI/agent/writer/
feature-engine independently subscribes. Never auto-grabs quote rights
(auto_hold_quote_right=0 in config, and no RightCtrl grab here).

This module imports only the market-data side of the SDK. The AST guard proves no
trade context/method is reachable.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from active_trader.moomoo.envelope import (
    BoundedStreamQueue, EventEnvelope, QueuePolicy, StreamType,
)


class SubState(str, Enum):
    REQUESTED = "REQUESTED"
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    ENTITLEMENT_MISSING = "ENTITLEMENT_MISSING"
    QUOTE_RIGHT_CONFLICT = "QUOTE_RIGHT_CONFLICT"
    QUOTA_DEFERRED = "QUOTA_DEFERRED"
    STALE = "STALE"
    UNSUBSCRIBING = "UNSUBSCRIBING"
    INACTIVE = "INACTIVE"
    FAILED = "FAILED"


class Priority(int, Enum):
    P0 = 0
    P1 = 1
    P2 = 2
    P3 = 3


SUPPORTED_STREAMS = (StreamType.QUOTE, StreamType.K_1M, StreamType.ORDER_BOOK, StreamType.TICKER)
QUEUE_POLICY = {
    StreamType.QUOTE: QueuePolicy.COALESCE,
    StreamType.K_1M: QueuePolicy.BOUNDED,
    StreamType.ORDER_BOOK: QueuePolicy.RING_GAP,
    StreamType.TICKER: QueuePolicy.APPEND_OVERFLOW,
    StreamType.CONTROL: QueuePolicy.CONTROL,
}


@dataclass
class Subscription:
    symbol: str
    stream_type: StreamType
    priority: Priority
    state: SubState = SubState.REQUESTED
    reason: str = ""


class SubscriptionOwner:
    """The one and only subscription authority. `quote_ctx` is injected so tests use
    a fake and the live smoke uses a real OpenQuoteContext (constructed by the caller,
    never a trade context)."""

    def __init__(self, quote_ctx=None, clock=time.monotonic):
        self._ctx = quote_ctx
        self._clock = clock
        self._lock = threading.Lock()
        self._subs: dict[tuple[str, StreamType], Subscription] = {}
        self._queues: dict[StreamType, BoundedStreamQueue] = {
            st: BoundedStreamQueue(QUEUE_POLICY[st]) for st in SUPPORTED_STREAMS
        }
        self._reconnect_epoch = 0
        self._conn_seq = 0
        self._first_push_seen: set[tuple[str, StreamType]] = set()
        self.entitlement: dict = {}
        self.quota: dict = {"total": None, "used": None, "remaining": None}

    # ---- entitlement / quota authority ---------------------------------
    def record_entitlement(self, evidence: dict) -> None:
        self.entitlement = dict(evidence)

    def record_quota(self, total: Optional[int], used: Optional[int]) -> None:
        remaining = None if total is None or used is None else total - used
        self.quota = {"total": total, "used": used, "remaining": remaining}

    def _quota_available(self, n: int = 1) -> bool:
        rem = self.quota.get("remaining")
        return rem is None or rem >= n

    # ---- subscribe (ordered: QUOTE, K_1M, ORDER_BOOK, TICKER) ----------
    def subscribe(self, symbol: str, stream_type: StreamType, priority: Priority,
                  entitled: bool = True) -> Subscription:
        with self._lock:
            key = (symbol, stream_type)
            sub = self._subs.get(key) or Subscription(symbol, stream_type, priority)
            self._subs[key] = sub
            if not entitled:
                sub.state = SubState.ENTITLEMENT_MISSING
                sub.reason = "no entitlement for this tier"
                return sub                     # lower tiers survive; do not raise
            if not self._quota_available():
                sub.state = SubState.QUOTA_DEFERRED
                sub.reason = "quota exhausted"
                return sub
            sub.state = SubState.PENDING
            if self._ctx is not None:
                ok, msg = self._ctx.subscribe([symbol], [stream_type.value])
                if not ok:
                    if "right" in str(msg).lower():
                        sub.state = SubState.QUOTE_RIGHT_CONFLICT
                    else:
                        sub.state = SubState.FAILED
                    sub.reason = "subscribe rejected (never auto-grab)"
                    return sub
            sub.state = SubState.ACTIVE
            u = self.quota.get("used")
            if u is not None:
                self.record_quota(self.quota["total"], u + 1)
            return sub

    def unsubscribe(self, symbol: str, stream_type: StreamType) -> None:
        with self._lock:
            key = (symbol, stream_type)
            sub = self._subs.get(key)
            if not sub:
                return
            sub.state = SubState.UNSUBSCRIBING
            if self._ctx is not None:
                self._ctx.unsubscribe([symbol], [stream_type.value])
            sub.state = SubState.INACTIVE

    # ---- callback → queue boundary (does NOT write DB/Parquet/LLM) -----
    def on_push(self, symbol: str, stream_type: StreamType, payload, *,
                provider_ts=None, provider_seq=None, is_cached=False,
                session=None, wall_iso=None) -> EventEnvelope:
        key = (symbol, stream_type)
        first = key not in self._first_push_seen
        if first:
            self._first_push_seen.add(key)
        self._conn_seq += 1
        env = EventEnvelope(
            event_id=f"{self._reconnect_epoch}-{self._conn_seq}",
            stream_type=stream_type.value, symbol=symbol,
            provider_timestamp=provider_ts, provider_receive_timestamp=provider_ts,
            gateway_receive_timestamp=(wall_iso or _iso_now()),
            gateway_receive_monotonic_ns=time.monotonic_ns(),
            reconnect_epoch=self._reconnect_epoch, connection_sequence=self._conn_seq,
            provider_sequence=provider_seq,      # null if not supplied — never invented
            is_first_push=first,
            is_cached=is_cached or first,        # first push treated as cached
            session=session, payload=payload)
        # first cached push is not a fresh signal
        self._queues[stream_type].put(env)
        return env

    def fresh_signal_eligible(self, env: EventEnvelope) -> bool:
        return not (env.is_first_push or env.is_cached)

    def reconnect(self) -> None:
        with self._lock:
            self._reconnect_epoch += 1
            self._first_push_seen.clear()
            for sub in self._subs.values():
                if sub.state == SubState.ACTIVE:
                    sub.state = SubState.PENDING

    def queue(self, stream_type: StreamType) -> BoundedStreamQueue:
        return self._queues[stream_type]

    def status(self) -> dict:
        with self._lock:
            return {
                "reconnect_epoch": self._reconnect_epoch,
                "entitlement": self.entitlement,
                "quota": self.quota,
                "subscriptions": [
                    {"symbol": s.symbol, "stream": s.stream_type.value,
                     "priority": s.priority.name, "state": s.state.value, "reason": s.reason}
                    for s in self._subs.values()],
                "queues": {st.value: {"depth": q.depth(), **q.metrics.__dict__}
                           for st, q in self._queues.items()},
            }


def _iso_now() -> str:
    # wall clock only for the human-readable field; ordering uses monotonic_ns
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
