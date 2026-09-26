# Options Desk Architecture Map — 2026-09-25

**Authority:** `READ_ONLY_ADVISORY` · no broker execution, order, 2FA, or durable-state mutation performed
**Review basis:** source/config/test inspection of the Options Desk v3 worktree; served release pin resolved to `2cfcb2947`
**Status:** audit artifact; implementation changes are specified separately

## System topology

```text
holdings / portfolio intent / watchlist conviction / option chains / IV history
                              │
                              ▼
                    scripts/options_engine.py
             strategy generators + eligibility + economics
                              │
                              ▼
        /api/v2/options/proposals + holdings-funnel + validation
                              │
                              ▼
 apps/command-center-v3/src/pages/OptionsHub.tsx
   Proposals · Open Options · Lifecycle · Overview · Trends
                              │
              ┌───────────────┴────────────────┐
              ▼                                ▼
     paper/manual evidence              operator review surfaces
     lifecycle/outcomes                  broker path (out of scope)
```

## Surface and data inventory

| Surface | Primary implementation | Inputs | Output / boundary |
|---|---|---|---|
| Options Desk | `OptionsHub.tsx` | proposal, position, overview, validation, holdings-funnel APIs | read/review UI; actions are separately gated |
| Proposal generation | `scripts/options_engine.py` | holdings, intent, conviction, chains, IV, Aegis | proposal rows with strategy economics and blockers |
| Proposal API | `scripts/api_v2.py:_options_proposals` | generated proposals + paper queue rows | filtered, enriched, semantically classified cards |
| Holdings funnel | `scripts/api_v2.py:_options_holdings_funnel` | owned shares, IV/edge, chain resolution | explicit refusal reasons; never fabricates covered shares |
| Open options | `scripts/api_v2.py:_options_open_positions` | broker read plus monitored paper positions | unified positions and alerts |
| Lifecycle | `scripts/options_lifecycle_engine.py` | policy JSON, position state, quote age, DTE | one primary lifecycle decision plus subordinate findings |
| Re-entry | `reentryDecisionScorecard.ts`, re-entry APIs | exits, holdings, market/technical state, plan mechanics | `READY`, `NEAR`, `WATCH`, `WAIT`, stale/missing-data states |
| CIO thesis | `scripts/lib/cio_theses.py` | versioned desk thesis and learning | pinned advisory context; no execution authority |
| Memory/cognition | instrument-record and cognition stores | research questions, priority, narrative, lessons | cognition-only influence; behavior fields fail closed |

## Recommendation flow

1. Gather underlying and portfolio context.
2. Match eligible strategy families and account/sleeve constraints.
3. Resolve option contracts or mark chain data unavailable; use modeled fallback only when explicitly tagged.
4. Compute premium, POP, EV, max profit/loss, breakeven, edge, liquidity, and blocker fields.
5. Apply strategy, portfolio, conviction, and execution-readiness semantics.
6. Attach underlying company/CIO context and render the proposal card.
7. Preserve blocked and unavailable reasons for auditability; the default UI may hide blocked cards but must retain their count and access.
8. Route only to advisory, paper, manual, or separately operator-gated paths. This review does not call those routes.

## Existing strengths

- Strategy configuration is externalized in `config/options_strategy_registry.yaml` and lifecycle policy is versioned in `config/options_lifecycle_policy.json`.
- Covered-call eligibility explicitly refuses positions below 100 shares.
- Live strategy flags fail closed and do not grant live execution by configuration alone.
- Re-entry scoring is deterministic and treats missing evidence as unavailable rather than passing.
- CIO thesis records carry an exact version pin and `READ_ONLY_ADVISORY` authority.

## Architecture gaps requiring remediation

| ID | Severity | Finding | Evidence / impact |
|---|---|---|---|
| ODA-01 | High | Stock-versus-options comparison is not a single canonical contract across cards. | Existing option cards expose option economics, but the required direct-equity alternative, capital opportunity cost, and comparative preferred structure are not consistently first-class fields. |
| ODA-02 | High | Strategy validation evidence is uneven by strategy. | Registry and validation strips exist, but paper evidence, lifecycle evidence, and decision criteria are not presented as one strategy matrix. |
| ODA-03 | Medium | Runtime freshness and provenance are distributed across fields and tooltips. | Stale data is handled in several paths; a recommendation-level freshness/provenance summary is needed. |
| ODA-04 | Medium | CIO context is not a universal publication contract for all recommendation surfaces. | `docs/cio/AUTHORITY.md` explicitly notes that not every platform recommendation is CIO-gated. |
| ODA-05 | Medium | The same strategy can appear in proposal, paper, manual, and live-review semantics. | The UI has route badges and blockers, but a normalized lifecycle/authority vocabulary would reduce ambiguity. |

