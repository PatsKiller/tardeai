# Source Export: scripts/telegram_alert_routing_policy.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/telegram_alert_routing_policy.py` |
| **Git Branch** | `main` |
| **Git Commit** | `c1286d314deb377df49713e1646f139db7f43643` |
| **Export Timestamp** | `2026-05-26T15:50:11Z` |
| **SHA256** | `6a7cb5dfc3a5f20814eb135a031f0935b9e977f8f5feadc55cf76e6c40899a71` |
| **File Size** | 3396 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""telegram_alert_routing_policy.py — Route alerts to correct Telegram destination.

Pure functions. No Telegram sends. No secrets printed.
"""
import os

PROPOSAL_ALERT_TYPES = {
    "ACTIONABLE_READY", "NEEDS_OPERATOR_DECISION", "BLOCKED_NEEDS_REBUILD",
    "BLOCKED_EXECUTION_FAILED", "PRICE_MOVED", "REBUILD_REQUIRED",
    "WATCHPOOL_READY", "EXPIRED_OR_STALE",
}


def _env(key: str) -> str:
    return os.environ.get(key, "")


def get_routing_config() -> dict:
    """Load routing config from environment. Never print raw values."""
    proposal_chat = _env("TRADEAI_PROPOSAL_ALERT_CHAT_ID") or _env("TELEGRAM_CHAT_ID")
    proposal_thread = _env("TRADEAI_PROPOSAL_ALERT_THREAD_ID")
    general_chat = _env("TRADEAI_GENERAL_ALERT_CHAT_ID") or _env("TELEGRAM_CHAT_ID")
    general_thread = _env("TRADEAI_GENERAL_ALERT_THREAD_ID")

    has_dedicated = bool(_env("TRADEAI_PROPOSAL_ALERT_CHAT_ID"))

    return {
        "mode": "dedicated_proposal_channel" if has_dedicated else "single_channel",
        "proposal_chat_configured": bool(proposal_chat),
        "general_chat_configured": bool(general_chat),
        "has_dedicated_proposal_channel": has_dedicated,
        "proposal_thread_configured": bool(proposal_thread),
        # Never include raw IDs — redacted references only
    }


def classify_alert_channel(alert_packet: dict) -> str:
    """Determine which channel type an alert belongs to."""
    alert_type = alert_packet.get("alert_type", "")
    if alert_type in PROPOSAL_ALERT_TYPES:
        return "proposal"
    return "general"


def telegram_destination_for_alert(alert_packet: dict, config: dict = None) -> dict:
    """Get the Telegram destination for an alert. Returns redacted info only."""
    cfg = config or get_routing_config()
    channel = classify_alert_channel(alert_packet)

    if channel == "proposal":
        chat_id = _env("TRADEAI_PROPOSAL_ALERT_CHAT_ID") or _env("TELEGRAM_CHAT_ID")
        thread_id = _env("TRADEAI_PROPOSAL_ALERT_THREAD_ID") or None
    else:
        chat_id = _env("TRADEAI_GENERAL_ALERT_CHAT_ID") or _env("TELEGRAM_CHAT_ID")
        thread_id = _env("TRADEAI_GENERAL_ALERT_THREAD_ID") or None

    return {
        "channel_type": channel,
        "chat_id": chat_id,  # Used internally for send — never logged raw
        "thread_id": thread_id,
        "configured": bool(chat_id),
        "mode": cfg.get("mode", "single_channel"),
    }


def redact_telegram_destination(destination: dict) -> dict:
    """Redact sensitive fields for logging/docs."""
    return {
        "channel_type": destination.get("channel_type"),
        "configured": destination.get("configured"),
        "mode": destination.get("mode"),
        "chat_id_redacted": f"***{str(destination.get('chat_id', ''))[-4:]}" if destination.get("chat_id") else "not_set",
        "thread_id_set": bool(destination.get("thread_id")),
    }


def validate_telegram_routing_config(config: dict = None) -> dict:
    """Validate routing config completeness."""
    cfg = config or get_routing_config()
    issues = []
    if not cfg.get("proposal_chat_configured"):
        issues.append("proposal_chat_not_configured")
    if not cfg.get("general_chat_configured"):
        issues.append("general_chat_not_configured")
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "mode": cfg.get("mode"),
    }
```
