# Broker Proposals UI — Live Execution Desk (v3)

Command Center → **Trading** → **Broker Proposals** tab (`BrokerProposals.tsx`).

Path B live queue for Schwab/Fidelity equity proposals promoted from the paper-agnostic queue.
See `docs/PROPOSAL_EXECUTION_PATHS.md` for the two-path model (Path A paper vs Path B live).

## Operator workflow

1. **Arrive** via **Promote to Broker** (screener/incubator) **or** watchlist bridge (BUY+ names auto-synced — see `docs/WATCHLIST_PROPOSAL_BRIDGE.md`).
2. **Read source badges** — green **◆ Watchlist**, blue **◆ Screener/Proposal**, or both when dual-attributed.
3. **Pick destination account** — Schwab (auto+2FA or manual) or Fidelity (FA manual only).
4. **Refresh prices** — live quote + thesis validity band + sizing recalc.
5. **Oversight** — local agents (Maria/Risk/Steph) + **Grok+ChatGPT** cloud review. Cloud auto-queues on detail load when thesis + lanes are ready (`api_v2._broker_oversight_for_proposal` → `maybe_queue_cloud_oversight`).
6. **Execute** — Schwab **Auto route (2FA)** opens **Route confirm** modal (review/edit trade → preview gates → request 2FA), or place at broker and **Executed manually**.

## Source badges

| Badge | Meaning |
|-------|---------|
| **◆ Watchlist BUY** (green) | Synced from watchlist bridge; persists while BUY/STRONG_BUY rating holds |
| **◆ Screener / Incubator** (blue) | Auto-proposal from scan/incubator pipeline |
| **Both** | Symbol on watchlist **and** has screener signal on the same card |

Hover for full `source_attribution` (API-computed on each row). Component: `ProposalSourceBadges.tsx`.

## Risk visualizations (v1)

See `docs/COMMAND_CENTER_RISK_VISUALIZATIONS.md` for the full hub map.

| Visual | Component | Purpose |
|--------|-----------|---------|
| **Thesis score ring** | `ThesisValidityGauge` | 0–100 from zone base + R:R/drift adjustments (e.g. `comfortable` 92 + live R:R ≥ 2 → **97**; `at_risk` → **38**) — not Hermes, litmus, or cloud verdict |
| **Drift gap bar** | `ThesisValidityBar` | Stop · entry · valid band · target · live price dot |
| **Sizing risk bar** | `PositionSizingRiskBar` | Queued shares vs account cap (red when oversized) |

## UI sections (per proposal card)

| Section | Purpose |
|---------|---------|
| **Thesis validity bar** | Visual drift gap — price band where entry zone + min R:R still hold (green/yellow/red) |
| **Account picker** | Grouped Schwab vs Fidelity; shows cash, open trades, daily slot usage |
| **Risk metrics** | Position, max risk, profit @ target, live R:R |
| **AI oversight** | Local review status, Grok/ChatGPT lane verdicts, consensus |
| **Actions** | Refresh prices · Edit trade · Executed manually · Auto route (→ Route confirm modal) / Record |

## Account selection

| Broker | Modes | UI label |
|--------|-------|----------|
| **Schwab** | API auto (gated, per-order 2FA) **or** manual at Schwab.com | `Schwab — API auto (2FA) or manual` |
| **Fidelity** | Manual only — **Active Trader Pro (FA)** | `Fidelity — FA manual only` |

Changing account re-runs `evaluate-promote` sizing caps for that destination (cash, daily limits).

**Operator route mode (`operator_route=True`):** Broker Proposals list/detail and live route use operator-confirmed size as authoritative. P0 readiness, policy caps, paper-queue sizing, and daily/concurrent limits surface as **warnings** — not GATE BLOCK. Hard blocks remain: invalid entry/stop, zero shares, over available cash, and live market gates.

**Share sizing display:** The card always shows two numbers when they differ:

- **Queued** — `proposed_shares` saved on the proposal (often paper/promote sizing, e.g. 6,760 sh).
- **Cap for [account]** — max allowed for the selected Schwab/Fidelity account (e.g. 292 sh on rollover IRA cash).

Risk metrics show **at queued size** first, then **if resized to cap**. Use **✎ Edit trade** to persist the cap before routing live.

Thesis validity band uses entry/stop/target + live quote — **not** Grok/ChatGPT (cloud is a separate oversight step).

## Thesis validity / drift gap

Computed by `scripts/broker_thesis_validity.py` and attached to every broker queue row as `thesis_validity`.

- **Valid band** — intersection of strategy entry-zone drift (from `proposal_lifecycle`) and min R:R floor (default 2:1).
- **Zone status** — `comfortable` (green) · `approaching` (yellow) · `at_risk` / `invalid` (red).
- **Visual** — stop / entry / valid zone / target markers + live price dot on `ThesisValidityBar.tsx`.

## Auto price recalibration (automated)

Broker queue prices are **persisted in DB** automatically — not display-only.

| Trigger | Script / path | Interval |
|---------|---------------|----------|
| **Cron** | `scripts/run_broker_queue_autocal.sh` → `broker_proposal_autocal.py --apply --force` | Every **5 min** 9:00–16:00 ET weekdays |
| **API list load** | `GET /api/v2/broker-proposals` calls `maybe_auto_recalibrate()` | Throttled ~5 min for stale rows |
| **Proactive quote refresh** | `run_proactive_quote_refresh.py` | Includes `APPROVED_FOR_PAPER_TEST` broker rows |

Autocal batch-fetches Schwab quotes (50 symbols/call), writes `current_price`, `price_drift_pct`, `entry_zone_status`, `last_price_source`, `updated_at`, then clears list cache.

Env: `BROKER_PRICE_MAX_AGE_MIN` (default 20), `BROKER_AUTOCAL_INTERVAL_SEC` (default 300), `BROKER_AUTOCAL_DISABLE=1` to turn off API trigger.

**UI note:** List rows use live quotes; light detail prefetch must not overwrite them (fixed in `mergeProposal`).

## 30-minute curation pass (trading hours)

Full broker-queue curation runs every **30 minutes** 9:00–16:00 ET weekdays (`run_broker_proposal_curator.sh`).

| Step | What |
|------|------|
| **Prices** | Batch Schwab refresh → DB persist (all rows, not just stale) |
| **Support lines** | `support_1` / `resistance_1` from 20d lows/highs (+ watchlist cards fallback) |
| **Strategy fit** | Re-run classifier — flags `strategy_changed` if proposal strategy no longer qualifies |
| **Criteria** | Thesis zone, live R:R floor (`BROKER_CURATOR_MIN_RR`, default 2), price freshness |
| **Hygiene** | Auto-expire/reject stale broker rows (entry missed, stop breached, superseded) |
| **Stamp** | `last_curated_at`, `curation_status`, `curation_snapshot` JSON on each row |

Cards show **Support / Resistance**, **Curated timestamp**, and status (`fresh` · `warn` · `stale` · `strategy_changed`).

Manual: `python3 scripts/broker_proposal_curator.py --apply` (add `--symbol RTX` for one name).

## Refresh prices + recalibrate (manual)

**Per card:** `↻ Refresh prices`  
**Queue:** `↻ Refresh all prices` (batch API `refresh-prices-batch`)

```bash
curl -s -X POST http://localhost:7777/api/v2/broker-proposals/refresh-prices \
  -H 'Content-Type: application/json' \
  -d '{"proposal_id": 123, "account": "fidelity_rollover_ira"}' | python3 -m json.tool
```

On refresh:

1. Fetches live quote (`_broker_promote_quote` → Schwab transport or `market_quote_provider`).
2. Updates `paper_trade_proposals.current_price` and `price_drift_pct`.
3. Recomputes `thesis_validity`, broker sizing, gates, oversight snapshot.

## Cloud AI oversight (Grok + ChatGPT)

| Action | API |
|--------|-----|
| Queue local reviews | `POST /api/v2/broker-proposals/queue-oversight` |
| Run Grok+ChatGPT | `POST /api/v2/broker-proposals/run-cloud-oversight` |
| Batch queue cloud | `POST /api/v2/broker-proposals/queue-cloud-batch` |

Backend: `scripts/broker_promote_oversight.py` → `cloud_review.review()`.

- **Auto-queue:** `_broker_oversight_for_proposal()` calls `maybe_queue_cloud_oversight()` before `evaluate_oversight()` so cards move from `not_run` → `running` without a manual **Run cloud** click.
- **DISAGREE** → oversight BLOCK (live route disabled until resolved).
- **CAUTION** → WARN (operator may proceed with eyes open).
- **AGREE** → PASS contribution toward promote-ready.
- Per-lane breakdown (Grok / ChatGPT verdict + assessment) shown in `BrokerIntelPanel`.

Requires local thesis text — run **AI Review** on the paper proposal first if cloud returns "No local thesis".

## Schwab auto route — review modal, OTOCO bracket + 2FA

When Schwab pilot is **armed**, **Auto route (2FA)** opens `BrokerRouteConfirmModal` before any 2FA is requested.

| Step | Endpoint / UI | Action |
|------|---------------|--------|
| 0 | **Route confirm** modal | Edit account, shares, entry, stop, target; live gate preview |
| 0b | `POST /api/v2/broker-proposals/route-preview` | Operator-route evaluation (warnings vs blocks) + economics |
| 0c | Trade plan gate (`broker_trade_plan_gate`) | **Hard block** if no authoritative plan (trade_plans / strategy card / confluence) — generic 2×R geometry is gambling; not waived on operator route |
| 1 | `POST /api/v2/broker-proposals/route` | Persist operator trade, build OTOCO intent, request per-order 2FA |
| 2 | Card 2FA panel + Telegram | Same trade packet (shares, entry/stop/target, risk, investment, R:R) |
| 3 | Operator approves | Web ticker, Telegram, or email code |
| 4 | `POST /api/v2/broker-proposals/route/confirm` | Submit Schwab OTOCO bracket after 2FA |

`route` body accepts optional `account`, `shares`, `entry`, `stop`, `target` — operator values override DB proposal fields for that route attempt.

Backend: `broker_entry_pilot.route_preview()` / `request_route(trade=...)` → `queue_router.route_proposal(..., trade=...)`.

Post-fill monitoring: `scripts/schwab_broker_trade_monitor.py` (cron `*/5` market hours) — R-trails stops, requests protective-stop MODIFY 2FA when needed.

Tests: `tests/test_broker_entry_pilot.py`

## Manual execution (closed loop)

**Executed manually** on any card → `ManualExecutionModal` → `POST /api/v2/executions/log-manual`.

Tagging + journal linkage: `scripts/manual_execution_tracker.py` (see `docs/OPTIONS_BROKER_EXECUTION_FLOWS.md`).

## API reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v2/broker-proposals` | GET | Fast queue list + accounts (detail lazy-loaded) |
| `/api/v2/broker-proposals/detail` | POST | Intel + sizing gates for one card |
| `/api/v2/broker-proposals/refresh-prices` | POST | Live quote + thesis band + recalibrated sizing |
| `/api/v2/broker-proposals/evaluate-promote` | POST | Account-preview sizing when destination changes (`operator_route` optional) |
| `/api/v2/broker-proposals/run-cloud-oversight` | POST | Grok+ChatGPT second opinion |
| `/api/v2/broker-proposals/queue-oversight` | POST | Queue Maria/Risk/Steph + local LLM |
| `/api/v2/broker-proposals/route-preview` | POST | Pre-2FA gate preview for operator-edited trade packet |
| `/api/v2/broker-proposals/route` | POST | Schwab OTOCO bracket + 2FA request (accepts operator trade fields) |
| `/api/v2/broker-proposals/route/confirm` | POST | Confirm 2FA and submit Schwab bracket |
| `/api/v2/executions/log-manual` | POST | Log manual fill + lineage |

Each list row includes `source_attribution` for badge rendering.

## Code map

| Layer | Files |
|-------|-------|
| UI | `BrokerProposals.tsx`, `BrokerProposalCard.tsx`, `BrokerRouteConfirmModal.tsx`, `ProposalSourceBadges.tsx`, `ThesisValidityBar.tsx`, `BrokerAccountPicker.tsx`, `BrokerIntelPanel.tsx` |
| Watchlist bridge | `scripts/watchlist_proposal_bridge.py` |
| Schwab entry | `scripts/brokers/broker_entry_pilot.py`, `scripts/queue_router.py`, `scripts/schwab_broker_trade_monitor.py` |
| Queue hygiene | `scripts/broker_queue_hygiene.py` (watchlist-exempt expiry) |
| Thesis math | `scripts/broker_thesis_validity.py` |
| Oversight | `scripts/broker_promote_oversight.py` |
| Sizing | `scripts/broker_promote_sizing.py` |
| API | `scripts/api_v2.py` — `_broker_proposals`, `_attach_source_attribution`, `_broker_refresh_prices` |
| Tests | `tests/test_broker_entry_pilot.py`, `tests/test_broker_thesis_validity.py`, `tests/test_broker_promote_oversight.py` |

## Related docs

- `docs/WATCHLIST_PROPOSAL_BRIDGE.md` — watchlist BUY+ → broker queue sync
- `docs/PROPOSAL_EXECUTION_PATHS.md` — Path A vs Path B
- `docs/OPTIONS_BROKER_EXECUTION_FLOWS.md` — options desk + shared manual-log flow
- `docs/broker-promote-sizing.md` — cash-based sizing caps (if present)