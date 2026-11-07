#!/usr/bin/env python3
"""record_decision_outcome.py — Record and backfill decision outcomes.

Links synthesis recommendations to actual price outcomes for learning.

Usage:
    python3 scripts/record_decision_outcome.py [--no-backfill] [--json] [--dry-run]

A real run does BOTH steps: insert an outcome row for every current synthesis that has none, then fill the
+1d/+7d/+30d closes of every row that is still missing one (from ``ticker_prices``) and score the rows that
became scoreable. ``--backfill`` is accepted for compatibility (it used to be opt-in, which is why the n8n
lane, whose argv has no flags, never backfilled a single price); ``--no-backfill`` skips the second step.

Dry run (n8n refactor wave 3, 2026-10-10): ``--dry-run`` runs ONLY read-only selections and the fill preview on
a session made READ ONLY at the server, prints a ``DRY-RUN`` report and returns; ``record_current_decisions``
and ``backfill_prices`` (the INSERT / UPDATE / commit) are not reachable from it. It writes no receipt.

A REAL run (the cron form, no flags) writes LaneRunReceipt@v1
``<state_root>/data/runtime/record-decision-outcome_last.json`` (``ok_at`` only on success). Exit codes:
0 = ran (0 new outcomes is a finding, still 0); 1 = the run failed (DB unavailable or a statement
raised -- each step is one transaction, so a failed step is not half-applied); 2 = usage error (unknown
argument; previously ignored silently).
"""
import argparse
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LANE_ID = "record-decision-outcome"

#: Provenance id prefix: an outcome row points back at the watchlist synthesis it was recorded from.
DECISION_ID_PREFIX = "synthesis"
#: The same instant, formatted for Python and for PostgreSQL, so a row inserted now and a row backfilled later
#: get the identical id.
_TS_FMT_PY = "%Y-%m-%dT%H:%M:%SZ"
_TS_FMT_PG = 'YYYY-MM-DD"T"HH24:MI:SS"Z"'

_DECISIONS_SQL = """
        SELECT fs.symbol, fs.recommendation, fs.confidence, fs.updated_at,
               tsc.strategy_type,
               sc.latest_price
        FROM watchlist_final_synthesis fs
        LEFT JOIN ticker_strategy_classifications tsc ON tsc.symbol = fs.symbol
        LEFT JOIN watchlist_strategy_cards sc ON sc.symbol = fs.symbol
        WHERE fs.superseded IS NOT TRUE
        AND NOT EXISTS (SELECT 1 FROM decision_outcomes dout WHERE dout.symbol = fs.symbol AND dout.created_at > fs.updated_at - INTERVAL '1 day')
    """

#: yfinance-sourced closes (yfinance, yfinance_eod) are never used: operator rule, Finviz/broker/DB closes only.
#: One row per outcome record, with the close nearest +1d/+7d/+30d (within +-3 days, matching the old per-row
#: lookups) and the "fill" flags: a column is written only when it is still NULL and a close was found.
_FILL_SRC_SQL = """
        SELECT o.id,
               o.price_1d IS NULL AND p.p1 IS NOT NULL AS fill_1d,
               o.price_7d IS NULL AND p.p7 IS NOT NULL AS fill_7d,
               o.price_30d IS NULL AND p.p30 IS NOT NULL AS fill_30d,
               o.decision_id IS NULL AS fill_id,
               p.p1, p.p7, p.p30
        FROM decision_outcomes o
        CROSS JOIN LATERAL (
            SELECT
              (SELECT t.close_price FROM ticker_prices t
                WHERE t.symbol = o.symbol
                  AND t.source NOT ILIKE 'yfinance%'
                  AND t.price_date BETWEEN o.created_at::date + 1 - 3 AND o.created_at::date + 1 + 3
                ORDER BY ABS(t.price_date - (o.created_at::date + 1)) LIMIT 1) AS p1,
              (SELECT t.close_price FROM ticker_prices t
                WHERE t.symbol = o.symbol
                  AND t.source NOT ILIKE 'yfinance%'
                  AND t.price_date BETWEEN o.created_at::date + 7 - 3 AND o.created_at::date + 7 + 3
                ORDER BY ABS(t.price_date - (o.created_at::date + 7)) LIMIT 1) AS p7,
              (SELECT t.close_price FROM ticker_prices t
                WHERE t.symbol = o.symbol
                  AND t.source NOT ILIKE 'yfinance%'
                  AND t.price_date BETWEEN o.created_at::date + 30 - 3 AND o.created_at::date + 30 + 3
                ORDER BY ABS(t.price_date - (o.created_at::date + 30)) LIMIT 1) AS p30
        ) p
    """

#: Set-based and idempotent: every price and the provenance id are COALESCEd, so a value another writer already
#: stored -- and the score computed from it -- is never overwritten. Row count = rows actually written.
_FILL_PRICES_SQL = f"""
        WITH src AS ({_FILL_SRC_SQL})
        UPDATE decision_outcomes o
        SET price_1d  = COALESCE(o.price_1d, src.p1),
            price_7d  = COALESCE(o.price_7d, src.p7),
            price_30d = COALESCE(o.price_30d, src.p30),
            decision_id = COALESCE(o.decision_id,
                                   '{DECISION_ID_PREFIX}:' || o.symbol || ':' ||
                                   to_char(o.created_at AT TIME ZONE 'UTC', '{_TS_FMT_PG}'))
        FROM src
        WHERE o.id = src.id
          AND (src.fill_1d OR src.fill_7d OR src.fill_30d OR src.fill_id)
    """

#: Read-only preview of the same fill (dry run).
_FILL_PREVIEW_SQL = f"""
        WITH src AS ({_FILL_SRC_SQL})
        SELECT count(*) AS rows,
               count(*) FILTER (WHERE fill_1d) AS fill_1d,
               count(*) FILTER (WHERE fill_7d) AS fill_7d,
               count(*) FILTER (WHERE fill_30d) AS fill_30d,
               count(*) FILTER (WHERE fill_id) AS fill_id,
               count(*) FILTER (WHERE fill_1d OR fill_7d OR fill_30d OR fill_id) AS would_backfill
        FROM src
    """

#: Rows that became scoreable (runs after the fill, in the same transaction, so it reads the filled prices).
_SCORE_CANDIDATES_SQL = """
        SELECT id, recommendation, price_at_decision, price_7d
        FROM decision_outcomes
        WHERE outcome_score IS NULL AND price_at_decision IS NOT NULL AND price_7d IS NOT NULL
    """

#: Never rewrites an existing score, and never moves an already-stamped evaluated_at.
_SCORE_UPDATE_SQL = """
        UPDATE decision_outcomes
        SET outcome_score = %s, evaluated_at = COALESCE(evaluated_at, NOW())
        WHERE id = %s AND outcome_score IS NULL
    """



def _receipt_lib():
    try:
        from scripts.lib import lane_last_receipt as lr
    except ImportError:  # scripts/ on sys.path, repo root not
        from lib import lane_last_receipt as lr
    return lr


def _select_decisions(cur) -> list:
    """Read-only: current syntheses without an outcome record."""
    cur.execute(_DECISIONS_SQL)
    return cur.fetchall()


def decision_id_for(symbol, when) -> str:
    """The deterministic provenance id of an outcome row: ``synthesis:<SYMBOL>:<UTC instant>``.

    ``when`` is the synthesis' ``updated_at`` (the row's ``created_at``). The SQL fill builds the identical string
    (``_TS_FMT_PG``), so a row inserted today and a row backfilled later agree, and re-running is a no-op.
    """
    if isinstance(when, str):
        when = datetime.fromisoformat(when.replace("Z", "+00:00"))
    elif not isinstance(when, datetime):  # a plain date from a driver/test double: midnight UTC
        when = datetime(when.year, when.month, when.day, tzinfo=timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return f"{DECISION_ID_PREFIX}:{symbol}:{when.astimezone(timezone.utc).strftime(_TS_FMT_PY)}"


def _outcome_score(recommendation, price_at_decision, price_after):
    """The categorical outcome score every stored row uses, exactly as the live writer computes it
    (``overnight_batch.evaluate_past_decisions``): 1.0 when the recommendation was right, -0.5 when a move of more
    than 5% went against it, 0 otherwise. None when it cannot be computed -- unknown is not zero.

    Only one definition of this column may exist. AVOID/IGNORE/NONE carry no direction, so they score on the
    fallback branch, which is what all 864 scored rows already do; changing that here would split the column into
    two meanings. Reported, not changed (LQ-20261107-130).
    """
    if price_at_decision is None or price_after is None:
        return None
    p0, p7 = float(price_at_decision), float(price_after)
    if p0 <= 0:
        return None
    change_pct = (p7 / p0 - 1) * 100
    rec = (recommendation or "").strip().upper()
    correct = ((rec in ("BUY", "ADD") and change_pct > 0)
               or (rec in ("SELL", "TRIM") and change_pct < 0)
               or (rec == "HOLD" and abs(change_pct) < 10))
    return 1.0 if correct else (-0.5 if abs(change_pct) > 5 else 0.0)


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def record_current_decisions(real_only: bool = True) -> int:
    """Record all current actionable synthesis decisions for real outcome tracking."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Find syntheses without outcome records
    decisions = _select_decisions(cur)

    recorded = 0
    for d in decisions:
        cur.execute("""
            INSERT INTO decision_outcomes
                (symbol, strategy_type, recommendation, price_at_decision, created_at, decision_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (d["symbol"], d.get("strategy_type"), d["recommendation"],
              float(d["latest_price"]) if d.get("latest_price") else None,
              d["updated_at"], decision_id_for(d["symbol"], d["updated_at"])))
        recorded += 1

    conn.commit()
    conn.close()
    print(f"[outcomes] Recorded {recorded} new decision outcomes")
    return recorded


def backfill_prices(days: int = 30) -> int:
    """Fill the +1d/+7d/+30d closes a decision outcome is still missing, and score the rows that became scoreable.

    One set-based UPDATE, not a per-row loop: the old loop selected only ``evaluated_at IS NULL`` rows, so a row
    another writer had touched was invisible to it forever. Fills are COALESCEd (an existing price, and the score
    computed from it, is never rewritten) and only a scoreless row is scored. Returns the rows written.
    """
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(_FILL_PRICES_SQL)
    # psycopg2 reports an UPDATE's row count from the command tag; a driver that could not would have raised, so a
    # falsy value here reads "the statement reported no rows", not "unknown".
    written = int(cur.rowcount or 0)  # nosemgrep: tq-py-missing-as-zero -- the UPDATE's own command tag, not a default

    # Same transaction, after the fill: a row whose +7d close was just found has become scoreable.
    cur.execute(_SCORE_CANDIDATES_SQL)
    for row in cur.fetchall():
        score = _outcome_score(row["recommendation"], row["price_at_decision"], row["price_7d"])
        if score is not None:
            cur.execute(_SCORE_UPDATE_SQL, (score, row["id"]))

    conn.commit()
    conn.close()
    print(f"[outcomes] Filled prices on {written} decision outcomes")
    return written


def dry_run(backfill: bool) -> dict:
    """Read-only preview. ``record_current_decisions`` / ``backfill_prices`` are not reachable from here."""
    import psycopg2.extras
    lr = _receipt_lib()
    conn = _get_conn()
    lr.enforce_readonly(conn)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    decisions = _select_decisions(cur)
    out = {"would_record": len(decisions),
           "would_record_no_price": sum(1 for d in decisions if not d.get("latest_price"))}
    print(f"[outcomes] DRY-RUN would record {len(decisions)} new decision outcomes")
    if backfill:
        cur.execute(_FILL_PREVIEW_SQL)
        r = cur.fetchone()
        if not r:  # a dry run that cannot measure its own preview must say so, never print a wall of zeros
            raise RuntimeError("the fill preview returned no count row")
        out.update(would_backfill=int(r["would_backfill"]),
                   would_fill={"1d": int(r["fill_1d"]), "7d": int(r["fill_7d"]),
                               "30d": int(r["fill_30d"]),
                               "decision_id": int(r["fill_id"])})
        print(f"[outcomes] DRY-RUN would fill prices on {out['would_backfill']} decision outcomes "
              f"(1d {out['would_fill']['1d']}, 7d {out['would_fill']['7d']}, 30d {out['would_fill']['30d']}, "
              f"decision_id {out['would_fill']['decision_id']})")
    conn.close()
    would_write = ["decision_outcomes (INSERT) x would_record"]
    if backfill:
        would_write.append("decision_outcomes (UPDATE price_*/decision_id) x would_backfill")
    lr.dry_run_report(LANE_ID, out, would_write=would_write)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Record and backfill decision outcomes")
    ap.add_argument("--backfill", action="store_true",
                    help="kept for compatibility; the backfill is now part of a real run")
    ap.add_argument("--no-backfill", action="store_true", help="record new outcomes only; fill no prices")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="read-only preview; writes nothing")
    args = ap.parse_args(argv)
    backfill = not args.no_backfill

    if args.dry_run:
        out = dry_run(backfill)
        if args.json:
            print(json.dumps(out, indent=2))
        return 0

    lr = _receipt_lib()
    started = datetime.now(timezone.utc).isoformat()
    summary: dict = {}
    try:
        summary["recorded"] = record_current_decisions()
        if backfill:
            summary["backfilled"] = backfill_prices()
    except Exception as exc:
        # Report what this run already wrote and committed, not a flat zero: the INSERT step commits on its own.
        # Each key is set only after its step committed, so an absent key means that step never completed and wrote
        # nothing -- a fact, not an unknown.
        produced = int(summary.get("recorded") or 0) + int(summary.get("backfilled") or 0)  # nosemgrep: tq-py-missing-as-zero -- see above
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="record_decision_outcome.py", summary=summary,
                              error=f"{type(exc).__name__}: {exc}",
                              output={"produced_count": produced, "attempted_count": produced,
                                      "skipped_reasons": {"dependency_unavailable": 1}})
        raise
    if args.json:
        print(json.dumps(summary, indent=2))
    # LaneRunReceipt@v2 output (n8n expected_output, produced_field produced_count): the rows this run wrote --
    # inserted outcomes + prices filled. None of either is a correct outcome for this lane; it says so.
    # Absent = that step did not run (--no-backfill) or committed nothing, not an unknown value.
    written = int(summary.get("recorded") or 0) + int(summary.get("backfilled") or 0)  # nosemgrep: tq-py-missing-as-zero -- see above
    lr.write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=started,
                          script="record_decision_outcome.py", summary=summary,
                          output={"produced_count": written, "attempted_count": written, "skipped_reasons": {},
                                  "empty_reason": None if written else "no_new_input"})
    return 0


if __name__ == "__main__":
    ROOT = PROJECT_ROOT
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    sys.exit(main())
