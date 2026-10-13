# Momentum lineage and lifecycle implementation

Status: DRAFT — locally implemented and tested; operational acceptance pending
Owner: Codex; authoritative producer and lane owners retain their existing roles
as_of: 2026-10-13T17:37:12.033950+00:00
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

## Requested live rollout — 2026-10-13

[DOC-CLAIM] The operator explicitly requested "push deploy live". This supplies remote intent and deployment intent; active scoped guard approval is still required by the repository's native approval procedure. Rollout session `a767b60e-d3ca-45a7-b74d-9b2e89ad2780` started at `2026-10-13T17:17:53+00:00` with documentation leases. The existing local candidate is `bcdcb69fc0306794b56379cdae0456fdc5262009`, source `a5c427791997038d07a53038a40ccac6afc1ce57`; no grant was active at the first rollout check.

[VERIFIED] CURRENT and `origin/main` advanced to `f7b881ac147ac7237ccbabd9b72c5099b54f69b9` after PRs #1717 and #1718. Their exact-head PR checks were read; the working candidate's CI and deployed acceptance remain separate and pending. The rollback release observed for this rollout is `f7b881ac1-main-exact-phase2-20261013-112950`. Policy file blobs are unchanged from the candidate. A merge preview found four content conflicts: shared candidates, API, momentum evidence and scanner projection. It changed neither HEAD nor the worktree. Public conflicts will be prepared under leases; protected incoming main code and protected validation require the requested per-task grant.

[CODE] Canonical release preparation currently clones CURRENT and creates `.env` / `config/broker_credentials.env` links in `scripts/cio_phase2_exact_main_deploy.sh`. This conflicts with AGENTS.md §24.7: "No agent reads, copies, links or prints `.env`, a rendered env file or any credential file". No release prepare/promote was executed. Preserve this finding; operator-owned secret provisioning is needed before an agent can complete a compliant rollout. An exact merged-SHA release grant is requested only after candidate integration and required CI are green.

[DOC-CLAIM] A bounded test-only execution-engineering grant was requested in this chat for integration of candidate `bcdcb69fc` with approved main `f7b881ac1` and three isolated A1/A2 validation invocations. Requesting it does not grant it. No Telegram message, grant issuance, protected test execution, push, merge-to-main or production mutation occurred at this stage.

[CODE] The four public conflicts are prepared in the registered worktree, without applying incoming protected paths. Preserve main's expandable five-fact controls, filter controls and full-row population labels; retain original source clocks, explicit factual verification and original producer accounting. `scan_run_date` / `scan_run_label` are accepted as run/session identity, never as an observation clock. A regression proves that a same-day row with only cache/DB/run-finish clocks retains its values and historical publication verification but cannot establish current qualifying facts. This preparation is a public integration checkpoint; it is not the final merge of main and has no native/full-release acceptance.

[TEST] Prepared public integration: `TRADE_AI_CI=1` targeted regression **465 passed in 21.56 seconds**, zero failed/skipped. The hermetic guard again refused three live-DSN attempts before libpq. JUnit artifact: `/tmp/momentum-public-integration-validation.xml`. Changed Python lint/format and diff checks passed. Frontend `npm run build` passed. Both screen fixture browser checks passed, with new receipts at `/tmp/momentum-ui-readbacks-public-integration.json`; original `/tmp/momentum-ui-readbacks.json` bytes and their original timestamps/hash are preserved, also archived at `/tmp/momentum-ui-readbacks-20261013T150356Z.json`. Headless Chromium initially failed on sandbox IPC; the approved isolated rerun used a fresh temporary profile and blocked non-loopback requests. No production browser profile or cookie was used. The test server was stopped after verification.

[VERIFIED] The operator ran the native approval script and typed `APPROVE`, granting 45 minutes and three execution-engineering uses. A host-context guard check observed three uses and 42 minutes remaining. The sandbox context has a separate isolated ledger; its empty result is not authoritative for the host grant. Use the host context for permission checks and preserve that distinction. The shared-Git write remained pending on sandbox approval until `2026-10-13T21:55:27Z`; the host grant had expired before bounded validation could start. No protected validation invocation consumed a use. Expiry never permits automatic renewal or use of an unrelated active grant.

[CODE] Main `f7b881ac1` was integrated as `9e0c8685c`; the newer approved public n8n PR #1719, main `5bfccec3a31bde75c68233ba9ce98022ae8adcd9`, was integrated as **`5b674ec4b33ac4e5aa6da18e30f1e6bcf69aa660`**. This is the frozen integrated code commit. Four prepared public resolutions were retained; the later API conflict retains canonical producer counts and main's alternate-population omission. Protected source directories and session-grant source are unchanged from reviewed main `f7b881ac1`. Imported Markdown hard-break whitespace was preserved; the tranche's diff check against the current-main base passed. No runtime configuration was changed; approved registry source was inherited from main.

[TEST] Frozen integrated code: **465 passed in 17.78 seconds**, with three live-DSN attempts refused before libpq. JUnit `/tmp/momentum-integrated-public-regression-5b674ec4b.xml`. Frontend build passed with existing bundle warnings. These are public targeted checks, not the pending protected native/release-equivalent/adversarial suites.

[TEST] `/tmp/momentum-bounded-validation.py preflight` returned exit 0 and `business_test_invocations=0`, receipt `/tmp/momentum-containment-preflight-3mg_1sxp/receipt.json`. The finite launcher masks host home, runtime, temporary, database/log and service locations, clears inherited environment and uses a private network/PID/IPC namespace. Business tests, once actively granted, execute only in copied immutable source fixtures with private Git metadata and empty owned state/dotenv. Its command prefix is approved before requesting a renewed window. Each of its three named invocations rechecks the exact-head grant, consumes one use, has a wall-clock bound and emits a dated receipt. Preflight proves containment startup only, not business test success. The fresh native window is requested only after this preparation; no push or deployment has occurred.

## Completed native validation attempts — 2026-10-13

[TEST] The operator renewed the exact-head `execution-engineering` grant for frozen head `d08a12507d9700b8c31fad3fe5bbe573b5e408b2`, source `5b674ec4b33ac4e5aa6da18e30f1e6bcf69aa660`, and the immutable ready packet. All three authorized fixture invocations completed between `2026-10-13T22:59:14Z` and `2026-10-13T23:05:21Z`. Each consumed one use; no engineering use remains. The host-context grant check confirmed this. Unrelated active grants are not authority for this tranche.

[TEST] Source-only release-equivalent validation passed **17/17 steps**, zero failures/warnings, 38.7 seconds. The unchanged Phase 11 adversarial suite passed **15 tests**, zero failures, 2.48 seconds. Both ran in private namespaces with host state and credentials masked. Production runtime acceptance remains `NOT_MEASURED`.

[TEST] The native PR regression finished with **187 passing file chunks and two failing file chunks**; the two gates contain three test failures. `cc_v3_boot_no_reload_loop` could not rewrite its fixture `dist/build-meta.json` because the launcher mounted the build read-only. Two `deploy_ff_dev_tree` cases could not parse Git diagnostics because the masked `/etc/alternatives/awk` broke `/usr/bin/awk`. These are harness failures; preserve their original failed receipts. No source fix, skip, exclusion or successful result is inferred from diagnosis.

[CODE] Prepare one corrected native-only invocation: copy the public frontend build into the owned writable fixture and bind only the resolved public `awk` binary into its private alternatives path. Keep the private network and all host-state/credential masks, the frozen source, the existing selector, base, budget and jobs unchanged. A new immutable packet binds the corrected launcher and documentation head; its grant must explicitly name `NATIVE_RETRY_ONLY` and the packet hash. Verify these two fixture conditions before asking for that one-use grant. Neither source-only nor adversarial validation needs repetition for this harness correction. The original implementation source stays byte-identical; only this dated evidence and the docs index are added.

[TEST] Corrected harness preflight returned exit 0 and `business_test_invocations=0`: `/tmp/momentum-containment-preflight-rd4_56fy/receipt.json`. It verified working public `awk`, a writable owned build copy and an unchanged original `build-meta.json`. It consumed no engineering use and ran no business test. The original launcher is preserved at `/tmp/momentum-bounded-validation-20261013T225914Z.py` with its original SHA256 `3e147c3e31a0d0a98c2fd1a6e9b6d421593cd64185c3957bdf1dd7160fa575fd`.

The [native validation record](MOMENTUM_LINEAGE_NATIVE_VALIDATION_20261013.json) preserves original clocks, failed diagnostics, scopes and artifact hashes. Remote synchronization remains blocked on a green native retry. No push, GitHub CI or deployment has occurred.

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
