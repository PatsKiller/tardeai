# R21 Codex brief — CONTROL_PLANE_BACKEND

**Summary freeze (accepted):** CONTROL_PLANE_API_V1_BASELINE @ `084674c5`
**Do not rename** summary routes or envelope keys (`ok/as_of/source_sha/freshness/data_quality/evidence_class/data`).

**R21.1 (open, additive):** detail routes, lineage adapters, extra contract/fault proof.
Do not break summary consumers. Field vocabulary remains ControlPlane@v1.0.0.

**Prior brief (superseded for HTTP shape):** ControlPlane@v1.0.0 envelope (`payload`).
**Version file:** `docs/convergence/CONTROL_PLANE_CONTRACT_VERSION` (vocabulary)
**HTTP freeze:** `docs/convergence/CONTROL_PLANE_API_V1_BASELINE.md`

## Implement

GET-only:

- `/api/v3/control-plane/system`
- `/api/v3/control-plane/agents`
- `/api/v3/control-plane/agents/{agent_id}`
- `/api/v3/control-plane/workflows`
- `/api/v3/control-plane/workflows/{trace_id}`
- `/api/v3/control-plane/research`
- `/api/v3/control-plane/stores`
- `/api/v3/control-plane/identity`
- `/api/v3/control-plane/notifications`
- `/api/v3/control-plane/learning`
- `/api/v3/control-plane/maturity`
- `/api/v3/control-plane/audit`

Every response is a ControlPlane envelope. POST/PUT/PATCH/DELETE → 405.

## Do not

- Edit `scripts/api_v2.py` (Integrator registers your module)
- Edit `App.tsx` / `NavRail.tsx`
- Enable local LLM
- Mutate broker/orders/stops/risk/2FA
- Push / open PRs
- Claim NATURAL_CURRENT if CURRENT pin does not run the code

## Return WORKSTREAM_HANDOFF as specified by Integrator.
