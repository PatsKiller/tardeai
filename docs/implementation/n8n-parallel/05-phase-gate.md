# Phase gate — muted gateway, not a cutover

As of 2026-10-07, phases 0, 1, and 2 are the measured record. The coordination gateway and the five pilot contracts now exist as a muted library. They are not served. Phases 6 through 9 are not implemented. Detail is in `06-findings-and-gateway.md`.

## What is true

- Served Trade AI pin, DOF checkout, and the n8n lab were measured and written down.
- All 173 lanes have one declared registry owner. Host conflicts are explicit in `ledgers/lane-ledger.json` rather than scored as a pass.
- Five pilot contracts exist and are DESIGN_ONLY.
- The installed n8n edition was compared with the feature list. Secret-bearing integrations are BLOCKED_POLICY.
- The lab already has its own database, a localhost port, a prior restore drill, and no queue mode.

## What is not true

- The gateway process is not installed, and its idempotency store is not a durable production ledger.
- No shadow workflow for the five pilots exists. No consumer receipt was produced for any pilot.
- No governed model call was made. The ADR text was corrected; the live model constant was not.
- No DOF workflow was added. DOF purchase, title, and bid authority stay with people and the existing code. There is no separate `dof_*` database role, so no DOF SQL route was added.
- No lane changed owner. Cron and systemd definitions were not deleted or paused. The two stale NEVER_SCHEDULED rows were not flipped to ACTIVE.
- `docs/INDEX.md` was not edited. That update belongs to a later closeout, after there is something serving to index.
- No weekly report was started. There is no live n8n lane to report.

## Phase 3 entry conditions

The next build, when it is done, is a Trade AI gateway that n8n does not own:

1. Authenticate the caller with a real check. Localhost and a shared network are not the check.
2. Accept only an event reference. Resolve bounded fields through allowlisted reads.
3. Refuse broker, grant, 2FA, promote, bid, payment, title, and canonical financial writes.
4. Record EXPECTED through CANCELLED as source-side facts, with the served SHA.
5. Prove malformed signature, replay, unknown lane, stale SHA, and duplicate delivery in tests.
6. Do not add a DOF SQL route on the shared `trade_ai` role. The role split was measured on 2026-10-07 and does not exist.

Items 1, 3, and 5 are covered by the library and its tests. Item 2 accepts the event reference and does not resolve production fields. Item 4 keeps the state machine in the caller's dict; that dict is not a durable source-side ledger. Activating a pilot on the host would still be a second path: the store is not durable, no consumer receipt exists, and the process is not installed.

`ledgers/event-reference.schema.json` is the shape the library checks. It is not served. Localhost is not authentication.

## Rollback

Rollback is to drop branch `wt/n8n-parallel-20261007` or revert the gateway commit. No service, crontab, timer, container, or database needs to be restored. The DOF policy branch is separate.
