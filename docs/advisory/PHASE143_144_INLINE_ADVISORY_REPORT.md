# Phases 143-144 — Inline Dual-Opinion Advisory + Journal/Backtest Intelligence

Status:      HISTORICAL
as_of:       2026-06-01T20:50:24-04:00
Measured at: efcc51365 / not measured

## Phase 143 — Inline Panels (COMPLETE)

### Reusable Component
`InlineDualOpinionPanel.tsx` — accepts `symbol`, `strategy`, `compact` props.

Two modes:
- **Compact**: Single-line badge showing agreement, scores, delta, risk flags
- **Full**: Two-column TradeAI vs Hermes with evidence, risk flags, lesson types, confidence

### API
`GET /api/v2/hermes/dual-opinion/inline?symbol=X&strategy=Y` — filters from full opinion set

### Pages Updated
| Page | Component | Mode | Where |
|------|-----------|------|-------|
| Proposal Sandbox | ProposalSandbox.tsx | Full | Detail drawer, before metadata |
| Self-Learning Overview | SelfLearningOverview.tsx | Compact | Detail drawer, before metadata |

### Target Pages (future)
| Page | Status |
|------|--------|
| AI Advisory | Not yet — needs opinion data for advisory items |
| Backtesting | Not yet — needs backtest-specific dual opinions |
| Trade Journal | Not yet — needs journal-specific dual opinions |
| Strategy Analytics | Not yet — needs strategy-level dual opinions |
| Risk Dashboard | Not yet — needs risk-specific opinions |

## Phase 144 — Journal/Backtest Dual-Opinion (DESIGN)

### Journal Dual-Opinion Logic
For each closed trade, Hermes should evaluate:

| Question | Source |
|----------|--------|
| Was entry thesis valid? | proposal context + catalyst |
| Was exit reason valid? | exit_reason field + Phase 131 forensics |
| Was stop planned/trailing/manual? | stop_type (captured in Phase 136) |
| Did price recover after exit? | MFE/MAE after exit |
| Should we have held longer? | Post-exit price action analysis |
| Is journal data complete? | Phase 133 completeness audit |
| What lesson should be queued? | Learning candidate extraction |
| Does Hermes agree with postmortem? | Compare Hermes audit vs postmortem text |

### Backtest Dual-Opinion Logic
For each strategy result, Hermes should evaluate:

| Question | Source |
|----------|--------|
| Is sample size sufficient? | Minimum 20 trades per strategy |
| Is overfitting likely? | Train/test split, parameter sensitivity |
| Does live match backtest? | strategy_backtest_results vs paper_trades |
| Are stops/targets consistent? | Phase 131 stop quality |
| Promote, pause, adjust, or observe? | Learning effectiveness metrics |

### Implementation Status
- Component built: YES
- API built: YES
- Core pages wired: Proposal Sandbox + Self-Learning
- Journal/backtest wiring: DEFERRED (needs journal-specific opinion generator)
- The dual opinion data currently comes from momentum candidate analysis only
- Journal/backtest opinions need a separate `generate_journal_dual_opinions.py` script

## Safety
- TradeAI originals overwritten: ZERO
- GO/WAIT mutation: ZERO
- Proposal/trade/broker/holdings: ZERO
- Journal mutation: ZERO
- Strategy mutation: ZERO
- Level 7: PROHIBITED
