#!/usr/bin/env python3
"""Apply Policy Review P2 to the existing lesson queue (operator-approved 2026-10-03).

    python3 scripts/lesson_queue_hygiene.py            # dry run: what would move, by reason
    python3 scripts/lesson_queue_hygiene.py --apply    # append ARCHIVED / RETIRE_PROPOSED events

Append-only: QUEUED lessons failing the rule get an ARCHIVED event (reversible by an
operator decide()); lessons contradicted by later quality outcomes get RETIRE_PROPOSED,
never RETIRED. Nothing is deleted, and nothing is promoted.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import lesson_outcome_quality as loq  # noqa: E402
import lesson_promotion as lp  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--root", help="state root containing data/cio (default: production state)")
    a = ap.parse_args(argv)
    root = Path(a.root) if a.root else None
    if root is None:
        try:
            from canonical_store_registry import production_state_root  # type: ignore
            root = Path(production_state_root())
        except Exception:  # noqa: BLE001
            root = Path.home() / "trade-ai-releases" / "persistent-state"
    env = {"TRADEAI_CIO_DIR": str(root / "data" / "cio")}
    price_on, daily_vol = loq.default_lookups()
    archive = lp.archive_plan(root, env, price_on=price_on, daily_vol=daily_vol)
    retire = lp.contradiction_plan(root, env, price_on=price_on, daily_vol=daily_vol)
    by_reason: dict[str, int] = {}
    for item in archive:
        key = item["reason"].split(":")[0]
        by_reason[key] = by_reason.get(key, 0) + 1
    queued = sum(1 for r in lp.state(root, env).values() if r.get("status") == "QUEUED")
    report = {"applied": a.apply, "queued_before": queued, "would_archive": len(archive),
              "archive_by_reason": by_reason, "would_remain_queued": queued - len(archive),
              "would_propose_retirement": len(retire), "price_lookups": price_on is not None,
              "sample": archive[:5], "retire_sample": retire[:5]}
    if a.apply:
        for item in archive:
            lp.archive(item["procedure_id"], item["reason"], root=root, env=env)
        for item in retire:
            lp.propose_retirement(item["procedure_id"], item, root=root, env=env)
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
