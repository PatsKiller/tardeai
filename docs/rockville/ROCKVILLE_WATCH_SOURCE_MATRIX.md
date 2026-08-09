# ROCKVILLE_WATCH_SOURCE_MATRIX

| Concern | Authority | Module / path |
|---------|-----------|---------------|
| Exact model policy | Server SSOT | `config/rockville/ROCKVILLE_WATCH_CIO_MODEL_POLICY.json` |
| Policy resolution | Server | `scripts/lib/rockville/model_policy.py` |
| Primary state projection | Deterministic | `scripts/lib/rockville/decision_projection.py` |
| Legacy presentation (fixed) | Deterministic | `scripts/operator_presentation.py` |
| Material fingerprint | Deterministic | `scripts/lib/rockville/material_fingerprint.py` |
| CIO once/day trigger | Deterministic scheduler | `scripts/lib/rockville/cio_scheduler.py` |
| Additive APIs | Read/shadow | `scripts/api_v3_watch_rockville.py` + `api_v2` ROUTES |
| Card v2 UI | Feature-flagged | `apps/command-center-v3/src/components/rockville/WatchCardV2.tsx` |
| CIO panel UI | Feature-flagged | `apps/command-center-v3/src/components/rockville/CioDailyPanel.tsx` |
| Watch hub mount | Shadow band | `apps/command-center-v3/src/pages/WatchHub.tsx` |
| FTH fixture | Tests | `tests/fixtures/rockville/ROCKVILLE_FTH_REGRESSION_FIXTURE.json` |
| Decision schema | Contract | `docs/rockville/ROCKVILLE_WATCH_DECISION_SCHEMA.json` |
| CIO schema | Contract | `docs/rockville/ROCKVILLE_WATCH_CIO_SCHEMA.json` |
| Reflective review schema | Contract | `docs/rockville/ROCKVILLE_WATCH_REFLECTIVE_REVIEW_SCHEMA.json` |
| Existing v2 watch consumers | Unchanged | `/api/v2/watch/*` |
| Agent Flash governance | Separate containment | `scripts/lib/agent_flash_governance.py` (exact flash; not CIO Pro bulk) |

## LLM authority boundary

| May | Must not |
|-----|----------|
| Summarize, synthesize, rank attention | Establish price / arithmetic |
| Challenge, explain evidence | Establish state / eligibility |
| Identify contradictions | Entry / stop / target / proposal / execution authority |
| Fail with typed codes | Silent fallback to Gemma/Grok/ChatGPT/other tier |
