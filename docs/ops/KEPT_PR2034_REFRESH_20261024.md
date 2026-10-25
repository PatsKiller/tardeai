# Kept PR2034: isolated refresh and compatibility evidence

Design-Task: DSN-20261024-kept-pr2034-refresh-P1-T1

Worker `codex-kept-pr2034-20261024`; claim `20261025T000050Z-codex-7b90d894`.

## Source boundary

The fresh worktree is `/home/johnclaw/wt-codex-kept-pr2034-20261024`, branch `work/DSN-20261024-kept-pr2034-refresh-P1-T1`, created from remote PR2034 head `a47bb5a17e87401573d24229c4eef17d407aa401`. Accepted main `d635873e1` was merged first. While validation ran, main advanced to accepted batch 24, `23e87f15b1e973f4520cedb28c5998036374c55e`; that pinned review basis is merged at `57bfb3a02c9d5fe335c4cad430d2e75a38e228fe`. No old-tree commit was cherry-picked or reused.

The operator's protected old-tree inventory reports 26 commits beyond that remote branch in `wt-prospect-writer`: 25 already belong to accepted main, and the only local-only commit is the merge `99f3dccae46358c3f92a74a3a9103bc78d6512a2`. This refresh does not reuse, discard, reset, stash or publish the private local merge; the 25 already-accepted commits arrive through accepted main. `wt-wpboard` is untouched as well. The immutable preflight [binding receipt](packets/kept-pr2034-refresh-20261024/BASE_BINDING.json) preserves the supplied inventory's hash; its pending status describes that earlier snapshot.

`TRADEAI_CIO_PROSPECT_PG_DUAL_WRITE` remains default off. This worker does not change environment files or runtime flags and makes no production database writes or provider calls. Fixture-only fake-backend tests are separate from live PostgreSQL proof; an unavailable driver must remain an explicit skip rather than a claimed real-database success.

## Clock defect and C1 compatibility

PR2034's reported evidence-only failure is a clock mismatch. The older fixture stamped its live overlapping claim with fixed `T0`, while the CLI used wall time; after two hours the claim became stale, so `take` was permitted and the negative assertion failed. Accepted main already contains `77dc6b476e825cfe495d25f984252bbf8d1ef433`, which creates that claim with the same real clock the CLI reads. The merged-head test file is byte-identical to accepted main (SHA-256 `3f930dbb5f6d7244dba7098966401bb2ec8caebd59b03ebbb35ed0e2069013ef`). Its overlap-refusal, free-task evidence-only closure, required evidence, taken-task refusal and plain-done refusal assertions pass unchanged; no new weakening or skip was added.

Two new integration cases run the actual C1 population → existing builder → prospect writer chain. Both default-off apply and dry-run execution preserve the canonical `FACTS_ONLY` record byte-for-byte, including its GUID, research and absent stage/stance/conviction fields. A PostgreSQL write backend must never be constructed. The existing C1 tests also retain legacy no-promotion, judgment/sibling-research preservation, identity guards, preflight refusal and stale-writer rejection. The builder, InstrumentRecord store and C1 production modules are unchanged from accepted main.

Production writer callbacks may read their declared build inputs through a read-only database connection even while dual-write is off. The tests inject stored inputs and fake backends; their no-live-connection proof does not relabel production's read path as absent.

## Handoff and validation

The initial normal claim check found `config/cio_surface_classification.json` held by W11. After that owner's normal handoff, the check returned free and this task claimed the file before merging. The automatic merge preserves every accepted-main classification and every original PR classification unchanged, including `schema:CioProspectWriterRun@v1`. W11's released classifier blob matches accepted main; its other source/proposed rows are untouched. No manual classification rewrite or owner bypass was used.

The affected hidden-driver suite covers the original clock/refusal assertions, writer, foundation/builder, shadow read-only, directives/proposals, catalyst facts, company facts and C1 population. The final [validation receipt](packets/kept-pr2034-refresh-20261024/VALIDATION.json) records the latest-main results, commands, log hashes, classification preservation and the remaining publication boundary. The first d635-based pass was 145 passes / three PostgreSQL skips, 34 registry/CIO passes, a passing native build and zero source-authority findings / 27 proposal warnings; those historical logs remain separate from the recheck after batch 24's Ask frontend, routing, tracking and classification changes.

The pinned `23e87f15b` recheck also passes: 145 affected tests / three explicit PostgreSQL skips, 34 registry/strict CIO tests, native build, all four no-new ratchets and docs index. Source authority reports zero findings / 27 proposal warnings. All 158 latest-main classifications, 150 original-PR classifications and 157 released W11 classifications remain unchanged in a 159-row union. The old private merge is not an ancestor. No production code changed during this final recheck; the additional commit binds its documentation/receipts to the accepted review basis.

This is local source/fixture acceptance. The worker performs no push, new PR creation, merge on GitHub, release, live model call, PostgreSQL write or scheduler change. Publication must fast-forward the same existing remote PR branch `feat/cio-prospect-writer-20261023`; the exact push-only command is handed to the coordinator/operator. `TRADEAI_CIO_PROSPECT_PG_DUAL_WRITE` remains off. A later activation and real database proof are separate operator work.
