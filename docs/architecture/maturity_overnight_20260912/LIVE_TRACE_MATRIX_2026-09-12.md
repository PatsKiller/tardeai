# Live trace matrix — clause → the exact artifact consulted

Every row names a file, a table or a command on this host, not a document.
Captured during 2026-09-12T00:31Z–01:46Z against served SHA `eb648174a`.

| capability | clause | artifact consulted | what it showed |
|---|---|---|---|
| L1 | wake spine runs organically | `/home/johnclaw/trade-ai-state/persistent_wake/state/wakes.jsonl` | 6 wakes, slots 00:00Z and 01:00Z, all `source_sha=eb648174a` |
| L1 | producers are declared and observable | `config/lane_registry.json` + `evaluate_lane()` | 4 spine lanes LIVE (0.10–0.66h), 3 SLOW, 6 UNVERIFIABLE by declaration |
| L1 | durable artifact carries SHA/release/epoch | wake provenance dict | `epoch_id` and `release` absent before this campaign; both now written |
| L1 | one state root | `stat -c %i` on both roots | inodes 9633692 vs 3573658 — two stores |
| L1 | served copy is not behind its producer | `scripts/check_state_root_split.py --json` | 164 stale served files; 19 `data/runtime` files newer on the served side |
| L2 | research producer recurs | `/home/johnclaw/trade-ai-state/persistent_wake/research_producer_health.json` | `outcome: produced`, `produced: 15`, `as_of` 0.36h old |
| L2 | producer reports honestly when it makes nothing | `/home/johnclaw/logs/governed_research_producer.log` | `{"ok": false, "outcome": "broken", "produced": 0}` on budget refusal |
| L2 | memory retrieved with decay, not a cliff | wake provenance `policy_decisions` | `stale_memory_retained_with_decay`, 879 wrong-subject rows excluded |
| L2 | circulation lane is alive | `systemctl --user status tradeai-free-first-circulation` | `failed (Result: timeout)`, 93 consecutive, 0 successes since 2026-09-08 |
| L2 | budget reaches the lane | `/home/johnclaw/logs/governed_research_producer.log` | `BUDGET_REFUSED:CALLER_DAILY_CAP` ×4 consecutive hours |
| L3 | a model authored a grounded judgment | `.../state/l3_judgment_cache.jsonl` | 5 entries, `deepseek-flash` returned, latency 2306–3786ms — on SHAs `14063a767`/`de0843b2d` |
| L3 | on the served epoch | same file, filtered by epoch | **0** |
| L3 | cost provenance | same file | `cost_usd: 0.0` on all five |
| L3 | judgment records are addressable | `.../state/views.jsonl` | two views, 18:00:36Z and 19:00:33Z, confidence 0.72 and 0.60, **one** `judgment_id` |
| L3 | the cache prevents repeat spend | same file | 5 distinct `cache_key`s, identical `input_digest` — 0% hit rate |
| L3 | refuses before spending, while permitted | wake provenance `l3` | `offpeak_deferred`, `provider_call_attempts: 0`, `live_provider_allowed: true` |
| L3 | budget floors exist | `llm_cost_reservations` 36h aggregate | `advisory_desk_opinion` $0.83435/1019 calls of a $1.50 pool |
| L3 | the author lane is registered | `llm_process_config` | **0 rows** for `l3_judgment_author` |
| L4 | anything revisits a due commitment | `crontab -l`, `systemctl --user list-unit-files` | 0 and 0 |
| L4 | somewhere to write an outcome | `scripts/lib/governed_commitment.py` | `GovernedCommitmentOutcome@v1` exists — the finding that it did not is falsified |
| L4 | predictions can be scored | `scripts/sweep_commitment_outcomes.py` dry run | 224 records, 99 predictions, **0 falsifiable**, earliest due 2026-09-17 |
| L5 | a failure surfaces as a failure | `timer_health()` run live | `healthy: true` beside `last_finished_at` 4.4 days old and a non-served SHA |
| L5 | the detector is wired to anything | `scripts/check_dark_contracts.py` `KNOWN_DARK` | the module is listed as having no consumer |
| M2 | contiguous organic cycles | `wakes.jsonl` by slot | 2 of a bar of 3 |
| M2 | gateway provider-ack SETTLED | `communication_events` on the served SHA | 1 SETTLED, 9 UNSETTLED, 1 UNKNOWN_LEGACY |
| M2 | inbound operator consumption | same table, `direction='inbound'` | **0** |
| M2 | commitments frozen before their window | `.../state/commitments.jsonl` | 6 on the epoch, all `frozen_at < due_at` |
| MVL | Sentinel reviews cite evidence | `data/cio/sentinel_reviews.jsonl` | **0 of 140** carry retrieval/evidence/memory fields |
| MVL | Darwin covers eligible artifacts | `data/cio/darwin_scorecards.jsonl` | 136 of 136 = 100% |
| MVL | nightly reflection produces candidates | `data/cio/cio_reflection_candidates.jsonl` | 14 records, 1002 cases seen, `auto_promotions: 0`, newest 2026-08-26 |
| MVL | no broker call | same file | `model_calls: 0`, `cost_usd: 0.0` |
| safety | MBI_BEHAVIOR preserved | every artifact written this campaign | `mbi_behavior: 0`, `authority: READ_ONLY_ADVISORY` |
| safety | one poller per bot token | `ps` over the live host | exactly one, pid 8953, cwd = the served release |
| safety | dry_run writes nothing durable | `scripts/lib/cortex_shadow_pipeline.py` | every durable write guarded at lines 166, 197, 218 |
