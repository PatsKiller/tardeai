# WP-37: hot-list registry matches the operator-captured command

Design-Task: T-20261023-838c62

The proposed change corrects only `scalp-hot-list.scheduler.command_text` to the
existing operator-approved 170-second outer budget and 180-second shell timeout.
It also retains the exact captured approval comment. All other registry fields,
including the schedule and dispatch authority, are byte/structure-preserved.
No host scheduler command was written or executed.

## Verified captured input

The coordinator supplied the read-only capture under grant `7cf078bf`:

- File: `/home/johnclaw/.cache/rtc/codex-wp37-20261024/census-20261024-coordinator-capture/crontab.txt`.
- SHA-256: `b2097df25a62e6824b6e7046d55a3f279b9b058e76b1bcd09c2da89b5a748626`.
- 1,077 lines; README capture time **2026-10-24T04:35:03Z**.
- Parser census: **348 active entries, 348 distinct active lines**.
- Unique hot-list entry: line **643**, schedule `*/2 6-9 * * 1-5`.

The hash was checked before use and after verification. The original sandbox
`crontab -l` refusal remains recorded separately; no retry or alternate spool
read occurred. This report uses the explicitly supplied file only. The
coordinator retains responsibility for the independent before/after host
fingerprint check; an unchanged captured file does not prove an unchanged host.

[Captured target line](packets/hot-list-capture-20261024/captured-hot-list.txt),
[verification](packets/hot-list-capture-20261024/VERIFICATION.json) and
[reconciliation observation](packets/hot-list-capture-20261024/RECONCILE_OBSERVATION.json)
bind the source and proposal to that hash. The prior budget approval is recorded
in `docs/designs/DSN-20261022-operator-approvals.md` and the captured comment
`(budget 170s, operator 2026-10-23)`. The October24 grant permits read-only capture;
it is not a new scheduler-write approval.

## Exact proposal and preserved boundaries

| Field | Before | Proposed |
|---|---|---|
| Outer deadline in `scheduler.command_text` | 100 seconds | 170 seconds |
| Shell `timeout` in that same string | 110 seconds | 180 seconds |
| Approval suffix | Absent | Exact captured operator comment |

These are parts of **one JSON field**. The original `flock` lock, market-day
gate, command, output redirection, schedule, owner, state, output signal and
shadow/W5/dry-run settings remain unchanged. The registry expression and
`dispatch.cron` stay `*/2 6-9 * * 1-5`; existing prose about the script's broader
06:00–12:00 window does not authorize extending the observed host schedule.

The cron inventory received an append-only observation/approval row tagged
`WP37_CAPTURE_20261024`. Its backup and before/after hashes are in the verification
receipt. This single observation does not remeasure workbook-wide progress.

## Reconciliation and remaining drift

The pure reconciler was run with the supplied cron capture and the committed
October9 unit snapshot, with live cron/unit/subprocess calls blocked. The units
are explicitly **historical**, not a current systemd census. It reports zero
structural problems; the hot-list line maps exactly once to `scalp-hot-list`,
and the complete proposed hot-list row survives reconciliation unchanged.

The reconciler preserves hand-maintained command text, so running it alone would
not repair this stale field. Its broader output was observed without committing
the regenerated registry. Separate item3 analysis explains the other changes
caused by mixing current cron text with historical rationalization/unit inputs;
structural success is not acceptance of those metadata changes.

The shadow dispatcher still declares deadline100/timeout110, and its reviewed
contract reflects that budget. This proposal records the existing host command;
it does not change the shadow execution budget. The onboarding gate requires
dispatcher timeout below its 120-second cadence, and the allowlist pins the
inline deadline. A separate reviewed parity/overlap decision is required before
changing those settings; the existing assertions remain intact.

## Verification

**69 existing regression tests pass with psycopg2 hidden**:

```bash
PYTHONPATH="$HOME/.cache/rtc/nopg" python -m pytest -q -p no:cacheprovider \
  tests/test_n8n_maturity_registry_reconcile_20261009.py \
  tests/test_scalp_premarket_onboard_20261014.py \
  tests/test_n8n_run_allowlist_20261008.py \
  tests/test_momentum_scalp_lane_refresh_20260928.py
```

Verification also checks the exact captured command, a unique active match,
unchanged remaining registry fields, and the input hash after use. No new test
file or runtime implementation is needed for this one-field metadata correction.
The required host-path and test-coverage ratchets, documentation index, claim,
secret and whitespace checks run before `PUSH_NEEDED`.

The operator/coordinator publishes and reviews the source PR. This packet does
not claim deployed or natural-run acceptance, change n8n activation, or alter the
host crontab.
