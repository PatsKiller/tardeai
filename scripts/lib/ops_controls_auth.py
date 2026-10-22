"""Ops -> Controls factors: WebAuthn passkeys (py_webauthn), TOTP recovery (pyotp), step-up tokens, approval HMAC.

AGENTS.md 19.0.0 §27.3 (PROPOSED). Risky acts need a passkey assertion with user verification REQUIRED, bound to one
request by a single-use challenge, plus the typed phrase (checked server-side, ops_controls_core.phrase_matches). TOTP
is recovery only: it may stand in for a passkey solely to register a passkey when none is active. Telegram confirms
nothing.

Libraries: ``webauthn`` (py_webauthn, Duo Labs) and ``pyotp`` are imported lazily. When either is missing the matching
route answers DEPENDENCY_MISSING (fail closed); install them from requirements.txt at activation.

Secrets: the approval HMAC key and the TOTP secret are 0600 files outside the repository (config/ops_controls.json
names the paths). A key file readable by group/other is refused. Agents never read them (§24.7).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

MIN_KEY_BYTES = 32


class AuthError(Exception):
    def __init__(self, code: str, detail: str = "", status: int = 403) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.status = status


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    s = str(text or "")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def new_step_up_token() -> str:
    return secrets.token_urlsafe(32)


# ── 0600 secret files ──────────────────────────────────────────────────────────────────────────────────────────────


def read_private_file(path: Path) -> Optional[bytes]:
    """The bytes of a 0600 file owned by this uid, else None (missing, wrong mode or owner = absent; fail closed)."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or (st.st_mode & 0o077):
        return None
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def load_hmac_key(path: Path) -> Optional[bytes]:
    raw = read_private_file(path)
    if raw is None:
        return None
    key = raw.strip()
    return key if len(key) >= MIN_KEY_BYTES else None


def approval_message(req: dict) -> bytes:
    body = {k: req.get(k) for k in ("request_id", "kind", "direction", "executor", "params", "expected_state_digest",
                                    "actor", "stepup_factor", "stepup_credential_id")}
    approved = req.get("approved_at")
    body["approved_at"] = approved.isoformat() if hasattr(approved, "isoformat") else approved
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sign_approval(key: bytes, req: dict) -> str:
    return hmac.new(key, approval_message(req), hashlib.sha256).hexdigest()


def verify_approval(key: Optional[bytes], req: dict) -> bool:
    sig = req.get("approval_sig")
    if not key or not isinstance(sig, str):
        return False
    return hmac.compare_digest(sign_approval(key, req), sig)


# ── WebAuthn ────────────────────────────────────────────────────────────────────────────────────────────────────────


def webauthn_available() -> bool:
    try:
        import webauthn  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


@dataclass
class VerifiedAssertion:
    credential_id: str
    new_sign_count: int
    user_verified: bool


@dataclass
class VerifiedRegistration:
    credential_id: str
    public_key: str        # base64url COSE key
    sign_count: int
    aaguid: Optional[str]
    transports: list


class PasskeyVerifier:
    """py_webauthn wrapper. Options are returned as JSON-ready dicts (base64url binary fields)."""

    def __init__(self, *, rp_id: str, rp_name: str, origins: list[str]) -> None:
        self.rp_id, self.rp_name, self.origins = rp_id, rp_name, list(origins)

    @staticmethod
    def _lib():
        try:
            import webauthn
            from webauthn.helpers import options_to_json, structs
        except Exception as exc:  # noqa: BLE001
            raise AuthError("DEPENDENCY_MISSING", "py_webauthn (pip package 'webauthn') is not installed", 503) from exc
        return webauthn, structs, options_to_json

    def registration_options(self, *, challenge: bytes, user_handle: bytes, user_name: str,
                             exclude_ids: list[str]) -> dict:
        wa, S, to_json = self._lib()
        opts = wa.generate_registration_options(
            rp_id=self.rp_id, rp_name=self.rp_name, user_name=user_name, user_id=user_handle,
            user_display_name=user_name, challenge=challenge, timeout=120000,
            attestation=S.AttestationConveyancePreference.NONE,
            authenticator_selection=S.AuthenticatorSelectionCriteria(
                resident_key=S.ResidentKeyRequirement.PREFERRED,
                user_verification=S.UserVerificationRequirement.REQUIRED),
            exclude_credentials=[S.PublicKeyCredentialDescriptor(id=b64url_decode(i)) for i in exclude_ids])
        return json.loads(to_json(opts))

    def verify_registration(self, *, credential: Any, challenge: bytes) -> VerifiedRegistration:
        wa, _S, _j = self._lib()
        try:
            v = wa.verify_registration_response(credential=credential, expected_challenge=challenge,
                                                expected_rp_id=self.rp_id, expected_origin=self.origins,
                                                require_user_verification=True)
        except Exception as exc:  # noqa: BLE001 — any library refusal is a refusal
            raise AuthError("ATTESTATION_INVALID", f"{type(exc).__name__}: {str(exc)[:160]}", 403) from exc
        transports = []
        if isinstance(credential, dict):
            transports = list((credential.get("response") or {}).get("transports") or [])
        return VerifiedRegistration(b64url(v.credential_id), b64url(v.credential_public_key), int(v.sign_count),
                                    str(v.aaguid) if getattr(v, "aaguid", None) else None, transports)

    def authentication_options(self, *, challenge: bytes, allow_ids: list[str]) -> dict:
        wa, S, to_json = self._lib()
        opts = wa.generate_authentication_options(
            rp_id=self.rp_id, challenge=challenge, timeout=120000,
            allow_credentials=[S.PublicKeyCredentialDescriptor(id=b64url_decode(i)) for i in allow_ids],
            user_verification=S.UserVerificationRequirement.REQUIRED)
        return json.loads(to_json(opts))

    def verify_assertion(self, *, credential: Any, challenge: bytes, public_key: str,
                         sign_count: int) -> VerifiedAssertion:
        wa, _S, _j = self._lib()
        try:
            v = wa.verify_authentication_response(credential=credential, expected_challenge=challenge,
                                                  expected_rp_id=self.rp_id, expected_origin=self.origins,
                                                  credential_public_key=b64url_decode(public_key),
                                                  credential_current_sign_count=int(sign_count),
                                                  require_user_verification=True)
        except Exception as exc:  # noqa: BLE001
            raise AuthError("ASSERTION_INVALID", f"{type(exc).__name__}: {str(exc)[:160]}", 403) from exc
        return VerifiedAssertion(b64url(v.credential_id), int(v.new_sign_count),
                                 bool(getattr(v, "user_verified", True)))


def credential_id_of(credential: Any) -> str:
    if not isinstance(credential, dict):
        raise AuthError("CREDENTIAL_INVALID", "credential must be the PublicKeyCredential JSON", 400)
    cid = credential.get("rawId") or credential.get("id")
    if not isinstance(cid, str) or not cid or len(cid) > 1400:
        raise AuthError("CREDENTIAL_INVALID", "credential id missing", 400)
    return cid.rstrip("=")


def client_challenge_of(credential: Any) -> str:
    """The challenge the browser signed (clientDataJSON.challenge, base64url). Used only to look up the issued
    challenge; the library then verifies the signature over it."""
    try:
        cdj = json.loads(b64url_decode(credential["response"]["clientDataJSON"]))
        ch = cdj["challenge"]
    except Exception as exc:  # noqa: BLE001
        raise AuthError("CREDENTIAL_INVALID", "clientDataJSON unreadable", 400) from exc
    if not isinstance(ch, str) or not ch:
        raise AuthError("CREDENTIAL_INVALID", "challenge missing", 400)
    return ch.rstrip("=")


# ── TOTP (recovery only) ───────────────────────────────────────────────────────────────────────────────────────────


def totp_fingerprint(secret: str) -> str:
    return hashlib.sha256(("ops-totp:" + secret).encode("utf-8")).hexdigest()[:16]


def totp_verify(secret: str, code: Any, *, now: Optional[float] = None, window: int = 1) -> Optional[int]:
    """The accepted RFC 6238 time step for ``code`` (30 s, 6 digits), or None. The caller records the step so it is
    never accepted twice."""
    try:
        import pyotp
    except Exception as exc:  # noqa: BLE001
        raise AuthError("DEPENDENCY_MISSING", "pyotp is not installed", 503) from exc
    c = str(code or "").strip()
    if not c.isdigit() or len(c) != 6:
        return None
    t = time.time() if now is None else now
    totp = pyotp.TOTP(secret)
    base = int(t // totp.interval)
    for off in range(-window, window + 1):
        step = base + off
        if hmac.compare_digest(totp.at(step * totp.interval), c):
            return step
    return None
