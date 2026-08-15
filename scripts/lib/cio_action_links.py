"""Short-lived signed CIO action links.

GET verifies and shows confirmation. POST/confirm applies the existing
governed disposition API. Unsigned GETs must not mutate advisory state.

Token binds: decision_id, input/evidence digests, action, issued/expires,
audience, nonce.

Authority: READ_ONLY_ADVISORY. No broker/order/stop.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from scripts.notification_url_builder import get_public_base_url

AUTHORITY = "READ_ONLY_ADVISORY"
ACTIONS = frozenset({"ack", "defer", "done", "reject", "rate", "open", "evidence", "research"})
MUTATING = frozenset({"ack", "defer", "done", "reject", "rate"})
DEFAULT_TTL_SEC = 7 * 24 * 3600
PROJECT_ROOT = Path(__file__).resolve().parents[2]
KEY_PATH = PROJECT_ROOT / "data" / "cio" / "cio_action_link.key"


def _now() -> float:
    return time.time()


def load_hmac_key(explicit: Optional[bytes] = None) -> bytes:
    if explicit:
        return explicit
    env = (os.environ.get("CIO_ACTION_LINK_KEY") or "").strip()
    if env:
        return env.encode("utf-8")
    if KEY_PATH.is_file():
        return KEY_PATH.read_bytes().strip()
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32).encode("utf-8")
    KEY_PATH.write_bytes(key)
    try:
        KEY_PATH.chmod(0o600)
    except OSError:
        pass
    return key


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def mint_action_token(
    *,
    decision_id: str,
    action: str,
    decision_input_digest: str = "",
    decision_evidence_digest: str = "",
    audience: str = "operator",
    ttl_sec: int = DEFAULT_TTL_SEC,
    key: Optional[bytes] = None,
    now: Optional[float] = None,
) -> str:
    action = str(action or "").strip().lower()
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    if not str(decision_id or "").strip():
        raise ValueError("decision_id required")
    issued = int(now if now is not None else _now())
    payload = {
        "decision_id": str(decision_id).strip(),
        "decision_input_digest": str(decision_input_digest or ""),
        "decision_evidence_digest": str(decision_evidence_digest or ""),
        "action": action,
        "issued": issued,
        "expires": issued + int(ttl_sec),
        "audience": str(audience or "operator"),
        "nonce": secrets.token_hex(8),
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(load_hmac_key(key), body, hashlib.sha256).digest()
    return f"{_b64(body)}.{_b64(sig)}"


def verify_action_token(
    token: str,
    *,
    expected_action: Optional[str] = None,
    expected_decision_id: Optional[str] = None,
    key: Optional[bytes] = None,
    now: Optional[float] = None,
) -> dict[str, Any]:
    raw = str(token or "").strip()
    if "." not in raw:
        return {"ok": False, "error": "malformed_token"}
    body_b64, sig_b64 = raw.split(".", 1)
    try:
        body = _unb64(body_b64)
        sig = _unb64(sig_b64)
    except Exception:
        return {"ok": False, "error": "malformed_token"}
    expect = hmac.new(load_hmac_key(key), body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expect):
        return {"ok": False, "error": "bad_signature"}
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return {"ok": False, "error": "malformed_payload"}
    ts = now if now is not None else _now()
    if int(payload.get("expires") or 0) < ts:
        return {"ok": False, "error": "expired", "payload": payload}
    if expected_action and str(payload.get("action")) != str(expected_action).lower():
        return {"ok": False, "error": "action_mismatch", "payload": payload}
    if expected_decision_id and str(payload.get("decision_id")) != str(expected_decision_id):
        return {"ok": False, "error": "decision_id_mismatch", "payload": payload}
    return {"ok": True, "payload": payload, "authority": AUTHORITY}


def reject_lan_url(url: str) -> bool:
    u = (url or "").lower()
    if "127.0.0.1" in u or "localhost" in u or "192.168." in u:
        return True
    if ":7777" in u:
        return True
    return False


def build_cio_hub_url() -> str:
    return f"{get_public_base_url()}/v3/cio"


def build_cio_decision_url(decision_id: str) -> str:
    did = quote(str(decision_id).strip(), safe="")
    return f"{get_public_base_url()}/v3/cio?decision={did}"


def build_cio_research_url(symbol: str = "") -> str:
    if symbol:
        return f"{get_public_base_url()}/v3/cio?tab=research&symbol={quote(str(symbol).upper(), safe='')}"
    return f"{get_public_base_url()}/v3/cio?tab=research"


def build_cio_evidence_url(decision_id: str) -> str:
    did = quote(str(decision_id).strip(), safe="")
    return f"{get_public_base_url()}/v3/cio?tab=evidence&decision={did}"


def build_signed_action_url(
    *,
    decision_id: str,
    action: str,
    decision_input_digest: str = "",
    decision_evidence_digest: str = "",
    key: Optional[bytes] = None,
) -> str:
    token = mint_action_token(
        decision_id=decision_id,
        action=action,
        decision_input_digest=decision_input_digest,
        decision_evidence_digest=decision_evidence_digest,
        key=key,
    )
    did = quote(str(decision_id).strip(), safe="")
    act = quote(str(action).strip().lower(), safe="")
    # Token is path-safe (urlsafe b64). Query `t=` is still needed; Telegram
    # truncates at `&` so this URL must contain exactly one query param.
    return f"{get_public_base_url()}/v3/go/cio/decision/{did}/action/{act}?t={token}"


def apply_signed_disposition(payload: dict[str, Any], *, rating: Optional[int] = None, note: str = "") -> dict[str, Any]:
    """POST-confirm path — calls the existing governed disposition API."""
    from scripts.api_v3_cio import post_decision_disposition

    action = str(payload.get("action") or "").lower()
    if action not in MUTATING:
        return {"ok": False, "error": "not_mutating_action", "authority": AUTHORITY}
    body = {
        "decision_id": payload.get("decision_id"),
        "disposition": action,
        "decision_input_digest": payload.get("decision_input_digest") or "",
        "decision_evidence_digest": payload.get("decision_evidence_digest") or "",
        "rating": rating,
        "note": note,
    }
    result = post_decision_disposition(str(payload.get("decision_id") or ""), body)
    try:
        from scripts.lib.cio_production_case import record_disposition
        record_disposition(str(payload.get("decision_id") or ""), {
            "disposition": action,
            "rating": rating,
            "note": note,
            "decision_input_digest": payload.get("decision_input_digest") or "",
            "decision_evidence_digest": payload.get("decision_evidence_digest") or "",
            "source": "signed_action_link",
        })
    except Exception:
        pass
    return result
