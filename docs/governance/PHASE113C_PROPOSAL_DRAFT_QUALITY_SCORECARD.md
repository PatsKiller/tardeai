# Phase 113C — Proposal Draft Quality Scorecard

Status:      DRAFT
as_of:       2026-06-01T15:53:13-04:00
Measured at: efcc51365 / not measured

## Scoring Dimensions (0-10 each, weighted)

| Dimension | Weight | What It Measures | Fail Threshold |
|-----------|--------|-----------------|---------------|
| **Thesis clarity** | 15% | Is the thesis specific, falsifiable, and time-bound? | < 4: vague or generic |
| **Catalyst evidence** | 15% | Is there a concrete, verifiable catalyst? Source cited? | < 4: no catalyst or unverified |
| **Risk definition** | 15% | Stop level defined? Max loss quantified? Invalidation clear? | < 5: no stop or no invalidation |
| **Position-size rationale** | 10% | Is the size justified by risk tolerance, portfolio heat, and account fit? | < 4: arbitrary size |
| **Stop/exit logic** | 10% | Exit rules beyond stop? Time stop? Target? Trail criteria? | < 4: stop-only with no plan |
| **Source traceability** | 10% | Can every claim be traced to a URL, DB view, or data source? | < 3: unsourced assertions |
| **Conflict check** | 5% | Does the draft conflict with existing positions, sector exposure, or open proposals? | < 5: unresolved conflict |
| **Portfolio fit** | 5% | Does this fit the portfolio strategy (defense, income, growth, speculative)? | < 4: misfit |
| **Tax/account fit** | 5% | Is the suggested account type appropriate (IRA/Roth/Taxable)? | < 4: wrong account for strategy |
| **Confidence calibration** | 10% | Is the stated confidence consistent with the evidence strength? | < 4: overconfident or unjustified |

## Composite Score

- **7.0+**: Draft quality matches or exceeds typical TradeAI proposal quality
- **5.0-6.9**: Acceptable but needs improvement in weak dimensions
- **3.0-4.9**: Below threshold — do not promote, needs rework
- **< 3.0**: Reject — fundamental quality failure

## Human-Review Outcome (appended after operator review)

| Outcome | Meaning |
|---------|---------|
| AGREE_ACTIONABLE | Operator agrees the thesis is worth pursuing |
| AGREE_NOT_NOW | Good thesis but timing/risk wrong |
| DISAGREE_THESIS | Thesis is wrong or unsupported |
| DISAGREE_DATA | Data/evidence is stale, wrong, or missing |
| ALREADY_COVERED | Position or proposal already exists for this symbol |
| ARCHIVE | Not worth acting on — archive |
