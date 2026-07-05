#!/usr/bin/env python3
"""hermes_discovery_inbox.py — CLI for the Hermes Discovery Inbox (Stage 1).

Advisory-only: reads/writes the hermes_discovery_* tables, never touches brokers.

Usage:
  python3 scripts/hermes_discovery_inbox.py --dry-run [--json]   # list inbox, no writes
  python3 scripts/hermes_discovery_inbox.py --ingest-test        # one sample per type
  python3 scripts/hermes_discovery_inbox.py --stats [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.hermes_discovery import inbox  # noqa: E402


def _jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


def cmd_dry_run(as_json: bool) -> int:
    rows = inbox.list_candidates(limit=500)
    grouped: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        grouped[r["candidate_type"]][r["status"]].append({
            "id": r["id"], "label": r["label"], "normalized_key": r["normalized_key"],
            "score": float(r["discovery_score"]) if r.get("discovery_score") is not None else None,
            "seen_count": r["seen_count"], "source_domain": r.get("source_domain"),
            "cluster_id": r.get("duplicate_cluster_id"),
            "is_operator": r.get("is_operator"),
            "last_seen_at": str(r.get("last_seen_at")),
        })
    payload = {ct: dict(st) for ct, st in grouped.items()}
    if as_json:
        print(json.dumps(_jsonable(payload), indent=2))
    else:
        if not payload:
            print("Discovery inbox is empty.")
        for ctype, by_status in sorted(payload.items()):
            print(f"\n== {ctype} ==")
            for status, items in sorted(by_status.items()):
                print(f"  [{status}] ({len(items)})")
                for it in items[:20]:
                    score = f"{it['score']:.3f}" if it["score"] is not None else "-"
                    op = " OPERATOR" if it["is_operator"] else ""
                    print(f"    #{it['id']} {it['label']!r} score={score} "
                          f"seen={it['seen_count']}{op}")
    return 0


def cmd_ingest_test() -> int:
    samples = [
        dict(candidate_type="SOURCE_CANDIDATE",
             label="Semafor Business daily newsletter",
             summary="Business newsletter repeatedly cited by graded synthesis runs.",
             source_domain="semafor.com", source_url="https://www.semafor.com/business",
             evidence=[{"source_domain": "semafor.com", "note": "cited in 3 graded syntheses"}]),
        dict(candidate_type="TREND_CANDIDATE",
             label="AI datacenter power buildout accelerating",
             summary="Multiple sources flag grid-constrained datacenter capex.",
             source_domain="reuters.com",
             evidence=[{"source_domain": "reuters.com", "note": "capex roundup"}],
             extracted_symbols=["VRT", "ETN"]),
        dict(candidate_type="TICKER_CANDIDATE",
             label="GOOGL",
             summary="Extracted from trend evidence.",
             source_domain="reuters.com", seed_symbols=["GOOGL"]),
        dict(candidate_type="TOPIC_CANDIDATE",
             label="Grid interconnection queue reform",
             summary="Recurring research topic across energy coverage.",
             source_domain="utilitydive.com"),
        dict(candidate_type="CONNECTOR_CANDIDATE",
             label="SEC EDGAR full-text search connector",
             summary="Potential structured source for filings-driven discovery.",
             source_domain="sec.gov"),
    ]
    ids = []
    for s in samples:
        row = inbox.upsert_candidate(actor="ingest-test", **s)
        ids.append((row["id"], row["candidate_type"], row["status"], row["seen_count"]))
        print(f"  upserted #{row['id']} {row['candidate_type']} "
              f"status={row['status']} seen={row['seen_count']} "
              f"score={row['discovery_score']}")
    print(json.dumps({"ids": [i for i, *_ in ids]}))
    return 0


def cmd_stats(as_json: bool) -> int:
    stats = inbox.inbox_stats()
    if as_json:
        print(json.dumps(_jsonable(stats), indent=2))
    else:
        t = stats["totals"]
        print(f"candidates={t.get('candidates', 0)} avg_score={t.get('avg_score', 0):.3f} "
              f"clustered={t.get('clustered', 0)} operator={t.get('operator_created', 0)}")
        print(f"audit_rows={stats['audit_rows']} feedback_rows={stats['feedback_rows']}")
        print("by_status:", json.dumps(stats["by_status"]))
        print("by_type:  ", json.dumps(stats["by_type"]))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="list current inbox grouped by type/status (no writes)")
    ap.add_argument("--ingest-test", action="store_true",
                    help="upsert one sample candidate per type (idempotent)")
    ap.add_argument("--stats", action="store_true", help="aggregate inbox counts")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    if args.ingest_test:
        return cmd_ingest_test()
    if args.stats:
        return cmd_stats(args.json)
    if args.dry_run:
        return cmd_dry_run(args.json)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
