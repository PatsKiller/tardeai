"""Telegram ``ACK RED`` reply → acknowledge the open market-risk episode (DSN-20261031-market-risk-engine P3-T7).

The operator answers a Red (or Orange) market-risk card by replying ``ACK RED``, ``ACK ORANGE`` or a bare ``ACK``.
This is the safe-direction one-step control the design names (AGENTS.md §27.3): it only silences repeats of the
open episode, and a tier upgrade or a newly STRESSed category re-opens it. Only allowlisted operator chats may
acknowledge (the same allowlist the inbound poller applies). The receipt is the episode store itself
(``escalation.acknowledge`` appends ``acks[]`` with actor, channel, time and tier). Advisory only: nothing here
sizes, orders, stops or weights anything (MBI_BEHAVIOR = 0).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

_ACK_RE = re.compile(r"^\s*ack(?:\s+(red|orange))?\s*[.!]?\s*$", re.IGNORECASE)


def is_ack_text(text: str | None) -> bool:
    return bool(_ACK_RE.match(str(text or "")))


def handle_ack_text(
    text: str,
    *,
    chat_id: Any,
    from_id: Any = None,
    allowed_chats: Iterable[Any],
    now: Optional[datetime] = None,
    path: Optional[Path] = None,
) -> Optional[str]:
    """Return the reply for an ACK message, or None when the text is not an ACK."""
    m = _ACK_RE.match(str(text or ""))
    if not m:
        return None
    allowed = {str(c) for c in allowed_chats if c is not None and str(c)}
    if str(chat_id) not in allowed:
        return "Not acknowledged: this chat is not an operator chat."
    try:
        from lib.market_risk import escalation
    except ImportError:  # imported as scripts.lib
        from scripts.lib.market_risk import escalation

    now = now or datetime.now(timezone.utc)
    ep = escalation.open_episode(escalation.load(path))
    if ep is None:
        return "Nothing open: there is no market-risk episode to acknowledge."
    said = (m.group(1) or "").upper()
    if said and said != str(ep.get("tier") or "").upper():
        return f"Not acknowledged: the open episode is {ep.get('tier')}, not {said}. Reply ACK {ep.get('tier')} or ACK."
    if ep.get("status") == "ACKED":
        return f"Already acknowledged at {ep.get('acknowledged_at')} ({ep.get('tier')}); repeats stay silenced."
    actor = f"telegram:{from_id or chat_id}"
    status, body = escalation.acknowledge(ep["id"], actor=actor, channel="telegram", now=now, path=path)
    if status != 200:
        return f"Not acknowledged: {body.get('error')}"
    got = body["episode"]
    return (
        f"Acknowledged market risk {got.get('tier')} (episode {got.get('id')}) at {got.get('acknowledged_at')}. "
        "Repeats are silenced; a tier upgrade or a new STRESS category re-opens it. Advisory: no order, size or stop."
    )
