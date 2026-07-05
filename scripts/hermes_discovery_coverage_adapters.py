#!/usr/bin/env python3
"""hermes_discovery_coverage_adapters.py — coverage-area adapters → Discovery
Inbox (Universal Research Discovery Layer, spec Part H).

Runs the eight coverage adapters in lib/hermes_discovery/coverage.py and feeds
their TOPIC candidates through inbox.upsert_candidate (Stage-1 enrichment —
domain classification, subject envelopes, advisory + professional-review
labels — happens inside the upsert). Areas:

  holdings watchlist sectors taxes retirement legal macro system_ops

Every run honors the same caps machinery as the scheduled ingestors
(config/hermes_discovery_schedule.json + latest scorecard do-no-harm):
per-run cap, max_candidates_per_domain_per_day against today's live candidate
counts, ticker/day and legal-tax/day caps, pause. Operator candidates are
never produced here, so pause quietly skips everything.

Advisory-only: never imports broker modules, never writes producer tables.
Idempotent: stable finding-class labels make re-runs bump seen_count.

Usage:
  python3 scripts/hermes_discovery_coverage_adapters.py --run [--dry-run] [--json]
  python3 scripts/hermes_discovery_coverage_adapters.py --run --taxes --macro --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from hermes_discovery_ingestors import (  # noqa: E402
    _domain_counts_today, _upsert_all, effective_caps, load_schedule_config,
    load_scorecard_do_no_harm, make_intake_gate)
from lib.hermes_discovery.coverage import COVERAGE_ADAPTERS, COVERAGE_DOMAINS  # noqa: E402

AREAS = list(COVERAGE_ADAPTERS)


def run_coverage(selected: list[str], *, dry_run: bool = False,
                 limit: int | None = None,
                 config_path: Path | str | None = None,
                 scorecard_path: Path | str | None = None) -> dict[str, Any]:
    """Run the selected coverage adapters under schedule-config caps.
    Returns the JSON run report. Fails closed on a broken schedule config."""
    report: dict[str, Any] = {
        "mode": "coverage",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": bool(dry_run),
        "do_no_harm": None,
        "caps_applied": {},
        "results": {},
        "by_domain_counts": {},
        "skipped_reasons": {},
    }
    try:
        cfg = load_schedule_config(config_path)
        dnh = (load_scorecard_do_no_harm(scorecard_path)
               if cfg.get("do_no_harm_pause_respected", True) else "steady")
        caps = effective_caps(cfg, dnh)
    except Exception as e:  # broken config → fail closed, write nothing
        report["error"] = f"schedule config load failed: {e}"[:300]
        return report

    report["do_no_harm"] = dnh
    report["caps_applied"] = caps

    skipped: dict[str, int] = {}
    gate = make_intake_gate(caps, _domain_counts_today(), skipped)
    domain_counts: Counter[str] = Counter()

    for area in selected:
        fn = COVERAGE_ADAPTERS[area]
        try:
            payloads = fn()
            if limit is not None:
                payloads = payloads[:max(0, int(limit))]
            res = _upsert_all(payloads, actor=f"coverage:{area}",
                              dry_run=dry_run, gate=gate)
            for c in res.get("candidates") or []:
                domain_counts[COVERAGE_DOMAINS[area]] += 1
            report["results"][area] = {
                "domain": COVERAGE_DOMAINS[area],
                "scanned": res.get("scanned", 0),
                "upserted": res.get("upserted", 0),
                "skipped": res.get("skipped", 0),
                "candidates": [
                    {k: c.get(k) for k in ("label", "id", "status", "seen_count")
                     if c.get(k) is not None}
                    for c in (res.get("candidates") or [])[:10]],
            }
        except Exception as e:  # one broken adapter never blocks the others
            report["results"][area] = {"domain": COVERAGE_DOMAINS[area],
                                       "error": str(e)[:200]}

    report["by_domain_counts"] = dict(domain_counts)
    report["skipped_reasons"] = skipped
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="run the selected adapters")
    for area in AREAS:
        ap.add_argument(f"--{area.replace('_', '-')}", dest=area,
                        action="store_true",
                        help=f"run the {area} adapter (default: all)")
    ap.add_argument("--limit", type=int, default=None,
                    help="max payloads per adapter (before caps)")
    ap.add_argument("--dry-run", action="store_true",
                    help="list would-be candidates without writing the inbox")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    if not args.run:
        ap.print_help()
        return 2

    selected = [a for a in AREAS if getattr(args, a)] or AREAS
    report = run_coverage(selected, dry_run=args.dry_run, limit=args.limit)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    elif report.get("error"):
        print(f"ERROR: {report['error']}")
    else:
        print(f"do_no_harm={report['do_no_harm']} "
              f"paused={report['caps_applied'].get('paused')} "
              f"dry_run={report['dry_run']}")
        for area, res in report["results"].items():
            if res.get("error"):
                print(f"[{area}] ERROR: {res['error']}")
                continue
            print(f"[{area}] domain={res['domain']} scanned={res['scanned']} "
                  f"upserted={res['upserted']} skipped={res['skipped']}")
            for c in res["candidates"]:
                extra = f" #{c['id']} {c.get('status')}" if "id" in c else ""
                print(f"    {c['label']!r}{extra}")
        if report["skipped_reasons"]:
            print(f"skipped_reasons: {report['skipped_reasons']}")
    return 1 if report.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
