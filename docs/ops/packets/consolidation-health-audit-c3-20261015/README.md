# consolidation-health-audit-c3-20261015: CONSOLIDATE wave C3, operator packet

**Status: PREPARED, NOT INSTALLED.** Merging adds an inert manifest and a NEVER_SCHEDULED runner. No crontab, unit, n8n
or DB change was made.

This is wave C3 of `docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.md`. The family is WS2 F36, the
health/audit plane. In the review it has 41 jobs: 22 live crontab lines plus timers. It is the largest family that has
no manifest; premarket (F11, 38 lines) and after-close (F12, 25 lines) already have theirs, and their flip packets are
built.

## What the manifest does (`config/pipelines/health_audit.json`)

A host serial stage can absorb a line only if its cadence survives. Four of the 22 F36 lines meet that bar: they are the
single-slot weekday-morning checks.

| Step (order) | Line | Today | In the stage |
|---|---|---|---|
| `alert_missing_conditions` | L204 | 07:30 | 07:30 (first) |
| `write_state_freshness_history` | L177 | 07:15 | about 15 min later |
| `portfolio_level_qa` | L210 | 07:40 | when the steps above end |
| `classifier_health_check` | L224 | 07:55 | earlier: the end of the chain |

- **Stage:** `morning`, proposed `30 7 * * 1-5`, serial. Each step carries `dow` 1-5, the line's own verbatim command,
  its flock and its log, and an `env` block taken from the line with `scripts/pipelines/derive_step_env.py`, names only.
- **Steps that send.** Two steps send on the host chokepoint: `alert_missing_conditions` and `portfolio_level_qa`. That
  is unchanged, because the runner is a host process and n8n is not involved.
- **Deferred (11).** These are multi-slot (hourly, every 4 h, 8/12/16, 8/20), evening or weekly, or already a fabric
  lane: `job-coverage-monitor` (canary) and `agent-number-grounding-slo` (shadow). Their target is the F36 fabric
  workflows: breach detector, hourly audit and daily audit, with one Run Lane node per check (MIGRATION_TARGET §3.2),
  after the incident flood is fixed.
- **Excluded (7).** All are STAY_HOST: the governance writer, the sender health checks, `trade-integrity-audit`,
  `system-rollup-snapshot`, `deepseek-balance-snapshot`, and the n8n SIEM bridge and diagnoser. The P1 path never
  depends on n8n.
- **Net change if flipped.** 4 lines become 1 runner line, so active job lines go from 394 to 391.

## Preconditions (§23.21 cutover standard: fix, dry run, regression, then one live run; no soak)

```bash
cd ~/trade-ai-releases/portfolio-server/CURRENT          # a release that contains this PR
bash scripts/pipelines/run_health_audit_pipeline.sh --stage morning --dry-run
#   expect 4 "[DRY_RUN] would run" lines on a weekday (0 on a weekend), nothing executed;
#   summary data/runtime/pipeline_health_audit_morning_last.json  dry_run=true executed_any=false
~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/bin/guard show 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -iE '^[[:space:]]*cron[[:space:]]'          # an active cron grant
```

## Apply (operator; `cron` grant; weekday after 08:00 ET so today's four checks have already run)

```bash
cd ~/trade-ai-releases/portfolio-server/CURRENT/docs/ops/packets/consolidation-health-audit-c3-20261015
bash install.sh                                 # DRY RUN from the live table: 4 lines commented, 1 runner line added
CRON_GRANT_ID=<id> bash install.sh --apply      # backup, crontab -, read back == candidate, VERIFY OK
# the one live run (§23.21) is the next weekday 07:30 tick, in cron's own environment; then read its summary:
jq '.overall_status, [.steps[] | {id, status}]' ~/trade-ai-releases/portfolio-server/CURRENT/data/runtime/pipeline_health_audit_morning_last.json
```

Then open the registry PR. It adds the stage lane `health-audit-pipeline-morning` as ACTIVE, with `scheduler.match` set
to `run_health_audit_pipeline.sh --stage morning`. The four rows `alert-missing-conditions`,
`write-state-freshness-history`, `portfolio-level-qa` and `classifier-health-check` become RETIRED with `superseded_by`
set to the stage lane. Run `reconcile_lane_registry.py --snapshot-in … --write` for the fixed point.

**Grant wording (suggested).** Type: `cron`. Text: "consolidation-health-audit-c3-20261015: comment 4 crontab lines
(L177/L204/L210/L224, F36 weekday-morning checks) `# RETIRED <date> c3-health-audit …` and add one line
`run_health_audit_pipeline.sh --stage morning --apply` via install.sh --apply; rollback.sh on failure. PR #<n> sha
<sha>."

## Rollback

```bash
bash rollback.sh                                # DRY RUN
CRON_GRANT_ID=<id> bash rollback.sh --apply     # removes the runner line, uncomments the 4 tagged lines, VERIFY OK
```

**Rehearsal:** `tests/test_consolidation_health_audit_c3_20261015.py`. On a fake crontab, `install.sh --apply` then
`rollback.sh --apply` gives back a byte-identical table.
