# P1 Phase A — Backtest UI and Links Report — 2026-05-29

## Changes Applied

### 1. Run Type Column — ADDED
- Backtesting Trades table now shows a "Source" column with color-coded badges
- green = replay (real trade replays), yellow = proposal (rejected/expired replays), purple = champion (hypothetical)
- No API change needed — `run_type` was already in the response
- File: `apps/command-center-v2/src/pages/Backtesting.tsx`

### 2. Classification Completeness — ADDED
- New "Classified" KPI card on Backtesting page: `3,593 / 3,593`
- Red accent if any unclassified rows exist (currently 0)
- API: `GET /api/v2/backtesting/status` now returns `classification_total`, `classification_classified`, `classification_unclassified`, `classification_pct`
- Files: `scripts/api_v2.py`, `apps/command-center-v2/src/pages/Backtesting.tsx`

### 3. Orphan Proposal/Trade Links — AUDITED, NOT RECONCILED
- 13 orphan links identified and categorized
- All 13 are "re-entry after cancel" pattern — a proposal creating multiple trades
- This is a design limitation (1:1 FK in a 1:N relationship), not a data bug
- No DB changes recommended — leave as-is, add P3 schema task for junction table
- Full audit exported to `orphan_proposal_trade_links.json`

## Files Changed
| File | Change |
|------|--------|
| `scripts/api_v2.py` | Added classification completeness to backtesting/status endpoint |
| `apps/command-center-v2/src/pages/Backtesting.tsx` | Added Source column to Trades table, Classified KPI card |

## Validation
| Check | Result |
|-------|--------|
| Python compile | PASS |
| TypeScript check | PASS |
| Vite build | PASS (309ms) |
| API classification_pct | 100.0 |
| API run_type in trades | Present |
| Orphan links audited | YES (13 identified) |

## Rows Mutated
**NONE** — UI/API changes only. No DB writes.

## Remaining P1 Gaps
1. ~~run_type column~~ — DONE
2. ~~classification completeness~~ — DONE
3. ~~orphan proposal/trade links~~ — AUDITED (no fix needed)
4. ATM expiry primary status — NOT in this session
5. Proposal lifecycle inspector — NOT in this session

## Safety
| Check | Result |
|-------|--------|
| Orders placed | NO |
| Broker writes | NO |
| paper_trades trade-state changes | NO |
| Proposal status mutations | NO |
| Journal mutations | NO |
| Classifier apply | NO |
| LLM calls | NO |
| Qwen/Gemma4/Grok used | NO |
| Cron changes | NO |
| Health-agent files changed | NO |
