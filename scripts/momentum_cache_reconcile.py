#!/usr/bin/env python3
"""Rebuild only a resettable shared-advisory projection from the existing owner snapshots.

No canonical business/cache writes, providers, broker, models, sends or credentials.
The host executor owns the approved flock. Dry run never writes. Apply requires the
operative reviewed safe lane and candidate arming; no n8n caller-supplied authority.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.n8n_momentum_lifecycle import cache_helper_admitted, load_admission  # noqa: E402
from scripts.lib.scanner_candidate_projection import read_candidate_snapshot  # noqa: E402

LANE = "momentum-cache-reconcile"
SCHEMA = "MomentumCacheReconcile@v1"
PROJECTION_REL = "data/runtime/shared_momentum_candidates_projection.json"
RECEIPT_REL = "data/runtime/momentum-cache-reconcile_last.json"
NO_CONSUMER_REASON = (
    "Proposed safe host lane; resettable derived projection only. Candidate consumer/runtime admission remains pending."
)


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(doc, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def reconcile(*, code_root: Path, state_root: Path, now: datetime, apply: bool = False) -> dict:
    admission = load_admission(code_root)
    candidate = json.loads((code_root / "config/n8n_momentum_lifecycle_candidate.json").read_text())
    stage = admission.registry.get(LANE, {}).get("scheduler", {}).get("stage")
    result = {
        "schema": SCHEMA,
        "lane_id": LANE,
        "as_of": now.isoformat(),
        "source_sha": admission.deployed_sha,
        "mode": "live" if apply else "dry_run",
        "execution_stage": stage
        if isinstance(stage, str) and stage in {"shadow", "canary", "cutover"}
        else "NOT_MEASURED",
        "canonical_business_writes": 0,
        "provider_calls": 0,
        "business_acceptance": "NOT_MEASURED",
        "scope": "RESETTABLE_DERIVED_ADVISORY_PROJECTION",
        "status": "REFUSED",
        "reason": None,
    }
    if apply and (
        candidate.get("enabled") is not True
        or candidate.get("recovery", {}).get("armed") is not True
        or not cache_helper_admitted(admission, LANE)
    ):
        result["reason"] = "operative_recovery_admission_unproven"
        return result
    projection = read_candidate_snapshot(
        state_root / "data/runtime/trade_ai_cache.json",
        state_root / "data/active_trader/momentum_alerts.jsonl",
        now=now,
    )
    result["projection"] = {
        k: projection.get(k)
        for k in (
            "schema",
            "projection_hash",
            "run_id",
            "run_date",
            "source_sha",
            "finished_at",
            "status",
            "candidate_count",
        )
    }
    if not any(meta.get("status") == "AVAILABLE" for meta in projection["source_metadata"].values()):
        result["reason"] = "owner_inputs_not_measured"
        return result
    # Retain all source freshness, UNKNOWN producer SHA, PENDING/STALE verdict and conflict metadata.
    # A reconstructed derived cache cannot heal an authoritative stale scan or prove consumer acceptance.
    result["status"] = "ok"
    result["reason"] = "derived_projection_reconciled" if apply else "would_reconcile_derived_projection"
    result["output_rel"] = PROJECTION_REL
    if apply:
        try:
            previous = json.loads((state_root / PROJECTION_REL).read_text())
        except (OSError, ValueError):
            previous = None

        def stable(row):
            return {k: v for k, v in row.items() if k != "generated_at"}

        if isinstance(previous, dict) and stable(previous) == stable(projection):
            result["reason"] = "derived_projection_already_consistent"
        else:
            _write(state_root / PROJECTION_REL, projection)
        _write(state_root / RECEIPT_REL, result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--code-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--apply", action="store_true")
    parser.add_argument("--now")
    args = parser.parse_args(argv)
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        parser.error("aware clock required")
    result = reconcile(code_root=args.code_root, state_root=args.state_root, now=now, apply=args.apply)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
