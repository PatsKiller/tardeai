#!/usr/bin/env python3
"""Materialize a deterministic CIOWeeklyLearningReview@v1 from existing ledgers."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.cio_feedback_learning_v1 import (  # noqa: E402
    build_weekly_learning_review,
    read_jsonl,
    reconcile_weekly_learning_review,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--week-ending", default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument("--decisions", default=str(ROOT / "data/cio/decision_payloads.jsonl"))
    parser.add_argument("--linked-feedback", default=str(ROOT / "data/cio/cio_linked_feedback.jsonl"))
    parser.add_argument("--ticker-feedback", default=str(ROOT / "data/cio/operator_ticker_feedback.jsonl"))
    parser.add_argument("--outcomes", default=str(ROOT / "data/cio/advisory_outcomes_v1.jsonl"))
    parser.add_argument("--output", default=str(ROOT / "data/cio/cio_weekly_learning_reviews.jsonl"))
    args = parser.parse_args()
    feedback = read_jsonl(args.linked_feedback) + read_jsonl(args.ticker_feedback)
    review = build_weekly_learning_review(
        week_ending=args.week_ending,
        decision_rows=read_jsonl(args.decisions),
        feedback_rows=feedback,
        outcome_rows=read_jsonl(args.outcomes),
    )
    result = reconcile_weekly_learning_review(review, store_path=args.output)
    stored = result["review"]
    print(json.dumps({
        "published": result["published"],
        "reason": result["reason"],
        "version": stored.get("version"),
        "observation_window": stored.get("observation_window_state"),
        "matured_outcomes": (stored.get("matured_outcomes") or {}).get("count"),
        "preference_candidates": len((stored.get("operator_feedback_patterns") or {}).get("preference_candidates") or []),
        "authority": stored.get("authority"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
