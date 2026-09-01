# Control-plane contract change log

Status:      ACTIVE
as_of:       2026-08-26T13:52:03-04:00
Measured at: efcc51365 / not measured

Integrator-owned. Workers must not edit this file.

## 2026-08-26 — CONTRACT_CHANGE-001 freeze ControlPlane@v1.0.0

| Field | Value |
|---|---|
| old version | Control-Plane Contracts v1 (markdown vocabulary) + R21-ControlPlaneInventory@v1 proposed_contracts |
| new version | **ControlPlane@v1.0.0** |
| reason | Parallel R21/R22/R23/R24 requires one machine-readable freeze. Markdown and inventory used overlapping names (`NotificationStatus` vs `NotificationReceipt`). |
| affected streams | R21, R22, R23, R24, QA |
| compatibility impact | Additive union. No existing live API is versioned yet, so there is no production consumer to break. |
| migration requirement | None. R22/R23/R24 consume fixtures generated from v1.0.0. R21 implements GET-only routes matching this schema. |

Canonical artifacts:

- `docs/convergence/CONTROL_PLANE_CONTRACT_VERSION`
- `schemas/control_plane/v1.0.0/envelope.json`
- `fixtures/control_plane/v1.0.0/`
- `scripts/lib/control_plane_contract_v1.py`
- `apps/command-center-v3/src/control-plane/contractV1.ts`

Do not bump this version to make frontend coding easier.

## 2026-08-26 — CONTRACT_CHANGE-002 freeze CONTROL_PLANE_API_V1_BASELINE

| Field | Value |
|---|---|
| old version | ControlPlane@v1.0.0 HTTP envelope (`payload`, `schema`, `page`, `computes_*`) as the consumption target |
| new version | **CONTROL_PLANE_API_V1_BASELINE** (`084674c5`) HTTP envelope (`ok`, `as_of`, `source_sha`, `freshness`, `data_quality`, `evidence_class`, `data`) |
| reason | Operator accepted implemented R21 summary APIs as the V1 consumption freeze so R22–R24 can wire now. ControlPlane@v1.0.0 remains field vocabulary (RuntimeStatus, EvidenceClass, lineage names), not the HTTP shape. |
| affected streams | R21, R22, R23, R24, QA |
| compatibility impact | Formal contract change. Pages that required `payload`/`schema=ControlPlane@v1.0.0` must consume `data` + `items`/`pagination`. Do not silently map missing fields. |
| migration requirement | R22 list views, R23, R24 GET `/api/v3/control-plane/*` summary routes. R22 detail/trace keep labeled fixtures until R21.1. Populated ControlPlane@v1.0.0 fixtures are MOCK only — never production data. |

Canonical artifacts:

- `docs/convergence/CONTROL_PLANE_API_V1_BASELINE.md`
- `docs/convergence/CONTROL_PLANE_API_V1_BASELINE.json`
- `fixtures/control_plane/api_v1_baseline/`
- `apps/command-center-v3/src/control-plane/apiV1Baseline.ts`
- `tests/test_control_plane_api_v1_baseline.py`

R21.1 (detail / lineage) must be additive. Do not rename frozen summary keys to match frontend convenience.

## 2026-08-26 — CONTRACT_CHANGE-003 freeze CONTROL_PLANE_API_V1.1 detail/lineage

| Field | Value |
|---|---|
| old version | CONTROL_PLANE_API_V1_BASELINE summary-only |
| new version | **CONTROL_PLANE_API_V1.1** (summary + detail + lineage) |
| reason | Operator accepted c3b105a7 / b5f55339. Outer envelope keys unchanged. |
| compatibility impact | Additive routes `/agents/{id}` and `/workflows/{id}`. Summary keys frozen. |
| migration requirement | R22 runtime mocks removed. Cross-ID lookup uses the same detail GET. |
