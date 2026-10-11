# CURRENT rollback (exact-main phase2)

Status:      ACTIVE
as_of:       2026-10-10
Authority:   READ_ONLY_ADVISORY

Do not run unless operator-authorized. Rollback moves CURRENT, restarts portfolio-server,
restarts the running bound units (the `TRADEAI_CURRENT_BOUND_UNITS` default in
`scripts/cio_phase2_exact_main_deploy.sh`: tradeai-health-agent.service, cio-governed-bridge.service,
tradeai-cio-telegram.service, tradeai-telegram-callback-poller.service,
tradeai-n8n-coordination-gateway.service, tradeai-n8n-run-relay.service,
tradeai-n8n-run-executor.service, tradeai-phone-status.service; a unit not installed or not running is
skipped), and rewrites the expected-release pin and ACTIVE_RELEASE. It also undoes the release-pin step
(`scripts/release_pin_daemons.py`): when the promote being rolled back is the one recorded in
`~/.local/state/cio-phase2-exact-main/release_pins/last_apply.json`, the drop-ins it archived are moved
back (sha256-checked) and its `90-release-pin.conf` files are archived. With no matching receipt, the pins
are rewritten to the rollback target instead. Broker-adjacent units are never touched. It does not
fast-forward the dev tree. A grant
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

## Release-pinned daemons (drop-ins) rollback

```bash
# DRY RUN: which user units are pinned to a release other than CURRENT (writes nothing)
bash scripts/cio_phase2_exact_main_deploy.sh pins

# Undo one pin apply by its receipt (moves archived drop-ins back, archives the managed file, daemon-reload).
# Refuses a unit whose 90-release-pin.conf changed since the apply ("drift") or whose original path is occupied.
python3 scripts/release_pin_daemons.py restore \
  --receipt ~/.local/state/cio-phase2-exact-main/release_pins/apply-<ts>.json

# Units reported "restart pending" keep their old code until restarted (operator decision for each):
systemctl --user restart <unit>
pid=$(systemctl --user show -p MainPID --value <unit>); readlink /proc/$pid/cwd
```

Archived drop-ins live under `~/.config/systemd/user/.release-pin-archive/<ts>/` with a `TRIPWIRE.README`;
`python3 scripts/release_pin_daemons.py tripwire` exits 3 if a live unit references that path.

## Executor v2 (opt-in) rollback

Executor v2 (#1598) runs only when the installed `tradeai-n8n-run-executor.service` sets
`TRADEAI_N8N_EXECUTOR_WORKERS` to 2 or more. A release rollback does not change that setting. To go back to
the v1 serial drain, an operator-authorized unit edit is needed:

```bash
# remove the Environment=TRADEAI_N8N_EXECUTOR_WORKERS=... line (or set it to 1) in
# ~/.config/systemd/user/tradeai-n8n-run-executor.service, then:
systemctl --user daemon-reload
systemctl --user restart tradeai-n8n-run-executor.service
# confirm: after the next run the file holds a RunReceipt@v1 (v2 writes ExecutorStatus@v1 there)
python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/trade-ai-releases/persistent-state/data/runtime/n8n_run_executor_last.json'))).get('schema'))"
```

The v1 drain leaves v2 RUNNING rows in place. A later v2 start reaps them once they are overdue, or once
they are stale and their owning executor pid is dead.
