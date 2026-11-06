"""One batching + repeat-floor mechanism for operator Telegram nudges.

Operator spec (SPEC_HOME_V008_NEEDS_YOU_APPROVALS_20261103.md §4): "Telegram: ONE short message per
new request ... batched and never repeated more than every 2 h. Quiet hours 22:00–07:00: only P0 pages;
everything else waits on the dashboard." The same section: "Incident escalations go to ONE digest, never
6 separate P1s." Both lanes call THIS module, so there is one batching style, one repeat floor and one
quiet window — not two mechanisms that drift.

Three pieces:

* :func:`batch_text` — the message body: a header, one bullet per item, then the footer. Used by
  ``scripts/approvals_notify.py`` (approval requests) and by ``scripts/lib/incident_supervisor.py``
  (the incident escalation digest).
* :class:`NudgeState` — a durable ``{key: iso8601 last-nudge}`` ledger so a still-open request is
  re-nudged at most once per ``floor_minutes`` (default 120) and never for a key that has gone away.
* :func:`nudge_decision` — should this run send? It composes the three rules in one order:
  nothing due → no send; inside the operator's quiet window → P1 only, everything else deferred (it
  stays due, so the first run after 07:00 sends ONE catch-up batch, never a message per item).

Quiet hours are NOT re-implemented here: the window (22:00–07:00 America/New_York, env-overridable) and
its exemptions already live in ``scripts/telegram_alert_router.py`` (operator decision 2026-10-09). This
module calls that function so the two surfaces cannot disagree about when night is.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "TelegramBatchLedger@v1"
DEFAULT_FLOOR_MINUTES = 120
PRIORITY_P1 = "P1"   # pages now, never quiet-held (the incident notifier's P1 contract)
PRIORITY_P2 = "P2"   # held inside the quiet window

FOOTER_DEFAULT = "Open Home on the dashboard."


def batch_text(*, header: str, items: Sequence[Mapping[str, Any]], footer: str | None = None) -> str:
    """ONE message body for every item in this run.

    Each item is a mapping with ``title`` (required) plus optional ``detail``, ``next`` and ``link``.
    Bullets, not paragraphs: the operator reads this on a phone, and the unit of the message is the
    run, never the item — six incidents arriving together must not become six messages.
    """
    lines = [str(header)]
    for it in items:
        title = str(it.get("title") or "").strip()
        if not title:  # a nameless row would render as a bare bullet; skip it rather than confuse
            continue
        lines.append(f"• {title}")
        detail = str(it.get("detail") or "").strip()
        if detail:
            lines.append(f"  {detail}")
        nxt = str(it.get("next") or "").strip()
        if nxt:
            lines.append(f"  Next: {nxt}")
        link = str(it.get("link") or "").strip()
        if link:
            lines.append(f"  {link}")
    if footer:
        lines.append("")
        lines.append(str(footer).strip())
    return "\n".join(lines)


def _parse(ts: Any) -> datetime | None:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class NudgeState:
    """Durable per-key last-nudge ledger (JSON). An unreadable file means "no history", never a crash."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)

    def load(self) -> dict[str, str]:
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        rows = doc.get("last_nudge") if isinstance(doc, dict) else None
        return {str(k): str(v) for k, v in (rows or {}).items() if k and v}

    def save(self, rows: Mapping[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps({"schema": SCHEMA, "last_nudge": dict(rows)}, indent=1, sort_keys=True),
                       encoding="utf-8")
        os.replace(tmp, self.path)

    def note(self, keys: Iterable[str], when: datetime) -> dict[str, str]:
        """Record that these keys were nudged at ``when``; returns the updated ledger (not yet saved)."""
        rows = self.load()
        for key in keys:
            rows[str(key)] = _iso(when)
        return rows

    def due(self, keys: Iterable[str], now: datetime, floor_minutes: int = DEFAULT_FLOOR_MINUTES) -> list[str]:
        """The keys whose last nudge is unknown or at least ``floor_minutes`` old."""
        rows = self.load()
        out: list[str] = []
        for key in keys:
            last = _parse(rows.get(str(key)))
            if last is None or (now - last) >= timedelta(minutes=max(0, int(floor_minutes))):
                out.append(str(key))
        return out


def in_quiet_hours(now: datetime | None = None) -> bool:
    """The operator's quiet window, from the ONE definition in telegram_alert_router (22:00–07:00 ET)."""
    try:
        from telegram_alert_router import intent_in_quiet_hours  # type: ignore -- script-dir import fallback when run without the repo root on sys.path
    except Exception:  # noqa: BLE001 — a missing router must not turn night into day
        return False
    return bool(intent_in_quiet_hours(now))


def nudge_decision(*, keys: Sequence[str], state: NudgeState, now: datetime,
                   priority: str = PRIORITY_P2, floor_minutes: int = DEFAULT_FLOOR_MINUTES,
                   quiet: bool | None = None) -> dict:
    """Decide whether this run may send, and which keys it covers.

    Order of rules (the spec's order): a key is due when it was never nudged or its floor has elapsed;
    a P2 with nothing due sends nothing; inside quiet hours only P1 may send, and a held batch is not
    consumed (its keys stay due, so 07:00 delivers ONE catch-up message).
    ``quiet`` is injectable for tests; production passes None and the router answers.
    """
    due = state.due(keys, now, floor_minutes)
    if not due:
        return {"send": False, "reason": "nothing due", "keys": []}
    pr = str(priority or PRIORITY_P2).strip().upper()
    if pr != PRIORITY_P1 and (in_quiet_hours(now) if quiet is None else bool(quiet)):
        return {"send": False, "reason": "quiet hours: wait for the dashboard, one catch-up batch at 07:00",
                "keys": due, "held": True}
    return {"send": True, "reason": "due", "keys": due, "priority": pr}
