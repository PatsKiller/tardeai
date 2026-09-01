# Dependency Ledger

Status:      ACTIVE
as_of:       2026-08-26T13:27:06-04:00
Measured at: efcc51365 / not measured

HTTP freeze: **CONTROL_PLANE_API_V1_BASELINE** (`084674c5`).
Field vocabulary: ControlPlane@v1.0.0.

| Item | Status |
|---|---|
| R21 summary APIs | AVAILABLE |
| R21 detail APIs | R21.1_PENDING (local preview `c3b105a7`; Codex handoff not accepted) |
| R21 lineage adapters | R21.1_PENDING |
| R22 list views | SUMMARY_APIS_CONSUMED (`50f2a5c6`) |
| R22 detail/trace | MOCK_BLOCKED_UNTIL_R21_1 |
| R23 | SUMMARY_APIS_CONSUMED (`c76088d3`) |
| R24 | SUMMARY_APIS_CONSUMED (`52b0ae64`) |
| QA | PASS (33 probes) |

Rules:

1. R22 list, R23, R24 consume GET `/api/v3/control-plane/*` summary routes now.
2. Missing canonical stores render `UNAVAILABLE` / `INVALID_SCHEMA` / `EMPTY_VALID`. Do not substitute populated mocks as live data.
3. R22 detail (`/agents/{id}`) and full workflow lineage keep labeled fixtures until R21.1.
4. R20 runtime evidence is separate from R21 admin visibility. CALLABLE_ONLY is valid before office LIVE.
5. R24 must not invent maturity scores.
6. Integrator owns shared route registration, schema registry, and cross-stream tests.
7. No worker push. No integrator push. No PR. No CI.

Blocking conditions: missing canonical source (honest UNAVAILABLE is not blocking), unsafe authority boundary, schema rename of the freeze, or any regression in existing live routes.
