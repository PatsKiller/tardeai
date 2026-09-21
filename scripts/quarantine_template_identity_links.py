#!/usr/bin/env python3
"""Quarantine identity links minted from machine-template boilerplate.

WHAT HAPPENED
-------------
`inbound_identity_tagger.tag_inbound` attempts ticker-ALIAS resolution before any
guard runs: `RI.resolve(doc, name)` at :255 is unguarded, while `_is_generic_term`
protects only the company-name fallback on the next line. A capitalised ordinary
word that is also a real ticker therefore binds an issuer.

`claude_escalation_handler.py:725` emits, every ten minutes, for each exhausted
component:

    ⚠️ AUTO-RETRY PAUSED (will re-arm): health:pipeline_freshness:<component>
    <detail>
    After <n> retries; autonomous re-arm in 30m.

The closing sentence begins "After", which resolves to AFTER (a real ticker) via
matched_via="ticker_alias" and is recorded as the message's PRIMARY subject.

Measured 2026-09-21 on the live spine:

  narrative_subjects links from communication_events .......... 77,667
  links whose source event body contains AUTO-RETRY PAUSED .... 44,665  (57.5%)
  distinct source events ...................................... 36,801
  AFTER as relationship='subject' ............................. 28,950
  communication_events with a subject_guid stamped ............ 36,801

Real tickers incidentally caught by the same predicate: CC, NKE, PFSI, PRIM —
one row each, four rows total. They are archived too, and the reversal below
restores them.

WHAT THIS DOES
--------------
Nothing is deleted from the live spine without a verified archive first, and the
event rows are never deleted at all.

  1. Copies every affected narrative_subjects row, whole and unmodified, into
     narrative_subjects_quarantine_20260921.
  2. Refuses to proceed unless the archive holds at least as many rows as are
     affected.
  3. Removes those links from narrative_subjects — the whole row IS the false
     claim here, so there is no derived column to null, unlike the analyst-rating
     precedent this follows.
  4. On communication_events, NULLs ONLY the derived subject_guid on those same
     events. The event, its body, its idempotency key and its deliveries are
     untouched — subject_guid is the only fabricated field.
  5. Leaves a tripwire view that fires if template-word links reappear.

REVERSAL
--------
    INSERT INTO narrative_subjects
    SELECT link_guid, row_guid, source_table, source_id, entity_type,
           subject_guid, semantic_subject, relationship, confidence,
           author_agent_id, schema_version, created_at
      FROM narrative_subjects_quarantine_20260921
     WHERE NOT EXISTS (SELECT 1 FROM narrative_subjects n
                        WHERE n.link_guid = narrative_subjects_quarantine_20260921.link_guid);

The event-side subject_guid is recoverable from the archived links by joining
source_id -> event_id on relationship='subject'.

NOT FIXED HERE
--------------
This repairs written rows. It does not stop new ones: the resolver guard and the
escalation-handler notify loop are separate changes, and this script is
deliberately idempotent so it can be re-run after they land.

    python scripts/quarantine_template_identity_links.py            # dry run
    python scripts/quarantine_template_identity_links.py --apply    # execute

AUTHORITY: OPERATOR_APPROVED. Destructive to derived identity only; approved
2026-09-21. Never run without --apply having been reviewed in a dry run first.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

QUARANTINE_TABLE = "narrative_subjects_quarantine_20260921"

#: The source-event predicate. Deliberately keyed on the TEMPLATE, not on a list
#: of symbols: a symbol list would sweep genuine mentions of AFTER or DB, while
#: the template is provably machine-generated boilerplate.
AFFECTED_EVENTS = "e.sanitized_body LIKE '%AUTO-RETRY PAUSED%'"

LINK_PREDICATE = f"""
    ns.source_table = 'communication_events'
    AND EXISTS (SELECT 1 FROM communication_events e
                 WHERE e.event_id = ns.source_id AND {AFFECTED_EVENTS})
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="execute; without it the script only reports")
    args = ap.parse_args()

    # db_adapter, not a hand-rolled psycopg2 connection: the env vars in a shell
    # are not the credentials the platform uses. A raw connect() here fails with
    # `password authentication failed for user "trade_ai"` -- the same defect that
    # produced 184,050 silent failures in active_trader_motion.
    from db_adapter import _get_conn  # noqa: PLC0415

    conn = _get_conn()
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute(f"SELECT count(*) FROM narrative_subjects ns WHERE {LINK_PREDICATE}")
    affected = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM narrative_subjects WHERE source_table='communication_events'")
    total = cur.fetchone()[0]
    cur.execute(f"""SELECT count(DISTINCT ns.source_id) FROM narrative_subjects ns
                     WHERE {LINK_PREDICATE}""")
    events = cur.fetchone()[0]
    cur.execute(f"""SELECT count(*) FROM communication_events e
                     WHERE {AFFECTED_EVENTS} AND subject_guid IS NOT NULL""")
    stamped = cur.fetchone()[0]

    print("Template-boilerplate identity links — quarantine")
    print("-" * 64)
    print(f"  comms links in spine   : {total:,}")
    print(f"  affected links         : {affected:,}  ({100.0 * affected / max(total, 1):.1f}%)")
    print(f"  distinct source events : {events:,}")
    print(f"  events with subject_guid: {stamped:,}  (NULLed; body untouched)")
    print(f"  quarantine table       : {QUARANTINE_TABLE}")

    cur.execute(f"""SELECT ns.semantic_subject, ns.relationship, count(*)
                      FROM narrative_subjects ns WHERE {LINK_PREDICATE}
                     GROUP BY 1,2 ORDER BY count(*) DESC LIMIT 10""")
    print("\n  what would be quarantined:")
    for sym, rel, n in cur.fetchall():
        print(f"    {str(sym):<8} {str(rel):<10} {n:,}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to execute.")
        conn.rollback()
        return 0

    try:
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {QUARANTINE_TABLE} "
            f"(LIKE narrative_subjects INCLUDING DEFAULTS)"
        )
        cur.execute(
            f"INSERT INTO {QUARANTINE_TABLE} "
            f"SELECT ns.* FROM narrative_subjects ns "
            f"WHERE {LINK_PREDICATE} "
            f"  AND NOT EXISTS (SELECT 1 FROM {QUARANTINE_TABLE} q "
            f"                   WHERE q.link_guid = ns.link_guid)"
        )
        archived = cur.rowcount

        cur.execute(f"SELECT count(*) FROM {QUARANTINE_TABLE}")
        held = cur.fetchone()[0]
        if held < affected:
            raise RuntimeError(
                f"archive holds {held:,} rows but {affected:,} are affected — "
                f"refusing to remove the live links"
            )

        cur.execute(
            f"DELETE FROM narrative_subjects ns WHERE {LINK_PREDICATE} "
            f"  AND EXISTS (SELECT 1 FROM {QUARANTINE_TABLE} q "
            f"               WHERE q.link_guid = ns.link_guid)"
        )
        removed = cur.rowcount

        cur.execute(
            f"UPDATE communication_events e SET subject_guid = NULL "
            f"WHERE {AFFECTED_EVENTS} AND subject_guid IS NOT NULL"
        )
        unstamped = cur.rowcount

        cur.execute(
            "CREATE OR REPLACE VIEW narrative_template_word_tripwire AS "
            "SELECT semantic_subject, count(*) AS links, max(created_at) AS newest "
            "  FROM narrative_subjects "
            " WHERE source_table = 'communication_events' "
            "   AND semantic_subject IN "
            "       ('AFTER','PRICE','QUOTE','LIVE','ALERT','MOVE','DATA','CHECK',"
            "        'GAP','WENT','NONE','OPEN','DOWN','ET','P','L') "
            " GROUP BY 1"
        )

        conn.commit()
        print(f"\n  archived           : {archived:,} rows (table now holds {held:,})")
        print(f"  links removed      : {removed:,}")
        print(f"  subject_guid NULLed: {unstamped:,} events")
        print("  tripwire view      : narrative_template_word_tripwire")
        return 0
    except Exception as exc:  # noqa: BLE001 - report and roll back, never half-apply
        conn.rollback()
        print(f"\n  ROLLED BACK: {type(exc).__name__}: {exc}")
        return 1
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
