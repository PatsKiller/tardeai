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
try:  # load .env so DB/LLM creds resolve under cron's minimal env (2026-06-15)
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

PROMPT = """You are a sharp trading-journal coach. Classify this CLOSED round-trip, grade it, and write ONE specific lesson. Reply ONLY with JSON.

Symbol: {symbol}  Account: {account}
Entry: ${entry_price} on {entry_time}
Exit: ${exit_price} on {exit_time}
Hold: {hold_label}   Shares: {qty}
Net P&L: ${net_pnl} ({pnl_pct}%)   Heuristic type: {classification}

LESSON RULES (strict — generic advice is rejected):
- Tie it to THIS trade's actual numbers (hold length, P&L size, % move).
- Do NOT mention "stop-loss"/"tighten stops" UNLESS the loss clearly came from a stop set too wide or absent.
- Long hold (>30 days) that LOST: address thesis invalidation, exit discipline, or opportunity cost — not stops.
- Scalp/day-trade: address entry timing or execution quality.
- A winner: name the specific thing to REPEAT.
One concrete sentence, no boilerplate.

Return JSON exactly:
{{"strategy": "<scalp|momentum|breakout|swing|mean_reversion|news_catalyst|position_trim|other>",
 "entry_grade": "<A|B|C|D|F>", "exit_grade": "<A|B|C|D|F>", "lesson": "<specific sentence>"}}"""


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


def run(limit=None, do_all=False, lane="deepseek-flash"):
    import llm_lane
    if not llm_lane.available(lane):
        lane = "local"
    conn = _conn(); cur = conn.cursor()
    # Stage 2a: canary test orders are never classified/graded — they aren't trading decisions
    where = "WHERE canary IS NOT TRUE" if do_all else "WHERE reviewed_at IS NULL AND canary IS NOT TRUE"
    cur.execute(f"""SELECT id, account, symbol, entry_time, exit_time, hold_minutes, qty, entry_price,
                      exit_price, net_pnl, pnl_pct, classification
                    FROM schwab_round_trips {where} ORDER BY abs(net_pnl) DESC NULLS LAST
                    {'LIMIT ' + str(int(limit)) if limit else ''}""")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    done = fail = 0
    for r in rows:
        hm = r.get("hold_minutes") or 0
        r["hold_label"] = f"{hm} minutes" if hm < 390 else f"{round(hm / 1440)} days"
        try:
            out = llm_lane.generate(PROMPT.format(**r), lane=lane, timeout=90)
            p = _parse(out)
        except Exception:
            p = None
        if not p:
            fail += 1; continue
        cur.execute("""UPDATE schwab_round_trips SET strategy_tag=%s, entry_grade=%s, exit_grade=%s,
                       lesson=%s, review_lane=%s, reviewed_at=NOW() WHERE id=%s""",
                    (p["strategy"], p["entry_grade"], p["exit_grade"], p["lesson"], lane, r["id"]))
        conn.commit(); done += 1
    print(json.dumps({"reviewed": done, "failed": fail, "total": len(rows)}, indent=2))
    return {"reviewed": done, "failed": fail}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--lane", default="grok", choices=["grok", "local"])
    a = ap.parse_args()
    run(limit=a.limit, do_all=a.all, lane=a.lane)


if __name__ == "__main__":
    main()
