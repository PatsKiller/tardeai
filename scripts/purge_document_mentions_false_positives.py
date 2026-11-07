#!/usr/bin/env python3
"""Purge document_mentions rows the rule refuses, and the duplicates the old index could not stop.

DRY RUN BY DEFAULT. It writes nothing and it deletes nothing unless `--apply` is given; the operator
(the lead) applies. Two classes of row, chosen by the same deterministic rule the writer uses:

  false_positive   a name/alias match that ``false_positive_reason`` refuses today. These rows were
                   written BEFORE the rule existed; nothing new produces them. Measured 2026-11-07:
                   89,625 of 147,207 name/alias rows, and the refusals were 100 % correct on the
                   adjudicated sample (LQ-287).
  null_duplicate   extra rows in a (document, role) group whose issuer could not be resolved. The old
                   unique index cannot see them because PostgreSQL treats every NULL as distinct, so
                   the backfill inserted one per pass. The first row of each group is KEPT; the extras
                   are removed. 1,681 rows in 1,599 groups measured 2026-11-07.

ARCHIVE FIRST, ALWAYS. Every purged row is copied into ``document_mentions_purged`` in the SAME
transaction, and the delete is issued only after the archived count equals the planned count; if the
copy is short, the transaction rolls back and nothing is deleted. ``--restore-batch=<id>`` puts a batch
back. The archive is the record: a purge you cannot undo is a delete, and this lane does not delete.

IDEMPOTENT. The selection is recomputed from the data every run, so a second run after an apply
selects nothing and prints ``nothing to purge``.

    python3 scripts/purge_document_mentions_false_positives.py                      # dry run, both classes
    python3 scripts/purge_document_mentions_false_positives.py --class null_duplicate
    python3 scripts/purge_document_mentions_false_positives.py --apply               # the lead runs this
    python3 scripts/purge_document_mentions_false_positives.py --restore-batch 20261107T2300Z
"""
from __future__ import annotations

import argparse
import collections
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import document_mentions as DM  # noqa: E402

ARCHIVE = "document_mentions_purged"
COLUMNS = (
    "id", "observed_at", "source_table", "source_id", "symbol", "subject_guid", "issuer_guid",
    "identity_status", "role", "role_source", "role_confidence", "matched_via", "matched_text",
    "schema_version", "authority",
)
CLASSES = ("false_positive", "null_duplicate")


def _conn():  # imported lazily so --help works without a database or its dependencies
    from backfill_document_mentions import _conn as backfill_conn

    return backfill_conn()


def select_false_positives(cur) -> list[tuple]:
    """Rows whose match the rule refuses today: (id, source_table, source_id, symbol, matched_text, role, reason)."""
    cur.execute(
        "SELECT id, source_table, source_id, symbol, matched_via, matched_text, role "
        "FROM document_mentions WHERE matched_via IN ('company_name','ticker_alias')"
    )
    rows = cur.fetchall()
    by_table: dict[str, set[int]] = collections.defaultdict(set)
    for r in rows:
        by_table[r[1]].add(r[2])
    texts: dict[tuple[str, int], tuple[str, str]] = {}
    for table, ids in by_table.items():
        spec = DM.SOURCES.get(table)
        if not spec or not spec["text"]:
            continue
        cols = " || ' ' || ".join(f"coalesce({c}::text,'')" for c in spec["text"])
        # Table and column names come from DM.SOURCES, a module constant, never from input; the id
        # list is the only value and it is a parameter.
        cur.execute(
            "SELECT " + spec["id"] + ", " + cols + ", coalesce(" + spec["own_symbol"] + "::text,'') "
            "FROM " + table + " WHERE " + spec["id"] + " = ANY(%s)",
            (sorted(ids),),
        )
        for i, t, own in cur.fetchall():
            texts[(table, i)] = (t or "", own or "")
    out: list[tuple] = []
    for mid, table, sid, sym, via, mt, role in rows:
        t, own = texts.get((table, sid), ("", ""))
        why = DM.false_positive_reason(mt, sym, via, text=t, own_symbol=own or None)
        if why:
            out.append((mid, table, sid, sym, mt, role, why))
    return out


def select_null_duplicates(cur) -> list[tuple]:
    """Extras in a NULL-issuer group, keeping the earliest row: (id, source_table, source_id, role, kept_id)."""
    cur.execute(
        """
        SELECT id, source_table, source_id, role, first_value(id) OVER (
                   PARTITION BY source_table, source_id, role ORDER BY id) AS kept_id
          FROM document_mentions
         WHERE issuer_guid IS NULL
         ORDER BY source_table, source_id, role, id
        """
    )
    return [(r[0], r[1], r[2], r[3], r[4]) for r in cur.fetchall() if r[0] != r[4]]


def ensure_archive(cur) -> None:
    # Identifiers are module constants, never input: assembled by concatenation so no value can be
    # interpolated into DDL.
    cur.execute("CREATE TABLE IF NOT EXISTS " + ARCHIVE + " (LIKE document_mentions INCLUDING DEFAULTS)")
    cur.execute("ALTER TABLE " + ARCHIVE + " ADD COLUMN IF NOT EXISTS purge_batch text")
    cur.execute("ALTER TABLE " + ARCHIVE + " ADD COLUMN IF NOT EXISTS purge_reason text")
    cur.execute("ALTER TABLE " + ARCHIVE
                + " ADD COLUMN IF NOT EXISTS purged_at timestamptz NOT NULL DEFAULT now()")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_dm_purged_batch ON " + ARCHIVE + " (purge_batch, id)")


def _stage_plan(cur, plan: dict[int, str]) -> None:
    """Put (id, reason) into a temp table so the archive and the delete are one set-wise statement each."""
    cur.execute("CREATE TEMP TABLE _purge_plan (id bigint PRIMARY KEY, reason text NOT NULL) ON COMMIT DROP")
    items = [(int(i), str(why)) for i, why in plan.items()]
    for start in range(0, len(items), 1000):
        chunk = items[start:start + 1000]
        values = ",".join(["(%s,%s)"] * len(chunk))
        params = [v for pair in chunk for v in pair]
        cur.execute("INSERT INTO _purge_plan (id, reason) VALUES " + values, params)


def apply_batch(conn, plan: dict[int, str], batch: str) -> tuple[int, int]:
    """Archive then delete, in one transaction. Returns (archived, deleted). Raises on any shortfall."""
    cur = conn.cursor()
    ensure_archive(cur)
    _stage_plan(cur, plan)
    cols = ", ".join(COLUMNS)                      # module constants, never input
    cur.execute(
        "INSERT INTO " + ARCHIVE + " (" + cols + ", purge_batch, purge_reason) "
        "SELECT " + ", ".join("d." + c for c in COLUMNS) + ", %s, p.reason "
        "FROM document_mentions d JOIN _purge_plan p ON p.id = d.id "
        "ON CONFLICT (purge_batch, id) DO NOTHING",
        (batch,),
    )
    archived = cur.rowcount
    if archived != len(plan):
        conn.rollback()
        raise RuntimeError(f"archived {archived} of {len(plan)} planned rows; rolled back, nothing deleted")
    cur.execute("DELETE FROM document_mentions d USING _purge_plan p WHERE p.id = d.id")
    deleted = cur.rowcount
    if deleted != len(plan):
        conn.rollback()
        raise RuntimeError(f"deleted {deleted} of {len(plan)} archived rows; rolled back")
    conn.commit()
    return archived, deleted


def restore_batch(conn, batch: str) -> int:
    cur = conn.cursor()
    cols = ", ".join(COLUMNS)
    cur.execute("INSERT INTO document_mentions (" + cols + ") SELECT " + cols + " FROM " + ARCHIVE
                + " WHERE purge_batch = %s ON CONFLICT DO NOTHING", (batch,))
    n = cur.rowcount
    conn.commit()
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--class", dest="klass", choices=(*CLASSES, "all"), default="all")
    ap.add_argument("--apply", action="store_true", help="archive and delete; without it this is a dry run")
    ap.add_argument("--restore-batch", metavar="BATCH", help="put a purged batch back, then stop")
    ap.add_argument("--samples", type=int, default=8, help="how many rows to show")
    args = ap.parse_args(argv)

    conn = _conn()
    if args.restore_batch:
        n = restore_batch(conn, args.restore_batch)
        print(f"restored {n} rows from batch {args.restore_batch}")
        return 0
    if not args.apply:
        conn.set_session(readonly=True)                   # a dry run cannot write even by accident
    cur = conn.cursor()

    classes = CLASSES if args.klass == "all" else (args.klass,)
    plan: dict[int, str] = {}
    fp: list[tuple] = []
    dups: list[tuple] = []
    if "false_positive" in classes:
        fp = select_false_positives(cur)
        for mid, _t, _sid, _sym, _mt, _role, why in fp:
            plan[mid] = why
    if "null_duplicate" in classes:
        dups = select_null_duplicates(cur)
        for mid, _t, _sid, _role, _kept in dups:
            plan[mid] = "null_issuer_duplicate"

    print(f"mode={'APPLY' if args.apply else 'DRY RUN'} classes={','.join(classes)}")
    print(f"false_positive rows  : {len(fp)}")
    if fp:
        reasons = collections.Counter(r[6] for r in fp)
        offenders = collections.Counter((r[4], r[3]) for r in fp)
        print("  reasons:", dict(reasons))
        print("  top offenders:", offenders.most_common(10))
    print(f"null_issuer_duplicate rows: {len(dups)}")
    if dups:
        tables = collections.Counter(d[1] for d in dups)
        print("  by source_table:", dict(tables))
        print("  samples (removed id -> kept id):", [(d[0], d[4], d[3]) for d in dups[:5]])
    print(f"planned total        : {len(plan)}")

    if not plan:
        print("nothing to purge")
        return 0
    if not args.apply:
        for mid in sorted(plan)[: max(0, args.samples)]:
            print(f"  would purge id={mid} reason={plan[mid]}")
        print("Dry run: nothing written, nothing deleted. Re-run with --apply to archive and delete.")
        return 0

    batch = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archived, deleted = apply_batch(conn, plan, batch)
    print(f"batch={batch} archived={archived} deleted={deleted}")
    print(f"undo: python3 scripts/purge_document_mentions_false_positives.py --restore-batch {batch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
