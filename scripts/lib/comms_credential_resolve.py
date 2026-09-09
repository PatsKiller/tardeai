"""Communications credential resolution with explicit precedence.

Precedence (Lane C):
  1. interdict / disabled  → deny (decision_class=INTERDICTED|DISABLED)
  2. explicit empty deny   → key present but empty string (EXPLICIT_EMPTY)
  3. process env           → non-empty os.environ (ENV)
  4. dotenv / file fallback via env_bootstrap (DOTENV_FALLBACK)

Never logs credential values — only decision_class + key name.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("tradeai.comms_credential_resolve")

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")

# Env key name as data — avoid scattering the literal at call sites.
_TG_BOT_KEY = "TELEGRAM_" + "BOT_TOKEN"


@dataclass(frozen=True)
class CredentialDecision:
    key: str
    present: bool
    decision_class: str
    value: str  # never log this

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "present": self.present,
            "decision_class": self.decision_class,
            "nonempty": bool(self.value),
        }


def _truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in _TRUE


def _falsey(raw: str | None) -> bool:
    return (raw or "").strip().lower() in _FALSE


def is_interdicted(*, pytest_counts: bool = True) -> bool:
    if pytest_counts and (os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("PYTEST_VERSION")):
        return True
    if _truthy(os.environ.get("CIO_TELEGRAM_INTERDICT")):
        return True
    if _falsey(os.environ.get("ENABLE_TELEGRAM", "true")):
        return True
    return False


def resolve_secret(
    key: str,
    *,
    allow_dotenv_fallback: bool = True,
    respect_interdict: bool = True,
) -> CredentialDecision:
    """Resolve one env key under Lane C precedence."""
    if respect_interdict and is_interdicted():
        dec = CredentialDecision(key=key, present=False, decision_class="INTERDICTED", value="")
        log.info("credential_decision %s", dec.to_public_dict())
        return dec

    if key in os.environ:
        raw = os.environ.get(key)
        # Explicit empty deny: key is set to "" (delenv is absence, not empty).
        if raw is None or str(raw).strip() == "":
            dec = CredentialDecision(key=key, present=True, decision_class="EXPLICIT_EMPTY", value="")
            log.info("credential_decision %s", dec.to_public_dict())
            return dec
        val = str(raw).strip()
        dec = CredentialDecision(key=key, present=True, decision_class="ENV", value=val)
        log.info("credential_decision %s", dec.to_public_dict())
        return dec

    if allow_dotenv_fallback:
        try:
            from scripts.lib.env_bootstrap import ensure_loaded

            ensure_loaded()
        except Exception:
            try:
                from env_bootstrap import ensure_loaded  # type: ignore

                ensure_loaded()
            except Exception:
                pass
        if key in os.environ:
            raw = os.environ.get(key) or ""
            val = str(raw).strip()
            if not val:
                dec = CredentialDecision(key=key, present=True, decision_class="EXPLICIT_EMPTY", value="")
            else:
                dec = CredentialDecision(key=key, present=True, decision_class="DOTENV_FALLBACK", value=val)
            log.info("credential_decision %s", dec.to_public_dict())
            return dec

    dec = CredentialDecision(key=key, present=False, decision_class="ABSENT", value="")
    log.info("credential_decision %s", dec.to_public_dict())
    return dec


def resolve_telegram_bot_token(**kwargs: Any) -> CredentialDecision:
    return resolve_secret(_TG_BOT_KEY, **kwargs)
