# Session 2026-05-28 — Trade AI LLM & Backtesting Summary

**Commits this session:** 13 (a8706f9 through 9b0ef70)

## Executive Summary

Major local LLM safety hardening session. Blocked unstable Qwen3:14b, established gemma3:4b as the sole GPU production model, built an enriched strategy classifier with evidence-based post-validation, applied it to 55 trades, upgraded Ollama 0.20.6 → 0.24.0, and ran workload canaries on Gemma4 and Qwen3 candidates. Gemma4 passes CPU but fails GPU/Vulkan — removed. System is stable on gemma3:4b GPU with full safety gates.

## Runtime & Model Changes

| Before | After |
|--------|-------|
| Ollama 0.20.6 | **Ollama 0.24.0** |
| qwen3:14b loaded with year-2318 expiry | gemma3:4b only, 5m keep_alive |
| No model safety router | Full safety router with disabled model blocking, pre-call cleanup, JSONL audit |
| No systemd override | Systemd drop-in: KEEP_ALIVE=5m, MAX_LOADED=1, NUM_PARALLEL=1 |

## Ollama Upgrade

- 0.20.6 → 0.24.0 (latest stable)
- v0.30-rc29 pre-release: NOT installed (risk)
- Systemd safety override survives upgrade
- GPU layer auto-detection changed (41 → 35 layers) — Ollama optimizes VRAM headroom

## Model Canary Results

| Model | CPU Basic | CPU Workload | GPU Workload | Status |
|-------|----------|-------------|-------------|--------|
| gemma3:4b | PASS | PASS | PASS | **Production** |
| gemma4:e4b | PASS | 3/3 PASS (58-75s) | 0/3 FAIL (garbage) | Removed |
| gemma4:e2b | PASS | 3/3 PASS (45s) | 0/3 FAIL (HTTP 500) | Removed |
| qwen3:14b | PASS | 1/3 (timeout) | N/A | Disabled |

## Final Production Model Decision

**gemma3:4b on GPU (Vulkan, Arc B50).** No change until Ollama adds Gemma4 Vulkan support.

## Classifier Hardening & Enrichment

### Safety Router (a8706f9)
- Disabled model blocking (DISABLED_LOCAL_LLM_MODELS)
- Pre-call cleanup: unloads blocked/stale models
- Fail-closed: if disabled model remains after cleanup, return None
- JSONL safety audit log at logs/llm_router_safety.jsonl

### Evidence-Based Classification (02fdcce, 80b34d9)
- Rewrote prompt to require concrete evidence, not guesses
- Added needs_review/unknown as first-class outputs
- Enriched SQL query joins ticker_strategy_classifications (9,743 rows), watchlist_strategy_cards, paper_trade_proposals
- Fixed JSON parser for malformed LLM array output

### Post-Validation Rules (97cf173)
- Dividend evidence gate: requires dividend/income keywords
- Hold-period gate: strategy-specific min/max ranges
- Hard gate: 0-day hold on long-hold strategy → needs_review unless 2+ sources agree
- Caution gate: 1-5 day hold requires 2+ sources
- Enrichment conflict detection: flags when sources disagree
- ADBE source-data rule: blocks dividend classification on watchlist-only evidence
- Confidence caps by evidence level

### Health Check (a8706f9)
- 7-check gate: Ollama reachable, qwen not loaded, gemma3 numeric, gemma3 JSON, disabled model routing, max one model, no unsafe jobs
- Self-detection fix for preflight from --apply mode (bbe3d54)

## Classifier Apply Results

### Batch 1: 55 trades (bbe3d54)
- 55/55 classified, 0 errors
- 34 strategy_backtest_trades rows updated
- Distribution: speculative_growth 36, recovery_watch 6, swing_trade 5, dividend_growth_compounder 3, sector_rotation 2, core_growth_compounder 2, swing_breakout 1
- Audit: 17/26 sampled evidence_supported, 7 questionable (0-day holds), 2 manual review (ADBE)
- Rollback SQL: docs/atm_lifecycle_v1_2026_05_28/classifier_apply/classifier_apply_55_rollback.sql

### Batch 2: Interrupted (79b2a7d, 1df2076)
- Ollama crashed mid-batch (SIGTERM + Connection refused)
- 0 backtest rows updated (all already classified in batch 1)
- Root cause: trades view shows trade_transactions as unclassified even though strategy_backtest_trades rows are filled
- **Design gap: classifier reads from trades view but writes to strategy_backtest_trades**

### Remaining 4 (6bfddaa)
- V: dividend_growth_compounder (0.9) — 1 row updated
- SHFS: needs_review — no enrichment
- FJSCX x2: needs_review — watchlist only
- 3 backtest trades remain unclassified

## Backtesting Filter Distinction

- Champion simulations: hypothetical (should not look like real trades)
- Replay trades: actual paper trade replays
- Replay proposals: rejected/expired proposal replays
- Real paper trades: actual Alpaca/Schwab paper trades
- Backtesting filters must be data-driven and source-aware

## Current Blockers

1. **Classifier source/writer mismatch**: reads trade_transactions (never updated), writes strategy_backtest_trades → same trades resurface
2. **3 unclassified backtest trades**: SHFS, FJSCX x2 need enrichment data
3. **Gemma4 GPU broken**: Vulkan support missing in Ollama 0.24.0
4. **ADBE watchlist source data**: tagged as speculative_growth in watchlist_strategy_cards (should be core_growth_compounder)

## Next Recommended Steps

1. Fix classifier source/writer alignment
2. Handle remaining SHFS/FJSCX when enrichment available
3. Reopen backtesting lifecycle phases after classifier data stable
4. Re-test Gemma4 GPU after next Ollama update
5. Do not run bulk apply without pre-state export and rollback SQL

## Safety Confirmation

| Check | Status |
|-------|--------|
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| Orders placed | NONE |
| Broker writes | NONE |
| Grok called | NONE |
| Cron changes | NONE |
| Live trading | NONE |
