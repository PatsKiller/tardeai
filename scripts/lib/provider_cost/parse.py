"""Source parsers: console, reservations, consumption, OpenClaw, Claude Code.

Never treat character counts as USD. Classify test_* as TRADE_AI_TEST.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .pricing import PRICE_UNKNOWN, calculate_usd
from .schema import (
    CLASS_CLAUDE_CODE,
    CLASS_CONSOLE_TOTAL,
    CLASS_KNOWN_BYPASS,
    CLASS_OPENCLAW,
    CLASS_TRADE_AI_PRODUCTION,
    CLASS_TRADE_AI_TEST,
    CLASS_UNKNOWN,
    CONF_EXACT,
    CONF_INFERRED,
    CONF_STRONG,
    CONF_UNKNOWN,
    COST_SOURCE_LOCAL_CALCULATED,
    COST_SOURCE_PROVIDER_REPORTED,
    ProviderCostEvent,
    event_id_for,
    is_test_process,
    money,
)


def _iso(value: Any) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    return str(value)


def parse_console_totals(rows: Iterable[dict[str, Any]]) -> list[ProviderCostEvent]:
    """Authoritative billed totals. These are CONSOLE_TOTAL, not attributed spend."""
    events: list[ProviderCostEvent] = []
    for r in rows:
        if str(r.get("attributed_system") or r.get("classification") or "") not in {
            "DEEPSEEK_ACCOUNT_BILLED_SPEND",
            CLASS_CONSOLE_TOTAL,
            "console_total",
        } and not r.get("is_console_total"):
            # also accept explicit console marker
            if str(r.get("api_key_label") or "") != "console_total":
                continue
        start = _iso(r.get("period_start") or r.get("date") or r.get("usage_start"))
        cost = money(r.get("billed_cost_usd") or r.get("provider_cost_usd"))
        ev = ProviderCostEvent(
            event_id=event_id_for(src="console", start=start, cost=cost, tokens=r.get("total_tokens")),
            provider=str(r.get("provider") or "deepseek"),
            classification=CLASS_CONSOLE_TOTAL,
            attribution_confidence=CONF_EXACT,
            usage_start=start,
            model=None if str(r.get("model") or "").upper() in {"UNKNOWN", ""} else r.get("model"),
            input_tokens=None,
            output_tokens=None,
            billable_units=_num(r.get("total_tokens")),
            provider_reported_cost_usd=cost,
            cost_source=COST_SOURCE_PROVIDER_REPORTED,
            evidence_refs=["console_export_or_screenshot"],
        )
        events.append(ev)
    return events


def parse_reservation_rows(rows: Iterable[dict[str, Any]]) -> list[ProviderCostEvent]:
    events: list[ProviderCostEvent] = []
    for r in rows:
        pid = r.get("process_id") or r.get("source_process")
        test = is_test_process(pid)
        start = _iso(r.get("created_at") or r.get("usage_start") or r.get("settled_at"))
        actual = money(r.get("actual_usd") or r.get("settled_usd"))
        reserved = money(r.get("reserved_usd") or r.get("estimated_usd"))
        # Reservation estimate is never automatically the provider cost.
        ev = ProviderCostEvent(
            event_id=event_id_for(
                src="reservation",
                rid=r.get("id") or r.get("reservation_id"),
                pid=pid,
                start=start,
                tokens=(r.get("actual_tokens_in"), r.get("actual_tokens_out")),
            ),
            provider="deepseek",
            classification=CLASS_TRADE_AI_TEST if test else CLASS_TRADE_AI_PRODUCTION,
            attribution_confidence=CONF_STRONG,
            usage_start=start,
            model=r.get("model"),
            source_service="cio_governed_bridge",
            source_process=str(pid) if pid else None,
            reservation_id=str(r.get("id") or r.get("reservation_id") or ""),
            request_id=r.get("request_id"),
            input_tokens=_int(r.get("actual_tokens_in") or r.get("tokens_in")),
            output_tokens=_int(r.get("actual_tokens_out") or r.get("tokens_out")),
            calculated_cost_usd=reserved,
            provider_reported_cost_usd=actual,
            cost_source=COST_SOURCE_PROVIDER_REPORTED if actual is not None else COST_SOURCE_LOCAL_CALCULATED,
            is_test=test,
            environment="test" if test else "production",
            evidence_refs=["llm_cost_reservations"],
        )
        events.append(ev)
    return events


def parse_consumption_rows(rows: Iterable[dict[str, Any]], *, at_default: str) -> list[ProviderCostEvent]:
    """Trade AI llm_consumption_log. estimated_cost_usd may be k-char — never use as USD
    unless cost_basis says provider_usage_x_registry_snapshot."""
    events: list[ProviderCostEvent] = []
    for r in rows:
        basis = str(r.get("cost_basis") or "")
        chars = _int(r.get("prompt_chars"))
        if chars is None:
            chars = _int(r.get("relative_units"))
        start = _iso(r.get("created_at") or r.get("usage_start") or at_default)
        model = r.get("model") or r.get("returned_model") or "deepseek-v4-flash"
        hit = _int(r.get("cache_hit_tokens") or r.get("prompt_cache_hit_tokens")) or 0
        miss = _int(r.get("cache_miss_tokens") or r.get("prompt_cache_miss_tokens"))
        if miss is None:
            miss = _int(r.get("tokens_in") or r.get("prompt_tokens")) or 0
        out = _int(r.get("tokens_out") or r.get("completion_tokens")) or 0
        priced = calculate_usd(
            provider="deepseek",
            model=str(model),
            at=start,
            cache_hit_input=hit,
            cache_miss_input=miss,
            output=out,
        )
        stored = money(r.get("estimated_cost_usd"))
        # k-char pollution: if basis is missing/oauth or value is huge vs tokens, ignore stored USD
        stored_is_usd = basis == "provider_usage_x_registry_snapshot"
        ev = ProviderCostEvent(
            event_id=event_id_for(
                src="consumption",
                id=r.get("id"),
                start=start,
                model=model,
                tok=(hit, miss, out),
            ),
            provider="deepseek",
            classification=CLASS_TRADE_AI_PRODUCTION,
            attribution_confidence=CONF_STRONG if stored_is_usd else CONF_INFERRED,
            usage_start=start,
            model=str(model),
            source_service=r.get("process_id") or "llm_consumption_log",
            source_process=r.get("process_id"),
            request_id=r.get("request_id"),
            input_tokens=miss,
            cached_input_tokens=hit,
            output_tokens=out,
            characters=chars,
            calculated_cost_usd=priced.get("calculated_cost_usd"),
            provider_reported_cost_usd=stored if stored_is_usd else None,
            cost_source=priced.get("cost_source") or PRICE_UNKNOWN,
            price_schedule_id=priced.get("price_schedule_id"),
            evidence_refs=["llm_consumption_log", f"cost_basis={basis or 'unset'}"],
        )
        events.append(ev)
    return events


def parse_openclaw_jsonl(paths: Iterable[Path]) -> list[ProviderCostEvent]:
    events: list[ProviderCostEvent] = []
    seen: set[str] = set()
    for path in paths:
        if not Path(path).is_file():
            continue
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            usage = obj.get("usage") or obj.get("tokenUsage") or {}
            model = obj.get("model") or obj.get("providerModel") or ""
            if "deepseek" not in str(model).lower() and "deepseek" not in str(obj.get("provider") or "").lower():
                # still accept explicit cost on deepseek provider traces
                if obj.get("provider") not in {"deepseek", "DeepSeek"}:
                    continue
            start = _iso(obj.get("timestamp") or obj.get("created_at") or obj.get("ts"))
            tin = _int(usage.get("input") or usage.get("prompt_tokens") or usage.get("input_tokens")) or 0
            tout = _int(usage.get("output") or usage.get("completion_tokens") or usage.get("output_tokens")) or 0
            reported = money(obj.get("cost") or obj.get("costUsd") or usage.get("cost"))
            eid = event_id_for(src="openclaw", path=str(path), start=start, model=model, tok=(tin, tout), msg=obj.get("id") or obj.get("messageId"))
            if eid in seen:
                continue
            seen.add(eid)
            priced = calculate_usd(provider="deepseek", model=str(model or "deepseek-v4-pro"), at=start, cache_miss_input=tin, output=tout)
            events.append(
                ProviderCostEvent(
                    event_id=eid,
                    provider="deepseek",
                    classification=CLASS_OPENCLAW,
                    attribution_confidence=CONF_STRONG if (tin or tout) else CONF_INFERRED,
                    usage_start=start,
                    model=str(model) or None,
                    source_service="openclaw",
                    source_host="linux",
                    input_tokens=tin,
                    output_tokens=tout,
                    calculated_cost_usd=priced.get("calculated_cost_usd"),
                    provider_reported_cost_usd=reported,
                    cost_source=priced.get("cost_source"),
                    price_schedule_id=priced.get("price_schedule_id"),
                    evidence_refs=[str(path)],
                )
            )
    return events


def parse_claude_code_jsonl(paths: Iterable[Path]) -> list[ProviderCostEvent]:
    """Claude Code Linux traces. Separate classification — not Trade AI ledger."""
    events: list[ProviderCostEvent] = []
    seen: set[str] = set()
    for path in paths:
        p = Path(path)
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            model = str(obj.get("model") or obj.get("message", {}).get("model") or "")
            if "deepseek" not in model.lower():
                continue
            usage = obj.get("usage") or (obj.get("message") or {}).get("usage") or {}
            start = _iso(obj.get("timestamp") or obj.get("created_at"))
            tin = _int(usage.get("input_tokens") or usage.get("prompt_tokens")) or 0
            tout = _int(usage.get("output_tokens") or usage.get("completion_tokens")) or 0
            cache = _int(usage.get("cache_read_input_tokens") or usage.get("cache_read_tokens")) or 0
            eid = event_id_for(src="claude_code", path=str(p), start=start, model=model, tok=(tin, tout, cache))
            if eid in seen:
                continue
            seen.add(eid)
            priced = calculate_usd(
                provider="deepseek",
                model=model.replace("[1m]", ""),
                at=start,
                cache_hit_input=cache,
                cache_miss_input=tin,
                output=tout,
            )
            reported = money(obj.get("costUsd") or obj.get("cost"))
            events.append(
                ProviderCostEvent(
                    event_id=eid,
                    provider="deepseek",
                    classification=CLASS_CLAUDE_CODE,
                    attribution_confidence=CONF_STRONG,
                    usage_start=start,
                    model=model,
                    source_service="claude_code",
                    source_host="linux",
                    source_process="claude",
                    input_tokens=tin,
                    cached_input_tokens=cache,
                    output_tokens=tout,
                    calculated_cost_usd=priced.get("calculated_cost_usd"),
                    provider_reported_cost_usd=reported,
                    cost_source=priced.get("cost_source"),
                    price_schedule_id=priced.get("price_schedule_id"),
                    evidence_refs=[str(p)],
                )
            )
    return events


def parse_bypass_rows(rows: Iterable[dict[str, Any]]) -> list[ProviderCostEvent]:
    events: list[ProviderCostEvent] = []
    for r in rows:
        start = _iso(r.get("usage_start") or r.get("created_at"))
        ev = ProviderCostEvent(
            event_id=event_id_for(src="bypass", site=r.get("call_site_id"), start=start, tok=r.get("tokens")),
            provider=str(r.get("provider") or "deepseek"),
            classification=CLASS_KNOWN_BYPASS,
            attribution_confidence=str(r.get("attribution_confidence") or CONF_INFERRED),
            usage_start=start,
            model=r.get("model"),
            source_service=r.get("call_site_id"),
            source_process=r.get("source_process"),
            input_tokens=_int(r.get("input_tokens")),
            output_tokens=_int(r.get("output_tokens")),
            calculated_cost_usd=money(r.get("calculated_cost_usd")),
            provider_reported_cost_usd=money(r.get("provider_reported_cost_usd")),
            evidence_refs=list(r.get("evidence_refs") or ["known_bypass_inventory"]),
        )
        events.append(ev)
    return events


def _int(value: Any) -> Optional[int]:
    if value is None or value == "" or str(value).upper() == "UNKNOWN":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> Optional[float]:
    if value is None or value == "" or str(value).upper() == "UNKNOWN":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
