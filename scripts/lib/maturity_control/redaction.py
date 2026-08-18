"""Secret redaction for maturity control GET APIs."""
from __future__ import annotations

import re
from typing import Any

_SECRET_KEYS = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|authorization|dsn|chat[_-]?id|bot_token)",
    re.I,
)
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}")
_KEYISH = re.compile(r"(?i)(sk-|xoxb-|ghp_|AIza)[A-Za-z0-9_\-]{8,}")


def redact_value(key: str, value: Any) -> Any:
    if _SECRET_KEYS.search(str(key or "")):
        return None if value in (None, "", []) else "[REDACTED]"
    if isinstance(value, str):
        v = _BEARER.sub(r"\1[REDACTED]", value)
        v = _KEYISH.sub("[REDACTED]", v)
        return v
    return value


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: redact(redact_value(str(k), v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj
