# Stage 6 Plan — /v3-next Read-Only Active Trader Workspace

**Run ID:** 20260722-01 · Controller: Stages 6–11 · Start HEAD: 5c8bc5af (device-auth tooling
commit; one ahead of the launcher's 69285d4e, explained). **Moomoo lockout honored** — no
login, no live data; fixtures only.

## Approach
Separate Vite+React bundle `apps/command-center-v3-next` (base `/v3-next/`, dev port 7790,
loopback), independent of `command-center-v3` (`/v3` untouched). Panels consume a fixtures
module shaped to the Stage 4 read contract. Every action control is disabled and issues no
write. Moomoo shows OFFLINE_IMPLEMENTED / CREDENTIAL_GATE_BLOCKED / LIVE_DATA_UNAVAILABLE with
no green/live badge. L2/tape/marks render explicit UNAVAILABLE (never fabricated).

## Deliverables
18-panel workspace (nav, session strip, prime queue, symbol selector, pre-trade/working/
in-trade tickets, P&L, chart, L2, tape, accounts, brokers, capabilities, rejections,
notifications, journal, read-only feature modal, parity/status). Vitest suite. Production
build. 7 artifacts.

## Non-goals
No TradingHub change; no /v3 change; no Stage 4 API mount into production; no write plane
(that is Stage 7, dev-only). No live Moomoo anything.
