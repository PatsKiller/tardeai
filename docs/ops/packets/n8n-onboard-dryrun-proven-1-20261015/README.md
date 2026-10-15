# n8n onboarding ONB-1 (2026-10-15): operator packet

Operator directive 2026-10-15, "N8N Cutover Decision": every lane family moves to n8n except the F07 daemons and the
`registry_systemd` assets (`docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.csv`, disposition
`MIGRATE_N8N`). The cutover factory can only take a lane that is already **onboarded**, meaning it has an allowlist
entry whose dry run is proven write-free (AGENTS §2 / §23.21). This packet onboards six such lanes in **SHADOW**. The
generic dispatcher fires each lane's offline `--dry-run` on the lane's natural schedule, and the cron line keeps doing
the real work.

**At merge: inert.** Nothing reaches the host until a release that contains this PR is promoted. After promotion, the
served registry and allowlist add 6 dry-run fires. No cron line moves, so the scheduler of record does not change.

| Lane | Cron line (2026-10-15) | Class | Lock | Script change in this wave |
|---|---|---|---|---|
| `hermes-discovery-ingestors` | L687 `0 */2 * * *` | ingest | `/tmp/hermes_discovery_ingest.lock` (on the line) | `--dry-run` was env + DB + SELECTs, now an offline plan; the old preview is `--preview`; receipt gains `produced_count` |
| `youtube-cookie-health-check` | L397 `45 19 * * *` | monitor | `/tmp/youtube_cookie_health_check.lock` (on the line) | `--dry-run` opened the cookie jar and queried the DB, now an offline plan (it never opens the jar); old preview is `--preview`; LaneRunReceipt added next to the legacy ScheduledJobReceipt |
| `generate-weekly-docx` | L155 `0 21 * * 0` | report | `/tmp/weekly_docx.lock` (on the line) | `--dry-run` rendered 3 chart PNGs, now an offline plan; the old JSON print is `--preview`; a failed export exits 1 (was 0) and sends no "generated" notice; receipt |
| `strategy-weekly-review` | L279 `30 10 * * 0` | learn | `/tmp/strategy_weekly_review.lock` **PROPOSED** | `--dry-run` made logs/, appended the log, wrote pipeline_runs, rewrote the health_agent snapshot and could send Telegram; now an offline plan before any import side effect; `--preview` never snapshots or sends; errors exit 1 (was 0); receipt |
| `premarket-watcher` | L264 `*/15 7-9 * * 1-5` | ingest | `/tmp/premarket_watcher.lock` **PROPOSED** | `--dry-run` appended the log, wrote pipeline_runs and called EDGAR / StockTwits / Yahoo; now an offline plan; the old preview is `--preview`; a missing `.env` no longer breaks import; receipt |
| `cio-stance-classification-drain` | L987 `20 7,19 * * 1-5` | pipeline | `/tmp/cio_stance_classify.lock` (on the line) | none to the dry run (refactor M5); receipt gains `produced_count`. The row adopts its refactor shard 05 proposal unchanged (wave R2-05, frozen argv with `--apply`, which `--dry-run` wins over) |

## What each lane carries

- **Registry.** `scheduler.stage: shadow` and `scheduler.wave: ONB-1`, except cio-stance, which has R2-05.
  `command_text` is the exact cron line, and `scheduler.match` hits that one line only. The dispatch block is
  `{mode: dry_run, class, wave: W4, priority 5, retry_policy: none}`. `output_signal` is the lane's
  LaneRunReceipt@v1 (`data/runtime/<lane>_last.json`, `ok_at`). The row is hand-curated: `adopted_*` set,
  `generated_by` dropped. `reconcile_lane_registry.py` only reorders.
- **Allowlist.** `dry_run_arg [--dry-run]`, `live_arg null` and `market_gate false`. `env_names` holds no broker
  name, in `report` mode with a written reason. The lock is the cron line's `flock -n` lock where one exists. Where
  none exists the lock is marked PROPOSED, and canary stays blocked until a cron packet adds it.
- **Health contract.** Status REVIEWED: agent-reviewed against source, awaiting your REVIEW pass (SW4 / LD-W1
  precedent). Every `inventory_text` edge is replaced with a sourced edge. Each contract carries an
  `N8nExpectedOutput@v1` rule that passes FW-M6. The rule is *declared only*: no allowlist entry sets
  `output_receipt`, so the executor's verdict stays `declared_not_enforced`.
- **Receipt counts.** `produced_count`, `attempted_count` and `empty_reason` ride additively through
  `write_lane_receipt(output={...})`. The document stays `LaneRunReceipt@v1` (marker `output_fields:
  LaneRunReceipt@v2`), because v1 readers match the schema exactly.
- **Effect key.** All six lanes append and/or send, so each has a key, staged with `cron_claim: false` and
  `n8n_claim: false`. Their sends go only through the `telegram_alert` chokepoint (capability audit
  `chokepoint_send`, `direct_sender` 0).
- **Capability baseline.** Five of the six lanes reach `broker_module` / `order_placement` only lazily, through
  `db_adapter -> holdings_guard -> schwab_position_sync -> schwab_transport` or the `api_v2` / `options_engine`
  chains. None reaches either at import. These lanes join the DD01 operator-ruled set ("n8n ignor broker code it
  can't trade live ccontinue": the trading lock refuses every order), and `--check` reports new=0.
  strategy-weekly-review reaches neither.

## Selection rule and what was left out

From the MIGRATE_N8N lanes (family != F09, source != registry_systemd, no allowlist entry, `--dry-run` already in
source), a lane is taken when all of these hold:

- `dispatch_eligible` passes on its exact cron line;
- it makes no in-process model call (an `llm` lane needs a `cio-governed-bridge` `llm_route`, §23.4);
- its live path does no paper or broker execution;
- it has no direct sender.

The per-lane skip reasons for the rest of the set are in the PR description.

## Dry-run proof (`dry_run_proof.json`)

1. **Write recorder.** `tests/support/dry_run_write_recorder.py` runs each script as `__main__` under a CPython audit
   hook, with the cron line's live switches added before `--dry-run` and no DB or TELEGRAM variables set. The hook
   records:
   - every write-mode `open`;
   - every filesystem mutation;
   - every `socket.connect` / `getaddrinfo`;
   - every subprocess;
   - every `sqlite3.connect`.

   **All six: zero events, and no DB, HTTP, dotenv or send module imported.** A negative-control test proves the
   recorder catches a write, a mkdir, a connect and a child process.
2. **Real executor.** `scripts/n8n_run_executor.py --once` drains a **live** request for each lane, using a scratch
   ledger, scratch state and scratch locks with the real allowlist and registry. The stage clamp runs each one
   `dry_run` (`stage_clamp.reason = stage_shadow`). All six end `RUN_DONE` with exit 0 and their `DRY-RUN …` plan.
   The state root afterwards holds only the executor's own run receipts, and no lane receipt.

The same proof runs in CI as `tests/test_n8n_onboard_dryrun_proven_1_20261015.py`.

## Operator steps

1. Merge, then prepare and promote as usual (docs/ops/FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md, `release-write` grant naming
   this PR and SHA).
2. After the first natural slot of each lane, verify it on the ledger (read-only):
   ```bash
   sqlite3 "file:$HOME/trade-ai-releases/persistent-state/data/governance/n8n_coordination_ledger.sqlite?mode=ro" \
     "SELECT lane_id, state, mode, finished_at FROM runs WHERE lane_id IN ('hermes-discovery-ingestors','youtube-cookie-health-check','generate-weekly-docx','strategy-weekly-review','premarket-watcher','cio-stance-classification-drain') ORDER BY requested_at DESC LIMIT 20"
   ```
   Expect `RUN_DONE` / `dry_run`. generate-weekly-docx and strategy-weekly-review fire on Sunday only.
3. **Rollback:** revert the PR and promote. Alternatively, set the lane's `dispatch.mode` to `off` in a registry PR.
   No host change is needed, because the cron lines never moved.

**Canary is not part of this packet.** Moving a lane to canary needs four things:

- the AGENTS §23.21 standard: fix, dry run, regression, then ≥1 live n8n run with cron present under the shared flock;
- a cron flock for the two PROPOSED locks;
- the lane's effect key armed;
- for the five chokepoint senders, an explicit decision that their live send stays on the cutover path.
