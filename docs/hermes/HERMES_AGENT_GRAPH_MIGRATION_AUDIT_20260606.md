# Hermes Agent Graph vs Global Profiles — Reconciliation Audit — 2026-06-06

Status:      HISTORICAL
as_of:       2026-06-07T00:03:46-04:00
Measured at: efcc51365 / not measured

## Summary
Two distinct Hermes layers coexist and BOTH are kept. The `/v3/hermes` page is the **Research Agent Graph**
(Trade AI research-workflow layer); **System → Hermes** is the **Global Hermes Profile** management panel.
They are separate subsystems — not merged, not duplicates.

## Old research-agent graph inventory (`/v3/hermes`, HermesHub.tsx)
Chief Hermes Coordinator · Source Discovery · Hermes Librarian · Embedded Curator · Promotion Review ·
Research Backlog Manager · Autonomous Research Manager. Depends on SearXNG (source discovery) + Trade AI
**safe views** (read-only; the WALL). Writes hermes_* staging tables; advisory/RAG only.

## New global profile inventory (System → Hermes)
default · tradeai · tradeai12b · dev · serverops (see HERMES_PROFILE_MATRIX / COMMAND_CENTER_PANEL docs).

## What migrated / what did NOT
- The CLI/chat assistant (sidecar → global install + profiles) migrated — that was the v1.8 work.
- The research-agent GRAPH did **NOT** migrate into profiles — it is a separate, still-active Trade AI
  subsystem. It runs on the project `.venv` + `scripts/hermes_*.py` via **systemd user timers**
  (hermes-autonomous-loop, hermes-source-discovery-dryrun, hermes-librarian-backlog-loop,
  hermes-embedding-promotion-review, hermes-backlog-health-check, hermes-shadow-scorer,
  hermes-observation-check, hermes-advisory-cache-worker, hermes-momentum-catalyst-morning).

## Sidecar / gateway dependency findings
- The research graph does **NOT** depend on the retired sidecar install (`hermes_sidecar/install`) or on
  `hermes-gateway.service` — its timers invoke `.venv/bin/python scripts/hermes_*.py` directly.
- **Stale reference (finding, not fixed here):** the Coordinator's kill-switch is documented/checked as
  `touch hermes_sidecar/.hermes/DISABLED`, but `.hermes` was rename-retired in v1.8, so that path is now
  stale. Recommend repointing the coordinator kill-switch to a live path (e.g. `data/runtime/HERMES_DISABLED`
  or `~/.hermes/DISABLED`) in a separate, operator-approved change. Out of scope for this reconciliation.

## Scheduler / process findings
- Research timers are enabled and `waiting` (active subsystem). No dependency on retired sidecar/gateway.
- No live sidecar gateway process; operator chat sessions untouched.

## SearXNG diagnosis
- Actual state: **UP** — `curl http://127.0.0.1:18888/` returns SearXNG HTML (searxng/2026.5.31), port
  listening, container "Up 6 days".
- The `/v3/hermes` graph reads SearXNG status from `/api/v2/hermes/infra` (`_ping` HTTP GET, 200-499 = up),
  which returns **up**. The operator's earlier "DOWN" was a stale/transient reading (served dist predating a
  fix or a transient `_ping` timeout).

## SearXNG UI fix applied
- Hardened the infra `_ping` for SearXNG (timeout 3s → 6s) to avoid false-DOWN under transient load; HTTP
  health remains the source of truth. Rebuilt the v3 frontend so the served UI reflects current status.
- Verified live: infra endpoint → SearXNG `up`.

## Decision: keep BOTH layers visible
- `/v3/hermes` relabeled to **"Hermes Research Agent Graph"** with a note clarifying it is the research-
  workflow layer, separate from the global Hermes profile/chat layer (managed under System → Hermes), and
  that it runs on project scripts/timers independent of the retired sidecar.

## Recommended next steps (operator-gated, separate)
1. Repoint the Coordinator kill-switch off the retired `hermes_sidecar/.hermes/DISABLED` path.
2. (Optional) relabel the infra strip "Hermes Gateway" node to clarify it's the retired sidecar gateway
   (correctly down; the research graph does not need it).

## Safety
Read-only diagnosis + UI label + ping timeout change + doc. No Docker/service restart or enable; no gateway/
Telegram/Discord/Codex/cron/systemd enablement; no broker/trading/secrets touched; no graph code deleted.

## Kill-switch repoint (2026-06-06)
The live Research Agent Graph / Coordinator kill-switch was repointed from the retired
`hermes_sidecar/.hermes/DISABLED` (and the non-canonical `~/.hermes/DISABLED`) to the canonical live
path **`data/runtime/HERMES_DISABLED`** across all 7 live readers, the Command Center API/UI, and the
coordinator cron comment. `touch data/runtime/HERMES_DISABLED` halts the fleet next tick; `rm` resumes.
See `HERMES_RESEARCH_GRAPH_KILL_SWITCH_REPOINT_20260606.md`.
