# Defense and Sectors Live Payload Audit — 2026-07-24

**Evidence:** operator-provided browser screenshots of the four live Tailnet JSON endpoints at approximately 11:49 ET.  
**Scope:** payload truth and frontend interpretation only. No host, service, broker, order, approval, 2FA or production state was changed.

## Endpoint timestamps

| Endpoint | Payload timestamp | Interpretation |
|---|---|---|
| `/api/v2/defense/posture` | `generated_at=2026-07-23T21:26:23Z` | Prior-close sector/market snapshot. Most sector rows are `as_of=2026-07-23`; Real Estate is visibly older at `2026-07-13`. |
| `/api/v2/defense/industries` | `captured_at=2026-07-23T16:30:05Z`, `capture_kind=refresh` | Midday display refresh. Current industry quadrants are not the same thing as a close-confirmed transition. Close runs own persistence and transition confirmation. |
| `/api/v2/defense/recommendations` | `generated_at=2026-07-24T14:10:01Z`, `as_of=2026-07-24` | Current recommendation build using prior snapshots and portfolio/config inputs. |
| `/api/v2/sectors/monitor` | intraday values visible on 2026-07-24 | Current day ETF/relative-strength monitor and enriched watch-universe screen matches. |

## Live sector findings

### Research leadership is not the same as an add recommendation

The recommendation payload has:

```text
get_into: []
```

Therefore there is no governed sector, ETF or stock add card in the current build. The frontend must not turn a leading monitor signal into `MONITOR FOR ENTRY` or imply that screened stocks are recommended.

### Technology: improving but narrow

- State: `IMPROVING`
- RS20: `-3.22%`
- Five-session slope: `+2.89%`
- Breadth: `19%` of 58 sampled members
- Effective book weight: `13.6%`

Interpretation: this is a sharp relative rebound from a still-negative 20-session level with very narrow participation. It is a research watch, not broad sector confirmation.

### Financials: leading but already a large book exposure

- State: `LEADING`
- RS20: approximately `+3.3%`
- Effective book weight: `23.4%`
- Direct book weight: `16.4%`

Interpretation: leadership does not imply capacity to add. The governed engine correctly emitted no add card. The UI must show the portfolio weight and defer to the recommendation/mandate layer.

### Energy: leading but policy/rails did not authorize an add

- State: `LEADING`
- RS20: approximately `+10.26%`
- Effective book weight: `3.6%`
- Current governed add cards: none

Interpretation: Energy is a legitimate research candidate. It is not a current allocation instruction. The active defensive-sector directive or other recommendation rails may be excluding it and require dated operator re-adjudication rather than silent override.

### Industrials: sector lagging while industries diverge

- Sector state: `LAGGING`
- RS20: approximately `-2.22%`
- Effective book weight: `16.3%`
- Industry examples in the refresh include improving Aerospace & Defense and leading Building Products & Equipment.

Interpretation: sector and industry layers are giving different-granularity signals. This is useful evidence, but it requires explicit contradiction handling. An improving industry under a lagging sector is a selective-security research case, not automatic sector rotation.

### Market style evidence is defensive

The posture payload shows:

- growth versus value: `LAGGING`;
- small versus large: `LAGGING`;
- equal weight versus cap weight: `WEAKENING`.

This does not support a broad risk-on conclusion.

### Market internals sample is not comprehensive breadth

The payload reports 15 rows for each `market_movers` signal, including 15 new highs and 15 new lows. This is consistent with the producer's top-15 cap. `NH/NL 15/15 — mixed tape` must be labeled as a capped movers sample and must not be interpreted as full-universe breadth.

### Row-level freshness differs

Most sector rows are dated 2026-07-23, but Real Estate is dated 2026-07-13. Aggregate `generated_at` alone is insufficient. The UI must expose per-row `as_of` and visibly flag stale rows.

## Live industry findings

The industry payload is a `refresh`, not a close capture. Examples visible in the screenshot include:

- Aerospace & Defense: `IMPROVING`, but still negative over the month relative to SPY;
- Agricultural Inputs: `LEADING`;
- Banks — Diversified: `LEADING`;
- Biotechnology: `LEADING`;
- Chemicals: `LEADING`;
- Communication Equipment: `IMPROVING` after strong short-window relative performance but negative month-relative level;
- Computer Hardware: `IMPROVING` with a very strong one-week rebound and a still-negative month-relative level;
- Auto Manufacturers: `LAGGING`;
- Airlines: `LAGGING`.

These are useful research classifications. They are not close-confirmed transition alerts unless the close-run evidence says so. The UI must avoid the word `confirmed` for midday industry states.

## Live recommendation findings

### No governed rotate-in book

`groups.get_into` is empty. The rotation brief should show research watches separately and explicitly state that no add card is active.

### Protective put was withheld by live structure rails

The visible XLI protective-put card shows:

- open interest about `5,255`;
- volume `8`;
- spread `22.2%`;
- delta about `0.28`;
- IV about `22.2`;
- required spread rail `<=12%`;
- `put_struct=null`.

This is a withheld research structure, not an actionable hedge. The UI should label it `WITHHELD — failed structure rails` rather than presenting it as a normal hedge idea.

### ARKX trim is a governed protect card

The visible recommendation is a core-position trim in the Rollover IRA, with a 50% trim calculation, explicit factor arithmetic, account/tax context, estimated proceeds and an invalidation/re-entry condition. This is meaningfully different from a watch-universe screen match and should remain in the governed recommendation lane.

## Live sector-monitor findings

The sector monitor shows repeated values of `95` across many candidates. The payload identifies these as `watch_score_kind=strategy_qualified`; many rows also have:

- `thin_coverage=true`;
- `cio_view=null`;
- `analyst_opinions=null` or low counts;
- `origin_system=agent_discovery` or another discovery source.

These are broad filter/screen eligibility scores, not equal conviction, expected return or portfolio recommendations. Required UI terminology:

- `screen matches`, not `setups` or `stock recommendations`;
- `screen 95`, with a tooltip stating it is not conviction;
- visible `THIN COVERAGE` and `NO CIO VIEW` labels;
- only complete governed recommendation cards may carry `ADD ON PULLBACK`.

## Resulting PR #166 truth-label changes

The draft now:

1. states when the governed add book is empty;
2. labels leading/improving sectors without add cards as `RESEARCH WATCH`;
3. displays sector row `as_of` and flags stale rows;
4. warns on narrow sector participation;
5. distinguishes governed stock candidates from screen matches;
6. renames setup counts and buttons to screen-match terminology;
7. exposes thin coverage and missing CIO synthesis;
8. labels failed protective-put structures as withheld;
9. keeps model outputs in critique-only lanes;
10. leaves every execution and permission boundary unchanged.

## Remaining validation gates

- Render PR #166 against these live payloads at desktop and narrow widths.
- Verify the page does not overflow with actual long industry names and coverage chips.
- Correct breadth to exactly 20 distinct trading closes.
- Add full field-level source/freshness/quality metadata.
- Normalize industry/SPY windows or attach an explicit quality penalty.
- Replace capped movers internals before making full-market breadth claims.
- Reconcile effective sector totals and stale/missing fund look-through factsheets.
- Run a dated operator review of the 2026-07-18 defensive lean; do not auto-change it.
