#!/usr/bin/env python3
"""Deliver the P1_DIGEST tier. Without this, classifying a message digests it away.

THE GAP THIS CLOSES. telegram_alert_router classifies operator messages into
P0_INTERRUPT / P1_DIGEST / P2_DASHBOARD_ONLY / P3_LOG_ONLY. A P1_DIGEST verdict makes
_legacy_send archive the message to telegram_outbox with channel='reports_archive'
and return False. Those rows are readable -- reports_portal surfaces them in the v3
Reports portal -- but nothing PUSHES them: the only active digest cron,
alert_daily_digest, reads the alert_events table, a different store. So "digest" has
meant "archived to a pull surface nobody was watching".

Measured 2026-08-31: 4,387 rows archived since 2026-07-02 against 1,707 delivered.
Two alarms were confirmed silent this way -- the signal-flow CRITICAL that hid a
24-day outage, and system_health_agent's AGENT STALENESS / PIPELINE HEALTH.

    python3 scripts/p1_digest_sender.py                 # dry run, prints the digest
    python3 scripts/p1_digest_sender.py --send          # deliver, then advance
    python3 scripts/p1_digest_sender.py --since-hours 6

DELIVERY BYPASSES THE ROUTER, DELIBERATELY. A digest OF suppressed messages that is
itself routed would be classified and suppressed in turn. That is not a hypothetical
loop: it is the same mechanism that swallowed its contents.

Read-only against the outbox. It never deletes or rewrites a row; the watermark is a
separate state file, so a bad run loses nothing and can be replayed.
"""
from __future__ import annotations

NO_CONSUMER_REASON = (
    "P1 digest delivery. The schedule is PROPOSED, not installed -- cron and systemd "
    "are operator-only -- so this contract has no scheduled caller by design and not "
    "by omission. Invoked today by the operator CLI and by tests/test_p1_digest_sender.py."
)

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

def _default_state_path() -> Path:
    """Shared persistent state, NOT a path relative to this checkout.

    THIS DEFAULT WAS TREE-RELATIVE AND IT RE-SENT A DIGEST. The job ran once from
    the deploy worktree (watermark -> 6159) and once from the hub, which had no
    watermark of its own, so it started at 0 and delivered 33 messages the operator
    had already received. Two files, one job:

        <deploy>/data/runtime/p1_digest_watermark.json   last_id 6159
        <hub>/data/runtime/p1_digest_watermark.json      last_id 6159

    Same class as the release-local logs/ and the two holdings copies: state keyed
    to a checkout diverges the moment a second checkout runs the same job. A
    watermark is exactly-once bookkeeping, so a per-tree copy is not a cache -- it
    is a duplicate delivery.

    Falls back to the checkout only when the shared root is absent, so tests and
    fresh clones still work.
    """
    shared = Path("/home/johnclaw/trade-ai-releases/persistent-state/state")
    if shared.is_dir():
        return shared / "p1_digest_watermark.json"
    return ROOT / "data" / "runtime" / "p1_digest_watermark.json"


# NOT `Path(os.environ.get(...)) or _default()`: Path("") is Path("."), which is
# TRUTHY, so that form silently resolves the watermark to the current directory.
_STATE_ENV = os.environ.get("P1_DIGEST_STATE", "").strip()
STATE = Path(_STATE_ENV) if _STATE_ENV else _default_state_path()

MAX_LINES = 25          # a digest longer than this is a wall, not a report
MAX_BODY = 3000         # keep well inside the transport's split threshold
DEFAULT_WINDOW_H = 24


_TAG = re.compile(r"<[^>]{1,40}>")


def _safe(text: str) -> str:
    """Neutralise a foreign producer's markup before embedding it.

    THE FIRST LIVE SEND FAILED ON THIS. The digest quotes other producers' titles
    verbatim, and those titles carry their own markup -- `<b>Health Agent...</b>`
    from an HTML producer, `*Trade AI v12.1d [0900]*` from a Markdown one. Telegram
    parsed the digest as Markdown, rejected it with a 400, and it arrived only via
    the plaintext fallback: two API calls per chat instead of one.

    An embedded title is DATA, not markup. HTML tags are stripped (they are another
    producer's parse_mode and mean nothing here) and the remainder goes through the
    shared escaper rather than a 127th private convention.
    """
    try:
        from telegram_transport import escape_markdown
    except Exception:                      # transport unavailable: strip, never trust
        return _TAG.sub("", text or "")
    return escape_markdown(_TAG.sub("", text or ""))


def _db_query(sql, params=None):
    from db_adapter import get_connection
    cur = get_connection().cursor()
    cur.execute(sql, params or [])
    return cur.fetchall()


def read_watermark() -> int:
    """Last delivered outbox id. 0 means "never run".

    A first run with a 0 watermark would page the entire 4,387-row backlog, so the
    window is bounded by time as well and the caller must ask for more explicitly.
    """
    try:
        return int(json.loads(STATE.read_text(encoding="utf-8")).get("last_id", 0))
    except Exception:
        return 0


def write_watermark(last_id: int, sent: int) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({
        "last_id": int(last_id),
        "delivered_count": int(sent),
        "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }, indent=2) + "\n", encoding="utf-8")


def collect(since_hours: int = DEFAULT_WINDOW_H, query=None) -> dict:
    q = query or _db_query
    watermark = read_watermark()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    rows = q(
        "SELECT id, sent_at, report_type, title, body FROM telegram_outbox "
        "WHERE channel = 'reports_archive' AND id > %s AND sent_at > %s "
        "ORDER BY id",
        [watermark, cutoff],
    ) or []
    return {"watermark": watermark, "since_hours": since_hours, "rows": rows}


def render(collected: dict) -> str:
    """Aggregate by cause with a count. Never a truncated list of the first N.

    A digest that shows five lines because the query said LIMIT 5 reports the query,
    not the system. Group, count, and say how many were folded.
    """
    rows = collected["rows"]
    if not rows:
        return ""
    kinds = Counter((r[2] or "unclassified") for r in rows)
    head = (f"📋 P1 digest — {len(rows)} suppressed message"
            f"{'s' if len(rows) != 1 else ''} in the last "
            f"{collected['since_hours']}h")
    lines = [head, ""]
    for kind, n in kinds.most_common(MAX_LINES):
        newest = max((r for r in rows if (r[2] or "unclassified") == kind),
                     key=lambda r: r[0])
        title = (newest[3] or (newest[4] or "")[:80] or "—").strip().splitlines()[0]
        lines.append(f"• {_safe(kind)} ×{n} — {_safe(title[:90])}")
    if len(kinds) > MAX_LINES:
        lines.append(f"…and {len(kinds) - MAX_LINES} more kinds")
    lines.append("")
    lines.append("Full text: v3 Reports portal (telegram_outbox, channel=reports_archive)")
    out = "\n".join(lines)
    return out[:MAX_BODY]


def deliver(text: str) -> bool:
    # bypass_router=True: a digest of suppressed messages must not itself be routed,
    # or it is classified and suppressed by the mechanism it exists to drain.
    from telegram_alert import send_telegram
    return bool(send_telegram(text, bypass_router=True))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="deliver (default is a dry run)")
    ap.add_argument("--since-hours", type=int, default=DEFAULT_WINDOW_H)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    collected = collect(args.since_hours)
    text = render(collected)
    if args.json:
        print(json.dumps({"pending": len(collected["rows"]),
                          "watermark": collected["watermark"],
                          "would_send": bool(text)}, indent=2))
    if not text:
        if not args.json:
            print("nothing to digest")
        return 0
    if not args.send:
        if not args.json:
            print("--- DRY RUN, nothing sent ---")
            print(text)
        return 0
    if not deliver(text):
        print("P1 DIGEST NOT DELIVERED — watermark NOT advanced, nothing lost", file=sys.stderr)
        return 1
    # Advance ONLY after a confirmed send. Advancing first would silently drop the
    # batch on a failed delivery -- the failure mode this whole exercise is about.
    write_watermark(max(r[0] for r in collected["rows"]), len(collected["rows"]))
    print(f"delivered {len(collected['rows'])} suppressed messages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
