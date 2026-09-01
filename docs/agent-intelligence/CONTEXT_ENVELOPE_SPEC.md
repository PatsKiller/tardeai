# ContextEnvelope@v1 — Specification

Status:      ACTIVE
as_of:       2026-08-16T22:03:26-04:00
Measured at: efcc51365 / not measured

Canonical context object shared by Alex and participating specialists.
Implemented in `scripts/lib/agent_context_envelope.py`.

## Contract

`context_envelope_version: "1.0"`

| Field | Type | Notes |
|-------|------|-------|
| `context_envelope_version` | string | always `"1.0"` |
| `wake_id` | string | durable wake identity |
| `trace_id` | string | trace identity (defaults to `tr_<wake_id>`) |
| `agent` | string | agent name |
| `role` | string | e.g. `cio_synthesis`, `risk_guardian`, `specialist`, `ledger` |
| `trigger` | string | why the agent woke |
| `trigger_type` | string | canonical trigger type |
| `trigger_digest` | string | digest of the trigger |
| `created_at` | ISO-8601 | volatile (excluded from digest) |
| `decision` | object | decision_id, input/evidence digests, standing recommendation, current_action, actionability, act_now, freshness |
| `office_truth` | object | holdings/cash/portfolio/risk/policy/tax refs + `source_asof` + `truth_digest` |
| `active_intent` | object | thesis_id, thesis_version, open_goal_ids, plan_ids, current_constraints |
| `episodic_memory` | object | query, memory_ids, records, conflicts, retrieval_status, provider |
| `research_memory` | object | case_ids, lesson_ids, hypothesis_ids, research_refs, counterevidence_refs, retrieval_status |
| `external_read_context` | object | mcp_calls, calendar_refs, document_refs, availability |
| `specialist_context` | object | prior_views, requested_views |
| `governance` | object | authority, permitted/denied capabilities, freshness_rules, memory_authority |
| `provenance` | object | context_digest, source_refs, built_at |

## Required behavior

1. **Deterministic stable digest** — `context_envelope_digest()` hashes canonical
   JSON of material content; timestamps and the digest field itself are excluded.
   Same inputs → same digest; any material change → new digest.
2. **Explicit source/as-of** — canonical truth carries `source_asof` and
   `truth_digest`; refs point at the canonical system of record, never a memory.
3. **Truth/memory separation** — memory lives only in `episodic_memory`; it can
   never be written back into `office_truth`.
4. **Conflicts surfaced** — `episodic_memory.conflicts` carries disputing memory
   as visible metadata, not primary context.
5. **Missing providers explicit** — `NOT_CONFIGURED` / `UNAVAILABLE` / `ERROR`
   retrieval statuses, never a silent empty list.
6. **No hidden fallback to stale memory** — retrieval status is recorded before
   synthesis; an empty result is `EMPTY`, distinct from "not consulted".

## Governance invariants

- `governance.authority` must equal `READ_ONLY_ADVISORY`.
- `governance.memory_authority` must equal `NON_AUTHORITATIVE_CONTEXT`.
- Validation fails closed on any deviation.

## Chokepoint

`get_context_for_agent(*, agent, wake, decision, symbols, plan_id,
required_domains, ...)` is the single entrypoint all agent reasoning must
migrate toward. It consults memory providers through a narrow duck-typed
protocol (`health()` + `search()`) and fails soft when providers are absent.

## Redaction

`redact_secrets()` removes credential-shaped keys and values (API keys, tokens,
passwords, bearer headers, private keys, session cookies, and high-entropy
secret literals) recursively and non-mutatingly.
