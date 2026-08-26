# Integrator-owned paths

Workers must not modify these files. Handoffs that touch them are rejected.

## Contracts and fixtures

- `docs/convergence/**`
- `schemas/control_plane/**`
- `fixtures/control_plane/**`
- `scripts/lib/control_plane_contract_v1.py`
- `apps/command-center-v3/src/control-plane/contractV1.ts`
- `tests/test_control_plane_contract_v1.py`
- `AI_WORK_POLICY.md`

## Central registration / shell (wired only after handoff review)

- `scripts/api_v2.py`
- `scripts/portfolio_server.py`
- `apps/command-center-v3/src/App.tsx`
- `apps/command-center-v3/src/components/NavRail.tsx`

R21 may *add* `scripts/api_v3_control_plane.py` and `scripts/lib/control_plane_*.py` **except** `control_plane_contract_v1.py`. Integrator registers the module in `api_v2.py`.

R22/R23/R24 may add pages under `apps/command-center-v3/src/pages/control-plane/` only. They must not register routes.

## Evidence / integration registry

- `docs/_evidence/r20-r24/**`
- `docs/convergence/UI_REPLACEMENT_MATRIX.md`
- `docs/convergence/DEPENDENCY_LEDGER.md`
- `docs/convergence/PARALLEL_EXECUTION_MANIFEST.md`

## Forbidden to all streams

- broker / order / stop / risk-policy / 2FA writers
- `RESEARCH_ALLOW_LOCAL_LLM` / `LLM_ALLOW_LOCAL_JUDGMENT` enablement
- live Command Center route replacement
- GitHub push / PR / CI
