# OpenClaw Notification Layer Plan

**Version:** 1.0  
**Date:** 2026-04-21  
**Author:** Claude Opus 4.6 (architect pass)  
**Status:** PLANNING — awaiting approval before implementation  
**Depends on:** Recommendation drafts (complete), article index (complete), watchlist system (complete)

---

## 1. Executive Summary

### What the notification layer is

A governed delivery pipeline that takes findings from the advisor memory (observations, escalations, recommendation drafts, watchlist events) and routes them to the user through the appropriate channel at the appropriate urgency — with full audit logging, dedup, and quality gates.

### Why it comes after drafts and article index

Notifications deliver content. That content must exist first:
- Drafts provide the recommendation text
- Escalations provide the urgency classification
- Article context provides the evidence richness
- Daily summaries provide the digest source

Without these, notifications would be empty shells or low-quality alerts.

### What it enables

- Daily email digest: "Here's what your advisor noticed today"
- Urgent Telegram alert: "Stop triggered on BND"
- Recommendation delivery: "V ALLOCATION_REVIEW drafted — 35 analysts, strong_buy"
- Watchlist digest: "3 new AI-generated candidates added"
- Full audit trail of what was sent, when, and why

### What it must NOT do

- Auto-execute trades or portfolio changes
- Bypass human approval for any action
- Send recommendations as if they are final decisions
- Modify escalation or draft status without explicit human action
- Overwhelm the user with low-value alerts

---

## 2. Scope Boundaries

| In Scope | Out of Scope |
|----------|-------------|
| Log every notification attempt | Auto-approve recommendations |
| Deliver via Gmail and Telegram | Execute portfolio changes |
| Dedup identical alerts within 48h | Force-route through Maria |
| Quality-gate before sending | External model calls for content |
| Daily digest batching | action_queue / approval_log |
| Urgent immediate alerts | | 

---

## 3. Candidate Notification Types

### Type 1: `daily_digest`

| Attribute | Value |
|-----------|-------|
| **Trigger:** | End of daily pipeline run |
| **Source:** | advisor_observations + escalation_queue + advisor_recommendations + daily_summary |
| **Urgency:** | Low (scheduled) |
| **Channel:** | Gmail |
| **Content:** | Ollama daily_summary + pending escalations + active drafts + watchlist changes |
| **Why:** | Single morning email gives the user a complete picture without checking dashboards |

### Type 2: `urgent_alert`

| Attribute | Value |
|-----------|-------|
| **Trigger:** | Severity 1 escalation created |
| **Source:** | escalation_queue WHERE severity = 1 |
| **Urgency:** | High (immediate) |
| **Channel:** | Telegram (primary) + Gmail (backup) |
| **Content:** | Escalation summary + key metric |
| **Why:** | Stop triggers, dividend cuts, position halts need same-day attention |

### Type 3: `recommendation_digest`

| Attribute | Value |
|-----------|-------|
| **Trigger:** | New recommendation drafts created today |
| **Source:** | advisor_recommendations WHERE status = 'draft' AND recommendation_date = today |
| **Urgency:** | Medium (include in daily digest or send separately if high-confidence) |
| **Channel:** | Gmail (part of daily digest) |
| **Content:** | Draft action, rationale, confidence, Yahoo analyst context |
| **Why:** | User should know what the advisor is proposing |

### Type 4: `stale_data_alert`

| Attribute | Value |
|-----------|-------|
| **Trigger:** | Pipeline freshness > 26h (missed scheduled run) |
| **Source:** | _freshness.json age check |
| **Urgency:** | Medium |
| **Channel:** | Telegram |
| **Content:** | "Pipeline has not run in {N}h — data may be stale" |
| **Why:** | Advisor can't function on stale data; user should know |

### Type 5: `watchlist_digest`

| Attribute | Value |
|-----------|-------|
| **Trigger:** | AI-generated watchlist items added or expired today |
| **Source:** | watchlist_items WHERE source_type='ai_generated' AND (created or expired today) |
| **Urgency:** | Low (include in daily digest) |
| **Channel:** | Gmail (part of daily digest) |
| **Content:** | New AI candidates + expired items + brief rationale |
| **Why:** | User should know what the AI watchlist is doing |

---

## 4. Proposed `notification_log` Table

```sql
CREATE TABLE IF NOT EXISTS notification_log (
    id serial PRIMARY KEY,
    created_at timestamptz DEFAULT now(),
    notification_date date NOT NULL,
    notification_type varchar(30) NOT NULL,
    channel varchar(20) NOT NULL,
    subject text,
    body_summary text,
    recommendation_ids integer[],
    escalation_ids integer[],
    observation_ids integer[],
    payload jsonb,
    status varchar(20) DEFAULT 'queued',
    dedupe_key varchar(100) NOT NULL,
    sent_at timestamptz,
    error text,
    UNIQUE(dedupe_key)
);
CREATE INDEX IF NOT EXISTS idx_notification_date ON notification_log(notification_date DESC);
CREATE INDEX IF NOT EXISTS idx_notification_status ON notification_log(status);
CREATE INDEX IF NOT EXISTS idx_notification_type ON notification_log(notification_type);
```

### Status model

```
queued → sending → sent
                 → failed (with error text)
```

Only these transitions. No auto-retry in first pass (failed stays failed, logged for review).

### Dedupe strategy

`dedupe_key` = `{notification_date}:{notification_type}:{channel}:{scope_hash}`

Where `scope_hash` is:
- For `daily_digest`: just `daily` (one per day per channel)
- For `urgent_alert`: `{escalation_id}` (one per escalation per channel)
- For `stale_data_alert`: `stale_{hour_bucket}` (one per 6h window)

This prevents:
- Duplicate daily digests on pipeline re-run
- Repeated urgent alerts for the same escalation
- Stale alerts firing every minute

### What lives in `payload` JSONB

Full notification content for audit/replay:
- HTML email body (for Gmail)
- Plain text body (for Telegram)
- All linked IDs
- Freshness metadata
- Generation timestamp

---

## 5. Delivery Channels

### Gmail (primary for digests)

| Aspect | Design |
|--------|--------|
| **Method:** | `gog gmail send -a john@jwwhiting.com` (already available via OpenClaw gog integration) |
| **Format:** | HTML email with structured sections |
| **When:** | Daily digest at pipeline completion; urgent alerts same-day |
| **Risk:** | LOW — gog is already installed and authenticated |

### Telegram (primary for urgent alerts)

| Aspect | Design |
|--------|--------|
| **Method:** | Existing `telegram_alert.send_telegram()` from `scripts/telegram_alert.py` |
| **Format:** | Plain text with emoji indicators |
| **When:** | Severity 1 escalations immediately; stale-data alerts |
| **Risk:** | LOW — already tested and working for Trade AI alerts |

### Dashboard-only (silent log)

| Aspect | Design |
|--------|--------|
| **Method:** | Write to `notification_log` with `channel='dashboard'`, `status='sent'` (no delivery needed) |
| **Format:** | Stored in DB only, queryable by Steph bridge |
| **When:** | Severity 3-4 findings that don't warrant email/telegram |
| **Risk:** | NONE — just a log entry |

### Recommended order

1. **Telegram urgent alerts** (lowest risk — already working for Trade AI)
2. **Gmail daily digest** (medium risk — needs gog shell-exec)
3. **Dashboard-only** (trivially safe — just DB write)

---

## 6. Trigger Model

### After pipeline completion (orchestrator end)

| Check | Notification |
|-------|-------------|
| Severity 1 escalation exists today | → `urgent_alert` via Telegram |
| Any recommendation drafts created today | → include in `daily_digest` |
| Pipeline completed successfully | → `daily_digest` via Gmail |
| AI watchlist items added/expired today | → include in `daily_digest` |

### After freshness check (could be in a separate timer)

| Check | Notification |
|-------|-------------|
| _freshness.json age > 26h | → `stale_data_alert` via Telegram |

### Trigger location

All triggers run at the END of the orchestrator pipeline, after all writes are complete. This ensures notifications reference committed data, not in-progress state.

---

## 7. Digest vs Alert Strategy

### Immediate alert (Telegram)

| Trigger | Why immediate |
|---------|--------------|
| Stop triggered (severity 1) | Real money at risk |
| Data stale > 26h | Advisor is blind |

### Daily digest (Gmail, next morning)

| Content | Why digest |
|---------|-----------|
| Daily summary (Ollama) | Overview, not urgent |
| Pending escalations (severity 2-3) | Important but not same-hour |
| Recommendation drafts | Review-oriented, not action-urgent |
| Watchlist changes | Informational |
| Performance snapshot | Context |

### Silent (dashboard-only)

| Content | Why silent |
|---------|-----------|
| Severity 4 observations | Background data |
| Unchanged escalations | Already notified |
| Routine pipeline success | Not worth emailing |

### Spam prevention

- **Dedupe window:** Same `dedupe_key` within 48h → skip
- **Digest batching:** Low-urgency items batch into one email, not N separate emails
- **Escalation once-per:** Same escalation only fires one urgent alert (dedupe by escalation_id)
- **Rate cap:** Max 2 Telegram messages per pipeline run; max 1 Gmail digest per day

---

## 8. Relationship to Steph and Maria

### Steph

- Steph reads notification_log via bridge skill (`notifications` query type)
- Steph can answer "what was sent today?" or "was I notified about V?"
- Steph does NOT generate or send notifications
- Steph does NOT modify notification status

### Maria

- Maria is NOT involved in first-pass notification delivery
- Future: Maria could format/personalize digest emails before sending
- Future: Maria could coordinate scheduling ("send digest at 7 AM not immediately")
- For now: notifications are generated and sent by the pipeline directly

### Role clarity

```
Pipeline GENERATES content → notification_log QUEUES → delivery script SENDS
Steph READS what was sent → User DECIDES what to do
```

No agent sends notifications conversationally. It's a background pipeline step.

---

## 9. Recommended Smallest Implementation Slice

### Choice: `notification_log` table + Telegram urgent alerts only

**Why this first:**

1. **Telegram is already working** — `telegram_alert.send_telegram()` is proven in Trade AI
2. **Only severity 1 escalations trigger** — very low volume (0-2 per day)
3. **Dedupe is simple** — one alert per escalation_id per day
4. **No Gmail integration needed** — avoids gog shell-exec complexity in first pass
5. **notification_log provides audit trail** immediately
6. **Daily digest can be added as second slice** — uses same table, adds Gmail delivery

**What to build:**
1. Create `notification_log` table
2. After escalation scoring in orchestrator, check for severity 1 escalations
3. For each, check dedupe_key in notification_log
4. If not already sent today, send via `telegram_alert.send_telegram()`
5. Log result (sent/failed) in notification_log

**Estimated effort:** 1.5-2 hours

---

## 10. Risks / Guardrails

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Spam** | HIGH | Dedupe key prevents same alert twice. Rate cap: max 2 Telegram/run, max 1 Gmail/day. |
| **Duplicate alerts** | MEDIUM | `UNIQUE(dedupe_key)` in notification_log. Same escalation → same key → skip. |
| **Stale notifications** | LOW | Notifications reference `notification_date` and linked IDs. Consumer can check freshness. |
| **Sending weak drafts** | MEDIUM | First pass: only severity 1 urgent alerts (factual, not draft-based). Digest includes drafts but framed as "pending review." |
| **Conflating draft with decision** | HIGH | Digest text always says "Draft recommendation pending review" — never "Action taken." |
| **Notification fatigue** | MEDIUM | Most findings stay silent (dashboard-only). Only severity 1 gets Telegram. Digest is one email/day. |
| **Channel failure** | LOW | notification_log records `status='failed'` + `error`. No auto-retry. Manual review. |
| **Gmail auth failure** | MEDIUM (deferred) | Gmail via gog needs re-tested. Deferred to second slice. Telegram is the safe first channel. |

---

## 11. Architect Recommendation

### Best first notification slice

**`notification_log` table + Telegram urgent alerts for severity 1 escalations.** This is the smallest useful notification step with the lowest risk (Telegram already works, severity 1 is very low volume, dedupe is simple).

### What remains deferred

| Deferred | Until |
|----------|-------|
| Gmail daily digest | After Telegram alerts proven (second slice) |
| Recommendation-draft digest | After daily digest works |
| Watchlist change digest | After daily digest works |
| Stale-data Telegram alert | After basic urgent alerts work |
| Dashboard-only notifications | After notification_log exists |
| Maria formatting integration | Much later |
| Auto-retry on failure | Much later |

### Should notifications come before action/approval work?

**Yes.** Notifications are delivery (low risk). Approval is execution authority (high risk). Build delivery first — it informs the user. Build approval second — it lets the user act.

---

## Appendix

### Sample notification_log row

```json
{
  "id": 1,
  "notification_date": "2026-04-21",
  "notification_type": "urgent_alert",
  "channel": "telegram",
  "subject": "Stop triggered",
  "body_summary": "1 stop(s) currently triggered. Pending review (severity 1).",
  "escalation_ids": [3],
  "recommendation_ids": null,
  "payload": {
    "telegram_text": "🚨 STOP TRIGGERED\n1 stop(s) currently triggered.\nSeverity: 1 (urgent)\nData freshness: 0.1h",
    "freshness_hash": "ea4ff1a05707"
  },
  "status": "sent",
  "dedupe_key": "2026-04-21:urgent_alert:telegram:esc_3",
  "sent_at": "2026-04-21T07:05:41"
}
```

### Sample Gmail digest structure

```
Subject: [OpenClaw] Daily Portfolio Digest — April 21

Body:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Daily Summary
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Ollama daily_summary text here]

⚡ Escalations (2 pending)
• [S1] 1 stop triggered
• [S2] V concentration at 15.8% above 15% threshold

📋 Recommendation Drafts (2 pending)
• STOP_REVIEW (conf 0.90) — 1 stop triggered
• ALLOCATION_REVIEW for V (conf 0.80) — Yahoo: 35 analysts, strong_buy, $393 target

👁️ Watchlist
• 5 AI-generated candidates active (ACHV, ALGS, EVTL, KURA, VANI)

📈 Portfolio: $1,209,000 | YTD +3.7% | 1W +2.1%

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Data freshness: 0.1h | Pipeline: ✅
```

### Sample urgent alert payload (Telegram)

```
🚨 STOP TRIGGERED

1 stop(s) currently triggered.

Severity: 1 (urgent)
Data freshness: 0.1h
Pipeline hash: ea4ff1a05707

View details: http://192.168.50.16:7777/reports/command_center.html
```

### Sample dedupe_key strategy

```python
# Daily digest: one per day per channel
dedupe_key = f"{date}:daily_digest:gmail:daily"

# Urgent alert: one per escalation per channel
dedupe_key = f"{date}:urgent_alert:telegram:esc_{escalation_id}"

# Stale data: one per 6-hour window
hour_bucket = datetime.now().hour // 6
dedupe_key = f"{date}:stale_data:telegram:bucket_{hour_bucket}"
```

---

*Notification layer plan created 2026-04-21. Awaiting architect approval before implementation.*
