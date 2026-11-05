#!/usr/bin/env python3
"""pipeline_disk_alert.py — the manifest runner's one way to page the operator about its own host.

Called by scripts/pipelines/_manifest_runner.sh when (a) the disk preflight finds free space below
config/pipelines/runner_disk_policy.json `min_free_mb`, or (b) the PipelineRun summary could not be
written. Both were silent on 2026-10-30 (RCA docs/audits/MARKET_SELLOFF_ALERT_RCA_2026-10-30.md,
finding 7). Sends ONE P1 operator-action intent (dedupe window 0, AGENTS.md §9.1) through the house
chokepoint telegram_alert.send_telegram; exit 0 when accepted, 1 when not, so the runner can log the
failure. Writes a best-effort receipt data/runtime/pipeline_disk_alert_last.json under the state root.
Never sources or prints .env values; telegram_alert bootstraps its own credentials.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

PRODUCER = "manifest_runner"


def build_message(pipeline: str, stage: str, reason: str, avail_mb: int | None, min_mb: int | None, mount: str) -> str:
    when = datetime.now(timezone.utc).astimezone().strftime("%a %m-%d %H:%M %Z")
    head = f"🚨 *PIPELINE HOST ALERT* — {pipeline}/{stage} · {when}"
    if reason == "low_disk":
        body = (
            f"Free space {avail_mb} MB is below the {min_mb} MB floor on {mount}. The steps are still running, "
            f"but logs, receipts and store writes can fail silently from here. Reclaim space now "
            f"(disk-hygiene dry-run first) and watch the pre-market dead-man."
        )
    elif reason == "summary_write_failed":
        body = (
            f"The PipelineRun receipt could not be written on {mount} (free {avail_mb} MB). The stage may have "
            f"run, but nothing durable proves it; freshness monitors will read it as missing."
        )
    else:
        body = f"{reason} (free {avail_mb} MB on {mount})"
    return f"{head}\n{body}"


def write_receipt(payload: dict) -> None:
    try:
        from lib.persistent_state_root import good_persistent_root

        p = good_persistent_root() / "data" / "runtime" / "pipeline_disk_alert_last.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    except Exception as e:  # noqa: BLE001 — a full disk is exactly when this fails; the send already happened
        print(f"[disk-alert] receipt not written: {type(e).__name__}: {e}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pipeline", required=True)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--reason", default="low_disk", choices=["low_disk", "summary_write_failed"])
    ap.add_argument("--avail-mb", type=int)
    ap.add_argument("--min-mb", type=int)
    ap.add_argument("--mount", default="?")
    ap.add_argument("--dry-run", action="store_true", help="print the intent; send nothing")
    args = ap.parse_args(argv)

    message = build_message(args.pipeline, args.stage, args.reason, args.avail_mb, args.min_mb, args.mount)
    print(message)
    if args.dry_run:
        print("[disk-alert] DRY RUN — intent P1 dedupe 0 producer", PRODUCER, "not sent")
        return 0
    accepted, error = False, None
    try:
        from telegram_alert import send_telegram

        accepted = bool(send_telegram(message, priority="P1", dedupe_minutes=0, producer=PRODUCER))
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"
    write_receipt(
        {
            "schema": "PipelineDiskAlert@v1",
            "at": datetime.now(timezone.utc).isoformat(),
            "pipeline": args.pipeline,
            "stage": args.stage,
            "reason": args.reason,
            "avail_mb": args.avail_mb,
            "min_mb": args.min_mb,
            "mount": args.mount,
            "accepted": accepted,
            "error": error,
        }
    )
    if not accepted:
        print(f"[disk-alert] P1 intent NOT accepted ({error or 'send_telegram returned falsy'})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
