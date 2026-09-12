# State-root reconciliation — operator adjudication required

Campaign: `trade-ai-maturity-overnight-20260912`  
Status: **NOT EXECUTED.** This runbook exists because the change is not
one an unattended agent should make. Read the direction census first.

## What is wrong

`scripts/lib/persistent_overlay.py` declares `OVERLAY_RELS` — the trees that
"must symlink into GOOD_PERSISTENT_ROOT" — and `cio_phase2_exact_main_deploy.sh`
applies that rule to the **release** directory. It was never applied to the
**canonical source tree**, which is where the batch plane actually executes:
106 active cron lines `cd` into the dev tree and write its real `data/…`,
while the API reads `CURRENT/data/… -> persistent-state`.

Two directories, two inodes, no error anywhere:

```
served   data/runtime/sector_momentum_latest.json  inode 9633692  2026-08-25
producer data/runtime/sector_momentum_latest.json  inode 3573658  2026-09-11
```

That is why the Oscillator board serves a 17-day-old reading while the producer
holds a current one, and why MVL counters read low: `sentinel_reviews.jsonl` is
140 rows on the producer plane and 104 on the served plane.

## Why this was not executed automatically

**The fork is bidirectional.** A newer-wins merge in either direction destroys
real data. Counts below are per tree, `producer newer` vs `served newer`,
tolerance 300s.

| tree | common | producer newer | served newer | within tolerance |
|---|---|---|---|---|
| `data/portfolios/state` | 106 | 48 | 8 | 50 |
| `data/runtime` | 184 | 88 | 19 | 77 |
| `data/cio` | 138 | 22 | 63 | 53 |
| `data/health` | 1 | 0 | 0 | 1 |
| `logs` | 37 | 6 | 28 | 3 |

`data/portfolios/state` holds live holdings, risk_management and
personal_situation. Guard's `state-write` scope covers exactly that path and
was **not** granted to this campaign, so that tree is out of scope regardless.

## The files that flow the wrong way

These are the ones a newer-wins merge toward the served root would destroy.
Each was written by something running from `CURRENT`, not from the dev tree.

### `data/portfolios/state` — 8 files newer on the SERVED side

| file | served copy ahead by |
|---|---|
| `redeploy_analytics_cache.json` | 41.1d |
| `.telegram_callback_offset` | 23.8d |
| `health_agent_status.json` | 16.5d |
| `health_agent_remediation_state.json` | 16.5d |
| `health_agent_alert_state.json` | 16.4d |
| `ytd_daily_pin.json` | 16.0d |
| `ticker_snapshot_latest.json` | 0.0d |
| `finviz_quote_cache.json` | 0.0d |

### `data/runtime` — 19 files newer on the SERVED side

| file | served copy ahead by |
|---|---|
| `secrets_admin_audit.jsonl` | 31.9d |
| `advisory_kb_lesson_candidates.jsonl` | 29.0d |
| `symbol_regime_state.json` | 21.9d |
| `research_lane_health.json` | 20.4d |
| `advisory_calibration.json` | 17.0d |
| `aegis_evening_packet.json` | 17.0d |
| `cio_reactive_cycle_last.json` | 16.5d |
| `finviz_strip_map_cache.json` | 16.4d |
| `health_agent_daemon_state.json` | 16.0d |
| `report_catalog.json` | 16.0d |
| `broker_autocal_last.json` | 16.0d |
| `file_integrity_manifest.json` | 15.3d |
| `coverage_stall_snapshot.json` | 11.5d |
| `last_secrets_data_backup.stamp` | 9.0d |
| `last_apps_backup.stamp` | 9.0d |
| `last_db_offsite_backup.stamp` | 9.0d |
| `reentry_decision_desk_latest.json` | 0.1d |
| `accuracy_sweep_log.jsonl` | 0.1d |
| `advisory_desk_latest.json` | 0.0d |

### `data/cio` — 63 files newer on the SERVED side

| file | served copy ahead by |
|---|---|
| `cio_telegram_rate.jsonl` | 21.0d |
| `cio_telegram_msg_dedup.jsonl` | 21.0d |
| `outcome_observations.jsonl` | 17.2d |
| `research_trigger_ledger.jsonl` | 17.2d |
| `research_skip_ledger.jsonl` | 17.2d |
| `reconciliation_latest.json` | 17.0d |
| `cio_event_cursors.jsonl` | 16.7d |
| `hermes_challenge_queue.jsonl` | 16.5d |
| `ticker_research_graph.jsonl` | 16.5d |
| `ticker_research_state.jsonl` | 16.5d |
| `watchdog_state.json` | 16.5d |
| `daily_intelligence_heartbeats.jsonl` | 16.5d |
| `watchdog_runs.jsonl` | 16.5d |
| `daily_intelligence_heartbeat.json` | 16.5d |
| `intelligence_lifecycle.jsonl` | 16.5d |
| `intelligence_delta_receipts.jsonl` | 16.5d |
| `context_use_receipts.jsonl` | 16.5d |
| `cio_notification_metrics.jsonl` | 16.5d |
| `office_state_latest.json` | 16.5d |
| `holdings_snapshot_latest.json` | 16.5d |
| … 43 more | |

### `logs` — 28 files newer on the SERVED side

| file | served copy ahead by |
|---|---|
| `health_manual_remediation.log` | 47.2d |
| `claude_escalation_retry_cmd.jsonl` | 35.5d |
| `health_agent_remediation.jsonl` | 35.0d |
| `health_agent.jsonl` | 35.0d |
| `telegram_poller_watchdog.log` | 29.0d |
| `cio_wake_dispatcher.log` | 28.2d |
| `cio_detector.log` | 28.0d |
| `watchpool_alerts_cron.log` | 27.9d |
| `cio_governed_bridge.log` | 26.0d |
| `advisory_outcome_scorer.log` | 26.0d |
| `cio_reactive_cycle.log` | 26.0d |
| `agent_runtime_producer.log` | 25.0d |
| `agent_runtime_health.log` | 25.0d |
| `claude_escalation_daemon.log` | 25.0d |
| `cio_detector_weekly.log` | 21.0d |
| `exit_outcomes.log` | 21.0d |
| `pullback_outcomes.log` | 21.0d |
| `watch_outcomes.log` | 21.0d |
| `research_scheduler.log` | 20.4d |
| `advisory_notif_broker.log` | 19.3d |
| … 8 more | |

## What the fix looks like once direction is adjudicated

Per tree, in this order. Nothing here is destructive until step 4, and step 4
moves rather than deletes.

```bash
REL=data/runtime          # one tree at a time; NEVER data/portfolios/state
P=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/$REL
S=/home/johnclaw/trade-ai-releases/persistent-state/$REL
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

# 1. Before-image of BOTH sides. Not one, both.
tar czf ~/backups/stateroot-$REL-producer-$STAMP.tgz -C "$(dirname $P)" "$(basename $P)"
tar czf ~/backups/stateroot-$REL-served-$STAMP.tgz   -C "$(dirname $S)" "$(basename $S)"

# 2. Re-run the census and keep it beside the backups.
python3 scripts/check_state_root_split.py --json > ~/backups/stateroot-census-$STAMP.json

# 3. Copy ONLY the adjudicated direction, file by file, never a bulk rsync
#    --delete. A per-file list is what makes this reviewable.

# 4. Replace the producer-side directory with a symlink to the persistent
#    root, preserving the original exactly as deploy already does for the
#    release side ('nothing is merged and nothing is deleted'):
mv "$P" "$P.pre-overlay-$STAMP"
ln -sfn "$S" "$P"

# 5. Prove it: one inode, and the gate green.
stat -c '%i %n' "$P/<a file>" "$S/<the same file>"
python3 scripts/check_state_root_split.py   # expects PASS
```

Rollback for step 4 is one command: `rm "$P" && mv "$P.pre-overlay-$STAMP" "$P"`.

## Make it stay fixed

`scripts/check_state_root_split.py` ships in PR #975 and defaults its `rels` to
`OVERLAY_RELS` itself, so a newly declared tree cannot fork without failing the
gate. Wire it into `cio_phase2_exact_main_deploy.sh` ahead of promote once the
existing divergence is reconciled — gating promote before then would block every
deploy on a pre-existing condition.
