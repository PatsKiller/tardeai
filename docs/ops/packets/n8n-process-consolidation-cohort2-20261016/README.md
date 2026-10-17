# n8n process consolidation, cohort 2 (2026-10-16): Hermes learning consumers fire on verified learning

Operator direction (2026-10-16): build explicit n8n flows that branch on verified results, trigger downstream work
when its inputs are ready, and replace unnecessary polling with events or watermarks. Cohort 1 (#1826) added
`run_done` triggers with `require_verdict`. This cohort applies them to the Hermes learning consumers.

## The bug

`discovery_yield_builder` and `tag_lift_discovery` read what Hermes outcome learning produces: the graded
`hermes_outcome_ledger` and `state/hermes/outcome_bus.json` plus its history snapshot. Outcome learning moved to
10:50-11:35 ET on 2026-08-21. The consumers stayed on the overnight clock: 03:45 / 03:50 ET until 2026-10-10, and
the 02:20 ET `hermes_overnight` night stage since the C1 flip on 2026-10-11. So every consumption read learning
output that was 15-16 hours old.

## Dependency map

```
hermes_learning learn stage (10:50 ET n8n fabric / 11:20 ET cron fallback, PIPELINE_EFFECT_CLAIM)
  outcome_grader ──> hermes_outcome_ledger (graded rows) ─────────────────> discovery_yield_builder
  tag_engine
  outcome_feedback_agent ──> state/hermes/outcome_bus.json + outcome_bus_history/<UTC stamp>_ofb_*.json ──> tag_lift_discovery
  outcome_learning ──> hermes_weight_calibration           (completion = the WATERMARK both consumers key on)
  config_governor
```

The trigger is the verified completion of `outcome_learning`, the last learning step before the governor. Its
inputs, the grader ledger and the outcome bus, are complete by then.

## What changed

| Item | Where | Runtime effect on merge+promote |
|---|---|---|
| Event lane | `config/lane_registry.json`: `hermes-discovery-yield-on-learning` (kind n8n, expression dispatcher, stage **shadow**, dispatch `dry_run`, W5, class learn). Trigger: `run_done` on `hermes-learning-outcome-learning`, `require_verdict [produced, empty_allowed]`. Schedule `20 2 * * *` mirrors the clock | Dry-run fires only. It stays inert until `hermes-learning-outcome-learning` writes a verified live RUN_DONE, which happens once the hermes-learning fabric process runs on n8n. Today the ledger has zero rows for it |
| Allowlist | `config/n8n_run_allowlist.json`: `live_arg null`, `dry_run_arg ["--dry-run"]`, command `$PY scripts/hermes_discovery_yield_builder.py --json --learning-watermark event`, lock `/tmp/hermes_yield_builder.lock` (flock; a dry run takes `.dryrun`) | Same |
| Health contract | `config/n8n_health_contracts.json`: `hermes-discovery-yield-on-learning`, agent-reviewed against source and awaiting the operator's REVIEW pass (SW4 precedent), `review_by` 2026-10-30 | none |
| Tag-lift event lane | **Proposed only, NOT wired** (`config/learning_watermark.json` `event_lane_blocked`). An n8n lane running `hermes_tag_lift_discovery.py` reaches broker_module / order_placement transitively through `db_adapter -> holdings_guard -> schwab_position_sync -> schwab_transport` (lazy imports). `config/n8n_lane_capability_baseline.json` is shrink-only and frozen to the operator's DD01 ruling of 2026-10-15, so admitting `hermes-tag-lift-on-learning` needs the operator to extend that ruling. **OPERATOR DECISION.** Until then tag-lift runs from the guarded clock only | none |
| Watermark guard | `scripts/lib/learning_watermark.py`, `config/learning_watermark.json` | The clock path (night-stage steps, no flag = clock) is guarded: it records what it consumed and no-ops, with a recorded reason, on an already-consumed watermark |
| Consumers | `scripts/hermes_discovery_yield_builder.py`, `scripts/hermes_tag_lift_discovery.py`: `--learning-watermark event\|clock` | See the guard row |
| Report | `scripts/report_learning_watermark.py` (read-only) | none |
| Tests | `tests/test_n8n_consolidation_cohort2_20261016.py`, registered as `n8n_consolidation_cohort2_20261016` | none |

The night-stage manifest is **unchanged**. The step commands stay verbatim slices of the cron lines (C1
equivalence). The clock guard comes from the scripts' default trigger, not from a new argv.

### The watermark (verified, never exit-code)

The watermark is the newest verified completion of `outcome_learning` from either scheduler:

- **n8n:** a ledger `RUN_DONE` (live) row whose receipt `output_verdict` is `produced` or `empty_allowed`. This uses
  the executor's verdict, read with the same function as `coordination/due`.
- **cron runner:** the `PipelineStepReceipt@v1` for the step (status ok, not dry), corroborated by an outcome_bus
  history snapshot stamped within 3600 s before it. That snapshot is the artifact tag-lift actually reads. A
  receipt without the snapshot is `upstream_unverified`.

### Decisions (pure `decide`, recorded only on live runs)

| trigger | no verified upstream | same / not-newer watermark | newer watermark |
|---|---|---|---|
| event | **no fire**. The reason is `upstream_missing`, `upstream_unverified` or `reader_error:*`. At the due level the event emits no item | **no fire**: `watermark_already_consumed_by_<event\|clock>` / `watermark_not_newer` | run |
| clock | run: `clock_fallback_*` (the pre-cohort behaviour) | **recorded no-op**, unless the last consumption is older than 36 h, in which case it runs: `stale_consumption_ceiling` | run (`new_watermark`) |

State lives in `<state_root>/data/runtime/learning_watermark/<consumer>.json`
(`LearningWatermarkConsumer@v1`). It holds the consumed watermark plus the last 30 decisions with reasons. Both
triggers share it. The event's due-level watermark is the consumer's own LaneRunReceipt, so a clock run also
blocks a re-fire there.

## Trigger state shipped: SHADOW

- The yield-builder event lane is `dry_run` with `live_arg null`. The tag-lift event lane is not wired (it is
  blocked on the DD01 operator decision above).
- An event fire runs `--dry-run --learning-watermark event`, which reports `WOULD RUN` / `WOULD NO-OP` with a
  reason and records nothing.
- The night-stage clock remains the live consumer, now watermark-aware.
- Going live is a separate PR after shadow proof (≥1 natural verified fire, decisions matching): set allowlist
  `live_arg` to `["--apply"]`, set dispatch `mode: live`, and add the lane to `TRADEAI_N8N_RELAY_LIVE_LANES`.
- Tag-lift needs the DD01 ruling first, then the same shadow → live steps with `live_arg []`.
- Prerequisite: the hermes-learning fabric process must run live on n8n. Without it the run_done trigger has no
  upstream row.

## Before / after staleness (input age at consumption)

Measured with `python scripts/report_learning_watermark.py --project-root ~/trade-ai-releases/portfolio-server/CURRENT --now 2026-10-16T21:00:00Z`.
Pre-C1 values come from `logs/hermes_outcome_learning.log` `ts` and `logs/hermes_discovery_yield.log`
`generated_at`.

| consumer | era | consumption time | learning completion | input age |
|---|---|---|---|---|
| discovery_yield_builder | to 2026-10-10 (cron 03:45 ET) | 07:45Z | 15:35Z the day before | **16.2 h** (weekdays mostly PEAK_SKIP, e.g. 10-08 and 10-09; ran 10-03, 10-04, 10-10, 10-11) |
| discovery_yield_builder | since C1 (02:20 night stage) | 06:20Z, 4/4 nights | 14:54Z the day before | **15.43 h** (median = max) |
| tag_lift_discovery | since C1 | 06:20Z | | **never consumed**: 4/4 nights `PEAK_SKIP` (06:20Z is inside the DeepSeek official peak 06-10Z Mon-Fri). Last real run 2026-10-11 07:50Z, a Saturday |
| yield builder (wired) / tag-lift (once ruled) | **event-driven (projected)** | verified RUN_DONE + dispatch lag | | **~1-2 min**: the run_done event start lag on the live router (`e:` rows of news-to-catalyst / research-insight-extractor, n=38) has median 61.6 s; p95 1,261 s comes from those lanes' coalesce/debounce. Runtime is <1 s (yield 0.2-0.3 s, tag-lift ~0.5 s) |

Tag-lift makes no model call: `tag_lift.py` and its `hermes_discovery` imports contain no LLM client. A tag-lift
event lane would run it without the off-peak wrapper, and at ~14:55Z it is outside the official peak anyway. So,
once the operator rules, event-driven tag-lift would consume every weekday instead of weekends only. No LLM route is involved, so the OAuth-first policy
is unaffected.

Until the fabric process runs live on n8n, learning arrives through the 11:20 ET cron fallback, the event stays
inert, and the clock keeps consuming at ~15.4 h. The guard now records each consumption and refuses a second pass
over one outcome bus.

## Operator crontab follow-up (not done here; propose only)

The 03:45 / 03:50 lines are already retired (commented `# RETIRED 2026-10-11 c1-manifest hermes_overnight`). Both
steps run inside:

```
20 2 * * * cd $PROJ && bash scripts/pipelines/run_hermes_pipeline.sh --manifest config/pipelines/hermes_overnight.json --stage night --apply >> logs/pipelines/hermes_cron.log 2>&1  # TRADEAI_LANE hermes-overnight-pipeline-night (parallel dry-run)
```

**Now:** no crontab change. The clock stays the fallback.

**After the event lanes go live:** the night-stage steps remain the watermark-aware fallback and no-op on consumed
learning, so the crontab can stay as it is. Removing the two steps from the night stage would be a manifest PR,
not a crontab edit. The only optional crontab change is to move the fallback after the learning window, so that
the clock and the cron learn fallback don't sit 15 h apart. Proposed line, operator decision:

```
45 11 * * * cd $PROJ && bash scripts/pipelines/run_hermes_pipeline.sh --manifest config/pipelines/hermes_overnight.json --stage night --apply >> logs/pipelines/hermes_cron.log 2>&1  # TRADEAI_LANE hermes-overnight-pipeline-night
```

This is not recommended as-is: it moves industry_novelty and siem_backlog too, and puts tag-lift's wrapper at
15:45Z, which is off-peak and so would change its cadence. The preferred end state is the event lanes live with
the 02:20 stage as the guarded fallback.

## Rails

- No broker.
- No credential reads: names only in env_names. The guard opens the coordination ledger sqlite `mode=ro`.
- No production DB writes, no crontab or systemd edits, no restarts, no sends.
- The dry runs quoted in the PR used a scratch `TRADEAI_STATE_ROOT`.
