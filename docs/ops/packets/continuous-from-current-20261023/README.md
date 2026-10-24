# WP-27: continuous scanner from CURRENT operator packet

Status: DRAFT — locally tested operator packet; no system configuration applied
as_of: 2026-10-24T02:43:06Z
Measured at: origin/main `fe826d2ecdb59a19bd7c510c8923c7b743f06eee`; worker `codex-wp27-20261023`

This packet changes only the system service's code root when the operator applies it. It preserves `/usr/bin/flock -n -E 0 /run/lock/tradeai-continuous.lock`, the service identity and every unrelated unit setting. `/usr/bin/env PROJECT_ROOT=.../CURRENT` prevents an inherited `PROJECT_ROOT` from silently returning the launcher to the canonical checkout. It never changes a timer, user unit, cron entry, credential, daemon source or broker setting.

The worker could read the base unit but not its protected `singleton.conf`; that denial was not retried through another path. An operator preview must prove the exact effective launch command and hash the actual fragment/drop-ins. Unknown commands, changed singleton arguments, unresolved files or unexpected configuration stop before installation. The expected old command is the independently documented flock form, **not** a claim that the protected file was read. A refusal means review/rebuild this packet; do not weaken it to force application.

## Preview and apply

Use the operator's terminal and sudo. First compare `SHA256SUMS`'s hash with the delivery report, then verify its contents. These commands need no placeholders:

```bash
wp27_packet=/home/johnclaw/wt-codex-wp27-20261023/docs/ops/packets/continuous-from-current-20261023
cd "$wp27_packet"
sha256sum SHA256SUMS
sha256sum -c SHA256SUMS
wp27_preview=$(sudo bash "$wp27_packet/install.sh" --preview)
sudo cat "$wp27_preview"
sudo cat "$(dirname "$wp27_preview")/registry-proposal.json"
```

Preview writes only a private root-owned receipt under `/var/lib/tradeai/operator-packets/continuous-from-current-20261023/`; it does not change systemd. It collects a narrow property allowlist, hashes unit source files, and verifies CURRENT's BUILD_SHA, launcher and persistent `logs`, `data/runtime`, `data/cio` targets. It never prints `Environment`, reads a credential file or makes a live API call.

After reviewing that receipt, choose one apply command. Both require the TTY phrase `INSTALL-CONTINUOUS-CURRENT`. The preview expires after fifteen minutes and is invalidated by any bound unit/payload or CURRENT change.

```bash
# Configure for the next existing natural start; does not start/restart the scanner.
wp27_install=$(sudo bash "$wp27_packet/install.sh" --apply --approved-preview "$wp27_preview")
sudo cat "$wp27_install"
```

Or, when the operator intends an immediate scanner restart outside the guarded window:

```bash
wp27_install=$(sudo bash "$wp27_packet/install.sh" --apply --approved-preview "$wp27_preview" --restart)
sudo cat "$wp27_install"
sudo bash "$wp27_packet/check.sh"
```

The installed drop-in is `/etc/systemd/system/tradeai-continuous.service.d/zzzz-wp27-current.conf`. The root adapter performs the equivalents of `sudo systemctl daemon-reload` and, only with `--restart`, `sudo systemctl restart tradeai-continuous.service`. It refuses an existing managed drop-in with different bytes. It preserves backups and recovery receipts, and archives instead of deleting. No automatic rollback or whole-unit replacement occurs.

The conservative guard refuses **every weekday** from 04:00 inclusive until 16:15 exclusive in America/New_York, including market holidays. There is no environment/clock override. It checks again after confirmation and before each configuration/restart mutation. DST is handled by `zoneinfo`. A boundary crossed mid-operation leaves the durable recovery receipt for the operator; it does not perform the next mutation.

## Proof and recovery

`CONFIGURED_PENDING_RESTART_OR_NATURAL_FIRE` proves configuration only. `RUNNING_FROM_VERIFIED_CURRENT` also requires active service state, stable MainPID/start time, and `/proc/PID/cwd` equal to CURRENT's physical verified release directory. The checker retries for at most twenty seconds. A CURRENT change, overriding drop-in, inactive service, lock-only exit, PID race or wrong cwd cannot produce a runtime pass. Even a runtime pass is not scanner/business-output acceptance; correlate the next scan run and consumer separately.

After a failed apply, stderr prints `RECOVERY_RECEIPT=<actual path>` immediately after the managed file is installed. `installed-before-reload.json` and `failed.json` are also rollback inputs. No failed action is automatically retried.

```bash
sudo bash "$wp27_packet/rollback.sh" --preview --receipt "$wp27_install"
sudo bash "$wp27_packet/rollback.sh" --apply --receipt "$wp27_install"
# Only if the operator also intends to restart the restored unit:
sudo bash "$wp27_packet/rollback.sh" --preview --receipt "$wp27_install" --restart
sudo bash "$wp27_packet/rollback.sh" --apply --receipt "$wp27_install" --restart
```

Rollback needs `ROLLBACK-CONTINUOUS-CURRENT`, checks the exact installed digest and any prior backup, archives this packet's drop-in, and restores only its prior version if one existed. It never removes or restores the protected singleton drop-in. A changed managed file or repeated rollback stops for inspection. The same time guard applies.

## Registry and later releases

The operative registry currently has one `tradeai-continuous` row marked PAUSED, with historical user-manager evidence and no explicit system scope. The preview generates a **review-only** `tradeai-continuous-system` row with system scope. It records ACTIVE only if the operator actually observed the system timer both enabled and active; otherwise PAUSED. Preserve the existing row while reconciling user/system scope in a separate normal registry PR; do not infer a timer state from the worker's partial unit read. The packet neither applies the proposed row nor enables scheduling.

`restart_root_frozen_units` in `scripts/cio_phase2_exact_main_deploy.sh` restarts **user** units only, and its default list excludes this scanner. Adding this system unit to `TRADEAI_CURRENT_BOUND_UNITS` would use the wrong manager. This packet does not change the deployer. After a later promote, the running scanner remains pinned to its old release until the existing next natural start, or an operator uses a fresh preview/apply with `--restart` outside the guard. The checker exposes stale-root drift. The 04:00 natural start is expected configuration behavior, still pending observed proof.

Paste back the safe preview, installation receipt and PID proof, then the first scan run identity/output/consumer evidence. Never paste credential values or environment contents.
