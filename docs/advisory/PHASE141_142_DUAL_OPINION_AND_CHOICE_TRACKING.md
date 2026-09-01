# Phases 141-142 — Dual-Opinion Advisory + Operator Choice Tracking

Status:      HISTORICAL
as_of:       2026-06-01T20:37:17-04:00
Measured at: efcc51365 / not measured

## Phase 141 — Dual-Opinion Advisory (COMPLETE)

### Results
| Metric | Value |
|--------|-------|
| Total opinions | 10 |
| Hermes AGREES | 3 |
| Hermes AGREES_WITH_CAUTION | 0 |
| Hermes NEEDS_MORE_EVIDENCE | 2 |
| Hermes DISAGREES | 5 |

### Architecture
- TradeAI original and Hermes enhancement stored side-by-side
- No overwrite of TradeAI output
- Dashboard at `/v2/dual-opinion` under System & Pipeline
- Cards show TradeAI score vs Hermes shadow score with agreement badge
- Detail drawer: TradeAI summary, Hermes enhancement, risk flags, lesson types, operator choices (disabled)

### API
- `GET /api/v2/hermes/dual-opinion` — reads from `data/advisory/dual_opinion/`
- `scripts/generate_dual_opinion_advisory.py` — generates opinions from shadow scorer + lineage

## Phase 142 — Operator Choice Tracking (DESIGN)

### Choice Schema
| Field | Type | Description |
|-------|------|-------------|
| dual_opinion_id | string | Reference to opinion |
| operator_choice | enum | KEEP_TRADEAI / USE_HERMES / KEEP_BOTH / REJECT / ESCALATE |
| choice_reason | text | Why this choice |
| chosen_at | timestamp | When decided |
| expected_outcome | text | What we expect to happen |
| outcome_status | enum | PENDING / CORRECT / INCORRECT / UNKNOWN |
| outcome_score | float | Quality score after outcome |

### Outcome Scoring (future)
Compare TradeAI-only vs Hermes-enhanced decisions:
- Price follow-through after candidate selection
- Stop quality on trades that used learning adjustments
- Catalyst validation (was the catalyst real?)
- Journal outcome alignment
- Operator usefulness rating

### Current Status
- UI shows disabled choice buttons with explanation
- No DB writes for choices yet
- Requires separate approval to enable operator choice tracking writes

## Safety
- TradeAI originals overwritten: ZERO
- GO/WAIT mutation: ZERO
- Proposal/trade/broker/holdings: ZERO
- Journal mutation: ZERO
- Level 7: PROHIBITED
