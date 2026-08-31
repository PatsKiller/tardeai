# Privacy & Redaction

Status:      ACTIVE
as_of:       2026-08-17T10:57:05-04:00
Measured at: efcc51365 / not measured

`READ_ONLY_ADVISORY` · Phase 9

This document specifies what the Agent Intelligence Foundation redacts, where
redaction happens, and the invariants that keep secrets, PII, and
chain-of-thought out of persisted state.

## What is redacted

Redaction is implemented by `redact_secrets()` in
`scripts/lib/agent_context_envelope.py` and is intentionally **over-broad
rather than under-broad**.

### 1. Secret-shaped keys

Any object key matching a credential shape is replaced with `[REDACTED]`,
regardless of its value:

- `api_key`, `api key`
- `secret`, `token`, `password`, `passwd`, `credential`
- `authorization`, `bearer`
- `private_key`, `private key`
- `session_cookie`
- `access_key`, `access key`
- `refresh_token`, `refresh token`

### 2. Secret-shaped values

Any string matching a token literal is replaced with `[REDACTED]`:

- `sk-…` (OpenAI-style keys)
- `ghp_…` (GitHub personal access tokens)
- `xoxb-…` / `xoxp-…` / `xoxr-…` / `xoxa-…` / `xoxs-…` (Slack tokens)
- `AKIA…` (AWS access-key ids)
- 32+ character hex literals
- any string containing a secret-shaped *key* (e.g. a whole line that reads
  `Authorization: Bearer abc123` is redacted in full)

### 3. Tokens / auth material

Tokens and authorization material are both redacted and **rejected at memory
admission**: `build_memory_record()` raises `ValueError` if `content` or
`subject` is secret- or token-shaped, so a token can never become a memory
record.

### 4. PII and full sensitive documents

- Operator PII is **not admitted** into memory (`MEM0_DUE_DILIGENCE.privacy`).
- Full sensitive documents are **never persisted**. The tool-call receipt stores
  only `request_digest` / `response_digest` (hashes), not raw bodies. The MCP
  gateway redacts the response *before* it is returned and *before* the receipt
  digest is computed.
- There is no code path that persists a full document body; documents are
  referenced by `document_id`/`path`/`source_url`, never by their contents.

## Where redaction happens

| Boundary | Module | Mechanism |
|----------|--------|-----------|
| Context envelope | `agent_context_envelope.py` | `redact_secrets()` primitive; memory is separated from truth and never merged back into `office_truth` |
| Run trace | `agent_run_trace.py` | `sanitize_trace()` strips chain-of-thought fields then redacts; `append_trace()` persists the sanitized copy |
| Tool trace | `agent_tool_trace.py` | `request_digest()`/`response_digest()` redact before hashing; `append_tool_call()` redacts the record before persist |
| MCP responses | `mcp_read_only_gateway.py` | `call_mcp_tool()` redacts the response in `_finish()` before returning it and before computing the receipt digest |
| Memory admission | `agent_memory_governance.py` | `_contains_secret()` rejects token-shaped content/subject at build time |

Because every persist path funnels through one of the `redact_secrets()` /
`sanitize_trace()` / digest primitives, there is a single, auditable redaction
seam.

## Chain-of-thought is never persisted

`agent_run_trace.py` maintains a forbidden-field set:

```text
chain_of_thought, cot, reasoning, internal_monologue, scratchpad
```

`_strip_forbidden()` recursively removes these fields before persist, and
`validate_trace()` rejects any trace that still contains `chain-of-thought` or
`internal-monologue` after sanitization. Reasoning is therefore in-memory only:
the trace records **what** was decided (structured decision/evidence digests),
never **how** it was reasoned about.

## The no-secrets-in-trace invariant

1. **Digests, not bodies.** Tool receipts store `request_digest` and
   `response_digest` (hashes of the redacted payload), never the raw
   request/response. A secret in a response cannot leak through the trace even
   if it slipped past a single redaction pass, because only the hash is stored.
2. **Redact before persist.** `append_tool_call()` and `append_trace()` both run
   redaction on the final record, so a caller cannot bypass redaction by
   constructing a record directly.
3. **Reject at the door.** Memory admission rejects secret-shaped content at
   `build_memory_record()`, so secrets cannot enter the memory store at all.

Net invariant: **no OAuth token, API token, session cookie, broker credential,
private signing key, or full sensitive document ever appears in an envelope,
a run trace, a tool trace, or a memory record.**

## Retention bounds

- **Memory** carries `valid_from` / `expires_at` and a `STATUS_EXPIRED` state;
  expired records are excluded from primary context and retrieval. Every
  production memory record must carry an explicit `expires_at`.
- **Run/tool traces** are append-only JSONL (`data/cio/agent_run_traces.jsonl`,
  tool traces). A bounded retention/rotation utility
  (`agent_trace_retention.enforce_trace_retention`) now exists with configured
  max age / max bytes / max rows, atomic rotation, and a governed-path guard;
  it defaults to dry-run (no write) and only ever touches the two governed
  trace paths. No production purge is performed in this remediation; an
  operator deployment step (timer/cron) is documented in the runbook.

> Residual risk: append-only traces are bounded **only when the retention step
> is actually scheduled/run**. The utility is implemented and tested; the
> operator must still schedule it before production activation (see
> DEPLOYMENT_RUNBOOK.md).
