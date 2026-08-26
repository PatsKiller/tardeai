"""agent_decision_payload.py — DecisionPayload@v1 + fail-soft emit.

READ_ONLY_ADVISORY. Captures operator-visible decision lineage for shadow
acceptance / memory promotion. Does NOT change decision semantics.

Flag: AGENT_DECISION_PAYLOAD (default 0).
  * OFF — no build, no append (parity with pre-Phase-1).
  * ON  — append one completed AgentRunTrace@v1 per decision with ``decision``
    set to DecisionPayload@v1 (redacted via sanitize_trace).

Symbol hygiene: never persist membership labels (CASH, REENTRY, WATCH, …)
as tickers — ``ticker_or_unavailable`` maps them to DATA_UNAVAILABLE.

Emit failures never raise and never mutate the caller's decision dict.
"""
from __future__ import annotations

import hashlib
import json
import re
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
    "holdings",
    "freeform",
    "material_scan",
    "product_notify",
    "situation",
})

# Desk / book membership labels that must never be stored as a ticker.
MEMBERSHIP_LABELS = frozenset({
    "CASH",
    "REENTRY",
    "RE-ENTRY",
    "RE_ENTRY",
    "WATCH",
    "WATCHLIST",
    "WATCH_LIST",
    "PORTFOLIO",
    "BOOK",
    "ALLOCATION",
    "DESK",
    "MARKET",
    "HOLDINGS",
    "UNIVERSE",
    "ALL",
    "INDEX",
    "SECTOR",
    "THEME",
    "NONE",
    "NULL",
    "N/A",
    "NA",
    "UNKNOWN",
    "TBD",
    "OPPORTUNITY",
    "ADVISORY",
    "FREEFORM",
    "SITUATION",
    "TOTAL",
    "OTHER",
    "SPARE",
    "RESERVE",
    "CASH_POSTURE",
})

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

_REENTRY_READY_NEAR = frozenset({"READY TO REVIEW", "NEAR ENTRY"})
_REENTRY_STATE_ACTION = {
    "READY TO REVIEW": "READY",
    "NEAR ENTRY": "NEAR",
}
# Reentry was emitting per desk tick (~127/name/day). Emit on action CHANGE
# or a periodic heartbeat, not both on every wake.
REENTRY_HEARTBEAT_HOURS = 4.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ticker_or_unavailable(symbol: Any) -> str:
    """Return a real ticker, or DATA_UNAVAILABLE for membership labels / junk.

    Never emit ``CASH``, ``REENTRY``, or other desk membership labels as a
    ticker. Empty / None / malformed → DATA_UNAVAILABLE. Real tickers
    (``UBER``, ``BRK.B``, ``BF-B``) are uppercased and preserved.
    """
    if symbol is None:
        return "DATA_UNAVAILABLE"
    s = str(symbol).strip().upper()
    if not s or s in MEMBERSHIP_LABELS:
        return "DATA_UNAVAILABLE"
    if not _TICKER_RE.fullmatch(s):
        return "DATA_UNAVAILABLE"
    return s


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
    ticker = ticker_or_unavailable(symbol)

    payload: dict[str, Any] = {
        "schema": PAYLOAD_SCHEMA,
        "decision_id": did,
        "wake_id": wid,
        "trace_id": tid,
        "symbol": ticker,
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
    if ticker == "DATA_UNAVAILABLE":
        payload["data_unavailable"] = True
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


def enrich_payload_with_cognition(
    payload: dict[str, Any],
    *,
    cognition_root: Path | str | None = None,
    held: Optional[set[str]] = None,
) -> dict[str, Any]:
    """Attach bounded cognition refs + receipt. Never copies the brain blob.

    Fail-soft: DecisionPayload remains valid if resolution fails.
    Does not mutate current_action (financial-lane action stays as emitted).
    """
    out = dict(payload) if isinstance(payload, dict) else {}
    ticker = ticker_or_unavailable(out.get("symbol"))
    if ticker == "DATA_UNAVAILABLE":
        out["cognition_refs"] = {"skipped": "non_security_symbol", "schema": "CIOCognitionRefs@v1"}
        out["question"] = "WHAT_MATERIAL_THING_CHANGED_FOR_THE_PORTFOLIO"
        return out
    try:
        from scripts.lib.cio_persistent_cognition import resolve_decision_cognition

        resolved = resolve_decision_cognition(
            ticker,
            decision_id=str(out.get("decision_id") or ""),
            wake_id=str(out.get("wake_id") or ""),
            task=str(out.get("surface") or "material_scan"),
            root=cognition_root,
            held=held,
        )
        refs = resolved.get("refs") or {}
        rec = resolved.get("receipt") or {}
        out["cognition_refs"] = refs
        out["context_receipt"] = {
            "schema": rec.get("schema"),
            "run_id": rec.get("run_id"),
            "decision_id": rec.get("decision_id"),
            "recorded_at": rec.get("recorded_at"),
            "source_sha": rec.get("source_sha"),
        }
        out["security_guid"] = resolved.get("security_guid")
        out["portfolio_delta"] = resolved.get("portfolio_delta")
        out["question"] = "WHAT_MATERIAL_THING_CHANGED_FOR_THE_PORTFOLIO"
        out["ticker_research_state_version"] = refs.get("ticker_research_state_version")
        out["curation_version"] = refs.get("curation_version")
        out["curation_id"] = refs.get("curation_id")
        out["symbol_thesis_version"] = refs.get("symbol_thesis_version")
        out["research_gap_ids"] = refs.get("research_gap_ids")
    except Exception as exc:  # noqa: BLE001 — fail-soft
        out["cognition_refs"] = {"error": type(exc).__name__, "schema": "CIOCognitionRefs@v1"}
        out["question"] = "WHAT_MATERIAL_THING_CHANGED_FOR_THE_PORTFOLIO"
    return out


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


def payload_from_reentry_row(
    row: dict[str, Any],
    *,
    wake_id: str,
    trace_id: Optional[str] = None,
) -> dict[str, Any]:
    """Map a re-entry desk row (READY/NEAR + advisory) → DecisionPayload@v1."""
    r = row if isinstance(row, dict) else {}
    intel = r.get("intel") if isinstance(r.get("intel"), dict) else {}
    advisory = r.get("advisory") if isinstance(r.get("advisory"), dict) else {}
    state = str(intel.get("state") or r.get("state") or "").strip().upper()
    action = (
        _REENTRY_STATE_ACTION.get(state)
        or advisory.get("action")
        or intel.get("action")
        or state
    )
    gates = r.get("gates") if isinstance(r.get("gates"), list) else []
    gates_eval = [g for g in gates if isinstance(g, dict)][:20]
    sym = r.get("symbol") or r.get("ticker")
    thesis_gate = r.get("thesis_gate") if isinstance(r.get("thesis_gate"), dict) else {}
    delta = r.get("research_delta") if isinstance(r.get("research_delta"), dict) else {}
    return build_decision_payload(
        decision_id=r.get("decision_id") or f"dec_reentry_{sym}_{state.replace(' ', '_')}",
        wake_id=wake_id,
        trace_id=trace_id,
        symbol=sym,
        surface="reentry",
        current_action=action,
        act_now=False,
        confidence=r.get("confidence"),
        decision_origin=infer_decision_origin(trigger="REENTRY_DESK"),
        evidence_refs=[r.get("plan_as_of")] if r.get("plan_as_of") else [],
        gates_evaluated=gates_eval,
        extra={
            "producer": "reentry",
            "previous_action": r.get("previous_action"),
            "reason_codes": list(
                thesis_gate.get("reason_codes") or r.get("reason_codes") or []
            )[:20],
            "thesis_id": r.get("symbol_thesis_id") or r.get("thesis_id"),
            "thesis_version": r.get("symbol_thesis_version") or r.get("thesis_version"),
            "research_delta_id": delta.get("delta_id") or r.get("research_delta_id"),
            "research_delta_classification": (
                delta.get("classification") or r.get("research_delta_classification")
            ),
            "truth_inputs": r.get("truth_inputs"),
            "source_freshness": r.get("source_freshness"),
            "notification_outcome": r.get("notification_outcome"),
            "intel_state": state or None,
        },
    )


def payload_from_watch_alert(
    alert: dict[str, Any],
    *,
    wake_id: str,
    trace_id: Optional[str] = None,
    message: Optional[str] = None,
) -> dict[str, Any]:
    """Map a fired watch alert → DecisionPayload@v1 (surface=watch)."""
    a = alert if isinstance(alert, dict) else {}
    cond = str(a.get("condition_type") or a.get("condition") or "ALERT_FIRED")
    aid = a.get("id") or a.get("alert_id") or "na"
    sym = a.get("symbol") or a.get("ticker")
    return build_decision_payload(
        decision_id=f"dec_watch_{aid}_{sym or 'na'}",
        wake_id=wake_id,
        trace_id=trace_id,
        symbol=sym,
        surface="watch",
        current_action=cond,
        act_now=False,
        decision_origin=infer_decision_origin(trigger="WATCH_ALERT"),
        extra={
            "alert_id": aid,
            "condition_type": cond,
            "message_preview": (str(message)[:160] if message else None),
        },
    )


def payload_from_advisory_opinion(
    row: dict[str, Any],
    opinion: dict[str, Any],
    *,
    wake_id: str,
    trace_id: Optional[str] = None,
) -> dict[str, Any]:
    """Map an advisory-desk row + opinion → DecisionPayload@v1."""
    r = row if isinstance(row, dict) else {}
    o = opinion if isinstance(opinion, dict) else {}
    verdict = o.get("verdict") or r.get("verdict")
    conv = o.get("conviction")
    conf: Optional[float] = None
    if conv is not None:
        try:
            c = float(conv)
            conf = (c / 10.0) if c > 10.0 else c
        except (TypeError, ValueError):
            conf = None
    origin = infer_decision_origin(
        trigger="ADVISORY_OPINION",
        synthesized=bool(o.get("degraded") and o.get("llm_rejected")),
    )
    return build_decision_payload(
        decision_id=r.get("decision_id") or f"dec_adv_{r.get('symbol')}_{r.get('advisory_row_hash') or ''}"[:80],
        wake_id=wake_id,
        trace_id=trace_id,
        symbol=r.get("symbol") or r.get("ticker"),
        surface="advisory",
        current_action=verdict,
        act_now=str(verdict or "").upper() in {"RE_ENTER", "EXIT", "TRIM", "ADD"},
        confidence=conf,
        decision_origin=origin,
        evidence_refs=list(o.get("evidence_cited") or [])[:20],
        extra={
            "advisory_row_hash": r.get("advisory_row_hash"),
            "row_class": r.get("row_class"),
        },
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
    cognition_root: Path | str | None = None,
    held: Optional[set[str]] = None,
) -> dict[str, Any]:
    """Emit one payload per decision dict. Fail-soft aggregate.

    Resolves canonical CIO cognition at emit time (IDs/versions + receipt).
    """
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
            pl = enrich_payload_with_cognition(pl, cognition_root=cognition_root, held=held)
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


def _reentry_fingerprint_path(path: Path | str | None) -> Path:
    dest = Path(path) if path is not None else DEFAULT_TRACE_PATH
    return dest.parent / "reentry_payload_last.json"


def _load_reentry_last(fp: Path) -> dict[str, Any]:
    try:
        if fp.is_file():
            data = json.loads(fp.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def _save_reentry_last(fp: Path, blob: dict[str, Any]) -> None:
    try:
        fp.parent.mkdir(parents=True, exist_ok=True)
        tmp = fp.with_suffix(".tmp")
        tmp.write_text(json.dumps(blob, indent=2, default=str) + "\n", encoding="utf-8")
        tmp.replace(fp)
    except OSError:
        pass


def _reentry_should_emit(
    symbol: str,
    action: str,
    last: dict[str, Any],
    *,
    now: Optional[datetime] = None,
    heartbeat_hours: float = REENTRY_HEARTBEAT_HOURS,
) -> str:
    """Return 'change' | 'heartbeat' | 'skip'."""
    now = now or datetime.now(timezone.utc)
    prev = last.get(symbol) if isinstance(last.get(symbol), dict) else {}
    prev_action = str(prev.get("action") or "")
    if prev_action != str(action or ""):
        return "change"
    ts = prev.get("ts")
    if not ts:
        return "heartbeat"
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        age_h = (now - t.astimezone(timezone.utc)).total_seconds() / 3600.0
    except (TypeError, ValueError):
        return "heartbeat"
    if age_h >= float(heartbeat_hours):
        return "heartbeat"
    return "skip"


def emit_reentry_operator_payloads(
    rows: Optional[list[dict[str, Any]]],
    *,
    flags: Optional[dict[str, Any]] = None,
    path: Path | str | None = None,
    wake_id: Optional[str] = None,
    fingerprint_path: Path | str | None = None,
    heartbeat_hours: float = REENTRY_HEARTBEAT_HOURS,
) -> dict[str, Any]:
    """Emit DecisionPayload@v1 for READY TO REVIEW / NEAR ENTRY rows with advisory.

    Operator-visible re-entry desk publish path. Fail-soft. Flag-gated.
    Membership labels and missing tickers are skipped (not emitted as CASH).

    Change-or-heartbeat: identical (symbol, action) within heartbeat_hours is
    skipped so coverage% is not inflated by wake-tick re-emissions.
    """
    flags = flags if flags is not None else load_feature_flags()
    if not decision_payload_enabled(flags):
        return {"emitted": 0, "attempted": 0, "skipped_unchanged": 0, "errors": [], "enabled": False}
    wid = str(wake_id or "").strip() or f"wake_reentry_{uuid.uuid4().hex[:10]}"
    emitted = 0
    attempted = 0
    skipped = 0
    errors: list[str] = []
    fp = Path(fingerprint_path) if fingerprint_path is not None else _reentry_fingerprint_path(path)
    last = _load_reentry_last(fp)
    now = datetime.now(timezone.utc)
    dirty = False
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        intel = row.get("intel") if isinstance(row.get("intel"), dict) else {}
        state = str(intel.get("state") or row.get("state") or "").strip().upper()
        if state not in _REENTRY_READY_NEAR:
            continue
        advisory = row.get("advisory") if isinstance(row.get("advisory"), dict) else {}
        if not (advisory.get("action") or intel.get("action")):
            continue
        sym = ticker_or_unavailable(row.get("symbol") or row.get("ticker"))
        if sym == "DATA_UNAVAILABLE":
            continue
        action = _REENTRY_STATE_ACTION.get(state) or str(
            advisory.get("action") or intel.get("action") or state
        )
        why = _reentry_should_emit(
            sym, str(action), last, now=now, heartbeat_hours=heartbeat_hours,
        )
        if why == "skip":
            skipped += 1
            continue
        attempted += 1
        try:
            pl = payload_from_reentry_row(row, wake_id=wid)
            pl["extra_emit_reason"] = why
            res = emit_decision_payload(pl, flags=flags, path=path, role="reentry")
            if res.get("emitted"):
                emitted += 1
                last[sym] = {"action": str(action), "ts": now.isoformat(), "reason": why}
                dirty = True
            elif res.get("error"):
                errors.append(str(res["error"]))
        except Exception as exc:  # noqa: BLE001
            errors.append(type(exc).__name__)
    if dirty:
        _save_reentry_last(fp, last)
    return {
        "emitted": emitted,
        "attempted": attempted,
        "skipped_unchanged": skipped,
        "errors": errors[:10],
        "enabled": True,
    }


def payload_from_holdings_health(
    row: dict[str, Any],
    *,
    wake_id: str,
    trace_id: Optional[str] = None,
) -> dict[str, Any]:
    """Map a holdings LLM health refresh → DecisionPayload@v1 (surface=holdings)."""
    r = row if isinstance(row, dict) else {}
    action = r.get("action") or r.get("holdings_llm_action") or "HOLD"
    return build_decision_payload(
        decision_id=f"dec_holdings_{r.get('symbol')}_{action}",
        wake_id=wake_id,
        trace_id=trace_id,
        symbol=r.get("symbol"),
        surface="holdings",
        current_action=action,
        act_now=str(action).upper() in {"TRIM", "EXIT", "ADD"},
        confidence=r.get("confidence"),
        decision_origin=infer_decision_origin(trigger="HOLDINGS_HEALTH"),
        extra={"health": r.get("health"), "model": r.get("model")},
    )


def emit_holdings_health_payload(
    row: dict[str, Any],
    *,
    flags: Optional[dict[str, Any]] = None,
    path: Path | str | None = None,
    wake_id: Optional[str] = None,
) -> dict[str, Any]:
    """Flag-gated holdings DecisionPayload@v1. Fail-soft. Never raises to caller."""
    flags = flags if flags is not None else load_feature_flags()
    out: dict[str, Any] = {"emitted": False, "enabled": decision_payload_enabled(flags), "error": None}
    if not out["enabled"]:
        return out
    try:
        if not isinstance(row, dict) or not row.get("symbol"):
            out["error"] = "invalid_row"
            return out
        wid = str(wake_id or "").strip() or f"wake_holdings_{uuid.uuid4().hex[:10]}"
        pl = payload_from_holdings_health(row, wake_id=wid)
        res = emit_decision_payload(pl, flags=flags, path=path, role="holdings")
        out["emitted"] = bool(res.get("emitted"))
        out["error"] = res.get("error")
        out["trace_id"] = res.get("trace_id")
        out["decision_id"] = res.get("decision_id")
        return out
    except Exception as exc:  # noqa: BLE001
        out["error"] = type(exc).__name__
        return out


def emit_opportunity_promote_payload(
    *,
    symbol: str,
    status: str,
    source: str = "curation",
    flags: Optional[dict[str, Any]] = None,
    path: Path | str | None = None,
    wake_id: Optional[str] = None,
) -> dict[str, Any]:
    """Flag-gated opportunity DecisionPayload@v1 on a two-way book add/stage."""
    flags = flags if flags is not None else load_feature_flags()
    out: dict[str, Any] = {"emitted": False, "enabled": decision_payload_enabled(flags), "error": None}
    if not out["enabled"]:
        return out
    try:
        wid = str(wake_id or "").strip() or f"wake_opp_{uuid.uuid4().hex[:10]}"
        pl = build_decision_payload(
            decision_id=f"dec_opp_{symbol}_{status}",
            wake_id=wid,
            symbol=symbol,
            surface="opportunity",
            current_action=status,
            act_now=str(status).upper() == "PROMOTED",
            decision_origin=infer_decision_origin(trigger="TWO_WAY_CURATION"),
            extra={"source": source},
        )
        res = emit_decision_payload(pl, flags=flags, path=path, role="opportunity")
        out["emitted"] = bool(res.get("emitted"))
        out["error"] = res.get("error")
        return out
    except Exception as exc:  # noqa: BLE001
        out["error"] = type(exc).__name__
        return out


def emit_watch_alert_payload(
    alert: dict[str, Any],
    *,
    flags: Optional[dict[str, Any]] = None,
    path: Path | str | None = None,
    wake_id: Optional[str] = None,
    message: Optional[str] = None,
) -> dict[str, Any]:
    """Emit DecisionPayload@v1 when a watch alert fires to the operator. Fail-soft."""
    flags = flags if flags is not None else load_feature_flags()
    out: dict[str, Any] = {"emitted": False, "enabled": decision_payload_enabled(flags), "error": None}
    if not out["enabled"]:
        return out
    try:
        if not isinstance(alert, dict):
            out["error"] = "invalid_alert"
            return out
        wid = str(wake_id or "").strip() or f"wake_watch_{uuid.uuid4().hex[:10]}"
        pl = payload_from_watch_alert(alert, wake_id=wid, message=message)
        res = emit_decision_payload(pl, flags=flags, path=path, role="watch")
        out["emitted"] = bool(res.get("emitted"))
        out["error"] = res.get("error")
        out["trace_id"] = res.get("trace_id")
        out["decision_id"] = res.get("decision_id")
        return out
    except Exception as exc:  # noqa: BLE001
        out["error"] = type(exc).__name__
        return out


def emit_advisory_opinion_payload(
    row: dict[str, Any],
    opinion: dict[str, Any],
    *,
    flags: Optional[dict[str, Any]] = None,
    path: Path | str | None = None,
    wake_id: Optional[str] = None,
) -> dict[str, Any]:
    """Emit DecisionPayload@v1 when an advisory opinion closes a recommendation.

    Cache hits are skipped (already captured on first generation). Fail-soft.
    """
    flags = flags if flags is not None else load_feature_flags()
    out: dict[str, Any] = {"emitted": False, "enabled": decision_payload_enabled(flags), "error": None}
    if not out["enabled"]:
        return out
    try:
        if not isinstance(opinion, dict):
            out["error"] = "invalid_opinion"
            return out
        if opinion.get("cache_hit"):
            out["error"] = "cache_hit_skip"
            return out
        if not (opinion.get("verdict") or (isinstance(row, dict) and row.get("verdict"))):
            out["error"] = "no_verdict"
            return out
        wid = str(wake_id or "").strip() or f"wake_advisory_{uuid.uuid4().hex[:10]}"
        pl = payload_from_advisory_opinion(row if isinstance(row, dict) else {}, opinion, wake_id=wid)
        res = emit_decision_payload(pl, flags=flags, path=path, role="advisory")
        out["emitted"] = bool(res.get("emitted"))
        out["error"] = res.get("error")
        out["trace_id"] = res.get("trace_id")
        out["decision_id"] = res.get("decision_id")
        return out
    except Exception as exc:  # noqa: BLE001
        out["error"] = type(exc).__name__
        return out


def emit_telegram_decision_payload(
    *,
    symbol: Optional[str] = None,
    action: str = "ADVISORY_REPLY",
    surface: str = "reentry",
    origin: str = "OPERATOR_ASK",
    flags: Optional[dict[str, Any]] = None,
    path: Path | str | None = None,
    wake_id: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Emit DecisionPayload@v1 when a Telegram CIO reply states a decision. Fail-soft."""
    flags = flags if flags is not None else load_feature_flags()
    out: dict[str, Any] = {"emitted": False, "enabled": decision_payload_enabled(flags), "error": None}
    if not out["enabled"]:
        return out
    try:
        wid = str(wake_id or "").strip() or f"wake_tg_{uuid.uuid4().hex[:10]}"
        surf = str(surface or "advisory").lower()
        if surf not in VALID_SURFACES:
            surf = "advisory"
        origin_u = str(origin or "OPERATOR_ASK").upper()
        if origin_u not in VALID_ORIGINS:
            origin_u = "OPERATOR_ASK"
        pl = build_decision_payload(
            decision_id=f"dec_tg_{ticker_or_unavailable(symbol)}_{surf}",
            wake_id=wid,
            symbol=symbol,
            surface=surf,
            current_action=action,
            act_now=False,
            decision_origin=origin_u,
            extra=extra,
        )
        res = emit_decision_payload(pl, flags=flags, path=path, role=surf)
        out["emitted"] = bool(res.get("emitted"))
        out["error"] = res.get("error")
        out["trace_id"] = res.get("trace_id")
        out["decision_id"] = res.get("decision_id")
        return out
    except Exception as exc:  # noqa: BLE001
        out["error"] = type(exc).__name__
        return out


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
            "with_decision_payload_v1_non_synth": 0,
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
    non_synth = with_schema - synthesized
    return {
        "rows": total,
        "with_decision": with_decision,
        "with_decision_payload_v1": with_schema,
        "with_decision_payload_v1_non_synth": non_synth,
        "synthesized": synthesized,
        "coverage": round(cov, 4),
    }
