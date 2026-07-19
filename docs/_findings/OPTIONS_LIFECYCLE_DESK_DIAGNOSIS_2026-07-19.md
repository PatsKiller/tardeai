# OPTIONS LIFECYCLE DESK — Phase 0 Read-Only Truth Audit
**Date:** 2026-07-19 · **Auditor:** Claude (read-only; no code or data changed)

## Executive summary

**There are ZERO open option positions anywhere in the system.** Every broker,
ledger, cache, and queue confirms it independently. The lifecycle desk is being
built *ahead of* its first position — which is the right order: the machinery
must exist and fail closed before the first covered call is ever sold.

The corollary: Phase 0 reconciliation is trivially clean (an empty book cannot
have duplicate legs), and **all acceptance demonstrations must run through the
Alpaca paper options lane** — the only lane that can legally open a position
today. No live-position evidence exists or can exist yet.

## 1. Position sources — live evidence (all read-only, 2026-07-19)

| Source | Method | Result |
|---|---|---|
| Schwab Rollover IRA (…258) | `schwab_transport.get_positions` | 20 positions, **0 options** |
| Schwab Roth (…415) | same | 2 positions, **0 options** |
| Schwab Taxable (…469) | same | 11 positions, **0 options** |
| Fidelity (via SnapTrade) | holdings.json account scan | **0 rows remain** (accounts emptied by the 07-16/17 ACATS transfer out) |
| Alpaca paper | `AlpacaPaperAdapter.get_positions` | 1 position (PSQ equity twin), **0 options** |
| `trade_transactions` ledger | OCC-pattern + description scan | **0 option transactions ever recorded** |
| `holdings.json` | symbol-shape scan | only 3 CUSIP dust rows (12507E201, 543354104, 628518102 — delisted residuals, not options) |

Options approval history: `options_approval_queue` = 510 rows — **477 blocked,
31 rejected, 1 ALPACA_PAPER_REJECTED, 1 pending** (CSCO covered_call, tier C,
created 07-18, expires 07-19, `live_eligible=false`). **No proposal has ever
reached approved/filled.** `options_paper_outcomes` = 0 rows.

## 2. Existing scaffolding (built, never populated)

The prior options-desk work left monitoring tables that have **never held a row**:

- `options_monitored_positions` (0 rows) — single-leg identity: proposal_id,
  broker, execution_route, alpaca ids, OCC-ish `option_symbol`, strategy, side,
  type, strike, expiration, contracts, entry prices/greeks/IV.
- `options_monitored_position_snapshots` (0 rows) — bid/ask/mark/spread%,
  full greeks, IV, intrinsic/extrinsic, DTE, OI/volume, unrealized P&L,
  **max_favorable_excursion already modeled**.
- `options_monitored_alerts` (0 rows) — position_id, alert_type, severity,
  message, acknowledged_at. **No lifecycle states** (no snooze/escalate/
  supersede/resolve), no dedupe key, no policy version.
- `journal_options_groups` (0 rows) — closed-group journal (group_key,
  strategy_label, net_pnl, legs jsonb).

**Gaps vs the required canonical model:** no strategy-level grouping entity
(everything is per-leg), no roll ancestry, no policy versioning, no
operator_objective, no data_quality_status, no decision ledger, no MAE/giveback
persistence, no assignment/exercise state, no fees, no realized P&L at the
strategy level.

## 3. Identity model facts

- Queue proposals carry `{symbol, strike, exp, contracts, delta, mid, account,
  strategy}` — **no OCC symbol, no legs array, no multiplier**. Multi-leg
  structures cannot be represented in the proposal shape today.
- Schwab positions API is the only broker feed that would surface a real option
  position (assetType OPTION with OCC symbol); nothing maps that shape into any
  table today.
- `options_chain_snapshots` (39,837 rows, 40 symbols, fresh to 07-19 09:32) —
  despite the name, `chain_json` holds **aggregates only** (note,
  expiration_count, underlying_price) + `vol_analytics_json`. The Defense-side
  `option_chain_snapshots` (27 rows/day) holds radar aggregates + one validated
  `cc_call`/`prot_put` pick. **No full per-contract chain is persisted anywhere**
  — chains are fetched live via `schwab_transport.get_option_chain` and reduced
  immediately. Ticket preflight (Phase 6) must therefore refresh chains at click
  time — which the requirements mandate anyway.
- Ex-dividend data: **no dividend calendar table exists** (checked
  `%dividend%`/`%exdiv%`). Phase 4 needs a source; `trade_transactions` records
  received dividends (history, not forward calendar).

## 4. Blockers found (must fix in-band, none block Phase 1)

1. **B-1 · No strategy grouping anywhere** — the required
   `options_strategy_positions`/`legs` split does not exist; the empty
   monitored tables are per-leg. Decision: build the new canonical entities;
   keep `options_monitored_*` frozen (empty), mark superseded in docs.
2. **B-2 · Proposal→position identity gap** — queue rows lack OCC symbols and
   leg arrays; fills would be un-reconcilable. The lifecycle intake must
   construct OCC identity from (symbol, exp, type, strike) and verify against
   broker fills, never trust the proposal alone.
3. **B-3 · No forward ex-div calendar** — early-assignment engine (Phase 4)
   requires one; must be added as a data feed with staleness flags, or the
   ex-div checks report DATA_BLOCKED (fail closed), never silently pass.
4. **B-4 · Chain data is transient** — every economic snapshot must persist its
   own quote evidence (bid/ask/ts/source) at capture time; nothing can be
   recomputed later from stored chains.

## 5. Canonical source of truth (the Phase 0 decision)

- **Open option positions:** the BROKER is canonical — Schwab positions API
  (assetType OPTION) for Schwab; Alpaca positions API for paper; Fidelity has
  no API (SnapTrade read-only sync + operator-recorded manual evidence).
  Local tables are a *reconciled mirror*, never the source.
- **Position closure:** broker fill evidence or explicit operator-recorded
  manual evidence ONLY (per the safety boundary). UI clicks never close.
- **Entry economics:** broker fills where available; queue proposal data is
  advisory context, demoted on any conflict; UNKNOWN stays UNKNOWN, never 0.
- **Marks:** live `get_option_chain` at snapshot time, with timestamp + source
  + spread% persisted per snapshot; stale ⇒ `data_quality_status=stale` ⇒
  DATA_BLOCKED recommendations.

## 6. Code-surface inventory (repo-wide read-only sweep, 2026-07-19)

**Proposal engine (MUST REMAIN INTACT):** `scripts/options_engine.py` (2,213
lines — CC/CSP/defined-risk/credit-spread generators, edge/POP/IV-rank gates,
`_parse_occ`) + `scripts/options_desk_enterprise.py` (919 lines — hard-risk
blocks, liquidity gate, book greeks, tier, `options_approval_queue` sync,
fail-closed `check_preflight_approval`) + `scripts/lib/options_pipeline/*`
generators + `config/strategies/*.yaml` (all `live_allowed: false`).

**Existing per-leg monitors (the layer this desk SUPERSEDES for management):**
- `options_engine.monitor_positions()` → `_fetch_schwab_option_positions()` —
  the ONLY place Schwab option legs are recognized (OCC regex over
  `get_positions`; the transport itself has no assetType OPTION branch).
- `scripts/lib/options_pipeline/paper_position_monitor.py` — marks-to-market
  `options_monitored_positions`, writes snapshots + `paper_position_alerts.py`
  (theta/DTE/assignment) — per-leg, no strategy grouping, no policy version,
  ephemeral advice labels.
- Active cron: `run_options_monitor.sh` */10 12:00–15:59 + 16:05 (moved off
  mornings 2026-07-17 to protect the scalp GPU window); Alpaca paper reconcile
  hourly 10:00–15:00; IV snapshot 15:45.

**Execution lanes (Phase 6 binds to these, never invents new ones):**
- Schwab live: `scripts/brokers/options_order_pilot.py` (OCC builder,
  single-leg specs, 2FA marker OPTIONS_EXECUTION_1, `schwab_pilot_orders`
  kind='options') gated by `options_execution_policy.evaluate()` (allowlist,
  ≤5 contracts, ≤$25K, strategies) AND the DB arm switch
  `system_controls['options_execution_enabled']` set only by typed phrase via
  `options_pilot_arm.py`. **Currently DISARMED; every strategy YAML
  live_allowed:false.**
- Alpaca paper: `alpaca_paper_options_executor.py` — the only lane that can
  submit today (paper-locked, LIMIT-only, 1-contract cap, BTO-only; spreads
  refused pending `multi_leg_proven`).
- Fidelity: manual only — `ManualExecutionModal.tsx` +
  `/api/v2/options/executions/log-manual`.
- `defense_execution.py`: equity-only (zero option references) — lifecycle
  tickets do NOT route through the Defense intent rail.

**UI:** `pages/OptionsHub.tsx` (Options tab in TradingHub) with
OptionProposalCardV4 / OptionPositionCardV4 / OptionChainPanel /
OptionReviewBar; ~25 `/api/v2/options/*` routes in api_v2.py (proposals,
open-positions, monitor, approval-queue, alpaca-paper lane, prime-rubric).

**Confirmed absent:** Fidelity option ingestion (SnapTrade flattens options to
bare symbols — a Fidelity option leg would appear as an unparseable symbol row);
Alpaca option read-adapter (executor lane only); full per-contract chain
persistence; forward ex-div calendar; strategy-level grouping anywhere.

## 7. Reconciliation verdict

With zero open positions: **no duplicate legs, no missing accounts, no
ungrouped spreads, no unverifiable entries — vacuously clean.** The first real
reconciliation happens the day the first position opens; the desk's health
checks (Phase 9) must make that day boring.
