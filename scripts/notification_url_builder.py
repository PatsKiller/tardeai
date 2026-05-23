#!/usr/bin/env python3
"""ALERT-URL-FQDN-1 — Central URL builder for user-facing notifications.

Converts local/internal IP links to Tailscale FQDN for Telegram/email messages.
Does NOT modify internal health-check or API binding code.
"""
import re

PUBLIC_BASE_URL = "https://ms01-openclaw.tail163d14.ts.net"
DASHBOARD_PATH = "/v2/"

# Patterns to replace in user-facing text
_REPLACEMENTS = [
    (re.compile(r"https?://192\.168\.50\.16:7777"), PUBLIC_BASE_URL),
    (re.compile(r"https?://192\.168\.50\.16"), PUBLIC_BASE_URL),
    (re.compile(r"192\.168\.50\.16:7777"), PUBLIC_BASE_URL.replace("https://", "")),
    (re.compile(r"https?://localhost:7777"), PUBLIC_BASE_URL),
    (re.compile(r"https?://127\.0\.0\.1:7777"), PUBLIC_BASE_URL),
    (re.compile(r"https?://100\.66\.120\.124:7777"), PUBLIC_BASE_URL),
    (re.compile(r"https?://100\.66\.120\.124"), PUBLIC_BASE_URL),
]


def get_public_base_url() -> str:
    return PUBLIC_BASE_URL


def build_dashboard_url(path: str = "/v2/") -> str:
    return f"{PUBLIC_BASE_URL}{path}"


def build_proposal_url(proposal_id) -> str:
    return f"{PUBLIC_BASE_URL}/v2/paper-proposals?id={proposal_id}"


def build_trade_url(trade_id) -> str:
    return f"{PUBLIC_BASE_URL}/v2/automated-trade-journal?trade={trade_id}"


def build_system_health_url() -> str:
    return f"{PUBLIC_BASE_URL}/v2/system-health"


def publicize_url(url: str) -> str:
    """Replace local/internal IPs with public FQDN in a URL string."""
    if not url:
        return url
    result = url
    for pattern, replacement in _REPLACEMENTS:
        result = pattern.sub(replacement, result)
    # Normalize double slashes in path (but not in https://)
    result = re.sub(r"(?<!:)//+", "/", result)
    return result


def publicize_message(text: str) -> str:
    """Replace all local/internal URLs in a message body with FQDN versions."""
    if not text:
        return text
    result = text
    for pattern, replacement in _REPLACEMENTS:
        result = pattern.sub(replacement, result)
    return result
