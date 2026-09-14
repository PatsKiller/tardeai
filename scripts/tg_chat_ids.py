"""tg_chat_ids.py — operator Telegram chat IDs, sourced from env/.env. NEVER hardcoded.

Hard rule: no hardcoded names/values — config comes from a source (env, .env, DB). This is the single
place alert chat IDs are resolved.

ROUTING (operator decision 2026-09-14, "1. yes" to the routing map)
-------------------------------------------------------------------
``chat_ids()`` used to return TRADEAI_PROPOSAL_ALERT_CHAT_ID + TELEGRAM_CHAT_ID merged, so every
generic broadcast that used it -- alert_dispatcher_unified (pipeline-critical, data-staleness, Brave
budget), hermes_score_alerts, the directive-event notifier -- also landed in the Proposal Decisions
group, which is for proposals and approvals only. The Telegram export audit showed holdings, stop and
health noise in that group.

* ``chat_ids()``           the operator's direct chats (TELEGRAM_CHAT_ID) -- generic alerts
* ``proposal_chat_ids()``  the Proposal Decisions group (TRADEAI_PROPOSAL_ALERT_CHAT_ID) -- proposals only
* ``allowed_chat_ids()``   both -- for INBOUND allowlists (button callbacks, replies), never for sending
"""
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _read(key: str) -> list:
    v = os.environ.get(key, "")
    if not v:
        try:
            for line in (_ROOT / ".env").read_text().splitlines():
                if line.startswith(key + "="):
                    v = line.split("=", 1)[1].strip()
                    break
        except Exception:
            pass
    out = []
    for c in str(v).split(","):
        c = c.strip().strip("'\"")
        if c and c not in out:
            out.append(c)
    return out


def chat_ids():
    """The operator's direct Telegram chats for generic alerts (de-duped, in order)."""
    return _read("TELEGRAM_CHAT_ID")


def proposal_chat_ids():
    """The Proposal Decisions group: proposals and approvals only."""
    return _read("TRADEAI_PROPOSAL_ALERT_CHAT_ID")


def allowed_chat_ids():
    """Every chat the operator uses -- for accepting inbound updates, not for broadcasting."""
    out = []
    for c in proposal_chat_ids() + chat_ids():
        if c not in out:
            out.append(c)
    return out
