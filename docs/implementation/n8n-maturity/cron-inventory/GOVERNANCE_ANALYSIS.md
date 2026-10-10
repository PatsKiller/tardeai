Status:      ACTIVE
as_of:       2026-10-09T23:00:06-04:00
Measured at: main c4782f219 / live b7dbe6e60-main-exact-phase2-20261009-210323

# Schedule and dependency governance — overlaps, duplicates, consolidation

Generated 2026-10-09 (read-only). Scope: **560 live scheduled units**: 438 crontab lines, 92 user timers, 1 system timer, 17 health-tick steps and 12 n8n workflows (the n8n active flags come from the 16:00Z committed snapshot). Representative week: **Mon 2026-10-12 to Sun 10-18, America/New_York (EDT)**. It has no NYSE holiday, so `market_day_gate` passes Mon–Fri. Wrappers are modelled per fire. `run_with_deepseek_offpeak.sh` (bulk: 10:00–21:00 ET and not the UTC peak; `--official`: not in UTC 01–04/06–10 on weekdays) and `llm_priority_guard.sh` (DEFER weekdays 06:00–11:59) use the logic in `scripts/lib/deepseek_offpeak.py` and the guard script. Monotonic timers (`OnUnitActiveSec`) are phased from `systemctl --user list-timers` `last`. Monthly lines (day-of-month 1) do not fire in this week.

Files: `overlaps.csv` (every minute where 2 or more jobs start), `overlaps_top20.csv`, `duplicates.csv`, `consolidation.csv`, `dependencies.csv`, `critical_paths.csv`, `DEPENDENCY_MAP.md`. Generators: `gov_sched.py`, `gov_evidence.py`, `gov_stage1-3.py` (rerunnable; about 15 s, about 60 MB RSS).

## Headline numbers

| measure | value |
|---|---|
| Scheduled fires / effective fires (after wrappers) in the week | 114,313 / 113,349 |
| Minutes-of-week with ≥2 jobs starting together | 8,407 of 10,080 (83%) |
| … High / Med / Low contention | 1,232 / 6,949 / 226 |
| … High by window | overnight 15, premarket 131, RTH 925, after-close 100, evening 20, weekend 41 |
| Largest single-minute pile-up | Mon 12:00 (116 jobs) |
| Distinct (time-of-day × job-set) overlap patterns | 1808 |
| Runtime evidence | log timestamps 148; log mtime - last fire 199; NONE 110; journal(wall clock, 7d) 86; health_tick_history duration_s 17 |
| Duplicate / redundant groups | 76 (identical-command 9, same script, different slots (V2 listed as identical) 1, multiple cleaners, one table 2, same broker read twice (2 min apart) 1, overlapping 5-min scanners 1, same script, different slots 4, persona fan-out (one runner, N timers) 1, same script, different args/modes 28, same script, mode flags differ 8, same script+args, different slots 4, double-scheduled across schedulers 7, multiple scanners, one table 10) |
| Consolidation + elimination groups | 69 (syntactic merge 9, semantic merge (code) 7, pipeline (manifest flip) 8, dispatcher consolidation 1, F pipeline consolidation 12, elimination 32) |
| Schedule entries removable (union, de-duplicated) | 323 (syntactic merge 2, semantic merge (code) 11, pipeline (manifest flip) 83, dispatcher consolidation 9, F pipeline consolidation 200, elimination 32); by source {'systemd-user-timer': 51, 'crontab': 266, 'n8n': 6} |

### Removable lines by evidence tier

| tier | new lines retired | cumulative |
|---|---|---|
| Tier A — proven, no code (eliminations: never-runs / R0 registry / no-op personas / never-produced-output; identical-command merges) | 34 | 34 |
| Tier B — code needed, small (V2 semantic merges) | 9 | 43 |
| Tier C — pipeline manifest flips (needs live stage receipts + N2) | 81 | 124 |
| Tier D — F pipeline consolidation (estimate: members − one stage per batch window) | 199 | 323 |

## 1. Overlaps

**Contention rule** (per start-minute, computed over the jobs starting in that minute plus those still running from earlier, using the estimated runtime):
- **High** if any of these holds:
  - Two jobs share a `flock -n` lock. One of them is skipped silently.
  - Two or more jobs that both *start* this minute and run at least 1 min write the same table.
  - Two or more jobs that run at least 1 min use the single local GPU (Ollama).
  - Five or more jobs hit Schwab, or five or more hit Finviz.
- **Med** if they share any other rate-limited provider, a write/read table, or a log.
- **Low** otherwise.

The score ranks windows. It adds weights for the shared resources and for the number of jobs, and multiplies by 1.5 inside premarket, the first 15 min of RTH and after-close.

- `:00` and `:30` pile-ups: **every hour of the week** has ≥2 jobs starting at both :00 and :30 (168/168 `:00` and 168/168 `:30` minutes). RTH top-of-hour minutes start 85–116 jobs. That is because the `*/5`, `*/10`, `*/15` and `*/30` RTH lines, the 9 `*:0/5` persona timers, the health tick and the hourly lines all align on :00.

- **Lock collisions (certain contention: the second `flock -n` exits without running):**
  - `/tmp/tradeai_quote_refresh.lock` — 15 minute(s)/week, e.g. Fri 10:45, Fri 12:45, Fri 13:45, Mon 10:45
  - `/tmp/catalyst_calibration_monitor.lock` — 7 minute(s)/week, e.g. Fri 05:40, Mon 05:40, Sat 05:40, Sun 05:40
  - `/tmp/source_attribution_monitor.lock` — 7 minute(s)/week, e.g. Fri 06:00, Mon 06:00, Sat 06:00, Sun 06:00
  - `/tmp/watch_directives_monitor.lock` — 7 minute(s)/week, e.g. Fri 06:20, Mon 06:20, Sat 06:20, Sun 06:20
  - `/tmp/analyst_daily_digest.lock` — 5 minute(s)/week, e.g. Fri 07:30, Mon 07:30, Thu 07:30, Tue 07:30
  - `/tmp/tradeai_maturity_remeasure.lock` — 1 minute(s)/week, e.g. Mon 06:40
  Except for the quote-refresh pair, each collision is a cron or timer line plus its n8n shadow on the same lock (see D-SCRIPT double-scheduled groups).

### Top 20 riskiest windows (collapsed across days)

| # | time | days | risk | score | start | concurrent | overlap min | why |
|---|---|---|---|---|---|---|---|---|
| 1 | 16:00 | Mon,Tue,Wed,Thu,Fri | High | 406.5 | 106 | 106 | 16.29 | write-write, both start this minute and run >=1 min: fred_economic_series,fundamental_data,hermes_directive_hits_staging,hermes_research_intelligence,hermes_validation_fi |
| 2 | 09:00 | Mon,Tue,Wed,Thu,Fri | High | 375.15 | 108 | 108 | 16.29 | write-write, both start this minute and run >=1 min: strategy_watchpool,trade_ai_scans,watch_directive_hits,watchlist_items / heavy provider: Finvizx14,Schwabx18 / 5 conc |
| 3 | 09:30 | Mon,Tue,Wed,Thu,Fri | High | 345.23 | 90 | 91 | 16.29 | write-write, both start this minute and run >=1 min: strategy_watchpool,trade_ai_scans,watch_directive_hits,watchlist_items / heavy provider: Finvizx15,Schwabx15 / 5 conc |
| 4 | 16:30 | Mon,Tue,Wed,Thu,Fri | High | 340.05 | 85 | 86 | 16.29 | write-write, both start this minute and run >=1 min: hermes_directive_hits_staging,hermes_research_intelligence,hermes_validation_findings,inference_ensemble_jobs,strateg |
| 5 | 14:00 | Mon,Tue,Wed,Thu,Fri | High | 314.15 | 115 | 115 | 16.29 | write-write, both start this minute and run >=1 min: events,fred_economic_series,fundamental_data,hermes_directive_hits_staging,hermes_research_intelligence,hermes_valida |
| 6 | 12:00 | Mon,Tue,Wed,Thu,Fri | High | 304.6 | 116 | 116 | 16.29 | write-write, both start this minute and run >=1 min: events,fred_economic_series,fundamental_data,hermes_directive_hits_staging,hermes_research_intelligence,hermes_valida |
| 7 | 13:00 | Mon,Tue,Wed,Thu,Fri | High | 296.95 | 113 | 113 | 16.29 | write-write, both start this minute and run >=1 min: events,fused_signals,hermes_directive_hits_staging,hermes_research_intelligence,hermes_validation_findings,inference_ |
| 8 | 15:00 | Mon,Tue,Wed,Thu,Fri | High | 288.65 | 113 | 113 | 16.29 | write-write, both start this minute and run >=1 min: events,hermes_directive_hits_staging,hermes_research_intelligence,hermes_validation_findings,inference_ensemble_jobs, |
| 9 | 10:00 | Mon,Tue,Wed,Thu,Fri | High | 285.85 | 115 | 115 | 16.29 | write-write, both start this minute and run >=1 min: material_changes,narrative_subjects,portfolio_intelligence_events,strategy_watchpool,watch_directive_hits,watchlist_i |
| 10 | 11:00 | Mon,Tue,Wed,Thu,Fri | High | 270.0 | 108 | 108 | 16.29 | write-write, both start this minute and run >=1 min: material_changes,narrative_subjects,strategy_watchpool,watch_directive_hits,watchlist_items / heavy provider: Finvizx |
| 11 | 13:30 | Mon | High | 259.35 | 94 | 95 | 16.29 | write-write, both start this minute and run >=1 min: data_source_health,events,hermes_directive_hits_staging,hermes_research_intelligence,hermes_validation_findings,infer |
| 12 | 13:30 | Tue,Wed,Thu,Fri | High | 255.2 | 93 | 94 | 16.29 | write-write, both start this minute and run >=1 min: data_source_health,events,hermes_directive_hits_staging,hermes_research_intelligence,hermes_validation_findings,infer |
| 13 | 12:30 | Mon,Tue,Wed,Thu,Fri | High | 252.95 | 90 | 91 | 16.29 | write-write, both start this minute and run >=1 min: events,hermes_directive_hits_staging,hermes_research_intelligence,hermes_validation_findings,inference_ensemble_jobs, |
| 14 | 15:30 | Mon,Tue,Wed,Thu,Fri | High | 247.7 | 89 | 90 | 16.29 | write-write, both start this minute and run >=1 min: events,hermes_directive_hits_staging,hermes_research_intelligence,hermes_validation_findings,inference_ensemble_jobs, |
| 15 | 14:30 | Mon,Tue,Wed,Thu,Fri | High | 243.55 | 88 | 89 | 16.29 | write-write, both start this minute and run >=1 min: events,hermes_directive_hits_staging,hermes_research_intelligence,hermes_validation_findings,inference_ensemble_jobs, |
| 16 | 11:30 | Mon,Tue,Wed,Thu,Fri | High | 237.1 | 89 | 90 | 16.29 | write-write, both start this minute and run >=1 min: strategy_watchpool,watch_directive_hits,watchlist_items / heavy provider: Finvizx14,Schwabx16 / 5 concurrent jobs wit |
| 17 | 10:30 | Mon,Tue,Wed,Thu,Fri | High | 235.5 | 87 | 88 | 16.29 | write-write, both start this minute and run >=1 min: data_source_health,strategy_watchpool,watch_directive_hits,watchlist_items / heavy provider: Finvizx13,Schwabx16 / 5  |
| 18 | 07:30 | Mon,Tue,Wed,Thu,Fri | High | 208.58 | 67 | 69 | 9.33 | same lock: analyst_daily_digest.lockx2 / write-write, both start this minute and run >=1 min: watchlist_items / heavy provider: Finvizx9,Schwabx5 / 4 concurrent jobs with |
| 19 | 07:00 | Mon,Tue,Wed,Thu,Fri | High | 204.0 | 77 | 78 | 1.7 | write-write, both start this minute and run >=1 min: fused_signals,portfolio_intelligence_events / heavy provider: Schwabx5,Finvizx8 / shared provider: Alpacax3,Anthropic |
| 20 | 08:00 | Mon | High | 195.67 | 80 | 81 | 4.13 | write-write, both start this minute and run >=1 min: inference_ensemble_jobs / heavy provider: Schwabx5,Finvizx8 / shared provider: Alpacax4,DeepSeekx2,Moomoox4,Ollama/lo |

### Riskiest window inside each batch window

| window | time | risk | score | start | why |
|---|---|---|---|---|---|
| overnight | Mon 04:00 | High | 68.6 | 62 | heavy provider: Ollama/local-GPU(>=1min)x2 / shared provider: Alpacax2,DeepSeekx2,Finvizx4,Schwabx3,Telegramx18 / write-write (short): atm_state,audit_log,content_embeddings,curation_loop_audit,health |
| premarket | Mon 09:00 | High | 375.15 | 108 | write-write, both start this minute and run >=1 min: strategy_watchpool,trade_ai_scans,watch_directive_hits,watchlist_items / heavy provider: Finvizx14,Schwabx18 / 5 concurrent jobs with runtime>=2min |
| RTH | Mon 09:30 | High | 345.23 | 90 | write-write, both start this minute and run >=1 min: strategy_watchpool,trade_ai_scans,watch_directive_hits,watchlist_items / heavy provider: Finvizx15,Schwabx15 / 5 concurrent jobs with runtime>=2min |
| after-close | Mon 16:00 | High | 406.5 | 106 | write-write, both start this minute and run >=1 min: fred_economic_series,fundamental_data,hermes_directive_hits_staging,hermes_research_intelligence,hermes_validation_findings,inference_ensemble_jobs |
| evening | Mon 20:00 | High | 115.3 | 68 | write-write, both start this minute and run >=1 min: aegis_covered_call_candidates,aegis_evidence_ledger,aegis_portfolio_briefs,aegis_rotation_candidates,aegis_steph_escalations,aegis_symbol_snapshot_ |
| weekend | Sat 20:00 | High | 106.0 | 58 | write-write, both start this minute and run >=1 min: aegis_covered_call_candidates,aegis_evidence_ledger,aegis_portfolio_briefs,aegis_rotation_candidates,aegis_steph_escalations,aegis_symbol_snapshot_ |

**Recommended staggering:** spread `*/N` RTH lines off :00/:30, for example by phase-shifting `*/10` to `3-59/10` and `*/15` to `7-59/15`. Move the 13 `*:0/5` timers (9 of them no-op personas) to a single runtime scheduler. Give n8n shadows their own lock or remove the duplicate trigger.

## 2. Duplicates

### V2's named groups, verified

| group | type | members | verification | action |
|---|---|---|---|---|
| D-IDENT-01 | identical-command | llm-intelligence-enrichment[L184];llm-intelligence-enrichment[L185];llm-intelligence-enrichment[L186] | VERIFIED (in V2's 10) | MERGE into one line (union schedule) — zero-risk syntactic; one lock/log already shared |
| D-IDENT-02 | identical-command | run-protection-pipeline-at-x-30-9-16[L358];run-protection-pipeline-at-30-20[L359] | VERIFIED (in V2's 10) | MERGE into one line (union schedule) — zero-risk syntactic; one lock/log already shared |
| D-IDENT-03 | identical-command | snaptrade-sync[L479];snaptrade-sync[L480] | VERIFIED (in V2's 10) | MERGE into one line (union schedule) — zero-risk syntactic; one lock/log already shared |
| D-IDENT-04 | identical-command | run-options-monitor[L697];run-options-monitor[L698] | VERIFIED (in V2's 10) | MERGE into one line (union schedule) — zero-risk syntactic; one lock/log already shared |
| D-IDENT-05 | identical-command | options-chain-snapshot[L759];options-chain-snapshot[L765] | VERIFIED (in V2's 10) | MERGE into one line (union schedule) — zero-risk syntactic; one lock/log already shared |
| D-IDENT-06 | identical-command | defense-recommendations[L760];defense-recommendations[L766] | VERIFIED (in V2's 10) | MERGE into one line (union schedule) — zero-risk syntactic; one lock/log already shared |
| D-IDENT-07 | identical-command | hermes-research-agenda-at-45-7[L821];hermes-research-agenda-at-15-18[L822] | VERIFIED (in V2's 10) | MERGE into one line (union schedule) — zero-risk syntactic; one lock/log already shared |
| D-IDENT-08 | identical-command | run-cio-event-detector-once-at-0-5[L844];run-cio-event-detector-once-at-0-8[L845];run-cio-event-detector-once-at-0-9[L84 | VERIFIED (in V2's 10) | MERGE into one line (union schedule) — zero-risk syntactic; one lock/log already shared |
| D-IDENT-09 | identical-command | active-trader-session-review[L1010];active-trader-session-review-close[L1011] | VERIFIED (in V2's 10) | MERGE into one line (union schedule) — zero-risk syntactic; one lock/log already shared |
| D-V2-IDENT-199-213 | same script, different slots (V2 listed as identical) | market-regime-collector[L199];market-regime-collector[L213] | PARTIAL: commands are NOT identical | MERGE only after deciding whether the 06:30 slot also needs the classifier; not a zero-risk syntactic merge |
| D-V2-C5a | multiple cleaners, one table | cleanup-stale-proposals[L132];run-scheduled-stale-proposal-sweeper-rep[L170];run-scheduled-stale-proposal-sweeper-dry[L1 | VERIFIED: 4 live stale-proposal cleaners found | MERGE into one sweeper (single --apply slot + report mode as a flag); retire the --dry-run and duplicate cleanup line |
| D-V2-C5b | same broker read twice (2 min apart) | schwab-position-sync[L499];positions-sync[L1019];positions-shadow-diff[L1020] | VERIFIED | MERGE: positions_sync already reads Schwab via the read-only path; drop schwab_position_sync's RTH slots or run it as po |
| D-V2-C5d | overlapping 5-min scanners | finviz-momentum-scalp-early-lane[L636];run-scalp-shadow-logger[L804];trade-ai-scalp-live[L1050] | VERIFIED (overlap) | MERGE L636+L804 into one 5-min scanner feeding the shadow logger; KEEP L1050 (trade-ai-scalp-live, §23.14 named exceptio |
| D-V2-llmspend | same script, different slots | llm-spend-report-daily[L963];llm-spend-report-weekly[L964];llm-spend-report-monthly[L965] | VERIFIED | MERGE 3→1: one daily run that emits weekly/monthly sections on their day |
| D-V2-openintel | same script, different slots | opening-intelligence[L789];opening-intelligence[L790];opening-intelligence-render[L791] | VERIFIED | MERGE 3→1-2; L789 (03:30) never runs (offpeak --official PEAK_SKIP) — eliminate |
| D-V2-atp2 | same script, different slots | run-scheduled-atp2-research-cycle-evenin[L151];run-scheduled-atp2-research-cycle-at-0-4[L157];run-scheduled-atp2-researc | VERIFIED | MERGE 5→2-3; L157 (04:00) never runs (PEAK_SKIP) — eliminate |
| D-V2-riovernight | same script, different slots | run-research-intelligence-overnight[L725];run-research-intelligence-overnight[L726];run-research-intelligence-overnight- | VERIFIED | MERGE 3→1; L726/L727 skip every weekday (official peak), run only weekends |

**Cron cannot union most of these schedules.** For example, `35 17` and `0 10` cannot be one cron expression without adding fires. On cron, only the L184–186 group collapses (3 → 1 line, 2 retired). Under the n8n dispatcher, every group becomes one row with N slots: 21 → 9 rows, 12 schedule entries retired. V2's figure of 13 lines assumes a dispatcher, not cron.


V2's '10 identical-command groups': **9 are byte-identical after normalisation**. The 10th, L199/L213 `market_regime_collector`, is **not** identical: L213 also chains `market_regime_classifier.py`. So only 9 groups (21 lines → 9 lines) are zero-risk merges. Merging by `union schedule` is possible in a single cron expression for only some of them; see consolidation.csv.

### Other groups found

| type | groups |
|---|---|
| persona fan-out (one runner, N timers) | 1 |
| same script, different args/modes | 28 |
| same script, mode flags differ | 8 |
| same script+args, different slots | 4 |
| double-scheduled across schedulers | 7 |
| multiple scanners, one table | 10 |
| multiple cleaners, one table | 1 |

**Double-scheduled across schedulers** (one script, two schedulers — highest priority, because a second writer is a correctness risk):

| group | members | schedules |
|---|---|---|
| D-SCRIPT-25 | source-attribution-monitor[L433];source-attribution-monitor[498d749165a93ff9] | 0 6 * * * / 0 6 * * * |
| D-SCRIPT-26 | catalyst-calibration-monitor[L435];catalyst-calibration-monitor[283ceeb030de5e66] | 40 5 * * * / 40 5 * * * |
| D-SCRIPT-27 | watch-directives-monitor[L444];watch-directives-monitor[5966437c872aa18b] | 20 6 * * * / 20 6 * * * |
| D-SCRIPT-34 | generate-analyst-daily-digest[L569];generate-analyst-daily-digest[ffa6bbfa93ad4056] | 30 7 * * 1-5 / 30 7 * * 1-5 |
| D-SCRIPT-42 | maturity-remeasure[L1000];maturity-remeasure[e18d7849b4142927] | 40 6 * * 1 / 40 6 * * 1 |
| D-SCRIPT-45 | finviz-view-contracts[tradeai-finviz-view-contracts.timer];finviz-view-contracts[2c725c7dfd4ac62f] | OnCalendar=Mon..Fri *-*-* 06:05:00 / 5 6 * * 1-5 |
| D-SCRIPT-46 | n8n-lab-watchdog[tradeai-n8n-lab-watchdog.timer];n8n-lab-watchdog[9208ac827e514183] | OnUnitActiveSec=5min / OnBootSec=2min / */5 * * * * |

## 3. Consolidation and elimination

### syntactic merge — 9 groups, 2 lines retired

| group | members | target | retire | risk |
|---|---|---|---|---|
| C-IDENT-01 | 3 | single crontab line `20 7,16,12 * * 1-5` | 2 | Low |
| C-IDENT-02 | 2 | single dispatcher row with one argv and N cron slots (schedules not union-able in one cron expression) | 0 | Low |
| C-IDENT-03 | 2 | single dispatcher row with one argv and N cron slots (schedules not union-able in one cron expression) | 0 | Low |
| C-IDENT-04 | 2 | single dispatcher row with one argv and N cron slots (schedules not union-able in one cron expression) | 0 | Low |
| C-IDENT-05 | 2 | single dispatcher row with one argv and N cron slots (schedules not union-able in one cron expression) | 0 | Low |
| C-IDENT-06 | 2 | single dispatcher row with one argv and N cron slots (schedules not union-able in one cron expression) | 0 | Low |
| C-IDENT-07 | 2 | single dispatcher row with one argv and N cron slots (schedules not union-able in one cron expression) | 0 | Low |
| C-IDENT-08 | 3 | single dispatcher row with one argv and N cron slots (schedules not union-able in one cron expression) | 0 | Low |
| C-IDENT-09 | 2 | single dispatcher row with one argv and N cron slots (schedules not union-able in one cron expression) | 0 | Low |

### semantic merge (code) — 7 groups, 11 lines retired

| group | members | target | retire | risk |
|---|---|---|---|---|
| C-V2-C5a | 4 | stale-proposal sweeper: one --apply 08:25 + report 16:10 as flag | 2 | Low |
| C-V2-C5b | 3 | positions_sync owns the broker read; schwab_position_sync becomes a step or is dropped in RTH | 1 | Med (broker-read class, stays on cron) |
| C-V2-C5d | 3 | one 5-min scalp scanner (L636+L804); L1050 untouched | 1 | Med |
| C-V2-llmspend | 3 | llm_spend_report daily with weekly/monthly sections | 2 | Low |
| C-V2-openintel | 3 | opening_intelligence 07:00 + 09:15 | 1 | Low |
| C-V2-atp2 | 5 | atp2 cycle: 3 slots (09:00, 16:05, 20:00) | 2 | Med |
| C-V2-riovernight | 3 | RI overnight: single 20:30 full phase (+ weekend archive) | 2 | Low |

### dispatcher consolidation — 1 groups, 9 lines retired

| group | members | target | retire | risk |
|---|---|---|---|---|
| C-PERSONA | 13 | one tradeai-agent-runtime scheduler (single timer iterates personas with work) | 9 | Low |

### pipeline (manifest flip) — 8 groups, 83 lines retired

| group | members | target | retire | risk |
|---|---|---|---|---|
| C-PIPE-premarket-premarket | 40 | stage `premarket:premarket` (45 5 * * *, window 05:45-07:25) — dispatcher lane `premarket-pipeline-premarket` | 40 | Med |
| C-PIPE-after_close-close-capture | 13 | stage `after_close:close-capture` (5 16 * * 1-5, window 16:05-16:30) — dispatcher lane `after-close-pipeline-c | 13 | Med |
| C-PIPE-after_close-broker-truth | 2 | stage `after_close:broker-truth` (25 17 * * 1-5, window 17:25-17:35) — dispatcher lane `after-close-pipeline-b | 2 | Med |
| C-PIPE-after_close-planning | 14 | stage `after_close:planning` (35 17 * * 1-5, window 17:35-18:40) — dispatcher lane `after-close-pipeline-plann | 14 | Med |
| C-PIPE-hermes_overnight-night | 5 | stage `hermes_overnight:night` (20 2 * * *, window 02:20-06:15) — dispatcher lane `hermes-overnight-pipeline-n | 5 | Med |
| C-PIPE-hermes_overnight-close | 2 | stage `hermes_overnight:close` (13 23 * * *, window 23:13-23:59) — dispatcher lane `hermes-overnight-pipeline- | 2 | Med |
| C-PIPE-hermes_learning-learn | 6 | stage `hermes_learning:learn` (50 10 * * *, window 10:50-11:50) — dispatcher lane `hermes-learning-pipeline-le | 6 | Med |
| C-PIPE-hermes_learning-tune | 1 | stage `hermes_learning:tune` (0 17 * * *, window 17:00-17:15) — dispatcher lane `hermes-learning-pipeline-tune | 1 | Med |

### F pipeline consolidation — 12 groups, 200 lines retired

| group | members | target | retire | risk |
|---|---|---|---|---|
| C-F-P01 | 15 | dispatcher lane `p01-*` (P01 (already a pipeline step or quiet prewarm)); one stage per batch window (5) | 10 | Med |
| C-F-P02 | 13 | dispatcher lane `p02-*` (P02); one stage per batch window (4) | 9 | Med |
| C-F-P03 | 24 | dispatcher lane `p03-*` (P03); one stage per batch window (6) | 18 | Med |
| C-F-P05 | 2 | dispatcher lane `p05-*` (P05); one stage per batch window (1) | 1 | Med |
| C-F-P06 | 4 | dispatcher lane `p06-*` (P06 (already a pipeline step or quiet prewarm)); one stage per batch window (5) | 0 | Med |
| C-F-P07 | 22 | dispatcher lane `p07-*` (P07); one stage per batch window (6) | 16 | Med |
| C-F-P10 | 39 | dispatcher lane `p10-*` (P10); one stage per batch window (6) | 33 | Med |
| C-F-P11 | 15 | dispatcher lane `p11-*` (P11)); one stage per batch window (6) | 9 | Med |
| C-F-P12 | 42 | dispatcher lane `p12-*` (P12 check registry); one stage per batch window (6) | 36 | Med |
| C-F-P13 | 29 | dispatcher lane `p13-*` (P13); one stage per batch window (6) | 23 | Med |
| C-F-P14 | 48 | dispatcher lane `p14-*` (P14); one stage per batch window (6) | 42 | Med |
| C-F-P15 | 7 | dispatcher lane `p15-*` (P15 one persona dispatcher (13 timers → 1)); one stage per batch window (4) | 3 | Med |

### Elimination candidates with proof — 32

never runs (wrapper gate): 2, registry R0_ELIMINATE: 20, never produced output: 1, no-op persona timer: 9

| job | schedule | class | eff/sched fires | proof |
|---|---|---|---|---|
| run-scheduled-atp2-research-cycle-at-0-4[L157] | 0 4 * * 1-5 | never runs (wrapper gate) | 0/5 | 0 of 5 fires in the representative week pass the wrapper: {'offpeak(--official):PEAK_SKIP': 5} |
| agent-intelligence-cron-deep[L160] | 0 8 * * 0 | registry R0_ELIMINATE | 1/1 | lane_registry recommendation R0_ELIMINATE value_class=Legacy |
| agent-intelligence-cron-daily[L187] | 25 6 * * 1-5 | registry R0_ELIMINATE | 5/5 | lane_registry recommendation R0_ELIMINATE value_class=Legacy |
| agent-intelligence-cron-intraday[L192] | 30 11,14 * * 1-5 | registry R0_ELIMINATE | 10/10 | lane_registry recommendation R0_ELIMINATE value_class=Legacy |
| cleanup-stale-locks[L230] | */5 * * * * | registry R0_ELIMINATE | 2016/2016 | lane_registry recommendation R0_ELIMINATE value_class=Technical Debt |
| alert-dispatcher-unified[L279] | 30 8,16 * * * | registry R0_ELIMINATE | 14/14 | lane_registry recommendation R0_ELIMINATE value_class=Legacy |
| ask-alerts[L486] | */30 8-18 * * 1-5 | registry R0_ELIMINATE | 110/110 | lane_registry recommendation R0_ELIMINATE value_class=Unused |
| reporting-engine[L573] | */15 6-17 * * 1-5 | registry R0_ELIMINATE | 240/240 | lane_registry recommendation R0_ELIMINATE value_class=Technical Debt |
| prewarm-finviz-strip-map[L574] | */8 6-17 * * 1-5 | registry R0_ELIMINATE | 480/480 | lane_registry recommendation R0_ELIMINATE value_class=Technical Debt |
| momentum-scalp-validation-fast-path[L633] | */2 6-11 * * 1-5 | registry R0_ELIMINATE | 900/900 | lane_registry recommendation R0_ELIMINATE value_class=Unused |
| prewarm-trade-ai[L753] | */5 * * * * | registry R0_ELIMINATE | 2016/2016 | lane_registry recommendation R0_ELIMINATE value_class=Technical Debt |
| opening-intelligence[L789] | 30 3 * * 1-5 | never runs (wrapper gate) | 0/5 | 0 of 5 fires in the representative week pass the wrapper: {'offpeak(--official):PEAK_SKIP': 5} |
| shadow-batch-generator-at-15-9[L792] | 15 9 * * 1-5 | registry R0_ELIMINATE | 5/5 | lane_registry recommendation R0_ELIMINATE value_class=Experimental |
| shadow-batch-generator-at-15-10[L793] | 15 10 * * 0 | registry R0_ELIMINATE | 1/1 | lane_registry recommendation R0_ELIMINATE value_class=Experimental |
| hermes-cross-source-synthesizer[L823] | 20 18 * * 1,4 | never produced output | 2/2 | log /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/logs/hermes_synthesizer.log does not exist (redirect target never created) |
| approval-reminder-reconcile[L998] | 12 * * * * | registry R0_ELIMINATE | 168/168 | lane_registry recommendation R0_ELIMINATE value_class=Unused |
| hermes-shadow-scorer[hermes-shadow-scorer.timer] | OnCalendar=Mon..Fri *-*-* 10 | registry R0_ELIMINATE | 15/15 | lane_registry recommendation R0_ELIMINATE value_class=Experimental |
| hermes-source-discovery-dryrun[hermes-source-discovery-dryru | OnCalendar=*-*-* 07:15:00 UT | registry R0_ELIMINATE | 7/7 | lane_registry recommendation R0_ELIMINATE value_class=Experimental |
| advisory-shadow-seed[tradeai-advisory-shadow-seed.timer] | OnCalendar=*-*-* 19:45:00 | registry R0_ELIMINATE | 7/7 | lane_registry recommendation R0_ELIMINATE value_class=Experimental |
| tradeai-advisory-shadow-session[tradeai-advisory-shadow-sess | OnCalendar=Mon..Fri *-*-* 09 | registry R0_ELIMINATE | 5/5 | lane_registry recommendation R0_ELIMINATE value_class=Experimental |
| tradeai-agent-runtime-aegis[tradeai-agent-runtime@aegis.time | OnCalendar=*:0/5 | no-op persona timer | 2016/2016 | V2 M2: 7d fires all no-work/empty-queue/REFUSED_STALE, 0 completed runs |
| tradeai-agent-runtime-argus[tradeai-agent-runtime@argus.time | OnCalendar=*:0/30 | no-op persona timer | 336/336 | V2 M2: 7d fires all no-work/empty-queue/REFUSED_STALE, 0 completed runs |
| tradeai-agent-runtime-darwin[tradeai-agent-runtime@darwin.ti | OnCalendar=hourly | no-op persona timer | 168/168 | V2 M2: 7d fires all no-work/empty-queue/REFUSED_STALE, 0 completed runs |
| tradeai-agent-runtime-iris[tradeai-agent-runtime@iris.timer] | OnCalendar=*:0/5 | no-op persona timer | 2016/2016 | V2 M2: 7d fires all no-work/empty-queue/REFUSED_STALE, 0 completed runs |
| tradeai-agent-runtime-maria[tradeai-agent-runtime@maria.time | OnCalendar=*:0/5 | no-op persona timer | 2016/2016 | V2 M2: 7d fires all no-work/empty-queue/REFUSED_STALE, 0 completed runs |
| tradeai-agent-runtime-risk-agent[tradeai-agent-runtime@risk_ | OnCalendar=*:0/30 | no-op persona timer | 336/336 | V2 M2: 7d fires all no-work/empty-queue/REFUSED_STALE, 0 completed runs |
| tradeai-agent-runtime-sentinel[tradeai-agent-runtime@sentine | OnCalendar=*:0/5 | no-op persona timer | 2016/2016 | V2 M2: 7d fires all no-work/empty-queue/REFUSED_STALE, 0 completed runs |
| tradeai-agent-runtime-tax-agent[tradeai-agent-runtime@tax_ag | OnCalendar=Mon-Fri *-*-* 17: | no-op persona timer | 5/5 | V2 M2: 7d fires all no-work/empty-queue/REFUSED_STALE, 0 completed runs |
| tradeai-agent-runtime-vega[tradeai-agent-runtime@vega.timer] | OnCalendar=*:0/5 | no-op persona timer | 2016/2016 | V2 M2: 7d fires all no-work/empty-queue/REFUSED_STALE, 0 completed runs |
| cio-memory-shadow-measure[tradeai-cio-memory-shadow-measure. | OnCalendar=*-*-* 06:20:00 | registry R0_ELIMINATE | 7/7 | lane_registry recommendation R0_ELIMINATE value_class=Experimental |
| tradeai-stance-organic-observe-early[tradeai-stance-organic- | OnCalendar=*-*-* 06:35:00 | registry R0_ELIMINATE | 7/7 | lane_registry recommendation R0_ELIMINATE value_class=Experimental |
| tradeai-stance-organic-observe[tradeai-stance-organic-observ | OnCalendar=*-*-* 09:05:00 | registry R0_ELIMINATE | 7/7 | lane_registry recommendation R0_ELIMINATE value_class=Experimental |

"never produced output" is flagged only when the command's own `>>` redirect target does not exist, which proves the redirect never ran (for example L823 `hermes_synthesizer.log`, V2 M1). Lines with no redirect at all (V2 M7: 18 lines) are **not** flagged here. Their output cannot be judged from a log.

## Method limits

- **Runtimes:**
  - Systemd units: journal wall-clock or Starting→Finished times (7 d).
  - Health-tick steps: `health_tick_history.jsonl`.
  - Cron lines: log timestamps (fire → last timestamp before the next fire; a lower bound when a job logs only at start) or log mtime − last fire (one sample, unshared logs only). The rest assume 1 min.
- **Static provider and table attribution is an approximation.** LLM vendor calls through the model chooser appear under the chooser, so DeepSeek, OpenAI and Grok are under-counted. Telegram mentions include gated or comms-editor paths.
- **n8n:** the 12 'active' workflows come from the 16:00Z snapshot. `9208ac827e514183` (lab-watchdog shadow) stopped at 18:05 ET (V2 C10), so its lock collision with the timer is historical.
- **Calendar:** the representative week excludes DST transitions and holidays. In EST (from 2026-11-01) the offpeak gates shift by one hour. Re-run with `UTC_OFFSET_H=-5` and a November `WEEK_START`.
