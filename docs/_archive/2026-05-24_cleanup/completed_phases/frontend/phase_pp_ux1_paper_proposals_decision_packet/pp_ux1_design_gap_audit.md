# PP-UX-1 Design Gap Audit

## 1. Screenshot-Observed Gaps

The ATLN recovery_watch card shows entry/stop/target/R:R and basic metrics but does not show:
- Sector or industry
- Why recovery_watch strategy applies
- Why entry is $1.50, stop $1.43, target $1.65
- Catalyst/news summary
- Evidence completeness detail
- What exact action to take next
- Why approval is or is not blocked

## 2. Documented Expected Decision Packet Fields

Per project docs, each proposal card should show:
- Narrative with catalyst/critic
- Signal quality and conviction label
- Technical context
- Sector/industry/regime
- Risk/reward with rationale
- Approve/reject case
- News summary
- Missing data warnings
- Agent/LLM review results
- Intelligence readiness
- actionState, topBlocker, nextActions, dataCompleteness
- 8 metric tiles (Strategy Fit, Execution, Technical, Catalyst, R:R, Agents, Backtest, Data)

## 3. Current API Fields Available

The API already returns 80+ fields per proposal including sector, industry, catalyst,
technical_snapshot, agent_reviews, llm_analysis, quality_review, approve_case,
reject_case, decision_state, missing_data, operator_verdict, pipeline_stages.

## 4. Missing API Fields

| Field | Source | Status |
|-------|--------|--------|
| strategy_description | YAML purpose | Not sent |
| strategy_entry_criteria | YAML entry_criteria | Not sent |
| strategy_risk_rules | YAML risk | Not sent |
| strategy_timeframe_display | YAML timeframe | Not sent |
| entry_rationale | Computed from strategy+scan | Not sent |
| stop_rationale | Computed from strategy config | Not sent |
| target_rationale | Computed from strategy config | Not sent |
| approval_blockers | Structured list | Partial (approval_blocked_reason is string) |
| staleness_policy | Per-strategy from YAML | Not sent |

## 5. Current Frontend Fields Displayed

- Symbol, strategy_id, signal_grade, score
- Entry/Current/Stop/Target prices
- R:R, Risk $, Shares, RVOL, RSI
- Age, Price check, AI review, Risk gate timestamps
- One-line thesis
- 8 metric tiles (Strategy Fit, Execution, Technical, Catalyst, R:R, Agents, Backtest, Data)
- Action buttons: Refresh Price, Check Execution, AI Review, Approve, Reject, Details
- Details drawer: Pipeline chevron, Support/Reject case, Technical metrics, Agent reviews, Missing data

## 6. Missing Frontend Display Fields

| Field | Available in API? | Shown? |
|-------|------------------|--------|
| Sector/industry | Yes | No — only in thesis if present |
| Strategy description | No | No |
| Entry rationale | No | No |
| Stop rationale | No | No |
| Target rationale | No | No |
| Entry criteria | No | No |
| Evidence completeness detail | Yes (missing_data) | Only as % tile |
| Approval blockers list | Partial | Not structured |
| Guided next-step workflow | Yes (next_actions) | Only in banner as text |
| Incubator lock reason | Partial | Vague message |
| Run underfilled explanation | Yes (pipeline-run-health) | One-line banner |

## 7. Workflow Blockers

- Approve button enabled even when risk gate not checked (uses confirm modal bypass)
- No clear "step 1, 2, 3" workflow for operator
- Proposal age warning not actionable (no Expire/Rebuild button)
- Missing data shown in details drawer only, not in main card

## 8. Safety Concerns

- Approve button CAN be clicked with confirm modal even when gates incomplete
- This is by design (cautious paper test) but UI should make the risk clearer
- No execution logic changes needed — only display/workflow clarity

## 9. Proposed Redesign

### Card Header
Add: sector/industry, strategy timeframe, company name if available

### Decision Banner (already exists, enhance)
Add: structured blocker list, explicit "approval blocked because..." text

### New Section: "Why This Setup?"
Show: strategy description, entry criteria match, catalyst summary, sector context

### New Section: "Trade Plan Rationale"
Show: entry/stop/target with source and reasoning

### Enhanced Missing Data
Move from details drawer to visible section when blockers exist

### Guided Workflow
Number the action buttons: Step 1 Refresh, Step 2 Check Execution, Step 3 AI Review
Disable Approve until prerequisite steps complete

### Run Health Panel
Show underfilled explanation, incubator lock reason, promotion caps
