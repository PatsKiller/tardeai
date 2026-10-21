#!/usr/bin/env python3
"""release_train_window_request.py — the n8n release-train request lane: append ONE TrainWindowRequest@v1, or nothing.

Release Train v2, Phase 4 (contract ``docs/ops/RELEASE_TRAIN_N8N_CONTRACT.md`` §5). Fired only by the n8n workflow
``tradeai-fabric-release-train`` through Run Lane (lanes ``release-train-request-<HHMM>``, one per window slot; the
slot is in the reviewed allowlist argv because a run request may name only a lane and a mode, AGENTS.md §23.3).

    python3 scripts/release_train_window_request.py --window 1800 --dry-run            # default: prints, writes nothing
    python3 scripts/release_train_window_request.py --window 1800 --append --shadow-only
    python3 scripts/release_train_window_request.py --window 1800 --append

What it does, on the host, every run: resolves the slot's window from the clock (DST-safe), classifies the tick
(on/off window), re-reads the STOP latch, the policy (armed, window enabled), the standing delegation and the
coordination config (shadow switch), and decides: no-op (STOP set or unreadable; or neither live-able nor shadow
enabled) or one request (``shadow`` true unless every live condition holds; an off-window request is always shadow).

What it writes: with ``--append`` only, ``<state_dir>/train_requests/journal/<id>.json`` (O_EXCL) + its ``pending/``
link, and the lane receipt ``data/runtime/release-train-request-<HHMM>_last.json`` (LaneRunReceipt, output fields:
produced_count 1 for an appended request, else 0 with empty_reason ``nothing_due``). ``--dry-run`` builds and
validates the same row, prints ``DRY-RUN {...}`` and writes nothing at all (AGENTS.md §6).

What it never does: merge, push, promote, roll back, run ``release_window.py`` or ``release_control_cli.py``, issue
or reserve a capability, write the STOP latch, read a credential, open a network connection, or send a message.
A request is REQUEST_ONLY: the controller re-validates every gate (contract C1-C4).

Exit: 0 = the run completed (a no-op or a duplicate is a result, not a failure); 1 = config/policy unusable or the
append failed; 2 = usage. MBI_BEHAVIOR = 0. AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import lane_last_receipt as LR  # noqa: E402
from scripts.lib import release_train_window as W  # noqa: E402

SCRIPT = "scripts/release_train_window_request.py"


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="release_train_window_request.py", description=__doc__.splitlines()[0])
    ap.add_argument("--window", required=True, choices=list(W.SLOTS), help="the window slot (HHMM, ET)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the request; write nothing (default)")
    mode.add_argument("--append", action="store_true", help="append the request to the spool")
    ap.add_argument("--shadow-only", action="store_true", help="never request a live train (shadow phase lanes)")
    ap.add_argument("--state-dir", default=None, help="release-window state dir (default: resolved like the runner)")
    ap.add_argument("--config", default=None, help=argparse.SUPPRESS)
    return ap


def run(
    argv: list[str],
    *,
    now: Optional[datetime] = None,
    policy: Optional[dict] = None,
    delegation_loader: Optional[Callable[[], Any]] = None,
    receipt_path: Optional[Path] = None,
    environ: Optional[dict] = None,
) -> int:
    try:
        a = _parser().parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code not in (0, None) else 0
    env = os.environ if environ is None else environ
    now = now or datetime.now(timezone.utc)
    lane_id = W.lane_for_slot(a.window)
    started = now.isoformat()
    append = bool(a.append)
    state_dir = Path(a.state_dir) if a.state_dir else None
    try:
        cfg = W.load_config(Path(a.config) if a.config else None)
    except W.ContractError as exc:
        return _finish(lane_id, append, False, {"disposition": "error", "reason": str(exc)[:160]}, started,
                       receipt_path, exit_code=1)
    snapshot = W.host_snapshot(now, a.window, cfg, stop_dir=state_dir, policy=policy,
                               delegation_loader=delegation_loader)
    start = W.window_start(a.window, now, cfg)
    tick = W.tick_kind(start, now, cfg)
    decision = W.decide(snapshot, tick, shadow_only=bool(a.shadow_only))
    summary: dict[str, Any] = {
        "slot": a.window, "window_id": W.window_id(start), "tick": tick, "disposition": decision["disposition"],
        "no_op_reason": decision["no_op_reason"], "shadow": decision["shadow"],
        "shadow_reason": decision["shadow_reason"], "readiness": snapshot, "request_id": None,
        "append": append,
    }
    if decision["disposition"] == "no_op":
        return _finish(lane_id, append, True, summary, started, receipt_path)
    run_id = env.get(LR.RUN_ID_ENV) or f"manual-{lane_id}-{now.strftime('%Y%m%dT%H%M%S')}"
    attempt_raw = env.get(LR.RUN_ATTEMPT_ENV) or ""
    try:
        doc = W.build_request(a.window, now, cfg, snapshot, decision, run_id=run_id,
                              attempt=int(attempt_raw) if attempt_raw.isdigit() else None,
                              run_mode=env.get(LR.RUN_MODE_ENV) or None, code_sha=env.get(LR.CODE_SHA_ENV) or None)
    except W.ContractError as exc:
        summary.update({"disposition": "error", "reason": str(exc)[:160]})
        return _finish(lane_id, append, False, summary, started, receipt_path, exit_code=1)
    summary["request_id"] = doc["request_id"]
    if not append:
        summary["would_append"] = doc
        return _finish(lane_id, False, True, summary, started, receipt_path)
    try:
        result, path = W.append_request(doc, state_dir)
    except (OSError, W.ContractError) as exc:
        summary.update({"disposition": "error", "reason": f"append failed: {type(exc).__name__}"})
        return _finish(lane_id, True, False, summary, started, receipt_path, exit_code=1)
    summary["disposition"] = "requested" if result == "appended" else "duplicate"
    summary["spool_path"] = str(path)
    return _finish(lane_id, True, True, summary, started, receipt_path,
                   produced=1 if result == "appended" else 0, evidence_path=str(path))


def _finish(lane_id: str, append: bool, ok: bool, summary: dict, started: str, receipt_path: Optional[Path], *,
            exit_code: int = 0, produced: int = 0, evidence_path: Optional[str] = None) -> int:
    if not append:
        LR.dry_run_report(lane_id, summary, would_write=["train_requests/journal/<request_id>.json",
                                                         "train_requests/pending/<request_id>.json"],
                          receipt=receipt_path)
        return exit_code
    output = {
        "produced_count": produced,
        "attempted_count": 1 if summary.get("disposition") in ("requested", "duplicate") else 0,
        "skipped_reasons": {summary["disposition"]: 1} if summary.get("disposition") not in (None, "requested")
        else {},
        "empty_reason": None if produced else "nothing_due",
        "output_evidence": [{"kind": "file_artifact", "path": evidence_path}] if evidence_path else [],
    }
    LR.write_lane_receipt(lane_id, ok=ok, exit_code=exit_code, started_at=started, script=SCRIPT,
                          summary={k: v for k, v in summary.items() if k != "would_append"},
                          path=receipt_path, output=output)
    print(json.dumps({"lane_id": lane_id, **{k: summary.get(k) for k in
                      ("disposition", "request_id", "shadow", "shadow_reason", "no_op_reason", "tick")}},
                     sort_keys=True))
    return exit_code


def main(argv: Optional[list[str]] = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
