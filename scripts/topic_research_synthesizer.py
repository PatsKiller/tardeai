#!/usr/bin/env python3
"""topic_research_synthesizer.py — actually RESEARCH the staged topic_research rows with real LLM analysis,
instead of leaving them as placeholder enqueue-markers ("Research topic 'X' from the Registry").

The topic bridge stages a placeholder row; the coordinator only flips its status. Nothing was writing real
research content — so the RetirementHub Planning Research tab showed empty markers. This fills each row with
a genuine, grounded research summary + thesis using the FREE LLM lanes (grok :8645 → chatgpt :8646 → local
gemma), in the operator's planning context. Advisory only; never a trade. Idempotent (skips rows already
synthesized, i.e. model_used != 'topic_monitor_bridge').

  python3 scripts/topic_research_synthesizer.py [--max 20] [--apply]   (default dry-run)
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_adapter import _get_conn


def _prompt(topic, context):
    ctx = f"\nInvestor context: {context}" if context else ""
    return (
        f'Research this topic for an individual investor and write a concise, factual briefing.{ctx}\n\n'
        f'TOPIC: "{topic}"\n\n'
        'Return ONLY a JSON object, no prose:\n'
        '{"summary": "120-180 words: what it is, the key facts/numbers, and why it matters for this '
        'investor", "thesis": "one-sentence actionable takeaway", "considerations": ["3-5 specific points: '
        'rules, thresholds, trade-offs, or risks"], "confidence": 0.0-1.0}\n'
        'Be specific and current (2026). If it involves tax/Medicare/Medicaid/estate law, note that a '
        'professional (elder-law attorney / tax advisor) should confirm. Do not fabricate exact figures you '
        'are unsure of — say "verify current figure".'
    )


def _synthesize(topic, context):
    try:
        import llm_lane
    except Exception:
        return None
    for lane in ("grok", "chatgpt", "local"):
        try:
            if not llm_lane.available(lane):
                continue
            raw = llm_lane.generate(_prompt(topic, context), lane=lane, timeout=70)
            m = re.search(r"\{.*\}", raw or "", re.S)
            if not m:
                continue
            d = json.loads(m.group())
            summ = (d.get("summary") or "").strip()
            if len(summ) < 60:
                continue
            cons = d.get("considerations") or []
            if cons:
                summ += "\n\nKey points: " + " · ".join(str(c).strip() for c in cons[:5] if str(c).strip())
            conf = d.get("confidence")
            conf = float(conf) if isinstance(conf, (int, float)) and 0 <= conf <= 1 else 0.6
            return {"summary": summ[:1800], "thesis": (d.get("thesis") or "").strip()[:400],
                    "confidence": round(conf, 2), "lane": lane}
        except Exception:
            continue
    return None


def run(apply=False, max_rows=20):
    conn = _get_conn(); cur = conn.cursor()
    # un-synthesized topic_research rows (still the bridge placeholder)
    cur.execute("""SELECT id, topic, evidence_json FROM hermes_research_intelligence
                   WHERE research_type='topic_research' AND model_used='topic_monitor_bridge'
                     AND summary ILIKE 'Research topic%%'
                   ORDER BY created_at DESC LIMIT %s""", (max_rows,))
    rows = cur.fetchall()
    done, skipped = [], 0
    for rid, topic, ev in rows:
        ev = ev if isinstance(ev, dict) else (json.loads(ev) if ev else {})
        # personal context from the linked topic_monitor row
        ctx = ""
        tmid = ev.get("topic_monitor_id")
        if tmid:
            cur.execute("SELECT personal_context FROM topic_monitor WHERE topic_id=%s", (tmid,))
            r2 = cur.fetchone()
            ctx = (r2[0] if r2 else "") or ""
        res = _synthesize(topic, ctx)
        if not res:
            skipped += 1
            continue
        done.append({"id": rid, "topic": (topic or "")[:50], "lane": res["lane"], "len": len(res["summary"])})
        if apply:
            cur.execute("""UPDATE hermes_research_intelligence
                           SET summary=%s, thesis=%s, confidence_score=%s,
                               model_used=%s, updated_at=now()
                           WHERE id=%s""",
                        (res["summary"], res["thesis"], res["confidence"],
                         f"synth:{res['lane']}", rid))
    if apply:
        conn.commit()
    print(json.dumps({"mode": "APPLIED" if apply else "DRY-RUN", "candidates": len(rows),
                      "synthesized": len(done), "no_lane_result": skipped,
                      "sample": done[:6]}, indent=2))
    return 0


def main():
    from dotenv import load_dotenv
    load_dotenv(str(Path(__file__).resolve().parent.parent / ".env"))
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=20)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    return run(apply=a.apply, max_rows=a.max)


if __name__ == "__main__":
    raise SystemExit(main())
