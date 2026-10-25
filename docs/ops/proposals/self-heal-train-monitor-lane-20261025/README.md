# Self-heal train monitor: lane registration proposal (2026-10-25)

Code: PR #2129 (`scripts/self_heal_train_monitor.py`, `docs/ops/SELF_HEAL_TRAIN_FIXER.md`). This folder and its PR
add the host units, the fix-log store registrations and the lane rows. Nothing is installed by merging.

Operator steps, in order:

1. Merge PR #2129, and release it, so that `CURRENT` contains the monitor.
2. Merge `registry_rows.json` into `config/lane_registry.json`, then re-pin
   `docs/ops/packets/disk-standing-apply-20261024`. The registry is sha-pinned. It is currently claimed by the
   watchdog-activation PR. When the row exists, the cron outage watchdog measures the heartbeat `ok_at` every 5
   minutes.
3. Install the timer, which needs an operator scheduler grant:
   `systemctl --user link ~/trade-ai-releases/portfolio-server/CURRENT/config/systemd/user/tradeai-self-heal-train-monitor.{service,timer}`,
   then `systemctl --user enable --now tradeai-self-heal-train-monitor.timer`. Flip the row to ACTIVE. The monitor
   runs SHADOW until AGENTS.md 20.4.0 is ACTIVE with section 28.14 ACTIVE.
4. Arm the fixer. Install `tradeai-self-heal-fixer.timer` the same way, and issue
   `bin/guard grant git-push --reason 'self-heal-fixer ...'`. Both are operator acts.

Dry run, which writes nothing:
`.venv/bin/python scripts/self_heal_train_monitor.py`

Kill switch: `touch ~/trade-ai-releases/persistent-state/data/self_heal/MONITOR_DISABLED`.
