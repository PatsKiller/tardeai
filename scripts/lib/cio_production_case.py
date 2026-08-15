"""Production CIO case store — event-sourced, one canonical case.

Append-only JSONL at data/cio/cio_production_cases.jsonl.

Decision, disposition, note, challenge, outcome, and Darwin score are
events on the same case_id. Never mint disp_<id> or note_<id> as case_id.

Does not mutate production config. No broker calls.

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _stable_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


AUTHORITY = "READ_ONLY_ADVISORY"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = PROJECT_ROOT / "data" / "cio" / "cio_production_cases.jsonl"

DECISION_OPENED = "DECISION_OPENED"
RETRIEVAL_RECORDED = "RETRIEVAL_RECORDED"
OPERATOR_DISPOSITION = "OPERATOR_DISPOSITION"
OPERATOR_NOTE = "OPERATOR_NOTE"
THESIS_CHALLENGE = "THESIS_CHALLENGE"
REVIEW_RESULT = "REVIEW_RESULT"
OUTCOME_OBSERVED = "OUTCOME_OBSERVED"
CASE_MATURED = "CASE_MATURED"
DARWIN_SCORED = "DARWIN_SCORED"
REFLECTION_CREATED = "REFLECTION_CREATED"

EVENT_TYPES = (
    DECISION_OPENED,
    RETRIEVAL_RECORDED,
    OPERATOR_DISPOSITION,
    OPERATOR_NOTE,
    THESIS_CHALLENGE,
    REVIEW_RESULT,
    OUTCOME_OBSERVED,
    CASE_MATURED,
    DARWIN_SCORED,
    REFLECTION_CREATED,
)

MATURED_OUTCOMES = frozenset({"POSITIVE", "NEGATIVE", "FLAT", "EXPIRED"})
CASE_STATUSES = ("OPEN", "AWAITING_OUTCOME", "MATURED", "SCORED", "CLOSED")

SCORER = "cio_production_case_darwin_v1"
FORMULA = "base50+disp+outcome+audit; auto_promote=0"

_ENVELOPE_KEYS = frozenset({
    "case_id",
    "decision_id",
    "decision_input_digest",
    "decision_evidence_digest",
    "event_type",
    "occurred_at",
    "recorded_at",
    "source",
    "authority",
    "payload",
    "auto_promoted",
    "creates_trade_authority",
    "status",
})

_STATUS_TO_EVENT = {
    "OPEN": DECISION_OPENED,
    "DISPOSITION": OPERATOR_DISPOSITION,
    "OPERATOR_DISPOSITION": OPERATOR_DISPOSITION,
    "OPERATOR_NOTE": OPERATOR_NOTE,
    "RETRIEVAL_RECORDED": RETRIEVAL_RECORDED,
    "THESIS_CHALLENGE": THESIS_CHALLENGE,
    "REVIEW_RESULT": REVIEW_RESULT,
    "OUTCOME": OUTCOME_OBSERVED,
    "OUTCOME_OBSERVED": OUTCOME_OBSERVED,
    "CASE_MATURED": CASE_MATURED,
    "DARWIN_SCORED": DARWIN_SCORED,
    "REFLECTION_CREATED": REFLECTION_CREATED,
    "CLOSED": REFLECTION_CREATED,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_path(path: Optional[Path] = None) -> Path:
    return path or DEFAULT_PATH


def case_id_for(decision_id: str, input_digest: str, evidence_digest: str) -> str:
    return "case_" + _stable_hash({
        "decision_id": decision_id,
        "in": input_digest,
        "ev": evidence_digest,
    })[:20]


def _digests_from(
    obj: Optional[dict[str, Any]],
    input_digest: str = "",
    evidence_digest: str = "",
) -> tuple[str, str]:
    obj = obj if isinstance(obj, dict) else {}
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    disp = obj.get("operator_disposition") if isinstance(obj.get("operator_disposition"), dict) else {}
    inp = (
        input_digest
        or str(obj.get("decision_input_digest") or obj.get("input_digest") or "")
        or str(payload.get("decision_input_digest") or payload.get("input_digest") or "")
        or str(disp.get("decision_input_digest") or disp.get("input_digest") or "")
    )
    evd = (
        evidence_digest
        or str(obj.get("decision_evidence_digest") or obj.get("evidence_digest") or "")
        or str(payload.get("decision_evidence_digest") or payload.get("evidence_digest") or "")
        or str(disp.get("decision_evidence_digest") or disp.get("evidence_digest") or "")
    )
    return inp, evd


def _legacy_case_id(case_id: str) -> bool:
    return case_id.startswith("disp_") or case_id.startswith("note_")


def _canonical_case_id(
    decision_id: str,
    input_digest: str,
    evidence_digest: str,
    case_id: str = "",
) -> str:
    if case_id and not _legacy_case_id(case_id):
        return case_id
    return case_id_for(decision_id, input_digest, evidence_digest)


def _event_type_of(row: dict[str, Any]) -> str:
    et = str(row.get("event_type") or "").strip()
    if et:
        return et
    status = str(row.get("status") or "").strip().upper()
    if status in _STATUS_TO_EVENT:
        return _STATUS_TO_EVENT[status]
    if status in EVENT_TYPES:
        return status
    return DECISION_OPENED


def _payload_of(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    if isinstance(payload, dict):
        return dict(payload)
    keys = (
        "symbol",
        "action",
        "stance",
        "decision_time_facts",
        "research",
        "operator_disposition",
        "outcome",
        "darwin",
        "note",
        "notes",
        "challenge",
        "review",
        "why_now",
        "text",
        "outcome_status",
        "evaluation_horizon",
        "maturity_at",
        "disposition",
        "rating",
    )
    out = {k: row[k] for k in keys if k in row}
    return out


def _outcome_status(outcome: Any) -> str:
    if isinstance(outcome, dict):
        return str(outcome.get("outcome_status") or "").strip().upper()
    return str(outcome or "").strip().upper()


def _is_matured_outcome(outcome: Any) -> bool:
    return _outcome_status(outcome) in MATURED_OUTCOMES


def _horizon_or_maturity(case: dict[str, Any], outcome: Optional[dict[str, Any]] = None) -> bool:
    oc = outcome if isinstance(outcome, dict) else (case.get("outcome") if isinstance(case.get("outcome"), dict) else {})
    return bool(
        oc.get("evaluation_horizon")
        or oc.get("maturity_at")
        or case.get("evaluation_horizon")
        or case.get("maturity_at")
    )


def _darwin_eligible(case: dict[str, Any]) -> bool:
    """P0-5: never score OPEN / unmatured / pending / missing outcome."""
    if str(case.get("status") or "").strip().upper() == "OPEN":
        return False
    outcome = case.get("outcome")
    if not isinstance(outcome, dict) or not outcome:
        return False
    status = _outcome_status(outcome)
    if not status or status == "PENDING_MATURATION" or status not in MATURED_OUTCOMES:
        return False
    # evaluation_horizon OR maturity_at OR outcome_status in matured set
    if not (_horizon_or_maturity(case, outcome) or status in MATURED_OUTCOMES):
        return False
    return True


def append_case_event(decision_id: str, payload: Optional[dict[str, Any]] = None, **kwargs: Any) -> dict[str, Any]:
    """Compat for converse persist_operator_challenge(did, payload)."""
    body = dict(payload or {})
    body.update(kwargs)
    disp = body.get("operator_disposition") if isinstance(body.get("operator_disposition"), dict) else {}
    note = str((disp or {}).get("note") or body.get("note") or "")
    disposition = str((disp or {}).get("disposition") or body.get("disposition") or "")
    inp, evd = _digests_from(body)
    recs = []
    if disposition:
        recs.append(record_disposition(decision_id, {
            "disposition": disposition,
            "note": note,
            "source": (disp or {}).get("source") or "append_case_event",
        }, input_digest=inp, evidence_digest=evd))
    if note:
        recs.append(record_note(decision_id, note, input_digest=inp, evidence_digest=evd,
                                source="append_case_event"))
    if str(body.get("operator_challenge_status") or "").upper() == "OPEN" or str(disposition).upper() == "REJECT":
        recs.append(record_challenge(
            decision_id,
            note=note,
            review=str(body.get("challenge_review") or "DATA_UNAVAILABLE"),
            input_digest=inp,
            evidence_digest=evd,
        ))
    return recs[-1] if recs else append_event(
        case_id_for(decision_id, inp, evd), DECISION_OPENED, body, decision_id, inp, evd,
        source="append_case_event",
    )


def append_event(
    case_id: str,
    event_type: str,
    payload: dict[str, Any],
    decision_id: str,
    input_digest: str = "",
    evidence_digest: str = "",
    source: str = "",
    path: Optional[Path] = None,
) -> dict[str, Any]:
    p = _resolve_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = dict(payload) if isinstance(payload, dict) else {"value": payload}
    occurred = _now()
    rec: dict[str, Any] = {
        "case_id": case_id,
        "decision_id": decision_id,
        "decision_input_digest": input_digest,
        "decision_evidence_digest": evidence_digest,
        "event_type": event_type,
        "occurred_at": occurred,
        "source": source or "cio_production_case",
        "authority": AUTHORITY,
        "payload": body,
        "auto_promoted": False,
        "creates_trade_authority": False,
    }
    symbol = body.get("symbol")
    if symbol:
        rec["symbol"] = symbol
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
    return rec


def append_case(case: dict[str, Any], path: Optional[Path] = None) -> dict[str, Any]:
    """Thin wrapper → append_event. Rewrites disp_* / note_* to case_id_for."""
    rec = dict(case or {})
    decision_id = str(rec.get("decision_id") or "")
    inp, evd = _digests_from(rec)
    raw_id = str(rec.get("case_id") or "")
    status = str(rec.get("status") or rec.get("event_type") or "")
    # Explicit P0-4 rewrite: DISPOSITION + disp_* uses digests from payload.
    if status.upper() == "DISPOSITION" and raw_id.startswith("disp_"):
        raw_id = case_id_for(decision_id, inp, evd)
        status = OPERATOR_DISPOSITION
    case_id = _canonical_case_id(decision_id, inp, evd, raw_id)
    event_type = str(rec.get("event_type") or "").strip() or _STATUS_TO_EVENT.get(status.upper(), status or DECISION_OPENED)
    if isinstance(rec.get("payload"), dict):
        payload = dict(rec["payload"])
    else:
        payload = {k: v for k, v in rec.items() if k not in _ENVELOPE_KEYS}
        if not payload:
            if rec.get("operator_disposition") is not None:
                payload = dict(rec["operator_disposition"]) if isinstance(rec["operator_disposition"], dict) else {
                    "operator_disposition": rec["operator_disposition"],
                }
            elif rec.get("outcome") is not None:
                payload = dict(rec["outcome"]) if isinstance(rec["outcome"], dict) else {"outcome": rec["outcome"]}
            elif rec.get("note") is not None:
                payload = {"note": rec["note"]}
    source = str(rec.get("source") or payload.get("source") or "cio_production_case")
    return append_event(
        case_id,
        event_type,
        payload,
        decision_id,
        inp,
        evd,
        source=source,
        path=path,
    )


def open_case_from_decision(
    decision: dict[str, Any],
    *,
    research: Optional[dict] = None,
    path: Optional[Path] = None,
    source: str = "cio_production_case",
) -> dict[str, Any]:
    did = str(decision.get("decision_id") or "").strip()
    inp = str(decision.get("decision_input_digest") or "")
    evd = str(decision.get("decision_evidence_digest") or "")
    cid = case_id_for(did, inp, evd)
    payload = {
        "symbol": decision.get("symbol"),
        "action": decision.get("action") or decision.get("stance"),
        "decision_time_facts": {
            "weight_pct": decision.get("current_weight_pct") or decision.get("weight_pct"),
            "delta_usd": decision.get("recommended_delta_usd") or decision.get("delta_usd"),
            "why_now": decision.get("why_now"),
        },
        "why_now": decision.get("why_now"),
    }
    opened = append_event(
        cid, DECISION_OPENED, payload, did, inp, evd, source=source, path=path,
    )
    opened["status"] = "OPEN"
    opened["research"] = {}
    if research:
        retrieval = append_event(
            cid, RETRIEVAL_RECORDED, dict(research), did, inp, evd,
            source=source, path=path,
        )
        opened["research"] = dict(research)
        opened["retrieval_recorded"] = True
        opened["retrieval_event_type"] = retrieval.get("event_type")
    return opened


def record_disposition(
    decision_id: str,
    disposition: dict[str, Any],
    input_digest: str = "",
    evidence_digest: str = "",
    path: Optional[Path] = None,
) -> dict[str, Any]:
    body = dict(disposition) if isinstance(disposition, dict) else {"disposition": disposition}
    inp, evd = _digests_from(body, input_digest, evidence_digest)
    cid = case_id_for(str(decision_id), inp, evd)
    source = str(body.get("source") or "operator")
    return append_event(
        cid, OPERATOR_DISPOSITION, body, str(decision_id), inp, evd,
        source=source, path=path,
    )


def record_note(
    decision_id: str,
    note: Any,
    input_digest: str = "",
    evidence_digest: str = "",
    path: Optional[Path] = None,
    **meta: Any,
) -> dict[str, Any]:
    if isinstance(note, dict):
        body = dict(note)
        body.update(meta)
        inp, evd = _digests_from(body, input_digest, evidence_digest)
    else:
        body = {"note": note, **meta}
        inp, evd = input_digest, evidence_digest
    cid = case_id_for(str(decision_id), inp, evd)
    source = str(body.get("source") or "operator")
    return append_event(
        cid, OPERATOR_NOTE, body, str(decision_id), inp, evd,
        source=source, path=path,
    )


def record_outcome(
    decision_id: str,
    outcome: Optional[dict[str, Any]] = None,
    input_digest: str = "",
    evidence_digest: str = "",
    path: Optional[Path] = None,
    **fields: Any,
) -> dict[str, Any]:
    body = dict(outcome or {})
    body.update(fields)
    inp, evd = _digests_from(body, input_digest, evidence_digest)
    cid = case_id_for(str(decision_id), inp, evd)
    source = str(body.get("source") or "cio_production_case")
    observed = append_event(
        cid, OUTCOME_OBSERVED, body, str(decision_id), inp, evd,
        source=source, path=path,
    )
    if _is_matured_outcome(body):
        append_event(
            cid,
            CASE_MATURED,
            {
                "outcome_status": _outcome_status(body),
                "evaluation_horizon": body.get("evaluation_horizon"),
                "maturity_at": body.get("maturity_at"),
            },
            str(decision_id),
            inp,
            evd,
            source=source,
            path=path,
        )
    return observed


def record_challenge(
    decision_id: str,
    challenge: Optional[dict[str, Any]] = None,
    input_digest: str = "",
    evidence_digest: str = "",
    path: Optional[Path] = None,
    **fields: Any,
) -> dict[str, Any]:
    body = dict(challenge or {})
    body.update(fields)
    inp, evd = _digests_from(body, input_digest, evidence_digest)
    cid = case_id_for(str(decision_id), inp, evd)
    source = str(body.get("source") or "operator")
    return append_event(
        cid, THESIS_CHALLENGE, body, str(decision_id), inp, evd,
        source=source, path=path,
    )


def score_case_darwin(case: dict[str, Any]) -> dict[str, Any]:
    """Deterministic job score — only after maturity. Not generic win rate."""
    if not _darwin_eligible(case):
        rec: dict[str, Any] = {
            "eligible": False,
            "darwin_status": "NOT_MATURED",
            "score": None,
            "scorer": SCORER,
            "formula": FORMULA,
            "authority": AUTHORITY,
        }
        # COP-21 / existing formula: auto_promoted cases are zeroed, never rewarded.
        if case.get("auto_promoted"):
            rec["score"] = 0
        return rec

    disp = str((case.get("operator_disposition") or {}).get("disposition") or "").lower()
    outcome = str((case.get("outcome") or {}).get("outcome_status") or "").upper()
    points = 50
    if disp in {"ack", "done"}:
        points += 10
    if disp == "reject":
        points -= 5
    if outcome == "POSITIVE":
        points += 20
    elif outcome == "NEGATIVE":
        points -= 20
    if case.get("research", {}).get("decision_use_audit", {}).get("signature_ok"):
        points += 10
    if case.get("auto_promoted"):
        points = 0
    score = max(0, min(100, points))
    return {
        "eligible": True,
        "darwin_status": "SCORED",
        "score": score,
        "scorer": SCORER,
        "formula": FORMULA,
        "authority": AUTHORITY,
    }


def maybe_score_if_mature(case: dict[str, Any], path: Optional[Path] = None) -> dict[str, Any]:
    """Append DARWIN_SCORED only when the case is Darwin-eligible."""
    existing = case.get("darwin") if isinstance(case.get("darwin"), dict) else {}
    if (
        str(case.get("status") or "").upper() == "SCORED"
        or str(existing.get("darwin_status") or "").upper() == "SCORED"
    ):
        return existing or score_case_darwin(case)
    result = score_case_darwin(case)
    if not result.get("eligible"):
        return result
    cid = str(case.get("case_id") or "")
    did = str(case.get("decision_id") or "")
    inp = str(case.get("decision_input_digest") or "")
    evd = str(case.get("decision_evidence_digest") or "")
    if cid:
        append_event(
            cid, DARWIN_SCORED, result, did, inp, evd,
            source="darwin", path=path,
        )
    return result


def load_cases(path: Optional[Path] = None) -> list[dict[str, Any]]:
    p = _resolve_path(path)
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def load_events(path: Optional[Path] = None) -> list[dict[str, Any]]:
    return load_cases(path)


def _row_case_id(row: dict[str, Any]) -> str:
    did = str(row.get("decision_id") or "")
    inp, evd = _digests_from(row)
    raw = str(row.get("case_id") or "")
    return _canonical_case_id(did, inp, evd, raw)


def _note_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        return str(payload.get("note") or payload.get("text") or "")
    return ""


def _fold_events(case_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "case_id": case_id,
        "decision_id": "",
        "decision_input_digest": "",
        "decision_evidence_digest": "",
        "status": "OPEN",
        "symbol": None,
        "action": None,
        "decision_time_facts": {},
        "research": {},
        "operator_disposition": None,
        "notes": [],
        "note": "",
        "challenge": None,
        "review": None,
        "outcome": None,
        "darwin": None,
        "auto_promoted": False,
        "authority": AUTHORITY,
        "creates_trade_authority": False,
    }
    saw_disposition = False
    saw_note = False
    saw_outcome = False
    saw_matured = False
    saw_scored = False
    saw_closed = False
    scored_payload: Optional[dict[str, Any]] = None

    for ev in events:
        et = _event_type_of(ev)
        payload = _payload_of(ev)
        out["decision_id"] = str(ev.get("decision_id") or out["decision_id"])
        if ev.get("decision_input_digest"):
            out["decision_input_digest"] = str(ev.get("decision_input_digest") or "")
        if ev.get("decision_evidence_digest"):
            out["decision_evidence_digest"] = str(ev.get("decision_evidence_digest") or "")
        if ev.get("auto_promoted"):
            out["auto_promoted"] = True

        if et == DECISION_OPENED:
            out["symbol"] = payload.get("symbol") or ev.get("symbol") or out["symbol"]
            out["action"] = payload.get("action") or payload.get("stance") or out["action"]
            facts = payload.get("decision_time_facts")
            if isinstance(facts, dict):
                out["decision_time_facts"] = facts
            if payload.get("research") and not out["research"]:
                out["research"] = payload.get("research") or {}
        elif et == RETRIEVAL_RECORDED:
            out["research"] = payload
        elif et == OPERATOR_DISPOSITION:
            disp = payload.get("operator_disposition") if isinstance(payload.get("operator_disposition"), dict) else payload
            out["operator_disposition"] = disp
            saw_disposition = True
            extra_note = _note_text(disp)
            if extra_note and not out["note"]:
                out["note"] = extra_note
        elif et == OPERATOR_NOTE:
            out["notes"].append(payload)
            text = _note_text(payload)
            if text:
                out["note"] = text
            saw_note = True
        elif et == THESIS_CHALLENGE:
            out["challenge"] = payload
        elif et == REVIEW_RESULT:
            out["review"] = payload
        elif et == OUTCOME_OBSERVED:
            oc = payload.get("outcome") if isinstance(payload.get("outcome"), dict) else payload
            out["outcome"] = oc
            saw_outcome = True
            if _is_matured_outcome(oc):
                saw_matured = True
        elif et == CASE_MATURED:
            saw_matured = True
            if out["outcome"] is None and payload:
                out["outcome"] = {
                    "outcome_status": payload.get("outcome_status"),
                    "evaluation_horizon": payload.get("evaluation_horizon"),
                    "maturity_at": payload.get("maturity_at"),
                }
                saw_outcome = True
        elif et == DARWIN_SCORED:
            saw_scored = True
            scored_payload = payload
        elif et == REFLECTION_CREATED:
            pass
        if str(payload.get("closed") or ev.get("closed") or "").upper() in {"1", "TRUE", "YES", "CLOSED"}:
            saw_closed = True
        if str(ev.get("status") or "").upper() == "CLOSED":
            saw_closed = True

    if saw_scored:
        out["status"] = "SCORED"
    elif saw_closed:
        out["status"] = "CLOSED"
    elif saw_matured or _is_matured_outcome(out.get("outcome")):
        out["status"] = "MATURED"
    elif saw_disposition or saw_note or saw_outcome:
        out["status"] = "AWAITING_OUTCOME"
    else:
        out["status"] = "OPEN"

    # Darwin only after CASE_MATURED / DARWIN_SCORED.
    # Persist SCORED only via DARWIN_SCORED; CASE_MATURED is eligible but not yet scored.
    if saw_scored and scored_payload is not None:
        d = dict(scored_payload)
        d.setdefault("eligible", True)
        d.setdefault("darwin_status", "SCORED")
        out["darwin"] = d
    elif saw_matured:
        computed = score_case_darwin(out)
        if computed.get("eligible"):
            computed = dict(computed)
            computed["darwin_status"] = "MATURED"
        out["darwin"] = computed

    return out


def materialize_cases(path: Optional[Path] = None) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for row in load_events(path):
        cid = _row_case_id(row)
        if cid not in grouped:
            grouped[cid] = []
            order.append(cid)
        grouped[cid].append(row)
    return [_fold_events(cid, grouped[cid]) for cid in order]


def materialize_case(case_id: str, path: Optional[Path] = None) -> dict[str, Any]:
    for joined in materialize_cases(path=path):
        if joined.get("case_id") == case_id:
            return joined
    return {
        "case_id": case_id,
        "status": "OPEN",
        "operator_disposition": None,
        "notes": [],
        "note": "",
        "outcome": None,
        "darwin": None,
        "research": {},
        "auto_promoted": False,
        "authority": AUTHORITY,
        "creates_trade_authority": False,
    }
