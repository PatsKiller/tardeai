#!/usr/bin/env python3
"""Backfill `watchlist_research_cards.latest_summary` rows that hold LLM JSON instead of a sentence.

LQ-20261107-1292: `/api/v2/watchlist/items` serves `latest_summary` as `research_summary`, and
`/v3/manual-execution` path-a cards rendered `{ "summary": "MPWR is not held…` for every row written
by the old writer fallback (a pretty-printed answer cut off before its closing brace). The code fix
makes the reader unwrap these rows on the way out; this script is the optional data repair, for the
operator to run — an agent does not run it.

Safety:
  * **dry by default** — no `--apply`, no writes, and the session is opened read-only;
  * `--apply` re-reads every row inside one transaction and updates only rows whose new text is
    non-empty and genuinely different; `updated_at` is left untouched (a repair is not new research);
  * rows the helper cannot unwrap are reported, never blanked;
  * no row is deleted, no schema change, nothing else on the connection is written.

Usage:
  python3 scripts/ops/backfill_watchlist_research_summary.py            # dry run
  python3 scripts/ops/backfill_watchlist_research_summary.py --json
  python3 scripts/ops/backfill_watchlist_research_summary.py --apply    # operator only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "scripts" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from cio_agent_contract import summary_text  # noqa: E402

JSON_SHAPED_SQL = """
    SELECT symbol, latest_summary
    FROM watchlist_research_cards
    WHERE latest_summary IS NOT NULL
      AND btrim(latest_summary) LIKE '{%'
    ORDER BY symbol
"""


def _connect(readonly: bool):
    import psycopg2

    dsn = os.getenv("TRADEAI_DB_DSN") or os.getenv("DATABASE_URL")
    if dsn:
        conn = psycopg2.connect(dsn)
    else:
        # Local socket by default, and the OS user unless DB_USER is set — the same identity the
        # sanctioned read-only `psql -h /var/run/postgresql -d trade_ai` uses.
        kwargs = {"dbname": os.getenv("DB_NAME", "trade_ai"), "host": os.getenv("DB_HOST") or "/var/run/postgresql"}
        for key, env in (("user", "DB_USER"), ("port", "DB_PORT"), ("password", "DB_PASSWORD")):
            if os.getenv(env):
                kwargs[key] = os.environ[env]
        conn = psycopg2.connect(**kwargs)
    if readonly:
        conn.set_session(readonly=True, autocommit=True)
    return conn


def plan(rows) -> tuple[list[dict], list[dict]]:
    """Split rows into (updatable, unrecoverable) without touching the database."""
    updates, stuck = [], []
    for symbol, old in rows:
        new = summary_text(old or "")
        if not new:
            stuck.append({"symbol": symbol, "reason": "empty-after-unwrap", "head": (old or "")[:80]})
        elif new == (old or "").strip():
            stuck.append({"symbol": symbol, "reason": "no-summary-member", "head": (old or "")[:80]})
        else:
            updates.append({"symbol": symbol, "old": old, "new": new})
    return updates, stuck


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the repair (operator only; dry run otherwise)")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--samples", type=int, default=5, help="sample rows to print (default 5)")
    ap.add_argument("--limit", type=int, default=0, help="cap rows updated (0 = all)")
    args = ap.parse_args()
    apply = bool(args.apply)

    conn = _connect(readonly=not apply)
    try:
        cur = conn.cursor()
        cur.execute(JSON_SHAPED_SQL)
        rows = [(r[0], r[1]) for r in cur.fetchall()]
        updates, stuck = plan(rows)
        if args.limit and args.limit > 0:
            updates = updates[: args.limit]

        report = {
            "apply": apply,
            "json_shaped_rows": len(rows),
            "would_update": len(updates),
            "unrecoverable": len(stuck),
            "applied": 0,
            "samples": [
                {"symbol": u["symbol"], "old_head": (u["old"] or "")[:90], "new": u["new"][:160]}
                for u in updates[: args.samples]
            ],
            "unrecoverable_samples": stuck[: args.samples],
        }

        if apply and updates:
            with conn:  # one transaction: any failure rolls the whole repair back
                cur = conn.cursor()
                for u in updates:
                    cur.execute(
                        """UPDATE watchlist_research_cards
                           SET latest_summary = %s
                           WHERE symbol = %s AND latest_summary = %s""",
                        (u["new"], u["symbol"], u["old"]),
                    )
                    report["applied"] += cur.rowcount
                cur.execute("SELECT count(*) FROM watchlist_research_cards WHERE btrim(latest_summary) LIKE '{%'")
                report["json_shaped_after"] = cur.fetchone()[0]
    finally:
        conn.close()

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    mode = "APPLY" if apply else "DRY RUN (no writes)"
    print(f"LQ-1292 watchlist_research_cards.latest_summary repair — {mode}")
    print(f"  JSON-shaped rows : {report['json_shaped_rows']}")
    print(f"  would update     : {report['would_update']}")
    print(f"  unrecoverable    : {report['unrecoverable']} (reported, left untouched)")
    if apply:
        print(f"  applied          : {report['applied']}")
        print(f"  JSON-shaped after: {report.get('json_shaped_after')}")
    for s in report["samples"]:
        print(f"  - {s['symbol']}: {s['old_head']!r} -> {s['new']!r}")
    for s in report["unrecoverable_samples"]:
        print(f"  ! {s['symbol']}: {s['reason']} ({s['head']!r})")
    if not apply:
        print("  re-run with --apply to write this repair (operator decision)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
