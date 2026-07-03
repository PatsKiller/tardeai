# Command Center v3 — Watchlist Hub

_Last updated 2026-07-03 (Security Card v2). Route: `/v3/watch`._

Decision-first watchlist: one full-width card per symbol with CIO view, plan levels, data-quality
flags, and a unified verdict → CTA matrix. Operators can propose entries directly from a card
without waiting for the cron bridge.

## UI layout

**Page:** `apps/command-center-v3/src/pages/WatchlistHub.tsx`

**Card:** `apps/command-center-v3/src/components/WatchlistCard.tsx` — **Security Card v2**: one
elevated surface with hairline-divided full-bleed rows (no boxes-in-boxes panels). The status
banner is the only tinted element; the primary button the only solid one. Color = signal only
(teal actionable / amber caution / red defect / green price numerals). Tokens:
`apps/command-center-v3/src/lib/watchlistCardTokens.ts`. Zones top→bottom:

| Zone | Content | Default |
|------|---------|---------|
| ① Header | Star, symbol (mono), HELD chip, provenance line (company · Hermes # · origin · sector), colored Street rating `ProAnalystPill` (+ CIO ≠ Street note), price/change, quiet Refresh | visible |
| ② Status banner | Verdict word + headline + one-line why (warning folded in) + primary CTA + one quiet secondary + ••• overflow menu | visible, dominant |
| ③ Trade plan | Limit / Stop / Target / R:R as 17px mono numerals with zone, %, R-per-share sub-captions; exit-vs-Street + sizing note | visible |
| ④ Conviction | CIO stance chip, confidence meter, models/validated/model/setup/urgency meta, one data-health line (dot + worst flag, full list in tooltip) | visible |
| ⑤ Exit ladder | T1 · T2 · T3 prices on one line + scale rule; per-step actions behind "Plan detail" (auto-opens on trade-focus verdicts); always shown when a ladder exists | summary |
| ⑥ Context | Technicals, catalyst, news, company one-liner, external-intel lanes; full description + `FibConfluencePanel` behind "More" | visible |
| ⑦ Due diligence | Weekly prospectus PDF/Word/↻ (`HoldingReportLinks`) with freshness · gen # · oversight verdict; obvious generate state when missing | visible |
| ⑧ Evidence | CIO narrative + evidence + advisory detail behind "CIO evidence & narrative" | collapsed |

Pullback entry levels (`entry_zone_low` / `entry_zone_hi`) render as the Limit sub-caption —
still on the default view. The old footer link row is gone; Intel drawer / Rec-Intel / Ensemble /
Monitor-on-desk live in the banner's ••• menu. Rule of one: each signal renders once, in its
owning zone (e.g. thin R:R = colored numeral + one why-line clause, not four repetitions).

## Decision matrix (detailed card view)

Logic: `apps/command-center-v3/src/lib/watchlistCardAction.ts` — `deriveRecommendedAction` +
`deriveSecondaryActions`. Each row sets hero text, **primary button**, **warning banner**, and
up to two secondary actions.

Verdicts: `READY` · `WAIT` · `SKIP` · `STALE` · `FIX` · `BUILD` · `WATCH`

| Card state (priority order) | Primary button | Warning banner | Secondary actions |
|----------------------------|----------------|----------------|-------------------|
| Private / non-tradeable | View Intel | Private ticker | Rec-Intel |
| No stop on plan | Adjust Plan | Risk undefined | View Intel |
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
the banner state: solid teal only on READY; amber outline on STALE; red outline on FIX; quiet
neutral on AVOID/monitor — a negative state never gets a visually rewarding CTA.

**Sizing hint** (`riskSizingHint`): when plan validated and R:R ≥ 1.5, shows "1–2% of available
cash sizing" on READY cards.

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