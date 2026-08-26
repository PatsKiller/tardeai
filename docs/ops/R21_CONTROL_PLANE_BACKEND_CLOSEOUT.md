# R21 Control-Plane Backend Closeout

**Date:** 2026-08-26  
**Workstream:** R21  
**Source SHA:** `e683e90f9a24b9cd56399054da33cc6c3b4ba8bb`  
**Authority:** `READ_ONLY_ADVISORY`

## Mission

Inventory the current administrative API surface and freeze a contract for a unified read-only Command Center control plane. This tranche is documentation and evidence only; it does not change application code, routes, persistence, or authority.

## Starting State

The repository already exposes a broad legacy `/api/v2` dispatcher in `scripts/api_v2.py`, additive `/api/v3` routes, a CIO-specific API module (`scripts/api_v3_cio.py`), and agent-runtime read routes (`scripts/agent_runtime/read_api.py`). These routes are useful canonical readers but are not one coherent contract: response envelopes, status vocabulary, pagination, freshness, and evidence labeling vary by endpoint.

## Existing Surface

The machine-readable inventory at [`docs/_evidence/r21/CONTROL_PLANE_API_INVENTORY.json`](../_evidence/r21/CONTROL_PLANE_API_INVENTORY.json) records concrete route groups for system health, agents, workflows/queues, research/Hermes, data/identity, notifications/CIO, learning/maturity, and audit. Representative existing readers include:

- `/api/v2/agents/summary`, `/api/v2/agent-health`, `/api/v3/agent-runtime/runs`
- `/api/v2/orchestration`, `/api/v2/tasks`, `/api/v2/queue/summary`
- `/api/v2/research-topics`, `/api/v2/research-intelligence`, `/api/v2/hermes/provenance`
- `/api/v2/data-product-health`, `/api/v2/intelligence-entities`, `/api/v2/symbol-cards`
- `/api/v2/notifications/recent`, `/api/v3/cio`, `/api/v3/alerts/active`
- `/api/v2/weekly-learning`, `/api/v2/hermes/maturity-dashboard`
- `/api/v2/ops/audit`, `/api/v2/trade-integrity-audit`, `/api/v2/system/siem`

## Contract Freeze

R21 proposes typed read models for `RuntimeStatus`, `AgentRuntimeStatus`, `AgentTaskStatus`, `WorkflowTrace`/`WorkflowNode`/`WorkflowEdge`, `ResearchAttentionStatus`, `CanonicalStoreStatus`, `IdentityStatus`, `NotificationReceipt`, `LearningEvidenceStatus`, and `AuditCapabilityClaim`. Field-level definitions are frozen in the JSON inventory and must be reused by R22/R23/R24 rather than redefined in frontend components.

The proposed namespace is `/api/v3/control-plane/*`. It is intentionally additive and read-only. Existing routes remain in place until parity, operator review, and rollback gates are complete.

## Gaps Requiring Implementation

1. No unified namespace/envelope joins the legacy readers.
2. Runtime states are not normalized (`LIVE_EVENT_DRIVEN`, `LIVE_SCHEDULED`, `CALLABLE_ONLY`, `EXPECTED_IDLE`, `SHADOW`, `DISABLED`, `BROKEN`).
3. No stable event-to-entity-to-research-to-CIO workflow trace exists.
4. Evidence class is not universal, risking replay/shadow/live conflation.
5. Canonical store and identity health are fragmented.
6. Notification candidate-to-receipt funnel is split across readers.
7. Maturity scores lack normalized proof references and limiting factors.
8. Pagination/filtering and mutation metadata vary across legacy endpoints.

## Safety / Authority

This workstream made no runtime or database changes. Proposed control-plane routes are `GET` only. They must not trade, place/cancel orders, change stops, modify risk policy, modify 2FA, promote financial policy, or alter memory behavior. Existing governed write endpoints remain outside this contract and require separate authority review.

## Tests and Evidence

- **Source inspection:** `scripts/api_v2.py:35539+` (`ROUTES`), `scripts/api_v3_cio.py` module header/routes, and `scripts/agent_runtime/read_api.py:32-41`.
- **Evidence artifact:** `docs/_evidence/r21/CONTROL_PLANE_API_INVENTORY.json`.
- **Automated tests:** none run; no application code was changed.
- **Live proof:** not claimed. A live HTTP contract probe remains an integration task for the Integrator after endpoint implementation.

## Handoff

This documentation-only handoff is ready for integration review. R22/R23/R24 may build typed mocks directly from the frozen contract. The Integrator owns route registration and any shared schema implementation; this workstream intentionally does not edit shared application files.

**Known limitation:** the proposed routes and schemas are not yet implemented. Status remains `CONTRACT_FROZEN_SOURCE_AUDIT_ONLY`.

## Implementation Addendum (R21 backend tranche)

The read-only projection implementation is now present in `scripts/control_plane_api.py`, with additive dispatch from `scripts/portfolio_server.py` for `/api/v3/control-plane/*`. Responses carry `as_of`, source SHA, freshness, data quality, and evidence class. Collection responses are bounded to 200 records. Missing or malformed canonical metadata is surfaced as `UNAVAILABLE` or `INVALID_SCHEMA`; no intelligence is fabricated.

Validation: `pytest -q tests/test_control_plane_api.py` -> 6 passed. Evidence: `docs/_evidence/r21/R21_ENDPOINTS.json` and `R21_FINAL_ACCEPTANCE.json`. This branch remains local and is not deployed; Integrator must wire canonical service readers and detail lineage routes during integration.
