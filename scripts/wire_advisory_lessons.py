#!/usr/bin/env python3
"""wire_advisory_lessons.py — extract the LESSON + TRADE GRADE from each external Grok/ChatGPT
paper-trade post-mortem advisory (hermes_external_research, trigger 'paper_postmortem:<id>') and wire
it into the EXISTING learning pipeline: per-trade rows in trade_lesson_memory (lesson_category
'external_advisory', deduped per trade+lane), then refresh strategy_lesson_rollup so the external
lessons flow into the per-strategy learning digest + recommendations.

Advisory-gated (prop-desk discipline): rows are written human_review_only=TRUE — they ENRICH the
operator's learning view and the strategy rollup; they do not silently auto-mutate strategy configs.

Cron: right after paper_trade_advisory (every 6h).
    .venv/bin/python scripts/wire_advisory_lessons.py
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

_LESSON_RE = re.compile(r"LESSON:\s*(.+?)(?:\s*\|\s*(?:TRADE\s*)?GRADE:|\n|$)", re.I | re.S)
_GRADE_RE = re.compile(r"(?:TRADE\s*)?GRADE:\s*([A-F][+-]?)", re.I)

# Map a free-text lesson to a coarse mistake/category bucket (best-effort, for rollup grouping).
_BUCKETS = [
    ("stop", "stop_quality"), ("entry", "entry_timing"), ("chas", "entry_timing"),
    ("exit", "exit_discipline"), ("target", "exit_discipline"), ("hold", "holding_period"),
    ("size", "sizing"), ("catalyst", "data_quality"), ("strategy", "strategy_fit"),
]


def _db(sql, params=None, fetch="all"):
    from db_adapter import _execute
    return _execute(sql, params, fetch=fetch)


def _category(lesson: str) -> str:
    lo = (lesson or "").lower()
    for kw, cat in _BUCKETS:
        if kw in lo:
            return cat
    return "external_advisory"


def _grade_quality(g: str | None) -> str | None:
    if not g:
        return None
    g = g[0].upper()
    return {"A": "excellent", "B": "good", "C": "fair", "D": "poor", "F": "poor"}.get(g)


def main():
    rows = _db(
        """SELECT h.id AS adv_id, h.lane, h.symbol, h.recommendation, h.trigger_reason,
                  pt.id AS trade_id, pt.strategy_id, pt.exit_reason, pt.exit_time::date AS close_date,
                  pt.pnl, pt.dollar_risk
           FROM hermes_external_research h
           JOIN paper_trades pt ON pt.id = CAST(split_part(h.trigger_reason, ':', 2) AS INTEGER)
           WHERE h.trigger_reason LIKE 'paper_postmortem:%'
             AND COALESCE(h.recommendation,'') <> ''""", fetch="all") or []

    wired, skipped = 0, 0
    for r in rows:
        rec = str(r["recommendation"] or "")
        lesson_m = _LESSON_RE.search(rec)
        lesson = (lesson_m.group(1).strip() if lesson_m else rec.strip())[:600]
        grade = (_GRADE_RE.search(rec).group(1) if _GRADE_RE.search(rec) else None)
        # one external row per (trade, lane); the table's unique key is (trade_id, lesson_category,
        # source_payload). We pin lesson_category='external_advisory' and differentiate lanes via the hash.
        sph = hashlib.sha256(f"{r['trade_id']}:{r['lane']}:adv".encode()).hexdigest()[:32]
        rmult = None
        try:
            risk = float(r["dollar_risk"] or 0)
            rmult = round(float(r["pnl"] or 0) / risk, 3) if risk else None
        except Exception:
            rmult = None
        try:
            res = _db(
                """INSERT INTO trade_lesson_memory
                     (trade_id, symbol, strategy_id, close_date, exit_reason, dashboard_verdict,
                      exit_quality, mistake_type, lesson_category, improved_lesson, next_operator_action,
                      action_owner, pnl, r_multiple, human_review_only, source_payload_hash)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,%s)
                   ON CONFLICT (trade_id, lesson_category, source_payload_hash) DO UPDATE
                     SET improved_lesson=EXCLUDED.improved_lesson, exit_quality=EXCLUDED.exit_quality,
                         created_at=now()
                   RETURNING id""",
                (r["trade_id"], r["symbol"], r["strategy_id"], r["close_date"], r["exit_reason"],
                 f"external:{r['lane']}", _grade_quality(grade), _category(lesson),
                 "external_advisory", f"[{r['lane']}] {lesson}", lesson,
                 f"external_{r['lane']}", r["pnl"], rmult, sph),
                fetch="one")
            wired += 1 if res else 0
        except Exception as e:
            skipped += 1
            print(f"  skip trade {r['trade_id']} [{r['lane']}]: {str(e)[:100]}")

    print(f"[wire_advisory_lessons] wired {wired} external lesson(s), {skipped} skipped")

    # Refresh the per-strategy rollup so the external lessons reach the learning digest/recommendations.
    try:
        rb = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_strategy_lesson_rollup.py"), "--apply"],
                            cwd=str(ROOT), capture_output=True, text=True, timeout=180)
        print(f"[wire_advisory_lessons] strategy_lesson_rollup refresh rc={rb.returncode} {(rb.stdout or '')[-120:].strip()}")
    except Exception as e:
        print(f"[wire_advisory_lessons] rollup refresh error: {str(e)[:120]}")


if __name__ == "__main__":
    main()
