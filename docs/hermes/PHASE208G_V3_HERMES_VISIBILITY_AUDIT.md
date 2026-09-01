# Phase 208G — v3 Hermes Visibility Audit (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T11:33:46-04:00
Measured at: efcc51365 / not measured

## What v3 already shows (good)
- **System → Hermes** (HermesPanel): global profiles (model/tools/status/purpose), View/Edit SOUL,
  terminal commands, Codex-dev readiness, gateway disabled warning, **Legacy/Retired Agents** section
  (`/api/v2/hermes/legacy-agents`, 24 items, read-only, explicit "no enable/run/edit · secrets redacted").
- **/v3/hermes** (HermesHub): live research-fleet graph (7 agents) + SearXNG/Trade-AI-safe-views + infra
  health strip; relabeled "Hermes Research Agent Graph" with two-layer note.

## Gaps identified
1. Profile rows expose `soul_exists`/`soul_bytes` but **not SOUL hash or last-modified** → no SOUL provenance
   at a glance. (LOW-RISK fix in 208H.)
2. The System→Hermes panel does not surface research-fleet last-run/health (that lives on the /v3/hermes
   graph). Acceptable (separation of layers), but a cross-link helps.
3. No explicit "retired-dependency-proof" badge — mitigated: legacy section already states read-only/no-run.

## Decision
Apply only the low-risk SOUL-provenance fix (208H): add `soul_hash` + `soul_mtime` to profiles-status and
render them in the profile rows. No model/tool/schedule/trading changes. Fleet health stays on the graph.
