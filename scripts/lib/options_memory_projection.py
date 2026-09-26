"""Options thesis store -> CIO bitemporal memory (M2) envelopes. Pure mapping.

2026-09-26 (operator): the CIO agent's long-term memory (memory_r10_m2) held
nothing about options. Every thesis version, CIO decision, follow-up, live
validation and abandonment lives only in data/cio/options_theses.jsonl
(OptionsThesisStore: append-only, hash-chained). This module maps those events
to CIOEnvelopeIntegrator envelopes; scripts/options_memory_projector.py writes
them.

Identity (one identity per distinct fact, because save_bitemporal_fact_version
closes every current row of an identity):

  OPTIONS_THESIS_VERSION            -> options_thesis        subject = option_strategy_guid (single-valued)
  OPTIONS_THESIS_DECISION           -> options_cio_decision  subject = uuid5(guid|decision_guid)
  OPTIONS_THESIS_FOLLOWUP_REQUESTED -> options_followup      subject = uuid5(guid|event_hash)
  OPTIONS_THESIS_FOLLOWUP_COMPLETE  -> options_followup      subject = uuid5(guid|event_hash)
  OPTIONS_VALIDATED                 -> options_validation    subject = uuid5(guid|event_hash)
  OPTIONS_THESIS_ABANDONED          -> options_thesis_outcome subject = uuid5(guid|event_hash)

The object payload is a strict allowlist per predicate. Account, contract
count, premium totals, max loss, capital required and quote sizes never leave
the thesis store (MBI_BEHAVIOR=0; cognitive memory is not financial truth).

AUTHORITY: READ_ONLY_ADVISORY. Nothing here sizes, orders or connects.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Iterable, Optional

SCHEMA = "OptionsMemoryProjection@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0
SOURCE_TYPE = "options_thesis_store"
PROVENANCE_SOURCE = "options_memory_projector"

EVENT_PREDICATES = {
    "OPTIONS_THESIS_VERSION": "options_thesis",
    "OPTIONS_THESIS_DECISION": "options_cio_decision",
    "OPTIONS_THESIS_FOLLOWUP_REQUESTED": "options_followup",
    "OPTIONS_THESIS_FOLLOWUP_COMPLETE": "options_followup",
    "OPTIONS_VALIDATED": "options_validation",
    "OPTIONS_THESIS_ABANDONED": "options_thesis_outcome",
}

# Keys that must never reach cognitive memory from an options event, at any
# depth. The integrator's FORBIDDEN_OBJECT_KEYS is checked on top of this.
OPTIONS_FORBIDDEN_KEYS = frozenset(
    {
        "account",
        "account_number",
        "broker_account",
        "contracts",
        "premium",
        "premium_total",
        "max_loss",
        "max_profit",
        "capital_required",
        "bid",
        "ask",
        "bid_size",
        "ask_size",
        "mid",
        "last",
        "portfolio_impact",
        "position_sizing_rationale",
        "recomputed",
        "live",
        "entry_criteria",
        "cash",
        "qty",
        "quantity",
        "shares",
        "size_usd",
        "order",
        "stop",
        "limit",
    }
)

# Text fields are clipped so one verbose review cannot dominate the payload.
TEXT_CLIP = 600
LIST_CLIP = 8


def _clip(v: Any, n: int = TEXT_CLIP) -> Any:
    if isinstance(v, str) and len(v) > n:
        return v[:n] + "…"
    return v


def _str_list(v: Any, n: int = LIST_CLIP) -> list[str]:
    if not isinstance(v, (list, tuple)):
        return []
    return [_clip(str(x)) for x in v if x not in (None, "")][:n]


def _thesis_object(e: dict[str, Any]) -> dict[str, Any]:
    it = e.get("investment_thesis") if isinstance(e.get("investment_thesis"), dict) else {}
    return {
        "strategy": e.get("strategy_type"),
        "pin": e.get("pin"),
        "version": e.get("version"),
        "supersedes": e.get("supersedes"),
        "thesis_state": e.get("thesis_gate_state"),
        "missing_required": _str_list(e.get("missing_required"), 20),
        "catalysts": _str_list(e.get("catalysts")),
        "exit_criteria": _str_list(e.get("exit_criteria")),
        "investment_thesis": {
            "summary": _clip(it.get("summary")),
            "state": it.get("state"),
            "stance": it.get("stance"),
            "pin": it.get("pin"),
        }
        if it
        else None,
    }


def _decision_object(e: dict[str, Any]) -> dict[str, Any]:
    rv = e.get("review") if isinstance(e.get("review"), dict) else {}
    return {
        "decision_guid": e.get("decision_guid"),
        "outcome": e.get("outcome") or rv.get("outcome"),
        "confidence": e.get("confidence") or rv.get("confidence"),
        "reasoning": _clip(rv.get("reasoning")),
        "concerns": _str_list(rv.get("concerns")),
        "unknowns": _str_list(rv.get("unknowns")),
        "assumptions_challenged": _str_list(rv.get("assumptions_challenged")),
        "reviewed_pin": e.get("reviewed_pin"),
        "supersedes": e.get("supersedes"),
    }


def _deliverable_texts(v: Any) -> list[str]:
    out: list[str] = []
    for d in v or []:
        if isinstance(d, dict):
            t = d.get("text") or d.get("deliverable")
        else:
            t = d
        if t:
            out.append(_clip(str(t)))
    return out[:LIST_CLIP]


def _followup_object(e: dict[str, Any]) -> dict[str, Any]:
    if e.get("event_type") == "OPTIONS_THESIS_FOLLOWUP_COMPLETE":
        answers = [a for a in (e.get("answers") or []) if isinstance(a, dict)]
        return {
            "stage": "COMPLETE",
            "research_id": e.get("research_id"),
            "deliverables": _deliverable_texts(answers),
            "answers": [
                {
                    "deliverable": _clip(str(a.get("deliverable") or "")),
                    "answered": bool(a.get("answered")),
                    "answer": _clip(a.get("answer")),
                }
                for a in answers
            ][:LIST_CLIP],
        }
    return {
        "stage": "REQUESTED",
        "research_id": e.get("research_id"),
        "deliverables": _deliverable_texts(e.get("deliverables")),
        "due_at": e.get("due_at"),
        "for_decision": e.get("for_decision"),
    }


def _validation_object(e: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": e.get("status"),
        "material_changes": _str_list(e.get("material_changes")),
        "validated_at": e.get("validated_at") or e.get("recorded_at"),
    }


def _outcome_object(e: dict[str, Any]) -> dict[str, Any]:
    return {
        "outcome": "ABANDONED",
        "reason": _clip(e.get("reason")),
        "missing_required": _str_list(e.get("missing"), 20),
    }


_OBJECT_BUILDERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "options_thesis": _thesis_object,
    "options_cio_decision": _decision_object,
    "options_followup": _followup_object,
    "options_validation": _validation_object,
    "options_thesis_outcome": _outcome_object,
}


def forbidden_keys_deep(obj: Any) -> set[str]:
    """Every forbidden key present anywhere in ``obj``."""
    try:
        from scripts.lib.cio_memory_integration import FORBIDDEN_OBJECT_KEYS
    except ImportError:  # scripts/ on sys.path
        from lib.cio_memory_integration import FORBIDDEN_OBJECT_KEYS  # type: ignore
    bad_keys = OPTIONS_FORBIDDEN_KEYS | FORBIDDEN_OBJECT_KEYS
    found: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in bad_keys:
                found.add(k)
            found |= forbidden_keys_deep(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            found |= forbidden_keys_deep(v)
    return found


def subject_for(predicate: str, event: dict[str, Any]) -> str:
    guid = str(event.get("position_guid") or "")
    if predicate == "options_thesis":
        return guid
    if predicate == "options_cio_decision":
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:options_memory:{guid}|{event.get('decision_guid')}"))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:options_memory:{predicate}:{guid}|{event.get('event_hash')}"))


def symbol_index(events: Iterable[dict[str, Any]]) -> dict[str, str]:
    """option_strategy_guid -> symbol, from thesis versions (decisions carry no symbol)."""
    out: dict[str, str] = {}
    for e in events:
        if e.get("position_guid") and e.get("symbol"):
            out[str(e["position_guid"])] = str(e["symbol"]).upper()
    return out


def decision_index(events: Iterable[dict[str, Any]]) -> dict[str, str]:
    """decision_guid -> event_hash of the event that issued it (for SUPERSEDES edges)."""
    return {
        str(e["decision_guid"]): str(e.get("event_hash"))
        for e in events
        if e.get("event_type") == "OPTIONS_THESIS_DECISION" and e.get("decision_guid")
    }


def _claim(predicate: str, sym: str, obj: dict[str, Any]) -> str:
    if predicate == "options_thesis":
        summ = ((obj.get("investment_thesis") or {}).get("summary") or "").strip()
        return (
            f"{sym} {obj.get('strategy') or 'option'} thesis {obj.get('pin')}: "
            f"state {obj.get('thesis_state')}" + (f" - {summ}" if summ else "")
        )[:TEXT_CLIP]
    if predicate == "options_cio_decision":
        return (
            f"CIO options decision {sym}: {obj.get('outcome')} ({obj.get('confidence')}) - {obj.get('reasoning') or ''}"
        )[:TEXT_CLIP]
    if predicate == "options_followup":
        return f"{sym} CIO follow-up research {str(obj.get('stage')).lower()}: {len(obj.get('deliverables') or [])} deliverable(s)"
    if predicate == "options_validation":
        return f"{sym} option live validation: {obj.get('status')}"
    return f"{sym} options thesis {str(obj.get('outcome')).lower()}: {obj.get('reason') or ''}"[:TEXT_CLIP]


def map_event(
    event: dict[str, Any],
    *,
    symbols: Optional[dict[str, str]] = None,
    decisions: Optional[dict[str, str]] = None,
    issuer_resolver: Optional[Callable[[str], Optional[str]]] = None,
) -> Optional[dict[str, Any]]:
    """One store event -> one integrator envelope (or None when not projected).

    The envelope carries ``provenance`` (a planned SUPERSEDES edge) when the
    event is a decision that supersedes an earlier one; the projector resolves
    both ends to fact ids at write time.
    """
    et = str(event.get("event_type") or "")
    predicate = EVENT_PREDICATES.get(et)
    guid = str(event.get("position_guid") or "")
    ehash = str(event.get("event_hash") or "")
    if not predicate or not guid or not ehash:
        return None
    sym = str(event.get("symbol") or (symbols or {}).get(guid) or "").upper() or None
    obj = {"option_strategy_guid": guid, "symbol": sym, "event_type": et, "recorded_at": event.get("recorded_at")}
    obj.update(_OBJECT_BUILDERS[predicate](event))
    obj = {k: v for k, v in obj.items() if v is not None}
    bad = forbidden_keys_deep(obj)
    if bad:  # defence in depth: the builders are allowlists, so this is a code defect
        raise RuntimeError(f"FINANCIAL_TRUTH_REFUSED: options memory payload has {sorted(bad)}")
    issuer = None
    if sym:
        try:
            issuer = (issuer_resolver or _default_issuer_resolver)(sym)
        except Exception:  # noqa: BLE001 — unknown issuer is "no issuer", not an error
            issuer = None
    issuer = issuer or event.get("underlying_issuer_guid") or None
    env: dict[str, Any] = {
        "predicate": predicate,
        "claim": _claim(predicate, sym or "?", obj),
        "object": obj,
        "symbol": sym,
        "subject_guid": subject_for(predicate, event),
        "issuer_guid": issuer,
        "valid_from": event.get("recorded_at"),
        "source_type": SOURCE_TYPE,
        "source_id": ehash,
        "trace_id": guid,
    }
    sup = event.get("supersedes") if predicate == "options_cio_decision" else None
    if sup:
        env["provenance"] = {
            "relation": "SUPERSEDES",
            "from_source_id": ehash,
            "to_source_id": (decisions or {}).get(str(sup)),
            "supersedes_decision_guid": str(sup),
        }
    return {k: v for k, v in env.items() if v is not None}


def _default_issuer_resolver(sym: str) -> Optional[str]:
    try:
        from scripts.lib.options_identity import resolve_issuer_guid
    except ImportError:
        from lib.options_identity import resolve_issuer_guid  # type: ignore
    return resolve_issuer_guid(sym)


def pending_events(events: list[dict[str, Any]], watermark: Optional[str]) -> tuple[list[dict[str, Any]], bool]:
    """Events after the watermark event_hash. (events, watermark_found).

    A watermark that is not in the log (store rewritten or restored) projects
    everything again; the projector's source_id check keeps that idempotent.
    """
    if not watermark:
        return list(events), True
    for i, e in enumerate(events):
        if e.get("event_hash") == watermark:
            return list(events[i + 1 :]), True
    return list(events), False


def plan(
    events: list[dict[str, Any]],
    watermark: Optional[str] = None,
    *,
    issuer_resolver: Optional[Callable[[str], Optional[str]]] = None,
) -> dict[str, Any]:
    """Map every pending event. Pure: no connection, no file writes."""
    symbols = symbol_index(events)
    decisions = decision_index(events)
    todo, found = pending_events(events, watermark)
    envelopes: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    for e in todo:
        env = map_event(e, symbols=symbols, decisions=decisions, issuer_resolver=issuer_resolver)
        if env is None:
            et = str(e.get("event_type") or "UNKNOWN")
            skipped[et] = skipped.get(et, 0) + 1
            continue
        envelopes.append(env)
    counts: dict[str, int] = {}
    for env in envelopes:
        counts[env["predicate"]] = counts.get(env["predicate"], 0) + 1
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "mbi_behavior": MBI_BEHAVIOR,
        "events_total": len(events),
        "events_pending": len(todo),
        "watermark": watermark,
        "watermark_found": found,
        "new_watermark": todo[-1].get("event_hash") if todo else watermark,
        "counts": counts,
        "not_projected": skipped,
        "provenance_planned": sum(1 for e in envelopes if e.get("provenance")),
        "envelopes": envelopes,
    }


__all__ = [
    "SCHEMA",
    "SOURCE_TYPE",
    "EVENT_PREDICATES",
    "OPTIONS_FORBIDDEN_KEYS",
    "forbidden_keys_deep",
    "map_event",
    "pending_events",
    "plan",
    "subject_for",
]
