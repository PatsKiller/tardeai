#!/usr/bin/env python3
"""backfill_subject_identity.py — put the research corpus on the identity spine.

Stage 0 of docs/architecture/MATERIAL_CHANGE_TO_QUESTIONS.md.

WHY THIS EXISTS
---------------
Measured 2026-09-06, roughly 336,000 rows could not be joined to a subject:

    catalyst_events              136,052   no subject_guid column at all
    hermes_external_research      48,456   no subject_guid column at all
    research_insights             46,717   no subject_guid column at all
    news_articles                 88,115   column present, never filled
    hermes_research_intelligence  16,742   column present, never filled

Anything that assembles "everything we know about X" by subject_guid therefore sees
about a third of the corpus. That is the most dangerous shape a gap can take: it does
not fail, it under-answers, and it looks identical to a complete answer.

THIS COSTS NOTHING
------------------
Resolution is a registry lookup — a pure function of the symbol. No model is called,
on any row, ever. `test_backfill_subject_identity.py` pins that, because the cheap
deterministic path is exactly the one a later change is tempted to "improve" with a
model.

FOUR OUTCOMES, NOT TWO
----------------------
A row is resolved, or it is not-applicable (cash, index), or the registry says it does
not know the symbol, or the registry could not be read at all. The last is not a
property of the row and must never be written as though the symbol were unknown — a
transient registry failure would otherwise permanently stamp good rows UNRESOLVED. On
a lookup failure the run stops rather than continuing to write worthless answers.

    python3 scripts/backfill_subject_identity.py --all                 # dry run
    python3 scripts/backfill_subject_identity.py --all --add-columns --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

#: Every table the dossier must be able to join, and the column holding its symbol.
TARGETS: dict[str, str] = {
    "catalyst_events": "symbol",
    "hermes_external_research": "symbol",
    "research_insights": "symbol",
    "news_articles": "symbol",
    "hermes_research_intelligence": "symbol",
}

#: Mirrors the shape already on news_articles. Kept identical on purpose: a second
#: near-miss spelling of the same idea is how a spine stops being one spine.
IDENTITY_COLUMNS = (
    ("subject_guid", "uuid"),
    ("issuer_guid", "uuid"),
    ("gics_sector", "text"),
    ("identity_status", "text"),
    ("identity_tagged_at", "timestamptz"),
)

#: One-way rank, as everywhere else on the spine. A backfill may raise a row's
#: confidence but never lower it: re-running must not degrade what a better-informed
#: pass already established.
RANK = {"CONFIRMED": 3, "CANDIDATE": 2, "UNRESOLVED": 1, None: 0, "": 0}

BATCH = int(os.getenv("IDENTITY_BACKFILL_BATCH", "2000"))


def _db():
    import psycopg2

    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
    return psycopg2.connect(
        host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"),
    )


def add_columns(cur, table: str, *, apply: bool) -> list[str]:
    """Idempotent. Returns the columns that were (or would be) added."""
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name=%s", (table,))
    have = {r[0] for r in cur.fetchall()}
    missing = [(c, t) for c, t in IDENTITY_COLUMNS if c not in have]
    for col, typ in missing:
        if apply:
            cur.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "{col}" {typ}')
    return [c for c, _ in missing]


def backfill(cur, table: str, symbol_col: str, *, apply: bool, limit: int | None) -> dict:
    """Resolve and stamp. Returns honest per-outcome counts.

    ``rows_produced`` is None when nothing was measured, and 0 when a pass genuinely
    found nothing to do. Two states cannot express "no input".
    """
    from scripts.lib.cio_subject_guid import lookup_identity_envelope

    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name=%s", (table,))
    have = {r[0] for r in cur.fetchall()}
    if "subject_guid" not in have:
        return {"table": table, "skipped": "no identity columns — run --add-columns",
                "rows_produced": None}

    cur.execute(
        f'SELECT DISTINCT {symbol_col} FROM {table} '
        f'WHERE {symbol_col} IS NOT NULL AND subject_guid IS NULL'
        + (f' LIMIT {int(limit)}' if limit else ""))
    symbols = [r[0] for r in cur.fetchall()]

    counts = {"resolved": 0, "unresolved": 0, "not_applicable": 0,
              "symbols_seen": len(symbols), "rows_stamped": 0}
    if not symbols:
        counts["rows_produced"] = 0
        return {"table": table, **counts}

    now = datetime.now(timezone.utc)
    for sym in symbols:
        env = lookup_identity_envelope(sym)
        if env.get("identity_lookup_failed"):
            # Not a fact about this symbol. Writing it would be a lie that outlives
            # the outage that caused it.
            raise RuntimeError(
                f"REGISTRY_UNREADABLE while resolving {sym!r}: "
                f"{env.get('identity_lookup_reason')} — stopping rather than stamping "
                f"rows UNRESOLVED on a transient failure")

        guid = env.get("subject_guid")
        if not guid:
            counts["not_applicable" if env.get("identity_lookup") == "NOT_APPLICABLE"
                   else "unresolved"] += 1
            continue
        counts["resolved"] += 1
        if not apply:
            continue
        cur.execute(
            # NULL identity_status means UNKNOWN, which is rank 0 — the LOWEST.
            # Coalescing it to 'CONFIRMED' made every untagged row look already
            # confirmed, so the guard matched nothing and the backfill reported 23
            # resolved symbols while writing zero rows. Rank order is
            # CONFIRMED > CANDIDATE > UNRESOLVED > unknown; only an already-CONFIRMED
            # row is protected from being rewritten.
            f'UPDATE {table} SET subject_guid=%s, issuer_guid=%s, identity_status=%s, '
            f'identity_tagged_at=%s '
            f'WHERE {symbol_col}=%s AND subject_guid IS NULL '
            f"  AND COALESCE(identity_status, '') <> 'CONFIRMED'",
            (guid, env.get("issuer_guid"), env.get("identity_status"), now, sym))
        counts["rows_stamped"] += cur.rowcount

    counts["rows_produced"] = counts["rows_stamped"] if apply else None
    return {"table": table, **counts}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", action="append", choices=sorted(TARGETS))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--add-columns", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    tables = sorted(TARGETS) if args.all else (args.table or [])
    if not tables:
        ap.error("pass --all or --table <name>")

    conn = _db()
    cur = conn.cursor()
    print(f"Stage 0 identity backfill — apply={args.apply} tables={len(tables)}")
    results = []
    for t in tables:
        added = add_columns(cur, t, apply=args.apply and args.add_columns) if args.add_columns else []
        if added:
            print(f"  {t}: {'added' if args.apply else 'would add'} {', '.join(added)}")
        if args.apply:
            conn.commit()
        res = backfill(cur, t, TARGETS[t], apply=args.apply, limit=args.limit)
        if args.apply:
            conn.commit()
        results.append(res)
        if res.get("skipped"):
            print(f"  {t}: SKIPPED — {res['skipped']}")
        else:
            print(f"  {t}: symbols={res['symbols_seen']} resolved={res['resolved']} "
                  f"unresolved={res['unresolved']} n/a={res['not_applicable']} "
                  f"rows_stamped={res['rows_stamped']}")
    conn.close()
    import json
    print("RESULT: " + json.dumps({"schema": "SubjectIdentityBackfill@v1",
                                  "authority": "READ_ONLY_ADVISORY",
                                  "model_calls": 0, "tables": results}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
