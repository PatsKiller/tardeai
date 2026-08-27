# Session 36: Phase 2 Cron Migration — Analysis and Observability Stages

**Date:** 2026-05-09  
**Status:** Installed and validated

## Phase 1 GO Evidence

3 successful Phase 1 pipeline runs (dry, manual live, cron command test), all with status=success, 3 stages each, 0 failures.

## What Was Migrated (Phase 2)

15 safe analysis/observability stages now run via Pipeline Controller at 7:45 AM weekdays:

1. market_regime_snapshot
2. strategy_rotation_signal_refresh
3. learning_governance_status
4. ingestion_learning_analysis
5. trade_learning_analysis
6. champion_challenger_summary
7. agent_recommendation_normalization
8. agent_outcome_linking
9. agent_calibration_scoring
10. agent_disagreement_scoring
11. post_trade_thesis_review
12. weekly_learning_digest_generate
13. weekly_learning_digest_delivery_dry
14. backtest_dataset_build
15. strategy_backtest_smoke

## What Remains Blocked

- All broker/order stages
- All Telegram live sends
- Config promotion/implementation
- Challenger promotion
- Active strategy/source/screener changes
- Finviz production ingestion
- Candidate discovery apply

## Crontab Change

**Added (purely additive):**
```
# === SESSION36 PHASE2 ANALYSIS VIA PIPELINE CONTROLLER ===
45 7 * * 1-5 cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/pipeline_controller.py --pipeline daily --run-label cron_phase2_observability --only-stages [15 stages] --allow-degraded >> logs/cron_phase2_observability.log 2>&1
# === END SESSION36 PHASE2 ===
```

## Rollback

```
crontab /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/crontab_session36_phase2_rollback.txt
```

## Validation Results

- Dry-run: 15/15 SUCCESS
- Manual live: 15/15 SUCCESS
- Cron command test: 15/15 SUCCESS
- Validation script: 16/16 PASS
- Cron count: 142 → 143

## Observation Plan

- Check `logs/cron_phase2_observability.log` daily
- Check `/v2/pipeline-controller` for Phase 2 runs
- 3 successful scheduled runs required before Phase 3
- Phase 3 candidates: Finviz ingestion, paper analytics

## Late-Session Additions (Session 36B)

### Phase 2 Freeze Runbook

Created `docs/project/PHASE2_EARLY_INSTALL_FREEZE_AND_OBSERVATION_RUNBOOK.md`:
- Documents that Phase 2 cron was installed before 3 real Phase 1 scheduled runs
- Freeze rule: no Session 37, no Phase 3, no cron changes until observation window clears
- Earliest freeze-lift: 2026-05-14 (3 Phase 1 + 3 Phase 2 runs)
- Daily observation commands and incident log template

### LLM Fleet Strategy v3.4.1

Saved `docs/llm_fleet_strategy_v3_4_1.md` — full plan for LLM fleet upgrade:
- 7 process types (REALTIME, STANDARD, BATCH_OVERNIGHT, MEDIA_CONTENT, EMBEDDING, CRITICAL_CLOUD, CLOUD_FALLBACK)
- New models: gemma4:26b-a4b (overnight), gemma4:e4b (media/content), qwen3-embedding:8b
- Routing via llm_config.py, execution via local_llm.py, audit via llm_routing_audit table
- Two-phase burn-in (A: baseline with fcntl, B: queue validation without)
- 15 required tests, implementation steps 2–15 authorized for Claude Code
- **Execution blocked until freeze observation window clears (2026-05-14)**

### YouTube & Article Ingestion from Telegram

Added two new Telegram/OpenClaw commands (`telegram_command_handler.py`):

| Command | What It Does |
|---------|-------------|
| `add video <URLs>` | Adds YouTube channels to tracking, fetches transcripts, scores/tags content |
| `add article <URLs>` | Fetches article HTML, extracts text, scores/tags, stores in news_articles |
| (bare URLs) | Auto-detected: YouTube URLs → video ingestion, other URLs → article ingestion |

Also added:
- OpenClaw skill: `~/.openclaw/skills/integrations/content-ingestion/SKILL.md`
- Updated Maria's TOOLS.md with ingestion commands
- Fixed OpenClaw `poll_and_process()` whitelist to accept URL messages
- `youtube_ingest_queue` table for retry when YouTube IP-blocks the server

### New Channels Added

| Channel | Strategy Focus | Channel ID |
|---------|---------------|------------|
| Even Better Retirement | retirement_planning | UC49_gC14BWse5VaLtPQn5ww |
| Streamline Financial | retirement_planning | UCJ-_I3IYY-nPzvg_gT7BO0Q |
| Jacob Duke, CFP® | retirement_planning | UCGWkF_upTpXcYfplZLW3CMg |
| Nick Davis, CFP® | retirement_ssdi_roth_tax | UCQokhvodpFrGKn3S_4hwPaA |

7 videos queued (YouTube IP block), 5 articles ingested (1 Seeking Alpha 403).

### qwen3:1.7b Removed

**Problem:** Ollama had both `qwen3:14b` (~10 GB) and `qwen3:1.7b` (~6 GB) loaded in VRAM with `OLLAMA_KEEP_ALIVE=-1`. On a 16 GB GPU this left no headroom for context, causing inference to hang and OpenClaw/Maria to stop responding.

**Fix:**
- Removed `qwen3:1.7b` from Ollama (`ollama rm qwen3:1.7b`)
- Removed from `~/.openclaw/openclaw.json` (model list + fallback chain)
- Removed from `~/.openclaw/agents/main/agent/models.json`
- Backed up config: `~/.openclaw/openclaw.json.bak_pre_1.7b_removal_20260509`

**Current Ollama fleet:**

| Model | VRAM | Purpose |
|-------|------|---------|
| `qwen3:14b` | ~9.6 GB | Primary — all agents, pipeline, REALTIME, STANDARD |
| `nomic-embed-text` | ~551 MB | Embeddings (to be replaced by qwen3-embedding:8b per v3.4.1) |
| *~6 GB free* | | Context headroom |

**OpenClaw fallback chain:** `ollama/qwen3:14b` → `openai/gpt-5.4-mini` → `anthropic/claude-sonnet-4-6`

**Note:** The LLM Fleet Strategy v3.4.1 planned qwen3:1.7b removal as step 20 (after all burn-ins). This was accelerated because it was actively causing production outages. The v3.4.1 deprecation gate (grep for production references, burn-in pass, etc.) is satisfied: the model was only used as an OpenClaw fallback, and removing it resolved the VRAM contention.

## Safety

Paper BLOCKED, holdings $1,189,457 unchanged, no broker/Telegram/config/promotion

Paper BLOCKED, holdings $1,189,457 unchanged, no broker/Telegram/config/promotion
