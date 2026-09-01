# Broker Trade Plan Gate — No Gambling on Generic 2×R

Status:      ACTIVE
as_of:       2026-06-24T13:45:49-04:00
Measured at: efcc51365 / not measured

Path B (live Schwab/Fidelity) requires an **authoritative trade plan** before Auto route or promote.
Generic `entry + 2×risk` geometry without a technical anchor is blocked — same standard as the
Proposals tab when `trade_plans` exist.

## Problem (2026-06-24)

Watchlist bridge rows used sleeve labels (`income`, `core_holding`) and filled missing targets with
**2:1 R:R math** when strategy cards were empty. Cards showed inflated **live R:R** (live price vs
old wide targets) while stored `proposed_rr` was exactly `2.0`.

## Solution stack

| Layer | File | Role |
|-------|------|------|
| Strategy resolver | `scripts/broker_strategy_resolver.py` | Sleeve → YAML `strategy_id`; `apply_strategy_exit_plan()` |
| Trade plan gate | `scripts/broker_trade_plan_gate.py` | PASS/WARN/BLOCK before live route |
| Watchlist bridge | `scripts/watchlist_proposal_bridge.py` | Skip insert/refresh without authoritative levels |
| Promote sizing | `scripts/broker_promote_sizing.py` | Calls gate on every `evaluate_broker_promote` |
| Oversight | `scripts/broker_promote_oversight.py` | Diligence stage **Trade plan** (step 6 of 7) |
| UI | `BrokerProposalCard.tsx` | Disables Auto route when `trade_plan.status === BLOCK` |

## Authoritative plan sources (priority)

1. `trade_plans` table (screener / backfill — same as Proposals tab)
2. `watchlist_strategy_cards` with support/resistance and stop/target
3. `indicator_confluence_cache` (scalp profile)
4. **Not authoritative:** generic 2×R, quote-only entry, curation `price_estimate` on the card UI alone

Bridge and gate **reject** rows that would only resolve to generic fallback sources.

## Exit geometry (`apply_strategy_exit_plan`)

1. **Stop** — below support × 0.97 (`fundamental` / `level_based`) or strategy `fixed_pct`
2. **Target** — above resistance × 1.02 when `target_method` allows
3. **Policy floor** — if resistance caps reward below minimum:
   - `min_rr = max(YAML risk.target_rr, thesis MIN_RR_DEFAULT 2.0)`
   - `target = max(resistance_target, entry + risk × min_rr)`
   - Source note: `target raised to X:1 policy floor (resistance capped $Y)`

Stops stay technical; targets are not blind 2×R when resistance is too close.

## Strategy alignment (watchlist held examples)

| Symbol | Sleeve | DB classification | Executable YAML |
|--------|--------|-------------------|-----------------|
| MS | `core_holding` | `core_growth_compounder` | Core Growth Compounder (policy R:R 3.0) |
| DFAI | `income` | `international_dividend` | International Dividend (policy R:R 2.0) |
| DB | `income` | `dividend_growth_compounder` | Dividend Growth Compounder (policy R:R 2.0) |

Resolver order: `ticker_strategy_classifications` → proposal `strategy_id` → sleeve map.

Sleeve map defaults: `income` → `dividend_growth_compounder`, `core_holding` → `core_growth_compounder`.

**2×R is not a strategy** — it is fallback math. Allocation policies (`ALLOCATION_POLICY`) have
`live_allowed: false` in YAML; live route may still warn on sizing caps separately.

## Environment

| Env | Default | Meaning |
|-----|---------|---------|
| `BROKER_REQUIRE_TRADE_PLAN` | `1` | Enforce gate on live routes |
| `BROKER_TRADE_PLAN_RR_TOLERANCE` | `0.03` | Detect exact R:R-only targets |

## Operator refresh (held watchlist names)

```bash
# 1. Materialize or backfill strategy cards (support/resistance/stop/target)
.venv/bin/python scripts/materialize_watchlist_strategy_cards.py --symbols MS DFAI DB

# 2. Re-derive proposal levels from cards (no generic 2R inserts)
.venv/bin/python scripts/watchlist_proposal_bridge.py --apply

# 3. Restart portfolio server so Python modules reload (port 7777)
#    Hot-reload only touches api_v2.py — gate modules need full restart.
```

## API / diligence

- `POST /api/v2/broker-proposals/detail` — includes `evaluation.trade_plan`
- `POST /api/v2/broker-proposals/route-preview` — hard blocks propagate to `hard_blocks`
- Promote diligence stages: Enrich → Agents → AI Review → Intel → Cloud → **Trade plan** → Broker

## Tests

- `tests/test_broker_trade_plan_gate.py`
- `tests/test_broker_strategy_resolver.py` (policy floor)

## Related docs

- `docs/PROPOSAL_EXECUTION_PATHS.md` — Path A vs Path B
- `docs/WATCHLIST_PROPOSAL_BRIDGE.md` — watchlist BUY+ sync
- `docs/BROKER_PROPOSALS_UI.md` — live desk UI