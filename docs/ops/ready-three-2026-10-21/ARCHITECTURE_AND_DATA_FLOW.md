# Architecture and data flow — indicator JSON and ready-three

## Current provisional integrated architecture and security boundary — 2026-10-22 20:58 UTC

Candidate `a7508b039b1f39d06bfc216726656b82ae5d0ca6` is based on `origin/main` `b9804fa577e6d2793f4539c7458452707a350f61`. The exact full profile remains in progress, with two observed failures and no aggregate terminal result: the unapproved direct `positions_current` reader in `desk_truth_monitor.py` (release blocker), and the AJG/OI=0 expectation in `everything_blocked_20260926`, reproduced on exact origin/main baseline. The latter is inherited/out-of-scope and its test and `scripts/options_engine.py` are untouched by this candidate diff. Keep trading logic out of the topic PRs. The provisional results section in [test results](TEST_RESULTS.md) is authoritative for details.

The pipeline PR's latest `safe_flock` commit `f6c2b8e9afd1664fd45013f4fea4cf504a7d4131` adds checks that reject pre-existing symlink leaves and unsafe writable non-sticky parent directories; its focused adversarial path tests pass 44/44. This closes those pre-existing-path cases. It does not close the check-then-open TOCTOU window. A full atomic `O_NOFOLLOW` plus directory-FD/open-relative design remains future work; do not describe the lock path as fully race-safe or adversarial-local-user hardened. Separately, the process reaper's pidfd and identity checks reduce PID-reuse risk but do not prevent a target process from `exec`ing a different program between validation and signal delivery; that check-to-signal race remains.

PR branch checkpoint, all local and unpushed: pipeline/locks `f6c2b8e9afd1664fd45013f4fea4cf504a7d4131` (2 commits ahead of `origin/main`); n8n probe evidence `909f359e2ae26c761a2c6003dea6b50ab9f9f4c4` (1 commit ahead); docs branch is being refreshed locally. These topic branches do not have an aggregate full-profile qualification.

---

## Historical integrated architecture and security boundary — 2026-10-22 20:08 UTC (superseded)

Implementation SHA `88fbafcc27b58b4ea1c78f5e78fcfa9059a5d170` integrates current main b9804fa with the ready-three hardening. The import gate rejects file-forged host provenance; FW-P4 reads UFW live through exact read-only sudo commands; FW-P5 reads the running container image ID and compares the pin with `docker image inspect` RepoDigests; n8n DB role membership is checked; proposed P3/P6 services load only the dedicated host-alert environment. Process cleanup retains pidfd identity checks and safe_flock retains kernel lock authority. Focused security/reaper/flock/pipeline suites pass 80 tests; the exact integrated full profile remains unrun. The systemd/sudoers artifacts are proposals, not installed controls.

The merged main adds `desk_truth_monitor.py`, whose holdings-drift and held-exit checks read `positions_current` directly. The only approved phase-3 positions reader is `watch_domains.held_positions` for Watch's symbol-held fact; it does not authorize monitor quantities, account scope, or cash. No registered domain reader serves these facts, so the data-source gate correctly fails this new reader. Do not register it as approved or measured without an operator decision; keep the feature blocked until an approved projection or a compliant redesign exists. The last supplied production probe remains the 15:45 snapshot and is not fresh at this review time.

## Exception-safe symbol lock cleanup — 2026-10-22

The enrichment advisory lock is session scoped and survives transaction commits. If a writer raises after PostgreSQL marks its transaction aborted, the old `finally` path attempted the unlock SELECT in that failed transaction; that could mask the writer error and retain the lock until connection close. The current candidate rolls back before unlock on the exception path and preserves the original writer exception if cleanup itself fails. A focused regression verifies this behavior. Actual cross-session contention and release still need a PostgreSQL-backed integration test; unit fakes do not prove server lock semantics.

The full-profile pass on `bc729ac1…` predates this fix and the later df3e main merge. Current candidate `4fc9928a…` remains unqualified pending a fresh exact-SHA profile.

---

## Historical architecture delta — 2026-10-22 12:45 UTC (superseded by the provisional 20:50 snapshot above)

The ready-three candidate now supervises symbol-enrichment child processes in bounded batches, waits for their exit outcomes, and updates enrichment success state only after a successful child completion. Per-symbol PostgreSQL session advisory locks prevent concurrent claims, with cleanup on completion. The lock probe commits its transaction; callers must commit or roll back prior work before calling it. Unit tests cover child outcomes, timeout/cleanup behavior, and lock isolation, but no live cross-session production-schema test has been performed. The candidate has focused validation only and is not deployed; see [current status](CURRENT_STATUS.md) and [test results](TEST_RESULTS.md).

The options-lifecycle workflow now sets GitHub token permissions to `contents: read` and constrains pip installation to `requirements.lock.txt`. This reduces permission and dependency drift but does not pin action/container images by digest; hosted Python 3.12 behavior and immutable supply-chain provenance remain unverified.

---

## Historical candidate review and qualification — 2026-10-22 07:37 UTC (superseded)

Candidate code SHA `1cba3e8db005a3ad6cd3085e93189f53c4742473` passed the full local CIO hardening profile (exit 0, 2,628 seconds; candidate manifest hash `3bb9acba…`). This covers the registered repository test gates, not hosted CI, production-schema behavior, production traffic, UAT, performance, or failover. Production remains on `4104effb…` with six critical health findings; no candidate deployment occurred. Security review confirms a narrow process-reaper check-to-signal race remains on fallback paths, and credential rotation, effective ingress/auth, and CI workflow supply-chain hardening are unverified. Keep those limits explicit in any release decision.

## Remediation integration update — 2026-10-22 03:44 UTC

**Historical corrected-branch validation — 2026-10-22 04:29 UTC:** At that checkpoint, fix branch was reported at `4112946f` and its targeted set passed 42 tests. Exact invocation/files were not supplied. This was then stronger targeted evidence than the earlier 21/21 on `0534a85b…`, but does not describe or qualify the current a7508 branch. Documentation commits were expected before the next profile at that time.

At this point, the four audit findings had fixes in combined local SHA `1a1825ba41fe2a7ee9f01f43f3e21088b0072063`, which merged candidate changes with `origin/main` `63d37108`; an earlier targeted blocker-fix set reported 24 passes (exact command/files unavailable). The 1a profile later terminated with the single stale PIDFILE assertion recorded in current status and test results. The later correction branch `4112946f` has a reported 42-test targeted pass, but still needs a full profile on the final SHA after documentation import. The prior full-profile PASS applies only to `ca8b3658…`. No push, PR, hosted validation, or deployment is evidenced.

The combined run exposed a stale test assertion: a live PIDFILE without a held kernel lock should permit execution (`RUN_DONE`), whereas actual kernel-lock contention should still skip (`RUN_SKIPPED_LOCK`). Separate correction commit `0534a85b906048321724cb35906420a002dec703` updates that expectation; targeted N8N executor + safe_flock tests reportedly pass 21/21 there. The correction is not in the exact SHA currently under run 4345, which still has the nonterminal assertion failure. A separate documentation review also found the feature-to-live runbook was stale; it is now locally updated with current operator approval, grant separation, and exact-SHA CI rules. No runbook release checker change was made.

## Candidate architecture audit — initial findings (2026-10-22 03:29 UTC)

At the time of review, architecture identified two **candidate release blockers** and two lower-priority correctness risks. The 03:29 report said remediation was still in a separate isolated worktree; the 03:44 update above supersedes that implementation status.

| Finding | Risk | Planned remediation and validation |
|---|---|---|
| A stale PIDFILE can cause a false skip even after the kernel-backed flock was successfully acquired. | Valid work can be suppressed by stale metadata, while the real lock owner is the kernel lock. **Release blocker.** | Make successful kernel-lock acquisition authoritative; reconcile PID metadata only while holding the lock. Add regressions for stale PIDFILE + free lock (must run) and live competing lock (must skip), plus concurrent launch checks. |
| More than 15 grouped failure keys can be truncated/handled in a way that incorrectly classifies the result as component-only. | Remediation may target only one component despite broader failure evidence. **Release blocker.** | Preserve the complete grouped-key set and derive component-only classification from all groups. Test 16+ groups, mixed components, and output ordering/truncation boundaries. |
| HELD outcomes can disagree between `fail_streak` and the operator log. | Operators may see contradictory retry/failure state. **Lower-priority risk.** | Define HELD counter semantics and use one outcome classification for both emitted log and counters; add a regression asserting they agree. |
| Production-root diagnostics can fall back to DEV logs. | Health/remediation may reason from stale development data when production logs are missing or inaccessible. **Lower-priority risk.** | Require explicit diagnostics root, default to canonical CURRENT, and fail visibly on missing/unreadable production logs instead of silently reading DEV. Test missing CURRENT and stale DEV fixtures. |

The findings and planned regression expectations remain useful review context. Current fix integration and validation status is recorded above; see [current status](CURRENT_STATUS.md) and [test results](TEST_RESULTS.md).

**Reliability review update — 2026-10-22 00:39 UTC:** Exact-d55 architecture review found that `scripts/safe_flock.sh` used a non-atomic PID-file check/write, not an OS lock. Isolated fix `598df101b3e0358876a1415f8f9c97faf02fc685` now holds a nonblocking kernel flock through command completion and reuses an inherited same-inode descriptor for outer-flock callers; 91 focused tests pass. It is not integrated with c2 or deployed. The lock inode must persist and must not be removed during routine cleanup, or parallel processes could lock different inodes. Metadata-only `_check_lock_contention` can still misreport if PID metadata is stale/absent, although the wrapper itself blocks concurrent commands. `process_reaper.py` still signals only the selected Python PID and does not revalidate process identity just before signaling; process-group/cgroup ownership, starttime/cmdline checks, and descendants require explicit design. No production changes were made.

**Integrated candidate update — 2026-10-22 00:45 UTC:** Final local branch SHA `0090b035ea8b483a1e37001920832221f77be5a6` adds the c2 monitor changes, canonical CURRENT diagnostics reads, the `safe_flock` OS lock, process identity/pidfd protection, and CI registration for the four new regression test files. The reaper snapshots process starttime and raw argv; it uses pidfd signaling where available, checks identity before TERM and KILL, and fails closed if identity changes or cannot be read. It does not kill process groups. On platforms without pidfd, a narrow check-to-signal race remains. PID-metadata-only lock health checks may still report free during an active kernel lock. Focused integrated suites pass 31 and 277 tests and coverage audit reports no new unlisted tests; the full profile is pending.

**Latest integrated state — 2026-10-22 01:04 UTC:** SHA `aa0d28e2eb5a07d2d26ca867a0b2854f1094215e` additionally aligns escalation verification with the shared substantive-failure filter and replaces silent Telegram-notification failure handling with a mode-0600 JSONL failure ledger. The ledger records timestamp/type and a generic error only; it excludes notification content and exception strings. Held items are not marked notified when delivery fails. Exact focused suites pass 6 alarm tests and 10 pipeline/verifier tests. The full profile is still pending.

**Reaper fallback integration evidence — 01:08 UTC:** Latest exact SHA `2e23ffb9f84b95ef3f76d567d4467a9d78f96dc5` adds a disposable child-process test that ignores SIGTERM and is escalated by the reaper through the identity-checked numeric-PID path; the parent reaps the child and asserts termination. This closes the previous no-live-process evidence gap for that fallback test path, but does not test the deployed reaper policy against production workloads or resolve its check-to-signal race on old kernels.

## Current implementation reconciliation — 2026-10-22 00:25 UTC

Remote main `d55da84d` contains merged PR #1887 and #1909 cleanup; its full hardening profile passed all 556 configured gates at exit 0. Production now serves exact d55 (built 00:08:15.726Z). Health remains degraded with repeated pipeline reaper SIGTERMs. The no-auth local communications endpoint returned HTTP 200 because deployed auth remains `enforce=true, report_only=true`; external route is unverified. A c2 full-profile candidate is being qualified after its prior interrupted attempt. A separate log-root fix has 10 focused tests but is not yet integrated with c2 or deployed. `json_finite` is source-verified, while production-schema persistence and a natural successful writer remain unproven. Older snapshots below are historical; use [current status](CURRENT_STATUS.md) for the as-of verdict.

**Current reliability architecture note — 2026-10-22 00:25 UTC:** The remediator's strategy execution root (`DEV_ROOT`, with executable code/venv) differed from the live diagnostics root (`CURRENT`). It therefore read stale development logs and could report zero circuit/rate-limit hits while the served release had current logs. Candidate commit `f2c9f5a9` separates these roots: observe logs under canonical `CURRENT`, keep strategy subprocess execution under DEV. Ten focused tests and static checks pass; this follow-on candidate still needs integration with the c2 fix, exact-final-SHA qualification and hosted checks. The deployed process reaper is separately enabled at 20 minutes and records actual SIGTERM kills; do not infer a safe new cap from successful-only duration samples.

**Evidence date:** 2026-10-21 13:05 UTC

**Latest implementation audit — 2026-10-21 18:14 UTC:** Production now serves a6ac0eb (the #1899 merge) and includes the narrow non-finite JSON indicator fix, but not the full #1889 candidate or #1887 ready-three UI/health changes. Current GitHub main is 71df62a. The Oct 21 failed indicator receipt predates the live fix; production outcome remains unverified pending the next scheduled run.

**Superseding runtime provenance check — 2026-10-21 16:33 UTC:** Production currently serves f161 (`CURRENT` symlink target `f161fb927-main-exact-phase2-20261021-114259`); its `indicator_universe_lane.py` imports `json_finite.dumps` as `_dumps` and applies `finite_or_none`. Read-only `crontab -l` confirms `PROJ=.../CURRENT`, the production venv, and weekday 08:00 EDT line 262 with `flock` and `--universe`. The Oct 21 failed receipt at 12:00 UTC predates the f161 build/deploy at 15:43 UTC, so that run is not a post-fix validation. No scheduler defect was found; the next natural run (Oct 22, 12:00 UTC) is needed. Do not manually invoke the writer.

**Status:** Reviewed implementation map; production DDL and runtime qualification remain unverified.

**C3 review addendum:** The separate dirty runtime-wiring worktree can reach executor subprocess spawn for a qualifying requested ledger row, but the child’s `host_write_context()` currently returns `None` and refuses business writes; the new private publication protocol has no production caller. Normal HTTP due remains held at v1, while executor claim is based on lane/state and does not verify gateway-origin provenance. Before activation: define a closed `DueResponse@v2`/new-key contract; persist server-minted admission provenance; verify it before attempt configuration and bind it to effect claim/publication; wire a host-mediated, fixed-operation child protocol with identity, timeout, replay, and crash semantics; then test forged/replayed rows, end-to-end canonical publication, and kill/timeout/stale/partial-failure cases. Do not widen the public v1 response or publish the dirty patch. Production activation is unverified.

**Scope:** The separate indicator JSON remediation in PR #1889 and the Communications ready-three candidate in PR #1887. This is an implementation map, not a production deployment claim.

## Indicator JSON path

The live indicator pipeline is scheduled from the weekday 08:00 ET `scripts/indicator_engine.py --universe` cron with `flock`. At the 16:33 UTC audit, line 262 was present and `PROJ` resolved through `CURRENT` to served release f161. The path evaluates symbols, produces nested indicator result maps, and writes cache records through `scripts/lib/indicator_universe_lane.py`. A second cache refresh path is implemented in `scripts/indicator_cache_refresh.py`. The API in `scripts/api_v2.py` serves cached, fresh, and batch results and also writes signal-history values/details.

PR #1889 introduces the shared `scripts/lib/json_safety.py` boundary. It recursively converts non-finite scalar values (`NaN`, positive/negative infinity, including supported NumPy/Decimal values) to JSON `null`, and serializes with `allow_nan=False` for PostgreSQL JSON. This prevents Python's non-standard `NaN` token from reaching PostgreSQL JSON parsing. The follow-up local commit `bfe56222c` preserves string object keys and rejects non-string keys before traversing values; it prevents distinct non-finite keys from collapsing into a single `None` key. Local commit `190724731` adds a regression for the exact production field `pivots_weekly.pp`; the adjacent four-suite run passes 38/4 on that local head.

The indicator JSON change is separate from the Communications ready-three work in PR #1887. The two branches have separate review and release gates. Neither candidate PR is merged. Production now serves f161, which contains finite-JSON normalization; the Oct 21 failed writer run was before this build was deployed, so only a later natural run can validate the runtime fix.

## Data and transaction boundaries

The cache write is the primary indicator result persistence path. `indicator_cache_refresh.py` also makes a best-effort `_iem_upsert` into `intelligence_entities` after the cache operation; that auxiliary write can fail independently and is not evidence of cache transaction failure. Signal history is a separate API write boundary. Non-finite JSON normalization covers the reviewed cache serialization and API value/details paths, but the production DDL and column contracts for cache, signal-history, and intelligence-entity tables were not found in repository sources or queried in production.

The hosted PostgreSQL CI shard uses an isolated temporary JSONB table. That validates JSON encoding and PostgreSQL acceptance for the fixture; it does not prove production nullability, constraints, indexes, or type compatibility. Before asserting full downstream coverage, obtain schema evidence read-only and test the actual entity scalar columns and signal-history schema in an isolated database matching production DDL.

## Operational state and failure boundary

### Pipeline watchdog child lifecycle

The live pipeline failure audit found two different measures: health's narrow unrecovered substantive count (22 failures in the 18:46 snapshot; latest verification says 23 unrecovered) and 235 raw failed status rows at the 16:45 audit, most zombie/empty or superseded. Reaper logs show `trade_ai_orchestrator` runs repeatedly terminated at the 20-minute process cap, most recently at 18:27Z and age 20.8 minutes. Separately, `pipeline_watchdog.run_ier_engine` used to launch up to 15 `symbol_enrichment.py` children without waiting, mark `last_enriched` immediately at spawn, and log success before those children finished; `health_tick` reaps the shared group after its 30-second grace. This creates both lost work and false-success/backoff risk.

Local candidate `d8aef046` tracks the child handles under a shared 25-second bound, records success and advances `last_enriched` only after exit code 0, and records spawn/nonzero/timeout failures without advancing the timestamp. Four relevant test suites pass 51 tests; Ruff and compile checks pass. The candidate still terminates children exceeding its bound and is not a durable queue, not hosted-qualified, and not deployed. A separately supervised bounded queue remains the durable architecture direction; increasing global grace or detaching subprocesses is insufficient under systemd control-group cleanup. Do not raise reaper caps or launch a live retry without owner review and profiling.

The Oct 21 natural receipt records `InvalidTextRepresentation`, exit 1. Its production log lines 599–603 show PostgreSQL rejected `NaN` in nested `pivots_weekly.pp` JSON on the ef085 release. That run was at 08:00 EDT; f161 did not build/deploy until 11:43 EDT and now contains finite-JSON normalization. Therefore the incident is not yet recovered, but the failed receipt does not test f161. Do not mark the production incident resolved until the next natural run succeeds with a fresh receipt and cache evidence.

The Communications candidate reconciles ready-three health and stuck-delivery reporting. Its exact remote head is PR #1887 SHA `1707d3c074774a7d7b7379cb717db421fa979c45`. Its successful hosted checks do not prove the candidate is deployed. The delivery summary endpoint can report success without ready-three coverage/window/clock fields; production verification must include the full candidate schema and behavior after an authorized deployment.

## Trust boundaries and release controls

- Keep the SPCX kill switch active while the related safety incident remains open.
- Do not manually execute the live indicator writer to produce qualification evidence; observe the scheduled run and retain its receipt/log/output.
- Treat production DB schema, external reachability, and service/process inventory as unverified unless refreshed from authoritative sources.
- A green PR check qualifies only the exact SHA checked. PR #1889 remote 7c checks do not qualify the unpushed local follow-up `bfe56222c`; PR #1887 checks at 1707 do not qualify newer local documentation commits.
- Merge/deploy require the repository guard, release authority, operational-risk disposition, and post-deployment evidence. No production mutation was performed during this review.
- C3 remains out of scope for activation. The design contract requires a new run-key prefix to update `KEY_RE` and `DueResponse@v2`; the reviewed due evaluator holds qualification refusals behind the current v1 boundary. Static allowlist rows have empty `live_arg`, but neither `/api/v2/system-controls` nor n8n `/healthz` attests current workflow activation. No C3 activation was attempted; actual runtime state remains unverified.

## Next architecture validation

1. After an authorized release, review a later natural cron receipt and verify whether the serialization failure is resolved.
2. Run JSON round trips against an isolated database initialized from production cache and signal-history DDL.
3. Verify whether best-effort `_iem_upsert` needs non-finite scalar policy based on its real column types and downstream consumers.
4. After an approved release, compare the served build SHA, API schema, health deltas, and indicator output to the reviewed candidate.
