#!/usr/bin/env python3
"""archive_duplicate_calibration_events.py — one survivor per (recommendation_id, scoring_window).

LQ-20261107-1032. Before 2026-11-08 ``agent_calibration_engine.py`` minted a random
``ACE_<UTC stamp>_<nonce>`` per row, so every weekly run inserted the same recommendations
again. Measured DB read-only on 2026-11-08 12:20 ET:

    agent_calibration_events          49,106 rows
    distinct (rec, scoring_window)     7,849 pairs        -> 6,411 groups hold 41,257 rows
    eligible 90-day set               73,525 joined rows   (7,038 distinct recommendations)

The engine now derives the event id from that pair (``scripts/lib/calibration_keys.py``), so it
never adds a second row for a pair it already scored. The rows the old code wrote stay, and
``agent_calibration_windows.recommendations`` counts rows — a duplicated group inflates the tier
evidence of the agent who emitted it. This script is the one-time cleanup for those rows.

ORDER OF OPERATIONS (the engine half first, this half second):
    1. deploy the fixed engine and let one run write its row for each pair;
    2. run this script --dry-run, read the counts and `groups_without_natural_key_row`;
    3. run --apply --confirm APPLY.
Step 1 first, because the survivor of a group is its NEWEST row — the fixed engine's row, which
is the one next week's run will update. If `groups_without_natural_key_row` is non-zero on a real
set, some group's newest row is a legacy row (that pair left the 90-day window before the fixed
engine ran); archiving the rest still leaves exactly one row, and the report says how many.

Archive, never delete (AGENTS.md §0 rule 6): each batch is written through
``scripts/lib/retention_archive.py`` to
``$TRADEAI_STATE_ROOT/archive/db_retention/agent_calibration_events/<stamp>-<label>-bNNNN.jsonl.gz``
with a ``RetentionArchiveManifest@v1`` sidecar and a ``RetentionArchiveTripwire@v1`` record,
re-read from disk and verified, and only then deleted in the same transaction. A failed verify
rolls the batch back.

Usage:
    python3 scripts/archive_duplicate_calibration_events.py                 # dry run (default)
    python3 scripts/archive_duplicate_calibration_events.py --json
    python3 scripts/archive_duplicate_calibration_events.py --apply --confirm APPLY
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# No import-time load_dotenv(PROJECT_ROOT/".env") -- session13_db.get_conn() runs the sanctioned
# env_bootstrap.load_env(), whose render-first order an earlier disk load would defeat (see the
# note in agent_calibration_engine.py; that ordering cost an empty dry run on 2026-11-08).
from lib import calibration_keys  # noqa: E402

TABLE = "agent_calibration_events"
LABEL = "duplicate-groups"
WRITER = "archive_duplicate_calibration_events"

#: Every row of a group except its newest one. A singleton group has exactly one row and that
#: row is the DISTINCT ON winner, so it is never selected: groups with one row are untouched.
#: The predicate is constant SQL (no user value), which is what retention_archive expects of
#: ``where_sql``: it runs under the table alias ``t``.
DUPLICATE_PREDICATE = """
    t.id NOT IN (
        SELECT DISTINCT ON (recommendation_id, COALESCE(scoring_window, '')) id
        FROM agent_calibration_events
        ORDER BY recommendation_id, COALESCE(scoring_window, ''),
                 created_at DESC NULLS LAST, id DESC
    )
"""

GROUP_SQL = """
    SELECT recommendation_id, COALESCE(scoring_window, '') AS scoring_window, count(*) AS n
    FROM agent_calibration_events
    GROUP BY 1, 2
    HAVING count(*) > 1
"""


def _retention_archive():
    from lib import retention_archive
    return retention_archive


def _get_conn():
    from session13_db import get_conn
    return get_conn()


def duplicate_groups(conn):
    """[(recommendation_id, scoring_window, rows)] for every group holding more than one row."""
    cur = conn.cursor()
    try:
        cur.execute(GROUP_SQL)
        return [(r[0], r[1], int(r[2])) for r in cur.fetchall()]
    finally:
        cur.close()


def groups_without_natural_key_row(conn, groups):
    """How many groups already hold the row the fixed engine will update (its natural-key id).

    Zero means the engine half ran first and every survivor is the row next week's run touches.
    """
    if not groups:
        return 0
    expected = {calibration_keys.event_key(rec, window) for rec, window, _n in groups}
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT calibration_event_id FROM agent_calibration_events WHERE calibration_event_id = ANY(%s)",
            (sorted(expected),))
        present = {r[0] for r in cur.fetchall()}
    finally:
        cur.close()
    return len(expected) - len(present)


def survey(conn):
    """Read-only counts: what exists, what a run would archive, where it would land."""
    ra = _retention_archive()
    groups = duplicate_groups(conn)
    rows_in_groups = sum(n for _rec, _win, n in groups)
    est = ra.estimate(conn, table=TABLE, where_sql=DUPLICATE_PREDICATE, key="id")
    cur = conn.cursor()
    try:
        cur.execute("SELECT count(*) FROM agent_calibration_events")
        total = int(cur.fetchone()[0])
    finally:
        cur.close()
    expected_rows = rows_in_groups - len(groups)
    out = {
        "table": TABLE,
        "rows_total": total,
        "duplicate_groups": len(groups),
        "rows_in_duplicate_groups": rows_in_groups,
        "rows_to_archive": est["rows"],
        "rows_kept": total - est["rows"],
        "rows_to_archive_expected": expected_rows,
        "predicate_matches_groups": est["rows"] == expected_rows,
        "groups_without_natural_key_row": groups_without_natural_key_row(conn, groups),
        "survivor_rule": "newest row of the group (created_at DESC, id DESC)",
        "archive_dir": str(ra.archive_root() / TABLE),
        "stored_bytes": est["stored_bytes"],
        "est_archive_bytes": est["est_archive_bytes"],
    }
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Archive every duplicate calibration event except the survivor of its group")
    parser.add_argument("--dry-run", action="store_true", help="report only (this is the default)")
    parser.add_argument("--apply", action="store_true",
                        help="archive then delete the duplicates (needs --confirm APPLY)")
    parser.add_argument("--confirm", metavar="WORD",
                        help="must be APPLY with --apply")
    parser.add_argument("--batch-rows", type=int, default=2000,
                        help="rows per verified archive batch (default 2000)")
    parser.add_argument("--max-rows", type=int, default=0,
                        help="stop after this many rows (0 = every duplicate)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    apply_mode = bool(args.apply)
    if apply_mode and (args.confirm or "").strip().upper() != "APPLY":
        print("refused: --apply needs --confirm APPLY (this is the operator's gate)", file=sys.stderr)
        return 2
    if apply_mode and args.batch_rows <= 0:
        print("refused: --batch-rows must be positive", file=sys.stderr)
        return 2

    conn = _get_conn()
    ra = _retention_archive()
    try:
        if not apply_mode:
            from lib.lane_last_receipt import enforce_readonly
            enforce_readonly(conn)
            out = {"mode": "dry_run", **survey(conn)}
            out["would_write"] = {"archive_batches": "one .jsonl.gz per batch",
                                  "rows_archived": out["rows_to_archive"],
                                  "rows_deleted_after_verify": out["rows_to_archive"]}
            if args.json:
                print(json.dumps(out, indent=2, default=str, sort_keys=True))
            else:
                print(f"agent_calibration_events: {out['rows_total']:,} rows, "
                      f"{out['duplicate_groups']:,} duplicated groups holding "
                      f"{out['rows_in_duplicate_groups']:,} rows")
                print(f"  would archive {out['rows_to_archive']:,} (keep {out['rows_kept']:,}; "
                      f"{out['survivor_rule']})")
                print(f"  archive dir {out['archive_dir']}  stored {out['stored_bytes']:,} B  "
                      f"est. archive {out['est_archive_bytes'] or 0:,} B")
                if not out["predicate_matches_groups"]:
                    print(f"  WARNING: predicate selects {out['rows_to_archive']:,}, group count "
                          f"implies {out['rows_to_archive_expected']:,}", file=sys.stderr)
                print(f"  groups already holding the natural-key row: "
                      f"{out['duplicate_groups'] - out['groups_without_natural_key_row']:,}"
                      f" of {out['duplicate_groups']:,}")
                print("  DRY RUN — nothing written. Apply with --apply --confirm APPLY")
            return 0

        before = survey(conn)
        max_rows = args.max_rows if args.max_rows and args.max_rows > 0 else max(before["rows_to_archive"], 1)
        res = ra.archive_then_delete_batches(
            conn,
            table=TABLE,
            where_sql=DUPLICATE_PREDICATE,
            label=LABEL,
            archive_dir=ra.archive_root() / TABLE,
            batch_rows=args.batch_rows,
            max_rows=max_rows,
            key="id",
            writer=WRITER,
        )
        after = survey(conn)
        out = {"mode": "applied", "before": before, "archived": res, "after": after}
        if args.json:
            print(json.dumps(out, indent=2, default=str, sort_keys=True))
        else:
            print(f"archived {res['rows_archived']:,} rows in {len(res['batches'])} verified batch(es) "
                  f"to {ra.archive_root() / TABLE}")
            print(f"  duplicate groups now: {after['duplicate_groups']:,} "
                  f"(was {before['duplicate_groups']:,}); rows {after['rows_total']:,} "
                  f"(was {before['rows_total']:,})")
        return 0 if res.get("status") == "ok" else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
