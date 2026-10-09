# N1 per-lane rollback and renewed acceptance packet

Status: SOURCE_ONLY / PROPOSED; NOT EXECUTED.
Owner: platform; operator approval governs application.
as_of: 2026-10-09T02:25:00Z.

Prepared by an independent read-only audit at 2026-10-09 02:25 UTC. **NOT EXECUTED.** This packet does not grant authority, consume native grants, deactivate workflows, restore cron, alter CURRENT, or send messages. Any application requires a fresh operator grant naming the exact workflows, existing container restart, per-lane cron edits, reviewed source registry, and expiry. Acquire the repository's exclusive deployment/production lease before runtime work; do not overlap another operator's promotion. Re-measure the identities and workflow states below at the grant boundary.

The task requires two natural shadow fires after all fixes, a successful lock-equivalent live canary while the old scheduler remains active, rollback proof, and registry consistency. The currently observed cutovers do not satisfy that strict contract. Subsequent successful production runs cannot establish that a missing pre-cutover canary occurred.

## Measured scope and priority

CURRENT and all four measured portfolio/gateway/relay/executor process roots are `4673f135f001b59f01a2b8fd938738542200d5f8` at 02:24 UTC. Cron has 437 active jobs, 1,047 raw lines, and four exact dated retirement tags. The n8n census at 02:17 UTC is 15 workflows, seven active and eight inactive. Its container restarted at 02:03:48 UTC. The independent host `tradeai-n8n-lab-watchdog.timer` remains enabled and active and is **outside this packet's mutation scope**. Backups, restore drills, reapers, process/DB watchdogs, broker/order/stop/risk/2FA authority and existing host senders are also outside its scope.

| Priority | Lane | Live workflow to unpublish | Existing shadow workflow | Exact cutover receipt | Restored cadence / existing lock |
|---|---|---|---|---|---|
| First | `n8n-incident-fanin` | `722fac0e043ea5c4` | `e511583d42831b8b` | `n8n-incident-fanin-20261009T020135Z-cutover.json` | `*/5 * * * *`; `safe_flock.sh /tmp/tradeai_n8n_incident_fanin.lock` |
| First | `crontab-snapshot-for-health-agent` | `c0d4c7845e5c4fcc` | `5439cd4d82e1f305` | `crontab-snapshot-for-health-agent-20261009T020135Z-cutover.json` | `*/20 * * * *`; **legacy line has no lock** |
| Next, if operator selects full N1 rollback | `n8n-pilot-dispatch` | `078e8fcbea0c5020` | `baddad5487f9c288` | `n8n-pilot-dispatch-20261009T020145Z-cutover.json` | `*/15 * * * *`; `safe_flock.sh /tmp/tradeai_n8n_pilot_dispatch.lock` |
| Next, if operator selects full N1 rollback | `n8n-research-intake-consumer` | `21fd15d5f8a4c4da` | `577f9dfaede632f3` | `n8n-research-intake-consumer-20261009T020135Z-cutover.json` | `*/15 * * * *`; `safe_flock.sh /tmp/tradeai_n8n_research_intake_consumer.lock` |

Receipts live under `/home/johnclaw/trade-ai-releases/persistent-state/data/runtime/n8n_cutover/`. Restore each receipt's exact `line_before`, retaining the already-added locks on the three Python lanes. Never restore a whole saved crontab. The snapshot receipt's original command writes the existing persistent-state `.tmp` then `mv`s it onto the final snapshot. Its restoration is safe only after its live n8n writer is unpublished, the container scheduler has reloaded, and all previously accepted snapshot runs have finished. A new shared lock is a separate proposed scheduler change, not part of exact restoration.

Incident's only current pre-cutover live n8n request at 02:00 ended `RUN_SKIPPED_LOCK`; zero successful pre-cutover canaries were measured. Snapshot's pre-cutover live n8n writer and unlocked cron shared the same `.tmp` and final paths. Pilot/research have a successful current 02:00 canary and original shared-lock equivalence, but strict final-fix chronology and per-lane rollback dry-run evidence remain incomplete. Three original immutable cutover receipts and the peer source registry contain corrupted cadence text. Preserve those receipts; correct source intent and append a superseding finding/correction artifact.

## Read-only preflight and rehearsal

Confirm CURRENT, exact process roots, n8n container ID/image, workflow version/active states, zero unrelated workflow changes, and the four tagged cron lines. Confirm the chosen mutable source worktree's registry rows match the applied n8n ownership and have valid cadences before calling rollback. **CURRENT's registry is still `kind: cron`; pointing rollback at CURRENT would refuse and editing its immutable config is prohibited.** The operator/coordinator must use a reviewed dedicated source worktree with the cutover rows, reconcile its intent, and ship the final registry through PR/CI/exact-main deployment.

Use an isolated fixture copy of the current crontab, selected immutable receipts, and reviewed registry to rehearse each rollback through the existing helper. Set `CRONTAB_CMD` to a fixture fake and `TRADEAI_STATE_ROOT` to the evidence fixture directory; do not connect the rehearsal to host crontab or production STATE_ROOT. Assert exactly one tagged line becomes active, other lines stay byte-identical, the registry scheduler returns to the receipt's `scheduler_before`, and refusal paths make no cron/config change.

The existing helper's default dry-run is **not strictly read-only**: `_cutover.py` takes its coordination lock and writes `CutoverReceipt@v1` plus `n8n_cutover_last.json`. Do not describe it as a no-write probe or run it on production state without the packet's authorization. No per-lane host rollback dry-run receipts were found in the measured host cutover directory. The real pilot rollback/re-cut at 02:01:45 is observed; it does not prove dry-run rehearsals for the other lanes.

## Minimal operator commands and order

Installed Community 2.43 supports per-workflow `unpublish:workflow --id` and `publish:workflow --id [--versionId]`. CLI activation changes require a restart to update the container's in-memory schedules. Do not use `--all`, direct DB updates, new n8n API credentials, workflow deletion, or a whole-crontab restore.

After fresh scoped grants and exclusive runtime ownership, unpublish the selected live workflows **before restoring any cron writer**, then restart only the existing `m8m-n8n` container once:

```bash
docker exec m8m-n8n n8n unpublish:workflow --id=722fac0e043ea5c4
docker exec m8m-n8n n8n unpublish:workflow --id=c0d4c7845e5c4fcc
# Only if the operator selected rollback of all four:
docker exec m8m-n8n n8n unpublish:workflow --id=078e8fcbea0c5020
docker exec m8m-n8n n8n unpublish:workflow --id=21fd15d5f8a4c4da
docker restart m8m-n8n
curl --fail --silent http://127.0.0.1:5678/healthz
```

Verify those exact workflow IDs are inactive, the image/container configuration and other active IDs are unchanged, relay/gateway/executor and the independent watchdog remain healthy, and no selected lane has a `REQUESTED`/`RUNNING` host-ledger row. Reading that SQLite ledger uses `mode=ro`; never instantiate its writer adapter to inspect it. If anything differs, stop before restoring cron. A queued live request can still execute after workflow deactivation; wait for measured drain instead of inventing a cancel operation.

For each selected lane, use the reviewed dedicated mutable registry and explicit immutable receipt. The following is the exact helper form for the incident priority lane. Substitute only the lane/receipt pairs in the table for the other selected lanes:

```bash
REVIEWED_WORKTREE=/home/johnclaw/tradeai-wt-runtime-n8n-host-recovery-20261008
TRADEAI_STATE_ROOT=/home/johnclaw/trade-ai-releases/persistent-state \
  "$REVIEWED_WORKTREE/.venv/bin/python" \
  "$REVIEWED_WORKTREE/scripts/pipelines/cutover/_cutover.py" rollback \
  --lane n8n-incident-fanin --code-root "$REVIEWED_WORKTREE" \
  --receipt /home/johnclaw/trade-ai-releases/persistent-state/data/runtime/n8n_cutover/n8n-incident-fanin-20261009T020135Z-cutover.json

# Only after reviewing the new dry-run receipt under the fresh scoped grant:
TRADEAI_STATE_ROOT=/home/johnclaw/trade-ai-releases/persistent-state \
  "$REVIEWED_WORKTREE/.venv/bin/python" \
  "$REVIEWED_WORKTREE/scripts/pipelines/cutover/_cutover.py" rollback \
  --lane n8n-incident-fanin --code-root "$REVIEWED_WORKTREE" \
  --receipt /home/johnclaw/trade-ai-releases/persistent-state/data/runtime/n8n_cutover/n8n-incident-fanin-20261009T020135Z-cutover.json \
  --apply
```

Re-read host crontab and verify only the chosen exact line changed. Capture the new rollback receipt and backup hash. Restoring two priority lanes changes the active-job count from the observed 437 to 439; restoring all four changes it to 441 **only if intervening edits are zero**. Re-measure counts, never assert those expected figures as observed. Match source registry intent to restored ownership in the same reviewed tranche; do not deploy a `kind:n8n` row over a restored active cron line.

## Renew shadow acceptance without premature live activation

Owner MFA is off and the n8n DB role retains superuser/create-role/create-DB/replication/bypass-RLS privileges. These observed policy preconditions remain blockers. MFA enrollment is operator-only; this packet performs no 2FA change. A separately reviewed least-privilege DB procedure must include backup/recovery verification. Do not infer either condition from a source file or weaken its gate.

After the security and source/host consistency prerequisites are resolved, publish **only** the selected existing shadow workflows, using their observed current versions, and restart the same container under a fresh scoped service grant:

```bash
docker exec m8m-n8n n8n publish:workflow --id=e511583d42831b8b
docker exec m8m-n8n n8n publish:workflow --id=5439cd4d82e1f305
# Add the pilot/research shadow IDs from the table only if selected.
docker restart m8m-n8n
```

Record an immutable `all_fixes_complete_at` timestamp **after** final source/host/workflow/lock repairs and successful restart/health proof. The prospective natural windows are the next two `*/5` incident fires and the next two `*/20` snapshot fires after that timestamp, plus two `*/15` fires for pilot/research if selected. Shadow live-output mtimes must remain unchanged; the snapshot shadow target is the separate `data/runtime/n8n_runs/shadow/crontab_snapshot.txt`. The authoritative legacy cron output should advance on its own schedule. If a shared lock causes a skipped shadow fire, that is lost work unless a declared contract says otherwise; it does not count toward the two required fires.

For every accepted fire, link workflow ID/execution ID, `isManual:false`, `mode:trigger`, green n8n event, the same `run_id` in durable RunRequested/RunReceipt, executor start/finish, `RUN_DONE`, exit 0, exact CURRENT SHA, no timeout/lock skip, dry-run output contract, and measured output/consumer behavior. The existing local n8n event log supplies metadata while success execution payload retention remains `none`. Never manually fire a workflow to manufacture natural acceptance. Weekly governance/maturity remain deferred; retain the independent host watchdog instead of handing its survival to n8n.

Snapshot requires a separate reviewed shared-lock addition on its cron command, maintaining the same path and atomic replace contract, **before** a simultaneous live canary. Before that grant and proof, keep its live workflow inactive. After two natural shadow proofs and a permitted successful live canary with the old scheduler active and the same lock, capture per-lane rollback dry-run proof and a fresh readiness verdict. No further cutover occurs for a strict `NO_GO` lane.

## Failure handling and evidence

If unpublish/restart fails, keep the intended live workflow inactive and recover the same pinned container under the remaining approved recovery use; do not automatically revive a conflicting writer. If rollback refuses or the cron/config write fails, inspect the new receipt, retain the new partial-state evidence, and stop. Preserve all unrelated cron lines and recovery services. Restore a single line from its named immutable receipt only under a separately reviewed corrective grant, never from a wholesale backup. If the subsequent source deployment fails, restore the prior exact release via the canonical release procedure while preserving the operator-approved scheduler ownership; then verify CURRENT, all affected process roots, API/build SHA, and schedule evidence again.

Primary evidence: [strict N1 matrix](38-runtime-strict-n1-matrix.json), [natural fires through 02:20](38-runtime-natural-runs-after-0220.json), [cutover/lock inspection](38-runtime-independent-inspection.json), [current host identities](38-runtime-post-0220-host-metadata.json), [current security metadata](38-runtime-security-metadata.json), [output-to-consumer observation](38-runtime-consumer-observation.json), and [02:20 snapshot hash proof](38-runtime-snapshot-after-0220.json). Installed CLI help was read with `docker exec m8m-n8n n8n publish:workflow --help`; no workflow was published by this audit.
