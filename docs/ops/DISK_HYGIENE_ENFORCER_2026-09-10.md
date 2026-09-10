# Disk hygiene enforcer (2026-09-10)

## Why

Host hit **98% disk** (~11G free). Primary cause: **hundreds** of
`~/trade-ai-releases/portfolio-server/*-main-exact-*` trees (~178G) plus uncapped
historical dumps under `~/backups` / `~/ops-backups`. Weekly `db_retention` was
running but did **not** cover `content_embeddings` (~10GB) and does not reclaim
filesystem space from old releases.

## Tools

| Piece | Role |
|---|---|
| `config/disk_hygiene_policy.yaml` | keep_n=10 releases; stale backup age caps |
| `scripts/disk_hygiene_enforcer.py` | `--dry-run` / `--apply` / `--status` |
| `linux_launchers/systemd/tradeai-disk-hygiene-enforcer.{service,timer}` | daily 04:15 apply |
| `scripts/db_retention.py` | now includes `content_embeddings` 180d |
| `scripts/hermes_score_history_retention.py` | fixed `%%` → `MOD(...)` SQL bug |
| `scripts/backup_enforcer.py` | unchanged hard-cap for `~/db_backups` max 1 |

## Install (user systemd)

```bash
cp linux_launchers/systemd/tradeai-disk-hygiene-enforcer.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tradeai-disk-hygiene-enforcer.timer
systemctl --user start tradeai-disk-hygiene-enforcer.service   # optional first apply
```

## Safety

- Never deletes `CURRENT` / `EXPECTED_RELEASE` targets
- Never deletes a release that is a live process cwd
- Never touches `~/db_backups` (backup_enforcer owns that cap)
- `--apply` required to mutate; timer runs `--apply`

## Operator first run

```bash
.venv/bin/python scripts/disk_hygiene_enforcer.py --status
.venv/bin/python scripts/disk_hygiene_enforcer.py --dry-run
.venv/bin/python scripts/disk_hygiene_enforcer.py --apply
df -h /
```
