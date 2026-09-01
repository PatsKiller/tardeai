# Phase 115B — Proposal Draft Score Results

Status:      DRAFT
as_of:       2026-06-01T16:27:11-04:00
Measured at: efcc51365 / not measured

## Scoring Thresholds (from Phase 113C + 115A)
- **7.0+**: Strong sandbox candidate
- **6.5–6.9**: Pass with limits
- **5.5–6.4**: Needs improvement
- **Below 5.5**: Reject or research-only

## Individual Packet Scores

### APPS (Composite: 6.7) — PASS WITH LIMITS

| Dimension | Score | Notes |
|-----------|-------|-------|
| Thesis clarity | 8 | Clear: WAIT draft, not entry. RSI overbought framing is honest. |
| Catalyst evidence | 5 | Prior win only — no fresh catalyst |
| Risk definition | 7 | Explicit "do not enter while RSI > 70" invalidation |
| Position size rationale | 6 | Conservative 0.5% for high beta |
| Stop/exit logic | 7 | RSI-based entry gate, SMA20 retest target |
| Source traceability | 8 | DB view, hermes_research id=4, trade history |
| Conflict check | 9 | No conflicts |
| Portfolio fit | 5 | Micro-cap tech, not core thesis |
| Tax/account fit | 6 | Taxable acknowledged with ST gains risk |
| Confidence calibration | 8 | Correctly flags overbought as WAIT — calibrated |
| **Composite** | **6.7** | **PASS** — strongest packet due to honest WAIT framing |

### SCHD (Composite: 6.1) — NEEDS IMPROVEMENT

| Dimension | Score | Notes |
|-----------|-------|-------|
| Thesis clarity | 7 | Income/dividend ETF thesis clear |
| Catalyst evidence | 6 | 82-article news reframe + source upgrade |
| Risk definition | 4 | No stop level, vague invalidation |
| Position size rationale | 6 | 2-3% allocation reasonable for ETF |
| Stop/exit logic | 4 | "Breakdown below SMA200" is too generic |
| Source traceability | 8 | Multiple hermes_research IDs + DB view |
| Conflict check | 5 | Warns about potential dividend overlap but doesn't resolve |
| Portfolio fit | 8 | Strong income/IRA fit |
| Tax/account fit | 8 | IRA for dividend income — correct |
| Confidence calibration | 6 | Reasonable |
| **Composite** | **6.1** | **NEEDS IMPROVEMENT** — risk definition too weak for position entry |

### INFU (Composite: 5.9) — NEEDS IMPROVEMENT

| Dimension | Score | Notes |
|-----------|-------|-------|
| Thesis clarity | 7 | Oversold swing_breakout thesis clear |
| Catalyst evidence | 5 | Prior wins only — no fresh catalyst |
| Risk definition | 3 | No entry/stop/target prices |
| Position size rationale | 6 | 1% risk for moderate beta |
| Stop/exit logic | 3 | Generic "below 52-week low" |
| Source traceability | 8 | DB view, hermes id=5, trade history |
| Conflict check | 9 | Clean |
| Portfolio fit | 7 | Healthcare small-cap, swing fit |
| Tax/account fit | 7 | IRA appropriate |
| Confidence calibration | 6 | 100% win rate on 2 trades — correctly notes insufficient sample |
| **Composite** | **5.9** | **NEEDS IMPROVEMENT** — missing concrete price levels |

### ASPN (Composite: 5.3) — NEEDS IMPROVEMENT

| Dimension | Score | Notes |
|-----------|-------|-------|
| Thesis clarity | 6 | Re-entry on pullback thesis OK |
| Catalyst evidence | 5 | Prior win only |
| Risk definition | 3 | No prices, vague invalidation |
| Position size rationale | 5 | 0.5% for high beta acknowledged |
| Stop/exit logic | 3 | Generic "below swing low" |
| Source traceability | 7 | DB view, hermes id=6 |
| Conflict check | 8 | Clean |
| Portfolio fit | 6 | Industrials, moderate fit |
| Tax/account fit | 6 | Taxable acknowledged |
| Confidence calibration | 5 | RSI 73 overbought noted but still suggests entry |
| **Composite** | **5.3** | **NEEDS IMPROVEMENT** — weak on risk and entry specifics |

### TRX (Composite: 5.0) — REJECT FOR PROPOSAL SANDBOX

| Dimension | Score | Notes |
|-----------|-------|-------|
| Thesis clarity | 6 | Recovery_watch thesis OK but generic |
| Catalyst evidence | 7 | 3 promoted items, earnings + catalyst article |
| Risk definition | 3 | No prices |
| Position size rationale | 5 | 0.25% conservative |
| Stop/exit logic | 3 | Generic |
| Source traceability | 9 | Best source coverage (3 promoted IDs) |
| Conflict check | 4 | Explicitly notes poor portfolio fit |
| Portfolio fit | 3 | Gold miner doesn't fit defense/AI thesis |
| Tax/account fit | 7 | IRA appropriate |
| Confidence calibration | 5 | 2/6 win rate acknowledged but still presented |
| **Composite** | **5.0** | **REJECT** — poor portfolio fit and 33% win rate |

## Summary

| Packet | Composite | Classification |
|--------|-----------|---------------|
| APPS | 6.7 | PASS WITH LIMITS — watchlist/wait |
| SCHD | 6.1 | NEEDS IMPROVEMENT — risk definition |
| INFU | 5.9 | NEEDS IMPROVEMENT — missing prices |
| ASPN | 5.3 | NEEDS IMPROVEMENT — weak risk/entry |
| TRX | 5.0 | REJECT — poor portfolio fit |

- **Average**: 5.8
- **Pass**: 1 (APPS)
- **Needs improvement**: 3 (SCHD, INFU, ASPN)
- **Reject**: 1 (TRX)
- **Common weakness**: Missing concrete entry/stop/target prices (Hermes lacks live quote access)

## Readiness Decision

**READY_FOR_READONLY_DASHBOARD_VISIBILITY** — packets have sufficient quality for read-only sandbox visibility. One passes threshold. Three are useful as research artifacts even if not proposal-grade. One rejected. Real proposal writes remain prohibited.
