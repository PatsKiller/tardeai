# OpenClaw Steph Bridge-Skill Plan

**Version:** 1.0  
**Date:** 2026-04-20  
**Author:** Claude Opus 4.6 (architect pass)  
**Status:** PLANNING — awaiting approval before implementation  
**Depends on:** Phase A1 (complete), Phase A2-supervisory (complete), Phase A2-enrichment (complete)

---

## 1. Executive Summary

### What the Steph bridge-skill layer is

A read-only query interface that lets Steph access the portfolio advisor's accumulated memory (observations, escalations, dividend history, daily summaries) when answering user questions — without modifying any state or generating recommendations of its own.

### Why it comes after A1/A2

The advisor memory must have data before Steph can query it. After A1+A2, the system has:
- 7+ observations per day accumulating
- 3+ escalations per day
- 11 dividend tickers with yield history
- 1 daily summary per run

After even a few days, Steph can answer "what has the advisor flagged?" with real data.

### What it enables

- Steph answers questions about portfolio advisor findings without needing them in SOUL.md
- User can ask "what's been escalated?" and get a live answer from Postgres
- Steph can cite specific observations with dates and evidence
- Reduces Steph's dependence on hardcoded SOUL.md portfolio snapshot

### What it must NOT do

- Write to any table
- Generate recommendations
- Trigger notifications
- Propose actions
- Modify escalation status (no "mark as reviewed")
- Call external models
- Route to Maria

---

## 2. Scope Boundaries

| In Scope | Out of Scope |
|----------|-------------|
| Read from `advisor_observations` | Write to any table |
| Read from `escalation_queue` | Generate recommendations |
| Read from `dividend_history` | Send notifications |
| Read from `action_signals_history` | Modify escalation status |
| Format output for Steph's use | Call external models |
| Include freshness/provenance info | Change Maria routing |
| | Approve/reject actions |

---

## 3. Candidate Bridge Skills

### A. `advisor-observations-query`

**Purpose:** Retrieve recent observations from the advisor memory.  
**Inputs:** Optional filters: date range, category, symbol.  
**Outputs:** List of observations with dates, categories, evidence snippets.  
**Why Steph needs it:** Answer "what has the advisor noticed about V this week?"  
**Separate or combined:** Could be part of a combined skill.

### B. `advisor-escalations-query`

**Purpose:** Retrieve pending/recent escalations from the queue.  
**Inputs:** Optional filters: status (pending/all), severity, symbol.  
**Outputs:** List of escalations with severity, trigger rule, summary, evidence.  
**Why Steph needs it:** Answer "what's currently escalated?" or "what's the most urgent issue?"  
**Separate or combined:** Could be part of a combined skill.

### C. `advisor-daily-summary-query`

**Purpose:** Retrieve the most recent Ollama-generated daily summary.  
**Inputs:** Optional: date (defaults to today).  
**Outputs:** The daily summary text + metadata (confidence, model).  
**Why Steph needs it:** Answer "give me today's advisor summary" or "what's the quick overview?"  
**Separate or combined:** Simplest — could be its own micro-skill.

### D. `advisor-dividend-history-query`

**Purpose:** Retrieve yield/income history for a specific ticker.  
**Inputs:** Symbol, optional date range.  
**Outputs:** Time series of yield_pct, annual_income per date.  
**Why Steph needs it:** Answer "what's the SCHD yield trend?" or "has CSWC yield changed?"  
**Separate or combined:** More specialized. Probably combined into one read skill.

### E. `advisor-signal-history-query`

**Purpose:** Retrieve signal history for a ticker from action_signals_history.  
**Inputs:** Symbol, optional date range.  
**Outputs:** Time series of signal + rule per date.  
**Why Steph needs it:** Answer "how long has V been at WATCH?" or "when did SCHD become ADD?"  
**Separate or combined:** Combined with the general query skill.

---

## 4. Recommended Smallest Skill Slice

### Recommendation: One multi-purpose read-only skill called `advisor-memory-reader`

**Why one skill, not five:**
1. OpenClaw skills are invoked by description matching in SKILL.md. One skill with a broad description is more likely to be correctly triggered than 5 narrow ones.
2. The underlying queries are simple (SELECT from 3-4 tables). The logic is "which table to query" not "complex computation."
3. Steph can use one skill entry point and the skill internally routes to the right query based on what the user asked.
4. Fewer moving parts = faster to implement and verify.

**Why not just add raw SQL access:**
A skill provides structured output with freshness metadata. Raw SQL gives Steph no guardrails on output formatting or freshness communication.

### Skill design

```yaml
name: advisor-memory-reader
description: Read-only access to the portfolio advisor memory. Use when the user asks about advisor observations, escalations, daily summaries, dividend yield history, or signal history for specific tickers. Returns structured data with freshness metadata. Does NOT generate recommendations.
```

**Capabilities within the single skill:**
1. Recent observations (last N days, by category or symbol)
2. Pending escalations (current queue)
3. Today's/latest daily summary
4. Dividend history for a symbol (last 30/90 days)
5. Signal history for a symbol (last 30 days)

---

## 5. Data Access Model

### Tables accessed (read-only)

| Table | Query Pattern |
|-------|---------------|
| `advisor_observations` | `WHERE observation_date >= now() - interval 'N days'` with optional category/symbol filter |
| `escalation_queue` | `WHERE status = 'pending'` or `WHERE created_at >= ...` |
| `dividend_history` | `WHERE symbol = $1 ORDER BY record_date DESC LIMIT N` |
| `action_signals_history` | `WHERE symbol = $1 ORDER BY signal_date DESC LIMIT N` |

### Access method

**Option A (RECOMMENDED): Shell script that queries Postgres and returns JSON**

Create a small script `scripts/advisor_memory_reader.py` that:
- Accepts a query type + optional args (symbol, days, category)
- Runs the appropriate SQL via `db_adapter._execute`
- Returns structured JSON to stdout
- Steph's skill invokes this script via shell exec

**Why script over direct DB:**
- Steph skills run via the OpenClaw gateway (Node.js process)
- The gateway can shell-exec Python scripts
- The script can load `.env` and use `db_adapter` directly
- No need for a new API endpoint on the portfolio server

**Option B: New API endpoint on port 7777**

Add `GET /api/advisor/observations?days=7&category=concentration` etc. Steph queries via HTTP.

**Why NOT Option B (for now):** More code changes to portfolio_server.py. The server is for the Command Center dashboard. Adding advisor query endpoints there mixes concerns. Better as a standalone script first, API endpoint later if needed.

### Freshness requirements

Every response from the skill MUST include:
- `queried_at`: ISO timestamp of when the query ran
- `data_freshness`: age of newest observation in result set
- `holdings_hash`: from `_freshness.json` (links to portfolio composition)
- `record_count`: how many rows returned

### Output structure

```json
{
  "query_type": "observations",
  "filters": {"days": 7, "category": "concentration"},
  "queried_at": "2026-04-20T17:00:00",
  "data_freshness": "0.5h",
  "holdings_hash": "ea4ff1a05707",
  "record_count": 5,
  "results": [
    {
      "date": "2026-04-20",
      "category": "concentration",
      "symbol": "V",
      "observation": "V is 15.7% of portfolio — signal: WATCH",
      "confidence": 1.0,
      "model": "rule"
    }
  ]
}
```

---

## 6. Steph Interaction Model

### What triggers the bridge skill

| User question | Triggers bridge skill? | Query type |
|---------------|:---:|---|
| "What has the advisor noticed?" | ✓ | observations, last 3 days |
| "What's currently escalated?" | ✓ | escalations, status=pending |
| "Give me today's advisor summary" | ✓ | daily_summary, today |
| "Show me SCHD yield history" | ✓ | dividend_history, symbol=SCHD |
| "How long has V been at WATCH?" | ��� | signal_history, symbol=V |
| "What's my portfolio value?" | ✗ | Steph reads holdings.json directly |
| "What's my YTD return?" | ✗ | Steph reads performance_history.json |
| "Should I trim V?" | ✗ | Steph answers from own judgment + context |

### What Steph still answers from existing JSON/live context

- Current portfolio value, account breakdowns, position details → `holdings.json`
- Current period returns → `performance_history.json`
- Current risk/stop status → `risk_management.json`
- Roth conversion math → `personal_situation.json` + thesis
- Technical indicators → `technical_snapshot.json`

The bridge skill adds HISTORICAL and ANALYTICAL context — not live operational data.

### How Steph combines bridge output with own reasoning

1. Steph receives user question
2. If it's about advisor memory/history → invoke bridge skill
3. Read structured output
4. Combine with Steph's own portfolio knowledge (from SOUL.md + live JSON)
5. Formulate answer citing specific dates, observations, evidence
6. Present to user in Steph's direct, numbers-first style

### Reducing SOUL.md staleness

With the bridge skill, Steph's SOUL.md no longer needs a frozen portfolio snapshot. Instead:
- SOUL.md keeps: strategy context, Roth rules, account structure, behavioral guidelines
- Bridge skill provides: current observations, escalations, yield data, signal history
- Live JSON provides: current prices, values, positions

---

## 7. Guardrails

| Guard | Enforcement |
|-------|-------------|
| **Read-only** | Script has no INSERT/UPDATE/DELETE queries. Only SELECT. |
| **No recommendation language from skill** | Skill returns raw data; Steph generates advice (not the skill). |
| **No state changes** | Script never modifies escalation status, observation records, or any table. |
| **No notification routing** | Skill has no awareness of notification_log or delivery systems. |
| **Freshness surface** | Every response includes `data_freshness` and `queried_at`. Steph always reports how fresh the data is. |
| **Evidence chain** | Results include IDs so Steph can cite specific observations. |
| **Bounded results** | Default LIMIT 20. Prevents unbounded queries from returning thousands of rows. |

---

## 8. Architecture Fit Recommendation

```
User → "What's been escalated?"
         │
         ▼
┌─────────────────────┐
│ STEPH (conversational)│
│ - Receives question    │
│ - Invokes bridge skill │
└──────────┬────────────┘
           │ shell-exec
           ▼
┌─────────────────────────┐
│ advisor-memory-reader.py │
│ (read-only script)       │
│ - Queries Postgres       │
│ - Returns JSON           │
└──────────┬──────────────┘
           │ structured JSON
           ▼
┌─────────────────────┐
│ STEPH (formats answer)│
│ - Cites observations  │
│ - Adds own judgment   │
│ - Responds to user    │
└───────────────────────┘
```

### Relationship to other components

| Component | Relationship |
|-----------|-------------|
| Portfolio agent | Writes data that bridge skill reads. No direct interaction. |
| Steph | Invokes bridge skill for historical/analytical context. |
| Maria | Unaware of bridge skill. Routes to Steph as before. |
| Notification layer (future) | Completely separate. Bridge skill doesn't touch it. |
| Recommendation layer (future) | Completely separate. Bridge skill only reads, never writes. |

---

## 9. Risks / Conflicts

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Steph reading stale advisor data** | MEDIUM | Every response includes `data_freshness`. Steph reports: "Advisor last ran 2h ago." |
| **Duplicate answer paths** | LOW | Clear rule: bridge skill for HISTORY, live JSON for CURRENT STATE. No overlap. |
| **Overloading with query types** | MEDIUM | Start with 3 query types only (observations, escalations, daily_summary). Add dividend/signal later. |
| **Confusing read with decision authority** | HIGH | Bridge skill returns DATA. Steph applies JUDGMENT. User decides. Never conflate. Steph always says "the advisor observed X" not "the advisor says do X." |
| **User thinking Steph is acting** | LOW | Steph's language: "The advisor has flagged..." not "I'm taking action on..." |
| **Script error breaks Steph** | LOW | Script returns structured error JSON on failure. Steph reports: "Advisor memory unavailable right now." |

---

## 10. Architect Recommendation

### Best first bridge skill to build

**One `advisor-memory-reader` skill with 3 initial query types:**
1. `observations` — recent observations (last 7 days default)
2. `escalations` — pending escalations
3. `daily_summary` — latest daily summary

Dividend and signal history added as a fast follow once the pattern is proven.

### What remains deferred

| Deferred | Until |
|----------|-------|
| Dividend history queries | After basic 3 types proven (1-2 weeks) |
| Signal history queries | Same |
| Write-back (mark escalation as reviewed) | Phase D/E (requires approval logic) |
| API endpoint version | After script version proven |
| Recommendation generation | Phase D (external model escalation) |

### Should this come before recommendation generation?

**Yes.** Bridge skills are read-only and low-risk. They let Steph (and the user) SEE what the advisor has accumulated before the system starts GENERATING advice. Visibility before autonomy.

---

## Appendix

### Sample user questions → bridge skill invocation

| User says | Steph invokes | Query params |
|-----------|--------------|--------------|
| "What has the advisor noticed about V?" | `advisor-memory-reader observations --symbol V --days 7` | type=observations, symbol=V, days=7 |
| "What's escalated right now?" | `advisor-memory-reader escalations --status pending` | type=escalations, status=pending |
| "Give me the advisor daily summary" | `advisor-memory-reader daily_summary` | type=daily_summary |
| "Show SCHD dividend yield over time" | `advisor-memory-reader dividends --symbol SCHD --days 30` | type=dividends, symbol=SCHD, days=30 |

### Sample bridge-skill output payload

```json
{
  "query_type": "escalations",
  "filters": {"status": "pending"},
  "queried_at": "2026-04-20T17:05:00",
  "data_freshness": "3.8h",
  "record_count": 3,
  "results": [
    {"severity": 1, "category": "risk", "symbol": null, "trigger_rule": "stop_triggered_present",
     "summary": "1 stop(s) currently triggered", "created": "2026-04-20", "status": "pending"},
    {"severity": 2, "category": "concentration", "symbol": "V", "trigger_rule": "concentration_above_15",
     "summary": "V concentration at 15.7% exceeds 15% threshold", "created": "2026-04-20", "status": "pending"},
    {"severity": 3, "category": "signal", "symbol": null, "trigger_rule": "signal_add_present",
     "summary": "4 ADD signals present in today's signal set", "created": "2026-04-20", "status": "pending"}
  ]
}
```

### Example: How Steph would use the data

User: "What's the advisor flagged today?"

Steph (after invoking bridge skill):
> Three items in the advisor escalation queue as of 3:05 PM today:
> 
> 1. **Stop triggered** (severity 1) — one position has hit its stop level. Most time-sensitive.
> 2. **V concentration** (severity 2) — V is at 15.7% of portfolio, above the 15% threshold. Currently held at WATCH due to upcoming earnings.
> 3. **Dividend gap opportunities** (severity 3) — 4 positions show ADD signals: SCHD, CSWC, PFLT, DIV.
>
> Data source: advisor memory, last pipeline run 3.8h ago (hash: ea4ff1a05707).

Note how Steph:
- Reports the findings factually
- Adds context from portfolio knowledge (earnings, position names)
- Cites freshness
- Does NOT recommend action (that's for the user or future recommendation phase)

---

*Steph bridge-skill plan created 2026-04-20. Awaiting architect approval before implementation.*
