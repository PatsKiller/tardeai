#!/usr/bin/env python3
"""Operator-gated lifecycle DLQ ledger + replay dry-run (G-LOOP-01 / P9 C–D).

Uses ``cio_registry_orphan_census`` findings (orphan / missing_cross_id) to
enqueue APPEND_ONLY_EVIDENCE rows and print planned replay actions.

    python scripts/cio_lifecycle_dlq.py --census-days 30
    python scripts/cio_lifecycle_dlq.py --census-days 30 --write-ledger
    python scripts/cio_lifecycle_dlq.py --census-days 30 --replay-dry-run
    python scripts/cio_lifecycle_dlq.py --census-days 30 --write-ledger --replay-dry-run
    TRADEAI_DLQ_APPLY=1 python scripts/cio_lifecycle_dlq.py --apply --write-ledger

Rails:
  - never_auto_remediate store_consistency
  - no silent identity merge
  - --apply refused unless TRADEAI_DLQ_APPLY=1; even then only appends
    apply-receipt / ledger rows — does NOT rewrite historical lineage/hubs
  - does NOT claim 99.99% completion
  - AUTHORITY READ_ONLY_ADVISORY · MBI=0

AUTHORITY: READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.canonical_store_registry import (  # noqa: E402
    AUTHORITY,
    MBI,
    production_state_root,
)
from scripts.lib.cio_dlq_ledger import (  # noqa: E402
    APPLY_ENV,
    SCHEMA,
    append_ledger_records,
    apply_env_armed,
    findings_from_census,
    ledger_path,
    make_apply_receipt,
    make_enqueue_record,
    make_replay_plan_record,
    plan_replay_actions,
)
from scripts.cio_registry_orphan_census import census as run_census  # noqa: E402

NO_CONSUMER_REASON = (
    "operator-invoked diligence CLI: CIOLifecycleDLQRun@v1 is a stdout / ledger "
    "receipt for G-LOOP-01 DLQ dry-run; not an ingested store contract. Durable "
    "rows live under data/cio/lifecycle_dlq.jsonl (APPEND_ONLY_EVIDENCE)."
)

RUN_SCHEMA = "CIOLifecycleDLQRun@v1"
DEFAULT_CENSUS_DAYS = 30


def build_run(
    *,
    root: Path,
    census_days: int,
    write_ledger: bool,
    replay_dry_run: bool,
    apply: bool,
    ledger_override: Path | None,
) -> dict[str, Any]:
    """Execute census → findings → optional ledger / dry-run / gated apply."""
    run_id = "dlqrun_" + secrets.token_hex(8)
    base = production_state_root(root)
    path = ledger_path(base, ledger_override)

    census_report = run_census(
        root=base,
        days=census_days,
        include_lineage_baseline=True,
    )
    findings = findings_from_census(census_report)
    plans = plan_replay_actions(findings) if (replay_dry_run or apply) else []

    written: list[str] = []
    refused: dict[str, Any] | None = None
    apply_receipt: dict[str, Any] | None = None
    enqueue_records: list[dict[str, Any]] = []
    plan_records: list[dict[str, Any]] = []

    if write_ledger:
        enqueue_records = [
            make_enqueue_record(f, census_days=census_days, run_id=run_id)
            for f in findings
        ]
        append_ledger_records(path, enqueue_records)
        written.append(f"enqueue:{len(enqueue_records)}")

    if replay_dry_run and write_ledger:
        plan_records = [
            make_replay_plan_record(p, run_id=run_id) for p in plans
        ]
        append_ledger_records(path, plan_records)
        written.append(f"replay_plan:{len(plan_records)}")

    if apply:
        if not apply_env_armed():
            refused = {
                "flag": "--apply",
                "reason": "APPLY_REFUSED",
                "detail": (
                    f"--apply refused unless {APPLY_ENV}=1. "
                    "Even when armed, apply only appends an apply-receipt; "
                    "it does not rewrite lineage/jsonl hubs."
                ),
                "env": APPLY_ENV,
                "env_value": os.environ.get(APPLY_ENV),
            }
        else:
            # Ensure plans exist even if operator skipped --replay-dry-run.
            if not plans:
                plans = plan_replay_actions(findings)
            apply_receipt = make_apply_receipt(
                plans, run_id=run_id, census_days=census_days
            )
            # Apply always appends receipt when armed — never mutates hubs.
            append_ledger_records(path, [apply_receipt])
            written.append("apply_receipt:1")

    headline = census_report.get("headline") or {}
    lb = census_report.get("lineage_baseline") or {}
    completion_note = None
    if isinstance(lb, dict) and lb.get("workflows") is not None:
        completion_note = {
            "workflows": lb.get("workflows"),
            "complete_to_checkpoint": lb.get("complete_to_checkpoint"),
            "completion_rate": lb.get("completion_rate"),
            "claim_99_99": False,
            "note": (
                "G-LOOP-01 remains OPEN until measured completion rises; "
                "this package does not claim 99.99%."
            ),
        }

    return {
        "schema": RUN_SCHEMA,
        "dlq_schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "never_auto_remediate": True,
        "mutates_historical_stores": False,
        "run_id": run_id,
        "root": str(base),
        "ledger_path": str(path),
        "census_days": census_days,
        "flags": {
            "write_ledger": write_ledger,
            "replay_dry_run": replay_dry_run,
            "apply": apply,
            "apply_env_armed": apply_env_armed(),
        },
        "census_headline": {
            "orphan_hits": headline.get("orphan_hits"),
            "missing_cross_id_hits": headline.get("missing_cross_id_hits"),
            "stores_present": headline.get("stores_present"),
            "stores_scanned": headline.get("stores_scanned"),
        },
        "finding_count": len(findings),
        "findings": findings,
        "replay_plans": plans,
        "written": written,
        "apply_refused": refused,
        "apply_receipt": apply_receipt,
        "lineage_baseline": completion_note,
        "rails": {
            "authority": AUTHORITY,
            "memory_behavior_influence": MBI,
            "never_auto_remediate_store_consistency": True,
            "no_silent_identity_merge": True,
            "apply_requires_env": APPLY_ENV,
            "apply_mutates_hubs": False,
            "claim_99_99": False,
        },
    }


def render(report: dict[str, Any]) -> str:
    lines = [
        "CIO lifecycle DLQ (READ_ONLY_ADVISORY · MBI=0 · never_auto_remediate)",
        f"run_id                  {report.get('run_id')}",
        f"root                    {report.get('root')}",
        f"ledger_path             {report.get('ledger_path')}",
        f"census_days             {report.get('census_days')}",
        f"finding_count           {report.get('finding_count')}",
    ]
    ch = report.get("census_headline") or {}
    lines.append(
        f"census                  orphan_hits={ch.get('orphan_hits')} "
        f"missing_cross_id={ch.get('missing_cross_id_hits')}"
    )
    lb = report.get("lineage_baseline") or {}
    if lb.get("workflows") is not None:
        rate = lb.get("completion_rate")
        rate_s = f" ({rate:.1%})" if isinstance(rate, (int, float)) else ""
        lines.append(
            f"lineage_baseline        {lb.get('complete_to_checkpoint')}/"
            f"{lb.get('workflows')} complete_to_checkpoint{rate_s} "
            "[NOT a 99.99% claim; G-LOOP-01 OPEN]"
        )
    flags = report.get("flags") or {}
    lines.append(
        f"flags                   write_ledger={flags.get('write_ledger')} "
        f"replay_dry_run={flags.get('replay_dry_run')} "
        f"apply={flags.get('apply')} "
        f"apply_env_armed={flags.get('apply_env_armed')}"
    )
    if report.get("written"):
        lines.append(f"ledger_writes           {', '.join(report['written'])}")
    refused = report.get("apply_refused")
    if refused:
        lines.append(f"APPLY_REFUSED           {refused.get('detail')}")
    plans = report.get("replay_plans") or []
    if plans:
        lines.append("replay_plans (dry-run; mutates_historical_stores=false):")
        for p in plans[:20]:
            lines.append(
                f"  {p.get('finding_id')}: {p.get('action')} "
                f"[{p.get('reason_code')}] {p.get('store_id')}.{p.get('field')}"
            )
        if len(plans) > 20:
            lines.append(f"  ... +{len(plans) - 20} more")
    elif flags.get("replay_dry_run") or flags.get("apply"):
        lines.append("replay_plans            (none — census clean in samples)")
    lines.append(
        "rails                   no hub rewrite · no silent identity merge · "
        "99.99% not claimed"
    )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "G-LOOP-01 operator-gated DLQ ledger + replay dry-run "
            "(APPEND_ONLY_EVIDENCE; never rewrites hubs)"
        ),
    )
    ap.add_argument(
        "--census-days",
        type=int,
        default=DEFAULT_CENSUS_DAYS,
        help=f"orphan census window in days (default {DEFAULT_CENSUS_DAYS})",
    )
    ap.add_argument(
        "--root",
        default=None,
        help="state root (default: production_state_root())",
    )
    ap.add_argument(
        "--ledger-path",
        default=None,
        help="override ledger path (default: <root>/data/cio/lifecycle_dlq.jsonl)",
    )
    ap.add_argument(
        "--write-ledger",
        action="store_true",
        help="append enqueue (+ optional replay_plan annotate) rows to ledger",
    )
    ap.add_argument(
        "--replay-dry-run",
        action="store_true",
        help="print planned replay actions (no hub writes; optional ledger annotate)",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help=(
            f"refused unless {APPLY_ENV}=1; even then only appends apply-receipt "
            "(does NOT mutate lineage/jsonl hubs)"
        ),
    )
    ap.add_argument("--json", action="store_true", help="emit JSON run receipt")
    args = ap.parse_args()

    root = Path(args.root) if args.root else production_state_root(None)
    ledger_override = Path(args.ledger_path) if args.ledger_path else None

    report = build_run(
        root=root,
        census_days=args.census_days,
        write_ledger=args.write_ledger,
        replay_dry_run=args.replay_dry_run,
        apply=args.apply,
        ledger_override=ledger_override,
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        print(render(report))

    # Non-zero when apply was requested but refused — fail closed for operators.
    if report.get("apply_refused"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
