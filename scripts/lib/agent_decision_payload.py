"""agent_decision_payload.py — DecisionPayload@v1 + fail-soft emit (Phase 1).

READ_ONLY_ADVISORY. Captures operator-visible decision lineage for shadow
acceptance / memory promotion. Does NOT change decision semantics.

Flag: AGENT_DECISION_PAYLOAD (default 0).
  * OFF — no build, no append (parity with pre-Phase-1).
  * ON  — append one completed AgentRunTrace@v1 per decision with ``decision``
    set to DecisionPayload@v1 (redacted via sanitize_trace).

Emit failures never raise and never mutate the caller's decision dict.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.agent_feature_flags import load_feature_flags
from scripts.lib.agent_run_trace import (
    DEFAULT_TRACE_PATH,
    STATUS_COMPLETED,
    append_trace,
    build_trace,
    close_trace,
    new_trace_id,
    sanitize_trace,
)

PAYLOAD_SCHEMA = "DecisionPayload@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

VALID_ORIGINS = frozenset({
    "DETERMINISTIC_RANK",
    "FRESH_RESEARCH",
    "MEMORY_INFLUENCED",
    "OPERATOR_ASK",
    "SYNTHESIZED",  # never count toward promotion arithmetic
})

VALID_SURFACES = frozenset({
    "reentry",
    "watch",
    "opportunity",
    "advisory",
    "freeform",
    "material_scan",
    "product_notify",
    "situation",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def decision_payload_enabled(flags: Optional[dict[str, Any]] = None) -> bool:
    flags = flags if flags is not None else load_feature_flags()
    return int(flags.get("AGENT_DECISION_PAYLOAD") or 0) == 1


def _digest(parts: list[Any]) -> str:
    raw = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return "ctx_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def infer_decision_origin(
    *,
    trigger: Optional[str] = None,
    provenance: Optional[dict[str, Any]] = None,
    memory_influenced: bool = False,
    synthesized: bool = False,
) -> str:
    """Honest origin label — never invent FRESH_RESEARCH."""
    if synthesized:
        return "SYNTHESIZED"
    if memory_influenced:
        return "MEMORY_INFLUENCED"
    if isinstance(provenance, dict):
        o = str(provenance.get("decision_origin") or "").upper()
        if o in VALID_ORIGINS:
            return o
    t = str(trigger or "").upper()
    if "OPERATOR" in t or "ASK" in t or "FREEFORM" in t:
        return "OPERATOR_ASK"
    if "RESEARCH" in t or "HERMES" in t or "FLASH" in t:
        return "FRESH_RESEARCH"
    return "DETERMINISTIC_RANK"


def build_decision_payload(
    *,
    decision_id: Optional[str] = None,
    wake_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    symbol: Optional[str] = None,
    surface: str = "advisory",
    current_action: Optional[str] = None,
    act_now: bool = False,
    confidence: Optional[float] = None,
    decision_origin: str = "DETERMINISTIC_RANK",
    inputs_digest: Optional[str] = None,
    evidence_refs: Optional[list[Any]] = None,
    gates_evaluated: Optional[list[dict[str, Any]]] = None,
    next_review: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build DecisionPayload@v1. Missing facts stay None / DATA_UNAVAILABLE — never invented."""
    surf = str(surface or "advisory").lower()
    if surf not in VALID_SURFACES:
        surf = "advisory"
    origin = str(decision_origin or "DETERMINISTIC_RANK").upper()
    if origin not in VALID_ORIGINS:
        origin = "DETERMINISTIC_RANK"

    action = current_action
    if action is None or action == "":
        action = "DATA_UNAVAILABLE"
    else:
        action = str(action).upper()

    conf: Optional[float] = None
    if confidence is not None:
        try:
            conf = float(confidence)
            if conf != conf:  # NaN
                conf = None
        except (TypeError, ValueError):
            conf = None

    did = str(decision_id or "").strip() or f"dec_{uuid.uuid4().hex[:12]}"
    wid = str(wake_id or "").strip() or f"wake_{uuid.uuid4().hex[:12]}"
    tid = str(trace_id or "").strip() or new_trace_id(wid)

    payload: dict[str, Any] = {
        "schema": PAYLOAD_SCHEMA,
        "decision_id": did,
        "wake_id": wid,
        "trace_id": tid,
        "symbol": (str(symbol).upper() if symbol else None),
        "surface": surf,
        "current_action": action,
        "act_now": bool(act_now),
        "confidence": conf,
        "decision_origin": origin,
        "inputs_digest": inputs_digest or _digest([did, wid, surf, action]),
        "evidence_refs": list(evidence_refs or [])[:20],
        "gates_evaluated": list(gates_evaluated or [])[:20],
        "next_review": next_review if isinstance(next_review, dict) else None,
        "authority": AUTHORITY,
        "financial_action": False,
        "as_of": _now_iso(),
    }
    if isinstance(extra, dict):
        for k, v in extra.items():
            if k in payload or v is None:
                continue
            # Never allow CoT / secret-shaped keys through extras
            kl = str(k).lower()
            if kl in {"chain_of_thought", "cot", "reasoning", "api_key", "token", "password"}:
                continue
            payload[k] = v
    return payload


def payload_from_material_decision(
    decision: dict[str, Any],
    *,
    wake_id: str,
    trace_id: Optional[str] = None,
    surface: str = "material_scan",
) -> dict[str, Any]:
    """Map a material-scan decision dict → DecisionPayload@v1."""
    d = decision if isinstance(decision, dict) else {}
    origin = infer_decision_origin(
        trigger=str(d.get("trigger") or d.get("category") or ""),
        provenance=d.get("provenance") if isinstance(d.get("provenance"), dict) else None,
    )
    action = (
        d.get("current_action")
        or d.get("standing_recommendation")
        or d.get("action")
        or d.get("status")
    )
    return build_decision_payload(
        decision_id=d.get("decision_id"),
        wake_id=wake_id,
        trace_id=trace_id,
        symbol=d.get("symbol"),
        surface=surface,
        current_action=action,
        act_now=bool(d.get("act_now") or str(action or "").upper() in {"RE_ENTER", "DO_NOW", "ACT_NOW"}),
        confidence=d.get("confidence"),
        decision_origin=origin,
        evidence_refs=d.get("evidence_refs") or d.get("evidence_ids") or [],
        gates_evaluated=d.get("gates_evaluated") if isinstance(d.get("gates_evaluated"), list) else [],
        next_review=d.get("next_review") if isinstance(d.get("next_review"), dict) else None,
    )


def payload_from_symbol_intelligence(
    card: dict[str, Any],
    *,
    wake_id: str,
    trace_id: Optional[str] = None,
    change_item: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Map an Investment Intelligence / SIO card → DecisionPayload@v1."""
    c = card if isinstance(card, dict) else {}
    change = change_item if isinstance(change_item, dict) else (c.get("change") or {})
    tech = c.get("technical") if isinstance(c.get("technical"), dict) else {}
    prov = c.get("provenance") if isinstance(c.get("provenance"), dict) else {}
    kind = str(change.get("kind") or "")
    surface = "reentry" if "reentry" in kind else (
        "opportunity" if "opportunity" in kind else "product_notify"
    )
    origin = infer_decision_origin(
        trigger=str(prov.get("trigger") or ""),
        provenance=prov,
    )
    to_state = change.get("to") or tech.get("status")
    return build_decision_payload(
        decision_id=c.get("object_id") or f"dec_{c.get('symbol')}_{kind}",
        wake_id=wake_id,
        trace_id=trace_id,
        symbol=c.get("symbol"),
        surface=surface,
        current_action=to_state,
        act_now=False,
        confidence=(c.get("thesis") or {}).get("confidence_0_10")
        if isinstance(c.get("thesis"), dict) else None,
        decision_origin=origin,
        evidence_refs=[c.get("object_id")] if c.get("object_id") else [],
        gates_evaluated=[],
        next_review=None,
        extra={"change_kind": kind or None},
    )


def emit_decision_payload(
    payload: dict[str, Any],
    *,
    flags: Optional[dict[str, Any]] = None,
    path: Path | str | None = None,
    agent: str = "alex",
    role: str = "decision_capture",
) -> dict[str, Any]:
    """Append a completed AgentRunTrace carrying DecisionPayload@v1. Fail-soft.

    Returns ``{emitted, trace_id, wake_id, decision_id, error}``.
    """
    out: dict[str, Any] = {
        "emitted": False,
        "trace_id": None,
        "wake_id": None,
        "decision_id": None,
        "error": None,
    }
    try:
        if not decision_payload_enabled(flags):
            return out
        if not isinstance(payload, dict) or payload.get("schema") != PAYLOAD_SCHEMA:
            out["error"] = "invalid_payload"
            return out
        wake_id = str(payload.get("wake_id") or "")
        trace_id = str(payload.get("trace_id") or new_trace_id(wake_id))
        payload = dict(payload)
        payload["trace_id"] = trace_id
        started = build_trace(
            trace_id=trace_id,
            wake_id=wake_id,
            agent=agent,
            role=role,
            trigger=payload.get("surface"),
            status=STATUS_COMPLETED,
        )
        closed = close_trace(
            started,
            status=STATUS_COMPLETED,
            decision=sanitize_trace(payload),
            notification={"sent": False, "channel": None},
            operator=None,
            learning={"auto_promoted": False, "synthesized": payload.get("decision_origin") == "SYNTHESIZED"},
        )
        dest = Path(path) if path is not None else DEFAULT_TRACE_PATH
        ok = append_trace(closed, path=dest)
        out["emitted"] = bool(ok)
        out["trace_id"] = trace_id
        out["wake_id"] = wake_id
        out["decision_id"] = payload.get("decision_id")
        if not ok:
            out["error"] = "append_failed"
        return out
    except Exception as exc:  # noqa: BLE001 — fail-soft
        out["error"] = f"{type(exc).__name__}"
        return out


def emit_payloads_for_decisions(
    decisions: list[dict[str, Any]],
    *,
    wake_id: str,
    surface: str = "material_scan",
    flags: Optional[dict[str, Any]] = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Emit one payload per decision dict. Fail-soft aggregate."""
    flags = flags if flags is not None else load_feature_flags()
    if not decision_payload_enabled(flags):
        return {"emitted": 0, "attempted": 0, "errors": [], "enabled": False}
    emitted = 0
    errors: list[str] = []
    attempted = 0
    for d in decisions or []:
        if not isinstance(d, dict):
            continue
        attempted += 1
        try:
            pl = payload_from_material_decision(d, wake_id=wake_id, surface=surface)
            res = emit_decision_payload(pl, flags=flags, path=path, role=surface)
            if res.get("emitted"):
                emitted += 1
            elif res.get("error"):
                errors.append(str(res["error"]))
        except Exception as exc:  # noqa: BLE001
            errors.append(type(exc).__name__)
    return {
        "emitted": emitted,
        "attempted": attempted,
        "errors": errors[:10],
        "enabled": True,
    }


def count_decision_payloads(path: Path | str | None = None) -> dict[str, Any]:
    """Coverage helper over agent_run_traces.jsonl."""
    p = Path(path) if path else DEFAULT_TRACE_PATH
    total = 0
    with_decision = 0
    with_schema = 0
    synthesized = 0
    if not p.exists():
        return {
            "rows": 0,
            "with_decision": 0,
            "with_decision_payload_v1": 0,
            "synthesized": 0,
            "coverage": 0.0,
        }
    try:
        with open(p, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                dec = row.get("decision")
                if isinstance(dec, dict) and dec:
                    with_decision += 1
                    if dec.get("schema") == PAYLOAD_SCHEMA:
                        with_schema += 1
                    if dec.get("decision_origin") == "SYNTHESIZED":
                        synthesized += 1
    except Exception:
        pass
    cov = (with_schema / total) if total else 0.0
    return {
        "rows": total,
        "with_decision": with_decision,
        "with_decision_payload_v1": with_schema,
        "synthesized": synthesized,
        "coverage": round(cov, 4),
    }
