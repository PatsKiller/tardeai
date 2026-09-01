# Phase 180D: ATM Paper-Only Guardrails Report

Status:      HISTORICAL
as_of:       2026-06-01T23:26:38-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-01
**Mode**: PAPER ONLY — Level 7 PROHIBITED

## Guardrail Verification

### Environment Variables

| Variable | Expected | Actual | Status |
|----------|----------|--------|--------|
| ALPACA_MODE | paper | `paper` | PASS |
| LIVE_TRADING_ENABLED | false/unset | NOT SET | PASS |
| LLM_DISABLE_LIVE_EXECUTION | true | `true` | PASS |
| ENABLE_ALPACA_PAPER | true | `true` | PASS |

### Code-Level Safety

| Check | File | Status |
|-------|------|--------|
| Live endpoint rejection | alpaca_paper_adapter.py:48-49 | PASS — raises RuntimeError if non-paper URL |
| Paper-only submission | proposal_paper_submitter.py:2-5 | PASS — docstring + code enforce paper |
| ALPACA_MODE check | proposal_paper_submitter.py:32 | PASS — reads and validates |
| LIVE_TRADING_ENABLED check | proposal_paper_submitter.py:31 | PASS — defaults false |
| Live trading gate | live_trading_gate.py | PASS — `allowed=False, mode=PAPER` |

### Database Safety

| Check | Status |
|-------|--------|
| ATM mode | `active` (paper only) |
| Enabled accounts | `alpaca_paper` only |
| Live account configured | NO |
| paper_trades.broker | `alpaca_paper` default |
| Live order endpoints | NONE configured |

### Kill Switch Availability

| Mechanism | Available | Tested |
|-----------|-----------|--------|
| ATM mode=paused | YES | YES (2026-05-22) |
| Per-account daily loss | 0.25% threshold set | NOT AUTO (manual_kill_switch_only=true) |
| Aggregate daily loss | 10% threshold set | NOT AUTO |
| HIGH_LLM_SCHEDULER_DISABLED | File-based kill switch | Available |
| Manual CLI halt | `--set-mode paused` | Available |

### Audit Trail

| Mechanism | Status |
|-----------|--------|
| ATM decision log | 168 entries — ACTIVE |
| Config change history | atm_config_history table |
| State change events | atm_state_events table — 6 entries |
| Paper trade audit | paper_trades table with broker/source fields |
| Proposal evidence snapshots | proposal_evidence_snapshots table |

## Summary

All paper-only guardrails are VERIFIED and OPERATIONAL:

- **ALPACA_MODE=paper**: Confirmed
- **No live endpoint**: Code blocks non-paper URLs with RuntimeError
- **No live trading gate passage**: `allowed=False, mode=PAPER`
- **All trades marked paper**: `broker='alpaca_paper'` default
- **Kill switch available**: Multiple mechanisms (manual preferred)
- **Audit trail complete**: Every decision, config change, and trade logged

No guardrail patches needed. The system is correctly locked to paper mode.
