"""Deterministic reconciliation. Never double-count. Never allocate unknown."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Iterable, Optional

from .schema import (
    CLASS_CLAUDE_CODE,
    CLASS_CONSOLE_TOTAL,
    CLASS_KNOWN_BYPASS,
    CLASS_OPENCLAW,
    CLASS_TRADE_AI_PRODUCTION,
    CLASS_TRADE_AI_TEST,
    CONF_EXACT,
    CONF_INFERRED,
    CONF_STRONG,
    CONF_UNKNOWN,
    HOST_CLASSES,
    PRODUCTION_CLASSES,
    ProviderCostEvent,
    money,
)


def _usd(ev: ProviderCostEvent) -> float:
    v = ev.attributed_usd()
    return float(v) if v is not None else 0.0


def dedupe(events: Iterable[ProviderCostEvent]) -> tuple[list[ProviderCostEvent], int]:
    """Dedupe by event_id (stable identity), never by dollar amount."""
    seen: dict[str, ProviderCostEvent] = {}
    prevented = 0
    for ev in events:
        if ev.event_id in seen:
            prevented += 1
            continue
        seen[ev.event_id] = ev
    return list(seen.values()), prevented


def reconcile(
    events: Iterable[ProviderCostEvent],
    *,
    supplied_baseline: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    uniq, prevented = dedupe(events)
    console = [e for e in uniq if e.classification == CLASS_CONSOLE_TOTAL]
    others = [e for e in uniq if e.classification != CLASS_CONSOLE_TOTAL]
    console_total = round(sum(_usd(e) for e in console), 6)

    by_class: dict[str, float] = defaultdict(float)
    by_conf: dict[str, float] = defaultdict(float)
    by_model: dict[str, float] = defaultdict(float)
    by_service: dict[str, float] = defaultdict(float)
    test_only = 0.0
    for e in others:
        usd = _usd(e)
        by_class[e.classification] += usd
        by_conf[e.attribution_confidence] += usd
        if e.model:
            by_model[str(e.model)] += usd
        svc = e.source_service or e.classification
        by_service[str(svc)] += usd
        if e.is_test or e.classification == CLASS_TRADE_AI_TEST:
            test_only += usd

    # LEDGER = Trade AI production + OpenClaw + known bypass (NOT test, NOT Claude Code)
    ledger_classes = {CLASS_TRADE_AI_PRODUCTION, CLASS_OPENCLAW, CLASS_KNOWN_BYPASS}
    ledger_events = [e for e in others if e.classification in ledger_classes and not e.is_test]
    ledger_attributed = round(sum(_usd(e) for e in ledger_events), 6)

    host_events = [e for e in others if e.classification in HOST_CLASSES and not e.is_test]
    host_attributed = round(sum(_usd(e) for e in host_events), 6)

    exact = round(by_conf.get(CONF_EXACT, 0.0), 6)
    strong = round(by_conf.get(CONF_STRONG, 0.0), 6)
    inferred = round(by_conf.get(CONF_INFERRED, 0.0), 6)
    unknown_conf = round(by_conf.get(CONF_UNKNOWN, 0.0), 6)

    ledger_gap = round(console_total - ledger_attributed, 6) if console else None
    host_gap = round(console_total - host_attributed, 6) if console else None

    residual = None
    residual_class = None
    if console_total:
        residual = host_gap
        if residual is not None and abs(residual) > 0.05:
            residual_class = "UNATTRIBUTABLE_WITH_CURRENT_PROVIDER_DATA"

    report = {
        "schema_version": "ProviderSpendReconciliation@v1",
        "CONSOLE_TOTAL": console_total,
        "ATTRIBUTED_TOTAL": round(ledger_attributed, 6),
        "UNATTRIBUTED_GAP": ledger_gap,
        "LEDGER_ATTRIBUTED": ledger_attributed,
        "HOST_ATTRIBUTED": host_attributed,
        "LEDGER_GAP": ledger_gap,
        "HOST_GAP": host_gap,
        "EXACT_ATTRIBUTED": exact,
        "STRONG_ATTRIBUTED": strong,
        "INFERRED_ATTRIBUTED": inferred,
        "UNKNOWN": unknown_conf,
        "TEST_ONLY_COST": round(test_only, 6),
        "CLAUDE_CODE": round(by_class.get(CLASS_CLAUDE_CODE, 0.0), 6),
        "OPENCLAW": round(by_class.get(CLASS_OPENCLAW, 0.0), 6),
        "TRADE_AI_PRODUCTION": round(by_class.get(CLASS_TRADE_AI_PRODUCTION, 0.0), 6),
        "KNOWN_BYPASS": round(by_class.get(CLASS_KNOWN_BYPASS, 0.0), 6),
        "by_class": {k: round(v, 6) for k, v in sorted(by_class.items())},
        "by_model": {k: round(v, 6) for k, v in sorted(by_model.items())},
        "by_service": {k: round(v, 6) for k, v in sorted(by_service.items())},
        "double_count_prevented": prevented,
        "event_count": len(uniq),
        "residual_unattributable_usd": residual,
        "residual_disposition": residual_class,
        "supplied_baseline": supplied_baseline,
        "notes": [
            "LEDGER_GAP excludes Claude Code (outside Trade AI ledger).",
            "HOST_GAP includes Claude Code on this host.",
            "test_* reservations are TEST_ONLY_COST and excluded from production.",
            "Character counts are never treated as USD.",
            "INFERRED is not presented as EXACT.",
        ],
    }
    blob = json.dumps(
        {k: report[k] for k in report if k != "supplied_baseline"},
        sort_keys=True,
        default=str,
    )
    report["report_hash"] = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return report
