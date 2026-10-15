# Packet: take maturity-remeasure off the relay live list (config-write, NOT APPLIED)

Source: `~/n8n-maturity-verification/arch-review-20261014/CANARY_DOUBLE_EFFECT_AUDIT.md`, finding 1.
Branch `fix/canary-effect-keys-20261015`. Prepared by Agent A, 2026-10-15. Not applied: the operator runs it under a
config-write grant.

## Why

`maturity-remeasure` is on `TRADEAI_N8N_RELAY_LIVE_LANES` (`~/.config/tradeai/n8n-live-lanes.env`) while its cron
line is active:

    L1005  40 6 * * 1 ... flock -n /tmp/tradeai_maturity_remeasure.lock $PY scripts/maturity_remeasure.py --write ...

Only the registry's `dispatch.mode: dry_run` keeps n8n from running it live today. `--write` appends to
`maturity_scores.jsonl`, and the shared `flock -n` does not stop a sequential second run in the same slot
(audit §4). One registry flip to `live` would bring back a Monday 06:40 double append. Taking the lane off the
live list removes that latent path. Its dry runs are unaffected: a registry-live lane missing from the list is
dispatched as `dry_run` (`scripts/lib/n8n_due._relay_dispatch_mode`), and a `dry_run` lane needs no list entry.
Put it back only in the step that comments L1005 (a proper cutover), or once its effect key is armed.

## What changes

One line in one file. 7 lanes become 6:

    before: n8n-pilot-dispatch n8n-incident-fanin n8n-research-intake-consumer crontab-snapshot-for-health-agent maturity-remeasure research-insight-extractor heartbeat-watch
    after:  n8n-pilot-dispatch n8n-incident-fanin n8n-research-intake-consumer crontab-snapshot-for-health-agent research-insight-extractor heartbeat-watch

The file is an `EnvironmentFile` of two units, so the change takes effect only after both restart:
`tradeai-n8n-run-relay.service` and `tradeai-n8n-coordination-gateway.service` (drop-ins `30-live-lanes.conf`).
No crontab line, registry row, allowlist entry or n8n workflow changes. Nothing is sent.

## Steps (operator)

```bash
P=$HOME/trade-ai-releases/portfolio-server/CURRENT/docs/ops/packets/maturity-remeasure-relay-live-removal-20261015
# (or this branch's checkout until the PR is promoted)
bash "$P/00_preflight.sh"                 # read-only; expect PREFLIGHT OK
bash "$P/01_apply.sh"                     # dry run: prints before/after, writes nothing
APPLY=1 bash "$P/01_apply.sh"             # backup + atomic rewrite
APPLY=1 bash "$P/02_restart.sh"           # restart relay + gateway (pick a minute away from :00/:05 slots)
bash "$P/03_verify.sh"                    # expect VERIFY OK
```

Rollback: `APPLY=1 bash "$P/09_rollback.sh"` (restores the newest backup, restarts both units, re-verifies).

## Evidence to keep

The outputs of `00_preflight.sh` and `03_verify.sh`. The backup
`~/.config/tradeai/n8n-live-lanes.env.pre-maturity-remeasure-removal-<UTC>` stays in place (never delete).

## Not in this packet

- Commenting L1005 (crontab grant; that is the lane's cutover).
- Any registry change: `dispatch.mode` stays `dry_run`.
