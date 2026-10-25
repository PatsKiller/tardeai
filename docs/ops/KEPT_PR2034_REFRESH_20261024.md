# Kept PR2034: isolated refresh and compatibility evidence

Design-Task: DSN-20261024-kept-pr2034-refresh-P1-T1

Worker `codex-kept-pr2034-20261024`; claim `20261025T000050Z-codex-7b90d894`.

## Source boundary

The fresh worktree is `/home/johnclaw/wt-codex-kept-pr2034-20261024`, branch `work/DSN-20261024-kept-pr2034-refresh-P1-T1`, created from remote PR2034 head `a47bb5a17e87401573d24229c4eef17d407aa401`. Accepted main was fetched at `d635873e1063efb8a9ff8e8ce542654ed2ef7654`.

The operator's protected old-tree inventory reports 26 commits beyond that remote branch in `wt-prospect-writer`: 25 already belong to accepted main, and the only local-only commit is the merge `99f3dccae46358c3f92a74a3a9103bc78d6512a2`. This refresh does not reuse, discard, reset, stash or publish any old-tree commit. `wt-wpboard` is untouched as well. The binding receipt preserves the supplied inventory's hash.

`TRADEAI_CIO_PROSPECT_PG_DUAL_WRITE` remains default off. This worker does not change environment files or runtime flags and makes no production database writes or provider calls. Fixture-only fake-backend tests are separate from live PostgreSQL proof; an unavailable driver must remain an explicit skip rather than a claimed real-database success.

## Initial diagnosis

PR2034's reported evidence-only failure is a clock mismatch. The older fixture stamped its live overlapping claim with fixed `T0`, while the CLI used wall time; after two hours the claim became stale, so `take` was permitted and the negative assertion failed. Accepted main already contains `77dc6b476e825cfe495d25f984252bbf8d1ef433`, which creates that claim with the same real clock the CLI reads. It retains the overlap-refusal, free-task evidence-only closure, required evidence, taken-task refusal and plain-done refusal assertions. The actual merged head still needs to be tested before claiming the refresh fixed CI.

The prospect writer must retain its original flag-off/dry-run boundaries and be re-tested with accepted C1's fact-only record path. A company-fact update must not manufacture a CIO judgment or promote a legacy/facts-only record. Any builder change requires a legitimate handoff from its current source owner.

## Held scope and remaining acceptance

The normal source claim check found `config/cio_surface_classification.json` held by W11 claim `20261024T234040Z-codex-3dc46c4e`. The existing PR adds `schema:CioProspectWriterRun@v1`, which accepted main does not contain. No held classification edit or merge resolution is attempted; normal owner handoff is required for that affected scope.

The current independent work is source diagnosis and preservation evidence only. It is not a merged-head test receipt, refreshed PR, production writer activation or runtime acceptance. After the held scope is resolved: merge accepted main in this fresh tree, retain current classifications and the writer schema, run the affected hidden-driver/C1/native/ratchet checks, commit locally and append one executable push-only `PUSH_NEEDED` for the existing PR branch. Do not create another PR or enable dual write.
