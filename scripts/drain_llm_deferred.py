#!/usr/bin/env python3
"""drain_llm_deferred.py — run the paid LLM work that was queued for off-peak.

The other half of `lib/llm_deferral`. When the free lanes are exhausted and the work is
not the operator's own ask, the call is queued instead of paid for at peak rates. This
drains that queue inside the off-peak window.

It refuses to run outside the window, because a drainer that ignores the window is just
a way of paying peak prices on a delay. `--force` exists for an operator who means it.

  drain_llm_deferred.py --dry-run     # show what would run, call nothing
  drain_llm_deferred.py               # drain, inside the window only
  drain_llm_deferred.py --limit 50    # wider batch
  drain_llm_deferred.py --force       # run outside the window (operator, deliberate)

Exit 0 = drained (or nothing due). Exit 2 = queue unreachable.

Governed bridge (2026-10-15, n8n llm lane batch 3): with TRADEAI_LLM_VIA_BRIDGE=1 (bound by the n8n run executor from
the allowlist ``llm_route`` of lane llm-deferred-drain, a process SET) the drainer leases ONLY rows whose process is in
the bound set (llm_deferral.claim_due process_ids; every other row stays pending for the host drainer) and re-issues
each as ONE governed-bridge request as that row's own process (the bridge routes it OAuth first and applies that
process's caps; the row's stored lane / model / policy are NOT honoured, because §23.4 lets no request choose a
model). gate_and_generate is never imported on that path. A refusal fails the row exactly like a provider error
(failed + error text); nothing else runs for it. --dry-run claims nothing and calls nothing. The cron line is unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


# Durable proof this ran, healthy or empty — a lane is verified by an artifact, never by
# an exit code (config/lane_registry.json, lane `llm-deferred-drain`).
HEARTBEAT_PATH = None  # resolved lazily against STATE_ROOT on a real run only


def _receipt(ok: bool, exit_code: int, summary: dict) -> None:
    from lib.lane_last_receipt import write_lane_receipt
    write_lane_receipt("llm-deferred-drain", ok=ok, exit_code=exit_code,
                       script="drain_llm_deferred.py", summary=summary)


def _write_heartbeat(payload: dict) -> None:
    try:
        from lib.lane_last_receipt import runtime_dir
        path = HEARTBEAT_PATH or runtime_dir() / "llm_deferred_drain.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2))
    except OSError as e:
        print(f"[deferred-drain] could not write heartbeat: {e}", file=sys.stderr)


def _via_bridge() -> bool:
    """The flag the n8n run executor binds from the allowlist llm_route; read directly."""
    import os

    return os.environ.get("TRADEAI_LLM_VIA_BRIDGE", "off").strip().lower() in {"1", "on", "bridge"}


def _bound_process_set() -> list[str]:
    """The processes the executor bound for this run ([] = none: the bridge drain then leases nothing)."""
    from lib.llm_bridge_route import bound_processes

    return sorted(bound_processes() or ())


def _run_one_via_bridge(row: dict) -> tuple[bool, str | None]:
    """ONE governed-bridge request as the row's own process. Never gate_and_generate, never the row's lane."""
    from lib.llm_bridge_route import require_text_via_bridge

    payload = row.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload or "{}")
    try:
        require_text_via_bridge(str(row["process_id"]), row["prompt"], timeout_s=180,
                                max_tokens=int(payload.get("max_tokens") or 2048))
    except Exception as e:  # noqa: BLE001 -- a refusal fails the row; never another provider
        return False, f"{type(e).__name__}: {e}"[:300]
    return True, None


def _run_one(row: dict) -> tuple[bool, str | None]:
    """Re-issue one queued call, with deferral bypassed so it cannot re-queue itself."""
    if _via_bridge():
        return _run_one_via_bridge(row)
    from lib.llm_consumption import gate_and_generate

    payload = row.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload or "{}")
    meta = dict(payload.get("metadata") or {})
    meta["deferral_bypass"] = True
    meta["deferred_request_id"] = str(row["id"])
    try:
        out = gate_and_generate(
            row["prompt"],
            lane=row["lane"],
            process_id=row["process_id"],
            task_summary=row.get("task_summary"),
            metadata=meta,
            model=payload.get("model"),
            max_tokens=int(payload.get("max_tokens") or 2048),
            response_json=bool(payload.get("response_json")),
            output_schema_id=payload.get("output_schema_id"),
            policy=payload.get("policy"),
        )
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"[:300]
    if not out or not str(out).strip():
        return False, "empty response"
    return True, None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--dry-run", action="store_true", help="show the batch, call nothing")
    ap.add_argument("--force", action="store_true",
                    help="drain outside the off-peak window (operator, deliberate)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.dry_run:
        print(f"DRY-RUN llm-deferred-drain: would drain up to {args.limit} queued requests within existing offpeak policy; no DB, reclaim, expiry, claim or model call")
        return 0
    from lib.deepseek_offpeak import is_scheduled_deepseek_window
    from lib import llm_deferral

    in_window = is_scheduled_deepseek_window()
    try:
        # Recover anything a previous run stranded BEFORE counting, or the summary
        # reports a queue that is smaller than the work actually outstanding.
        reclaimed = llm_deferral.reclaim_stale()
        expired = llm_deferral.expire_stale()
        summary = llm_deferral.queue_summary()
    except Exception as e:
        print(f"[deferred-drain] queue unreachable: {e}", file=sys.stderr)
        _receipt(False, 2, {"queue_error": type(e).__name__})
        return 2

    if not in_window and not args.force:
        # Not an error. The queue exists precisely so this work waits.
        result = {"skipped": "OUTSIDE_OFFPEAK_WINDOW", "expired": expired,
                  "reclaimed": reclaimed, **summary}
        _write_heartbeat({"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **result})
        print(json.dumps(result, indent=2) if args.json
              else f"[deferred-drain] outside off-peak window; "
                   f"{summary['pending']} pending, {expired} expired")
        return 0

    try:
        batch = (llm_deferral.claim_due(limit=args.limit, process_ids=_bound_process_set()) if _via_bridge()
                 else llm_deferral.claim_due(limit=args.limit))
    except Exception as e:
        print(f"[deferred-drain] could not claim: {e}", file=sys.stderr)
        _receipt(False, 2, {"claim_error": type(e).__name__})
        return 2

    ok_n = fail_n = 0
    for row in batch:
        ok, err = _run_one(row)
        llm_deferral.complete(str(row["id"]), ok=ok, error=err)
        ok_n, fail_n = (ok_n + 1, fail_n) if ok else (ok_n, fail_n + 1)
        if not ok:
            print(f"[deferred-drain] {row['process_id']}: {err}", file=sys.stderr)

    after = llm_deferral.queue_summary()
    result = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "claimed": len(batch), "ok": ok_n, "failed": fail_n,
              "expired": expired, "reclaimed": reclaimed,
              "forced": bool(args.force), **after}
    _write_heartbeat(result)
    rc = 1 if fail_n else 0
    _receipt(fail_n == 0, rc, {"claimed": len(batch), "completed": ok_n, "failed": fail_n,
                            "expired": expired, "reclaimed": reclaimed})
    print(json.dumps(result, indent=2) if args.json
          else f"[deferred-drain] {len(batch)} claimed, {ok_n} ok, {fail_n} failed, "
               f"{expired} expired, {after['pending']} still pending")
    return rc


if __name__ == "__main__":
    sys.exit(main())
