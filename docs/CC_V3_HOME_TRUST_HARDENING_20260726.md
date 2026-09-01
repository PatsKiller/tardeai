# CC v3 Home Trust Hardening — 2026-07-26

Status:      ACTIVE
as_of:       2026-07-26T15:33:45-04:00
Measured at: efcc51365 / not measured

**Branch:** `grok/home-trust-harden-20260726` (owned isolation lane — does not collide with Watch/Defense/Agent PRs)

## Problem statement (operator Home snapshot)

| Surface | Symptom | Root cause |
|---------|---------|------------|
| Morning Synthesis | `. **##. **##…` spam | Corrupt gemma output cached without quality gate |
| Market Movers | All chips 0 · "no rows" | Weekend/RTH-idle capture presented as live empty board |
| SETUPS | 0 GO · 0 WAIT · 0 NOGO | Last scan Jul 23; zeros read as "no opportunities" |
| Unprotected | Gauge 11 vs briefing 7 | LLM prompt used a different count source |
| YOUR BOOK | holdings.json Jul 24 vs prices Jul 26 | Snapshot lag unlabeled |
| Hermes Gateway | Red "offline" | **By design** — not an outage |

## Hermes gateway investigation

**Verdict: not a false positive of systemd status; it is intentionally disabled.**

Evidence (`docs/hermes/PHASE208D_HERMES_JOB_CALL_GRAPH.md`, PHASE208I audit):

- `hermes-gateway.service` → `is-enabled = disabled`, often `active=failed`
- **No active/scheduled research job depends on the gateway**
- Research fleet runs via **project `.venv` + `scripts/hermes_*.py` + systemd user timers** (autonomous-loop, source-discovery, librarian, embedding-promotion, backlog-health, shadow-scorer, observation-check, advisory-cache, momentum-catalyst)
- Gateway unit still points at retired sidecar `hermes_sidecar/install` — retained as audit artifact only

**Do not "fix" by enabling the gateway** unless an operator-approved plan reintroduces the sidecar. Enabling it can wake retired paths.

**Home presentation rule:** when autonomous loop is ON and research is staging, show Gateway as **disabled (by design — fleet via timers)** in neutral/amber, not red outage. CTA → System → Hermes for the profile/legacy inventory, not a restart button.

## Changes on this branch

1. **`scripts/llm_content_quality.py`** — fail-closed prose validator
2. **`scripts/llm_intelligence_enrichment.py`** — free local Ollama first; reject bad prose; keep prior good cache; unprotected count from `risk_management.json` only
3. **`MarketMoversBoard.tsx`** — empty-state taxonomy: weekend / premarket / afterhours / capture_failed / empty_rth
4. **`BookTreemap.tsx`** — amber lag hint when `as_of` is behind calendar day
5. **`homeLabels.ts`** — `isScanStale`, `isValidBriefingProse`, `briefingProse`, extra `plainAlert` rules
6. **`healthCta.ts`** — release manifest / unlinked trade / hermes gateway routes
7. **`HomeHub.tsx`** — STALE setup state, synthesis filter, Hermes gateway label, thin equity note

## Operator follow-ups (not blocked on this PR)

- Re-run `llm_intelligence_enrichment.py --section morning_synthesis` after deploy to replace corrupt cache (or delete bad row and wait for next 7:20 weekday cron)
- Align `holdings.json` write cadence with overview repricer so Book lag stays 0 most days
- Metrics-history backfill if equity curve stays &lt;10 days
- Clear release-manifest FAIL + link the unlinked 7d trade through Proposals (process, not UI)

## Safety

Advisory/visibility only. No broker, order, stop, proposal, or GO/WAIT mutation.
