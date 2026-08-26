# R21 Codex brief — CONTROL_PLANE_BACKEND

**Contract:** ControlPlane@v1.0.0
**Version file:** `docs/convergence/CONTROL_PLANE_CONTRACT_VERSION`
**Schema:** `schemas/control_plane/v1.0.0/envelope.json`
**Fixtures:** `fixtures/control_plane/v1.0.0/*.json` (response shape to match)
**Python types:** `scripts/lib/control_plane_contract_v1.py` (do not modify; consume)

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
