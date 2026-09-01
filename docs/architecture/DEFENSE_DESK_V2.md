# Defense Desk v2 — Whole Market · Industries · The Rotation Picture (2026-07-18)

Status:      ACTIVE
as_of:       2026-07-18T00:18:51-04:00
Measured at: efcc51365 / not measured

Session 2 of the Defense Desk. Ships **A2 (market layer) + B2 (industry layer) + C2
(coverage completion) + D2 (design rebuild)**. E2 (the v1 engines: WS-B positioning,
WS-C move-out, WS-D2–D5 hedge/short desks) fell below the explicit cut line — see §E2.
Advisory/paper only; the page places nothing; 2FA/live gates untouched.

## WS-A2 — Whole-market layer (`sector_momentum_engine.py compute_market()`)
- **Indices**: SPY/QQQ/IWM/DIA — 5/20/60d returns + `rs_*` vs SPY (QQQ rs20 is the
  tech-lag cross-check; on go-live day QQQ rs20 −5.55 vs DIA +2.31).
- **Style spreads**: VUG−VTV (growth/value), IWM−SPY (small/large), RSP−SPY (equal/cap)
  — spread s5/s20/s60 + slope, classified by the SAME `classify()` quadrants and
  persisted as `STYLE:<key>` rows in `sector_momentum_state`, joining the identical
  2-close debounce/alert machinery as sectors.
- **Internals**: NH/NL + unusual-volume counts reused from `market_movers_latest.json`
  (top-15 caps per signal — labeled "top-15 capped", never exchange-wide claims).
- **`market_state_line()`**: one plain-English line, e.g. `Market: SPY -1.4% wk ·
  equal-weight leading cap-weight (+3.0% 20d) · small caps leading · NH/NL 15/15 —
  mixed tape · 4/11 sectors lagging`. Template unit-tested with synthetic inputs.
- Snapshot key `market` in `sector_momentum_latest.json`; served via existing
  `/api/v2/defense/posture`.

## WS-C2 — Coverage completion (the "—" cells)
Root cause was a **NAME MISMATCH, not thin coverage**: trade_ai_scans/finviz use
"Financial Services"/"Consumer Cyclical"/"Basic Materials"/"Consumer Defensive"/
"Communication Services" while the engine queried ETF-label names. Fixed with
`sector_aliases` in `config/sector_momentum.json` resolved by `_aliases()` →
`t.sector = ANY(%s)` in the breadth/Hermes/news queries. Post-fix: all 11 sectors show
breadth (22–78%, n=41–60) and Hermes pulse — zero "—" cells. Membership is 80–480
symbols/sector.

## WS-B2 — Industry layer (`scripts/finviz_industry_groups.py`)
- **Source**: `grp_export.ashx?g=industry&v=141` (144 industries × Perf W/M/Q/H/Y/YTD;
  v=152 lacks multi-period perf) through the shared `finviz_throttle` + FINVIZ_COOKIE.
  1 request/run, **2 runs/day** (cron 12:30 display refresh + 16:18 `--close`).
- **Quadrant mapping** (documented, same classify): level = perf_month − SPY 21-session
  return, direction = perf_week − SPY 5-session return.
- **States persist only on `--close`** into `industry_momentum_state` (PK as_of+industry)
  → one observation/session → the sector 2-close debounce applies unchanged.
- **Alert gating**: confirmed transitions alert ONLY when the industry intersects the
  held book or `operator_starred_symbols` (NOT watchlist_items — its 5,200+ actives
  would mark every industry "watched"), cap 3/day, Telegram prefix INDUSTRY MOMENTUM.
- **Candidate pools** (`source_type=industry_momentum`, advisory, never auto-trade):
  confirmed LAGGING worst-rel1w → defensive_short pool; IMPROVING best → watch rail.
- Fail-closed: <100 parsed groups aborts without touching state/snapshot.
- Snapshot `industry_momentum_latest.json` (~50KB) → `/api/v2/defense/industries`
  (separate endpoint — the Home strip polls `/defense/posture` and stays light).
- Industry→sector map = modal sector per industry from trade_ai_scans (2 unmapped:
  Lumber & Wood Production, Textile Manufacturing → "Other").

## WS-D2 — Page rebuild (`DefenseHub.tsx`)
- **RRG-style rotation scatter** (dependency-free SVG): x=RS20 (industries: rel1m),
  y=slope (rel1w), dot area ∝ book weight w/ min size, quadrant tints/labels matching
  `classify()`, Sectors|Industries toggle. Industries mode plots held/starred + 1w
  extremes (~30 dots) — the 144-dot cloud is unreadable.
- **Sector spine**: heatRamp()-colored cells (RS5/RS20/slope/breadth/HermesΔ),
  book-weight bars, row click = detail fold + industry drill-by-sector.
- **Industry fold**: top/bottom-1w strips, per-sector drill table (state rail, rel/perf
  heat cells, held/★ symbols), candidate pools rendered with advisory labels.
- **Confirmed-transitions timeline**: 30 sessions of debounce-confirmed chips (engine
  `--backfill` now emits a `confirmed` ledger via the same `fire()` rule) + live chips.
- **Would-have-fired fold is now DEBOUNCED** — raw un-debounced flips demoted to a
  footnote count (30 sessions: 89 raw flips → 64 confirmed; the filter absorbed 25
  single-day flickers).
- Zero raw hex — all colors from `watchTokens` (BB/T/heatRamp).

## §E2 — cut-line report
A2/B2/C2/D2 shipped and verified this session; **E2 fell below the line entirely** —
none of the v1 engines were started. All remain pre-verified viable (v1 diagnosis:
chains readable, short_float captured, paper short works, taxable margin VERIFIED).
Next Defense session picks up WS-B → WS-C → WS-D2–D5 in that order; the industry
LAGGING pool now already feeds D4's candidate list shape.

## Live verification (2026-07-18)
- State line + indices/styles/internals rendered from live data; tests
  `scripts/test_sector_momentum_debounce.py` v1 (6) + v2 (style-spread quadrants,
  state-line template) all pass.
- Industry first close-capture: 144 groups — 69 LEADING / 29 IMPROVING / 7 WEAKENING /
  39 LAGGING vs SPY (megacap-led selloff mechanically flips most equal-weight groups
  rel-positive — coherent with RSP−SPY LEADING). Bottom-1: **Computer Hardware rel1w
  −15.0, holding ANET, ★ SMCI** — the tech weakness localized to one book position.
- Playwright full-page screenshot: zero console errors, all folds render.

## Gotchas (new in v2)
- Held ETFs have extra repricer rows in ticker_prices — RS windows must date-intersect
  with SPY or they misalign (the false "warming up" on XLI/XLB).
- Fail-soft except blocks around per-sector queries MUST `conn.rollback()` or every
  later query dies InFailedSqlTransaction.
- Finviz groups: v=141 is the performance view; v=152 (valuation) lacks multi-period perf.
- Dispatcher envelope: `/api/v2/*` responses wrap payloads under `data` — curl checks
  must read one level down (useApi unwraps automatically).
- Cron entries need `cd` — caught a FIFTH time on this desk's midday entry.
