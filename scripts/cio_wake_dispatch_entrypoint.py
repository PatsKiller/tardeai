"""
CIO Wake Dispatch Entrypoint — Recurring dispatcher scheduler entry.

This is the correct entry-point for the recurring cron/systemd timer.
It replaces the broken direct-CIORunWorker cron that existed before
Gate-B/Level-0.

The entry:
  1. Applies CIOWakeBacklogPolicy to PENDING wakes (expire, cancel
     superseded, mark already-satisfied)
  2. Calls CIOWakeDispatcher.poll_and_dispatch() — sole wake claimant
  3. Executes CIORunWorker on each dispatched run_id — run executor only

CIORunWorker never scans wakes, claims wakes, or creates runs.
CIOWakeDispatcher is the sole wake owner.

Usage:
    python3 scripts/cio_wake_dispatch_entrypoint.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure project root on path
_PROJECT = Path(__file__).resolve().parents[1]
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

log = logging.getLogger("tradeai.cio_wake_dispatch_entrypoint")


def main():
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore
    from scripts.lib.cio_run import CIORunStore
    from scripts.lib.cio_run_worker import CIORunWorker
    from scripts.lib.cio_wake_dispatcher import CIOWakeDispatcher
    from scripts.lib.cio_wake_backlog_policy import CIOWakeBacklogPolicy

    wake_store = CIOWakeJobStore()
    run_store = CIORunStore()
    run_store.initialize()

    # ── Step 0: Backlog policy ─────────────────────────────────────────
    policy = CIOWakeBacklogPolicy()
    backlog_result = policy.apply(wake_store, run_store=run_store, max_dispatches=5)
    total_classified = (
        backlog_result["dispatched_count"]
        + backlog_result["expired_count"]
        + backlog_result["superseded_count"]
        + backlog_result["satisfied_count"]
    )
    if total_classified > 0:
        log.info(
            "backlog: classified=%s DISPATCH=%s EXPIRE=%s SUPERSEDED=%s SATISFIED=%s",
            total_classified,
            backlog_result["dispatched"],
            backlog_result["expired"],
            backlog_result["superseded"],
            backlog_result["satisfied"],
        )

    # ── Step 1: Dispatch ──────────────────────────────────────────────
    dispatcher = CIOWakeDispatcher(wake_store=wake_store, run_store=run_store)
    result = dispatcher.poll_and_dispatch(max_dispatches=5)

    log.info(
        "dispatched=%s skipped=%s errors=%s",
        result["dispatched_count"],
        result["skipped_count"],
        result["error_count"],
    )

    # ── Step 2: Execute each dispatched run ────────────────────────────
    worker = CIORunWorker(run_store=run_store, mode="shadow")
    for d in result.get("dispatched", []):
        run_id = d["run_id"]
        wake_id = d["wake_job_id"]

        dispatcher.mark_in_flight(wake_id)
        exec_result = worker.execute(run_id)

        # Terminal closure
        dispatcher.on_run_completed(
            wake_id,
            run_id,
            exec_result.get("status", "FAILED"),
        )

        log.info(
            "run=%s wake=%s status=%s blocked_by=%s",
            run_id,
            wake_id,
            exec_result.get("status"),
            exec_result.get("blocked_by", ""),
        )

    log.info("entrypoint complete: runs=%s", result["dispatched_count"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    main()
