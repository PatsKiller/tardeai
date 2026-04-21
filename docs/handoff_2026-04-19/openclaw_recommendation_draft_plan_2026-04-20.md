# OpenClaw Recommendation-Draft Layer Plan

**Version:** 1.0  
**Date:** 2026-04-20  
**Author:** Claude Opus 4.6 (architect pass)  
**Status:** PLANNING — awaiting approval before implementation  
**Depends on:** Phase A1, A2-supervisory, A2-enrichment, Steph bridge (all complete)

---

## 1. Executive Summary

### What the recommendation-draft layer is

A controlled system that converts escalated observations into structured **recommendation drafts** — proposals that articulate what situation exists, what kind of review is warranted, and how confident the system is. Drafts exist in a `draft` status only. They do not act, notify, or execute.

### Why it comes now

The foundation is ready:
- Observations accumulate daily (7+ per run)
- Escalations identify threshold crossings (3+ per run)
- Daily summaries provide synthesis
- Steph can query all of the above via bridge skill

The missing link: the system notices things and escalates them, but never articulates "here's what this might mean and what kind of review it warrants." Recommendation drafts fill that gap.

### What it enables

- Structured articulation of "what warrants attention and why"
- Confidence-scored proposals that Steph can present to the user
- A queue of pending reviews that can later feed into notifications
- Self-assessment capability (track whether past drafts were accepted/rejected)

### What it still must NOT do

- Send notifications
- Modify portfolio state (stops, allocations, holdings)
- Execute trades
- Auto-approve anything
- Route to Maria
- Call external models (first pass is local/rule-based only)

---

## 2. Scope Boundaries

| In Scope | Out of Scope |
|----------|-------------|
| Create recommendation drafts | Send Gmail/Telegram |
| Store in Postgres with status='draft' | Write to notification_log |
| Link to escalations + observations | Write to action_queue |
| Assign confidence scores | Execute any portfolio change |
| Make drafts queryable by Steph | Auto-approve or auto-action |
| Local Ollama for rationale text | Call external models (Sonnet/GPT-4o) |
| | Change Maria routing |
| | Modify existing pipeline outputs |

---

## 3. Proposed `advisor_recommendations` Table

```sql
CREATE TABLE IF NOT EXISTS advisor_recommendations (
    id serial PRIMARY KEY,
    created_at timestamptz DEFAULT now(),
    recommendation_date date NOT NULL,
    symbol varchar(20),
    action varchar(30) NOT NULL,
    rationale text NOT NULL,
    confidence numeric(3,2) NOT NULL,
    model varchar(30) NOT NULL,
    escalation_ids integer[],
    observation_ids integer[],
    evidence_summary jsonb NOT NULL,
    status varchar(20) DEFAULT 'draft',
    notified_at timestamptz,
    reviewed_at timestamptz,
    reviewed_by varchar(20),
    outcome_notes text,
    expires_at date,
    dedupe_key varchar(100) NOT NULL,
    UNIQUE(dedupe_key)
);
CREATE INDEX IF NOT EXISTS idx_recommendations_status ON advisor_recommendations(status);
CREATE INDEX IF NOT EXISTS idx_recommendations_date ON advisor_recommendations(recommendation_date DESC);
CREATE INDEX IF NOT EXISTS idx_recommendations_symbol ON advisor_recommendations(symbol);
```

### Column rationale

| Column | Purpose |
|--------|---------|
| `recommendation_date` | Logical date (dedup + query by day) |
| `symbol` | NULL for portfolio-level, non-NULL for ticker-specific |
| `action` | Draft type: REVIEW, WATCH_CLOSELY, YIELD_REVIEW, etc. |
| `rationale` | Human-readable explanation of why this draft exists |
| `confidence` | 0.00-1.00 confidence score |
| `model` | 'rule' or 'ollama:qwen3:1.7b' — who generated |
| `escalation_ids` | FK array linking to source escalations |
| `observation_ids` | FK array linking to supporting observations |
| `evidence_summary` | Machine-readable evidence snapshot |
| `status` | 'draft' only for now. Future: 'queued'→'notified'→'accepted'/'rejected'/'expired' |
| `expires_at` | Auto-expire after 14 days if not reviewed |
| `dedupe_key` | Prevents duplicate drafts (see below) |

### Dedup strategy

`dedupe_key` = `{recommendation_date}:{symbol or 'portfolio'}:{action}:{trigger_rule}`

Examples:
- `2026-04-20:V:ALLOCATION_REVIEW:concentration_above_15`
- `2026-04-20:portfolio:STOP_REVIEW:stop_triggered_present`
- `2026-04-20:portfolio:YIELD_REVIEW:signal_add_present`

**Why this works:** One recommendation per (date, symbol, action, trigger) combination. Same escalation on the same day for the same ticker won't produce duplicate drafts. Different days or different triggers CAN produce new drafts.

### What is deferred

- `notified_at`, `reviewed_at`, `reviewed_by`, `outcome_notes` — populated by future notification + approval phases
- Status transitions beyond 'draft' — future phases
- `dollar_impact`, `target_allocation_pct` — require quantitative modeling (Phase F)

---

## 4. Draft Generation Model

### Eligible escalations

A recommendation draft is generated when:
1. An escalation exists with `status = 'pending'` AND
2. The escalation's severity is 1 or 2 (urgent or important) AND
3. No unexpired draft with the same `dedupe_key` already exists

Severity 3 (noteworthy) escalations do NOT generate drafts in this first pass — they appear in daily summaries and digests but don't warrant formal recommendation drafts yet.

### Supporting evidence requirements

A draft must cite:
- At least 1 escalation (the trigger)
- At least 1 observation (the underlying data)
- Evidence summary JSON with key metrics

### When NOT to generate a draft

| Condition | Reason |
|-----------|--------|
| Severity 3 or 4 | Not important enough for formal draft |
| Same dedupe_key exists and is unexpired | Avoid duplicates |
| Observation data is >24h stale | Don't draft on stale information |
| Holdings_hash doesn't match current freshness | Portfolio composition changed; wait for next run |

### What "enough evidence" means

Minimum: 1 escalation + 1 supporting observation from the same day. The escalation provides the "what crossed a threshold" and the observation provides the "current state."

---

## 5. Draft Types

| Action | Meaning | Trigger |
|--------|---------|---------|
| `ALLOCATION_REVIEW` | Position size warrants review | concentration_above_15 or _20 |
| `STOP_REVIEW` | Stop-related situation warrants review | stop_triggered_present |
| `YIELD_REVIEW` | Dividend/income opportunity warrants review | signal_add_present (dividend gap) |
| `WATCH_CLOSELY` | Generic important finding warrants close monitoring | Any severity 1-2 without more specific type |
| `POST_EARNINGS_REVIEW` | Post-earnings situation warrants reassessment | (future: earnings date trigger) |
| `DATA_FRESHNESS_REVIEW` | Pipeline health issue | data_stale_24h |

### Conservative framing

These are ALL framed as "review" or "watch" — never "execute" or "trade." The recommendation says "this warrants your attention" not "do this now."

---

## 6. Confidence Model

### Rule-based drafts (first pass)

| Evidence Pattern | Confidence |
|-----------------|:---:|
| Severity 1 escalation + fresh data + clear threshold crossing | 0.90 |
| Severity 2 escalation + fresh data | 0.80 |
| Severity 2 escalation + partially stale data | 0.70 |
| Below minimum evidence threshold | Do NOT generate draft |

### Future: Model-generated confidence (Phase D)

When external models are added, they provide their own confidence which may override rule-based scores. For now, all drafts are rule-based with deterministic confidence.

### Minimum confidence to create a draft

**0.70** — below this, the system has insufficient evidence or data quality to justify a formal recommendation draft. Observations and escalations still exist, but no draft is generated.

---

## 7. Guardrails

| Guard | Enforcement |
|-------|-------------|
| **No execution language** | Drafts use "warrants review" / "monitor closely" / "assess after [event]" — never "execute" / "sell now" / "trim immediately" |
| **No state mutation** | Draft writer has no access to stops.json, holdings.json, or thesis config. Read-only data access only. |
| **No auto-notification** | `status` starts at 'draft'. Nothing reads 'draft' status for notification delivery. |
| **No approval bypass** | No code path transitions status from 'draft' to 'executed' without human review. |
| **Provenance required** | Every draft records `model`, `escalation_ids`, `observation_ids`, `evidence_summary`. |
| **Expiration** | All drafts expire after 14 days. Stale drafts stop being surfaced. |
| **Dedupe** | `UNIQUE(dedupe_key)` prevents same draft from appearing multiple times. |
| **Banned language check** | Same regex validation as enrichment: reject if "you should", "I recommend buying", etc. appear in rationale. |

---

## 8. Recommended Smallest Implementation Slice

### Choice: Rule-template drafts from severity 1-2 escalations only

**What to build:**
1. Create `advisor_recommendations` table
2. After escalation scoring in orchestrator, check today's severity 1-2 escalations
3. For each qualifying escalation, generate a rule-template draft:
   - Map trigger_rule → action type
   - Generate rationale from template + evidence data
   - Compute confidence from severity + data freshness
   - Write draft with dedupe_key
4. Add `recommendations` query type to `advisor_memory_reader.py` (read-only)

**Why rule-template first (not Ollama):**
- Deterministic, testable, no model variability
- Establishes the table structure and workflow before adding model-generated text
- Ollama rationale enrichment can be added as a second step (like A2-enrichment was for observations)

**Estimated effort:** 2-3 hours

---

## 9. Interaction with Steph

### How Steph reads drafts

New query type in `advisor_memory_reader.py`:
```bash
python3 advisor_memory_reader.py recommendations [--status draft] [--symbol V]
```

Returns structured JSON with draft details.

### How Steph frames drafts to the user

**Good Steph phrasing:**
> "The advisor has drafted an ALLOCATION_REVIEW for V. It notes that V concentration has been above 15% and the current signal is WATCH pending earnings. Confidence: 0.80. This is a draft — no action has been taken."

**Bad Steph phrasing:**
> "I'm recommending you sell V."
> "The system has decided to trim your position."

### Rules for Steph

- Always state "the advisor has drafted..." not "I recommend..."
- Always include confidence level
- Always note it's a draft (no action taken)
- Always mention freshness of underlying data
- Never imply Steph has authority to act on drafts
- If user asks "should I do this?" — Steph can give opinion, but clearly distinguishes between the draft (agent's finding) and Steph's judgment

### Bridge skill integration

Add `recommendations` as a 4th query type to the existing `advisor_memory_reader.py`. Same read-only pattern. Same JSON output structure.

---

## 10. Risks / Guardrails

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Premature recommendation quality** | HIGH | Rule-template drafts only. No model-generated text yet. Templates are conservative ("warrants review"). |
| **Duplicate drafts** | LOW | `UNIQUE(dedupe_key)` prevents same (date, symbol, action, trigger) from duplicating. |
| **Over-triggering from weak escalations** | MEDIUM | Only severity 1-2 generate drafts. Severity 3 is excluded. Minimum confidence 0.70. |
| **Draft language too actionable** | MEDIUM | Templates use "review" framing. Banned-word check on any model-generated rationale. |
| **Recommendation pollution** | MEDIUM | 14-day expiration. Dedupe prevents accumulation. Only 1-3 drafts per day expected. |
| **User confusion about draft vs decision** | HIGH | Steph always frames as "advisor has drafted" + "this is a draft, no action taken." Status explicitly says 'draft'. |
| **Not enough history for meaningful drafts** | LOW | Rule-based drafts don't need history — they react to today's threshold crossings. Model-enriched drafts (later) will need history. |

---

## 11. Architect Recommendation

### Best first recommendation-draft slice

**Rule-template drafts from severity 1-2 escalations.** No Ollama. No external models. Deterministic, testable, conservative.

Maps:
- `concentration_above_15` → `ALLOCATION_REVIEW`
- `concentration_above_20` → `ALLOCATION_REVIEW` (higher confidence)
- `stop_triggered_present` → `STOP_REVIEW`
- `signal_add_present` → excluded (severity 3)
- `data_stale_24h` → `DATA_FRESHNESS_REVIEW`

Expected output: 1-3 drafts per day. All with status='draft'. All queryable by Steph.

### What remains deferred

| Deferred | Until |
|----------|-------|
| Ollama-generated rationale text | After rule-template proven (1-2 weeks) |
| External model synthesis | Phase D |
| Notification delivery of drafts | Phase E |
| Action queue from accepted drafts | Phase F |
| Outcome tracking (P&L after acceptance) | Phase F+ |
| POST_EARNINGS_REVIEW type | Requires earnings date trigger integration |

### Should recommendation drafts happen before notification planning?

**Yes.** Drafts are the content that notifications would deliver. Without drafts, there's nothing to notify about. Build the content layer (drafts) first, then the delivery layer (notifications).

---

## Appendix

### Sample recommendation draft row

```json
{
  "id": 1,
  "recommendation_date": "2026-04-20",
  "symbol": "V",
  "action": "ALLOCATION_REVIEW",
  "rationale": "V concentration at 15.7% exceeds the 15% threshold. Current signal is WATCH (earnings-suppressed from original TRIM). This position warrants allocation review after earnings report.",
  "confidence": 0.80,
  "model": "rule",
  "escalation_ids": [2],
  "observation_ids": [42],
  "evidence_summary": {
    "portfolio_pct": 15.7,
    "trigger_rule": "concentration_above_15",
    "signal": "WATCH",
    "severity": 2
  },
  "status": "draft",
  "expires_at": "2026-05-04",
  "dedupe_key": "2026-04-20:V:ALLOCATION_REVIEW:concentration_above_15"
}
```

### Sample good draft rationale

> "V concentration at 15.7% exceeds the 15% threshold. Current signal is WATCH (earnings-suppressed from original TRIM). This position warrants allocation review after earnings report."

**Why good:** Factual, cites specific numbers, explains the situation, uses "warrants review" not "you should sell."

### Sample bad draft rationale

> "You should trim V immediately to reduce concentration risk. I recommend rotating 30% into SCHD for better yield."

**Why bad:** "should trim immediately", "I recommend rotating" — action language that implies decision authority.

### Sample Steph phrasing when using a draft

User: "What's the advisor saying about V?"

Steph:
> The advisor has drafted an **ALLOCATION_REVIEW** for V (confidence 0.80).
>
> Summary: V is at 15.7% concentration — above the 15% threshold. The signal is currently WATCH due to upcoming earnings, but the underlying concentration concern remains.
>
> This is a draft review flag only — no action has been proposed or taken. After the earnings report, you may want to revisit whether the TRIM signal should be honored.
>
> Data freshness: 0.4h ago. Holdings hash: ea4ff1a05707.

---

*Recommendation-draft plan created 2026-04-20. Awaiting architect approval before implementation.*
