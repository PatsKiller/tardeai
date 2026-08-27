# Proposal Lifecycle Visibility Audit — 2026-05-29

## Source of Truth
- **Table**: `paper_trade_proposals` (141 rows, ~115 columns)
- **API**: `/api/v2/paper-proposals` (main enriched list)
- **UI**: `PaperProposals.tsx` (main page), `ATMControlRoom.tsx` (hygiene/dedup panels)

## Status Lifecycle

### Primary Status (`status` column)
| Status | Count | Set By |
|--------|-------|--------|
| REJECTED | 72 | Operator, risk gate, auto-cleanup |
| EXPIRED | 62 | Sweeper, staleness policy |
| expired | 3 | `_expire_stale_proposals()` in api_v2.py (BUG: lowercase) |
| APPROVED_FOR_PAPER_TEST | 2 | `approve_proposal()` success |
| RISK_BLOCKED | 2 | Risk gate blocks at approval |
| PENDING | 0 | Initial state (none currently active) |

Additional statuses in code but not in DB: APPROVED, MODIFIED, BROKER_SUBMITTED, CANCELLED, CONVERTED, REVIEWED.

### Overlapping Status Dimensions
1. **`status`** — primary lifecycle state
2. **`lifecycle_status`** — ACTIVE, ENTRY_ZONE_VALID, ENTRY_MISSED, EXPIRED, NEEDS_REVIEW
3. **`action_state`** — BLOCKED, MISSING_DATA, NEEDS_REVIEW, REJECTED, STALE
4. **`paper_submit_state`** — NOT_SUBMITTED, SUBMITTED, EXECUTED
5. **`enrichment_status`** — PENDING, IN_PROGRESS, COMPLETE, FAILED

### Critical Bug: Case Inconsistency
`_expire_stale_proposals()` (api_v2.py:7501) sets `status='expired'` (lowercase). All other scripts set `status='EXPIRED'` (uppercase). 3 rows have lowercase. Queries using `status = 'EXPIRED'` miss them. `TERMINAL_STATUSES` includes both but not all queries use it.

## Proposal Creation Paths (4 sources)
| Script | Source | Context |
|--------|--------|---------|
| `auto_proposal_generator.py` | strategy_signals | Main cron path, signals with score >= 40 |
| `paper_trade_logger.py` | Manual/API | `create_manual_proposal()` via dashboard |
| `incubator_proposal_promoter.py` | incubator_universe | Promotes qualifying incubator candidates |
| API `/api/v2/paper-proposals/from-signal` | strategy_signals | Manual creation from signal via API |

## Enrichment Pipeline
Two systems run in parallel:
1. **Inline async** (at creation): agent reviews → intelligence analyzer → quality reviewer
2. **Continuous cron** (`proposal_enrichment_loop.py`): 8 stages with completion weights totaling 100:
   - source (10), strategy (15), catalyst (15), technical (15), risk (10), execution (15), agents (10), llm (10)

Enrichment satellite tables: `proposal_technical_snapshots` (58), `proposal_agent_reviews` (457), `proposal_llm_review_queue`, `proposal_execution_readiness`, `proposal_research_packets` (36), `proposal_backtest_snapshots` (58), `proposal_lifecycle_events` (136).

## Duplicate/Stale Detection (3 systems)
1. **`phase6_proposal_staleness_policy.py`**: Strategy-aware thresholds (60min scalp to 14400min income)
2. **`cleanup_stale_proposals.py`**: PENDING/APPROVED >24h, BLOCKED >4h, MISSING_DATA >48h → REJECTED
3. **`_expire_stale_proposals()` in api_v2.py**: Intraday >8h, past expires_at, ENTRY_MISSED >15% drift → expired (lowercase bug)

Duplicate detection at creation: same signal_id OR same symbol+strategy+date with active status.

## Links to Other Tables
| Link | Direction | Status |
|------|-----------|--------|
| proposals.paper_trade_id → paper_trades.id | 20 linked | Bidirectional inconsistency: 33 paper_trades have proposal_id but only 20 proposals have paper_trade_id |
| proposals.outcome_trade_id → paper_trades.id | 5 linked | |
| proposals → strategy_backtest_trades | **NO DIRECT FK** | Backtest evidence stored in proposal_backtest_snapshots, not as FK |
| proposals → proposal_* satellite tables | Via proposal_id | No FK constraints |
| proposals.source_signal_id → strategy_signals.id | Logical link | |

## UI Gaps
1. **Action state divergence**: PaperProposals.tsx derives actionState client-side from execution readiness, NOT from DB `action_state` column. Can diverge.
2. **Hygiene panel checks wrong field**: Uses `signal_decision` instead of `status` for classification. Proposals with status=EXPIRED but signal_decision=GO show incorrectly.
3. **Naming collision**: `/api/v2/proposal-detail/<id>` queries `watchlist_proposals` (rebalancing), NOT `paper_trade_proposals`.
4. **ATM expiry doesn't update status**: Setting `atm_expired_at` doesn't change status from PENDING — proposal stays PENDING but invisible to ATM.

## API Gaps
1. No single "proposal full lifecycle" endpoint that aggregates status + enrichment + satellite data + linked trade outcome
2. No classification completeness metric surfaced
3. No real-time dedup (batch only via lifecycle_trace.py)
4. No FK constraints → orphan detection requires ad-hoc queries

## P0/P1/P2 Enhancement List

### P0 — Must fix before next trading day
1. Fix `expired` vs `EXPIRED` case inconsistency in `_expire_stale_proposals()`
2. Fix hygiene panel to use `status` instead of `signal_decision`

### P1 — Important next
3. Add `run_type` column to Trades table on backtesting page
4. Reconcile bidirectional paper_trade_id / proposal_id inconsistency (13 orphan links)
5. Add proposal lifecycle inspector that aggregates all satellite data
6. Surface 3,592/3,593 classification ratio in backtesting UI
7. Fix ATM expiry to also set status = EXPIRED (not just atm_expired_at)

### P2 — Polish
8. Add source_trade_id FK to strategy_backtest_trades for replay provenance
9. Add explicit is_hypothetical column to strategy_backtest_trades
10. Real-time dedup detection (not just batch via lifecycle_trace)
11. Unified proposal detail endpoint
12. Add FK constraints to proposal → paper_trades links

### P3 — Technical debt
13. Migrate trade_closed and trade_transactions schemas into tracked migrations
14. Reconcile strategy_backtest_results schema drift
15. Track broker/account columns added to strategy_backtest_trades
