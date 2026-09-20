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
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.deepseek_offpeak import is_scheduled_deepseek_window  # noqa: E402
from lib import llm_deferral  # noqa: E402

# Durable proof this ran, healthy or empty — a lane is verified by an artifact, never by
# an exit code (config/lane_registry.json, lane `llm-deferred-drain`).
HEARTBEAT_PATH = PROJECT_ROOT / "data/runtime/llm_deferred_drain.json"


def _write_heartbeat(payload: dict) -> None:
    try:
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_PATH.write_text(json.dumps(payload, indent=2))
    except OSError as e:
        print(f"[deferred-drain] could not write heartbeat: {e}", file=sys.stderr)


def _run_one(row: dict) -> tuple[bool, str | None]:
    """Re-issue one queued call, with deferral bypassed so it cannot re-queue itself."""
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--dry-run", action="store_true", help="show the batch, call nothing")
    ap.add_argument("--force", action="store_true",
                    help="drain outside the off-peak window (operator, deliberate)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    in_window = is_scheduled_deepseek_window()
    try:
        # Recover anything a previous run stranded BEFORE counting, or the summary
        # reports a queue that is smaller than the work actually outstanding.
        reclaimed = llm_deferral.reclaim_stale()
        expired = llm_deferral.expire_stale()
        summary = llm_deferral.queue_summary()
    except Exception as e:
        print(f"[deferred-drain] queue unreachable: {e}", file=sys.stderr)
        return 2

    if not in_window and not args.force:
        # Not an error. The queue exists precisely so this work waits.
        result = {"skipped": "OUTSIDE_OFFPEAK_WINDOW", "expired": expired,
                  "reclaimed": reclaimed, **summary}
        if not args.dry_run:
            _write_heartbeat({"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **result})
        print(json.dumps(result, indent=2) if args.json
              else f"[deferred-drain] outside off-peak window; "
                   f"{summary['pending']} pending, {expired} expired")
        return 0

    if args.dry_run:
        # READ-ONLY. This must never call claim_due(): a preview that claims consumes the
        # work it is previewing and strands it. Measured 2026-09-20, on the first live use.
        try:
            preview = llm_deferral.preview_due(limit=args.limit)
        except Exception as e:
            print(f"[deferred-drain] could not preview: {e}", file=sys.stderr)
            return 2
        print(json.dumps({"would_run": [
            {"id": str(r["id"]), "process_id": r["process_id"], "lane": r["lane"],
             "task_summary": r.get("task_summary")} for r in preview],
            "expired": expired, "reclaimed": reclaimed, **summary}, indent=2))
        return 0

    try:
        batch = llm_deferral.claim_due(limit=args.limit)
    except Exception as e:
        print(f"[deferred-drain] could not claim: {e}", file=sys.stderr)
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
    print(json.dumps(result, indent=2) if args.json
          else f"[deferred-drain] {len(batch)} claimed, {ok_n} ok, {fail_n} failed, "
               f"{expired} expired, {after['pending']} still pending")
    return 0


if __name__ == "__main__":
    sys.exit(main())
