# Self-heal train monitor: lane registration (2026-10-25)

Code: PR #2129 (`scripts/self_heal_train_monitor.py`, `docs/ops/SELF_HEAL_TRAIN_FIXER.md`). This folder and PR #2131
add the host units, the fix-log store registrations and the lane rows. Nothing here needs an operator act
(coordinator relay of the operator, 2026-10-25: no operator acts).

How each piece lands:

1. **Arming.** AGENTS.md 21.0.0 §28.14 (PR #2128) becoming ACTIVE arms both lanes. There is no guard grant. Until
   then the monitor runs SHADOW and the fixer is "not armed".
2. **Timers.** The release installs them. The groups `self-heal-train-monitor` and `self-heal-fixer` in
   `config/staged_user_units.json` (follow-up to PR #2134) are installed by `scripts/install_staged_units.py` at
   `cio_phase2_exact_main_deploy.sh` promote. That step runs a `--dry-run` first, archives replaced copies, runs
   `enable --now`, and reads back is-active and the heartbeat.
3. **Lane rows.** Once PR #2134 lands (it re-pins the disk packet), a follow-up PR merges `registry_rows.json` into
   `config/lane_registry.json` and re-pins `docs/ops/packets/disk-standing-apply-20261024`. The cron outage watchdog
   then measures the monitor's heartbeat `ok_at` every 5 minutes.

Dry run, which writes nothing:
`.venv/bin/python scripts/self_heal_train_monitor.py`

Kill switches:
- `~/trade-ai-releases/persistent-state/data/self_heal/MONITOR_DISABLED` stops both lanes.
- `~/trade-ai-releases/persistent-state/data/self_heal/FIXER_DISABLED` stops the fixer only.
