# Options & Broker Execution Flows

Trade AI v12 closed-loop design for automatic vs manual broker execution.

> **Equity proposals (same two-path model):** see `docs/PROPOSAL_EXECUTION_PATHS.md`
> — **Path A** paper auto (Alpaca testing) vs **Path B** live Schwab 2FA auto / Fidelity FA manual.

## Options Desk (`/v3/trading` → Options tab)

### What generates proposals

`scripts/options_engine.py` scans:

- **Schwab + Fidelity holdings** from `data/portfolios/state/holdings.json` (normalized `price` / `current_price`)
- Schwab option chain (live) with **Black-Scholes fallback** when chain is thin
- Portfolio intent sleeve (V, SCHD, LMT) and Aegis screening

### Strategy types

| Strategy | Description | Typical account |
|----------|-------------|---------------|
| `covered_call` | Income on owned stock (≥100 shares) | Schwab or Fidelity |
| `cash_secured_put` | Short put funded by account cash | Fidelity (SPAXX) / Schwab |
| `protective_put` | Long put hedge on large positions (≥$15k) | Any manual sleeve |
| `long_call` / `credit_spread` | High-conviction defined risk | Schwab auto path |

### Execution labels

Each proposal carries:

- `broker` — `schwab` | `fidelity`
- `execution_mode` — `auto_or_manual` | `manual`
- `execution_label` — e.g. `Manual · Fidelity` or `Schwab · auto or manual`
- `auto_eligible` — `true` only for Schwab (options pilot + 2FA)

**Fidelity** proposals always show `Manual · Fidelity` — execute at the broker, then log via **Executed manually**.

### Quality gates

- Default: edge ≥62, POP ≥52%, IV rank ≥20
- **Manual/Fidelity holdings**: relaxed IV floor (12) and edge floor (52) — still turnkey, no junk
- Income-sleeve names (portfolio_intent): edge floor 52

## Broker Proposals (`/v3/trading` → Broker Proposals tab)

Unified live queue for Schwab + Fidelity equity proposals from `paper_trade_proposals`.
**Full UI guide:** `docs/BROKER_PROPOSALS_UI.md`

### Card layout (2026-06-23 redesign)

- **Thesis validity bar** — visual drift gap (green/yellow/red) from `broker_thesis_validity.py`
- **Account picker** — Schwab (auto+manual) vs Fidelity (FA manual only) with cash/slot preview
- **↻ Refresh prices** — `POST /api/v2/broker-proposals/refresh-prices` (quote + recalibrate sizing)
- **AI oversight** — Queue local reviews · **Run Grok+ChatGPT** (per-lane verdicts + consensus)
- **Actions** — Executed manually · Edit trade · Auto route (2FA) / Record (Fidelity)

### Account selection

Grouped destination picker per row:

- **Charles Schwab** — **Auto route (2FA)** when pilot armed, or **Executed manually**
- **Fidelity** — **Active Trader Pro (FA)** manual only → **Executed manually** to close the loop

### Manual adjustment modal

**Executed manually** opens a modal pre-filled from:

`POST /api/v2/broker-proposals/prepare-manual`

Editable fields:

- Shares / contracts
- Entry, stop, target (equity)
- Strike, expiration, premium (options)
- Risk:reward
- Origin link (watchlist / watchpool / proposal)

Submit logs via:

`POST /api/v2/executions/log-manual`

## Closed-loop tracking

`scripts/manual_execution_tracker.py` + `manual_execution_log` table.

### Auto-tagging priority

1. Options proposal (exact ID from modal)
2. Equity proposal (`paper_trade_proposals`)
3. Watchpool (`strategy_watchpool`)
4. Watchlist (`watchlist_items`)
5. Directive (`watch_directives`)

### What gets updated

- `manual_execution_log` — audit row with origin + adjusted params
- `lifecycle_events` — `manual_execution_logged` event
- `rec_ticker_attribution.executed` — learning loop flag

### Options-specific log

`POST /api/v2/options/executions/log-manual` — same tracker, `execution_type=option`.

### Metrics (Health Agent)

`GET /api/v2/executions/tracking-metrics`

Monitored by `health_agent.py` → `collect_proposal_maturity()`:

- `manual_tagging_failing` — untagged manual trades
- `proposal_conversion_low` — good broker proposals ignored
- `options_proposals_ignored` — quality options not logged

## Operator quick reference

1. **Options on Fidelity holdings** → Options Desk → Force scan → pick proposal → execute at Fidelity → **Executed manually**
2. **Equity from system proposal** → Broker Proposals → choose account → **Executed manually** (or Schwab Auto 2FA)
3. **Quick log without modal** → Broker Proposals → **Executed manually** on any row

## API summary

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v2/options/proposals` | GET | Options proposals (filters: strategy, min_pop, min_edge) |
| `/api/v2/broker-proposals` | GET | Schwab/Fidelity queue + account metadata |
| `/api/v2/broker-proposals/refresh-prices` | POST | Live quote + thesis band + sizing recalc |
| `/api/v2/broker-proposals/run-cloud-oversight` | POST | Grok+ChatGPT second opinion |
| `/api/v2/broker-proposals/queue-oversight` | POST | Queue local agent + LLM reviews |
| `/api/v2/broker-proposals/prepare-manual` | POST | Pre-fill adjustment modal |
| `/api/v2/executions/log-manual` | POST | Log equity manual execution + tagging |
| `/api/v2/options/executions/log-manual` | POST | Log options manual execution |
| `/api/v2/executions/tracking-metrics` | GET | Conversion + tagging stats |

## Migration

Apply: `migrations/20260622_manual_execution_lineage.sql`