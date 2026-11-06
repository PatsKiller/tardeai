# Alerting and self-healing readiness — 2026-11-02

Source-edit handoff only. Jobs correction is committed at `b48296dad` on `wt/cc-watchers-audit-20261102`, dependency local `88a5fa664` (original `b6b6bd396`). Neither this handoff nor passing tests establishes deployment or operational acceptance. No send, activation, scheduling change, push, merge or grant modification was performed by this audit agent.

## Evidence roots and time

[VERIFIED] Served directory observed at session start: `portfolio-server/59ff17d2b-main-exact-phase2-20261102-100204`. Runtime evidence root: persistent-state. Source base: `a95a911a9`. Exact artifact names below are relative to this audit scratch directory. No credential values, chat/account identifiers, portfolio values or private host identifiers are included.

[VERIFIED] `installation-metadata.json`, as_of `2026-11-02T18:58:48.910262Z`, records whitelisted `systemctl --user show` properties and cron line counts. It runs no unit or producer. Timer presence is not a delivery receipt. A oneshot being inactive between runs is not itself unhealthy.

[VERIFIED] `projection-comparison.json` records old/new pure reader projections against the same frozen Jobs rows and a fresh existing watchdog receipt. This is read-only source projection, not the served API. `browser-verification.json` is an explicitly synthetic isolated browser fixture of the actual Jobs component at 1440/390 px; zero external or mutating requests. It proves rendering, not live delivery.

## Readiness matrix

| Component | Designed / implemented | Merged / deployed source | Installed / armed | Actually ran / delivered | Current assessment |
|---|---|---|---|---|---|
| Independent missed-run watchdog | [CODE] `scripts/cron_outage_watchdog.py`, explicit success receipts, >=2 misses, refusal tracking and monitor incidents | [VERIFIED] source exists in served release | [VERIFIED] timer loaded, enabled and active at18:58:48Z; monitor mode enabled by reviewed configuration | [VERIFIED] fresh CRIT receipt18:55:00Z; current poll HELD, accepted true, delivered false; state last confirmed delivery18:42:01Z | Operating and detecting incidents; latest delivery unconfirmed; output presentation previously concealed this distinction |
| Failure pager | [CODE] `scripts/delivery_failure_alerts.py::page_p1`, event handler called by deployment/queue paths; not a periodic job | [VERIFIED] source exists in served release | [CODE] no cron registration required; routing is invoked by events | [VERIFIED] latest retained typed receipt03:45:17Z, P2 recovery, ROUTED/accepted true/delivered false | Implemented and invoked; fresh end-to-end channel qualification not proven. “Not registered—cannot page” was false |
| Merge notifier | [CODE] digest + reconcile replace retired per-PR timer | [VERIFIED] current scripts exist in served release | [VERIFIED] digest/reconcile timers both loaded, enabled, active; obsolete notify not-found as intended; registry still NEVER_SCHEDULED for actual timer lanes | [VERIFIED] both services failedexit1 at18:58:48Z; prior reconcile success18:30 is no longer current | Real service failure plus declaration drift; do not install retired timer or turn registry mismatch green |
| Self-heal code fixer | [CODE] isolated coding worker/evaluator, request queue, protected-path/claim/egress/test/PR controls | [VERIFIED] fixer implementation exists in served release | [VERIFIED] PAUSED declaration, zero active cron lines, no unit; last applied receipt armedfalse; generic temporary push grant does not name self-heal-fixer | [VERIFIED]07:43:31Z receipt applied,5 fix_requested,0 attempted/PR/deployed; refusal “no active git-push guard grant” | Implementation exists but scheduled fixer is not operational. Real authority/install/qualification blockers remain |
| Main-red autoheal | [CODE] separate infrastructure CI rerun path, not a general code fixer | [VERIFIED] #2477 source available in served release | [VERIFIED] timer/service not-found, no retained last receipt at declared runtime path | Not observed running or recovering | Implemented/deployed source is not installed/armed/running evidence |
| n8n failure diagnosis | [CODE] diagnosis/intake to repair requests | [VERIFIED] source present | [VERIFIED]1 active cron entry | [VERIFIED]18:18:01Z apply receipt oktrue | Intake runs; that does not establish downstream fixes |

## Why CRIT could show “delivery not required”

[VERIFIED] At18:30:00Z watchdog receipt was CRIT, alert_requiredtrue, notificationNOT_REQUIRED/deliveredfalse; state last delivery18:04:00Z. [CODE] `cron_outage_watchdog.py::deliver` has a1800s reminder interval and updates last delivery only on a typed deliveredtrue sender outcome. That poll was inside its dedupe interval, so incident severity and current send requirement were different facts. The old UI lowercased NOT_REQUIRED with no prior delivery clock, making the active incident look unimportant.

[VERIFIED] Later18:52–18:55Z polls changed to HELD/acceptedtrue/deliveredfalse. State recorded an intervening transport-confirmed18:42:01Z delivery. This is neither a blanket dead-channel diagnosis nor evidence that the current poll reached the operator.

[CODE] A second dedupe contract conflicts with the1800s watchdog repeat: `scripts/lib/comms_editor.py::fingerprint` removes timestamps/IDs, while `DuplicateLedger.check` defaults to `DUPLICATE_WINDOW_HOURS=20`. Watchdog requests `dedupe_minutes=0` at the intent router, but that does not override the editor. Stable reminder text can therefore be HELD for20h. [VERIFIED] contemporaneous live editor receipts18:51/18:52/18:53 show duplicate_of present and held_reasonnull; no secret/chat identifiers were inspected or emitted. Exact message-to-editor correlation should be preserved in the scoped correction tests rather than inferred from timing alone. Lead classified this P0 and requested a narrow guarded source fix; no hold was cleared and no bypass used.

[CODE] `telegram_alert.py::delivery_outcome` truthfully separates HELD/ROUTED/FAILED from DELIVERED, but watchdog retains only status/accepted/delivered/kind. It does not retain the editor hold cause or message id/count, so current diagnostics need additional provenance. A bool-only historic receipt is weaker than a typed transport receipt.

## Why self-heal is disabled; real versus artificial blockers

[VERIFIED] Fixer code is present. It is not only documentation. Last apply attempt07:43:31Z retained5 requests and no execution attempt because arming failed. [CODE] `arming_verdict` requires a matching explicit self-heal-fixer push grant and budget; a broad temporary feature-branch grant does not supply lane authority.

[CODE] `policy_verdict` checks an old literal heading containing “24.11 Self-heal fix PRs from the self-heal-fixer lane” plus ACTIVE. Current24.11 is the broker market-data provision. This is brittle policy coupling and stale section numbering, but replacing a substring does not grant the missing authority. The scheduled push capability must be explicitly ratified through the real governance path, then represented by a structured capability rather than authority inferred from prose/history.

[VERIFIED] No installed fixer cron line. [CODE] Proposed cron install is section17 governed and separate from git push authority. No previously denied activation was retried by this audit. Lead supplied prior cc4 genuine-denial context; this audit did not independently reproduce that historical denial.

[VERIFIED] Configured Claude Code binary and bwrap exist; unprivileged user namespaces are enabled. Configured Codex CLI path is absent and that backend is disabled. [DOC-CLAIM] These prerequisites do not prove sandbox isolation, credential withholding, egress qualification, protected-path refusal or useful fixes under production identity. No credential was read and no paid candidate run was performed.

What would happen if merely scheduled today: [CODE] it should retain requests and refuse arming/policy before proposing/pushing; if those checks were bypassed, the unqualified paid/egress/scheduler identity would be unsafe. Do not equate “install cron” with a complete readiness change.

## Preferred architecture and remaining work

[CODE + RECOMMENDATION] Keep deterministic incident detection, request routing, due checks, retries, budgets and exact-head release controls outside the coding model. Use the already implemented, operator-selected Claude Code isolated worker for the first qualification; a second model backend is optional after equivalent harness qualification. Use internal governed reasoning for bounded diagnosis/triage, then a coding worker produces a local candidate. Require an independent evaluator, protected-path and claim checks, strict egress redaction, offline tests, draft PR, exact-head CI, governed merge/release and post-release acceptance. Codex is appropriate only after the configured CLI/backend is present and qualified. This is a hybrid architecture derived from existing code and the operator’s prior implementation directive, not a product capability claim.

Technical requirements: qualify sandbox/egress under actual non-secret execution identity; seed a synthetic defect and prove protected-path refusal; show stderr/exit/duration/traceback evidence; prove queue reclaim/idempotency and no repeated paid attempts; prove candidate versus independent evaluator separation; ensure a failed attempt cannot push; retain exact head/receipt linkage; acceptance must observe the eventual served release. Main-red infrastructure reruns remain a separate bounded lane.

Governance requirements: explicit lane arming/push capability and budget, active policy capability for scheduled PR uploads, approved installation under the scheduler grant and reviewed registry declaration. No code agent can self-issue these from a handoff or substring. Genuine prior denials remain binding.

## Jobs/UI correction implemented

[CODE] `b48296dad` reads only fixed existing watcher receipts. It shows event-driven pager identity, real digest identity/declaration drift, last disarmed fixer receipt/time, CRIT versus monitor freshness, current send versus previous confirmed delivery and dedupe deadline only for the matching finding fingerprint. It does not infer success from the next due time, acceptedtrue, future/dry-run receipts or mere code presence. It integrates `JobFailureDiagnostics@v1` in failed rows and the operator evidence sheet, preserving missing exit/trace/host identity as explicit gaps. It does not fabricate a traceback or expose raw worker/host identifiers.

[VERIFIED] Frozen Jobs snapshot18:45:27.608050Z has687 registered rows:493ACTIVE,22paused,140retired,32NEVER_SCHEDULED. Unknown217 includes185ACTIVE+32NEVER_SCHEDULED;343due today is another population. 185/493=37.53% of active,185/687=26.93% of all registered. The patch reclassifies the32 intentionally unscheduled rows without turning185 real evidence gaps healthy; UI explicitly shows trigger populations. Inventory separately annotates nonlive intent; the patch does not activate or claim live success for those lanes.

[CODE] Existing #2444 already contains systemd schedule census and5 validated-success fallback fixes. This branch deliberately preserves those for normal integration rather than overwriting/doubling them. Lead must reconcile the overlapping jobs_health.py changes.

## Validation performed

[VERIFIED]128 combined Python checks passed; final18 watcher checks passed after final reader changes. Ruff0.16.2 passed. Coverage gate found0new unlisted tests; dark-contract gate found0new unexplained contracts; line-ending gate7files/0findings; git diff --check passed. Native frontend suite12checks, TypeScript and full npm build passed; Vite1621modules. Existing bundle-size/boot-script warning remains. Synthetic actual-component browser at1440/390 verified distinct watcher labels, current HELD + prior delivery clock, failure evidence sheet,44px review control, no horizontal overflow and0external/mutating requests. Artifacts: frontend-build.log, browser-verification.json, watchers-{1440,390}.png, diagnostics-{1440,390}.png, projection-comparison.json.

No claim of served behavior, live message delivery, active fixer or recovered service follows from these tests. Those are still pending integration/approval/runtime acceptance.

## Concrete controlled test plan for lead

[VERIFIED] Existing sender dry run executed without sending:

    python3 scripts/delivery_failure_alerts.py --dry-run --kind cc_operations_audit_test --message 'TEST ONLY: Command Center operations audit; no incident or trading action.'

Output:

    {"would_page": true, "kind": "cc_operations_audit_test", "message": "TEST ONLY: Command Center operations audit; no incident or trading action."}

Next offline test: independent reviewer verifies the scoped repeat fix with synthetic clock, state, sender and duplicate ledger; unchanged/early duplicates stay suppressed, authorized due repeat reaches only mocked transport, forged markers/context fail closed, stance/product holds and interdict remain, and failure does not advance delivery state. No account/credential/provider needed.

Live verification remains a distinct explicitly authorized operator-surface action for lead. Preserve the current interdict and guard decisions. Use a plainly marked TEST with no financial content, one chosen approved channel and strict cap; stop before send if the dry-run destination family/routing differs. Retain typed DELIVERED/HELD/ROUTED/FAILED status, provider-message-id presence only (no identifiers in report), timestamp, duration, reason, and actual operator acknowledgement. Keep synthetic audit receipt separate from operational health to avoid converting the test into a real recovery claim. Telegram evidence does not establish email/SMS routing; each enabled channel needs separate permission/cost review and its own receipt. No live send has occurred in this audit.

## Remediation keys for lead deduplication

P0 ALERT-REPEAT-CONTRACT:20h editor versus30m watchdog; narrow source proposal pending independent review.
P0 MERGE-NOTIFIER-RUNTIME:installed digest/reconcile failed; repair root cause, not retired notify installation.
P0 SELFHEAL-ACTIVATION:code exists, but explicit authority/install/qualification missing; preserve genuine denial.
P1 WATCHER-REGISTRY-DRIFT:review actual digest/reconcile registration through protected path.
P1 FAILURE-RECEIPT-PROVENANCE:retain safe hold reason and typed delivery lineage; do not treat accepted as delivered.
P1 ACTIVE-JOB-EVIDENCE:185ACTIVE unknowns need source-owned tickets; inventory owns member map.
P2 WATCHER-READMODEL:implemented atb48296dad, unmerged/unreleased pending lead integration.
P2 POLICY-CAPABILITY:replace fragile self-heal heading gate only after correct policy capability is ratified.

## Final source / review checkpoint

[VERIFIED] Peer release advanced during this audit. `served-source-presence.json`, as_of19:11:48.938435Z, resolves CURRENT to `a95a911a9-main-exact-phase2-20261102-133203`; all6 listed source files exist. Earlier59ff pin is a session-start observation. The pure projection comparison field is explicitly `session_start_served_release`, not a current served assertion. Neither new source commit below is in that served release.

[VERIFIED] Separate P0 repeat-contract patch frozen locally at `e6ad137a1edf6d60117f82664cc2778c862ed312`,6files. It keeps the deterministic watchdog due decision, issues a private internal-code context bound to original body, admits only the actual wrapper/wire chunks, and scopes the editor content identity to findings/configured positive reminder_seconds/epoch slot. A second stable finding/content family cooldown prevents early duplicate admission across slot boundaries if watchdog state is lost. Plain payload text/JSON/producer/zero-dedupe cannot issue context. This is code provenance against untrusted payload, not cryptographic authentication or a security boundary against arbitrary Python execution.

[CODE] Global20h ordinary-content dedupe, product/stance/missing-decision holds, intent routing, interdict, transport and typed delivery checks remain in place. The patch sends nothing by itself. It also binds an existing exception class string before a callback in telegram_alert.py to resolve inherited RuffF821, without changing routing policy.

[VERIFIED]21new synthetic real-path checks pass, including configured1200s interval (no magic30min), early/no-send, same-slot retry, lost-state slot boundary cooldown, due repeat, changed finding, payload forgery, exact-body mismatch, wire normalization/multi-chunk binding, invalid cadence, context reset on exception, interdict, product/CIO holds, router dedupe and failed transport. Earlier80adjacent editor/wrapper/watchdog checks and215additional notification/router/prevention checks pass; final30repeat/outcome checks pass after minimal ExitStack/finally scoping. Ruff, test registration, dark contracts, line-endings6files/0findings, git diff and normal commit hooks pass. Broader inherited tests attempted2live-DSN connections; the hermetic test guard refused both before libpq. No DB connection or alternative path occurred.

The commit hook initially refused the new claim because its worklog Plan was missing. The actual approved steps/checkpoints were recorded through the owning session and the normal hook rerun passed; no override. Initial large loop indentation tripped the whitespace-churn gate, so the implementation now uses ExitStack/finally and preserves the loop text; the gate passes without exception.

Lead requested two independent adversarial reviews before production. Claim20c2c686 is held frozen awaiting those reviews; source is locally committed, clean, unpushed/unmerged/undeployed. Source-edit Jobs claim5301963e was released normally for lead integration. Worktree and all commits remain preserved. No live notification or control activation has occurred.
