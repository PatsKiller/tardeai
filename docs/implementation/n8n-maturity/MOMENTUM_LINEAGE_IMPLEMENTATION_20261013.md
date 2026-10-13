# Momentum lineage and lifecycle implementation

Status: IN PROGRESS — local implementation; runtime acceptance pending
Owner: Codex; authoritative producer and lane owners retain their existing roles
as_of: 2026-10-13T14:06:29Z
Measured at: base f0ebb82acd44fa0db790d29390d711daa0831a96; CURRENT f0ebb82ac-main-exact-phase2-20261012-224843
Branch: wt/momentum-lineage-20261013
Worktree: /tmp/tradeai-momentum-lineage-20261013
Session: fe842e09-c425-4af2-bd3e-734dccfdb560

The operator requested execution of the six-step plan after this record is written. The change preserves original observations from producer through cache and API to both candidate screens; distinguishes catalyst relevance, factual verification and model confidence; applies canonical run accounting to header, panel and history; reconciles security/session/event observations without changing source decisions; and verifies the lifecycle through alert delivery with bounded recovery.

## Existing components and measured gaps

[CODE] Extend these existing contracts and components rather than create a second pipeline:

| Component | Existing implementation | Gap to close |
| --- | --- | --- |
| Candidate projection | `scripts/lib/scanner_candidate_projection.py`, `SharedMomentumCandidates@v1` | Symbol-only grouping; missing observation time can inherit a run timestamp; source record/event identity absent. |
| Evidence projection | `scripts/lib/momentum_setup_evidence.py`, `MomentumSetupEvidence@v1` | Verification combines a reported boolean with same-day publication freshness; numerical facts share one row timestamp. |
| Run accounting | `scripts/lib/setup_run_contract.py`, `SetupRunSummary@v1` | History still aggregates by day and uses a separate counting path. |
| Screens | `SharedMomentumCandidates.tsx`, TradingHub and ActiveTraderHub | Shared component exists; richer original observation and catalyst distinctions need rendering. |
| Lifecycle | `scripts/lib/n8n_momentum_lifecycle.py` | Receipt and output gates exist; actual consumer and delivery proof must be correlated rather than inferred from declarations or successful exits. |
| Recovery | Existing deterministic dispatcher and lifecycle planner | Preserve original-slot budgets, admission, owner review, locks and storage/dependency gates; recovery remains disarmed until operational acceptance. |

[VERIFIED] Repository review found 65 PRs merged in the preceding 72-hour window (2026-10-10T13:48:05Z through 2026-10-13T13:48:05Z). GitHub PR census returned `65`. CURRENT's `GIT_SHA` and `BUILD_SHA` both returned `f0ebb82acd44fa0db790d29390d711daa0831a96`.

[DOC-CLAIM] The peer receipt `~/n8n-maturity-verification/reconciliation-20261012/OBSERVER_FIRST_NATURAL_FIRE_FAILURE_20261013.json` records an observer fire at 2026-10-13T13:55:00.044Z, `first_fire_acceptance=FAILED`, with error response unmeasured. It is an operational investigation item, not evidence that a source edit fixes the deployed observer.

## Implementation sequence

1. Preserve source observation envelopes: canonical security identity when supplied/resolved, immutable observation/event/run IDs, original zoned timestamps, source reference and producer identity. Processing timestamps stay distinct. Missing source evidence stays unknown.
2. Carry publication evidence and separate relevance, factual verification, model confidence and freshness. A stale or prior-session publication does not lose its historical verification; confidence never establishes verification.
3. Extend canonical accounting for per-run history and make header/panel/history reuse its taxonomy and run identity. Label daily aggregation and different candidate populations explicitly.
4. Reconcile observations within security/session/event scope. Preserve decisions and chronology, show unmatched/ambiguous evidence, and render identical projection identity on both screens.
5. Extend existing lifecycle gates for trigger, host receipt, business output, consumer readback and delivery evidence. Explicitly distinguish intentionally absent/suppressed notifications from failed or unmeasured delivery.
6. Exercise negative and recovery paths with isolated fixtures; run native regression, frontend and quality checks; document exact results and operational acceptance packet.

## Scope and authority

The governed session claims the implementation record, public projection/evidence/run/lifecycle helpers, existing scanner/cache/API producers, shared frontend component and existing relevant test files. Source is based on exact main in a registered isolated worktree. Production stores are not claimed or written. Existing provider/source owners, financial decisions, execution engines and authoritative store writers retain their authority.

Broker execution files, credentials, trading policy, live flags, scheduler activation, workflow publication, legacy retirement and release promotion are outside this local source tranche. Protected producer work requires its separate execution-engineering grant. New authoritative writers or sources require their registry approval; this tranche extends existing consumers and producers. Remote push is separately authorized under AI_WORK_POLICY.md. Runtime rollout requires exact-SHA release authority and applicable cron/service grants.

## Validation and acceptance

Tests run with `TRADE_AI_CI=1`, contained state roots and synthetic inputs. No test may reach production DB, relay, gateway, credentials, model/provider calls or operator delivery.

Required cases:

- Original observation and publication times and source references survive cache refresh, API projection and both screens; unavailable timestamps are never replaced with composition time.
- Prior-day verified publications retain verification while freshness/relevance remain separate; high confidence cannot turn unsupported facts into verified evidence.
- Same ticker with different security identity, session or event is not falsely reconciled. Source decisions remain unchanged and historical changes remain visible.
- Per-run summary partitions reconcile; repeated run attempts and daily aggregation retain explicit identity/scope. Missing counts stay unavailable.
- Missing, stale, wrong-run, wrong-SHA or duplicate-effect trigger/receipt/output/readback/delivery evidence fails the applicable lifecycle gate.
- Recovery refuses unknown actions, missing owner review, exhausted retry slots, unhealthy storage/dependencies or missing grants. A successful retry still needs downstream proof.

Source acceptance comprises targeted and relevant regression tests, frontend checks, changed-file quality, dry-run output and durable fixture artifacts. Operational acceptance remains separate: authorized exact-source deployment, actual host collection, correlated consumer/delivery observations, required natural fires and lane-specific rollout gates. No exit code or fixture receipt is presented as production proof.

## Progress and results

- 2026-10-13T14:06:29Z: registered worktree and governed local session accepted; shared lease acquired with no overlapping claims. This record is the first source write, before implementation.
- Implementation, validation and runtime outcomes will be appended here with their original timestamps, source references and run identities.

## Rollback

Before deployment, retain the reviewed source commit and existing production release identity. Operational rollback follows the existing exact-source release procedure and stops only approved candidate scheduling before restoring its affected legacy trigger. Preserve all original observations, notification receipts and retry history. Never restore an entire crontab or delete evidence.
