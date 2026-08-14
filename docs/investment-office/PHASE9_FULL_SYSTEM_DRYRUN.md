# Phase 9 — Full-System Integration Dry-Run

**"One autonomous cycle, wired end-to-end, with an asserted evidence spine."**

## Goal

Prove that Phases 1–8 are not eight islands but one machine. A single autonomous
advisory cycle flows through every component — wake, snapshot, specialists,
synthesis, capital plan, report v2, office home, operator disposition — and every
material fact traces back to a durable, hash-chained record.

## The single cycle

```
wake ─▶ snapshot ─▶ specialists ─▶ synthesis ─▶ capital plan
    ─▶ report v2 ─▶ office home ─▶ operator disposition
```

Concretely, `run_full_cycle()` executes:

1. **Wake** — enqueue a `SCHEDULE_DUE` wake; the dispatcher is the sole claimant.
2. **Dispatch** — `CIOWakeDispatcher.poll_and_dispatch` creates the CIO run.
3. **Health + snapshot** — pass 1: health check, evidence snapshot (all domains AVAILABLE).
4. **Specialists** — route `holdings` / `watch` / `risk`; run parks in `WAITING_FOR_SPECIALISTS`.
5. **Resume** — pass 2: auto-resume, resolve completed specialist advisories, convene the committee.
6. **Synthesis** — committee synthesis (HOLD, unanimous SUPPORT) → `InvestmentDecision@v1`.
7. **Actions + notifications** — write CIO actions, enqueue shadow notifications, complete the run.
8. **Disposition** — operator disposition recorded against the first action.
9. **Composition** — Capital Plan (P6), Report v2 (P7), Office Home (P8) are all composed from the same run.
10. **Spine assertion** — every linkage and every store hash chain is verified.

## Delivered

| Artifact | Path | Purpose |
| --- | --- | --- |
| Full-cycle orchestrator | `scripts/lib/cio_full_cycle.py` | single entry that wires all phases + asserts the spine |
| Dry tests | `tests/test_cio_full_cycle.py` | 7 tests over the cycle, spine, determinism, fail-soft |
| CLI | `scripts/cio_full_cycle_dryrun.py` | sandbox / `--live` / `--json` one-shot run |
| This document | `docs/investment-office/PHASE9_FULL_SYSTEM_DRYRUN.md` | scope, spine, gaps fixed, checkpoint |

## The evidence spine

Every `run_full_cycle()` result carries a `spine` dict and a verified `integrity`
report. The spine is the complete trace from run-ID to operator disposition:

| Link | Asserted by | Durable record |
| --- | --- | --- |
| wake → run | `run.trigger_ref == wake_job_id` | `CIORunStore` |
| run → snapshot | `run.input_snapshot_id == snapshot_id` | `CIORunStore` |
| run → specialists | `run.specialist_requests` (3 handoffs, no nulls) | `CIORunStore` |
| run → decision | `decision_id` from synthesis | committee synthesis output |
| decision → action | `action.cio_decision_id == decision_id` | `CIOActionLedger` |
| run → action | `action.origin_run_id == run_id` | `CIOActionLedger` |
| action → notification | `notification.cio_action_id ∈ action_ids` | `NotificationOutbox` |
| action → disposition | `outcome.cio_action_id == action_id` | `CIOOutcomeStore` |

Integrity verification runs `verify_integrity()` over the run store, action
ledger, and notification outbox — every event hash chain must be unbroken.

## Integration gaps found and fixed

The dry-run surfaced four real defects and closed them:

1. **Run-worker dropped run linkage on actions.** `CIORunWorker._write_actions`
   did not pass `origin_run_id`, so generated actions were unlinkable from their
   run. Fixed in `scripts/lib/cio_run_worker.py`.

2. **Resume path left runs parked in `SPECIALIST_REVIEW`.** A resumed run that had
   consumed completed specialists never advanced to `CIO_SYNTHESIS`. Fixed by an
   explicit transition in `CIORunWorker.execute`.

3. **Decision identity not persisted to actions.** `recommendations_from_decision`
   already carried `cio_decision_id`, but `_write_actions` and `CIOActionLedger`
   dropped it. Added `cio_decision_id` end-to-end (worker → ledger payload →
   replay).

4. **`specialist_requests` leaked `null` and over-counted.** The
   `evidence_built → SPECIALIST_REVIEW` transition emitted
   `CIO_RUN_SPECIALIST_REQUESTED` without a `handoff_id`, appending `None` and
   inflating the counter. `_apply_event` now guards on `handoff_id` and captures
   `input_snapshot_id` from the synthesis/review transitions.

5. **STATUS fallback actions were not recorded to the run.** When synthesis
   produced no recommendations, `_write_actions` wrote a STATUS action to the
   ledger but never transitioned the run store, so `created_action_ids` missed it.
   The fallback now transitions the run like the normal path.

## Determinism and fail-soft

- All inputs are explicit fixtures (holdings, queue, sector opportunities, thesis,
  attribution, income, source refs); nothing is invented at runtime.
- The cycle is deterministic for fixed inputs: the random run/wake/action IDs
  differ, but the decision position, action count, notification count, and all
  composed dollar figures are identical across runs.
- Fail-soft: empty holdings degrade to a zero-cash plan without raising; a
  no-recommendation synthesis degrades to a STATUS action; the office home still
  renders all six sections.

## CLI

```bash
python3 scripts/cio_full_cycle_dryrun.py                       # sandbox
python3 scripts/cio_full_cycle_dryrun.py --disposition ACCEPTED --rating 4
python3 scripts/cio_full_cycle_dryrun.py --json
python3 scripts/cio_full_cycle_dryrun.py --live                # canonical data/cio stores
```

`--live` targets the canonical `data/cio/*.jsonl` stores exactly as the production
cron would, but with dry-run fixtures. Both modes are advisory-only.

## Authority

`READ_ONLY_ADVISORY`. The cycle composes canonical state, writes advisory actions,
enqueues shadow notifications, and records operator dispositions. It cannot trade,
move stops, or touch 2FA.

## Checkpoint 9

`python3 -m pytest tests/test_cio_full_cycle.py` (7 tests) plus the CLI dry-run
must show `ok: True`, `11/11` integrity checks passing, and a complete spine from
`run_id` to disposition. Related suites (`test_p2_cio_run`,
`test_cio_action_ledger`, `test_cio_checkpoint4_resume`,
`test_cio_checkpoint4_synthesis`, `test_gate_d_evidence_gate`,
`test_gate_b2_closure`) remain green.

## Phase 9 status

Complete (code + dry tests + CLI + docs). The cycle and spine are proven in
sandbox; the `--live` path is available for the operator's Git/release checkpoint.
