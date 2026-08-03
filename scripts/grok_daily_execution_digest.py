#!/usr/bin/env python3
"""grok_daily_execution_digest.py — Grok summary of the deterministic coaching queue (advisory, strict JSON).

Feeds the COMPUTED coaching items (not raw trades) to Grok -> a strict-JSON daily digest stored in
daily_execution_grok_digests. Grok interprets; it does NOT authorize any live change. Parse-strict: a bad
response is stored review_status='parse_failed', never fabricated.

  python3 scripts/grok_daily_execution_digest.py --apply           # latest run
  python3 scripts/grok_daily_execution_digest.py --run-id 1 --apply
"""
import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
PROMPT_VERSION = "daily_coach_v1"

PROMPT = """You are a trading-execution coach producing a DAILY digest. Below are ALREADY-COMPUTED, ranked
coaching items from deterministic replay metrics (volume confirmation, capture ratio, missed runners,
hypothesis backtests). Interpret them — do NOT invent numbers or recommend changing any live strategy config.
Hypotheses are shadow-research only. Be specific.

Window summary: {summary}
Top coaching items (rank | type | n | lesson):
{items}
Hypothesis verdicts (evidence-only): {hyps}

Return STRICT JSON ONLY, exactly these keys:
{{"daily_headline": "...", "top_behavior_to_fix": "...", "top_3_lessons": ["...","...","..."],
"symbols_to_replay": ["..."], "strategies_to_review": ["..."], "do_not_overfit_warning": "...",
"shadow_research_candidates": [{{"hypothesis":"...","why":"...","sample_size":0,"status":"shadow_only"}}],
"operator_checklist": ["...","..."], "confidence": 0.0}}"""


def _parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    req = {"daily_headline", "top_behavior_to_fix", "top_3_lessons", "symbols_to_replay",
           "strategies_to_review", "do_not_overfit_warning", "shadow_research_candidates",
           "operator_checklist", "confidence"}
    return d if req.issubset(d.keys()) else None


def run(run_id=None, apply=False, lane="deepseek-flash"):
    import psycopg2.extras, llm_lane
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if not run_id:
        cur.execute("SELECT id FROM daily_execution_coaching_runs ORDER BY id DESC LIMIT 1")
        r = cur.fetchone()
        if not r:
            print(json.dumps({"status": "NO_RUNS"})); return
        run_id = r["id"]
    cur.execute("SELECT summary FROM daily_execution_coaching_runs WHERE id=%s", (run_id,))
    summary = (cur.fetchone() or {}).get("summary", "")
    cur.execute("SELECT rank, item_type, sample_size, lesson FROM daily_execution_coaching_items WHERE run_id=%s ORDER BY rank LIMIT 14", (run_id,))
    items = cur.fetchall()
    cur.execute("SELECT item_type, lesson FROM daily_execution_coaching_items WHERE run_id=%s AND item_type='hypothesis_candidate'", (run_id,))
    hyps = "; ".join(h["lesson"][:100] for h in cur.fetchall()) or "none"
    item_txt = "\n".join(f"  {it['rank']} | {it['item_type']} | n={it['sample_size']} | {it['lesson'][:120]}" for it in items)
    prompt = PROMPT.format(summary=summary, items=item_txt, hyps=hyps)
    try:
        text = llm_lane.generate(prompt, lane=lane, timeout=120)
    except Exception as e:
        print(json.dumps({"status": "lane_error", "error": str(e)[:120]})); return
    parsed = _parse(text)
    status = "ok" if parsed else "parse_failed"
    if apply:
        wcur = conn.cursor()
        wcur.execute("""INSERT INTO daily_execution_grok_digests (run_id, model_lane, prompt_version, digest_json, review_status)
                        VALUES (%s,%s,%s,%s,%s)""", (run_id, lane, PROMPT_VERSION, json.dumps(parsed or {"raw": text[:500]}), status))
        conn.commit()
    print(json.dumps({"run_id": run_id, "status": status, "digest": parsed}, indent=2, default=str))
    return {"status": status, "digest": parsed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", type=int)
    ap.add_argument("--lane", default="grok")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    run(a.run_id, a.apply, a.lane)


if __name__ == "__main__":
    main()
