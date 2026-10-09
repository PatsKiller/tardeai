"""The canonical CADI v2 contract; v1 records are preserved, never rewritten.

Only structural validation lives here. Economics/model authority is deliberately
absent: CADI-01 cannot convert an old heuristic preference into a proven winner.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Iterable, Mapping

SCHEMA = "SymbolDecisionObject@v2"
ERROR_SCHEMA = "CrossAssetDecisionError@v1"
BATCH_SCHEMA = "CrossAssetDecisionBatchReceipt@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
NO_CONSUMER_REASON = (
    "CADI-01 contracts are consumed by DecisionStore, compatibility adapters and batch validation; "
    "operator API integration and organic decision-shadow activation remain later gated tickets."
)
ACTION_CLASSES = (
    "BUY",
    "STRONG_BUY",
    "ADD",
    "ADD_ON_PULLBACK",
    "REENTRY",
    "ENTRY_NEAR",
    "UPGRADE",
    "CONVICTION",
    "HOLD",
    "MONITOR",
    "HEDGE",
    "SELL",
    "TRIM",
    "REDUCE",
    "EXIT",
)
GROUPS = (
    "identity",
    "equity_thesis",
    "research_state",
    "event_state",
    "signal_state",
    "position_state",
    "options_state",
    "cio_state",
    "historical_state",
    "expression_comparison",
    "audit_history",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def normalize_action(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("UNKNOWN_ACTION")
    action = value.strip().upper().replace(" ", "_").replace("-", "_")
    if action not in ACTION_CLASSES:
        raise ValueError("UNKNOWN_ACTION")
    return action


def _timestamp(value: Any) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    except (ValueError, TypeError):
        return False


def build_decision(
    *,
    symbol: str,
    action: str | None,
    source: str,
    as_of: str | None = None,
    available_at: str | None = None,
    source_versions: Mapping[str, Any] | None = None,
    groups: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an unpriced, non-authoritative decision from explicit source facts.

    None action is a NO_SIGNAL assembly record, not an investment signal. Unknown
    action values are refused; the batch boundary turns refusals into receipts.
    """
    if not isinstance(symbol, str):
        raise ValueError("SYMBOL_MUST_BE_STRING")
    sym = symbol.strip().upper()
    if not sym:
        raise ValueError("SYMBOL_REQUIRED")
    ts = as_of or _now()
    supplied = deepcopy(dict(groups or {}))
    if supplied.get("authority", AUTHORITY) != AUTHORITY or supplied.get("financial_action", False) is not False:
        raise ValueError("AUTHORITY_REFUSED")
    obj = {name: (supplied.get(name, []) if name == "audit_history" else supplied.get(name, {})) for name in GROUPS}
    ident = obj["identity"]
    if not isinstance(ident, dict):
        raise ValueError("identity_must_be_object")
    if ident.get("symbol") and str(ident["symbol"]).strip().upper() != sym:
        raise ValueError("IDENTITY_SYMBOL_CONFLICT")
    ident.update(symbol=sym)
    ident.setdefault("subject_guid", None)
    ident.setdefault("security_guid", None)
    ident.setdefault("issuer_guid", None)
    ident.setdefault("identity_status", "CONFIRMED" if ident["security_guid"] else "UNRESOLVED")
    ident.setdefault("as_of", ts)
    position = obj["position_state"]
    if isinstance(position, dict):
        position.setdefault("held_shares", None)
        position.setdefault("accounts", [])
        position.setdefault("coverage_100", None)
        position.setdefault("cash_available", None)
    signal = obj["signal_state"]
    if not isinstance(signal, dict):
        raise ValueError("signal_state_must_be_object")
    signal.update(action=normalize_action(action) if action is not None else None, source=source)
    comparison = obj["expression_comparison"]
    if not isinstance(comparison, dict):
        raise ValueError("expression_comparison_must_be_object")
    comparison.update(winner=None, decision="NO_PROVEN_WINNER", evidence_class="decision-shadow")
    comparison.setdefault("candidates", deepcopy(comparison.get("ranked") or []))
    if not obj["audit_history"]:
        obj["audit_history"] = [{"ts": ts, "actor": source, "action": "assembled"}]
    obj.update(
        schema=SCHEMA,
        authority=AUTHORITY,
        financial_action=False,
        as_of=ts,
        available_at=available_at,
        source_versions=deepcopy(dict(source_versions or {})),
        model_version=None,
        status="EVALUATED" if action is not None else "NO_SIGNAL",
    )
    obj["evaluation_id"] = "eval_" + _digest(obj)
    errors = validate_decision(obj)
    if errors:
        raise ValueError("INVALID_DECISION:" + ",".join(errors))
    return obj


def adapt_decision(record: Mapping[str, Any]) -> dict[str, Any]:
    """Lossless read adapter for both grouped and event-envelope v1 formats."""
    if not isinstance(record, Mapping):
        raise ValueError("RECORD_MUST_BE_OBJECT")
    if record.get("schema") == SCHEMA:
        obj = deepcopy(dict(record))
        errors = validate_decision(obj)
        if errors:
            raise ValueError("INVALID_DECISION:" + ",".join(errors))
        return obj
    if record.get("schema") != "SymbolDecisionObject@v1":
        raise ValueError("UNSUPPORTED_SCHEMA")
    if record.get("authority") != AUTHORITY or record.get("financial_action", False) is not False:
        raise ValueError("AUTHORITY_REFUSED")
    for name in GROUPS:
        if name not in record or not isinstance(record[name], list if name == "audit_history" else dict):
            raise ValueError("INVALID_LEGACY_GROUP:" + name)
    signal = record["signal_state"]
    if "action" in signal and "kind" in signal:
        action_value = None if signal["action"] == "none" else normalize_action(signal["action"])
        kind_value = None if signal["kind"] == "none" else normalize_action(signal["kind"])
        if action_value != kind_value:
            raise ValueError("ACTION_CONFLICT")
    raw_action = signal.get("action", signal.get("kind"))
    action = None if raw_action == "none" else normalize_action(raw_action)
    ts = record.get("as_of") or record["identity"].get("as_of")
    if not _timestamp(ts):
        raise ValueError("LEGACY_AS_OF_REQUIRED")
    obj = build_decision(
        symbol=record["identity"].get("symbol"),
        action=action,
        source=signal.get("source") or signal.get("lane") or "legacy_unknown",
        as_of=ts,
        available_at=record.get("available_at"),
        source_versions=record.get("source_versions"),
        groups=record,
    )
    obj["legacy"] = {
        "format": "event_envelope" if "evaluation_id" in record else "grouped",
        "schema": record["schema"],
        "payload": deepcopy(dict(record)),
    }
    # Aggregated legacy cover is not proof that one account can cover a call.
    obj["position_state"]["coverage_100"] = None
    # Preserve the original key separately; schema upgrade gives this version a
    # distinct deterministic identity instead of colliding with its v1 sibling.
    obj["evaluation_id"] = "eval_" + _digest({k: v for k, v in obj.items() if k != "evaluation_id"})
    return obj


def validate_decision(obj: Any) -> list[str]:
    """Total validator: malformed input yields errors rather than batch failure."""
    if not isinstance(obj, dict):
        return ["record_must_be_object"]
    errors = []
    if obj.get("schema") != SCHEMA:
        errors.append("schema_mismatch")
    if obj.get("authority") != AUTHORITY or obj.get("financial_action") is not False:
        errors.append("authority_refused")
    for name in GROUPS:
        if not isinstance(obj.get(name), list if name == "audit_history" else dict):
            errors.append("invalid_group:" + name)
    identity = obj.get("identity") if isinstance(obj.get("identity"), dict) else {}
    if not isinstance(identity.get("symbol"), str) or not identity["symbol"].strip():
        errors.append("symbol_required")
    if identity.get("identity_status") not in ("CONFIRMED", "UNRESOLVED", "CONFLICTED"):
        errors.append("identity_status_invalid")
    if identity.get("identity_status") == "CONFIRMED" and not identity.get("security_guid"):
        errors.append("confirmed_identity_requires_security_guid")
    for key in ("subject_guid", "security_guid", "issuer_guid"):
        guid = identity.get(key)
        if guid is not None and (not isinstance(guid, str) or not guid.strip()):
            errors.append("invalid_guid:" + key)
    if not _timestamp(obj.get("as_of")):
        errors.append("as_of_timezone_required")
    if obj.get("available_at") is not None and not _timestamp(obj["available_at"]):
        errors.append("available_at_timezone_required")
    if not isinstance(obj.get("source_versions"), dict):
        errors.append("source_versions_required")
    signal = obj.get("signal_state") if isinstance(obj.get("signal_state"), dict) else {}
    if signal.get("action") not in ACTION_CLASSES and not (
        signal.get("action") is None and obj.get("status") == "NO_SIGNAL"
    ):
        errors.append("unknown_action")
    if not isinstance(signal.get("source"), str) or not signal["source"].strip():
        errors.append("source_required")
    comparison = obj.get("expression_comparison") if isinstance(obj.get("expression_comparison"), dict) else {}
    if comparison.get("winner") is not None or comparison.get("decision") != "NO_PROVEN_WINNER":
        errors.append("winner_not_authorized_in_CADI01")
    if not isinstance(obj.get("evaluation_id"), str) or not obj["evaluation_id"].startswith("eval_"):
        errors.append("evaluation_id_required")
    if not obj.get("audit_history"):
        errors.append("audit_history_required")
    try:
        canonical_json(obj)
    except (ValueError, TypeError):
        errors.append("nonfinite_or_nonjson_value")
    return errors


def error_receipt(
    *,
    symbol: Any,
    raw_action: Any,
    source: Any,
    as_of: str,
    error_code: str,
    detail: str = "",
    source_event_id: Any = None,
    source_versions: Any = None,
) -> dict[str, Any]:
    receipt = {
        "schema": ERROR_SCHEMA,
        "authority": AUTHORITY,
        "financial_action": False,
        "symbol": symbol,
        "raw_action": raw_action,
        "source": source,
        "as_of": as_of,
        "error_code": error_code,
        "detail": detail,
        "source_event_id": source_event_id,
        "source_versions": source_versions,
        "evidence_class": "decision-shadow",
    }
    receipt["evaluation_id"] = "error_" + _digest(receipt)
    return receipt


def validate_error_receipt(obj: Any) -> list[str]:
    """Validate stored error envelopes without discarding malformed raw evidence."""
    if not isinstance(obj, dict):
        return ["record_must_be_object"]
    errors = []
    if obj.get("schema") != ERROR_SCHEMA:
        errors.append("schema_mismatch")
    if obj.get("authority") != AUTHORITY or obj.get("financial_action") is not False:
        errors.append("authority_refused")
    if not isinstance(obj.get("error_code"), str) or not obj["error_code"].strip():
        errors.append("error_code_required")
    if not isinstance(obj.get("evaluation_id"), str) or not obj["evaluation_id"].startswith("error_"):
        errors.append("evaluation_id_required")
    if not _timestamp(obj.get("as_of")):
        errors.append("as_of_timezone_required")
    try:
        canonical_json(obj)
    except (ValueError, TypeError):
        errors.append("nonfinite_or_nonjson_value")
    return errors


def _error_value(value: Any) -> Any:
    """Malformed non-JSON input is represented explicitly, never laundered."""
    if isinstance(value, float) and not math.isfinite(value):
        return {"invalid_type": "nonfinite_float", "representation": repr(value)}
    if isinstance(value, dict):
        return {str(key): _error_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_error_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"invalid_type": type(value).__name__, "representation": repr(value)}


def process_decision_batch(
    rows: Iterable[Any], *, store: Any = None, as_of: str | None = None, dry_run: bool = False
) -> dict[str, Any]:
    """Isolate row failures; persist errors alongside decisions, never orders."""
    ts = as_of or _now()
    if not _timestamp(ts):
        raise ValueError("BATCH_AS_OF_REQUIRED")
    results, errors = [], []
    evaluated = duplicates = 0
    for row in rows:
        raw = row if isinstance(row, Mapping) else {}
        signal = raw.get("signal_state") if isinstance(raw.get("signal_state"), dict) else {}
        raw_action = raw.get("action", signal.get("raw_action", signal.get("action", signal.get("kind"))))
        source = raw.get("source") or signal.get("source") or signal.get("lane") or "unknown"
        identity = raw.get("identity") if isinstance(raw.get("identity"), dict) else {}
        symbol = raw.get("symbol") or identity.get("symbol")
        try:
            if not isinstance(row, Mapping):
                raise ValueError("RECORD_MUST_BE_OBJECT")
            if raw.get("authority", AUTHORITY) != AUTHORITY or raw.get("financial_action", False) is not False:
                raise ValueError("AUTHORITY_REFUSED")
            if raw.get("schema"):
                obj = adapt_decision(raw)
            else:
                obj = build_decision(
                    symbol=symbol,
                    action=normalize_action(raw_action),
                    source=source,
                    as_of=raw.get("as_of") or ts,
                    available_at=raw.get("available_at"),
                    source_versions=raw.get("source_versions"),
                    groups=raw.get("groups"),
                )
        except (ValueError, TypeError, KeyError) as exc:
            code = "UNKNOWN_ACTION" if str(exc) == "UNKNOWN_ACTION" else "INVALID_RECORD"
            obj = error_receipt(
                symbol=_error_value(symbol),
                raw_action=_error_value(raw_action),
                source=_error_value(source),
                as_of=ts,
                error_code=code,
                detail=str(exc),
                source_event_id=_error_value(raw.get("event_id", signal.get("event_id", signal.get("signal_id")))),
                source_versions=_error_value(raw.get("source_versions")),
            )
            errors.append(obj)
            result = {"state": "DRY_RUN"} if dry_run or store is None else store.append_error(obj)
        else:
            # Storage failures are not bad-input receipts and must never be
            # misreported as successful, durable processing of the input row.
            result = {"state": "DRY_RUN"} if dry_run or store is None else store.append(obj)
            evaluated += 1
        duplicates += result.get("state") == "DUPLICATE_IGNORED"
        results.append({"symbol": _error_value(symbol), "evaluation_id": obj["evaluation_id"], **result})
    return {
        "schema": BATCH_SCHEMA,
        "authority": AUTHORITY,
        "financial_action": False,
        "evidence_class": "decision-shadow",
        "as_of": ts,
        "ok": not errors,
        "evaluated": evaluated,
        "failed": len(errors),
        "duplicates": duplicates,
        "results": results,
        "errors": errors,
    }
