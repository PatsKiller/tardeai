Status: SOURCE_ONLY; not merged upstream or deployed
as_of: 2026-10-11
Measured at: fresh main ec465e9fd; guarded fake tests and committed-source gates only

# Refactor shards 05–08 local source integration

The separate branch `n8nmat/train-refactor-05-08-20261011` merges the final shard heads in order:
05 `5b8a0aa25`, 06 `eeb3fea56`, 07 `ce2e3220e`, 08 `7eaf2e91f`. The existing 01–04 train is separately owned.
Registry, allowlist and contract conflicts are reconciled by stable lane IDs; all existing contracts and
reviewer fields remain unchanged. Main's recommendation normalizer deduplication remains alongside shard 08's
offline plan and cleanup-before-success receipt fix. All four shard tests and main's existing registrations remain.

The 148 assigned rows contain 22 source shadow proposals, 68 blocked rows, 26 sender exclusions,
24 broker exclusions and eight class exclusions. These are source dispositions, not runtime acceptance.
Fresh main has already retired five proposal lanes: `run-sec-form4-momentum-context`, `iris-proposal-curator`,
`price-db-sync`, `sync-dividend-data` and `watch-valuation-backfill`. Their retirement and supersession fields remain;
they are not counted as newly ready active lanes. The other 17 proposals are ACTIVE source rows. Every new contract
remains DRAFT and every new allowlist entry has `live_arg: null`.

Two shard 07 rows, `hermes-scope-governor` and `aegis-evening-packet`, still carried generator ownership.
The integration adopts their exact proposed payloads as hand-maintained rows so committed-snapshot regeneration
retains their shadow blocks. Registry ordering places all hand-maintained rows before generated rows, preserving
row objects. Static tests now pin 76 declared shadow blocks and 232 generated rows, require the three previously
writing previews to have the proven offline shadow shape, and use the new stance/commitment canonical receipts.
The health review and authority gates are unchanged.

The approved selected cron snapshot is dated `2026-10-11T17:05:28.513179+00:00`; the full cron census and timer
runtime are NOT_MEASURED. The nine original missing-lock proposals remain operator packets. Three belong to
already retired lanes and require ownership reconciliation before any installation. No cron line or lock is installed.

The four shard fake suites and main normalizer deduplication test pass under a scratch minimal environment,
empty dotenv, nodeps and pre-import DB/socket/production-file guards inherited by subprocesses. Source registry,
authority, coverage, host-path, dark-contract and docs gates are checked separately. These checks confer no live
acceptance: health fails on 22 DRAFT contracts. Prior mandatory shard profiles failed or stopped on safety refusals;
their broad actions are not retried here. Integration full-profile status is STOPPED_ON_REFUSAL / not rerun.
Runtime acceptance, natural receipts, canary, lock installation, model routing and live firing remain NOT_MEASURED.

The untracked `OPERATOR_REVIEW_LIST.tsv`, `INTEGRATION_REPORT.json`, `SHARED_CHANGES_PACKET.md`,
`EXTERNAL_DOC_APPEND_PACKET.md` and `integration-gates/` form the local handoff. Shared external documentation
is serialized by the parent integrator. Operator review, isolated inherited fixtures, exact required gates and later
runtime acceptance remain prerequisites; this source packet is not ready to push, merge upstream or release.
