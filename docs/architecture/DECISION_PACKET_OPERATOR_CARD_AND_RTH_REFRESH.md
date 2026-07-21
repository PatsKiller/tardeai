# Decision Packet Operator Card + RTH Few-Hour Refresh

**Shipped:** 2026-07-21 · **Commit:** `b2fbcd90`  
**Status:** LIVE (advisory-only — no orders, no 2FA from this surface)  
**Related UI:** Command Center v3 Watchlist · `DecisionPacketBand`  
**Related code:** `packet_invalidation.py`, `decision_action_policy.py`, `shadow_batch_generator.py`, `operatorDecisionCard.ts`

## Why this exists

Two trust failures landed on the same operator surface:

1. **Audit-dense packet UI** — family state grids, dual hashes, and model lanes
   competed with the only question that matters: *what do I do now?*
2. **False freshness** — technical enrichment timestamps churned every cron tick
   and forced `TECHNICALS_CHANGED` / REFRESH even when RSI/levels had not moved;
   separately, star / buy / strong-buy **decision plans** could sit for **12h**
   during cash hours because action policy and the batch both hard-pinned overnight TTL.

This doc is the as-built authority for the compact operator card and the
trading-day refresh contract.

## Operator card contract

**Primary surface:** `apps/command-center-v3/src/components/DecisionPacketBand.tsx`  
**Presentation pure function:** `apps/command-center-v3/src/lib/operatorDecisionCard.ts`  
**Wire-in:** `WatchlistCardV4` embeds the band; full packet audit stays behind **Details**.

### Primary states (color + CTA)

| State | Meaning | Typical CTA |
|-------|---------|-------------|
| READY | Action policy allows propose (eligible blueprint) | Review Swing Proposal |
| WAIT | Conditional / pullback / no setup yet | Set Entry Alert / Details |
| REFRESH | Inputs no longer current (`should_be_stale` or invalidation) | Refresh Strategy |
| BLOCKED | Event / data blocks new entry | Review Event Risk |
| NO TRADE | Preferred no-trade / nothing eligible | Details |
| MANAGE POSITION | Symbol is held — management first, not a new starter | Review Position |

Rules:

- One headline, one thesis line, ≤3 chips, optional mechanics line.
- **No orders. No 2FA.** Advisory only; proposal path stays approval + 2FA.
- HELD comes from live ownership / portfolio membership — not stale
  `watchlist_symbol_master` phantom portfolio rows (membership sync).
- When stale, mechanics are labeled **previous plan** — never presented as current.

### Timestamps on the card

Always surface for the operator:

- **Clock time** of build (`generated_at` / `evaluated_at`) in America/New_York
- **Age** (`packet_age_hours` → “built Xm/h ago”)
- **TTL applied** when current (`ttl_hours_applied`, with `RTH` tag when cash session)

Chip examples: `10:30 AM EDT · 1.2H AGO` or `NEEDS REFRESH`.

## Invalidation & freshness contract

**Module:** `scripts/packet_invalidation.py` · **Policy version:** `1.1.1`  
**Packet version:** `1.1.0-shadow`

### Time policy (trading day)

| Session | Default packet TTL | Technicals age gate |
|---------|-------------------|---------------------|
| US cash RTH Mon–Fri 09:30–16:00 ET | **4h** (`PACKET_TTL_HOURS_RTH`) | **4h** |
| Overnight / weekend | **12h** (`PACKET_TTL_HOURS`) | **36h** off-hours |

Env overrides: `PACKET_TTL_HOURS`, `PACKET_TTL_HOURS_RTH`,
`PACKET_TECHNICALS_STALE_HOURS`, `PACKET_TECHNICALS_STALE_HOURS_OFF`,
`PACKET_PRICE_DRIFT_PCT` (default **5%**), `PACKET_FUNDAMENTALS_STALE_DAYS` (default 7).

Helpers:

- `is_us_cash_rth(now)`
- `effective_ttl_hours(now)` — star / buy / strong-buy plan cadence
- `effective_technicals_stale_hours(now)`
- `technical_content_hash(rsi, change_pct, rvol)` — **material bands only**

### What forces REFRESH (named reasons)

`TTL_EXPIRED` · `PRICE_DRIFT` · `NEW_CATALYST` · `EARNINGS_CHANGED` ·
`OWNERSHIP_CHANGED` · `FUNDAMENTALS_CHANGED` · `FUNDAMENTALS_STALE` ·
`TECHNICALS_CHANGED` · `TECHNICALS_STALE` · `PROPOSAL_STATE_CHANGED` ·
`OPTIONS_CHAIN_STALE` · `PACKET_VERSION_CHANGED` · major `POLICY_VERSION_CHANGED`

### What must **not** force REFRESH

- Enrichment clock-only churn (`last_enriched_at` tick with no RSI/chg/rvol band shift)
- Policy micro-bumps (e.g. `1.0.0` → `1.1.1`) — only major series (`1.x` → `2.x`)
- Overall input-hash mismatch with no section reason when caused by legacy
  as_of-in-tech-hash noise

Technical hash bands: RSI 5-pt · daily change 1% · RVOL 0.5×. Timestamps live on
the snapshot for **age** gates, not inside the changed-content hash.

## Action policy (`should_be_stale`)

**Module:** `scripts/decision_action_policy.py` · **Sole eligibility authority**

- `evaluate_action(..., ttl_hours=None)` — **None defaults to RTH-aware TTL**
  (bug fixed 2026-07-21: a hard default of 12h had blocked the RTH path).
- Result always carries freshness fields for the UI:

```text
generated_at, packet_age_hours, ttl_hours_applied, rth, should_be_stale
```

- `should_be_stale == true` when age > applied TTL → action `REFRESH`, state `STALE`.
- Block text includes `RTH` when the short cash-session window applied, e.g.  
  `packet is 5.0h old (>4h TTL RTH)`.

Current-input validation (when `current_snapshot` is supplied) runs
`compare_packet_inputs` with the same resolved TTL before any blueprint READY path.

## Shadow batch regeneration (star / buy / strong-buy)

**Module:** `scripts/shadow_batch_generator.py`

Evidence-based target set (label is **sort-only**, not a gate): star · directive ·
held · material move+RVOL · catalyst · scope-S1 · packet-absent. Eligible rating
sort keys still include `STRONG_BUY` / `BUY` / `ADD` / `ADD_ON_PULLBACK` / `HOLD`.

Freshness:

- Default `SHADOW_BATCH_FRESH_HOURS` **unset** → RTH-aware via
  `_effective_fresh_hours()` / `packet_invalidation.effective_ttl_hours`
- Explicit env value overrides for ops/tests
- `classify_freshness` skips only when `inputs_match` under that TTL (hash +
  drift + catalyst + age), so a 5h-old star/buy plan regenerates during RTH

## Ownership / HELD truth

Sold names must not show HELD. Portfolio membership is reconciled by
`scripts/sync_portfolio_watchlist_membership.py` so phantom
`watchlist_symbol_master` `source=portfolio` rows cannot invent held state after
exit. Decision packets read ownership from the same holdings truth path used by
action policy.

## Three-axis plan families (semantic)

Packets materialize `plan_families` with constructibility · decision · action so
EVENT_BLOCKED never renders as “Swing ELIGIBLE · READY”. Operator card maps
policy + held + validity into the six primary states above; family audit remains
in the Details drawer.

## Tests & evidence

| Suite | Coverage |
|-------|----------|
| `tests/test_packet_invalidation.py` | RTH 4h vs overnight 12h, enrich-churn not TECHNICALS_CHANGED, material RSI band, TTL_EXPIRED at 5h RTH, batch fresh-hours helper |
| `tests/test_decision_action_policy.py` | `should_be_stale` + RTH 5h STALE, off-hours 5h still current, age/TTL fields |
| `tests/test_operator_decision_card.mjs` | Operator presentation contract |
| Playwright e2e | `apps/command-center-v3/e2e/operator-cards-screenshots.spec.ts` + screenshots under `e2e/screenshots/operator-cards/` |

## Operator runbook

1. Hard-refresh CC v3 Watch after deploy (new `DecisionPacketBand` bundle).
2. Expect chips with **as-of ET time** and age on current plans.
3. After ~4h RTH without regen, expect **NEEDS REFRESH** / Refresh Strategy — not
   silent READY on a stale plan.
4. Batch: `python3 scripts/shadow_batch_generator.py --dry-run` shows
   `fresh_hours` under the RTH-aware policy; `--run` regenerates stale set only.
5. Override only if needed: `PACKET_TTL_HOURS_RTH=4`, `SHADOW_BATCH_FRESH_HOURS`
   (leave unset for RTH-aware).

## Explicit non-goals

- Does **not** submit, approve, or 2FA any order.
- Does **not** replace CIO synthesis 24h re-synthesis (holdings-change trigger
  still owns narrative re-sync).
- Finviz technical enrichment stale hint (`marketAwareStale`, ~1h RTH) remains a
  **data-quality** cue on the card — separate from decision-packet TTL.

## Ownership map

| Concern | Owner |
|---------|--------|
| Input snapshot + invalidation reasons | `scripts/packet_invalidation.py` |
| Action eligibility + `should_be_stale` | `scripts/decision_action_policy.py` |
| Batch regen cadence | `scripts/shadow_batch_generator.py` |
| Packet materialize / families | `scripts/decision_packet.py` |
| Operator presentation | `operatorDecisionCard.ts` + `DecisionPacketBand.tsx` |
| Watchlist embed | `WatchlistCardV4.tsx` / Watch hub |
