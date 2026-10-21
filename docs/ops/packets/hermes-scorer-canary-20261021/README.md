# hermes-watchlist-scorer: n8n canary → cutover, 2026-10-21 (operator packet)

```
Status:      DRAFT (operator packet; nothing in it has run on the host)
as_of:       2026-10-21T13:15:00-04:00
Measured at: origin/main a6ac0ebbe + this branch (feat/hermes-scorer-n8n-canary-20261021); host not measured
Authority:   operator 2026-10-21 ~13:05 ET, verbatim: "push live now"; and 2026-10-21, verbatim:
             "comment out whats working now this can be a fallback". AGENTS.md §23.11, §23.12, §23.19, §23.25
```

## What this changes

The release moves lane `hermes-watchlist-scorer` from n8n **shadow** to **canary**. It uses the same cron-row shape as the
existing canary lanes (`agent-outcome-linker`, `watchlist-enrichment-sweep`), built with `scripts/n8n_cutover_wave.py`'s
own `canary_row` and `canary_contract` helpers:

- `config/lane_registry.json`: `scheduler.stage canary` and `dispatch.mode live`. The row stays `kind: cron` with the
  L451 `command_text`. A dated `canary` block records the operator waiver verbatim.
- `config/n8n_run_allowlist.json`: `live_arg []`, so the live argv equals the cron argv
  (`$PY scripts/hermes_watchlist_scorer.py --once`). The lock stays `/tmp/hermes_scorer.lock`, which is the lock in
  L451's `flock -n`, so n8n and cron never double-run.
- `config/n8n_health_contracts.json`: `stage canary`. The contract stays operator-REVIEWED, and the waiver is recorded
  in `review.stage_rereview.operator_words`.

**Operator waiver.** The usual 3-market-day shadow evidence wait (onboarding standard step 8) is waived by the operator.
The shadow evidence available at promotion, as the operator session reported it (`[DOC-CLAIM]`, not re-measured here):
RUN_DONE dry runs at 12:55 and 13:00 ET with exit 0, 1408 items, 812 scored and 0 errored. The shadow lane was
released in `a6ac0ebbe` (PR #1899).

**Why canary and not cutover in this release.** The operator asked for a same-day cutover with L451 kept as a
fallback. The cron line stays installed until the first live n8n RUN_DONE. In that in-between state, a cutover row
(`kind: n8n`, `expression: dispatcher`) fails two gates: `CRON_PRESENT_WHILE_SCHEDULER_N8N`
(`check_lane_registry --state-drift` on the host) and `CUTOVER_CRON_LINE_ACTIVE` (`check_registry_runtime_truth`).
Canary is the stage the gates accept for "n8n live + cron still installed". The row moves to cutover in the next
registry PR, after step 4 below (`n8n_cutover_wave.py cutover`). This is the CW1 wave procedure.

## Order (do not reorder)

| # | Step | Who / authority | Proof to check before the next step |
|---|---|---|---|
| 1 | **Release** this PR (merge, then serve the release as `portfolio-server/CURRENT`). | operator release grant naming the SHA (§24.8) | `bash 01_live_list_add.sh` (dry run) prints `ok` for all 4 served checks: stage canary, mode live, live_arg [], lock |
| 2 | **Live-list add**: `bash 01_live_list_add.sh --apply`. | config-write + service grant | the script prints `read back OK` and `<unit> active, live list carries hermes-watchlist-scorer` for both `tradeai-n8n-run-relay` and `tradeai-n8n-coordination-gateway` |
| 3 | **Verify a live n8n RUN_DONE with rows written.** Wait for the next `*/15` dispatcher slot. Do not force a run: the gateway refuses a free-form live key. | read-only | `bash 02_retire_cron_line.sh --since <UTC time of step 2>` (dry run) prints `proof: PASS`, meaning a ledger `live` `RUN_DONE` and receipt `produced_count >= 1`. A `RUN_SKIPPED_LOCK` means cron held the shared lock; wait for the next slot. A `RUN_FAILED` sends the lane back to cron (§23.12): stop and use rollback R2 |
| 4 | **Retire cron L451**: add the inventory approval and mint the cron grant (below), then `bash 02_retire_cron_line.sh --since <same> --apply`. | approved inventory row `cron:L449` + `cron` grant | the script prints `APPLIED`; `crontab -l \| grep hermes_watchlist_scorer` shows only `# RETIRED 2026-10-21 n8n-cutover hermes-watchlist-scorer ...` |
| 5 | **Registry PR → cutover** (agent): `python3 scripts/n8n_cutover_wave.py cutover --lanes hermes-watchlist-scorer --wave HS-20261021`, set the contract `stage` to `cutover`, then release it. | reviewed registry PR (§23.11) | `check_registry_runtime_truth.py --dry-run` shows no contradiction for the lane; the next natural slots stay `RUN_DONE` (monitored, not awaited, §8.1) |

### Step 4 inputs

The inventory key for the scorer line is **`cron:L449`**. `docs/implementation/n8n-maturity/cron-inventory/data/inventory.csv`
was numbered on 2026-10-09; the live crontab line today is L451. Add this line to `EXTRA_APPROVALS` in
`~/n8n-maturity-verification/cron-inventory/funnel/overlay.py`:

```python
 "cron:L449": "Approved 2026-10-21 (operator): hermes-watchlist-scorer n8n cutover - comment out crontab L451 as `# RETIRED 2026-10-21 n8n-cutover hermes-watchlist-scorer` after the first live n8n RUN_DONE ('push live now'; 'comment out whats working now this can be a fallback')",
```

The cron grant (operator only):

```bash
bin/guard grant cron --for 2h --uses 2 --reason "hermes-watchlist-scorer n8n cutover: comment out crontab L451 (inventory cron:L449) via docs/ops/packets/hermes-scorer-canary-20261021/02_retire_cron_line.sh; fallback 03_fallback.sh; AGENTS §23.12, §23.25"
```

Both edits use the repo's cutover tool, `scripts/n8n_cutover_wave.py comment-cron`. It backs up the crontab to
`~/.local/state/tradeai/backups/`, makes one write, and reads the result back. The line is commented, never deleted.
The tag is the repo's standard `# RETIRED <date> n8n-cutover <lane> <original line>`, which
`_cutover.py rollback --lane`, `check_registry_runtime_truth` and `03_fallback.sh` all parse. A
`(fallback: uncomment)` note inside the tag would be restored into the crontab line by those parsers, so it is not
added. This README and `03_fallback.sh` are where the fallback is documented.

## Rollback

Nothing is deleted at any step.

- **R1: put cron back** (after step 4): `bash 03_fallback.sh --apply` under the cron grant. It uncomments only the
  tagged line. Proof: `crontab -l | grep -v '^#' | grep -c hermes_watchlist_scorer` prints `1`. With both schedulers
  firing again, the shared flock keeps one run per slot.
- **R2: stop n8n firing it live** (after step 2): restore the live-list backup that step 2 printed
  (`~/.config/tradeai/n8n-live-lanes.env.bak-<ts>-hermes-scorer-canary`) and restart `tradeai-n8n-run-relay` and
  `tradeai-n8n-coordination-gateway`. The dispatcher's live requests are then demoted to dry_run. Proof: the next ledger
  row for the lane is `mode dry_run`. **Do R1 first if step 4 has already run**, or no scheduler writes.
- **R3: back to shadow in the repo**: revert this commit, which sets stage shadow, dispatch.mode dry_run and live_arg
  null, then release it.

## Guarantees kept

The lane's import closure reaches no sender, broker, order or `db_adapter` module. This is pinned by
`tests/test_hermes_scorer_n8n_shadow_20261021.py::test_scorer_closure_has_no_sender_broker_or_order_reach`,
`tests/test_lane_transitive_capabilities_20261015.py` and `tests/test_agents_policy_7_0_0_advisory_market_data.py`,
with no baseline or frozen-set exception added.

The lane appends `hermes_score_history` rows. A shared flock stops two runs from overlapping, but it does not stop a
second run later in the same slot. So, like every appending canary lane, it carries a **STAGED** effect key in
`config/n8n_effect_keys.json` (`cron_claim false`, `n8n_claim false`, so the executor claims nothing). The scorer
already skips the history INSERT when composite and rank are unchanged. The key is armed only by a later cutover
packet (`effect_claim.py set-owner`), never by this one.
