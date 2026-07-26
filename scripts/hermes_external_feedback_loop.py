#!/usr/bin/env python3
"""hermes_external_feedback_loop.py — score the usefulness of external-researcher recommendations and feed
the signal back into the learning system (Phase 213 gap #2). ADVISORY-ONLY.

For each scored-eligible hermes_external_research row (status='sent', usefulness_score IS NULL), rate the
recommendation's usefulness 0.0–1.0 via the LOCAL model (gemma3 — intrinsic actionability/specificity/
grounding), enhanced by the symbol's realized outcome AFTER the research date when available. Writes
usefulness_score + a feedback note into evidence_json. NEVER touches broker/order/stop/proposal/scoring —
the per-lane usefulness aggregate is advisory input to lane routing only.

  python3 scripts/hermes_external_feedback_loop.py            # dry-run
  python3 scripts/hermes_external_feedback_loop.py --apply
"""
import os, sys, json, argparse, urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KILL = ROOT / "data" / "runtime" / "HERMES_DISABLED"
OLLAMA = "http://127.0.0.1:11434/api/chat"
for ln in (ROOT / ".env").read_text().splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip())
import psycopg2


def _db():
    return psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
                            user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"))


def _outcome(cur, symbol, after):
    """Realized pnl on the symbol for trades closed AFTER the research date (forward-looking outcome)."""
    if not symbol:
        return None
    try:
        cur.execute("""SELECT count(*), coalesce(sum(realized_pnl),0) FROM trade_instances
                       WHERE symbol=%s AND lower(coalesce(status,''))='closed'
                         AND close_date > %s""", (symbol, after))
        n, pnl = cur.fetchone()
        return {"closed_trades_after": int(n), "realized_pnl_after": float(pnl)} if n else None
    except Exception:
        cur.connection.rollback(); return None


def _rate(question, recommendation, dissent, outcome, model):
    """Local-LLM usefulness rating 0..1 (intrinsic + outcome-aware). Falls back to 0.5 if unavailable."""
    prompt = (f"Rate how USEFUL this external research recommendation is for a paper-trading research system. "
              f"Judge actionability, specificity, and grounding. This is advisory; do not suggest trading.\n"
              f"Question: {question}\nRecommendation: {recommendation}\nDissent: {dissent}\n"
              f"Realized outcome since (if any): {json.dumps(outcome)}\n"
              f'Return ONLY JSON: {{"usefulness": 0.0-1.0, "rationale": "one sentence"}}')
    try:
        body = json.dumps({"model": model, "stream": False, "format": "json",
                           "messages": [{"role": "user", "content": prompt}],
                           "options": {"num_ctx": 4096 if ("12b" in model or "27b" in model) else 8192,
                                       "num_predict": 200, "temperature": 0.2}}).encode()
        req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
        content = json.loads(urllib.request.urlopen(req, timeout=120).read()).get("message", {}).get("content", "")
        d = json.loads(content[content.find("{"):content.rfind("}") + 1])
        u = max(0.0, min(1.0, float(d.get("usefulness", 0.5))))
        return u, str(d.get("rationale", ""))[:240]
    except Exception as e:
        return 0.5, f"(neutral fallback — local rater unavailable: {str(e)[:60]})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--model", default="gemma3:4b")
    ap.add_argument("--max-rows", type=int, default=25)
    args = ap.parse_args()
    if KILL.exists():
        print("ABORT: kill-switch present"); sys.exit(2)
    c = _db(); cur = c.cursor()
    cur.execute("""SELECT id, lane, symbol, question, recommendation, dissent, created_at
                   FROM hermes_external_research
                   WHERE status='sent' AND usefulness_score IS NULL AND recommendation IS NOT NULL
                   ORDER BY id ASC LIMIT %s""", (args.max_rows,))
    rows = cur.fetchall()
    print(f"Hermes External Feedback Loop — eligible={len(rows)} apply={args.apply} model={args.model}")
    scored = 0
    for rid, lane, symbol, question, rec, dissent, created in rows:
        outcome = _outcome(cur, symbol, created)
        u, rationale = _rate(question, rec, dissent, outcome, args.model)
        fb = {"usefulness_feedback": {"scored_by": f"local:{args.model}", "scored_at": datetime.now().isoformat(),
              "outcome": outcome, "rationale": rationale}}
        print(f"  id={rid} lane={lane} sym={symbol or '-'} usefulness={u:.2f} outcome={outcome} :: {rationale[:80]}")
        if args.apply:
            note = f"usefulness={u:.2f} ({rationale}); outcome={json.dumps(outcome)}; scored_by=local:{args.model}"
            cur.execute("""UPDATE hermes_external_research
                           SET usefulness_score=%s, learning_candidate=%s WHERE id=%s""",
                        (u, note[:500], rid))
            c.commit()   # commit per-row so one bad row can't drop the batch
            scored += 1
    if args.apply:
        c.commit()
    # per-lane learning signal (advisory)
    cur.execute("""SELECT lane, count(*), round(avg(usefulness_score)::numeric,3)
                   FROM hermes_external_research WHERE usefulness_score IS NOT NULL GROUP BY lane ORDER BY 3 DESC""")
    agg = [{"lane": r[0], "scored": int(r[1]), "avg_usefulness": float(r[2])} for r in cur.fetchall()]
    c.close()
    print("RESULT:", json.dumps({"scored_now": scored, "per_lane_usefulness": agg}))


if __name__ == "__main__":
    main()
