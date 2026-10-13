# Momentum lineage and lifecycle implementation

Status: DRAFT — locally implemented and tested; operational acceptance pending
Owner: Codex; authoritative producer and lane owners retain their existing roles
as_of: 2026-10-13T15:20:37.103705+00:00
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
- First documentation commit: `a91c62d69`; tested source commit: `a5c427791997038d07a53038a40ccac6afc1ce57`. The tested source commit changes 25 implementation/test files. Subsequent documentation commits do not establish new runtime evidence.
- [TEST] `TRADE_AI_CI=1` targeted regression: **464 passed**, zero failed/skipped, 19.18 seconds. JUnit began at `2026-10-13T11:06:36.185456-04:00`. The hermetic guard reported **three live-DSN connection attempts refused before libpq**; no live database connection is asserted. Tests exercise original-clock preservation, ambiguous identity/session/event matches, run attempts and partitions, independent catalyst evidence, subject binding, missing market observations, health dedupe and lifecycle refusal/recovery cases.
- [TEST] Both actual local React screens, `/v3/active-trader?tab=Alerts` and `/v3/trading?tab=Trade%20AI`, passed headless-browser assertions at `2026-10-13T15:03:56.976Z` and `2026-10-13T15:03:57.972Z`. Every API response was an explicit synthetic fixture and non-loopback requests were blocked. Both read the same snapshot hash, original observation/run metadata and supporting publication. These are **LOCAL_FIXTURE_DOM_READBACK** receipts, never production consumer receipts.
- [TEST] `npm run build` passed its frontend unit/design/contrast checks, TypeScript and Vite build. Existing boot-script and chunk-size warnings remain. Ruff passed on all 23 changed Python files; formatting was checked against the base-file ratchet rather than reformatting legacy files wholesale. Diff whitespace and line-ending checks passed.
- [VERIFIED] Public registry gates passed: no new unlisted tests (2,015 total test files; 1,087 in CI), data-source authority zero findings (58 domains, 22 providers, all approved), and secret scan passed (10,634 files). No registry, schedule, credential or live flag was changed.
- [TEST] The real lifecycle CLI dry run, using copied public configuration in `/tmp/momentum-lifecycle-validation-code` and an explicitly empty sanitized snapshot, returned `collection_source=EXPLICIT_FIXTURE`, `acceptance=NOT_MEASURED`, `recovery.intents=[]`, `held.reason=retry_disarmed`, exit 0. The first invocation used the source worktree as `--code-root` and failed because it has no release `SOURCE_COMMIT` stamp; the corrected invocation used a separately labeled fixture root. No stamp was added to the source worktree and no monitor state was written. Quoted output and hashes are in [the validation record](MOMENTUM_LINEAGE_VALIDATION_20261013.json).
- [VERIFIED] The native PR selector was inspected without executing its selected suites: 346 files, 180 gates, estimated 539.9 seconds under its 540-second budget, 489 deferred files. Its selected broker/Active Trader execution tests require an active per-task `execution-engineering` grant under AGENTS.md §0 rule 2 and §2B/§22. Required native/release-equivalent validation is **pending**, not green.

## Operational acceptance still required

The local source tranche is implemented and its targeted behavior is tested. It is not pushed, independently reviewed, merged, deployed, or accepted as working on the host. The [next-actions record](MOMENTUM_LINEAGE_NEXT_ACTIONS_20261013.json) provides the bounded validation request and remaining owner/rollout obligations.

- Obtain a test-only execution-engineering grant for the exact reviewed source before inspecting/executing the protected native tests; preserve isolation and refuse any real broker/provider/DB/credential reach. Complete the required native and release-equivalent gates before remote synchronization.
- Bind the existing lifecycle product projection to real screen-consumer receipts and correlated communications-gateway route/delivery receipts. The verifier now rejects missing, stale or mismatched evidence; fixture records and declarative consumer names cannot close that gap. No new authoritative receipt producer or store has been approved or installed by this change.
- Confirm the failed deployed observer's actual error and repair its existing lane under applicable grants. Upstream Finviz/orchestrator/proposal/promoter outputs need fresh, original-run evidence, not a session-cache timestamp rewrite. Repeated-alert fixes do not restore an absent producer.
- An operator must refresh authenticated YouTube cookies. Synthetic cookie-format tests prove parsing only; cookie presence never proves an authenticated live session. No live cookie was read, exported or replaced.
- After independent review, exact-head local/remote CI and explicit remote intent, request exact-SHA release and any applicable cron/service/producer grants. Validate authorized installed runs with durable host output, both consumer readbacks and actual delivery or a receipted route decision; observe every natural-fire gate required by the existing onboarding standard. Recovery stays disarmed until its health contract and bounded retry admission are accepted.

Existing source observations without security identity, observation/publication time or factual-verification method remain explicitly unknown. This change cannot reconstruct original facts that their producer never recorded. Broker execution and financial decision policies remain outside this tranche.

## Operator supplied failure cases

The operator added dated Telegram examples during implementation (2026-10-13). Treat them as incident evidence for their original times, not current runtime measurements. Preserve the reported observation time and public message subject when reproducing them in isolated fixtures; do not commit approval codes, credentials or account information.

- YouTube cookie health: October 11 reported no authentication cookies. Verify synthetic HttpOnly parsing and truthful authentication-health states. Never open/export/replace the live cookie file. Actual authenticated refresh remains an operator task.
- October 12 Finviz/orchestrator/proposal/promoter freshness alerts repeated every five minutes with `retry_disarmed`. Correlate expected scheduler slots and real output; emit stable incidents and retain explicit recovery authority. Do not run the pasted apply commands or arm protected recovery from the alert text.
- Freshness SLOs inferred a dead pipeline from zero GO/proposal counts. Separate business outcome counts from producer liveness and declare market/session applicability.
- The pre-open brief rendered missing SPY/VIX observations as `+0.00%` and `0.0`. Missing market observations must render unavailable with original provenance.
- A WFF social alert received TROW links/footer. Preserve one explicit message subject through body, links, evidence and footer.
- An approval request acquired stock links for ordinary technical words. Operational/approval content must not enter financial symbol extraction.
- October 13 Active Trader messages carry unavailable scanner/catalyst/float/RVOL fields. Preserve that unknown state while repairing attachment lineage; do not fabricate fact values or change source trigger decisions.

## Rollback

Before deployment, retain the reviewed source commit and existing production release identity. Operational rollback follows the existing exact-source release procedure and stops only approved candidate scheduling before restoring its affected legacy trigger. Preserve all original observations, notification receipts and retry history. Never restore an entire crontab or delete evidence.
