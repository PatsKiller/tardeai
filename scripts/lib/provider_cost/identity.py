"""Safe key fingerprints. Never persist or return raw secrets."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from typing import Optional

_SECRET_NAME_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd|authorization|bearer|credential)"
)

# Domain-separated pepper. Not a secret store — just prevents trivial reversal
# of short key suffixes. Operators may override via PROVIDER_COST_FP_PEPPER.
_DEFAULT_PEPPER = "tradeai-provider-cost-fp-v1"


def _pepper() -> bytes:
    return (os.environ.get("PROVIDER_COST_FP_PEPPER") or _DEFAULT_PEPPER).encode("utf-8")


def fingerprint_key(raw: Optional[str], *, provider: str = "deepseek") -> Optional[str]:
    """Irreversible fingerprint: provider + HMAC-SHA256(key)[:16]."""
    if not raw:
        return None
    key = str(raw).strip()
    if not key:
        return None
    digest = hmac.new(_pepper(), f"{provider}\n{key}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{provider}:{digest[:16]}"


def redacted_key_id(raw: Optional[str], *, provider: str = "deepseek") -> Optional[str]:
    """Human-safe label: ds_…last4 plus fingerprint suffix. Never the secret."""
    if not raw:
        return None
    key = str(raw).strip()
    if len(key) < 8:
        tail = "xxxx"
    else:
        tail = key[-4:]
    fp = fingerprint_key(key, provider=provider) or "unknown"
    short = fp.split(":")[-1][:4]
    prefix = {"deepseek": "ds", "openai": "oa", "anthropic": "an"}.get(provider, "k")
    return f"{prefix}_…{tail}/{short}"


def looks_like_secret_name(name: str) -> bool:
    return bool(_SECRET_NAME_RE.search(str(name or "")))


def redact_mapping(value):
    """Recursively replace secret-shaped keys/values. Never mutates input."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if looks_like_secret_name(str(k)):
                out[str(k)] = "[REDACTED]"
            else:
                out[str(k)] = redact_mapping(v)
        return out
    if isinstance(value, list):
        return [redact_mapping(v) for v in value]
    if isinstance(value, str) and len(value) >= 20 and re.fullmatch(r"[A-Za-z0-9_\-]{20,}", value):
        # long opaque tokens — do not emit
        return "[REDACTED]"
    return value
