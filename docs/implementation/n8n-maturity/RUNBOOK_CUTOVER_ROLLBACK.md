# Runbook — cut a lane over from cron to n8n, and roll it back

```
Status:      ACTIVE
as_of:       2026-10-14T13:30:00-04:00
Measured at: source origin/governance/agents-advisory-market-data-lanes-20261014 73eebc5c1 (scripts/pipelines/cutover/_cutover.py,
             packets under ~/n8n-maturity-verification/packets/); CURRENT 8ae8a5b91-main-exact-phase2-20261013-234427
Owner:       platform (n8n maturity program)
Policy:      AGENTS.md §0 rails 6–8, §8.1, §9.3, §17, §23.2, §23.12, §23.14, and §23.21 (8.0.0, PROPOSED) — the operator's
             cutover standard of 2026-10-14 ~11:05 ET. Where this runbook and AGENTS.md differ, AGENTS.md wins.
```

One procedure for every n8n cutover — dispatcher rows (§23.12) and lane-specific workflows (§23.2). It restates the
rules; it adds none. Worked examples: `~/n8n-maturity-verification/packets/cutover-research-insight-extractor/OPERATOR.md`
(single lane, applied 2026-10-13 17:56 ET) and `packets/migration-batch/` (batch fire, verify, cutover, rollback).
Current lane status: [`MIGRATION_STATE_20261014.md`](MIGRATION_STATE_20261014.md). Picture:
[`N8N_RUNTIME_ARCHITECTURE.md`](N8N_RUNTIME_ARCHITECTURE.md).

## 0. Never

- Never cut over a §23.14 lane (broker, order, stop, position, paper execution, secret render, guard, release deploy,
  daemon, sender outside the named exceptions). The token test and `lane_dispatch.dispatch_eligible` refuse them.
- Never delete a crontab line — comment it (`# RETIRED <date> n8n-cutover <lane_id>`) (§0 rail 6).
- Never restore a whole crontab to roll back one lane — roll back per line (§23.2).
- Never override a market-hours or off-peak gate to make a forced fire land (§8.1).
- Agents never read the relay bearer or any `.env` (§24.7): the live fire through the relay is the operator's
  `fire_batch.sh`, or a fire the dispatcher makes itself at canary.

## 1. Readiness — the four criteria (AGENTS.md §23.21)

| # | Criterion | Evidence to record | How to get it |
|---|---|---|---|
| 1 | Defect fixed | PR number, merge SHA, CURRENT release id that serves it | `gh pr view`, `readlink ~/trade-ai-releases/portfolio-server/CURRENT` |
| 2 | n8n dry run passes | ledger `runs` row: lane, mode `dry_run`, `RUN_DONE`, finished_at; `RunReceipt@v1` with `output_signal` mtime unchanged; any earlier failure followed by a clean fire | natural shadow fire, or forced: `packets/migration-batch/fire_batch.sh <lanes.tsv>` (operator) then `verify_batch.py` (agent, read-only) |
| 3 | Lane regression tests pass | the command and its result, `TRADE_AI_CI=1` | `TRADE_AI_CI=1 python3 -m pytest -q <the lane's tests>` |
| 4 | ≥ 1 successful `live` n8n run with cron present under the shared lock | ledger row mode `live` `RUN_DONE`; `output_signal` mtime after the trigger; allowlist `lock` == every `flock` lock in the cron line; any overlapping cron fire shows `RUN_SKIPPED_LOCK` or ran harmlessly | row at `stage: canary`, `dispatch.mode: live`, allowlist `live_arg` set, lane in `TRADEAI_N8N_RELAY_LIVE_LANES` (config-write grant); dispatcher fire, or forced with `fire_batch.sh … --confirm-live` (operator) |

- A `RUN_SKIPPED_LOCK` alone is **not** criterion 4: it proves no double run, not that the n8n-started run works
  (§23.12, audit E C8).
- **Window-bound lanes** (market-hours or other clock gate in the cron line) fire inside the window — 09:30–16:00 ET
  on a trading day for RTH lanes. A deferral receipt from outside the window is not criterion 4.
- **No soak.** No number of clean days, and no natural shadow slot, is a condition (§23.21). Natural fires after
  cutover are monitored (§5), never awaited.
- **Before 8.0.0 is ratified,** `trade-ai-scalp-live` keeps the ACTIVE §23.3 / §23.14 text (cron fallback until three
  clean market days). Do not retire its cron line until `APPROVE_AGENTS_POLICY_8_0_0` is given.

## 2. Approvals — who decides what

| Step | Authority | Who |
|---|---|---|
| Registry row to `shadow` / `canary`, allowlist `live_arg` | merged, reviewed registry PR = the operator's scheduling decision (§23.11) | agent writes; operator merges (or the standing approval while one exists) |
| Health contract `REVIEWED` before canary / cutover | lane owner (§23.19) | owner |
| Lane in `TRADEAI_N8N_RELAY_LIVE_LANES`; executor drop-ins | `config-write` grant | operator mints; agent or operator applies |
| Forced live fire through the relay | the operator's shell (reads the bearer) | operator |
| Cutover `--apply` and every rollback `--apply` | one `cron` grant whose reason names **every lane id** in the wave (§23.12, §17) | operator mints (`bin/guard grant cron --for <≤12h> --uses <n> --reason "n8n-cutover <lane ids> …"`); agent or operator runs |
| Registry row flip on served CURRENT, if done in place | `release-write` grant naming the release | operator |
| Retiring `trade-ai-scalp-live`'s cron line | AGENTS 8.0.0 ratified (`APPROVE_AGENTS_POLICY_8_0_0`) plus the wave `cron` grant | operator |

Check an active grant with `bin/guard show` and strip colour codes before deciding a grant is absent
(`… | sed 's/\x1b\[[0-9;]*m//g'`). A grant's reason must name the PR or SHA it releases when it is a release grant
(§24.8).

## 3. Cutover — per lane, inside a wave

Run from CURRENT with the production state root:

```bash
cd ~/trade-ai-releases/portfolio-server/CURRENT
export TRADEAI_STATE_ROOT=~/trade-ai-releases/persistent-state

# 1. Dry run — reads crontab, writes a CutoverReceipt@v1 with applied:false and nothing else. Quote its output.
python3 scripts/pipelines/cutover/_cutover.py cutover --lane <lane_id> --workflow-id dispatcher

# 2. Apply — needs the active cron grant naming <lane_id>. One crontab write (backup first) + registry rewrite.
python3 scripts/pipelines/cutover/_cutover.py cutover --lane <lane_id> --workflow-id dispatcher --apply
```

- Dispatcher lanes take `--workflow-id dispatcher` — never `tradeai-dispatcher`, which is refused (§23.11). A
  lane-specific workflow passes its n8n workflow id.
- Multi-line lanes: `scheduler.match` as a list, or `--expect-lines K` (see `_cutover.py` docstring).
- systemd lanes: `_cutover.py` does not run `systemctl`; the receipt carries the `systemctl --user disable --now
  <timer>` for the operator under `config-write`.
- What it does: comments the exact line(s) `# RETIRED <date> n8n-cutover <lane_id>`, flips the row to
  `kind: n8n`, `expression: dispatcher`, `stage: cutover`, writes `CutoverReceipt@v1` to
  `$TRADEAI_STATE_ROOT/data/runtime/n8n_cutover/<lane_id>-<ts>.json`, backs the crontab up to
  `~/.local/state/tradeai/backups/`. It refuses on 0 or > 1 matches, an already-commented line, a non-ACTIVE row or
  a row already `kind: n8n`.
- Batch: `packets/migration-batch/cutover_batch/install.sh` (dry run by default; `--apply` under the cron grant) for
  every lane whose live fire `verify_batch.py` marked PASS.
- **Commit the registry change on main** in a PR the same day, so the next promote does not resurrect the cron-kind
  row (`cutover-research-insight-extractor/OPERATOR.md`).

## 4. Verify — immediately after apply

1. `crontab -l | grep -n "n8n-cutover <lane_id>"` shows the commented line; no uncommented line matches the lane.
2. `python3 scripts/check_lane_registry.py --fail-on-new --state-drift` reports no
   `CRON_PRESENT_WHILE_SCHEDULER_N8N` for the lane.
3. A forced dispatcher fire, or the next slot, gives a ledger `live` `RUN_DONE` and an advanced `output_signal`
   (§8.1 forced run); at the old cron minute only the dispatcher fires.
4. Re-measure and record (§6).

## 5. Monitor after cutover — and the rollback triggers

The first natural fires are monitored, not awaited (§23.12 last bullet, §8.1). Roll back the lane when any of these
holds: a natural fire `RUN_FAILED`, `RUN_TIMEOUT` or missing at its slot; `heartbeat-watch` raises `STALE_2X` for the
lane; the incident fan-in opens a finding for it; `check_lane_registry` reports a double schedule; the lane's output
diverges from what cron produced. One failure is enough; there is no grace count.

## 6. Rollback — per line

```bash
cd ~/trade-ai-releases/portfolio-server/CURRENT
export TRADEAI_STATE_ROOT=~/trade-ai-releases/persistent-state

# Dry run first; quote it.
python3 scripts/pipelines/cutover/_cutover.py rollback --lane <lane_id> [--receipt <CutoverReceipt path>]
# Apply under the cron grant.
python3 scripts/pipelines/cutover/_cutover.py rollback --lane <lane_id> [--receipt <CutoverReceipt path>] --apply
```

- Uncomments exactly the lines tagged `n8n-cutover <lane_id>` (refuses unless their count equals the receipt's) and
  restores `scheduler_before` from the cutover receipt. Never a wholesale crontab restore.
- Then take the lane out of the live path: remove it from `TRADEAI_N8N_RELAY_LIVE_LANES` (`config-write`) and set the
  row's `dispatch.mode` to `off` (or `dry_run` at `stage: shadow`) by registry PR (`lane_dispatch.DISPATCH_MODES`), so
  cron is the single scheduler again.
- systemd lanes: the receipt carries `systemctl --user enable --now <timer>` for the operator.
- Verify: the line is live again (`crontab -l`), the next cron slot writes the `output_signal`, and
  `check_lane_registry --state-drift` is clean. The lane rejoins a later wave by registry PR (§23.12).

## 7. What to record — every cutover and every rollback

In the PR body, the cron-inventory change-log row and `~/n8n-maturity-verification/REMEDIATION_PLAN.md` §9:

- lane id, wave, grant id(s) and their reasons, operator who approved;
- criteria 1–4 evidence from §1 (PR/SHA/release; dry-run ledger row; test command and result; live ledger row,
  `output_signal` path and mtime, lock equality, overlap evidence);
- the `_cutover.py` dry-run output (quoted), the apply `CutoverReceipt@v1` path, the crontab backup path and the
  crontab sha before and after;
- the post-cutover verification (§4) and the first natural fire when it comes;
- for a rollback: the trigger (§5), the rollback receipt and the verification.

Then update `ROADMAP.md` §0 and the Cutover_Tracker sheet of `cron-inventory/CRON_INVENTORY_LATEST.xlsx`.
