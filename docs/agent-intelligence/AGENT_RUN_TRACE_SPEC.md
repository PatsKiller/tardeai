# AgentRunTrace@v1 — Specification

Status:      ACTIVE
as_of:       2026-08-16T22:03:26-04:00
Measured at: efcc51365 / not measured

Structured, redacted, append-only trace of one agent run.
Implemented in `scripts/lib/agent_run_trace.py`.

## Contract

`trace_version: "1.0"`

| Field | Type | Notes |
|-------|------|-------|
| `trace_version` | string | always `"1.0"` |
| `trace_id` | string | `tr_<wake_id>` or `tr_<uuid16>` |
| `wake_id` | string | durable wake identity |
| `parent_trace_id` | string | specialist parent linkage |
| `trigger` / `trigger_digest` | string | why the agent woke |
| `agent` / `role` | string | identity |
| `started_at` / `ended_at` | ISO-8601 | lifecycle |
| `status` | enum | `started` \| `completed` \| `error` \| `superseded` |
| `context` | object | context_digest + canonical source refs + memory/mcp call ids |
| `reasoning_runtime` | object | model, prompt_version/digest, specialist/tool calls, retries, errors |
| `decision` | object | input/evidence digests, baseline/final action+size, blocker, reason_for_change |
| `notification` | object | considered/sent, dedupe_key, suppressed_reason, notification_id |
| `operator` | object | disposition, note_event_id |
| `follow_up` | object | scheduled, follow_up_at, revisit_id |
| `learning` | object | case_id, outcome_id, lesson_ids, hypothesis_ids |
| `performance` | object | latency_ms, tokens, estimated cost |
| `security` | object | authority, denied_tool_attempts, redaction_count |

## Required behavior

1. **Chain-of-thought never persisted** — fields named
   `chain_of_thought` / `cot` / `reasoning` / `internal_monologue` / `scratchpad`
   are stripped recursively before persist.
2. **Secrets redacted** — `sanitize_trace()` applies `redact_secrets()` over the
   whole record.
3. **Append-safe, crash-safe** — JSONL at `data/cio/agent_run_traces.jsonl`,
   one line per record, `flush()` per write.
4. **Queryable** — `query_traces()` filters by `wake_id`, `trace_id`,
   `decision_id`, `case_id`, `agent`.
5. **Fail-soft** — append/query never raise; they return `False`/`[]` on error.

## Storage

Reuses the existing durable pattern from `cio_wake_traces.py`. No new database.
Retention policy is deferred to Phase 10 (bounded retention).
