# Phase P2b — Plan enrichment (brain depth)

**Authority:** READ_ONLY_ADVISORY  
**Branch:** `feature/advisory-desk-v1`  
**Code:** `scripts/lib/cio_plan_enrichment.py`  
**Policy:** `config/cio_llm_policy.yaml`

## What “material” means

LLM budget may be spent only for material sources, e.g.:

- Situation types S1–S8 / `situation.raised`
- `OPERATOR_MESSAGE` / `S0_OPERATOR_CONVERSE`
- Optional high-priority goal wakes

**Non-material (no LLM):** pure heartbeat no-change, deterministic `/cio` status, `system.heartbeat_ok`.

## Flags

| Flag / config | Default | Effect |
|---|---|---|
| `llm.enabled` / `CIO_LLM_ENRICH` | on / unset=on | `0` forces template-only enrichment |
| `max_calls_per_hour` | 12 | Soft local cap (+ bridge global cap) |
| `enrich_dedup_hours` | 6 | Skip re-LLM same plan_id if evidence hash unchanged |
| `situation_notify_telegram` / `CIO_SITUATION_NOTIFY` | false / 0 | Optional Telegram on new plan |
| Flash vs Pro | Flash default | Pro for OPERATOR_MESSAGE, S0, S8 |

## narrative_source

| Value | Meaning |
|---|---|
| `llm` | Governed bridge returned validated JSON |
| `template` | Cap/provider/validation blocked — deterministic view + “LLM deferred” |

## Evidence contract

- Pack built from `plan.evidence_refs` + detector summary numbers  
- Model output JSON schema: summary, options, recommendation, risks, revisit_hint, cited_fields  
- Validator rejects numeric tokens not in pack (one retry, then template)

## Disable LLM on wakes

```bash
export CIO_LLM_ENRICH=0
# or config/cio_llm_policy.yaml llm.enabled: false
```

## Honest autonomy language

This is an **advisory colleague**: event/situation/chat → optional governed narrative under cap → plan fields.  
Not an autonomous trader. No orders/stops/2FA. Heartbeat remains the safety net.

## Tests

```bash
.venv/bin/python -m pytest tests/test_cio_plan_enrichment_p2b.py -q
```
