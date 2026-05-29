# System Health Agent Architecture

**Updated:** 2026-05-29
**Files:** `scripts/system_health_agent.py` (1,124 lines), `scripts/claude_escalation_handler.py` (271 lines), `scripts/pipeline_health_monitor.py` (171 lines)

---

## Overview

The system health agent is a self-healing pipeline monitor that runs every 5 minutes during market hours. It detects broken components, attempts automatic fixes, and escalates unresolvable problems to Claude Code CLI for investigation.

```
Cron (*/5 min)
  → system_health_agent.py --apply
    → Check 30+ components (log freshness, lock contention, output validity)
    → Auto-retry failed components (retry_cmd)
    → Auto-remediate stale agents (queue refresh jobs)
    → Enrich-before-reject stuck proposals
    → Escalate unresolved → claude_escalation_queue.json
      → claude_escalation_handler.py (*/15 min)
        → Local LLM diagnosis (gemma3:4b)
        → Claude Code CLI invocation (claude -p)
        → Log intervention + notify operator
```

## Cron Schedule

| Script | Schedule | Purpose |
|--------|----------|---------|
| `system_health_agent.py --apply` | `*/5 9-20 * * 1-5` | Market hours check |
| `system_health_agent.py --apply` | `*/15 * * * 0,6` | Weekend check |
| `system_health_agent.py --apply` | `0 7 * * 1-5` | Pre-market full check |
| `claude_escalation_handler.py` | `*/15 7-20 * * 1-5` | Process escalation queue |

## Components Monitored (30+)

### Pipeline Core
- orchestrator, screener, promoter, news_ingestion, stop_manager, reconciler

### Trade Monitoring
- fill_verification, tca_analyzer, journal_writer

### Data Pipeline
- price_cache, portfolio_sync, holdings_refresh, finviz_enrichment, dividend_tracker, rag_indexer

### Agents
- maria_research, steph_income, aegis_overnight, social_scalp, risk_agent, iris_taxonomy

### Proposals & ATM
- proposal_enrichment (`*/10 4-19`), auto_enrichment (`*/10 4-19`), atm_evaluator, atm_reconciler

### LLM & Intelligence
- llm_backtesting, topic_curator, incubator_screener, content_entity_links

### Governance
- maturity_board, governance_check, cio_decisions

## Health Check Logic

For each component, the agent checks:

1. **Log freshness**: Is the log file recent? (configurable max_age per component)
2. **Lock contention**: Is a flock lock stuck? (older than expected runtime)
3. **Output validity**: Does the log contain errors, tracebacks, or anomalies?

Results: `OK`, `STALE`, `FAILED`, `LOCKED`

## Auto-Remediation (Self-Healing)

### Level 1: Retry Command
Each component has a `retry_cmd`. If a check fails, the agent runs it:
```python
subprocess.run(retry_cmd, shell=True, timeout=120)
```
If retry succeeds → component recovered. If retry fails → escalate.

### Level 2: Agent Staleness Auto-Queue
For stale agents (`tax_agent`, `iris`, `maria_research`), the agent queues refresh jobs:
```sql
INSERT INTO watchlist_agent_jobs (symbol, requested_agent, request_type, status, priority, submitted_from)
VALUES (%s, %s, 'full_analysis', 'queued', 1, 'health_agent_remediation')
```

### Level 3: Proposal Enrich-Before-Reject (NEW — 2026-05-29)

**Before:** Proposals stuck >2h with no enrichment were immediately rejected.
**After:** 
1. Detect PENDING proposals with `packet_state IN ('NEW', 'MISSING_DATA', 'ENRICHING')` older than 30 min
2. Trigger `auto_enrichment_runner.py --force-all` (up to 3 attempts)
3. Increment `enrichment_attempt_count` per proposal
4. Only reject after **3 failed enrichment attempts** OR **6 hour hard timeout**
5. Proposals with 2+ failed attempts are escalated to Claude Code queue

### Level 4: Claude Code Escalation
Unresolved problems are written to `logs/claude_escalation_queue.json`:
```json
{
  "component": "proposal_enrichment_stuck",
  "detail": "Proposal #147 REPL stuck after 3 enrichment attempts",
  "fixable": true,
  "retry_cmd": ".venv/bin/python scripts/auto_enrichment_runner.py --force-all --limit 5",
  "escalated_at": "2026-05-29T14:00:01Z",
  "source": "system_health_agent"
}
```

## Claude Code Escalation Handler

`scripts/claude_escalation_handler.py` runs every 15 minutes and processes the queue:

### Step 1: Local LLM Diagnosis
For `fixable` items, calls the local LLM (gemma3 via Ollama) with the alert detail + recent log tail:
```
Diagnose this Trade AI error and suggest a fix:
Alert: {detail}
Recent log: {tail of relevant log}
```

### Step 2: Claude Code CLI Invocation
Invokes `claude -p` with a structured prompt describing all unresolved problems:
```bash
claude -p "The Trade AI health agent has escalated N problem(s)..." --output-format text
```
- Timeout: 5 minutes
- Working directory: project root
- Non-interactive mode (`CLAUDE_NO_INTERACTIVE=1`)

### Step 3: Logging & Notification
- Logs intervention to `claude_interventions` table (component, problem, diagnosis, solution, status)
- Sends Telegram notification with result (✅ resolved / ❌ failed)
- Clears the queue after processing

## Escalation Queue Items

| Source | Component | Fixable | When |
|--------|-----------|---------|------|
| Failed retry | Any component | Yes (has retry_cmd) | After retry_cmd fails |
| Stale agents | agent_staleness | No | After auto-queue fails |
| Portfolio risk | portfolio_risk | No (informational) | Always |
| Pipeline output gap | pipeline_output | Yes | When 0 proposals/trades in window |
| Enrichment stuck | proposal_enrichment_stuck | Yes | After 2+ enrichment attempts fail |

## Known Gaps (Addressed 2026-05-29)

### 1. Enrichment Timing Gap — FIXED
**Problem:** Enrichment crons only ran 9-15. Proposals created 4-9 AM sat unenriched.
**Fix:** Crons extended to `*/10 4-19 * * 1-5`.

### 2. Reject-Without-Fixing — FIXED  
**Problem:** Health agent rejected unenriched proposals after 2h without attempting enrichment.
**Fix:** Enrich-before-reject logic. Trigger enrichment up to 3 times, only reject after 3 failures or 6h.

### 3. Escalation Only Diagnoses — KNOWN LIMITATION
**Problem:** Claude Code escalation handler calls `claude -p` which investigates but may not apply fixes autonomously.
**Mitigation:** Fixable items include `retry_cmd` so Claude Code can run the fix. Operator is notified via Telegram.

## Pipeline Health Monitor

`scripts/pipeline_health_monitor.py` (171 lines) is a lighter check that detects GO tickers with missing analysis and auto-re-queues enrichment/agents. It runs as part of the broader health pipeline but is not the primary self-healing agent.

## Monitoring the Health Agent

```bash
# Check latest health agent run
tail -30 logs/system_health_agent.log

# Check escalation queue
cat logs/claude_escalation_queue.json | python3 -m json.tool

# Check Claude Code interventions
.venv/bin/python3 -c "
import sys; sys.path.insert(0, 'scripts')
from db_adapter import _get_conn
conn = _get_conn(); cur = conn.cursor()
cur.execute('SELECT id, component, problem, status, created_at FROM claude_interventions ORDER BY created_at DESC LIMIT 5')
for r in cur.fetchall(): print(r)
"

# Check enrichment status
tail -10 logs/auto_enrichment.log
tail -10 logs/proposal_enrichment.log

# Manual health check (dry-run)
.venv/bin/python scripts/system_health_agent.py --verbose

# Manual escalation processing (dry-run)
.venv/bin/python scripts/claude_escalation_handler.py --dry-run
```
