# Phase 2 — Recurring research producer: scheduled-entry trace + gap

Date (America/New_York): 2026-09-10 01:00. Campaign: Grok-closure.

## Gap found

The persistent-wake subject selector reads a research-objects JSONL feed
(`TRADEAI_WAKE_RESEARCH_OBJECTS_PATH`, `scripts/lib/wake_subject_selector.py`),
but **nothing in the serving tree writes that feed**. Every research cron
produced research into its own desk store, never a `ResearchObject@v1` into the
wake feed. Therefore the selector's `unconsumed_research` candidates were always
empty and no `research`-typed wake object was ever produced.

## Scheduled research entries (classified)

`crontab_backup.txt` carries 883 lines; 57 research-related cron entries (the
"127" figure spans crontab + systemd timers + internal cadence loops). They fall
into exactly one producer family, all with the SAME disconnect:

| Family | Producer | Provider/router | Durable output | Wake feed? |
|---|---|---|---|---|
| Tiered SLA dispatcher | `research_scheduler.py` → `hermes_external_researcher.py` | DeepSeek (governed external; local generative forbidden) | `hermes_external_research` table | NO |
| ATP-2 cycle | `run_scheduled_atp2_research_cycle.sh` | mixed | ATP-2 stores | NO |
| Auto-research | `auto_research.py` | mixed | auto-research store | NO |
| Brave/search | `brave_router.py` (governed), `brave_search.py`, `web_research.py` | Brave | `brave_router_cache.json`, research stores | NO |
| Research intelligence (RI) | `run_research_intelligence_overnight.sh`, `research_intelligence_queue.py`, `topic_research_synthesizer.py` | DeepSeek | `hermes_research_intelligence` table | NO |
| Insight extractor | `research_insight_extractor.py` | local (heuristic) | `research_insights` | NO |
| Finviz proactive/sector | `finviz_proactive_research.py`, `finviz_sector_research.py` | Finviz | article/ticker stores | NO |
| Hermes agenda/worker/catalyst | `hermes_research_agenda.py`, `hermes_research_worker_pool.py`, `hermes_momentum_catalyst_researcher.py` | DeepSeek | `hermes_research_intelligence` | NO |
| Alex gov research | `alex_gov_research.py` | gov sources | alex store | NO |

None of the ~57 entries emits a `ResearchObject@v1` row (with `subject_guid`,
`research_id`, source URL, content hash) into `TRADEAI_WAKE_RESEARCH_OBJECTS_PATH`.
`wake_selection_feed.export_research_proxies` (referenced in earlier handoffs) is
not present in the serving tree — the producer side of the loop was never landed.

## Canonical recurring path implemented

`scripts/lib/governed_research_producer.py` — the ONE producer:

```
scheduled trigger
  → governed brave_router.search (budget governance, fail-closed)
  → durable ResearchObject@v1 (only after real provider results)
  → atomic append to TRADEAI_WAKE_RESEARCH_OBJECTS_PATH (dedupe by research_id)
  → wake_subject_selector → run_persistent_wake
```

- Feature flag `GOVERNED_RESEARCH_PRODUCER_ENABLED` (default OFF).
- No direct provider bypass (only `brave_router.search`; asserted by test).
- Distinguishes `nothing_eligible` vs `produced` vs `broken`; budget denial is
  counted separately.
- Feed health (count/age/last-success/failure) via `GOVERNED_RESEARCH_PRODUCER_HEALTH_PATH`.
- 12 tests cover: disabled, real-success production, provider unavailable,
  budget denied, stale-only empty, duplicate dedupe, missing source SHA,
  missing subject_guid skip, empty feed, feed age, no-bypass, atomic append.
- Registered in `run_cio_hardening_ci.py` GATES; `check_test_coverage.py
  --fail-on-new` reports 0 new unlisted.

## Rollback / disable

Disable = set `GOVERNED_RESEARCH_PRODUCER_ENABLED=0`. Rollback = stop appending;
the feed is append-only (never truncated by this module); the health file
records the last write. The module writes no DB rows and no broker state.
