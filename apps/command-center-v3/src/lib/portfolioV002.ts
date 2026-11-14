/** Portfolio v002 (operator-approved with amendments 2026-11-11, design/pages/portfolio/v002) — the page model.
 *
 *  Engineering Constitution: unknown beats wrong. Pure functions only; the page owns fetching.
 *
 *  Protection rule (DECISIONS-20261111):
 *    - OK only when every counted position was read and has a verified resting stop
 *      (a pending_activation resting GTC stop counts, G1);
 *    - GAP when a good read shows a counted position with no resting stop;
 *    - WARN (D1) when the only protection was a stop that expired (protection existed, no longer active);
 *    - UNKNOWN whenever protection cannot be verified. UNKNOWN is never drawn as NO STOP and never as OK.
 *  The per-row verdict is the backend's (cio_truth.protection_for -> holdings `protection_state`, LQ-2165).
 *  This module never re-derives a row's state from stop fields. It applies only the operator's time rules to it
 *  (2026-11-12, R1/R2, config/protection_verdict.json in LQ-2412) and rolls the rows up GAP > UNKNOWN > WARN > OK,
 *  the order of the backend rollups (LQ-2412 protection_verdict, LQ-2415). No served rollup is read yet (G2), so
 *  the verdict is marked NEEDS BACKEND; until one is, the client verdict errs to UNKNOWN, never to OK (LQ-2460):
 *    - an unknown value is never small: an unpriced non-exempt, non-cash row counts even when the wire says
 *      counted:false (LQ-2469, the cio_truth rule after LQ-2431). Only a KNOWN value under $100 is listed, not
 *      counted, not hidden (DECISIONS-20261111);
 *    - no counted position reads UNKNOWN unless the position count independently confirms zero;
 *    - R1: a GAP whose only stop expired is UNKNOWN in the regular session, WARN after the close (D1);
 *    - R2: a GAP whose stop read is older than the freshness limit is UNKNOWN; the last-known GAP stays listed.
 *      The limit itself is fresh (age > limit is stale). The session is 09:30:00 <= ET < 16:00:00, Mon-Fri.
 *  One verdict for one book (LQ-2483, LQ-2708). The owner of the served verdict is protection_verdict.headline
 *  (LQ-2412/2436, lead ruling); no route serves it yet (G2). Until one does, this module applies the owner's rules to
 *  the rows it has, and the shared fixture tests/fixtures/portfolio_protection_books_lq2708.json is read by both sides:
 *  the Python test runs each book's positions through cio_truth.protection_for (the wire) and stops_protection.summary;
 *  the page test runs the same wire through this module. Invariants on every book: the page never reads GAP where the
 *  backend reads OK, and never OK where it reads anything else. Membership agrees because this branch carries LQ-2431
 *  (e5afdf19d) and LQ-2436 (c280ec89d): an unpriced or <= 0 row is counted on the wire too.
 *  Declared splits, all with the page on the owner's side and never less alarmed than OK:
 *    - zero counted, count not confirmed: summary OK, page UNKNOWN with its cause (owner: UNKNOWN, LQ-2412 21083f476);
 *    - R1 expired stop in session and R2 stale GAP read: summary GAP (no clock), page UNKNOWN with the last-known GAP
 *      kept as a P0 row (owner: UNKNOWN). R1 reads protection.expired_stop (LQ-2412) or stop_state 'expired'.
 *  Not mirrored: the owner's 2169 counted set (an operator-exempt class) and its per-broker read ages. The rows carry
 *  neither, so the page cannot see them; rendering the served verdict (G2) is what closes that.
 *  I1/I2 defaults: unreadable -> UNKNOWN; no source -> UNKNOWN + NEEDS BACKEND; timeout (30 s) -> TIMED OUT;
 *  missing data -> UNKNOWN. Missing is never healthy. No /api/v2/overview read. */

export const PORTFOLIO_V002_TIMEOUT_MS = 30_000
export const API = {
  holdings: '/api/v2/portfolio/holdings',
  incidents: '/api/v2/home/incidents',
  /** LQ-2467: portfolio.last_seen, same server-stamped contract as Home's home.last_seen (write is gated). */
  lastSeen: '/api/v2/ui/prefs/get?key=portfolio.last_seen',
  prefs: '/api/v2/ui/prefs',
  /** PR-004: the portfolio-scoped gate projection (PortfolioGates@v1). The route is wired by the integrator; until it
   *  answers, the page reads HTTP 404 and renders the honest unavailable state, never a verdict. */
  gates: '/api/v2/portfolio/gates',
  /** PR-005: the portfolio-scoped change list (PortfolioChanges@v1). `?since=<ISO>` is the SERVER-stamped visit cursor
   *  read before this load stamps its own visit (LQ-2467); absent, the server windows the last 24 h and says so. */
  changes: '/api/v2/portfolio/changes',
} as const
export const PORTFOLIO_LAST_SEEN_KEY = 'portfolio.last_seen'

export type ReadState = 'OK' | 'UNKNOWN' | 'TIMED OUT' | 'LOADING'
export interface Read<T> { state: ReadState; data: T | null; error: string | null; at: string | null; source: string }
export const loadingRead = <T,>(source: string): Read<T> => ({ state: 'LOADING', data: null, error: null, at: null, source })

/** One GET with a hard 30 s timeout. Never throws: the result says what happened. A `{ok, data}` envelope is unwrapped. */
export async function readOnce<T>(source: string, timeoutMs = PORTFOLIO_V002_TIMEOUT_MS, fetchImpl: typeof fetch = fetch): Promise<Read<T>> {
  const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null
  let timedOut = false
  const timer = setTimeout(() => { timedOut = true; ctl?.abort() }, timeoutMs)
  const at = new Date().toISOString()
  try {
    const r = await fetchImpl(source, { signal: ctl?.signal, cache: 'no-store', credentials: 'same-origin' })
    if (!r.ok) return { state: 'UNKNOWN', data: null, error: `HTTP ${r.status}`, at, source }
    const body = (await r.json()) as unknown
    return { state: 'OK', data: unwrap(body) as T, error: null, at, source }
  } catch (e) {
    if (timedOut) return { state: 'TIMED OUT', data: null, error: `no answer after ${Math.round(timeoutMs / 1000)} s`, at, source }
    return { state: 'UNKNOWN', data: null, error: e instanceof Error ? e.message : String(e), at, source }
  } finally {
    clearTimeout(timer)
  }
}

export function unwrap(body: unknown): unknown {
  if (body && typeof body === 'object' && 'data' in body && 'ok' in body) {
    const b = body as { ok?: unknown; data?: unknown }
    if (b.data && typeof b.data === 'object') return b.data
  }
  return body
}

// ── wire shapes (only the fields this page reads) ─────────────────────────────────────────────────────
export interface ProtectionWire { state?: string; reason?: string | null; cause?: string | null; source?: string | null; as_of?: string | null; counted?: boolean; expired_stop?: boolean; price_missing?: boolean }
export interface HoldingWire {
  symbol?: string; account?: string; account_id?: string; account_label?: string; broker?: string
  quantity?: number | null; shares?: number | null; market_value?: number | null; price?: number | null
  price_as_of?: string | null; price_stale?: boolean | null; price_source?: string | null; quote_source?: string | null
  market_value_as_of?: string | null; market_value_source?: string | null; shares_synced_at?: string | null
  day_change?: number | null; day_change_pct?: number | null; prior_close?: number | null
  cost_basis?: number | null; cost_basis_source?: string | null; basis_status?: string | null
  basis_partial?: boolean | null; basis_unknown?: boolean | null
  /** cio_truth `basis_for()`: the acquisition cost AND its own verdict. `status` is 'recorded' only when a usable cost
   *  exists; when it is 'unknown' the `gap.reason` is the precise sentence the page must print instead of a figure. */
  basis_truth?: {
    cost_basis_usd?: number | null; unrealized_pl_usd?: number | null; unrealized_pl_pct?: number | null
    source?: string | null; status?: string | null; gap?: { reason?: string | null } | null
    conflicts?: { field?: string; reason?: string | null }[] | null
  } | null
  /** Position weight, when the producer publishes one. Absent today: the page names it not published, never divides
   *  two served numbers itself (operator one-broker rule, 2026-11-14). */
  weight_pct?: number | null; weight_basis?: string | null
  is_cash?: boolean; asset_type?: string | null
  stop_state?: string | null; stop_price?: number | null; stop_qty?: number | null; stop_captured_at?: string | null; stop_source?: string | null
  stop_order_id?: string | null; order_id?: string | null; stop_note?: string | null
  protection_state?: string | null; protection?: ProtectionWire | null
}

/** PortfolioMeasures@v1 (LQ-20261113-3124R, cc-deepseek-7). The writer materializes this block; GET never computes.
 *  Only the fields the page draws are typed. A value is drawn only when the projection published it with a status;
 *  the page never adds, subtracts or re-derives one measure from another (operator Q1, 2026-11-13: the broker store
 *  is the accounting anchor and a broker->Finviz re-mark is an estimate beside it, never inside it). */
export interface FinvizEstimateWire {
  label?: string; basis?: string; value?: number | null; marks_at?: string | null; delta?: number | null
  note?: string | null; total_with_broker_nav?: number | null; delta_vs_broker?: number | null; delta_note?: string | null
}
export interface MeasureWire {
  measure?: string; label?: string; value?: number | null; status?: string | null; basis?: string | null
  as_of?: string | null; definition?: string | null; gap?: { reason?: string | null; requires?: string | null; unvalued_rows?: unknown[]; start_unknown?: unknown[] } | null
  finviz_estimate?: FinvizEstimateWire | null
  coverage?: { measured_rows?: number | null; unknown_rows?: number | null; row_count?: number | null; unknown?: unknown[] | null } | null
  rows?: number | null
  start?: { equity_usd?: number | null; as_of?: string | null; source?: string | null; note?: string | null } | null
  end?: { equity_usd?: number | null; as_of?: string | null; source?: string | null } | null
  drill_down?: {
    price_move_estimate?: number | null; closed_today_trade_effect?: number | null; closed_today_rows?: unknown[] | null
    fees_today?: number | null; income_today?: number | null; external_flows_today?: number | null; reconciles?: boolean | null
  } | null
  candidate?: number | null
  known_components?: { price_move_estimate?: number | null; closed_today_trade_effect?: number | null; fees_today?: number | null; income_today?: number | null; external_flows_today?: number | null; note?: string | null } | null
  source?: string | null
}
export interface MeasuresBlockWire {
  contract_version?: string; status?: string; materialized?: boolean
  generated_at?: string | null; as_of?: string | null
  gap?: { reason?: string | null } | null
  measures?: Partial<Record<string, MeasureWire>> | null
  labels?: Partial<Record<string, string>> | null
  basis?: { applied?: string | null; why?: string | null } | null
  finviz_estimates_are_separate?: boolean
  /** BrokerContract@v1's receipt block when the producer nests it in the measures block (R5c, b6). */
  broker_contract?: { pnl?: { verified?: boolean | null } | null } | null
}
export interface HoldingsWire {
  holdings?: HoldingWire[] | null; total_value?: number | null; today_change?: number | null
  positions_as_of?: string | null; valuation_as_of?: string | null; quote_as_of?: string | null
  /** PositionCountAuthority@v1 (`scripts/lib/position_count_authority.py` counts_for_rows). `position_count` is the
   *  HEADLINE scope (`holdings.non_cash_over_100`), never "the count"; `agree` is the cross-scope flag — false on
   *  every real book, because cash / under-the-floor / unpriced rows are different populations — so it is never read
   *  as a comparison or as a finding (C5/C6, REVIEW-CAMPAIGN8H-item1-fix-cc-deepseek-2). Findings are the contract's. */
  position_counts?: {
    agree?: boolean; position_count?: number; all_rows?: number; held_count?: number; primary_scope?: string
    scopes?: Record<string, number>; distinct_values?: number[]; summary?: string
    findings?: { code?: string; detail?: string }[]; [k: string]: unknown
  } | null
  /** PortfolioMeasures@v1. Present only once the writer has materialized it; absent is UNKNOWN, never computed here. */
  measures?: MeasuresBlockWire | null
  /** BrokerContract@v1's input version, when the producer publishes it (PR-002/PR-018, cc-deepseek-2). Absent today:
   *  the scope line names it as not published rather than inventing one. */
  snapshot_id?: string | null
  /** BrokerContract@v1's receipt block, when the producer publishes one. `pnl.verified` is the ONLY thing that can
   *  license a verified daily P&L; a measure status alone is not a receipt (R5c, b6). */
  broker_contract?: { pnl?: { verified?: boolean | null } | null; [k: string]: unknown } | null
  reconciliation?: { total?: { verified?: boolean | null; provisional?: boolean | null } | null; [k: string]: unknown } | null
}
export interface IncidentsWire { counts?: { P0?: number; P1?: number } | null; served_at?: string | null; items?: unknown[] | null }

// ── formatting ────────────────────────────────────────────────────────────────────────────────────────
export function fmtET(iso: string | null | undefined, withDay = false): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const opts: Intl.DateTimeFormatOptions = { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' }
  if (withDay) opts.weekday = 'short'
  return d.toLocaleString('en-US', opts).replace(',', '')
}
export function fmtAge(ms: number | null): string {
  if (ms == null || !Number.isFinite(ms)) return '—'
  const m = Math.max(0, Math.round(ms / 60_000))
  if (m < 60) return `${m} m`
  const h = Math.round(m / 60)
  return h < 48 ? `${h} h` : `${Math.round(h / 24)} d`
}
export function fmtUsd(v: number | null | undefined, signed = false): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const s = Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 0 })
  const sign = v < 0 ? '−' : signed && v > 0 ? '+' : ''
  return `${sign}$${s}`
}
export function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}%`
}
export function fmtShares(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return v.toLocaleString('en-US', { maximumFractionDigits: 3 })
}
function ageMs(iso: string | null | undefined, nowMs: number): number | null {
  if (!iso) return null
  const t = Date.parse(iso)
  return Number.isFinite(t) ? Math.max(0, nowMs - t) : null
}
/** Signed age, for the one question ageMs's clamp hides: is this observation LATER than the capture clock?
 *  (PR-003: an impossible future observation is unverified evidence, never an ordinary successful read.) */
function skewMs(iso: string | null | undefined, nowMs: number): number | null {
  if (!iso) return null
  const t = Date.parse(iso)
  return Number.isFinite(t) ? nowMs - t : null
}
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

// ── per-row protection (display only; the verdict is the backend's) ──────────────────────────────────
export type RowProtection = 'PROTECTED' | 'GAP' | 'WARN' | 'UNKNOWN' | 'EXEMPT'
export const STOP_OWNER = 'stop_health_check / Stop Management'

export interface PositionModel {
  key: string; symbol: string; account: string; accountKey: string; broker: string
  shares: number | null; value: number | null; price: number | null; dayPct: number | null; dayUsd: number | null
  isCash: boolean; counted: boolean; underFloor: boolean; unpriced: boolean
  /** R2: the backend said GAP but its stop read is past the freshness limit; the row reads UNKNOWN, the GAP stays listed. */
  lastKnownGap: boolean
  protection: RowProtection; chip: string; reason: string; cause: string | null; source: string; verifiedAt: string | null
  stopPrice: number | null; priceStale: boolean | null
  /** OBS-P1 (operator 11:15 ET, 2026-11-14): the row's mark is an observation with a source and a clock, and its
   *  session move is a PRICE MOVE — never called P&L. `priceAt` is the row's own `price_as_of`; null means the read
   *  published no per-row quote clock and the row must say so (basisOf()/priceClock() name which clock was used). */
  priceSource: string | null; priceAt: string | null
  /** Weight and basis, drawn only as the read publishes them. `basis.status` 'UNKNOWN' carries the precise reason. */
  weightPct: number | null; weightBasis: string | null; basis: BasisView
  /** OP-026: per-share WEIGHTED REMAINING BASIS = recorded basis ÷ held shares, computed from the same row the drawer
   *  reads. Null when the basis is not recorded or no share count is published — never 0, and never the wire
   *  `avg_cost` (a second field that can disagree with the basis, e.g. a rebased rollover lot set). */
  avgEntry: number | null
  /** Resting stop quantity from the wire (`stop_qty`), never a derived number; null when the read did not publish it. */
  restingShares: number | null
  /** Display-only coverage classification (covered/partial/uncovered/planned-only/exempt/unverifiable). It never
   *  changes the backend's protection verdict or the rollup. */
  coverage: CoverageView
  /** PR-017: a planned level is its own fact, drawn beside the broker-evidence state. A plan never promotes UNKNOWN
   *  to NO STOP and never counts as coverage; the wire publishes it as stop_source 'planned' (or stop_state). */
  planned: PlannedFacet | null
  /** PR-003: the row's verification time is later than the capture clock. An impossible future observation cannot
   *  label a successful read; a PROTECTED row with such a time reads UNKNOWN with its cause. */
  verifiedAtInvalid: boolean
  raw: HoldingWire
}

export interface PlannedFacet { price: number | null; source: string; at: string | null }

/** Display-only stop coverage (campaign vocabulary, 2026-11-14). The backend's protection_state stays the verdict;
 *  this class answers "how much of the holding does a resting stop actually cover", which the verdict does not say.
 *  COVERED     a resting stop and no evidence of a shortfall in the read
 *  PARTIAL     a resting stop exists but its quantity is less than the held shares (resting vs held is drawn)
 *  UNCOVERED   a good read shows no resting stop (GAP), or the only stop expired (WARN)
 *  PLANNED_ONLY the stop exists only as a plan at the broker; counts as unprotected
 *  EXEMPT      policy-exempt (cash / money market / sweep)
 *  UNVERIFIABLE protection could not be read; never drawn as uncovered
 *  Never derived from arithmetic the projection owns: resting/held are wire values, drawn side by side. */
export type CoverageCategory = 'COVERED' | 'PARTIAL' | 'UNCOVERED' | 'PLANNED_ONLY' | 'EXEMPT' | 'UNVERIFIABLE'
export interface CoverageView {
  category: CoverageCategory; chip: string; label: string
  restingShares: number | null; heldShares: number | null; detail: string
}
export const COVERAGE_ORDER: CoverageCategory[] = ['COVERED', 'PARTIAL', 'UNCOVERED', 'PLANNED_ONLY', 'EXEMPT', 'UNVERIFIABLE']

function coverageFor(pr: Pick<PositionModel, 'protection' | 'chip' | 'reason'>, h: HoldingWire, held: number | null): CoverageView {
  const resting = num(h.stop_qty)
  const planned = String(h.stop_source || '').toLowerCase() === 'planned' || String(h.stop_state || '').toLowerCase() === 'planned'
  const shares = held != null && held > 0 ? held : null
  if (pr.protection === 'EXEMPT') {
    return { category: 'EXEMPT', chip: 'EXEMPT', label: 'Exempt from stop coverage', restingShares: resting, heldShares: shares,
      detail: 'Cash / money-market / sweep rows are exempt by policy; no stop is expected.' }
  }
  if (pr.protection === 'UNKNOWN') {
    return { category: 'UNVERIFIABLE', chip: 'UNKNOWN', label: 'Coverage cannot be verified', restingShares: resting, heldShares: shares,
      detail: `${pr.reason}. A stop quantity in an unread book is not coverage; this is never drawn as NO STOP.` }
  }
  if (pr.protection === 'GAP' || pr.protection === 'WARN') {
    if (planned && pr.protection === 'GAP') {
      return { category: 'PLANNED_ONLY', chip: 'PLANNED ONLY', label: 'Planned only', restingShares: resting, heldShares: shares,
        detail: 'The level exists only as a plan at the broker; no resting order protects the position, so it counts as unprotected.' }
    }
    return { category: 'UNCOVERED', chip: pr.protection === 'WARN' ? 'EXPIRED' : 'NO STOP', label: pr.protection === 'WARN' ? 'Expired stop' : 'Uncovered',
      restingShares: resting, heldShares: shares,
      detail: pr.protection === 'WARN' ? 'Protection existed but the stop expired; nothing rests at the broker now.' : 'The broker read succeeded and shows no resting stop.' }
  }
  // PROTECTED: a resting stop. Draw the quantities the read published; call it partial only when both are known.
  if (shares != null && resting != null && resting < shares) {
    return { category: 'PARTIAL', chip: `PARTIAL ${fmtShares(resting)}/${fmtShares(shares)}`, label: 'Partial coverage',
      restingShares: resting, heldShares: shares,
      detail: `The resting stop covers ${fmtShares(resting)} of ${fmtShares(shares)} held shares. The backend verdict stays PROTECTED; the uncovered remainder is drawn, not hidden.` }
  }
  return { category: 'COVERED', chip: pr.chip, label: 'Covered', restingShares: resting, heldShares: shares,
    detail: resting == null || shares == null
      ? 'A resting stop is present. This read did not publish both the resting quantity and the held quantity, so full coverage is not proven.'
      : `The resting stop covers ${fmtShares(resting)} of ${fmtShares(shares)} held shares.` }
}
export function coverageOf(p: PositionModel): CoverageView { return p.coverage }

/** Stop-read freshness limits: config/data_source_authority.json domain `broker_stops` (stale_after_hours 0.25,
 *  stale_after_hours_closed 72), read by cio_truth.stop_freshness_contract() and by the owner rollup
 *  protection_verdict.headline (LQ-2436 F1). The LQ-2708 contract test pins this to the same file. */
export const STOP_READ_MAX_AGE_MS = { session: 900_000, offHours: 72 * 3_600_000 } as const

/** R1: what an expired-only stop reads while the regular session is open. config/protection_verdict.json
 *  `protection_verdict.expired_day_stop_open_session` (LQ-2412, shipped UNKNOWN); UNKNOWN is also the owner's fallback
 *  when that file is absent or invalid. The LQ-2708 contract test pins this to the file when it exists. */
export const R1_EXPIRED_OPEN_SESSION: 'UNKNOWN' | 'GAP' | 'WARN' = 'UNKNOWN'

/** No usable value: missing, not a number, or <= 0 (a feed that writes 0 for no quote). Never "under the floor".
 *  The value alone decides, exactly as the owner does (protection_verdict.price_missing_of, LQ-2436 F3) and as
 *  cio_truth.protection_for sets protection.price_missing. A wire flag beside a known positive value (the row was
 *  repriced after the protection read) is not used: the owner and the summary both list that row, so counting it
 *  here would draw a GAP the served verdict reads OK (LQ-2708). */
export function priceMissing(h: HoldingWire): boolean {
  const v = num(h.market_value)
  return v == null || v <= 0
}

/** Regular US equity session, 09:30-16:00 ET Mon-Fri. No holiday calendar: a holiday reads as open, which picks the
 *  stricter limit (R2) and UNKNOWN over WARN (R1), the safe side of both rules. */
export function sessionOpenET(nowMs: number): boolean {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
    .formatToParts(new Date(nowMs))
  const get = (t: string) => parts.find(x => x.type === t)?.value || ''
  if (get('weekday') === 'Sat' || get('weekday') === 'Sun') return false
  const m = Number(get('hour')) * 60 + Number(get('minute'))
  return m >= 9 * 60 + 30 && m < 16 * 60
}

export interface RowContext { nowMs: number; sessionOpen?: boolean }
type RowView = Pick<PositionModel, 'protection' | 'chip' | 'reason' | 'cause' | 'source' | 'verifiedAt' | 'stopPrice' | 'lastKnownGap'>

/** The fields the stop-read rule reads, declared structurally so a second surface can apply the SAME rule to the
 *  rows it is served. Risk › Exposure reads /api/v2/cio/pages, whose rows carry the stop-read clock
 *  (`stop_captured_at`), the stop state and the projection's own `stop_evidence` mark — but no `protection` verdict.
 *  It therefore calls this module's rule rather than computing an age or a limit of its own (2026-11-14, R5b #1:
 *  AMANX read UNKNOWN on Portfolio and a bare "Planned level · Observed Apr 18" on Risk with no freshness verdict). */
export type StopReadWire = Pick<HoldingWire, 'protection' | 'protection_state' | 'stop_price' | 'stop_captured_at' | 'stop_source' | 'stop_state'> & {
  stop_evidence?: { stale?: boolean | null; age_hours?: number | null; as_of?: string | null } | null
}

export function rowProtection(h: StopReadWire, ctx: RowContext = { nowMs: Date.now() }): RowView {
  const r = rowView(h, ctx)
  return { lastKnownGap: false, ...r }
}

function rowView(h: StopReadWire, ctx: RowContext): Omit<RowView, 'lastKnownGap'> & { lastKnownGap?: boolean } {
  const p = h.protection || {}
  const st = String(h.protection_state || p.state || '').toUpperCase()
  const stopPrice = num(h.stop_price)
  const verifiedAt = p.as_of ?? h.stop_captured_at ?? null
  // PR-003: an observation later than the page's own clock is impossible. It is never an ordinary successful
  // verification: a PROTECTED row reads UNKNOWN, and no age-based rule (R2) treats a negative age as fresh.
  const skew = skewMs(verifiedAt, ctx.nowMs)
  const invalidAt = skew != null && skew < 0
  const source = p.source || h.stop_source || 'none'
  if (st === 'PROTECTED') {
    if (invalidAt) {
      return { protection: 'UNKNOWN', chip: 'UNKNOWN', cause: 'Invalid Stop Read Time',
        reason: `The stop read time (${fmtET(verifiedAt, true)}) is later than the capture clock; the verification cannot be trusted`,
        source, verifiedAt, stopPrice }
    }
    return { protection: 'PROTECTED', chip: stopPrice != null && stopPrice > 0 ? `STOP $${stopPrice.toFixed(2)}` : 'STOP · price not recorded',
      reason: p.reason || 'Resting stop', cause: null, source, verifiedAt, stopPrice }
  }
  if (st === 'GAP') {
    const open = ctx.sessionOpen ?? sessionOpenET(ctx.nowMs)
    // R1/D1: the backend keeps an expired-only stop as GAP and marks it (LQ-2412 protection.expired_stop).
    if (p.expired_stop === true || String(h.stop_state || '').toLowerCase() === 'expired') {
      return open
        ? { protection: R1_EXPIRED_OPEN_SESSION, chip: 'EXPIRED',
          reason: `The stop expired and the session is open; protection cannot be verified (R1: ${R1_EXPIRED_OPEN_SESSION})`,
          cause: 'Expired Stop', source, verifiedAt, stopPrice }
        : { protection: 'WARN', chip: 'EXPIRED', reason: 'The stop expired after the close; protection existed but is no longer active (D1: WARN, never OK)',
          cause: 'Expired Stop', source, verifiedAt, stopPrice }
    }
    // R2: a GAP from a read past the freshness limit is UNKNOWN; the last-known GAP stays visible. A GAP row with no
    // as_of carries no age to judge (the book-level read age is the served rollup's, G2) and stays GAP.
    // C1 (REVIEW-S2-portfolio-risk-b1 §5): a stop-read time LATER than the capture clock is an impossible observation,
    // not a stale one. `ageMs` clamps at 0, so its `age < 0` test could never fire and this row read NO STOP while its
    // own sentence said the read could not be trusted. It is UNKNOWN with its own cause, it leaves the NO STOP
    // population, and the last-known GAP stays visible (lastKnownGap).
    const f = stopReadFreshness(h, ctx.nowMs, open)
    if (f.kind === 'invalid') {
      return { protection: 'UNKNOWN', chip: 'UNKNOWN', lastKnownGap: true,
        reason: `The stop read time (${fmtET(verifiedAt, true)}) is later than the capture clock; the verification cannot be trusted`,
        cause: 'Invalid Stop Read Time', source, verifiedAt, stopPrice }
    }
    if (f.kind === 'stale') {
      return { protection: 'UNKNOWN', chip: 'UNKNOWN', lastKnownGap: true,
        reason: `Last known: no resting stop, but the stop read is ${fmtAge(f.ageMs)} old (limit ${fmtAge(f.limitMs)}); R2: UNKNOWN`,
        cause: 'Stale Stop Read', source, verifiedAt, stopPrice }
    }
    return { protection: 'GAP', chip: 'NO STOP', reason: p.reason || 'Stop read succeeded and shows no resting stop',
      cause: 'Unprotected Position', source, verifiedAt, stopPrice }
  }
  if (st === 'EXEMPT') return { protection: 'EXEMPT', chip: 'EXEMPT', reason: p.reason || 'Exempt', cause: null, source: 'policy', verifiedAt: null, stopPrice }
  if (st === 'UNKNOWN') {
    return { protection: 'UNKNOWN', chip: 'UNKNOWN', reason: p.reason || 'Protection cannot be verified', cause: p.cause || 'Protection Unknown',
      source, verifiedAt, stopPrice }
  }
  // No verdict on the row: never guess from stop fields (I1/I2: no source -> UNKNOWN + NEEDS BACKEND).
  return { protection: 'UNKNOWN', chip: 'UNKNOWN', reason: 'The row carries no protection_state', cause: 'No Protection Verdict',
    source: 'none', verifiedAt: null, stopPrice }
}

/** R2's age rule, in ONE place: the stop-read clock, the limit that applies (session 15 m / off-hours 72 h,
 *  STOP_READ_MAX_AGE_MS) and the verdict a read deserves. `rowView` masks a GAP with it; Risk › Exposure's stop
 *  detail sheet draws it beside the served state instead of showing a bare "Observed Apr 18" (2026-11-14, R5b #1).
 *  One limit, one implementation, one sentence — no surface computes its own.
 *  - `unpublished`: the row publishes no read time, so an age cannot be measured (never drawn as fresh);
 *  - `invalid`: the read time is later than the clock — an impossible observation, never a fresh one;
 *  - `fresh` / `stale`: measured against the limit for the session state at `nowMs`.
 *  When the projection also publishes `stop_evidence.stale`, the two marks are compared and a disagreement is
 *  said out loud (a drift between the served mark and this rule is never resolved silently). */
export interface StopReadFreshness {
  kind: 'unpublished' | 'invalid' | 'fresh' | 'stale'
  asOf: string | null; ageMs: number | null; limitMs: number; sessionOpen: boolean
  servedStale: boolean | null; agreesWithServed: boolean | null
  line: string
}
export function stopReadFreshness(h: StopReadWire, nowMs: number, sessionOpen?: boolean): StopReadFreshness {
  const open = sessionOpen ?? sessionOpenET(nowMs)
  const limitMs = open ? STOP_READ_MAX_AGE_MS.session : STOP_READ_MAX_AGE_MS.offHours
  const p = h.protection || {}
  const asOf = p.as_of ?? h.stop_captured_at ?? null
  const servedStale = typeof h.stop_evidence?.stale === 'boolean' ? h.stop_evidence!.stale! : null
  const basis = `${open ? 'session' : 'off-hours'} limit ${fmtAge(limitMs)}`
  const skew = skewMs(asOf, nowMs)
  let kind: StopReadFreshness['kind']; let ageMs: number | null = null; let line: string
  if (skew == null) {
    kind = 'unpublished'; line = 'UNKNOWN · no stop-read time is published, so the read age is not measured'
  } else if (skew < 0) {
    kind = 'invalid'; line = `UNKNOWN · the stop-read time (${fmtET(asOf, true)}) is later than the clock; the read cannot be trusted`
  } else {
    ageMs = skew
    if (ageMs > limitMs) {
      kind = 'stale'
      line = `UNKNOWN · the stop read is ${fmtAge(ageMs)} old (${basis}); the served state is last known, not a current read (R2, the rule Portfolio applies)`
    } else {
      kind = 'fresh'; line = `fresh · read ${fmtAge(ageMs)} ago · ${basis}`
    }
  }
  const agreesWithServed = servedStale == null || kind === 'unpublished' || kind === 'invalid'
    ? null : servedStale === (kind === 'stale')
  if (servedStale != null && !agreesWithServed) {
    line += agreesWithServed === false
      ? ` · the served stop evidence marks it ${servedStale ? 'stale' : 'fresh'} — the two marks disagree`
      : ` · the served stop evidence marks it ${servedStale ? 'stale' : 'fresh'}`
  }
  return { kind, asOf, ageMs, limitMs, sessionOpen: open, servedStale, agreesWithServed, line }
}

// ── measured downside to the resting stop (OP-023, operator 2026-11-14 13:11:57 ET) ─────────────────
/** The operator's Risk column: one measured fact per position, never a score.
 *
 *  "Hypothetical downside to stop (verified stop price)" = (mark − resting stop) × the quantity the resting stop
 *  covers. It is a DISTANCE to a resting order price. It is not an execution price, not a loss, not P&L and not a
 *  floor: a stop can gap through, and the held quantity with no order behind it has no figure at all (the amendment
 *  of 13:16 ET requires the covered and uncovered quantities to be separate values, and `uncovered: no stop` to be
 *  its own state). The composite score stays undecided (`RISK_SCORE`) and nothing here feeds one.
 *
 *  Every input is a served field, drawn with its own source and clock. Eligibility and staleness are the page's
 *  EXISTING rules — the row's `protection` verdict and coverage class, and `stopReadFreshness` (STOP_READ_MAX_AGE_MS
 *  from `config/data_source_authority.json` domain broker_stops). This function adds no threshold, TTL or tolerance,
 *  and an unknown cost basis never gates it: basis is an unrealized-P&L input only. */
export type DownsideState =
  | 'MEASURED' | 'PARTIAL' | 'EXEMPT' | 'UNCOVERED' | 'PLANNED_ONLY' | 'EXPIRED'
  | 'STOP_STALE' | 'STOP_UNDATED' | 'STOP_PRICE_MISSING' | 'STOP_QTY_MISSING' | 'MARK_MISSING'
  | 'MARK_STALE' | 'AT_OR_BELOW_STOP' | 'UNVERIFIABLE'

export interface DownsideMeasure {
  state: DownsideState
  /** Dollars below the mark to the verified resting stop, over the COVERED quantity only. Null unless measured. */
  usd: number | null
  /** (mark − stop) / mark, in percent (a positive distance below the mark). Null whenever `usd` is null. */
  pct: number | null
  coveredQty: number | null
  /** Held quantity with no resting order behind it. It never carries a downside figure — only a state. */
  uncoveredQty: number | null
  uncoveredState: 'uncovered: no stop' | null
  mark: { value: number | null; source: string | null; asOf: string | null; stale: boolean | null }
  stop: { value: number | null; source: string; asOf: string | null; freshness: StopReadFreshness['kind'] | null }
  /** Short cell text: a dollars figure, or the state in words. Never blank and never a false 0. */
  cell: string
  /** What the figure is, or why there is none. */
  reason: string
  /** The arithmetic as drawn (or the statement that none is drawn). */
  formula: string
  /** Cost basis, carried for the reader: it gates unrealized P&L only, never this measure (amendment 3). */
  basis: { status: BasisView['status']; reason: string | null }
}

/** A compact cell figure. The EXACT value is drawn in the row's facts line, the sheet and the CSV; a 56 px column
 *  abbreviates to three significant digits and the title carries the full arithmetic. */
export function downsideCellText(usd: number): string {
  if (usd >= 1_000_000) return `$${(usd / 1_000_000).toFixed(1)}M`
  if (usd >= 10_000) return `$${(usd / 1000).toFixed(1)}k`
  return fmtUsd(usd)
}

export function downsideToStop(p: PositionModel, ctx: { nowMs: number; sessionOpen?: boolean }): DownsideMeasure {
  const f = stopReadFreshness(p.raw, ctx.nowMs, ctx.sessionOpen)
  const mark = { value: p.price, source: p.priceSource, asOf: p.priceAt, stale: p.priceStale }
  const stop = { value: p.stopPrice, source: p.source, asOf: p.verifiedAt, freshness: f.kind }
  const basis = { status: p.basis.status, reason: p.basis.reason }
  const held = p.shares != null && p.shares > 0 ? p.shares : null
  const coveredQty = held != null && p.restingShares != null && p.restingShares > 0 ? Math.min(held, p.restingShares) : null
  const uncoveredQty = held != null && coveredQty != null ? Math.round((held - coveredQty) * 1e6) / 1e6 : null
  const mk = (state: DownsideState, cell: string, reason: string, extra: Partial<DownsideMeasure> = {}): DownsideMeasure => ({
    state, usd: null, pct: null, coveredQty: null, uncoveredQty: null, uncoveredState: null,
    mark, stop, cell, reason, formula: 'no figure is drawn', basis, ...extra,
  })
  const noStop = (state: DownsideState, cell: string, reason: string) =>
    mk(state, cell, reason, { uncoveredQty: held, uncoveredState: held != null ? 'uncovered: no stop' : null })

  if (p.isCash || p.coverage.category === 'EXEMPT')
    return mk('EXEMPT', 'cash', 'Cash / money-market / sweep rows are exempt from stop coverage by policy; there is no stop to measure to.')
  if (p.coverage.category === 'UNVERIFIABLE' || p.protection === 'UNKNOWN')
    return noStop('UNVERIFIABLE', 'unknown', `${p.reason}. A level in an unread book is last known, not a verified stop price, so no distance is drawn.`)
  if (p.coverage.category === 'PLANNED_ONLY')
    return noStop('PLANNED_ONLY', 'planned', 'The level exists only as a plan at the broker; a plan is not a resting order and protects nothing, so there is no verified stop price to measure to.')
  if (p.protection === 'WARN')
    return noStop('EXPIRED', 'expired', 'Protection existed but the stop expired; nothing rests at the broker now, so there is no verified stop price to measure to.')
  if (p.coverage.category === 'UNCOVERED')
    return noStop('UNCOVERED', 'no stop', 'The broker read succeeded and shows no resting stop. Unprotected exposure is not a known loss and is never drawn as one.')

  // PROTECTED: a resting stop exists. Every input is gated by an existing rule, in the order a reader checks them.
  if (stop.value == null || stop.value <= 0)
    return mk('STOP_PRICE_MISSING', 'no stop px', 'The resting stop was read without a verified stop price (a value ≤ 0 is missing, owner rule); the distance cannot be computed.', { coveredQty })
  if (mark.value == null || mark.value <= 0)
    return mk('MARK_MISSING', 'no mark', 'This read published no mark for the row, so the distance to the stop cannot be computed.', { coveredQty })
  if (mark.stale === true)
    return mk('MARK_STALE', 'stale mark', `The served quote is marked stale (${mark.source || 'source not named'}, ${fmtET(mark.asOf, true)} ET); a distance measured from a stale mark is not drawn.`, { coveredQty })
  if (f.kind === 'stale' || f.kind === 'invalid')
    return mk('STOP_STALE', 'stale stop', `${f.line}. The stop price is last known, not a current read, so no distance is drawn.`, { coveredQty })
  if (f.kind === 'unpublished')
    return mk('STOP_UNDATED', 'undated', `${f.line}. Without a stop-read clock the stop price is not verified for this measure.`, { coveredQty })
  if (coveredQty == null) {
    if (p.restingShares == null || p.restingShares <= 0)
      return mk('STOP_QTY_MISSING', 'no qty', 'The read did not publish the resting stop quantity, so the covered quantity is not proven and no figure is drawn over the whole holding.', { coveredQty })
    return mk('STOP_QTY_MISSING', 'no held qty', 'The read did not publish a held quantity, so neither the covered nor the uncovered quantity can be named.', { coveredQty })
  }
  const partial = uncoveredQty != null && uncoveredQty > 0
  if (mark.value <= stop.value)
    return mk('AT_OR_BELOW_STOP', 'at/below', `The mark ${fmtUsd(mark.value)} is at or below the resting stop ${fmtUsd(stop.value)}; there is no distance below the mark to measure, and a fill is not confirmed.`,
      { coveredQty, uncoveredQty, uncoveredState: partial ? 'uncovered: no stop' : null })
  const usd = Math.round((mark.value - stop.value) * coveredQty * 100) / 100
  const pct = ((mark.value - stop.value) / mark.value) * 100
  const formula = `(mark ${fmtUsd(mark.value)} − stop ${fmtUsd(stop.value)}) × ${fmtShares(coveredQty)} covered shares = ${fmtUsd(usd)}`
  return mk(partial ? 'PARTIAL' : 'MEASURED', downsideCellText(usd),
    partial
      ? `Hypothetical downside to stop (verified stop price) over the ${fmtShares(coveredQty)} covered shares. ${fmtShares(uncoveredQty!)} held shares have no resting order: uncovered: no stop.`
      : `Hypothetical downside to stop (verified stop price) over the ${fmtShares(coveredQty)} held shares. A stop is a resting order price, not an executed price.`,
    { usd, pct, coveredQty, uncoveredQty, uncoveredState: partial ? 'uncovered: no stop' : null, formula })
}

/** The row's facts-line sentence: the exact figure (never the compact cell form), its percent, the covered quantity
 *  and, when partial, the uncovered quantity as its own state. Same strings the sheet and the CSV draw. */
export function downsideLine(m: DownsideMeasure): string {
  if (m.state === 'MEASURED' || m.state === 'PARTIAL') {
    const head = `hypothetical downside to stop ${fmtUsd(m.usd)} (${m.pct!.toFixed(1)}% below the mark) · covered ${fmtShares(m.coveredQty)}`
    return m.uncoveredState ? `${head} · ${fmtShares(m.uncoveredQty!)} uncovered: no stop` : head
  }
  return `hypothetical downside to stop: ${m.state === 'EXEMPT' ? 'cash row · no stop expected' : m.cell}`
}

export function positionsFrom(w: HoldingsWire | null, nowMs: number = Date.now()): PositionModel[] {
  const rows = Array.isArray(w?.holdings) ? w!.holdings! : []
  const ctx: RowContext = { nowMs, sessionOpen: sessionOpenET(nowMs) }
  return rows.map((h, i) => {
    const value = num(h.market_value)
    const isCash = !!h.is_cash
    const pr = rowProtection(h, ctx)
    const countedFlag = h.protection?.counted
    // F1 (REVIEW-2448, folded from LQ-2469): an unknown value is never small. An unpriced row (no value, or <= 0) stays
    // counted even when the wire says counted:false, so an unpriced GAP stays a GAP. Only a KNOWN positive value under
    // the floor is listed, not counted (operator DECISIONS-20261111: "under $100: listed, not counted, not hidden").
    const unpriced = priceMissing(h)
    const counted = pr.protection !== 'EXEMPT' && !isCash && ((countedFlag ?? true) || unpriced)
    const symbol = String(h.symbol || '?').toUpperCase()
    const account = String(h.account_label || h.account || h.account_id || '—')
    const accountKey = String(h.account || h.account_id || h.account_label || '—')
    const heldShares = num(h.shares) ?? num(h.quantity)
    // PR-017: the planned level is published beside the broker evidence, never folded into it.
    const plannedOnly = String(h.stop_source || '').toLowerCase() === 'planned' || String(h.stop_state || '').toLowerCase() === 'planned'
    const planned: PlannedFacet | null = plannedOnly
      ? { price: num(h.stop_price), source: String(h.stop_source || 'planned'), at: h.stop_captured_at ?? null } : null
    const atAge = skewMs(pr.verifiedAt, ctx.nowMs)
    const basis = basisView(h)
    // OP-026: the weighted remaining basis per share is the RECORDED basis over the held shares — the same two
    // numbers the drawer prints. A cash row has no acquisition cost; an unknown basis stays null.
    const avgEntry = basis.status === 'RECORDED' && basis.usd != null && heldShares != null && heldShares > 0
      ? basis.usd / heldShares : null
    return {
      key: `${h.account_id || h.account || i}:${symbol}`, symbol, account, accountKey, broker: String(h.broker || '—'),
      shares: heldShares, value, price: num(h.price), dayPct: num(h.day_change_pct), dayUsd: num(h.day_change),
      isCash, counted, unpriced: unpriced && !isCash, underFloor: pr.protection !== 'EXEMPT' && !isCash && !counted,
      ...pr, priceStale: h.price_stale ?? null, restingShares: num(h.stop_qty), coverage: coverageFor(pr, h, heldShares),
      priceSource: String(h.price_source || h.quote_source || '') || null, priceAt: h.price_as_of ?? null,
      weightPct: num(h.weight_pct), weightBasis: String(h.weight_basis || '') || null, basis, avgEntry,
      planned, verifiedAtInvalid: atAge != null && atAge < 0, raw: h,
    }
  }).sort((a, b) => (b.value ?? -1) - (a.value ?? -1))
}

// ── protection rollup (mirror of stops_protection.summary) ───────────────────────────────────────────
export type Verdict = 'OK' | 'GAP' | 'WARN' | 'UNKNOWN' | 'TIMED OUT' | 'LOADING'
export interface BrokerInput { broker: string; state: 'OK' | 'UNKNOWN' | 'GAP' | 'WARN'; counted: number; protectedN: number; oldest: string | null; cause: string | null }
export interface ProtectionModel {
  verdict: Verdict; counted: number | null; protectedN: number | null; gap: number | null; warn: number | null; unknown: number | null
  listedNotCounted: number | null; exempt: number | null
  action: PositionModel[]; oldestRead: string | null; brokers: BrokerInput[]; cause: string | null
}

export function protectionModel(read: Read<HoldingsWire>, positions: PositionModel[]): ProtectionModel {
  const empty = { counted: null, protectedN: null, gap: null, warn: null, unknown: null, listedNotCounted: null, exempt: null, action: [], oldestRead: null, brokers: [] }
  if (read.state === 'LOADING') return { verdict: 'LOADING', ...empty, cause: null }
  if (read.state !== 'OK') return { verdict: read.state, ...empty, cause: `${read.source}: ${read.error || read.state}` }
  const counted = positions.filter(p => p.counted)
  // F2: no counted position is OK only when the position count independently confirms zero; otherwise UNKNOWN.
  if (counted.length === 0) {
    const pc = read.data?.position_counts
    const confirmedZero = pc?.agree === true && pc?.position_count === 0
    if (!confirmedZero || positions.length === 0) {
      return { verdict: 'UNKNOWN', ...empty,
        counted: positions.length ? 0 : null, listedNotCounted: positions.length ? positions.filter(p => p.underFloor).length : null,
        exempt: positions.length ? positions.filter(p => p.protection === 'EXEMPT' || p.isCash).length : null,
        cause: positions.length === 0 ? 'The holdings read returned no positions'
          : confirmedZero ? null : 'No counted position, and the position count does not confirm zero' }
    }
  }
  const n = { PROTECTED: 0, GAP: 0, WARN: 0, UNKNOWN: 0 }
  for (const p of counted) n[p.protection === 'EXEMPT' ? 'UNKNOWN' : p.protection]++
  // F3: GAP > UNKNOWN > WARN > OK, the order of the backend rollups (2412, 2415).
  const verdict: Verdict = n.GAP ? 'GAP' : n.UNKNOWN ? 'UNKNOWN' : n.WARN ? 'WARN' : 'OK'
  const rank: Record<RowProtection, number> = { GAP: 0, UNKNOWN: 1, WARN: 2, PROTECTED: 3, EXEMPT: 4 }
  const action = counted.filter(p => p.protection !== 'PROTECTED')
    .sort((a, b) => rank[a.protection] - rank[b.protection] || (b.value ?? -1) - (a.value ?? -1))
  let oldestRead: string | null = null
  for (const p of counted) if (p.protection === 'PROTECTED' && p.verifiedAt && (oldestRead == null || p.verifiedAt < oldestRead)) oldestRead = p.verifiedAt
  const byBroker = new Map<string, PositionModel[]>()
  for (const p of counted) byBroker.set(p.broker, [...(byBroker.get(p.broker) || []), p])
  const brokers: BrokerInput[] = [...byBroker.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([broker, ps]) => {
    const prot = ps.filter(p => p.protection === 'PROTECTED')
    const gap = ps.some(p => p.protection === 'GAP'), warn = ps.some(p => p.protection === 'WARN')
    const unk = ps.find(p => p.protection === 'UNKNOWN' || p.protection === 'EXEMPT')
    let oldest: string | null = null
    for (const p of prot) if (p.verifiedAt && (oldest == null || p.verifiedAt < oldest)) oldest = p.verifiedAt
    return { broker, state: gap ? 'GAP' : unk ? 'UNKNOWN' : warn ? 'WARN' : 'OK', counted: ps.length, protectedN: prot.length, oldest,
      cause: gap ? 'Unprotected Position' : unk ? unk.cause : warn ? 'Expired Stop' : null }
  })
  return {
    verdict, counted: counted.length, protectedN: n.PROTECTED, gap: n.GAP, warn: n.WARN, unknown: n.UNKNOWN,
    listedNotCounted: positions.filter(p => p.underFloor).length,
    exempt: positions.filter(p => p.protection === 'EXEMPT' || p.isCash).length,
    action, oldestRead, brokers, cause: null,
  }
}

// ── the four financial measures (PortfolioMeasures@v1, LQ-20261113-3124R) ─────────────────────────────
/** The page reads the projection; it never computes a measure. Three rules, from the operator's Q1 decision
 *  (2026-11-13) and the 3124R contract:
 *    1. a value is drawn only when the wire published it with a status — never defaulted, never summed here;
 *    2. the broker store is the anchor and the Finviz estimate is drawn BESIDE it with its delta and timestamp,
 *       never added into any 'today' figure (`finviz_estimates_are_separate`);
 *    3. a missing block is UNKNOWN with the writer's reason, and GET never computes one (absent -> four UNKNOWN).
 *  The four labels are the projection's own; no screen invents a fifth 'today' number. */
export const MEASURES_CONTRACT = 'PortfolioMeasures@v1'
export const MEASURE_KEYS = ['account_value', 'price_move_estimate', 'account_value_change_1d', 'verified_daily_pnl'] as const
export type MeasureKey = (typeof MEASURE_KEYS)[number]
export const MEASURE_LABELS: Record<MeasureKey, string> = {
  account_value: 'Account value',
  price_move_estimate: 'Estimated price movement of current holdings',
  account_value_change_1d: 'Account value change since prior close',
  verified_daily_pnl: 'Verified daily P&L',
}
/** measures_absent().gap.reason (scripts/lib/portfolio_measures.py, folded by 3124R). Quoted, not paraphrased. */
export const MEASURES_ABSENT_REASON = 'this holdings document was written before the measures were materialized; the writer must run once before the four measures are published (GET never computes)'
export const UNVERIFIED_NOTE = 'A verified figure requires a stored, signed, per-account reconciliation; GET never computes one.'
/** A6 (REVIEW-CAMPAIGN8H-item1-fix-cc-deepseek-2): the closed set of statuses that assert a figure. The writer
 *  (`scripts/lib/portfolio_measures.py`, 3124R) emits exactly these; a future status such as GAP must be added here
 *  deliberately before it can draw a number. */
export const FIGURE_STATUSES: ReadonlySet<string> = new Set(['MEASURED', 'VERIFIED', 'PARTIAL'])

export interface MeasureComponent { key: string; label: string; value: number | null; note: string | null }
export interface MeasureView {
  key: MeasureKey; label: string; value: number | null; status: string
  statusClass: 'ok' | 'warn' | 'neutral' | 'bad'
  text: string; definition: string | null; gap: string | null; asOf: string | null
  estimate: { label: string; value: number | null; delta: number | null; at: string | null; note: string | null } | null
  components: MeasureComponent[]
  reconciles: boolean | null
  candidate: number | null
}
export interface MeasuresModel {
  state: 'LOADING' | 'ABSENT' | 'PRESENT' | 'UNREADABLE'
  contractVersion: string | null
  materialized: boolean
  asOf: string | null
  generatedAt: string | null
  reason: string | null
  basis: string | null
  basisWhy: string | null
  finvizSeparate: boolean
  /** The verified daily P&L is not a stored VERIFIED figure (it is UNKNOWN by contract today). */
  dayUnverified: boolean
  measures: MeasureView[]
}

function measureStatusClass(status: string): MeasureView['statusClass'] {
  if (status === 'MEASURED' || status === 'VERIFIED') return 'ok'
  if (status === 'PARTIAL') return 'warn'
  return 'neutral'
}

function emptyMeasure(key: MeasureKey, status: string, text: string, gap: string | null = null): MeasureView {
  return { key, label: MEASURE_LABELS[key], value: null, status, statusClass: measureStatusClass(status), text,
    definition: null, gap, asOf: null, estimate: null, components: [], reconciles: null, candidate: null }
}

function componentValue(v: unknown): number | null {
  const n = num(v)
  return n == null ? null : n
}
function componentNote(v: unknown): string | null {
  return num(v) == null ? 'UNKNOWN — not zero' : null
}
const COMPONENT_LABELS: Record<string, string> = {
  price_move_estimate: 'Estimated price movement of current holdings',
  closed_today_trade_effect: 'Closed-today trade effect',
  fees_today: 'Fees today',
  income_today: 'Income today',
  external_flows_today: 'External flows today',
}

/** One measure from the wire. No arithmetic: every number is the projection's, or it is absent. */
function measureFrom(key: MeasureKey, m: MeasureWire | undefined, block: MeasuresBlockWire, receiptSigned = true): MeasureView {
  if (!m || typeof m !== 'object') {
    return emptyMeasure(key, 'UNKNOWN', `The measures block carries no ${key}.`,
      `The projection published no ${key}; the page does not compute it.`)
  }
  const publishedStatus = typeof m.status === 'string' && m.status.trim() ? m.status.trim().toUpperCase() : null
  const status = publishedStatus ?? 'UNKNOWN'
  const wireValue = num(m.value)
  // C1 (REVIEW-CAMPAIGN8H-item1-...-cc-deepseek-6, F3): a number is drawn only when the wire published it under a
  // status that asserts a figure. A statusless value — or one the wire itself marks UNKNOWN — is not a figure: it is
  // null here, so it can never be drawn in a row or promoted to the header.
  // R5c: a verified daily P&L draws only under a signed receipt — a VERIFIED status alone is not one.
  const receiptAllows = key !== 'verified_daily_pnl' || receiptSigned
  const value = receiptAllows && publishedStatus != null && FIGURE_STATUSES.has(publishedStatus) ? wireValue : null
  const label = (m.label && String(m.label)) || block.labels?.[key] || MEASURE_LABELS[key]
  const gap = m.gap && typeof m.gap === 'object' ? (m.gap.reason ?? null) : null
  const fields: string[] = []
  if (value != null) fields.push(fmtUsd(value, key !== 'account_value'))
  if (publishedStatus == null) fields.push('status not published — not a figure')
  else if (publishedStatus === 'UNKNOWN' && wireValue != null) fields.push('marked UNKNOWN — the wire value is not drawn')
  // A6: any other status outside the closed set is said out loud rather than swallowed by "no figure published".
  else if (value == null && wireValue != null) fields.push(`status ${publishedStatus} does not assert a figure — the wire value is not drawn`)
  if (key === 'account_value' && num(m.rows) != null) fields.push(`${m.rows} rows`)
  if (key === 'price_move_estimate' && m.coverage) {
    const mr = num(m.coverage.measured_rows), ur = num(m.coverage.unknown_rows), rc = num(m.coverage.row_count)
    if (mr != null && rc != null) fields.push(`${mr} of ${rc} rows measured${ur ? `, ${ur} unknown` : ''}`)
  }
  if (key === 'account_value_change_1d' || key === 'verified_daily_pnl') {
    const start = num(m.start?.equity_usd), end = num(m.end?.equity_usd)
    if (start != null || end != null) fields.push(`start ${fmtUsd(start)} → end ${fmtUsd(end)}`)
  }
  if (key === 'verified_daily_pnl' && !receiptSigned) fields.push('no signed reconciliation receipt is on file — a VERIFIED label alone is not a receipt; the figure is not drawn')
  if (key === 'verified_daily_pnl' && value == null && num(m.candidate) != null) fields.push(`candidate ${fmtUsd(num(m.candidate), true)} (not verified)`)
  if (status === 'PARTIAL') fields.push('partial: at least one input is missing')
  if (gap) fields.push(gap)
  if (fields.length === 0) fields.push(status === 'UNKNOWN' ? (gap || 'the projection published no value') : 'no figure published')
  const fin = m.finviz_estimate && typeof m.finviz_estimate === 'object' ? m.finviz_estimate : null
  const estimate = fin
    ? { label: fin.label || 'Finviz mark estimate', value: num(fin.total_with_broker_nav) ?? num(fin.value),
        delta: num(fin.delta_vs_broker) ?? num(fin.delta), at: fin.marks_at ?? null,
        note: fin.delta_note || fin.note || null }
    : null
  const components: MeasureComponent[] = []
  const dd = m.drill_down || (key === 'verified_daily_pnl' ? m.known_components : null)
  if (dd && typeof dd === 'object') {
    for (const k of Object.keys(COMPONENT_LABELS)) {
      const raw = (dd as Record<string, unknown>)[k]
      if (raw === undefined) continue
      components.push({ key: k, label: COMPONENT_LABELS[k], value: componentValue(raw), note: componentNote(raw) })
    }
  }
  return {
    key, label, value, status, statusClass: measureStatusClass(status),
    text: fields.join(' · '), definition: m.definition ?? null, gap, asOf: m.as_of ?? null, estimate, components,
    reconciles: typeof m.drill_down?.reconciles === 'boolean' ? m.drill_down.reconciles : null,
    candidate: num(m.candidate),
  }
}

export function measuresModel(read: Read<HoldingsWire>): MeasuresModel {
  const base = { contractVersion: MEASURES_CONTRACT, materialized: false, asOf: null, generatedAt: null, reason: null,
    basis: null, basisWhy: null, finvizSeparate: true, dayUnverified: true }
  if (read.state === 'LOADING') {
    return { ...base, state: 'LOADING', measures: MEASURE_KEYS.map(k => emptyMeasure(k, 'LOADING', 'reading…')) }
  }
  if (read.state !== 'OK') {
    const why = `${read.source}: ${read.error || read.state}`
    return { ...base, state: 'UNREADABLE', reason: why, measures: MEASURE_KEYS.map(k => emptyMeasure(k, 'UNKNOWN', `Holdings not read: ${why}`)) }
  }
  const block = read.data?.measures
  const present = block && typeof block === 'object' && block.materialized !== false
  /** C1: only a value the wire published under a status that asserts a figure counts as a value in the block. */
  const assertsFigure = (m: MeasureWire | undefined): boolean => {
    if (!m || typeof m !== 'object') return false
    const s = typeof m.status === 'string' ? m.status.trim().toUpperCase() : ''
    return FIGURE_STATUSES.has(s) && num(m.value) != null
  }
  const anyValue = !!(present && block!.measures && Object.values(block!.measures).some(assertsFigure))
  if (!present || (String(block!.status || '').toUpperCase() === 'UNKNOWN' && !anyValue)) {
    const reason = block?.gap?.reason || MEASURES_ABSENT_REASON
    return { ...base, state: 'ABSENT', asOf: block?.as_of ?? null, generatedAt: block?.generated_at ?? null, reason,
      basis: block?.basis?.applied ?? null, basisWhy: block?.basis?.why ?? null,
      measures: MEASURE_KEYS.map(k => emptyMeasure(k, 'UNKNOWN', reason, reason)) }
  }
  const receipt = pnlReceipt(read.data)
  const measures = MEASURE_KEYS.map(k => measureFrom(k, block!.measures?.[k], block!, receipt.signed))
  const v = measures.find(m => m.key === 'verified_daily_pnl')
  return {
    ...base, state: 'PRESENT', contractVersion: block!.contract_version || MEASURES_CONTRACT, materialized: true,
    asOf: block!.as_of ?? null, generatedAt: block!.generated_at ?? null,
    basis: block!.basis?.applied ?? null, basisWhy: block!.basis?.why ?? null,
    finvizSeparate: block!.finviz_estimates_are_separate !== false,
    dayUnverified: !receipt.signed || !v || v.status !== 'VERIFIED',
    measures,
  }
}

// ── coverage counts (display vocabulary; never changes the verdict) ──────────────────────────────────
export interface CoverageCounts {
  covered: number; partial: number; uncovered: number; planned: number; exempt: number; unverifiable: number
  restingShares: number | null; heldShares: number | null
  /** F4 (REVIEW-CAMPAIGN8H-item1): true only when EVERY eligible row published both quantities. When false, the
   *  share totals are a partial sum and every consumer must say "published", never present them as a total. */
  totalsComplete: boolean
  /** R5b #2 (2026-11-14): the six categories above count EVERY row this page drew (30 rows live: covered, under-$100
   *  listed-only, exempt cash, ...). The four tiles count only `counted` rows (11 live). Both are right; the page
   *  must name the relation instead of printing two denominators as one sentence. These fields are that relation,
   *  counted over the same loop so the two populations can never be counted from different rows. */
  rows: number; counted: number
  uncountedUnderFloor: number; uncountedExempt: number
  /** true only when counted + under-$100 + exempt accounts for every drawn row; false means the page must state the
   *  total without asserting a split it cannot prove. */
  uncountedReconciles: boolean
}
export function coverageCounts(ps: PositionModel[]): CoverageCounts {
  const c: CoverageCounts = { covered: 0, partial: 0, uncovered: 0, planned: 0, exempt: 0, unverifiable: 0, restingShares: null, heldShares: null, totalsComplete: false,
    rows: ps.length, counted: 0, uncountedUnderFloor: 0, uncountedExempt: 0, uncountedReconciles: false }
  let rest = 0, held = 0, restKnown = false, heldKnown = false, eligible = 0, both = 0
  for (const p of ps) {
    const cov = p.coverage
    if (p.counted) c.counted++
    else if (p.underFloor) c.uncountedUnderFloor++
    else if (cov.category === 'EXEMPT') c.uncountedExempt++
    if (cov.category === 'COVERED') c.covered++
    else if (cov.category === 'PARTIAL') c.partial++
    else if (cov.category === 'PLANNED_ONLY') c.planned++
    else if (cov.category === 'EXEMPT') c.exempt++
    else if (cov.category === 'UNVERIFIABLE') c.unverifiable++
    else c.uncovered++
    if (cov.category !== 'EXEMPT' && cov.category !== 'UNVERIFIABLE' && !p.isCash) {
      eligible++
      if (cov.restingShares != null) { rest += cov.restingShares; restKnown = true }
      if (cov.heldShares != null) { held += cov.heldShares; heldKnown = true }
      if (cov.restingShares != null && cov.heldShares != null) both++
    }
  }
  c.restingShares = restKnown ? rest : null
  c.heldShares = heldKnown ? held : null
  c.totalsComplete = eligible > 0 && both === eligible
  c.uncountedReconciles = c.counted + c.uncountedUnderFloor + c.uncountedExempt === c.rows
  return c
}

/** The scope sentence both surfaces print in front of the six categories (R5b #2). It states which population the
 *  categories count (every drawn row), which population the tiles count (`counted`), and how the two relate, so the
 *  live page cannot read "11 counted" beside "15 uncovered" as one arithmetic claim. When the split does not
 *  reconcile, the total is stated and the split is not asserted. */
export function coverageScopeRelation(c: CoverageCounts): string {
  const head = `all ${c.rows} row${c.rows === 1 ? '' : 's'} drawn · ${c.counted} counted (the tiles)`
  const uncounted = c.rows - c.counted
  if (uncounted <= 0) return head
  return c.uncountedReconciles
    ? `${head} · ${uncounted} not counted: ${c.uncountedUnderFloor} under $100, listed only · ${c.uncountedExempt} exempt`
    : `${head} · ${uncounted} not counted (the under-$100 / exempt split does not reconcile)`
}

// ── one snapshot, two payload shapes (R5c, b6) ───────────────────────────────────────────────────────
/** R5c (operator 2026-11-14 11:06 ET): Portfolio reads `/api/v2/portfolio/holdings`; Risk reads
 *  `/api/v2/cio/pages`. Both are projections of ONE broker snapshot, but they are two wire shapes with the
 *  position read clock in a different place (`positions_as_of` on one, `positions.as_of` on the other). This is
 *  the single accessor both pages call, so the sentence they render is one computation, not two that happen to
 *  match. `snapshot_id` is published by neither today; it is NAMED as missing, never invented. */
export type SnapshotWire = {
  snapshot_id?: string | null
  positions_as_of?: string | null
  positions?: { as_of?: string | null } | null
}
export interface SnapshotFacts {
  snapshotId: string | null
  observedAt: string | null
  accountCount: number
  accounts: string
  /** The one sentence both pages render verbatim. */
  line: string
  missing: string[]
}
export function snapshotFacts(
  w: SnapshotWire | null | undefined,
  rows: Array<{ account_id?: string | null; account?: string | null }>,
  accountFilter = 'all',
): SnapshotFacts {
  const id = typeof w?.snapshot_id === 'string' && w.snapshot_id.trim() ? w.snapshot_id.trim() : null
  const observedAt = w?.positions_as_of || w?.positions?.as_of || null
  const keys = new Set(rows.map(r => r.account_id ?? r.account ?? null).filter((k): k is string => !!k))
  const accounts = accountFilter && accountFilter !== 'all' ? accountFilter : `all accounts (${keys.size})`
  const missing: string[] = []
  if (id == null) missing.push('snapshot id')
  if (observedAt == null) missing.push('positions read clock')
  const line = `${id ? `snapshot ${id}` : 'snapshot id not published'} · positions read ${observedAt ? `${fmtET(observedAt, true)} ET` : 'clock not published'} · ${accounts}`
  return { snapshotId: id, observedAt, accountCount: keys.size, accounts, line, missing }
}

/** Two reads describe the same snapshot only when they publish the same position clock. `null` = cannot say. */
export function sameSnapshot(a: SnapshotFacts | null | undefined, b: SnapshotFacts | null | undefined): { same: boolean | null; line: string } {
  const x = a?.observedAt ?? null, y = b?.observedAt ?? null
  if (!x || !y) return { same: null, line: 'the two reads cannot be compared: one of them publishes no position clock' }
  if (x === y) return { same: true, line: `the same snapshot clock on both pages: ${fmtET(x, true)} ET` }
  return { same: false, line: `different snapshot clocks: ${fmtET(x, true)} ET here, ${fmtET(y, true)} ET there` }
}

/** R5c item 3: the verified daily P&L is licensed by a SIGNED reconciliation receipt, not by a measure status.
 *  The producer marks it UNKNOWN today (reconciliation total `provisional: true`), so this gate is dormant; it
 *  exists so a producer that one day sends `status: VERIFIED` without a receipt cannot make the page print a
 *  plausible number. `verified: false` and an absent receipt are the same fact. */
export interface PnlReceiptWire {
  broker_contract?: { pnl?: { verified?: boolean | null } | null } | null
  measures?: { broker_contract?: { pnl?: { verified?: boolean | null } | null } | null } | null
  reconciliation?: { total?: { verified?: boolean | null } | null } | null
}
export function pnlReceipt(w: PnlReceiptWire | null | undefined): { signed: boolean; line: string } {
  const signed = [w?.broker_contract?.pnl?.verified, w?.measures?.broker_contract?.pnl?.verified,
    w?.reconciliation?.total?.verified].some(v => v === true)
  return { signed, line: signed ? 'a signed reconciliation receipt is on file' : 'no signed reconciliation receipt is on file' }
}

// ── OBS-P1: mark, session price move, weight, unrealized P&L (operator 2026-11-14 11:15 ET) ─────────
/** The four facts the operator read as missing from the live rows. Each is drawn from the read, never computed:
 *  the mark and its source/clock, the market value, the session PRICE MOVE (never P&L), and unrealized P&L only on a
 *  recorded cost basis — with the read's own reason when there is none. Weight is drawn only if the producer published
 *  it; the page never divides two served numbers (one-broker rule). */
export interface BasisView {
  status: 'RECORDED' | 'UNKNOWN'
  usd: number | null
  pnlUsd: number | null
  pnlPct: number | null
  source: string | null
  /** The precise sentence to print in place of a P&L figure. Never a zero, never blank. */
  reason: string | null
  /** A recorded basis the read flags as conflicting is named, never silently chosen. */
  conflict: string | null
  /** REVIEW F1: why a RECORDED basis still has no figure (the read withheld the mark/value), else null. Kept
   *  apart from `reason`, which says why there is no USABLE BASIS — the two must never share a sentence. */
  pnlGap: string | null
}

export function basisView(h: HoldingWire | null | undefined): BasisView {
  const t = h?.basis_truth ?? null
  const usd = num(t?.cost_basis_usd) ?? num(h?.cost_basis)
  const partial = h?.basis_partial === true || h?.basis_unknown === true
  const statusRaw = String(t?.status ?? h?.basis_status ?? '').toLowerCase()
  const conflict = Array.isArray(t?.conflicts) && t!.conflicts!.length
    ? String(t!.conflicts![0]?.reason || 'the read flags a cost-basis conflict') : null
  // REVIEW F2: a verdict is drawn from a verdict. Only the read's own `recorded` status licenses a basis (and,
  // with it, a P&L figure). The earlier `statusRaw !== 'unknown'` also licensed a row that published NO status at
  // all — the page manufactured a verdict the producer never gave. `unknown`, absent, and any other value are all
  // non-recorded now, each with a reason that says which.
  if (statusRaw === 'recorded' && usd != null && usd > 0 && !partial) {
    const pnlUsd = num(t?.unrealized_pl_usd)
    return { status: 'RECORDED', usd, pnlUsd, pnlPct: num(t?.unrealized_pl_pct),
      source: String(t?.source || h?.cost_basis_source || '') || null, reason: null, conflict,
      // REVIEW F1: cio_truth keeps status 'recorded' with unrealized_pl_usd null when the row has no mark and no
      // market_value (value None -> pnl None). The basis is present; only the figure is absent, and the row names
      // which input the read withheld.
      pnlGap: pnlUsd != null ? null
        : num(h?.price) == null && num(h?.market_value) == null
          ? 'the read publishes no unrealized figure because the row has no published mark or market value'
          : 'the read publishes no unrealized figure for this row' }
  }
  // The read's own gap sentence wins; the fallback names the exact field that is missing, never "0".
  const reason = String(t?.gap?.reason || '') || (partial
    ? 'cost basis is partial — the broker lot history starts after some acquisitions'
    : statusRaw && statusRaw !== 'unknown'
      ? `basis status "${statusRaw}" is not a recorded basis`
      : usd != null && usd > 0
        ? 'a cost basis value is present but no basis status is published in this read — not treated as recorded'
        : usd != null && usd <= 0
          ? 'cost basis is zero or negative in the read — not a usable acquisition cost'
          : 'cost basis not reported by the broker read')
  return { status: 'UNKNOWN', usd: null, pnlUsd: null, pnlPct: null, source: null, reason, conflict, pnlGap: null }
}

export interface PriceClock { at: string | null; perRow: boolean; line: string }
/** The clock a mark was observed at. A row's own `price_as_of` when published; otherwise the read's batch quote clock,
 *  labelled AS the batch — the row never inherits a per-row time it does not have. */
export function priceClock(h: HoldingWire | null | undefined, w: HoldingsWire | null | undefined): PriceClock {
  const own = h?.price_as_of ?? null
  if (own) return { at: own, perRow: true, line: `quote read ${fmtET(own, true)} ET` }
  const batch = w?.quote_as_of ?? null
  if (batch) return { at: batch, perRow: false, line: `book quote clock ${fmtET(batch, true)} ET · no per-row quote time published` }
  return { at: null, perRow: false, line: 'no quote clock published in this read' }
}

export interface MoneyLine { text: string; known: boolean; cls: 'up' | 'dn' | null }
/** The session move, labelled a PRICE MOVE. (price - prior close) has never been a verified P&L: the aggregate day
 *  figure is documented as mixing prior-mark deltas with fill-aware session P&L, so this line never says "P&L". */
export function moveToday(p: Pick<PositionModel, 'isCash' | 'dayUsd' | 'dayPct'>): MoneyLine {
  if (p.isCash) return { text: 'cash row · no price move', known: true, cls: null }
  const usd = p.dayUsd, pct = p.dayPct
  if (usd == null && pct == null) return { text: 'price move today not published in this read', known: false, cls: null }
  const parts: string[] = []
  if (pct != null) parts.push(fmtPct(pct))
  if (usd != null) parts.push(fmtUsd(usd, true))
  const v = usd ?? pct
  return { text: `price move today ${parts.join(' · ')}${usd == null ? ' · $ move not published' : ''}`, known: true, cls: v == null || v === 0 ? null : v > 0 ? 'up' : 'dn' }
}

/** OP-026: the weighted remaining basis, with its per-share average, from the SAME recorded basis the unrealized line
 *  uses. A missing basis is named as such — the phrase "basis not recorded" plus the read's own reason — and it never
 *  suppresses the mark, the market value or the price move (missing basis blocks unrealized P&L, not price facts). */
export function basisLine(p: Pick<PositionModel, 'isCash' | 'avgEntry' | 'basis'>): MoneyLine {
  if (p.isCash) return { text: 'cash row · no cost basis', known: true, cls: null }
  if (p.basis.status !== 'RECORDED' || p.basis.usd == null) {
    return { text: `basis not recorded — ${p.basis.reason || 'no recorded acquisition cost in this read'}`, known: false, cls: null }
  }
  const avg = p.avgEntry == null ? ' · avg entry not computable (no published share count)' : ` · avg entry $${p.avgEntry.toFixed(2)}`
  return { text: `basis ${fmtUsd(p.basis.usd)}${avg}${p.basis.conflict ? ` · ${p.basis.conflict}` : ''}`, known: true, cls: null }
}

/** Unrealized P&L — drawn ONLY on a recorded basis, with the basis named. Otherwise the reason, never a figure. */
export function unrealizedLine(b: BasisView, fmt: (v: number) => string = v => fmtUsd(v, true)): MoneyLine {
  if (b.status !== 'RECORDED') {
    return { text: `unrealized P&L not shown — ${b.reason || 'no recorded cost basis in this read'}`, known: false, cls: null }
  }
  // REVIEW F1: the basis IS recorded; only the figure is not published. Saying "no recorded cost basis" here
  // contradicted the Cost basis field on the same row (and its CSV line), which carries the dollar amount.
  if (b.pnlUsd == null) {
    // A cost basis is a stock, not a delta: drawn unsigned, never "+$1,500".
    return { text: `unrealized P&L not published in this read — a recorded cost basis${b.usd != null ? ` (${fmtUsd(b.usd)})` : ''} is present; ${b.pnlGap || 'the read publishes no unrealized figure for this row'}`, known: false, cls: null }
  }
  const pct = b.pnlPct == null ? ' % not published' : ` (${fmtPct(b.pnlPct)})`
  return { text: `${fmt(b.pnlUsd)}${pct} on recorded basis${b.source ? ` · ${b.source}` : ''}`, known: true, cls: b.pnlUsd === 0 ? null : b.pnlUsd > 0 ? 'up' : 'dn' }
}

export function weightLine(p: Pick<PositionModel, 'isCash' | 'weightPct' | 'weightBasis'>): MoneyLine {
  if (p.isCash) return { text: 'cash row · no position weight', known: true, cls: null }
  if (p.weightPct == null) return { text: 'weight not published in this read', known: false, cls: null }
  return { text: `${p.weightPct.toFixed(1)}% of ${p.weightBasis || 'the book (basis not named in the read)'}`, known: true, cls: null }
}

export interface BasisCoverage { recorded: number; missing: number; total: number; line: string }
/** "N of M positions have a recorded cost basis", over the non-cash rows this read drew (cash has no basis). An empty
 *  population is named as empty — never "0 of 0" and never a full-coverage claim. */
export function basisCoverage(ps: PositionModel[]): BasisCoverage {
  const rows = ps.filter(p => !p.isCash)
  const recorded = rows.filter(p => p.basis.status === 'RECORDED').length
  const missing = rows.length - recorded
  const line = rows.length === 0
    ? 'no non-cash rows in this read, so cost-basis coverage cannot be counted'
    : `cost basis recorded for ${recorded} of ${rows.length} non-cash position${rows.length === 1 ? '' : 's'}${missing ? ` (${missing} without a usable basis — their unrealized P&L is not drawn)` : ''}`
  return { recorded, missing, total: rows.length, line }
}

// ── CSV export (client-side; served columns only, no computed P&L) ───────────────────────────────────
/** OBS-P1: the CSV carries the same four facts the rows draw, the basis verdict WITH its reason, and the one snapshot
 *  identity every surface of the page read (`snapshotFacts()`), so an exported row cannot disagree with its row. */
export const CSV_COLUMNS = ['symbol', 'account', 'broker', 'held_shares', 'resting_stop_shares', 'coverage', 'protection',
  'price_usd', 'price_source', 'price_as_of', 'price_stale', 'value_usd', 'weight_pct', 'weight_basis',
  'move_today_usd', 'move_today_pct', 'basis_status', 'cost_basis_usd', 'avg_entry_usd', 'unrealized_pnl_usd', 'unrealized_pnl_pct',
  'basis_reason', 'basis_source', 'stop_price', 'stop_source', 'stop_order_id', 'verified_at', 'reason',
  'hypothetical_downside_to_stop_usd', 'hypothetical_downside_to_stop_pct', 'downside_state',
  'downside_covered_qty', 'downside_uncovered_qty', 'downside_uncovered_state', 'downside_reason', 'downside_formula',
  'snapshot_id', 'positions_as_of'] as const
function csvCell(v: unknown): string {
  const s = v == null ? '' : String(v)
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}
export function holdingsCsv(ps: PositionModel[], snap?: Pick<SnapshotFacts, 'snapshotId' | 'observedAt'> | null, nowMs: number = Date.now()): string {
  const lines = [CSV_COLUMNS.join(',')]
  for (const p of ps) {
    const b = p.basis
    // OP-023: the downside columns come from the SAME derivation the row and the sheet draw, at the same clock, so an
    // exported value cannot disagree with the row it came from. A state is exported where no figure exists.
    const d = downsideToStop(p, { nowMs })
    lines.push([
      p.symbol, p.account, p.broker, p.shares, p.restingShares, p.coverage.category, p.protection,
      p.price, p.priceSource, p.priceAt, p.priceStale, p.value, p.weightPct, p.weightBasis,
      p.isCash ? null : p.dayUsd, p.isCash ? null : p.dayPct,
      b.status, b.usd, p.avgEntry, b.pnlUsd, b.pnlPct, b.status === 'UNKNOWN' ? b.reason : null, b.source,
      p.stopPrice, p.raw.stop_source ?? p.source, p.raw.stop_order_id ?? p.raw.order_id ?? null,
      p.verifiedAt, p.reason,
      d.usd, d.pct == null ? null : Number(d.pct.toFixed(2)), d.state,
      d.coveredQty, d.uncoveredQty, d.uncoveredState, d.reason, d.formula,
      snap?.snapshotId ?? null, snap?.observedAt ?? null,
    ].map(csvCell).join(','))
  }
  return lines.join('\r\n')
}

export interface P0Item { category: string; detail: string }
export function p0Items(read: Read<HoldingsWire>, prot: ProtectionModel): P0Item[] | null {
  if (read.state !== 'OK') return null  // cannot be counted; never "0"
  const out: P0Item[] = []
  const gaps = prot.action.filter(p => p.protection === 'GAP')
  if (gaps.length) out.push({ category: 'Unprotected Position', detail: `${gaps.map(p => p.symbol).join(', ')}: no resting stop in a good read` })
  // R2: the last-known GAP and its P0 row stay visible while the verdict reads UNKNOWN.
  const lastKnown = prot.action.filter(p => p.lastKnownGap)
  if (lastKnown.length) out.push({ category: 'Unprotected Position (stale read)', detail: `${lastKnown.map(p => p.symbol).join(', ')}: last read showed no resting stop; the read is past its freshness limit` })
  // C6 (REVIEW-CAMPAIGN8H-item1-fix-cc-deepseek-2): a P0 comes only from a finding the count contract PUBLISHED.
  // `agree === false` is the cross-scope flag — false on every real book — and raising a P0 from it put "1 P0" on
  // a healthy, fully protected page (and in the served v002 build).
  const pcRows = read.data?.position_counts
  const finding = Array.isArray(pcRows?.findings) ? pcRows!.findings!.find(f => f && (f.detail || f.code)) : null
  if (finding) {
    out.push({ category: 'Position Count Mismatch', detail: String(finding.detail || finding.code) })
  }
  return out
}

// ── status rows ───────────────────────────────────────────────────────────────────────────────────────
export type StatusState = 'OK' | 'STALE' | 'UNKNOWN' | 'TIMED OUT' | 'LOADING' | 'WARN'
export interface StatusRow {
  id: string; name: string; state: StatusState | string; text: string; cause?: string; needsBackend?: boolean
  /** PR-006: the exact evidence set this count covers, one tap away. A count without a destination is a claim. */
  href?: string
}
export const LIMITS = { positionsMs: 60 * 60_000, pricesMs: 30 * 60_000, alertsMs: 15 * 60_000 }

export function statusRows(hr: Read<HoldingsWire>, ir: Read<IncidentsWire>, positions: PositionModel[], nowMs: number): StatusRow[] {
  const rows: StatusRow[] = []
  const w = hr.data
  // Value/Today are NOT drawn here: the four measures block (measuresModel) owns every financial figure, so the page
  // can never show a store number beside a projection number as if they were two candidates. This row is the
  // positions-store read health only (the mock's "Value OK · positions 28 m old").
  if (hr.state !== 'OK') {
    const st = hr.state
    rows.push({ id: 'row-value', name: 'Positions read', state: st, text: st === 'LOADING' ? 'reading…' : `${hr.error || st}`, cause: st === 'LOADING' ? undefined : `Source: ${API.holdings}` })
  } else {
    const a = ageMs(w?.positions_as_of, nowMs)
    const vs: StatusState = a == null ? 'UNKNOWN' : a > LIMITS.positionsMs ? 'STALE' : 'OK'
    rows.push({ id: 'row-value', name: 'Positions read', state: vs,
      text: a == null ? 'no positions timestamp in the read' : `positions ${fmtAge(a)} old · limit 60 m`,
      cause: vs === 'OK' ? undefined : 'Cause: Positions Sync · Source: positions store · Owner: position sync lane' })
  }
  rows.push({ id: 'row-risk', name: 'Risk', state: 'UNKNOWN', text: 'pending decision: no approved risk-score definition (G7)', needsBackend: true })
  if (hr.state === 'OK') {
    const priced = positions.filter(p => !p.isCash)
    const stale = priced.filter(p => p.priceStale === true)
    const unknownFresh = priced.filter(p => p.priceStale == null && !p.raw.price_as_of)
    const qa = ageMs(hr.data?.quote_as_of, nowMs)
    const st: StatusState = stale.length ? 'STALE' : unknownFresh.length || qa == null ? 'UNKNOWN' : qa > LIMITS.pricesMs ? 'STALE' : 'OK'
    rows.push({ id: 'row-prices', name: 'Prices', state: st,
      text: stale.length ? `${stale.length} of ${priced.length} stale · quotes ${fmtAge(qa)} old · limit 30 m`
        : `${priced.length} priced · quotes ${fmtAge(qa)} old · limit 30 m`,
      cause: stale.length ? `Cause: Market Feed (${stale.slice(0, 4).map(p => p.symbol).join(', ')}${stale.length > 4 ? '…' : ''}) · Source: quote cache · Owner: repricer lane` : undefined })
  } else {
    rows.push({ id: 'row-prices', name: 'Prices', state: hr.state, text: hr.state === 'LOADING' ? 'reading…' : 'no read' })
  }
  if (ir.state === 'OK') {
    const c = ir.data?.counts
    const a = ageMs(ir.data?.served_at || ir.at, nowMs)
    // PR-006: the count names its entity and its scope — open lifecycle incidents across ALL pages, deduplicated by
    // the shared incident store. It is a different population from the position review count above, and says so.
    if (!c || (c.P0 == null && c.P1 == null)) rows.push({ id: 'row-alerts', name: 'Incidents · all pages', state: 'UNKNOWN', text: 'no counts in the read', href: '/ops/incidents' })
    else rows.push({ id: 'row-alerts', name: 'Incidents · all pages', state: (c.P0 ?? 0) > 0 ? 'WARN' : 'OK',
      text: `${c.P0 ?? 0} P0 · ${c.P1 ?? 0} P1 open lifecycle incidents · read ${fmtAge(a)} old · limit 15 m · not the position review count`,
      href: '/ops/incidents' })
  } else {
    rows.push({ id: 'row-alerts', name: 'Incidents · all pages', state: ir.state, text: ir.state === 'LOADING' ? 'reading…' : `${ir.error || ir.state}`, href: '/ops/incidents' })
  }
  return rows
}

// ── filters ───────────────────────────────────────────────────────────────────────────────────────────
/** `covered`, `partial`, `unprotected` (no broker stop: uncovered or planned-only, never a plan counted as a stop)
 *  and `unknown` are MUTUALLY EXCLUSIVE over the counted population (PR-001): a row appears in exactly one of the
 *  four, so the tiles on the page sum to the counted total. `planned` is the independent facet filter (PR-017):
 *  any row carrying a planned level, whatever its broker-evidence state. */
export type HoldingsFilter = 'all' | 'covered' | 'unprotected' | 'partial' | 'planned' | 'unknown' | 'exempt' | 'under100' | 'review'
export function filterPositions(ps: PositionModel[], f: HoldingsFilter, account: string): PositionModel[] {
  return ps.filter(p => (account === 'all' || p.account === account) && (
    f === 'all' ? true
      : f === 'covered' ? p.counted && p.coverage.category === 'COVERED'
        : f === 'unprotected' ? p.counted && (p.coverage.category === 'UNCOVERED' || p.coverage.category === 'PLANNED_ONLY')
          : f === 'partial' ? p.counted && p.coverage.category === 'PARTIAL'
            : f === 'planned' ? p.planned != null || p.coverage.category === 'PLANNED_ONLY'
              : f === 'unknown' ? p.counted && p.coverage.category === 'UNVERIFIABLE'
                : f === 'exempt' ? p.coverage.category === 'EXEMPT'
                  : f === 'review' ? p.counted && (p.protection === 'GAP' || p.lastKnownGap)
                    : p.underFloor))
}

/** PR-006: the positions a stop-review badge counts — unprotected in a good read, or the last-known GAP kept while
 *  its read is stale. Never a category count, never an incident count: this is one entry per position. */
export function reviewPositions(ps: PositionModel[]): PositionModel[] {
  return ps.filter(p => p.counted && (p.protection === 'GAP' || p.lastKnownGap))
}

/** PR-001: the four mutually exclusive counted-position states, so the headline tiles add to the counted total and
 *  a partial position is never counted as fully covered. Exempt and under-floor rows are outside `counted`. */
export interface ExclusiveCoverage { covered: number; partial: number; noStop: number; unknown: number; counted: number; complete: boolean }
export function exclusiveCoverage(ps: PositionModel[]): ExclusiveCoverage {
  const counted = ps.filter(p => p.counted)
  const n = { covered: 0, partial: 0, noStop: 0, unknown: 0 }
  // N1 (REVIEW-S2-portfolio-risk-b1 §6): an `else` catch-all made `complete` true by construction, so the page's
  // "the four states do not add to the counted total" sentence was dead. Every category is named here; one this rollup
  // does not know leaves the total short and the page says so instead of quietly calling it Unknown.
  let known = 0
  for (const p of counted) {
    const c = p.coverage.category
    if (c === 'COVERED') n.covered++
    else if (c === 'PARTIAL') n.partial++
    else if (c === 'UNCOVERED' || c === 'PLANNED_ONLY') n.noStop++
    else if (c === 'UNVERIFIABLE' || c === 'EXEMPT') n.unknown++
    else continue
    known++
  }
  return { ...n, counted: counted.length, complete: known === counted.length }
}

// ── scope and coverage (PR-002) ───────────────────────────────────────────────────────────────────────
/** PR-002 (sprint 8H-2): one line that names every denominator the page uses, so "Holdings · 30 / $1,255,586 ·
 *  33 rows / 28 of 33 measured / 2 of 25 stale / showing 25 of 30 / 11 counted" can be reconciled without opening
 *  source code. Every number is a served field or a count of the rows this read drew; none is computed P&L. A fact
 *  the read does not publish (today: the snapshot id, until BrokerContract@v1 lands on the wire) is NAMED as not
 *  published rather than omitted or invented. */
export interface ScopeCoverage {
  accounts: string
  sourceRows: number | null; cashRows: number | null; nonCashRows: number | null; unpricedRows: number | null
  countedHere: number; countedScope: string
  blockHeadline: number | null; blockScope: string | null
  quoteable: number; drawn: number; filtered: number; rendered: number
  snapshotId: string | null
  /** Named facts the read does not publish. Never silently dropped. */
  missing: string[]
  /** Named disagreements between two published denominators (never a verdict). */
  mismatches: string[]
}
export function scopeCoverage(
  read: Read<HoldingsWire>, ps: PositionModel[], o: { account: string; filtered: number; rendered: number },
): ScopeCoverage {
  const w = read.state === 'OK' ? read.data : null
  const pc = w?.position_counts
  const scope = (k: string): number | null => {
    const v = pc?.scopes?.[k]
    return typeof v === 'number' && Number.isFinite(v) ? v : null
  }
  const sourceRows = typeof pc?.all_rows === 'number' ? pc.all_rows : scope('holdings.all_rows')
  const countedHere = ps.filter(p => p.counted).length
  const blockHeadline = typeof pc?.position_count === 'number' ? pc.position_count : null
  const blockScope = typeof pc?.primary_scope === 'string' && pc.primary_scope ? pc.primary_scope : null
  const quoteable = ps.filter(p => !p.isCash && p.price != null).length
  const snapshotId = typeof w?.snapshot_id === 'string' && w.snapshot_id.trim() ? w.snapshot_id.trim() : null
  const missing: string[] = []
  if (read.state !== 'OK') missing.push('every count (the holdings read failed)')
  else {
    // R5c: the snapshot id is named by snapshotFacts()'s own line (shared with Risk); it is not repeated here.
    if (sourceRows == null) missing.push('source row count (the count block names no all-rows scope)')
  }
  const mismatches: string[] = []
  if (read.state === 'OK' && sourceRows != null && sourceRows !== ps.length) {
    mismatches.push(`the count block's all-rows scope counts ${sourceRows}; this read parsed ${ps.length} rows`)
  }
  return {
    // REVIEW O1: the account count is over the account KEY, never the display label — the Scope line and the
    // snapshot line on the same row must not print two different account counts for one book.
    accounts: o.account === 'all' ? `all accounts (${new Set(ps.map(p => p.accountKey)).size})` : o.account,
    sourceRows, cashRows: scope('holdings.cash'), nonCashRows: scope('holdings.non_cash'),
    unpricedRows: scope('holdings.unpriced'),
    countedHere, countedScope: 'non-cash, non-exempt rows this page drew',
    blockHeadline, blockScope,
    quoteable, drawn: ps.length, filtered: o.filtered, rendered: o.rendered,
    snapshotId, missing, mismatches,
  }
}

/** The classic stop desk link carries the full position identity (2026-11-14 campaign): symbol, the account key
 *  both as `account` (the lot the hub focuses) and `acct` (its account filter), the broker and the position key.
 *  The Stop Management tab consumes symbol+acct; the extra broker/position keys name the same row for the desk. */
export function stopDeskHref(p: PositionModel): string {
  const q = new URLSearchParams()
  q.set('tab', 'Stop Management')
  q.set('symbol', p.symbol)
  q.set('account', p.accountKey)
  q.set('acct', p.accountKey)
  q.set('broker', p.broker)
  q.set('position', p.key)
  q.set('drawerTab', 'stops')
  return `/portfolio-classic?${q.toString()}`
}

// ── position detail (value provenance, operator focus 2) ─────────────────────────────────────────────
export interface FieldRow { field: string; value: string; age: string; provenance: string; needsBackend?: boolean }
export function positionFields(p: PositionModel, w: HoldingsWire | null, nowMs: number): FieldRow[] {
  const h = p.raw
  const sharesAt = h.shares_synced_at || w?.positions_as_of || null
  const priceAt = h.price_as_of || w?.quote_as_of || null
  const valueAt = h.market_value_as_of || w?.valuation_as_of || null
  const cov = p.coverage
  return [
    { field: 'Shares', value: fmtShares(p.shares), age: fmtAge(ageMs(sharesAt, nowMs)), provenance: `Source: positions store · Writer: position sync lane · as of ${fmtET(sharesAt, true)}` },
    { field: 'Resting stop', value: cov.restingShares == null ? 'not published' : `${fmtShares(cov.restingShares)} of ${fmtShares(cov.heldShares)} held`,
      age: fmtAge(ageMs(p.verifiedAt, nowMs)), provenance: `Source: ${p.source} · stop quantity from the broker read (stop_qty)` },
    { field: 'Coverage', value: `${cov.label}${cov.restingShares != null && cov.heldShares != null ? ` · ${fmtShares(cov.restingShares)} of ${fmtShares(cov.heldShares)} shares` : ''}`,
      age: fmtAge(ageMs(p.verifiedAt, nowMs)), provenance: cov.detail },
    { field: 'Identity', value: `${p.accountKey} · ${p.broker}`, age: '—',
      provenance: `Position: ${p.symbol}${p.raw.stop_order_id || p.raw.order_id ? ` · order ${p.raw.stop_order_id || p.raw.order_id}` : ' · no order id in the read'}` },
    { field: 'Price', value: p.price == null ? 'not published' : `$${p.price.toFixed(2)}`, age: fmtAge(ageMs(priceAt, nowMs)),
      provenance: `Source: ${h.price_source || h.quote_source || 'not named in the read'} · Writer: repricer lane${p.priceStale ? ' · STALE' : ''} · ${priceClock(h, w).line}` },
    { field: 'Value', value: fmtUsd(p.value), age: fmtAge(ageMs(valueAt, nowMs)),
      provenance: `Source: ${h.market_value_source || 'shares × price'} · per-field writer/refresh not served (G5)`, needsBackend: true },
    { field: 'Weight', value: weightLine(p).text, age: '—',
      provenance: 'Position weight is drawn only when the read publishes it; this page never divides two served numbers.' },
    { field: 'Cost basis', value: p.isCash ? 'not applicable (cash row)' : p.basis.status === 'RECORDED' ? fmtUsd(p.basis.usd) : 'basis not recorded',
      age: '—', provenance: p.isCash ? 'A cash balance has no acquisition cost; no P&L is drawn from one.'
        : p.basis.status === 'RECORDED'
          ? `Source: ${p.basis.source || h.cost_basis_source || 'not named in the read'}${p.basis.conflict ? ` · ${p.basis.conflict}` : ''}`
          : p.basis.reason || 'no recorded acquisition cost' },
    // OP-026: the weighted remaining basis per share — the same number the holdings row prints, from the same basis.
    { field: 'Avg entry', value: p.isCash ? 'not applicable (cash row)' : p.avgEntry == null ? 'not recorded (no usable basis)' : `$${p.avgEntry.toFixed(2)}`,
      age: '—', provenance: 'Weighted remaining basis ÷ held shares, computed from the recorded cost basis — never the wire avg_cost field.' },
    { field: 'Unrealized P&L', value: p.isCash ? 'cash row · no unrealized P&L' : unrealizedLine(p.basis).text, age: '—',
      provenance: 'Drawn only on a recorded cost basis; otherwise the read’s own reason is printed — never a zero.' },
    { field: 'Price move today', value: p.isCash ? 'cash row' : p.dayUsd == null && p.dayPct == null ? 'not published'
      : `${p.dayPct == null ? '% not published' : fmtPct(p.dayPct)} · ${p.dayUsd == null ? '$ move not published' : fmtUsd(p.dayUsd, true)}`,
      age: fmtAge(ageMs(priceAt, nowMs)),
      provenance: `Served value vs prior close${num(h.prior_close) != null ? ` $${num(h.prior_close)!.toFixed(2)}` : ''} · Source: quote cache · this is a price move, NOT P&L — nothing here is reconciled` },
    { field: 'Book snapshot', value: w?.snapshot_id || 'snapshot id not published', age: fmtAge(ageMs(w?.positions_as_of, nowMs)),
      provenance: `Positions read ${w?.positions_as_of ? `${fmtET(w.positions_as_of, true)} ET` : 'clock not published'} — the same identity the header and the CSV carry` },
    { field: 'Stop', value: p.protection === 'PROTECTED' ? p.chip : p.protection === 'UNKNOWN' ? 'UNKNOWN' : p.protection === 'EXEMPT' ? 'exempt' : cov.chip,
      age: fmtAge(ageMs(p.verifiedAt, nowMs)), provenance: `Source: ${p.source} · Writer: stop read lane · ${p.reason}` },
    { field: 'Risk', value: 'PENDING DECISION', age: '—', provenance: 'no approved risk-score definition (G7); nothing is scored here', needsBackend: true },
  ]
}

// ── audit categories (lifecycle labels need the validation_events store: NEEDS BACKEND) ──────────────
export interface AuditCategory { category: string; count: number; symbols: string[]; source: string; owner: string }
export function auditCategories(prot: ProtectionModel, p0: P0Item[] | null): AuditCategory[] {
  const out: AuditCategory[] = []
  const gap = prot.action.filter(p => p.protection === 'GAP'), warn = prot.action.filter(p => p.protection === 'WARN')
  const unk = prot.action.filter(p => p.protection === 'UNKNOWN')
  if (gap.length) out.push({ category: 'Unprotected Position', count: gap.length, symbols: gap.map(p => p.symbol), source: 'stop store', owner: STOP_OWNER })
  if (warn.length) out.push({ category: 'Expired Stop', count: warn.length, symbols: warn.map(p => p.symbol), source: 'stop store', owner: STOP_OWNER })
  if (unk.length) out.push({ category: 'Protection Unknown', count: unk.length, symbols: unk.map(p => p.symbol), source: 'stop store', owner: STOP_OWNER })
  for (const i of p0 || []) if (i.category === 'Position Count Mismatch') out.push({ category: i.category, count: 1, symbols: [], source: 'positions store', owner: 'position sync lane' })
  return out
}

// ── Since your last visit: the anchor (portfolio.last_seen, LQ-2467) ─────────────────────────────────
/** The anchor is readable, and since PR-005 the change LIST is served too (ValidationChanges / PortfolioChanges@v1):
 *  the sheet asks `GET /api/v2/portfolio/changes?since=<seen_at>`, where `seen_at` is the value the SERVER returned
 *  before this load stamped its own visit. A visit is recorded only after the page's reads settle, and the server
 *  stamps it (scripts/lib/home_last_seen.py) — the client never sends a time. */
export interface LastSeenReadWire {
  status?: string; window_basis?: string; last_visit_recorded?: boolean; fallback_window_hours?: number; fallback_text?: string
  seen_at?: string | null; previous_seen_at?: string | null; age_sec?: number | null; device?: string | null; schema?: string; reason?: string
}
export interface LastSeenWire { ok?: boolean; key?: string; value?: unknown; updated_at?: string | null; read?: LastSeenReadWire | null }
export type VisitRecord = 'PENDING' | 'RECORDED' | 'REFUSED' | 'FAILED'
export interface SinceVisitModel {
  status: 'RECORDED' | 'NOT_RECORDED' | 'UNKNOWN' | 'LOADING'
  windowBasis: string; windowText: string
  seenAt: string | null; previousSeenAt: string | null; device: string | null; reason: string | null
}
export function sinceVisitModel(read: Read<LastSeenWire>): SinceVisitModel {
  const base = { windowBasis: 'fallback_24h', seenAt: null, previousSeenAt: null, device: null, reason: null }
  if (read.state === 'LOADING') return { ...base, status: 'LOADING', windowText: 'reading…' }
  if (read.state !== 'OK') return { ...base, status: 'UNKNOWN', reason: `${read.source}: ${read.error || read.state}`,
    windowText: `The last-visit read did not complete (${read.error || read.state}); the window is unknown.` }
  const r = read.data?.read
  if (!r || typeof r !== 'object') return { ...base, status: 'UNKNOWN', reason: 'the prefs route returned no reading',
    windowText: 'The prefs route returned no reading; the window is unknown.' }
  const raw = String(r.status || 'UNKNOWN').toUpperCase()
  const status: SinceVisitModel['status'] = raw === 'RECORDED' || raw === 'NOT_RECORDED' ? raw : 'UNKNOWN'
  const windowBasis = String(r.window_basis || 'fallback_24h')
  const seenAt = r.seen_at ?? null
  const age = num(r.age_sec)
  const windowText = status === 'RECORDED' && seenAt
    ? `Since your last visit ${fmtET(seenAt, true)} ET${age != null ? ` (${fmtAge(age * 1000)} ago)` : ''}`
    : status === 'NOT_RECORDED' ? (r.fallback_text || 'Your last visit is not recorded; the window is the last 24 h.')
      : `The last-visit record is unreadable (${r.reason || 'no valid seen_at'}); the window is unknown.`
  return { status, windowBasis, windowText, seenAt, previousSeenAt: r.previous_seen_at ?? null,
    device: r.device ?? null, reason: r.reason ?? null }
}
export function deviceOf(width: number): 'phone' | 'desktop' { return width < 768 ? 'phone' : 'desktop' }
/** Stamp this visit (same route and gate as Home): server owns the times; only the device is sent. */
export async function recordPortfolioVisit(width: number, fetchImpl: typeof fetch = fetch): Promise<VisitRecord> {
  try {
    const r = await fetchImpl(API.prefs, {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: PORTFOLIO_LAST_SEEN_KEY, value: { device: deviceOf(width) } }),
    })
    if (r.status === 401 || r.status === 403) return 'REFUSED'
    if (!r.ok) return 'FAILED'
    const body = (await r.json().catch(() => null)) as { ok?: boolean } | null
    return body && body.ok === false ? 'REFUSED' : 'RECORDED'
  } catch {
    return 'FAILED'
  }
}

// ── gate evidence + the served portfolio gate store (PR-004, sprint 8H-2) ────────────────────────────
/** Each gate the design expects, with the evidence THIS page can see and what the served store answers. The evidence
 *  is page-computed and labelled as such; a gate is never reported open or closed without a served row. */
export interface GateEvidence {
  gate: string; blocks: string; blocksTrading: boolean; threshold: string; pageEvidence: string
  /** PR-004: the id a store declaration would carry for this expectation. Naming it lets a declaration match; it is
   *  not a claim that one exists. */
  expectsGateId: string
  /** PR-004: what the served gate store says about this expectation. `UNAVAILABLE` = the read failed, so no verdict may
   *  be drawn; `NOT_GATED_BY_STORE` = the store was read and declares no gate with `expectsGateId`; `GATED` = it does. */
  served: 'GATED' | 'NOT_GATED_BY_STORE' | 'UNAVAILABLE'
  servedText: string
  servedRow?: GateRow
  needs: string; owner: string
}

/** The exact contract `scripts/lib/portfolio_validation.py` serves as PortfolioGates@v1. A payload that does not name
 *  this schema is refused rather than read optimistically (typed contracts win; unknown beats wrong). */
export const GATES_SCHEMA = 'PortfolioGates@v1'
export interface PortfolioGateWire {
  gate_id: string; title?: string | null; category?: string | null; status?: string | null
  blocks_trading?: boolean | null; due_at?: string | null; owner?: string | null
  label?: string | null; label_text?: string | null
  last_eval?: { result?: string | null; at?: string | null; detail?: string | null } | null
  clock?: { state?: string | null; at?: string | null; age_s?: number | null; threshold_s?: number; text?: string | null } | null
  window?: { end?: string | null; proven_at?: string | null; days_remaining?: number | null; label_text?: string | null } | null
  next_action?: string | null; decl_path?: string | null
}
export interface PortfolioGatesWire {
  schema: string; served_at?: string | null; state: 'OK' | 'STALE' | 'UNKNOWN'; reason?: string | null
  text?: string | null
  scope?: { categories?: string[]; gates?: number | null } | null
  snapshot?: { computed_at?: string | null; age_s?: number | null; threshold_s?: number; basis?: string | null } | null
  writer?: { lane_id?: string | null; last_ok_at?: string | null; receipt?: string | null } | null
  counts?: { rows?: number; failed?: number; overdue?: number; open?: number; closed?: number
    blocks_trading?: number; blocks_trading_unknown?: number; never_evaluated?: number; clock_unreadable?: number } | null
  items?: PortfolioGateWire[] | null
}
/** One served gate, flattened for rendering. Every field is the projection's; nothing is inferred here. */
export interface GateRow {
  gateId: string; title: string; status: string; labelText: string | null
  blocksTrading: boolean | null
  lastEvalResult: string | null; lastEvalAt: string | null; lastEvalDetail: string | null
  clockState: string; clockText: string
  windowEnd: string | null; daysRemaining: number | null
  owner: string | null; nextAction: string | null; declPath: string | null
}
export interface GateStoreModel {
  /** UNAVAILABLE = the read itself failed (absent route, HTTP error, an unexpected contract) — never a verdict.
   *  UNKNOWN = the projection answered and reached no state (its own reason is quoted, never replaced). */
  state: 'OK' | 'STALE' | 'UNKNOWN' | 'UNAVAILABLE'
  chip: 'OK' | 'STALE' | 'UNKNOWN'
  reason: string | null
  headline: string
  scopeLine: string
  snapshotLine: string
  writerLine: string
  rows: GateRow[]
  /** Served facts that must not be read as reassurance, counted and named rather than hidden. */
  caveats: string[]
}

const gateStr = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim() : null)
const gateNum = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

/** PR-004: the served portfolio-scoped gate projection, ready to render — or an honest refusal. A failed read is
 *  `UNAVAILABLE` and says why; a payload under another schema is refused, not read optimistically. */
export function gateStore(read: Read<PortfolioGatesWire>, nowMs: number): GateStoreModel {
  const w = read.state === 'OK' && read.data && (read.data as unknown as { schema?: unknown }).schema === GATES_SCHEMA
    ? read.data : null
  if (w == null) {
    const why = read.state === 'LOADING' ? 'the gate store read has not answered yet'
      : read.state === 'OK' ? `the read answered an unexpected contract (not ${GATES_SCHEMA})`
        : `the gate store read failed (${read.error || read.state})`
    return { state: 'UNAVAILABLE', chip: 'UNKNOWN', reason: read.error, headline: why, rows: [], caveats: [],
      scopeLine: 'scope: not available', snapshotLine: 'not available', writerLine: 'not available' }
  }
  const items = Array.isArray(w.items) ? w.items : []
  const rows: GateRow[] = items.filter(i => i && gateStr(i.gate_id) != null).map(i => ({
    gateId: gateStr(i.gate_id)!, title: gateStr(i.title) || 'untitled gate',
    status: gateStr(i.status) || 'UNRECORDED', labelText: gateStr(i.label_text),
    // tri-state: a NULL stays null so the page can say "does not declare", never "does not block"
    blocksTrading: i.blocks_trading === true ? true : i.blocks_trading === false ? false : null,
    lastEvalResult: gateStr(i.last_eval?.result), lastEvalAt: gateStr(i.last_eval?.at),
    lastEvalDetail: gateStr(i.last_eval?.detail),
    clockState: gateStr(i.clock?.state) || 'unknown', clockText: gateStr(i.clock?.text) || 'no clock published',
    windowEnd: gateStr(i.window?.end), daysRemaining: gateNum(i.window?.days_remaining),
    owner: gateStr(i.owner), nextAction: gateStr(i.next_action), declPath: gateStr(i.decl_path),
  }))
  const c = w.counts
  const n = c?.rows ?? rows.length
  // F2 (REVIEW-S2-portfolio-risk-b5): a counts object that omits open/closed says so. Only a SERVED zero is drawn as
  // zero — an absent count is unavailable, never "0 open · 0 closed".
  const counted = (label: string, v: number | undefined) => v == null ? `${label} not published` : `${v} ${label}`
  const countsLine = c == null ? null
    : `${n} gate${n === 1 ? '' : 's'} in scope · ${counted('open', c.open)} · ${counted('closed', c.closed)}`
      + `${c.failed ? ` · ${c.failed} failed` : ''}${c.overdue ? ` · ${c.overdue} overdue` : ''}`
      + `${c.blocks_trading ? ` · ${c.blocks_trading} declare they block trading` : ''}`
  const state = w.state === 'OK' || w.state === 'STALE' ? w.state : 'UNKNOWN'
  const headline = state === 'UNKNOWN'
    ? `no gate verdict: ${gateStr(w.reason) || 'the projection reached no state'}`
    : countsLine || `the projection published no counts (${rows.length} row${rows.length === 1 ? '' : 's'} read)`
  const snap = w.snapshot
  const snapshotLine = snap == null ? 'no snapshot clock published'
    : `${snap.basis === 'open_gates' ? 'open-gate clock' : snap.basis === 'closed_gates' ? 'closure clock' : 'clock'}`
      + ` · ${gateStr(snap.computed_at) ? fmtET(snap.computed_at, true) : 'no time'}`
      + `${gateNum(snap.age_s) != null ? ` · ${fmtAge(gateNum(snap.age_s)! * 1000)} old` : ''}`
      + `${gateNum(snap.threshold_s) != null ? ` · limit ${fmtAge(gateNum(snap.threshold_s)! * 1000)}` : ''}`
      + `${gateStr(w.text) ? ` · ${w.text}` : ''}`
  const writerLine = w.writer == null ? 'no writer recorded'
    : `writer ${gateStr(w.writer.lane_id) || 'not named'} · last ok ${gateStr(w.writer.last_ok_at) ? fmtET(w.writer.last_ok_at!, true) : 'not published'}`
      + `${gateStr(w.writer.receipt) ? ` · receipt ${w.writer.receipt}` : ''}`
  const caveats: string[] = []
  const blocksUnknown = rows.filter(r => r.blocksTrading == null).length
  if (blocksUnknown) {
    caveats.push(`${blocksUnknown} gate${blocksUnknown === 1 ? '' : 's'} do not declare whether they block trading: that is unknown, not “does not block”`)
  }
  const badClock = rows.filter(r => r.clockState === 'unreadable' || r.clockState === 'future').length
  if (badClock) caveats.push(`${badClock} gate evaluation time${badClock === 1 ? ' is' : 's are'} not a readable, non-future time`)
  if (state === 'UNKNOWN' && rows.length) caveats.push('rows are shown with their own clocks, but no verdict is drawn from them')
  if (state === 'STALE') caveats.push(`the projection is STALE: ${gateStr(w.reason) || 'no reason published'}`)
  // The clock is served twice (a timestamp and its age). If they disagree, say so instead of trusting one silently.
  const at = gateStr(snap?.computed_at), ageS = gateNum(snap?.age_s)
  if (snap && at && ageS != null && nowMs > 0) {
    const implied = Date.parse(at) + ageS * 1000
    if (Number.isFinite(implied) && Math.abs(nowMs - implied) > 120_000) {
      caveats.push('the snapshot time and its own age disagree by more than two minutes')
    }
  }
  return { state, chip: state, reason: gateStr(w.reason), headline, scopeLine: `scope: ${(w.scope?.categories || []).join(', ') || 'not named in the read'}`,
    snapshotLine, writerLine, rows, caveats }
}

/** The exact contract `scripts/lib/portfolio_validation.py` serves as PortfolioChanges@v1. Refused under another
 *  schema, never read optimistically. */
export const CHANGES_SCHEMA = 'PortfolioChanges@v1'
export interface PortfolioChangeWire {
  event_id?: number | null; source_kind?: string | null; source_id?: string | null
  category?: string | null; transition?: string | null; label?: string | null; label_text?: string | null
  occurred_at?: string | null; detected_at?: string | null; summary?: string | null; owner?: string | null
}
export interface PortfolioChangesWire {
  schema: string; served_at?: string | null; state: 'OK' | 'UNKNOWN'; reason?: string | null
  window?: { basis?: string | null; since?: string | null; until?: string | null } | null
  count?: number | null; latest_at?: string | null; may_be_truncated?: boolean | null
  outside_window?: { before?: number; after?: number; unreadable?: number; out_of_scope?: number } | null
  items?: PortfolioChangeWire[] | null
}
/** One served change, flattened. Each row keeps its OWN event time; nothing is re-stamped with the page clock. */
export interface ChangeRow {
  key: string; sourceId: string; category: string | null; transition: string; labelText: string | null
  occurredAt: string | null; detectedAt: string | null; summary: string | null; owner: string | null
}
export interface ChangesModel {
  /** EMPTY = the store was read and measured zero changes in the window (not "not declared").
   *  UNAVAILABLE = the read itself failed — never an empty list. */
  state: 'OK' | 'EMPTY' | 'UNKNOWN' | 'UNAVAILABLE'
  chip: 'OK' | 'UNKNOWN'
  reason: string | null
  headline: string
  windowLine: string
  rows: ChangeRow[]
  caveats: string[]
}

/** PR-005: the served change list, ready to render — or an honest refusal. */
export function changesModel(read: Read<PortfolioChangesWire>, sinceVisit?: SinceVisitModel | null): ChangesModel {
  const w = read.state === 'OK' && read.data && (read.data as unknown as { schema?: unknown }).schema === CHANGES_SCHEMA
    ? read.data : null
  if (w == null) {
    const why = read.state === 'LOADING' ? 'the change list read has not answered yet'
      : read.state === 'OK' ? `the read answered an unexpected contract (not ${CHANGES_SCHEMA})`
        : `the change list read failed (${read.error || read.state})`
    return { state: 'UNAVAILABLE', chip: 'UNKNOWN', reason: read.error, headline: why, windowLine: 'window: not available',
      rows: [], caveats: [] }
  }
  const win = w.window
  const basis = gateStr(win?.basis) || 'unknown'
  const since = gateStr(win?.since), until = gateStr(win?.until)
  // F1 (REVIEW-S2-portfolio-risk-b5): the 24 h fallback must say WHY it has no cursor. A FAILED (or unreadable)
  // last-visit read is not a book with no recorded visit; only a successful NOT_RECORDED read may say that.
  const cursorWhy = sinceVisit == null ? null
    : sinceVisit.status === 'UNKNOWN' ? `the last-visit read gave no usable cursor: ${sinceVisit.reason || 'no reason published'}`
      : sinceVisit.status === 'NOT_RECORDED' ? null
        : `the last-visit record gives no cursor to window from (status ${sinceVisit.status})`
  const windowLine = `${basis === 'last_visit' ? 'since your last visit' : basis === 'fallback_24h'
    ? (cursorWhy ? `the last 24 h (${cursorWhy}; the window is a fallback, not a recorded cursor)`
      : 'the last 24 h (no visit cursor was recorded)') : `window basis: ${basis}`}`
    + `${since ? ` · from ${fmtET(since, true)}` : ''}${until ? ` → ${fmtET(until, true)} ET` : ''}`
  const items = Array.isArray(w.items) ? w.items : []
  const rows: ChangeRow[] = items.filter(i => i && (gateStr(i.source_id) != null || i.event_id != null)).map((i, n) => ({
    key: String(i.event_id ?? `${gateStr(i.source_id) || 'event'}-${n}`),
    sourceId: gateStr(i.source_id) || 'unnamed gate', category: gateStr(i.category),
    transition: gateStr(i.transition) || 'unrecorded transition', labelText: gateStr(i.label_text) || gateStr(i.label),
    occurredAt: gateStr(i.occurred_at), detectedAt: gateStr(i.detected_at),
    summary: gateStr(i.summary), owner: gateStr(i.owner),
  }))
  const count = gateNum(w.count) ?? rows.length
  const state: ChangesModel['state'] = w.state === 'OK' ? (count === 0 ? 'EMPTY' : 'OK') : 'UNKNOWN'
  const headline = state === 'UNKNOWN'
    ? `no change list: ${gateStr(w.reason) || 'the projection reached no state'}`
    : count === 0 ? 'no changes in this window (a measured zero, not an absent store)'
      : `${count} change${count === 1 ? '' : 's'} since ${basis === 'last_visit' ? 'your last visit' : 'the window opened'}`
        + `${gateStr(w.latest_at) ? ` · newest ${fmtET(w.latest_at, true)} ET` : ''}`
  const caveats: string[] = []
  const out = w.outside_window
  if (out && (out.out_of_scope || 0) > 0) {
    caveats.push(`${out.out_of_scope} event${out.out_of_scope === 1 ? '' : 's'} on this store belong to another page's scope and are not shown`)
  }
  const excluded = (out?.before || 0) + (out?.after || 0) + (out?.unreadable || 0)
  if (excluded > 0) {
    caveats.push(`${excluded} row${excluded === 1 ? '' : 's'} fell outside the window (or carried no readable time) and are counted, not published`)
  }
  if (w.may_be_truncated) caveats.push(`the window may hold more than the ${rows.length} shown; the newest are listed first`)
  if (rows.some(r => r.occurredAt == null)) caveats.push('a row without a readable event time is listed without one; the page will not invent a time')
  return { state, chip: state === 'UNKNOWN' ? 'UNKNOWN' : 'OK', reason: gateStr(w.reason), headline, windowLine, rows, caveats }
}

/** What the served store says about one expectation, in words, with no verdict of the page's own. */
function servedLine(expectsGateId: string, store: GateStoreModel | null): {
  served: GateEvidence['served']; servedText: string; servedRow?: GateRow
} {
  if (store == null || store.state === 'UNAVAILABLE') {
    return { served: 'UNAVAILABLE', servedText: `the gate store could not be read${store?.reason ? ` (${store.reason})` : ''}; no gate verdict is shown` }
  }
  const row = store.rows.find(r => r.gateId === expectsGateId)
  if (!row) {
    return { served: 'NOT_GATED_BY_STORE', servedText: `the store was read and declares no gate with id ${expectsGateId}; this expectation is ungated, which is not a pass` }
  }
  return {
    served: 'GATED', servedRow: row,
    servedText: `${row.status}${row.lastEvalResult ? ` · last result ${row.lastEvalResult}` : ''}`
      + `${row.lastEvalAt ? ` at ${fmtET(row.lastEvalAt, true)}` : ' · never evaluated'}`
      + ` · ${row.clockText}`
      + `${row.windowEnd ? ` · window to ${fmtET(row.windowEnd, true)}` : ''}`
      + `${row.owner ? ` · owner ${row.owner}` : ''}${row.nextAction ? ` · next: ${row.nextAction}` : ''}`,
  }
}

export function gateEvidence(prot: ProtectionModel, measures: MeasuresModel, positions: PositionModel[],
  holdings: HoldingsWire | null = null, store: GateStoreModel | null = null): GateEvidence[] {
  const cov = coverageCounts(positions)
  const accounts = new Set(positions.filter(p => !p.isCash).map(p => p.broker))
  // A7 (REVIEW-CAMPAIGN8H-item1-fix): a broker whose rows are all EXEMPT carries no counted position, so it must not
  // read as covered by the stop read this page observed. Counted brokers are named against the non-cash set.
  const countedBrokers = new Set(positions.filter(p => p.counted).map(p => p.broker))
  const priced = positions.filter(p => !p.isCash)
  const stale = priced.filter(p => p.priceStale === true).length
  // The holdings document does carry the position-count block; a gate must not claim it cannot see what the read
  // published (UI may not contradict reality). C5: compare LIKE WITH LIKE — the block's holdings.all_rows scope
  // against the rows this read drew — quote its own summary, name the headline as a named scope, and never read the
  // cross-scope `agree` flag as a comparison (it is false on every real book by construction).
  const pc = holdings?.position_counts
  const scopeCount = (k: string): number | null => {
    const s = pc?.scopes
    return s && typeof s[k] === 'number' ? s[k] : null
  }
  const allRows = num(pc?.all_rows) ?? scopeCount('holdings.all_rows')
  const headline = num(pc?.position_count)
  const headlineScope = typeof pc?.primary_scope === 'string' && pc.primary_scope ? pc.primary_scope : 'holdings.non_cash_over_100'
  const blockSummary = typeof pc?.summary === 'string' && pc.summary.trim() ? pc.summary.trim() : null
  const countEvidence = pc == null
    ? 'the position count block is not in this read'
    : allRows == null
      ? `the count block names no all-rows scope; this read parsed ${positions.length} rows and nothing here compares them`
      : [
        // PR-002: the comparison is normalised rows, not the rendered list ("rendered" is reserved for displayed items).
        `the block's holdings.all_rows scope counts ${allRows}; this read parsed ${positions.length} normalised row${positions.length === 1 ? '' : 's'}; ${allRows === positions.length ? 'they match' : 'they differ'}`,
        headline != null ? `the block's headline ${headline} is its ${headlineScope} scope` : null,
        blockSummary ? `its own summary: ${blockSummary}` : null,
      ].filter(Boolean).join(' · ')
  const rows = [
    { gate: 'Stop read covers every broker', blocks: 'Protection: OK', blocksTrading: true, threshold: 'every broker read inside 900 s (session) / 72 h (closed)', owner: 'stops lane',
      expectsGateId: 'VG-PORT-STOP-READ-PER-BROKER',
      pageEvidence: prot.counted == null ? 'no counted book was read' : `${prot.counted} counted position${prot.counted === 1 ? '' : 's'} in ${countedBrokers.size} of ${accounts.size} broker${accounts.size === 1 ? '' : 's'} with non-cash rows; ${prot.protectedN ?? '—'} protected, ${cov.partial} partial`,
      needs: 'a served protection rollup with a per-broker read state (G2/G3)' },
    { gate: 'Price check · 5 sessions clean', blocks: 'VALIDATED on Price Mismatch', blocksTrading: false, threshold: '5 sessions, not one read', owner: 'repricer lane',
      expectsGateId: 'VG-PORT-PRICE-5-SESSIONS',
      pageEvidence: `${stale} stale of ${priced.length} priced rows in this read; one read cannot show a five-session window`,
      needs: 'a served check result with a five-session window (gate store, LQ-2141)' },
    { gate: 'Position count agrees', blocks: 'VALIDATED on Count Mismatch', blocksTrading: false, threshold: "the rows drawn this read = the count block's holdings.all_rows scope; no published tolerance", owner: 'position sync lane',
      expectsGateId: 'VG-PORT-COUNT-AGREES',
      pageEvidence: countEvidence,
      needs: 'the gate store row for count agreement (the page can see the block, not the gate)' },
    { gate: 'Value reconciles to the accounting anchor', blocks: 'VALIDATED on Value Mismatch', blocksTrading: false, threshold: 'a stored signed reconciliation', owner: 'portfolio lane',
      expectsGateId: 'VG-PORT-VALUE-RECONCILES',
      pageEvidence: measures.state === 'PRESENT'
        ? `account value ${measures.measures.find(m => m.key === 'account_value')?.status ?? 'UNKNOWN'}; day figures ${measures.dayUnverified ? 'UNVERIFIED' : 'verified'}`
        : 'no measures block in this holdings document',
      needs: 'a stored signed reconciliation (measure 4) plus the gate store row' },
  ]
  // PR-004: each expectation now carries the served store's answer. A row is never labelled NOT AVAILABLE again: either
  // the store was read (and says gated / not declared) or the read failed (and no verdict is drawn).
  return rows.map(r => ({ ...r, ...servedLine(r.expectsGateId, store) }))
}

// ── risk score: an isolated pending decision (G7) ────────────────────────────────────────────────────
/** RISK-SCORE-SPEC-20261111 is STATUS: PROPOSED, awaiting operator sign-off; nothing is implemented. This page
 *  therefore draws no score, no letter and no colour for risk, and says why in one place. */
export const RISK_SCORE = {
  status: 'PENDING DECISION' as const,
  spec: 'RISK-SCORE-SPEC-20261111 (design/pages/portfolio/v002)',
  text: 'The risk score is proposed, not approved: no definition has been signed off and no backend computes one. '
    + 'The page draws no number and no band for a composite score. The Risk column is a separate, measured '
    + 'per-position fact — the hypothetical downside to the verified resting stop — never a score.',
}

