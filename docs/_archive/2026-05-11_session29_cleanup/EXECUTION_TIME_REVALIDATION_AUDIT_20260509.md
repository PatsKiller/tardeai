# Execution-Time Revalidation Audit

Generated: 2026-05-09

## Problem Statement

When a paper trade recommendation is created at time T1 and admin approval/execution happens at time T2, the system must NOT assume T1 data is still valid. This applies to any delay — intraday drift, overnight, weekend, holiday, or simply slow admin review.

## Current Paper Trade Execution Paths

### Path 1: Telegram Manual (`/pt` + `/ptapprove`)
- Creates proposal → direct approval → `paper_trade_logger.approve_proposal()` → Alpaca
- **Revalidation:** NONE
- **Market session check:** NONE
- **Staleness check:** NONE

### Path 2: API `/api/v2/paper-proposals/submit-alpaca-paper`
- POST → `check_gates()` (10 gates) → `paper_execution_revalidator.revalidate()` → Alpaca bracket order
- **Revalidation:** YES (Session 27B revalidator)
- **Market session check:** NO (implicit via day TIF)
- **Staleness check:** YES (via revalidator)

### Path 3: API `/api/v2/paper-proposals/submit-alpaca-paper-bracket`
- Bracket order with dry-run validation → same revalidator path
- **Revalidation:** YES
- **Market session check:** YES (UTC 13.5-20.0 range check)
- **Staleness check:** Implicit via revalidator

### Path 4: Auto-Execution (`alpaca_paper_adapter.find_candidates`)
- Scans GO signals → direct `submit_entry()` with risk gate
- **Revalidation:** NONE
- **Market session check:** NONE
- **Staleness check:** NONE (only checks scan_date < 24h)

## Gap Analysis

| Check | Path 1 | Path 2 | Path 3 | Path 4 |
|-------|--------|--------|--------|--------|
| Risk Gate | Yes | Yes | Yes | Yes |
| Execution Revalidation | NO | Yes | Yes | NO |
| Market Session Check | NO | NO | Yes | NO |
| Recommendation Staleness | NO | Yes* | NO | NO |
| Price Drift Check | NO | Yes* | NO | NO |
| Duplicate Trade Check | Yes | Yes | Yes | Yes |
| Spread/Liquidity Check | NO | NO | NO | NO |

*Via Session 27B revalidator

## Required Changes

1. **All 4 paths** must call execution-time revalidation before any broker submission
2. Market session enforcement on all paths
3. Recommendation/approval staleness with strategy-aware thresholds
4. Price drift detection with material change thresholds
5. Spread/liquidity checks
6. Existing paper_trade_proposals columns for recheck state already exist from Session 27B

## Tables Needing New Columns

- `paper_trade_proposals` — already has execution_recheck_required, approved_pending_recheck, last_recheck_id, execution_validated_at, material_change_pending_approval
- `paper_trades` — needs entered_after_recheck, entry_recheck_id, entry_readiness_score, recommendation_to_entry_seconds, approval_to_entry_seconds

## Integration Point

The safest insertion point is immediately before `alpaca_paper_adapter.submit_entry()` — wrapping it with a mandatory revalidation gate that all 4 paths must pass through.
