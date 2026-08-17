"""Fail-soft cost-event emitter for future application-layer attribution.

Never raises into the model-call path. Never writes raw keys.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .identity import fingerprint_key
from .pricing import calculate_usd
from .schema import (
    CLASS_TRADE_AI_PRODUCTION,
    CLASS_TRADE_AI_TEST,
    CONF_STRONG,
    ProviderCostEvent,
    event_id_for,
    is_test_process,
)

_DEFAULT_PATH = Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT" / "data" / "runtime" / "provider_cost" / "events.jsonl"


def emit_paid_call(
    *,
    provider: str,
    model: str,
    process_id: Optional[str] = None,
    request_id: Optional[str] = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cache_hit_tokens: int = 0,
    cache_miss_tokens: int | None = None,
    raw_key: Optional[str] = None,
    usage_start: Optional[str] = None,
    path: Optional[Path] = None,
) -> Optional[str]:
    try:
        start = usage_start or datetime.now(timezone.utc).isoformat()
        miss = int(cache_miss_tokens if cache_miss_tokens is not None else prompt_tokens)
        priced = calculate_usd(
            provider=provider,
            model=model,
            at=start,
            cache_hit_input=int(cache_hit_tokens or 0),
            cache_miss_input=miss,
            output=int(completion_tokens or 0),
        )
        test = is_test_process(process_id)
        ev = ProviderCostEvent(
            event_id=event_id_for(
                src="emit",
                provider=provider,
                model=model,
                rid=request_id,
                start=start,
                tok=(cache_hit_tokens, miss, completion_tokens),
            ),
            provider=provider,
            classification=CLASS_TRADE_AI_TEST if test else CLASS_TRADE_AI_PRODUCTION,
            attribution_confidence=CONF_STRONG,
            usage_start=start,
            model=model,
            source_process=process_id,
            request_id=request_id,
            key_fingerprint=fingerprint_key(raw_key, provider=provider),
            input_tokens=miss,
            cached_input_tokens=int(cache_hit_tokens or 0),
            output_tokens=int(completion_tokens or 0),
            calculated_cost_usd=priced.get("calculated_cost_usd"),
            cost_source=priced.get("cost_source"),
            price_schedule_id=priced.get("price_schedule_id"),
            is_test=test,
            source_host=os.uname().nodename if hasattr(os, "uname") else None,
            evidence_refs=["provider_cost.emit_paid_call"],
        )
        dest = Path(path) if path else Path(os.environ.get("PROVIDER_COST_EVENT_LOG") or _DEFAULT_PATH)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev.to_dict(), sort_keys=True, default=str) + "\n")
        return ev.event_id
    except Exception:
        return None
