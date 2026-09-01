"""Fail-soft cost-event emitter for application-layer attribution.

Never raises into the model-call path. Never writes raw keys.
Successful canonical calls emit once. Possibly-billable failures emit an
attempt with PRICE_UNKNOWN / usage unknown rather than invented USD.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .context import current_attribution
from .identity import fingerprint_key, redact_mapping
from .pricing import PRICE_UNKNOWN, calculate_usd
from .schema import (
    CLASS_TRADE_AI_PRODUCTION,
    CLASS_TRADE_AI_TEST,
    CONF_STRONG,
    CONF_UNKNOWN,
    ProviderCostEvent,
    event_id_for,
    is_test_process,
)

_DEFAULT_PATH = Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT" / "data" / "runtime" / "provider_cost" / "events.jsonl"

OUTCOME_SUCCESS = "success"
OUTCOME_ATTEMPT = "possibly_billable_attempt"
OUTCOME_PRE_SEND = "pre_send_failure"

_SEEN_IDS: set[str] = set()


def _dest(path: Optional[Path] = None) -> Path:
    return Path(path) if path else Path(os.environ.get("PROVIDER_COST_EVENT_LOG") or _DEFAULT_PATH)


def _merge_attr(**kwargs: Any) -> dict[str, Any]:
    attr = current_attribution()
    for key in (
        "source_service",
        "source_process",
        "source_lane",
        "agent",
        "run_id",
        "reservation_id",
        "environment",
        "process_id",
    ):
        val = kwargs.get(key)
        if val is not None and val != "":
            attr[key] = val
    if "source_process" not in attr and attr.get("process_id"):
        attr["source_process"] = attr["process_id"]
    return attr


def emit_cost_event(
    *,
    provider: str,
    model: str,
    outcome: str = OUTCOME_SUCCESS,
    process_id: Optional[str] = None,
    request_id: Optional[str] = None,
    client_request_id: Optional[str] = None,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    cache_hit_tokens: Optional[int] = None,
    cache_miss_tokens: Optional[int] = None,
    raw_key: Optional[str] = None,
    usage_start: Optional[str] = None,
    path: Optional[Path] = None,
    source_service: Optional[str] = None,
    source_process: Optional[str] = None,
    source_lane: Optional[str] = None,
    agent: Optional[str] = None,
    run_id: Optional[str] = None,
    reservation_id: Optional[str] = None,
    environment: Optional[str] = None,
    request_sent: Optional[bool] = None,
    possibly_billable: Optional[bool] = None,
    error_class: Optional[str] = None,
    evidence_refs: Optional[list[str]] = None,
) -> Optional[str]:
    """Canonical emit. Never invents tokens or USD. Never persists raw secrets."""
    try:
        start = usage_start or datetime.now(timezone.utc).isoformat()
        attr = _merge_attr(
            process_id=process_id,
            source_service=source_service,
            source_process=source_process,
            source_lane=source_lane,
            agent=agent,
            run_id=run_id,
            reservation_id=str(reservation_id) if reservation_id is not None else None,
            environment=environment,
        )
        src_process = attr.get("source_process") or process_id
        if not attr.get("source_service"):
            attr["source_service"] = "deepseek_client.chat"
        test = is_test_process(src_process)

        has_usage = any(
            v is not None
            for v in (prompt_tokens, completion_tokens, cache_hit_tokens, cache_miss_tokens)
        )
        usage_unknown = not has_usage

        if outcome == OUTCOME_PRE_SEND:
            request_sent = False if request_sent is None else bool(request_sent)
            possibly_billable = False
            priced = {
                "calculated_cost_usd": None,
                "cost_source": PRICE_UNKNOWN,
                "price_schedule_id": None,
                "band": None,
                "cache_hit": None,
            }
        elif outcome == OUTCOME_ATTEMPT and usage_unknown:
            request_sent = True if request_sent is None else bool(request_sent)
            possibly_billable = True
            priced = {
                "calculated_cost_usd": None,
                "cost_source": PRICE_UNKNOWN,
                "price_schedule_id": None,
                "band": None,
                "cache_hit": None,
            }
        else:
            miss = cache_miss_tokens if cache_miss_tokens is not None else prompt_tokens
            if miss is None and not has_usage:
                priced = {
                    "calculated_cost_usd": None,
                    "cost_source": PRICE_UNKNOWN,
                    "price_schedule_id": None,
                    "band": None,
                    "cache_hit": None,
                }
                usage_unknown = True
            else:
                priced = calculate_usd(
                    provider=provider,
                    model=model,
                    at=start,
                    cache_hit_input=int(cache_hit_tokens or 0),
                    cache_miss_input=int(miss or 0),
                    output=int(completion_tokens or 0),
                )
            if request_sent is None:
                request_sent = True
            if possibly_billable is None:
                possibly_billable = True

        # Explicit cache-hit bit for §9.2 surfaces (None when usage unknown).
        if priced.get("cache_hit") is None and cache_hit_tokens is not None:
            priced["cache_hit"] = int(cache_hit_tokens or 0) > 0

        ev = ProviderCostEvent(
            event_id=event_id_for(
                src="emit",
                provider=provider,
                model=model,
                rid=request_id,
                client_rid=client_request_id,
                outcome=outcome,
                start=start,
                tok=(cache_hit_tokens, cache_miss_tokens, prompt_tokens, completion_tokens),
                err=error_class,
            ),
            provider=provider,
            classification=CLASS_TRADE_AI_TEST if test else CLASS_TRADE_AI_PRODUCTION,
            attribution_confidence=CONF_UNKNOWN if usage_unknown and outcome != OUTCOME_SUCCESS else CONF_STRONG,
            usage_start=start,
            model=model,
            source_service=attr.get("source_service"),
            source_process=src_process,
            source_lane=attr.get("source_lane"),
            agent_name=attr.get("agent"),
            run_id=attr.get("run_id"),
            request_id=request_id,
            reservation_id=str(attr["reservation_id"]) if attr.get("reservation_id") is not None else None,
            key_fingerprint=fingerprint_key(raw_key, provider=provider),
            input_tokens=None if prompt_tokens is None and usage_unknown else (
                int(cache_miss_tokens) if cache_miss_tokens is not None else (
                    int(prompt_tokens) if prompt_tokens is not None else None
                )
            ),
            cached_input_tokens=None if cache_hit_tokens is None else int(cache_hit_tokens),
            output_tokens=None if completion_tokens is None else int(completion_tokens),
            calculated_cost_usd=priced.get("calculated_cost_usd"),
            cost_source=priced.get("cost_source"),
            price_schedule_id=priced.get("price_schedule_id"),
            rate_tier=priced.get("band"),
            cache_hit=priced.get("cache_hit"),
            environment=attr.get("environment"),
            is_test=test,
            evidence_refs=list(evidence_refs or ["provider_cost.emit_cost_event"]),
            source_host=os.uname().nodename if hasattr(os, "uname") else None,
            client_request_id=client_request_id,
            request_sent=bool(request_sent),
            possibly_billable=bool(possibly_billable),
            outcome=outcome,
            error_class=error_class,
            usage_unknown=bool(usage_unknown),
        )
        if ev.event_id in _SEEN_IDS:
            return ev.event_id
        payload = ev.to_dict()
        dumped = json.dumps(payload, sort_keys=True, default=str)
        if raw_key and str(raw_key) in dumped:
            return None
        # Belt-and-braces: never persist Authorization/Bearer-shaped values.
        if "Bearer " in dumped or '"Authorization"' in dumped:
            dumped = json.dumps(redact_mapping(payload), sort_keys=True, default=str)
        dest = _dest(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("a", encoding="utf-8") as fh:
            fh.write(dumped + "\n")
        _SEEN_IDS.add(ev.event_id)
        return ev.event_id
    except Exception:
        return None


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
    source_service: Optional[str] = None,
    source_process: Optional[str] = None,
    source_lane: Optional[str] = None,
    agent: Optional[str] = None,
    run_id: Optional[str] = None,
    reservation_id: Optional[str] = None,
    environment: Optional[str] = None,
    client_request_id: Optional[str] = None,
) -> Optional[str]:
    """Backward-compatible success emit. Wrappers must not call this if chat() already will."""
    return emit_cost_event(
        provider=provider,
        model=model,
        outcome=OUTCOME_SUCCESS,
        process_id=process_id,
        request_id=request_id,
        client_request_id=client_request_id,
        prompt_tokens=int(prompt_tokens or 0),
        completion_tokens=int(completion_tokens or 0),
        cache_hit_tokens=int(cache_hit_tokens or 0),
        cache_miss_tokens=cache_miss_tokens,
        raw_key=raw_key,
        usage_start=usage_start,
        path=path,
        source_service=source_service,
        source_process=source_process,
        source_lane=source_lane,
        agent=agent,
        run_id=run_id,
        reservation_id=reservation_id,
        environment=environment,
        request_sent=True,
        possibly_billable=True,
        evidence_refs=["provider_cost.emit_paid_call"],
    )


def emit_attempt(
    *,
    provider: str,
    model: str,
    request_id: Optional[str] = None,
    client_request_id: Optional[str] = None,
    raw_key: Optional[str] = None,
    error_class: Optional[str] = None,
    path: Optional[Path] = None,
    **kwargs: Any,
) -> Optional[str]:
    """Record a possibly-billable failure without inventing cost."""
    return emit_cost_event(
        provider=provider,
        model=str(model or ""),
        outcome=OUTCOME_ATTEMPT,
        request_id=request_id,
        client_request_id=client_request_id,
        raw_key=raw_key,
        error_class=error_class,
        path=path,
        request_sent=True,
        possibly_billable=True,
        evidence_refs=["provider_cost.emit_attempt"],
        **{k: v for k, v in kwargs.items() if k != "outcome"},
    )
