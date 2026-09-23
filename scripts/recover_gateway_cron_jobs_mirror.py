#!/usr/bin/env python3
"""CLI: recover / flush gateway cron jobs.json mirror (Stage 4).

Examples (from repo root):

  .venv/bin/python scripts/recover_gateway_cron_jobs_mirror.py --dry-run
  .venv/bin/python scripts/recover_gateway_cron_jobs_mirror.py --apply
  .venv/bin/python scripts/recover_gateway_cron_jobs_mirror.py --apply \\
      --operator-pick ~/.openclaw/cron/jobs.json.migrated
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.gateway_cron_jobs_mirror import (  # noqa: E402
    flush_jobs_mirror,
    recover_jobs_json_if_missing,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cron-dir", type=Path, default=None)
    p.add_argument("--dry-run", action="store_true", default=False)
    p.add_argument("--apply", action="store_true", default=False)
    p.add_argument(
        "--operator-pick",
        type=str,
        default=None,
        help="When candidates diverge, path of the chosen .migrated/.bak file",
    )
    p.add_argument(
        "--flush-empty",
        action="store_true",
        default=False,
        help="If primary missing and no candidates, atomically write empty jobs list",
    )
    args = p.parse_args(argv)
    dry = bool(args.dry_run) or not bool(args.apply)
    report = recover_jobs_json_if_missing(
        cron_dir=args.cron_dir,
        dry_run=dry,
        operator_pick=args.operator_pick,
    )
    out = report.to_dict()
    if (
        report.action == "missing_no_candidate"
        and args.flush_empty
        and (args.apply or args.dry_run)
    ):
        out["flush_empty"] = flush_jobs_mirror(
            {"version": 1, "jobs": []},
            cron_dir=args.cron_dir,
            dry_run=dry,
        )
        if args.apply and out["flush_empty"].get("ok"):
            out["ok"] = True
            out["action"] = "flushed_empty"
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
