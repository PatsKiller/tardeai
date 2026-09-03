"""Host and method safety for the CC runtime harness.

Never default to production. Refuse private/live hosts unless an explicit
read-only test flag is present. Never send POST/PUT/PATCH/DELETE to a live host.
"""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

PRODUCTION_HOST_MARKERS = (
    "trade-ai",
    "tardeai",
    "production",
    "prod.",
    "live.",
    "ms01",
    "rockville",
)

PRIVATE_NETWORK_PREFIXES = (
    "10.",
    "192.168.",
    "172.16.",
    "172.17.",
    "172.18.",
    "172.19.",
    "172.2",
    "172.3",
)

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    reason: str
    host_class: str  # loopback | ephemeral | preview | live_refused | unknown


def _is_loopback(host: str) -> bool:
    h = (host or "").strip().lower().rstrip(".")
    if h in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def _looks_private(host: str) -> bool:
    h = (host or "").strip().lower()
    if _is_loopback(h):
        return False
    try:
        ip = ipaddress.ip_address(h)
        return bool(ip.is_private or ip.is_link_local)
    except ValueError:
        return any(h.startswith(p) for p in PRIVATE_NETWORK_PREFIXES)


def _looks_production(host: str) -> bool:
    h = (host or "").strip().lower()
    return any(m in h for m in PRODUCTION_HOST_MARKERS)


def classify_base_url(base_url: str | None) -> SafetyDecision:
    if not base_url:
        return SafetyDecision(False, "missing_base_url", "unknown")
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    if not host:
        return SafetyDecision(False, "unparseable_host", "unknown")
    if _is_loopback(host):
        return SafetyDecision(True, "loopback_ok", "loopback")
    if _looks_production(host):
        return SafetyDecision(False, "production_host_refused", "live_refused")
    if _looks_private(host):
        flag = os.environ.get("CC_RUNTIME_ALLOW_LIVE_READONLY", "").strip()
        if flag in {"1", "true", "TRUE", "yes", "YES"}:
            return SafetyDecision(True, "private_host_readonly_flag", "preview")
        return SafetyDecision(
            False,
            "private_live_host_refused_without_CC_RUNTIME_ALLOW_LIVE_READONLY",
            "live_refused",
        )
    # Public non-loopback still refused unless preview env explicitly set
    preview = os.environ.get("CC_RUNTIME_PREVIEW_BASE_URL", "").strip()
    if preview and base_url.rstrip("/") == preview.rstrip("/"):
        return SafetyDecision(True, "explicit_preview_env", "preview")
    return SafetyDecision(False, "non_loopback_host_refused", "live_refused")


def assert_method_allowed(method: str, base_url: str | None) -> SafetyDecision:
    m = (method or "GET").upper()
    host = classify_base_url(base_url)
    if m in MUTATING_METHODS:
        if host.host_class in {"loopback", "ephemeral"} or (host.allowed and host.host_class == "loopback"):
            # Still refuse mutating against anything classified live/preview.
            if host.host_class == "loopback" and _is_loopback(urlparse(base_url or "").hostname or ""):
                # Hermetic fixture server may implement POST for negative-control
                # detection only when CC_RUNTIME_ALLOW_FIXTURE_MUTATION=1.
                if os.environ.get("CC_RUNTIME_ALLOW_FIXTURE_MUTATION", "") in {
                    "1",
                    "true",
                    "TRUE",
                }:
                    return SafetyDecision(True, "fixture_mutation_allowed", "ephemeral")
                return SafetyDecision(
                    False,
                    "mutating_method_blocked_even_on_loopback_without_fixture_flag",
                    "loopback",
                )
        return SafetyDecision(
            False,
            f"mutating_method_{m}_refused_against_live_or_preview",
            host.host_class,
        )
    if not host.allowed:
        return SafetyDecision(False, host.reason, host.host_class)
    return SafetyDecision(True, "get_ok", host.host_class)


def redact_secrets(text: str) -> str:
    """Redact secrets and account-like identifiers from evidence text."""
    out = text
    patterns = [
        (r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*[\"']?[^\s,\"']+", r"\1=REDACTED"),
        (r"(?i)bearer\s+[a-z0-9\-._~+/]+=*", "Bearer REDACTED"),
        (r"\b[0-9]{8,12}\b", "ACCT_REDACTED"),  # coarse account ids
        (r"(?i)(alpaca|schwab|moomoo)_[a-z0-9_]+", r"\1_ACCOUNT_REDACTED"),
    ]
    for pat, repl in patterns:
        out = re.sub(pat, repl, out)
    return out


def default_hermetic_base() -> str:
    """Never returns a production URL."""
    return "http://127.0.0.1:0"  # port 0 → ephemeral bind
