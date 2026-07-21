# Command Center v3 — Watchlist Hub

_Last updated 2026-07-21 (operator decision card + RTH few-hour plan refresh). Route: `/v3/watch`._

Decision-first watchlist: one full-width card per symbol with CIO view, plan levels, data-quality
flags, and a unified verdict → CTA matrix. Operators can propose entries directly from a card
without waiting for the cron bridge.

**Decision packet surface (2026-07-21):** the primary strategy readout is the **operator card**
(`DecisionPacketBand` + `operatorDecisionCard.ts`) — one state, one CTA, built timestamp/age,
Details for audit. Canonical architecture:
`docs/architecture/DECISION_PACKET_OPERATOR_CARD_AND_RTH_REFRESH.md`.

## UI layout

**Page:** `apps/command-center-v3/src/pages/WatchlistHub.tsx`

**Card:** `apps/command-center-v3/src/components/WatchlistCard.tsx` — **Security Card v2**: one
elevated surface with hairline-divided full-bleed rows (no boxes-in-boxes panels). The status
banner is the only tinted element; the primary button the only solid one. Color = signal only
(teal actionable / amber caution / red defect / green price numerals). Tokens:
`apps/command-center-v3/src/lib/watchlistCardTokens.ts`. Zones top→bottom:

| Zone | Content | Default |
|------|---------|---------|
| ① Header (1 line) | Star, symbol, HELD chip, colored Street rating pill, CIO ≠ Street note, provenance (company · Hermes # · origin · sector · on-watchlist tenure), price/change, quiet Refresh | visible |
| ② Status banner (1 line) | Verdict word · headline · ellipsized why (full on hover) · R:R chip · primary CTA · one quiet secondary · ••• menu — the only tinted element | visible, dominant |
| ③ Trade plan ⟷ Sizing (2-col grid ≥1100px) | LEFT: L/S/T/R:R numerals + zone/%/R sub-captions, Entry thesis line, one-line T1/T2/T3 ladder + core rule ("Plan detail" expander). RIGHT: `SizingTable` — per-account shares/invest/risk-$/%cash at 1%|2% toggle, cash-cap ⚠, insufficient-cash states, held-position footer, "size ▸" → Propose modal pre-filled (READY states only); Deploy column (capital ≠ risk), footer "N% = max loss if stopped"; liquidity "tight" >50% cash; wide-stop volatility note (>7% → 0.75%, >10% → 0.5% suggested risk); HARD deploy cap = sizing_policy.max_deploy_pct_of_cash from proposal-accounts (env MAX_DEPLOY_PCT_OF_CASH, default 20) — caps the table and blocks modal submit with no override | visible |
| ④ Conviction ⟷ Intelligence (2-col grid) | LEFT: CIO stance chip, confidence meter + band, meta, CIO note (2-line clamp, age ⚠ >24h), data-health line. RIGHT: Catalyst-or-none + next-earnings date (amber ≤14d; "none scheduled next 14d" fallback), top news-or-none, Trend (YTD · +X% since added · vs sector), Technicals, company one-liner + intel lanes ("More" → up to 3 more headlines, full description, Fib panel) | visible |
| ⑤ Footer strip (1 line) | Due-diligence status + PDF/Word/↻/Generate + "CIO evidence" expander | visible |

Grid stacks to single column below 1100px (`.wlc-grid` in index.css). Card height ≈470px vs
≈800px in v2 (−40%). Expander bodies render full-width below their grid row. The Sizing module
reuses `computeRiskSizedShares` (cash-basis, retirement hard guard) and pre-fills
`WatchlistProposeSeed.account_key`/`risk_pct` — the card itself never submits.

### Card data feeds (v3 addenda)

- `watchlist_items.first_seen_price` — stamped by the intraday enrichment sweep on a row's
  first enrichment (`COALESCE`, never overwritten); historical rows backfilled for the Hermes
  top-250 via `scripts/backfill_first_seen_price.py` (yfinance close at `first_seen_at`; rows
  without history stay NULL and the card omits the segment). Powers "+X% since added".
- `symbol_profiles.next_earnings_date` — `scripts/earnings_enrich.py` scope widened from
  held-only to held + Hermes-top-200 (`--watchlist-top`, staleness filter `--stale-days 3`
  keeps daily yfinance calls near the churn). Passed through on items as `next_earnings_date`.

## Operator decision card (packet band — primary strategy surface)

**Components:** `DecisionPacketBand.tsx` · `operatorDecisionCard.ts` · embedded from `WatchlistCardV4.tsx`.

| Operator state | When | Primary CTA |
|----------------|------|-------------|
| READY | Action policy allows propose (eligible blueprint) | Review Swing Proposal |
| WAIT | Conditional / pullback / no setup | Set Entry Alert / Details |
| REFRESH | `should_be_stale` or invalidation reasons | Refresh Strategy |
| BLOCKED | Event / data block | Review Event Risk |
| NO TRADE | Preferred no-trade / nothing eligible | Details |
| MANAGE POSITION | Held symbol — manage first | Review Position |

**Freshness (star / buy / strong-buy plans):** during US cash RTH (09:30–16:00 ET) packet TTL is
**4h**; overnight/weekend **12h**. Action policy returns `should_be_stale`, `packet_age_hours`,
`ttl_hours_applied`, `generated_at`, `rth`. Card chips show ET build time + age; stale plans never
masquerade as READY. Technical enrichment “stale after ~1h RTH” (`marketAwareStale`) remains a
separate **data-quality** flag — not the decision-packet TTL.

**Invalidation owner:** `scripts/packet_invalidation.py` (material tech bands; no enrich-clock
false REFRESH). **Batch regen:** `scripts/shadow_batch_generator.py` uses the same RTH-aware window
by default. Full contract: architecture doc above.

## Decision matrix (legacy card action strip)

Logic: `apps/command-center-v3/src/lib/watchlistCardAction.ts` — `deriveRecommendedAction` +
`deriveSecondaryActions`. Each row sets hero text, **primary button**, **warning banner**, and
up to two secondary actions. Coexists with the operator packet band; the band is the strategy
conclusion, this matrix still drives sizing / propose / data-refresh affordances on the broader card.

Verdicts: `READY` · `WAIT` · `SKIP` · `STALE` · `FIX` · `BUILD` · `WATCH`

Stale-plan defects rank ABOVE the R:R branches — stored `entry_rr` is meaningless once levels are
incoherent or price has left the zone. Nightly auto-heal: `scripts/plan_drift_revalidator.py`
(17:25, before the planner run) re-plans defective Hermes-top-250 symbols via
`watchlist_entry_planner` (env `PLAN_DRIFT_REPLAN_PCT=15`, `PLAN_DRIFT_MIN_AGE_H=20`, cap 25).

| Card state (priority order) | Primary button | Warning banner | Secondary actions |
|----------------------------|----------------|----------------|-------------------|
| Private / non-tradeable | View Intel | Private ticker | Rec-Intel |
| No stop on plan | Adjust Plan | Risk undefined | View Intel |
| Target ≤ limit (incoherent plan) | Rebuild Plan (red) | Plan incoherent — stale levels | View Intel |
| Price >15% from limit (drifted plan) | Rebuild Plan (amber) | Price left the planned zone | View Intel |
| R:R &lt; 1.0 or &lt; 1.5 | Adjust Plan | R:R below threshold | View Intel |
| Plan target below Street | Review Exit | Target below Street mean | View Intel |
| Data stale / doubt / pending | Refresh Data | Data stale or doubt | View Intel |
| CIO AVOID / SELL / TRIM | Review Risks (quiet) | CIO view: avoid | Rec-Intel, Ensemble |
| CIO ≠ Street divergence | View Intel | Disagreement banner | Rec-Intel, Ensemble |
| Advisory caution | View Intel | Advisory caution | Rec-Intel, Ensemble |
| Low CIO conf (&lt; 0.5) | View Intel | Low confidence | Rec-Intel, Ensemble |
| Ready / near entry + plan | **Propose Entry** | — | View Intel, Rec-Intel |
| No validated plan | Build Plan | No validated plan | View Intel |
| Monitor (plan, await trigger) | View Intel | — | Rec-Intel, Monitor |

**Rules:** Refresh Data wins over cautious holds when data quality is poor. Propose Entry only
when positive + validated plan + no caution/divergence/stale. Primary button treatment matches
the banner state: solid teal only on READY; amber outline on STALE; quiet neutral on
AVOID/monitor — a negative state never gets a visually rewarding CTA. Red is reserved for hard
plan defects (no stop, R:R &lt; 1) — advisory FIX states (thin edge, target-below-Street /
Review Exit) render amber banner + amber outline.

**Sizing hint** (`riskSizingHint`): when plan validated and R:R ≥ 1.5, shows "1–2% of available
cash sizing" on READY cards.

**Data-quality flags** (`dataQualityFlags`): data doubt, awaiting enrichment, stale technicals,
enrichment age, agents pending, CIO synthesis pending, advisory caution, low CIO conf, no live price.

**Reasoning line** (`actionReasoning`): CIO vs Street divergence, Hermes rank, advisory note,
plan/R:R state, synthesis snippet.

## Holdings-change re-synthesis

`scripts/holdings_change_trigger.py` — after every holdings.json write (hooked in
`schwab_position_sync.protected_holdings_write`, the single gate both the Schwab sync and the
SnapTrade merge write through), per-symbol share totals are diffed against
`data/portfolios/state/holdings_symbol_state.json`. A held-state flip (opened/closed) or a
≥10% share change on a watchlist-tracked symbol enqueues a `full_chain` job
(`request_type=holdings_change`, priority 1, `submitted_from=holdings_change_trigger`) so the
CIO narrative's PORTFOLIO POSITION block re-syncs with reality instead of waiting for the next
scheduled pass. First run baselines silently; CLI: dry-run default, `--apply`, `--baseline`.
Root cause this closes: SMCI bought 2026-07-03 12:33 still showed the prior night's
"zero position" narrative (advisory-only; no order surface).

## Failed-LLM narrative guard

`run_synthesis` skips the upsert entirely when every LLM lane fails (raw starts with
"LLM error") — the prior good synthesis stays in place instead of being clobbered with the
error string. The items API additionally filters `synthesis_narrative ILIKE 'LLM error:%'`
out of the `fs` join. Backlog from the Apr 29 – May 8 2026 outage (404 rows, e.g. ANET's
65-day-old error note) was purged via `scripts/purge_error_synthesis.py` (backup → delete →
re-enqueue Hermes-top-200 overlap only, capped).

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