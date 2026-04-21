# OpenClaw Phase A2-Enrichment — Local Ollama Enrichment Plan

**Version:** 1.0  
**Date:** 2026-04-20  
**Author:** Claude Opus 4.6 (architect pass)  
**Status:** PLANNING — awaiting approval before implementation  
**Depends on:** Phase A1 (complete), Phase A2-supervisory (complete)

---

## 1. Executive Summary

### What Phase A2-enrichment is

A lightweight local-only Ollama pass that reads today's observations and escalations, then generates a single structured **daily summary observation** — a concise machine-readable digest of what the system noticed today, with priority ordering and thematic grouping.

### Why it comes after observations + escalation queue

Raw observations are factual data points ("V is 15.7%"). Escalations flag threshold crossings ("V exceeds 15%"). But neither produces a coherent picture of "what matters today across all signals." The enrichment layer synthesizes across observations without crossing into recommendation territory.

### What it enables

- A single "here's what matters today" observation that a future notification pipeline can use as digest source
- Priority ordering that goes beyond mechanical severity levels
- Thematic grouping (multiple observations may relate to the same underlying situation)
- A precedent for Ollama-as-analysis (establishes prompting patterns, performance baseline)

### What it must NOT do

- Generate recommendations ("you should...")
- Trigger notifications
- Write to notification_log
- Propose actions
- Call external models
- Modify Steph/Maria configs
- Change any JSON output format

---

## 2. Scope Boundaries

| In Scope | Out of Scope |
|----------|-------------|
| Read today's observations from DB | Generate recommendations |
| Read today's escalations from DB | Write to notification_log |
| Call local Ollama (qwen3:1.7b) | Call external APIs (Sonnet/GPT-4o) |
| Write one enriched observation (category='daily_summary') | Write action proposals |
| Priority-order today's findings | Propose stop/allocation changes |
| Thematic grouping | Register OpenClaw skills |
| | Modify Maria/Steph configs |

---

## 3. Candidate Enrichment Outputs

### A. `daily_summary` observation (RECOMMENDED first)

**Purpose:** Single concise paragraph summarizing today's portfolio situation from all observations and escalations. Machine-readable, not conversational.

**Source data:** All `advisor_observations` + `escalation_queue` for today's date.

**Why safe:** It summarizes WHAT IS across multiple data points. No action language. No forward-looking claims.

**Storage:** Write to `advisor_observations` with `category='daily_summary'`, `source='ollama:enrichment'`, `model='ollama:qwen3:1.7b'`.

**Example output:**
> "Today: Portfolio $1,209K (+3.7% YTD). V concentration at 15.7% (above 15% threshold, earnings-suppressed). 1 stop triggered. 4 positions at ADD signal (SCHD, CSWC, PFLT, DIV — dividend gap). Income run-rate $10,367/yr from 15 payers. Pipeline fresh."

### B. `escalation_digest` observation

**Purpose:** Summary of pending escalations with relative priority assessment.

**Source data:** `escalation_queue WHERE status='pending'` + evidence JSON.

**Why safe:** Reports what's escalated and why, ordered by significance. Descriptive only.

**Storage:** Same as above, `category='escalation_digest'`.

**Example output:**
> "3 pending escalations: (1) 1 stop triggered [severity 1], (2) V at 15.7% above 15% concentration threshold [severity 2], (3) 4 ADD signals from dividend gap rule [severity 3]. Most time-sensitive: triggered stop."

### C. Priority score annotation (DEFERRED)

**Purpose:** Add a 0-1 priority score to each escalation beyond mechanical severity.

**Why deferred:** Requires reliable numeric output from Ollama. Better to establish text summarization first, then add scoring once patterns are clear.

### D. Novelty annotation (DEFERRED)

**Purpose:** Flag whether today's observation represents a new development vs continuation.

**Why deferred:** Requires comparing against multi-day history. More complex prompt engineering. Do after daily_summary is proven.

### E. Signal persistence annotation (DEFERRED)

**Purpose:** Note how many consecutive days a signal has persisted.

**Why deferred:** Could be done with pure SQL (no LLM needed). Better as a rule-based enhancement to Phase A1 observations, not an Ollama enrichment.

---

## 4. Storage Strategy

### Recommendation: Write to existing `advisor_observations` table

No new table needed. Use:
- `category = 'daily_summary'` or `'escalation_digest'`
- `source = 'ollama:enrichment'`
- `model = 'ollama:qwen3:1.7b'`
- `confidence = 0.85` (lower than 1.0 since model-generated, but high because grounded in data)
- `evidence = {observation_ids: [...], escalation_ids: [...], input_text: "..."}`

**Why this is the smallest safe approach:**
- No schema change needed
- Existing UNIQUE constraint handles dedup: `(observation_date, symbol, category, source)`
- `symbol = ''` for portfolio-level summary (same convention as Phase A1)
- Existing queries already work

---

## 5. Local Ollama Usage Model

### Model

`qwen3:1.7b` — already deployed, already used by Trade AI for catalyst scoring. Fast (<5s per call), free, adequate for structured summarization.

### Prompt shape

```
/no_think
You are a portfolio surveillance system. Summarize today's findings factually.

TODAY'S OBSERVATIONS:
{formatted list of observations with evidence}

TODAY'S ESCALATIONS:
{formatted list of escalations with severity}

RULES:
- State WHAT IS, never WHAT SHOULD BE
- No recommendations, no "should", "consider", "buy", "sell"
- Order by importance (severity 1 first)
- Include key numbers (portfolio %, dollar values)
- Maximum 3 sentences
- Reference specific tickers and categories

SUMMARY:
```

### Input limits

- Total input: ~2000 tokens max (observations + escalations for one day easily fit)
- Output: 100-200 tokens (3 sentences)
- `num_predict=200`, `temperature=0.3` (low creativity, high factuality)

### Grounding requirements

- Every claim in the summary must trace to a specific observation or escalation
- Evidence JSON in the output observation includes `observation_ids` and `escalation_ids` used as input
- If Ollama produces ungrounded claims, they should be detectable by cross-referencing evidence

### Cost/performance

- **Cost:** $0 (local Ollama)
- **Latency:** 3-8 seconds per summary
- **Frequency:** Once per pipeline run (daily)
- **Total pipeline impact:** +5-10 seconds

---

## 6. Guardrails

### Hard rules for enrichment output

| Rule | Enforcement |
|------|-------------|
| No "should", "consider", "recommend" | Post-generation regex check. If found, discard and log warning. |
| No "buy", "sell", "trim", "rotate" as imperatives | Same regex check. |
| No fabricated numbers | All numbers in output must exist in input observations. |
| Must reference evidence | `evidence` JSON must list IDs of input observations/escalations. |
| Maximum output length | 200 tokens / 3 sentences. Truncate if exceeded. |
| Required `confidence < 1.0` | Model-generated text always gets confidence 0.85, not 1.0. |
| Required `model` field | Always `'ollama:qwen3:1.7b'` — never blank or 'rule'. |

### Post-generation validation

```python
_BANNED_WORDS = ["should", "consider", "recommend", "buy", "sell", "rotate", "trim"]
if any(w in summary.lower() for w in _BANNED_WORDS):
    print("  [enrichment] ⚠️  Banned recommendation language detected — discarding")
    summary = None  # Don't write poisoned summary
```

### Fallback if Ollama unavailable

If Ollama times out or is down:
- Skip enrichment silently
- Log: `[enrichment] Ollama unavailable — skipping daily summary`
- Pipeline continues normally
- No observation written for today (it'll be generated on next successful run)

---

## 7. Verification Strategy

### Compare enrichment against raw observations

After writing the daily_summary:
```sql
SELECT observation FROM advisor_observations
WHERE observation_date = CURRENT_DATE AND source = 'ollama:enrichment';
-- Compare: does it only contain claims supported by other observations for same date?
```

### Ensure no recommendation language

Automated regex check before write. Also manual spot-check during verification:
```python
assert not any(w in summary.lower() for w in ["should", "consider", "recommend", "buy", "sell", "rotate", "trim"])
```

### Ensure reproducibility

Same input → approximately same output (with temperature=0.3). Not bit-for-bit identical, but structurally consistent (same tickers mentioned, same numbers cited).

### Ensure existing pipeline unchanged

```bash
# Before vs after: JSON outputs must be byte-for-byte identical
diff <(cat data/portfolios/state/action_signals.json) <(after-run action_signals.json)
# Expected: no diff (enrichment doesn't touch pipeline outputs)
```

---

## 8. Recommended Smallest Implementation Slice

### Choice: Write one `daily_summary` observation only

**Why this and not escalation_digest:**
- The daily_summary synthesizes ALL observations (broader value)
- The escalation_digest only covers escalated items (subset)
- Starting with the broader summary establishes the Ollama prompting pattern
- escalation_digest can be added trivially once daily_summary works

**Implementation:**
1. After observations + escalations are written (end of pipeline)
2. Read today's observations + escalations from DB
3. Format into Ollama prompt
4. Call Ollama (qwen3:1.7b, timeout=30s)
5. Strip `<think>` tags from output
6. Validate against banned words
7. Write to `advisor_observations` with `category='daily_summary'`, `source='ollama:enrichment'`
8. If anything fails: log and skip (non-blocking)

**Estimated effort:** 1-1.5 hours

---

## 9. Risks / Guardrails

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Ollama hallucinates recommendation language** | HIGH | Regex check before write. Discard if banned words found. Confidence <1.0 marks it as model-generated. |
| **Adding text noise to memory** | MEDIUM | Only 1 summary per day. Short (3 sentences max). Category='daily_summary' makes it easy to filter out. |
| **Duplicating Steph's future role** | LOW | Summary is factual digest, not advice. Steph gives advice when asked. These serve different purposes. |
| **Polluting advisor memory with weak summaries** | MEDIUM | confidence=0.85 (not 1.0). Model field records provenance. Easy to identify and bulk-delete if quality is poor. |
| **Slowing pipeline** | LOW | 5-10 seconds for one Ollama call. Pipeline already takes 4+ minutes. Negligible. |
| **Ollama unavailable** | LOW | Non-blocking. Skip with log. Pipeline unaffected. |
| **Output too verbose** | LOW | num_predict=200 hard cap. "Maximum 3 sentences" in prompt. |

---

## 10. Architect Recommendation

### Best next implementation slice

**Write one `daily_summary` observation per pipeline run.**

- Uses existing table (no schema change)
- Uses existing Ollama (already deployed)
- Follows existing patterns (same as Trade AI catalyst scoring in scoring.py)
- 1-1.5 hours to implement
- Independently valuable (future digest email can use this directly)

### What remains deferred

| Deferred | Until |
|----------|-------|
| `escalation_digest` | After daily_summary proves reliable (1-2 weeks) |
| Priority scoring | Phase C (monitoring daemon) |
| Novelty annotation | Phase C |
| Signal persistence annotation | Better as rule-based (Phase A1 enhancement) |
| External model enrichment | Phase D |

### Should this happen before or after Steph bridge skills?

**Before.** The daily_summary enrichment is a pipeline step (background, automatic). Steph bridge skills are a conversational interface (requires OpenClaw skill registration). The enrichment accumulates useful data that Steph will later query. Building the data first, then the query interface, is the right order.

---

## Appendix

### Example Ollama prompt

```
/no_think
You are a portfolio surveillance system. Summarize today's findings factually.

TODAY'S OBSERVATIONS:
- [performance] Portfolio at $1,208,609 | YTD +3.7% | 1W +2.1%
- [dividend] Portfolio dividend income: $10,367/yr from 15 payers
- [concentration] V is 15.7% of portfolio — signal: WATCH
- [concentration] FID-CONTRA-F is 14.0% of portfolio — signal: TRIM
- [signal] 4 positions have ADD signal: SCHD, CSWC, PFLT, DIV
- [risk] Portfolio heat: 6.0% | 1 stops triggered | 0 in danger zone
- [freshness] Pipeline completed successfully in 228s

TODAY'S ESCALATIONS:
- [severity 1] 1 stop(s) currently triggered
- [severity 2] V concentration at 15.7% exceeds 15% threshold
- [severity 3] 4 ADD signals present in today's signal set

RULES:
- State WHAT IS, never WHAT SHOULD BE
- No recommendations, no "should", "consider", "buy", "sell"
- Order by importance (severity 1 first)
- Include key numbers (portfolio %, dollar values)
- Maximum 3 sentences

SUMMARY:
```

### Example good output

> "One stop is triggered today (priority attention needed). V remains the largest position at 15.7% of the $1.21M portfolio, above the 15% concentration threshold but held at WATCH due to upcoming earnings. Income pipeline steady at $10,367/yr from 15 dividend payers with 4 positions flagging dividend-gap ADD opportunities."

**Why good:** Factual, prioritized, includes numbers, no action language, 3 sentences.

### Example bad output (would be discarded)

> "You should consider trimming V since it exceeds 15%. I recommend adding to the 4 dividend-gap positions to boost income toward the $28K target."

**Why bad:** "should consider", "trimming", "recommend", "adding" — all banned words. Would be caught by regex and discarded.

### How enriched text links to raw evidence

```json
{
  "observation_date": "2026-04-20",
  "symbol": "",
  "category": "daily_summary",
  "observation": "One stop is triggered today...",
  "evidence": {
    "observation_ids": [101, 102, 103, 104, 105, 106, 107],
    "escalation_ids": [1, 2, 3],
    "input_token_count": 312,
    "output_token_count": 87,
    "ollama_duration_ms": 4200
  },
  "source": "ollama:enrichment",
  "confidence": 0.85,
  "model": "ollama:qwen3:1.7b",
  "freshness_hash": "ea4ff1a05707"
}
```

---

*Phase A2-enrichment plan created 2026-04-20. Awaiting architect approval before implementation.*
