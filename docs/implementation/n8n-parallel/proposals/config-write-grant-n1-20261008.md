# Config-write grant packet — N1 night (2026-10-08)

**Status:** PROPOSED — measured host state; no `systemctl` write executed; grant text in §5
**Owner:** platform (n8n scheduler-of-record program Day 0; operator John)

**AUTHORITY: READ_ONLY_ADVISORY — PROPOSAL.** Nothing here was executed. The operator runs the `systemctl`
lines under the config-write / service grant in §5. Companion: `../19-n1-cutover-packet-20261008.md`.

Measured 2026-10-08 14:40–14:48 UTC with read-only `systemctl --user list-unit-files 'tradeai-*'`,
`systemctl --user show -p Id,FragmentPath,UnitFileState,ActiveState,SubState,ExecStart,WorkingDirectory,EnvironmentFiles <unit>`
and `systemctl --user list-timers --all`. Served CURRENT = `e2b9dd72b-main-exact-phase2-20261008-103136`.
Repo unit files: `config/systemd/user/` at `72b0ce6be`. `$CUR` below = `$HOME/trade-ai-releases/portfolio-server/CURRENT`,
`$STATE` = `$HOME/trade-ai-releases/persistent-state`, `$VENV_PY` = `$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python`
(the shared interpreter; every unit on the host uses it and that is **not** what "runs from the dev tree" means here).

**Criterion used for "executes from the dev tree"**: `WorkingDirectory` or the *script path* in `ExecStart`
is under `trade-ai-v12-rebuild` (code executes from the checkout that may lag main), as opposed to
`trade-ai-releases/portfolio-server/CURRENT`. Measured across all 69 `tradeai-*` services that reference the
dev tree anywhere, **29** execute their code from it. This packet covers the subset the N1 night needs
(§2 relay/executor, §3 alert units, §4 timers); the other 17 are listed in §6 for a later packet.

---

## 1. Summary of what tonight's grant does and does not cover

| item | units | host state (measured) | repo unit file | in tonight's grant? |
|---|---|---|---|---|
| A. run relay + executor | `tradeai-n8n-run-relay.service`, `tradeai-n8n-run-executor.service` | **not installed** (no `list-unit-files` row; relay port `172.19.0.1:18092` → HTTP 000) | both present, already CURRENT-pinned | **yes**: link + enable from CURRENT |
| B. `--alert` monitors re-pin | `tradeai-data-plausibility`, `tradeai-data-source-health`, `tradeai-expected-services`, `tradeai-gap-resolution`, `tradeai-served-copy-split` (5 `.service`) | WorkingDirectory = dev tree, `ExecStart … scripts/<x>.py --alert` relative → resolves in the dev tree | present, **already fixed** to CURRENT (comment "2026-10-08: ran from the DEV tree … now run the served release") | **yes**: install the CURRENT copy + daemon-reload |
| B'. 6th `--alert` monitor | `tradeai-operator-answer-quality.service` | same dev-tree shape (`WorkingDirectory=…/trade-ai-v12-rebuild`, relative script) | present but **still dev-tree** (`config/systemd/user/tradeai-operator-answer-quality.service:18-20`) | **no** — needs its own PR first |
| C. timer re-pins | `tradeai-governance-pipeline.service`, `tradeai-portfolio-daily-cadence.service`, `-weekly-`, `-monthly-`, `-lookthrough-cadence.service` (5 services behind 5 enabled timers) | WorkingDirectory = dev tree, `ExecStart=/usr/bin/bash <dev tree>/scripts/pipelines/run_*.sh --apply` | **MISSING** from `config/systemd/user/` (no `.service`, no `.timer`) | **no** — separate PR adds the unit files; listed in §4 with the proposed CURRENT text |
| D. watchdog timer (conditional) | `tradeai-n8n-lab-watchdog.timer` | enabled, service already CURRENT-pinned | present (timer header says "PROPOSAL ONLY") | only if the N1 packet's lane-5 cutover is applied (packet §3.5 recommends deferring) |

The task brief said "5 alert units"; six `--alert` units were measured in the dev-tree shape. Five have a
corrected repo file and are in scope; the sixth (`operator-answer-quality`) is not, for the reason in B'.

---

## 2. Relay and executor — link + enable from CURRENT

### 2.1 Measured

- `systemctl --user list-unit-files 'tradeai-*'` → no row for `tradeai-n8n-run-relay.service` or
  `tradeai-n8n-run-executor.service`. `curl -s -m 3 -o /dev/null -w '%{http_code}' http://172.19.0.1:18092/status` → `000`.
- Gateway the executor drains: `tradeai-n8n-coordination-gateway.service` is `enabled/active`, `WorkingDirectory=$CUR`,
  `ExecStart=/bin/bash $CUR/scripts/n8n_coordination_gateway_run.sh`; `http://127.0.0.1:18091/healthz` →
  `{"ok": true, "durable": true, "run_scope": true, "run_lanes": 7}`.
- Secrets, names only (never values): `/run/user/<uid>/tradeai/env` contains one line each for
  `TRADEAI_N8N_RELAY_BEARER`, `TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N`, `TRADEAI_N8N_GATEWAY_HMAC_KEY`; it does **not**
  contain `TRADEAI_VENV_PYTHON` (the executor then uses the `Environment=` line in its unit, which sets it).
  The optional per-unit files `~/.config/tradeai/n8n-relay.env` and `~/.config/tradeai/n8n-gateway.env` are absent
  (both are `EnvironmentFile=-…`, so absence is not a start failure).
- Host convention: every installed unit is a **copy** in `~/.config/systemd/user/` (regular files, mode 0600,
  e.g. `tradeai-n8n-coordination-gateway.service` dated Oct 7 22:11), not a symlink.

### 2.2 Repo unit files (`config/systemd/user/`, both already CURRENT-pinned)

| unit | WorkingDirectory | ExecStart | env |
|---|---|---|---|
| `tradeai-n8n-run-relay.service` (`:22-27`) | `%h/trade-ai-releases/portfolio-server/CURRENT` | `%h/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python %h/trade-ai-releases/portfolio-server/CURRENT/scripts/n8n_run_relay.py --host 172.19.0.1 --port 18092` | `EnvironmentFile=-%t/tradeai/env`, `-%h/.config/tradeai/n8n-relay.env`; `TRADEAI_STATE_ROOT`, `TRADEAI_N8N_GATEWAY_URL=http://127.0.0.1:18091`; `Restart=always`, `MemoryMax=128M`, `CPUQuota=10%` |
| `tradeai-n8n-run-executor.service` (`:15-20`) | same | `… python %h/trade-ai-releases/portfolio-server/CURRENT/scripts/n8n_run_executor.py --interval 5` | `EnvironmentFile=-%t/tradeai/env`, `-%h/.config/tradeai/n8n-gateway.env`; `TRADEAI_STATE_ROOT`, `TRADEAI_VENV_PYTHON=<dev venv>`; `Restart=always`, `MemoryMax=1G`; `After=tradeai-n8n-coordination-gateway.service` |

Neither sets `NoNewPrivileges` (relevant: the executor must be able to run `crontab -l` for the
`crontab-snapshot-for-health-agent` lane; the health agent's unit could not).

### 2.3 Sequence (config-write grant)

```bash
CUR=$HOME/trade-ai-releases/portfolio-server/CURRENT
# link from CURRENT (as requested). NOTE: `systemctl link` needs an absolute path and refuses if a unit of that
# name already exists in ~/.config/systemd/user (neither does today). The link target is the CURRENT symlink
# path, so the unit text follows promotions; see the caveat below.
systemctl --user link "$CUR/config/systemd/user/tradeai-n8n-run-executor.service"
systemctl --user link "$CUR/config/systemd/user/tradeai-n8n-run-relay.service"
systemctl --user daemon-reload
systemctl --user enable --now tradeai-n8n-run-executor.service      # executor first: it creates $STATE/data/runtime/n8n_runs/shadow/
systemctl --user enable --now tradeai-n8n-run-relay.service
```

Caveat (NOT VERIFIED): `systemctl link` may store the *resolved* release-directory path rather than the
`CURRENT` symlink; if so the link breaks when that release directory is retired. The host-consistent
alternative is a copy, which is what every other unit is:
`install -m 0600 "$CUR/config/systemd/user/<unit>" "$HOME/.config/systemd/user/<unit>"` then the same
`daemon-reload` / `enable --now`. Either way `show -p FragmentPath` records which was done.

### 2.4 Verification (quote each in the grant thread)

```bash
systemctl --user show -p FragmentPath,UnitFileState,ActiveState,SubState,ExecStart,WorkingDirectory tradeai-n8n-run-executor.service
systemctl --user show -p FragmentPath,UnitFileState,ActiveState,SubState,ExecStart,WorkingDirectory tradeai-n8n-run-relay.service
#   expect ActiveState=active SubState=running, WorkingDirectory=$CUR, ExecStart script path under $CUR
journalctl --user -u tradeai-n8n-run-executor.service -n 3 --no-pager
#   expect one JSON line {"executor": "started", "ledger": ".../n8n_coordination_ledger.sqlite", "allowlist": "$CUR/config/n8n_run_allowlist.json", "lanes": [7 ids], ...}
ls -d $HOME/trade-ai-releases/persistent-state/data/runtime/n8n_runs/shadow        # created at executor start (scripts/n8n_run_executor.py:350)
journalctl --user -u tradeai-n8n-run-relay.service -n 2 --no-pager
#   expect {"ok": true, "host": "172.19.0.1", "port": 18092, "authority": "READ_ONLY_ADVISORY"} (scripts/n8n_run_relay.py:305)
curl -s -m 3 -o /dev/null -w '%{http_code}\n' http://172.19.0.1:18092/status     # GET /status; 401 without the bearer is the healthy answer (do_GET, :277-283)
```

First receipt paths (appear after the first n8n request, not at start):
executor → `$STATE/data/runtime/n8n_runs/<run_id>.json` and `$STATE/data/runtime/n8n_run_executor_last.json`
(`n8n_run_executor.py:65-66`); relay → `$STATE/data/runtime/n8n_relay/relay_log.jsonl` and
`$STATE/data/runtime/n8n_relay/n8n_run_relay_last.json` (`n8n_run_relay.py:137-139`). Doc 17 §5.1 names the
end-to-end check: a `curl` from inside the n8n container to the relay with the bearer returns a
`RunRequested` row for `n8n-lab-watchdog` in `dry_run`, and the executor's receipt for it is `RUN_DONE`.

### 2.5 Rollback

```bash
systemctl --user disable --now tradeai-n8n-run-relay.service
systemctl --user disable --now tradeai-n8n-run-executor.service
systemctl --user daemon-reload          # `disable` removes the link for a linked unit; for a copy also rm ~/.config/systemd/user/<unit>
```
Nothing else depends on these two units today (no cron line or timer calls them); n8n workflows that POST to
the relay simply fail their Assert node until it is back.

---

## 3. The five `--alert` monitor units — re-pin to CURRENT

### 3.1 Measured host state vs repo file

All five host units: `UnitFileState=disabled` (static-style, driven by their timers which are enabled),
`FragmentPath=$HOME/.config/systemd/user/<unit>` (copies), `WorkingDirectory=$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild`,
`ExecStart=$VENV_PY scripts/<script> --alert` — the relative `scripts/…` resolves against the dev tree.

| unit | host ExecStart (script, relative → dev tree) | repo file ExecStart / WorkingDirectory (CURRENT) | timer (repo `OnCalendar`) | registry lane → output_signal (first receipt after re-pin) |
|---|---|---|---|---|
| `tradeai-data-plausibility.service` | `scripts/data_plausibility_monitor.py --alert` | `WorkingDirectory=%h/trade-ai-releases/portfolio-server/CURRENT`; `ExecStart=$VENV_PY %h/trade-ai-releases/portfolio-server/CURRENT/scripts/data_plausibility_monitor.py --alert` (`:24-26`) | `*-*-* 06:20:00` | `data-plausibility-audit` → `$STATE/data/runtime/data_plausibility_last_run.json` (cadence 24 h) |
| `tradeai-data-source-health.service` | `scripts/check_data_source_health.py --alert` | same shape, `check_data_source_health.py --alert` (`:22-24`) | `*-*-* *:27:00` | `data-source-health-audit` → `data/runtime/data_source_health_last_run.json` (1 h) |
| `tradeai-expected-services.service` | `scripts/check_expected_services.py --alert` | same shape (`:20-22`) | `*-*-* *:12:00` | `expected-services-audit` → `data/runtime/expected_services_last_run.json` (1 h) |
| `tradeai-gap-resolution.service` | `scripts/check_gap_resolution.py --alert` | same shape (`:20-22`) | `*-*-* *:07,37:00` | `gap-resolution-audit` → `data/runtime/gap_resolution_last_run.json` (0.5 h) |
| `tradeai-served-copy-split.service` | `scripts/check_served_copy_split.py --alert` | same shape (`:21-23`), plus `Nice=10`, `IOSchedulingClass=idle` | `*-*-* *:42:00` | `served-copy-split-audit` → `data/runtime/served_copy_split_last_run.json` (1 h) |

Each repo file keeps `SuccessExitStatus=0 1` (exit 1 = a finding, not a unit failure) and the shared venv
interpreter (comment in each file: "Interpreter stays the shared venv").

### 3.2 Sequence (config-write grant)

```bash
CUR=$HOME/trade-ai-releases/portfolio-server/CURRENT
BK=$HOME/.local/state/tradeai/backups/units-$(date -u +%Y%m%dT%H%M%SZ)-pre-alert-repin; mkdir -p "$BK"
for u in tradeai-data-plausibility tradeai-data-source-health tradeai-expected-services tradeai-gap-resolution tradeai-served-copy-split; do
  cp -p "$HOME/.config/systemd/user/$u.service" "$BK/"                                   # rollback copy
  install -m 0600 "$CUR/config/systemd/user/$u.service" "$HOME/.config/systemd/user/$u.service"   # host units are copies; `link` would refuse (file exists)
done
systemctl --user daemon-reload
# timers stay enabled and untouched; the services are oneshot and are started by their timers. Optional one-off fire to get
# the first CURRENT-run receipt now instead of at the next OnCalendar tick:
#   systemctl --user start tradeai-gap-resolution.service   (next natural tick is :07/:37 anyway)
```

(If the operator prefers `link` for consistency with §2: `rm` the host copy first, then
`systemctl --user link "$CUR/config/systemd/user/$u.service"`; same caveat as §2.3.)

### 3.3 Verification

```bash
for u in tradeai-data-plausibility tradeai-data-source-health tradeai-expected-services tradeai-gap-resolution tradeai-served-copy-split; do
  systemctl --user show -p Id,WorkingDirectory,ExecStart "$u.service" | grep -c 'trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts\|WorkingDirectory=.*trade-ai-v12-rebuild'   # expect 0
  systemctl --user show -p WorkingDirectory "$u.service"                                   # expect …/portfolio-server/CURRENT
done
systemctl --user list-timers --all --no-pager | grep -E 'data-plausibility|data-source-health|expected-services|gap-resolution|served-copy-split'   # 5 rows, NEXT populated
# first receipt after the next tick (paths from config/lane_registry.json output_signal):
stat -c '%y %n' $HOME/trade-ai-releases/persistent-state/data/runtime/{data_plausibility,data_source_health,expected_services,gap_resolution,served_copy_split}_last_run.json
journalctl --user -u tradeai-gap-resolution.service -n 5 --no-pager     # the script's own log line must name a CURRENT path, not the dev tree
```

### 3.4 Rollback

```bash
for u in …same five…; do install -m 0600 "$BK/$u.service" "$HOME/.config/systemd/user/$u.service"; done
systemctl --user daemon-reload
```

---

## 4. The five timer-driven pipeline services — NO repo unit file (separate PR)

Measured (all `UnitFileState=static`, `FragmentPath=$HOME/.config/systemd/user/<unit>`, `WorkingDirectory=$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild`):

| service | host ExecStart | timer (host `OnCalendar`, enabled) | registry lane → output_signal | proposed CURRENT replacement (for the PR that adds `config/systemd/user/<unit>`) |
|---|---|---|---|---|
| `tradeai-governance-pipeline.service` | `/usr/bin/bash $HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts/pipelines/run_governance_pipeline.sh --apply` | `Mon..Fri *-*-* 07:40:00` and `Sun *-*-* 18:00:00` | `governance-pipeline` → `data/runtime/governance_pipeline_last_run.json` (24 h) | `WorkingDirectory=%h/trade-ai-releases/portfolio-server/CURRENT`; `ExecStart=/usr/bin/bash %h/trade-ai-releases/portfolio-server/CURRENT/scripts/pipelines/run_governance_pipeline.sh --apply` |
| `tradeai-portfolio-daily-cadence.service` | `… run_portfolio_maintenance_pipeline.sh --cadence daily --apply` | `Mon..Fri *-*-* 07:30:00` | `portfolio-daily-cadence` → `data/runtime/portfolio_maintenance_daily_last_run.json` (48 h) | same pattern, `--cadence daily --apply` |
| `tradeai-portfolio-weekly-cadence.service` | `… --cadence weekly --apply` | `Sun *-*-* 20:30:00` | `portfolio-weekly-cadence` → `…_weekly_last_run.json` (168 h) | `--cadence weekly --apply` |
| `tradeai-portfolio-monthly-cadence.service` | `… --cadence monthly --apply` | `*-*-01 07:35:00` | `portfolio-monthly-cadence` → `…_monthly_last_run.json` (744 h) | `--cadence monthly --apply` |
| `tradeai-portfolio-lookthrough-cadence.service` | `… --cadence lookthrough --apply` | `Sun *-*-01..07 06:30:00` | `portfolio-lookthrough-cadence` → `…_lookthrough_last_run.json` (744 h) | `--cadence lookthrough --apply` |

`ls config/systemd/user/ | grep -E 'governance-pipeline|portfolio-.*-cadence'` → nothing. There is no repo
text to install, so these five are **not in tonight's grant**: the PR must first add the ten unit files
(5 `.service` with the CURRENT paths above, 5 `.timer` reproducing the measured `OnCalendar`), then a later
config-write grant installs them with the §3.2 sequence. `tradeai-portfolio-backup-cadence.service` was *not*
in the dev-tree set and needs nothing.

Also not in scope (same reason — repo file still dev-tree): `tradeai-operator-answer-quality.service`
(timer `*-*-* *:22,52:00`, lane `operator-answer-quality-audit` → `data/runtime/operator_answer_quality_last_run.json`).
Its PR is a two-line change mirroring the other five.

---

## 5. Grant texts

Service / config-write grant (one, for §2 + §3):

```
PR #<n> sha <sha>: link+enable tradeai-n8n-run-relay.service and tradeai-n8n-run-executor.service from CURRENT; re-pin 5 --alert units (data-plausibility, data-source-health, expected-services, gap-resolution, served-copy-split) to CURRENT (install unit copy + daemon-reload); no broker, send, deploy, crontab
```

Conditional add-on, only if the N1 packet's lane 5 is applied in the cron-write window (packet §3.5 recommends deferring):

```
… ; disable --now tradeai-n8n-lab-watchdog.timer after its CutoverReceipt (re-enable on rollback)
```

`<n>` / `<sha>` = this packet's PR number and head SHA from `gh pr view <n> --json headRefOid` at grant time.
Order tonight: §2 (relay + executor) **before** any N1 shadow activation; §3 any time in the same window;
§4 and B' after their PRs merge and promote.

---

## 6. The other 18 dev-tree executors (measured, out of scope tonight)

For the record, the remaining `tradeai-*` services whose WorkingDirectory or script path is the dev tree
(all `inactive` at measurement; one `failed`): `advisory-shadow-session` (failed), `agent-worktree-retention`,
`backup-enforcer`, `cio-desk-memo-regen`, `disk-pressure-guard`, `eod-consolidated-close`, `finviz-view-contracts`,
`governance-facts`, `governance-status`, `holdings-agent-enqueue`, `iris-taxonomy`, `maturity-board`,
`operator-readiness`, `slo-burn-rate`, `sm-render`, `source-litmus`, `stance-organic-observe` (WorkingDirectory
CURRENT but script path dev tree), `tax-lots-rebuild`. Six more run from the retired worktree
`tradeai-wt-cursor-guardrails` (`flash-llm-intelligence`, `flash-portfolio-risk`, `flash-watchlist-daily`,
`hermes-research-remediation`, `intelligence-remediation`, `main-desk-free-llm-weekly`) — a separate finding.

## 7. NOT VERIFIED

- `systemctl link` semantics against the `CURRENT` symlink (resolved vs. kept) and release retention of a linked file.
- That the relay binds `172.19.0.1:18092` on this host (the docker bridge address is the unit's `--host`; ufw rule `172.19.0.0/16 → 18092` per doc 17 §5.1 is the operator's).
- The first-receipt paths for §3 assume the scripts write their registry `output_signal`; the registry rows say so, the scripts were not read for this packet.
- No secret value was read; only the presence of variable names in `/run/user/<uid>/tradeai/env` was counted.
