# Command Center v3 — Watchlist Hub

_Last updated 2026-07-03. Route: `/v3/watch`. HEAD: `ee0e14d1`._

Decision-first watchlist: one full-width card per symbol with CIO view, plan levels, data-quality
flags, and a unified verdict → CTA matrix. Operators can propose entries directly from a card
without waiting for the cron bridge.

## UI layout

**Page:** `apps/command-center-v3/src/pages/WatchlistHub.tsx`

**Card:** `apps/command-center-v3/src/components/WatchlistCard.tsx` — single-column rows (not a
2-column grid). Each card shows:

| Zone | Content |
|------|---------|
| Header | Star, symbol, `ProAnalystPill`, CIO pill + confidence, verdict chip, price |
| DATA strip | Stale technicals, advisory caution, low CIO conf, enrichment age, agents pending, no live price |
| Hero | Action text, one-line reasoning, plan line (limit/stop/target/zone), R:R badge |
| CTAs | Primary + secondary (e.g. Propose + Monitor; Review setup + Refresh) |
| Plan grid | Limit, stop, target, pullback zone, R:R, model, exit vs Street |
| Fib | `FibConfluencePanel` lazy-loaded on card (pullback confluence visible by default) |
| More | Finviz strip, sector, catalyst, news (expandable) |

Pullback entry levels (`entry_zone_low` / `entry_zone_hi`, setup type) are on the default view —
not hidden under "More".

## Decision matrix

Logic lives in `apps/command-center-v3/src/lib/watchlistCardAction.ts` (`deriveRecommendedAction`).

Verdicts: `READY` · `WAIT` · `SKIP` · `STALE` · `FIX` · `BUILD` · `WATCH`

| Condition (priority order) | Verdict | Primary CTA |
|----------------------------|---------|-------------|
| Private / non-tradeable | SKIP | View intel |
| No stop on plan | FIX | Fix plan |
| Stale technicals + plan exists | STALE | Refresh |
| CIO AVOID / SELL / TRIM | SKIP | View intel |
| R:R &lt; 1.0 | FIX | Fix plan |
| R:R &lt; 1.5 | FIX | Fix plan |
| Plan target below Street | FIX | Review exit |
| Advisory caution (no plan) | WAIT | Review |
| Advisory caution (plan on file) | WAIT | Review setup |
| CIO conf &lt; 0.5 | WAIT | Review setup |
| `entry_urgency` ready / near_entry + plan | READY | **Propose** |
| Enriched, no plan | BUILD | Build |
| Not enriched | STALE | Refresh |
| Plan + entry, awaiting trigger | WATCH | Desk |
| Default | WAIT | Review setup |

**Secondary CTA** (`deriveSecondaryAction`): WAIT/SKIP/WATCH with plan → Monitor; intel/review
states → Refresh; otherwise Intel.

**Sizing hint** (`riskSizingHint`): when plan validated and R:R ≥ 1.5, shows "1–2% of available
cash sizing" on READY and WAIT cards.

**Data-quality flags** (`dataQualityFlags`): data doubt, awaiting enrichment, stale technicals,
enrichment age, agents pending, CIO synthesis pending, advisory caution, low CIO conf, no live price.

**Reasoning line** (`actionReasoning`): CIO vs Street divergence, Hermes rank, advisory note,
plan/R:R state, synthesis snippet.

## Propose Entry modal

**Component:** `apps/command-center-v3/src/components/WatchlistProposeModal.tsx`

Opened from card primary CTA when verdict is `READY` (`PROPOSE_ENTRY`). Sizes on **available cash /
buying power**, not total account equity.

### Sizing math

`apps/command-center-v3/src/lib/watchlistProposeSizing.ts`:

```
risk budget = sizing_base × risk%     (1% or 2%)
shares      = floor(budget ÷ (entry − stop))
shares      = min(shares, floor(sizing_base ÷ entry))   # cash cap
```

- **Taxable Schwab:** `sizing_base` = settled cash (falls back to buying power).
- **Retirement (IRA / Roth / Rollover):** cash only — margin / buying power ignored
  (`resolveSizingBase` hard guard).
- **Fidelity:** cash from holdings snapshot (`SPAXX`, sweep positions).

Modal shows explicit breakdown: `% × cash = risk budget`, shares from stop distance, actual
`% of cash` and `% of equity` (reference only). Warns when investment exceeds cash; requires
`confirm_over_cash` on submit.

### Accounts API

`GET /api/v2/proposal-accounts` (30s server cache)

Merges `broker_accounts` + `holdings.json` summaries so Schwab and Fidelity destinations appear
even when Schwab live API is stale. Each row:

| Field | Meaning |
|-------|---------|
| `account_key` | e.g. `schwab_rollover_ira`, `fidelity_rollover_ira` |
| `display_name` | Human label |
| `account_type` | Taxable, Rollover IRA, Roth IRA, … |
| `is_retirement` | Cash-only sizing |
| `cash` | Settled cash |
| `buying_power` | Schwab buying power (taxable) |
| `account_value` | Total equity (reference % only) |
| `sizing_base` | **Base for risk %** — cash or buying power |
| `sizing_ready` | `true` when `sizing_base > 0` |

**Example (DXCM @ $67.80, stop $66, Schwab Rollover IRA):**

| Base | 1% risk budget | Shares |
|------|----------------|--------|
| Cash ~$29,340 (correct) | ~$293 | ~163 |
| Equity ~$584k (old bug) | ~$5,845 | ~3,247 |

### Submit

`POST /api/v2/watchlist/<SYMBOL>/propose`

Body: `account`, `shares`, `entry`, `stop`, `target`, `risk_pct`, optional `confirm_over_risk`,
`confirm_over_cash`.

Backend (`_wl_propose_symbol` in `scripts/api_v2.py`) validates:

- 2% cap on **cash** risk (`confirm_over_risk` to override)
- Investment ≤ available cash (`confirm_over_cash` to override)
- Falls back to equity % only when cash base unavailable

Promotes via `entry_desk_ops.promote_to_broker_queue` with `source=watchlist_card`.

## Backend modules

| Module | Role |
|--------|------|
| `scripts/api_v2.py` | `_proposal_accounts`, `_wl_propose_symbol`, watchlist items |
| `scripts/account_policy.py` | `cash_for_account`, `sizing_cash_base`, `is_retirement_account` |
| `scripts/watchlist_proposal_bridge.py` | Cron dual-lane sync (separate path — see bridge doc) |

## Operator notes

**Restart after `account_policy.py` changes.** A long-running portfolio server may serve stale
Python modules. Symptom: `GET /api/v2/proposal-accounts` returns
`module 'account_policy' has no attribute 'sizing_cash_base'`.

```bash
systemctl --user restart portfolio-server.service
curl -s http://127.0.0.1:8765/api/v2/proposal-accounts | jq '.accounts[] | {account_key, sizing_base}'
```

**Frontend:** rebuild `apps/command-center-v3` and hard-refresh the browser after UI changes.

## Tests

```bash
.venv/bin/python -m pytest tests/test_watchlist_propose_sizing.py -q
```

## Related docs

- `docs/WATCHLIST_PROPOSAL_BRIDGE.md` — cron bridge to broker queue (BUY+ ratings)
- `docs/PEER_REVIEW_PACKET_COMMAND_CENTER_PAGES.md` — §5 Watchlist peer-review section
- `docs/BROKER_TRADE_PLAN_GATE.md` — authoritative plan enforcement

## Recent commits (2026-07-02 — 2026-07-03)

- `ee0e14d1` — Stronger CTAs, DATA strip, sizing hints on WAIT cards
- `caad93ad` — Explicit cash-based sizing math + IRA cash-only guard
- `25e9c27e` — Cash sizing + working account load + Schwab/Fidelity cash fallback
- `ee225be5` — Decision-first cards: CIO, reasoning, R:R, data quality
- `9aa8119c` — Restore pullback zone, plan line, Fib confluence on cards
- `2ac2d7ad` — Rich single-column cards with intel visible by default
- `bd642190` — Propose modal: size on available cash, include Fidelity accounts