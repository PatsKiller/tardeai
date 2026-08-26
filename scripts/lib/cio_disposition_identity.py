"""Immutable decision disposition identity.

Canonical key is decision_id (+ input/evidence digests). Legacy
position:<symbol>:<account> events remain readable as LEGACY_UNVERSIONED
and must not auto-apply to a new decision.

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
VALID_DISPOSITIONS = frozenset({"ack", "defer", "done", "reject", "rate"})


def is_legacy_key(key: str) -> bool:
    return str(key or "").startswith("position:")


def canonical_key(*, decision_id: str = "", action_id: str = "", kind: str = "position") -> str:
    if str(kind or "") == "action" and action_id:
        return f"action:{action_id}"
    if decision_id:
        return f"decision:{decision_id}"
    return ""


def parse_key(key: str) -> dict[str, Any]:
    k = str(key or "")
    if k.startswith("decision:"):
        return {"kind": "decision", "decision_id": k.split(":", 1)[1], "legacy": False}
    if k.startswith("action:"):
        return {"kind": "action", "action_id": k.split(":", 1)[1], "legacy": False}
    if k.startswith("position:"):
        parts = k.split(":")
        return {
            "kind": "legacy_position",
            "symbol": parts[1] if len(parts) > 1 else "",
            "account": parts[2] if len(parts) > 2 else "",
            "legacy": True,
            "classification": "LEGACY_UNVERSIONED",
        }
    return {"kind": "unknown", "legacy": False, "raw": k}


def lookup_decision(
    decision_id: str,
    store: Any,
    *,
    input_digest: str = "",
    evidence_digest: str = "",
) -> dict[str, Any]:
    """Resolve a decision_id against a current/archived store.

    store may be:
      - list of decision dicts
      - dict keyed by decision_id
      - dict with keys current/archived lists
    """
    current, archived = _flatten_store(store)
    did = str(decision_id or "").strip()
    if not did:
        return {"ok": False, "error": "missing_decision_id"}
    if did in current:
        rec = current[did]
        mode = "current"
    elif did in archived:
        rec = archived[did]
        mode = "archived"
    else:
        return {"ok": False, "error": "unknown_decision_id", "decision_id": did}
    if input_digest:
        got = str(rec.get("decision_input_digest") or "")
        if got and got != str(input_digest):
            return {"ok": False, "error": "decision_input_digest_mismatch",
                    "expected": got, "got": input_digest, "mode": mode}
    if evidence_digest:
        got = str(rec.get("decision_evidence_digest") or "")
        if got and got != str(evidence_digest):
            return {"ok": False, "error": "decision_evidence_digest_mismatch",
                    "expected": got, "got": evidence_digest, "mode": mode}
    return {"ok": True, "decision": rec, "mode": mode}


def _flatten_store(store: Any) -> tuple[dict[str, dict], dict[str, dict]]:
    current: dict[str, dict] = {}
    archived: dict[str, dict] = {}
    if store is None:
        return current, archived
    if isinstance(store, list):
        for d in store:
            if isinstance(d, dict) and d.get("decision_id"):
                current[str(d["decision_id"])] = d
        return current, archived
    if isinstance(store, dict):
        if "current" in store or "archived" in store:
            for d in store.get("current") or []:
                if isinstance(d, dict) and d.get("decision_id"):
                    current[str(d["decision_id"])] = d
            for d in store.get("archived") or []:
                if isinstance(d, dict) and d.get("decision_id"):
                    archived[str(d["decision_id"])] = d
            return current, archived
        # keyed map
        for k, v in store.items():
            if isinstance(v, dict):
                did = str(v.get("decision_id") or k)
                current[did] = v
    return current, archived


def applicable_dispositions(
    latest_by_key: dict[str, dict[str, Any]],
    *,
    decision_id: str,
    action_id: str = "",
    kind: str = "position",
) -> Optional[dict[str, Any]]:
    """Return the disposition for this immutable decision only.

    Legacy position:<symbol>:<account> rows are never auto-applied.
    """
    key = canonical_key(decision_id=decision_id, action_id=action_id, kind=kind)
    if not key:
        return None
    rec = latest_by_key.get(key)
    if rec:
        return rec
    # Also accept raw decision_id as key (new contract)
    if decision_id and decision_id in latest_by_key:
        return latest_by_key[decision_id]
    return None


def build_disposition_event(
    *,
    decision_id: str,
    disposition: str,
    decision_input_digest: str = "",
    decision_evidence_digest: str = "",
    symbol: str = "",
    account: str = "",
    action: str = "",
    rating: Any = None,
    note: str = "",
    operator_actor_id: str = "",
    mode: str = "current",
) -> dict[str, Any]:
    return {
        "decision_id": decision_id,
        "decision_key": canonical_key(decision_id=decision_id),
        "decision_input_digest": decision_input_digest or None,
        "decision_evidence_digest": decision_evidence_digest or None,
        "symbol": symbol or None,
        "account": account or None,
        "action": action or None,
        "disposition": disposition,
        "rating": rating,
        "note": note or None,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "operator_actor_id": operator_actor_id or None,
        "mode": mode,
        "identity_class": "IMMUTABLE_DECISION",
        "authority": AUTHORITY,
    }


def validate_post(
    *,
    decision_key: str,
    body: dict[str, Any],
    store: Any,
) -> dict[str, Any]:
    body = body or {}
    disp = str(body.get("disposition") or "").strip().lower()
    if disp not in VALID_DISPOSITIONS:
        return {"ok": False, "error": "invalid_disposition", "allowed": sorted(VALID_DISPOSITIONS)}
    parsed = parse_key(decision_key)
    if parsed.get("legacy"):
        return {
            "ok": False,
            "error": "legacy_key_not_writable",
            "classification": "LEGACY_UNVERSIONED",
            "detail": "New dispositions must use decision_id, not position:symbol:account",
        }
    did = str(body.get("decision_id") or parsed.get("decision_id") or "").strip()
    if parsed.get("kind") == "action":
        return {
            "ok": True,
            "mode": "action",
            "event": build_disposition_event(
                decision_id=f"action:{parsed.get('action_id')}",
                disposition=disp,
                rating=body.get("rating"),
                note=str(body.get("note") or "")[:500],
                operator_actor_id=str(body.get("operator_actor_id") or ""),
                mode="action",
            ),
        }
    if not did:
        return {"ok": False, "error": "missing_decision_id"}
    found = lookup_decision(
        did, store,
        input_digest=str(body.get("decision_input_digest") or ""),
        evidence_digest=str(body.get("decision_evidence_digest") or ""),
    )
    if not found.get("ok"):
        return found
    rating = body.get("rating")
    if rating is not None:
        try:
            rating = int(rating)
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid_rating"}
        if not (1 <= rating <= 5):
            return {"ok": False, "error": "invalid_rating"}
    rec = found["decision"]
    event = build_disposition_event(
        decision_id=did,
        disposition=disp,
        decision_input_digest=str(body.get("decision_input_digest") or rec.get("decision_input_digest") or ""),
        decision_evidence_digest=str(body.get("decision_evidence_digest") or rec.get("decision_evidence_digest") or ""),
        symbol=str(body.get("symbol") or rec.get("symbol") or ""),
        account=str(body.get("account") or rec.get("account") or ""),
        action=str(body.get("action") or rec.get("action") or rec.get("stance") or ""),
        rating=rating,
        note=str(body.get("note") or "")[:500],
        operator_actor_id=str(body.get("operator_actor_id") or ""),
        mode=str(found.get("mode") or "current"),
    )
    return {"ok": True, "mode": found.get("mode"), "event": event, "decision": rec}
