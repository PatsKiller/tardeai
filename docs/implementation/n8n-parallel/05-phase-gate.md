# Phase gate — stop before the event gateway

As of 2026-10-07, phases 0, 1, and 2 of this work order are recorded. Phases 3 through 9 are not implemented.

## What is true

- Served Trade AI pin, DOF checkout, and the n8n lab were measured and written down.
- All 173 lanes have one declared registry owner. Host conflicts are explicit in `ledgers/lane-ledger.json` rather than scored as a pass.
- Five pilot contracts exist and are DESIGN_ONLY.
- The installed n8n edition was compared with the feature list. Secret-bearing integrations are BLOCKED_POLICY.
- The lab already has its own database, a localhost port, a prior restore drill, and no queue mode.

## What is not true

- No signed event gateway exists.
- No source-side idempotency ledger for an n8n effect exists.
- No shadow workflow for the five pilots exists.
- No consumer receipt was produced for any pilot.
- No governed model call was made, and the ADR model-id drift was not edited.
- No DOF workflow was added. DOF purchase, title, and bid authority stay with people and the existing code.
- No lane changed owner. Cron and systemd definitions were not deleted or paused.
- `docs/INDEX.md` was not edited. That update belongs to a later closeout, after there is something serving to index.
- No weekly report was started. There is no live n8n lane to report.

## Phase 3 entry conditions

The next build, when it is done, is a Trade AI gateway that n8n does not own:

1. Authenticate the caller with a real check. Localhost and a shared network are not the check.
2. Accept only an event reference. Resolve bounded fields through allowlisted reads.
3. Refuse broker, grant, 2FA, promote, bid, payment, title, and canonical financial writes.
4. Record EXPECTED through CANCELLED as source-side facts, with the served SHA.
5. Prove malformed signature, replay, unknown lane, stale SHA, and duplicate delivery in tests.
6. Leave DOF on its own schema and its own role. Do not add those routes until the role split is measured.

Until those exist, activating a pilot would be a second ungoverned path. This program stops at the contracts.

`ledgers/event-reference.schema.json` is a DESIGN_ONLY shape for that future reference. It is not served and not authenticated.

## Rollback

This phase changed documentation in the worktree only. Rollback is to drop the worktree branch. No service, crontab, timer, container, or database needs to be restored.
