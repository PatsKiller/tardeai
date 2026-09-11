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

#: ALWAYS. Operator decision 2026-09-07, overriding the market-hours default set the
#: day before: "it's Monday morning now and that has no bearing on it, I should be
#: receiving it no matter what day of the week."
#:
#: The market-hours window was wrong in practice. AOUT burst at 07:13 and SPCX at
#: 16:41 — both outside it — and 36 consecutive notifier runs reported
#: HELD_OUTSIDE_WINDOW while the operator saw nothing and reasonably concluded the
#: layer was dark. News does not wait for the opening bell, and a detector whose
#: output is invisible for sixteen hours a day is indistinguishable from one that is
#: not running.
#:
#: Set to "market" to restore weekday 09:30-16:00 gating.
NOTIFY_WINDOW = os.getenv("MATERIAL_CHANGE_NOTIFY_WINDOW", "always")
MARKET_TZ = ZoneInfo(os.getenv("MATERIAL_CHANGE_TZ", "America/New_York"))
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)

#: Never announce a change older than this. A stale alert is noise, and after a
#: weekend or an outage the backlog would otherwise arrive as a wall of text.
MAX_AGE_HOURS = int(os.getenv("MATERIAL_CHANGE_MAX_AGE_HOURS", "72"))

#: Route this notice through the comms gateway instead of the legacy chokepoint.
#: OFF by default. The gateway additionally requires COMMS_GATEWAY_MODE=CANARY
#: (or ACTIVE) and the message class to be in COMMS_GATEWAY_CANARY_CLASSES, so
#: three independent switches must agree before a single message changes path.
GATEWAY_NOTICE_FLAG = "MATERIAL_CHANGE_GATEWAY_NOTICE"


def gateway_notice_enabled(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(GATEWAY_NOTICE_FLAG, "")).strip().lower() in {"1", "true", "yes", "on"}
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
                  observed_at, universe_reason, subject_guid, evidence_json
             FROM material_changes
            WHERE notified_at IS NULL
              AND observed_at > now() - (%s || ' hours')::interval
            ORDER BY magnitude DESC NULLS LAST
            LIMIT %s""", (MAX_AGE_HOURS, limit))
    cols = ["change_guid", "symbol", "kind", "magnitude", "baseline",
            "observed_value", "observed_at", "universe_reason", "subject_guid",
            "evidence_json"]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def context(cur, change: dict) -> dict:
    """WHAT HAPPENED and WHAT IT MEANS — not how many rows we hold.

    The first version of this alert reported "we hold 212 articles, 209 catalysts".
    That is internal plumbing on the operator's phone: it says nothing about the
    company, nothing about what changed, and nothing about what to do. The operator's
    verdict was correct — "what am I supposed to do with these".

    So this returns, in order of preference:
      1. the NARRATIVE the curation step already wrote — plain sentences, grounded in
         cited evidence, e.g. "shares surged 25.47% after hours on better-than-
         expected Q2 sales"
      2. the questions it decided were worth asking
      3. failing both, the actual HEADLINE that triggered it
    """
    sg = change.get("subject_guid")
    out: dict = {}

    cur.execute("""SELECT sentences FROM subject_state_narratives
                    WHERE change_guid = %s ORDER BY created_at DESC LIMIT 1""",
                (change["change_guid"],))
    row = cur.fetchone()
    if row and row[0]:
        payload = row[0] if isinstance(row[0], list) else json.loads(row[0])
        out["narrative"] = [n.get("sentence") for n in payload if n.get("sentence")]

    cur.execute("""SELECT question FROM due_diligence_questions
                    WHERE change_guid = %s ORDER BY created_at LIMIT 2""",
                (change["change_guid"],))
    out["questions"] = [r[0] for r in cur.fetchall()]

    # The raw trigger, for when curation has not run yet.
    ev = change.get("evidence_json") or {}
    if isinstance(ev, str):
        try:
            ev = json.loads(ev)
        except Exception:  # noqa: BLE001
            ev = {}
    rng = ev.get("id_range")
    if not out.get("narrative") and rng:
        cur.execute("""SELECT headline FROM catalyst_events
                        WHERE id BETWEEN %s AND %s AND symbol = %s
                          AND headline IS NOT NULL
                        ORDER BY published_at DESC LIMIT 1""",
                    (rng[0], rng[1], change["symbol"]))
        r = cur.fetchone()
        if r:
            out["headline"] = r[0]
    if not out.get("narrative") and not out.get("headline") and sg:
        cur.execute("""SELECT title FROM news_articles
                        WHERE subject_guid = %s AND title IS NOT NULL
                        ORDER BY published_at DESC LIMIT 1""", (sg,))
        r = cur.fetchone()
        if r:
            out["headline"] = r[0]

    if sg:
        cur.execute("""SELECT max(created_at)::date FROM hermes_external_research
                        WHERE subject_guid = %s""", (sg,))
        r = cur.fetchone()
        out["last_research"] = str(r[0]) if r and r[0] else None
    return out


def dedupe_by_symbol(changes: list[dict]) -> list[dict]:
    """One line per SYMBOL, strongest signal wins.

    The 2026-09-07 queue listed AOUT twice (two news bursts hours apart) and SPCX
    twice. A name appearing repeatedly in one alert is not more informative — it is
    harder to read, and it crowds out the other names.
    """
    best: dict[str, dict] = {}
    for c in changes:
        sym = c["symbol"]
        cur = best.get(sym)
        if cur is None or (c.get("magnitude") or 0) > (cur.get("magnitude") or 0):
            c = dict(c)
            c["also"] = (cur or {}).get("also", 0) + (1 if cur else 0)
            best[sym] = c
        else:
            cur["also"] = cur.get("also", 0) + 1
    return sorted(best.values(),
                  key=lambda x: (-(x.get("precedence") or 0), -(x.get("magnitude") or 0)))


#: What the magnitude means, in words. "x1.2 vs usual" is noise dressed as signal.
def _headline_line(c: dict) -> str:
    sym, kind = c["symbol"], c["kind"]
    mag = float(c["magnitude"] or 0)
    if kind == "price_excursion":
        return (f"{sym} — moved {float(c['observed_value']):.0f}%, "
                f"{mag:.0f}x its normal daily range")
    if kind == "news_burst":
        return f"{sym} — unusual news volume, {mag:.0f}x normal"
    if kind == "sector_move":
        return f"{sym} — sector-wide move"
    ev = c.get("evidence") or {}
    ctype = str(ev.get("catalyst_type") or "").replace("_", " ")
    return f"{sym} — {ctype or 'new catalyst'}"


def render(changes: list[dict], ctx: dict[str, dict]) -> str:
    changes = dedupe_by_symbol(changes)
    lines = [f"Material change — {len(changes)} name(s) worth a look"]
    for c in changes:
        info = ctx.get(str(c["change_guid"]), {})
        lines.append("\n" + _headline_line(c))

        # WHAT HAPPENED. The narrative if we have one, else the actual headline.
        if info.get("narrative"):
            for sentence in info["narrative"][:2]:
                lines.append(f"  {sentence}")
        elif info.get("headline"):
            lines.append(f"  {info['headline'][:150]}")

        # WHY IT IS IN FRONT OF YOU.
        tier = c.get("universe_reason", "")
        why = ("you hold this" if "held" in tier else
               "you asked about this" if "operator" in tier else
               "re-entry candidate" if "reentry" in tier else "on your watchlist")
        if "operator" in tier:
            why = "you asked about this"
        lines.append(f"  · {why}")

        # WHAT TO DO. Never advice — the open question, or the absence of research.
        if info.get("questions"):
            lines.append(f"  · open question: {info['questions'][0]}")
        elif not info.get("last_research"):
            lines.append("  · never researched — questions are being generated now")
        else:
            lines.append(f"  · last researched {info['last_research']}")
    lines.append("\nAdvisory only. No position action taken or implied.")
    return "\n".join(lines)


def route_check(message: str) -> str:
    """Would the router send THIS message, or suppress it?

    Asked BEFORE sending, on purpose. An earlier version asked afterwards by reading
    the most recent communication_deliveries row — but "most recent row" is not "the
    row for my send", and a stale SUPPRESSED row made a successful send look unknown.

    should_send_telegram() is a pure function of the message, correlated to exactly
    this text, so there is nothing to mis-attribute. A router that cannot be imported
    is treated as "will send" — that is the legacy path's own behaviour, and assuming
    suppression there would silence every alert on a partial install.
    """
    try:
        from telegram_alert_router import should_send_telegram
    except ImportError:
        return "WILL_SEND"
    return "WILL_SEND" if should_send_telegram(message) else "WOULD_SUPPRESS"


def deliver_notice(message: str, *, subject_key: str) -> tuple[bool, dict]:
    """Send one operator notice. Returns (accepted, gateway_report).

    Extracted from main() so the alarm can be FIRED by a test. An alarm that has
    never been observed firing is indistinguishable from no alarm, and this
    file's send had no firing test at all.

    Delivery owner: legacy by default, gateway when explicitly enabled.

    Every gateway-SETTLED row that has ever existed (3, all-time) is a staged
    proof message asking the operator to reply "OK". Those are controlled
    evidence and are excluded from acceptance, so the gateway has never carried
    an organic producer. This is that producer, and it is a real one: the notice
    is assembled from material_changes the detector actually found, not from an
    event invented to move a counter.
    """
    if not gateway_notice_enabled():
        from telegram_alert import send_telegram

        return bool(send_telegram(message, message_class="operator_alert")), {"attempted": False}

    from scripts.lib.comms.channel_adapters import send_via_gateway

    gw = send_via_gateway(
        "telegram",
        body=message,
        producer="notify_material_change",
        subject_key=subject_key,
        event_type="material_change_notice",
        message_class="operator_alert",
        retention_class="operational_30d",
        deliver=True,
        severity="info",
    )
    # SENT IS NOT SETTLED. `delivered` means the gateway owned the send and the
    # provider acknowledged it; `ok` can be true for a publish merely recorded,
    # and a reservation is not a delivery.
    accepted = bool(gw.get("delivered"))
    report = {
        "attempted": True,
        "delivered": accepted,
        "delivery_owned": bool(gw.get("delivery_owned")),
        "gateway_mode": gw.get("gateway_mode"),
        "event_id": gw.get("event_id"),
        "delivery_id": gw.get("delivery_id"),
        "errors": gw.get("errors") or ([gw["error"]] if gw.get("error") else []),
    }
    if not accepted:
        # Do NOT silently fall back to legacy. A gateway failure that quietly
        # succeeded as legacy would report SENT, consume the rows, and leave the
        # gateway counter at zero with nothing to explain why.
        print(f"gateway did not deliver ({report['errors']}) — "
              "changes left pending, no legacy fallback", file=sys.stderr)
    return accepted, report


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
    ctx = {str(r["change_guid"]): context(cur, r) for r in rows}

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

    # Delivery owner: legacy by default, gateway when explicitly enabled.
    #
    # Every gateway-SETTLED row that has ever existed (3, all-time) is a staged
    # proof message asking the operator to reply "OK". Those are controlled
    # evidence and are excluded from acceptance, so the gateway has never carried
    # an organic producer. This is that producer — and it is a real one: the
    # notice below is assembled from material_changes the detector actually
    # found, not from an event invented to move a counter.
    #
    # The flag defaults OFF and rollback needs no deploy: unset it and the very
    # next 15-minute run goes back down the legacy path.
    accepted, gw_result = deliver_notice(message, subject_key=str(
        rows[0].get("subject_guid") or rows[0]["change_guid"]))
    result["gateway"] = gw_result
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
