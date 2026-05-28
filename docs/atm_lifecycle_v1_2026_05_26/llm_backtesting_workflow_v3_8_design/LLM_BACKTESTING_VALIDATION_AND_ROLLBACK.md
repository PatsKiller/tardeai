# LLM Backtesting Validation and Rollback

## Validation
- Dry-run each job
- Verify structured JSON output
- BLMN repaired row produces clean analysis
- APPS repair row produces clean analysis
- No orders placed
- No broker writes
- Model call logging verified

## System Health Agent Validation
- All 3 LLM jobs appear in system_health_agent MONITORED_COMPONENTS
- Health agent detects local LLM availability (Ollama)
- Health agent detects Grok API availability
- Health agent flags overdue Stage 1 / Stage 2 / monthly reviews
- Health agent reports LLM timeout rate and malformed output count
- /api/v2/execution-integrity or /api/v2/system-health includes llm_backtesting_health block
- System Health dashboard shows LLM Backtesting Health section
- Escalation rules: WARN for backlogs, CRITICAL for local LLM down

## Rollback
- Delete trade_llm_reviews rows
- Delete monthly_llm_meta_reviews rows
- Remove LLM jobs from system_health_agent MONITORED_COMPONENTS
- Drop tables if needed
- git revert
