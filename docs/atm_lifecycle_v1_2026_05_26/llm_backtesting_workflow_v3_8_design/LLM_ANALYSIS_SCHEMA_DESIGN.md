# LLM Analysis Schema Design (NOT YET APPLIED)

## trade_llm_reviews
- id bigserial PK
- paper_trade_id bigint
- trace_id text
- proposal_id text
- symbol text
- strategy_id text
- review_stage text (close_analysis | delayed_review | monthly_meta)
- model_provider text (local | grok | other)
- model_name text
- prompt_version text
- input_snapshot_hash text
- generated_at timestamptz
- trade_close_date date
- review_due_date date
- status text
- summary text
- strengths text
- weaknesses text
- thesis_assessment text
- execution_assessment text
- stop_assessment text
- tca_assessment text
- post_close_assessment text
- backtest_comparison text
- lessons text
- confidence numeric
- data_quality_gaps jsonb
- payload jsonb

## monthly_llm_meta_reviews
- id bigserial PK
- month text (YYYY-MM)
- model_provider text
- model_name text
- generated_at timestamptz
- trade_count int
- reviewed_trade_count int
- patterns text
- strengths text
- weaknesses text
- strategy_lessons text
- behavioral_notes text
- recommendations text
- payload jsonb
