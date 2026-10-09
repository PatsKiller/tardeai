# Authorized rollout packet — prepared, host changes NOT APPLIED

Operator steering: “merge, deployment, scheduler cutover push live send any grants fix what needs fixing”. This authorizes rollout preparation and requests; the guard still records the operator's own approvals. Broker/order/stop/risk/2FA authority is unchanged. Sender/provider/model authority stays on the host. No policy ratification is inferred.

## Exact identities and merge

Repository PatsKiller/tardeai. PR #1539 head `5f4d610db6451f76bc1b39fe7ed3e8aa9d299779`; all eight PR CI jobs passed. Operator approved the narrow Git request `e28bd08674d23631` through the native Telegram button. The one use was consumed, PR marked ready, and merge verified at `2026-10-09T00:41:59Z`: **`d8c527aea977fd0136cfc302001117a8c2919e6e`**. No direct-to-main push or force push.

Deploy source: `/home/johnclaw/tradeai-wt-runtime-n8n-exact-deploy-20261008`, detached at that exact merge SHA. Rollback CURRENT: `/home/johnclaw/trade-ai-releases/portfolio-server/eec946b2c-main-exact-phase2-20261008-165420`, SHA `eec946b2cebaa1378dab285c506c789f6dff1fb4`. The 00:44:41Z read-only baseline still reports that CURRENT. Exact merge-SHA main CI must pass before promotion; no outage/emergency override is requested.

## Reviewed runtime correction

Read-only unit metadata confirms `tradeai-n8n-run-relay.service` and `tradeai-n8n-run-executor.service` active with LoadState=not-found, empty FragmentPath and Restart=no. Each has two dangling symlinks: the unit path and `default.target.wants/<unit>`, all pointing into removed `72b0ce6be-main-exact-phase2-20261008-120818`.

Archive those four links in the bounded recovery directory. Replace only the two top-level links with regular copies of the exact approved release's `config/systemd/user/<unit>`. Repoint only the two existing wanted links to their stable regular units (`systemctl --user enable --force` for these two names). No new process or scheduler is introduced. Source runtime policy remains Restart=always, relay MemoryMax=128M/CPUQuota=10%, executor MemoryMax=1G. EnvironmentFile contents are not read, printed, copied or altered.

## Minimum native grants

1. `release-write`, 30 minutes, 3 uses: canonical prepare/promote and conditional rollback of merge SHA d8c527aea977fd0136cfc302001117a8c2919e6e, PR #1539; prior release above. No other release or state/broker authority.
2. `config-write`, 30 minutes, 2 uses: archive/replace just those four measured n8n unit/wants links and install exact approved unit files. No cron/workflow, secret file or notification flag changes.
3. `service`, 30 minutes, 3 uses: reload/repair those two units; canonical portfolio-server promotion and CURRENT rebind of the existing default units (tradeai-health-agent, cio-governed-bridge, tradeai-cio-telegram, tradeai-telegram-callback-poller, tradeai-n8n-coordination-gateway, tradeai-n8n-run-relay, tradeai-n8n-run-executor); conditional rollback/restart of the same set. No arbitrary services or broker processes.
4. `maintree`, 30 minutes, 1 use: only the canonical deployment helper's clean fast-forward of `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` to that same merge SHA; refuse dirty/divergent copies. No history rewrite or feature edits in primary.

Each reason must name this exact SHA/PR and intended scope. Approval of one scope does not substitute for another. Native requests grant nothing until the operator approves. No sudo grant is requested through Telegram: remote sudo is explicitly forbidden by the guard; retired Ollama system-service stop and privileged firewall inspection remain keyboard/operator actions until authorized by that native route.

## Execution and acceptance

After approved grants, use canonical `scripts/cio_phase2_exact_main_deploy.sh prepare`, verify release GIT_SHA/SOURCE_COMMIT/BUILD_SHA, persistent-state mappings and frontend full build. Archive and repair the four exact links, reload and verify loaded unit definitions; do not restart them on a mixed release. Promote through the canonical script only when exact merge-SHA main CI is green. Defer its optional primary fast-forward with `CIO_DEPLOY_FF_DEV_TREE=0` until all semantic checks pass; then invoke the same `scripts/lib/ff_dev_tree.sh` helper under the maintree grant and verify exact SHA/clean state. This changes ordering only: final success still requires the primary fast-forward. Any failed promote/browser/API/root acceptance before that point leaves primary untouched and rolls CURRENT/services back. Capture each command's specific exit status.

The rollout caller must treat ANY promote or semantic acceptance failure as failure: if CURRENT moved, immediately call canonical rollback to the captured prior release, retain stable regular unit definitions and rebind the same existing processes, then verify health/roots and record a failed receipt. The canonical script's own HTTP rollback is supplemented by this outer check for later root/unit/browser/projection failures. Never claim success merely because CURRENT moved or services restarted.

Required acceptance: exact CURRENT/process/API/Command Center source SHA, built_at, health; all n8n gateway/relay/executor processes resolve approved CURRENT; stable enabled unit files and cgroup/restart policy; read-only SchedulerOperations API agrees with read-only host observations; LIVE Playwright uses actual API with no interception, no console errors/endless loader/raw JSON/fake zeros/stale-current labels, working drilldown and 390px overflow. Browser and API checks do not fire lanes or send notifications.

## Scheduler/live-send bounds

Cutover remains conditional on two NATURAL SHADOW fires after all fixes, valid live canary with original legacy scheduler active, same lock, output and rollback proof. This authorization is not fabricated run proof. Weekly/monthly NO_GO lanes remain on existing ownership while evidence is incomplete; N2 waits for N1. Live send is being clarified as an existing host-governed advisory notification scope; no new n8n sender/broker path or unbounded test messages.

## Cleanup

Retain redacted grant/use/revocation, merge, main CI, prepare/install/promote/acceptance/rollback receipts and refreshed census in this evidence directory. Revoke unused scoped grants at completion/failure. No secret values in artifacts.
