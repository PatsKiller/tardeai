#!/usr/bin/env python3
"""Re-tag the last 30 days of messages that carry no subject_guid.

WHY THIS EXISTS
---------------
Operator, 2026-09-21: "Backfill last 30 days of messages with guids when fixed."

"When fixed" is load-bearing. Running this against the OLD tagger would have
written tens of thousands of wrong identities at scale: `tag_inbound` attempted
ticker-ALIAS resolution with no guard, so "After 17 retries" bound AFTER, "Price
$31.76" bound TROW, and the EOD report's primary subject was OPEN (Opendoor).
This script is therefore deliberately useless until the resolver guard lands --
it calls the SAME tagger the live path calls, so it inherits the fix rather than
reimplementing it.

WHAT IT COVERS
--------------
Measured 2026-09-21 over the trailing 30 days:

  INBOUND   callback_query        168   subject_guid on 0
  INBOUND   telegram_command       84   subject_guid on 0
  OUTBOUND  alert                  80   subject_guid on 0
  OUTBOUND  material_change_notice 76   subject_guid on 0
  OUTBOUND  agent_outbound         16   subject_guid on 2
  OUTBOUND  pipeline_stale/health/symbol_alert/digest   8   subject_guid on 0
                                                      ---
                                          432 events needing identity

plus 6,134 `operator_message` rows whose guid is absent. Those are included only
with --include-operator-messages: they are the highest-volume class and the one
most likely to contain genuine prose, so they are re-tagged separately and
reviewed separately.

WHAT IT DOES NOT DO
-------------------
Never overwrites an existing subject_guid. `WHERE subject_guid IS NULL` is the
only selector, so a re-run cannot rewrite identity already established -- the
same guard tag_outbound_event uses. Idempotent by construction.

It also does not touch narrative_subjects rows that already exist for an event;
write_narrative is responsible for its own de-duplication.

    python scripts/backfill_message_identity.py                    # dry run
    python scripts/backfill_message_identity.py --apply            # execute
    python scripts/backfill_message_identity.py --days 7 --apply   # narrower window

AUTHORITY: OPERATOR_APPROVED. Writes derived identity only. Dry-run first.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

#: operator_message is excluded by default: 6,134 rows, genuine prose, and a
#: different review question from machine templates.
DEFAULT_EXCLUDED = ("operator_message",)


def _scope_sql(days: int, excluded: tuple[str, ...]) -> tuple[str, list]:
    """The shared WHERE clause as literal SQL plus its driver parameters.

    `event_type <> ALL(%s)` matches the old `NOT IN (...)` for every row, NULL event_type included
    (both evaluate to NULL and exclude it).
    """
    sql = ("created_at > now() - %s * interval '1 day' "
           "AND subject_guid IS NULL AND sanitized_body IS NOT NULL")
    params: list = [int(days)]
    if excluded:
        sql += " AND event_type <> ALL(%s)"
        params.append(list(excluded))
    return sql, params


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="execute; without it the script only reports")
    ap.add_argument("--days", type=int, default=30, help="window (default 30)")
    ap.add_argument("--include-operator-messages", action="store_true",
                    help="also re-tag the 6,134 operator_message rows")
    ap.add_argument("--limit", type=int, default=0, help="cap events processed (0 = no cap)")
    args = ap.parse_args()

    from db_adapter import _get_conn  # noqa: PLC0415

    excluded = () if args.include_operator_messages else DEFAULT_EXCLUDED

    conn = _get_conn()
    conn.autocommit = False
    cur = conn.cursor()

    # `scope` is fixed SQL text with %s placeholders; the window and the excluded types travel
    # as driver parameters in `scope_params`, never in the SQL text.
    scope, scope_params = _scope_sql(args.days, excluded)

    cur.execute(  # nosemgrep: tq-py-sql-fstring -- scope is literal SQL from _scope_sql; values are params
        f"SELECT count(*) FROM communication_events WHERE {scope}", scope_params)
    todo = cur.fetchone()[0]
    cur.execute(  # nosemgrep: tq-py-sql-fstring -- scope is literal SQL from _scope_sql; values are params
        f"""SELECT direction, event_type, count(*)
                      FROM communication_events WHERE {scope}
                     GROUP BY 1,2 ORDER BY count(*) DESC""", scope_params)
    breakdown = cur.fetchall()

    print(f"Message identity backfill — trailing {args.days} days")
    print("-" * 64)
    print(f"  events needing a subject_guid : {todo:,}")
    print(f"  operator_message included     : {args.include_operator_messages}")
    for d, et, n in breakdown:
        print(f"    {str(d):<9} {str(et):<24} {n:,}")

    # Show what the CURRENT tagger would produce, so a dry run proves the fix is
    # in place before anything is written.
    from scripts.lib.cio_outbound_identity import subjects_from_tag, tag_text  # noqa: PLC0415

    # The FULL body, exactly as --apply passes it. An earlier version previewed
    # left(sanitized_body, 300) while --apply used the whole column, so the dry
    # run resolved a different subject set than the real run -- ('AI','subject')
    # appeared at 300 chars and vanished at 260. A dry run that does not match
    # the run it previews is worse than no dry run: it is false assurance.
    cur.execute(  # nosemgrep: tq-py-sql-fstring -- scope is literal SQL from _scope_sql; values are params
        f"""SELECT event_id, sanitized_body
                      FROM communication_events WHERE {scope}
                     ORDER BY created_at DESC LIMIT 5""", scope_params)
    print("\n  what the CURRENT tagger resolves on the FULL body (as --apply will):")
    for eid, body in cur.fetchall():
        subs = subjects_from_tag(tag_text(body or ""))
        shown = [(s.get("value"), s.get("relationship")) for s in subs] or "— no subject (correct for boilerplate)"
        print(f"    {str(eid)[:8]}  {shown}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to execute.")
        conn.rollback()
        return 0

    from scripts.lib.cio_outbound_identity import tag_outbound_event  # noqa: PLC0415

    limit_sql = " LIMIT %s" if args.limit else ""
    limit_params = [int(args.limit)] if args.limit else []
    cur.execute(  # nosemgrep: tq-py-sql-fstring -- scope/limit_sql are literal SQL; values are params
        f"""SELECT event_id, sanitized_body FROM communication_events
                     WHERE {scope} ORDER BY created_at DESC{limit_sql}""", scope_params + limit_params)
    rows = cur.fetchall()

    tagged = linked = skipped = failed = 0
    for eid, body in rows:
        try:
            report = tag_outbound_event(cur, str(eid), body or "", author_agent_id="cio")
            n = int(report.get("linked") or 0)
            if n:
                tagged += 1
                linked += n
            else:
                skipped += 1        # no resolvable subject: correct for boilerplate
        except Exception:           # noqa: BLE001 - one bad row must not lose the batch
            failed += 1

    conn.commit()
    print(f"\n  events processed   : {len(rows):,}")
    print(f"  events tagged      : {tagged:,}")
    print(f"  links written      : {linked:,}")
    print(f"  no subject found   : {skipped:,}   (expected for machine templates)")
    print(f"  errors             : {failed:,}")
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
