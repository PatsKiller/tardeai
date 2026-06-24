# Watchlist → Broker Proposals Bridge

Closes the gap where **watchlist BUY / STRONG_BUY** ratings lived in research tables but never appeared in the **Broker Proposals** queue (`paper_trade_proposals` with `origin='watchlist'` was historically zero).

## Problem

| Layer | Before bridge |
|-------|----------------|
| Watchlist | 500+ symbols rated BUY/STRONG_BUY via `watchlist_research_cards`, `watchlist_final_synthesis`, analyst data |
| Broker queue | Only screener/incubator `auto_proposal_generator` rows — watchlist never synced |
| UI | Broker Proposals tab empty of watchlist names; no source badges |

## Solution

`scripts/watchlist_proposal_bridge.py` upserts tagged broker-queue rows:

| Field | Value |
|-------|--------|
| `origin` | `watchlist` |
| `discovery_source` | `watchlist` |
| `intended_broker` | `schwab_taxable` (env: `WATCHLIST_BROKER_ACCOUNT`) |
| `status` | `PENDING` |
| `cio_view` | BUY / STRONG_BUY / ADD / ADD_ON_PULLBACK |
| `sizing_basis.watchlist_rating` | Same rating + Hermes score for sort |

### Persistence rules

- **Stay** while watchlist rating remains BUY, STRONG_BUY, ADD, or ADD_ON_PULLBACK.
- **Refresh** entry/stop/target from authoritative sources only (`trade_plans` → strategy card → confluence).
- **Skip (no insert)** when no authoritative plan exists — **no generic 2×R geometry** (see `docs/BROKER_TRADE_PLAN_GATE.md`).
- **Expire (REJECTED)** when rating drops below BUY.
- **Skip** symbols that already have an active **non-watchlist** proposal (screener wins).
- **Dedupe** older duplicate watchlist rows per symbol (keeps newest).
- **Reconcile** sleeve labels (`income`, `core_holding`) → executable YAML via `broker_strategy_resolver`.

### Entry pricing

Priority for `proposed_entry`:

1. `watchlist_entry_plans.limit_price`
2. `watchlist_strategy_cards.ideal_entry`
3. `watchlist_entry_plans.entry_zone_high`
4. Batch Schwab quote (`last`) for top-ranked names missing plans (max 40 per run)

Names without entry **and** without authoritative stop/target (strategy card / trade plan) are **skipped**.

### Exit levels + R:R policy floor

`broker_strategy_resolver.apply_strategy_exit_plan()`:

- Stop below watchlist **support** (fundamental / level_based).
- Target above **resistance** when configured.
- If resistance caps R:R below YAML/thesis minimum (`max(target_rr, 2.0)`), target is **raised** to the policy floor (stop stays support-anchored).

`sizing_basis.plan_source` and `exit_rationale.sources` record provenance for the trade-plan gate.

## Operator commands

```bash
# Preview (no writes)
.venv/bin/python scripts/watchlist_proposal_bridge.py --dry-run

# Apply sync (default max 40 new per run)
.venv/bin/python scripts/watchlist_proposal_bridge.py --apply

# Larger backlog pass
.venv/bin/python scripts/watchlist_proposal_bridge.py --apply --max-new 80
```

## Cron

From `crontab_backup.txt` (install on host):

```
*/15 7-17 * * 1-5  watchlist_proposal_bridge.py --apply
```

Log: `logs/watchlist_proposal_bridge.log`

## API auto-sync

`GET /api/v2/broker-proposals` and `GET /api/v2/paper-proposals` call `maybe_sync_on_load()` before reading rows.

| Env | Default | Meaning |
|-----|---------|---------|
| `WATCHLIST_PROPOSAL_SYNC_ON_LOAD` | `false` | Enable light sync on API load (off by default — blocks single-threaded server) |
| `WATCHLIST_PROPOSAL_SYNC_CAP` | `25` | Max new rows per API load |
| `WATCHLIST_PROPOSAL_MAX_NEW` | `40` | Max new rows per CLI `--apply` |
| `WATCHLIST_BROKER_ACCOUNT` | `schwab_taxable` | Destination account |
| `WATCHLIST_DEFAULT_RISK_USD` | `150` | Risk-based share sizing |
| `WATCHLIST_DEFAULT_MAX_SHARES` | `500` | Share cap |

Response includes `watchlist_sync` stats on broker-proposals.

## Source badges (UI)

Every proposal card shows **where the signal came from**:

| Badge | Color | When |
|-------|-------|------|
| **◆ Watchlist BUY** | Green | `origin=watchlist` or symbol has active BUY+ watchlist rating |
| **◆ Screener / Incubator / Proposal** | Blue | Auto-proposal pipeline (`origin=auto`, screener/incubator signal) |
| **Both** | Green + Blue | Symbol on watchlist **and** has screener/proposal signal |

API field: `source_attribution` — `{ watchlist, proposal, watchlist_rating, proposal_channel, label }`.

UI: `ProposalSourceBadges.tsx` on **Broker Proposals** and **Proposals** tabs.

## Broker queue hygiene

Watchlist-origin rows are **exempt** from the 24h age cap and entry-drift expiry in `broker_queue_hygiene.py`. They are removed only when the watchlist rating drops (bridge `_expire_stale_watchlist`).

Duplicate watchlist copies are rejected by hygiene + bridge dedupe.

## Related docs

- `docs/BROKER_TRADE_PLAN_GATE.md` — authoritative plan enforcement (no gambling 2×R)
- `docs/BROKER_PROPOSALS_UI.md` — live desk UI + Schwab OTOCO 2FA
- `docs/PROPOSAL_EXECUTION_PATHS.md` — Path A paper vs Path B live
- `docs/CHEAT_SHEET.md` — operator commands

## Code map

| File | Role |
|------|------|
| `scripts/watchlist_proposal_bridge.py` | Sync engine |
| `scripts/broker_strategy_resolver.py` | Sleeve → YAML + exit policy |
| `scripts/broker_trade_plan_gate.py` | Live-route plan gate |
| `scripts/api_v2.py` | `_fetch_watchlist_buy_symbols`, `_attach_source_attribution`, `maybe_sync_on_load` hook |
| `scripts/broker_queue_hygiene.py` | Watchlist-exempt expiry + dedupe reject |
| `apps/command-center-v3/src/components/ProposalSourceBadges.tsx` | Badge UI |
| `apps/command-center-v3/src/lib/proposalSource.ts` | Client attribution helper |