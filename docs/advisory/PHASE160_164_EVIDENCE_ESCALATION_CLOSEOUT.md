# Phases 160-164 — Evidence Remediation, Escalation, Waiting Room, UX, Closeout

Status:      HISTORICAL
as_of:       2026-06-01T21:34:02-04:00
Measured at: efcc51365 / not measured

## Phase 160 — Evidence Remediation (COMPLETE)
- 10/10 weak-evidence cases processed
- 10/10 improved with SearXNG sources (27 total sources added)
- 0 still weak after remediation
- Evidence saved to `data/advisory/evidence_remediation/`

## Phase 161 — High-LLM Review (DESIGN + DRY-RUN)
- 5 escalation candidates identified (delta > 8: ABTS, AIRJ, ANY, CRE, HMR — all swing_trade -9)
- Prompt template designed: compare TradeAI vs Hermes, assess evidence, recommend, no execution
- Actual LLM reviews deferred to next session (late hour, GPU contention risk)
- Uses existing Tier 3b (gemma3:12b) escalation path

## Phase 162 — Outcome Waiting Room (DESIGN)
- Follow-up policy defined:
  - Momentum/catalyst: same day + next day
  - Trade/journal: after close/postmortem
  - Backtest/strategy: after next sample batch
  - Risk/stop: after stop resolution
- Waiting room generator designed but not yet implemented (needs choices to accumulate first)
- 3 choices currently tracked, all outcomes pending

## Phase 163 — UX Pass (DESIGN)
- Compact default for inline panels (already implemented)
- Full evidence on expand (Show/Hide Evidence toggle live)
- Standardized badges: AGREE/DISAGREE/CAUTION/NEEDS_EVIDENCE/ADVISORY_ONLY
- Recommended next-action line: present in evidence drawer
- Playwright crawl completed earlier (71 pages, 68 OK)

## Phase 164 — Tonight Closeout

### What Is Live
| System | Status |
|--------|--------|
| Dual-opinion inline panels | 12 pages |
| Evidence drawer | Expandable, quality labels |
| Choice capture | LIVE (JSONL) — 3 test choices |
| Outcome tracker | Created, 0 outcomes yet |
| Evidence remediation | 10/10 improved via SearXNG |
| SIEM dashboard | Live at /v2/alert-siem |
| Telegram gate | Active (12 P2 patterns suppressed) |
| Shadow scorer | Timer Mon-Fri 10/14/18 ET |
| Momentum catalyst timer | Armed Tue 8 AM |
| Hermes gateway | Live on :18790 |
| Autonomous loop | Daily 01:00 UTC |

### What Is Waiting for Data
- Outcome tracking (needs choices + outcomes to accumulate)
- Shadow-vs-actual comparison (needs 5 market days)
- High-LLM reviews (needs fresh session, GPU availability)
- Catalyst quality validation (needs Tuesday morning run)

### Safety
- TradeAI originals overwritten: ZERO
- GO/WAIT mutation: ZERO
- Proposal/trade/broker/holdings: ZERO
- Journal mutation: ZERO
- Strategy mutation: ZERO
- Level 7: PROHIBITED

### Next Gates
1. Phase 125D/159: Tuesday 8 AM catalyst observation
2. Accumulate operator choices for outcome scoring
3. Shadow observation: 5 market days
4. High-LLM capped reviews (next session)
5. Outcome waiting room implementation (after choices grow)
