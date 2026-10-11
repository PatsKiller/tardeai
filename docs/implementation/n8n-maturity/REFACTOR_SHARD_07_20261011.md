Status: SOURCE_ONLY
as_of: 2026-10-11
Measured at: base 9f602186a958df4c2d9f36f04a0ad1809bfce808; branch n8nmat/refactor-shard-07; fake tests only

# Shard 07 source refactor

Seven new source proposals use strict offline `--dry-run`, reject unknown and abbreviated flags, and write `LaneRunReceipt@v1` only on a real run. Explicit dry-run takes precedence over observed `--apply`. The proposed registry uses `scheduler.stage: shadow`, `scheduler.wave: R2-07`, `dispatch.wave: W4`, `dispatch.mode: dry_run`, and `live_arg: null`. No scheduler, service, release, business data or workflow was changed. None of these seven lanes was already admitted on the base.

All seven new health contracts remain DRAFT with SOURCE_ONLY evidence, CLASS_DEFAULT_PROVISIONAL baselines, NOT_MEASURED ledgers and null runs_considered. There is no new operator review or reviewer field. Runtime readiness requires review, measured ledger evidence and the operator canary/cutover packet.

The approved scoped cron snapshot is dated 2026-10-11T17:05:28.513179+00:00. Its 151 selected lines are observed host evidence supplied by the integrator; the full cron census and all timer states are NOT_MEASURED. Exact script arguments and repeated schedules are preserved. No local crontab read was performed.

## Proposed lane commands and locks

| Lane | Exact cron script argv | Proposed lock | Needs outer flock |
|---|---|---|---|
| document-mentions-backfill | `scripts/backfill_document_mentions.py --all --limit 4000 --apply` | `/tmp/document_mentions_backfill.lock` | False |
| aegis-evening-packet | `scripts/aegis_evening_packet.py` | `/tmp/aegis_evening_packet.lock` | False |
| hermes-scope-governor | `scripts/hermes_scope_governor.py --apply` | `/tmp/hermes-scope-governor.lock` | True |
| iris-proposal-curator | `scripts/iris_proposal_curator.py --apply` | `/tmp/iris-proposal-curator.lock` | True |
| price-db-sync | `scripts/price_db_sync.py` | `/tmp/price-db-sync.lock` | True |
| sync-dividend-data | `scripts/sync_dividend_data.py` | `/tmp/sync-dividend-data.lock` | True |
| watch-valuation-backfill | `scripts/watch_valuation_backfill.py --limit 400` | `/tmp/watch_valuation_backfill.lock` | False |

The governor’s current safe_flock.sh is a PID-file wrapper; it does not provide an outer flock. Its proposed flock and the three cron lines without any lock require a separate operator packet. Other proposed lock paths equal their observed outer flock paths. The document backfill timeout is the observed 25 minutes; other proposed timeouts without an observed timeout remain source defaults.

All seven env allowlists stay in report mode: complete real-path shared import closure has not been proven. Entrypoint loaders copy only named environment keys. No broker names occur in proposed env_names. Shared import closure, partial provider failure semantics and compound/model/timer owners need their owning shared work before enforce mode or runtime readiness.

## Exact approved cron lines

### document-mentions-backfill

```cron
25 * * * * cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && flock -n /tmp/document_mentions_backfill.lock timeout 25m $PY scripts/backfill_document_mentions.py --all --limit 4000 --apply >> /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/logs/document_mentions.log 2>&1
```

### aegis-evening-packet

```cron
45 19 * * * cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && PYTHONPATH=/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT flock -n /tmp/aegis_evening_packet.lock $PY scripts/aegis_evening_packet.py >> logs/aegis_evening_packet.log 2>&1
```

### hermes-scope-governor

```cron
7,37 * * * * cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/hermes_scope_governor.lock $PY scripts/hermes_scope_governor.py --apply >> logs/hermes_scope_governor.log 2>&1
```

### iris-proposal-curator

```cron
20 7 * * * cd $PROJ && $PY scripts/iris_proposal_curator.py --apply >> logs/iris_proposal_curator.log 2>&1
```

### price-db-sync

```cron
20 7 * * 1-5 cd $PROJ && $PY scripts/price_db_sync.py >> logs/price_db_sync.log 2>&1
```

### sync-dividend-data

```cron
5 7 * * 1-5 cd $PROJ && $PY scripts/sync_dividend_data.py >> logs/dividend_sync.log 2>&1
```

### watch-valuation-backfill

```cron
47 6 * * * cd $PROJ && flock -n /tmp/watch_valuation_backfill.lock $PY scripts/watch_valuation_backfill.py --limit 400 >> logs/watch_valuation_backfill.log 2>&1  # yfinance valuation supplement for Watch names Finviz misses (resumable, capped); feeds finviz-strip-map fallback (2026-07-25)
```

## Validation and limits

The shard test freezes all seven original entrypoints at the base as text fixtures and invokes old/new entrypoints with literal observed cron arguments. Business boundaries are replaced before invocation. It compares stdout, calls, arguments and success exit codes; real fake-run receipt tests also preserve prior ok_at when an exception is raised. Tests and every Python child run in a scratch minimal environment with empty dotenv plus pre-import DB, socket, host-command and production-file barriers. The nodeps dependency shim alone is not a safety barrier.

The existing dividend preview test now separately verifies the offline CLI and its retained READ ONLY preview helper. The first inherited regression run exposed five price backfill tests that used real DB connections and packet tests that attempted cron discovery; required barriers stopped those effects. Their affected tests now use explicit fake connections/writer boundaries and scratch packet/health inputs, with stronger argument and cleanup assertions. PostgreSQL backend semantics remain outside this fake test evidence. The required health gate refuses the seven new DRAFT contracts; the PR profile retains the corresponding assertion failure. Exact gate exits, tails and barrier attempts are in untracked refactor-gates-07/summary.json and REFACTOR_EVIDENCE_07.md. This document makes no green-profile or deployment claim.

Document/aegis/governor/iris/price/dividend/valuation error exits now retain the previous receipt success timestamp. Governor ok:false, failed taxonomy applies, primary packet write failure and all-fetch-failed valuation runs return failure. The price receipt currently counts the initial daily-price writer only; existing fail-soft secondary provider stages remain an explicit shared follow-up. Dividend and valuation plans label uncomputed counts NOT_MEASURED.

## All assigned lanes

Counts: {'SHADOW_READY': 7, 'SKIP_SENDER': 6, 'BLOCKED': 17, 'SKIP_CLASS': 2, 'SKIP_BROKER': 5}; 37 total, zero duplicate source admissions. SHADOW_READY means a source proposal with offline argv evidence; it does not mean reviewed or deployed.

| Lane | Classification | Result | Class | Reason |
|---|---|---|---|---|
| document-mentions-backfill | WRITER | SHADOW_READY | ingest | Strict offline preview overrides --apply; real argv retains --all --limit and --apply; real-run mentions/watermark counts in lane receipt. |
| cio-defer-revisit | SENDER | SKIP_SENDER | — | process_due_defers reaches publish_material_decision/CIO delivery; sender work belongs to the notification-intent migration. |
| hermes-update-check | READ_ONLY | BLOCKED(systemd_source_unresolved) | — | Registry identifies a timer but supplies no script/exec_start; no matching tracked source found. Need owning timer evidence and supported admission shape. |
| gap-resolution-audit | SENDER | SKIP_SENDER | — | Tracked service invokes check_gap_resolution.py --alert; monitor alert transport stays with sender migration. |
| contradiction-adjudicator | WRITER | BLOCKED(systemd_and_model_route) | llm | Tracked timer calls --apply --max-pairs 20; paid judge uses in-process deepseek-flash, not a declared governed-bridge route. Systemd shape unsupported. |
| hermes-overnight-pipeline-close | WRITER | BLOCKED(compound_child_ownership) | learn | Existing pipeline --stage close --dry-run spans unowned child scripts; no independent CLI/receipt and child-effect proof for this shard. |
| run-cio-event-detector-once-at-0-8 | WRITER | BLOCKED(inline_shared_entrypoint) | learn | Inline python -c calls shared lib.cio_event_detector; no owned script entrypoint for strict CLI/receipt refactor. Needs shared owner work. |
| tradeai-agent-runtime-morgan | WRITER | BLOCKED(systemd_and_model_route) | llm | Persona runtime timer invokes shared module --agent morgan --once --max-batch 8; no supported standalone timer shadow shape or verified named bridge route. |
| n8n-lab-watchdog | READ_ONLY | SKIP_CLASS | monitor | Host HTTP watchdog is an outside-n8n monitor, outside ingest/llm/learn; no runtime probe run here. |
| industry-momentum-groups | SENDER | SKIP_SENDER | — | finviz_industry_groups.main reaches industry_momentum.emit_telegram/send_telegram; both cron schedules stay unchanged. |
| run-warrior-weekly-audit | SENDER | SKIP_SENDER | — | Launcher invokes warrior_weekly_audit_cron.py --days 7, which sends Telegram; no launcher or child change. |
| watch-review-workers | WRITER | BLOCKED(model_route) | llm | Maria execute worker calls run_watch_review_canary.run_agent_call/in-process gate_and_generate; no named governed bridge admission proof. |
| watch-review-workers-cio | WRITER | BLOCKED(model_route) | llm | CIO execute worker uses the same unadmitted route; argv --mode execute --allow-execute --role cio stays untouched. |
| active-trader-session-review | BROKER | SKIP_BROKER | — | scripts/active_trader/session_review.py is in the execution file set. Source not opened or investigated. |
| active-trader-session-review-close | BROKER | SKIP_BROKER | — | Same execution file set as session-review; source not opened or investigated. |
| aegis-evening-packet | WRITER | SHADOW_READY | learn | Offline bounded packet plan; real run writes source packet and lane receipt. Primary destination failure exits 1 and preserves receipt ok_at. |
| agent-event-router | SENDER | SKIP_SENDER | — | Router directly reaches its _send_telegram transport helper; no admission added. |
| analyst-urgent-refresh | SENDER | SKIP_SENDER | — | Regenerates reports and invokes email send with credential-file lookup. No credential file read and no sends or model calls performed. |
| defense-recommendations | BROKER | SKIP_BROKER | — | Sizing/account-capability behavior path found during source classification; further investigation stopped. |
| llm-deferred-drain | WRITER | BLOCKED(model_route) | llm | Deferred payload selects lane/model for in-process llm_consumption.gate_and_generate; not a named bridge capability route. |
| enrich-proposal-technicals | BROKER | SKIP_BROKER | — | Entrypoint explicitly enriches active broker proposal symbols via proposal_technical_snapshot; no broker proposal path investigated further. |
| hermes-observation-check | READ_ONLY | SKIP_CLASS | monitor | Systemd host observation monitor calls service/container state commands; outside three admitted R1 classes and timer shape unsupported. |
| hermes-scope-governor | WRITER | SHADOW_READY | learn | Explicit --dry-run returns before DB/engine import. Normal argv remains unchanged; result ok:false exits 1, receipt carries numeric counts only. |
| iris-proposal-curator | WRITER | SHADOW_READY | learn | Offline duplicate/taxonomy plan, strict flags and lane receipt; --apply behavior remains, failed apply result exits 1. |
| journal-review-builder | WRITER | BLOCKED(model_route) | llm | Existing dry-run/receipt are useful source code but llm_lane.generate --lane grok/local is not a governed named bridge route; no admission added. |
| price-db-sync | WRITER | SHADOW_READY | ingest | Offline daily-price plan; existing ticker_prices writer retained, DB_PASSWORD-only named loader, real-run receipt preserves exceptions and initial write count. |
| recommendation-intelligence-engine | WRITER | BLOCKED(untyped_failures) | learn | Lifecycle events, rotations and quality stages catch failures yet publish ok:true/exit0; real-run health needs typed partial/failure semantics before admission. |
| reconcile-exit-advisory-outcomes | WRITER | BLOCKED(unowned_price_closure) | learn | _closes_since imports holdings_gain_guardian._bars_with_volume; unowned broker/price-provider closure cannot be claimed safe by a shard CLI wrapper. |
| risk-gate | BROKER | SKIP_BROKER | — | Financial fail-closed gate covers broker submission/live trade contexts; no financial control edits or tests. |
| run-scheduled-two-way-curation-options | WRITER | BLOCKED(unowned_options_child) | learn | Shell sources whole environment and calls unowned fold_options_edge_backfill.py; child effect/receipt ownership and boundary review required. |
| run-scheduled-two-way-curation-desk | WRITER | BLOCKED(unowned_curation_child) | learn | Shell desk-emit calls emit_and_drain_desk_curation.py --apply; child writes advisory/defense feedback and drains staging (stage-only without --promote). No send proven: unowned child/env closure and fail-soft results require shared work. |
| run-watchlist-agent-jobs-offpeak | WRITER | BLOCKED(compound_model_route) | llm | Whole-env/off-peak/lock wrapper spans unowned agent-job children, not one declared named bridge process. Preserve cap/window behavior. |
| symbol-enrichment | WRITER | BLOCKED(env_and_untyped_provider_failures) | ingest | Import-time whole .env copy, direct resolve_secret and per-tier catches/empty returns prevent a truthful typed real-run success verdict; shared closure needed. |
| sync-dividend-data | WRITER | SHADOW_READY | ingest | Strict offline capped dividend plan; existing READ ONLY preview helper retained/tested. DB_PASSWORD-only loader; existing counts/failure receipt preserved. |
| topic-curator-at-30-9-13 | WRITER | BLOCKED(model_route) | llm | Calls in-process governed_cloud_generation rather than declared cio-governed-bridge; shared topic-curator receipt does not isolate both lane identities. |
| topic-curator-ensemble | WRITER | BLOCKED(model_route) | llm | Same unadmitted model closure; --ensemble and dedicated ensemble output signal preserved untouched. |
| watch-valuation-backfill | WRITER | SHADOW_READY | ingest | Offline configurable valuation plan; DB adapter lazy on real path, durable receipt and all-fetch-failed exit1; existing cached rows preserved. |

## Handoff and rollback

The integrator serializes shared external ROADMAP, REMEDIATION_PLAN and backlog append blocks. External inventory_rows_07.tsv contains all 37 rows; only seven proposals use new_stage shadow-ready, every skip/block uses unchanged. CRON_FLOCK_NEEDED.tsv, SHARED_CHANGES_NEEDED.md and the DRAFT review list are local untracked handoff artifacts. The workbook remains the integrator’s task.

Rollback before integration is to omit this local commit. After an authorized source merge, revert the shard source commit in the normal review flow; there are no host mutations to undo. Keep existing cron work until separately authorized migration packets pass.
