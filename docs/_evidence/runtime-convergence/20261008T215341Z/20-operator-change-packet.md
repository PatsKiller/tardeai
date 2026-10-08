# Operator-only runtime packet — prepared, NOT APPLIED

Read `AGENTS.md` §9.3: “Installing, editing or removing a scheduler entry is operator-only. Propose.” §17 and §22 require deployment authorization tied to exact SHA. This task explicitly forbids deployment/cutover without a separate grant. Source commits and PR approval do not activate any of the commands below. Re-measure CURRENT, service PIDs, file hashes and container digest at grant time. Grants must name exact scope, host, SHA and expiry; separate grants for units, cron, compose/security and deployment. No broker/2FA/send/risk-policy authority is included.

## A. Missing n8n unit definitions and old execution roots — P1

Observed relay/executor have LoadState=not-found and point to retained older code while installed symlinks point to a release removed by retention. Gateway is CURRENT. Source deploy now includes all three processes and fails if restart/root verification fails. Source relay/executor unit comments prescribe stable regular files.

Proposed unit-only grant, after the approved exact-main release exists: validate its `GIT_SHA` and both unit contents; archive existing symlink paths with `cp -a` in a private operator recovery directory; replace just `~/.config/systemd/user/tradeai-n8n-run-relay.service` and `tradeai-n8n-run-executor.service` with regular copies of the approved release's corresponding `config/systemd/user/` files, mode 0644; `systemctl --user daemon-reload`; `systemctl --user restart tradeai-n8n-run-relay.service tradeai-n8n-run-executor.service`. Verify each `LoadState=loaded`, nonempty FragmentPath, Restart=on-failure, configured cgroup bounds, MainPID cwd exact approved release and loopback/bridge binds. Verify gateway independently. No workflow/cron changes in this grant.

Concrete reviewed command structure, variables deliberately supplied by the operator's grant rather than inferred:

```bash
# Operator runs only after approval. Validate approved_release SHA before this block.
# approved_release must be the immutable deployed main release, not this worktree.
for unit in tradeai-n8n-run-relay.service tradeai-n8n-run-executor.service; do
  cp -a "$HOME/.config/systemd/user/$unit" "$approved_recovery_dir/$unit"
  unlink "$HOME/.config/systemd/user/$unit" # only if it is the measured dangling symlink
  install -m 0644 "$approved_release/config/systemd/user/$unit" "$HOME/.config/systemd/user/$unit"
done
systemctl --user daemon-reload
systemctl --user restart tradeai-n8n-run-relay.service tradeai-n8n-run-executor.service
systemctl --user show tradeai-n8n-run-relay.service tradeai-n8n-run-executor.service \
  --property=LoadState,FragmentPath,ActiveState,MainPID,Restart,MemoryMax,CPUQuotaPerSecUSec
```

Rollback must restore a valid previously pinned release's regular unit contents and executor root, reload/restart and verify receipts. Restoring a dangling symlink is not recovery. Record queued run IDs before restart; verify no double claim/side effect. Do not dump Environment values. Exact deployment grant remains separate.

## B. Ollama retirement mismatch — P1

Operator intent is RETIRED; measured `ollama.service` is enabled/running. First classify residual embedding consumers and choose their retired/paused/replacement states. Proposed explicit system-service grant: `sudo systemctl disable --now ollama.service`; verify `systemctl show ollama.service --property=ActiveState,UnitFileState,MainPID`; verify no Ollama listener/consumer retry storm. Do not auto-enable during rollback: retirement remains authoritative, and recovery/replacement needs an explicit operator decision. No chat model or embedding key is moved to n8n.

## C. n8n security/recovery — P1/P2

Owner MFA=false and n8n DB role is superuser. The owner must enable MFA and escrow recovery codes manually; this agent does not mutate 2FA. Preserve the existing encryption key; verify an operator-managed escrow/recovery procedure without printing or rotating it. Backup dump alone cannot recover encrypted credentials without that key.

Use an isolated Postgres 17 target/volume and a non-superuser application role; dump from current 16, restore privately, correct application object ownership/grants, validate workflow metadata/credentials decryptability, read-only security audit and relay auth. Do not grant CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS. Prove rollback to untouched source volume and container digest, then request a separate compose cutover grant. Never edit the existing role blindly during active executions.

Current UI is loopback-only. Current TCP samples reach bridge relay 18092 and fail on sampled TradeAI/DOF/DB/gateway/Ollama ports. Firewall rule inspection is BLOCKED by sudo authorization, so request read-only privileged rules first. Review exact current Docker network/subnet/rule IDs before a scoped firewall grant; allow n8n subnet only relay host ingress plus its own DB network requirement. Rollback only the rules installed by that packet, never a global firewall reset.

Set `N8N_PUBLIC_API_DISABLED=true` in the measured compose service if no operator consumer requires it (0 API keys observed, audit says enabled). Preserve loopback publishing, environment blocking, node excludes and disabled community packages. Add an HTTP healthcheck using the version-supported health endpoint; independently preserve watchdog/backup/recovery paths. Success payload retention remains none; propose minimal status+execution-id acceptance observations instead of saving payloads. Keep errors bounded and prune 168h. Set explicit log/metrics/runner settings only after reviewing actual requirements.

Nightly backup and weekly restore drill have observed receipts. Add a read-only security-audit schedule only under a scheduler grant with a lane row, bounded timeout, redacted artifact, consumer and failure receipt. Do not enable Redis/queue mode: measured load provides no demonstrated throughput need.

## D. Scheduler/registry remediation — P1/P2

395 observed entries are unmatched by the source registry's exact mapping. This count includes wrappers/stages and enabled/disabled OpenClaw/workflows; it is not 395 distinct business processes. Review `13-registry-proof-gaps.json` and exact observations. Resolve owners, domain, consumer, receipts, output freshness and allowed exceptions before installing rows or schedules. Old n8n monitor intent ACTIVE conflicts with observed workflow inactive; explicit NO_SIGNAL reason is source-only, no activation is proposed.

For the quote-lock same-minute collision, obtain distinct process/consumer contracts before selecting one scheduler; for runtime/cadence mismatches, derive SLA and exact proposed expression from baseline. Submit one per-line packet with before/after fires, receipts, effective completion target, registry change and exact rollback. Retain independent financial/safety/watchdog/reaper lanes.

## E. N1 acceptance and cutover — NO_GO

After exact-main approved deployment and stable unit recovery, require two natural shadow fires per lane after all fixes. Record n8n execution state/id, accepted unique run_id, durable REQUESTED/claim/DONE exit0, original lock, before/after dry-run output semantics, correct SHA, no traceback/dropped request/unexpected skip. Keep legacy schedule during live canary and prove output/rollback/schedule fidelity. Weekly manual canary may be labelled MANUAL_CANARY only if the policy permits it; it never satisfies a NATURAL shadow requirement. No manual firing was performed here. Current lane matrix is uniformly NO_GO. N2 waits for N1 stability.
