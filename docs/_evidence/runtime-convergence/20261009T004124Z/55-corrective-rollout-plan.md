# Corrective deployment and N1 recovery plan

Status: PROPOSED; no authority granted and no N1 rollback applied by this packet.
Owner: platform coordinator.
as_of: 2026-10-09T03:23:00Z.
Evidence class: SOURCE_ONLY for the implementation and plan; host identities below are timestamped OBSERVED_CURRENT evidence.

The operator explicitly requested push, merge, deployment, scheduler remediation, grants and documentation. Native approvals remain required by AGENTS.md. The coordinator holds exclusive deployment/production coordination lease `46088dc8-f61a-492b-969f-54ea739d6a04`; the lease grants no runtime authority. Existing grants belonging to other campaigns are neither consumed nor revoked.

[50-pre-corrective-host-metadata.json](50-pre-corrective-host-metadata.json) measured CURRENT, portfolio-server, gateway, relay, executor and Command Center at `d444fe9eb970f9e9640c149794f95f334deee320` at 03:02:41 UTC. CURRENT directory was `/home/johnclaw/trade-ai-releases/portfolio-server/d444fe9eb-main-exact-phase2-20261008-225242`. Re-measure this rollback target immediately before the exact-SHA grant packet. The candidate must include current main, pass final combined local acceptance and required PR checks, merge, and pass push-to-main CI for the exact merge SHA. No deployment from a feature worktree or outdated main.

## Four N1 lanes to recover

The [strict N1 matrix](38-runtime-strict-n1-matrix.json) classifies all four frequent lanes NO_GO. Later live runs cannot supply incident's missing successful pre-cutover canary or snapshot's missing shared-lock canary. The source intent correction restores legacy cron ownership with an explicit NO_GO reason, while preserving output contracts and the corrected consumer descriptions. Source intent is not proof that runtime restoration has occurred.

| Lane | Live workflow to unpublish | Receipt basename | Legacy cadence |
|---|---|---|---|
| n8n-incident-fanin | 722fac0e043ea5c4 | n8n-incident-fanin-20261009T020135Z-cutover.json | `*/5 * * * *` |
| crontab-snapshot-for-health-agent | c0d4c7845e5c4fcc | crontab-snapshot-for-health-agent-20261009T020135Z-cutover.json | `*/20 * * * *` |
| n8n-pilot-dispatch | 078e8fcbea0c5020 | n8n-pilot-dispatch-20261009T020145Z-cutover.json | `*/15 * * * *` |
| n8n-research-intake-consumer | 21fd15d5f8a4c4da | n8n-research-intake-consumer-20261009T020135Z-cutover.json | `*/15 * * * *` |

Receipts are under the existing persistent-state `data/runtime/n8n_cutover` directory. Preserve their original hashes and malformed cadence evidence. Original `scheduler_before.expression` strings also contain command descriptions; source intent uses the validated five schedule fields from the exact `line_before`, retaining the original match marker. The operational rollback receipt retains its historical scheduler object; compare its normalized cadence and match to the prepared source. [Source intent and original receipt hashes](56-n1-restoration-source-intent.json) record this metadata correction without rewriting any receipt. Rehearse the existing per-lane rollback helper using copied receipts, a fake CRONTAB_CMD, and isolated locks/state/backups. Record prior negative source-intent proof and per-line rehearsal results before any host request. Do not restore a whole crontab.

## Grant packet and execution order

After exact source/CI identities exist, prepare a fresh packet naming the PR, full merge SHA, prepared release, actual prior CURRENT, four workflow IDs, four exact receipt hashes, current cron hash, permitted unit/container names, expiry and uses. Request only the necessary native git-push, release-write, cron, config-write, service and maintree scopes. Requests grant nothing until the operator approves through the guard. Do not consume a mismatched grant.

Prepare the canonical immutable release and verify persistent-state mappings, full frontend build and exact SHA stamps. Keep primary unchanged during live acceptance. Before any cron writer is restored, unpublish only the four named live workflows through the installed n8n CLI; restart only the existing `m8m-n8n` container; verify unrelated workflow active/version state is unchanged, selected workflows are inactive, and all previously accepted selected-lane requests have drained from the read-only host ledger. Keep their frequent shadows inactive. A failure stops restoration.

Use a reviewed mutable operational registry copy outside CURRENT for the existing `_cutover.py rollback --lane --receipt` helper. It starts with the measured n8n ownership and corrected valid cadences. Apply each exact single-line restoration after its reviewed dry-run. Preserve the three Python-lane locks; restore snapshot's exact unlocked legacy command only after its other writer is inactive and drained. Verify every unrelated cron byte, all original receipts, expected four source scheduler rows and the independent host watchdog remain unchanged. Re-measure counts rather than asserting an expected total.

Promote only the exact approved prepared release through `cio_phase2_exact_main_deploy.sh`, rebinding its existing CURRENT-bound services. Accept only exact CURRENT/process/API/build SHA agreement and read-only LIVE Playwright against the actual API: route, honest rows/counters, Problems filter, drilldown, console, loader and 390px overflow checks. Any required promotion or semantic acceptance failure invokes canonical rollback to the captured prior release, then verifies roots and health; approved scheduler ownership stays recorded as separate state. Fast-forward the clean primary checkout through the existing helper only after semantic acceptance. Never overwrite dirty/divergent primary state.

Record every grant/use/revocation, command exit, workflow change, per-lane restoration, exact release, browser/API proof and conditional recovery. Subsequent natural legacy fires can demonstrate restored scheduling; they are not N1 shadow acceptance. N2 generated workflows remain inactive and are not imported or cut over. Host senders, model-secret ownership, broker/order/stop/risk/2FA authority and policy ratification remain unchanged. Retired Ollama's privileged system-service action and owner MFA enrollment remain separate operator work.

Full program source acceptance remains blocked pending the documented proof and design gaps; exact deployment alone cannot establish production convergence.
