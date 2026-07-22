#!/usr/bin/env python3
"""ALERT-URL-FQDN-1 — Central URL builder for user-facing notifications.

Converts local/internal IP links to the Tailscale FQDN AND rewrites legacy /v2/ dashboard paths to their
/v3/ Command Center equivalents (v3 is the canonical UI). For Telegram/email messages only — does NOT modify
internal health-check or API binding code.

Deep-link contract (2026-07-21):
  • Prefer https://{TAILSCALE_HOSTNAME} when set — matches `tailscale serve` → :7777 (no port in URL).
  • Override with NOTIFICATION_PUBLIC_BASE_URL if needed.
  • Query tabs use %20 (never +) so Telegram clients and SPA routers agree.
  • All Telegram body/button links MUST go through this module.
"""
from __future__ import annotations

import os
import re
from urllib.parse import quote, urlencode
# Host only (for rewrite rules)
_FQDN = os.getenv("TAILSCALE_HOSTNAME", "ms01-openclaw.tail163d14.ts.net").strip() or "ms01-openclaw.tail163d14.ts.net"


def get_public_base_url() -> str:
    """Canonical public base for operator-facing links (no trailing slash).

    Priority:
      1. NOTIFICATION_PUBLIC_BASE_URL (explicit override)
      2. https://{TAILSCALE_HOSTNAME}  — Tailscale serve on :443 → localhost:7777
      3. http://{FQDN}:7777           — direct portfolio_server (fallback)
    """
    explicit = (os.getenv("NOTIFICATION_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    host = (os.getenv("TAILSCALE_HOSTNAME") or _FQDN).strip()
    if host:
        # Serve terminates TLS on 443 and proxies to :7777 — this is the URL phones on
        # the tailnet can open. Do NOT force :7777 here (breaks serve / certs).
        return f"https://{host}"
    return f"http://{_FQDN}:7777"


PUBLIC_BASE_URL = get_public_base_url()  # evaluated at import; prefer get_public_base_url() at call time
DASHBOARD_PATH = "/v3/"
_HOSTPORT = get_public_base_url().split("://", 1)[-1]

# Internal IPs/hosts → canonical public base. Guard ports so :8443 DOF endpoint is preserved.
def _replacements():
    base = get_public_base_url()
    hostport = base.split("://", 1)[-1]
    fqdn = (os.getenv("TAILSCALE_HOSTNAME") or _FQDN).strip()
    return [
        (re.compile(r"https?://192\.168\.50\.16:7777"), base),
        (re.compile(r"https?://192\.168\.50\.16(?!:\d)"), base),
        (re.compile(r"192\.168\.50\.16:7777"), hostport),
        (re.compile(r"https?://localhost:7777"), base),
        (re.compile(r"https?://127\.0\.0\.1:7777"), base),
        (re.compile(r"https?://100\.66\.120\.124:7777"), base),
        (re.compile(r"https?://100\.66\.120\.124(?!:\d)"), base),
        # Port-less FQDN already correct when base is https://fqdn — leave alone.
        # Port-bearing :7777 form → upgrade to base if base is serve-https.
        (re.compile(r"https?://" + re.escape(fqdn) + r":7777"), base),
    ]


# Legacy /v2/ page -> /v3/ hub route.
_V2_TO_V3 = [
    (re.compile(r"/v2/(?:paper-proposals|paper-status|paper-governance|trade-ai|paper-trading)\b"), "/v3/trading"),
    (re.compile(r"/v2/(?:automated-trade-journal|paper-journal|journal)\b"), "/v3/journal"),
    (re.compile(r"/v2/(?:system-health|system_health|alerts|siem|jobs|crons)\b"), "/v3/system"),
    (re.compile(r"/v2/risk(?:-regime[a-z/_-]*|[_-][a-z/_-]*)?\b"), "/v3/risk"),
    (re.compile(r"/v2/(?:recovery|reco)[a-z/_-]*\b"), "/v3/risk"),
    (re.compile(r"/v2/(?:next-actions?|action-inbox|actions?)[a-z/_-]*\b"), "/v3/"),
    (re.compile(r"/v2/(?:approvals?|pending[_-]proposals?|proposals?)[a-z/_-]*\b"), "/v3/trading"),
    (re.compile(r"/v2/(?:retirement[a-z_-]*|tax-lots|tax_lots)\b"), "/v3/retirement"),
    (re.compile(r"/v2/(?:overnight[a-z-]*|intelligence[a-z-]*)\b"), "/v3/intelligence"),
    (re.compile(r"/v2/hermes[a-z/_-]*\b"), "/v3/hermes"),
    (re.compile(r"/v2/watchpool\b"), "/v3/watch?tab=watchpool"),
    (re.compile(r"/v2/watchlist\b"), "/v3/watch?tab=watchlist"),
    (re.compile(r"/v2/sectors?\b"), "/v3/watch?tab=sectors"),
    (re.compile(r"/v2/inbox\b"), "/v3/"),
    (re.compile(r"/v3/watchpool\b"), "/v3/watch?tab=watchpool"),
    (re.compile(r"/v3/watchlist\b"), "/v3/watch?tab=watchlist"),
    (re.compile(r"/v3/sectors\b"), "/v3/watch?tab=sectors"),
    (re.compile(r"/v2/portfolio[a-z/_-]*\b"), "/v3/portfolio"),
    (re.compile(r"/v2/agents?[a-z/_-]*\b"), "/v3/agents"),
    (re.compile(r"/v2/strateg(?:y|ies)[a-z/_-]*\b"), "/v3/strategy"),
    (re.compile(r"/v2/symbol/[A-Z.]+/[a-z]+\b"), "/v3/journal"),
    (re.compile(r"/v2/(?:morning-brief|daily-brief|evening-brief|briefing|brief|digest|home|dashboard|index)\b"), "/v3/"),
    (re.compile(r"/v2/?(?=[\s\")]|$)"), "/v3/"),
    (re.compile(r"/v2/"), "/v3/"),
]


def _to_v3(url: str) -> str:
    if not url:
        return url
    for pat, rep in _V2_TO_V3:
        url = pat.sub(rep, url)
    return url


def build_dashboard_url(path: str = "/v3/", query: dict | None = None) -> str:
    """Build absolute CC v3 URL. `path` like /v3/trading; query values urlencoded (%20 not +)."""
    base = get_public_base_url()
    if not path.startswith("/"):
        path = "/" + path
    path = _to_v3(path)
    if not query:
        return f"{base}{path}"
    # quote (not quote_plus) so spaces become %20 — Telegram + SPA both handle %20 reliably
    def _qv(s, safe="", encoding=None, errors=None):
        return quote(str(s), safe=safe, encoding=encoding, errors=errors)

    q = urlencode(
        {k: v for k, v in query.items() if v is not None and v != ""},
        quote_via=_qv,
    )
    return f"{base}{path}?{q}"


def build_proposal_url(proposal_id, symbol: str | None = None) -> str:
    """Deep-link to Trading → Proposals for one proposal id.

    Path form /v3/go/proposal/{id} — NO query-string & separators.
    Telegram / many mobile browsers truncate URLs at the first bare &.
    """
    base = get_public_base_url()
    pid = str(proposal_id).strip()
    url = f"{base}/v3/go/proposal/{pid}"
    if symbol:
        # single optional query only (no second &)
        url += f"?symbol={quote(str(symbol).upper(), safe='')}"
    return url


def build_broker_order_url(intent_id: str) -> str:
    """Deep-link to Trading → Broker Orders for one intent id (2FA approval).

    Path form /v3/go/order/{intent_id} — avoids ?tab=...&intent=... which Telegram
    often truncates after the first & so the intent id never arrives.
    """
    base = get_public_base_url()
    iid = str(intent_id).strip()
    return f"{base}/v3/go/order/{iid}"


def build_broker_order_url_legacy_query(intent_id: str) -> str:
    """Legacy query form (kept for tests / local SPA). Prefer build_broker_order_url."""
    return build_dashboard_url("/v3/trading", {"tab": "Broker Orders", "intent": str(intent_id)})


def build_trade_url(trade_id) -> str:
    return build_dashboard_url("/v3/journal", {"trade": str(trade_id)})


def build_system_health_url() -> str:
    return build_dashboard_url("/v3/system")


def publicize_url(url: str) -> str:
    """Replace internal IPs with the public FQDN AND legacy /v2/ paths with /v3/ in a URL string."""
    if not url:
        return url
    result = url
    for pattern, replacement in _replacements():
        result = pattern.sub(replacement, result)
    result = re.sub(r"(?<!:)//+", "/", result)
    return _to_v3(result)


def publicize_message(text: str) -> str:
    """Replace internal URLs AND legacy /v2/ dashboard paths in a message body with FQDN /v3/ versions."""
    if not text:
        return text
    result = text
    for pattern, replacement in _replacements():
        result = pattern.sub(replacement, result)
    return _to_v3(result)


def telegram_url_button(text: str, url: str) -> dict:
    """Inline keyboard URL button — preferred over body Markdown links (survives parse failures)."""
    return {"text": text, "url": url}
