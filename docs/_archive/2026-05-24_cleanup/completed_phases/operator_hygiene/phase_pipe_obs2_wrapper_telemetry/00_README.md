# PIPE-OBS-2 — Wrapper Telemetry Instrumentation

**Status:** COMPLETE

## What Was Patched

8 scheduled wrappers now emit pipeline_runs telemetry after every run:

| Wrapper | Pipeline Key | Category |
|---------|-------------|----------|
| run_scheduled_quote_refresh.sh | proactive_quote_refresh | Data Collection |
| run_scheduled_atp2_research_cycle.sh | atp2_research_{cycle} | Scoring |
| run_scheduled_system_facts.sh | system_facts | Governance |
| run_scheduled_a1a_check.sh | a1a_compliance | Governance |
| run_scheduled_maturity_control_board.sh | maturity_control_board | Governance |
| run_scheduled_stale_proposal_sweeper.sh | stale_proposal_sweeper | Proposal Pipeline |
| run_closed_trade_digest_cron.sh | closed_trade_digest | Intelligence |
| run_afterhours_candidate_preparation.sh | afterhours_candidate_prep | Proposal Pipeline |

## Pattern

Each wrapper:
1. Records `_TELEM_START` timestamp before command
2. Runs command with `set +e` to capture exit code
3. Sets status to `success` or `failed` based on exit code
4. Calls `record_stage_run()` from `pipeline_run_telemetry.py`

## Safety

- No fake production success rows
- Status comes from real exit code
- All safety guards (ALPACA_MODE, LLM_DISABLE, holdings) preserved
- No trades/orders/approvals

## Tests

6/6 pass.
