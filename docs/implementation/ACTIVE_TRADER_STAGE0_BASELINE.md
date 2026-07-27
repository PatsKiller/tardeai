# Active Trader Stage 0 — Baseline

**Packet:** G (`scripts/operator_packets/packet_g_active_trader_stage0.{sh,py}`)  
**Stage:** 0 — baseline inventory + **read-only** health/status scaffolds  
**Program:** `docs/prompts/CODEX_ACTIVE_TRADER_MOOMOO_SCALP_IMPLEMENTATION_v1_1.md`  
**Litmus:** `docs/prompts/ACTIVE_TRADER_ARCHITECT_LITMUS_REVIEW_PROMPT_v1_0.md`  
**Controlling architecture:** v3.3 (session-scoped live authority — **not** activated here)

## Goal (Stage 0 only)

Map what exists today, publish honest gaps, and ship additive **GET-only**
`/api/v3/active-trader/*` stubs that always report:

```json
{ "stage": 0, "write": false, "canary": false }
```

No live orders, no session authorize, no canary, no agent OPERATIONAL, no Moomoo order path.

## What exists today (honest inventory)

| Surface | Status | Notes |
|---------|--------|--------|
| Command Center `/v3` TradingHub | **Live operator UI** | Tabs: Trade AI scanner, Options, Open Trades, Broker Proposals, Entry Desk, Execution, Scalp, ATM, Broker Orders, Schwab Accounts |
| Broker proposals (`paper_trade_proposals` + `/api/v2/broker-proposals/*`) | **Operational paper/promote pipeline** | Human + gate-driven; not Active Trader session envelope |
| Journal (`/api/v2/journal*`, JournalHub) | **Operational closed-trade journal** | Realized P&L, reviews, lessons — not AT session journal |
| Broker orders drafts/preview (`/api/v2/broker-orders/*`) | **Partial** | Preview/drafts/shadow-recon exist; live path is gated and **out of Stage 0** |
| Momentum scalp scanners / regimes | **Operational research path** | Finviz + config under `config/*scalp*`; not AT session canary |
| Moomoo Stage 0 (Packet F) | **Scaffold** | Read-plane foundation only (`docs/operations/MOOMOO_STAGE0_FOUNDATION_v1.md`) |
| Agent runtime SHADOW (Packets D/E) | **SHADOW evidence + promotion gate** | Never OPERATIONAL from those packets |
| `/v3-next` Active Trader workspace | **Missing** | Program Stage 6+ |
| AT session / 2FA / live canary | **Missing** | Stages 7–8, 14 |
| `/api/v3/active-trader/*` (full Stage 4) | **Stage 0 stubs only** | health/status/sessions empty |

## Gaps vs program Stage 0–4

1. No Active Trader session schema or authorization envelope tables (Stage 1).
2. No multi-broker capability registry for AT (Stage 2).
3. No dedicated AT read API for candidates/orders/positions (Stage 4) — only Stage 0 health.
4. No `/v3-next` UI shell (Stage 6).
5. TradingHub Scalp is **not** the Active Trader Next product surface.

## Stage 0 deliverables in this PR

| Artifact | Role |
|----------|------|
| This file | Baseline |
| `ACTIVE_TRADER_ROUTE_API_DB_MAP.md` | Route / API / DB map |
| `ACTIVE_TRADER_CURRENT_GUARDRAILS.md` | Guardrails in force |
| `config/active_trader.stage0.example.yaml` | Feature flags **default OFF** |
| `scripts/active_trader/` | Read-only API + flags |
| `scripts/active_trader_read_boot.py` | Host mount helper |
| Packet G | Prepare-only operator gate |
| Unit tests | flags off; `write:false`; ack required |

## Explicit non-goals

- Stages 1–13 implementation
- Multi-account live trading
- Runner / session 2FA order path
- Live canary (`live_canary` remains false)
- Moomoo order path / trade unlock
- Agent timer enable or OPERATIONAL promotion
- Changing Packet D/E/F behavior

## Acceptance (Stage 0)

- [x] Baseline + route map + guardrails docs committed
- [x] `GET /api/v3/active-trader/health` and `/status` return `stage:0`, `write:false`, `canary:false`
- [x] Sessions list empty without inventing sessions
- [x] All feature flags default OFF in example config
- [x] Packet G default-disabled; missing ack refuses; execute never enables live_canary
- [x] Tests pass without network or live brokers
