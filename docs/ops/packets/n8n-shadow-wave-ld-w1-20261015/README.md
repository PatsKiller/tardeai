# n8n shadow wave LD-W1 (2026-10-15): operator packet

This is wave **M1** of the lane disposition table (`docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.md`).
Six MIGRATE_N8N leaf lanes join the fabric in **SHADOW**. The generic dispatcher fires each lane's offline `--dry-run`
on the lane's natural schedule, and the cron line keeps doing the real work.

**At merge: inert.** Nothing reaches the host until a release that contains this PR is promoted. After promotion, the
served registry and allowlist add 6 dry-run fires. No line moves, so the scheduler of record does not change.

| Lane | Cron line (2026-10-15) | Class | Lock | Script change in this wave |
|---|---|---|---|---|
| `opening-intelligence-render` | L796 `15 9 * * 1-5` | report | `/tmp/opening_intel.lock` (on the line) | none (shard 03 dry run + receipt) |
| `hermes-discovery-scorecard` | L837 `30 5 * * *` | report | `/tmp/hermes_discovery_scorecard.lock` PROPOSED | none (shard 04) |
| `wire-advisory-lessons` | L606 `30 */6 * * *` | learn | `/tmp/wire_lessons.lock` (on the line) | none (completion 119) |
| `incubator-rolloff-engine` | L269 `0 10 * * 1-5` | hygiene | `/tmp/incubator_rolloff.lock` PROPOSED | offline `--dry-run` (wins over `--apply`); old DB preview → `--preview` (READ ONLY); receipt on `--apply` |
| `pattern-extractor` | L790 `0 9 1 * *` | learn | `/tmp/pattern_extractor.lock` (on the line) | offline `--dry-run` before the module's `.env` load and log handler; old preview → `--preview`; receipt on a real run |
| `goal-gate-bridge` | L983 `35 * * * *` | report | `/tmp/goal_gate_bridge.lock` PROPOSED | `--dry-run` (wins over `--write-measurements`); receipt on `--write-measurements` |

## What each lane carries

- **Registry.** `scheduler.stage: shadow` and `wave: LD-W1`. `command_text` is the exact cron line. The dispatch block is
  `{mode: dry_run, class, wave: W4, priority 5, retry_policy: none}`. `output_signal` is the lane's LaneRunReceipt@v1.
  The row is hand-curated: `adopted_*` set, `generated_by` dropped.
- **Allowlist.** `command` is `[$PY, <script>]` with no live switch. `dry_run_arg` is `[--dry-run]` and `live_arg` is
  `null`. `env_names` holds no broker name, in report mode. The lock is the cron line's `flock -n` lock where one exists.
  Where none exists the lock is marked PROPOSED, and canary stays blocked until a cron packet adds it.
- **Health contract.** Status is REVIEWED. The contract was agent-reviewed against source and awaits your REVIEW pass,
  as in the SW4 precedent.
- **Effect key.** Only `incubator-rolloff-engine` appends rows (one `incubator_events` row per roll-off), so it alone
  has one. It is staged with `cron_claim: false` and `n8n_claim: false`.

## Selection rule and what was left out

A lane was selected only if it met all of these:

- one script on the line;
- no `--send`, `--telegram` or `--alert`;
- no LLM wrapper or model call;
- no send, broker module or account read anywhere in the import closure (`advisory_lane_guard.scan_entry`).

These candidates were held back:

- **`agent-recommendation-normalizer`:** SW4 P0, a random `recommendation_id` on every run.
- **`sec-fundamentals-ingest` and `sec-filings-feed`:** the import closure reaches `api_v2`.
- **`defense-recommendations`:** options and holdings advice.
- **`symbol-enrichment` and `indicator-engine`:** these go to the RETIRE packet instead.
- **`build-symbol-profiles-at-0-19` and `drain-discovery-backlog`:** both pass the filter, but each belongs to a
  refactor shard 05-08 proposal that `tests/test_refactor_shards_05_08_locks_20261011.py` pins as held. Adopting them is
  that owner's PR.

Strict criteria gave 6 lanes, not the 15-25 the brief asked for. The remaining pool needs refactor before shadow; those
are waves M3 and M4 in the table.

## Dry-run proof (`dry_run_proof_20261015.json`)

The real executor, `scripts/n8n_run_executor.py --once`, ran against a scratch ledger, scratch state and scratch locks,
with the real allowlist entries and the real registry. It received a **live** request for each of the 6 lanes.

- The stage clamp ran each one `dry_run`. The receipt shows `stage_clamp.reason = stage_shadow`.
- All 6 ended `RUN_DONE` with exit 0 and the lane's `DRY-RUN …` plan in `stdout_tail`.
- The scratch state root afterwards held only the executor's own receipts. No lane receipt or other state file was
  written.

The same proof runs in CI as `tests/test_shadow_wave_ld_w1_20261015.py`.

## Operator steps

1. Merge, then prepare and promote as usual (docs/ops/FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md, `release-write` grant naming this PR and SHA).
2. After the first natural slot of each lane, verify it on the ledger (read-only):
   ```bash
   sqlite3 "file:$HOME/trade-ai-releases/persistent-state/data/governance/n8n_coordination_ledger.sqlite?mode=ro" \
     "SELECT lane_id, state, mode, finished_at FROM runs WHERE lane_id IN ('opening-intelligence-render','hermes-discovery-scorecard','wire-advisory-lessons','incubator-rolloff-engine','pattern-extractor','goal-gate-bridge') ORDER BY requested_at DESC LIMIT 20"
   ```
   Expect `RUN_DONE` / `dry_run`. `pattern-extractor` fires only on the 1st of the month.
3. **Rollback:** revert the PR and promote. Alternatively, set the lane's `dispatch.mode` to `off` in a registry PR. No
   host change is needed, because the cron lines never moved.

**Canary is not part of this packet.** Moving a lane to canary needs four things:

- the AGENTS §23.21 standard: fix, dry run, regression, then ≥1 live n8n run with cron present under the shared flock;
- a cron flock where the lock is PROPOSED;
- an armed effect key for `incubator-rolloff-engine`;
- the §23.23 migration freeze lifted: the Run Lane fault matrix and the run-outcome callback.
