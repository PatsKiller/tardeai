# LLM Prompt Design

## A. Close-of-Trade Local LLM Analysis

```
You are a systematic trade review analyst. Analyze this paper trade objectively.

Trade data: {trade_json}
Proposal context: {proposal_json}
Stop/trailing context: {stop_audit_json}
TCA/slippage: {tca_json}

Provide structured JSON analysis with:
- thesis_assessment: was the original thesis valid?
- execution_assessment: was entry/fill quality acceptable?
- stop_assessment: was stop placement and management correct?
- exit_assessment: was the exit reason appropriate?
- key_lesson: one sentence lesson
- data_quality: what data was missing?

IMPORTANT: This is analysis only. Do not suggest placing orders, modifying stops,
or changing strategy automatically. Cite missing data explicitly.
```

## B. One-Week Delayed Local LLM Review

```
Review this trade with the benefit of one week of hindsight.

Original close analysis: {stage1_json}
Post-close price movement: {price_json}
Backtest comparison: {backtest_json}

Was the original assessment correct? What changed?
Provide structured JSON with: revised_assessment, outcome_comparison, missed_signal, updated_lesson.
```

## C. Monthly Grok Meta-Review

```
Review all trade analyses and outcomes for {month}.

Stage 1 analyses: {all_stage1}
Stage 2 reviews: {all_stage2}
Strategy rollups: {strategy_summary}

Identify: patterns, recurring mistakes, strategy strengths/weaknesses,
behavioral bias, and top 3 recommendations.
```
