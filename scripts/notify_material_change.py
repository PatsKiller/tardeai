#!/usr/bin/env python3
"""notify_material_change.py — tell the operator when a tracked name moves.

Stage 2 of docs/architecture/MATERIAL_CHANGE_TO_QUESTIONS.md. Advisory only.

WHY THIS EXISTS
---------------
On 2026-09-05 three watchlist names were up 15-40% and nothing said so. Stage 1 now
detects it — AOUT at 14.93x its own average daily move — but a detector nobody reads
is the same as no detector. This is the part that closes the original complaint, and
it costs nothing: no model is called.

SIGNAL DISCIPLINE
-----------------
Notify on the CHANGE, not on the sweep. This runs on a schedule but only ever speaks
when stage 1 found something new, and each change_guid is announced exactly once. A
detector that fires every fifteen minutes trains the operator to ignore it, and a
muted alarm is worse than no alarm — this system has lost detectors that way before.

DELIVERED IS NOT THE SAME AS ACCEPTED
-------------------------------------
send_telegram returns True when the platform ACCEPTED the event, which is not proof
the operator saw it. On 2026-09-05 two adjacent rows both read LEGACY_DELIVERED and
one had been suppressed by the router. So the outcome is recorded as what was
actually observed, and a change is only marked notified when the send was accepted —
a suppressed alert stays pending rather than being silently consumed.

    python3 scripts/notify_material_change.py            # dry run, prints the message
    python3 scripts/notify_material_change.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SCHEMA = "MaterialChangeNotice@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

#: Operator choice 2026-09-06: market hours. "always" ignores the window.
NOTIFY_WINDOW = os.getenv("MATERIAL_CHANGE_NOTIFY_WINDOW", "market")
MARKET_TZ = ZoneInfo(os.getenv("MATERIAL_CHANGE_TZ", "America/New_York"))
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)

#: Never announce a change older than this. A stale alert is noise, and after a
#: weekend or an outage the backlog would otherwise arrive as a wall of text.
MAX_AGE_HOURS = int(os.getenv("MATERIAL_CHANGE_MAX_AGE_HOURS", "72"))
#: Ceiling per run, so one thrashing name cannot dominate the channel.
MAX_PER_RUN = int(os.getenv("MATERIAL_CHANGE_MAX_PER_RUN", "8"))

#: MaterialChangeNotice@v1 is a send receipt. Its consumer is the operator, who is
#: not a code path — the durable record of what was announced lives on
#: material_changes.notified_at / notify_outcome, which IS read (by this script, to
#: avoid re-announcing). Declared rather than left dark: an undeclared contract is
#: indistinguishable from one whose caller was forgotten.
NO_CONSUMER_REASON = (
    "send receipt; the durable state it stands for is material_changes.notified_at, "
    "which this script reads to guarantee each change is announced exactly once"
)

DDL = """
ALTER TABLE material_changes ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;
ALTER TABLE material_changes ADD COLUMN IF NOT EXISTS notify_outcome TEXT;
"""

KIND_LABEL = {
    "price_excursion": "moved",
    "catalyst_new": "new catalyst",
    "news_burst": "news burst",
}


def _db():
    import psycopg2

    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
    return psycopg2.connect(
        host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"))


def in_window(now: datetime | None = None) -> bool:
    """Market hours in the exchange's timezone, weekdays only.

    Outside the window a change is left PENDING, not dropped — it is announced at
    the next open. Dropping it would mean a Friday-evening move is never mentioned,
    which is the failure this whole feature exists to fix.
    """
    if NOTIFY_WINDOW == "always":
        return True
    n = (now or datetime.now(timezone.utc)).astimezone(MARKET_TZ)
    if n.weekday() >= 5:
        return False
    return MARKET_OPEN <= n.time() <= MARKET_CLOSE


def pending(cur, *, limit: int) -> list[dict]:
    cur.execute(
        """SELECT change_guid, symbol, kind, magnitude, baseline, observed_value,
                  observed_at, universe_reason, subject_guid
             FROM material_changes
            WHERE notified_at IS NULL
              AND observed_at > now() - (%s || ' hours')::interval
            ORDER BY magnitude DESC NULLS LAST
            LIMIT %s""", (MAX_AGE_HOURS, limit))
    cols = ["change_guid", "symbol", "kind", "magnitude", "baseline",
            "observed_value", "observed_at", "universe_reason", "subject_guid"]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def context(cur, subject_guid) -> dict:
    """What we already hold on this name — the orientation an alert needs.

    A bare "AOUT +45%" is a number. "AOUT moved 14.9x its normal daily range, we
    hold 12 articles and 3 catalysts on it, last research was 63 days ago" is the
    beginning of a decision.
    """
    if not subject_guid:
        return {}
    out = {}
    for label, sql in (
        ("articles", "SELECT count(*) FROM news_articles WHERE subject_guid=%s"),
        ("catalysts", "SELECT count(*) FROM catalyst_events WHERE subject_guid=%s"),
    ):
        cur.execute(sql, (subject_guid,))
        out[label] = int(cur.fetchone()[0] or 0)
    cur.execute("""SELECT max(created_at)::date FROM hermes_external_research
                    WHERE subject_guid=%s""", (subject_guid,))
    row = cur.fetchone()
    out["last_research"] = str(row[0]) if row and row[0] else None
    return out


def render(changes: list[dict], ctx: dict[str, dict]) -> str:
    lines = [f"Material change — {len(changes)} tracked name(s)"]
    for c in changes:
        sym, kind = c["symbol"], c["kind"]
        mag = float(c["magnitude"] or 0)
        c_ctx = ctx.get(str(c["subject_guid"]), {})
        if kind == "price_excursion":
            head = (f"{sym}: {float(c['observed_value']):.1f}% — "
                    f"{mag:.1f}x its normal daily move "
                    f"(usual {float(c['baseline']):.1f}%)")
        else:
            head = f"{sym}: {KIND_LABEL.get(kind, kind)} (x{mag:.1f} vs usual)"
        lines.append("\n" + head)
        lines.append(f"  tracked as: {c['universe_reason']}   observed {str(c['observed_at'])[:16]}")
        if c_ctx:
            known = f"  we hold {c_ctx.get('articles', 0)} articles, {c_ctx.get('catalysts', 0)} catalysts"
            known += (f"; last research {c_ctx['last_research']}"
                      if c_ctx.get("last_research") else "; no prior research")
            lines.append(known)
        else:
            # Absence is a fact about our corpus, not about the world.
            lines.append("  no identity match — nothing linked in the corpus yet")
    lines.append("\nAdvisory only. No position action taken or implied.")
    return "\n".join(lines)


def route_check(message: str) -> str:
    """Would the router send THIS message, or suppress it?

    Asked BEFORE sending, on purpose. The first attempt at this asked afterwards by
    reading the most recent communication_deliveries row — but "most recent row" is
    not "the row for my send", and a stale SUPPRESSED row from an earlier attempt
    made a successful send look unknown.

    should_send_telegram() is a pure function of the message and is correlated to
    exactly this text, so there is nothing to mis-attribute. A router that cannot be
    imported is treated as "will send" — that is the legacy path's own behaviour, and
    assuming suppression there would silence every alert on a partial install.
    """
    try:
        from telegram_alert_router import should_send_telegram
    except ImportError:
        return "WILL_SEND"
    return "WILL_SEND" if should_send_telegram(message) else "WOULD_SUPPRESS"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--ignore-window", action="store_true",
                    help="operator-run only; scheduled jobs must respect the window")
    args = ap.parse_args()

    conn = _db()
    cur = conn.cursor()
    # Unconditional, including on a dry run: the columns are additive, nullable and
    # idempotent (ADD COLUMN IF NOT EXISTS), and a dry run that cannot read the same
    # shape the apply path writes is not a rehearsal of anything. Gating this behind
    # --apply made the dry run fail with UndefinedColumn on a clean install.
    cur.execute(DDL)
    conn.commit()

    open_now = args.ignore_window or in_window()
    rows = pending(cur, limit=MAX_PER_RUN)
    ctx = {str(r["subject_guid"]): context(cur, r["subject_guid"]) for r in rows
           if r["subject_guid"]}

    result = {"schema": SCHEMA, "authority": AUTHORITY, "model_calls": 0,
              "pending": len(rows), "in_window": open_now,
              # None when nothing was attempted; 0 is a measured zero.
              "rows_produced": None, "outcome": None}

    if not rows:
        result["rows_produced"] = 0 if args.apply else None
        print(f"{SCHEMA}: nothing pending")
        print("RESULT: " + json.dumps(result))
        return 0

    message = render(rows, ctx)
    print(message)
    if not open_now:
        # Held, not dropped. A Friday-evening move must still be announced Monday.
        print(f"\n[held — outside the {NOTIFY_WINDOW} window; stays pending]")
        result["outcome"] = "HELD_OUTSIDE_WINDOW"
        print("RESULT: " + json.dumps(result))
        return 0
    if not args.apply:
        print("\n[dry run — nothing sent, nothing marked]")
        print("RESULT: " + json.dumps(result))
        return 0

    routed = route_check(message)
    if routed == "WOULD_SUPPRESS":
        # Do not send into a suppression, and above all do not consume the changes.
        # On the first live run the send was ACCEPTED, the router suppressed it into
        # the 8pm digest, and three changes were marked notified while the operator
        # received nothing. Consumed-and-silent is the worst outcome available here:
        # the row is gone and the silence looks normal.
        result["outcome"] = "WOULD_SUPPRESS"
        result["rows_produced"] = 0
        print("router would suppress this message — left pending, not sent",
              file=sys.stderr)
        conn.close()
        print("RESULT: " + json.dumps(result))
        return 0

    from telegram_alert import send_telegram

    accepted = bool(send_telegram(message, message_class="operator_alert"))
    result["outcome"] = "SENT" if accepted else "NOT_ACCEPTED"
    if accepted:
        cur.execute("""UPDATE material_changes
                          SET notified_at = now(), notify_outcome = %s
                        WHERE change_guid = ANY(%s::uuid[])""",
                    ("SENT", [str(r["change_guid"]) for r in rows]))
        result["rows_produced"] = cur.rowcount
        conn.commit()
    else:
        result["rows_produced"] = 0
        print("send not accepted — changes left pending for the next run",
              file=sys.stderr)
    conn.close()
    print("RESULT: " + json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
