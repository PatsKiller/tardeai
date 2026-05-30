# Memory Notes for Next Session — 2026-05-29 Final

## Backtest Classification
- **Complete**: 3,593 / 3,593 (100%)
- SHFS id=860 is `speculative_growth` — manual operator-approved correction
- Rollback: `docs/atm_lifecycle_v1_2026_05_29/shfs_860_apply/SHFS_860_ROLLBACK.sql`
- Do NOT run classifier apply — classification is done

## Proposal Lifecycle
- P0 bugs FIXED: expired case, hygiene panel status field
- ATM expiry sets primary status='EXPIRED' (commit e139030)
- Lifecycle inspector endpoint LIVE: `GET /api/v2/paper-proposals/lifecycle-inspector?proposal_id=<id>`
- UI Inspect button: NOT YET ADDED (P2)
- Hygiene panel: 141 total, 65 expired, 74 rejected, 2 linked, 0 needs_review
- 13 orphan proposal/trade links: audited, 1:N pattern, no fix needed

## Backtesting UI
- Source column added (green=replay, yellow=proposal, purple=champion)
- "Strategy Coverage" KPI: 3,593/3,593 in status API
- KPI row is now 7 cards (was 6): Datasets, Runs, Backtest Rows, Results, Strategy Coverage, Flagged, Missed
- Labels clarified: "Backtest Rows" not "Sim Trades", source-aware filter text
- "LLM Review Coverage" tab (was "LLM Reviews") with explainer banner
- Coverage cards: "Real Paper Trades With LLM Review" / "Backtest Rows With LLM Review"
- Sample-size badges: "very small" (<5), "small sample" (<20) on Strategy + Trail Analysis
- Context banner explains backtesting rows are not live broker orders
- 15/15 Playwright screenshots captured verifying new labels

## Self-Healing / Escalation
- retry_cmd direct execution hardened (commit 069fc8a)
- Tier 3a: Gemma4 31B via llama.cpp — validated, ~8min, flock guard
- Tier 3b: gemma3:12b fallback if Tier 3a times out
- Next observation: 4 AM pre-market enrichment cycle

## Model Policy
- Production: gemma3:12b (Ollama)
- Fallback: gemma3:4b (Ollama)
- Deep/offline: Gemma4 31B (llama.cpp only)
- DISABLED: qwen3:14b, gemma4 e2b/e4b, gemma3:27b GPU
- Max concurrent: 1
- Do NOT change routing without operator approval + 50 canary dry-runs

## Environment
- ALPACA_MODE=paper
- LLM_DISABLE_LIVE_EXECUTION=true
- Ollama remains production runtime

## Automated Trading Audit
- ATM is **active** and working correctly
- Most proposals are momentum_scalp (intraday skip list) — correctly rejected
- Non-intraday proposals (SNOW, ONDS) were approved and created paper trades
- New endpoint: `GET /api/v2/atm/execution-readiness` (read-only diagnostic)
- No fix needed — if more automated trades desired, generate non-intraday proposals
- R:R floating point gate bug fixed (commit 5e6b7fa) — was blocking all proposals

## What to Check First Next Session
1. `git status` and `git log --oneline -5`
2. `.venv/bin/python scripts/check_local_llm_health.py`
3. Check 4 AM enrichment logs for rejected-before-enrichment=0
4. Check escalation queue/retry_cmd logs
5. If Gemma4 31B Tier 3a ran overnight, verify output captured
6. Check `GET /api/v2/atm/execution-readiness` for pending proposals
7. Verify R:R gate is no longer blocking proposals (fixed in 5e6b7fa)
