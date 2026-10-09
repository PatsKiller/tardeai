# CURRENT rollback (exact-main phase2)

Status:      ACTIVE
as_of:       2026-10-09
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
