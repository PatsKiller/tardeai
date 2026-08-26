# Control-plane contract change log

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
