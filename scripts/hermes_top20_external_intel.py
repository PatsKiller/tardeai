#!/usr/bin/env python3
"""hermes_top20_external_intel.py — curate the top-N Hermes-ranked watchlist names into a well-formatted
context and send each to the FREE external LLM lanes (ChatGPT via openai-codex OAuth + Grok via xAI) for
enhanced intelligence. Reuses hermes_external_researcher.py (auth, capability cache, storage to
hermes_external_research). ADVISORY — never trades.

Skips a (symbol, lane) pair already researched in the last FRESH_HOURS. Cadence via cron.

  python3 scripts/hermes_top20_external_intel.py [--top 20] [--lanes chatgpt,grok] [--apply]
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
FRESH_HOURS = 12


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _top(conn, n):
    cur = conn.cursor()
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, hermes_rank, hermes_composite_score,
                     hermes_score_components, rsi, trend
                   FROM watchlist_items WHERE hermes_rank IS NOT NULL AND hermes_rank <= %s
                   ORDER BY symbol, hermes_composite_score DESC""", (n,))
    rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
    rows.sort(key=lambda r: r["hermes_rank"])
    return rows


def _question(r):
    c = r.get("hermes_score_components") or {}
    facs = "; ".join(f"{k}={v.get('score')}({v.get('detail')})" for k, v in c.items() if not k.startswith("_"))
    return (
        f"You are an elite equity analyst. {r['symbol']} ranks #{r['hermes_rank']} on our watchlist "
        f"(internal composite {r['hermes_composite_score']}/100, confidence {c.get('_confidence')}). "
        f"RSI {r.get('rsi')}, trend {r.get('trend')}. Factor reads — {facs}. "
        "Give ENHANCED intelligence, concise and specific (no boilerplate): "
        "(1) your conviction high/medium/low + a one-line thesis; "
        "(2) the 2-3 most important catalysts or risks we may be missing; "
        "(3) is the current trade setup valid — better entry / invalidation level; "
        "(4) any competitive or sector dynamic that changes the picture. "
        "End with a single line: VERDICT: <bullish|neutral|bearish> | CONVICTION: <high|med|low>."
    )


def _recent(conn, symbol, lane):
    cur = conn.cursor()
    cur.execute("""SELECT 1 FROM hermes_external_research WHERE symbol=%s AND lane=%s
                   AND created_at > now() - interval '%s hours'
                   AND status IN ('sent','ok','complete','success') LIMIT 1""",
                (symbol, lane, FRESH_HOURS))
    return cur.fetchone() is not None


def run(top=20, lanes=("chatgpt", "grok"), apply=False):
    conn = _conn()
    rows = _top(conn, top)
    report = {"top": len(rows), "lanes": list(lanes), "called": 0, "skipped": 0, "detail": []}
    for r in rows:
        q = _question(r)
        for lane in lanes:
            if _recent(conn, r["symbol"], lane):
                report["skipped"] += 1
                continue
            if not apply:
                report["detail"].append({"symbol": r["symbol"], "lane": lane, "action": "dry-run"})
                continue
            try:
                cp = subprocess.run(
                    [sys.executable, str(PROJECT_ROOT / "scripts" / "hermes_external_researcher.py"),
                     "--lane", lane, "--symbol", r["symbol"], "--question", q,
                     "--trigger", "top20_curation", "--priority", "P2", "--apply"],
                    cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=180)
                ok = cp.returncode == 0
                report["called"] += 1 if ok else 0
                report["detail"].append({"symbol": r["symbol"], "lane": lane, "ok": ok})
            except Exception as e:
                report["detail"].append({"symbol": r["symbol"], "lane": lane, "error": str(e)[:80]})
    print(json.dumps({k: report[k] for k in ("top", "lanes", "called", "skipped")}, indent=2))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--lanes", default="chatgpt,grok")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    run(top=a.top, lanes=tuple(x.strip() for x in a.lanes.split(",") if x.strip()), apply=a.apply)


if __name__ == "__main__":
    main()
