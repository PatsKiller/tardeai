# Wave B — CC orchestrate (research-intake + watch-refresh)

```
Status: ACTIVE
as_of: 2026-10-11T15:15:00-04:00
Measured at: code PR on n8nmat/wave-b-research-intake-watch-refresh off origin/main 99027ac72 (#1706)
Canonical repo path: docs/implementation/n8n-maturity/WAVE_B_CC_ORCHESTRATE_2026-10-11.md
Authority: AGENTS.md §23 / §24.1; N8N_VS_COMMAND_CENTER_EVALUATION Wave B; N8N_ONBOARDING_STANDARD.md
Supersedes: none
See also: scripts/lib/n8n_cc_wave_b_emit.py; scripts/lib/n8n_watch_refresh_events.py; apps/command-center-v3 Coordination page
```

## What landed (additive shadow / dry_run first)

1. **Research intake emit** — `POST /api/v2/research-intelligence/run-topic` and CIO `NEED_DATA` call
   `safe_emit_research_intake` (default `TRADEAI_N8N_CC_EMIT_MODE=dry_run`). Host enqueue paths
   unchanged. Consumer remains `n8n-research-intake-consumer`.
2. **Watch refresh lifecycle** — start emit from the API enqueue; terminal emit from
   `_reconcile_run`. Workers stay systemd-run / PG jobs. Lane id `watch-refresh`.
3. **Coordination UI** — Wave B lane filter chips, spotlights panel (shadow + host last.json),
   lane runs table (`?source=runs`), `artifact`/`artifact_ref` + `idempotency_key` on projection.

## Emit modes

| `TRADEAI_N8N_CC_EMIT_MODE` | Behaviour |
|---------------------------|-----------|
| `off` / `0` | no-op |
| `dry_run` (default) | write sidecars + `data/runtime/n8n_cc_wave_b/spotlights.json`; no gateway POST |
| `apply` / `1` | also `accept_event` (fail-soft) |

## Host follow-ups (not this PR)

- Add `watch-refresh` to `TRADEAI_N8N_GATEWAY_EXTRA_LANES` (config-write / service restart) before `apply` sticks.
- Flip emit mode to `apply` on CURRENT after a controlled canary.
- Promote `n8n-research-intake-consumer` health contract DRAFT → REVIEWED (Wave A gate).

## Do-not-do

- No senders, no n8n messaging credentials, no P1 dependency on n8n (§24.1 / §23.14).
- Do not replace watch-refresh workers with n8n spawn.
- Do not invent success from n8n `workflow_entity` status (W0 RC8).
