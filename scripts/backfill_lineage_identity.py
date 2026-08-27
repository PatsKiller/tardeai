#!/usr/bin/env python3
"""Re-stamp existing lineage envelopes with their durable entity identity.

    python scripts/backfill_lineage_identity.py            # dry run
    python scripts/backfill_lineage_identity.py --json
    python scripts/backfill_lineage_identity.py --apply

Identity resolution now happens on the envelope write path, so every *new*
envelope carries a `subject_guid`. Envelopes written before that change do not,
and lineage is append-only -- nothing rewrites them on its own, so the
completion report keeps reading `0 / 97` until they are touched again.

This re-upserts each envelope through the normal write path. It adds nothing of
its own: the identity comes from the same resolver a live write would use, and
an envelope whose subject does not resolve is left exactly as it is rather than
being given a placeholder. Because the store is append-only, the prior version
stays on disk and remains readable -- this adds a version, it does not edit one.

AUTHORITY: READ_ONLY_ADVISORY. Identity only; no stage, status or outcome field
is touched.
"""
from __future__ import annotations

NO_CONSUMER_REASON = (
    "one-shot backfill; ran 2026-08-27 for the 58 pre-#556 envelopes. Re-run manually if lineage is ever rebuilt."
)

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.lib.cio_lineage import (  # noqa: E402
    ENVELOPE_RECORD,
    LineageStore,
    _stamp_identity,
)


def plan(path: Path | str | None = None) -> list[dict[str, Any]]:
    """Envelopes whose identity would change, and how."""
    store = LineageStore(path)
    changes = []
    for workflow, env in _latest_by_workflow(store).items():
        before = (env.get("subject_guid"), env.get("entity_type"))
        probe = dict(env)
        _stamp_identity(probe)
        after = (probe.get("subject_guid"), probe.get("entity_type"))
        if before != after:
            changes.append({
                "workflow_id": workflow,
                "subject_id": probe.get("subject_id"),
                "from": {"subject_guid": before[0], "entity_type": before[1]},
                "to": {"subject_guid": after[0], "entity_type": after[1]},
            })
    return changes


def _latest_by_workflow(store: LineageStore) -> dict[str, dict[str, Any]]:
    """Fold the append-only log to the live version of each workflow.

    Counting raw rows instead of folding is how an earlier audit reported 315
    workflows where there were 94.
    """
    latest: dict[str, dict[str, Any]] = {}
    for row in store._rows():
        wf = row.get("workflow_id")
        if wf and row.get("record_type") == ENVELOPE_RECORD:
            latest[str(wf)] = row
    return latest


def run(apply: bool = False, path: Path | str | None = None) -> dict[str, Any]:
    changes = plan(path)
    if apply:
        store = LineageStore(path)
        for change in changes:
            # An empty update still routes through upsert_envelope, which stamps
            # identity and appends a new version. Nothing else is modified.
            store.upsert_envelope(change["workflow_id"], {})
    return {
        "schema": "LineageIdentityBackfill@v1",
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
        "applied": bool(apply),
        "envelopes_changed": len(changes),
        "changes": changes[:20],
        "truncated": max(0, len(changes) - 20),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill lineage envelope identity")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    result = run(apply=args.apply)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"envelopes_changed  {result['envelopes_changed']}")
        for change in result["changes"]:
            print(f"  {change['workflow_id']}  {change['subject_id']}  "
                  f"{change['from']['entity_type']} -> {change['to']['entity_type']}")
        if result["truncated"]:
            print(f"  ... and {result['truncated']} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
