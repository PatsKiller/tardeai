"""Telegram ``ACK RED`` reply → acknowledge the open market-risk episode (DSN-20261031-market-risk-engine P3-T7).

The operator answers a market-risk card by replying ``ACK RED`` or ``ACK ORANGE``. This is the safe-direction one-step
control the design names (AGENTS.md §27.3): it only silences repeats of the open episode, and a tier upgrade or a newly
STRESSed category re-opens it. Rules (review of #2354):

* **The tier word is checked under the ledger lock.** ``escalation.acknowledge(expected_tier=...)`` refuses when the open
  episode's tier is not the one the operator named, so an ORANGE→RED upgrade that lands between the operator reading
  ORANGE and the ACK arriving can never be silenced by "ACK ORANGE".
* **RED needs the words ``ACK RED``.** A bare ``ACK`` never acknowledges a RED.
* **A bare ``ACK`` must be a reply to a market-risk card.** It binds to the tier that card shows and to the episode
  that was open when the card went out (the card is no older than the episode's last tier change); anything else is
  refused with the reason.
* **Only the operator.** The chat must be allowlisted AND the sender's ``from.id`` must be an operator id
  (``TRADEAI_OPERATOR_FROM_IDS``, else the allowlisted chat ids, which for a private chat equal the operator's own id),
  so another member of an allowlisted group cannot acknowledge.

The receipt is the episode store itself (``escalation.acknowledge`` appends ``acks[]`` and the ``.acks.jsonl`` sidecar).
Advisory only: nothing here sizes, orders, stops or weights anything (MBI_BEHAVIOR = 0).
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

_ACK_RE = re.compile(r"^\s*ack(?:\s+(red|orange))?\s*[.!]?\s*$", re.IGNORECASE)
_CARD_TIER_RE = re.compile(r"\b(?:MARKET RISK\s+(RED|ORANGE)\b|(RED|ORANGE) ALERT ACTIVE)")


def is_ack_text(text: str | None) -> bool:
    return bool(_ACK_RE.match(str(text or "")))


def operator_from_ids(allowed_chats: Iterable[Any]) -> set[str]:
    """Operator Telegram user ids: ``TRADEAI_OPERATOR_FROM_IDS`` when set, else the allowlisted chat ids (a private
    chat's id is the operator's user id). Same rule as ``telegram_callback_handler._allowed_from_ids``."""
    raw = os.environ.get("TRADEAI_OPERATOR_FROM_IDS", "").strip()
    if raw:
        return {x.strip() for x in raw.split(",") if x.strip()}
    return {str(c) for c in allowed_chats if c is not None and str(c)}


def card_tier(text: str | None) -> str | None:
    """The tier a market-risk card shows ("MARKET RISK RED 83/100" or "RED ALERT ACTIVE — …"), or None."""
    m = _CARD_TIER_RE.search(str(text or ""))
    return (m.group(1) or m.group(2)).upper() if m else None


def _parse(s: Any) -> datetime | None:
    if not s:
        return None
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def handle_ack_text(
    text: str,
    *,
    chat_id: Any,
    from_id: Any = None,
    allowed_chats: Iterable[Any],
    reply_to: Optional[dict] = None,
    now: Optional[datetime] = None,
    path: Optional[Path] = None,
) -> Optional[str]:
    """Return the reply for an ACK message, or None when the text is not an ACK.

    ``reply_to`` is the Telegram ``reply_to_message`` object (its ``text`` and unix ``date``)."""
    m = _ACK_RE.match(str(text or ""))
    if not m:
        return None
    allowed = [c for c in allowed_chats if c is not None and str(c)]
    if str(chat_id) not in {str(c) for c in allowed}:
        return "Not acknowledged: this chat is not an operator chat."
    if from_id is None or str(from_id) not in operator_from_ids(allowed):
        return "Not acknowledged: only the operator can acknowledge market risk."
    try:
        from lib.market_risk import escalation
    except ImportError:  # imported as scripts.lib
        from scripts.lib.market_risk import escalation

    now = now or datetime.now(timezone.utc)
    ep = escalation.open_episode(escalation.load(path))
    if ep is None:
        return "Nothing open: there is no market-risk episode to acknowledge."
    said = (m.group(1) or "").upper()
    episode_id = ep["id"]
    if said:
        expected = said
    else:
        shown = card_tier((reply_to or {}).get("text"))
        if not shown:
            return (
                f"Not acknowledged: reply ACK {ep.get('tier')} (or reply ACK to the market-risk alert itself). "
                "A bare ACK must answer a market-risk card."
            )
        if shown == "RED":
            return "Not acknowledged: a RED needs the words ACK RED."
        sent = (reply_to or {}).get("date")
        anchor = _parse(ep.get("anchor_at") or ep.get("opened_at"))
        if sent is None or anchor is None or datetime.fromtimestamp(int(sent), timezone.utc) < anchor:
            return (
                f"Not acknowledged: that card is older than the open {ep.get('tier')} episode. "
                f"Reply ACK {ep.get('tier')} to acknowledge it."
            )
        expected = shown
    if ep.get("status") == "ACKED" and str(ep.get("tier")).upper() == expected:
        return f"Already acknowledged at {ep.get('acknowledged_at')} ({ep.get('tier')}); repeats stay silenced."
    actor = f"telegram:{from_id}"
    status, body = escalation.acknowledge(
        episode_id, actor=actor, channel="telegram", now=now, path=path, expected_tier=expected
    )
    if status != 200:
        return f"Not acknowledged: {body.get('error')}"
    got = body["episode"]
    return (
        f"Acknowledged market risk {got.get('tier')} (episode {got.get('id')}) at {got.get('acknowledged_at')}. "
        "Repeats are silenced; a tier upgrade or a new STRESS category re-opens it. Advisory: no order, size or stop."
    )
