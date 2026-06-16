#!/usr/bin/env python3
"""ALERT-URL-FQDN-1 — Central URL builder for user-facing notifications.

Converts local/internal IP links to the Tailscale FQDN AND rewrites legacy /v2/ dashboard paths to their
/v3/ Command Center equivalents (v3 is the canonical UI). For Telegram/email messages only — does NOT modify
internal health-check or API binding code.
"""
import re

PUBLIC_BASE_URL = "https://ms01-openclaw.tail163d14.ts.net"
DASHBOARD_PATH = "/v3/"   # v3 is canonical

# Internal IPs/hosts -> public Tailscale FQDN
_REPLACEMENTS = [
    (re.compile(r"https?://192\.168\.50\.16:7777"), PUBLIC_BASE_URL),
    (re.compile(r"https?://192\.168\.50\.16"), PUBLIC_BASE_URL),
    (re.compile(r"192\.168\.50\.16:7777"), PUBLIC_BASE_URL.replace("https://", "")),
    (re.compile(r"https?://localhost:7777"), PUBLIC_BASE_URL),
    (re.compile(r"https?://127\.0\.0\.1:7777"), PUBLIC_BASE_URL),
    (re.compile(r"https?://100\.66\.120\.124:7777"), PUBLIC_BASE_URL),
    (re.compile(r"https?://100\.66\.120\.124"), PUBLIC_BASE_URL),
]

# Legacy /v2/ page -> /v3/ hub route. v3 routes: home(/v3/), portfolio, risk, trading, strategy, agents,
# intelligence, hermes, retirement, journal, watchlist, watchpool, sectors, system. Order matters (specific
# first); the trailing rules catch anything remaining so no /v2/ link survives.
_V2_TO_V3 = [
    (re.compile(r"/v2/(?:paper-proposals|paper-status|paper-governance|trade-ai|paper-trading)\b"), "/v3/trading"),
    (re.compile(r"/v2/(?:automated-trade-journal|paper-journal|journal)\b"), "/v3/journal"),
    (re.compile(r"/v2/(?:system-health|system_health|alerts|siem|jobs|crons)\b"), "/v3/system"),
    (re.compile(r"/v2/risk(?:-regime[a-z/_-]*|[_-][a-z/_-]*)?\b"), "/v3/risk"),
    (re.compile(r"/v2/(?:recovery|reco)[a-z/_-]*\b"), "/v3/risk"),     # Recovery Watch section lives in Risk hub
    (re.compile(r"/v2/(?:next-actions?|action-inbox|actions?)[a-z/_-]*\b"), "/v3/"),  # Action Inbox is on Home (longest-first; consume hyphen tails)
    (re.compile(r"/v2/(?:approvals?|pending[_-]proposals?|proposals?)[a-z/_-]*\b"), "/v3/trading"),  # approvals/proposals live on Trading
    (re.compile(r"/v2/(?:retirement[a-z_-]*|tax-lots|tax_lots)\b"), "/v3/retirement"),
    (re.compile(r"/v2/(?:overnight[a-z-]*|intelligence[a-z-]*)\b"), "/v3/intelligence"),
    (re.compile(r"/v2/hermes[a-z/_-]*\b"), "/v3/hermes"),
    (re.compile(r"/v2/watchpool\b"), "/v3/watchpool"),
    (re.compile(r"/v2/watchlist\b"), "/v3/watchlist"),
    (re.compile(r"/v2/sectors?\b"), "/v3/sectors"),
    (re.compile(r"/v2/portfolio[a-z/_-]*\b"), "/v3/portfolio"),
    (re.compile(r"/v2/agents?[a-z/_-]*\b"), "/v3/agents"),
    (re.compile(r"/v2/strateg(?:y|ies)[a-z/_-]*\b"), "/v3/strategy"),
    (re.compile(r"/v2/symbol/[A-Z.]+/[a-z]+\b"), "/v3/journal"),  # symbol drilldown -> journal
    # briefs / digests / home / dashboard have no standalone v3 page — they live on the v3 home (/v3/).
    (re.compile(r"/v2/(?:morning-brief|daily-brief|evening-brief|briefing|brief|digest|home|dashboard|index)\b"), "/v3/"),
    (re.compile(r"/v2/?(?=[\s\")]|$)"), "/v3/"),                   # bare /v2/ -> /v3/ home
    (re.compile(r"/v2/"), "/v3/"),                                 # any remaining /v2/<x> -> /v3/<x>
]


def _to_v3(url: str) -> str:
    if not url:
        return url
    for pat, rep in _V2_TO_V3:
        url = pat.sub(rep, url)
    return url


def get_public_base_url() -> str:
    return PUBLIC_BASE_URL


def build_dashboard_url(path: str = "/v3/") -> str:
    return _to_v3(f"{PUBLIC_BASE_URL}{path}")


def build_proposal_url(proposal_id) -> str:
    return f"{PUBLIC_BASE_URL}/v3/trading?proposal={proposal_id}"


def build_trade_url(trade_id) -> str:
    return f"{PUBLIC_BASE_URL}/v3/journal?trade={trade_id}"


def build_system_health_url() -> str:
    return f"{PUBLIC_BASE_URL}/v3/system"


def publicize_url(url: str) -> str:
    """Replace internal IPs with the public FQDN AND legacy /v2/ paths with /v3/ in a URL string."""
    if not url:
        return url
    result = url
    for pattern, replacement in _REPLACEMENTS:
        result = pattern.sub(replacement, result)
    result = re.sub(r"(?<!:)//+", "/", result)  # normalize double slashes (not in https://)
    return _to_v3(result)


def publicize_message(text: str) -> str:
    """Replace internal URLs AND legacy /v2/ dashboard paths in a message body with FQDN /v3/ versions."""
    if not text:
        return text
    result = text
    for pattern, replacement in _REPLACEMENTS:
        result = pattern.sub(replacement, result)
    return _to_v3(result)
