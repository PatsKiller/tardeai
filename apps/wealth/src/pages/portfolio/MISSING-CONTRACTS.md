# Portfolio: missing contracts for Retirement, Levels & valuation, Allocation

Audit 2026-11-16. Each route below renders only what its producer serves. Nothing is estimated. "Owner" is a
suggestion for the lead; no producer was changed by this lane.

## portfolio/retirement

Partial state: renders `/api/v2/retirement` (accounts, loan, golden window, dividend income, milestones, roadmap
clocks) and `/api/v2/retirement/planning-research` (themes). Served 0 is shown Unknown.

| Missing | Precise contract | Producer | Suggested owner |
|---|---|---|---|
| Missing vs zero | `accounts`, `loan`, `dividend_income`, `current_age` built with `or 0`; serve null (or a `field_state`) when the stored roadmap lacks the value | `scripts/api_v2.py` `retirement()` | backend owner (api_v2) |
| Projections | `projections[scenario]` with `{rate_assumption, horizon_years, contributions, as_of}` so a balance is never shown without its assumptions | `retirement()` | backend owner |
| Narrative | `intelligence_brief` embeds a fixed 7% growth and a fixed monthly need; serve those as stored, editable assumptions, or drop the figures from the text | `retirement()` | backend owner + operator (assumption values) |
| Roth ladder, income floor, mortgage, rates | held in `data/portfolios/state/retirement_roadmap.json` but not in the response | `retirement()` | backend owner |
| Staleness verdict | `roadmap_stale` computed from `generated_at` against a stated limit | `retirement()` | backend owner |
| Dividend clock | `dividend_income.as_of` (calendar build time) | `retirement()` / dividend calendar | backend owner |
| Holdings tie | `canonical_total` with its snapshot clock and basis, so the roadmap total can be reconciled to Holdings | `retirement()` | backend owner |
| Research source clock | `planning-research.as_of` is the request time; serve `built_at` per theme | `_retirement_planning_research` | backend owner |

Reader spec for `readers.ts` (population lane owns the file): two entries, `retirement` -> `/api/v2/retirement` and
`retirementResearch` -> `/api/v2/retirement/planning-research`, both GET, no params, class: stored-state (not heavy),
unwrapping `{ok, data}`. Until added, the page calls `getJson` directly with those paths (as `AllocationLive` does).

## portfolio/levels

Partial state: per-symbol price levels from `/api/v2/indicators/levels?symbol=X`, grouped, one GET on user action.
Valuation is stated not wired.

| Missing | Precise contract | Producer | Suggested owner |
|---|---|---|---|
| Clock | `computed_at`, `expires_at` of the confluence cache entry | `scripts/api_v2.py` `_indicator_levels_handler` | backend owner |
| Held-symbols form | `GET /api/v2/portfolio/levels` returning levels for the held symbols with a per-symbol `as_of` and the last price used | new, beside `_indicator_levels_handler` | backend owner |
| Error shape | handler returns an unwrapped tuple (`400, {ok:false}`); standardise on the ROUTES wrapper | `_indicator_levels_handler` | backend owner |
| Valuation | `valuation-assessment@1` rows (`status`, PE_TRAILING/PE_FORWARD with period and basis, benchmarks, as_of); rows carry `valuation: null` today | holdings/fundamentals producer, no methodology wired | operator decision, then backend owner |
| Level semantics | `color` is presentation only; serve `kind` and `timeframe` instead | `_indicator_levels_handler` | backend owner |

Reader spec for `readers.ts`: `indicatorLevels` -> `/api/v2/indicators/levels?symbol={symbol}`, GET, per-symbol,
validated `^[A-Z][A-Z0-9.\-]{0,9}$`, no poll.

## portfolio/allocation (D2)

Partial state: drilldown, named bases and a computed reconciliation of the allocation total to the Holdings
summation over the same rows are rendered.

| Missing | Precise contract | Producer | Suggested owner |
|---|---|---|---|
| Producer percent basis | `portfolio_pct_basis` (value field plus snapshot clock) beside `portfolio_pct`, so the drawer percent can be reconciled | holdings producer behind `/api/v2/portfolio/holdings` | backend owner |

Note: the page's row sleeve key duplicates the selector's `sectorOf` (`Cash & sweep` for cash, else sector, else
`Unclassified`). Exporting that function from the selector would remove the copy.
