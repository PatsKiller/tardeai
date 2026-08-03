#!/usr/bin/env python3
"""journal_review_builder.py — LLM entry/exit grade + lesson for REAL closed trades into the journal's
review store (journal_trade_reviews). Paper closed trades (trades view, source=paper_trades) by default;
Schwab round-trips already carry grade+lesson in schwab_round_trips (Journal→Real Accounts).

Idempotent: skips trades already reviewed (by trade_key = symbol:account:close_date). Read-only of facts.

  python3 scripts/journal_review_builder.py [--limit N]
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
GRADE_TO_SCORE = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}

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


def run(limit=None, lane="deepseek-flash"):
    import llm_lane
    if not llm_lane.available(lane):
        lane = "local"
    conn = _conn(); cur = conn.cursor()
    cur.execute(f"""SELECT symbol, account, exit_date::date AS cd, strategy_id, entry_price, exit_price,
                      shares, pnl, exit_reason
                    FROM trades WHERE status='closed' AND source_table='paper_trades'
                      AND entry_price > 0 AND exit_price > 0
                    ORDER BY exit_date DESC {'LIMIT ' + str(int(limit)) if limit else ''}""")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    done = skip = fail = 0
    for r in rows:
        tk = f"{r['symbol']}:{r['account']}:{r['cd']}"
        cur.execute("SELECT 1 FROM journal_trade_reviews WHERE trade_key=%s", (tk,))
        if cur.fetchone():
            skip += 1; continue
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
    print(json.dumps({"reviewed": done, "skipped_existing": skip, "failed": fail, "candidates": len(rows)}, indent=2))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--lane", default="grok", choices=["grok", "local"])
    a = ap.parse_args(); run(limit=a.limit, lane=a.lane)


if __name__ == "__main__":
    main()
