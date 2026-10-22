# Runbook — cut a lane over from cron to n8n, and roll it back

```
Status:      ACTIVE
as_of:       2026-10-21T15:50:00-04:00
Measured at: origin/main 7faa8cddf (scripts/n8n_cutover_wave.py, scripts/pipelines/cutover/_cutover.py,
             scripts/n8n_cutover_checklist.py, docs/ops/packets/hermes-scorer-canary-20261021/)
Owner:       platform (n8n maturity program)
Policy:      AGENTS.md §0 rules 6–8, §8.1, §9.3, §17, §23.2, §23.12, §23.14, §23.23 (4), §23.25, and §23.21
             (16.0.0, PROPOSED; rebuilt from 8.0.0 / PR #1727). Where this runbook and AGENTS.md differ, AGENTS.md wins.
```

One procedure for every n8n cutover. It restates the rules and adds none. First drafted for PR #1727 (2026-10-14,
unmerged); updated for the cutover factory (`scripts/n8n_cutover_wave.py`, 2026-10-15), effect keys and the
2026-10-21 `hermes-watchlist-scorer` packet, which is the current worked example
(`docs/ops/packets/hermes-scorer-canary-20261021/README.md`). Current counts:
[`MIGRATION_STATE_20261021.md`](MIGRATION_STATE_20261021.md). Picture: [`N8N_RUNTIME_ARCHITECTURE.md`](N8N_RUNTIME_ARCHITECTURE.md).

## 0. Never

- Never cut over an F07 daemon or a `registry_systemd` asset (§23.25), or a lane `lane_dispatch.dispatch_eligible`
  refuses.
- Never delete a crontab line: comment it as `# RETIRED <date> n8n-cutover <lane> <original line>` (§0 rule 6). Do not
  add free text inside the tag; the rollback parsers would restore it into the line.
- Never restore a whole crontab to roll back one lane: roll back per line (§23.2).
- Never override a market-hours or off-peak gate to make a forced fire land (§8.1).
- Agents never read the relay bearer or any `.env` (§24.7), and never force a live run of an F09 lane (§23.25).

## 1. Readiness — the four criteria (§23.21)

| # | Criterion | Evidence to record | How to get it |
|---|---|---|---|
| 1 | Defect fixed | PR, merge SHA, the CURRENT release that serves it | `gh pr view`; `readlink ~/trade-ai-releases/portfolio-server/CURRENT` |
| 2 | n8n dry run passes | ledger row mode `dry_run` `RUN_DONE`; receipt `output_signal` unchanged; any earlier failure followed by a clean fire | the shadow slot, or a forced `dry_run` fire through `coordination/run` (§8.1) |
| 3 | Lane regression tests pass | command and result, `TRADE_AI_CI=1` | `TRADE_AI_CI=1 python3 -m pytest -q <the lane's tests>` |
| 4 | ≥ 1 successful `live` n8n run with the cron line present under the shared lock | ledger row mode `live` `RUN_DONE`; `output_signal` advanced after the trigger; allowlist `lock` == the cron line's `flock` lock | the dispatcher's next slot once the lane is canary and in the live list; or a live fire the operator forces inside the lane's window |

- `python3 scripts/n8n_cutover_wave.py evidence --lanes <ids> --since <ISO>` reads the ledger (read-only) for (2) and (4).
- A `RUN_SKIPPED_LOCK` alone is **not** (4): it proves no double run, not that the n8n run works (§23.12).
- **The live run is usually the slot.** The gateway refuses a free-form live key (`run_key_namespace_refused`), so a
  keyed lane needs its `d:` slot. An operator-forced live fire that the gateway accepts counts when it is inside the
  lane's window; record it in the acceptance packet as `OPERATOR_FORCED_LIVE` with `forced_by: "operator"`,
  `operator_ref` (the operator's word or grant id) and `window_gate_overridden: false`
  (`scripts/n8n_cutover_checklist.py`).
- **No soak.** No number of clean days and no natural shadow slot is a condition under §23.21. **Until 16.0.0 is
  ratified,** onboarding step 8 (natural shadow slot) and the `trade-ai-scalp-live` three-clean-market-day fallback
  (§23.3, §23.14) are still ACTIVE text: a lane moves past them only on the operator's per-lane waiver, recorded
  verbatim (registry `canary.operator_waiver`, contract `review.stage_rereview`), as `hermes-watchlist-scorer` did on
  2026-10-21 ("push live now").

## 2. Approvals — who decides what

| Step | Authority | Who |
|---|---|---|
| Canary rows (registry `stage: canary`, `dispatch.mode: live`; allowlist `live_arg`, lock; contract stage; effect key) | merged, reviewed registry PR (§23.11) | agent writes with `n8n_cutover_wave.py apply`; operator merges |
| Health contract `REVIEWED` before canary / cutover | lane owner (§23.19) | owner; stage refresh with `contract-canary --operator-rereview "<words>"` |
| Release serving the canary rows | release grant naming the SHA (§24.8) | operator |
| Lane in `TRADEAI_N8N_RELAY_LIVE_LANES`, relay and gateway restart | `config-write` + service grant | operator mints; packet `01_*` script applies |
| Effect-key owner move (keyed lanes) | `cron` grant (fabric) | `effect_claim.py set-owner`, packet `02_effect_owners.sh` |
| Comment the cron line(s) | approved cron-inventory row + one `cron` grant naming every lane id in the wave (§23.12, §17) | operator mints; `n8n_cutover_wave.py comment-cron --apply` |
| Dispatcher-row PR after the lines are commented | reviewed registry PR | agent writes with `n8n_cutover_wave.py cutover`; operator merges |

Check an active grant with `bin/guard show` and strip colour codes before deciding it is absent.

## 3. Cutover — a wave, with the factory

From the served release, production state root:

```bash
cd ~/trade-ai-releases/portfolio-server/CURRENT
export TRADEAI_STATE_ROOT=~/trade-ai-releases/persistent-state

python3 scripts/n8n_cutover_wave.py plan --lanes <ids> --json          # verdict per lane; SKIP carries the gate's reason
python3 scripts/n8n_cutover_wave.py apply --lanes <ids> --wave <W>     # in a branch: canary rows, then a reviewed PR
python3 scripts/n8n_cutover_wave.py packet --lanes <ids> --wave <W> --out <dir>   # operator packet, dry run by default
```

Then, after the PR is merged and served: the packet's live-list step, the effect-owner step for keyed lanes, the
live evidence for every lane (§1 (4)), and

```bash
python3 scripts/n8n_cutover_wave.py comment-cron --lanes <ids>            # dry run: prints the exact edits; quote it
python3 scripts/n8n_cutover_wave.py comment-cron --lanes <ids> --apply    # cron grant: backup, one write, read back
python3 scripts/n8n_cutover_wave.py cutover --lanes <ids> --wave <W>      # in a branch: §23.11 dispatcher rows
```

- The row stays `kind: cron`, `stage: canary` while its line is live; a cutover row with a live line fails
  `CRON_PRESENT_WHILE_SCHEDULER_N8N` and `CUTOVER_CRON_LINE_ACTIVE`.
- Single lane: `scripts/pipelines/cutover/_cutover.py cutover --lane <id> --workflow-id dispatcher` (dry run first,
  `--apply` under the cron grant) comments the line and rewrites the row in one step (§23.12).
- systemd lanes: the receipt carries the `systemctl --user disable --now <timer>` for the operator under `config-write`.

## 4. Verify — immediately after the comment

1. `crontab -l | grep -n "n8n-cutover <lane>"` shows the commented line; no uncommented line matches the lane.
2. `python3 scripts/check_lane_registry.py --fail-on-new --state-drift` and
   `python3 scripts/check_registry_runtime_truth.py --dry-run` report nothing for the lane once the dispatcher-row
   PR is served.
3. The next slot gives a ledger `live` `RUN_DONE` and an advanced `output_signal`; at the old cron minute only the
   dispatcher fires.

## 5. Monitor after cutover — and the rollback triggers

Natural fires are monitored, not awaited (§23.12 last bullet, §8.1). Roll the lane back when a natural fire is
`RUN_FAILED`, `RUN_TIMEOUT` or missing at its slot; `heartbeat-watch` raises `STALE_2X` for it; the incident fan-in
opens a finding for it; a double schedule is reported; or its output diverges from what cron produced. One failure is
enough.

## 6. Rollback — the commented line is the fallback

```bash
python3 scripts/pipelines/cutover/_cutover.py rollback --lane <lane_id>           # dry run first; quote it
python3 scripts/pipelines/cutover/_cutover.py rollback --lane <lane_id> --apply   # cron grant
```

- It uncomments exactly the lines tagged `n8n-cutover <lane_id>`. A wave packet's fallback script does the same for
  its lanes (`03_fallback.sh` in the hermes packet). With both schedulers firing again, the shared lock keeps one run
  per slot.
- Then take the lane out of the live path: restore the live-list backup (or remove the lane) and restart the relay and
  gateway, move the effect-key owner back to `cron` for keyed lanes, and set the row back by registry PR.
- A line commented with any other tag (for example the 2026-10-16 `# N8N-ONLY TEST` line of
  `hermes-momentum-catalyst-scalp`) is not parsed by `_cutover.py`; uncomment it by hand under the cron grant.

## 7. What to record — every cutover and every rollback

In the PR body and the cron-inventory change-log row: lane id, wave, grant ids and reasons, the operator's words
(and any waiver, verbatim); criteria (1)–(4) evidence from §1; the dry-run outputs quoted; the crontab backup path;
the post-cutover verification (§4); for a rollback, the trigger (§5) and the verification.
