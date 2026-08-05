# CECO Maria/CIO authorization audit (read-only)

**Date:** 2026-08-05  
**Result:** **NOT PROVEN** → artifacts **QUARANTINED**  
**reason_code:** `UNVERIFIED_OPERATOR_AUTHORIZATION`

## Artifacts examined

| Agent | Path (quarantine) | process_id | model | request_id in artifact | cost |
|-------|-------------------|------------|-------|------------------------|------|
| Maria | `data/runtime/watchlist_intelligence/quarantine/CECO_maria.json` | `watchlist_maria_flash_narrative` | `deepseek-v4-flash` | `d5d84ee9-d186-4529-bd15-607c0a5f7a66` | 0.0002247 |
| CIO | `data/runtime/watchlist_intelligence/quarantine/CECO_cio.json` | `watchlist_steph_flash_narrative` | `deepseek-v4-flash` | `4b32e404-151e-49be-a55a-e8163c02b6d9` | 0.00018634 |

## Evidence found

### Consumption (`llm_consumption_log`)

Rows for processes around 2026-08-05 09:39–09:40 ET:

| id | process_id | task_summary | estimated_cost | provider_request_id |
|----|------------|--------------|----------------|---------------------|
| 4162 | watchlist_maria_flash_narrative | agent_flash:agent_narrative:intel-maria-CECO | 0.000225 | **NULL** |
| 4163 | watchlist_steph_flash_narrative | agent_flash:cio_synthesis:intel-cio-CECO | 0.000186 | **NULL** |

**Gap:** consumption rows do **not** carry `provider_request_id` matching the artifact request IDs.

### Reservations (`llm_cost_reservations`)

| id | process_id | projected | actual | status | model |
|----|------------|-----------|--------|--------|-------|
| 128 | watchlist_maria_flash_narrative | 0.000869 | 0.000225 | settled | deepseek-v4-flash |
| 129 | watchlist_steph_flash_narrative | 0.000869 | 0.000186 | settled | deepseek-v4-flash |

### Operator authorization event

- **Not found** in operator command / authorization audit tables.
- Artifact field `operator_approved: true` is **self-asserted** by `run_watchlist_intelligence_proof_reviews.py`.
- Chat approval text is not a durable authorization ledger event.

### Host containment

- Flag **remained active**: `~/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED`  
  content: `active reason=gate2-p0-pr284-final-e2e`
- Proof run used **process-scoped** override (`AGENT_JOBS_P0_CONTAINED=0` + alternate flag path) without removing the host flag.

## Disposition

1. Artifacts moved to `quarantine/` (not deleted).  
2. Projection excludes quarantine and demotes self-asserted COMPLETE → `NOT_RUN` / `UNVERIFIED_OPERATOR_AUTHORIZATION`.  
3. No new provider calls during correction.
