#!/usr/bin/env python3
"""run_governed_research_producer.py — scheduled entrypoint for the research producer.

Phase 2 of the Grok-closure campaign closed the *producer* gap
(``scripts/lib/governed_research_producer.py``, 12 tests) but shipped it as a
library: no entrypoint, no cron, feature flag default OFF. The observable
consequence, every hour, in ``logs/wake_selection_feed.log``::

    {"counts": {"material_changes": 86, "receipts": 62, "research_objects_proxy": 0}}

``research_objects_proxy`` is 0 on every single pass, so
``wake_subject_selector`` has no research candidates and every wake falls
through to ``selection_source="material_change"``. The research -> wake edge is
implemented and inert. This module is the missing scheduled trigger.

It is deliberately thin. All governance -- budget, fail-closed provider policy,
dedupe, atomic append, health reporting -- lives in the library and is NOT
re-implemented or relaxed here.

Fail-closed by construction:
  * No target source given  -> ``nothing_eligible``, no provider call.
  * ``GOVERNED_RESEARCH_PRODUCER_ENABLED`` unset/0 -> ``disabled``, no side effects.
  * ``BRAVE_ROUTER_LIVE`` unset -> the router itself refuses to leave the host.
  * ``--dry-run`` resolves and prints targets and exits BEFORE any provider call.

Exit status is 0 for ``produced``, ``nothing_eligible`` and ``disabled`` -- all
are legitimate scheduled outcomes -- and 1 only for ``broken``. Note that exit 0
is not evidence of work (AGENTS.md §0 rule 8); the durable artifact is the feed
row plus the health file, which is what the wake selector and the maturity
surface actually read.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[1]
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from scripts.lib import governed_research_producer as grp  # noqa: E402


def _targets_from_file(path: Path) -> list[dict]:
    """Accept either a JSON list or JSONL; each row needs at least ``symbol``."""
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    if raw.lstrip().startswith("["):
        rows = json.loads(raw)
    else:
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    out = []
    for r in rows:
        if isinstance(r, str):
            out.append({"symbol": r})
        elif isinstance(r, dict):
            out.append(r)
    return out


def _targets_from_symbols(spec: str) -> list[dict]:
    return [{"symbol": s.strip()} for s in spec.split(",") if s.strip()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = p.add_mutually_exclusive_group()
    src.add_argument("--symbols", help="comma-separated symbols, e.g. NVDA,AMD")
    src.add_argument("--targets-file", type=Path,
                     help="JSON list or JSONL of {symbol, subject_guid?, query?}")
    p.add_argument("--limit", type=int, default=0,
                   help="cap the number of targets per pass (0 = no cap). A cap "
                        "bounds provider spend on a scheduled path.")
    p.add_argument("--dry-run", action="store_true", default=True,
                   help="resolve targets and report; never calls the provider "
                        "(default)")
    p.add_argument("--execute", action="store_true",
                   help="actually produce research (overrides --dry-run); still "
                        "no-ops unless GOVERNED_RESEARCH_PRODUCER_ENABLED is on")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.targets_file:
        targets = _targets_from_file(args.targets_file)
    elif args.symbols:
        targets = _targets_from_symbols(args.symbols)
    else:
        targets = []

    if args.limit and args.limit > 0:
        targets = targets[: args.limit]

    dry_run = not args.execute
    if dry_run:
        # Resolution uses the identity registry only; no provider boundary is
        # crossed. This is the control that proves what a live pass WOULD do.
        resolved = grp._resolve_targets(targets, dict(os.environ))
        print(json.dumps({
            "mode": "dry_run",
            "enabled": grp.enabled(),
            "requested": len(targets),
            "eligible": len(resolved),
            "skipped_no_subject_guid": len(targets) - len(resolved),
            "targets": resolved,
            "feed_path": str(grp.feed_path() or ""),
            "health_path": str(grp.health_path() or ""),
            "source_sha": grp.source_sha(),
        }, sort_keys=True))
        return 0

    result = grp.produce_research(targets=targets)

    print(json.dumps({
        "outcome": result.outcome,
        "ok": result.ok,
        "disabled": getattr(result, "disabled", False),
        "eligible": getattr(result, "eligible", 0),
        "produced": getattr(result, "produced", 0),
        "errors": list(getattr(result, "errors", []) or []),
        "source_sha": grp.source_sha(),
    }, sort_keys=True))

    return 1 if result.outcome == "broken" else 0


if __name__ == "__main__":
    raise SystemExit(main())
