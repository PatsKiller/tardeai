# Active Trader Stage 0 — Baseline

Status:      HISTORICAL
as_of:       2026-07-27T12:13:37-04:00
Measured at: efcc51365 / not measured

**Packet:** G (`scripts/operator_packets/packet_g_active_trader_stage0.{sh,py}`)  
**Stage:** 0 — baseline inventory + **read-only** health/status scaffolds  
**Program:** `docs/prompts/CODEX_ACTIVE_TRADER_MOOMOO_SCALP_IMPLEMENTATION_v1_1.md`  
**Litmus:** `docs/prompts/ACTIVE_TRADER_ARCHITECT_LITMUS_REVIEW_PROMPT_v1_0.md`  
**Moomoo data plane:** `docs/operations/MOOMOO_STAGE0_FOUNDATION_v1.md`  
**Controlling architecture:** v3.3 (session-scoped live authority — **not** activated here)  
**Operator product intent recorded:** 2026-07-27

## Goal (Stage 0 only)

Map what exists today, publish honest multi-broker gaps, and ship additive **GET-only**
`/api/v3/active-trader/*` stubs that always report:

```json
{
  "stage": 0,
  "write": false,
  "canary": false,
  "venues": {
    "schwab":  { "data": false, "execution": false, "read_only_inventory": true },
    "moomoo":  { "data": false, "execution": false, "read_only_inventory": true },
    "alpaca":  { "data": false, "execution": false, "read_only_inventory": true }
  }
}
```

Venue flags are **inventory / intent only** at Stage 0 — all false for live data and
execution. No live orders, no session authorize, no canary, no agent OPERATIONAL,
no Moomoo/Alpaca/Schwab place-order wiring.

---

## Product intent (operator-confirmed 2026-07-27)

These are **product requirements for later stages**, not Stage 0 implementation.

### Multi-broker role

| Venue | Role (intent) |
|-------|----------------|
| **Schwab / thinkorswim** | **Primary** execution and account home when the name is electronically eligible |
| **Moomoo** | **Augment** when Schwab compliance blocks electronic entry (low-float / call-broker names); also **Level 2 + time-and-sales** not entitled on Alpaca/Schwab for the scalp path |
| **Alpaca** | **Augment** paper/live-capable alternate when Schwab cannot take the name and Moomoo is not preferred; not a L2/tape substitute |

**Schwab block problem:** Momentum scalp cannot wait on a phone desk when Schwab
marks a security as requiring broker assistance / electronic entry not allowed /
microcap restrictions. Active Trader must be able (in later stages, under session
envelope) to route or fall back to an already-approved Moomoo/Alpaca account —
never invent an unapproved account without a new 2FA / session amendment.

### Desk product (near-ready setups)

- Surface **near-ready** setups, not only classic high-RVOL scanner **GO**.
- May include **building volume/momentum** below default RVOL thresholds / symbols
  **not** on the main Trade AI GO list.
- Operator **opts in**: chooses share size + per-account allocation.
- Then (stages 1+ under session authority) system may manage entry/exit:
  buy/sell limit, sell market, flatten.
- Entry bias (later stages): first candle breaking pullback + gates.
- **Explicitly NOT** unattended discover-and-fire without opt-in.

Stage 0 only **documents** this intent. No managed lifecycle code, no order path.

---

## What exists today (honest inventory)

| Surface | Status | Notes |
|---------|--------|--------|
| Command Center `/v3` TradingHub | **Live operator UI** | Tabs: Trade AI, Options, Open Trades, Broker Proposals, Entry Desk, Execution, **Scalp**, ATM, Broker Orders, Schwab Accounts |
| TradingHub **Scalp** tab | **Research / scanner desk** | High-RVOL / Finviz-adjacent GO path — **not** the multi-broker AT opt-in product |
| Broker proposals (`paper_trade_proposals` + `/api/v2/broker-proposals/*`) | **Operational paper/promote** | Human + gate-driven; not AT session envelope |
| Journal (`/api/v2/journal*`, JournalHub) | **Operational closed-trade journal** | Realized P&L / reviews — not AT session journal |
| Broker orders drafts/preview (`/api/v2/broker-orders/*`) | **Partial** | Preview/drafts/shadow-recon; live path gated; **out of Stage 0** |
| **Alpaca paper** paths | **Partial operational** | Paper reconciler / paper proposals exist; not AT multi-venue session |
| **Schwab** transport + pilot stack | **Gated live pilot** | Write boundary + 2FA/readiness — not AT Stage 0 |
| **Moomoo Stage 0** (Packet F) | **Read-plane scaffold** | Config + fail-closed client + preflight; **no** order path / unlock |
| Agent runtime SHADOW (Packets D/E) | **SHADOW evidence + promotion gate** | Never OPERATIONAL from those packets |
| `/v3-next` Active Trader workspace | **Missing** | Program Stage 6+ |
| AT session / opt-in / 2FA / live canary | **Missing** | Stages 7–8, 14 |
| `/api/v3/active-trader/*` full Stage 4 | **Stage 0 stubs only** | health/status/sessions empty |

## Multi-broker matrix (Stage 0 inventory — not wired)

| Venue | Market data (today) | Execution (today) | AT Stage 0 flag |
|-------|---------------------|-------------------|-----------------|
| Schwab/TOS | Quotes via existing market path; L2 limited by entitlement | Gated pilot / human desks | `venues.schwab.*` all false for live |
| Moomoo | Stage 0 OpenD **data** scaffold only | **None** (order path OUT) | `venues.moomoo.*` false |
| Alpaca | Paper/live quote APIs elsewhere | Paper + restricted live elsewhere | `venues.alpaca.*` false |

**Data vs execution:** Moomoo is first-class for **L2/tape** in product intent; Schwab
remains primary for **compliant electronic execution** when allowed; Alpaca augments
execution when Schwab blocks and policy allows.

## Operator opt-in → managed lifecycle (named only; not implemented)

Future stages (not this PR) must implement, under session envelope:

1. Operator selects near-ready setup + **opt-in** size + account allocation  
2. Session authorize (2FA / envelope)  
3. Managed entry (pullback break + gates) / exit (limit, market sell, flatten)  
4. Venue selection: Schwab primary; Moomoo/Alpaca only if bound into envelope  
5. Journal + Darwin feedback  

Stage 0 **does not** implement any of the above.

## Gaps vs program Stage 0–4

1. No Active Trader session schema or authorization envelope (Stage 1).  
2. No multi-broker capability registry for AT (Stage 2).  
3. No dedicated AT read API for candidates/orders/positions (Stage 4) — only Stage 0 health.  
4. No `/v3-next` UI shell (Stage 6).  
5. TradingHub Scalp is **not** the Active Trader Next product surface.  
6. No near-ready / below-RVOL candidate projection for AT.

## Stage 0 deliverables in this PR

| Artifact | Role |
|----------|------|
| This file | Baseline + multi-broker product intent |
| `ACTIVE_TRADER_ROUTE_API_DB_MAP.md` | Route / API / DB map |
| `ACTIVE_TRADER_CURRENT_GUARDRAILS.md` | Guardrails in force |
| `config/active_trader.stage0.example.yaml` | Feature flags **default OFF** |
| `scripts/active_trader/` | Read-only API + flags + venues inventory |
| `scripts/active_trader_read_boot.py` | Host mount helper |
| Packet G | Prepare-only operator gate |
| Unit tests | flags off; `write:false`; venues present; ack required |

## Explicit non-goals

- Stages 1–13 implementation  
- Order placement on **any** venue (Schwab / Moomoo / Alpaca)  
- Session authorize / 2FA live path  
- Live canary (`live_canary` remains false)  
- OpenD trade unlock  
- Agent timer enable or OPERATIONAL promotion  
- Unattended discover-and-fire  
- Changing Packet D/E/F behavior (except scanner-safe probes if needed for CI)

## Acceptance (Stage 0)

- [x] Baseline + multi-broker matrix + opt-in intent documented  
- [x] Route map + guardrails docs committed  
- [x] `GET /api/v3/active-trader/health` returns `stage:0`, `write:false`, `canary:false`, `venues` read-only inventory  
- [x] Sessions list empty without inventing sessions  
- [x] All feature flags default OFF in example config  
- [x] Packet G default-disabled; missing ack refuses; execute never enables live_canary  
- [x] Tests pass without network or live brokers  
