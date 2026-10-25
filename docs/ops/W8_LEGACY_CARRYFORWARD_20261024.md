# Worker A carry-forward: six shadow lanes

Status: IN_PROGRESS — six config rows integrated; non-config source-helper integration pending
as_of: 2026-10-24
Design-Task: DSN-20261024-w8-legacy-carryforward-P1-T1

The approved `legacy-pr-carryforward.md` assigns the Worker A source at `8ba33bd6c4612770a71a814874632eaba3b19f6e` to a fresh task/branch/worktree on accepted main `d635873e1063efb8a9ff8e8ce542654ed2ef7654`. The original W8 source `369de0121` and its one publication request remain frozen and separate.

W8 owns the six registry/allowlist/health integrations: holdings drift, options desk staleness, held exit coverage, options desk quote refresh (inert), Ask CIO research and JSONL archive rotation. Five runnable source entries must stay SHADOW/dry_run with `live_arg=null`. Quote refresh retains no operative allowlist/dispatch and remains NEVER_SCHEDULED. Its shadow candidate is a proposal, not activation.

The JSONL archive health review now cites the explicit operator 2026-10-24 carry-forward instruction; it does not invent an earlier review or activate removal. Existing archive-removal disablement and accepted disk hygiene configuration are preserved. The non-config source helper must merge the JSONL retention fields into current accepted files and preserve active Ask-quality edits.

The [source packet](packets/w8-legacy-carryforward-20261024/SOURCE_PLAN.json) pins the exact old bundle and new baseline. The fresh main has 678 registry rows; all survive, including `cio-prospect-shadow` and `cio-company-facts-populate`. Six requested rows are added without importing stale whole-file state. The old source contains an extra Schwab health contract; that is outside this six-lane package and belongs to W12's separate reviewed read-lane work. The other 31 F09 host-cron lanes stay unchanged.

Normal claim handoffs precede every blocked-path edit. W8 normally continued its own original `73e39f48` claim to `65d8aa22`, retaining the frozen initial source/evidence and transferring only the three config paths to the new `899f2f66` carry-forward claim. No force or override was used. At registration, the old Worker A claim `b22fbf19`, C1 retention claim `6173fb78`, disk continuation `e0e36ea8`, Ask-quality claim `95156ec6` and the initial W8 config claim require normal scoped coordination. No override or foreign-session change is performed. The ordinary new task take recorded an old stale design-tree overlap in its audit metadata; direct readback confirmed the foreign `3fd3d5c3` claim remained active and unchanged.

No runnable source is published, migrated or activated by this worker. Final proof must include full affected tests with psycopg2 hidden, ratchets, native registry/health checks, reconciliation CHECK only, CIO completeness, build, and preservation of every preexisting row and pending proposal. Source-helper and configuration changes will form one reviewed carry-forward package with one PUSH_NEEDED when complete.

## Configuration checkpoint

The six-row merge has 684 registry rows, 139 allowlist entries and 164 health contracts. All 678/134/158 previous objects and all other top-level fields are exactly preserved (see `config-preservation.json`). Five runnable source entries are dry-run-only shadow rows; quote refresh remains inert. The archive review now has the explicit carry-forward reference. Staged quote-refresh metadata correctly says policy19.0.0 is ACTIVE, while admission remains a separate unmet condition.

The first focused hidden-Postgres run passed14cases and failed1: the accepted main disk configuration does not yet contain `jsonl_retention`; that field is part of the pending non-config/retention source port. This is an incomplete combined package, not a green or publishable result. No PUSH_NEEDED is issued for this checkpoint.
