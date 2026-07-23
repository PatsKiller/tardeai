"""Stage 5 — event envelope + bounded queues.

Callbacks validate, timestamp, allocate a local monotonic sequence, and enqueue.
They never write DB/Parquet, call an LLM, compute expensive features, call another
broker, or trade. provider_sequence is null when the SDK does not supply one —
never invented.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional

PAYLOAD_SCHEMA_VERSION = "moomoo-md-1"


class StreamType(str, Enum):
    QUOTE = "QUOTE"
    K_1M = "K_1M"
    ORDER_BOOK = "ORDER_BOOK"
    TICKER = "TICKER"
    CONTROL = "CONTROL"


@dataclass
class EventEnvelope:
    event_id: str
    stream_type: str
    symbol: str
    provider_timestamp: Optional[str]
    provider_receive_timestamp: Optional[str]
    gateway_receive_timestamp: str
    gateway_receive_monotonic_ns: int
    reconnect_epoch: int
    connection_sequence: int
    provider_sequence: Optional[int]
    is_first_push: bool
    is_cached: bool
    session: Optional[str]
    payload: Any
    broker: str = "MOOMOO"
    payload_schema_version: str = PAYLOAD_SCHEMA_VERSION
    source_version: str = "10.9.6908"

    def as_dict(self) -> dict:
        return asdict(self)


class QueuePolicy(str, Enum):
    CONTROL = "CONTROL"          # never intentionally drop
    COALESCE = "COALESCE"        # quote: latest-value coalescing
    RING_GAP = "RING_GAP"        # order book: bounded ring + gap marker
    APPEND_OVERFLOW = "APPEND_OVERFLOW"  # ticker: append + overflow marker
    BOUNDED = "BOUNDED"          # candles: bounded, no silent loss


@dataclass
class QueueMetrics:
    received: int = 0
    written: int = 0
    coalesced: int = 0
    dropped: int = 0
    gap_markers: int = 0
    overflow_markers: int = 0
    max_depth: int = 0


class BoundedStreamQueue:
    """One queue per stream with an explicit policy. Never silently discards P0."""

    def __init__(self, policy: QueuePolicy, capacity: int = 4096):
        self.policy = policy
        self.capacity = capacity
        self._dq: deque = deque()
        self._latest: dict = {}
        self._lock = threading.Lock()
        self.metrics = QueueMetrics()

    def put(self, env: EventEnvelope) -> None:
        with self._lock:
            self.metrics.received += 1
            if self.policy is QueuePolicy.COALESCE:
                key = env.symbol
                if key not in self._latest:
                    self._dq.append(key)
                else:
                    self.metrics.coalesced += 1
                self._latest[key] = env
            elif self.policy is QueuePolicy.CONTROL:
                self._dq.append(env)          # control is never dropped
            else:
                if len(self._dq) >= self.capacity:
                    if self.policy is QueuePolicy.RING_GAP:
                        self._dq.popleft()
                        self.metrics.dropped += 1
                        self.metrics.gap_markers += 1
                        self._dq.append(_gap_marker(env))
                    elif self.policy is QueuePolicy.APPEND_OVERFLOW:
                        self.metrics.overflow_markers += 1
                        self._dq.append(_overflow_marker(env))
                    else:  # BOUNDED — refuse silently-lossy behavior, block-drop with marker
                        self.metrics.dropped += 1
                        self.metrics.gap_markers += 1
                        self._dq.append(_gap_marker(env))
                else:
                    self._dq.append(env)
            self.metrics.max_depth = max(self.metrics.max_depth, len(self._dq))

    def drain(self) -> list:
        with self._lock:
            if self.policy is QueuePolicy.COALESCE:
                out = [self._latest[k] for k in self._dq]
                self._dq.clear()
                self._latest.clear()
            else:
                out = list(self._dq)
                self._dq.clear()
            self.metrics.written += len(out)
            return out

    def depth(self) -> int:
        with self._lock:
            return len(self._dq)


def _gap_marker(env: EventEnvelope) -> dict:
    return {"marker": "SEQUENCE_GAP", "stream_type": env.stream_type,
            "symbol": env.symbol, "at_monotonic_ns": env.gateway_receive_monotonic_ns}


def _overflow_marker(env: EventEnvelope) -> dict:
    return {"marker": "QUEUE_OVERFLOW", "stream_type": env.stream_type,
            "symbol": env.symbol, "at_monotonic_ns": env.gateway_receive_monotonic_ns}
