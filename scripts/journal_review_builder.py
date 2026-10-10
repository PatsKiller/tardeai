#!/usr/bin/env python3
"""journal_review_builder.py — LLM entry/exit grade + lesson for REAL closed trades into the journal's
review store (journal_trade_reviews). Paper closed trades (trades view, source=paper_trades) by default;
Schwab round-trips already carry grade+lesson in schwab_round_trips (Journal→Real Accounts).

Idempotent: skips trades already reviewed (by trade_key = symbol:account:close_date). Read-only of facts.

  python3 scripts/journal_review_builder.py [--limit N] [--dry-run]

Lane journal-review-builder (cron L457).

--dry-run (AGENTS.md §6): reads the candidate closed trades and the already-reviewed keys through a
READ ONLY session (lane_last_receipt.enforce_readonly) and returns BEFORE llm_lane is imported, so no
model call (paid or local) and no INSERT/commit is reachable. It prints the would-review count and keys
in one DRY-RUN report line; no receipt.

A real run writes <state_root>/data/runtime/journal-review-builder_last.json (LaneRunReceipt@v1; ok_at
only on success). Exit codes: 0 = ran (nothing new to review is 0; some reviews failing while others
were written is 0, counted in ``failed``); 1 = the run failed: crash / DB unavailable, or there were
trades to review and EVERY one failed (no LLM lane, unparseable replies); 2 = usage error.
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
GRADE_TO_SCORE = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}
LANE_ID = "journal-review-builder"


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.journal_review_builder
        from scripts.lib import lane_last_receipt as lr
    return lr

PROMPT = """You are a sharp trading-journal coach. Review this CLOSED trade. Reply ONLY with JSON.

Symbol {symbol} | account {account} | strategy {strategy_id}
Entry ${entry_price} -> Exit ${exit_price} | shares {shares} | P&L ${pnl} | exit: {exit_reason}

LESSON RULES (strict — generic advice is rejected):
- Tie it to THIS trade's actual numbers and exit reason.
- Do NOT mention "stop-loss"/"tighten stops" UNLESS the loss clearly came from a stop set too wide or absent.
- A winner: name the specific thing to REPEAT. A loser: name the specific decision that caused it.
One concrete sentence, no boilerplate.

Return JSON exactly:
{{"setup": "<short setup name>", "entry_grade": "<A|B|C|D|F>", "exit_grade": "<A|B|C|D|F>",
 "lesson": "<specific sentence>", "strengths": ["<short tag>"], "mistakes": ["<short tag>"]}}"""


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _parse(raw):
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return {"setup": str(d.get("setup", ""))[:60], "entry_grade": str(d.get("entry_grade", "C"))[:1].upper(),
                "exit_grade": str(d.get("exit_grade", "C"))[:1].upper(), "lesson": str(d.get("lesson", ""))[:300],
                "strengths": [str(s)[:30] for s in (d.get("strengths") or [])][:5],
                "mistakes": [str(s)[:30] for s in (d.get("mistakes") or [])][:5]}
    except Exception:
        return None


def pending_reviews(cur, limit=None):
    """Read-only: (candidates, rows still to review, skipped_existing). SELECTs only."""
    cur.execute(f"""SELECT symbol, account, exit_date::date AS cd, strategy_id, entry_price, exit_price,
                      shares, pnl, exit_reason
                    FROM trades WHERE status='closed' AND source_table='paper_trades'
                      AND entry_price > 0 AND exit_price > 0
                    ORDER BY exit_date DESC {'LIMIT ' + str(int(limit)) if limit else ''}""")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    todo, skip, seen = [], 0, set()
    for r in rows:
        tk = f"{r['symbol']}:{r['account']}:{r['cd']}"
        if tk in seen:  # same key twice in one pass: the first review covers it (as the interleaved loop did)
            skip += 1; continue
        cur.execute("SELECT 1 FROM journal_trade_reviews WHERE trade_key=%s", (tk,))
        if cur.fetchone():
            skip += 1; continue
        seen.add(tk)
        todo.append((tk, r))
    return rows, todo, skip


def run(limit=None, lane="grok", dry_run=False):
    conn = _conn()
    if dry_run:
        _receipt_lib().enforce_readonly(conn)
    cur = conn.cursor()
    rows, todo, skip = pending_reviews(cur, limit)
    if dry_run:
        # AGENTS.md §6: returns before llm_lane is imported and before any INSERT/commit.
        res = {"would_review": len(todo), "skipped_existing": skip, "candidates": len(rows),
               "lane_requested": lane, "trade_keys": [tk for tk, _ in todo[:20]]}
        print(json.dumps(res, indent=2, default=str))
        _receipt_lib().dry_run_report(LANE_ID, res, would_write=[
            f"journal_trade_reviews (insert) x {len(todo)} -- one {lane} LLM call each"])
        return res
    import llm_lane
    if not llm_lane.available(lane):
        lane = "local"
    done = fail = 0
    for tk, r in todo:
        try:
            p = _parse(llm_lane.generate(PROMPT.format(**r), lane=lane, timeout=90))
        except Exception:
            p = None
        if not p:
            fail += 1; continue
        cur.execute("""INSERT INTO journal_trade_reviews
                         (trade_key, symbol, account, closed_date, setup_name, execution_quality_score,
                          risk_management_score, lesson_learned, strength_tags, mistake_tags, coach_notes)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (tk, r["symbol"], r["account"], r["cd"], p["setup"], GRADE_TO_SCORE.get(p["entry_grade"], 3),
                     GRADE_TO_SCORE.get(p["exit_grade"], 3), p["lesson"], p["strengths"], p["mistakes"], f"{lane}_review"))
        conn.commit(); done += 1
    res = {"reviewed": done, "skipped_existing": skip, "failed": fail, "candidates": len(rows), "lane": lane}
    print(json.dumps(res, indent=2))
    return res


def main(argv=None) -> int:
    from datetime import datetime, timezone
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--lane", default="grok", choices=["grok", "local"])
    ap.add_argument("--dry-run", action="store_true", help="count what would be reviewed; no LLM call, no write")
    a = ap.parse_args(argv)
    if a.dry_run:
        try:
            run(limit=a.limit, lane=a.lane, dry_run=True)
        except Exception as exc:
            print(f"[journal_review] DRY-RUN failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        return 0
    started = datetime.now(timezone.utc).isoformat()
    try:
        res = run(limit=a.limit, lane=a.lane)
    except Exception as exc:
        _receipt_lib().write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                                          script="journal_review_builder.py", error=f"{type(exc).__name__}: {exc}")
        raise
    failed = res["failed"] > 0 and res["reviewed"] == 0
    rc = 1 if failed else 0
    _receipt_lib().write_lane_receipt(LANE_ID, ok=not failed, exit_code=rc, started_at=started,
                                      script="journal_review_builder.py", summary=res)
    return rc


if __name__ == "__main__":
    sys.exit(main())
