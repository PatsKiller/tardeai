# 19 — N1 cutover packet (2026-10-08)

**Status:** PROPOSED — dry-run receipts only; no crontab, unit, registry or n8n change executed; every `--apply` is the operator's under the grants in §6/§7
**Owner:** platform (n8n scheduler-of-record program Day 0, tranche N1; operator John)

**AUTHORITY: READ_ONLY_ADVISORY — PROPOSAL.** Nothing in this file was executed against the host. Every
cutover and rollback below was run in **dry-run** (the tool's default) against a **saved copy** of the
crontab behind a fake `crontab` (the mechanism of `tests/test_n8n_lane_cutover_20261008.py::_fake_crontab`),
with the registry read from this worktree and receipts written to a scratch state root. The operator
executes the `--apply` steps under the grants in §6 and §7 and under
`docs/implementation/n8n-parallel/proposals/config-write-grant-n1-20261008.md`.

| fact | value | source |
|---|---|---|
| measured | 2026-10-08 14:40–14:48 UTC (10:40–10:48 EDT) | this session |
| code | branch `docs/n1-cutover-packet` at `72b0ce6be` (= main; train #1522 merged) | `git log` |
| served CURRENT | `e2b9dd72b-main-exact-phase2-20261008-103136` | `readlink -f $HOME/trade-ai-releases/portfolio-server/CURRENT` |
| state root | `$HOME/trade-ai-releases/persistent-state` (`$STATE` below) | `scripts/lib/lane_registry.py::state_root` |
| crontab env | line 3 `PROJ=$HOME/trade-ai-releases/portfolio-server/CURRENT`; line 4 `PY=$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python`; 1045 lines | `crontab -l` (read-only) |
| gateway | `http://127.0.0.1:18091/healthz` → `{"ok": true, "durable": true, "run_scope": true, "run_lanes": 7}` | `curl` 14:45Z |
| n8n lab | `http://127.0.0.1:5678/healthz` → HTTP 200 | `curl` 14:45Z |
| relay | `172.19.0.1:18092` → no answer (HTTP 000); `tradeai-n8n-run-relay.service` and `tradeai-n8n-run-executor.service` are **not installed** (`systemctl --user list-unit-files 'tradeai-*'` has no row for either) | measured; see the config-write packet |
| run receipts | `$STATE/data/runtime/n8n_runs/` **does not exist** (the executor creates it at start, `scripts/n8n_run_executor.py:350`) → no shadow or canary receipt exists for any lane | `ls` 14:45Z |
| cutover receipts | `$STATE/data/runtime/n8n_cutover/` does not exist (nothing cut over yet) | `ls` 14:45Z |
| workflow index | `docs/implementation/n8n-parallel/workflows/generated/INDEX.json` (`code_sha 86c38602e48f`, generated 2026-10-08T12:59:49Z, credential `tradeai-run-relay`) | file |

Tools referenced (all in this tree): `scripts/pipelines/cutover/cutover_lane.sh` → `_cutover.py cutover --lane`
(`_cutover.py:371-461`), `rollback_lane.sh` → `_cutover.py rollback --lane` (`:464-556`),
`scripts/report_n8n_lane_readiness.py` (verdict GO / GO_WITH_NOTES / NO_GO from existing evidence only),
`scripts/n8n_cutover_checklist.py --tranche N1` (ticks boxes only from files on disk),
`scripts/n8n_run_executor.py` (RunReceipt@v1 writer), `scripts/n8n_run_relay.py` (bearer relay),
`scripts/safe_flock.sh` (lock event log).

---

## 1. The nine lanes at a glance

Registry rows: `config/lane_registry.json` (line numbers are the row's `"lane_id"` line at `72b0ce6be`).
Workflow ids: `workflows/generated/INDEX.json`. Allowlist: `config/n8n_run_allowlist.json`.

| # | lane_id | host scheduler today | registry row | cadence h | output_signal (rel. `$STATE`) | shadow wf id | live wf id | cutover path | readiness 14:46Z |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `n8n-pilot-dispatch` | crontab line 1024, `*/15 * * * *` | L3121, kind `cron`, ACTIVE | 0.25 | `data/runtime/n8n_pilot_dispatch_last.json` | `baddad5487f9c288` | `078e8fcbea0c5020` | `cutover_lane.sh` (cron line) | NO_GO: no shadow/canary receipt; host present_once=True; signal age 0.01 h |
| 2 | `n8n-incident-fanin` | crontab line 1025, `*/5 * * * *` | L3141, `cron`, ACTIVE | 0.1 | `data/runtime/n8n_incident_fanin_last.json` | `e511583d42831b8b` | `722fac0e043ea5c4` | `cutover_lane.sh` (cron line) | NO_GO: same two blockers; signal age 0.01 h |
| 3 | `n8n-research-intake-consumer` | crontab line 1044, `*/15 * * * *` | L3728, `cron`, ACTIVE | 0.25 | `data/runtime/n8n_research_intake_last.json` | `577f9dfaede632f3` | `21fd15d5f8a4c4da` | `cutover_lane.sh` (cron line) | NO_GO: same; signal age 0.01 h |
| 4 | `crontab-snapshot-for-health-agent` | crontab line 993, `*/20 * * * *` | L2583, `cron`, ACTIVE | 0.34 | `data/runtime/crontab_snapshot.txt` | `5439cd4d82e1f305` | `c0d4c7845e5c4fcc` | `cutover_lane.sh` (cron line) | NO_GO: same; signal age 0.09 h |
| 5 | `n8n-lab-watchdog` | `tradeai-n8n-lab-watchdog.timer` (OnUnitActiveSec=5min, enabled) | L3224, `systemd`, ACTIVE | 0.1 | `data/runtime/n8n_lab_watchdog_last.json` | `9208ac827e514183` | `54069d7c36598de8` | `cutover_lane.sh` + operator `systemctl --user disable --now` (config-write) | NO_GO: same; signal age 0.06 h |
| 6 | `lane-governance-packet-weekly` | **none** (NEVER_SCHEDULED) | L3748, kind `none`, NEVER_SCHEDULED | 168 | `data/runtime/lane_governance_packet_last.json` | `e6f62397d5ae2aa2` | `175e44ef2a1614a4` | **REFUSED by `cutover_lane.sh`** (exit 2); needs a registry-row PR, no crontab change | NO_GO: state NEVER_SCHEDULED; kind none not measurable; no receipts |
| 7 | `maturity-remeasure` | crontab line 1000, `40 6 * * 1` | L2796, `cron`, ACTIVE | 168 | `data/governance/maturity_latest.json` | `a26114588930ae9b` | `e18d7849b4142927` | `cutover_lane.sh` (cron line; `flock` lock shared) | NO_GO: no receipts; note: 0 safe_flock completions on record (cron uses plain `flock`); signal age 76 h (limit 336 h) |
| 8 | `n8n-monitor-trade-ai` | n8n workflow `s57KBllvqf6Jb5xF` (active, "Every 5 minutes") | **no row** | — | — | `4e8c571514edcfc2` | `e10e7c19321c906a` | **n8n-native**: deactivate the legacy workflow; generated files not runnable (not allowlisted) | NO_GO: no registry row |
| 9 | `n8n-monitor-dof` | n8n workflow `GXwhbRkwsGcYZxgn` (active, "Every 5 minutes") | **no row** | — | — | `7b7392a0cfa5cdde` | `e10087387b964e87` | same as 8 | NO_GO (by construction: no row) |

Readiness quotes are verbatim from `$PY scripts/report_n8n_lane_readiness.py --lane <lane>` run from this
worktree at 14:46Z (§5.3). Every lane is NO_GO today for the same structural reason: the executor is not
installed, so no RunReceipt exists. The packet is therefore an **order of operations**, not a go signal.

**Scope of the "9 cutovers"** (what `--apply` actually touches): five crontab lines (1, 2, 3, 4, 7) commented
in place; one timer disabled by the operator (5); one registry-only first scheduling that the cutover tool
refuses and that must come as a registry PR (6); two n8n-native deactivations with no host entry (8, 9).

---

## 2. Common mechanics (cited once, used by every lane)

### 2.1 Shadow evidence (`mode=dry_run`)

The shadow workflow (`<lane>-shadow.json`) is Schedule → Set → `POST {TRADEAI_N8N_RUN_URL}/run` with body
`{"lane_id": "<lane>", "mode": "dry_run", "requested_by": "<lane>-shadow"}` under the `tradeai-run-relay`
Header Auth credential → Code "Assert REQUESTED" (node list from the generated files). The relay records a
`RunRequested` row; the executor drains it and writes:

- **RunReceipt@v1 file**: `$STATE/data/runtime/n8n_runs/<run_id>.json` (`n8n_run_executor.py:65,259-269`);
  last-run mirror `$STATE/data/runtime/n8n_run_executor_last.json` (`:66`); the same JSON is in the ledger
  row `runs.receipt_json` (`scripts/lib/n8n_coordination_ledger.py:145-158`, columns `run_id, lane_id, mode,
  state, requested_by, caller_id, requested_at, started_at, finished_at, exit_code, duration_s, receipt_json`).
- **Pass criteria**: `lane_id` = the lane, `mode` = `dry_run`, `state` = `RUN_DONE`, `exit_code` = 0, and
  `output_signal_mtime_before == output_signal_mtime_after` (fields written at `:211,227`). The three
  coordination scripts write their `_last.json` only under `--apply` (`n8n_pilot_dispatch.py:302-307`,
  `n8n_incident_fanin.py:360-364`, `n8n_research_intake_consumer.py:180-184`); `maturity_remeasure.py`
  writes only with `--write` (`:226`); the snapshot and watchdog lanes' `dry_run_arg` redirect the write to
  `$STATE/data/runtime/n8n_runs/shadow/…` (allowlist). So "output_signal untouched" is a measurable
  equality on the receipt, not an assumption.
- **Fail states** to grep for: `RUN_FAILED` (`reason` `exit_<n>` or `spawn:<Exc>`), `RUN_REFUSED`
  (`lane_not_allowlisted`, `bad_mode`, `mode_unavailable:<mode>`), `RUN_SKIPPED_LOCK` (`:202-240`).

### 2.2 Canary evidence (`mode=live`, host scheduler still live)

Deactivate `<lane>-shadow`, activate `<lane>` (or press "Execute workflow" once for a weekly lane,
doc 17 §5.4). Required, per lane:

1. One RunReceipt with `mode=live`, `state=RUN_DONE`, `exit_code=0`, `output_signal` = the registry path,
   and `output_signal_mtime_after > output_signal_mtime_before` (the signal advanced because of the n8n fire).
2. No `RUN_SKIPPED_LOCK` receipt for the lane inside one cadence window, and no second start of the same
   component inside that window. Where that is logged depends on `lock_kind` (allowlist):
   - `safe_flock` lanes (1, 2, 3, 4, 6): the executor wraps the command in `bash scripts/safe_flock.sh <lock>`
     (`n8n_run_executor.py:139`), which appends `started` / `completed` / `lock_skip` events to
     `<PROJECT_ROOT>/logs/safe_flock_events.jsonl` (`scripts/safe_flock.sh:27-30,70,87,104`). PROJECT_ROOT is
     the executor's WorkingDirectory = CURRENT, and `CURRENT/logs` resolves to
     `$HOME/trade-ai-releases/persistent-state/logs` (measured with `readlink -f`), so the file is
     **`$STATE/logs/safe_flock_events.jsonl`**, `component` = lock basename without `.lock`
     (`tradeai_n8n_pilot_dispatch`, `tradeai_n8n_incident_fanin`, `tradeai_n8n_research_intake_consumer`,
     `tradeai_crontab_snapshot`, `tradeai_lane_governance_packet`). Event row shape (measured 14:45Z):
     `ts, component, event_type, severity, lock_file, pid_file, command, message, exit_code`.
     Check: exactly one `started` for the component in the window, and the n8n run's `completed` has `exit_code 0`.
   - `flock` lanes (5, 7): the executor runs `flock -n -E 75 <lock> …` (`:136-137`); there is no event log.
     Proof is the receipt: a conflict is `RUN_SKIPPED_LOCK` / `reason flock_held` (`:229-231`). Zero such rows
     in the window = no double run.
   - **Caveat for lanes 1, 2, 3**: the live cron lines carry **no lock at all** (crontab lines 1024, 1025,
     1044; the allowlist `source` field says so). The safe_flock lock protects only the n8n side; a cron fire
     and an n8n fire in the same minute would both run. Mitigation in §6: fire the canary by hand at an
     off-cadence minute (e.g. :07 for a `*/5` lane) and compare the lane's own `_last.json` `as_of` with the
     RunReceipt `started_at`/`finished_at`; a cron fire inside that span means the canary must be repeated.
3. Relay health: `$STATE/data/runtime/n8n_relay/relay_log.jsonl` has no `relay_bad_bearer` row and
   `n8n_run_relay_last.json` shows `auth_failures` unchanged (`n8n_run_relay.py:134-139,185-202`).

### 2.3 Cutover and rollback commands (one form, per lane)

```bash
cd $HOME/trade-ai-releases/portfolio-server/CURRENT      # or the checkout named in §6.2
PY=$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python
export TRADEAI_STATE_ROOT=$HOME/trade-ai-releases/persistent-state
# dry-run (default) — writes only $STATE/data/runtime/n8n_cutover/<lane>-<ts>-cutover-dry-run.json
scripts/pipelines/cutover/cutover_lane.sh <lane> --workflow-id <live wf id> --cadence "<cron expr>"
# apply — backs up the crontab to ~/.local/state/tradeai/backups/crontab-<ts>-pre-cutover-lane-<lane>.txt,
# comments the ONE matching line as "# RETIRED 2026-10-08 n8n-cutover <lane> <line>", flips the registry row
scripts/pipelines/cutover/cutover_lane.sh <lane> --workflow-id <live wf id> --cadence "<cron expr>" --apply
# rollback dry-run / apply — uncomments exactly the tagged line, restores scheduler_before from the receipt
scripts/pipelines/cutover/rollback_lane.sh <lane>
scripts/pipelines/cutover/rollback_lane.sh <lane> --apply
# readiness (read-only; --write adds $STATE/data/runtime/n8n_lane_readiness_last.json)
$PY scripts/report_n8n_lane_readiness.py --lane <lane>
```

Refusals are exit 2 with a `…-refused.json` receipt (`_cutover.py:359-366`): no row, row not ACTIVE, row
already `n8n`, kind not cron/systemd, 0 or >1 uncommented matches, a line already tagged, missing
`--workflow-id`, or a registry whose re-serialisation would churn other lines (`:235-242`). Every lane
action takes `/tmp/n8n_cutover.lock` non-blocking (`:270-280`), so two cutovers cannot interleave.

**Where the registry flip lands (operator decision, §6.2).** `--apply` rewrites
`config/lane_registry.json` under `CUTOVER_CODE_ROOT` (default: the tree the script runs from,
`_cutover.py:220-221`). Run from CURRENT it edits the served release's copy (lost at the next promote);
run from a git checkout it edits a file that must still be merged and promoted. Either way the five/six
flipped rows must reach `main` in a registry PR in the same window, or the lane monitor reports the lane
ORPHANED (`kind: cron` with its line commented; AGENTS.md §23 "a lane left kind: cron with its line
removed is reported ORPHANED") and `check_lane_registry --fail-on-new --state-drift` is red.

---

## 3. Per-lane packet

Each block: live host entry → registry row → workflow files → shadow evidence → canary evidence →
commands → dry-run receipt (quoted from §5). Paths in the quoted cron lines are shown with `$HOME`.

### 3.1 `n8n-pilot-dispatch`

- **Live cron line** (crontab line 1024, read-only `crontab -l`):
  `*/15 * * * * cd $PROJ && set -a && . /run/user/$(id -u)/tradeai/env && set +a && TRADEAI_STATE_ROOT=$HOME/trade-ai-releases/persistent-state $PY scripts/n8n_pilot_dispatch.py --apply >> $HOME/trade-ai-releases/persistent-state/logs/n8n_pilot_dispatch.log 2>&1`
  — no lock on the line.
- **Registry row** (`config/lane_registry.json:3121`): `scheduler {kind: cron, expression: "*/15 * * * * n8n_pilot_dispatch.py --apply", match: "scripts/n8n_pilot_dispatch.py"}`, `expected_cadence_hours 0.25`, `output_signal {file_mtime, data/runtime/n8n_pilot_dispatch_last.json}`, ACTIVE since 2026-10-07 (cron grant `99d773a23dbd784c`).
- **Allowlist entry**: `$PY scripts/n8n_pilot_dispatch.py`, lock `/tmp/tradeai_n8n_pilot_dispatch.lock` (`safe_flock`), timeout 300 s, `dry_run_arg --dry-run`, `live_arg --apply`, `market_gate false`.
- **Workflows**: `workflows/generated/n8n-pilot-dispatch-shadow.json` (id `baddad5487f9c288`) and `n8n-pilot-dispatch.json` (id `078e8fcbea0c5020`); schedule `*/15 * * * *`, fidelity EXACT.
- **Shadow evidence**: `$STATE/data/runtime/n8n_runs/<run_id>.json` with `lane_id n8n-pilot-dispatch, mode dry_run, state RUN_DONE, exit_code 0, output_signal_mtime_before == _after`; `$STATE/logs/safe_flock_events.jsonl` has one `started` + one `completed exit_code 0` for component `tradeai_n8n_pilot_dispatch`.
- **Canary evidence**: one `mode live` receipt as in §2.2 with `output_signal_mtime_after > _before` on `data/runtime/n8n_pilot_dispatch_last.json`; exactly one `started` for the component in the 15-minute window; no `RUN_SKIPPED_LOCK`. Off-cadence manual fire (§2.2 caveat).
- **Cutover**: `scripts/pipelines/cutover/cutover_lane.sh n8n-pilot-dispatch --workflow-id 078e8fcbea0c5020 --cadence "*/15 * * * *"` then the same with `--apply`.
- **Rollback**: `scripts/pipelines/cutover/rollback_lane.sh n8n-pilot-dispatch --apply` + deactivate workflow `078e8fcbea0c5020`.
- **Readiness**: `$PY scripts/report_n8n_lane_readiness.py --lane n8n-pilot-dispatch` → 14:46Z: `NO_GO` (two blockers: no shadow / no canary receipt; `host scheduler: cron match='scripts/n8n_pilot_dispatch.py' present_once=True`; `output_signal: age=0.01h limit=0.5h`).
- **Dry-run receipt** (sandbox, §5.1): exit 0; `scheduler after: {"kind": "n8n", "expression": "078e8fcbea0c5020", "match": "scripts/n8n_pilot_dispatch.py", "cadence": "*/15 * * * *"}`; `line_after` = `# RETIRED 2026-10-08 n8n-cutover n8n-pilot-dispatch */15 * * * * cd $PROJ && …`. Rollback dry-run (after a sandbox apply, §5.2): exit 0, `would uncomment` the tagged line back to the original; rollback `--apply` in the sandbox restored the line and the row (§5.3, this is the tranche's "real rollback" lane).

### 3.2 `n8n-incident-fanin`

- **Live cron line** (line 1025): `*/5 * * * * cd $PROJ && set -a && . /run/user/$(id -u)/tradeai/env && set +a && TRADEAI_STATE_ROOT=$HOME/trade-ai-releases/persistent-state $PY scripts/n8n_incident_fanin.py --apply >> $HOME/trade-ai-releases/persistent-state/logs/n8n_incident_fanin.log 2>&1` — no lock.
- **Registry row** (`:3141`): kind `cron`, expression `*/5 * * * * n8n_incident_fanin.py --apply`, match `scripts/n8n_incident_fanin.py`, cadence 0.1 h, signal `data/runtime/n8n_incident_fanin_last.json`, ACTIVE.
- **Allowlist**: lock `/tmp/tradeai_n8n_incident_fanin.lock` (`safe_flock`), timeout 180 s, `--dry-run` / `--apply`.
- **Workflows**: shadow `e511583d42831b8b`, live `722fac0e043ea5c4`; `*/5 * * * *` EXACT.
- **Shadow / canary evidence**: as §2.1 / §2.2 with component `tradeai_n8n_incident_fanin`, signal `n8n_incident_fanin_last.json`, 5-minute window. Note this lane *consumes* the watchdog and executor receipts (`n8n_incident_fanin.py:126-129,231`), so after cutover it is also the first consumer to notice a missing n8n fire.
- **Cutover**: `cutover_lane.sh n8n-incident-fanin --workflow-id 722fac0e043ea5c4 --cadence "*/5 * * * *"` [`--apply`]. **Rollback**: `rollback_lane.sh n8n-incident-fanin --apply`. **Readiness**: `--lane n8n-incident-fanin` → NO_GO (no receipts; `present_once=True`; `age=0.01h limit=0.2h`).
- **Dry-run receipt**: exit 0; scheduler after `{"kind": "n8n", "expression": "722fac0e043ea5c4", "match": "scripts/n8n_incident_fanin.py", "cadence": "*/5 * * * *"}`; rollback dry-run exit 0 (§5.2).

### 3.3 `n8n-research-intake-consumer`

- **Live cron line** (line 1044): `*/15 * * * * cd $PROJ && set -a && . /run/user/$(id -u)/tradeai/env && set +a && TRADEAI_STATE_ROOT=$HOME/trade-ai-releases/persistent-state $PY scripts/n8n_research_intake_consumer.py --apply >> logs/n8n_research_intake.log 2>&1  # TRADEAI_LANE n8n-research-intake-consumer` — no lock.
- **Registry row** (`:3728`): kind `cron`, match `scripts/n8n_research_intake_consumer.py`, cadence 0.25 h, signal `data/runtime/n8n_research_intake_last.json`, ACTIVE since 2026-10-08 (cron grant `6fa4f93c2a15ff9b`).
- **Allowlist**: lock `/tmp/tradeai_n8n_research_intake_consumer.lock` (`safe_flock`), timeout 300 s, `--dry-run` / `--apply`.
- **Workflows**: shadow `577f9dfaede632f3`, live `21fd15d5f8a4c4da`; `*/15 * * * *` EXACT.
- **Shadow / canary**: §2.1 / §2.2, component `tradeai_n8n_research_intake_consumer`, 15-minute window. The live run enqueues into `ri_research_queue` under the intake daily cap (registry `reason_evidence`), so a double fire would at worst enqueue the same request twice inside the cap — check the receipt's `enqueued_today` did not jump by 2.
- **Cutover**: `cutover_lane.sh n8n-research-intake-consumer --workflow-id 21fd15d5f8a4c4da --cadence "*/15 * * * *"` [`--apply`]. **Rollback**: `rollback_lane.sh n8n-research-intake-consumer --apply`. **Readiness**: NO_GO (no receipts; `present_once=True`; `age=0.01h limit=0.5h`).
- **Dry-run receipt**: exit 0; scheduler after `{"kind": "n8n", "expression": "21fd15d5f8a4c4da", …, "cadence": "*/15 * * * *"}`; rollback dry-run exit 0.

### 3.4 `crontab-snapshot-for-health-agent`

- **Live cron line** (line 993): `*/20 * * * * crontab -l > $HOME/trade-ai-releases/persistent-state/data/runtime/crontab_snapshot.txt.tmp 2>/dev/null && mv -f $HOME/trade-ai-releases/persistent-state/data/runtime/crontab_snapshot.txt.tmp $HOME/trade-ai-releases/persistent-state/data/runtime/crontab_snapshot.txt  # R-03: readable crontab snapshot for the hardened health agent` — no lock.
- **Registry row** (`:2583`): kind `cron`, match `crontab_snapshot.txt.tmp`, cadence 0.34 h, signal (absolute) `$STATE/data/runtime/crontab_snapshot.txt`, ACTIVE (cron grant `1d4795f8471a664a`).
- **Allowlist**: `bash -c 'crontab -l > "${1}.tmp" && mv -f "${1}.tmp" "${1}"' crontab_snapshot <target>`; lock `/tmp/tradeai_crontab_snapshot.lock` (`safe_flock`), timeout 30 s; `dry_run_arg` target `$STATE/data/runtime/n8n_runs/shadow/crontab_snapshot.txt`, `live_arg` target `$STATE/data/runtime/crontab_snapshot.txt`.
- **Workflows**: shadow `5439cd4d82e1f305`, live `c0d4c7845e5c4fcc`; `*/20 * * * *` EXACT.
- **Shadow evidence**: receipt `mode dry_run RUN_DONE exit 0`, **and** `$STATE/data/runtime/n8n_runs/shadow/crontab_snapshot.txt` exists with the same line count as `crontab -l` (1045 today) — this proves `crontab -l` works inside the executor unit (the health agent's own unit could not, registry `state_reason`; the executor unit sets no `NoNewPrivileges`, `config/systemd/user/tradeai-n8n-run-executor.service:13-27`). Until that receipt exists this is **NOT VERIFIED**.
- **Canary**: live receipt with `output_signal_mtime_after > _before` on `crontab_snapshot.txt`; one `started` for `tradeai_crontab_snapshot` in the 20-minute window. A cron/n8n overlap here is harmless (same bytes, atomic `mv`).
- **Cutover**: `cutover_lane.sh crontab-snapshot-for-health-agent --workflow-id c0d4c7845e5c4fcc --cadence "*/20 * * * *"` [`--apply`]. **Rollback**: `rollback_lane.sh crontab-snapshot-for-health-agent --apply`. **Readiness**: NO_GO (no receipts; `cron match='crontab_snapshot.txt.tmp' present_once=True`; `age=0.09h limit=0.68h`).
- **Dry-run receipt**: exit 0; `would comment: */20 * * * * crontab -l > …`; rollback dry-run exit 0.
- **Self-reference note**: after cutover the file this lane writes is itself the health agent's view of the crontab, and the cutover comments this lane's own line; the next n8n fire records that. The health agent's `cron_missing` checks keep working because they read the snapshot, not the registry.

### 3.5 `n8n-lab-watchdog`

- **Live timer**: `tradeai-n8n-lab-watchdog.timer` — `systemctl --user list-timers`: last 10:42:18 EDT, next 10:47:18; `show`: `TimersMonotonic OnUnitActiveUSec=5min`, `OnBootUSec=2min`, `UnitFileState=enabled`, `FragmentPath=$HOME/.config/systemd/user/tradeai-n8n-lab-watchdog.timer`. Service: WorkingDirectory CURRENT, `ExecStart=/usr/bin/flock -n /tmp/tradeai-n8n-lab-watchdog.lock <dev venv python> $HOME/trade-ai-releases/portfolio-server/CURRENT/scripts/n8n_lab_watchdog.py --url http://127.0.0.1:5678/healthz --receipt $STATE/data/runtime/n8n_lab_watchdog_last.json --timeout 3` (already executes from CURRENT).
- **Registry row** (`:3224`): kind `systemd`, expression `tradeai-n8n-lab-watchdog.timer (5m)`, match `tradeai-n8n-lab-watchdog.timer`, cadence 0.1 h, signal `data/runtime/n8n_lab_watchdog_last.json`, ACTIVE (config-write grant `113fa7d3b2344284`). Row note: "Replaces the two in-n8n monitor workflows".
- **Allowlist**: `$PY scripts/n8n_lab_watchdog.py --url http://127.0.0.1:5678/healthz --timeout 3`, lock `/tmp/tradeai-n8n-lab-watchdog.lock` (`flock`, same file as the unit → exit 75 on conflict), timeout 20 s; `dry_run_arg --receipt $STATE/data/runtime/n8n_runs/shadow/n8n_lab_watchdog_last.json`, `live_arg --receipt $STATE/data/runtime/n8n_lab_watchdog_last.json`.
- **Workflows**: shadow `9208ac827e514183`, live `54069d7c36598de8`; `*/5 * * * *` EXACT (timer is monotonic 5 min; n8n fires on the wall-clock — fidelity note in INDEX).
- **Shadow evidence**: `mode dry_run RUN_DONE exit 0`; `$STATE/data/runtime/n8n_runs/shadow/n8n_lab_watchdog_last.json` written; live signal mtime unchanged.
- **Canary evidence**: live receipt, signal advanced; **no** `RUN_SKIPPED_LOCK reason flock_held` in the 5-minute window (the timer and n8n share the flock file: a conflict is visible as exactly that state).
- **Cutover** (two parts): `cutover_lane.sh n8n-lab-watchdog --workflow-id 54069d7c36598de8 --cadence "*/5 * * * *"` [`--apply`] flips the row and writes `operator_command: "systemctl --user disable --now tradeai-n8n-lab-watchdog.timer"` into the receipt; the operator runs that command under the **config-write** grant (never the tool: `_cutover.py:24-27`). Rollback: `rollback_lane.sh n8n-lab-watchdog --apply` + `systemctl --user enable --now tradeai-n8n-lab-watchdog.timer` (receipt `operator_command`).
- **Readiness**: NO_GO (no receipts; `systemd match='tradeai-n8n-lab-watchdog.timer' present_once=True`; `age=0.06h limit=0.2h`).
- **Dry-run receipt**: exit 0; prints `operator command (NOT run here; config-write grant): systemctl --user disable --now tradeai-n8n-lab-watchdog.timer`; sandbox apply receipt `crontab_backup: null`, `operator_command` as above; rollback dry-run exit 0 with `operator command … enable --now`.
- **Recommendation (operator decision)**: this lane is the *independent* probe behind the rollback trigger "n8n `/healthz` down > 10 min" (doc 17 §7). Scheduled by n8n, it cannot fire when n8n is down, so the trigger would go blind. Proposal: run shadow and canary, but **keep the host timer** (do not apply this cutover) until a second, host-side probe exists; or cut it over last and accept that `n8n-incident-fanin` (host cron until its own cutover) is the only remaining watcher.

### 3.6 `lane-governance-packet-weekly`

- **Live host entry**: none. Registry row (`:3748`) is `scheduler {kind: none}`, `state NEVER_SCHEDULED` since 2026-10-08, cadence 168 h, signal `data/runtime/lane_governance_packet_last.json` (last written 2026-10-07 21:50 EDT by hand, age 12.9 h). The proposed cron line in `state_reason` is `20 6 * * 1 … report_lane_governance_packet.py --write --period weekly`.
- **Allowlist**: `$PY scripts/report_lane_governance_packet.py --period weekly`, lock `/tmp/tradeai_lane_governance_packet.lock` (`safe_flock`), timeout 600 s, `dry_run_arg --dry-run`, `live_arg --write`.
- **Workflows**: shadow `e6f62397d5ae2aa2`, live `175e44ef2a1614a4`; schedule `20 6 * * 1`, fidelity **PROPOSED** (INDEX note: "n8n would be the first scheduler-of-record. Needs the registry row flipped from NEVER_SCHEDULED").
- **Shadow evidence**: `mode dry_run RUN_DONE exit 0` and the signal mtime unchanged (`--dry-run` prints section counts, writes nothing — `report_lane_governance_packet.py:14`). **Canary**: one manual live fire → signal advanced, `json + md + receipt` under `$STATE` (registry `state_reason`); component `tradeai_lane_governance_packet` started once.
- **Cutover command result** (sandbox, §5.1): `cutover_lane.sh lane-governance-packet-weekly --workflow-id 175e44ef2a1614a4 --cadence "20 6 * * 1"` → **exit 2**, receipt `…-cutover-refused.json` with `problems: ["lane state is 'NEVER_SCHEDULED', not ACTIVE", "scheduler.kind 'none' has no host entry to retire", "scheduler.match / expression is empty; nothing to find on the host"]`. This is by design (`_cutover.py:385-393`): there is no host line to retire.
- **What is needed instead**: a registry-row PR (queue it behind W1/W2 under the board's registry lock; this packet does not touch the registry) setting the row to `state ACTIVE`, `scheduler {kind: n8n, expression: "175e44ef2a1614a4", match: "scripts/report_lane_governance_packet.py", cadence: "20 6 * * 1"}` with the canary receipt as `reason_evidence`. No crontab write, so **this lane is outside the cron-write grant**. After that PR is promoted, `rollback_lane.sh` would refuse (no applied cutover receipt) — rollback for this lane is "deactivate workflow `175e44ef2a1614a4`" plus a registry PR back to NEVER_SCHEDULED.
- **Readiness**: NO_GO — `BLOCKER: lane state is NEVER_SCHEDULED, not ACTIVE`; `host scheduler not measurable: kind 'none'`; no receipts; `age=12.92h limit=336.0h`.

### 3.7 `maturity-remeasure`

- **Live cron line** (line 1000): `40 6 * * 1 CUR=$(readlink -f $HOME/trade-ai-releases/portfolio-server/CURRENT) && cd "$CUR" && flock -n /tmp/tradeai_maturity_remeasure.lock $PY scripts/maturity_remeasure.py --write >> $HOME/trade-ai-releases/persistent-state/logs/maturity_remeasure.log 2>&1` — plain `flock -n`, same lock file as the allowlist.
- **Registry row** (`:2796`): kind `cron`, expression `40 6 * * 1 maturity_remeasure.py --write`, match `maturity_remeasure.py`, cadence 168 h, signal `data/governance/maturity_latest.json` (resolved under `$STATE`; last write 2026-10-05 06:40 EDT, age 76 h), ACTIVE.
- **Allowlist**: `$PY scripts/maturity_remeasure.py`, lock `/tmp/tradeai_maturity_remeasure.lock` (`flock`), timeout 600 s, `dry_run_arg []` (measure and print, write nothing), `live_arg --write`.
- **Workflows**: shadow `a26114588930ae9b`, live `e18d7849b4142927`; `40 6 * * 1` EXACT.
- **Shadow evidence**: `mode dry_run RUN_DONE exit 0`, signal mtime unchanged. **Canary** (weekly lane: doc 17 §5.4 "one manual natural-equivalent fire"): a live fire runs `--write`, which replaces `maturity_latest.json` **and appends a row to `data/governance/maturity_scores.jsonl`** (`maturity_remeasure.py:7,226`) — an off-schedule weekly datapoint. Operator decision: accept the extra row, or treat the first natural Monday fire (2026-10-12 06:40 EDT) as the canary and cut over only after it (readiness cannot reach GO without a live receipt, so this delays the lane past the Day-0 window).
- **Double-run proof**: shared `flock -n` → a conflict is `RUN_SKIPPED_LOCK reason flock_held`; zero such receipts in the window. The readiness note "safe_flock tradeai_maturity_remeasure: only 0 completion(s) on record (want 3)" is expected: the cron line uses plain `flock`, which writes no event log.
- **Cutover**: `cutover_lane.sh maturity-remeasure --workflow-id e18d7849b4142927 --cadence "40 6 * * 1"` [`--apply`]. **Rollback**: `rollback_lane.sh maturity-remeasure --apply`. **Readiness**: NO_GO (no receipts; `cron match='maturity_remeasure.py' present_once=True`; `age=76.09h limit=336.0h`).
- **Dry-run receipt**: exit 0; `would comment: 40 6 * * 1 CUR=$(readlink -f …) && cd "$CUR" && flock -n /tmp/tradeai_maturity_remeasure.lock …`; rollback dry-run exit 0.

### 3.8 `n8n-monitor-trade-ai` and 3.9 `n8n-monitor-dof` (n8n-native)

- **Live entry**: n8n workflows `s57KBllvqf6Jb5xF` (`n8n-monitor-trade-ai`) and `GXwhbRkwsGcYZxgn` (`n8n-monitor-dof`), both `active: true` in `docs/implementation/n8n-parallel/workflows/INDEX.json` (as of 2026-10-07T00:08Z), Schedule "Every 5 minutes" → HTTP GET → Code. Per the `n8n-lab-watchdog` registry note they "lost their targets when S1/S2 bound the API and DOF to loopback" — they fire and fail. **NOT VERIFIED** from this session (no n8n DB read).
- **Registry row**: none (`report_n8n_lane_readiness.py --lane n8n-monitor-trade-ai` → `NO_GO BLOCKER: no registry row`). **Allowlist**: none. **Cutover tool**: `cutover_lane.sh n8n-monitor-trade-ai --workflow-id e10e7c19321c906a --cadence "*/5 * * * *"` → exit 2, `REFUSED: no registry row for lane 'n8n-monitor-trade-ai'` (same for `-dof`, §5.1).
- **Generated files**: `n8n-monitor-trade-ai{,-shadow}.json` (`4e8c571514edcfc2` / `e10e7c19321c906a`) and `n8n-monitor-dof{,-shadow}.json` (`7b7392a0cfa5cdde` / `e10087387b964e87`) POST `{"lane_id": "n8n-monitor-trade-ai", "mode": …}` to the relay. Because the lane is not allowlisted the relay answers **403 `relay_lane_not_allowlisted`** (`n8n_run_relay.py:214`) and the Assert node fails. **Do not activate these four workflows**; they are placeholders until a registry row + allowlist entry exist (separate PR), and the watchdog lane already replaces them.
- **Proposed "cutover"** (n8n operator action, outside the cron-write grant): deactivate — never delete — the two legacy workflows: `docker exec m8m-n8n n8n update:workflow --id=s57KBllvqf6Jb5xF --active=false` and `… --id=GXwhbRkwsGcYZxgn --active=false`; INDEX note alternatively says rename to `-legacy` before importing the N1 set (name clash). Evidence: `docker exec m8m-n8n n8n list:workflow` shows both `active=false`; `n8n_export_workflows.py --write` refreshes `workflows/INDEX.json`. **Rollback**: `--active=true` on the same ids. Readiness: not applicable (no row) — record the two ids as DONE-BY-REPLACEMENT in the board.

---

## 4. Shadow → canary → cutover ladder summary (what must exist before `--apply`)

| gate | file that proves it | tool that reads it |
|---|---|---|
| relay + executor live | `systemctl --user show -p ActiveState tradeai-n8n-run-executor.service tradeai-n8n-run-relay.service`; `$STATE/data/runtime/n8n_runs/shadow/` exists | config-write packet |
| shadow receipt per lane | `$STATE/data/runtime/n8n_runs/<run_id>.json` `mode dry_run RUN_DONE exit 0` | `report_n8n_lane_readiness.py` (e), `n8n_cutover_checklist.py` "Shadow" |
| canary receipt per lane | same dir, `mode live RUN_DONE exit 0`, signal advanced, zero `RUN_SKIPPED_LOCK` | readiness (e), checklist "Canary" |
| host entry exactly once | `crontab -l` / timer enabled | readiness (b) |
| signal fresh | `< 2 × expected_cadence_hours` | readiness (c) |
| cutover dry-run receipt | `$STATE/data/runtime/n8n_cutover/<lane>-<ts>-cutover-dry-run.json` | checklist "Cutover dry-run" |
| cutover applied | `…-cutover.json` `applied: true`, `crontab_backup` set (cron) / `operator_command` (timer) | checklist "Cutover applied" |
| registry flipped + drift clean | row `kind: n8n`; `$PY scripts/check_lane_registry.py --fail-on-new --state-drift` exit 0 | checklist "Registry row flipped" |
| rollback dry-run (every lane) / real (first lane) | `…-rollback-dry-run.json` / `…-rollback.json` | checklist "Rollback proven" / "executed for real once" |
| acceptance | next natural fire's RunReceipt + fresh signal; `scripts/n8n_migration_board.py` row phase CUTOVER | checklist "Post-cutover natural fire" |

`$PY scripts/n8n_cutover_checklist.py --tranche N1` at 14:48Z: every lane 2/12 (workflows + registry row ticked;
the monitors 1/12), all evidence lines "none in data/runtime/n8n_runs" / "none in data/runtime/n8n_cutover".

---

## 5. Dry-run run log (sandbox; nothing on the host changed)

Sandbox: `SB=<scratchpad>/n1sandbox`; `crontab -l > $SB/crontab.saved`; `cp crontab.saved crontab.store`;
fake `crontab` = `if "$1" = -l: cat store; if "$1" = -: cat > store` (the test's `_fake_crontab`);
env `CRONTAB_CMD=$SB/crontab BACKUP_DIR=$SB/backups CUTOVER_DATE=2026-10-08 N8N_CUTOVER_LOCK=$SB/lock`.
After every phase: `cmp crontab.saved <(crontab -l)` → identical (live crontab untouched);
`git diff --quiet config/lane_registry.json` → clean (worktree registry untouched);
`$STATE/data/runtime/n8n_cutover/` still absent on the host.

### 5.1 Phase A — cutover dry-run, registry = this worktree (`CUTOVER_CODE_ROOT=$WT`, `TRADEAI_STATE_ROOT=$SB/stateA`)

| lane | command | exit | receipt (under `$SB/stateA/data/runtime/n8n_cutover/`) |
|---|---|---|---|
| n8n-pilot-dispatch | `cutover_lane.sh n8n-pilot-dispatch --workflow-id 078e8fcbea0c5020 --cadence "*/15 * * * *"` | 0 | `n8n-pilot-dispatch-20261008T144729Z-cutover-dry-run.json` |
| n8n-incident-fanin | `… --workflow-id 722fac0e043ea5c4 --cadence "*/5 * * * *"` | 0 | `n8n-incident-fanin-20261008T144729Z-cutover-dry-run.json` |
| n8n-research-intake-consumer | `… --workflow-id 21fd15d5f8a4c4da --cadence "*/15 * * * *"` | 0 | `n8n-research-intake-consumer-20261008T144729Z-cutover-dry-run.json` |
| crontab-snapshot-for-health-agent | `… --workflow-id c0d4c7845e5c4fcc --cadence "*/20 * * * *"` | 0 | `crontab-snapshot-for-health-agent-20261008T144729Z-cutover-dry-run.json` |
| n8n-lab-watchdog | `… --workflow-id 54069d7c36598de8 --cadence "*/5 * * * *"` | 0 | `n8n-lab-watchdog-20261008T144730Z-cutover-dry-run.json` (operator command printed) |
| lane-governance-packet-weekly | `… --workflow-id 175e44ef2a1614a4 --cadence "20 6 * * 1"` | **2** | `lane-governance-packet-weekly-20261008T144730Z-cutover-refused.json` |
| maturity-remeasure | `… --workflow-id e18d7849b4142927 --cadence "40 6 * * 1"` | 0 | `maturity-remeasure-20261008T144730Z-cutover-dry-run.json` |
| n8n-monitor-trade-ai | `… --workflow-id e10e7c19321c906a --cadence "*/5 * * * *"` | **2** | `n8n-monitor-trade-ai-20261008T144730Z-cutover-refused.json` ("no registry row") |
| n8n-monitor-dof | `… --workflow-id e10087387b964e87 --cadence "*/5 * * * *"` | **2** | `n8n-monitor-dof-20261008T144730Z-cutover-refused.json` ("no registry row") |

Quoted receipt (pilot-dispatch, trimmed, host paths as `$HOME`):

```json
{"schema": "CutoverReceipt@v1", "lane_id": "n8n-pilot-dispatch", "action": "cutover",
 "at": "2026-10-08T14:47:29+00:00", "applied": false, "mode": "dry-run",
 "code_sha": "ecf106cd85e408dea93c849ceb716f3f7fe9bc62", "lane_kind_before": "cron",
 "scheduler_before": {"kind": "cron", "expression": "*/15 * * * * n8n_pilot_dispatch.py --apply", "match": "scripts/n8n_pilot_dispatch.py"},
 "scheduler_after": {"kind": "n8n", "expression": "078e8fcbea0c5020", "match": "scripts/n8n_pilot_dispatch.py", "cadence": "*/15 * * * *"},
 "crontab_backup": null,
 "line_before": "*/15 * * * * cd $PROJ && set -a && . /run/user/$(id -u)/tradeai/env && set +a && TRADEAI_STATE_ROOT=$HOME/trade-ai-releases/persistent-state $PY scripts/n8n_pilot_dispatch.py --apply >> …",
 "line_after": "# RETIRED 2026-10-08 n8n-cutover n8n-pilot-dispatch */15 * * * * cd $PROJ && …",
 "operator_command": null, "registry_sha_before": "92dc5440e38d…", "registry_sha_after": null, "problems": [],
 "cadence": "*/15 * * * *", "workflow_id": "078e8fcbea0c5020"}
```

(`code_sha` is the pre-merge worktree head `ecf106cd8`; the branch was fast-forwarded to `72b0ce6be` afterwards — the registry rows are byte-identical between the two.)

Rollback dry-run against the un-flipped worktree registry (`rollback_lane.sh n8n-pilot-dispatch`) → exit 2,
`REFUSED: lane is kind 'cron', not n8n (nothing to roll back)` / `no applied cutover receipt … (pass --receipt)` —
which is why §5.2 applies the cutover inside the sandbox first.

### 5.2 Phase B — sandbox apply on a COPY of the registry (`CUTOVER_CODE_ROOT=$SB/code`, `TRADEAI_STATE_ROOT=$SB/stateB`)

`cutover_lane.sh <lane> … --apply` for the six cutover-able lanes: each printed
`applied: registry <sha12>→<sha12> backup=$SB/backups/crontab-20261008T1447…Z-pre-cutover-lane-<lane>.txt receipt=…-cutover.json`
(the watchdog apply has no backup: no crontab line). `diff crontab.saved crontab.store` = exactly **5 changed
lines**, each the original prefixed `# RETIRED 2026-10-08 n8n-cutover <lane> `. The registry copy diff is
42 lines = the six `scheduler` blocks and nothing else (no churn; `_serialise_registry` guard).

Then `rollback_lane.sh <lane>` (dry-run) for all six → exit 0 each, receipts
`<lane>-20261008T144759Z-rollback-dry-run.json` / `maturity-remeasure-20261008T144800Z-rollback-dry-run.json`, each
printing `scheduler after` = the original cron/systemd block and `would uncomment` the tagged line; the watchdog
prints `operator command … systemctl --user enable --now tradeai-n8n-lab-watchdog.timer`.

### 5.3 Phase B3 — real rollback rehearsal for the first lane (sandbox)

`rollback_lane.sh n8n-pilot-dispatch --apply` → exit 0, `applied: registry 804719a2c694→66a3e667af1f
backup=$SB/backups/crontab-20261008T144800Z-pre-rollback-lane-n8n-pilot-dispatch.txt receipt=n8n-pilot-dispatch-20261008T144800Z-rollback.json`.
After it: the `*/15 … n8n_pilot_dispatch.py --apply` line is uncommented (1 live match, 0 tagged lines) and the
copy's row is back to `{kind: cron, expression: "*/15 * * * * n8n_pilot_dispatch.py --apply", match: "scripts/n8n_pilot_dispatch.py"}`.
This is the rehearsal of §7's "first lane real rollback".

---

## 6. The one cron-write grant (batched, 30-minute window)

### 6.1 Grant text

```
PR #<n> sha <sha>: cutover 9 N1 lanes to n8n via cutover_lane.sh --apply (comment lines with dated tag; registry kind n8n); rollback_lane.sh per lane; no broker, send, deploy
```

`<n>` / `<sha>` = this packet's PR number and the head SHA shown by `gh pr view <n> --json headRefOid` at
grant time (a reason of the form `pr:N` never matches; the ledger needs "PR #N sha <sha>"). Scope the grant
actually exercises: five crontab line comments (lanes 1, 2, 3, 4, 7) and their registry flips; the watchdog
timer disable (lane 5) is a **config-write** action listed in the companion packet; lane 6 needs a registry
PR, lanes 8–9 an n8n deactivation — none of those three touches the crontab.

### 6.2 Preconditions (all must be true at T+0, each a quoted command output in the grant thread)

1. Config-write packet done: both units `ActiveState=active`; `$STATE/data/runtime/n8n_runs/shadow/` exists.
2. Per lane 1–5 and 7: shadow receipt and canary receipt present (§2.1, §2.2);
   `$PY scripts/report_n8n_lane_readiness.py --lane <lane>` = GO or GO_WITH_NOTES (today: NO_GO for all).
3. `crontab -l | grep -c 'n8n-cutover'` = 0 (no stale tags); `$PY scripts/check_lane_registry.py --fail-on-new --state-drift` exit 0.
4. Decide `CUTOVER_CODE_ROOT` (§2.3): recommended = a clean checkout of `main` at the promoted SHA
   (`git -C <checkout> rev-parse HEAD` = `readlink -f CURRENT` suffix), so the flipped rows are committed as
   the N1 registry PR immediately after the window; the receipts carry `registry_sha_before/after` as proof.
5. n8n `/healthz` 200 and gateway `/healthz` `ok:true` within the last minute.

### 6.3 Window (T = grant issue; every step quotes its receipt path)

| T+ | step | command / proof |
|---|---|---|
| 0 | snapshot | `crontab -l > ~/.local/state/tradeai/backups/crontab-$(date -u +%Y%m%dT%H%M%SZ)-pre-n1.txt` (the tool also backs up per lane) |
| 2 | lane 1 dry-run → apply | `cutover_lane.sh n8n-pilot-dispatch --workflow-id 078e8fcbea0c5020 --cadence "*/15 * * * *"` then `--apply`; `crontab -l \| grep -c '^# RETIRED 2026-10-08 n8n-cutover n8n-pilot-dispatch '` = 1 |
| 4 | lane 1 rollback dry-run → **real rollback** → re-cut | `rollback_lane.sh n8n-pilot-dispatch`; `rollback_lane.sh n8n-pilot-dispatch --apply` (line back, row `cron`); `cutover_lane.sh n8n-pilot-dispatch … --apply` again. Three receipts. |
| 8 | lane 2 | `cutover_lane.sh n8n-incident-fanin --workflow-id 722fac0e043ea5c4 --cadence "*/5 * * * *"` → `--apply` → `rollback_lane.sh n8n-incident-fanin` (dry-run) |
| 11 | lane 3 | `… n8n-research-intake-consumer --workflow-id 21fd15d5f8a4c4da --cadence "*/15 * * * *"` → `--apply` → rollback dry-run |
| 14 | lane 4 | `… crontab-snapshot-for-health-agent --workflow-id c0d4c7845e5c4fcc --cadence "*/20 * * * *"` → `--apply` → rollback dry-run |
| 17 | lane 7 | `… maturity-remeasure --workflow-id e18d7849b4142927 --cadence "40 6 * * 1"` → `--apply` → rollback dry-run (only if the canary decision in §3.7 was "accept") |
| 20 | lane 5 (if not deferred per §3.5) | `… n8n-lab-watchdog --workflow-id 54069d7c36598de8 --cadence "*/5 * * * *"` → `--apply` (registry only) → operator `systemctl --user disable --now tradeai-n8n-lab-watchdog.timer` under the config-write grant → rollback dry-run |
| 23 | n8n side | for each applied lane: live workflow active, shadow workflow inactive (`docker exec m8m-n8n n8n list:workflow`) |
| 25 | gates | `$PY scripts/check_lane_registry.py --fail-on-new --state-drift` exit 0; `$PY scripts/n8n_cutover_checklist.py --tranche N1 --write`; `$PY scripts/n8n_migration_board.py` (board row phase CUTOVER) |
| 28 | registry PR | commit the flipped rows from `CUTOVER_CODE_ROOT` with the receipt paths in the PR body; merge + promote before the next promote (else CURRENT reverts to `kind: cron` with the lines commented → ORPHANED) |
| 30 | close | grant window ends; next natural fires are the acceptance evidence (§4 last row) |

Deferred/out of grant: lane 6 registry PR (§3.6), lanes 8–9 deactivation (§3.8), the 6th alert unit and the 5
timer unit files (config-write packet §4).

---

## 7. Rollback-proof plan

- **First lane real rollback**: `n8n-pilot-dispatch` (T+4): `rollback_lane.sh n8n-pilot-dispatch --apply` must
  print `applied: registry …→… backup=… receipt=…-rollback.json`, `crontab -l` must show the original line 1024
  uncommented and zero `n8n-cutover n8n-pilot-dispatch` tags, and the row must read `kind: cron` again
  (sandbox rehearsal §5.3 did exactly this). Then re-cut. Deactivating `078e8fcbea0c5020` during the rollback
  minute is optional: the lane would at worst double-run once under the safe_flock lock.
- **Every other lane**: rollback dry-run only, receipt `…-rollback-dry-run.json` quoted in the thread.
- **Rollback target**: under five minutes (AGENTS.md §23.6): `rollback_lane.sh <lane> --apply` +
  `docker exec m8m-n8n n8n update:workflow --id=<live id> --active=false`; for the watchdog,
  `systemctl --user enable --now tradeai-n8n-lab-watchdog.timer` from the receipt's `operator_command`.
  The shadow workflow may stay active through a rollback (dry runs only, doc 17 §7).
- **If rollback itself refuses** (`found 0/2 tagged lines`, `match already live`): restore the single line by
  hand from `crontab_backup` named in the cutover receipt — still one line, never the whole backup.

---

## 8. Rollback triggers (doc 17 §7 / AGENTS.md §23.6, with the file that shows each)

| trigger | where it shows | threshold |
|---|---|---|
| `RUN_FAILED` after the last three cron runs succeeded | `$STATE/data/runtime/n8n_runs/*.json` `state RUN_FAILED` for the lane; prior cron success = the lane's `_last.json` `ok:true` ×3 (or the maturity log) | first occurrence |
| `output_signal` older than 2 × cadence after cutover | `report_n8n_lane_readiness.py --lane <lane>` line `output_signal: age=… limit=…`; lane monitor | age > limit (0.5 h, 0.2 h, 0.5 h, 0.68 h, 0.2 h, 336 h, 336 h for lanes 1–7) |
| `CRON_PRESENT_WHILE_SCHEDULER_N8N` | `check_lane_registry --fail-on-new --state-drift` (`scripts/lib/n8n_lane_host_conflict.py:79`) | any |
| relay bearer failures | `$STATE/data/runtime/n8n_relay/relay_log.jsonl` rows `relay_bad_bearer` (401); `n8n_run_relay_last.json` `auth_failures` | any increase |
| n8n `/healthz` down > 10 min | `n8n_lab_watchdog_last.json` non-200 across ≥ 2 consecutive probes → `n8n_incident_fanin` event | > 10 min |
| any `RUN_REFUSED` row | ledger `runs.state = 'RUN_REFUSED'`; receipt `reason` (`lane_not_allowlisted`, `bad_mode`, `mode_unavailable`) | any |

Rollback is the operator's decision on the finding (AGENTS.md §23.6).

---

## 9. NOT VERIFIED (cannot be measured from this session)

- Any shadow or canary receipt: the executor/relay are not installed; `data/runtime/n8n_runs/` does not exist.
- That `crontab -l` works inside the executor unit (lane 4 shadow proves it).
- The legacy monitor workflows' current state in n8n (INDEX says active; the registry note says they lost their targets); whether the operator prefers rename-to-`-legacy` or deactivate.
- That the n8n Schedule node fires at the same wall-clock minutes as cron for `*/5`, `*/15`, `*/20` (INDEX `schedule_fidelity: EXACT` is the generator's claim; the first canary receipt timestamps confirm it).
- The secret material in n8n (the `tradeai-run-relay` Header Auth credential) — names only were checked: `TRADEAI_N8N_RELAY_BEARER` and `TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N` are present (count 1 each) in `/run/user/<uid>/tradeai/env`; the per-unit env files `~/.config/tradeai/n8n-relay.env` and `n8n-gateway.env` are absent (optional `EnvironmentFile=-`).
- Whether the lane monitor on CURRENT reads the registry from CURRENT (assumed; it decides the ORPHANED window in §2.3).
- Release retention behaviour for a unit **linked** (not copied) into a release directory (config-write packet).
