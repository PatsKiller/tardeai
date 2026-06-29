#!/usr/bin/env python3
"""run_finviz_momentum_scalp_scan.py — P0-2: canonical every-5-minute Finviz momentum-scalp scan.

Operator decision (2026-06-28): Finviz momentum-scalp discovery runs every 5 minutes, 06:00-12:00 ET,
trading days. This wrapper refreshes the Finviz source (throttle-safe, reusing the proven
finviz_screener_runner) and OPTIONALLY hands off to the early lane (signal sync → proposals →
validation fast path). Default is DRY-RUN. Source rows only — NO broker calls.

SAFETY: no live broker writes; sandbox/simulated validation only (and only with an explicit flag/env);
operator confirmation / 2FA untouched; quote freshness / TTL / route policy / liquidity / risk gates /
kill switches never weakened. Social-only stays WATCH/WAIT/SCOUT; large-float scouts manual-review only.

    python3 scripts/run_finviz_momentum_scalp_scan.py --dry-run            # report only (default)
    python3 scripts/run_finviz_momentum_scalp_scan.py --apply             # finviz source refresh
    python3 scripts/run_finviz_momentum_scalp_scan.py --apply --sync-signals --generate-proposals \
        --run-validation-fast-path                                        # full early-lane handoff

Env flags (cron): MOMENTUM_SCALP_EARLY_LANE=1 (enable handoff), MOMENTUM_SCALP_SYNC_SIGNALS=1,
MOMENTUM_SCALP_GENERATE_PROPOSALS=1, MOMENTUM_SCALP_VALIDATION_FAST_PATH=1, MOMENTUM_SCALP_VALIDATION_SUBMIT=1.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import momentum_scalp_early_lane_runner as lane  # noqa: E402

CONFIG = ROOT / "config" / "finviz_momentum_scalp_screen.yaml"


def load_window() -> dict:
    try:
        cfg = yaml.safe_load(CONFIG.read_text())["momentum_scalp_finviz_screen"]
        w = cfg.get("window_et") or {}
        return {"start": w.get("start", "06:00"), "end": w.get("end", "12:00")}
    except Exception:
        return dict(lane.WINDOW)


def _env(name: str) -> bool:
    return os.getenv(name) == "1"


def main() -> int:
    ap = argparse.ArgumentParser(description="Finviz momentum-scalp scan (every 5 min, 06:00-12:00 ET)")
    ap.add_argument("--dry-run", action="store_true", help="report only (default)")
    ap.add_argument("--apply", action="store_true", help="run the Finviz source refresh (source rows only)")
    ap.add_argument("--window", choices=["early", "full"], default="full",
                    help="early/full both map to the 06:00-12:00 ET strategy window")
    ap.add_argument("--sync-signals", action="store_true", help="hand off to strategy_signal_sync")
    ap.add_argument("--generate-proposals", action="store_true", help="hand off to auto_proposal_generator")
    ap.add_argument("--run-validation-fast-path", action="store_true",
                    help="hand off to the validation fast path (dry unless --submit-validation/env)")
    ap.add_argument("--submit-validation", action="store_true", help="sandbox validation submit")
    ap.add_argument("--ignore-window", action="store_true", help="run outside 06:00-12:00 ET")
    ap.add_argument("--now", type=str, help="override ET now (ISO) for testing")
    args = ap.parse_args()

    window = load_window()
    t = lane.now_et(args.now)
    window_ok = lane.is_trading_day(t) and lane.in_window(t, window)
    apply = args.apply and not args.dry_run

    # Env-driven handoff (cron): MOMENTUM_SCALP_EARLY_LANE enables the chain.
    early = _env("MOMENTUM_SCALP_EARLY_LANE")
    sync = args.sync_signals or (early and _env("MOMENTUM_SCALP_SYNC_SIGNALS")) or (early and not any(
        [args.sync_signals, args.generate_proposals, args.run_validation_fast_path]))
    gen = args.generate_proposals or (early and _env("MOMENTUM_SCALP_GENERATE_PROPOSALS"))
    val = args.run_validation_fast_path or (early and _env("MOMENTUM_SCALP_VALIDATION_FAST_PATH"))
    submit = args.submit_validation or _env("MOMENTUM_SCALP_VALIDATION_SUBMIT")

    rep = {"tool": "run_finviz_momentum_scalp_scan", "generated_at": datetime.now().isoformat(),
           "now_et": t.strftime("%H:%M"), "window": window, "window_ok": window_ok,
           "dry_run": not apply, "stages": []}

    if not window_ok and not args.ignore_window:
        rep.update(status="SKIPPED_OFF_WINDOW",
                   note="Off-window no-op (06:00-12:00 ET trading days). Use --ignore-window to force.")
        print(json.dumps(rep, default=str))
        return 0

    # Stage 1 — Finviz source refresh (throttle-safe; source rows only).
    rep["stages"].append(lane.stage_finviz_scan(dry_run=not apply))
    # Stage 2-4 — optional handoff.
    if sync:
        rep["stages"].append(lane.stage_signal_sync(dry_run=not apply))
    if gen:
        rep["stages"].append(lane.stage_proposal_gen(dry_run=not apply))
    if val:
        rep["stages"].append(lane.stage_validation(submit=submit and apply))

    counts = lane.scan_counts()
    failed = [s["stage"] for s in rep["stages"] if not s.get("ok")]
    rep.update(status=("DRY_RUN" if not apply else ("PASS" if not failed else "PARTIAL")),
               scan_counts=counts, failed_stages=failed,
               handoff={"sync_signals": sync, "generate_proposals": gen,
                        "run_validation_fast_path": val, "submit_validation": submit and apply},
               safety_note="No live broker writes. Sandbox/simulated validation only. Operator/2FA untouched.",
               validation_note="Validation maturity unchanged — empirical sample is still the blocker to 4.5.")
    # Single parseable JSON log line (timestamp, counts, GO/WAIT/SCOUT, handoff, errors).
    print(json.dumps(rep, default=str))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
