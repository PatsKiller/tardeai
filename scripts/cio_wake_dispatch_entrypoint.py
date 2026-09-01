"""
CIO Wake Dispatch Entrypoint — Recurring dispatcher scheduler entry.

This is the correct entry-point for the recurring cron/systemd timer.
It replaces the broken direct-CIORunWorker cron that existed before
Gate-B/Level-0.

The entry:
  1. Applies CIOWakeBacklogPolicy to PENDING wakes (expire, cancel
     superseded, mark already-satisfied)
  2. Calls CIOWakeDispatcher.poll_and_dispatch() — sole wake claimant
  3. For each dispatched wake: load-by-subject and run the research gate
     (`decide_after_load`, #810) BEFORE the run executes
  4. Executes CIORunWorker on each dispatched run_id — run executor only
  5. Applies the cycle as COGNITION and persists the record

Until 2026-09-01 steps 3 and 5 existed only behind `--dry-run`, and the
installed timer runs without it (`crontab: */5 * * * * ... no flag`). So the
#810 function was reachable only by hand: `load-by-subject` was built, tested,
and consumed by no scheduled wake -- the dark contract in AGENTS.md 13.4.
`test_entrypoint_exposes_dry_run_flag` asserted only that the NAME appeared in
this file, which a dry-run-only call satisfies. A grep for a symbol cannot see
which branch the symbol is in.

CIORunWorker never scans wakes, claims wakes, or creates runs.
CIOWakeDispatcher is the sole wake owner.

Usage:
    python3 scripts/cio_wake_dispatch_entrypoint.py
    python3 scripts/cio_wake_dispatch_entrypoint.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure project root on path
_PROJECT = Path(__file__).resolve().parents[1]
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

log = logging.getLogger("tradeai.cio_wake_dispatch_entrypoint")


def dry_run_record_consult(*, max_wakes: int = 5) -> list[dict]:
    """P1 dry-run: load-by-subject + cadence verdict. No claim, no run, no Telegram.

    Prints one line per PENDING wake: subject_key, wake verdict, research
    preflight decision, and whether ResearchNeedDecision.decide would be called.
    """
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore
    from scripts.lib.cio_wake_subject import decide as wake_decide
    from scripts.lib.cio_instrument_record import InstrumentRecordStore
    from scripts.lib.cio_research_preflight import decide_after_load

    wake_store = CIOWakeJobStore()
    wakes = wake_store.list_wakes(status="PENDING", limit=max_wakes)
    try:
        store = InstrumentRecordStore()
        known = {str(r.get("subject_key")) for r in store.all() if r.get("subject_key")}
    except Exception as exc:
        log.warning("record store unavailable for dry-run: %s", exc)
        store, known = None, set()

    rows: list[dict] = []
    for wake in wakes:
        wd = wake_decide(wake, store=store, known_keys=known)
        sk = wd.get("subject_key")
        research = None
        if sk:
            research = decide_after_load(
                sk, plan={"material": True, "symbols": [str(sk).split(":")[-1]]},
            )
        row = {
            "wake_job_id": wake.get("wake_job_id"),
            "subject_key": sk,
            "wake_verdict": wd.get("verdict"),
            "wake_reason": wd.get("reason"),
            "record_found": wd.get("record_found"),
            "research_decision": (research or {}).get("decision"),
            "research_reason": (research or {}).get("reason"),
            "decide_called": (research or {}).get("decide_called"),
            "record_loaded": (research or {}).get("record_loaded"),
        }
        rows.append(row)
        print(
            f"P1_DRY subject_key={row['subject_key']!r} "
            f"wake_verdict={row['wake_verdict']} "
            f"research={row['research_decision']}/{row['research_reason']} "
            f"decide_called={row['decide_called']} "
            f"record_loaded={row['record_loaded']} "
            f"wake={row['wake_job_id']}"
        )
    if not rows:
        print("P1_DRY no PENDING wakes")
    return rows


def apply_cycle_and_persist(subject_key: str, research: dict | None,
                            exec_result: dict | None = None) -> dict:
    """Apply one dispatched wake as cognition, then persist the record.

    The writer is the existing one: `cio_rehydrate.apply_after_cycle` produces
    the cognition delta and `InstrumentRecordStore.upsert` is the store's own
    append-only write. No second store is created here, and nothing routes
    around `apply_cognition` -- which is what raises BehaviorWriteRefused, so
    a behaviour field can never reach the record through this path.

    `strict=False` deliberately: a wake that moved nothing must be RECORDED as
    a no-op, not raised into a cron loop where it would abort the remaining
    dispatches. The no-op is still a failed persist and is counted as one.
    """
    out = {"subject_key": subject_key, "persisted": False, "reason": None,
           "changed": []}
    if not subject_key:
        out["reason"] = "no_subject"
        return out
    try:
        from scripts.lib.cio_instrument_record import InstrumentRecordStore
        from scripts.lib.cio_rehydrate import apply_after_cycle

        store = InstrumentRecordStore()
        rec = store.load(subject_key)
        if not rec:
            out["reason"] = "no_record"
            return out
        updated, changed = apply_after_cycle(
            rec, decision=research or None, strict=False,
        )
        out["changed"] = list(changed)
        if not changed:
            # AGENTS.md 13.4: a cognition write moving none of the four fields
            # is a FAILED persist. Reported, never silently counted as success.
            out["reason"] = "cognition_noop"
            return out
        store.upsert(updated)
        out["persisted"] = True
        out["reason"] = "persisted"
        return out
    except Exception as exc:
        # Named, never bare: a write-back failure must not take down the
        # dispatch cycle, and must not disappear either.
        log.exception("cognition write-back failed for %s", subject_key)
        out["reason"] = f"{type(exc).__name__}: {exc}"
        return out


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Consult records only — no claim, no run mint, no Telegram",
    )
    args = ap.parse_args(argv)
    if args.dry_run:
        dry_run_record_consult()
        return

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

    # ── Step 1b: M5 evidence ──────────────────────────────────────────
    # The record consult happens inside poll_and_dispatch, before any claim.
    # Emit what it changed, to the log AND to a durable artifact, so the proof
    # comes from a scheduled unattended run rather than from running this by
    # hand. A lane whose only evidence is a hand-run has not proven a schedule.
    consult = result.get("record_consult") or {}
    log.info(
        "record_consult: wakes=%s subject_resolved=%s record_found=%s "
        "changed_by_record=%s skipped_cadence_not_due=%s no_subject=%s",
        consult.get("wakes_considered"), consult.get("subject_resolved"),
        consult.get("record_found"), consult.get("decisions_changed_by_record"),
        consult.get("skipped_cadence_not_due"), consult.get("no_subject"),
    )
    for ch in (consult.get("changed") or []):
        log.info("record_changed_decision: subject=%s without_record=%s "
                 "with_record=%s reason=%s",
                 ch.get("subject_key"), ch.get("without_record"),
                 ch.get("with_record"), ch.get("reason"))
    try:
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        _p = _PROJECT / "data" / "cio" / "wake_record_consult.json"
        _p.parent.mkdir(parents=True, exist_ok=True)
        _p.write_text(_json.dumps({
            "schema": "WakeRecordConsult@v1",
            "authority": "READ_ONLY_ADVISORY",
            "as_of": _dt.now(_tz.utc).replace(microsecond=0).isoformat(),
            "unattended": True,
            "entrypoint": "cron: */5 * * * * cio_wake_dispatch_entrypoint.py",
            **consult,
        }, indent=2, default=str) + "\n", encoding="utf-8")
    except Exception:
        log.exception("record_consult artifact write failed (fail-soft)")

    # ── Step 1b: Persist today's investment books even if no wake fires ─
    try:
        from scripts.lib.cio_investment_product import build_product, persist_product
        persist_product(build_product())
    except Exception:
        log.exception("investment product persist failed (fail-soft)")

    # ── Step 2: Execute each dispatched run ────────────────────────────
    from scripts.lib.cio_action_ledger import CIOActionLedger
    from scripts.lib.cio_notification_outbox import NotificationOutbox
    from scripts.lib.cio_investment_product import build_investment_product_synthesis_fn
    from scripts.lib.cio_health_boundary import CIOHealthBoundary
    from scripts.lib.cio_operator_profile import OperatorProfile

    # The snapshot collects health_data_quality and operator_profile only from
    # the stores handed to the worker. This entrypoint passed neither, so both
    # REQUIRED domains resolved DATA_UNAVAILABLE on every run and the evidence
    # gate blocked before synthesis -- 54 of 55 runs, continuously since
    # 2026-08-10. The gate was right; it was being asked about stores nobody
    # gave it. Fail-soft: a store that cannot be built leaves its domain
    # unavailable, which is the pre-existing behaviour, never a fabricated one.
    try:
        health_boundary = CIOHealthBoundary()
    except Exception:
        log.exception("health boundary unavailable (fail-soft)")
        health_boundary = None
    try:
        operator_profile = OperatorProfile()
    except Exception:
        log.exception("operator profile unavailable (fail-soft)")
        operator_profile = None

    worker = CIORunWorker(
        run_store=run_store,
        action_ledger=CIOActionLedger(),
        notification_outbox=NotificationOutbox(),
        health_boundary=health_boundary,
        operator_profile=operator_profile,
        mode="shadow",
        synthesis_fn=build_investment_product_synthesis_fn(),
    )
    from scripts.lib.cio_research_preflight import decide_after_load

    research_rows: list[dict] = []
    persist_rows: list[dict] = []

    for d in result.get("dispatched", []):
        run_id = d["run_id"]
        wake_id = d["wake_job_id"]
        subject_key = d.get("subject_key")

        # ── #810: load-by-subject, then the research gate. LIVE, no --dry-run.
        # Before the run, so a record the operator already spoke to changes what
        # the gate decides rather than being consulted after the fact.
        research = None
        if subject_key:
            try:
                research = decide_after_load(
                    subject_key,
                    plan={"material": True,
                          "symbols": [str(subject_key).split(":")[-1]]},
                )
                research_rows.append({
                    "subject_key": subject_key,
                    "wake_job_id": wake_id,
                    "decision": research.get("decision"),
                    "reason": research.get("reason"),
                    "decide_called": research.get("decide_called"),
                    "record_loaded": research.get("record_loaded"),
                })
                log.info(
                    "research_gate subject=%s decision=%s reason=%s "
                    "decide_called=%s record_loaded=%s",
                    subject_key, research.get("decision"),
                    research.get("reason"), research.get("decide_called"),
                    research.get("record_loaded"),
                )
            except Exception:
                log.exception("research gate failed for %s", subject_key)
                research_rows.append({"subject_key": subject_key,
                                      "wake_job_id": wake_id,
                                      "decision": "ERROR"})

        dispatcher.mark_in_flight(wake_id)
        exec_result = worker.execute(run_id)

        # Terminal closure
        dispatcher.on_run_completed(
            wake_id,
            run_id,
            exec_result.get("status", "FAILED"),
        )

        # ── Cognition write-back, after the cycle produced its outcome.
        row = apply_cycle_and_persist(subject_key, research, exec_result)
        row["wake_job_id"] = wake_id
        persist_rows.append(row)
        log.info("cognition_persist subject=%s persisted=%s reason=%s changed=%s",
                 row.get("subject_key"), row.get("persisted"),
                 row.get("reason"), ",".join(row.get("changed") or []))

        log.info(
            "run=%s wake=%s status=%s blocked_by=%s",
            run_id,
            wake_id,
            exec_result.get("status"),
            exec_result.get("blocked_by", ""),
        )

    # Durable evidence, beside the consult artifact: a scheduled unattended run
    # must leave proof it consulted and wrote back, not only a log line that
    # rotates. A log line is not a durable surface (AGENTS.md 9.1).
    # Last-cycle-only overwrite erased the 13:35 research hit (LITMUS_WAKE);
    # write_cycle keeps current="now" and retains hits (cap 20).
    try:
        from datetime import datetime as _dt, timezone as _tz
        from scripts.lib.wake_research_persist import write_cycle

        _p = _PROJECT / "data" / "cio" / "wake_research_persist.json"
        write_cycle(_p, {
            "schema": "WakeResearchPersist@v1",
            "authority": "READ_ONLY_ADVISORY",
            "as_of": _dt.now(_tz.utc).replace(microsecond=0).isoformat(),
            "unattended": True,
            "entrypoint": "cron: */5 * * * * cio_wake_dispatch_entrypoint.py",
            "dispatched": result["dispatched_count"],
            "research_called": len(research_rows),
            "persisted": sum(1 for r in persist_rows if r.get("persisted")),
            "cognition_noop": sum(1 for r in persist_rows
                                  if r.get("reason") == "cognition_noop"),
            "no_record": sum(1 for r in persist_rows
                             if r.get("reason") == "no_record"),
            "research": research_rows,
            "persist": persist_rows,
        })
    except Exception:
        log.exception("research/persist artifact write failed (fail-soft)")

    log.info("entrypoint complete: runs=%s research=%s persisted=%s",
             result["dispatched_count"], len(research_rows),
             sum(1 for r in persist_rows if r.get("persisted")))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    main(sys.argv[1:])
