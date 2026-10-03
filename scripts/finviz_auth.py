"""Finviz Elite credentials: session cookie first, Elite API token as the backstop.

FINVIZ_COOKIE is a browser session and expires; FINVIZ_API_TOKEN is the Elite
export token (``auth=`` query param) and does not. AGENTS.md requires trying the
token before declaring Finviz auth dead. Secret values never leave these helpers
in a form meant for logs: anything recorded goes through ``redact``.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_AUTH_PARAM = re.compile(r"(auth=)[^&\s'\"]+", re.IGNORECASE)


def finviz_secret(name: str) -> str:
    """Resolve a secret by name (tmpfs SM render, env, disk .env)."""
    try:
        sec = ROOT / "scripts" / "secrets"
        if str(sec) not in sys.path:
            sys.path.insert(0, str(sec))
        from resolve_secret import resolve_secret
        return (resolve_secret(name, "") or "").strip().strip("'\"")
    except Exception:
        return (os.environ.get(name) or "").strip().strip("'\"")


def with_auth_token(url: str, token: str) -> str:
    if not token or "auth=" in url:
        return url
    return f"{url}{'&' if '?' in url else '?'}auth={token}"


def redact(text: object, *secrets: str) -> str:
    """Text safe to log or persist: auth= params and any given secret removed."""
    out = _AUTH_PARAM.sub(r"\1<redacted>", str(text or ""))
    for secret in secrets:
        if secret and len(secret) >= 6:
            out = out.replace(secret, "<redacted>")
    return out
