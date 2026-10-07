# Phase 1 install commands (operator), 2026-10-07

Every line below changes a scheduler, a unit, a secret, or a production surface, so each is an operator
action under a named grant. Nothing here has been run. Order matters.

## 0. Bitwarden SM keys (project trade-ai-prod) — operator creates, `render_env` delivers
- `TRADEAI_N8N_GATEWAY_HMAC_KEY` — 48 random bytes, e.g. `openssl rand -hex 32` (≥ 32 bytes required)
- `TRADEAI_N8N_GATEWAY_HMAC_KEY_PREVIOUS` — empty until the first rotation
- `N8N_ENCRYPTION_KEY_ESCROW` — copy of the lab's `N8N_ENCRYPTION_KEY` (escrow only; the lab keeps its own .env)
- `N8N_OWNER_PASSWORD` — move the value out of `/home/johnclaw/m8m-bakeoff-lab/.env` after MFA is on
- `PORTFOLIO_SERVER_BIND` is NOT a secret: it goes in a systemd drop-in (S1 proposal)
Then: `systemctl --user start tradeai-sm-render.service` and confirm the names appear in
`grep -oE '^TRADEAI_N8N_GATEWAY_HMAC_KEY' /run/user/1000/tradeai/env`.

## 1. Lab hardening (compose) — applies `proposals/docker-compose.n8n.hardened.yml`
Only after a fresh backup: `bash scripts/n8n_lab_backup.sh --apply` (done once 2026-10-07T14:40Z).
PG17 + non-superuser role need a NEW volume: dump → `docker compose -f … down` → new volume → up → restore
via `scripts/n8n_lab_restore_drill.sh` logic against the new container → verify 157 tables + 4 workflows →
`N8N_ENCRYPTION_KEY` unchanged. Operator decision: do the PG17 step now, or apply only items 1–4 of the
proposal (healthcheck, retention, webhook var, host alias) in place with `docker compose up -d`.

## 2. Units (service grant) — files already in `config/systemd/user/`
```
cp config/systemd/user/tradeai-n8n-lab-watchdog.{service,timer} ~/.config/systemd/user/
cp config/systemd/user/tradeai-n8n-coordination-gateway.service ~/.config/systemd/user/
# edit the gateway ExecStart wrapper args if needed: --port 18091 --expected-sha $(cat ~/trade-ai-releases/portfolio-server/CURRENT/GIT_SHA) --allow-lane incident-fanin
systemctl --user daemon-reload
systemctl --user enable --now tradeai-n8n-lab-watchdog.timer
systemctl --user enable --now tradeai-n8n-coordination-gateway.service
curl -s http://127.0.0.1:18091/healthz   # expect {"ok":true,"durable":true,"ledger":".../n8n_coordination_ledger.sqlite"}
```
Note: `--expected-sha` pins the gateway to one served SHA; promote changes the SHA, so the wrapper must read
`CURRENT/GIT_SHA` at start and the unit must be restarted after every promote (add it to the post-promote
restart list next to the desk bot).

## 3. Cron lines (cron grant) — append with `crontab -l > backup; (crontab -l; cat lines) | crontab -`
```
*/15 * * * * cd $PROJ && TRADEAI_STATE_ROOT=/home/johnclaw/trade-ai-releases/persistent-state $PY scripts/n8n_pilot_dispatch.py --apply >> /home/johnclaw/trade-ai-releases/persistent-state/logs/n8n_pilot_dispatch.log 2>&1
*/5 * * * *  cd $PROJ && TRADEAI_STATE_ROOT=/home/johnclaw/trade-ai-releases/persistent-state $PY scripts/n8n_incident_fanin.py --apply >> /home/johnclaw/trade-ai-releases/persistent-state/logs/n8n_incident_fanin.log 2>&1
30 3 * * *   cd $PROJ && bash scripts/n8n_lab_backup.sh --apply >> /home/johnclaw/trade-ai-releases/persistent-state/logs/n8n_lab_backup.log 2>&1
0 4 * * 0    cd $PROJ && bash scripts/n8n_lab_restore_drill.sh --apply >> /home/johnclaw/trade-ai-releases/persistent-state/logs/n8n_lab_restore_drill.log 2>&1
```
Both dispatch scripts read the gateway key from the environment: source the rendered env on the line
(`set -a; . /run/user/$(id -u)/tradeai/env; set +a;`) as the other SM-consuming cron lines do.
In the SAME PR as the crontab change, flip the four registry rows (`n8n-pilot-dispatch`, `n8n-incident-fanin`,
`n8n-lab-backup`, `n8n-lab-restore-drill`) to ACTIVE with `scheduler.kind=cron` and the expression above;
otherwise `check_lane_registry --state-drift` fails on the next CI run.

## 4. S1 / S2 (config-write + DB grants) — see `S1-portfolio-server-bind.md`, `S2-dof-bind-and-role.md`
```
mkdir -p ~/.config/systemd/user/portfolio-server.service.d
printf '[Service]\nEnvironment=PORTFOLIO_SERVER_BIND=127.0.0.1\n' > ~/.config/systemd/user/portfolio-server.service.d/30-bind-loopback.conf
systemctl --user daemon-reload && systemctl --user restart portfolio-server.service
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.50.16:7777/api/health   # expect connection refused
```
(Needs the served code to include the `PORTFOLIO_SERVER_BIND` change from this PR; the n8n monitor workflow
`n8n-monitor-trade-ai` will go red and must be repointed to the gateway healthz.)

## 5. n8n owner MFA — in the n8n UI (Settings → Personal → Two-factor); then rotate the owner password into SM.
