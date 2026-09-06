#!/usr/bin/env python3
"""Tag the research corpus with identity-spine GUIDs and GICS sector.

    python3 scripts/backfill_research_identity.py --table hermes_research_intelligence
    python3 scripts/backfill_research_identity.py --all --apply --limit 5000

DRY RUN IS THE DEFAULT. `--apply` is required to write, because this touches an
authoritative store and the whole point of the tag is that downstream agents will
trust it.

WHAT IT DOES
------------
symbol -> identity_registry -> {subject_guid, issuer_guid, identity_status}
symbol -> intelligence_entities.sector -> gics_sector

Both are pure lookups against data already in the system. Nothing is inferred,
nothing is classified, no model is called: a row is either resolvable or it is
left alone. Measured resolvability before writing this: 16,594 of 16,746
symbol-bearing research rows (99%).

WHY IT NEVER DOWNGRADES
-----------------------
Re-running must be safe. A row already tagged CONFIRMED is not overwritten by a
later CANDIDATE resolution — same one-way rule the registry itself enforces, so a
feed that stops publishing CUSIPs cannot quietly degrade the corpus.

WHY UNRESOLVED ROWS ARE LEFT NULL
---------------------------------
A tag with a null subject_guid is indistinguishable downstream from an untagged
row, and writing one would inflate apparent coverage. Unresolved rows stay NULL
and are reported as the measurement they are.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

TABLES = ("hermes_research_intelligence", "news_articles")


def _conn():
    import psycopg2
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        dbname=os.environ.get("DB_NAME", "trade_ai"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD"),
    )


def _sector_map(cur) -> dict[str, str]:
    """GICS sector by symbol. intelligence_entities keys on entity_id."""
    cur.execute("""SELECT upper(entity_id), max(sector)
                     FROM intelligence_entities
                    WHERE sector IS NOT NULL AND entity_id IS NOT NULL
                    GROUP BY 1""")
    from lib import research_identity as RI  # noqa: PLC0415
    out = {}
    for sym, v in cur.fetchall():
        g = RI.normalize_sector(v)
        if sym and g:
            out[sym] = g
    cur.execute("""SELECT upper(symbol), max(sector)
                     FROM aegis_symbol_snapshot_nightly
                    WHERE sector IS NOT NULL AND symbol IS NOT NULL
                      AND btrim(sector) <> ''
                    GROUP BY 1""")
    for sym, v in cur.fetchall():        # entity registry wins; aegis fills gaps
        g = RI.normalize_sector(v)       # fund-strategy labels are dropped here
        if sym and g:
            out.setdefault(sym, g)
    return out


REQUIRED = ("subject_guid", "issuer_guid", "gics_sector",
            "identity_status", "identity_tagged_at")


def preflight(cur, table: str) -> list[str]:
    """Name the missing columns instead of dying inside a SELECT.

    Without this the first symptom is `column "subject_guid" does not exist`
    from a query three functions deep, which reads like a code bug rather than
    "the migration has not been applied yet".
    """
    cur.execute("""SELECT column_name FROM information_schema.columns
                    WHERE table_name = %s""", (table,))
    have = {r[0] for r in cur.fetchall()}
    return [c for c in REQUIRED if c not in have]


def run(table: str, limit: int, apply: bool) -> dict:
    from lib import research_identity as RI

    doc = RI.load_registry()
    conn = _conn()
    cur = conn.cursor()
    missing = preflight(cur, table)
    if missing:
        conn.close()
        return {"table": table, "error": "MIGRATION_NOT_APPLIED", "missing": missing,
                "considered": 0, "guid": 0, "sector": 0, "unresolved": 0,
                "skipped_no_downgrade": 0, "written": 0}
    sectors = _sector_map(cur)

    cur.execute(f"""SELECT id, symbol, identity_status
                      FROM {table}
                     WHERE symbol IS NOT NULL
                       AND (subject_guid IS NULL OR gics_sector IS NULL)
                     ORDER BY created_at DESC NULLS LAST
                     LIMIT %s""", (limit,))
    rows = cur.fetchall()

    stat = {"table": table, "considered": len(rows), "guid": 0,
            "sector": 0, "unresolved": 0, "skipped_no_downgrade": 0, "written": 0}
    writes = []
    for rid, sym, cur_status in rows:
        tag = RI.resolve(doc, sym)
        gics = sectors.get(str(sym or "").strip().upper())
        if tag is None and gics is None:
            stat["unresolved"] += 1
            continue
        if tag is not None and cur_status and not RI.is_upgrade(cur_status, tag["identity_status"]):
            tag = None
            stat["skipped_no_downgrade"] += 1
        if tag is not None:
            stat["guid"] += 1
        if gics is not None:
            stat["sector"] += 1
        if tag is None and gics is None:
            continue
        writes.append((rid, tag, gics))

    if apply and writes:
        for rid, tag, gics in writes:
            sets, vals = [], []
            if tag:
                sets += ["subject_guid=%s", "issuer_guid=%s", "identity_status=%s",
                         "identity_tagged_at=now()"]
                vals += [tag["subject_guid"], tag["issuer_guid"], tag["identity_status"]]
            if gics:
                sets.append("gics_sector=%s"); vals.append(gics)
            vals.append(rid)
            cur.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=%s", vals)
            stat["written"] += 1
            if stat["written"] % 500 == 0:
                conn.commit()
        conn.commit()

    conn.close()
    return stat


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", choices=TABLES)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--apply", action="store_true", help="write (default is dry run)")
    a = ap.parse_args()
    targets = TABLES if a.all else ([a.table] if a.table else [])
    if not targets:
        ap.error("--table or --all required")

    mode = "APPLY" if a.apply else "DRY RUN — nothing written"
    print(f"[{mode}]")
    for t in targets:
        s = run(t, a.limit, a.apply)
        if s.get("error"):
            print(f"  {s['table']}: {s['error']} — missing columns: {', '.join(s['missing'])}")
            print(f"     apply sql/research_identity_tags.sql first (needs a db-write grant)")
            continue
        print(f"  {s['table']}: considered={s['considered']} "
              f"guid={s['guid']} sector={s['sector']} unresolved={s['unresolved']} "
              f"no_downgrade={s['skipped_no_downgrade']} written={s['written']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
