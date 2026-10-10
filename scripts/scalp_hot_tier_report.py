#!/usr/bin/env python3
"""scalp_hot_tier_report.py — read-only report for the momentum-scalp hot tier (operator decision (4), 2026-10-10).

    python3 scripts/scalp_hot_tier_report.py --budget       # projected Finviz / SearXNG / StockTwits usage
    python3 scripts/scalp_hot_tier_report.py --freshness    # the four freshness SLOs (broker-freshness check)
    python3 scripts/scalp_hot_tier_report.py --triggers     # what each event-triggered consumer WOULD do now
    python3 scripts/scalp_hot_tier_report.py                # flag state + phase + budget + freshness

Writes nothing, calls no provider. ``--freshness`` reads the scalp list (L1050's universe file and, premarket, the
screener membership rows through a READ ONLY session), the enrichment cache, the day's Hermes catalyst JSONL, the
trigger watermarks and the social hot lane's receipt. Exit 0, or with ``--strict`` 1 when any SLO is degraded or
failed (for a health contract's ``broker_domain_stale`` check). Outside market days 06:00-16:00 ET every SLO is NO_SLO.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import scalp_hot_tier as hot  # noqa: E402


def build(budget: bool, freshness: bool, triggers: bool = False) -> dict:
    rep: dict = {
        "schema": "ScalpHotTierReport@v1",
        "hot_tier": hot.flag_state(),
        "phase": hot.phase(),
        "screener_ids": hot.scalp_screener_ids(ROOT),
        "writes": "none",
        "provider_calls": 0,
    }
    if budget:
        rep["budget"] = hot.budget_projection(screeners=len(rep["screener_ids"]))
    if freshness:
        from lib.data_broker import scalp_list as sl

        rep["freshness"] = sl.freshness_report(project_root=ROOT)
    if triggers:
        from lib import scalp_list_trigger as trig
        from lib.data_broker import scalp_list as sl

        env = sl.get_scalp_list()
        # decide() is read-only: a shadow view of the event trigger, never a commit
        rep["triggers"] = {c: trig.decide(c, env, hot_enabled=True) for c in trig.CONSUMERS}
        rep["triggers_knob_off"] = {c: trig.decide(c, env, hot_enabled=False) for c in trig.CONSUMERS}
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--budget", action="store_true")
    ap.add_argument("--freshness", action="store_true")
    ap.add_argument("--triggers", action="store_true", help="shadow: each consumer's trigger decision (no commit)")
    ap.add_argument("--strict", action="store_true", help="exit 1 when any SLO is degraded or failed")
    args = ap.parse_args(argv)
    both = not (args.budget or args.freshness or args.triggers)
    rep = build(args.budget or both, args.freshness or both, args.triggers)
    print(json.dumps(rep, indent=1, default=str))
    if args.strict and (rep.get("freshness") or {}).get("overall") in ("degraded", "failed"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
