# ADR-010 — Consolidated approval packages in front of the guard

Status: PROPOSED (package `cognitive_transformation_20260927`, 2026-09-27) · extends AGENTS.md §9 "Operator approval for push and deploy" and §22; supersedes nothing.
Authority: READ_ONLY_ADVISORY. Broker and per-order approvals (A4/A5) are excluded by rail.

## Context
Twelve-plus approval queues exist. The guard's remote approval is sound (single-use codes, inline buttons, one `getUpdates` poller, forbidden scopes), but `grants.json` holds one grant per tier — a concurrent campaign's approval replaced another's on 2026-09-27 — and only `chat_id` is verified `[CODE; DOC-CLAIM: memory 09-27]`. The operator receives many separate asks because each script asks for itself.

## Decision
1. An `ApprovalPackage@v1` ledger (append-only, hash-chained, in persistent-state) aggregates a wave's operator/security/infra/software/budget items with their rule, reversibility, rollback and review references.
2. One consolidated Telegram message per package, in the guard's layout, with per-item and `all` decisions by button or command; chunked under the transport limit; sent outside the digest router.
3. The existing callback poller settles decisions (no second consumer); `from_id` is verified against an allowlist.
4. Approved items mint guard grants **per package**, with reasons naming package, PR, SHA and campaign, so campaigns no longer overwrite each other and `release_grant_binding` keeps failing closed.
5. 24 h answer window with reminders at +4 h and +12 h; expiry re-requests only the undecided delta; remotely-forbidden scopes are marked NEEDS_LOCAL, never granted remotely.

## Consequences
- The operator sees one message per wave instead of dozens; history and audit are queryable.
- Trade approvals, `/caps` and per-order 2FA stay separate.
- The six-stage workflow (architecture → infra → security → operator → execution → validation) has a durable artifact per stage.

## Rejected alternatives
- A new approval bot (a second poller collides; a second token is a second secret).
- Tier-keyed grants with longer windows (the collision remains).
