// The adapter: GET /api/v2/portfolio/holdings (served, R13 3ac0b4058) → portfolio-holdings@2.
//
// It is a PURE function over the payload's `data` object and a `now` in ms. It never fetches, never writes, never
// throws on a malformed payload (a render must not crash), and never computes a value the wire did not serve —
// with exactly one stated exception, `belowFloor` (C2), which the wire does not mark and which the contract
// defines here. Everything else is a rename, a unit label, or an honest `null` with the reason recorded.
//
// Why some contract fields are null on this read, stated rather than hidden (see README §"Adapter gaps"):
//   * `fib` — the wire serves a ladder but NO clock for it; FibLadder.window.asOf is required, and using the quote
//     clock would label a clock the producer never declared for the ladder. Reported absent, never mislabelled.
//   * `valuation` — valuation-assessment@1 is not wired on this route; the row's bare `pe`/`forward_pe` numbers
//     are NOT an assessment, and turning one into a status would be the exact claim that contract forbids.
//   * `accounts[].cashUsd` — the reconciliation block serves per-account ending equity, not per-account cash.
//
// The two wire shapes that are easy to get wrong, both pinned by a planted-payload test:
//   1. `scope_coverage.excluded` is the "listed, not counted" population (under the floor), NOT rows removed
//      before the counters. Removals have to be recovered as `priceable.row_count − rendered_rows` and labelled
//      as a rule the producer does not state (C3).
//   2. `priceableRows` is `scope_coverage.priceable.row_count` (33), never `scope_coverage.rows_read` (30).
//      Taking rows_read renders a 0-row gap for a book that read 33 and rendered 30.

import type {
  AccountTotal, BookMeasure, BookSource, ClockProvenance, ClockRole, DeclaredClock, FibLadder, HoldingsBook,
  HoldingsCounts, HoldingsFreshness, HoldingsRow, HoldingsSession, ListedNotCounted, Population,
  PopulationExclusion, Protection, ProtectionState, RowFundamentals, RowKind, ServedFreshness, ServedIdentity,
} from './contract'
import { PORTFOLIO_HOLDINGS_CONTRACT_VERSION } from './contract'
import { accountDisplayLabel } from './accountLabel'
import { attachDisplayIdentity, nameSourceFrom } from './displayIdentity'

export interface AdaptResult {
  book: HoldingsBook | null
  /** Non-null when the payload cannot be a book. The page then shows ERROR, not a table of nulls. */
  error: string | null
}

type Json = Record<string, unknown>

const isObj = (v: unknown): v is Json => v !== null && typeof v === 'object' && !Array.isArray(v)
const asObj = (v: unknown): Json => (isObj(v) ? v : {})
const asArr = (v: unknown): unknown[] => (Array.isArray(v) ? v : [])
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: unknown): string | null => (typeof v === 'string' && v.length > 0 ? v : null)

/** A clock role from `clock_provenance`. `position_list` is the DOCUMENT build clock — see contract's trap. */
const CLOCK_ROLES: { key: string; role: ClockProvenance['role']; build: boolean }[] = [
  { key: 'positions', role: 'POSITIONS', build: false },
  { key: 'position_list', role: 'BUILD', build: true },
  { key: 'quote', role: 'QUOTE', build: false },
  { key: 'valuation', role: 'VALUATION', build: false },
  // The stop-read observation clock: one of the three clocks the served freshness verdict is computed from.
  { key: 'stops', role: 'STOPS', build: false },
]

function clocksFrom(wire: Json): ClockProvenance[] {
  const cp = asObj(wire.clock_provenance)
  const out: ClockProvenance[] = []
  for (const { key, role, build } of CLOCK_ROLES) {
    const c = asObj(cp[key])
    const mixed = typeof c.mixed === 'boolean' ? c.mixed : undefined
    const unknownRows = num(c.unknown_rows)
    // The producer publishes `last_read_as_of` when it WITHHELD its read stamp as the book's clock (partial
    // account coverage). Carried only when `as_of` is absent: if the clock stands, the datum IS the clock and
    // printing it twice would read as two clocks.
    const withheld = str(c.as_of) === null ? str(c.last_read_as_of) : null
    out.push({
      role,
      at: str(c.as_of),
      source: str(c.source_field) ?? key,
      isBuildClock: build,
      ...(mixed === undefined ? {} : { mixed }),
      ...(unknownRows === null ? {} : { unknownRows: unknownRows as number }),
      ...(withheld === null ? {} : { withheldAsOf: withheld }),
    })
  }
  // R5 (review 2026-11-15T040420Z): the response's own render time, declared when the wire serves it, under
  // REQUEST — the role the page labels "Rendered at". It is never a source clock, so it is not in CLOCK_ROLES:
  // an older body that serves no `rendered_at` gains no clock it does not have.
  const rendered = asObj(cp.rendered_at)
  if (str(rendered.as_of) !== null) {
    out.push({ role: 'REQUEST', at: str(rendered.as_of), source: str(rendered.source_field) ?? 'rendered_at',
      isBuildClock: false })
  }
  return out
}

/** Wire protection is per row but serves no stop price: `stops_read` publishes counts only. */
const NEXT_STEP: Record<string, string> = {
  'No Stop Read': 'read this account’s working orders at the broker; until then protection is UNKNOWN',
  'Not Protected': 'place a stop if this position is meant to be protected',
  'No position': 'none — the broker holds no position for this row',
}

function protectionFrom(wire: Json, state: string | null): Protection | null {
  if (state === 'EXEMPT') return null
  const p = asObj(wire.protection)
  const wireState = str(p.state) ?? state
  const mapped: ProtectionState =
    wireState === 'PROTECTED' ? 'PROTECTED' : wireState === 'GAP' || wireState === 'NOT_PROTECTED' ? 'GAP' : 'UNKNOWN'
  const cause = str(p.cause)
  // The wire carries no per-row resting stop price on this route (stops_read publishes counts only).
  const stop = num(p.stop)
  // RC1 (review 2026-11-15T1745Z): the default next step may not claim a stop "is served" when no stop price was
  // served. A PROTECTED row served without a price renders "pending activation — stop price not served" beside the
  // next step, so this sentence says recorded, not served; the two never contradict. A served price keeps the
  // served wording.
  const protectedDefault = stop !== null
    ? 'none — a resting stop is served for this row'
    : 'none — a resting stop is recorded for this row; its price is not served'
  return {
    state: mapped,
    stop,
    basis: str(p.source) ?? null,
    asOf: str(p.as_of),
    // F-7: this row's OWN clock, as the producer publishes it. `stops_read.stale` is the BOOK's summary flag and
    // is never copied onto a row. A missing per-row flag stays null (no clock applies), never false.
    stale: typeof wire.protection_stale === 'boolean' ? wire.protection_stale : null,
    nextStep: (cause !== null ? NEXT_STEP[cause] : undefined) ?? (mapped === 'PROTECTED'
      ? protectedDefault
      : 'read this account’s working orders; the route serves no per-row stop price'),
    reason: str(p.reason) ?? `producer state ${wireState ?? 'missing'}`,
  }
}

/** Wire `analyst_rating` is either a label or a number; carry it as text and claim no verdict. */
const ratingText = (v: unknown): string | null =>
  typeof v === 'string' && v.length > 0 ? v : typeof v === 'number' && Number.isFinite(v) ? String(v) : null

/**
 * The served fundamentals, as served. A cash row has none (there is no issuer behind a cash sweep), and a
 * security whose enrichment never ran carries all-null rather than zeros — an absent P/E is not a P/E of 0.
 */
function fundamentalsFrom(wire: Json, kind: RowKind): RowFundamentals | null {
  if (kind === 'CASH') return null
  const f: RowFundamentals = {
    sector: str(wire.sector),
    industry: str(wire.industry),
    peTrailing: num(wire.pe),
    peForward: num(wire.forward_pe),
    epsTtm: num(wire.eps_ttm),
    epsNextY: num(wire.eps_next_y),
    peg: num(wire.peg),
    beta: num(wire.beta),
    perfYtdPct: num(wire.perf_ytd_pct),
    rsi: num(wire.rsi),
    sma20Pct: num(wire.sma20_pct),
    sma50Pct: num(wire.sma50_pct),
    sma200Pct: num(wire.sma200_pct),
    week52HighPct: num(wire.week52_high_pct),
    shortFloatPct: num(wire.short_float_pct),
    insiderOwnPct: num(wire.insider_own_pct),
    instOwnPct: num(wire.inst_own_pct),
    analystRating: ratingText(wire.analyst_rating),
  }
  // All-null is the honest "the enrichment never reached this row": keep it as a stated absence, not a block
  // of zeroes the page would have to disbelieve field by field.
  return Object.values(f).every(v => v === null) ? null : f
}

/**
 * The wire's `identity` block, passed through (spec R5). No route serves one today; when one does, the server has
 * already resolved it, and the client only reads the verdict. Only the shape R5 defines is accepted — status
 * `CONFIRMED` is the sole admitting value and `cusip` the sole basis — so an unreadable block is `null`, and a
 * `CONFIRMED` verdict still has to survive the resolver's identifier-length check before it names anything (R8).
 */
function servedIdentityFrom(v: unknown): ServedIdentity | null {
  if (!isObj(v)) return null
  if (str(v.basis) !== 'cusip') return null
  return {
    status: str(v.status) === 'CONFIRMED' ? 'CONFIRMED' : 'UNVERIFIED',
    name: str(v.name),
    basis: 'cusip',
    identifier: str(v.identifier),
  }
}

function rowFrom(wire: Json, floorUsd: number | null): HoldingsRow | null {
  const symbol = str(wire.symbol)
  if (symbol === null) return null
  const isCash = wire.is_cash === true || str(wire.asset_type) === 'CASH'
  const kind: RowKind = isCash ? 'CASH' : 'SECURITY'
  const shares = num(wire.shares) ?? num(wire.quantity) ?? 0
  const marketValue = num(wire.market_value)
  const basisTotal = num(wire.cost_basis_total)
  const avgServed = num(wire.avg_cost)
  // avgCost is remaining basis / remaining shares (contract). Prefer the served per-share basis; fall back to the
  // served total divided by the served shares. A 0.0 from a row that declares NO basis source is "no basis served",
  // not a $0.00 cost — the wire uses 0.0 for both, and only `cost_basis_source` tells them apart.
  const hasBasisSource = str(wire.cost_basis_source) !== null
  const avgCost = avgServed !== null && (avgServed !== 0 || hasBasisSource)
    ? avgServed
    : basisTotal !== null && basisTotal !== 0 && shares > 0
      ? basisTotal / shares
      : null
  const accountKey = str(wire.account_key) ?? str(wire.account_id) ?? str(wire.account) ?? ''
  return {
    accountKey,
    accountLabel: str(wire.account_label) ?? str(wire.account) ?? accountKey,
    symbol,
    name: str(wire.name) ?? str(wire.company) ?? symbol,
    // The identity inputs beside the unchanged `name` (spec R2/R5, additive): the two raw sources, the ladder
    // branch `name` came from, and the server-resolved verdict when a route serves one. `name` itself stays byte-
    // identical so Holdings search and the selector's consumers keep today's results (R7); display reads
    // `identity`, attached once per symbol after the rows are built.
    nameRaw: str(wire.name),
    companyName: str(wire.company),
    nameSource: nameSourceFrom(str(wire.name), str(wire.company), symbol),
    servedIdentity: servedIdentityFrom(wire.identity),
    kind,
    shares,
    price: num(wire.price) ?? num(wire.current_price),
    priceAsOf: str(wire.price_as_of),
    avgCost,
    marketValue,
    gainLoss: num(wire.gain_loss),
    gainLossPct: num(wire.gain_loss_pct),
    // Percent of the cash-inclusive book, served. A missing weight is 0 only because the contract's field is a
    // number; it is counted as a malformed cell so the coverage note can say so.
    portfolioPct: num(wire.portfolio_pct) ?? 0,
    dayChange: num(wire.day_change),
    dayChangePct: num(wire.day_change_pct),
    marketCapB: num(wire.market_cap_b),
    yieldPct: num(wire.yield_pct),
    // C2: the one adapter-DERIVED field. An unpriced row (null) is never "below the floor": unknown is not under.
    belowFloor: marketValue !== null && floorUsd !== null && marketValue < floorUsd,
    worthless: kind === 'SECURITY' && marketValue === 0,
    protection: kind === 'CASH' ? null : protectionFrom(wire, str(wire.protection_state)),
    // The classification's own provenance, carried at the row level (contract r6 §5 binds these three on the
    // row). `asset_type` decides whether a row is a fund; `profile_source: 'unavailable'` says the carried
    // sector label could not be sourced. None of the three is derived here.
    assetType: str(wire.asset_type),
    profileSource: str(wire.profile_source),
    profileUpdatedAt: str(wire.profile_updated_at),
    fundamentals: fundamentalsFrom(wire, kind),
    // Served but clockless (README §Adapter gaps): reported absent rather than given a clock it does not have.
    fib: null as FibLadder | null,
    valuation: null,
  }
}

function measuresFrom(wire: Json): BookMeasure[] {
  const block = asObj(asObj(wire.measures).measures)
  const metrics = asArr(wire.metrics).filter(isObj)
  const out: BookMeasure[] = []
  for (const id of ['account_value', 'price_move_estimate', 'account_value_change_1d', 'verified_daily_pnl'] as const) {
    const m = asObj(block[id])
    const metric = metrics.find(x => str(x.metric_id) === `portfolio.${id}`)
    const status = str(m.status) === 'MEASURED' ? 'MEASURED' : 'UNKNOWN'
    const verified = metric !== undefined && metric.verified === true
    const receiptId = metric !== undefined ? str(metric.receipt) : null
    const asOf =
      str(m.as_of) ??
      str(asObj(m.end).as_of) ??
      str(asObj(m.start).as_of) ??
      (status === 'MEASURED' ? str(asObj(wire.measures).as_of) : null)
    out.push({
      id,
      label: str(m.label) ?? id,
      // account_value publishes `basis` and no `definition`; the contract quotes the basis there (C1.2).
      definition: str(m.definition) ?? str(m.basis) ?? '',
      status,
      valueUsd: num(m.value),
      verified,
      receiptId,
      asOf,
      reason:
        status === 'UNKNOWN'
          ? (str(asObj(m.gap).reason) ?? str(m.reason) ?? `the producer reports ${str(m.status) ?? 'no status'}`)
          : verified
            ? ''
            : 'measured, not verified — the ledger publishes no receipt for this measure',
    })
  }
  return out
}

function populationFrom(wire: Json, renderedRows: number, coverage: string[]): Population {
  const sc = asObj(wire.scope_coverage)
  const priceable = asObj(sc.priceable)
  const priceableRows = num(priceable.row_count) ?? renderedRows
  const excluded: PopulationExclusion[] = []
  const gap = priceableRows - renderedRows
  if (gap > 0) {
    excluded.push({
      kind: 'OTHER',
      label: 'read and not rendered',
      count: gap,
      rule: 'the producer publishes the gap (scope_coverage.priceable.row_count − rendered_rows) but no rule for it: scope_coverage.filtered_rows is null and findings is empty',
    })
  } else if (gap < 0) {
    coverage.push(`rendered ${renderedRows} rows from a population the producer sized at ${priceableRows}`)
  }
  const listedNotCounted: ListedNotCounted[] = asArr(sc.excluded).filter(isObj).map(e => ({
    reason: str(e.reason) ?? 'listed, not counted',
    count: num(e.count) ?? 0,
    scope: str(e.scope) ?? 'unstated',
  }))
  return { priceableRows, renderedRows, excluded, listedNotCounted, floorUsd: num(sc.min_position_usd) }
}

function countsFrom(wire: Json, rows: HoldingsRow[], coverage: string[]): HoldingsCounts {
  const scopes = asObj(asObj(wire.scope_coverage).scopes)
  const cash = rows.filter(r => r.kind === 'CASH').length
  const nonCash = rows.length - cash
  const allRows = num(scopes['holdings.all_rows']) ?? rows.length
  if (allRows !== rows.length) coverage.push(`the producer counts ${allRows} rows and the payload lists ${rows.length}`)
  return {
    allRows,
    nonCash: num(scopes['holdings.non_cash']) ?? nonCash,
    cash: num(scopes['holdings.cash']) ?? cash,
    nonCashOverFloor: num(scopes['holdings.non_cash_over_100']) ?? 0,
    heldUnderFloor: num(scopes['holdings.held_under_100']) ?? 0,
    primaryScopeLabel: 'holdings · non-cash rows priced at or above the notional floor',
  }
}

function sessionFrom(wire: Json): HoldingsSession {
  const labelled = asArr(wire.holdings).filter(isObj).map(r => str(r.market_session)).filter((s): s is string => s !== null)
  const distinct = Array.from(new Set(labelled))
  if (distinct.length === 1 && asArr(wire.holdings).length === labelled.length) {
    return { status: 'KNOWN', phase: distinct[0], latestOpenSession: null, asOf: null, source: 'holdings[].market_session', reason: '' }
  }
  const total = asArr(wire.holdings).length
  return {
    status: 'UNKNOWN',
    phase: null,
    latestOpenSession: null,
    asOf: null,
    source: 'holdings[].market_session',
    reason: labelled.length === 0
      ? `no row declares a market session (${total} rows): the route publishes no session field`
      : `${labelled.length} of ${total} rows carry a session label (${distinct.join(', ')}): one row's label is not the book's session`,
  }
}

// Exported for the gate test only: the label join's preference (`account_key` before `account`) is a
// behaviour of this call site, not of the helper, so a helper-only test cannot pin it (cc-deepseek-3's
// mutant M-B keys on `account` alone and stays green at 62/62; the live payload's `schwab_roth` rows
// carry `account_key: 'schwab_roth_ira'`). shell-logic.test.mjs compiles this module and calls it.
export function accountsFrom(wire: Json): AccountTotal[] | null {
  const rec = asObj(wire.reconciliation)
  const list = asArr(rec.accounts).filter(isObj)
  if (list.length === 0) return null
  // The display label for the same account is served on the holdings rows of this payload, not on this block:
  // join it here rather than render the raw key (lead finding, 2026-11-15T05:09Z; accountLabel.ts).
  const rowLabels = new Map<string, string>()
  for (const r of asArr(wire.holdings)) {
    const row = asObj(r)
    const rowKey = str(row.account_key) ?? str(row.account)
    const rowLabel = str(row.account_label)
    if (rowKey !== null && rowLabel !== null && !rowLabels.has(rowKey)) rowLabels.set(rowKey, rowLabel)
  }
  return list.map(a => {
    const end = asObj(a.end_equity)
    const key = str(a.account) ?? ''
    return {
      accountKey: key,
      accountLabel: accountDisplayLabel(key, str(a.account_label), rowLabels.get(key) ?? null),
      totalUsd: num(end.value_usd),
      // The reconciliation serves ending equity per account, not cash per account; null, never 0.
      cashUsd: null,
      asOf: str(end.as_of),
      source: str(end.source) ?? 'reconciliation.accounts[].end_equity',
    }
  })
}

function dayPnlClock(wire: Json): DeclaredClock {
  const d = asObj(asObj(wire.clock_provenance).day_pnl)
  const at = str(d.as_of)
  if (str(d.status) === 'KNOWN' && at !== null) return { status: 'KNOWN', at, reason: '' }
  return { status: 'UNKNOWN', at: null, reason: str(asObj(d.gap).reason) ?? 'the producer declares no day-change clock' }
}

/** Clock role named by the served verdict's `clock` key, or null when the producer served none. */
const FRESHNESS_CLOCK_ROLE: Record<string, ClockRole> = { positions: 'POSITIONS', quote: 'QUOTE', stops: 'STOPS' }

/**
 * The producer's ONE freshness verdict (F-2/F-3/F-5), or null when this producer serves none.
 *
 * It is computed from the source-observation clocks against the registry limit — not from the cache window and
 * not from `truth.stale`. `stale` is only a boolean when a verdict was actually computed: an UNKNOWN book is
 * neither fresh nor stale, and must never be shown as either.
 */
function servedFreshness(wire: Json): ServedFreshness | null {
  const f = asObj(wire.freshness)
  const status = str(f.status)
  if (status !== 'FRESH' && status !== 'STALE' && status !== 'UNKNOWN') return null
  const gap = str(asObj(f.gap).reason)
  return {
    status,
    stale: status === 'UNKNOWN' ? null : status === 'STALE',
    clock: str(f.clock),
    clockLabel: str(f.clock_label),
    asOf: str(f.as_of),
    ageSeconds: num(f.age_s),
    limitSeconds: num(f.limit_s),
    limitSource: str(f.limit_source),
    window: f.window === 'open' || f.window === 'closed' ? f.window : null,
    rule: str(f.rule),
    gap,
  }
}

/**
 * F-1: which clock `asOf` actually is — the label follows the VALUE, never the verdict about it.
 *
 * `asOf` is `truth.as_of`, the producer's aggregate clock (the quote clock on every body carrying
 * `last_repriced`), while the served verdict's `clock` is the one furthest past its own limit — usually stops or
 * positions. Labelling the value with the verdict's clock prints a quote instant as "STOP READ clock"
 * (R2, review 2026-11-15T040420Z), so the declared clock whose INSTANT equals `asOf` wins (instants compared, not
 * strings: the wire writes one clock as `…Z` and another with an ET offset). Only when no declared clock dates
 * the value does the verdict's role apply, and only when the verdict is about that same instant; otherwise the
 * value is UNDECLARED — no clock role is known, said plainly rather than dressed as a producer clock.
 */
function asOfClockFrom(clocks: ClockProvenance[], asOf: string, served: ServedFreshness | null): ClockRole {
  const at = Date.parse(asOf)
  if (Number.isFinite(at)) {
    const match = clocks.find(c => c.at !== null && Date.parse(c.at) === at)
    if (match !== undefined) return match.role
    const servedRole = FRESHNESS_CLOCK_ROLE[served?.clock ?? '']
    if (servedRole !== undefined && Date.parse(served?.asOf ?? '') === at) return servedRole
  }
  return 'UNDECLARED'
}

/**
 * Map the RESPONSE BODY of GET /api/v2/portfolio/holdings to a book.
 *
 * The body is `{ ok, data: {...}, _swr: {...} }`: the book lives under `data`, and its freshness annotation
 * (`_swr`) sits BESIDE it, not inside it. The outer `ok` is read for nothing — it is HTTP-level, and the shell's
 * RenderState decides availability from the declared nested paths (this route publishes no `data.ok`).
 */
export function adaptHoldings(body: unknown): AdaptResult {
  const root = asObj(body)
  const wire = isObj(root.data) ? root.data : {}
  if (!isObj(root.data)) return { book: null, error: 'the response carries no data block' }
  const holdings = asArr(wire.holdings)
  const coverage: string[] = []
  const clocks = clocksFrom(wire)
  const sc = asObj(wire.scope_coverage)
  const floorUsd = num(sc.min_position_usd)
  const rows: HoldingsRow[] = []
  let malformed = 0
  for (const h of holdings) {
    const row = isObj(h) ? rowFrom(h, floorUsd) : null
    if (row === null) malformed += 1
    else rows.push(row)
  }
  if (malformed > 0) coverage.push(`${malformed} listed row(s) carried no symbol and are not shown`)
  // One display identity per symbol, resolved once over the whole book (spec R1/R2): every row of a symbol then
  // renders the same name and the same status. Attaching copies the rows, so no later reader can hold one without.
  const identified = attachDisplayIdentity(rows)
  const population = populationFrom(wire, identified.length, coverage)
  const counts = countsFrom(wire, identified, coverage)
  const positions = asObj(asObj(wire.clock_provenance).positions)
  // F-1 (ledger 2026-11-15T0325Z): the book's as-of is the QUOTE clock when `truth.as_of` carries it. The page
  // used to print the literal role 'POSITIONS' over it, which read a quote instant as the positions aggregate.
  // The role now follows the field that actually won, and an unlabelled `as_of` is called undeclared, not named.
  const truthAsOf = str(asObj(wire.truth).as_of)
  const positionsAsOf = str(positions.as_of)
  const asOf = truthAsOf ?? positionsAsOf ?? str(wire.as_of)
  if (asOf === null) return { book: null, error: 'the payload declares no readable as_of' }
  const swr = asObj(root._swr)
  const staleAfterHours = num(asObj(asObj(asObj(wire.evidence).portfolio).clocks).stale_after_hours)
  const served = servedFreshness(wire)
  // F-1/R2: the label follows the INSTANT, never the field's name — see `asOfClockFrom`. A value no declared
  // clock dates is 'UNDECLARED' (the tip's name for "no clock role is known"), never dressed as a producer clock.
  const asOfClock: ClockRole = asOfClockFrom(clocks, asOf, served)
  if (asOfClock === 'UNDECLARED') coverage.push('the payload’s as_of names no clock role: it is shown as undeclared')
  const freshness: HoldingsFreshness = {
    served,
    // The CACHE facts below age this RESPONSE, never the book: `age_s`/`stale` say when the body was built inside
    // the cache window (the producer labels the clock `cache_build`). They are the fallback verdict only.
    // Served or null — never 0. `age_s: 0` would be a served age, and a block that serves none must not be aged.
    ageSeconds: num(swr.age_s),
    // Served or null — never 0. A served 0 h would be a real zero-hour limit; an absent clock is not that, and a
    // page that printed "past the 0 s limit" would be quoting a number the producer never served.
    staleAfterSeconds: staleAfterHours !== null ? Math.round(staleAfterHours * 3600) : null,
    // Only a PRESENT `stale: false` is fresh (missing boolean is never true). Absent block: the read cannot prove
    // itself current, so it is not current, and the page must say the block was absent rather than that it reported.
    stale: isObj(root._swr) ? swr.stale !== false : true,
    blockPresent: isObj(root._swr),
    withdrawn: false,
  }
  if (!isObj(root._swr)) coverage.push('the response carries no _swr block: freshness is treated as stale')

  const note = [
    `${identified.length} rows as served: ${counts.cash} cash and ${counts.nonCash} non-cash.`,
    `The producer counts ${counts.nonCashOverFloor} non-cash rows at or above the ${population.floorUsd ?? 'unstated'} floor and ${counts.heldUnderFloor} below it; the rows below the floor are listed and outside the counted scope, not omitted.`,
    ...coverage,
  ].join(' ')
  const source: BookSource = 'LIVE'
  const book: HoldingsBook = {
    contract: PORTFOLIO_HOLDINGS_CONTRACT_VERSION,
    source,
    asOf,
    asOfClock,
    clocks,
    rows: identified,
    counts,
    population,
    accounts: accountsFrom(wire),
    measures: measuresFrom(wire),
    session: sessionFrom(wire),
    freshness,
    dayPnl: dayPnlClock(wire),
    coverageNote: note,
  }
  return { book, error: null }
}
