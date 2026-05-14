# Phase 2C — Nightly Hybrid RAG Enablement

**Date:** 2026-05-14
**Status:** ENABLED for daily 23:00 deep queue

## Why Nightly Enablement Is Approved

The 20-job two-stage pilot demonstrated:
- 20/20 jobs succeeded, 0 failures
- Two-stage lifecycle worked cleanly (no model co-residency violations)
- Deep overnight jobs previously had ZERO RAG context (SQL-only)
- Hybrid RAG adds 10 context results from 2-6 source types per job
- No noise or quality degradation observed
- Prefetch overhead: 6.8s for 20 jobs (~341ms avg)
- Total pilot runtime: 20.1 minutes

## What Changed

The daily 23:00 deep queue cron now includes `--enable-hybrid-rag`.

**Old daily cron:**
```
0 23 * * * cd ... && ./scripts/run_deep_overnight_llm_window.sh >> logs/deep_overnight_llm_window.log 2>&1
```

**New daily cron:**
```
0 23 * * * cd ... && ./scripts/run_deep_overnight_llm_window.sh --enable-hybrid-rag >> logs/deep_overnight_llm_window.log 2>&1
```

**Friday extended cron:** UNCHANGED (no `--enable-hybrid-rag`)

## Two-Stage Lifecycle

| Stage | Models | Purpose | Duration |
|-------|--------|---------|----------|
| A (prefetch) | nomic + qwen3-embedding:8b | Hybrid context retrieval | ~10-30s |
| Transition | unload qwen3-embedding | Prevent co-residency | ~5s |
| B (generation) | gemma3-overnight | Deep reasoning with cached context | ~20-60 min |
| Restore | qwen3:14b + nomic | Production model restore | ~10s |

**Hard rule:** qwen3-embedding:8b and gemma3-overnight must NEVER be co-resident.

## Approved Job Types

risk_synthesis, recovery_watch_review, closed_trade_review, auto_journal_review,
manual_journal_review, journal_pattern_review, proposal_review, strategy_classification

## Blocked Job Types

Market-hours agents, Telegram, OpenClaw, broker/execution, risk gates, order placement

## Production Unchanged

| Item | Changed? |
|------|----------|
| Production content_embeddings | NO |
| Global production RAG routing | NO |
| Market-hours RAG behavior | NO |
| .env | NO |
| Broker/holdings/execution | NO |
| Friday extended hybrid | NO (disabled) |
| Phase 2D promotion | BLOCKED |

## Monitoring

```bash
./scripts/monitor_phase2c_hybrid_nightly.sh
```

## Rollback

**Preferred** — restore pre-change crontab backup:
```bash
./scripts/rollback_phase2c_hybrid_nightly.sh
```

**Manual fallback** — if backup missing, remove all hybrid flags:
```bash
crontab -l | sed \
  -e 's/ --enable-hybrid-rag//g' \
  -e 's/ --hybrid-prefetch-limit [0-9]*//g' \
  -e 's/ --hybrid-job-types [^ ]*//g' \
  -e 's/ --hybrid-context-file [^ ]*//g' \
  -e 's/ --hybrid-final-k [0-9]*//g' \
  -e 's/ --hybrid-mode [^ ]*//g' \
  -e 's/ --hybrid-strict [^ ]*//g' \
  | crontab -
```

Rollback disables Phase 2C nightly hybrid only. Phase 1 base deep overnight schedule is preserved.
