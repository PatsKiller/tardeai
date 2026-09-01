# Memory Notes for Next Session — 2026-05-29

Status:      HISTORICAL
as_of:       2026-05-29T20:41:58-04:00
Measured at: efcc51365 / not measured

Durable context for the next Trade AI session.

## Classifier State — COMPLETE

- **Source/writer mismatch is FIXED** (commit ae8efe0). `--apply` requires explicit `--source strategy_backtest_trades`.
- Do NOT use the legacy trades_view apply path — it is blocked.
- **3,592/3,593 backtest trades classified** (99.97%).
- **SHFS (id=860) is the only remaining unclassified** backtest row — needs enrichment data or manual classification.
- trade_transactions 153 rows show unclassified in the `trades` view — this is expected and permanent (no strategy_id column).
- No more bulk classifier batches needed.
- Rollback SQL: `docs/atm_lifecycle_v1_2026_05_28/classifier_apply/classifier_apply_55_rollback.sql`

## Backtesting Source Labels

- Champion simulations (BT_* run_id, 3,516 rows) = hypothetical — do NOT treat as real trades
- Replay trades (ER_* run_id, 77 rows) = actual trade replays
- Real paper trades = paper_trades table (38 with strategy_id, 16 closed)
- Filters must remain data-driven and source-aware

## Local LLM Model Policy

- **Primary classifier/review model: gemma3:12b on GPU/Vulkan** — better consistency than 4b
- **Fast fallback: gemma3:4b** — use only if 12b fails health/preflight/timeout/VRAM
- **Offline quality reviewer: gemma4:31b Q3_K_M on llama.cpp** — best output quality, 15-25x slower, hybrid GPU/CPU only
- Do NOT use qwen3:14b, gemma4 e2b/e4b, or gemma3:27b on GPU
- Do NOT call Grok
- Max concurrent local generation jobs: 1
- gemma3:12b requires `num_ctx=4096` to avoid VRAM overcommit on model swap
- Classifier default model is gemma3:12b (set in script, not .env)
- .env `LOCAL_LLM_MODEL=gemma3:4b` is the router fallback only

## llama.cpp Runtime

- Installed at `~/llama-cpp-vulkan/llama-b9405/` (pre-built Ubuntu Vulkan x64, b9405)
- GGUF models at `~/llama-cpp-vulkan/` (gemma3-12b-hf.gguf 6.8GB, gemma4-31b-hf.gguf 14GB)
- Ollama GGUF format is INCOMPATIBLE with upstream llama.cpp — separate downloads required
- llama-server runs on port 8081 (OpenAI-compatible API)
- NOT production — no systemd service, no auto-restart, no VRAM contention guard
- Keep Ollama as production runtime until llama.cpp passes 50+ trade batch validation

## Ollama Configuration

- Version: **0.24.0**
- Systemd override: KEEP_ALIVE=5m, MAX_LOADED=1, NUM_PARALLEL=1
- Health check: `scripts/check_local_llm_health.py` must PASS 7/7 before any LLM action

## Enrichment Pipeline — FIXED (2026-05-29)

- **Root cause:** Proposals created at 4 AM sat unenriched because enrichment crons only ran 9-15. Health agent rejected them at 7 AM (2h stale sweep) with 0 enrichment attempts.
- **Cron fix (12325ce):** Both `auto_enrichment_runner` and `proposal_enrichment_loop` now run `*/10 4-19 * * 1-5` (every 10 min, 4 AM - 7:50 PM weekdays)
- **Health agent fix (ff804a5):** Enrich-before-reject — triggers enrichment up to 3 attempts before rejecting. Only rejects after 3 failed attempts OR 6h hard timeout. Stuck proposals escalated to Claude Code queue.
- **Verify on next pre-market session:** Check that 4 AM proposals get enriched within 30 min, not rejected at 7 AM
- Crontab backup: `/tmp/crontab_pre_enrichment_fix_20260529.txt`

## Escalation Handler — Production-Validated Tiered System

**Validated in production 2026-05-29 11:45 AM.** Fallback chain worked: gemma4 timed out → gemma3:12b completed 4,742 char analysis → queue cleared. No API credits used.

| Tier | Engine | Purpose | Status |
|------|--------|---------|--------|
| 1 | Direct retry_cmd | Execute allowlisted safe commands (17 allowed, 19 blocked) | Active |
| 2 | gemma3:4b (Ollama) | Quick triage diagnosis | Active |
| **3a** | **gemma4:31b (llama.cpp)** | Deep root cause analysis (auto-starts server) | Active (may timeout on cold start) |
| **3b** | **gemma3:12b (Ollama)** | Fast analysis fallback | **Active — primary workhorse** |
| 3c | Claude Code CLI | Optional, requires API credits | Disabled by default (`ESCALATION_USE_CLAUDE_CLI=true` to enable) |

- **Claude CLI is NOT the default** — credit balance was exhausted. All tiers use free local models.
- **Allowlist config:** `config/claude_escalation_allowlist.yaml` — env guards enforce ALPACA_MODE=paper
- **Retry log:** `logs/claude_escalation_retry_cmd.jsonl`
- **Known:** gemma4:31b Tier 3a may timeout on cold start (server load + inference > 360s). Tier 3b catches it.

## Health Agent Self-Healing (4 Levels)

1. **Retry command** — each component has a retry_cmd, run automatically on failure
2. **Agent auto-queue** — stale agents get refresh jobs queued in watchlist_agent_jobs
3. **Enrich-before-reject** — stuck proposals get enrichment triggered (up to 3 attempts) before rejection
4. **Tiered escalation** — unresolved problems go through Tier 1→2→3a→3b→3c chain (see above)
- Full architecture doc: `docs/project/SYSTEM_HEALTH_AGENT_ARCHITECTURE.md`

## Auto-Trading Pipeline — 4 Cascading Fixes (2026-05-29)

Zero trades executed today due to 4 cascading failures. All fixed:

| # | Problem | Root Cause | Fix | Commit |
|---|---------|-----------|-----|--------|
| 1 | 4 AM proposals died unenriched | Enrichment crons only ran 9-15 | Extended to `*/10 4-19` | 12325ce |
| 2 | All new proposals blocked | R:R floating point: `2.00 < 2.0` | Added round(4) + 0.005 tolerance | 5e6b7fa |
| 3 | momentum_scalp/gap_and_go always rejected | `same_day_skip_strategies` gate | Removed skip, proceed through normal gates | 5caf445 |
| 4 | FATN ready at 14:20, ATM didn't look until 14:30 | ATM only on 15-min cron | Immediate ATM trigger on ENTRY_ZONE_VALID | 5caf445 |

**Verify tomorrow morning:**
- 4 AM proposals get enriched within 30 min
- Proposals with R:R ≈ 2.0 pass pre-promotion gate
- momentum_scalp proposals proceed through ATM (not auto-skipped)
- ATM fires immediately when enrichment sets ENTRY_ZONE_VALID
- If screener finds liquid candidates, trades should execute

**Health agent now monitors:**
- Pre-promotion gate blocking rate (R:R false positives)
- Open trades with no agent analysis in 3+ days
- Enrichment-stuck proposals (enrich-before-reject)

## Hardcoded Model References

- **FIXED** (commits 40c1ae1, b6e7571): 13 runtime scripts cleaned
- Remaining qwen3:14b references are only in comments/docstrings and historical validation scripts

## Safety

- ALPACA_MODE=paper — do NOT change
- LLM_DISABLE_LIVE_EXECUTION=true — do NOT change
- No live execution
- No bulk apply without pre-state export and rollback SQL
