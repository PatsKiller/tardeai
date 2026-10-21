# n8n LLM lanes on the governed bridge, batches 1–4: operator steps (operator packet, 2026-10-21)

```
Status:      DRAFT (operator packet; nothing in it has run on the host)
as_of:       2026-10-21
Measured at: origin/main 7faa8cddf + branch integ/cleanup-batch-d-20261021; host not measured
Authority:   operator 2026-10-21, "approve all your recommendations" (PR triage rows #1804–#1807).
             AGENTS.md §23.4, §23.11, §23.18, §23.25; operator D10 ("try OAuth first … then DeepSeek").
Source:      PRs #1804 → #1805 → #1806 → #1807, integrated in order
```

## What merged code does by itself

Nothing runs differently on the host until the steps below are done.

- **Every new branch is behind `TRADEAI_LLM_VIA_BRIDGE`, which only the n8n run executor sets.** It sets it from an
  allowlist entry's `llm_route`. The cron path is unchanged.
- **Allowlist (`config/n8n_run_allowlist.json`).** Only the two existing entry-planner entries
  (`watchlist-entry-planner-limit`, `-scope`) gain `llm_route {via: cio-governed-bridge, process_id:
  watchlist_entry_planner}`. Their registry rows stay `r1_pending` with no dispatch block, so they stay inert. The
  `run-research-intelligence-overnight` blocked reason now records that its route blocker is cleared. Every lane main
  had (including #1899/#1904/#1905, `hermes-watchlist-scorer`) is kept exactly as main has it.
- **No lane registry row, health contract, workflow or live-list entry changes.** No other lane gains an allowlist
  entry here. Onboarding each lane is its own reviewed registry-train PR (§23.11 "one registry PR at a time").
- **New registry processes (`config/llm_process_registry.json`).** `analyst_report_critique`,
  `analyst_report_editorial`, `blind_review_runner`, `defense_weekly_oversight`, `due_diligence_questions`,
  `hermes_usefulness_score_n8n`, `incubator_llm_screener` (`default_mode: manual`), `journal_review_builder`,
  `portfolio_lookthrough_themes`, `proposal_llm_review`.
- **Changed registry rows.** Caps the bridge accepts, and `n8n_oauth_first` routing rows. `directive_keyword_enhancer`,
  `hermes_analyst_coverage`, `hermes_cross_source_synthesizer`, `hermes_external_research`, `holdings_llm_refresh`,
  `ri_narrative_enrich`, `topic_ingestion`, `topic_research_synthesizer`, `watchlist_entry_planner`, and the six
  `watchlist_*` agent processes. The six agent rows add grok/chatgpt to `allowed_lanes`; the cron path still requests
  only deepseek-flash for them.
- **Bridge server map.** `cio_governed_model_bridge.CALLER_TASK_PROCESS_MAP` and `governed_process_routes` gain an
  `advisory_desk/<process>` route for each of the 25 processes above (every new and changed row).

## Order (do not reorder)

| # | Step | Who / authority | Proof before the next step |
|---|---|---|---|
| 0 | Release containing these commits is CURRENT | release grant | `GIT_SHA` of CURRENT contains the merge |
| 1 | Restart `cio-governed-bridge.service` so it loads the new server map | operator (bridge restart; same as #1760/#1770) | a dry probe of one new route is refused for caps/consumption, not with an unknown-process error |
| 2 | Seed the new `llm_process_config` rows from the registry, reviewed. It is a DB write. Use the existing registry seed path (`llm_consumption` seeding; precedent `tests/test_llm_process_seed_sync_20261010.py`: a new row carries the registry allowlist and dollar cap, and an operator-set cap is never overwritten). Dry-run first and quote the planned rows. | operator | `SELECT process_id, allowed_lanes, daily_cost_cap_usd FROM llm_process_config WHERE process_id IN (…)` shows the 10 new ids |
| 3 | Per lane, when wanted: a reviewed onboarding PR adds its allowlist entry with `llm_route` and its registry row (`shadow` first) | registry-train PR merge = §17 decision (§23.11) | `check_lane_registry`, `check_n8n_health_contracts` clean |
| 4 | Per lane, live: add the lane id to `TRADEAI_N8N_RELAY_LIVE_LANES` in `~/.config/tradeai/n8n-live-lanes.env` (shared with the gateway) | operator, config-write grant (§23.3) | relay `/runs/<lane>/last?mode=live` shows a `RUN_DONE` receipt |
| 5 | Any n8n workflow import, activation or edit these lanes need (the dispatcher already fires dispatcher rows) | operator, `cron` grant naming the workflow id (§17, §23.11) | `check_n8n_activation_grants.py` clean |

No step above was run by the integrating agent. That covers no bridge restart, DB write, live-list edit, n8n
import or activation, or cron change.

## Rollback

Revert the merge and promote the previous release. The cron path never depended on these branches. Seeded
`llm_process_config` rows are inert without the bridge routes; archive them, do not delete (§0 rule 6).
