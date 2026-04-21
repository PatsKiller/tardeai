# OpenClaw Supervisory Control-Layer Schema Plan

**Version:** 1.0  
**Date:** 2026-04-20  
**Author:** Claude Opus 4.6 (architect pass)  
**Status:** PLANNING — awaiting approval before implementation  
**Depends on:** Phase A1 (complete), Phase A1 observations accumulating

---

## 1. Executive Summary

### What this layer is

The supervisory control layer is the **decision and governance pipeline** between raw observations (Phase A1) and user-facing actions. It determines what's worth escalating, stores recommendation drafts, queues notifications, and gates all portfolio state changes behind human approval.

### Why it comes after Phase A1

Phase A1 answers "what does the system see?" This layer answers "what should we do about it?" — with guardrails to prevent autonomous action.

### What it enables

- Observations can be promoted to escalation candidates
- High-confidence findings can generate recommendation drafts
- Recommendations can be queued for notification
- All portfolio state changes require explicit approval
- Complete audit trail: observation → escalation → recommendation → approval → action

### What it still does NOT enable

- No autonomous trade execution (always human-approved)
- No Gmail send (notifications queued only — delivery is Phase E)
- No external model escalation yet (that's Phase D)
- No Steph/Maria conversational integration yet (bridge skills are Phase B+)

---

## 2. Role Boundaries

| Role | Owns | Does NOT own |
|------|------|-------------|
| **Portfolio Agent** (background) | Surveillance, observation generation, escalation scoring, recommendation drafting | User communication, final decisions, trade execution |
| **Steph** (conversational, on-demand) | Judgment, validation, answering user questions about findings, reviewing recommendations when asked | Background surveillance, automated monitoring, notification delivery |
| **Maria** (conversational, personal) | Communication delivery, scheduling, coordination | Financial judgment, portfolio decisions, observation generation |
| **Human (John)** | Final authority, approval/rejection, execution decisions | Monitoring (delegated to agent) |

### Key principle

```
Agent OBSERVES → Agent PROPOSES → Steph VALIDATES (optional) → Human DECIDES → Pipeline EXECUTES
```

No entity skips a level. The agent never acts. The agent only writes to memory and proposes.

---

## 3. Proposed Core Tables

### `escalation_queue`

**Purpose:** Tracks observations that crossed an importance threshold and need further attention.

```sql
CREATE TABLE IF NOT EXISTS escalation_queue (
    id serial PRIMARY KEY,
    created_at timestamptz DEFAULT now(),
    observation_id integer REFERENCES advisor_observations(id),
    symbol varchar(20),
    severity smallint NOT NULL,          -- 1=urgent, 2=important, 3=noteworthy, 4=informational
    category varchar(20) NOT NULL,
    trigger_rule varchar(50) NOT NULL,   -- 'concentration_above_15'|'yield_drop_15pct'|'signal_persistent_5d'|...
    summary text NOT NULL,               -- human-readable escalation reason
    evidence jsonb NOT NULL,
    status varchar(20) DEFAULT 'pending', -- 'pending'|'reviewed'|'actioned'|'dismissed'|'expired'
    reviewed_at timestamptz,
    reviewed_by varchar(20),             -- 'steph'|'human'|'auto_expire'
    expires_at date,
    UNIQUE(observation_id, trigger_rule)
);
CREATE INDEX IF NOT EXISTS idx_escalation_status ON escalation_queue(status, severity);
CREATE INDEX IF NOT EXISTS idx_escalation_created ON escalation_queue(created_at DESC);
```

**Writes:** Portfolio agent (background, after observation scoring)  
**Reads:** Steph (query skill), notification pipeline, dashboard  
**Deferred:** Auto-expiration daemon, Steph conversational review

### `advisor_recommendations`

**Purpose:** Stores actionable proposals generated from escalated findings. Always in "draft" until human approves.

```sql
CREATE TABLE IF NOT EXISTS advisor_recommendations (
    id serial PRIMARY KEY,
    created_at timestamptz DEFAULT now(),
    symbol varchar(20),
    action varchar(20) NOT NULL,         -- 'TRIM'|'ADD'|'ROTATE'|'ADJUST_STOP'|'WATCH'|'REVIEW'
    rationale text NOT NULL,
    target_allocation_pct numeric(5,2),
    dollar_impact numeric(12,2),
    confidence numeric(3,2) NOT NULL,
    model varchar(30) NOT NULL,          -- 'rule'|'ollama:qwen3:1.7b'|'claude-sonnet-4'
    escalation_ids integer[],            -- FK array to escalation_queue entries
    observation_ids integer[],           -- FK array to advisor_observations
    status varchar(20) DEFAULT 'draft',  -- 'draft'|'queued'|'notified'|'accepted'|'rejected'|'expired'
    notified_at timestamptz,
    actioned_at timestamptz,
    outcome_notes text,
    outcome_pnl numeric(12,2),
    UNIQUE(created_at, symbol, action)
);
CREATE INDEX IF NOT EXISTS idx_recommendations_status ON advisor_recommendations(status);
CREATE INDEX IF NOT EXISTS idx_recommendations_symbol ON advisor_recommendations(symbol);
```

**Writes:** Portfolio agent (after escalation + model synthesis)  
**Reads:** Notification pipeline, Steph, approval UI, outcome tracker  
**Deferred:** Outcome tracking (post-action P&L), recommendation comparison over time

### `notification_log`

**Purpose:** Audit trail of all notifications sent or queued, preventing duplicates and enabling delivery tracking.

```sql
CREATE TABLE IF NOT EXISTS notification_log (
    id serial PRIMARY KEY,
    created_at timestamptz DEFAULT now(),
    channel varchar(20) NOT NULL,        -- 'gmail'|'telegram'|'dashboard'|'queued'
    notification_type varchar(30) NOT NULL, -- 'urgent_alert'|'daily_digest'|'weekly_synthesis'|'recommendation'
    severity smallint,
    subject text,
    body_preview text,
    recommendation_ids integer[],
    escalation_ids integer[],
    delivered boolean DEFAULT false,
    delivered_at timestamptz,
    dedupe_key varchar(100),             -- prevents same notification within window
    UNIQUE(dedupe_key)
);
CREATE INDEX IF NOT EXISTS idx_notification_created ON notification_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notification_channel ON notification_log(channel);
```

**Writes:** Notification pipeline (future Phase E)  
**Reads:** Delivery daemon, dedup checker, audit queries  
**Deferred:** Gmail MCP integration, Telegram delivery, Maria coordination

### `action_queue`

**Purpose:** Proposals for portfolio state changes that require human approval before execution.

```sql
CREATE TABLE IF NOT EXISTS action_queue (
    id serial PRIMARY KEY,
    created_at timestamptz DEFAULT now(),
    action_type varchar(30) NOT NULL,    -- 'adjust_stop'|'change_allocation'|'add_position'|'trim_position'|'update_thesis'
    symbol varchar(20),
    proposed_change jsonb NOT NULL,       -- {field: "stop_price", from: 280, to: 265}
    recommendation_id integer REFERENCES advisor_recommendations(id),
    status varchar(20) DEFAULT 'proposed', -- 'proposed'|'approved'|'rejected'|'executed'|'expired'
    proposed_by varchar(30) NOT NULL,    -- 'portfolio_agent'|'steph'|'human'
    approved_by varchar(20),             -- 'human' (always, for now)
    approved_at timestamptz,
    executed_at timestamptz,
    execution_result jsonb,
    expires_at date
);
CREATE INDEX IF NOT EXISTS idx_action_queue_status ON action_queue(status);
CREATE INDEX IF NOT EXISTS idx_action_queue_symbol ON action_queue(symbol);
```

**Writes:** Portfolio agent, Steph (via recommendation acceptance)  
**Reads:** Approval UI (Command Center modal or Telegram confirm), execution pipeline  
**Deferred:** Execution integration, Command Center approval modal

### `approval_log`

**Purpose:** Immutable record of every approval/rejection decision for audit and self-assessment.

```sql
CREATE TABLE IF NOT EXISTS approval_log (
    id serial PRIMARY KEY,
    decision_at timestamptz DEFAULT now(),
    action_queue_id integer REFERENCES action_queue(id),
    recommendation_id integer REFERENCES advisor_recommendations(id),
    decision varchar(10) NOT NULL,       -- 'approved'|'rejected'|'deferred'
    decided_by varchar(20) NOT NULL,     -- 'human'|'steph'
    reason text,
    context jsonb                        -- snapshot of state at decision time
);
CREATE INDEX IF NOT EXISTS idx_approval_decision ON approval_log(decision_at DESC);
```

**Writes:** Approval handler (human action via UI or Telegram)  
**Reads:** Audit queries, agent self-assessment, recommendation accuracy tracking  
**Deferred:** Self-assessment logic (compare recommendations to outcomes)

---

## 4. Workflow Model

### End-to-end flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                       PIPELINE RUNS (daily)                          │
└─────────────────────────────────┬───────────────────────────────────┘
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 1. OBSERVE: Write to advisor_observations (Phase A1 — DONE)         │
└─────────────────────────────────┬───────────────────────────────────┘
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 2. SCORE: Evaluate observations against escalation rules            │
│    - Is this above a threshold?                                      │
│    - Is this novel (not already escalated recently)?                 │
│    - Does it cross a portfolio-impact boundary?                      │
│    → If yes: write to escalation_queue                              │
└─────────────────────────────────┬───────────────────────────────────┘
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 3. RECOMMEND (optional): Generate recommendation from escalation     │
│    - Local model (Phase C) or external model (Phase D)              │
│    - Requires confidence >= 0.7 to generate                          │
│    → Write to advisor_recommendations (status='draft')              │
└─────────────────────────────────┬───────────────────────────────────┘
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 4. NOTIFY: Queue notification if recommendation is strong enough     │
│    - Severity 1-2: queue immediately                                 │
│    - Severity 3: include in next daily digest                       │
│    - Severity 4: dashboard only                                     │
│    → Write to notification_log (delivered=false)                    │
└─────────────────────────────────┬───────────────────────────────────┘
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 5. DELIVER: Send notification via channel (Phase E)                  │
│    - Gmail / Telegram / Dashboard badge                             │
│    → Update notification_log (delivered=true)                       │
└─────────────────────────────────┬───────────────────────────────────┘
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 6. APPROVE: Human reviews and decides (always required for action)   │
│    → Write to action_queue (status='approved'|'rejected')           │
│    → Write to approval_log                                          │
└─────────────────────────────────┬───────────────────────────────────┘
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 7. EXECUTE (future): Apply approved change to portfolio state        │
│    - Update stops.json, thesis config, or flag for broker action    │
│    → Update action_queue (status='executed')                        │
│    → Track outcome in advisor_recommendations                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 5. Escalation Logic Model

### Severity levels

| Level | Name | Meaning | Response Time | Example |
|:---:|------|---------|:---:|---------|
| **1** | Urgent | Requires attention today | Same-hour | Stop triggered, dividend cut, position halted |
| **2** | Important | Should review within 24h | Same-day | Concentration crossed 15%, analyst cluster downgrade, signal persistent 5+ days |
| **3** | Noteworthy | Include in digest | Next morning | New ADD signal, yield change >5%, monthly performance milestone |
| **4** | Informational | Store only, don't notify | Archive | Background observation, baseline data point |

### Escalation trigger rules

| Trigger | Rule | Severity |
|---------|------|:---:|
| `concentration_above_15` | portfolio_pct > 15% for any ticker | 2 |
| `concentration_above_20` | portfolio_pct > 20% | 1 |
| `yield_drop_15pct` | annual_yield_pct decreased >15% from 30-day avg | 2 |
| `dividend_cut` | quarterly_amount decreased vs prior quarter | 1 |
| `signal_persistent_trim` | TRIM signal for same ticker for 5+ consecutive days | 2 |
| `signal_new_add` | New ADD signal (wasn't ADD yesterday) | 3 |
| `stop_triggered` | stop_triggered count > 0 | 1 |
| `stop_danger` | danger count > 0 and not already escalated today | 2 |
| `performance_milestone` | Total value crosses $50K boundary (e.g., $1.25M) | 3 |
| `data_stale_24h` | Pipeline hasn't run in 24+ hours | 2 |

### Confidence thresholds

| Stage | Minimum Confidence | Notes |
|-------|:---:|-------|
| Observation → Escalation | N/A (rule-based triggers) | All observations are confidence=1.0 in Phase A1 |
| Escalation → Recommendation | 0.70 | Model must express confidence in proposed action |
| Recommendation → Notification | 0.70 | Same — don't notify on low-confidence findings |
| Recommendation → Action Queue | 0.80 | Higher bar for proposing actual portfolio changes |

### Novelty / repetition logic

- **Dedup window:** Same (symbol, trigger_rule) not escalated more than once per 7 days unless severity changes
- **Escalation decay:** Unreviewed escalations expire after 14 days (status → 'expired')
- **Repeated observations:** Same observation pattern for 5+ days → promotes to escalation (persistence trigger)

---

## 6. Notification Architecture

### What belongs in `notification_log`

Every message sent or queued — regardless of channel. Enables:
- "Was John already told about this?" (dedup)
- "What was sent last week?" (audit)
- "Did delivery succeed?" (reliability)

### Channel routing

| Severity | Primary Channel | Backup | Timing |
|:---:|---|---|---|
| 1 (Urgent) | Gmail + Telegram | — | Immediate |
| 2 (Important) | Gmail | Telegram | Within 4h |
| 3 (Noteworthy) | Daily digest (Gmail) | Dashboard | Next 7 AM |
| 4 (Informational) | Dashboard badge only | — | On next visit |

### How Maria fits

Maria is the **delivery coordinator**, not the decision maker:
- Portfolio agent writes to notification_log with `delivered=false`
- Maria (or a notification daemon) reads pending notifications and delivers via `gog gmail send`
- Maria does NOT generate the content — she formats and sends
- Maria can add personal touches (greeting, context) but does not change the recommendation substance

### Duplicate prevention

`notification_log.dedupe_key` = hash of (symbol + trigger_rule + date window). If key exists within 48h window, skip.

---

## 7. Approval / Action Gate

### What must ALWAYS require approval

| Action | Why |
|--------|-----|
| Adjust stop price | Direct risk exposure change |
| Change target allocation | Modifies thesis |
| Propose buy/sell | Real money at stake |
| Modify thesis config (investment_thesis.json) | Changes system behavior |
| Send urgent external notification | User interruption |

### What can be auto-approved (eventually, after validation period)

| Action | After validation period |
|--------|----------------------|
| Daily digest email | After 30 days of manual approval |
| Dashboard badge updates | Immediately (no user impact) |
| Observation writes | Immediately (append-only memory) |
| Escalation queue writes | Immediately (internal state) |

### How approvals are stored

```
action_queue.status: proposed → approved/rejected
approval_log: immutable record of decision + reason + context snapshot
```

### Linking proposals to evidence chain

Every `action_queue` entry links to:
- `recommendation_id` → which recommendation proposed this
- Recommendation links to `escalation_ids[]` → which escalations informed it
- Escalation links to `observation_id` → which observation triggered it

**Full audit trail:** action → recommendation → escalation → observation → raw data

---

## 8. Maria / Steph / Portfolio Agent Interaction Model

### Responsibility matrix

| Function | Portfolio Agent | Steph | Maria | Human |
|----------|:-:|:-:|:-:|:-:|
| Background surveillance | ✓ | | | |
| Observation generation | ✓ | | | |
| Escalation scoring | ✓ | | | |
| Recommendation generation | ✓ | Validates | | |
| On-demand portfolio Q&A | | ✓ | Routes | |
| Notification content creation | ✓ | | | |
| Notification delivery | | | ✓ | |
| Calendar/scheduling | | | ✓ | |
| Recommendation review | | ✓ (advisory) | | ✓ (decision) |
| Approval authority | | | | ✓ |
| Stop/allocation changes | | | | ✓ (approves) |

### How Steph queries the agent

Future bridge skill: Steph can query `advisor_observations`, `escalation_queue`, `advisor_recommendations` when asked questions like:
- "What has the advisor flagged this week?"
- "Why is V still at WATCH?"
- "What's the current recommendation on SCHD?"

Steph reads from DB. Steph does NOT write to these tables (except marking escalations as 'reviewed').

### How Maria delivers

Maria receives notification_log entries with `delivered=false`:
- Formats for Gmail (subject, body, greeting)
- Sends via `gog gmail send`
- Updates `notification_log.delivered = true`
- Logs delivery timestamp

Maria never generates financial content. She only delivers.

---

## 9. Recommended Smallest Next Implementation Slice

### Recommendation: `escalation_queue` only (Phase A2-supervisory)

**Why this first:**
1. It bridges observations (have) to recommendations (future)
2. It's read-only for the user (no approval logic needed yet)
3. It can use simple rule-based triggers (no external model)
4. Steph can query it immediately ("what's been escalated?")
5. It doesn't require notification delivery

**What to build:**
- Create `escalation_queue` table
- Add escalation scoring logic after observation writes (5-10 rule-based triggers)
- No notification delivery
- No recommendation generation
- No action queue
- No approval logic

**Estimated effort:** 2-3 hours (same pattern as Phase A1)

**Why NOT `advisor_recommendations` first:**
- Requires model synthesis (local or external) — more complex
- Requires confidence scoring — needs tuning
- Risks generating low-quality recommendations too early (not enough observation history)
- Better to accumulate escalations first, then learn what patterns actually merit recommendations

---

## 10. Risks / Guardrails

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Duplicate notifications** | HIGH | `dedupe_key` in notification_log. 48h window. Same finding won't re-notify. |
| **Conflicting advice** | MEDIUM | Single source of truth: portfolio agent writes, Steph validates. No competing recommendation generators. |
| **Stale Steph context** | HIGH | Steph's SOUL.md has frozen portfolio snapshot. Bridge skill lets Steph read live DB state instead. |
| **Memory pollution** | MEDIUM | Observations are confidence=1.0 (facts only). Recommendations require 0.7+ confidence. Escalation requires rule match. |
| **Approval bypass** | LOW (by design) | `action_queue.status` starts at 'proposed'. Only human can set 'approved'. No code path skips this. |
| **Role confusion (Maria/Steph)** | MEDIUM | Clear rule: Maria delivers, never advises. Steph advises, never delivers. Agent observes, never acts. |
| **Recommendation overreach** | HIGH | Phase D (external models) is explicitly deferred. Only generate recommendations after 30+ days of escalation history inform what patterns are meaningful. |
| **Alert fatigue** | HIGH | Severity routing: only S1-S2 generate real-time notifications. S3 batches into daily digest. S4 is silent. |
| **Stale escalations** | MEDIUM | 14-day expiration. Unreviewed escalations auto-expire and stop contributing to recommendations. |
| **Cost explosion** | LOW (for now) | Phase A2 escalation is rule-based (free). External models only in Phase D with $30/month hard cap. |

---

## 11. Architect Recommendation

### Best next implementation slice

**Phase A2-supervisory: `escalation_queue` table + rule-based escalation scoring.**

- Add the table
- After observations are written (end of orchestrator), scan today's observations + recent history against 5-10 trigger rules
- Write escalations for findings that cross thresholds
- No notifications, no recommendations, no approvals
- ~2-3 hours, same proven pattern

### What should remain deferred

| Deferred | Until |
|----------|-------|
| `advisor_recommendations` | Phase C/D (need observation + escalation history first) |
| `notification_log` + Gmail | Phase E (need recommendations first) |
| `action_queue` + `approval_log` | Phase F (need notifications + approval UI first) |
| External model calls | Phase D (need local escalation patterns first) |
| Bridge skills for Steph | Phase B/C (need enough data to query meaningfully) |

### Should Phase A2 come before supervisory implementation?

**No.** The original Phase A2 (Ollama enrichment of observations) is useful but lower priority than escalation scoring. Escalation uses simple rules (concentration >15%? signal persistent 5+ days?) and doesn't need LLM enrichment. Build escalation rules first, add Ollama enrichment to observations later.

**Recommended order:**
1. Phase A2-supervisory: `escalation_queue` + rule scoring (this)
2. Phase A2-enrichment: Ollama daily summary of observations
3. Phase C: Local monitoring daemon (timer-based)
4. Phase D: External model escalation
5. Phase E: Notification delivery + Gmail

---

## Appendix

### Sample Rows

#### `escalation_queue`
```json
{
  "id": 1,
  "observation_id": 42,
  "symbol": "V",
  "severity": 2,
  "category": "concentration",
  "trigger_rule": "concentration_above_15",
  "summary": "V concentration at 15.7% — above 15% threshold for 3 consecutive days",
  "evidence": {"portfolio_pct": 15.7, "days_above": 3, "signal": "WATCH"},
  "status": "pending",
  "expires_at": "2026-05-04"
}
```

#### `advisor_recommendations`
```json
{
  "id": 1,
  "symbol": "V",
  "action": "REVIEW",
  "rationale": "V has been above 15% concentration for 5 days. Earnings report on April 27 may change thesis. Review after earnings.",
  "confidence": 0.75,
  "model": "ollama:qwen3:1.7b",
  "escalation_ids": [1, 3],
  "status": "draft"
}
```

#### `notification_log`
```json
{
  "id": 1,
  "channel": "gmail",
  "notification_type": "daily_digest",
  "severity": 3,
  "subject": "[OpenClaw] Daily Portfolio Digest — April 21",
  "body_preview": "3 observations, 1 escalation (V concentration). Portfolio +0.3% today.",
  "recommendation_ids": [],
  "delivered": true,
  "dedupe_key": "digest_2026-04-21"
}
```

#### `action_queue`
```json
{
  "id": 1,
  "action_type": "adjust_stop",
  "symbol": "LMT",
  "proposed_change": {"field": "stop_price", "from": 430.0, "to": 445.0, "reason": "trailing stop tightened after 5% gain"},
  "recommendation_id": 5,
  "status": "proposed",
  "proposed_by": "portfolio_agent"
}
```

#### `approval_log`
```json
{
  "id": 1,
  "action_queue_id": 1,
  "recommendation_id": 5,
  "decision": "approved",
  "decided_by": "human",
  "reason": "Agreed — tighten trailing stop on LMT",
  "context": {"total_value": 1210000, "lmt_value": 52000}
}
```

### Example: End-to-End Flow (Important, non-urgent)

1. **Day 1:** Pipeline runs. Observation: "V is 15.2% of portfolio — signal: TRIM"
2. **Day 3:** Observation repeats: "V is 15.7% — signal: WATCH (earnings suppressed TRIM)"
3. **Day 5:** Escalation trigger fires: `signal_persistent_trim` (5 consecutive days above 12%, even though currently WATCH). Escalation written (severity=2).
4. **Day 5:** (Phase D) External model generates recommendation: "REVIEW V position after April 27 earnings. If beats, maintain. If misses, honor original TRIM signal." (confidence=0.78)
5. **Day 5:** Notification queued: channel=gmail, type=recommendation, severity=2
6. **Day 5:** Maria delivers email: "[OpenClaw] V Concentration Review Needed"
7. **April 28:** John reviews after earnings. Decides: "Keep for now, tighten trailing stop."
8. **April 28:** Action queue: adjust_stop V. Approval: approved. Execution: stops.json updated.

### Example: Urgent Flow

1. **9:15 AM:** Pipeline detects stop triggered for BND (price dropped below stop_price)
2. **9:15 AM:** Observation written (category=risk, confidence=1.0)
3. **9:15 AM:** Escalation immediate (severity=1, trigger=stop_triggered)
4. **9:15 AM:** Notification queued: channel=telegram+gmail, type=urgent_alert
5. **9:16 AM:** Telegram sent: "🚨 BND stop triggered at $69.50 (current: $69.20)"
6. **9:16 AM:** Gmail sent: "[OpenClaw URGENT] BND Stop Triggered"
7. **John reviews:** Decides to sell or hold. Logs decision.

### Example: Routine/Non-Urgent Flow

1. **Daily pipeline:** Observation: "Portfolio YTD +3.8%, total $1,209,000"
2. **No escalation:** Performance is normal, no threshold crossed
3. **Included in daily digest:** Part of next morning's digest email
4. **No action required:** Informational only

---

*Supervisory schema plan created 2026-04-20. Awaiting architect approval before implementation.*
