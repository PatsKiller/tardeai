"""ProviderCostEvent@v1 + classification / confidence contracts."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

SCHEMA_VERSION = "ProviderCostEvent@v1"

CLASS_TRADE_AI_PRODUCTION = "TRADE_AI_PRODUCTION"
CLASS_TRADE_AI_TEST = "TRADE_AI_TEST"
CLASS_TRADE_AI_DEV = "TRADE_AI_DEV"
CLASS_OPENCLAW = "OPENCLAW"
CLASS_CLAUDE_CODE = "CLAUDE_CODE"
CLASS_CURSOR = "CURSOR"
CLASS_GROK_BUILD = "GROK_BUILD"
CLASS_KNOWN_BYPASS = "KNOWN_BYPASS"
CLASS_OTHER_HOST_LOCAL = "OTHER_HOST_LOCAL"
CLASS_OTHER_CONFIRMED = "OTHER_CONFIRMED"
CLASS_UNKNOWN = "UNKNOWN"
CLASS_CONSOLE_TOTAL = "CONSOLE_TOTAL"

VALID_CLASSES = frozenset(
    {
        CLASS_TRADE_AI_PRODUCTION,
        CLASS_TRADE_AI_TEST,
        CLASS_TRADE_AI_DEV,
        CLASS_OPENCLAW,
        CLASS_CLAUDE_CODE,
        CLASS_CURSOR,
        CLASS_GROK_BUILD,
        CLASS_KNOWN_BYPASS,
        CLASS_OTHER_HOST_LOCAL,
        CLASS_OTHER_CONFIRMED,
        CLASS_UNKNOWN,
        CLASS_CONSOLE_TOTAL,
    }
)

CONF_EXACT = "EXACT"
CONF_STRONG = "STRONG"
CONF_INFERRED = "INFERRED"
CONF_UNKNOWN = "UNKNOWN"
VALID_CONFIDENCE = frozenset({CONF_EXACT, CONF_STRONG, CONF_INFERRED, CONF_UNKNOWN})

COST_SOURCE_PROVIDER_REPORTED = "PROVIDER_REPORTED"
COST_SOURCE_LOCAL_CALCULATED = "LOCAL_CALCULATED"
COST_SOURCE_PRICE_UNKNOWN = "PRICE_UNKNOWN"

PRODUCTION_CLASSES = frozenset({CLASS_TRADE_AI_PRODUCTION, CLASS_KNOWN_BYPASS})
HOST_CLASSES = frozenset(
    {
        CLASS_TRADE_AI_PRODUCTION,
        CLASS_TRADE_AI_DEV,
        CLASS_OPENCLAW,
        CLASS_CLAUDE_CODE,
        CLASS_CURSOR,
        CLASS_GROK_BUILD,
        CLASS_KNOWN_BYPASS,
        CLASS_OTHER_HOST_LOCAL,
        CLASS_OTHER_CONFIRMED,
    }
)


def is_test_process(process_id: Any) -> bool:
    s = str(process_id or "").strip()
    return s.startswith("test_") or s == "test" or "/tests/" in s


@dataclass
class ProviderCostEvent:
    """Canonical cost event. Optional fields stay None rather than invented."""

    event_id: str
    provider: str
    classification: str
    attribution_confidence: str
    usage_start: str
    model: Optional[str] = None
    source_service: Optional[str] = None
    source_process: Optional[str] = None
    source_host: Optional[str] = None
    source_lane: Optional[str] = None
    agent_name: Optional[str] = None
    run_id: Optional[str] = None
    request_id: Optional[str] = None
    reservation_id: Optional[str] = None
    account_id_redacted: Optional[str] = None
    organization_id: Optional[str] = None
    project_id: Optional[str] = None
    key_fingerprint: Optional[str] = None
    usage_end: Optional[str] = None
    input_tokens: Optional[int] = None
    cached_input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
    characters: Optional[int] = None
    billable_units: Optional[float] = None
    price_schedule_id: Optional[str] = None
    calculated_cost_usd: Optional[float] = None
    provider_reported_cost_usd: Optional[float] = None
    cost_source: Optional[str] = None
    # AGENTS.md §9.2: measured cost must carry the rate tier and cache-hit bit.
    # rate_tier is peak | off_peak | flat | None (unknown / pre-send).
    rate_tier: Optional[str] = None
    cache_hit: Optional[bool] = None
    environment: Optional[str] = None
    is_test: bool = False
    evidence_refs: list[str] = field(default_factory=list)
    observed_at: Optional[str] = None
    schema_version: str = SCHEMA_VERSION
    client_request_id: Optional[str] = None
    request_sent: Optional[bool] = None
    possibly_billable: Optional[bool] = None
    outcome: Optional[str] = None
    error_class: Optional[str] = None
    usage_unknown: Optional[bool] = None

    def attributed_usd(self) -> Optional[float]:
        if self.provider_reported_cost_usd is not None:
            return float(self.provider_reported_cost_usd)
        if self.calculated_cost_usd is not None:
            return float(self.calculated_cost_usd)
        return None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def event_id_for(**parts: Any) -> str:
    """Deterministic identity. Never dollar-amount-only."""
    payload = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    return "pce_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def money(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    return round(float(value), 6)
