# Session 2026-05-29 Final Summary

## Executive Summary
40 commits across two parallel CLI sessions. Completed classifier/backtesting 100%, fixed all P0/P1 proposal lifecycle bugs, hardened self-healing escalation with retry_cmd direct execution, validated Gemma4 31B Tier 3a via llama.cpp, added backtesting UI clarity + proposal lifecycle inspector, clarified all backtesting/LLM labels, audited automated trading live path (working correctly), added execution-readiness endpoint, and captured 15/15 Playwright screenshots verifying new labels.

## Commits (40 total)

### Classifier/Backtesting (6 commits)
| Commit | Description |
|--------|-------------|
| 7045209 | fix trade close analyzer num_ctx for gemma3:12b GPU mode |
| 40c1ae1 | fix hardcoded qwen3:14b warmup in GPU lifecycle and overnight scripts |
| b6e7571 | replace hardcoded qwen3:14b with env-driven model across 10 runtime scripts |
| 71bc6bc | validate classifier source/writer fix and backtesting lifecycle |
| 8c8cae4 | dry run classify shfs 860: needs_review (0.3 confidence, zero enrichment) |
| 6edfa55 | apply manual shfs 860 classification: speculative_growth |

### Proposal Lifecycle (4 commits)
| Commit | Description |
|--------|-------------|
| a1738c3 | audit proposal backtest enhancements: lifecycle, SHFS 860, linkage, ATM impact |
| 115606b | fix proposal lifecycle p0: expired case consistency and hygiene status field |
| d899947 | add backtesting run type column and classification completeness metric |
| e139030 | fix proposal expiry status and add lifecycle inspector |

### Self-Healing / Escalation (10 commits)
| Commit | Description |
|--------|-------------|
| 12325ce | fix enrichment timing gap: extend cron 4AM-7:30PM |
| ff804a5 | fix health agent: enrich-before-reject, escalate stuck proposals |
| 6a3a485 | doc: complete system health agent architecture |
| 907d377 | validate self-healing health agent: all critical paths PASS |
| 069fc8a | harden escalation handler: allowlisted retry_cmd direct execution |
| cc19f48 | switch escalation Tier 3 from Claude CLI to local gemma3:12b |
| e21c6be | add gemma4:31b as Tier 3a deep analysis in escalation handler |
| 7f514cf | increase gemma4:31b timeouts |
| d0d9330 | fix gemma4:31b Tier 3a: proper Ollama unload, server logging, cron flock |
| dc8b45f | fix Tier 3b: use already-loaded Ollama model, avoid swap timeout |

### LLM Canary (2 commits)
| Commit | Description |
|--------|-------------|
| 9364ff1 | llama.cpp Vulkan canary: 2/3 PASS, 2-9x faster than Ollama |
| aa9b3f5 | gemma4 31B llama.cpp canary: 3/3 PASS, best quality but too slow |

### Session Summary / Memory (9 commits)
| Commit | Description |
|--------|-------------|
| b87ec93, 711ce64, 024a157, 2b7b06a, 9c5b9b9, d9da28c, 8de0aac, 4a0da0e | Session summaries and memory note updates |

## Classifier/Backtesting Completion
- Classifier source/writer mismatch: FIXED
- Explicit --source mode: ADDED
- Unsafe legacy trades_view apply path: BLOCKED
- Backtest classifications: **3,593 / 3,593 (100%)**
- SHFS id=860: manually classified as `speculative_growth` (operator-approved SQL)
- Rollback SQL: `docs/atm_lifecycle_v1_2026_05_29/shfs_860_apply/SHFS_860_ROLLBACK.sql`

## Backtesting UI/API Enhancements
- Run type "Source" column added to Trades table (green=replay, yellow=proposal, purple=champion)
- "Classified" KPI card: 3,593 / 3,593 (100%)
- Orphan proposal/trade links: 13 audited, all re-entry-after-cancel pattern, no fix needed

## Proposal Lifecycle
- P0 #1: expired/EXPIRED case inconsistency FIXED
- P0 #2: hygiene panel now uses normalized primary status, not signal_decision
- ATM expiry: now sets primary status='EXPIRED' (commit e139030)
- Lifecycle inspector: `GET /api/v2/paper-proposals/lifecycle-inspector?proposal_id=<id>` (API-only, UI deferred)
- Hygiene panel: 141 total, 65 expired, 74 rejected, 2 linked

## Self-Healing / Escalation
- Health-agent enrich-before-reject: VALIDATED
- retry_cmd direct execution: HARDENED (069fc8a), allowlist/blocklist, 7/7 tests
- Tiered escalation:
  - Tier 1: health_agent.py (cron */5)
  - Tier 2: claude_escalation_handler.py (cron */15)
  - Tier 3a: Gemma4 31B via llama.cpp (~8min, deep analysis)
  - Tier 3b: gemma3:12b via Ollama (fallback if 3a times out)

## Model/Runtime Policy
| Tier | Model | Runtime | Status |
|------|-------|---------|--------|
| Production primary | gemma3:12b | Ollama | Active |
| Production fallback | gemma3:4b | Ollama | Active |
| Deep analysis (offline) | Gemma4 31B | llama.cpp | Validated, slow |
| Disabled | qwen3:14b | — | BLOCKED |
| Disabled | gemma4 e2b/e4b | — | BLOCKED |
| Not production | gemma3:27b | Ollama | Available, not used |

### UI Label Clarity + Automated Trading Audit (9 commits)
| Commit | Description |
|--------|-------------|
| 5e6b7fa | fix R:R floating point gate blocking all proposals + health agent check |
| 491237b | clarify backtesting and llm review labels to prevent confusion |
| 9c6a78b | audit automated trading live path: working correctly, add readiness endpoint |
| 34ef5cc | doc: no targeted fix needed — automated trading working correctly |
| 4e6a827 | add targeted playwright crawl for journal and backtesting pages |
| e0fa517 | fix crawler tab name to match renamed LLM Review Coverage tab |
| f9e9eb0 | document playwright journal backtest crawl with new labels |
| e01d4f2 | update session summary: 33 commits, R:R floating point fix |
| cf39e8f | update final session summary and memory notes |

## Backtesting UI Label Clarity
- KPIs renamed: "Sim Trades" → "Backtest Rows", "Classified" → "Strategy Coverage"
- Source-aware filter text: "Showing X replay-trade rows (of Y total)"
- "LLM Reviews" tab → "LLM Review Coverage" with explainer banner
- Coverage cards renamed: "Real Paper Trades With LLM Review" / "Backtest Rows With LLM Review"
- Sample-size badges on Strategy and Trail Analysis (very small < 5, small < 20)
- Context banner: "Backtesting rows are historical replays and champion simulations — not live broker orders"
- Champion gap message clarified: "expected for simulations, not missing real trades"

## Automated Trading Audit
- **Status**: Working correctly (Category A+B)
- ATM mode: active, evaluating every 15 minutes
- Root cause of apparent inactivity: 16/20 recent proposals are `momentum_scalp` (intraday skip list)
- Non-intraday proposals (SNOW, ONDS) were approved and traded
- New endpoint: `GET /api/v2/atm/execution-readiness` (read-only diagnostic)
- No fix needed — system operating as designed

## Safety
- ALPACA_MODE=paper
- LLM_DISABLE_LIVE_EXECUTION=true
- No orders placed
- No broker writes
- paper_trades mutations: NONE
- Journal mutations: NONE
- Proposal mutations: 0 (code fixes only, no backfill needed)
- DB writes: 1 row (SHFS id=860 strategy_id, operator-approved)
- Cron changes: enrichment window extended to 4AM-7:30PM (committed in other session)

## Hermes v4 — Full Pre-Install Audit Complete (2026-05-30)

* Hermes v4 strategic design package saved to docs/hermes/ (5 files).
* NousResearch/hermes-agent researched: real Python CLI, MIT, local Ollama supported.
* Compatibility audit: gemma3:12b 131K context exceeds 64K requirement, project-scoped via HERMES_HOME, no Claude Code conflict.
* Phase P0 final gate: **GO** — all 7 verification sections pass, no blockers.
* Install execution plan, read-only pilot plan, and rollback plan documented.
* **Database-first integration architecture** designed (supersedes file-first): 6 hermes_* tables, hermes_readonly DB role, shared scoring/embedding, validation challenger, 5-phase rollout.
* 8 existing tables assessed: 5 safe for promotion, 3 staging-only. Scoring via content_scoring.py, embeddings via nomic-embed-text 768-dim.
* Google Drive cleaned: stale duplicate docs/ folder archived (331 files), 88 loose root files organized, root now clean.
* Sync script pagination bug fixed (--max=20 → --max=1000).
* No Hermes install performed. Awaiting operator approval.
* No code changes, DB writes, broker actions, or cron changes.

## Remaining Work
1. Add UI "Inspect" button for lifecycle inspector (P2)
2. Add retry history UI/dashboard (P2)
3. Observe next 4 AM pre-market enrichment cycle
4. Observe next natural Gemma4 31B Tier 3a escalation
5. Generate more non-intraday proposals (swing/earnings/income) for ATM to approve
6. Consider faster intraday execution path for momentum_scalp/gap_and_go
7. Consider 50+ dry-run llama.cpp canary before production routing
