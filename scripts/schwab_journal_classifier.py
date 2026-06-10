#!/usr/bin/env python3
"""schwab_journal_classifier.py — LLM strategy classification + journal review for Schwab round-trips.

For each closed round-trip in schwab_round_trips, asks the local LLM to tag the strategy and grade the
entry/exit with a one-line lesson. Read-only of facts; writes only the enrichment columns. Idempotent —
only processes rows not yet reviewed (unless --all).

  python3 scripts/schwab_journal_classifier.py [--limit N] [--all]
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

PROMPT = """You are a trading journal analyst. Classify this CLOSED round-trip and grade it. Reply ONLY with JSON.

Symbol: {symbol}  Account: {account}
Entry: ${entry_price} on {entry_time}
Exit: ${exit_price} on {exit_time}
Hold: {hold_minutes} minutes   Shares: {qty}
Net P&L: ${net_pnl} ({pnl_pct}%)   Heuristic type: {classification}

Return JSON exactly:
{{"strategy": "<one of: scalp, momentum, breakout, swing, mean_reversion, news_catalyst, position_trim, other>",
 "entry_grade": "<A|B|C|D|F>", "exit_grade": "<A|B|C|D|F>",
 "lesson": "<one specific sentence: what to repeat or fix>"}}"""


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _parse(raw):
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return {"strategy": str(d.get("strategy", "other"))[:40],
                "entry_grade": str(d.get("entry_grade", "C"))[:2],
                "exit_grade": str(d.get("exit_grade", "C"))[:2],
                "lesson": str(d.get("lesson", ""))[:300]}
    except Exception:
        return None


def run(limit=None, do_all=False):
    import local_llm
    conn = _conn(); cur = conn.cursor()
    where = "" if do_all else "WHERE reviewed_at IS NULL"
    cur.execute(f"""SELECT id, account, symbol, entry_time, exit_time, hold_minutes, qty, entry_price,
                      exit_price, net_pnl, pnl_pct, classification
                    FROM schwab_round_trips {where} ORDER BY abs(net_pnl) DESC NULLS LAST
                    {'LIMIT ' + str(int(limit)) if limit else ''}""")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    done = fail = 0
    for r in rows:
        try:
            out = local_llm.generate(PROMPT.format(**r), timeout=90)
            p = _parse(out)
        except Exception:
            p = None
        if not p:
            fail += 1; continue
        cur.execute("""UPDATE schwab_round_trips SET strategy_tag=%s, entry_grade=%s, exit_grade=%s,
                       lesson=%s, reviewed_at=NOW() WHERE id=%s""",
                    (p["strategy"], p["entry_grade"], p["exit_grade"], p["lesson"], r["id"]))
        conn.commit(); done += 1
    print(json.dumps({"reviewed": done, "failed": fail, "total": len(rows)}, indent=2))
    return {"reviewed": done, "failed": fail}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    run(limit=a.limit, do_all=a.all)


if __name__ == "__main__":
    main()
