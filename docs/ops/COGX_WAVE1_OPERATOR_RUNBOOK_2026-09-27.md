# COGX Wave 1 — operator runbook: the commands only you can run

```
Status:      ACTIVE
as_of:       2026-09-27T20:45:00-04:00
Measured at: origin/main cbf603526; PR #1305 (branch wt/cogx-w1-t1-20260927) not merged; served 8f2a178d5-main-exact-phase2-20260927-171004
Authority:   operator-only actions (AGENTS.md §17, §22). Every command below is reversible and says how.
Package:     docs/architecture/cognitive_transformation_20260927/; approval pkg-20260927-cogx-w1-d9e1 (all 14 items)
```

Run in this order. Steps 1–2 are safe before the merge; 3–7 need the merged SHA on CURRENT. Nothing here touches a broker.
`$PY` is the crontab's interpreter: `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python`.

## 1. Rotate the plaintext database credentials (S-1)

`~/.config/tradeai/agent-operator.env` carries three DSNs in plaintext: `AGENT_RUNTIME_SOURCE_DSN` (production `trade_ai_shadow_ro`),
`AGENT_RUNTIME_READ_DSN` and `AGENT_RUNTIME_DISPATCH_DSN` (lab roles, rendered from Bitwarden SM by `tradeai-sm-render.timer` every 4 h).

```bash
# 1a — production read-only role (script backs the env file up, generates the password, never prints it)
sudo -v && bash ~/ops-rotation/rotate_trade_ai_shadow_ro.sh

# 1b — lab roles: change the two secrets in Bitwarden SM first (SHADOW_DSN, SHADOW_READER_DSN), then
systemctl --user start tradeai-sm-render.service && systemctl --user status tradeai-sm-render.service --no-pager | tail -3
# then set the same passwords on the lab cluster (superuser johnclaw via the socket; paste each password when prompted):
psql -h ~/tradeai-lab/sock -p 5433 -d postgres -c "\password agentic_runtime_reader"
psql -h ~/tradeai-lab/sock -p 5433 -d postgres -c "\password agentic_runtime_shadow_rw"

# verify: crons that source the env still connect (read-only probe)
$PY -c "import os,psycopg2;[psycopg2.connect(os.environ[k]).close() or print(k,'ok') for k in ('AGENT_RUNTIME_SOURCE_DSN','AGENT_RUNTIME_READ_DSN','AGENT_RUNTIME_DISPATCH_DSN')]"
```
Rollback: the timestamped `.bak-…` copy of the env file; previous secret version in Bitwarden SM.

## 2. Production Postgres: roles, schema, grants (S-2, I-1, S-3)

```bash
WT=/home/johnclaw/tradeai-wt-cogx-w1-20260927   # after merge use: /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
sudo -u postgres psql -d trade_ai -v ON_ERROR_STOP=1 \
  -c "CREATE ROLE intelligence_reader NOLOGIN;" \
  -c "CREATE ROLE intelligence_writer NOLOGIN;"
sudo -u postgres psql -d trade_ai -v ON_ERROR_STOP=1 -f $WT/migrations/2026_09_27_intelligence_v1.sql
sudo -u postgres psql -d trade_ai -v ON_ERROR_STOP=1 \
  -c "GRANT USAGE ON SCHEMA intelligence TO intelligence_reader, intelligence_writer;" \
  -c "GRANT SELECT ON ALL TABLES IN SCHEMA intelligence TO intelligence_reader;" \
  -c "GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA intelligence TO intelligence_writer;" \
  -c "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA intelligence TO intelligence_writer;" \
  -c "ALTER DEFAULT PRIVILEGES IN SCHEMA intelligence GRANT SELECT ON TABLES TO intelligence_reader;" \
  -c "ALTER DEFAULT PRIVILEGES IN SCHEMA intelligence GRANT SELECT, INSERT, UPDATE ON TABLES TO intelligence_writer;" \
  -c "GRANT intelligence_reader TO trade_ai;" \
  -c "GRANT intelligence_writer TO trade_ai;"
# verify: 11 tables, 7 with row-level security forced, vector column present
sudo -u postgres psql -d trade_ai -Atc "select count(*) from pg_tables where schemaname='intelligence'"
sudo -u postgres psql -d trade_ai -Atc "select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='intelligence' and c.relforcerowsecurity"
sudo -u postgres psql -d trade_ai -Atc "select exists(select 1 from information_schema.columns where table_schema='intelligence' and table_name='embedding' and column_name='vec')"
```
Expected: `11`, `7`, `t`. Rollback (safe): `sudo -u postgres psql -d trade_ai -f $WT/migrations/2026_09_27_intelligence_v1.down.sql`.
Full revert is your reviewed `DROP SCHEMA intelligence CASCADE` — never automatic.

## 3. Merge and deploy PR #1305

```bash
# review, then merge on GitHub (0 required reviews today; the merge is yours)
gh pr view 1305 --json mergeStateStatus,statusCheckRollup -q '{state:.mergeStateStatus, checks:[.statusCheckRollup[]|{name:.name,c:.conclusion}]}'
gh pr merge 1305 --merge
# deploy the exact merged SHA (release-write grant must name it — see step 4)
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && git fetch origin && SHA=$(git rev-parse origin/main) && echo $SHA
bash scripts/cio_phase2_exact_main_deploy.sh prepare && bash scripts/cio_phase2_exact_main_deploy.sh promote $SHA
readlink /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT   # must start with ${SHA:0:9}
systemctl --user restart tradeai-cio-telegram.service               # desk code changed (callback handler)
```

## 4. Guard grants for this package (manual — automatic minting was refused by the classifier)

The guard store holds one grant per tier. `bin/guard show` first; do not overwrite another campaign's live grant — wait for it to expire or ask me for a combined reason.
```bash
G=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/bin/guard; $G show
R="pkg:pkg-20260927-cogx-w1-d9e1 pr:1305 sha:$SHA campaign:cognitive-transformation-20260927"
$G grant release-write --for 14400 --uses 10 --reason "$R: prepare/promote/rollback of that exact SHA; no broker writes" --yes
$G grant service       --for 14400 --uses 10 --reason "$R: install + enable tradeai-supervisor-breach-detector.timer and tradeai-gir-projector.timer" --yes
$G grant cron          --for 14400 --uses 4  --reason "$R: append the two lines in docs/ops/COGX_WAVE1_CRONTAB_LINES.txt (lanes platform-conformance-audit, approval-package-reminder); crontab backed up first" --yes
$G grant db-write      --for 14400 --uses 10 --reason "$R: intelligence.* projection tables only (seed_supervisor_sla --apply, gir_projector --apply)" --yes
```

## 5. Install the four lanes (O-2, I-4)

```bash
CUR=/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
# systemd (2 timers): copy from the served release, never from a worktree
for u in tradeai-supervisor-breach-detector.service tradeai-supervisor-breach-detector.timer tradeai-gir-projector.service tradeai-gir-projector.timer; do
  install -m 0644 $CUR/config/systemd/user/$u ~/.config/systemd/user/$u && echo installed $u; done
systemctl --user daemon-reload
systemctl --user enable --now tradeai-supervisor-breach-detector.timer tradeai-gir-projector.timer
systemctl --user list-timers --all | grep -E "supervisor-breach|gir-projector"
# cron (2 lines): back up, append, reinstall via stdin (a bare `crontab file` silently fails here)
crontab -l > ~/backups-crontab/crontab-$(date -u +%Y%m%dT%H%M%SZ)-pre-cogx-w1.txt
{ crontab -l; grep -v '^#' $CUR/docs/ops/COGX_WAVE1_CRONTAB_LINES.txt; } | crontab -
crontab -l | grep -cE "report_platform_conformance|approval_package_reminder"    # expect 2
```
Rollback: `systemctl --user disable --now <timer>`; restore the crontab backup with `crontab - < <backup>`.

## 6. First real runs (SLA seed, projection, conformance, detector)

```bash
cd $CUR
$PY scripts/seed_supervisor_sla.py --json-out ~/trade-ai-releases/persistent-state/data/runtime/supervisor_sla_seed.json --apply
$PY scripts/gir_projector.py --apply --state ~/trade-ai-releases/persistent-state/data/runtime/gir_projector_state.json     # ~2 min; 141k entities / 250k edges
sudo -u postgres psql -d trade_ai -Atc "set app.tenant_id='tradeai:tenant:primary'; select class, count(*) from intelligence.gir_entity group by 1 order by 1"
TRADEAI_ROOT=$CUR $PY scripts/report_platform_conformance.py --write
$PY scripts/supervisor_breach_detector.py --write
cat ~/trade-ai-releases/persistent-state/data/runtime/supervisor_breach_detector_latest.json | head -20
```
Expected first detector result: about 25 NO_OUTPUT lanes (the list in `docs/ops/COGX_WAVE1_STATUS_2026-09-27.md`) — those are findings to triage, not detector faults.

## 7. Tell me it is done
Reply on Telegram or here with the CURRENT pin and the three verify numbers from step 2. I then mark the package items EXECUTED, run the post-deploy validation (stage 6), and open tranche 4.
