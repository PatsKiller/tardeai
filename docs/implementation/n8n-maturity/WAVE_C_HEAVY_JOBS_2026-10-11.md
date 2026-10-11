# Wave C — heavy CC jobs (advisory / analyst / brief / legacy Run)

```
Status: ACTIVE
as_of: 2026-10-11T18:45:00-04:00
Measured at: code PR on n8nmat/wave-c-heavy-jobs off origin/main c15b7b98c
Canonical repo path: docs/implementation/n8n-maturity/WAVE_C_HEAVY_JOBS_2026-10-11.md
Authority: AGENTS.md §23 / §24.1; N8N_VS_COMMAND_CENTER_EVALUATION Wave C; N8N_ONBOARDING_STANDARD.md
Supersedes: none (pairs with WAVE_B_CC_ORCHESTRATE_2026-10-11.md)
See also: scripts/lib/n8n_cc_wave_c.py; scripts/advisory_desk_run_now.py; scripts/analyst_prospectus_generate.py; scripts/aegis_brief_regenerate.py
```

## What landed (additive; CURRENT-safe default)

1. **Wave B polish** — Coordination projection already exposes `research-intake` + `watch-refresh` spotlights
   (`lane_spotlights` → `GET /api/v2/coordination/events` → CC Coordination page). Proof steps below.
2. **C1 Advisory run-now** — `start_run_now` enqueues `advisory-desk-run-now` via
   `host_run_request` when Wave C mode is on; executor CLI
   `scripts/advisory_desk_run_now.py` runs `execute_run_now` (desk + enrich). API still returns 202 with
   `run_id` / ledger pointer. Authority `READ_ONLY_ADVISORY`.
3. **C2 Analyst / brief** — `POST /api/v2/reports/analyst/generate` and
   `POST /api/v2/reports/brief/regenerate` enqueue dedicated lanes (not
   `generate-analyst-daily-digest`) when Wave C mode is on; 202 + `run_id`.
4. **C3 Legacy Run buttons** — `/api/run-portfolio`, `run-trade-ai`, `run-aegis`, `run-pipeline`,
   `run-recovery-review`, `run-reprice` no longer spawn Thread/subprocess. Clear JSON refuse
   (409/410) unless a mapped lane is already allowlisted (none of the Ops mappings are today).

## Wave C modes

| `TRADEAI_N8N_CC_WAVE_C_MODE` | Behaviour |
|----------------------------|-----------|
| `off` / `0` (default) | C1/C2 keep prior Thread / sync inline paths (CURRENT drop-in safe) |
| `dry_run` | `host_run_request` with `mode=dry_run` (prove path; no paid LLM) |
| `apply` / `1` | `host_run_request` with `mode=live` (executor stage-clamps shadow → dry_run) |

C3 refuse is **always on** (not gated by Wave C mode): unsafe UI spawn is removed regardless.

## Lane ids

| lane_id | CLI | API | stage / dispatch |
|---------|-----|-----|------------------|
| `advisory-desk-run-now` | `scripts/advisory_desk_run_now.py` | `POST /api/v3/advisory/run-now` | shadow; dry_run_arg `--dry-run`; live_arg `[]` (paid after cutover) |
| `analyst-prospectus-generate` | `scripts/analyst_prospectus_generate.py` | `POST /api/v2/reports/analyst/generate` | shadow; request sidecar under `data/runtime/n8n_cc_wave_c/requests/` |
| `aegis-brief-regenerate` | `scripts/aegis_brief_regenerate.py` | `POST /api/v2/reports/brief/regenerate` | shadow; no Telegram send |

Health contracts for all three are **REVIEWED** (operator-ready purpose + upstream_stale).

## C3 disposition table

| Route | Disposition | Mapped lane | Allowlisted today? | HTTP |
|-------|-------------|-------------|--------------------|------|
| `/api/run-portfolio` | refuse_until_allowlisted | `portfolio-daily-cadence` | no (`pending_tranches.N2`) | 409 |
| `/api/run-trade-ai` | refuse_until_allowlisted | — | — | 410 |
| `/api/run-aegis` | refuse_until_allowlisted | — | — | 410 |
| `/api/run-pipeline` | refuse_until_allowlisted | — | — | 410 |
| `/api/run-recovery-review` | refuse_until_allowlisted | — | — | 410 |
| `/api/run-reprice` | refuse_until_allowlisted | — | — | 410 |

Prefer refuse over inventing unsafe lanes. If `portfolio-daily-cadence` later gains a full allowlist
entry, `legacy_run_refuse` will retarget via `host_run_request` automatically.

## Wave B spotlight proof (operator)

```bash
# 1) Shadow emit (default TRADEAI_N8N_CC_EMIT_MODE=dry_run)
TRADEAI_STATE_ROOT=$HOME/trade-ai-releases/persistent-state \
  python3 -c "from scripts.lib.n8n_cc_wave_b_emit import safe_emit_research_intake, safe_emit_watch_refresh; \
print(safe_emit_research_intake(subject='wave-c-proof', request_type='topic')); \
print(safe_emit_watch_refresh(run_id=0, phase='start'))"

# 2) Projection includes both spotlights
python3 -c "from scripts.lib.n8n_coordination_projection import project; \
import json; print(json.dumps([s['lane_id'] for s in project()['spotlights']], indent=2))"

# 3) HTTP (served CURRENT)
curl -sS 'http://127.0.0.1:7777/api/v2/coordination/events' | jq '.spotlights[]|.lane_id'
# expect research-intake and/or watch-refresh when sidecars exist
```

## Hermetic tests

```bash
TRADE_AI_CI=1 python3 -m pytest -q \
  tests/test_n8n_cc_wave_c_20261011.py \
  tests/test_advisory_desk_run_now.py \
  tests/test_n8n_run_allowlist_20261008.py \
  tests/test_n8n_cc_wave_b_emit_20261011.py
```

## Host follow-ups (not this PR)

- Set `TRADEAI_N8N_CC_WAVE_C_MODE=dry_run` on CURRENT, confirm ledger REQUESTED→RUN_DONE for the three lanes.
- Flip to `apply` after a controlled canary (still shadow-clamped until stage promote).
- Promote registry stage shadow → canary/cutover when live paid path is intended.
- Add `portfolio-daily-cadence` (etc.) to the runnable allowlist only with a shared lock + dry-run contract before retargeting Ops Run buttons.
- `EXTRA_LANES` / relay live list only if a dispatcher/n8n workflow is later attached (these rows are host on-demand today).

## Do-not-do

- No n8n senders, no broker/order/secret/guard/deploy lanes, no P1 dependency on n8n (§24.1 / §23.14).
- Do not overload `generate-analyst-daily-digest` for ad-hoc prospectus generate.
- Do not invent success from n8n `workflow_entity` status (W0 RC8).
