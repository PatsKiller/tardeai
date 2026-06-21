#!/usr/bin/env python3
"""prewarm_retirement_ensemble.py — pre-warm the multi-LLM ensemble for the top-N RetirementHub
'Planning Research' items so the retirement/finance/risk sub-scores are already present when the operator
opens the card (instead of waiting on the on-demand '⚖ Ensemble' click).

Mirrors the UI exactly: same data source (hermes_research_intelligence topic_research, theme-filtered),
the same target_id slug the RetirementHub card computes (`ret_<slugged-topic>`, target_type='signal'), and
the same content (topic + thesis + summary). The free-lane ensemble worker then validates the enqueued
jobs and persists results that the card's GET /api/v2/inference/ensemble lookup finds by (target_type,
target_id). Idempotent: skips items that already have a fresh result or an open job.

  python3 scripts/prewarm_retirement_ensemble.py                 # dry-run (default)
  python3 scripts/prewarm_retirement_ensemble.py --apply         # enqueue
  python3 scripts/prewarm_retirement_ensemble.py --apply --limit 16 --fresh-days 5
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_adapter import _get_conn

# Same theme set as api_v2._retirement_planning_research (only themed items appear in the UI).
THEMES = [
    r"roth|conversion|golden window|rmd", r"medicare|irmaa|part b|part d",
    r"medicaid|mapt|asset protection|lookback|spend.?down", r"estate|trust|probate|life estate|special needs",
    r"ssdi|social security|tax|magi|irs", r"dividend|covered call|jepi|income|cef|pty|nav|bond|annuit",
]
_THEME_RX = re.compile("|".join(THEMES), re.I)


def ui_slug(topic: str) -> str:
    """Replicate the RetirementHub slug(): 'ret_' + lower, non-alnum→_, trim _, cap 50."""
    c = re.sub(r"[^a-z0-9]+", "_", (topic or "").lower())
    c = re.sub(r"^_+|_+$", "", c)
    return "ret_" + c[:50]


def _rank(status: str) -> int:
    return 2 if status in ("promoted", "embedded") else 1 if status == "staged" else 0


def gather(limit: int):
    cur = _get_conn().cursor()
    cur.execute("""SELECT topic, summary, thesis, confidence_score, status, created_at
                   FROM hermes_research_intelligence
                   WHERE research_type='topic_research'
                   ORDER BY created_at DESC LIMIT 400""")
    seen, items = set(), []
    for topic, summary, thesis, conf, status, at in cur.fetchall():
        blob = f"{topic or ''} {summary or ''}"
        if not _THEME_RX.search(blob):
            continue
        key = (topic or "")[:60]
        if key in seen:
            continue
        seen.add(key)
        items.append({"topic": topic, "summary": summary or "", "thesis": thesis or "",
                      "confidence": float(conf) if conf is not None else 0.0,
                      "status": status or "", "at": str(at or "")})
    # same prioritization as the UI: researched/promoted → confidence → recency
    items.sort(key=lambda x: (_rank(x["status"]), x["confidence"], x["at"]), reverse=True)
    return items[:limit]


def _has_fresh(cur, tid: str, fresh_days: int) -> bool:
    cur.execute("""SELECT 1 FROM inference_ensemble_results
                   WHERE target_type='signal' AND target_id=%s
                     AND created_at > NOW() - make_interval(days => %s) LIMIT 1""", (tid, fresh_days))
    return cur.fetchone() is not None


def _has_open_job(cur, tid: str) -> bool:
    cur.execute("""SELECT 1 FROM inference_ensemble_jobs
                   WHERE target_type='signal' AND target_id=%s AND status IN ('queued','running') LIMIT 1""", (tid,))
    return cur.fetchone() is not None


def run(apply: bool, limit: int, fresh_days: int) -> int:
    conn = _get_conn(); cur = conn.cursor()
    items = gather(limit)
    enqueued = skipped = 0
    print(f"{'APPLY' if apply else 'DRY-RUN'} · top {len(items)} planning-research items (fresh window {fresh_days}d)")
    for it in items:
        tid = ui_slug(it["topic"])
        if _has_fresh(cur, tid, fresh_days):
            skipped += 1; print(f"  · warm   {tid[:46]:<46} {it['topic'][:48]}"); continue
        if _has_open_job(cur, tid):
            skipped += 1; print(f"  · queued {tid[:46]:<46} {it['topic'][:48]}"); continue
        print(f"  → enqueue {tid[:46]:<46} [{it['status']}/{it['confidence']:.2f}] {it['topic'][:44]}")
        enqueued += 1
        if apply:
            content = f"{it['topic']}\n{it['thesis']}\n{it['summary']}"[:1200]
            cur.execute("""INSERT INTO inference_ensemble_jobs
                             (target_type, target_id, subject, content, task, requested_by, status)
                           VALUES ('signal', %s, %s, %s, 'retirement_planning', 'prewarm_cron', 'queued')""",
                        (tid, it["topic"][:300], content))
    if apply:
        conn.commit()
    print(f"\n{'✓ enqueued' if apply else 'would enqueue'} {enqueued} · skipped {skipped} (already warm/queued)")
    if not items:
        print("(no themed planning-research items found)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--fresh-days", type=int, default=7)
    a = ap.parse_args()
    sys.exit(run(a.apply, a.limit, a.fresh_days))
