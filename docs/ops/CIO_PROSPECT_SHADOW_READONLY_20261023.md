# WP-21: restore the CIO prospect shadow lane without broker reach

Status: DRAFT — source candidate, runtime acceptance not measured
as_of: 2026-10-24T02:29:00Z
Measured at: base `fe826d2ecdb59a19bd7c510c8923c7b743f06eee`; task `T-20261023-84a7f0`

The shadow lane removed from batch 10 can be restored without adding a DD01 exception. Its former entrypoint's static closure reached **1,240 modules**, including broker modules and order-placement functions through two optional projection fallbacks. After extracting the existing injected-query implementations, that closure is **33 modules**, with no forbidden broker, order-placement or direct-sender capability. These measurements are AST source observations, not a production execution.

## Cause and implementation

The shortest forbidden paths were:

```text
cio_prospect_shadow_build -> cio_prospect_builder -> catalyst_record
  -> db_adapter -> holdings_guard -> schwab_position_sync
cio_prospect_shadow_build -> cio_prospect_builder -> watch_intelligence
  -> watch_domains -> positions_sync -> schwab_transport
```

Both builder calls already supplied a read-only query callable. Importing the broad modules nevertheless exposed their optional host DB fallback and unrelated Watch operations to the static lane audit.

- `catalyst_record_readonly.py` now owns the existing injected bulk query and its normalization/deduplication helpers. `catalyst_record.py` re-exports those exact function objects and keeps its host-owned collector fallback.
- `watch_directives_readonly.py` owns the existing active-ticker query, sorting and strict/fail-soft behavior. `watch_intelligence.py` delegates to it and retains the optional host DB fallback for current API callers.
- The builder imports the narrow implementations. The SQL, GUID/event provenance, result shape, factual-verification distinctions and query failure semantics remain shared with the existing public projection facades.

This is an extraction within the registered projections. It adds no store, writer, provider, source selection or trading behavior. The authority validator reports no blocking findings. The DD01 baseline and its frozen capability test are unchanged.

## Shadow onboarding record

| Requirement | Candidate binding |
|---|---|
| Owner / purpose | CIO; assemble one read-only prospect per confirmed `security_guid` from existing inputs |
| Native trigger | Existing n8n Schedule Trigger dispatcher; cadence `*/30 9-16 * * 1-5`, America/New_York |
| Stage / mode | `scheduler.stage=shadow`, `dispatch.mode=dry_run`; no host trigger is changed |
| Executor | `$PY scripts/cio_prospect_shadow_build.py --with-db --dry-run` |
| DB / credentials | Existing host connection is enforced READ ONLY; n8n receives no credential; tests inject rows and use a private fixture cluster |
| Lock / timeout | Existing reviewed `/tmp/tradeai_cio_prospect_shadow.lock` binding, 600-second timeout; executor uses its disjoint dry-run lock |
| Business effects | Dry run writes no prospect, store, shadow artifact or business receipt; `live_arg` remains null |
| Health contract | Original #1953 contract restored unchanged, including the actual 2026-10-22 operator review; no new review identity or approval is manufactured |
| Contract catalogue | 158 entries after restoration; the restored contract contains no UNKNOWN field |
| Recovery | Existing `transient-2` shadow policy retained; no new remediation authority, sender or live mode |
| Acceptance | Source checks only; deployment, scheduled host execution, consumers and live advancement remain separate coordinator/operator evidence |

The public query behavior remains tested through both facades. A missing directive query remains distinguishable from an empty successful query under `strict=True`. Catalyst confidence is not promoted into independently verified publication evidence.

## Verification

- Final combined regression: **392 passed, one existing skip** (14 relevant source, query, fixture-Postgres, registry, contract, capability and CI-gate files).
- Focused source/query parity group: 30 passed.
- Registry, native-shadow inventory and contract-baseline group: 245 passed, one existing skip.
- Fixture Postgres foundation cases: two passed on a throwaway Unix-socket-only cluster under the work package's unique home-directory scratch path. The initial sandbox denial is retained in the evidence.
- Static forbidden-capability audit: none for the restored lane; no baseline addition.
- Registry and health-contract validators: clean. Four unrelated historical contract review deadlines remain overdue; they were not extended by this change.
- Data-source authority validator: zero blocking findings; no ceiling rewritten.
- Reconciliation uses the committed `scheduler_snapshot_20261009.json`. Its preview found zero semantic changes to existing rows; `--write` placed the restored row at the generator's fixed point. Snapshot cron/unit counts are historical source inputs, not a fresh host census.

Durable local evidence: `/home/johnclaw/.cache/rtc/codex-wp21-20261023/` (`transitive-before.json`, `transitive-after.json`, `focused.log`, `regression.log`, `registry-regression.log`, `fixture-postgres-rerun.log`, `data-authority.json`, `reconcile-preview.json`, `reconcile-applied.log`, `final-regression.log`).

The branch is prepared for the operator's publication and the coordinator's exact-head CI review. No workflow was activated, host schedule altered, live broker called or production migration run by this worker.
