#!/usr/bin/env python3
"""backfill_hermes_strategy_tags.py — Populate strategy_tags on hermes_research_intelligence."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

_RULES = [
    (r"momentum.?scalp|scalp|rvol|intraday", "momentum_scalp"),
    (r"social|meme|reddit|twitter|x\.com", "social_route"),
    (r"swing|position|dividend|income", "swing"),
    (r"recovery|reentry", "recovery_watch"),
    (r"sector.?rotat", "sector_rotation"),
    (r"catalyst|earnings|fda|trial", "catalyst"),
    (r"protection|stop|risk", "risk_protection"),
    (r"holdings|portfolio|position", "holdings"),
]


def _infer_tags(text: str, research_type: str | None) -> list[str]:
    blob = f"{research_type or ''} {text or ''}".lower()
    tags = []
    for pat, tag in _RULES:
        if re.search(pat, blob, re.I):
            tags.append(tag)
    if not tags:
        tags.append("general_research")
    # dedupe preserve order
    seen = set()
    out = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:4]


def run(apply: bool = False, limit: int = 5000) -> dict:
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """SELECT id, topic, summary, thesis, research_type, tags
           FROM hermes_research_intelligence
           WHERE strategy_tags IS NULL OR cardinality(strategy_tags) = 0
           ORDER BY created_at DESC LIMIT %s""",
        (limit,),
    )
    rows = cur.fetchall()
    updated = 0
    samples = []
    for rid, topic, summary, thesis, rtype, existing in rows:
        stags = _infer_tags(f"{topic} {summary} {thesis}", rtype)
        if apply:
            cur.execute(
                "UPDATE hermes_research_intelligence SET strategy_tags=%s WHERE id=%s",
                (stags, rid),
            )
            updated += cur.rowcount
        if len(samples) < 8:
            samples.append({"id": rid, "strategy_tags": stags, "topic": (topic or "")[:60]})
    if apply:
        conn.commit()
    out = {"ok": True, "apply": apply, "candidates": len(rows), "updated": updated, "samples": samples}
    print(json.dumps(out, indent=2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=5000)
    args = ap.parse_args()
    run(apply=args.apply, limit=args.limit)


if __name__ == "__main__":
    main()