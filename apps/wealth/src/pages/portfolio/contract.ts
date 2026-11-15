// portfolio-holdings@2 — PROPOSED slice contract (owner cc-deepseek-6, reviewer cc-deepseek-8).
//
// STATUS: PROPOSED r3 (2026-11-15T00:4xZ, review REVIEW-PORTFOLIO-HOLDINGS-r2-cc-deepseek-8-20261115T0031Z
// applied: C1 measure provenance, C2 who derives the floor mark, C3 listed-vs-omitted and the `rowsRead` name
// collision, C4 a rendered count that did not add up, A1–A3). Still NOT APPROVED_FOR_WIRING (runbook step 5).
// Nothing in this folder reads /api.
//
// @2, not @1: C3 renames `Population.rowsRead` to `priceableRows` and C1 adds a required `verified` to every
// measure. A changed shape under an unchanged version number is the drift the version suffix exists to stop.
//
// Units are part of the contract and are the two traps measured on 2026-11-14:
//   * `portfolioPct` is already a PERCENT of the cash-inclusive book (30 wire rows sum 100.0). Never x100.
//   * `marketCapB` is in MILLIONS (holdings wire `market_cap_b`). Format by dividing by 1000 for B;
//     never multiply by 1e6 into dollars.
//
// The client renders; it does not compute. Every dollar, percent, count, total and verdict below is a SERVED
// field. The page never derives a value from shares x price, never derives a P/L, never scores a security, and
// NEVER sums rows to make a total — `accounts[]` exists so that no renderer has to.
//
// Missing is not zero: an absent measure is `null` plus a reason, and renders as "N/A — <reason>". An unpriced
// row is `marketValue: null`, not `$0.00`; a zero-value delisted row is `worthless: true`, which is a fact, not
// an absence.

import type { ValuationAssessment } from '../../contracts/valuation'

export const PORTFOLIO_HOLDINGS_CONTRACT_VERSION = 'portfolio-holdings@2' as const

/** Where the book came from. A FIXTURE book must be labelled as synthetic wherever it renders. */
export type BookSource = 'FIXTURE' | 'LIVE'

export type RowKind = 'SECURITY' | 'CASH'

/** A clock the producer declares. UNKNOWN is a real, renderable state — never a missing one. */
export interface DeclaredClock {
  status: 'KNOWN' | 'UNKNOWN'
  at: string | null
  reason: string
}

/**
 * Every clock the producer declares. The build clock is the trap: on today's wire the positions clock and the
 * document build clock differ by a day, so a single unlabeled `asOf` would let an adapter age the book from the
 * wrong one.
 *
 * Mapping from the wire's `clock_provenance` keys (A2): `positions` → POSITIONS, `position_list` → BUILD,
 * `valuation` → VALUATION, `quote` → QUOTE, `stops` → STOPS; `day_pnl` is not a clock role here — it stays the
 * separate `dayPnl` field, because the wire declares the day-change clock UNKNOWN rather than dating it.
 * REQUEST is not a source clock: it is the response's own render time (`clock_provenance.rendered_at`), declared
 * in the clock ledger as "Rendered at" only when the wire serves it. It is never a freshness input. UNDECLARED is
 * the absence of a role: an `asOf` that no declared clock dates is labelled so, never dressed as a producer clock.
 *
 * POSITIONS is an AGGREGATION over the rows, not a single instant: the wire marks it `mixed: true` and carries
 * `oldest_known_as_of` / `newest_known_as_of` / `unknown_rows`. `at` is the aggregate the producer publishes
 * (its documented rule: the oldest known row, unknown if any row lacks a declared instant), and the disclosure
 * is carried alongside rather than flattened away.
 */
export type ClockRole = 'POSITIONS' | 'BUILD' | 'QUOTE' | 'VALUATION' | 'STOPS' | 'REQUEST' | 'UNDECLARED'

export interface ClockProvenance {
  role: ClockRole
  at: string | null
  source: string
  /** True for the document build clock — always identified, never inferred from the latest timestamp. */
  isBuildClock: boolean
  /** The wire's `mixed` for an aggregated role (POSITIONS). Absent means not stated, not false. */
  mixed?: boolean
  /** Rows an aggregated clock could not date (`unknown_rows`). Absent means not stated. */
  unknownRows?: number
  /**
   * The producer's datum that it WITHHELD as this clock (`last_read_as_of`), served when the clock cannot stand
   * for the book — today the stop read, when a displayed account has no dated broker read. It is diagnosis, not
   * the clock: the ledger prints it under its own label ("not the book's clock") rather than in the `at` slot,
   * so a withheld datum never becomes an age the page then ages the book from. Absent means nothing was withheld.
   */
  withheldAsOf?: string | null
}

export type ProtectionState = 'PROTECTED' | 'GAP' | 'UNKNOWN'

/**
 * Protection as served: the state, the resting stop if there is one, the basis that produced it and the
 * clock of the broker stop read. `nextStep` is always present so the row is actionable, not just coloured.
 */
export interface Protection {
  state: ProtectionState
  stop: number | null
  basis: string | null
  asOf: string | null
  /**
   * This ROW's own staleness, from its own clock (wire `protection_stale`). `null` means no clock applies — exempt,
   * or a clock that never dated the row's observation. It is never the book-wide stop-read flag.
   *
   * Part of this row's protection VERDICT, not a decoration: it ships as a sibling key of `protection` only
   * because the pinned LQ-2708 wire fixture compares `protection` byte-exactly. Moving it inside that object is
   * therefore a deliberate contract revision (fixture regeneration + a re-check of the old-site page test), never
   * a tidy-up.
   */
  stale: boolean | null
  nextStep: string
  reason: string
}

/**
 * Fibonacci retracement of the stored 52-week range — the honest label for what the wire's `fib` is.
 * This is NOT support/resistance: no pivot, support, resistance or timeframe field is served on any row.
 */
export interface FibLadder {
  method: 'FIB_52W_RANGE'
  levels: { ratio: number; price: number }[]
  nearestLevel: number | null
  retracementFromHighPct: number | null // percent
  window: { high: number; low: number; asOf: string }
}

export interface HoldingsRow {
  /** Stable key: `${accountKey}:${symbol}` — the same key valuation-assessment@1 uses. */
  accountKey: string
  accountLabel: string
  symbol: string
  name: string
  kind: RowKind
  shares: number
  price: number | null
  priceAsOf: string | null
  /** Remaining basis / remaining shares — not first-entry cost. Null when the producer has none. */
  avgCost: number | null
  /**
   * Null when the row is UNPRICED — the wire has a designed `unpriced` scope, and 28 of 33 priceable rows are
   * measured today. A null here renders "N/A — unpriced", never $0.00. A genuine zero (a delisted holding kept
   * at zero value) is `0` with `worthless: true`.
   */
  marketValue: number | null
  gainLoss: number | null
  gainLossPct: number | null // percent
  /** PERCENT of the cash-inclusive book. */
  portfolioPct: number
  dayChange: number | null
  dayChangePct: number | null
  marketCapB: number | null // MILLIONS
  yieldPct: number | null // percent; null = not published
  /**
   * C2: this is ADAPTER-DERIVED, not a producer mark. The wire marks no row with a floor flag — it serves the
   * floor (`min_position_usd`), each row's `market_value`, and two counts (`non_cash_over_100`,
   * `held_under_100`). The adapter compares `marketValue < floorUsd` once, here, and the invariant in
   * `fixtureInvariants.ts` is that comparison's definition. An unpriced row is never "below": unknown is not
   * under the floor.
   */
  belowFloor: boolean
  /** A held security the producer keeps at zero value (delisted / worthless). A fact, not an absence. */
  worthless: boolean
  /** Null only for rows where protection does not apply (cash). */
  protection: Protection | null
  /**
   * The wire's `asset_type`, as served (EQUITY / ETF / MUTUAL_FUND / CASH …), or null when the row omits it.
   * Row-level, not inside `fundamentals`: a cash row and an unenriched row carry no fundamentals block, and
   * the sector rule still has to know a row is a fund (contract r6 §5 binds `asset_type`).
   */
  assetType: string | null
  /**
   * The wire's `profile_source` — where the row's classification came from. `'unavailable'` is a provenance
   * verdict: the classification could not be sourced, so the carried `sector` text must not be read as one
   * (contract r6 §5, R6e). Null when the wire did not serve the field.
   */
  profileSource: string | null
  /** The wire's `profile_updated_at`, an ISO instant, or null when not served. A clock, not a verdict. */
  profileUpdatedAt: string | null
  /** Null for a cash row, and for a security the enrichment never reached. Every field served or null. */
  fundamentals: RowFundamentals | null
  fib: FibLadder | null
  valuation: ValuationAssessment | null
}

/**
 * The fundamentals the wire actually serves on each row, carried as served.
 *
 * Two rules this shape keeps:
 *   * `peTrailing` / `peForward` are the wire's bare `pe` / `forward_pe` MULTIPLES. They are NOT a
 *     valuation-assessment@1 assessment, so they carry no status and claim none: a cell prints the multiple
 *     and says it is a served multiple, not an assessment. Turning a bare number into ASSESSED would be the
 *     claim that contract forbids.
 *   * Nothing here is derived. A field the wire omits is `null` and renders "N/A — <reason>"; no EPS is
 *     computed from price / pe, no growth rate from two EPS values.
 *
 * `marketCapB` and `yieldPct` stay on the row (the table already renders them); they are deliberately NOT
 * duplicated here.
 */
export interface RowFundamentals {
  sector: string | null
  industry: string | null
  /** Wire `pe` — a served multiple, not an assessment. */
  peTrailing: number | null
  /** Wire `forward_pe` — a served multiple, not an assessment. */
  peForward: number | null
  /** Wire `eps_ttm`, in dollars per share as published. */
  epsTtm: number | null
  /** Wire `eps_next_y` — the provider's next-year estimate, not a measurement. */
  epsNextY: number | null
  peg: number | null
  beta: number | null
  /** Wire `perf_ytd_pct` — percent, as the provider publishes it. */
  perfYtdPct: number | null
  rsi: number | null
  sma20Pct: number | null
  sma50Pct: number | null
  sma200Pct: number | null
  /** Wire `week52_high_pct` — percent below the 52-week high, as served. Not support/resistance. */
  week52HighPct: number | null
  shortFloatPct: number | null
  insiderOwnPct: number | null
  instOwnPct: number | null
  /** Wire `analyst_rating`; a provider label, rendered as text with no colour verdict. */
  analystRating: string | null
}

export interface HoldingsCounts {
  allRows: number
  nonCash: number
  cash: number
  nonCashOverFloor: number
  /** C2: the producer's own under-floor count (wire `holdings.held_under_100`), carried beside the over count. */
  heldUnderFloor: number
  /** Which population the header count names. A count without its scope is a defect. */
  primaryScopeLabel: string
}

/**
 * Rows the producer READ AND RENDERED but did not COUNT — the wire's `scope_coverage.excluded`, which means the
 * opposite of an omission. Today: `{reason: "priced under $100: listed, not counted", count, scope:
 * "holdings.held_under_100"}`. These rows are in the table; they are simply outside the counted population.
 * They are carried HERE, not in `Population.excluded`, so that "omitted" can never be printed about a row the
 * reader can see (C3).
 */
export interface ListedNotCounted {
  reason: string
  count: number
  /** The wire's own population name, so the count keeps its scope. */
  scope: string
}

/**
 * The read-side population, stated rather than collapsed into a count.
 *
 * Two populations, and they must not be merged:
 *   * `excluded` = rows REMOVED before the counters (the wire reads 30 rows after a filter dropped three dead
 *     CUSIPs from a priceable population of 33). Only removals belong here — the arithmetic
 *     `priceableRows − renderedRows == Σ excluded` is what makes the gap renderable ("3 omitted").
 *   * `listedNotCounted` = rows that ARE rendered and are outside the counted scope.
 */
export type ExclusionKind = 'DEAD_CUSIP_ZERO_VALUE' | 'OTHER'

export interface PopulationExclusion {
  kind: ExclusionKind
  label: string
  count: number
  /** The rule that removed them, in the producer's words. */
  rule: string
}

export interface Population {
  /**
   * C3: rows the producer read before its read-side filter, from `scope_coverage.priceable.row_count` (33).
   * Deliberately NOT called `rowsRead`: the wire has its own `scope_coverage.rows_read` — 30, the post-filter
   * number — and an adapter reading this field by name would take 30 and report a 0 gap.
   */
  priceableRows: number
  /** Rows in this book; must equal `rows.length`. */
  renderedRows: number
  /** Removals only — never the listed-not-counted population. */
  excluded: PopulationExclusion[]
  listedNotCounted: ListedNotCounted[]
  /** The wire's `min_position_usd`, so the "over floor" count has a population to be checked against. */
  floorUsd: number | null
}

/**
 * Per-account totals as the PRODUCER publishes them. `null` means the producer served no totals block —
 * render nothing rather than summing rows. Summing rows is forbidden: the served payload omits `accounts`
 * today, while the document build constructs `total_usd`/`cash_usd` per account.
 */
export interface AccountTotal {
  accountKey: string
  accountLabel: string
  totalUsd: number | null
  cashUsd: number | null
  asOf: string | null
  source: string
}

export type MeasureStatus = 'MEASURED' | 'UNKNOWN'

/**
 * One of the four governed book measures.
 *
 * C1.3: nothing here is one block "carried verbatim". TWO wire blocks have to be joined by the adapter:
 *   * `measures.measures{}` — value, label, basis and clock;
 *   * `data.metrics[]`, keyed `portfolio.<id>` — `verified` and the receipt id. Today all four entries are
 *     `verified: false, receipt: null`; the ledger publishes no receipt for any of them.
 * An adapter that carries only the first block will render four receipts that do not exist.
 *
 * C1.2: the wire is not uniform, so the mapping is stated per measure:
 *   * `account_value` publishes `basis` + `finviz_estimate` and NO `definition` — `definition` here is the
 *     served `basis`, quoted;
 *   * `account_value_change_1d` carries no `as_of` of its own — its clock is `end.as_of`;
 *   * `verified_daily_pnl` states its reason in `gap.reason`, not `reason`.
 *
 * C1.1: the rule the ledger actually holds is MEASURED ⇒ value + clock; VERIFIED ⇒ receipt. "Measured" is not
 * "verified", and a MEASURED measure with `verified: false` is the normal case on this read. One measure
 * (`verified_daily_pnl`) is UNKNOWN and must stay UNKNOWN — it is not a zero and not a fallback.
 */
export interface BookMeasure {
  id: 'account_value' | 'price_move_estimate' | 'account_value_change_1d' | 'verified_daily_pnl'
  label: string
  /** The wire's `definition`, or its `basis` where the wire publishes no definition (see per-measure mapping). */
  definition: string
  status: MeasureStatus
  valueUsd: number | null
  /** From `data.metrics[].verified`. False means measured-but-not-verified, never unknown. */
  verified: boolean
  /** From `data.metrics[].receipt`; null today for every measure, and required once `verified` is true. */
  receiptId: string | null
  asOf: string | null
  reason: string
}

export interface HoldingsSession {
  status: 'KNOWN' | 'UNKNOWN'
  phase: string | null
  latestOpenSession: string | null
  asOf: string | null
  /** Where the session label came from. The rows carry none, so the source is part of the claim. */
  source: string | null
  reason: string
}

/** The producer's ONE freshness verdict, computed from the SOURCE-observation clocks (wire `data.freshness`). */
export interface ServedFreshness {
  /** FRESH | STALE over the source clocks; UNKNOWN when a clock cannot be dated (unknown beats wrong). */
  status: 'FRESH' | 'STALE' | 'UNKNOWN'
  /** Served verdict; `null` alongside UNKNOWN — an undatable book is not a fresh one, and not a stale one either. */
  stale: boolean | null
  /** The clock the verdict is about (`positions` | `quote` | `stops`), or `null` when it could not be computed. */
  clock: string | null
  /** The role label for that clock, e.g. "QUOTE" — the label the page prints, never a literal. */
  clockLabel: string | null
  /** When that clock last observed the book. Not the read, not the render, not the cache. */
  asOf: string | null
  ageSeconds: number | null
  /** The registry limit the verdict applied (`config/data_source_authority.json`), not the cache window. */
  limitSeconds: number | null
  /** Where that limit came from, so a printed limit names its source. */
  limitSource: string | null
  window: 'open' | 'closed' | null
  rule: string | null
  /** Why the verdict could not be computed, when it could not. */
  gap: string | null
}

export interface HoldingsFreshness {
  /**
   * The producer's verdict over its SOURCE clocks, or `null` when the wire served none (an older producer).
   * Judge currency by this. The four fields below are the RESPONSE's cache facts, not the book's clocks.
   */
  served: ServedFreshness | null
  /** The served cache age, or `null` when the response did not serve one. Never 0 to stand in for "unknown". */
  ageSeconds: number | null
  /**
   * The served stale-after limit in seconds, or `null` when `evidence.portfolio.clocks.stale_after_hours` was not
   * served. Never 0 to stand in for "unknown" — the page says "limit not served"; a served 0 stays a served 0.
   */
  staleAfterSeconds: number | null
  /**
   * The CACHE verdict: was this body built inside the cache window? A false value is a claim of freshness, so only
   * a served `stale: false` may produce one. It is the fallback when no source-clock verdict is served — never a
   * substitute for `served`.
   */
  stale: boolean
  /**
   * Whether the response carried a freshness annotation at all. `false` means `stale` is an ASSUMPTION the adapter
   * made, not a verdict the producer published — the page says so instead of attributing it to a block that is absent.
   */
  blockPresent: boolean
  /** True when THIS PAGE withdrew the claim (a failed read, or one whose currency could not be proven). */
  withdrawn: boolean
}

export interface HoldingsBook {
  contract: typeof PORTFOLIO_HOLDINGS_CONTRACT_VERSION
  source: BookSource
  /** The clock the freshness is measured from; `asOfClock` says which declared clock that is. */
  asOf: string
  asOfClock: ClockRole
  clocks: ClockProvenance[]
  rows: HoldingsRow[]
  counts: HoldingsCounts
  population: Population
  accounts: AccountTotal[] | null
  measures: BookMeasure[]
  session: HoldingsSession
  freshness: HoldingsFreshness
  /** The wire has no per-row observation clock for day change; it declares that, and so do we. */
  dayPnl: DeclaredClock
  /** One sentence naming what the rows are and what they exclude. Rendered, never hidden. */
  coverageNote: string
}
