#!/usr/bin/env python3
"""Re-embed advisory KB lessons with the allowlisted embedding model (append-only).

Dry-run by default: reports which ratified lessons lack a vector from the
allowlisted model (nomic-embed-text) and never calls the embedding endpoint.
--apply embeds each with that model and appends rows to the embeddings store
(advisory_kb_lessons_embeddings.jsonl); lesson rows are never rewritten.
Retrieval then prefers that same-content vector over a lesson's original
(e.g. qwen3-embedding:8b) vector. See kb_lessons.reembed_lessons.

  python3 scripts/kb_lessons_reembed.py                  # dry-run report
  python3 scripts/kb_lessons_reembed.py --apply          # write embedding rows
  python3 scripts/kb_lessons_reembed.py --lessons PATH   # alternate lesson log
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.advisory import kb_lessons as kb  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report only (default)")
    mode.add_argument("--apply", action="store_true", help="embed and append embedding rows")
    ap.add_argument("--lessons", default="", help="lesson log (default: kb_lessons.LESSONS_PATH)")
    ap.add_argument("--applications", default="", help="counter events (default: sibling of the lesson log)")
    ap.add_argument("--all-statuses", action="store_true", help="include candidates (retired always skipped)")
    ap.add_argument("--show-ids", action="store_true", help="list lesson ids to embed")
    args = ap.parse_args(argv)
    if args.lessons:
        kb.LESSONS_PATH = Path(args.lessons)
        kb.APPLICATIONS_PATH = (Path(args.applications) if args.applications
                                else kb.LESSONS_PATH.with_name("advisory_kb_lesson_applications.jsonl"))
    out = kb.reembed_lessons(apply=bool(args.apply), status=None if args.all_statuses else "ratified")
    if not args.show_ids:
        out.pop("ids", None)
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
