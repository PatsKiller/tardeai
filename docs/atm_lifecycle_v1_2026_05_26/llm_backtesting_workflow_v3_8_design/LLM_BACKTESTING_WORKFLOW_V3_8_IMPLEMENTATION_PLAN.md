# v3.8 LLM-Assisted Backtesting Workflow

## Three-Stage Workflow

### Stage 1 — Close-of-Trade Analysis
- Trigger: immediately at trade close
- Model: local 3.14B LLM
- Inputs: open/close data, fills, trade logs, proposal/thesis context, stop/trailing context, TCA
- Output: structured close-of-trade analysis JSON

### Stage 2 — Delayed Post-Close Review
- Trigger: ~1 week after close
- Model: local LLM
- Inputs: Stage 1 output + post-close price, backtest data, journal, TCA, stop audit, missed proposals
- Output: follow-up review comparing original interpretation vs actual outcome

### Stage 3 — Monthly Meta-Review
- Trigger: monthly
- Model: Grok or configured external
- Inputs: all Stage 1 + Stage 2 for the month, journal-learning summary, paper-vs-backtest, strategy rollups
- Output: monthly patterns, strengths, weaknesses, behavioral issues, strategy lessons, recommendations

## Safety
- No trading actions from LLM output
- No broker writes
- No stop modifications
- No automatic strategy changes
- LLM output is advisory only
- Operator must approve any action derived from LLM analysis

## Validation
- Dry-run mode for all jobs
- Prompt versioning
- Input snapshot hashing
- Model timeout / retry / cost control
