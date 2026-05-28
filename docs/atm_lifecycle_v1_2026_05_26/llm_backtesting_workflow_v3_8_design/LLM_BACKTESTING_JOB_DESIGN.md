# LLM Backtesting Job Design

## Job 1: trade_close_llm_analyzer.py
- Runs after trade close (cron or event-driven)
- Local 3.14B LLM
- Writes trade_llm_reviews (stage=close_analysis)
- Modes: --dry-run, --apply
- Timeout: 120s per trade
- Cost: local only (free)

## Job 2: delayed_trade_llm_reviewer.py
- Runs daily, finds trades closed ~7 days ago without Stage 2 review
- Local LLM
- Writes trade_llm_reviews (stage=delayed_review)
- Modes: --dry-run, --apply

## Job 3: monthly_grok_trade_meta_review.py
- Runs monthly (1st of month)
- Grok API (external, cost-controlled)
- Writes monthly_llm_meta_reviews
- Modes: --dry-run, --apply
- Budget cap: configurable per month

All jobs: no trading actions, no broker writes, no stop modifications.

## System Health Agent Integration

**STATUS: IMPLEMENTED** — All 3 LLM jobs + ATM position reconciler are now in
system_health_agent.py MONITORED_COMPONENTS (added in audit fix commit).
When jobs are actually deployed, the health agent will automatically monitor them.

### Job 1: trade_close_llm_analyzer
```python
{"component": "trade_close_llm_analyzer", "display": "LLM Close-of-Trade Analysis",
 "schedule": "event-driven or */30 after market close", "log_file": "llm_backtesting/close_analyzer.log",
 "max_age_min": 1500, "max_runtime_sec": 300, "critical": False,
 "downstream": "trade_llm_reviews (close_analysis), journal learning quality"},
```

### Job 2: delayed_trade_llm_reviewer
```python
{"component": "delayed_trade_llm_reviewer", "display": "LLM Delayed Post-Close Review",
 "schedule": "0 10 * * 1-5", "log_file": "llm_backtesting/delayed_reviewer.log",
 "max_age_min": 1500, "max_runtime_sec": 600, "critical": False,
 "downstream": "trade_llm_reviews (delayed_review), weekly learning quality"},
```

### Job 3: monthly_grok_trade_meta_review
```python
{"component": "monthly_grok_meta_review", "display": "Monthly Grok Meta-Review",
 "schedule": "0 10 1 * *", "log_file": "llm_backtesting/monthly_meta.log",
 "max_age_min": 45000, "max_runtime_sec": 900, "critical": False,
 "downstream": "monthly_llm_meta_reviews, strategy learning"},
```

### Health Checks the Agent Must Perform

1. **LLM model availability** — is the local 3.14B LLM reachable? (Ollama health check)
2. **Grok API availability** — is XAI_API_KEY set? Is Grok responding? (monthly check only)
3. **Review freshness** — are closed trades getting Stage 1 analysis within expected window?
4. **Delayed review backlog** — are trades closed >7 days ago missing Stage 2 reviews?
5. **Monthly review due** — has the monthly meta-review been generated this month?
6. **Model timeout rate** — are LLM calls timing out frequently?
7. **Prompt version drift** — is the prompt version in use matching the latest configured version?
8. **Cost tracking** — for Grok: is monthly spend within budget cap?
9. **Data quality** — are LLM reviews referencing valid paper_trade_ids and lifecycle_trace_ids?
10. **Output validation** — are LLM outputs structured JSON? Any malformed responses?

### Escalation Rules

- Stage 1 missing for >24h after trade close: WARN
- Stage 2 backlog >5 trades: WARN
- Monthly review overdue by >3 days: WARN
- Local LLM unreachable: CRITICAL (blocks all LLM analysis)
- Grok API key missing: INFO (only affects monthly)
- Model timeout >3 consecutive: WARN
- Malformed LLM output: WARN (log and skip, do not block pipeline)

### API Visibility

Add to /api/v2/execution-integrity or /api/v2/system-health:

```json
"llm_backtesting_health": {
    "local_llm_available": true/false,
    "grok_available": true/false,
    "stage1_pending_count": N,
    "stage2_backlog_count": N,
    "monthly_review_due": true/false,
    "last_stage1_at": "ISO timestamp",
    "last_stage2_at": "ISO timestamp",
    "last_monthly_at": "ISO timestamp",
    "model_timeout_rate": 0.0,
    "malformed_output_count": 0,
    "grok_monthly_spend": "$X.XX",
    "grok_budget_remaining": "$X.XX"
}
```

### Dashboard Visibility

Add LLM Backtesting Health section to System Health page showing:
- Local LLM status (online/offline)
- Grok status (configured/missing key)
- Stage 1 pending count
- Stage 2 backlog count
- Monthly review status
- Last generated timestamps
- Error/timeout rate
