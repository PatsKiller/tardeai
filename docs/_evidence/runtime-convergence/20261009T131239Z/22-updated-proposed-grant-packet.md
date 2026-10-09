# Proposed exact-source deployment and selected scheduler recovery packet

**PROPOSED / SOURCE_ONLY — not requested, approved, prepared or applied.** This document grants nothing. The parent may request native scopes only after the relevant exact local/remote validation below. No peer grants are consumed or revoked.

Source checkpoint: **`13527203a9753c7841b98bcfa127a785065bed2c`**, incorporating main checkpoint **`bbff99766cd80ea630543abfaa639eb41eae5eb9`**. Final combined local acceptance is pending after current-main integration; no new push/PR exists at this packet's preparation. These checkpoints are not the eventual exact deployed merge SHA. [Earlier plan][plan] is superseded by this expanded selected-workflow scope; [current task audit][audit] explains the outstanding defects and operator exceptions.

## Binding manifest — fill and verify before requesting each grant

| Binding | Required value/receipt |
|---|---|
| Physical worktree / guard | Resolve and verify `/home/johnclaw/tradeai-wt-runtime-n8n-host-recovery-20261008`; use its executable absolute `bin/guard`, not a stale relative path. |
| Branch / source HEAD / source tree | `codex/runtime-n8n-host-recovery-20261008`; **FINAL_FULL_HEAD / TREE / FINAL_LOCAL_RECEIPT = PENDING**. Record clean state, current main and merge-base. |
| Remote / PR / checks | Repository `PatsKiller/tardeai`; verify actual origin URL; **PR_NUMBER / EXACT_PR_HEAD / REQUIRED_PR_CI = PENDING**. |
| Exact release source | **DEPLOY_MERGE_SHA / EXACT_MAIN_CI / PREPARED_RELEASE / SOURCE_MANIFEST = PENDING**. Must be current origin/main, reviewed and green, with no hybrid tree. |
| Prior release | **PRIOR_CURRENT_REALPATH / PRIOR_SHA / PRIOR_DROPIN_HASH / PRIOR_PIN_METADATA = freshly captured PENDING**. Last observed a9fa SHA `a9fa8b89b616f685145d27d6d2d62da3a1fab970`, release `/home/johnclaw/trade-ai-releases/portfolio-server/a9fa8b89b-main-exact-phase2-20261009-084133`; do not assume unchanged. |
| Runtime snapshot | **SNAPSHOT_TIMESTAMP / CRON_SHA / SELECTED_WORKFLOW_STATE_VERSION_HASHES / UNRELATED_WORKFLOW_HASH / SERVED_REGISTRY_HASH / WATCHDOG_STATE = fresh PENDING**. Old cron hash `b336c72c5c122ae5eeb7e664d6fa767f5dbd3ab1697ea63493c7c98120f65974` is comparison evidence only. |
| Native approvals | **SESSION/LEASE_ID / PACKET_SHA256 / GRANT_ID_BY_SCOPE / REASON / EXPIRY / USES = PENDING**. Coordination lease is not runtime approval. Re-read `guard show` before each mutation. |

Every grant reason must name this packet hash, branch or exact merge SHA/PR as applicable, resources, phase, prior rollback release, expiry and use budget. Reject absent, expired, replaced, unrelated or mismatched grants. No agent types or simulates `APPROVE`. Merge authorization is a separate recorded operator action; a push grant does not confer merge/deploy authority.

## Exact selected workflows

Unpublish these **nine IDs only**, using the installed n8n CLI after fresh active/version/hash confirmation. Preserve their definitions and execution history. No blanket shadow disable, import, deletion, reactivation or replacement.

| Group / lane | Exact workflow ID | Reason / retained host scheduler |
|---|---|---|
| N1 incident | `722fac0e043ea5c4` | Restore original */5 cron from receipt below |
| N1 snapshot | `c0d4c7845e5c4fcc` | Restore original */20 unlocked snapshot cron |
| N1 pilot | `078e8fcbea0c5020` | Restore original */15 cron |
| N1 research intake | `21fd15d5f8a4c4da` | Restore original */15 cron |
| N2 overnight night shadow | `0a170db6744afd7f` | Deployed predecessor gate lacks required proof; existing host schedule remains |
| N2 after-close broker-truth shadow | `0d48d2951cdc0cd0` | Same gate defect; no broker authority change |
| N2 after-close planning shadow | `19e0ed9711cfb320` | Same gate defect; host schedule remains |
| N2 Hermes learning tune shadow | `c7dc5a8273bf6f44` | Same gate defect; host schedule remains |
| Weekly maturity live | `e18d7849b4142927` | Unproven canary plus duplicate Monday06:40 authority; **legacy `40 6 * * 1` cron remains active** |

Evidence: [live workflow metadata][workflows] and [maturity audit][maturity]. Four N1 frequent shadows and the old maturity shadow stay in their measured inactive states; every other workflow's active/version state remains unchanged. Source template fixes do not update DB workflow code; corrected N2 import/activation requires a separate reviewed packet after N1 acceptance.

Four immutable receipt paths are under `/home/johnclaw/trade-ai-releases/persistent-state/data/runtime/n8n_cutover/`:

| Lane / receipt basename | Expected original receipt SHA-256 |
|---|---|
| `n8n-incident-fanin-20261009T020135Z-cutover.json` | `de637f1fc6fd2f615bd38176a1e15d38ecef93eaaeeca48993389c7423738cb3` |
| `crontab-snapshot-for-health-agent-20261009T020135Z-cutover.json` | `8c411632c9e30dd5bb2e4d9d60e31b6de6cce9c498fde5f6fd0986152bda9f3d` |
| `n8n-pilot-dispatch-20261009T020145Z-cutover.json` | `475fa1597dcc97d98c8edf3c8914057f5c62c4125c9f13a37ab06ae7b1f1a64f` |
| `n8n-research-intake-consumer-20261009T020135Z-cutover.json` | `5123fa967bbafe371d3128e8822dac5bf316e18baca5be0d71dd8797aaccaeda` |

Compare the actual immutable `line_before` with the freshly captured tagged cron line and reviewed helper output. Refuse any difference: the helper currently warns and can restore host text, so its exit0 alone is insufficient. Never rewrite the original receipt to make a comparison pass. [Isolated four-lane rehearsal][rehearsal] is TEST_ONLY, not host recovery.

## Minimum proposed native scopes and use budgets

These are **bounded proposed maxima**, not obtained permissions. Count actual native consumption against the final command manifest before presenting prompts; never batch to bypass guard classification. Any required extra command/use, changed identity or longer window needs a new reviewed packet and approval.

| Scope | Proposed window / maximum uses | Named actions and dependency |
|---|---|---|
| `git-push` | 30m / **1** | One push of exact final validated branch HEAD; no force, history rewrite or unrelated ref. Only after final local gates pass. |
| `release-write` | 30m / **3** | Canonical prepare, promote, one conditional rollback to captured prior release. Request only after merge SHA and required PR/main CI are green. |
| `config-write` | 30m / **15** | Up to9 selected workflow unpublish operations;4 reviewed operational-registry lane writes coupled to receipt recovery;canonical release binding/config transaction for promotion and conditional rollback. Temporary reviewed-copy preparation is reversible source preparation, not a grant to edit CURRENT. No compose/env/key/secret or unrelated registry changes. |
| `cron` | 30m / **13** | Nine exact workflow unpublish actions under ACTIVE policy2.0.1 §23, plus four per-lane exact single-line restorations; no whole-crontab replacement, new cadence, unrelated entry or maturity cron change. |
| `service` | 30m / **3 reviewed transactions** | One restart of existing `m8m-n8n` after selected unpublish;canonical promote/rebind;conditional canonical rollback/rebind. Final native command consumption must fit this budget or approval must be rebound. |
| `maintree` | 30m / **1** | Clean fast-forward of canonical primary to exact approved merge SHA **after** semantic live acceptance. No reset/dirty overwrite/history rewrite. |

Promotion/rollback service allowlist is `portfolio-server.service` plus the helper's existing CURRENT-bound set: `tradeai-health-agent.service`, `cio-governed-bridge.service`, `tradeai-cio-telegram.service`, `tradeai-telegram-callback-poller.service`, `tradeai-n8n-coordination-gateway.service`, `tradeai-n8n-run-relay.service`, `tradeai-n8n-run-executor.service`. Verify the exact helper version and active installed units before the grant; preserve restart/resource/send policies. Canonical binding paths include the portfolio-server `20-exact-sha-release.conf`, CURRENT/ACTIVE_RELEASE and the helper's existing release state/receipts; bind their actual paths in the final manifest. Do not install or restart an unlisted service. Independent timers/watchdogs/backups/reapers are preserved, not disabled or consolidated.

## Ordered execution and acceptance dependencies

1. Finish exact local acceptance, diff/authority review and source freeze. Obtain only the scoped push approval; publish PR once, run required CI, record explicit merge authorization, merge, and verify exact main CI. If main advances, reconcile/revalidate before release requests.
2. Capture fresh prior CURRENT, process/build identity, cron/registry/workflow versions and all rollback mappings. Complete an exact-source release preparation with frontend build/SHA stamps and persistent-state mapping validation under release authority. Primary stays unchanged during preparation/live acceptance.
3. Under approved configuration scope, unpublish the nine selected workflows, then restart only `m8m-n8n` under service scope. Read back selected inactive states and unchanged unrelated active/version state. Keep named shadows inactive. Verify no accepted selected-lane `REQUESTED`/`RUNNING` host requests, queued claims or relevant accepted n8n executions remain; DB `running` labels alone are not proof. Drain safely; do not cancel/replay work. Any ambiguity stops cron restoration.
4. Review a mutable operational registry **outside immutable CURRENT**, initialized from fresh ownership with valid measured cadences. Run `scripts/pipelines/cutover/_cutover.py rollback --lane <exact-lane> --receipt <exact-receipt>` dry-run using explicitly bound registry/state/backup paths, then one `--apply` per approved lane. Verify exact original line, normalized five-field cadence and match against prepared source intent. Preserve three existing safe_flock locks; snapshot's original is unlocked and may be restored only after its competing writer is inactive and fully drained. Original receipts, unrelated cron bytes/registry rows and watchdog state must remain unchanged. Remeasure counts; do not substitute an expected total.
5. **Only after all four restorations**, promote exact approved prepared merge-SHA release through `cio_phase2_exact_main_deploy.sh` with **`CIO_DEPLOY_FF_DEV_TREE=0`**, so its automatic primary fast-forward is deferred until external semantic acceptance. Verify CURRENT/process/API/build SHA, four cron ownership rows, selected inactive workflows, CURRENT-relative child paths and deliberate shared interpreter. Live no-interception Playwright must cover real row/API agreement, Problems/drilldown, truthful nulls, console/loader and390px overflow. No manual shadow fire, LLM/provider call or broker mutation is an acceptance step.
6. Canonical primary fast-forward is permitted only after semantic acceptance; refuse dirty/divergent state. Observe subsequent natural legacy fires and receipt/output/consumer behavior separately. Successful restored cron work is not N1 shadow/cutover acceptance. Record grants/uses/revocations, exits, hashes, applied scheduler receipts, exact release and rollback outcome; revoke unused own grants in finally and show final state.

## Failure recovery and explicit exclusions

Any promotion/semantic failure invokes **canonical rollback to the freshly captured PRIOR_CURRENT_REALPATH/PRIOR_SHA**, with the same approved service rebinds and root/API/build verification. Preserve scheduler recovery as separate state: **do not re-enable the nine NO_GO/defective workflows or re-retire restored cron merely to match old source**. The prior a9 release declares four n8n owners; reverting code after cron restoration can expose registry drift. Record that drift honestly, retain reviewed mutable recovery receipts and stop for corrective exact-source deployment; never edit the immutable prior release or claim convergence.

If workflow pause/drain or one lane restoration fails, stop before promotion and capture the exact partial state. Do not undo successful lane restorations or activate unsafe workflows without a newly reviewed recovery action. No restore of an entire saved crontab or n8n database.

**MFA OFF is RETAIN_WITH_REASON**, per operator exception; no MFA/2FA change or blocking prerequisite. **No model selection or provider calls until the user names a model.** No broker/order/stop/risk/send-authority mutation, provider-key migration, automatic policy approval, DB privilege/schema migration, queue replay or cross-asset activation belongs to this packet.

Ollama retirement remains a **separate privileged keyboard-only operator action**: proposed exact step `sudo systemctl disable --now ollama.service`, followed by state/port/residual-consumer readback. `sudo` is remote-forbidden under AGENTS; do not request it remotely, simulate keyboard approval, use `sudo -n`, change sudoers or infer authority from this packet. No local-model fallback or provider probe is allowed.

[plan]: /home/johnclaw/tradeai-wt-runtime-n8n-host-recovery-20261008/docs/_evidence/runtime-convergence/20261009T004124Z/55-corrective-rollout-plan.md
[audit]: /home/johnclaw/tradeai-wt-runtime-n8n-host-recovery-20261008/docs/_evidence/runtime-convergence/20261009T131239Z/20-all-requested-tasks-audit.md
[workflows]: /home/johnclaw/tradeai-wt-runtime-n8n-host-recovery-20261008/docs/_evidence/runtime-convergence/20261009T131239Z/live-n8n-metadata.json
[maturity]: /home/johnclaw/tradeai-wt-runtime-n8n-host-recovery-20261008/docs/_evidence/runtime-convergence/20261009T131239Z/maturity-canary-audit.json
[rehearsal]: /home/johnclaw/tradeai-wt-runtime-n8n-host-recovery-20261008/docs/_evidence/runtime-convergence/20261009T004124Z/56-n1-independent-rollback-rehearsal.json

PLATFORM_RUNTIME_SOURCE_ACCEPTANCE_BLOCKED


October9 integration supplement: current main3b5c248569908adfad9a60ca895e0fa9b2aa2c49 contains policy3.0.0 PROPOSED, with2.0.1 governing. Workflow scheduler edits require cron scope (§23); config scope alone is insufficient. Source checkpoint b1c1a9157ea10a29637cdbb42198c8dd21fe4e9f also includes CADI offline replay and research feed dedupe fixes. No model selection, provider calls or policy ratification. Rebind all PENDING exact-source/native-grant fields after final combined acceptance and actual merge.
