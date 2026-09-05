# Controlled Curation and Provenance (Phase 5)

**Status:** Implemented in-process (no real LLM calls).  
**Code:** `scripts/lib/comms/curation.py`  
**Contract:** `CurationReceipt@v1`  
**Related:** `docs/architecture/communication-event.md`, gateway remediation plan (Drive)

---

## Purpose

Improve narrative quality only where policy allows. Orders, positions, approvals, broker facts, risk limits, protection incidents, and related protected facts are **never** rewritten by an LLM. Default curation mode is **DETERMINISTIC**.

Any LLM mutation of protected facts forces **DETERMINISTIC FALLBACK** with failure evidence on a `CurationReceipt`.

---

## Curation modes

| Mode | Meaning |
|---|---|
| `DETERMINISTIC` | Facts/body from producer or stable render; no model |
| `TEMPLATE` | Deterministic facts filled into a fixed template |
| `LLM_SUMMARY` | Approved Tier-2 synthesis (precomputed text only in this phase) |
| `LLM_CHALLENGE` | Tier-3 adversarial review when novelty/conflict flags set |
| `HUMAN_EDIT` | Operator-authored narrative |

---

## Tier policy

| Tier | Classes (examples) | Allowed mode |
|---|---|---|
| 0 | `approval`, `protection_incident`, `broker_fact`, `order_state`, `risk_limit`, `account_fact`, `health`, `outage`, `threshold`, `audit_notice`, `operator_alert` | `DETERMINISTIC` only |
| 1 | `digest`, `digest_item`, `status_report`, `ops_summary` | `TEMPLATE` |
| 2 | `research`, `research_brief`, `advisory`, `advisory_recommendation`, `thesis_update`, `intelligence_summary` | `LLM_SUMMARY` |
| 3 | Same research/advisory set when `novelty=True` or `conflict=True` | `LLM_CHALLENGE` |

Unknown classes fail closed to `DETERMINISTIC`. Novelty/conflict flags never escalate Tier-0 classes.

`select_curation_mode(message_class, *, novelty=False, conflict=False)` encodes this policy.

---

## Protected facts

`PROTECTED_FACT_KEYS` covers prices, quantities, accounts, risk limits, approvals/order ids, timestamps, authorities, and action tokens (see module constant for the full frozenset).

`preserve_protected_facts(before, after)` deep-compares the protected subset. Narrative-only keys may change freely.

---

## CurationReceipt@v1

Every curation path returns a receipt with:

- `curation_mode`, `provider`, `model`
- `prompt_template_id`, `prompt_template_version`
- `input_hashes`, `output_hash`, `retrieved_context_ids`
- `latency_ms`, `token_cost`
- `fallback_reason`, `fact_preservation_ok`
- `protected_facts_before_hash`, `protected_facts_after_hash`
- `policy_decision` (`allow` \| `deny_deterministic` \| `fallback_deterministic`)

Optional light persistence: `store_curation_receipt` / `get_curation_receipt` (in-process map keyed by `event_id`). Not a durable DB table in this phase.

---

## API surface

| Function | Role |
|---|---|
| `select_curation_mode` | Policy decision |
| `curate_deterministic` | Tier-0/1 body + receipt (optional template) |
| `apply_llm_curation_result` | Accept **precomputed** curated text; enforce fact preservation |
| `preserve_protected_facts` | Deep compare of protected keys |
| `store_curation_receipt` / `get_curation_receipt` | Memory receipt store |

**No real LLM API calls** are made from this module. Callers that invoke models elsewhere must pass the resulting text and claimed `protected_facts_after` into `apply_llm_curation_result`.

### Fallback behaviour

If protected facts differ after LLM curation:

1. `fact_preservation_ok=False`
2. `fallback_reason=protected_fact_mutation`
3. `curation_mode` forced to `DETERMINISTIC`
4. Body protected facts restored from the event’s original `protected_facts`
5. Delivered `sanitized_body` comes from the deterministic path, not the rejected LLM text

Tier-0 classes requesting LLM apply are denied (`policy_decision=deny_deterministic`) and rendered deterministically even when facts are unchanged.

---

## Tests

`tests/test_comms_curation.py`:

- Default DETERMINISTIC for approvals/protection
- LLM path allowed for research
- Protected-fact mutation → fallback
- Receipt fields populated
- `fact_preservation_ok` true when unchanged

---

## Non-goals (this phase)

- Calling DeepSeek / Grok / ChatGPT from the gateway
- Durable `curation_receipts` SQL table
- Wiring every producer through curation before publish
- Citation validation pipeline (follow-on)

Producer migration and transport cutover remain later phases.
