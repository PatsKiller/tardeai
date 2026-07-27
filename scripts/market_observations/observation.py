#!/usr/bin/env python3
"""M3-S5.5 — normalized, immutable market-observation contract.

A provider-neutral record of one piece of market data from one source, carrying the provenance /
freshness / entitlement / sequence metadata the architecture requires around observations (rather
than downstream consumers polling raw providers). Immutable (frozen dataclass): an observation is a
fact-at-a-time, never mutated after normalization.

Field names ALIGN with the house Observation envelope (architecture v3.3 §5.2, lines 583-602):
`source_system, source_record_id, symbol_or_entity, observed_at, provider_at, received_at,
normalized_at, source_version, source_hash, quality_state, freshness_state, entitlement_state,
sequence_id, payload_ref`. `to_house_envelope()` emits exactly those names for interop/persistence.
Provenance maps to the §15.7 control tables (`md_entitlement_state`, `md_data_quality`,
`md_feature_snapshot`, `md_sequence_gap`) — those tables are NOT created/written by this shadow stage.

SAFETY: this module holds NO credentials and NO raw secret-bearing payloads. `payload_ref` is an
opaque handle/summary, never a raw auth-bearing response. Market-signal code must never consume
account/position/order observations as scoring inputs (enforced by the isolation tests).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Mapping, Optional


class ObservationType(str, Enum):
    BAR = "bar"
    QUOTE = "quote"              # bid/ask (NBBO or venue L1)
    TRADE = "trade"              # time & sales print
    ORDER_BOOK = "order_book"    # depth snapshot (T2)
    ACCOUNT_FACT = "account_fact"
    POSITION_FACT = "position_fact"
    ORDER_FACT = "order_fact"


# Observation types that are MARKET SIGNAL (may feed scoring/triggers) vs BROKER STATE (may NOT).
MARKET_SIGNAL_TYPES = frozenset({
    ObservationType.BAR, ObservationType.QUOTE, ObservationType.TRADE, ObservationType.ORDER_BOOK})
BROKER_STATE_TYPES = frozenset({
    ObservationType.ACCOUNT_FACT, ObservationType.POSITION_FACT, ObservationType.ORDER_FACT})


class EntitlementState(str, Enum):
    AVAILABLE_REALTIME = "AVAILABLE_REALTIME"
    AVAILABLE_DELAYED = "AVAILABLE_DELAYED"
    AVAILABLE_HISTORICAL = "AVAILABLE_HISTORICAL"
    IEX_ONLY = "IEX_ONLY"
    SIP_REALTIME = "SIP_REALTIME"
    SIP_DELAYED = "SIP_DELAYED"
    SCAFFOLD_ONLY = "SCAFFOLD_ONLY"
    UNAVAILABLE = "UNAVAILABLE"
    UNRESOLVED = "UNRESOLVED"


class FreshnessState(str, Enum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class QualityState(str, Enum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"        # e.g. venue-partial (IEX) standing in for consolidated
    CONFLICT = "CONFLICT"
    UNVERIFIED = "UNVERIFIED"


class DataTier(str, Enum):
    # design-doc numbering (operator ruling 2026-07-27): T2 = book (best) … T0 = bars (weakest)
    T2 = "T2"     # full order book / tape (moomoo) — best
    T1 = "T1"     # consolidated SIP trades + NBBO — real-time only
    T1_VENUE = "T1_venue"   # real-time trades/NBBO but venue-partial (IEX) — NOT consolidated
    T0 = "T0"     # bars-only — weakest, ships today


@dataclass(frozen=True)
class Observation:
    """One normalized observation. Frozen: create a new one rather than mutating."""
    source_system: str                 # 'alpaca' | 'yahoo' | 'schwab' | 'moomoo'
    source_record_id: str              # provider-side id or a synthesized deterministic id
    symbol: str                        # == house `symbol_or_entity`
    observation_type: ObservationType
    observed_at: Optional[str]         # house §5.2: exchange/event time (falls back to provider_at)
    provider_at: Optional[str]         # provider's data timestamp (ISO) — when the market event was
    received_at: str                   # when we received it (ISO)
    normalized_at: str                 # when we normalized it (ISO)
    source_version: str                # adapter/contract version
    source_hash: str                   # deterministic hash of the normalized payload (integrity)
    quality_state: QualityState
    freshness_state: FreshnessState
    entitlement_state: EntitlementState
    feed: Optional[str] = None         # 'iex' | 'sip' | venue | None
    delayed: bool = False
    sequence_id: Optional[int] = None  # provider sequence for gap detection (T2)
    data_tier: DataTier = DataTier.T0
    payload_ref: Mapping[str, Any] = field(default_factory=dict)  # NON-secret normalized values only

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("observation_type", "quality_state", "freshness_state", "entitlement_state", "data_tier"):
            v = d.get(k)
            if isinstance(v, Enum):
                d[k] = v.value
        # enum instances survive asdict for str-enums as their value already in some paths; normalize
        d["observation_type"] = self.observation_type.value
        d["quality_state"] = self.quality_state.value
        d["freshness_state"] = self.freshness_state.value
        d["entitlement_state"] = self.entitlement_state.value
        d["data_tier"] = self.data_tier.value
        return d

    def to_house_envelope(self) -> dict:
        """Emit the exact house §5.2 field names (symbol_or_entity, observed_at, …) for interop."""
        return {
            "source_system": self.source_system, "source_record_id": self.source_record_id,
            "symbol_or_entity": self.symbol, "observed_at": self.observed_at or self.provider_at,
            "provider_at": self.provider_at, "received_at": self.received_at,
            "normalized_at": self.normalized_at, "source_version": self.source_version,
            "source_hash": self.source_hash, "quality_state": self.quality_state.value,
            "freshness_state": self.freshness_state.value, "entitlement_state": self.entitlement_state.value,
            "sequence_id": self.sequence_id, "payload_ref": dict(self.payload_ref),
            "feed": self.feed, "delayed": self.delayed, "data_tier": self.data_tier.value,
        }

    def is_market_signal(self) -> bool:
        return self.observation_type in MARKET_SIGNAL_TYPES

    def is_broker_state(self) -> bool:
        return self.observation_type in BROKER_STATE_TYPES


def payload_hash(payload: Mapping[str, Any]) -> str:
    """Deterministic hash of a normalized (non-secret) payload for integrity/provenance."""
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def make_observation(
    *, source_system: str, symbol: str, observation_type: ObservationType,
    payload: Mapping[str, Any], provider_at: Optional[str], received_at: str, normalized_at: str,
    observed_at: Optional[str] = None,
    entitlement_state: EntitlementState, freshness_state: FreshnessState = FreshnessState.UNKNOWN,
    quality_state: QualityState = QualityState.OK, feed: Optional[str] = None, delayed: bool = False,
    sequence_id: Optional[int] = None, data_tier: DataTier = DataTier.T0,
    source_record_id: Optional[str] = None, source_version: str = "m3-s5.5",
) -> Observation:
    """Build an immutable Observation, hashing the (non-secret) payload. Timestamps are supplied by
    the caller (never generated here) so the contract is deterministic/testable."""
    ph = payload_hash(payload)
    return Observation(
        source_system=source_system,
        source_record_id=source_record_id or f"{source_system}:{symbol}:{observation_type.value}:{ph}",
        symbol=symbol.upper(), observation_type=observation_type,
        observed_at=observed_at or provider_at,
        provider_at=provider_at, received_at=received_at, normalized_at=normalized_at,
        source_version=source_version, source_hash=ph,
        quality_state=quality_state, freshness_state=freshness_state, entitlement_state=entitlement_state,
        feed=feed, delayed=delayed, sequence_id=sequence_id, data_tier=data_tier,
        payload_ref=dict(payload),
    )
