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
    python3 scripts/backfill_subject_identity.py --all --apply --dry-run   # dry run (wins)

LANE (cron L926, ``--all --apply``): identity-sweep-stage0.

--dry-run wins over --apply (and over --add-columns): ``apply`` is computed once as
``args.apply and not args.dry_run`` and every UPDATE / ALTER / commit is behind it; a dry run's
session is also READ ONLY at the server (lane_last_receipt.enforce_readonly). A run without --apply
is the same dry run. A dry run prints one DRY-RUN report line (symbols that would resolve per table,
topics, columns that would be added) and never writes the lane receipt.

A real (--apply) run writes <state_root>/data/runtime/identity-sweep-stage0_last.json
(LaneRunReceipt@v1: rows_stamped / topic_rows / unresolvable_rows / symbols_resolved per run; ok_at only
on success). Exit codes: 0 = ran (zero rows stamped is a finding -- it is the usual yield -- and still
0); 1 = the run failed: DB unavailable, or the registry could not be read (REGISTRY_UNREADABLE, which
stops the run rather than stamp UNRESOLVED), or any other crash -- the receipt is written ``failed``
and the error re-raised; 2 = usage error (no --all / --table).
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

LANE_ID = "identity-sweep-stage0"


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.backfill_subject_identity
        from scripts.lib import lane_last_receipt as lr
    return lr

#: SubjectIdentityBackfill@v1 is a run receipt, and nothing reads it yet. Its
#: consumer is stage 1 of docs/architecture/MATERIAL_CHANGE_TO_QUESTIONS.md — the
#: material-change detector, which needs to know how much of the corpus is actually
#: joinable before it can honestly report what it did and did not see. Declaring the
#: gap here rather than leaving it silent is the point of check_dark_contracts: the
#: recurring defect in this codebase is a versioned contract whose caller was never
#: wired, and which passes its own tests forever.
NO_CONSUMER_REASON = (
    "run receipt for a stage-0 backfill; consumer is the stage-1 material-change "
    "detector, which is not built yet (docs/architecture/MATERIAL_CHANGE_TO_QUESTIONS.md)"
)


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


#: Topic slugs are SUBJECTS TOO, just not securities. catalyst_events and
#: news_articles carry rows whose "symbol" is a research theme — d107_energy_transition,
#: su_industry_insurance_brokers — because the catalyst engine files theme research under
#: the same column as company research.
#:
#: Giving those a SECURITY guid would be fabricating identity. Leaving them NULL makes a
#: third of the corpus permanently unjoinable and indistinguishable from rows nobody has
#: looked at yet. They get their own deterministic guid instead, minted the way the rest
#: of the spine mints, so theme research is retrievable alongside the companies it
#: touches — which is most of its value.
TOPIC_NAMESPACE = "topic"


def topic_guid(topic_id: str) -> str:
    """Deterministic, and identical to how security_identity mints."""
    import uuid

    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:{TOPIC_NAMESPACE}:{topic_id}"))


#: A symbol that is neither a security nor a known topic. Recorded rather than left
#: NULL: "examined and unresolvable" and "never examined" are different states, and a
#: column that cannot tell them apart cannot measure its own coverage. Values like
#: ASSET, NEW, NEED, TO and STUDY are English words a ticker extractor mistook for
#: symbols — an upstream defect, but one this layer must not silently absorb.
UNRESOLVABLE = "UNRESOLVABLE"


def classify_remainder(cur, table: str, symbol_col: str, *, apply: bool) -> dict:
    """Resolve topics, then mark whatever is left as examined-and-unresolvable.

    After this runs, `identity_status IS NULL` means exactly one thing: nobody has
    looked at this row yet. That is what makes coverage measurable.
    """
    counts = {"topics": 0, "topic_rows": 0, "unresolvable_rows": 0}
    now = datetime.now(timezone.utc)

    cur.execute("SELECT to_regclass('public.topic_monitor')")
    has_topics = cur.fetchall()[0][0] is not None
    if has_topics:
        cur.execute(
            f'SELECT DISTINCT t.topic_id FROM {table} x '
            f'JOIN topic_monitor t ON t.topic_id = x.{symbol_col} '
            f'WHERE x.subject_guid IS NULL')
        for (tid,) in cur.fetchall():
            counts["topics"] += 1
            if not apply:
                continue
            cur.execute(
                f'UPDATE {table} SET subject_guid=%s, identity_status=%s, identity_tagged_at=%s '
                f'WHERE {symbol_col}=%s AND subject_guid IS NULL',
                (topic_guid(tid), "CONFIRMED", now, tid))
            counts["topic_rows"] += cur.rowcount

    if apply:
        # Everything still unresolved has now been looked at by both resolvers.
        cur.execute(
            f'UPDATE {table} SET identity_status=%s, identity_tagged_at=%s '
            f'WHERE subject_guid IS NULL AND identity_status IS NULL',
            (UNRESOLVABLE, now))
        counts["unresolvable_rows"] = cur.rowcount
    return counts


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


def _totals(results: list[dict]) -> dict:
    keys = ("symbols_seen", "resolved", "unresolved", "not_applicable", "rows_stamped",
            "topics", "topic_rows", "unresolvable_rows")
    out = {k: sum(int(r.get(k) or 0) for r in results) for k in keys}
    out["tables"] = len(results)
    out["tables_skipped"] = sorted(r["table"] for r in results if r.get("skipped"))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", action="append", choices=sorted(TARGETS))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--add-columns", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="report only; wins over --apply")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args(argv)

    tables = sorted(TARGETS) if args.all else (args.table or [])
    if not tables:
        ap.error("pass --all or --table <name>")

    # AGENTS.md §6: one decision, made before the connection opens; every write below is behind it.
    apply = bool(args.apply and not args.dry_run)
    started = datetime.now(timezone.utc).isoformat()
    results: list[dict] = []
    added_by_table: dict[str, list[str]] = {}
    try:
        conn = _db()
        if not apply:
            _receipt_lib().enforce_readonly(conn)
        cur = conn.cursor()
        print(f"Stage 0 identity backfill — apply={apply} tables={len(tables)}")
        for t in tables:
            added = add_columns(cur, t, apply=apply) if args.add_columns else []
            if added:
                added_by_table[t] = added
                print(f"  {t}: {'added' if apply else 'would add'} {', '.join(added)}")
            if apply:
                conn.commit()
            res = backfill(cur, t, TARGETS[t], apply=apply, limit=args.limit)
            if apply:
                conn.commit()
            if not res.get("skipped") and not args.limit:
                # Only on a full pass. Under --limit the remainder has not actually been
                # examined, and marking it UNRESOLVABLE would be a lie the next run
                # inherits.
                res.update(classify_remainder(cur, t, TARGETS[t], apply=apply))
                if apply:
                    conn.commit()
            results.append(res)
            if res.get("skipped"):
                print(f"  {t}: SKIPPED — {res['skipped']}")
            else:
                print(f"  {t}: symbols={res['symbols_seen']} resolved={res['resolved']} "
                      f"unresolved={res['unresolved']} n/a={res['not_applicable']} "
                      f"rows_stamped={res['rows_stamped']}"
                      + (f" | topics={res.get('topics', 0)} topic_rows={res.get('topic_rows', 0)}"
                         f" unresolvable={res.get('unresolvable_rows', 0)}"
                         if "topics" in res else ""))
        conn.close()
    except Exception as exc:
        print(f"Stage 0 identity backfill FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        if apply:
            _receipt_lib().write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                                              script="backfill_subject_identity.py", summary=_totals(results),
                                              error=f"{type(exc).__name__}: {exc}")
            raise
        return 1
    import json
    print("RESULT: " + json.dumps({"schema": "SubjectIdentityBackfill@v1",
                                  "authority": "READ_ONLY_ADVISORY",
                                  "model_calls": 0, "tables": results}, default=str))
    totals = _totals(results)
    if not apply:
        _receipt_lib().dry_run_report(LANE_ID, {**totals, "would_add_columns": added_by_table}, would_write=[
            "UPDATE <table> SET subject_guid/issuer_guid/identity_status for resolved symbols x resolved",
            "UPDATE <table> topic subject_guid x topics; identity_status=UNRESOLVABLE for the remainder"
            " (full pass only)"])
        return 0
    _receipt_lib().write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=started,
                                      script="backfill_subject_identity.py", summary=totals)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
