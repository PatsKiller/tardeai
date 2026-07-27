# Active Trader — Route / API / DB map (Stage 0 inventory)

Honest map of **current** production surfaces vs **Active Trader Next** targets.
Stage 0 does not replace `/v3` TradingHub.

## UI routes (Command Center)

| Path | Component | Relation to Active Trader |
|------|-----------|---------------------------|
| `/v3` → `trading` | `TradingHub.tsx` | Existing scalp/proposals desk — **not** AT session UI |
| `/v3` → `journal` | `JournalHub` | Closed-trade journal — separate from AT session journal |
| `/v3-next` | *(absent)* | Program target Stage 6+ |
| `/api/v3/active-trader/*` | Stage 0 stubs | This PR — health/status/sessions only |

### TradingHub tabs (existing)

`Trade AI` · `Options` · `Open Trades` · `Proposals` · `Entry Desk` · `Execution` ·
`Broker Recon` · `Scalp` · `ATM Controls` · `Broker Orders` · `Schwab Accounts`

## API surfaces

### Stage 0 (this PR) — GET only

| Method | Path | Behavior |
|--------|------|----------|
| GET | `/api/v3/active-trader/health` | `{ stage:0, write:false, canary:false, ... }` |
| GET | `/api/v3/active-trader/status` | Same stage flags + feature flag snapshot (all off) |
| GET | `/api/v3/active-trader/sessions` | `{ sessions: [] }` until Stage 1 schema |
| * | other methods on prefix | **405** — never mutate |

Contract: `active-trader-stage0-read-api-v1`  
Code: `scripts/active_trader/read_http.py` · mount via `scripts/active_trader_read_boot.py` in `portfolio_server.py`

### Existing operator APIs (not AT Stage 0)

| Prefix | Examples | DB / notes |
|--------|----------|------------|
| `/api/v2/broker-proposals/*` | list, detail, promote-from-paper, oversight | `paper_trade_proposals` |
| `/api/v2/broker-orders/*` | preview, drafts, shadow-recon, pilot status | intents/events tables; live order I/O gated |
| `/api/v2/broker-accounts/*` | list, readiness, automation-policy | account registry |
| `/api/v2/journal/*` | closed trades, reviews, analytics | `trade_closed`, review tables |
| `/api/v2/stops/*` | management, lifecycle, reentry-watch | protective stops |
| `/api/v3/agent-runtime/*` | runs/artifacts/reviews (GET) | isolated `agentic_runtime` schema |
| `/api/health` | process health | unrelated to AT stage flags |

## Database (relevant today)

| Table / schema | Used by | AT Stage 0 |
|----------------|---------|------------|
| `paper_trade_proposals` | Broker Proposals UI | Read inventory only — no AT session FK |
| `trade_closed` + journal review tables | JournalHub | Not AT session journal |
| Broker order intent / event tables | Broker Orders desk | Out of Stage 0 write path |
| `agentic_runtime.*` | Agent SHADOW evidence | Separate promotion gate (Packet E) |
| AT session / authorization tables | *(not present)* | Stage 1+ |

## Feature flags

Example: `config/active_trader.stage0.example.yaml`

| Flag | Default | Stage 0 |
|------|---------|---------|
| `active_trader_ui` | false | off |
| `session_builder` | false | off |
| `session_authorize` | false | off |
| `live_canary` | false | **must stay false** |
| `order_routes` | false | off |
| `moomoo_order_path` | false | off |
| `multi_account_live` | false | off |
| `runner` | false | off |

## Packet G registration

On `--execute` + ack `APPLY-AT-STAGE0`, Packet G may write a **docs checksum + read flags**
record under `docs/implementation/active_trader_stage0_registry.json` only.
It must never set `live_canary: true` or enable order routes.
