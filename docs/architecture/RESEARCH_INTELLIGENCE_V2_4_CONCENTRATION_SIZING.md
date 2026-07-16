# Research Intelligence v2.4 — Concentration-Aware Sizing

**Status:** Implemented · **Date:** 2026-07-15  
**Builds on:** v2.3 consistent portfolio-aware recommendations  
**CC surface:** Command Center v3 only (`/v3/` Research Intelligence hub)

## Goal

Make **concentration risk** and **portfolio heat** first-class inputs that actively shape ticker roles, position size bands, funding trims, and theme capacity — not decorative flags.

## Concentration framework

### Single-name thresholds (% of household book)

| Level | Threshold | Behavior |
|-------|-----------|----------|
| elevated | ≥12% (cores) / ≥8% non-core | Flag; monitor |
| caution | ≥20% (or ≥12% non-core hard) | Prefer as **funding source** |
| high | ≥25% | Require funded adds; trim candidate language |
| extreme | ≥30% | Block net new until rebalanced |

Core long-horizon names: `SCHG`, `SCHD`, `V` — elevated weight expected, still measured.

### Book-level

- **top-3 weight** and HHI-style score
- `book_level`: `normal` | `elevated` | `high`
- Multiplier on new-add size: elevated ×0.75, high ×0.50

### Theme capacity

Soft max targets (`THEME_TARGET_MAX`), e.g.:

| Theme | Soft max |
|-------|----------|
| defense / power_infra | 10% |
| ai_infra | 12% |
| dividend_income | 35% |
| growth | 42% |
| bonds | 15% |

Each theme exposes: `current_pct`, `target_max_pct`, `room_pct`, `level` (`room` / `moderate` / `elevated` / `full`).

At **full**, engine returns `allow_add=False` → rotate/upgrade only.

## Portfolio heat

Loaded from `data/portfolios/state/risk_management.json`:

| Heat level | `portfolio_heat_pct` | Size mult |
|------------|----------------------|-----------|
| low | &lt;5% | ×1.00 |
| elevated | 5–8% | ×0.85 |
| moderate | 8–12% | ×0.65 |
| high | 12–18% | ×0.45 |
| extreme | ≥18% | ×0.25 |

Also surfaces `pct_protected`, stop count, unprotected count in feed context.

## Sizing engine API

`scripts/lib/research_intelligence_portfolio.py`

| Function | Purpose |
|----------|---------|
| `load_portfolio_context()` | Weights + concentration + heat + theme capacity |
| `size_new_position(...)` | Min/max % band, `allow_add`, reasons, funding flag |
| `size_held_review(symbol)` | Held-name trim/hold language by concentration level |
| `funding_sources(need_pct)` | Prefer high-concentration names as `trim_candidate` |
| `build_advisory(...)` | Category-gated recs using the above |

### Size formula (simplified)

```
base = conviction {low:1.25, medium:2.25, high:3.5}
× heat_mult × book_conc_mult × vol_mult
capped by theme room (~45% of remaining room)
floored at 0.5% when add allowed
prefer_funded when heat≥moderate or book≠normal
```

**Why this size** strings are returned as `sizing_reason` and appended to `sizing_guidance` for operator transparency.

## Roles

| Role | Meaning |
|------|---------|
| `add_candidate` | Funded starter after diligence |
| `trim_candidate` | Reduce weight / funding source |
| `hold_review` | Existing holding — thesis/stop/size |
| `protect` | Stop hygiene first |
| `watchlist` | Off-book — research path, not funded order |

## Quality tiers (systematic)

| Tier | Criteria (approx.) |
|------|--------------------|
| **A** | LLM body deep **or** advisory_score ≥5 (ticks + size + reason + bull/bear + impl + depth) |
| **B** | Solid floor: body + ticks/size/action |
| **C** | Thin — verify sources |

## UI (CC v3)

- Action strip: tickers, sizing, **Why this size**, heat/conc chips
- Badges: Tier A/B/C, Tickers & size, Conc. elevated/high
- Right rail: **Book weights** (with level), **Concentration & heat**, **Theme capacity**

## Feed version

`version: "2.4"`

`portfolio_context` now includes `concentration`, `heat`, `theme_capacity`.

## Operator notes

1. Hard-refresh `/v3/` after dist rebuild.
2. Heat reads risk_management SSOT — refresh stops/risk job to keep heat current.
3. Soft theme maxes are advisory policy, not hard compliance gates.
