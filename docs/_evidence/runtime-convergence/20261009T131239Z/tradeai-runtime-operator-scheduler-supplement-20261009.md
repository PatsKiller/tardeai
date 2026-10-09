# Corrected operator-owned scheduler recovery packet

**PROPOSED / SOURCE_ONLY; NOT INVOKED, REQUESTED, GRANTED OR APPLIED.** Supersedes the actor assignment in step3 and step4 of [repo22](/home/johnclaw/tradeai-wt-runtime-n8n-host-recovery-20261008/docs/_evidence/runtime-convergence/20261009T131239Z/22-updated-proposed-grant-packet.md). Exact final source/merge SHA, CI, fresh prior CURRENT, workflow versions, native grant IDs/reasons/uses and application receipts remain PENDING. Previous measured CURRENT3b is a comparison checkpoint, never an assumed deployment binding.

## Why operator execution is required

[AGENTS.md §9.3](/home/johnclaw/tradeai-wt-runtime-n8n-host-recovery-20261008/AGENTS.md:2451) says: **“Installing, editing or removing a scheduler entry is operator-only. Propose.”** Unreplaced §23.2 applies §9.3 in full and says:

> Install, activate, edit or retire only under an operator grant — a `cron` grant for the crontab/timer side, a `config-write` grant for units and registry-bearing config (§9.3 rule2, §17). An agent proposes the workflow JSON (exported under `docs/implementation/n8n-parallel/workflows/`); the operator imports and activates it.

These grants are necessary; they do not independently remove the operator-only actor boundary. Root must not promise to execute the nine n8n unpublish operations merely because cron/config grants exist. The four host cron restorations are also operator-owned scheduler edits. Any claimed delegation must be explicit in a fresh action record, permitted by the governing policy and accepted by the classifier; a general task instruction or grant reason is not such proof. On denial, stop and retain the operator action boundary. No command rephrasing, wrapper, direct SQL or API route may bypass it.

The current header is AGENTS3.0.0 **PROPOSED / Effective-DatePENDING**, with2.0.1 governing. No proposed Agent, bridge-token or routing authority applies. The broad user instruction authorizes preparing recovery and sending real scoped native grant requests after validation; only the operator supplies approval, and grant approval remains separate from operator-only scheduler execution.

**Observed statement, not observed raw rejection:** [N8N_PROGRAM_BOARD.md](/home/johnclaw/N8N_PROGRAM_BOARD.md:145),10:59EDT, says Agent A's unpublish was classifier-denied and names `/home/johnclaw/n8n-agent-hardening/unpublish_n2_ungranted_20261009.sh` for the operator. That file contains16 N2 IDs plus restart; **do not run it for this nine-ID packet**. The raw rejection receipt and its exact classifier rationale are NOT_MEASURED here. It was Agent A's reported denial, not a root attempt. The board's16-workflow claim does not expand this packet or prove grant provenance for any other action.

## Exact operator-only n8n actions

First root performs read-only prechecks: actual CURRENT/process/build SHA, selected active/version hashes, complete unrelated workflow state hash, container identity/image/config, cron bytes/hash and four tagged lines, watchdog state, immutable receipt hashes and selected accepted host requests. Acquire exclusive runtime coordination; this is not authority. Rebind the reviewed packet to fresh observations. An already-inactive or changed selected ID requires recorded reconciliation before approving/executing, never a guessed replacement. Existing definitions and execution history stay saved; no import/delete/publish/`--all`.

After exact operator approval and fresh checks, **the operator**, through the n8n UI or pasted installed CLI commands, unpublishes only these IDs. CLI spelling is grounded in the installed2.43 source/help observation in [38-rollback-readiness](/home/johnclaw/tradeai-wt-runtime-n8n-host-recovery-20261008/docs/_evidence/runtime-convergence/20261009T004124Z/38-rollback-readiness.md:36); recheck the installed version before use. Execute individually and stop on any failure; this document has not executed them.

```bash
docker exec m8m-n8n n8n unpublish:workflow --id=722fac0e043ea5c4
docker exec m8m-n8n n8n unpublish:workflow --id=c0d4c7845e5c4fcc
docker exec m8m-n8n n8n unpublish:workflow --id=078e8fcbea0c5020
docker exec m8m-n8n n8n unpublish:workflow --id=21fd15d5f8a4c4da
docker exec m8m-n8n n8n unpublish:workflow --id=0a170db6744afd7f
docker exec m8m-n8n n8n unpublish:workflow --id=0d48d2951cdc0cd0
docker exec m8m-n8n n8n unpublish:workflow --id=19e0ed9711cfb320
docker exec m8m-n8n n8n unpublish:workflow --id=c7dc5a8273bf6f44
docker exec m8m-n8n n8n unpublish:workflow --id=e18d7849b4142927
```

The first four are N1live incident/snapshot/pilot/research; the next four are defective N2shadows; the last is duplicate weekly maturity. Preserve the active legacy maturity `40 6 * * 1` cron, four inactive N1 frequent shadows, inactive old maturity shadow, and every unrelated workflow's active/version state. Other N2 IDs in Agent A's16-ID script are outside this packet.

## Restart, drain and four operator-only restorations

1. Retain operator action receipts and read back all nine inactive states plus unchanged unrelated state. CLI DB changes require in-memory scheduler reload. Restart only the existing `m8m-n8n` container once under an exact fresh service approval, by the operator or an expressly permitted service executor. Root must verify its classifier/grant before any service invocation; refusal remains a stop. No image/compose/env/credential change, extra worker or new unit.
2. Read-only verify container health, same image/config, nine inactive states, unrelated states and watchdogs; correlate host ledger/RunReceipts with relevant accepted n8n requests. Require no selected `REQUESTED`/`RUNNING` host claims or executable queued accepted requests before cron restoration. DB `running` labels alone are insufficient. Wait for natural drain; no cancellation/replay/manual fire. Record an unknown or failed check and stop before restoring a competing writer.
3. The operator reviews a mutable operational registry **outside immutable CURRENT**, initialized to measured four-lane n8n ownership. Bind its root/path/hash, final helper SHA, backup/state/lock paths and the immutable receipt hashes from repo22. The final source's four cron-intent rows are not the rollback helper's starting operational registry. Before each helper call, independently prove exactly one matching retired tag, no active matching line, and byte equality between the tag's uncommented command and the immutable receipt `line_before`. **Any difference refuses application**: current helper merely warns and can restore different host text, so exit0 does not prove that precheck.

| Operator restoration lane | Immutable receipt basename | Exact cadence / retained lock |
|---|---|---|
| `n8n-incident-fanin` | `n8n-incident-fanin-20261009T020135Z-cutover.json` | `*/5 * * * *`; original safe_flock |
| `crontab-snapshot-for-health-agent` | `crontab-snapshot-for-health-agent-20261009T020135Z-cutover.json` | `*/20 * * * *`; original unlocked line, only after competing writer fully drained |
| `n8n-pilot-dispatch` | `n8n-pilot-dispatch-20261009T020145Z-cutover.json` | `*/15 * * * *`; original safe_flock |
| `n8n-research-intake-consumer` | `n8n-research-intake-consumer-20261009T020135Z-cutover.json` | `*/15 * * * *`; original safe_flock |

Receipts are under `/home/johnclaw/trade-ai-releases/persistent-state/data/runtime/n8n_cutover/`. Operator helper form is `<EXACT_REVIEWED_HELPER_PYTHON> <EXACT_REVIEWED_HELPER_PATH> rollback --lane <table-lane> --code-root <MUTABLE_OPERATIONAL_ROOT> --state-root <BOUND_STATE_ROOT> --receipt <table-receipt-full-path>`, then the same reviewed command with `--apply` once per lane. All placeholders must be filled, hashed and approved before paste. **The helper dry-run takes a lock and writes receipts; it is not a no-write precheck.** Its host receipt/backup writes must be included in the exact native consumption manifest; any additional required scope/use needs approval before execution. No invocation in this review.

4. The operator restores one exact line per lane and records each result. Root then remeasures lines/counts/registry/receipts: unrelated cron bytes and registry rows unchanged, original receipts unchanged, three existing locks retained, no double authority and source intent matches restored cron ownership. Do not assert an expected count as observed, replace the whole crontab, edit immutable releases or secretly re-enable an unsafe workflow.
5. Only after these operator-owned steps pass can root proceed with separately approved exact-source canonical deployment. Preserve `CIO_DEPLOY_FF_DEV_TREE=0` until real semantic browser acceptance, exact prior rollback binding and existing CURRENT-bound service allowlist. Successful recovery is not retrospective N1 shadow/canary acceptance.

## Bounded native budget and retained exclusions

Keep **cron30m / maximum13 scheduler actions: nine operator workflow retirements plus four operator per-line restorations**. Keep repo22's proposed config-write15 and service3 reviewed transactions only if the verified actual native command consumption fits them. Record the actor separately for each use; do not repurpose the nine workflow uses as agent permission, count a denied attempt as successful or hide extra dry-run/state writes. Push/release/maintree grants remain separate later stages; all grant IDs/reasons/uses are PENDING. Root may send genuine native requests within the user-authorized task after complete validation; root never supplies or simulates the approval reply. If operator execution or permitted delegation has no receipt, report recovery PENDING and stop promotion.

No blanket shadow disable, workflow DB rewrite, provider/model call or selection, bridge token, policy ratification, new writer, broker/order/stop/risk/2FA/send-authority change. MFA OFF remains the explicit operator exception. Ollama retirement remains a separate privileged keyboard-only action. Failure recovery preserves partial evidence and corrected inactive workflow state; no automatic reactivation of the unsafe nine.

PLATFORM_RUNTIME_SOURCE_ACCEPTANCE_BLOCKED
