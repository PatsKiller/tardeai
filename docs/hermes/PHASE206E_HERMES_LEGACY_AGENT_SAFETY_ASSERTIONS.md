# Phase 206E — Hermes Legacy Agent Safety Assertions — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T10:33:09-04:00
Measured at: efcc51365 / not measured

The read-only legacy-agent visibility (206B–206D) holds every safety boundary. Each assertion below is
enforced by construction and verified.

| # | Assertion | How enforced | Verified |
|---|-----------|--------------|----------|
| 1 | Gateway service remains **disabled** | Nothing in 206B–D starts/enables it; endpoint only *reads* `is-active/is-enabled` | `failed / disabled` (live) |
| 2 | Retired sidecar gateway remains **disabled** | No retired wrapper/gateway invoked anywhere | retired dirs untouched |
| 3 | **No** retired wrapper path executable from UI | UI renders text only; `actions_available=[]`; no POST route | endpoint + UI reviewed |
| 4 | **No** POST/action for retired agents | `/api/v2/hermes/legacy-agents` is GET-only; no enable/run/edit handler added | route table |
| 5 | tradeai/tradeai12b safety-critical tools remain **disabled** | Not touched; `disabled_toolsets:[x_search]` + all toolsets off unchanged | profiles-status: disabled |
| 6 | dev/serverops remain unconfigured / human-invoked | Not touched | profiles-status unchanged |
| 7 | Codex remains operator-interactive only | Not touched; no OAuth/token handling added | codex-dev-status unchanged |
| 8 | Inventory is **read-only** | Script never executes wrappers/services; writes only its JSON | header guarantees + run |
| 9 | **No secrets** exposed | SOUL/config scanned for non-secret fields; secret lines redacted; runtime-state contents not read | 0 real values in payload |
| 10 | Retired dirs **unchanged** | Only stat/read of text files; no writes into retired dirs | mtimes unchanged |

## Out of scope (explicitly NOT done)
No runtime re-enable, no migration/rebuild of legacy agents, no tool enablement on any active profile,
no Codex auto-config, no v2 UI, no trading/proposal/protection/broker/holdings changes, no live trading,
Level 7 prohibited.
