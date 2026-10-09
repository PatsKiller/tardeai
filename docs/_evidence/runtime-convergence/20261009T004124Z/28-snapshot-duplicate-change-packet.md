# Snapshot duplicate scheduler correction — prepared, NOT APPLIED

Operator authorization: “merge, deployment, scheduler cutover push live send any grants fix what needs fixing”. AGENTS.md §9.3 says “Installing, editing or removing a scheduler entry is operator-only.” §23.2 applies this to n8n workflows. The native guard must record the operator's approval of this exact correction; authorization does not replace acceptance proof.

## Observed defect

At 2026-10-09 01:29Z, host `crontab -l` still has the ACTIVE `*/20 * * * *` snapshot command. It writes the persistent-state `data/runtime/crontab_snapshot.txt.tmp` and moves it onto `crontab_snapshot.txt`, without the executor lock. CURRENT's lane registry declares that cron as owner.

Actual n8n workflow `c0d4c7845e5c4fcc`, name `crontab-snapshot-for-health-agent`, is also active every 20 minutes in LIVE mode. Natural execution 740 at 01:20Z requested host run `n8n-wf-c0d4c7845e5c4fcc-740`, completed exit 0 on approved CURRENT d8c527aea977fd0136cfc302001117a8c2919e6e, and advanced the same output after cron had already written it. Its `/tmp/tradeai_crontab_snapshot.lock` is absent from the legacy command. Two independent live schedulers write the same temporary and final paths. Locks do not justify duplicate scheduling.

Evidence: `26-natural-runs-first.json` records n8n started/success trigger metadata and corresponding durable RunReceipt. `crontab -l` was re-run with read-only host permissions after the sandbox denied setgid access. Source-only registry intent is distinct from those observations.

## Exact correction

Unpublish ONLY the prematurely live n8n workflow `c0d4c7845e5c4fcc`, then restart ONLY container `m8m-n8n` so its in-memory scheduler removes that entry. Preserve the current image/container ID, compose configuration, environment, scoped relay credential, encryption key, payload retention and other workflow activation states. Legacy cron stays active and remains scheduler of record. Shadow workflow `5439cd4d82e1f305` stays active; its output is the separate shadow copy. Preserve the independent host n8n watchdog, recovery, backups and restore drill.

Installed Community 2.43.0 command source `/usr/local/lib/node_modules/n8n/dist/commands/unpublish/workflow.js` confirms `n8n unpublish:workflow --id=...` changes only the named workflow's active state and requires restart. This agrees with [official n8n CLI documentation](https://github.com/n8n-io/n8n-docs/blob/main/docs/deploy/host-n8n/configure-n8n/use-the-command-line.md). No direct SQL mutation or new owner/API credential is needed.

## Dry-run and boundaries

A dry-run helper must read-only verify: approved CURRENT unchanged; workflow ID/name currently active; all 12 workflow activation states; snapshot cron still active/unlocked; the existing container ID/image and running state; no in-flight retained execution. It writes only an evidence artifact and prints the exact command plan. Any mismatch blocks application.

Native scopes requested: `cron`, 30 minutes, 2 uses, for this one workflow unpublish and conditional rollback only; `service`, 30 minutes, 2 uses, for this one n8n container restart and conditional rollback only. No host crontab edit, new workflow, live canary, scheduler cutover, send or broker mutation is covered. No state-store data or credential is read or changed. Never unpublish all workflows.

Application consumes those approved scopes, uses the installed CLI, verifies DB active=false, restarts the exact existing container, then verifies /healthz HTTP 200, same image, seven remaining active workflow IDs, unchanged legacy cron and host relay/executor health. CLI output is captured privately and filtered to command outcome metadata. Unexpected errors or state changes block success.

## Recovery

If only restart/health fails, preserve the corrected inactive duplicate state, retry recovery of the same pinned container under the remaining service use, and keep legacy cron/host recovery operating. Restoring this NO_GO duplicate to live is an exceptional rollback requiring explicit re-evaluation; an error must never automatically revive conflicting ownership. The named workflow can be republished with the existing stored version only under a separately reviewed rollback decision; never activate all workflows. Other workflow states must match the before snapshot.

## Acceptance

Require two subsequent natural 20-minute shadow fires with green event metadata and matching CURRENT host receipts, the authoritative cron output advancing, and zero executions of the unpublished LIVE workflow after restart. No manual workflow firing. This resolves a duplicate by retaining existing ownership; it is not an n8n cutover or complete platform convergence.
