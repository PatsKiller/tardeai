# Wave B — CC orchestrate (research-intake + watch-refresh)

> **Superseded in part — operator directive 2026-10-15 "N8N Cutover Decision" (decision D11).** All lane families are
> approved for n8n cutover except F07 (long-running daemons and `@reboot` services) and all `registry_systemd` assets,
> which stay on the server unchanged (revisit at the next architecture review). Verbatim: "The rationale that these
> workflows should remain host-side, cron-based, or external due to maturity, reliability, operational risk,
> monitoring requirements, or similar concerns is not accepted as a blocker." "If any existing documentation,
> standards, inventory notes, exception records, or implementation guidance state otherwise, consider that guidance
> superseded." Every keep-on-cron / stay-on-cron / §23.14 / `pipeline_excluded_gate` / STAY_HOST / STAY EXTERNAL /
> "not eligible for n8n" statement in this document is kept as history and is superseded for every non-F07,
> non-`registry_systemd` lane. Current dispositions: `docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.csv`
> (waves CD1-CD6); n8n schedules broker-family lanes but never holds a broker credential or calls an order route
> itself (`docs/architecture/n8n/N8N_REFERENCE_ARCHITECTURE.md` §2a).

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
