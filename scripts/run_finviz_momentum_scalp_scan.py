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

SCALP HOT TIER (operator decision (4), 2026-10-10; inert unless SCALP_HOT_TIER=1 and no kill file, lib/scalp_hot_tier):
  --hot-list-only   the hot-tier list owner: market days 06:00-09:30 ET only, refreshes the four scalp screeners
                    (assets/screeners.yaml window `scalp`) whenever the last DONE receipt is older than ~2 min; no
                    handoff stage. Outside that window, or with the knob off, it prints SKIPPED_* and exits 0.
  (the */5 lane)    with the knob on: inside 06:00-09:30 its own refresh is skipped (the hot line owns it), and its
                    signal-sync + proposal stages run only when the scalp list's as_of advanced
                    (lib/scalp_list_trigger, consumer `l636-proposal-stage`). The validation stage is unchanged.
With the knob off this script behaves exactly as before.
"""
from __future__ import annotations

import argparse
import json
import time as _time
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import momentum_scalp_early_lane_runner as lane  # noqa: E402
from lib import scalp_hot_tier as hot  # noqa: E402
from lib import scalp_list_trigger as trig  # noqa: E402

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


def _proposal_trigger() -> dict:
    """Read the scalp list (read-only) and decide whether the proposal stage fires. Never raises."""
    try:
        from lib.data_broker import scalp_list as sl

        env = sl.get_scalp_list()
    except Exception as exc:  # unreadable list -> decide() sees no as_of -> FIRE_STALE_LIST on the legacy cadence
        env = {"as_of": None, "symbols": [], "error": f"{type(exc).__name__}: {exc}"[:200]}
    return {"list_env": env, "decision": trig.decide("l636-proposal-stage", env)}


def _hot_list_only(args, rep: dict, *, apply: bool, hot_on: bool, hot_list_phase: bool) -> int:
    """The hot-tier list owner: scalp-screener refresh only (no handoff). Single writer stays the screener runner."""
    rep["mode"] = "hot_list_only"
    if not hot_on:
        rep.update(status="SKIPPED_FLAG_OFF", hot_tier=hot.flag_state())
        print(json.dumps(rep, default=str))
        return 0
    if not hot_list_phase and not args.ignore_window:
        rep.update(status="SKIPPED_OFF_HOT_WINDOW", phase=hot.phase(lane.now_et(args.now)))
        print(json.dumps(rep, default=str))
        return 0
    ids = hot.scalp_screener_ids()
    age = lane.refresh_age_min()
    due_after = max(0.0, hot.LIST_REFRESH_MIN - hot.LIST_REFRESH_GRID_TOLERANCE_MIN)
    rep["refresh_policy"] = {"screener_ids": ids, "refresh_if_older_min": hot.LIST_REFRESH_MIN,
                             "due_after_min": due_after, "refresh_age_min": None if age is None else round(age, 2)}
    if age is not None and age < due_after:
        rep["stages"].append({"stage": "finviz_scan", "ran": False, "ok": True,
                              "reason": f"skipped_fresh (age={age:.2f}m < {due_after:g}m)"})
    elif not apply:
        rep["stages"].append({"stage": "finviz_scan", "ran": False, "ok": True, "reason": "dry_run_no_refresh",
                              "would_run": [["finviz_screener_runner.py", "--screener", sid] for sid in ids],
                              "finviz_export_requests": len(ids)})
    else:
        deadline = lane.outer_deadline_s(args.deadline_s)
        rep["stages"].append(lane.stage_finviz_scan(dry_run=False, deadline_s=deadline,
                                                    started_monotonic=_time.monotonic(), screener_ids=ids))
    failed = [st["stage"] for st in rep["stages"] if not st.get("ok")]
    rep.update(status=("DRY_RUN" if not apply else ("PASS" if not failed else "PARTIAL")), failed_stages=failed,
               safety_note="Source refresh only (screener membership). No broker call, no proposal, no send.")
    print(json.dumps(rep, default=str))
    return 0 if not failed else 1


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
    ap.add_argument("--skip-finviz-refresh", action="store_true",
                    help="run handoff stages only (fast) — used by health auto-remediation to unstick the lane")
    ap.add_argument("--refresh-if-older-min", type=float, default=None,
                    help="refresh Finviz only when the last DONE refresh receipt is older than N minutes "
                         "(one cron line, one lock; replaces the killed */15 refresh line — 2026-09-28)")
    ap.add_argument("--deadline-s", type=float, default=None,
                    help="outer deadline in seconds (default env MOMENTUM_SCALP_OUTER_DEADLINE_S); "
                         "stage timeouts are clamped so the run ends before cron's `timeout` kills it")
    ap.add_argument("--hot-list-only", action="store_true",
                    help="scalp hot tier list owner (SCALP_HOT_TIER=1): 2-min scalp-screener refresh 06:00-09:30 ET")
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

    hot_on = hot.enabled()
    hot_list_phase = hot_on and hot.in_window("list_hot", t)
    rep["hot_tier"] = {"enabled": hot_on, "list_hot_phase": hot_list_phase}
    if args.hot_list_only:
        return _hot_list_only(args, rep, apply=apply, hot_on=hot_on, hot_list_phase=hot_list_phase)

    if not window_ok and not args.ignore_window:
        rep.update(status="SKIPPED_OFF_WINDOW",
                   note="Off-window no-op (06:00-12:00 ET trading days). Use --ignore-window to force.")
        print(json.dumps(rep, default=str))
        return 0

    # Stage 1 — Finviz source refresh (throttle-safe; source rows only). Skippable for a fast
    # downstream-only unstick (health auto-remediation).
    deadline = lane.outer_deadline_s(args.deadline_s)
    started = _time.monotonic()
    rep["deadline_s"] = deadline
    if args.skip_finviz_refresh:
        rep["stages"].append({"stage": "finviz_scan", "ran": False, "ok": True, "reason": "skipped_finviz_refresh"})
    elif hot_list_phase:
        rep["stages"].append({"stage": "finviz_scan", "ran": False, "ok": True,
                              "reason": "skipped_hot_tier_owns_refresh (--hot-list-only line, 06:00-09:30 ET)"})
    elif args.refresh_if_older_min is not None:
        age = lane.refresh_age_min()
        # Grid tolerance (2026-09-28, observed 10:20→11:40): the lane runs on a */5 grid and the
        # DONE receipt is stamped ~20 s into a run, so at the 15-minute mark the age reads
        # 14.5–14.7 min and the refresh slipped to every 20 min. A refresh is due when the age is
        # within one grid slack of the threshold.
        if age is not None and age < args.refresh_if_older_min - lane.REFRESH_GRID_TOLERANCE_MIN:
            rep["stages"].append({"stage": "finviz_scan", "ran": False, "ok": True,
                                  "reason": f"skipped_finviz_refresh_fresh (age={age:.1f}m < {args.refresh_if_older_min:g}m)",
                                  "refresh_age_min": round(age, 1)})
        else:
            st = lane.stage_finviz_scan(dry_run=not apply, deadline_s=deadline, started_monotonic=started)
            st["refresh_age_min_before"] = None if age is None else round(age, 1)
            rep["stages"].append(st)
    else:
        rep["stages"].append(lane.stage_finviz_scan(dry_run=not apply, deadline_s=deadline, started_monotonic=started))
    # Stage 2-4 — optional handoff. With the hot tier on, sync + proposals fire on the scalp list's as_of advancing.
    trigger = None
    if hot_on and (sync or gen):
        trigger = _proposal_trigger()
        rep["hot_tier"]["proposal_trigger"] = trigger["decision"]
    if trigger is not None and not trigger["decision"].get("fire"):
        why = "skipped_no_list_advance: " + str(trigger["decision"].get("decision"))
        if sync:
            rep["stages"].append({"stage": "signal_sync", "ran": False, "ok": True, "reason": why})
        if gen:
            rep["stages"].append({"stage": "proposal_gen", "ran": False, "ok": True, "reason": why})
    else:
        if sync:
            rep["stages"].append(lane.stage_signal_sync(dry_run=not apply))
        if gen:
            rep["stages"].append(lane.stage_proposal_gen(dry_run=not apply))
        handoff_ok = all(st.get("ok") for st in rep["stages"] if st.get("stage") in ("signal_sync", "proposal_gen"))
        if trigger is not None and apply and handoff_ok:
            trig.commit("l636-proposal-stage", trigger["list_env"], decision=trigger["decision"]["decision"])
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
