#!/usr/bin/env python3
"""Quarantine percent-valued Finviz recom rows replayed since 2026-09-08 (2026-10-18).

WHAT HAPPENED
-------------
The 2026-09-13 fix (header-keyed Finviz parse + ``_classify_recom``) stopped NEW
bad values, and ``quarantine_fabricated_analyst_ratings.py`` cleaned the rows
written before it. But 13 ``ticker_enrichment_cache.json`` entries cached
2026-09-05..09-11 (JNUG "-95.44%", BELFB "938.86%", ...) belong to symbols that
left the refresh universe, so they were never re-fetched, and
``save_analyst_consensus_history`` replayed them into ``analyst_consensus_history``
every day: JNUG -95.44 -> "Strong Buy".

The writer and the cache loader now refuse such values (scripts/lib/
analyst_recom_guard.py). This script repairs what was already written.

WHAT THIS DOES
--------------
Default is a DRY RUN: it lists the bad cache entries and the bad table rows and
writes nothing.

With ``--apply`` AND a non-empty ``TRADEAI_REMEDIATION_GRANT`` (operator only):

  1. copies every affected row, whole, into
     ``analyst_consensus_history_quarantine_20261018`` (idempotent on id);
  2. on those rows in the live table sets ONLY ``recom_score`` and
     ``analyst_rating`` to NULL -- ``recom_raw`` is kept as evidence;
  3. with ``--apply-cache`` also archives the cache file to
     ``data/state/archive/ticker_enrichment_cache.<stamp>.json`` and nulls the
     same two derived fields on the bad cache entries (``recom_reject_reason``
     names why). Nothing is ever deleted.

REVERSAL
--------
    UPDATE analyst_consensus_history a
       SET recom_score = q.recom_score, analyst_rating = q.analyst_rating
      FROM analyst_consensus_history_quarantine_20261018 q
     WHERE a.id = q.id;

USAGE
-----
    python3 scripts/remediate_analyst_consensus_20261018.py              # dry run
    TRADEAI_REMEDIATION_GRANT='<grant id>' \\
      python3 scripts/remediate_analyst_consensus_20261018.py --apply [--apply-cache]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from lib.analyst_recom_guard import recom_reject_reason, sanitize_enrichment_record  # noqa: E402

QUARANTINE_TABLE = "analyst_consensus_history_quarantine_20261018"
DEFAULT_SINCE = "2026-09-08"
GRANT_ENV = "TRADEAI_REMEDIATION_GRANT"

# A "%" in the raw text, or a numeric score off the 1..5 scale, is not a rating.
AFFECTED_PREDICATE = (
    "snapshot_date >= %(since)s AND ("
    " position('%%' in coalesce(recom_raw, '')) > 0"
    " OR (recom_score IS NOT NULL AND NOT (recom_score BETWEEN 1 AND 5))"
    " )"
)


def default_cache_path() -> Path:
    return _HERE.parent / "data" / "state" / "ticker_enrichment_cache.json"


def scan_cache(cache: dict) -> list[dict]:
    """Return the cache entries whose recom is refused by the guard."""
    bad = []
    for sym, rec in (cache or {}).items():
        if str(sym).startswith("_") or not isinstance(rec, dict):
            continue
        reason = recom_reject_reason(rec.get("recom"), rec.get("recom_score"))
        if reason:
            bad.append({
                "symbol": sym, "recom": rec.get("recom"),
                "recom_score": rec.get("recom_score"),
                "analyst_rating": rec.get("analyst_rating"),
                "cached_at": rec.get("cached_at"), "reason": reason,
            })
    return sorted(bad, key=lambda b: b["symbol"])


def scan_rows(cur, since: str) -> list[tuple]:
    cur.execute(
        "SELECT id, snapshot_date, symbol, recom_raw, recom_score, analyst_rating, source "
        f"FROM analyst_consensus_history WHERE {AFFECTED_PREDICATE} "
        "ORDER BY snapshot_date DESC, symbol",
        {"since": since},
    )
    return list(cur.fetchall())


def apply_rows(conn, since: str) -> dict:
    """Archive then null the derived columns. Caller holds the grant."""
    cur = conn.cursor()
    try:
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {QUARANTINE_TABLE} "
            "(LIKE analyst_consensus_history INCLUDING DEFAULTS)"
        )
        cur.execute(
            f"INSERT INTO {QUARANTINE_TABLE} SELECT * FROM analyst_consensus_history a "
            f"WHERE {AFFECTED_PREDICATE} "
            f"AND NOT EXISTS (SELECT 1 FROM {QUARANTINE_TABLE} q WHERE q.id = a.id)",
            {"since": since},
        )
        archived = cur.rowcount
        cur.execute(
            "UPDATE analyst_consensus_history a SET recom_score = NULL, analyst_rating = NULL "
            f"WHERE {AFFECTED_PREDICATE} "
            f"AND EXISTS (SELECT 1 FROM {QUARANTINE_TABLE} q WHERE q.id = a.id)",
            {"since": since},
        )
        nulled = cur.rowcount
        conn.commit()
        return {"archived": archived, "nulled": nulled}
    except Exception:
        conn.rollback()
        raise


def apply_cache(cache_path: Path, now: datetime | None = None) -> dict:
    """Archive the cache file, then null derived fields on refused entries."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    archive_dir = cache_path.parent / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived = archive_dir / f"{cache_path.stem}.{stamp}.json"
    shutil.copy2(cache_path, archived)
    cache = json.loads(cache_path.read_text())
    flagged = [s for s, r in cache.items()
               if not str(s).startswith("_") and isinstance(r, dict) and sanitize_enrichment_record(r)]
    tmp = cache_path.with_suffix(".json.remediate.tmp")
    tmp.write_text(json.dumps(cache, default=str))
    os.replace(tmp, cache_path)
    return {"archive": str(archived), "flagged": flagged}


def _connect():
    from quarantine_fabricated_analyst_ratings import _env_from_runtime
    import psycopg2

    env = _env_from_runtime()
    conn = psycopg2.connect(host=env["DB_HOST"], port=env.get("DB_PORT", 5432),
                            dbname=env["DB_NAME"], user=env["DB_USER"],
                            password=env["DB_PASSWORD"])
    conn.autocommit = False
    return conn


def run(argv=None, *, connect=_connect, environ=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="execute (needs TRADEAI_REMEDIATION_GRANT)")
    ap.add_argument("--apply-cache", action="store_true",
                    help="with --apply, also flag the bad cache entries (file archived first)")
    ap.add_argument("--since", default=DEFAULT_SINCE)
    ap.add_argument("--cache", type=Path, default=None)
    ap.add_argument("--no-db", action="store_true", help="cache scan only")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    env = os.environ if environ is None else environ

    cache_path = args.cache or default_cache_path()
    cache = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())
    bad_cache = scan_cache(cache)

    rows: list[tuple] = []
    conn = None
    if not args.no_db:
        conn = connect()
        rows = scan_rows(conn.cursor(), args.since)

    report = {
        "mode": "apply" if args.apply else "dry_run",
        "since": args.since,
        "cache_path": str(cache_path),
        "bad_cache_entries": bad_cache,
        "bad_rows": len(rows),
        "bad_rows_by_symbol": {},
    }
    for r in rows:
        report["bad_rows_by_symbol"][r[2]] = report["bad_rows_by_symbol"].get(r[2], 0) + 1

    if not args.json:
        print("Analyst consensus remediation 2026-10-18")
        print("-" * 64)
        print(f"  cache entries refused : {len(bad_cache)}  ({cache_path})")
        for b in bad_cache:
            print(f"    {b['symbol']:<8} recom={str(b['recom']):<10} rating={str(b['analyst_rating']):<12} "
                  f"cached_at={b['cached_at']} reason={b['reason']}")
        if not args.no_db:
            print(f"  table rows since {args.since} : {len(rows)}")
            for r in rows[:20]:
                print(f"    {str(r[1])[:10]} {r[2]:<8} raw={str(r[3]):<10} score={str(r[4]):<10} "
                      f"rating={str(r[5]):<12} source={r[6]}")

    if not args.apply:
        if conn is not None:
            conn.rollback()
            conn.close()
        report["note"] = "DRY RUN - nothing written. Operator: --apply with TRADEAI_REMEDIATION_GRANT."
        print(json.dumps(report, default=str) if args.json else f"\n{report['note']}")
        return 0

    grant = str(env.get(GRANT_ENV) or "").strip()
    if not grant:
        if conn is not None:
            conn.close()
        print(f"REFUSED: --apply needs {GRANT_ENV} (operator grant). Nothing written.", file=sys.stderr)
        return 2
    report["grant"] = grant
    if conn is not None:
        report["db"] = apply_rows(conn, args.since)
        conn.close()
    if args.apply_cache and cache_path.exists() and bad_cache:
        report["cache"] = apply_cache(cache_path)
    print(json.dumps(report, default=str) if args.json else
          f"\nAPPLIED under grant {grant}: {report.get('db')} cache={report.get('cache')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
