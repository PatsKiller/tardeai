# CURRENT rollback (exact-main phase2)

Status:      ACTIVE
as_of:       2026-10-10 (n8n executor/gateway drop-in rollbacks); 2026-10-09 otherwise
Authority:   READ_ONLY_ADVISORY

Do not run unless operator-authorized. Rollback moves CURRENT, restarts portfolio-server,
restarts the running bound units (the `TRADEAI_CURRENT_BOUND_UNITS` default in
`scripts/cio_phase2_exact_main_deploy.sh`: tradeai-health-agent.service, cio-governed-bridge.service,
tradeai-cio-telegram.service, tradeai-telegram-callback-poller.service,
tradeai-n8n-coordination-gateway.service, tradeai-n8n-run-relay.service,
tradeai-n8n-run-executor.service, tradeai-phone-status.service; a unit not installed or not running is
skipped), and rewrites the expected-release pin and ACTIVE_RELEASE. It does not fast-forward the dev tree. A grant
whose reason only says "promote" does not authorize rollback; rollback does not consume
that grant.

```bash
# Status
bash scripts/cio_phase2_exact_main_deploy.sh status

# Rollback to PREV recorded in ~/.local/state/cio-phase2-exact-main/state.env
bash scripts/cio_phase2_exact_main_deploy.sh rollback

# Verify the symlink, the commit, health, and that the desk bot followed CURRENT
readlink -f /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
cat /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/SOURCE_COMMIT
curl -fsS http://localhost:7777/api/v2/health
pid=$(systemctl --user show -p MainPID --value tradeai-cio-telegram.service)
readlink -f /proc/$pid/cwd
```

## Executor v2 (opt-in) rollback

Executor v2 (#1598) runs only when the installed `tradeai-n8n-run-executor.service` sets
`TRADEAI_N8N_EXECUTOR_WORKERS` to 2 or more. **Live since 2026-10-10 13:07 ET: 3 workers, set by the drop-in
`~/.config/systemd/user/tradeai-n8n-run-executor.service.d/10-executor-v2.conf`** (service grant eebd4ca0a6b31bd2).
A release rollback does not change that setting. To go back to the v1 serial drain, an operator-authorized edit of
the drop-in is needed (`config-write` + `service`); never delete the drop-in:

```bash
sed -i 's/^Environment=TRADEAI_N8N_EXECUTOR_WORKERS=3$/Environment=TRADEAI_N8N_EXECUTOR_WORKERS=1/' \
  ~/.config/systemd/user/tradeai-n8n-run-executor.service.d/10-executor-v2.conf
systemctl --user daemon-reload
systemctl --user restart tradeai-n8n-run-executor.service
# confirm: after the next run the file holds a RunReceipt@v1 (v2 writes ExecutorStatus@v1 there)
python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/trade-ai-releases/persistent-state/data/runtime/n8n_run_executor_last.json'))).get('schema'))"
```

The v1 drain leaves v2 RUNNING rows in place. A later v2 start reaps them once they are overdue, or once
they are stale and their owning executor pid is dead.

## Gateway `n8n-workflow-error` lane rollback

Added 2026-10-10 16:27 ET by the drop-in
`~/.config/systemd/user/tradeai-n8n-coordination-gateway.service.d/20-workflow-error-lane.conf` (config-write grant
8c235faa82733127). To remove it (`config-write` + `service`), edit the drop-in value back to
`TRADEAI_N8N_GATEWAY_EXTRA_LANES=incident-fanin research-intake` (never delete the file), then
`systemctl --user daemon-reload && systemctl --user restart tradeai-n8n-coordination-gateway.service` and check
`curl -s http://127.0.0.1:18091/healthz`. Relay `POST /event` then answers `unknown_lane`. Every other n8n rollback:
`docs/implementation/n8n-maturity/N8N_ONBOARDING_STANDARD.md` §11.
